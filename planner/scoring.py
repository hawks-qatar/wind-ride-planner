"""Wind scoring: turns a forecast + a route into a 0-100 score and a plain-English reason.

The same algorithm is mirrored in site/planner.js for the in-browser "check any
day" mode; tests/test_js_parity.py keeps the two in sync.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from .geo import compass_point, wind_components
from .weather import circular_mean_deg, grid_key, parse_time, sample, window_hours

STATUS_ORDER = {"good": 0, "caution": 1, "unsafe": 2}
NOTABLE_KMH = 5  # head/tail winds below this are described as calm


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _wavg(values, weights):
    total = sum(weights)
    return sum(v * w for v, w in zip(values, weights)) / total if total else 0.0


def score_route(route: dict, legs: list[dict], weather: dict, day: date, window: list[str], cfg: dict) -> dict:
    th, wt, mult = cfg["thresholds"], cfg["weights"], cfg["exposure_multipliers"]
    grid = cfg["weather"]["grid_deg"]
    speed = cfg["average_speed_kmh"][route["type"]]
    start = parse_time(day, window[0])

    leg_results = []
    for leg in legs:
        when = start + timedelta(hours=(leg["start_km"] + leg["km"] / 2) / speed)
        series = weather.get(grid_key(leg["mid_lat"], leg["mid_lon"], grid))
        s = sample(series, when) if series else None
        if s is None:
            return {"id": route["id"], "name": route["name"], "type": route["type"],
                    "distance_km": route["distance_km"], "score": None, "status": "no_data",
                    "reason": "No forecast available for this time yet.", "flags": [], "legs": []}
        head, cross = wind_components(leg["bearing"], s["dir"], s["wind"])
        m = mult.get(leg["exposure"], 1.0)
        gust = s["gust"] if s["gust"] is not None else s["wind"]
        penalty = (max(0.0, abs(cross) - th["crosswind_free_kmh"]) * m * wt["crosswind"]
                   + max(0.0, gust - th["gust_penalty_kmh"]) * m * wt["gust"]
                   + max(0.0, s["wind"] - th["wind_caution_kmh"]) * wt["average_wind"])
        leg_results.append({
            "from": leg["from"], "to": leg["to"], "direction": leg["direction"],
            "exposure": leg["exposure"], "km": round(leg["km"], 1),
            "bearing": round(leg["bearing"]), "time": when.strftime("%H:%M"),
            "wind": s["wind"], "wind_dir": s["dir"], "gust": gust, "temp": s["temp"], "vis": s["vis"],
            "head": head, "cross": cross, "exposure_mult": m, "penalty": penalty,
        })

    kms = [lr["km"] for lr in leg_results]
    base_penalty = _wavg([lr["penalty"] for lr in leg_results], kms)

    out = [lr for lr in leg_results if lr["direction"] == "out"]
    back = [lr for lr in leg_results if lr["direction"] == "back"]
    head_out = _wavg([lr["head"] for lr in out], [lr["km"] for lr in out])
    head_back = _wavg([lr["head"] for lr in back], [lr["km"] for lr in back])
    # Positive when you fight the wind while fresh and get pushed home; negative the other way round.
    pattern = _clamp((head_out - head_back) / 2 * wt["pattern_bonus"],
                     -wt["pattern_bonus_max"], wt["pattern_bonus_max"])

    max_wind = max(lr["wind"] for lr in leg_results)
    max_gust = max(lr["gust"] for lr in leg_results)
    temps = [lr["temp"] for lr in leg_results if lr["temp"] is not None]
    viss = [lr["vis"] for lr in leg_results if lr["vis"] is not None]
    max_temp = max(temps) if temps else None
    min_vis = min(viss) if viss else None
    worst = max(leg_results, key=lambda lr: abs(lr["cross"]) * lr["exposure_mult"])

    flags = []
    extra = 0.0
    if max_temp is not None and max_temp > th["heat_c"]:
        flags.append("heat")
        extra += wt["heat_penalty"]
    if min_vis is not None and min_vis < th["dust_visibility_m"]:
        flags.append("dust")
        extra += wt["dust_penalty"]

    if max_wind > th["wind_skip_kmh"] or max_gust > th["gust_skip_kmh"]:
        status = "unsafe"
        flags.append("high_wind")
    elif (max_wind > th["wind_caution_kmh"] or abs(worst["cross"]) > th["crosswind_caution_kmh"]
          or max_gust > th["gust_penalty_kmh"] or flags):
        status = "caution"
    else:
        status = "good"

    score = round(_clamp(100 - base_penalty + pattern - extra, 0, 100))
    result = {
        "id": route["id"], "name": route["name"], "type": route["type"],
        "distance_km": route["distance_km"], "score": score, "status": status, "flags": flags,
        "head_out": round(head_out, 1), "head_back": round(head_back, 1),
        "max_wind": round(max_wind, 1), "max_gust": round(max_gust, 1),
        "max_cross": round(abs(worst["cross"]), 1),
        "worst_cross_leg": f"{worst['from']} to {worst['to']}", "worst_cross_exposure": worst["exposure"],
        "max_temp": None if max_temp is None else round(max_temp, 1),
        "min_vis": None if min_vis is None else round(min_vis),
        "legs": [_public_leg(lr) for lr in leg_results],
    }
    result["reason"] = explain(result, cfg)
    return result


def _public_leg(lr: dict) -> dict:
    return {k: (round(v, 1) if isinstance(v, float) else v)
            for k, v in lr.items() if k not in ("penalty", "exposure_mult")}


def _n(x: float, digits: int = 0) -> str:
    """Round half up for display (matches JavaScript's toFixed on the page)."""
    f = 10 ** digits
    return f"{math.floor(x * f + 0.5) / f:.{digits}f}"


def explain(r: dict, cfg: dict) -> str:
    """One or two plain-English sentences a rider can read at a glance."""
    th = cfg["thresholds"]
    parts = []
    ho, hb = r["head_out"], r["head_back"]
    n = NOTABLE_KMH
    if ho >= n and hb <= -n:
        parts.append(f"Headwind on the way out (~{_n(ho)} km/h), tailwind pushing you home.")
    elif ho <= -n and hb >= n:
        parts.append(f"Tailwind out but headwind on the way home (~{_n(hb)} km/h) - a harder finish.")
    elif max(abs(ho), abs(hb)) < n:
        parts.append("Little head- or tailwind either way.")
    else:
        parts.append(f"Mixed wind: {_ht(ho)} out, {_ht(hb)} back.")

    c = r["max_cross"]
    stretch = f"{r['worst_cross_leg']} ({r['worst_cross_exposure'].replace('_', ' ')})"
    if c > th["crosswind_caution_kmh"]:
        parts.append(f"Strong crosswind ~{_n(c)} km/h on {stretch}.")
    elif c > th["crosswind_free_kmh"]:
        parts.append(f"Moderate crosswind, worst ~{_n(c)} km/h on {stretch}.")
    else:
        parts.append("Crosswinds light.")

    g = r["max_gust"]
    if g > th["gust_skip_kmh"]:
        parts.append(f"Gusts to {_n(g)} km/h - too strong.")
    elif g > th["gust_penalty_kmh"]:
        parts.append(f"Gusts to {_n(g)} km/h - stay alert.")
    else:
        parts.append(f"Gusts up to {_n(g)} km/h.")
    if "heat" in r["flags"]:
        parts.append(f"Hot: up to {_n(r['max_temp'])}°C.")
    if "dust" in r["flags"]:
        parts.append(f"Low visibility (dust, haze or fog) ~{_n(r['min_vis'] / 1000, 1)} km.")
    return " ".join(parts)


def _ht(h: float) -> str:
    if abs(h) < NOTABLE_KMH:
        return "calm"
    return f"{'headwind' if h > 0 else 'tailwind'} ~{_n(abs(h))}"


def rank(results: list[dict]) -> list[dict]:
    """Safe routes first, then by score (higher is better)."""
    return sorted(results, key=lambda r: (r["score"] is None, STATUS_ORDER.get(r["status"], 3),
                                          -(r["score"] or 0), r["distance_km"]))


def day_settings(day: date, cfg: dict) -> dict:
    """Default ride type and window for a date; club days come from config ride_days."""
    for rd in cfg["ride_days"].values():
        if rd["weekday"] == day.weekday():
            return {"ride_type": rd["ride_type"], "window": rd["window"], "club_day": True}
    other = cfg["other_days"]
    return {"ride_type": other["ride_type"], "window": other["window"], "club_day": False}


def plan_day(day: date, ride_type: str, routes: list[dict], legs_by_route: dict, weather: dict, cfg: dict) -> dict:
    """Score every route of the ride type and pick a recommendation plus alternates."""
    window = day_settings(day, cfg)["window"]
    scored = rank([score_route(r, legs_by_route[r["id"]], weather, day, window, cfg)
                   for r in routes if r["type"] == ride_type])
    usable = [r for r in scored if r["score"] is not None]
    plan = {
        "date": day.isoformat(), "weekday": day.strftime("%A"), "ride_type": ride_type,
        "window": window, "routes": scored,
        "recommended": usable[0] if usable else None,
        "alternates": usable[1:1 + cfg.get("alternates", 2)],
        "hourly": hourly_summary(day, window, usable[0], legs_by_route, weather, cfg) if usable else [],
    }
    plan["status"], plan["advice"] = _advice(plan, day, routes, legs_by_route, weather, cfg)
    plan["summary"] = _summary(plan)
    return plan


def _advice(plan, day, routes, legs_by_route, weather, cfg):
    top = plan["recommended"]
    if top is None:
        return "no_data", "No forecast for this date yet (Open-Meteo covers about 16 days)."
    if top["status"] != "unsafe":
        return top["status"], ""
    th = cfg["thresholds"]
    msg = (f"Wind is above the safe limit on every {plan['ride_type']} route "
           f"(over {th['wind_skip_kmh']} km/h or gusts over {th['gust_skip_kmh']} km/h). "
           "Skip or ride short instead.")
    if plan["ride_type"] == "long":
        short = rank([score_route(r, legs_by_route[r["id"]], weather, day, plan["window"], cfg)
                      for r in routes if r["type"] == "short"])
        ok = [r for r in short if r["status"] in ("good", "caution")]
        if ok:
            msg += f" Best short option: {ok[0]['name']} (score {ok[0]['score']})."
            plan["short_fallback"] = ok[0]
    return "unsafe", msg


def _summary(plan):
    top = plan["recommended"]
    if not top:
        return None
    legs = top["legs"]
    kms = [lg["km"] for lg in legs]
    direction = circular_mean_deg([lg["wind_dir"] for lg in legs], [lg["km"] * lg["wind"] for lg in legs])
    return {
        "wind_avg": round(_wavg([lg["wind"] for lg in legs], kms), 1),
        "wind_dir": round(direction) % 360,
        "wind_dir_compass": compass_point(direction),
        "gust_max": top["max_gust"], "temp_max": top["max_temp"], "vis_min": top["min_vis"],
    }


def hourly_summary(day, window, route_result, legs_by_route, weather, cfg):
    """Hour-by-hour wind for the ride window, averaged over the recommended route's grid cells."""
    grid = cfg["weather"]["grid_deg"]
    keys = sorted({grid_key(lg["mid_lat"], lg["mid_lon"], grid) for lg in legs_by_route[route_result["id"]]})
    rows = []
    for h in window_hours(day, window):
        samples = [s for s in (sample(weather[k], h) for k in keys if k in weather) if s]
        if not samples:
            continue
        rows.append({
            "time": h.strftime("%H:%M"),
            "wind": round(sum(s["wind"] for s in samples) / len(samples), 1),
            "gust": round(max(s["gust"] or 0 for s in samples), 1),
            "dir": round(circular_mean_deg([s["dir"] for s in samples], [s["wind"] for s in samples])),
            "temp": round(max(s["temp"] for s in samples if s["temp"] is not None), 1)
            if any(s["temp"] is not None for s in samples) else None,
        })
    return rows
