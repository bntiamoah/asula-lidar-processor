import logging
import time
from contextlib import closing
from io import BytesIO
from uuid import UUID

import psycopg
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ValidationError

from pointcloud.extract import InvalidScan, extract
from pointcloud.services import BUCKET, EPSG, MAX_BYTES, QUEUE, database, object_key, queue, storage

log = logging.getLogger(__name__)


class Job(BaseModel):
    scan_id: UUID
    version: str


def process(job: Job) -> None:
    scan_id = job.scan_id
    with database() as conn:
        row = conn.execute(
            "SELECT status, object_version FROM scans WHERE id = %s FOR UPDATE",
            (scan_id,),
        ).fetchone()
        if row is None or row["status"] != "queued" or row["object_version"] != job.version:
            log.info("Skipping stale or duplicate job scan_id=%s", scan_id)
            return

        try:
            obj = storage().get_object(
                Bucket=BUCKET, Key=object_key(scan_id), VersionId=job.version
            )
            with closing(obj["Body"]) as body:
                if not 0 < obj["ContentLength"] <= MAX_BYTES:
                    raise InvalidScan("File must be nonempty and at most 16 MiB")
                count, pole = extract(BytesIO(body.read()))
        except InvalidScan as exc:
            conn.execute(
                "UPDATE scans SET status = 'failed', error = %s WHERE id = %s",
                (str(exc), scan_id),
            )
            log.warning("Rejected scan scan_id=%s reason=%s", scan_id, exc)
            return

        if pole is not None:
            conn.execute(
                """INSERT INTO features (scan_id, kind, location, height_m)
                VALUES (%s, 'pole_candidate', ST_SetSRID(ST_MakePoint(%s, %s, %s), %s), %s)""",
                (scan_id, pole.x, pole.y, pole.z, EPSG, pole.height_m),
            )
        conn.execute(
            "UPDATE scans SET status = 'done', point_count = %s WHERE id = %s",
            (count, scan_id),
        )
    log.info("Finished scan_id=%s points=%s detected=%s", scan_id, count, pole is not None)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sqs = queue()
    url = sqs.get_queue_url(QueueName=QUEUE)["QueueUrl"]
    log.info("Polling queue %s", QUEUE)
    while True:
        try:
            result = sqs.receive_message(QueueUrl=url, WaitTimeSeconds=10, MaxNumberOfMessages=1)
            for message in result.get("Messages", []):
                job = Job.model_validate_json(message["Body"])
                process(job)
                sqs.delete_message(QueueUrl=url, ReceiptHandle=message["ReceiptHandle"])
        except (BotoCoreError, ClientError, psycopg.Error, ValidationError) as exc:
            log.exception("Worker operation failed; any unacknowledged message can retry: %s", exc)
            time.sleep(2)


if __name__ == "__main__":
    main()
