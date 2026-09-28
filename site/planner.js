/*
 * In-browser copy of the Python planner (planner/geo.py, routes.py, weather.py,
 * scoring.py) used for the "check any day" live mode. Keep the two in sync:
 * tests/test_js_parity.py runs both on the same forecast and compares results.
 *
 * Times are "naive" Qatar local times, handled as UTC Date objects so the
 * browser's own timezone never interferes.
 */
(function (root) {
  "use strict";

  // ---------- geo ----------
  const R = 6371.0088;
  const rad = (d) => (d * Math.PI) / 180;
  const deg = (r) => (r * 180) / Math.PI;
  const mod360 = (x) => ((x % 360) + 360) % 360;

  function haversineKm(lat1, lon1, lat2, lon2) {
    const p1 = rad(lat1), p2 = rad(lat2), dp = p2 - p1, dl = rad(lon2 - lon1);
    const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(a));
  }

  function bearingDeg(lat1, lon1, lat2, lon2) {
    const p1 = rad(lat1), p2 = rad(lat2), dl = rad(lon2 - lon1);
    const x = Math.sin(dl) * Math.cos(p2);
    const y = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
    return mod360(deg(Math.atan2(x, y)));
  }

  function windComponents(heading, windFrom, speed) {
    const rel = rad(windFrom - heading);
    return [speed * Math.cos(rel), speed * Math.sin(rel)];
  }

  function windToUv(speed, fromDeg) {
    return [-speed * Math.sin(rad(fromDeg)), -speed * Math.cos(rad(fromDeg))];
  }

  function uvToWind(u, v) {
    const s = Math.hypot(u, v);
    return s === 0 ? [0, 0] : [s, mod360(deg(Math.atan2(-u, -v)))];
  }

  const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  const compassPoint = (d) => COMPASS[Math.floor(mod360(d) / 22.5 + 0.5) % 16];

  // ---------- routes ----------
  function turnaroundIndex(wps) {
    const t = wps.findIndex((w) => w.turnaround);
    if (t >= 0) return t;
    let best = 0, bestD = -1;
    wps.forEach((w, i) => {
      const d = haversineKm(wps[0].lat, wps[0].lon, w.lat, w.lon);
      if (d > bestD) { bestD = d; best = i; }
    });
    return best;
  }

  function routeLegs(route) {
    const wps = route.waypoints;
    const turn = turnaroundIndex(wps);
    const raw = [];
    for (let i = 0; i < wps.length - 1; i++) raw.push(haversineKm(wps[i].lat, wps[i].lon, wps[i + 1].lat, wps[i + 1].lon));
    const scale = route.distance_km / (raw.reduce((a, b) => a + b, 0) || 1);
    const legs = [];
    let startKm = 0;
    for (let i = 0; i < wps.length - 1; i++) {
      const a = wps[i], b = wps[i + 1], km = raw[i] * scale;
      legs.push({
        from: a.name, to: b.name,
        bearing: bearingDeg(a.lat, a.lon, b.lat, b.lon),
        km, start_km: startKm,
        mid_lat: (a.lat + b.lat) / 2, mid_lon: (a.lon + b.lon) / 2,
        exposure: b.exposure || "highway",
        direction: i < turn ? "out" : "back",
      });
      startKm += km;
    }
    return legs;
  }

  // ---------- weather ----------
  const HOURLY_VARS = ["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "temperature_2m", "visibility"];

  function gridKey(lat, lon, grid) {
    const snap = (x) => (Math.round(Math.round(x / grid) * grid * 1e4) / 1e4).toFixed(4);
    return snap(lat) + "," + snap(lon);
  }

  function collectPoints(legsByRoute, grid) {
    const keys = new Set();
    Object.values(legsByRoute).forEach((legs) => legs.forEach((l) => keys.add(gridKey(l.mid_lat, l.mid_lon, grid))));
    return [...keys].sort();
  }

  function buildRequestUrl(points, startDate, endDate, cfg) {
    const q = new URLSearchParams({
      latitude: points.map((p) => p.split(",")[0]).join(","),
      longitude: points.map((p) => p.split(",")[1]).join(","),
      hourly: HOURLY_VARS.join(","),
      wind_speed_unit: "kmh",
      timezone: cfg.timezone,
      start_date: startDate,
      end_date: endDate,
    });
    return cfg.weather.api_url + "?" + q.toString().replace(/%2C/g, ",");
  }

  function parseResponse(points, payload) {
    const items = Array.isArray(payload) ? payload : [payload];
    if (items.length !== points.length) throw new Error(`expected ${points.length} locations, got ${items.length}`);
    const out = {};
    points.forEach((key, i) => {
      const h = items[i].hourly;
      out[key] = {
        time: h.time, wind: h.wind_speed_10m, dir: h.wind_direction_10m, gust: h.wind_gusts_10m,
        temp: h.temperature_2m, vis: h.visibility || h.time.map(() => null),
      };
    });
    return out;
  }

  async function fetchForecast(points, startDate, endDate, cfg) {
    const res = await fetch(buildRequestUrl(points, startDate, endDate, cfg));
    if (!res.ok) throw new Error("Open-Meteo error " + res.status);
    return parseResponse(points, await res.json());
  }

  // Naive local time helpers (Date objects used in UTC only).
  const pad = (n) => String(n).padStart(2, "0");
  function parseTime(day, hhmm) {
    const [y, m, d] = day.split("-").map(Number);
    const [hh, mm] = hhmm.split(":").map(Number);
    return new Date(Date.UTC(y, m - 1, d, hh, mm));
  }
  const fmtHour = (t) => `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())}T${pad(t.getUTCHours())}:00`;
  const fmtHM = (t) => `${pad(t.getUTCHours())}:${pad(t.getUTCMinutes())}`;

  const lerp = (a, b, f) => (a == null ? b : b == null ? a : a + (b - a) * f);

  function sample(series, when) {
    if (!series._index) {
      Object.defineProperty(series, "_index", { value: new Map(series.time.map((t, i) => [t, i])), enumerable: false });
    }
    const frac = (when.getUTCMinutes() * 60 + when.getUTCSeconds()) / 3600;
    const i0 = series._index.get(fmtHour(when));
    if (i0 === undefined) return null;
    const i1 = frac > 0 && i0 + 1 < series.time.length ? i0 + 1 : i0;
    if (series.wind[i0] == null || series.dir[i0] == null) return null;
    const [u0, v0] = windToUv(series.wind[i0], series.dir[i0]);
    const [u1, v1] = series.wind[i1] != null && series.dir[i1] != null ? windToUv(series.wind[i1], series.dir[i1]) : [u0, v0];
    const [speed, dir] = uvToWind(lerp(u0, u1, frac), lerp(v0, v1, frac));
    return {
      wind: speed, dir,
      gust: lerp(series.gust[i0], series.gust[i1], frac),
      temp: lerp(series.temp[i0], series.temp[i1], frac),
      vis: lerp(series.vis[i0], series.vis[i1], frac),
    };
  }

  function windowHours(day, window) {
    const start = parseTime(day, window[0]), end = parseTime(day, window[1]);
    const hours = [];
    let h = new Date(start.getTime());
    h.setUTCMinutes(0);
    while (h.getTime() <= end.getTime() + 59 * 60000) {
      hours.push(new Date(h.getTime()));
      h = new Date(h.getTime() + 3600000);
    }
    return hours;
  }

  function circularMeanDeg(dirs, weights) {
    weights = weights || dirs.map(() => 1);
    let x = 0, y = 0;
    dirs.forEach((d, i) => { x += weights[i] * Math.sin(rad(d)); y += weights[i] * Math.cos(rad(d)); });
    return mod360(deg(Math.atan2(x, y)));
  }

  // ---------- scoring ----------
  const STATUS_ORDER = { good: 0, caution: 1, unsafe: 2 };
  const NOTABLE_KMH = 5;
  const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
  const r1 = (x) => Math.round(x * 10) / 10;
  function wavg(values, weights) {
    const t = weights.reduce((a, b) => a + b, 0);
    return t ? values.reduce((s, v, i) => s + v * weights[i], 0) / t : 0;
  }

  function scoreRoute(route, legs, weather, day, window, cfg) {
    const th = cfg.thresholds, wt = cfg.weights, mult = cfg.exposure_multipliers;
    const grid = cfg.weather.grid_deg, speed = cfg.average_speed_kmh[route.type];
    const start = parseTime(day, window[0]);
    const lr = [];
    for (const leg of legs) {
      const when = new Date(start.getTime() + ((leg.start_km + leg.km / 2) / speed) * 3600000);
      const series = weather[gridKey(leg.mid_lat, leg.mid_lon, grid)];
      const s = series ? sample(series, when) : null;
      if (!s) {
        return { id: route.id, name: route.name, type: route.type, distance_km: route.distance_km, score: null,
          status: "no_data", reason: "No forecast available for this time yet.", flags: [], legs: [] };
      }
      const [head, cross] = windComponents(leg.bearing, s.dir, s.wind);
      const m = mult[leg.exposure] ?? 1.0;
      const gust = s.gust != null ? s.gust : s.wind;
      const penalty = Math.max(0, Math.abs(cross) - th.crosswind_free_kmh) * m * wt.crosswind
        + Math.max(0, gust - th.gust_penalty_kmh) * m * wt.gust
        + Math.max(0, s.wind - th.wind_caution_kmh) * wt.average_wind;
      lr.push({ from: leg.from, to: leg.to, direction: leg.direction, exposure: leg.exposure, km: r1(leg.km),
        bearing: Math.round(leg.bearing), time: fmtHM(when), wind: s.wind, wind_dir: s.dir, gust, temp: s.temp,
        vis: s.vis, head, cross, exposure_mult: m, penalty });
    }
    const kms = lr.map((l) => l.km);
    const basePenalty = wavg(lr.map((l) => l.penalty), kms);
    const out = lr.filter((l) => l.direction === "out"), back = lr.filter((l) => l.direction === "back");
    const headOut = wavg(out.map((l) => l.head), out.map((l) => l.km));
    const headBack = wavg(back.map((l) => l.head), back.map((l) => l.km));
    const pattern = clamp(((headOut - headBack) / 2) * wt.pattern_bonus, -wt.pattern_bonus_max, wt.pattern_bonus_max);

    const maxWind = Math.max(...lr.map((l) => l.wind));
    const maxGust = Math.max(...lr.map((l) => l.gust));
    const temps = lr.map((l) => l.temp).filter((t) => t != null);
    const viss = lr.map((l) => l.vis).filter((v) => v != null);
    const maxTemp = temps.length ? Math.max(...temps) : null;
    const minVis = viss.length ? Math.min(...viss) : null;
    const worst = lr.reduce((a, b) => (Math.abs(b.cross) * b.exposure_mult > Math.abs(a.cross) * a.exposure_mult ? b : a));

    const flags = [];
    let extra = 0;
    if (maxTemp != null && maxTemp > th.heat_c) { flags.push("heat"); extra += wt.heat_penalty; }
    if (minVis != null && minVis < th.dust_visibility_m) { flags.push("dust"); extra += wt.dust_penalty; }
    let status;
    if (maxWind > th.wind_skip_kmh || maxGust > th.gust_skip_kmh) { status = "unsafe"; flags.push("high_wind"); }
    else if (maxWind > th.wind_caution_kmh || Math.abs(worst.cross) > th.crosswind_caution_kmh ||
             maxGust > th.gust_penalty_kmh || flags.length) status = "caution";
    else status = "good";

    const result = {
      id: route.id, name: route.name, type: route.type, distance_km: route.distance_km,
      score: Math.round(clamp(100 - basePenalty + pattern - extra, 0, 100)), status, flags,
      head_out: r1(headOut), head_back: r1(headBack), max_wind: r1(maxWind), max_gust: r1(maxGust),
      max_cross: r1(Math.abs(worst.cross)), worst_cross_leg: `${worst.from} to ${worst.to}`,
      worst_cross_exposure: worst.exposure,
      max_temp: maxTemp == null ? null : r1(maxTemp), min_vis: minVis == null ? null : Math.round(minVis),
      legs: lr.map(({ penalty, exposure_mult, ...rest }) => {
        const o = {};
        for (const [k, v] of Object.entries(rest)) o[k] = typeof v === "number" && !Number.isInteger(v) ? r1(v) : v;
        return o;
      }),
    };
    result.reason = explain(result, cfg);
    return result;
  }

  // Round half up for display (Python side uses the same rule).
  const n0 = (x, digits = 0) => (Math.floor(x * 10 ** digits + 0.5) / 10 ** digits).toFixed(digits);
  const ht = (h) => (Math.abs(h) < NOTABLE_KMH ? "calm" : `${h > 0 ? "headwind" : "tailwind"} ~${n0(Math.abs(h))}`);

  function explain(r, cfg) {
    const th = cfg.thresholds, n = NOTABLE_KMH, parts = [];
    const ho = r.head_out, hb = r.head_back;
    if (ho >= n && hb <= -n) parts.push(`Headwind on the way out (~${n0(ho)} km/h), tailwind pushing you home.`);
    else if (ho <= -n && hb >= n) parts.push(`Tailwind out but headwind on the way home (~${n0(hb)} km/h) - a harder finish.`);
    else if (Math.max(Math.abs(ho), Math.abs(hb)) < n) parts.push("Little head- or tailwind either way.");
    else parts.push(`Mixed wind: ${ht(ho)} out, ${ht(hb)} back.`);

    const c = r.max_cross;
    const stretch = `${r.worst_cross_leg} (${r.worst_cross_exposure.replace("_", " ")})`;
    if (c > th.crosswind_caution_kmh) parts.push(`Strong crosswind ~${n0(c)} km/h on ${stretch}.`);
    else if (c > th.crosswind_free_kmh) parts.push(`Moderate crosswind, worst ~${n0(c)} km/h on ${stretch}.`);
    else parts.push("Crosswinds light.");

    const g = r.max_gust;
    if (g > th.gust_skip_kmh) parts.push(`Gusts to ${n0(g)} km/h - too strong.`);
    else if (g > th.gust_penalty_kmh) parts.push(`Gusts to ${n0(g)} km/h - stay alert.`);
    else parts.push(`Gusts up to ${n0(g)} km/h.`);
    if (r.flags.includes("heat")) parts.push(`Hot: up to ${n0(r.max_temp)}°C.`);
    if (r.flags.includes("dust")) parts.push(`Low visibility (dust, haze or fog) ~${n0(r.min_vis / 1000, 1)} km.`);
    return parts.join(" ");
  }

  function rank(results) {
    return [...results].sort((a, b) =>
      (a.score == null) - (b.score == null) ||
      (STATUS_ORDER[a.status] ?? 3) - (STATUS_ORDER[b.status] ?? 3) ||
      (b.score || 0) - (a.score || 0) ||
      a.distance_km - b.distance_km);
  }

  const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  function weekdayOf(day) { return parseTime(day, "00:00").getUTCDay(); }

  function daySettings(day, cfg) {
    const pyWeekday = (weekdayOf(day) + 6) % 7; // Python: Monday = 0
    for (const rd of Object.values(cfg.ride_days)) {
      if (rd.weekday === pyWeekday) return { ride_type: rd.ride_type, window: rd.window, club_day: true };
    }
    return { ride_type: cfg.other_days.ride_type, window: cfg.other_days.window, club_day: false };
  }

  function planDay(day, rideType, routes, legsByRoute, weather, cfg) {
    const window = daySettings(day, cfg).window;
    const scored = rank(routes.filter((r) => r.type === rideType)
      .map((r) => scoreRoute(r, legsByRoute[r.id], weather, day, window, cfg)));
    const usable = scored.filter((r) => r.score != null);
    const plan = {
      date: day, weekday: WEEKDAYS[weekdayOf(day)], ride_type: rideType, window, routes: scored,
      recommended: usable[0] || null,
      alternates: usable.slice(1, 1 + (cfg.alternates ?? 2)),
      hourly: usable.length ? hourlySummary(day, window, usable[0], legsByRoute, weather, cfg) : [],
    };
    const top = plan.recommended;
    if (!top) { plan.status = "no_data"; plan.advice = "No forecast for this date yet (Open-Meteo covers about 16 days)."; }
    else if (top.status !== "unsafe") { plan.status = top.status; plan.advice = ""; }
    else {
      const th = cfg.thresholds;
      let msg = `Wind is above the safe limit on every ${rideType} route (over ${th.wind_skip_kmh} km/h or gusts over ${th.gust_skip_kmh} km/h). Skip or ride short instead.`;
      if (rideType === "long") {
        const ok = rank(routes.filter((r) => r.type === "short")
          .map((r) => scoreRoute(r, legsByRoute[r.id], weather, day, window, cfg)))
          .filter((r) => r.status === "good" || r.status === "caution");
        if (ok.length) { msg += ` Best short option: ${ok[0].name} (score ${ok[0].score}).`; plan.short_fallback = ok[0]; }
      }
      plan.status = "unsafe"; plan.advice = msg;
    }
    if (top) {
      const legs = top.legs, kms = legs.map((l) => l.km);
      const dir = circularMeanDeg(legs.map((l) => l.wind_dir), legs.map((l) => l.km * l.wind));
      plan.summary = { wind_avg: r1(wavg(legs.map((l) => l.wind), kms)), wind_dir: Math.round(dir) % 360,
        wind_dir_compass: compassPoint(dir), gust_max: top.max_gust, temp_max: top.max_temp, vis_min: top.min_vis };
    } else plan.summary = null;
    return plan;
  }

  function hourlySummary(day, window, routeResult, legsByRoute, weather, cfg) {
    const grid = cfg.weather.grid_deg;
    const keys = [...new Set(legsByRoute[routeResult.id].map((l) => gridKey(l.mid_lat, l.mid_lon, grid)))].sort();
    const rows = [];
    for (const h of windowHours(day, window)) {
      const samples = keys.filter((k) => weather[k]).map((k) => sample(weather[k], h)).filter(Boolean);
      if (!samples.length) continue;
      const temps = samples.map((s) => s.temp).filter((t) => t != null);
      rows.push({
        time: fmtHM(h),
        wind: r1(samples.reduce((a, s) => a + s.wind, 0) / samples.length),
        gust: r1(Math.max(...samples.map((s) => s.gust || 0))),
        dir: Math.round(circularMeanDeg(samples.map((s) => s.dir), samples.map((s) => s.wind))),
        temp: temps.length ? r1(Math.max(...temps)) : null,
      });
    }
    return rows;
  }

  const api = {
    haversineKm, bearingDeg, windComponents, compassPoint, turnaroundIndex, routeLegs,
    gridKey, collectPoints, buildRequestUrl, parseResponse, fetchForecast, sample, windowHours,
    scoreRoute, explain, rank, daySettings, planDay,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Planner = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
