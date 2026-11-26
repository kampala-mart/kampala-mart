# V11 FIXED - same design, server-only
- index.html: early script blocks SHARED localStorage keys, keeps per-device km_session / cookie / push only.
- index.html: end script SSE + 1s version poll + server unread badges, reload only when idle & not typing.
- server.py: VERSION, SSE /api/events, GET /api/version, GET /api/unread, POST /api/patch atomic, dedupe notifications by id, bump on every save.
Deploy: upload all files to GitHub, Render redeploys. Build pip install -r requirements.txt | Start python server.py
