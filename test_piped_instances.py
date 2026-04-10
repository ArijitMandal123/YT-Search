import requests

# Test alternative Piped instance lists
print("=== Testing Piped registries ===")
registries = [
    "https://piped-instances.kavin.rocks/",
    "https://worker-snowy-bonus-aaf4.ci-f.workers.dev/",  # Cloudflare mirror
]
for reg in registries:
    try:
        r = requests.get(reg, timeout=10)
        data = r.json()
        print(f"{reg} -> {len(data)} instances")
    except Exception as e:
        print(f"{reg} -> ERROR: {e}")

# Test direct Piped API endpoints
print("\n=== Testing known Piped API endpoints for streams ===")
test_video = "BaW_jenozKc"
piped_apis = [
    "https://api.piped.private.coffee",
    "https://pipedapi.kavin.rocks",
    "https://api-piped.mha.fi",
    "https://pipedapi.r4fo.com",
    "https://api.piped.yt",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.darkness.services",
    "https://api.piped.projectsegfau.lt",
    "https://pipedapi.ngn.tf",
    "https://pipedapi.in.projectsegfau.lt",
    "https://api.piped.privacydev.net",
    "https://pipedapi.leptons.xyz",
    "https://piped-api.lunar.icu",
]

working = []
for api in piped_apis:
    try:
        sr = requests.get(f"{api}/streams/{test_video}", timeout=8)
        if sr.status_code == 200:
            sdata = sr.json()
            vs = sdata.get("videoStreams", [])
            if vs:
                print(f"  OK    {api} -> {len(vs)} video streams")
                working.append(api)
            elif sdata.get("error"):
                print(f"  ERROR {api} -> {sdata['error'][:80]}")
            else:
                print(f"  EMPTY {api} -> 0 streams")
        else:
            print(f"  HTTP  {api} -> {sr.status_code}")
    except Exception as e:
        err = str(e)[:60]
        print(f"  FAIL  {api} -> {err}")

# Test Invidious instances
print("\n=== Testing Invidious instances ===")
inv_apis = [
    "https://inv.tux.pizza",
    "https://invidious.privacyredirect.com",
    "https://invidious.protokoll-11.dev",
    "https://yt.artemislena.eu",
    "https://invidious.perennialte.ch",
    "https://iv.datura.network",
    "https://invidious.privacytools.io",
    "https://inv.thepixora.com",
    "https://yewtu.be",
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://iv.ggtyler.dev",
    "https://invidious.flokinet.to",
]

inv_working = []
for api in inv_apis:
    try:
        sr = requests.get(f"{api}/api/v1/videos/{test_video}", timeout=8)
        if sr.status_code == 200:
            sdata = sr.json()
            fs = sdata.get("formatStreams", [])
            af = sdata.get("adaptiveFormats", [])
            if fs or af:
                print(f"  OK    {api} -> {len(fs)} format + {len(af)} adaptive")
                inv_working.append(api)
            else:
                print(f"  EMPTY {api}")
        else:
            print(f"  HTTP  {api} -> {sr.status_code}")
    except Exception as e:
        err = str(e)[:60]
        print(f"  FAIL  {api} -> {err}")

print(f"\n=== SUMMARY ===")
print(f"Working Piped: {len(working)} -> {working}")
print(f"Working Invidious: {len(inv_working)} -> {inv_working}")
