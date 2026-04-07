import requests

url = "https://www.youtube.com/watch?v=dlE9AY9sXGs"
print(f"Testing Cobalt API for {url}")

headers = {
    "Accept": "application/json",
    "Content-Type": "application/json"
}

payload = {
    "url": url,
    "vQuality": "1080",
    "vCodec": "h264",
    "isAudioOnly": False,
    "isNoAudio": False
}

try:
    r = requests.post("https://co.wuk.sh/api/json", json=payload, headers=headers)
    print(f"Status: {r.status_code}")
    print(r.text)
except Exception as e:
    print(e)
