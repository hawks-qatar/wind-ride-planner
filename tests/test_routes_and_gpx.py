import copy
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from planner.gmaps import directions_url
from planner.gpx import route_to_gpx
from planner.routes import RouteError, load_routes, route_legs, turnaround_index, validate_routes

ROOT = Path(__file__).resolve().parents[1]
ROUTES = load_routes(ROOT / "routes.json")


def test_route_library_is_valid_and_balanced():
    short = [r for r in ROUTES if r["type"] == "short"]
    long_ = [r for r in ROUTES if r["type"] == "long"]
    assert len(short) >= 6 and len(long_) >= 6


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r["id"])
def test_distances_match_ride_type(route):
    # "about" 60-120 km short and 200-350 km long, with a little slack.
    lo, hi = (60, 130) if route["type"] == "short" else (200, 350)
    assert lo <= route["distance_km"] <= hi


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r["id"])
def test_every_route_is_a_round_trip_with_out_and_back(route):
    wps = route["waypoints"]
    assert (wps[0]["lat"], wps[0]["lon"]) == (wps[-1]["lat"], wps[-1]["lon"])
    dirs = {leg["direction"] for leg in route_legs(route)}
    assert dirs == {"out", "back"}


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r["id"])
def test_legs_add_up_to_route_distance(route):
    assert sum(leg["km"] for leg in route_legs(route)) == pytest.approx(route["distance_km"])


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r["id"])
def test_maps_link_within_limit(route):
    url = directions_url(route["waypoints"], 8)
    assert url.count("%7C") <= 7


def test_turnaround_defaults_to_farthest_point():
    wps = [{"name": "a", "lat": 25.3, "lon": 51.5}, {"name": "b", "lat": 25.5, "lon": 51.5},
           {"name": "c", "lat": 25.9, "lon": 51.3}, {"name": "a", "lat": 25.3, "lon": 51.5}]
    assert turnaround_index(wps) == 2


def test_validation_catches_swapped_lat_lon():
    bad = copy.deepcopy(ROUTES[:1])
    w = bad[0]["waypoints"][1]
    w["lat"], w["lon"] = w["lon"], w["lat"]
    with pytest.raises(RouteError, match="outside Qatar"):
        validate_routes(bad)


def test_validation_catches_bad_exposure_and_duplicates():
    bad = copy.deepcopy(ROUTES[:1])
    bad[0]["waypoints"][1]["exposure"] = "windy"
    with pytest.raises(RouteError, match="exposure"):
        validate_routes(bad)
    with pytest.raises(RouteError, match="duplicated"):
        validate_routes(copy.deepcopy(ROUTES[:1]) * 2)


def test_gpx_is_valid_xml_with_all_points():
    route = copy.deepcopy(ROUTES[0])
    route["name"] = "Fish & Chips <Loop>"
    root = ET.fromstring(route_to_gpx(route))
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    assert root.find("g:rte/g:name", ns).text == "Fish & Chips <Loop>"
    assert len(root.findall("g:rte/g:rtept", ns)) == len(route["waypoints"])
    assert len(root.findall("g:trk/g:trkseg/g:trkpt", ns)) == len(route["waypoints"])
