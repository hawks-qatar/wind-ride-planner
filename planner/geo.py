"""Geometry and wind-vector helpers.

Conventions
-----------
* Bearings are degrees clockwise from true north (0 = N, 90 = E).
* Wind direction follows the meteorological convention used by Open-Meteo:
  it is the direction the wind blows FROM (a 0 deg wind comes from the north).
"""
from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, in [0, 360)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(x, y)) % 360


def wind_components(heading_deg: float, wind_from_deg: float, wind_speed: float) -> tuple[float, float]:
    """Split wind into (headwind, crosswind) relative to the rider's heading.

    headwind  > 0: wind in the rider's face; < 0: tailwind.
    crosswind > 0: wind pushing from the rider's right; < 0: from the left.
    """
    rel = math.radians(wind_from_deg - heading_deg)
    head = wind_speed * math.cos(rel)
    cross = wind_speed * math.sin(rel)
    # Tidy floating-point noise so exact cases read cleanly (e.g. 0.0 not 1e-15).
    return round(head, 9) + 0.0, round(cross, 9) + 0.0


def wind_to_uv(speed: float, from_deg: float) -> tuple[float, float]:
    """Wind speed/direction to (u east, v north) vector of where the air moves TO."""
    rad = math.radians(from_deg)
    return -speed * math.sin(rad), -speed * math.cos(rad)


def uv_to_wind(u: float, v: float) -> tuple[float, float]:
    """Inverse of wind_to_uv: returns (speed, from_deg)."""
    speed = math.hypot(u, v)
    if speed == 0:
        return 0.0, 0.0
    return speed, math.degrees(math.atan2(-u, -v)) % 360


def compass_point(deg: float) -> str:
    """16-point compass name for a bearing, e.g. 315 -> 'NW'."""
    names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return names[int((deg % 360) / 22.5 + 0.5) % 16]
