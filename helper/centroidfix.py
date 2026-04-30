#!/usr/bin/env python3
"""
merge_geojson_spatial.py

Matches geometries from noheader_district.geojson (GeometryCollection, accurate coords)
to named features in district.geojson (FeatureCollection) using CENTROID distance,
completely ignoring index order.

Algorithm:
  1. Compute centroid for every geometry in BOTH files
  2. For each noheader geometry, find the nearest district centroid (Haversine distance)
  3. Assign that district's id + properties to the noheader geometry
  4. Detect and warn about any duplicate assignments (two noheader geoms -> same district)
  5. Write a clean FeatureCollection output

Usage:
    python merge_geojson_spatial.py
    python merge_geojson_spatial.py --source district.geojson \
                                    --target noheader_district.geojson \
                                    --output output_district.geojson
"""

import json
import math
import argparse
from pathlib import Path
from collections import defaultdict


# ---------------------------------------------------------------------------
# Geometry helpers (pure Python, no dependencies)
# ---------------------------------------------------------------------------

def flatten_coords(coordinates):
    """Recursively flatten nested coordinate arrays to a list of [lon, lat] pairs."""
    if not coordinates:
        return []
    # Base case: a single coordinate pair [lon, lat] — both numbers
    if isinstance(coordinates[0], (int, float)):
        return [coordinates]
    result = []
    for item in coordinates:
        result.extend(flatten_coords(item))
    return result


def polygon_centroid(ring):
    """
    Compute centroid of a polygon ring using the standard area-weighted formula.
    ring: list of [lon, lat] pairs (closed or unclosed)
    Returns (lon, lat)
    """
    n = len(ring)
    if n == 0:
        return (0.0, 0.0)
    if n == 1:
        return (ring[0][0], ring[0][1])

    area = 0.0
    cx = 0.0
    cy = 0.0

    for i in range(n):
        j = (i + 1) % n
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        cross = xi * yj - xj * yi
        area += cross
        cx += (xi + xj) * cross
        cy += (yi + yj) * cross

    area *= 0.5
    if abs(area) < 1e-12:
        # Degenerate polygon — fall back to simple mean
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        return (sum(lons) / len(lons), sum(lats) / len(lats))

    cx /= (6.0 * area)
    cy /= (6.0 * area)
    return (cx, cy)


def geometry_centroid(geometry):
    """
    Compute centroid for any GeoJSON geometry type.
    Returns (lon, lat).
    """
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates", [])

    if gtype == "Point":
        return (coords[0], coords[1])

    elif gtype in ("LineString", "MultiPoint"):
        pts = flatten_coords(coords)
        if not pts:
            return (0.0, 0.0)
        return (sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts))

    elif gtype == "Polygon":
        # Use only the exterior ring (coords[0])
        exterior = coords[0] if coords else []
        return polygon_centroid(exterior)

    elif gtype == "MultiPolygon":
        # Weighted average of each polygon's centroid by its approximate area
        centroids_areas = []
        for poly_coords in coords:
            exterior = poly_coords[0] if poly_coords else []
            cx, cy = polygon_centroid(exterior)
            # Approximate area (shoelace, unsigned)
            n = len(exterior)
            area = 0.0
            for i in range(n):
                j = (i + 1) % n
                area += exterior[i][0] * exterior[j][1]
                area -= exterior[j][0] * exterior[i][1]
            area = abs(area) * 0.5
            centroids_areas.append((cx, cy, area))
        total_area = sum(a for _, _, a in centroids_areas)
        if total_area < 1e-12:
            # Fall back to simple mean
            all_pts = flatten_coords(coords)
            return (sum(p[0] for p in all_pts) / len(all_pts),
                    sum(p[1] for p in all_pts) / len(all_pts))
        lon = sum(cx * a for cx, _, a in centroids_areas) / total_area
        lat = sum(cy * a for _, cy, a in centroids_areas) / total_area
        return (lon, lat)

    elif gtype == "GeometryCollection":
        # Recurse into sub-geometries
        sub_geoms = geometry.get("geometries", [])
        pts = [geometry_centroid(g) for g in sub_geoms]
        if not pts:
            return (0.0, 0.0)
        return (sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts))

    else:
        # Fallback: flatten all coords
        pts = flatten_coords(coords)
        if not pts:
            return (0.0, 0.0)
        return (sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts))


def haversine_km(lon1, lat1, lon2, lat2):
    """Great-circle distance in km between two (lon, lat) points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def merge(source_path: str, target_path: str, output_path: str) -> None:
    with open(source_path, encoding="utf-8") as f:
        source = json.load(f)

    with open(target_path, encoding="utf-8") as f:
        target = json.load(f)

    # Validate
    assert source.get("type") == "FeatureCollection", \
        f"Expected FeatureCollection in {source_path}, got: {source.get('type')}"
    assert target.get("type") == "GeometryCollection", \
        f"Expected GeometryCollection in {target_path}, got: {target.get('type')}"

    source_features = source["features"]       # has names, bad coords
    target_geometries = target["geometries"]   # no names, accurate coords

    print(f"Source features  (with district names): {len(source_features)}")
    print(f"Target geometries (accurate coords):     {len(target_geometries)}")
    print()

    # Step 1: compute centroids for source (named) features
    print("Computing source centroids...")
    source_centroids = []
    for feat in source_features:
        lon, lat = geometry_centroid(feat["geometry"])
        source_centroids.append({
            "lon": lon,
            "lat": lat,
            "id": feat.get("id"),
            "properties": feat.get("properties", {}),
        })

    # Step 2: compute centroids for target geometries
    print("Computing target centroids...")
    target_centroids = []
    for geom in target_geometries:
        lon, lat = geometry_centroid(geom)
        target_centroids.append({"lon": lon, "lat": lat})

    # Step 3: match each target geometry to nearest source feature
    print("Matching by centroid distance...")
    print()

    assignments = []          # list of (target_idx, source_idx, dist_km)
    source_usage = defaultdict(list)  # source_idx -> [target_idxs]

    for t_idx, t_cen in enumerate(target_centroids):
        best_dist = float("inf")
        best_s_idx = -1
        for s_idx, s_cen in enumerate(source_centroids):
            dist = haversine_km(t_cen["lon"], t_cen["lat"],
                                s_cen["lon"], s_cen["lat"])
            if dist < best_dist:
                best_dist = dist
                best_s_idx = s_idx
        assignments.append((t_idx, best_s_idx, best_dist))
        source_usage[best_s_idx].append(t_idx)

    # Step 4: report matches
    print(f"{'Target':>6}  {'District':<20}  {'Dist (km)':>10}  {'Source centroid':>30}  {'Target centroid'}")
    print("-" * 100)
    for t_idx, s_idx, dist_km in assignments:
        s = source_centroids[s_idx]
        t = target_centroids[t_idx]
        district = s["properties"].get("DISTRICT", "?")
        flag = " ⚠️  LARGE DISTANCE" if dist_km > 50 else ""
        print(f"{t_idx:>6}  {district:<20}  {dist_km:>10.2f}  "
              f"({s['lon']:>10.5f}, {s['lat']:>9.5f})  "
              f"({t['lon']:>10.5f}, {t['lat']:>9.5f}){flag}")

    print()

    # Step 5: warn about duplicates
    duplicates = {s_idx: t_idxs for s_idx, t_idxs in source_usage.items() if len(t_idxs) > 1}
    if duplicates:
        print("⚠️  WARNING: Multiple target geometries matched to the same source district!")
        for s_idx, t_idxs in duplicates.items():
            district = source_centroids[s_idx]["properties"].get("DISTRICT", "?")
            print(f"   District '{district}' (source #{s_idx}) <- target indices {t_idxs}")
        print()

    unmatched_sources = [s_idx for s_idx in range(len(source_features))
                         if s_idx not in source_usage]
    if unmatched_sources:
        print("⚠️  WARNING: These source districts were not matched to any target geometry:")
        for s_idx in unmatched_sources:
            district = source_centroids[s_idx]["properties"].get("DISTRICT", "?")
            print(f"   Source #{s_idx}: '{district}'")
        print()

    # Step 6: build output FeatureCollection
    merged_features = []
    for t_idx, s_idx, dist_km in assignments:
        s = source_centroids[s_idx]
        merged_features.append({
            "type": "Feature",
            "id": s["id"],
            "properties": s["properties"],
            "geometry": target_geometries[t_idx],   # accurate coords
        })

    output = {
        "type": "FeatureCollection",
        "features": merged_features,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ Done! Written {len(merged_features)} features to '{output_path}'")


def main():
    parser = argparse.ArgumentParser(
        description="Spatially match GeometryCollection to FeatureCollection using centroid distance."
    )
    parser.add_argument("--source", default="district.geojson",
                        help="FeatureCollection with district names (default: district.geojson)")
    parser.add_argument("--target", default="noheader_district.geojson",
                        help="GeometryCollection with accurate coords (default: noheader_district.geojson)")
    parser.add_argument("--output", default="output_district.geojson",
                        help="Output path (default: output_district.geojson)")
    args = parser.parse_args()

    for path in [args.source, args.target]:
        if not Path(path).exists():
            raise FileNotFoundError(f"File not found: '{path}'")

    merge(args.source, args.target, args.output)


if __name__ == "__main__":
    main()