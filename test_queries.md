# YouTube Metadata API: Test Queries

Use these JSON payloads to test the API enrichment, duration filtering, and search relevance.

## 🎌 Anime (Raw & Aesthetic)

### 1. Aesthetic Scenery (Filter 1-5 mins)
```json
{
  "query": "Garden of Words rain scenery 4k aesthetic raw no subs",
  "duration_min": 60,
  "duration_max": 300,
  "max_results": 1
}
```

### 2. Action Scene (High Intensity)
```json
{
  "query": "Jujutsu Kaisen Gojo vs Sukuna raw 1080p no subs",
  "duration_min": 30,
  "duration_max": 240,
  "max_results": 1,
  "enrich": true
}
```

### 3. One Piece (The Laboon Test)
```json
{
  "query": "One Piece Laboon whale tragic promise raw",
  "duration_min": 60,
  "duration_max": 300,
  "max_results": 1
}
```

### 4. Ghibli Backgrounds
```json
{
  "query": "Studio Ghibli relaxing scenery lofi background raw",
  "duration_min": 120,
  "max_results": 1
}
```

### 5. Anime Opening (Music Focus)
```json
{
  "query": "Oshi no Ko Idol official opening creditless",
  "duration_min": 80,
  "duration_max": 100,
  "max_results": 1
}
```

---

## 🎬 Movies & Cinema

### 6. Cinematic Landscapes
```json
{
  "query": "Interstellar wormhole scene 4k high quality",
  "duration_min": 60,
  "duration_max": 300,
  "max_results": 1
}
```

### 7. Epic Speeches (Dialogue Test)
```json
{
  "query": "Lord of the Rings Aragorn speech Black Gate 4k",
  "duration_min": 40,
  "duration_max": 180,
  "max_results": 1
}
```

### 8. Movie Soundtracks (Audio Enrichment)
```json
{
  "query": "Inception Time Hans Zimmer official soundtrack 1080p",
  "duration_min": 240,
  "max_results": 1
}
```

### 9. Sci-Fi Atmosphere
```json
{
  "query": "Dune 2021 Arrakis landscape cinematic 4k atmosphere",
  "duration_min": 60,
  "duration_max": 600,
  "max_results": 1
}
```

### 10. Classic Cinema Moments
```json
{
  "query": "The Godfather 'Offer he can't refuse' scene HD",
  "duration_min": 30,
  "duration_max": 200,
  "max_results": 1
}
```

---

## 🎮 Gaming & Trailers

### 11. Official Cinematic Trailers
```json
{
  "query": "Elden Ring Shadow of the Erdtree official cinematic trailer",
  "duration_min": 120,
  "duration_max": 400,
  "max_results": 1
}
```

### 12. Cyberpunk Atmosphere (Rain/Driving)
```json
{
  "query": "Cyberpunk 2077 Night City driving aesthetic rain raw",
  "duration_min": 300,
  "max_results": 1
}
```

### 13. Boss Fights (Pure Gameplay)
```json
{
  "query": "Black Myth Wukong gameplay boss fight no commentary",
  "duration_min": 180,
  "duration_max": 900,
  "max_results": 1
}
```

### 14. Retro Gaming Vibes
```json
{
  "query": "Zelda Ocarina of Time Hyrule Field aesthetic Nintendo 64",
  "duration_min": 60,
  "max_results": 1
}
```

### 15. Gaming Music / Orchestral
```json
{
  "query": "League of Legends Legends Never Die official orchestral",
  "duration_min": 180,
  "max_results": 1
}
```

---

## 🌍 Nature, World & ASMR

### 16. Drone Footage (Landscapes)
```json
{
  "query": "Cinematic drone footage Iceland landscapes 4k 60fps",
  "duration_min": 300,
  "max_results": 1
}
```

### 17. City Walking Tours (Background)
```json
{
  "query": "Tokyo Shibuya night walking tour 4k binaural ASMR",
  "duration_min": 600,
  "duration_max": 3600,
  "max_results": 1
}
```

### 18. Nature Sounds (Pure Audio/Visual)
```json
{
  "query": "Amazon Rainforest sounds bird chirping heavy rain 10 hours",
  "duration_min": 3600,
  "max_results": 1,
  "enrich": false
}
```

### 19. Space / Universe Exploration
```json
{
  "query": "Hubble Space Telescope 4k ultra hd nebula galaxy",
  "duration_min": 300,
  "max_results": 1
}
```

### 20. Underwater / Ocean
```json
{
  "query": "Great Barrier Reef underwater drone footage 4k coral",
  "duration_min": 120,
  "max_results": 1
}
```

---

## 🎵 Music & Lo-Fi

### 21. Lo-Fi Hip Hop (Long Form)
```json
{
  "query": "lofi hip hop radio beats to relax study to",
  "duration_min": 3600,
  "max_results": 1
}
```

### 22. Synthwave / Retrowave
```json
{
  "query": "synthwave neon city drive background music",
  "duration_min": 1800,
  "max_results": 1
}
```

### 23. Dark Academia Ambient
```json
{
  "query": "dark academia library ambient rain fireplace sounds",
  "duration_min": 1800,
  "max_results": 1
}
```

### 24. Epic Orchestral Battle Music
```json
{
  "query": "Two Steps From Hell Victory official audio",
  "duration_min": 240,
  "max_results": 1
}
```

### 25. Piano instrumentals
```json
{
  "query": "Joe Hisaishi Merry-Go-Round of Life piano solo",
  "duration_min": 180,
  "max_results": 1
}
```
