"""Open-Meteo forecast fetching and time interpolation.

Weather is fetched on a coarse grid (config weather.grid_deg, ~11 km at 0.1 deg):
every route leg is matched to the grid cell containing its midpoint, and all
cells are requested in ONE multi-location Open-Meteo call.
"""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from .geo import uv_to_wind, wind_to_uv

HOURLY_VARS = ["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "temperature_2m", "visibility"]


def grid_key(lat: float, lon: float, grid: float) -> str:
    """Snap a coordinate to the weather grid and return a stable 'lat,lon' key."""
    glat = round(round(lat / grid) * grid, 4)
    glon = round(round(lon / grid) * grid, 4)
    return f"{glat:.4f},{glon:.4f}"


def collect_points(legs_by_route: dict[str, list[dict]], grid: float) -> list[str]:
    keys = {grid_key(leg["mid_lat"], leg["mid_lon"], grid)
            for legs in legs_by_route.values() for leg in legs}
    return sorted(keys)


def build_request_url(points: list[str], start: date, end: date, cfg: dict) -> str:
    lats = ",".join(p.split(",")[0] for p in points)
    lons = ",".join(p.split(",")[1] for p in points)
    params = {
        "latitude": lats,
        "longitude": lons,
        "hourly": ",".join(HOURLY_VARS),
        "wind_speed_unit": "kmh",
        "timezone": cfg["timezone"],
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }
    return cfg["weather"]["api_url"] + "?" + urllib.parse.urlencode(params, safe=",")


def parse_response(points: list[str], payload) -> dict[str, dict]:
    """Normalise Open-Meteo's response (a list for multi-location) to {grid_key: hourly}."""
    items = payload if isinstance(payload, list) else [payload]
    if len(items) != len(points):
        raise ValueError(f"expected {len(points)} locations from Open-Meteo, got {len(items)}")
    out = {}
    for key, item in zip(points, items):
        h = item["hourly"]
        out[key] = {
            "time": h["time"],
            "wind": h["wind_speed_10m"],
            "dir": h["wind_direction_10m"],
            "gust": h["wind_gusts_10m"],
            "temp": h["temperature_2m"],
            "vis": h.get("visibility") or [None] * len(h["time"]),
        }
    return out


def fetch_forecast(points: list[str], start: date, end: date, cfg: dict, timeout: int = 30) -> dict:
    url = build_request_url(points, start, end, cfg)
    req = urllib.request.Request(url, headers={"User-Agent": "wind-ride-planner (motorcycle club tool)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    return parse_response(points, payload)


def _lerp(a, b, f):
    if a is None:
        return b
    if b is None:
        return a
    return a + (b - a) * f


def sample(series: dict, when: datetime) -> dict | None:
    """Interpolate one grid cell's hourly series at a local (naive) datetime.

    Wind is interpolated as a vector so 350 deg -> 10 deg passes through north,
    not south. Returns None when the time is outside the forecast.
    """
    base = when.replace(minute=0, second=0, microsecond=0)
    frac = (when - base).total_seconds() / 3600
    index = series.setdefault("_index", {t: i for i, t in enumerate(series["time"])})
    i0 = index.get(base.strftime("%Y-%m-%dT%H:%M"))
    if i0 is None:
        return None
    i1 = i0 + 1 if frac > 0 and i0 + 1 < len(series["time"]) else i0

    def val(name, i):
        return series[name][i]

    if val("wind", i0) is None or val("dir", i0) is None:
        return None
    u0, v0 = wind_to_uv(val("wind", i0), val("dir", i0))
    w1, d1 = val("wind", i1), val("dir", i1)
    u1, v1 = wind_to_uv(w1, d1) if w1 is not None and d1 is not None else (u0, v0)
    speed, direction = uv_to_wind(_lerp(u0, u1, frac), _lerp(v0, v1, frac))
    return {
        "wind": speed,
        "dir": direction,
        "gust": _lerp(val("gust", i0), val("gust", i1), frac),
        "temp": _lerp(val("temp", i0), val("temp", i1), frac),
        "vis": _lerp(val("vis", i0), val("vis", i1), frac),
    }


def window_hours(day: date, window: list[str]) -> list[datetime]:
    """Whole hours covering the ride window, e.g. 05:30-09:30 -> 05:00 ... 10:00."""
    start = parse_time(day, window[0])
    end = parse_time(day, window[1])
    h = start.replace(minute=0)
    hours = []
    while h <= end + timedelta(minutes=59):
        hours.append(h)
        h += timedelta(hours=1)
    return hours


def parse_time(day: date, hhmm: str) -> datetime:
    hh, mm = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, hh, mm)


def circular_mean_deg(dirs: list[float], weights: list[float] | None = None) -> float:
    weights = weights or [1.0] * len(dirs)
    x = sum(w * math.sin(math.radians(d)) for d, w in zip(dirs, weights))
    y = sum(w * math.cos(math.radians(d)) for d, w in zip(dirs, weights))
    return math.degrees(math.atan2(x, y)) % 360
