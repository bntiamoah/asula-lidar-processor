import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import laspy
import numpy as np
from pyproj import CRS

from pointcloud.services import EPSG

BASE_URL = "http://127.0.0.1:8000"


def make_scan(path: Path) -> None:
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.offsets = np.array([500_000.0, 4_500_000.0, 0.0])
    header.add_crs(CRS.from_epsg(EPSG))
    points = laspy.LasData(header)
    angle = np.linspace(0, 4 * np.pi, 120)
    points.x = 500_000 + 0.12 * np.cos(angle)
    points.y = 4_500_000 + 0.12 * np.sin(angle)
    points.z = np.linspace(10, 14, len(angle))
    points.write(path)


def main() -> None:
    with TemporaryDirectory() as workdir, httpx.Client(base_url=BASE_URL, timeout=10) as client:
        path = Path(workdir) / "synthetic-pole.laz"
        make_scan(path)

        created = client.post("/scans", json={"filename": path.name}).raise_for_status().json()
        route = f"/scans/{created['id']}"
        if client.post(f"{route}/process").status_code != 409:
            raise RuntimeError("Processing before upload should return HTTP 409")
        httpx.put(created["upload_url"], content=path.read_bytes(), timeout=10).raise_for_status()
        client.post(f"{route}/process").raise_for_status()

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            scan = client.get(route).raise_for_status().json()
            if scan["status"] == "failed":
                raise RuntimeError(f"Worker rejected the scan: {scan['error']}")
            if scan["status"] == "done":
                break
            time.sleep(0.5)
        else:
            raise TimeoutError("Scan did not complete; inspect worker logs")

        repeated = client.post(f"{route}/process").raise_for_status().json()
        if repeated["status"] != "done":
            raise RuntimeError("Repeating the process request changed the completed scan")
        features = client.get(f"{route}/features").raise_for_status().json()
        nearby = client.get(
            "/features/near", params={"x": 500_000, "y": 4_500_000, "radius_m": 2}
        ).raise_for_status().json()
        if scan["point_count"] != 120 or len(features["features"]) != 1:
            raise RuntimeError(f"Expected 120 points and one pole candidate: {scan}, {features}")
        candidate = features["features"][0]
        if candidate["kind"] != "pole_candidate" or abs(candidate["height_m"] - 4.0) > 0.02:
            raise RuntimeError(f"Unexpected feature: {candidate}")
        if not any(item["scan_id"] == created["id"] for item in nearby["features"]):
            raise RuntimeError("Spatial query did not find the uploaded scan's candidate")

        print(json.dumps({"scan": scan, "features": features}, indent=2))


if __name__ == "__main__":
    main()
