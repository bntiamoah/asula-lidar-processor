from io import BytesIO

import laspy
import numpy as np
import pytest
from pyproj import CRS

from pointcloud.extract import InvalidScan, extract
from pointcloud.services import EPSG


def scan(*, width: float = 0.2, epsg: int = EPSG) -> BytesIO:
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.add_crs(CRS.from_epsg(epsg))
    points = laspy.LasData(header)
    points.x = np.linspace(500_000, 500_000 + width, 20)
    points.y = np.full(20, 4_500_000)
    points.z = np.linspace(10, 14, 20)
    buffer = BytesIO()
    points.write(buffer, do_compress=False)
    buffer.seek(0)
    return buffer


def test_extracts_tall_narrow_cluster():
    count, pole = extract(scan())
    assert count == 20
    assert pole is not None
    assert pole.height_m == pytest.approx(4.0)
    assert pole.z == pytest.approx(10.0)


def test_wide_cluster_is_valid_but_not_a_pole():
    assert extract(scan(width=3)) == (20, None)


def test_rejects_unexpected_coordinate_system():
    with pytest.raises(InvalidScan, match="EPSG:26918"):
        extract(scan(epsg=26917))


def test_rejects_non_lidar_content():
    with pytest.raises(InvalidScan, match="Unable to read"):
        extract(BytesIO(b"not a LAS file"))
