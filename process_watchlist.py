import json
import os

def process_watchlist(json_path, app_py_path):
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            watchlist = json.load(f)
    except FileNotFoundError:
        print(f"Error: {json_path} not found. Please run the JS snippet and save the file first.")
        return

    print(f"Loaded {len(watchlist)} items from watchlist.")

    # Dictionary format for app.py
    # "Title": "ID",
    new_entries = {}
    for item in watchlist:
        title = item['title']
        movie_id = item['id']
        # normalize title text if needed (e.g. remove " - Disney+ Hotstar" etc if present)
        new_entries[title] = movie_id

    # Generate the code snippet
    print("\n--- Copy and Paste this into app.py (inside DISNEY_IDS) ---\n")
    for title, movie_id in new_entries.items():
        print(f'    "{title}": "{movie_id}",')
    print("\n-----------------------------------------------------------\n")

    # Optional: Automatically update app.py (safer to just print for now as requested by plan)
    # But I can write a function to merge it if the user wants.

if __name__ == "__main__":
    # Assuming the user saved it as disney_watchlist.json in the same folder
    json_path = "disney_watchlist.json" 
    app_py_path = "app.py"
    process_watchlist(json_path, app_py_path)
