import sys
import time
import requests
import json

PIPED = [
    "https://api.piped.private.coffee",
    "https://api-piped.mha.fi",
    "https://piped-api.hostux.net",
]

INVIDIOUS = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://yewtu.be",
]

VID = "sEAPQEtaTuM" # Maomao Loses It

print(f"Testing stream extraction for {VID}...")

for base in PIPED:
    print(f"\n--- Testing Piped: {base} ---")
    try:
        url = f"{base}/streams/{VID}"
        r = requests.get(url, timeout=10)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            if 'error' in data:
                print(f"Error returned: {data['error']}")
            else:
                streams = data.get('videoStreams', [])
                if streams:
                    print(f"SUCCESS: Found {len(streams)} video streams")
                    print(f"Sample: {streams[0].get('url')[:60]}...")
                else:
                    print("Found no video streams but no error.")
    except Exception as e:
        print(f"Exception: {e}")

for base in INVIDIOUS:
    print(f"\n--- Testing Invidious: {base} ---")
    try:
        url = f"{base}/api/v1/videos/{VID}"
        r = requests.get(url, timeout=10)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            streams = data.get('formatStreams', [])
            if streams:
                print(f"SUCCESS: Found {len(streams)} video streams")
                print(f"Sample: {streams[0].get('url')[:60]}...")
            else:
                 print("Found no video streams.")
    except Exception as e:
         print(f"Exception: {e}")
