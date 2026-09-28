/* Page logic: picks a day, gets a plan (prebuilt or live), renders it. */
(function () {
  "use strict";
  const P = window.Planner;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const state = { cfg: null, routes: [], routeById: {}, legs: {}, forecast: null, live: {}, date: null, type: null, map: null };
  const STATUS_TEXT = { good: "Good to ride", caution: "Ride with care", unsafe: "Skip or ride short", no_data: "No forecast yet" };
  const FLAG_TEXT = { heat: "Heat", dust: "Low visibility", high_wind: "High wind" };
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  // ---------- dates (Qatar local) ----------
  function qatarNow() {
    return new Date(Date.now() + state.cfg.utc_offset_hours * 3600000); // read with getUTC*
  }
  const iso = (d) => d.toISOString().slice(0, 10);
  const addDays = (s, n) => { const d = new Date(s + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return iso(d); };
  function nice(s) {
    const d = new Date(s + "T00:00:00Z");
    return `${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
  }

  function nextClubDay(fromIso, weekday) {
    // weekday uses Python numbering (Mon=0) like config.json
    for (let i = 0; i < 8; i++) {
      const d = addDays(fromIso, i);
      const settings = P.daySettings(d, state.cfg);
      const py = (new Date(d + "T00:00:00Z").getUTCDay() + 6) % 7;
      if (settings.club_day && (weekday === undefined || py === weekday)) {
        if (i === 0) {
          // today only counts until the ride window ends
          const now = qatarNow();
          const [hh, mm] = settings.window[1].split(":").map(Number);
          if (now.getUTCHours() * 60 + now.getUTCMinutes() > hh * 60 + mm) continue;
        }
        return d;
      }
    }
    return fromIso;
  }

  // ---------- data ----------
  async function getJson(url) {
    const r = await fetch(url, { cache: "no-cache" });
    if (!r.ok) throw new Error(url + " " + r.status);
    return r.json();
  }

  function prebuilt(date, type) {
    const f = state.forecast;
    if (!f || !f.days) return null;
    const day = f.days.find((d) => d.date === date);
    return day ? day.plans[type] : null;
  }

  function prebuiltIsFresh() {
    const f = state.forecast;
    if (!f || !f.generated_at) return false;
    const ageH = (Date.now() - new Date(f.generated_at).getTime()) / 3600000;
    return ageH < state.cfg.live_refresh_after_hours;
  }

  async function livePlan(date, type) {
    if (!state.live[date]) {
      const points = P.collectPoints(state.legs, state.cfg.weather.grid_deg);
      state.live[date] = P.fetchForecast(points, date, date, state.cfg);
    }
    try {
      const wx = await state.live[date];
      return P.planDay(date, type, state.routes, state.legs, wx, state.cfg);
    } catch (e) {
      delete state.live[date];
      throw e;
    }
  }

  async function getPlan(date, type, forceLive) {
    const saved = prebuilt(date, type);
    if (saved && prebuiltIsFresh() && !forceLive) {
      return { plan: saved, source: `Forecast from ${fmtStamp(state.forecast.generated_at)}.`, canRefresh: true };
    }
    try {
      const plan = await livePlan(date, type);
      return { plan, source: "Live forecast from Open-Meteo, just now." };
    } catch (e) {
      if (saved) return { plan: saved, source: `Couldn't refresh (offline?). Showing forecast from ${fmtStamp(state.forecast.generated_at)}.` };
      throw e;
    }
  }

  function fmtStamp(s) {
    const d = new Date(s);
    const q = new Date(d.getTime() + state.cfg.utc_offset_hours * 3600000);
    return `${nice(iso(q))}, ${String(q.getUTCHours()).padStart(2, "0")}:${String(q.getUTCMinutes()).padStart(2, "0")} Qatar time`;
  }

  // ---------- render ----------
  const kmh = (x) => (x == null ? "–" : `${Math.round(x)} km/h`);

  function scoreBadge(r) {
    return `<div class="score ${r.status}">${r.score ?? "–"}<small>${esc(STATUS_TEXT[r.status] ? r.status.replace("_", " ") : "")}</small></div>`;
  }

  function flags(r) {
    if (!r.flags || !r.flags.length) return "";
    return `<div class="flags">${r.flags.map((f) => `<span class="flag ${f}">${FLAG_TEXT[f] || f}</span>`).join("")}</div>`;
  }

  function routeButtons(r) {
    const route = state.routeById[r.id];
    return `<div class="btns">
      <a class="btn primary" href="${esc(route.maps_url)}" target="_blank" rel="noopener">Open in Google Maps</a>
      <a class="btn" href="${esc(route.gpx)}" download="${esc(route.id)}.gpx">Download GPX</a>
    </div>`;
  }

  function renderRoute(r, label) {
    const route = state.routeById[r.id];
    return `<div class="route-top">
        <div>
          <div class="tag">${esc(label)}</div>
          <h3>${esc(r.name)}</h3>
          <div class="meta">${r.distance_km} km round trip &middot; out ${esc(outDesc(r))}</div>
        </div>
        ${scoreBadge(r)}
      </div>
      <p class="reason">${esc(r.reason)}</p>
      ${flags(r)}
      ${route.exposure_notes ? `<p class="notes">${esc(route.exposure_notes)}</p>` : ""}
      ${routeButtons(r)}`;
  }

  function outDesc(r) {
    const route = state.routeById[r.id];
    const turn = route.waypoints[P.turnaroundIndex(route.waypoints)];
    return `to ${turn.name}`;
  }

  function render(plan, source) {
    const cfg = state.cfg;
    $("loading").hidden = true;
    $("error").hidden = true;
    $("content").hidden = false;
    $("source").innerHTML = source;

    const banner = $("banner");
    banner.className = `card banner ${plan.status}`;
    const rec = plan.recommended;
    banner.innerHTML = `<strong>${STATUS_TEXT[plan.status] || ""}</strong>${esc(plan.advice || (rec ? `Recommended: ${rec.name}.` : ""))}`;

    $("day-title").textContent = `${plan.weekday} ${nice(plan.date).slice(4)}`;
    $("day-sub").textContent = `${plan.ride_type === "long" ? "Long ride" : "Short ride"} · ${plan.window[0]}–${plan.window[1]}`;

    const s = plan.summary;
    $("s-wind").textContent = s ? kmh(s.wind_avg) : "–";
    $("s-dir").innerHTML = s ? `${s.wind_dir_compass} <small class="muted">${s.wind_dir}°</small>` : "–";
    $("s-gust").textContent = s ? kmh(s.gust_max) : "–";
    $("s-temp").textContent = s && s.temp_max != null ? `${Math.round(s.temp_max)}°C` : "–";
    $("s-vis").textContent = s && s.vis_min != null ? (s.vis_min >= 10000 ? "10+ km" : `${(s.vis_min / 1000).toFixed(1)} km`) : "–";
    // Arrow points where the wind blows TO.
    const toDeg = s ? (s.wind_dir + 180) % 360 : 0;
    $("arrow-rot").setAttribute("transform", `rotate(${toDeg})`);
    $("wind-arrow").setAttribute("aria-label", s ? `Wind from ${s.wind_dir_compass}` : "No wind data");

    renderChart(plan.hourly || [], plan.window);

    $("rec").innerHTML = rec ? renderRoute(rec, "Recommended") : `<p class="muted">No route could be scored for this day.</p>`;
    $("alts").innerHTML = (plan.alternates || []).map((a, i) => `<section class="card route alt">${renderRoute(a, `Alternate ${i + 1}`)}</section>`).join("")
      + (plan.short_fallback ? `<section class="card route alt">${renderRoute(plan.short_fallback, "Short ride instead")}</section>` : "")
      || `<p class="muted">No alternates.</p>`;

    $("all").innerHTML = `<table><thead><tr><th>Route</th><th class="num">km</th><th class="num">Score</th></tr></thead><tbody>${
      (plan.routes || []).map((r) => `<tr><td><span class="dot ${r.status}"></span>${esc(r.name)}<div class="muted small">${esc(r.reason)}</div></td><td class="num">${r.distance_km}</td><td class="num">${r.score ?? "–"}</td></tr>`).join("")
    }</tbody></table>`;

    renderMap(rec ? state.routeById[rec.id] : null, s);
    renderWhatsApp(plan);
    document.querySelectorAll(".th").forEach((el) => { el.textContent = cfg.thresholds[el.dataset.th]; });
  }

  function renderChart(rows, window) {
    const el = $("chart");
    if (!rows.length) { el.innerHTML = `<p class="muted small">No hourly data.</p>`; return; }
    const th = state.cfg.thresholds;
    const W = 340, H = 170, top = 18, bottom = 44, left = 6, right = 6;
    const maxV = Math.max(30, ...rows.map((r) => r.gust || 0), ...rows.map((r) => r.wind)) * 1.1;
    const n = rows.length, slot = (W - left - right) / n, bw = Math.min(28, slot * 0.55);
    const y = (v) => top + (H - top - bottom) * (1 - v / maxV);
    const x = (i) => left + slot * (i + 0.5);
    const [ws, we] = window.map((t) => { const [h, m] = t.split(":").map(Number); return h + m / 60; });
    const hourOf = (t) => Number(t.slice(0, 2));
    const winX0 = left + slot * (ws - hourOf(rows[0].time)), winX1 = left + slot * (we - hourOf(rows[0].time) + 1) - slot;
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Hourly wind and gusts">`;
    svg += `<rect class="inwin" x="${winX0}" y="${top - 12}" width="${Math.max(0, winX1 - winX0 + slot / 2)}" height="${H - bottom - top + 12}"/>`;
    const cy = y(th.wind_caution_kmh);
    svg += `<line class="limit" x1="${left}" x2="${W - right}" y1="${cy}" y2="${cy}"/>`;
    rows.forEach((r, i) => {
      const cls = r.wind > th.wind_skip_kmh ? "bar bad" : r.wind > th.wind_caution_kmh ? "bar hot" : "bar";
      svg += `<rect class="${cls}" x="${x(i) - bw / 2}" y="${y(r.wind)}" width="${bw}" height="${Math.max(1, y(0) - y(r.wind))}" rx="3"/>`;
      svg += `<text class="val" x="${x(i)}" y="${y(r.wind) - 4}">${Math.round(r.wind)}</text>`;
      svg += `<text class="lbl" x="${x(i)}" y="${H - bottom + 14}">${r.time}</text>`;
      svg += `<g transform="translate(${x(i)} ${H - 12}) rotate(${(r.dir + 180) % 360})"><path class="dir" d="M0 -8 L5 4 L0 1 L-5 4 Z"/></g>`;
    });
    const pts = rows.map((r, i) => `${x(i)},${y(r.gust || 0)}`).join(" ");
    svg += `<polyline class="gust" points="${pts}"/>`;
    rows.forEach((r, i) => { svg += `<circle class="gust-dot" cx="${x(i)}" cy="${y(r.gust || 0)}" r="2.5"/>`; });
    svg += `</svg><div class="legend"><span><i style="background:var(--bar)"></i>Wind km/h</span><span><i style="background:var(--gust)"></i>Gusts</span><span><i style="background:var(--caution)"></i>Caution line ${th.wind_caution_kmh} km/h</span><span>Arrows: where the wind blows</span></div>`;
    el.innerHTML = svg;
  }

  // ---------- map ----------
  function windBadge(s) {
    if (!s) return "";
    return `<svg viewBox="-15 -15 30 30"><g transform="rotate(${(s.wind_dir + 180) % 360})"><path d="M0 -12 L7 5 L1 2 L1 12 L-1 12 L-1 2 L-7 5 Z"/></g></svg>${esc(s.wind_dir_compass)} ${Math.round(s.wind_avg)} km/h`;
  }

  function renderMap(route, s) {
    $("map-wind").innerHTML = windBadge(s);
    $("map-wind").hidden = !s;
    const holder = $("map");
    if (!route) { holder.innerHTML = ""; return; }
    if (route.embed_url) {
      if (state.map) { state.map.remove(); state.map = null; }
      holder.innerHTML = `<iframe loading="lazy" allowfullscreen referrerpolicy="no-referrer-when-downgrade" title="Google map of ${esc(route.name)}" src="${esc(route.embed_url)}"></iframe>`;
      $("map-note").textContent = "Google Maps directions through the route's key waypoints.";
      return;
    }
    $("map-note").textContent = "Straight lines between waypoints (approximate). Tap “Open in Google Maps” for turn-by-turn.";
    loadLeaflet().then((L) => {
      if (state.map) { state.map.remove(); state.map = null; }
      holder.innerHTML = "";
      const map = L.map(holder, { scrollWheelZoom: false, attributionControl: true });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(map);
      const latlngs = route.waypoints.map((w) => [w.lat, w.lon]);
      const turn = P.turnaroundIndex(route.waypoints);
      const brand = getComputedStyle(document.documentElement).getPropertyValue("--brand").trim() || "#0f766e";
      L.polyline(latlngs.slice(0, turn + 1), { color: brand, weight: 5, opacity: 0.9 }).addTo(map).bindTooltip("Way out");
      L.polyline(latlngs.slice(turn), { color: brand, weight: 5, opacity: 0.55, dashArray: "8 8" }).addTo(map).bindTooltip("Way back");
      route.waypoints.forEach((w, i) => {
        if (i === 0 || i === route.waypoints.length - 1 || i === turn) return;
        L.circleMarker([w.lat, w.lon], { radius: 4, color: brand, weight: 2, fillColor: "#fff", fillOpacity: 1 }).addTo(map).bindTooltip(esc(w.name));
      });
      const start = route.waypoints[0], end = route.waypoints[route.waypoints.length - 1], far = route.waypoints[turn];
      const sameEnd = start.lat === end.lat && start.lon === end.lon;
      L.circleMarker([start.lat, start.lon], { radius: 9, color: "#fff", weight: 3, fillColor: "#15803d", fillOpacity: 1 })
        .addTo(map).bindTooltip(sameEnd ? "Start / Finish" : "Start", { permanent: true, direction: "right" })
        .bindPopup(esc(start.name));
      if (!sameEnd) {
        L.circleMarker([end.lat, end.lon], { radius: 9, color: "#fff", weight: 3, fillColor: "#b91c1c", fillOpacity: 1 })
          .addTo(map).bindTooltip("Finish", { permanent: true, direction: "right" }).bindPopup(esc(end.name));
      }
      L.circleMarker([far.lat, far.lon], { radius: 8, color: "#fff", weight: 3, fillColor: "#b45309", fillOpacity: 1 })
        .addTo(map).bindTooltip("Turnaround", { permanent: true, direction: "left" }).bindPopup(esc(far.name));
      map.fitBounds(L.latLngBounds(latlngs), { padding: [95, 30] });
      state.map = map;
    }).catch(() => {
      holder.innerHTML = `<p class="muted small" style="padding:16px">Map couldn't load. Use “Open in Google Maps” above.</p>`;
    });
  }

  let leafletPromise = null;
  function loadLeaflet() {
    if (window.L) return Promise.resolve(window.L);
    if (leafletPromise) return leafletPromise;
    leafletPromise = new Promise((resolve, reject) => {
      const css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css";
      document.head.appendChild(css);
      const js = document.createElement("script");
      js.src = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js";
      js.onload = () => resolve(window.L);
      js.onerror = () => { leafletPromise = null; reject(new Error("leaflet")); };
      document.head.appendChild(js);
    });
    return leafletPromise;
  }

  // ---------- WhatsApp ----------
  function pageLink(plan) {
    const u = new URL(location.href);
    u.search = `?date=${plan.date}&type=${plan.ride_type}`;
    u.hash = "";
    return u.toString();
  }

  function renderWhatsApp(plan) {
    const s = plan.summary, rec = plan.recommended;
    const club = state.cfg.club_name ? `${state.cfg.club_name} · ` : "";
    const lines = [`🏍️ *${club}${plan.weekday} ${nice(plan.date).slice(4)} – ${plan.ride_type === "long" ? "Long" : "Short"} ride* (${plan.window[0]}–${plan.window[1]})`];
    if (s) {
      let w = `💨 Wind ${Math.round(s.wind_avg)} km/h from ${s.wind_dir_compass}, gusts to ${Math.round(s.gust_max)} km/h`;
      if (s.temp_max != null) w += `, up to ${Math.round(s.temp_max)}°C`;
      lines.push(w);
    }
    if (plan.status === "unsafe") lines.push(`⚠️ ${plan.advice}`);
    if (rec) {
      const icon = rec.status === "good" ? "✅" : rec.status === "caution" ? "🟠" : "⛔";
      lines.push("", `${icon} *${rec.name}* (${rec.distance_km} km, score ${rec.score})`, rec.reason,
        `🗺️ ${state.routeById[rec.id].maps_url}`);
    }
    if (plan.alternates && plan.alternates.length) {
      lines.push("", "Alternates: " + plan.alternates.map((a, i) => `${i + 2}) ${a.name} (${a.score})`).join("  "));
    }
    lines.push("", `Details: ${pageLink(plan)}`);
    const text = lines.join("\n");
    $("wa-text").value = text;
    $("wa-share").href = "https://wa.me/?text=" + encodeURIComponent(text);
  }

  // ---------- controls ----------
  function setType(type) {
    state.type = type;
    document.querySelectorAll(".seg button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.type === type)));
  }

  function renderQuick() {
    const today = iso(qatarNow());
    const chips = [
      ["Next Tuesday", nextClubDay(today, 1), "short"],
      ["Next Saturday", nextClubDay(today, 5), "long"],
      ["Tomorrow", addDays(today, 1), null],
    ].filter((c, i, all) => all.findIndex((o) => o[1] === c[1]) === i);
    $("quick").innerHTML = chips.map(([label, d, t]) =>
      `<button type="button" class="chip" data-date="${d}" data-type="${t || ""}" aria-pressed="${d === state.date && (!t || t === state.type)}">${label} <span class="muted">${nice(d).slice(4)}</span></button>`).join("");
  }

  async function update(opts = {}) {
    const { forceLive = false, pushUrl = true } = opts;
    $("date").value = state.date;
    setType(state.type);
    renderQuick();
    if (pushUrl) history.replaceState(null, "", `?date=${state.date}&type=${state.type}`);
    $("loading").hidden = false;
    try {
      const { plan, source, canRefresh } = await getPlan(state.date, state.type, forceLive);
      const extra = canRefresh ? ` <button type="button" id="refresh">Refresh live</button>` : "";
      render(plan, esc(source) + extra);
      const btn = document.getElementById("refresh");
      if (btn) btn.onclick = () => update({ forceLive: true });
    } catch (e) {
      $("loading").hidden = true;
      $("content").hidden = true;
      $("error").hidden = false;
      $("error").textContent = "Couldn't get the forecast. Check your connection and try again. (" + e.message + ")";
    }
  }

  async function init() {
    try {
      const [cfg, routes] = await Promise.all([getJson("data/config.json"), getJson("data/routes.json")]);
      state.cfg = cfg;
      if (cfg.club_name) {
        document.title = `${cfg.club_name} Ride Check`;
        $("club-title").textContent = `${cfg.club_name} Ride Check`;
      }
      state.routes = routes;
      routes.forEach((r) => { state.routeById[r.id] = r; state.legs[r.id] = P.routeLegs(r); });
    } catch (e) {
      $("loading").textContent = "Site data missing. Run: python -m planner.build";
      return;
    }
    try { state.forecast = await getJson("data/forecast.json"); } catch (e) { state.forecast = null; }
    if (state.forecast && state.forecast.generated_at) $("generated").textContent = `Last automatic update: ${fmtStamp(state.forecast.generated_at)}.`;

    const today = iso(qatarNow());
    const maxDay = addDays(today, state.cfg.weather.max_forecast_days - 1);
    $("date").min = today;
    $("date").max = maxDay;

    const params = new URLSearchParams(location.search);
    const pDate = params.get("date");
    state.date = pDate && /^\d{4}-\d{2}-\d{2}$/.test(pDate) && pDate >= today && pDate <= maxDay ? pDate : nextClubDay(today);
    const pType = params.get("type");
    state.type = pType === "short" || pType === "long" ? pType : P.daySettings(state.date, state.cfg).ride_type;

    $("date").addEventListener("change", () => {
      if (!$("date").value) return;
      state.date = $("date").value;
      state.type = P.daySettings(state.date, state.cfg).ride_type;
      update();
    });
    document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => { state.type = b.dataset.type; update(); }));
    $("quick").addEventListener("click", (ev) => {
      const chip = ev.target.closest(".chip");
      if (!chip) return;
      state.date = chip.dataset.date;
      state.type = chip.dataset.type || P.daySettings(state.date, state.cfg).ride_type;
      update();
    });
    $("copy").addEventListener("click", async () => {
      const t = $("wa-text");
      try { await navigator.clipboard.writeText(t.value); } catch (e) { t.select(); document.execCommand("copy"); }
      $("copy").textContent = "Copied ✓";
      setTimeout(() => { $("copy").textContent = "Copy text"; }, 1800);
    });
    update();
  }

  init();
})();
