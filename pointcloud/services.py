import os
from uuid import UUID

import boto3
import psycopg
from botocore.config import Config
from psycopg.rows import dict_row

BUCKET = "pointcloud-scans"
QUEUE = "pointcloud-jobs"
DEAD_LETTER_QUEUE = "pointcloud-failed-jobs"
MAX_BYTES = 16 * 1024 * 1024
MAX_POINTS = 250_000
EPSG = 26918


def database():
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=5)


def storage(*, public: bool = False):
    endpoint = os.environ["UPLOAD_URL_BASE" if public else "MOTO_URL"]
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def queue():
    return boto3.client("sqs", endpoint_url=os.environ["MOTO_URL"])


def object_key(scan_id: UUID) -> str:
    return f"scans/{scan_id}"
