from dataclasses import dataclass
from typing import BinaryIO

import laspy
import numpy as np
from pyproj.exceptions import CRSError

from pointcloud.services import EPSG, MAX_POINTS


class InvalidScan(ValueError):
    pass


@dataclass(frozen=True)
class PoleCandidate:
    x: float
    y: float
    z: float
    height_m: float


def extract(stream: BinaryIO) -> tuple[int, PoleCandidate | None]:
    try:
        with laspy.open(stream) as reader:
            count = reader.header.point_count
            if not 0 < count <= MAX_POINTS:
                raise InvalidScan(f"Point count must be between 1 and {MAX_POINTS:,}")
            crs = reader.header.parse_crs()
            if crs is None or crs.to_epsg() != EPSG:
                raise InvalidScan(f"File must declare EPSG:{EPSG}")
            points = reader.read()
    except (laspy.errors.LaspyException, EOFError, CRSError) as exc:
        raise InvalidScan("Unable to read LAS/LAZ data") from exc

    x, y, z = (np.asarray(axis) for axis in (points.x, points.y, points.z))
    if len(x) != count:
        raise InvalidScan("Point count does not match the file header")
    if not all(np.isfinite(axis).all() for axis in (x, y, z)):
        raise InvalidScan("Coordinates must be finite")
    height = float(np.ptp(z))
    if count < 10 or height < 2.0 or max(np.ptp(x), np.ptp(y)) > 0.8:
        return count, None
    return count, PoleCandidate(float(np.median(x)), float(np.median(y)), float(z.min()), height)
