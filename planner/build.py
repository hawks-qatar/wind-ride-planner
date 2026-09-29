"""Build the static site data.

    python -m planner.build                 # fetch forecast, write site/data + site/gpx
    python -m planner.build --serve         # ...then preview at http://localhost:8000
    python -m planner.build --weather-file saved.json   # offline, from a saved forecast

The Google Maps Embed key is read from the environment variable named in
config.json (google_maps.embed_api_key_env) or from a local .env file. It is
never stored in the repo; it only ends up in the generated site (which is public,
so the key MUST be restricted to your site's domain - see README).
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .gmaps import directions_url, embed_url
from .gpx import route_to_gpx
from .routes import load_routes, route_legs
from .scoring import SESSIONS, day_settings, plan_day
from .weather import collect_points, fetch_forecast

ROOT = Path(__file__).resolve().parents[1]


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_env_key(name: str) -> str:
    """Env var first, then a KEY=value line in a local .env file (git-ignored)."""
    if os.environ.get(name):
        return os.environ[name].strip()
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    return ""


def site_routes(routes: list[dict], cfg: dict, key: str) -> list[dict]:
    max_wp = cfg["google_maps"]["max_waypoints"]
    out = []
    for r in routes:
        out.append({
            **r,
            "maps_url": directions_url(r["waypoints"], max_wp),
            "embed_url": embed_url(r["waypoints"], key, max_wp) if key else None,
            "gpx": f"gpx/{r['id']}.gpx",
        })
    return out


def build(out_dir: Path, days: int, weather_file: Path | None, save_weather: Path | None) -> dict:
    cfg = load_config(ROOT / "config.json")
    routes = load_routes(ROOT / "routes.json")
    legs = {r["id"]: route_legs(r) for r in routes}
    key = read_env_key(cfg["google_maps"]["embed_api_key_env"])

    data_dir, gpx_dir = out_dir / "data", out_dir / "gpx"
    for d in (data_dir, gpx_dir):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)

    for r in routes:
        (gpx_dir / f"{r['id']}.gpx").write_text(route_to_gpx(r, cfg.get("club_name", "")), encoding="utf-8", newline="\n")
    public_cfg = {k: v for k, v in cfg.items() if not k.startswith("_")}
    (data_dir / "config.json").write_text(json.dumps(public_cfg, indent=1), encoding="utf-8")
    (data_dir / "routes.json").write_text(json.dumps(site_routes(routes, cfg, key), indent=1), encoding="utf-8")

    now = datetime.now(timezone(timedelta(hours=cfg["utc_offset_hours"])))
    today = now.date()
    end = today + timedelta(days=days - 1)
    fetch_end = end + timedelta(days=1)  # evening rides can run past midnight
    forecast = {"generated_at": now.isoformat(timespec="minutes"), "timezone": cfg["timezone"],
                "has_embed_key": bool(key), "days": [], "error": None}
    try:
        if weather_file:
            weather = json.loads(weather_file.read_text(encoding="utf-8"))
        else:
            points = collect_points(legs, cfg["weather"]["grid_deg"])
            print(f"Fetching Open-Meteo forecast for {len(points)} grid points, {today} to {end} ...")
            weather = fetch_forecast(points, today, fetch_end, cfg)
        if save_weather:
            save_weather.write_text(json.dumps(weather), encoding="utf-8")
        d = today
        while d <= end:
            settings = day_settings(d, cfg)
            forecast["days"].append({
                "date": d.isoformat(), "weekday": d.strftime("%A"), **settings,
                "plans": {s: {t: plan_day(d, t, routes, legs, weather, cfg, s) for t in ("short", "long")}
                          for s in SESSIONS},
            })
            d += timedelta(days=1)
    except Exception as exc:  # keep the site usable (it can still fetch live in the browser)
        forecast["error"] = f"{type(exc).__name__}: {exc}"
        print(f"WARNING: forecast failed: {forecast['error']}", file=sys.stderr)

    (data_dir / "forecast.json").write_text(json.dumps(_slim(forecast), separators=(",", ":")), encoding="utf-8")
    return forecast


def _slim(forecast: dict) -> dict:
    """Drop per-leg detail from the published forecast; the page doesn't use it (keeps the file small)."""
    def strip(r):
        return {k: v for k, v in r.items() if k != "legs"} if r else r
    for day in forecast["days"]:
        for plans in day["plans"].values():
            for plan in plans.values():
                plan["routes"] = [strip(r) for r in plan["routes"]]
                plan["recommended"] = strip(plan["recommended"])
                plan["alternates"] = [strip(r) for r in plan["alternates"]]
                if plan.get("short_fallback"):
                    plan["short_fallback"] = strip(plan["short_fallback"])
    return forecast


def serve(out_dir: Path, port: int) -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out_dir))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"Preview: http://localhost:{port}/  (Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build the Wind Ride Planner site data.")
    p.add_argument("--out", type=Path, default=ROOT / "site", help="site folder (default: site/)")
    p.add_argument("--days", type=int, default=None, help="days to prebuild (default: config)")
    p.add_argument("--weather-file", type=Path, help="use a saved forecast instead of calling Open-Meteo")
    p.add_argument("--save-weather", type=Path, help="save the fetched forecast (for offline runs/tests)")
    p.add_argument("--serve", action="store_true", help="start a local preview server after building")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    cfg = load_config(ROOT / "config.json")
    days = args.days or cfg["weather"]["forecast_days_prebuilt"]
    forecast = build(args.out, days, args.weather_file, args.save_weather)
    for day in forecast["days"]:
        plan = day["plans"][day["session"]][day["ride_type"]]
        top = plan["recommended"]
        label = f"{top['name']} ({top['score']}, {top['status']})" if top else plan["advice"]
        print(f"  {day['date']} {day['weekday'][:3]} {day['session']:7} {day['ride_type']:5} -> {label}")
    if args.serve:
        serve(args.out, args.port)
    return 1 if forecast["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
