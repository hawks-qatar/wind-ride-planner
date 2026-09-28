"""Load, validate and pre-process the route library (routes.json)."""
from __future__ import annotations

import json
from pathlib import Path

from .geo import bearing_deg, haversine_km

EXPOSURES = ("urban", "highway", "open_desert", "coastal", "causeway")
RIDE_TYPES = ("short", "long")
# Generous box around Qatar; catches swapped lat/lon and typos.
QATAR_BBOX = {"lat": (24.4, 26.3), "lon": (50.6, 51.8)}


class RouteError(ValueError):
    pass


def load_routes(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    routes = data["routes"]
    validate_routes(routes)
    return routes


def validate_routes(routes: list[dict]) -> None:
    seen = set()
    for r in routes:
        rid = r.get("id")
        where = f"route '{rid}'"
        if not rid or rid in seen:
            raise RouteError(f"{where}: id missing or duplicated")
        seen.add(rid)
        for key in ("name", "type", "distance_km", "waypoints"):
            if key not in r:
                raise RouteError(f"{where}: missing '{key}'")
        if r["type"] not in RIDE_TYPES:
            raise RouteError(f"{where}: type must be one of {RIDE_TYPES}")
        if not r["distance_km"] > 0:
            raise RouteError(f"{where}: distance_km must be positive")
        wps = r["waypoints"]
        if len(wps) < 3:
            raise RouteError(f"{where}: needs at least 3 waypoints (start, far point, back to start)")
        for i, w in enumerate(wps):
            lat, lon = w.get("lat"), w.get("lon")
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                raise RouteError(f"{where}: waypoint {i} needs numeric lat and lon")
            if not (QATAR_BBOX["lat"][0] <= lat <= QATAR_BBOX["lat"][1]
                    and QATAR_BBOX["lon"][0] <= lon <= QATAR_BBOX["lon"][1]):
                raise RouteError(f"{where}: waypoint {i} ({lat},{lon}) is outside Qatar - lat/lon swapped?")
            if i > 0 and w.get("exposure", "highway") not in EXPOSURES:
                raise RouteError(f"{where}: waypoint {i} exposure must be one of {EXPOSURES}")
        if sum(1 for w in wps if w.get("turnaround")) > 1:
            raise RouteError(f"{where}: only one waypoint can be the turnaround")


def turnaround_index(waypoints: list[dict]) -> int:
    """Index where the way out ends: explicit 'turnaround' flag or farthest point from start."""
    for i, w in enumerate(waypoints):
        if w.get("turnaround"):
            return i
    s = waypoints[0]
    return max(range(len(waypoints)),
               key=lambda i: haversine_km(s["lat"], s["lon"], waypoints[i]["lat"], waypoints[i]["lon"]))


def route_legs(route: dict) -> list[dict]:
    """Split a route into legs with bearing, road distance and direction (out/back).

    Straight-line leg lengths are scaled so they add up to the route's real
    distance_km; this keeps timing estimates honest even though waypoints are sparse.
    """
    wps = route["waypoints"]
    turn = turnaround_index(wps)
    raw = [haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) for a, b in zip(wps, wps[1:])]
    scale = route["distance_km"] / (sum(raw) or 1.0)
    legs = []
    start_km = 0.0
    for i, (a, b) in enumerate(zip(wps, wps[1:])):
        km = raw[i] * scale
        legs.append({
            "from": a["name"], "to": b["name"],
            "bearing": bearing_deg(a["lat"], a["lon"], b["lat"], b["lon"]),
            "km": km,
            "start_km": start_km,
            "mid_lat": (a["lat"] + b["lat"]) / 2,
            "mid_lon": (a["lon"] + b["lon"]) / 2,
            "exposure": b.get("exposure", "highway"),
            "direction": "out" if i < turn else "back",
        })
        start_km += km
    return legs
