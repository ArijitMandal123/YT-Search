import yt_dlp
import sys
ydl_opts = {'quiet': True, 'extract_flat': True}
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info('ytsearch3:The Apothecary Diaries Maomao Jinshi investigation 4k', download=False)
    for entry in info['entries']:
        print(f"{entry['id']} - {entry['title']}")
