# HAWKS Qatar – Wind Ride Planner

A small web tool for the **HAWKS Qatar** motorcycle club. It checks the wind for the
Tuesday (short) and Saturday (long) rides and recommends the route that
avoids the worst of it, with two alternates, a map, an "Open in Google
Maps" button, a GPX download and a WhatsApp-ready summary.

**Live site: <https://hawks-qatar.github.io/wind-ride-planner/>**

Club members just open the public link on their phone. No account or app is
needed.

> **⚠️ The route waypoints in `routes.json` are approximate suggestions.**
> Check every route on a map (road names, turns, that roads connect,
> closures, private or industrial areas) and fix the coordinates before the
> site is shared with the club.

---

## What it does

| | |
|---|---|
| **Days** | Tuesday = short ride (60–120 km), Saturday = long ride (200–350 km). Any other day can be checked too. |
| **Ride window** | Saturday 08:00–12:00 and Tuesday 20:00–23:00 Qatar time, matching the club calendar (set in `config.json`). |
| **Weather** | [Open-Meteo](https://open-meteo.com/) (free, no key): hourly wind speed, direction, gusts, temperature, visibility. |
| **Where** | Wind is sampled all along every route (about 36 points on an ~11 km grid), not just Doha, so Al Shamal, Dukhan and Mesaieed are each looked up separately. |
| **Output** | Recommended route and 2 alternates with plain-English reasons, wind arrow, hourly chart, map, Google Maps link, GPX, WhatsApp text. |
| **Hosting** | GitHub Pages (free), rebuilt by GitHub Actions every Tue and Sat at 06:00 Qatar time. |

## How the wind score works (for presenting to the club)

Every route is split into stretches between waypoints. For each stretch we know
**which way we're riding** (the compass bearing) and **when we'll be there**
(riding at a steady average speed from the start of the ride window). We look
up the forecast wind for that place and time, then split it into two parts:

* **Headwind / tailwind**: the part of the wind blowing along the road. It costs
  fuel and energy but is not dangerous.
* **Crosswind**: the part blowing across the road. This pushes the bike
  sideways and is the main safety concern.

Then each route starts at **100 points** and:

1. **Loses points for crosswind** above 10 km/h. It loses **more** on open desert
   (×1.3), coast (×1.4) and causeways (×1.6), where there is nothing to block
   the wind, and less in town (×0.6).
2. **Loses points for gusts** above 40 km/h.
3. **Loses points for strong average wind** above 25 km/h.
4. **Gains points for "headwind out, tailwind home"**: you fight the wind while
   fresh and get pushed home when tired. The opposite (easy out, hard fight
   home) *loses* points.
5. **Loses points for heat** above 38 °C and **low visibility** (dust, haze or
   fog) under 5 km.

The safest-scoring route is recommended. Any route with wind over **35 km/h** or
gusts over **55 km/h** is marked **unsafe**, and the page says **"Skip or ride
short instead"**. On a Saturday it also suggests the best short route. Every
number above can be changed in `config.json`.

The waypoints are sparse, so the wind a rider actually meets will differ. Treat
the score as a guide, not a guarantee.

## Project layout

```
config.json            all settings and thresholds (edit me)
routes.json            the route library (edit me)
planner/               Python: builds the site data
  geo.py               bearings, head/crosswind maths
  routes.py            route loading/validation, legs, turnaround
  weather.py           Open-Meteo fetch + time interpolation
  scoring.py           score, status, reasons, recommendation
  gmaps.py             Google Maps directions/embed URLs, waypoint thinning
  gpx.py               GPX export
  build.py             CLI: writes site/data/*.json and site/gpx/*.gpx
site/                  the static web page
  index.html, style.css, app.js
  planner.js           browser copy of the scoring (for "check any day")
tests/                 pytest suite (incl. Python ↔ JavaScript parity)
.github/workflows/deploy.yml   scheduled build + GitHub Pages deploy
```

## Run it locally

Needs Python 3.10+ (and Node only if you want to run the JS parity tests).
Everything installs into a local `.venv`; nothing is installed globally.

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m planner.build --serve
```

**macOS / Linux:**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m planner.build --serve
```

Then open <http://localhost:8000>. The build prints a one-line recommendation
per day in the terminal as well.

Useful options:

* `--days 10`: prebuild more days (default 7).
* `--save-weather wx.json` / `--weather-file wx.json`: save a forecast and rebuild offline from it.
* `--port 8080`: use a different preview port.

## "Check any day" mode

The page has a date picker, quick buttons (next Tuesday, next Saturday,
tomorrow) and a Short/Long switch. Links keep the choice (`?date=2026-10-03&type=long`),
so a shared link opens the same day.

* The scheduled build **prebuilds the next 7 days**.
* For other dates (up to Open-Meteo's 16-day limit), or when the saved forecast
  is more than 6 hours old (`live_refresh_after_hours`), the page **fetches Open-Meteo
  directly in the browser** and runs the same scoring in `site/planner.js`.
* If the live fetch fails, the page falls back to the saved forecast and says so.

`tests/test_js_parity.py` checks that the browser and Python versions give the
same results. If you change the scoring, change both files and run the tests.

## Editing routes (`routes.json`)

Each route looks like this:

```json
{
  "id": "simaisma-coast",
  "name": "Simaisma Coastal Run",
  "type": "short",
  "distance_km": 72,
  "exposure_notes": "Shown on the page under the reason.",
  "waypoints": [
    {"name": "Doha Corniche (Sheraton Park)", "lat": 25.3183, "lon": 51.5290},
    {"name": "Lusail Boulevard", "lat": 25.4000, "lon": 51.5150, "exposure": "urban"},
    {"name": "Simaisma Beach", "lat": 25.5750, "lon": 51.4850, "exposure": "coastal", "turnaround": true},
    {"name": "Doha Corniche (Sheraton Park)", "lat": 25.3183, "lon": 51.5290, "exposure": "urban"}
  ]
}
```

* **id**: unique, lowercase, dashes (used for the GPX file name).
* **type**: `short` or `long`.
* **distance_km**: the real road distance of the whole loop. Measure it in Google Maps.
* **waypoints**: in riding order, starting and ending at the meeting point (Mondrian Doha).
  * **exposure**: describes the stretch *from the previous waypoint to this one*:
    `urban`, `highway`, `open_desert`, `coastal` or `causeway`.
  * **turnaround**: `true` on the point where "the way out" ends. If it's missing,
    the point farthest from the start is used.
  * **key**: `true` on points that force Google Maps onto the right road. They
    are always kept when the link is trimmed to Google's waypoint limit (8).
* To get coordinates: long-press a spot in Google Maps and copy the `lat, lon` it shows.
* Add enough waypoints that the route can't be "shortcut" onto another road.
  Leaflet draws straight lines between them.

After editing, run `python -m pytest -q`. The tests check the file (valid JSON,
coordinates inside Qatar, sensible distances, round trips).

## Changing thresholds (`config.json`)

| Setting | Default | Meaning |
|---|---|---|
| `club_name` | `HAWKS Qatar` | Shown in the page header, WhatsApp text and GPX files |
| `ride_days.*.window` | Tue `20:00`–`23:00`, Sat `08:00`–`12:00` | Ride window (`other_days` for the rest: `08:00`–`12:00`) |
| `ride_days.*.ride_type` | Tue `short`, Sat `long` | Which route list to use |
| `average_speed_kmh` | 70 / 75 | Used to estimate when you reach each stretch (include stops) |
| `thresholds.wind_caution_kmh` | 25 | Average wind above this costs points and triggers "caution" |
| `thresholds.wind_skip_kmh` | 35 | Above this: unsafe, "skip or ride short" |
| `thresholds.gust_penalty_kmh` | 40 | Gusts above this cost points |
| `thresholds.gust_skip_kmh` | 55 | Gusts above this: unsafe |
| `thresholds.crosswind_free_kmh` | 10 | Crosswind below this is ignored |
| `thresholds.crosswind_caution_kmh` | 20 | Crosswind above this triggers "caution" |
| `thresholds.heat_c` | 38 | Heat flag |
| `thresholds.dust_visibility_m` | 5000 | Low-visibility flag (metres) |
| `weights.*` | | Points lost per km/h over each limit, pattern bonus, heat/dust penalties |
| `exposure_multipliers.*` | | How much worse crosswind/gusts are on each kind of road |
| `google_maps.max_waypoints` | 8 | Waypoints kept in Google Maps links |

## Google Maps

### "Open in Google Maps" button (no key needed)

Uses Google's universal directions link
(`https://www.google.com/maps/dir/?api=1&origin=…&destination=…&waypoints=…&travelmode=driving`),
which opens the Google Maps app on phones. Long routes are trimmed to 8 waypoints:
the turnaround and `key` points are kept, and the rest are spread evenly along the route.

### Embedded map (optional key)

If a Google Maps key is configured, the page shows a **Google Maps Embed
(directions mode)** of the recommended route. Without a key, it automatically
uses a **Leaflet + OpenStreetMap** map that draws the route, the start/finish
and turnaround markers, and a wind arrow. The page works either way.

#### Create and lock down a key

The key ends up inside the public web page, so **anyone can see it**. That is
normal for the Embed API, but you must restrict it so only your site can use it.

1. Go to <https://console.cloud.google.com/> and sign in.
2. **Create a project** (top bar → project picker → *New project*), e.g. `club-ride-planner`.
3. Google Maps Platform needs a **billing account** linked to the project
   (*Billing* → link or create one). Maps Embed API requests are currently
   free with no usage limit, so a club site should cost nothing. Check
   <https://developers.google.com/maps/billing-and-pricing/pricing> to confirm, and
   set a **budget alert** (*Billing → Budgets & alerts*, e.g. $1) for peace of mind.
4. *APIs & Services → Library* → search **"Maps Embed API"** → **Enable**.
5. *APIs & Services → Credentials* → **Create credentials → API key**. Copy it.
6. Click the new key to edit it:
   * **Application restrictions → Websites (HTTP referrers)**, add:
     * `https://hawks-qatar.github.io/wind-ride-planner/*`
     * `http://localhost:8000/*` (only if you want the Google map in local previews)
   * **API restrictions → Restrict key →** tick only **Maps Embed API**.
   * **Save.** (Changes can take a few minutes to apply.)

#### Use the key

* **Locally:** copy `.env.example` to `.env` and fill in `GOOGLE_MAPS_EMBED_KEY=...`
  (`.env` is git-ignored), or set the environment variable before building.
* **On GitHub:** *Settings → Secrets and variables → Actions → New repository secret*,
  name `GOOGLE_MAPS_EMBED_KEY`. (A repository *variable* with the same name also works.)

Never commit the key to the repository.

## Deploying (GitHub Pages)

1. Merge the pull request into `main`.
2. *Settings → Pages → Build and deployment → Source:* **GitHub Actions**.
3. (Optional) add the `GOOGLE_MAPS_EMBED_KEY` secret as above.
4. *Actions → Build and deploy → Run workflow* to publish the first time.
5. The site appears at **<https://hawks-qatar.github.io/wind-ride-planner/>**.

After that the workflow runs on its own **every Tuesday and Saturday at 03:00 UTC
(06:00 Qatar)**. Pull requests run the tests only; they don't deploy.

Notes:

* GitHub may start scheduled runs a few minutes late at busy times.
* GitHub **pauses scheduled workflows after 60 days with no repository activity**.
  If that happens, re-enable it from the Actions tab (or push any small commit).
* The page also refreshes the forecast live in the browser, so it stays current
  between scheduled builds.

## Tests

```bash
python -m pytest -q
```

They cover:

* bearings and head/tail/crosswind components (including wrap-around at north)
* the Google Maps URL builder (waypoint limit, order, key points, percent-encoding)
* route file validation and GPX output
* the scoring rules (headwind-out preference, crosswind and exposure penalties, gust/wind limits, heat and visibility flags, "skip or ride short")
* Python and JavaScript giving the same results (skipped if Node isn't installed)

## Credits

Weather data by [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0). Map tiles ©
[OpenStreetMap](https://www.openstreetmap.org/copyright) contributors.
