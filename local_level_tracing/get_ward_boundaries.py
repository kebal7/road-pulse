import pandas as pd
import requests
import json
import time
import os

def get_boundaries_in_batches():
    csv_file = 'nepal_wards_full_list.csv'
    output_file = 'nepal_wards_final.geojson'
    
    if not os.path.exists(csv_file):
        print(f"Error: {csv_file} not found. Please run your first script again to generate the CSV.")
        return

    # Load IDs from CSV
    df = pd.read_csv(csv_file)
    # Ensure osm_id is clean (no decimals)
    all_ids = df['osm_id'].dropna().unique().astype(int).tolist()
    
    print(f"Loaded {len(all_ids)} ward IDs from CSV.")

    url = "https://overpass-api.de/api/interpreter"
    headers = {'User-Agent': 'NepalRoadPulse_BatchScraper/6.0'}
    
    batch_size = 50  # Smaller batches = more stable
    all_features = []

    print(f"Processing in batches of {batch_size}...")

    for i in range(0, len(all_ids), batch_size):
        batch = all_ids[i:i + batch_size]
        # Format IDs for Overpass: id1,id2,id3...
        id_string = ",".join(map(str, batch))
        
        # Optimized query: Fetch specific relations by ID
        query = f"[out:json][timeout:120];(rel(id:{id_string}););out geom;"
        
        success = False
        attempts = 0
        while not success and attempts < 3:
            try:
                response = requests.post(url, data={'data': query}, headers=headers, timeout=120)
                
                if response.status_code == 429:
                    print(f"  Rate limited. Waiting 30s...")
                    time.sleep(30)
                    attempts += 1
                    continue
                
                response.raise_for_status()
                elements = response.json().get('elements', [])
                
                for el in elements:
                    if 'members' in el:
                        coords_list = []
                        for member in el['members']:
                            if 'geometry' in member:
                                line = [(p['lon'], p['lat']) for p in member['geometry']]
                                coords_list.append(line)
                        
                        if not coords_list: continue

                        feature = {
                            "type": "Feature",
                            "id": el['id'],
                            "geometry": {"type": "MultiLineString", "coordinates": coords_list},
                            "properties": el.get('tags', {})
                        }
                        all_features.append(feature)
                
                print(f"  Batch {i//batch_size + 1}: Fetched {len(elements)} items. Total: {len(all_features)}")
                success = True
                time.sleep(1) # Be nice to the server
                
            except Exception as e:
                print(f"  Error in batch starting at index {i}: {e}. Retrying...")
                attempts += 1
                time.sleep(5)

    # Final Save
    print(f"\nFinalizing... Saving {len(all_features)} features to {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({"type": "FeatureCollection", "features": all_features}, f, ensure_ascii=False)
    
    print("SUCCESS! You can now use nepal_wards_final.geojson")

if __name__ == "__main__":
    get_boundaries_in_batches()