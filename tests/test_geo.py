import math

import pytest

from planner.geo import (bearing_deg, compass_point, haversine_km, uv_to_wind,
                         wind_components, wind_to_uv)


# --- bearings -------------------------------------------------------------

@pytest.mark.parametrize("dlat,dlon,expected", [
    (0.1, 0.0, 0.0),     # due north
    (0.0, 0.1, 90.0),    # due east
    (-0.1, 0.0, 180.0),  # due south
    (0.0, -0.1, 270.0),  # due west
])
def test_bearing_cardinal_directions(dlat, dlon, expected):
    lat, lon = 25.3, 51.5
    assert bearing_deg(lat, lon, lat + dlat, lon + dlon) == pytest.approx(expected, abs=0.1)


def test_bearing_doha_to_al_khor_is_roughly_north():
    # Al Khor is NNW-ish of the Corniche.
    b = bearing_deg(25.3183, 51.5290, 25.6850, 51.5050)
    assert 350 < b < 360


def test_bearing_doha_to_dukhan_is_roughly_west():
    b = bearing_deg(25.3183, 51.5290, 25.4250, 50.7850)
    assert 275 < b < 285


def test_bearing_always_in_range():
    for lat2, lon2 in [(25.0, 51.0), (26.0, 52.0), (25.3, 51.5)]:
        assert 0 <= bearing_deg(25.3, 51.5, lat2, lon2) < 360


def test_haversine_known_distance():
    # One degree of latitude is ~111.2 km.
    assert haversine_km(25.0, 51.0, 26.0, 51.0) == pytest.approx(111.2, abs=0.3)


# --- wind components ------------------------------------------------------

def test_pure_headwind():
    # Riding north into a wind FROM the north.
    head, cross = wind_components(0, 0, 20)
    assert head == pytest.approx(20)
    assert cross == pytest.approx(0, abs=1e-6)


def test_pure_tailwind():
    # Riding south with a wind FROM the north behind you.
    head, cross = wind_components(180, 0, 20)
    assert head == pytest.approx(-20)
    assert cross == pytest.approx(0, abs=1e-6)


def test_crosswind_from_right():
    # Riding north, wind FROM the east hits your right side.
    head, cross = wind_components(0, 90, 20)
    assert head == pytest.approx(0, abs=1e-6)
    assert cross == pytest.approx(20)


def test_crosswind_from_left():
    head, cross = wind_components(0, 270, 20)
    assert cross == pytest.approx(-20)


def test_quartering_headwind_45_degrees():
    head, cross = wind_components(90, 45, 20)  # riding east, wind from NE
    assert head == pytest.approx(20 * math.cos(math.radians(45)))
    assert cross == pytest.approx(-20 * math.sin(math.radians(45)))  # from the left


def test_components_preserve_magnitude():
    for heading in range(0, 360, 30):
        for wind_from in range(0, 360, 45):
            h, c = wind_components(heading, wind_from, 17)
            assert math.hypot(h, c) == pytest.approx(17)


def test_wrap_around_north():
    # Heading 350, wind from 10 -> 20 deg off the nose, almost a pure headwind.
    head, cross = wind_components(350, 10, 10)
    assert head == pytest.approx(10 * math.cos(math.radians(20)))
    assert cross > 0


def test_out_and_back_swaps_head_and_tail():
    out_head, _ = wind_components(0, 0, 15)
    back_head, _ = wind_components(180, 0, 15)
    assert out_head == -back_head


# --- vector helpers -------------------------------------------------------

@pytest.mark.parametrize("speed,direction", [(10, 0), (15, 90), (22, 225), (5, 359)])
def test_uv_round_trip(speed, direction):
    s, d = uv_to_wind(*wind_to_uv(speed, direction))
    assert s == pytest.approx(speed)
    assert (d - direction + 180) % 360 - 180 == pytest.approx(0, abs=1e-6)


def test_north_wind_moves_air_south():
    u, v = wind_to_uv(10, 0)
    assert u == pytest.approx(0, abs=1e-9)
    assert v == pytest.approx(-10)


@pytest.mark.parametrize("deg,name", [(0, "N"), (11, "N"), (12, "NNE"), (315, "NW"), (359, "N"), (180, "S")])
def test_compass_point(deg, name):
    assert compass_point(deg) == name
