"""Coverage geometry: swath corridor and holiday (gap) detection.

Same projection approach as survey-grid: work in a transverse-Mercator frame
centred on the data (true headings, unit scale), buffer each track segment to
its local swath width, union into a coverage polygon, and — when a survey
plan polygon is loaded — subtract coverage from plan to get the holidays.
"""

from __future__ import annotations

from pyproj import CRS, Transformer
from shapely import ops, union_all
from shapely.geometry import LineString, MultiPolygon, Polygon, mapping, shape


def _local_crs(lat: float, lon: float) -> CRS:
    return CRS.from_proj4(
        f"+proj=tmerc +lat_0={lat} +lon_0={lon} +k=1 +x_0=0 +y_0=0 "
        "+ellps=WGS84 +units=m +no_defs"
    )


def coverage_geojson(fixes: list[dict], plan_geojson: dict | None = None) -> dict:
    """FeatureCollection: track line, coverage polygon, holidays (if plan set).

    ``fixes`` need lat, lon and swath_m keys (swath_m may be None — those
    segments contribute track but no coverage width).
    """
    features: list[dict] = []
    if len(fixes) < 2:
        return {"type": "FeatureCollection", "features": features}

    lat0 = fixes[len(fixes) // 2]["lat"]
    lon0 = fixes[len(fixes) // 2]["lon"]
    local = _local_crs(lat0, lon0)
    to_local = Transformer.from_crs("EPSG:4326", local, always_xy=True)
    to_wgs = Transformer.from_crs(local, "EPSG:4326", always_xy=True)

    pts = [to_local.transform(f["lon"], f["lat"]) for f in fixes]
    track = LineString(pts)
    features.append(
        {
            "type": "Feature",
            "properties": {"kind": "track", "fixes": len(fixes)},
            "geometry": mapping(ops.transform(to_wgs.transform, track)),
        }
    )

    strips = []
    for (p0, p1), f0, f1 in zip(zip(pts, pts[1:]), fixes, fixes[1:]):
        widths = [w for w in (f0.get("swath_m"), f1.get("swath_m")) if w]
        if not widths or p0 == p1:
            continue
        strips.append(LineString([p0, p1]).buffer(sum(widths) / len(widths) / 2.0))
    if strips:
        covered = union_all(strips)
        features.append(
            {
                "type": "Feature",
                "properties": {"kind": "coverage", "area_m2": round(covered.area, 1)},
                "geometry": mapping(ops.transform(to_wgs.transform, covered)),
            }
        )
        if plan_geojson is not None:
            plan_local = ops.transform(to_local.transform, _plan_polygon(plan_geojson))
            holidays = plan_local.difference(covered)
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "kind": "holidays",
                        "area_m2": round(holidays.area, 1),
                        "plan_area_m2": round(plan_local.area, 1),
                        "covered_pct": round(100.0 * (1.0 - holidays.area / plan_local.area), 1)
                        if plan_local.area
                        else None,
                    },
                    "geometry": mapping(ops.transform(to_wgs.transform, holidays)),
                }
            )
    return {"type": "FeatureCollection", "features": features}


def _plan_polygon(plan_geojson: dict) -> Polygon | MultiPolygon:
    g = plan_geojson
    if g.get("type") == "FeatureCollection":
        g = g["features"][0]
    if g.get("type") == "Feature":
        g = g["geometry"]
    poly = shape(g)
    if poly.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"plan must be a Polygon, got {poly.geom_type}")
    if not poly.is_valid:
        raise ValueError("plan polygon is invalid")
    return poly
