#!/usr/bin/env python3
"""
merge_geojson_header.py

Converts noheader_district.geojson (a GeometryCollection with accurate coordinates)
into a proper FeatureCollection by copying the structure and properties
(id, DISTRICT name, etc.) from district.geojson — matched by index order.

Structure:
  district.geojson          → FeatureCollection → features[i] has id, properties.DISTRICT, geometry
  noheader_district.geojson → GeometryCollection → geometries[i] has accurate coordinates

Result:
  output_district.geojson   → FeatureCollection → features[i] has id, properties.DISTRICT,
                               and geometry from noheader_district.geojson

Usage:
    python merge_geojson_header.py
    python merge_geojson_header.py --source district.geojson \
                                   --target noheader_district.geojson \
                                   --output output_district.geojson
"""

import json
import argparse
from pathlib import Path


def merge(source_path: str, target_path: str, output_path: str) -> None:
    with open(source_path, encoding="utf-8") as f:
        source = json.load(f)  # FeatureCollection

    with open(target_path, encoding="utf-8") as f:
        target = json.load(f)  # GeometryCollection

    # Validate types
    assert source.get("type") == "FeatureCollection", \
        f"Expected 'FeatureCollection' in {source_path}, got: {source.get('type')}"
    assert target.get("type") == "GeometryCollection", \
        f"Expected 'GeometryCollection' in {target_path}, got: {target.get('type')}"

    source_features = source.get("features", [])
    target_geometries = target.get("geometries", [])

    # Warn if counts differ
    if len(source_features) != len(target_geometries):
        print(f"WARNING: feature count mismatch!")
        print(f"   district.geojson features:            {len(source_features)}")
        print(f"   noheader_district.geojson geometries: {len(target_geometries)}")
        print(f"   Will merge up to {min(len(source_features), len(target_geometries))} features.")

    count = min(len(source_features), len(target_geometries))

    merged_features = []
    for i in range(count):
        src_feat = source_features[i]
        tgt_geom = target_geometries[i]

        merged_feature = {
            "type": "Feature",
            "id": src_feat.get("id", i),
            "properties": src_feat.get("properties", {}),  # e.g. {"DISTRICT": "HUMLA"}
            "geometry": tgt_geom,                           # accurate coords from noheader
        }
        merged_features.append(merged_feature)

    output = {
        "type": "FeatureCollection",
        "features": merged_features,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Done! Merged {count} features -> '{output_path}'")
    if merged_features:
        sample = merged_features[0]
        print(f"  Sample feature 0:")
        print(f"    id:         {sample.get('id')}")
        print(f"    properties: {sample.get('properties')}")
        coords_preview = sample.get("geometry", {}).get("coordinates", [[[]]])[0][:2]
        print(f"    first 2 coords: {coords_preview}")


def main():
    parser = argparse.ArgumentParser(
        description="Merge FeatureCollection metadata into GeometryCollection coordinates."
    )
    parser.add_argument("--source", default="district.geojson",
                        help="FeatureCollection GeoJSON with district names (default: district.geojson)")
    parser.add_argument("--target", default="noheader_district.geojson",
                        help="GeometryCollection GeoJSON with accurate coordinates (default: noheader_district.geojson)")
    parser.add_argument("--output", default="output_district.geojson",
                        help="Output file path (default: output_district.geojson)")
    args = parser.parse_args()

    for path in [args.source, args.target]:
        if not Path(path).exists():
            raise FileNotFoundError(
                f"File not found: '{path}' — make sure it's in the same folder as this script."
            )

    merge(args.source, args.target, args.output)


if __name__ == "__main__":
    main()