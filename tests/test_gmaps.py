from urllib.parse import parse_qs, urlparse

import pytest

from planner.gmaps import directions_url, embed_url, select_waypoints

START = {"name": "Start", "lat": 25.3183, "lon": 51.5290}


def line_route(n_inner, flags=None):
    """Start -> n_inner points heading north -> back to start. flags: {index: {...}}."""
    pts = [dict(START)]
    for i in range(1, n_inner + 1):
        p = {"name": f"P{i}", "lat": 25.3183 + 0.05 * i, "lon": 51.5290}
        p.update((flags or {}).get(i, {}))
        pts.append(p)
    pts.append(dict(START))
    return pts


def query(url):
    return parse_qs(urlparse(url).query)


# --- waypoint selection ---------------------------------------------------

def test_keeps_all_when_under_limit():
    pts = line_route(5)
    assert select_waypoints(pts, 8) == pts[1:-1]


def test_limits_waypoint_count():
    pts = line_route(20)
    for limit in (1, 3, 8):
        assert len(select_waypoints(pts, limit)) == limit


def test_zero_limit_returns_nothing():
    assert select_waypoints(line_route(10), 0) == []


def test_preserves_riding_order():
    pts = line_route(20)
    chosen = select_waypoints(pts, 8)
    idx = [pts.index(p) for p in chosen]
    assert idx == sorted(idx)


def test_always_keeps_turnaround():
    pts = line_route(20, {7: {"turnaround": True}})
    assert pts[7] in select_waypoints(pts, 3)


def test_keeps_key_points():
    pts = line_route(20, {2: {"key": True}, 19: {"key": True}})
    chosen = select_waypoints(pts, 4)
    assert pts[2] in chosen and pts[19] in chosen


def test_too_many_key_points_still_respects_limit():
    flags = {i: {"key": True} for i in range(1, 21)}
    flags[10]["turnaround"] = True
    pts = line_route(20, flags)
    chosen = select_waypoints(pts, 5)
    assert len(chosen) == 5
    assert pts[10] in chosen


def test_fill_points_are_spread_out():
    pts = line_route(30)
    chosen = select_waypoints(pts, 4)
    idx = sorted(pts.index(p) for p in chosen)
    gaps = [b - a for a, b in zip(idx, idx[1:])]
    assert min(gaps) >= 3  # not bunched together


# --- URL building ---------------------------------------------------------

def test_directions_url_structure():
    pts = line_route(3)
    url = directions_url(pts)
    assert url.startswith("https://www.google.com/maps/dir/?api=1&")
    q = query(url)
    assert q["origin"] == ["25.31830,51.52900"]
    assert q["destination"] == ["25.31830,51.52900"]
    assert q["travelmode"] == ["driving"]
    assert q["waypoints"][0].split("|") == ["25.36830,51.52900", "25.41830,51.52900", "25.46830,51.52900"]


def test_directions_url_is_percent_encoded():
    url = directions_url(line_route(3))
    raw_query = url.split("?", 1)[1]
    assert "%2C" in raw_query and "%7C" in raw_query
    assert "|" not in raw_query and "," not in raw_query and " " not in raw_query


def test_directions_url_respects_waypoint_limit():
    url = directions_url(line_route(25), max_waypoints=8)
    assert len(query(url)["waypoints"][0].split("|")) == 8


def test_directions_url_without_waypoints():
    pts = [START, {"name": "End", "lat": 25.4, "lon": 51.5}]
    assert "waypoints" not in query(directions_url(pts))


def test_directions_url_needs_two_points():
    with pytest.raises(ValueError):
        directions_url([START])


def test_embed_url_encodes_key_and_uses_driving():
    url = embed_url(line_route(12), "AIza test/key+1", max_waypoints=8)
    assert url.startswith("https://www.google.com/maps/embed/v1/directions?")
    assert "AIza%20test%2Fkey%2B1" in url
    q = query(url)
    assert q["key"] == ["AIza test/key+1"]
    assert q["mode"] == ["driving"]
    assert len(q["waypoints"][0].split("|")) == 8


def test_embed_url_requires_key():
    with pytest.raises(ValueError):
        embed_url(line_route(3), "")
