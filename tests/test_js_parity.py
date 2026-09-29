"""The browser (site/planner.js) and Python planners must agree on the same forecast."""
import json
import math
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from planner.routes import load_routes, route_legs
from planner.scoring import plan_day
from planner.weather import collect_points

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
ROUTES = load_routes(ROOT / "routes.json")
LEGS = {r["id"]: route_legs(r) for r in ROUTES}


def varied_weather(day: date, seed: int):
    """Deterministic but uneven weather: speed/direction vary by place and hour."""
    times = [f"{(day + timedelta(days=h // 24)).isoformat()}T{h % 24:02d}:00" for h in range(48)]
    out = {}
    for n, key in enumerate(collect_points(LEGS, CFG["weather"]["grid_deg"])):
        lat, lon = (float(x) for x in key.split(","))
        base = 8 + seed * 6 + 6 * math.sin(lat * 7 + seed) + 4 * math.cos(lon * 5)
        out[key] = {
            "time": times,
            "wind": [max(0.0, base + 3 * math.sin(h / 3 + n)) for h in range(48)],
            "dir": [(300 + seed * 70 + 40 * math.sin(lon * 3 + h / 5)) % 360 for h in range(48)],
            "gust": [max(0.0, base * 1.5 + 5 * math.cos(h / 4)) for h in range(48)],
            "temp": [30 + seed * 3 + 5 * math.sin(h / 6) for h in range(48)],
            "vis": [None if n % 5 == 0 else 3000 + 20000 * abs(math.sin(h + seed)) for h in range(48)],
        }
    return out


@pytest.mark.parametrize("seed,day,ride_type,session", [
    (0, date(2026, 9, 29), "short", "evening"),
    (1, date(2026, 10, 3), "long", "morning"),
    (2, date(2026, 10, 1), "short", "morning"),
    (3, date(2026, 10, 1), "long", "evening"),  # runs past midnight
    (4, date(2026, 10, 3), "long", "morning"),  # windy enough to trigger "skip"
])
def test_js_matches_python(tmp_path, seed, day, ride_type, session):
    wx = varied_weather(day, seed)
    wx_file = tmp_path / "wx.json"
    wx_file.write_text(json.dumps(wx), encoding="utf-8")
    py = plan_day(day, ride_type, ROUTES, LEGS, wx, CFG, session)
    out = subprocess.run([NODE, str(ROOT / "tests" / "js_plan.js"), str(ROOT / "config.json"),
                          str(ROOT / "routes.json"), str(wx_file), day.isoformat(), ride_type, session],
                         capture_output=True, text=True, encoding="utf-8", check=True)
    js = json.loads(out.stdout)

    assert js["session"] == py["session"] == session
    assert js["status"] == py["status"]
    assert js["weekday"] == py["weekday"]
    assert [r["id"] for r in js["routes"]] == [r["id"] for r in py["routes"]]
    for a, b in zip(js["routes"], py["routes"]):
        assert a["status"] == b["status"], a["id"]
        assert a["flags"] == b["flags"], a["id"]
        assert abs(a["score"] - b["score"]) <= 1, a["id"]
        assert a["reason"] == b["reason"], a["id"]
    assert js["summary"]["wind_dir_compass"] == py["summary"]["wind_dir_compass"]
    assert [h["time"] for h in js["hourly"]] == [h["time"] for h in py["hourly"]]
    for a, b in zip(js["hourly"], py["hourly"]):
        assert a["wind"] == pytest.approx(b["wind"], abs=0.11)
    assert bool(js["advice"]) == bool(py["advice"])
