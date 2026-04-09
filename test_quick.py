import requests

# Test a broader set of Piped API instances
instances = [
    'https://api.piped.private.coffee',
    'https://pipedapi.r4fo.com',
    'https://pipedapi.leptons.xyz',  
    'https://pipedapi.drgns.space',
    'https://piapi.ggtyler.dev',
    'https://pipedapi.ngn.tf',
    'https://api.piped.projectsegfau.lt',
]

vid = 'dQw4w9WgXcQ'
for inst in instances:
    try:
        r = requests.get(f'{inst}/streams/{vid}', timeout=12)
        if r.status_code == 200:
            d = r.json()
            vs = len(d.get('videoStreams', []))
            a = len(d.get('audioStreams', []))
            if vs > 0:
                print(f'OK   {inst} -> {vs}v {a}a')
            else:
                err = d.get('error', 'no streams')
                print(f'FAIL {inst} -> {err}')
        else:
            print(f'FAIL {inst} -> HTTP {r.status_code}')
    except Exception as e:
        emsg = str(e)[:80]
        print(f'ERR  {inst} -> {emsg}')

print('\n--- Invidious ---')
inv_instances = [
    'https://inv.nadeko.net',
    'https://invidious.nerdvpn.de',
    'https://inv.thepixora.com',
    'https://yewtu.be',
    'https://vid.puffyan.us',
    'https://invidious.fdn.fr',
    'https://yt.artemislena.eu',
]

for inst in inv_instances:
    try:
        r = requests.get(f'{inst}/api/v1/videos/{vid}', timeout=12)
        if r.status_code == 200:
            d = r.json()
            fs = len(d.get('formatStreams', []))
            af = len(d.get('adaptiveFormats', []))
            if fs > 0 or af > 0:
                print(f'OK   {inst} -> {fs} fmt, {af} adaptive')
            else:
                print(f'FAIL {inst} -> no formats in response')
        else:
            print(f'FAIL {inst} -> HTTP {r.status_code}')
    except Exception as e:
        emsg = str(e)[:80]
        print(f'ERR  {inst} -> {emsg}')
