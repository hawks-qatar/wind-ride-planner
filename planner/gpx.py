"""GPX 1.1 export so riders can load routes into GPS units and bike nav apps."""
from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr


def route_to_gpx(route: dict) -> str:
    name = escape(route["name"])
    desc = escape(f"{route['type'].title()} ride, about {route['distance_km']} km round trip. "
                  "Waypoints are approximate - verify before riding.")
    rtepts, trkpts = [], []
    for w in route["waypoints"]:
        lat, lon = quoteattr(f"{w['lat']:.6f}"), quoteattr(f"{w['lon']:.6f}")
        rtepts.append(f"    <rtept lat={lat} lon={lon}><name>{escape(w['name'])}</name></rtept>")
        trkpts.append(f"      <trkpt lat={lat} lon={lon}/>")
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="Wind Ride Planner" xmlns="http://www.topografix.com/GPX/1/1">',
        f"  <metadata><name>{name}</name><desc>{desc}</desc></metadata>",
        "  <rte>",
        f"    <name>{name}</name>",
        *rtepts,
        "  </rte>",
        "  <trk>",
        f"    <name>{name}</name>",
        "    <trkseg>",
        *trkpts,
        "    </trkseg>",
        "  </trk>",
        "</gpx>",
        "",
    ])
