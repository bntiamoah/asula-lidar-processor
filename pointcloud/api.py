import json
from typing import Annotated, Literal
from uuid import UUID, uuid4

from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, FiniteFloat, field_validator

from pointcloud.services import BUCKET, EPSG, MAX_BYTES, QUEUE, database, object_key, queue, storage

app = FastAPI(title="Point Cloud API", version="0.1.0")


class ScanInput(BaseModel):
    filename: str = Field(min_length=5, max_length=255)

    @field_validator("filename")
    @classmethod
    def lidar_extension(cls, value: str) -> str:
        if not value.lower().endswith((".las", ".laz")):
            raise ValueError("filename must end in .las or .laz")
        return value


class CreatedScan(BaseModel):
    id: UUID
    upload_url: str


class ScanState(BaseModel):
    id: UUID
    status: Literal["awaiting_upload", "queued", "done", "failed"]
    point_count: int | None
    error: str | None


class Feature(BaseModel):
    scan_id: UUID
    kind: str
    x: float
    y: float
    z: float
    height_m: float


class FeatureResults(BaseModel):
    epsg: int = EPSG
    features: list[Feature]


FEATURE_COLUMNS = (
    "scan_id, kind, ST_X(location) AS x, ST_Y(location) AS y, ST_Z(location) AS z, height_m"
)


@app.get("/health")
def health() -> dict[str, str]:
    with database() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.post("/scans", status_code=201)
def create_scan(body: ScanInput) -> CreatedScan:
    scan_id = uuid4()
    upload_url = storage(public=True).generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": object_key(scan_id)},
        ExpiresIn=300,
    )
    with database() as conn:
        conn.execute("INSERT INTO scans (id, filename) VALUES (%s, %s)", (scan_id, body.filename))
    return CreatedScan(id=scan_id, upload_url=upload_url)


@app.get("/scans/{scan_id}")
def get_scan(scan_id: UUID) -> ScanState:
    with database() as conn:
        row = conn.execute(
            "SELECT id, status, point_count, error FROM scans WHERE id = %s", (scan_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Scan not found")
    return ScanState.model_validate(row)


@app.post("/scans/{scan_id}/process", status_code=202)
def process_scan(scan_id: UUID) -> ScanState:
    with database() as conn:
        row = conn.execute(
            "SELECT id, status, point_count, error FROM scans WHERE id = %s FOR UPDATE",
            (scan_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Scan not found")
        if row["status"] == "awaiting_upload":
            try:
                obj = storage().head_object(Bucket=BUCKET, Key=object_key(scan_id))
            except ClientError as exc:
                if exc.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
                    raise HTTPException(409, "Upload the file before processing") from exc
                raise
            if not 0 < obj["ContentLength"] <= MAX_BYTES:
                raise HTTPException(422, "File must be nonempty and at most 16 MiB")
            version = obj.get("VersionId")
            if not version or version == "null":
                raise HTTPException(503, "Object storage versioning is not ready")
            conn.execute(
                "UPDATE scans SET status = 'queued', object_version = %s WHERE id = %s",
                (version, scan_id),
            )
            sqs = queue()
            sqs.send_message(
                QueueUrl=sqs.get_queue_url(QueueName=QUEUE)["QueueUrl"],
                MessageBody=json.dumps({"scan_id": str(scan_id), "version": version}),
            )
            row["status"] = "queued"
    return ScanState.model_validate(row)


@app.get("/scans/{scan_id}/features")
def scan_features(scan_id: UUID) -> FeatureResults:
    get_scan(scan_id)
    with database() as conn:
        rows = conn.execute(
            f"SELECT {FEATURE_COLUMNS} FROM features WHERE scan_id = %s", (scan_id,)
        ).fetchall()
    return FeatureResults(features=[Feature.model_validate(row) for row in rows])


@app.get("/features/near")
def nearby_features(
    x: FiniteFloat,
    y: FiniteFloat,
    radius_m: Annotated[FiniteFloat, Query(gt=0, le=10_000)] = 50,
) -> FeatureResults:
    with database() as conn:
        rows = conn.execute(
            f"""SELECT {FEATURE_COLUMNS} FROM features
            WHERE ST_DWithin(location, ST_SetSRID(ST_MakePoint(%s, %s), {EPSG}), %s)
            ORDER BY scan_id LIMIT 100""",
            (x, y, radius_m),
        ).fetchall()
    return FeatureResults(features=[Feature.model_validate(row) for row in rows])
