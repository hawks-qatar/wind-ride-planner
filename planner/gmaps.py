"""Google Maps link builders (no API key needed for directions links)."""
from __future__ import annotations

from urllib.parse import quote, urlencode

from .geo import haversine_km
from .routes import turnaround_index

DIRECTIONS_BASE = "https://www.google.com/maps/dir/"
EMBED_BASE = "https://www.google.com/maps/embed/v1/directions"


def fmt_point(p: dict) -> str:
    return f"{p['lat']:.5f},{p['lon']:.5f}"


def select_waypoints(points: list[dict], max_waypoints: int) -> list[dict]:
    """Pick at most `max_waypoints` intermediate points (origin/destination excluded).

    Keeps the turnaround and any point flagged "key" first (they force the right
    roads), then fills the remaining slots with points spread evenly by distance
    along the route. Riding order is always preserved.
    """
    if max_waypoints < 0:
        raise ValueError("max_waypoints must be >= 0")
    inner = list(range(1, len(points) - 1))
    if len(inner) <= max_waypoints:
        return [points[i] for i in inner]
    if max_waypoints == 0:
        return []

    cum = [0.0]
    for a, b in zip(points, points[1:]):
        cum.append(cum[-1] + haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]))
    total = cum[-1]

    turn = turnaround_index(points)
    must = [i for i in inner if i == turn or points[i].get("key")]
    if len(must) > max_waypoints:
        # Too many key points: keep the turnaround plus an even spread of the rest.
        others = [i for i in must if i != turn]
        room = max_waypoints - (1 if turn in must else 0)
        step = len(others) / room if room else 0
        chosen = {others[int(k * step)] for k in range(room)}
        if turn in must:
            chosen.add(turn)
        return [points[i] for i in sorted(chosen)]

    # Fill the free slots one at a time with the point farthest (along the route)
    # from everything already chosen, so the kept points end up evenly spread.
    chosen = set(must)
    anchors = [0.0, total]
    for _ in range(max_waypoints - len(chosen)):
        candidates = [i for i in inner if i not in chosen]
        taken = anchors + [cum[j] for j in chosen]
        chosen.add(max(candidates, key=lambda i: min(abs(cum[i] - t) for t in taken)))
    return [points[i] for i in sorted(chosen)]


def _encode(params: dict) -> str:
    # quote (not quote_plus) with no safe characters: "," -> %2C and "|" -> %7C.
    return urlencode(params, quote_via=quote, safe="")


def directions_url(points: list[dict], max_waypoints: int = 8) -> str:
    """Universal Google Maps directions link; opens the Maps app on phones."""
    if len(points) < 2:
        raise ValueError("need at least an origin and a destination")
    params = {"api": "1", "origin": fmt_point(points[0]), "destination": fmt_point(points[-1])}
    wps = select_waypoints(points, max_waypoints)
    if wps:
        params["waypoints"] = "|".join(fmt_point(p) for p in wps)
    params["travelmode"] = "driving"
    return DIRECTIONS_BASE + "?" + _encode(params)


def embed_url(points: list[dict], api_key: str, max_waypoints: int = 8) -> str:
    """Maps Embed API (directions mode) URL. Requires an API key restricted by referrer."""
    if not api_key:
        raise ValueError("api_key is required for the Embed API")
    params = {"key": api_key, "origin": fmt_point(points[0]), "destination": fmt_point(points[-1])}
    wps = select_waypoints(points, max_waypoints)
    if wps:
        params["waypoints"] = "|".join(fmt_point(p) for p in wps)
    params["mode"] = "driving"
    return EMBED_BASE + "?" + _encode(params)
