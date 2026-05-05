import requests
import pandas as pd
import sys

def get_nepal_wards():
    print("Step 1: Connecting to OpenStreetMap Servers...")
    
    # We try the main server first, then a mirror if it fails
    url = "https://overpass-api.de/api/interpreter"
    
    # The 'User-Agent' is required to prevent the 406 error. 
    # It tells the server who you are.
    headers = {
        'User-Agent': 'NepalWardDataScraper/1.0 (https://github.com/yourusername/project)',
        'Accept-Encoding': 'gzip, deflate, br',
    }

    query = """
    [out:json][timeout:300];
    area["ISO3166-1"="NP"]["admin_level"="2"]->.searchArea;
    (
      relation["boundary"="administrative"]["admin_level"="9"](area.searchArea);
    );
    out tags;
    """

    try:
        # We send the request with headers now
        response = requests.post(url, data={'data': query}, headers=headers, timeout=300)
        
        # If the main server fails with 406, try the French mirror
        if response.status_code == 406:
            print("Main server blocked request (406). Trying Mirror server...")
            url = "https://overpass.openstreetmap.fr/api/interpreter"
            response = requests.post(url, data={'data': query}, headers=headers, timeout=300)

        response.raise_for_status()
        data = response.json()
        
        elements = data.get('elements', [])
        if not elements:
            print("No wards found. The query might have returned an empty set.")
            return

        print(f"Step 2: Data received! Found {len(elements)} wards.")

        ward_list = []
        for item in elements:
            tags = item.get('tags', {})
            row = {
                'osm_id': item.get('id'),
                'ward_number': tags.get('ward', 'N/A'),
                'name_nepali': tags.get('name', 'N/A'),
                'name_english': tags.get('name:en', 'N/A'),
                'municipality': tags.get('is_in:municipality', tags.get('parent_name', 'N/A')),
                'admin_level': tags.get('admin_level'),
                'wikidata_id': tags.get('wikidata', 'N/A')
            }
            ward_list.append(row)

        df = pd.DataFrame(ward_list)
        # Sort by ward number if possible
        df = df.sort_values(by=['ward_number'])
        
        filename = 'nepal_wards_full_list.csv'
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        
        print(f"Step 3: Success! Saved to {filename}")

    except requests.exceptions.HTTPError as err:
        print(f"HTTP Error: {err}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    get_nepal_wards()