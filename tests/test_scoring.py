import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from planner.routes import load_routes, route_legs
from planner.scoring import day_settings, plan_day, score_route
from planner.weather import collect_points, sample, window_hours

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
ROUTES = load_routes(ROOT / "routes.json")
LEGS = {r["id"]: route_legs(r) for r in ROUTES}
DAY = date(2026, 10, 3)  # a Saturday
WINDOW = ["05:30", "09:30"]

# Simple due-north out-and-back route: Doha -> 50 km north -> Doha.
NORTH = {
    "id": "north", "name": "Straight North", "type": "short", "distance_km": 100,
    "waypoints": [
        {"name": "Doha", "lat": 25.30, "lon": 51.50},
        {"name": "North", "lat": 25.75, "lon": 51.50, "exposure": "highway"},
        {"name": "Doha", "lat": 25.30, "lon": 51.50, "exposure": "highway"},
    ],
}


def uniform_weather(keys, wind=20, direction=0, gust=None, temp=30, vis=20000, day=DAY):
    # Two days of hours, like the real build (evening rides can run past midnight).
    times = [f"{(day + timedelta(days=h // 24)).isoformat()}T{h % 24:02d}:00" for h in range(48)]
    n = len(times)
    return {k: {"time": times, "wind": [wind] * n, "dir": [direction] * n,
                "gust": [gust if gust is not None else wind * 1.3] * n,
                "temp": [temp] * n, "vis": [vis] * n} for k in keys}


def score_north(**kw):
    legs = route_legs(NORTH)
    wx = uniform_weather(collect_points({"north": legs}, CFG["weather"]["grid_deg"]), **kw)
    return score_route(NORTH, legs, wx, DAY, WINDOW, CFG)


def all_weather(**kw):
    return uniform_weather(collect_points(LEGS, CFG["weather"]["grid_deg"]), **kw)


def test_headwind_out_tailwind_back_is_preferred():
    good = score_north(wind=18, direction=0)      # wind from north: head out, tail home
    bad = score_north(wind=18, direction=180)     # wind from south: tail out, head home
    assert good["head_out"] == pytest.approx(18, abs=0.5)
    assert good["head_back"] == pytest.approx(-18, abs=0.5)
    assert good["score"] > bad["score"]
    assert "Headwind on the way out" in good["reason"]
    assert "headwind on the way home" in bad["reason"]


def test_crosswind_costs_more_than_head_or_tail():
    along = score_north(wind=22, direction=0)
    across = score_north(wind=22, direction=90)
    assert across["max_cross"] == pytest.approx(22, abs=0.5)
    assert across["score"] < along["score"]
    assert "crosswind" in across["reason"].lower()


def test_exposure_increases_crosswind_penalty():
    import copy
    coastal = copy.deepcopy(NORTH)
    for w in coastal["waypoints"][1:]:
        w["exposure"] = "coastal"
    legs = route_legs(coastal)
    wx = uniform_weather(collect_points({"c": legs}, CFG["weather"]["grid_deg"]), wind=22, direction=90)
    assert score_route(coastal, legs, wx, DAY, WINDOW, CFG)["score"] < score_north(wind=22, direction=90)["score"]


def test_calm_day_is_good_and_high_score():
    r = score_north(wind=6, direction=45, gust=10)
    assert r["status"] == "good"
    assert r["score"] >= 95


def test_gusts_over_40_penalised_and_over_55_unsafe():
    calm = score_north(wind=15, gust=30)
    gusty = score_north(wind=15, gust=48)
    wild = score_north(wind=15, gust=60)
    assert gusty["score"] < calm["score"]
    assert gusty["status"] == "caution"
    assert wild["status"] == "unsafe"


def test_high_average_wind_is_unsafe():
    assert score_north(wind=38, gust=45)["status"] == "unsafe"


def test_heat_and_dust_flags():
    r = score_north(wind=8, temp=41, vis=2500)
    assert "heat" in r["flags"] and "dust" in r["flags"]
    assert r["status"] == "caution"
    assert "Hot" in r["reason"] and "visibility" in r["reason"]


def test_plan_day_picks_recommendation_and_two_alternates():
    plan = plan_day(DAY, "long", ROUTES, LEGS, all_weather(wind=12, direction=330), CFG)
    assert plan["recommended"]["type"] == "long"
    assert len(plan["alternates"]) == 2
    ids = [plan["recommended"]["id"]] + [a["id"] for a in plan["alternates"]]
    assert len(set(ids)) == 3
    scores = [plan["recommended"]["score"]] + [a["score"] for a in plan["alternates"]]
    assert scores == sorted(scores, reverse=True)
    assert plan["summary"]["wind_dir_compass"] in ("NNW", "NW")
    start_hour = CFG["sessions"][CFG["ride_days"]["saturday"]["session"]]["window"][0][:2]
    assert plan["hourly"][0]["time"] == f"{start_hour}:00"


def test_plan_day_warns_skip_when_too_windy():
    plan = plan_day(DAY, "long", ROUTES, LEGS, all_weather(wind=40, gust=60), CFG)
    assert plan["status"] == "unsafe"
    assert "Skip or ride short" in plan["advice"]


def test_plan_day_without_data():
    plan = plan_day(DAY, "short", ROUTES, LEGS, {}, CFG)
    assert plan["status"] == "no_data"
    assert plan["recommended"] is None


def test_day_settings_from_config():
    tue, sat, thu = (day_settings(d, CFG) for d in (date(2026, 9, 29), date(2026, 10, 3), date(2026, 10, 1)))
    assert (tue["ride_type"], tue["session"]) == ("short", "evening")
    assert (sat["ride_type"], sat["session"]) == ("long", "morning")
    assert thu["club_day"] is False and thu["session"] == "morning"
    assert tue["window"] == CFG["sessions"]["evening"]["window"]


@pytest.mark.parametrize("session", ["morning", "evening"])
@pytest.mark.parametrize("ride_type", ["short", "long"])
def test_every_day_supports_both_sessions(session, ride_type):
    thursday = date(2026, 10, 1)
    plan = plan_day(thursday, ride_type, ROUTES, LEGS, all_weather(wind=10, day=thursday), CFG, session)
    assert plan["session"] == session
    assert plan["window"] == CFG["sessions"][session]["window"]
    assert plan["recommended"]["type"] == ride_type
    assert plan["hourly"][0]["time"] == CFG["sessions"][session]["window"][0][:2] + ":00"


def test_long_evening_ride_runs_past_midnight():
    # At a relaxed pace a long ride starting at 20:00 finishes after midnight; it must still be scored.
    slow = {**CFG, "average_speed_kmh": {**CFG["average_speed_kmh"], "long": 50}}
    plan = plan_day(DAY, "long", ROUTES, LEGS, all_weather(wind=10), slow, "evening")
    assert plan["status"] != "no_data"
    assert all(r["score"] is not None for r in plan["routes"])
    times = [leg["time"] for r in plan["routes"] for leg in r["legs"]]
    assert times[0] >= "20:00" and any(t < "06:00" for t in times)


def test_sample_interpolates_wind_as_vector():
    series = {"time": ["2026-10-03T05:00", "2026-10-03T06:00"], "wind": [10, 10], "dir": [350, 10],
              "gust": [15, 25], "temp": [30, 32], "vis": [None, None]}
    s = sample(series, datetime(2026, 10, 3, 5, 30))
    assert s["dir"] == pytest.approx(0, abs=0.01) or s["dir"] == pytest.approx(360, abs=0.01)
    assert s["gust"] == pytest.approx(20)
    assert s["temp"] == pytest.approx(31)
    assert s["vis"] is None


def test_window_hours_cover_ride_window():
    hours = window_hours(DAY, ["05:30", "09:30"])
    assert [h.hour for h in hours] == [5, 6, 7, 8, 9, 10]
