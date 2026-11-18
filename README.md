# Asula LiDAR Processor

A local interview project for asynchronous LiDAR processing. Upload a generated LAZ file, turn it into a background job, extract one pole candidate, and find it with a PostGIS distance query. It uses no cloud account and is not intended for public deployment.

## Run on Windows

1. Extract the ZIP and open PowerShell in the `asula-lidar-processor` folder. Start Docker Desktop in Linux container mode. Verify Python 3.13 and Compose:

   ```powershell
   py -3.13 --version
   docker compose version
   ```

2. Start the stack and wait for the API:

   ```powershell
   docker compose up --build --wait --wait-timeout 120
   ```

   The one-time `init` service applies the Alembic migration and creates the Moto bucket and queues. `Exited (0)` for `init` is expected. Open [Swagger UI](http://127.0.0.1:8000/docs) to see the endpoints. Docker pulls/builds images on the first run; the database uses an `amd64` image, which requires emulation on Windows ARM64.

3. Generate and process a scan. These commands use the virtual environment directly, so no PowerShell activation or execution-policy change is needed:

   ```powershell
   py -3.13 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
   .\.venv\Scripts\python.exe scripts\demo.py
   ```

   Expect `"status": "done"`, `"point_count": 120`, and one `"kind": "pole_candidate"` roughly 4 meters tall. The script also verifies the candidate can be found with the spatial endpoint.

4. Run checks, inspect logs, or stop:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest -q
   .\.venv\Scripts\python.exe -m ruff check .
   docker compose logs --tail 50 init api worker
   docker compose down
   ```

   `docker compose down` preserves the database volume, but Moto data is in memory and is lost when its container stops. Use `docker compose down --volumes` **only** when you want to delete local scan records and start fresh. If Windows reports a port conflict, check for other programs using ports `8000` and `5000`.

## Follow the request through the code

```text
Client -- POST /scans --> FastAPI -- scan record --> PostgreSQL
Client -- PUT presigned URL --> Moto S3
Client -- POST /scans/{id}/process --> FastAPI -- job --> Moto SQS
Moto SQS --> Worker -- read pinned version --> Moto S3
Worker -- commit feature and status --> PostgreSQL/PostGIS
Client -- GET status, scan features, or features near a point --> FastAPI
```

1. [API](pointcloud/api.py): creates the scan record and a short-lived URL so file bytes bypass the API. It checks that an upload exists before returning `202 Accepted` for processing. `GET /scans/{id}` tracks progress.
2. [Worker](pointcloud/worker.py): takes a row lock and ignores stale or duplicate deliveries. It commits the result before deleting the message. An invalid input is marked `failed`; temporary dependency errors leave the message unacknowledged so it can retry.
3. [Extractor](pointcloud/extract.py): treats the **entire scan** as one cluster. A cluster with at least 10 points, at least 2 m of height, and no more than 0.8 m of span along either horizontal axis is a candidate. It is not a detector for full street scenes.
4. [Migration](migrations/versions/0001_scans_and_features.py): creates a `PointZ` geometry and a GiST index. `/features/near?x=500000&y=4500000&radius_m=2` uses `ST_DWithin` for a **2D** radius query. Input and output x/y are NAD83 / UTM zone 18N (EPSG:26918) meters, not longitude and latitude. The result is capped at 100 and not ranked by distance.
5. [CI workflow](.github/workflows/ci.yml): runs lint, unit tests, and an end-to-end Compose smoke test when you push or open a pull request. It does not deploy to AWS.

## What to say in the interview

- **Why object storage and a queue?** Don’t route large uploads through the API or wait for processing inside a request. Scale the API and worker independently, and acknowledge a job only after its result is durable.
- **What happens if processing runs twice?** The worker checks the scan state and the S3 object version under a row lock. Feature insertion and the `done` state commit together, so redelivery after commit does not insert a second feature.
- **What would change for production?** This demo is unauthenticated, binds its public ports to loopback, and uses dummy credentials. Add authentication, scan ownership, IAM roles, and enforce upload limits at admission rather than only when processing is requested. Use a transactional outbox to coordinate database state and queue publication, reconcile dead-letter jobs (which can currently still show `queued`), and replace the long-held worker lock with a short claim/lease before processing large scans. Tile or stream large files and use a measured multi-object extractor.
- **How would you prove the index helps?** Compare `EXPLAIN (ANALYZE, BUFFERS)` on a larger fixture with and without the spatial index. A one-row demo may correctly choose a sequential scan; don’t claim a speedup you haven’t measured.

The demo expects LAS/LAZ with EPSG:26918 in the header, a file no larger than 16 MiB, and no more than 250,000 points. Start with the generated file rather than downloading a real scan.
