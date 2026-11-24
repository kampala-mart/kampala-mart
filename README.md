# Kampala Mart - Render + Postgres (CLEAN v3)

## Upload - do this EXACTLY once
1. On GitHub, delete ALL files in the repo (so no _1 / duplicate files remain).
2. Extract this zip ONCE into an EMPTY folder. Do NOT extract it twice into the same folder - that creates _1 duplicates.
3. Upload ALL files from that empty folder to GitHub. You must see exactly these 8 files, no _1 files:
   index.html, public/index.html, server.py, requirements.txt, render.yaml, sw.js, manifest.json, README.md
4. Render > kampala-mart > Manual Deploy > Deploy latest commit > wait for Live.
5. HARD REFRESH your site: Ctrl+Shift+R (or on phone: clear site data). Old service worker cached the blank page - a normal reload will keep showing blank!
6. Check https://<your-app>.onrender.com/api/health -> must say storage postgres after DATABASE_URL is set.

## Why v3 was blank before
v2 had a broken line `[STRIPPED]` in the save function - invalid JS, whole app failed to load -> blank page. v3 fixes it. Verified: main app script passes node --check.
