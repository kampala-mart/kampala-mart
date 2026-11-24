# Kampala Mart - v4 FIX: Approve now saves to Postgres + all browsers can load flat format

## What v4 fixes (v3 bug)
- v3: second browser could NOT read cloud (expected old rows[0].data format, server sends flat {products}).
- v3: Google-first load returned early because Google URL is empty.
- v3: Approve button never PUT to cloud (empty setTimeout).
- v4: Approve now PUTs the live list to /api/shop. Load handles both flat and old formats.

## Upload (same as before, ONCE)
1. GitHub: delete ALL files, extract this zip ONCE into an EMPTY folder, upload all files. No _1 files.
2. Render > kampala-mart > Manual Deploy > Deploy latest commit > wait Live.
3. HARD REFRESH: Ctrl+Shift+R (phone: clear site data).
4. Test: phone add product > computer Approve > other browser reload must show it.
5. Check https://<app>.onrender.com/api/health -> storage postgres.

## Note
Script km-v42-push-js has a pre-existing syntax error in the ORIGINAL file too (fails node --check in original as well). It is an isolated script tag and does not block the main app. Left untouched to avoid changing behaviour.
