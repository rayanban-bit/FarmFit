"""Generate data/demo_parcels.geojson: ILLUSTRATIVE plot geometry placed in Qatari farming districts.

These polygons are invented shapes in local metres anchored at approximate district locations. They are
NOT cadastral boundaries and carry no ownership information. Replace via the cadastre adapter when a
real parcel service is available.
"""
import json
import math
from pathlib import Path

R = 6_371_008.8

PLOTS = [
    ("DEMO-01", "Demo plot 01", "Al Shahaniya (approx.)", 51.2100, 25.3900, [(0, 0), (102, 4), (98, 52), (-2, 48)]),
    ("DEMO-02", "Demo plot 02", "Al Shahaniya (approx.)", 51.2138, 25.3922, [(0, 0), (110, -6), (135, 45), (60, 90), (-8, 55)]),
    ("DEMO-03", "Demo plot 03 (L-shaped)", "Al Shahaniya (approx.)", 51.2068, 25.3936, [(0, 0), (160, 0), (160, 45), (60, 45), (60, 120), (0, 120)]),
    ("DEMO-04", "Demo plot 04", "Al Shahaniya (approx.)", 51.2105, 25.3862, [(0, 0), (200, 0), (190, 110), (10, 95)]),
    ("DEMO-05", "Demo plot 05", "Al Khor hinterland (approx.)", 51.5000, 25.7000, [(0, 0), (60, 0), (58, 52), (2, 50)]),
    ("DEMO-06", "Demo plot 06", "Al Shamal (approx.)", 51.1800, 26.0000, [(0, 0), (190, -10), (240, 70), (190, 150), (20, 160), (-20, 70)]),
]


def to_lonlat(lon0, lat0, x, y):
    lat = lat0 + math.degrees(y / R)
    lon = lon0 + math.degrees(x / (R * math.cos(math.radians(lat0))))
    return [round(lon, 7), round(lat, 7)]


def main():
    feats = []
    for pid, name, district, lon0, lat0, pts in PLOTS:
        ring = [to_lonlat(lon0, lat0, x, y) for x, y in pts]
        ring.append(ring[0])
        feats.append({"type": "Feature", "properties": {"id": pid, "name": name, "district": district,
                                                        "source": "DEMO - illustrative geometry, not cadastral"},
                      "geometry": {"type": "Polygon", "coordinates": [ring]}})
    out = Path(__file__).resolve().parents[2] / "data" / "demo_parcels.geojson"
    out.write_text(json.dumps({"type": "FeatureCollection", "name": "farmfit demo parcels", "features": feats}, indent=1), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
