# Kampala Mart - Render + Postgres (does NOT wipe)

Your design is unchanged (desktop + phone in one file). Data now lives in Render Postgres at /api/shop, so redeploys / restarts / free-plan sleeps CANNOT wipe products.

## Deploy (one Blueprint, creates web service + database together)
1. Create a free GitHub repo, upload ALL files in this folder (keep structure: server.py + requirements.txt at root, site in public/).
2. Render.com > New + > Blueprint > connect that repo > Apply. Render creates BOTH:
   - Web Service `kampala-mart`
   - Database `kampala-mart-db` (free Postgres)
   Render auto-sets DATABASE_URL on the web service from the database. Do NOT paste it manually.
3. Wait for deploy to go Live. Open your https://<your-app>.onrender.com
4. Check: open https://<your-app>.onrender.com/api/health - it must say "storage":"postgres"
5. Test: add a product on your phone > reload on desktop > it must appear.
6. Owner Panel > Save to Cloud / Save This Shop once, to push your current shop into Postgres.
7. Prove it does not wipe: Render > your service > Manual Deploy > Deploy latest commit, wait, reload site - products must still be there.

## If you already deployed the old disk version
Option A (cleanest): deploy this Blueprint as a NEW service + database, then in the OLD site Owner Panel save once, and in the NEW site load - or just re-add products.
Option B: in your EXISTING service, add env var DATABASE_URL from an existing Render Postgres database, set Build Command to `pip install -r requirements.txt`, redeploy. The old data.json is ignored once DATABASE_URL is set.

## How it works
- Seller upload / owner change -> app auto-saves PUT /api/shop -> server upserts ONE row (id=1) in Postgres table `shop(data JSONB)`
- Every visitor loads GET /api/shop -> same Postgres row -> everyone sees same shop
- Empty saves rejected (409) so a blank load can never wipe a live shop
- Table is auto-created on first start: CREATE TABLE IF NOT EXISTS shop (id INT PRIMARY KEY, data JSONB)

## Files
- public/index.html - your site, cleaned (no PythonAnywhere/Cloudflare/Google Sheets, no hardcoded keys)
- server.py - serves site + /api/shop, Postgres-first
- requirements.txt - psycopg2-binary
- render.yaml - Blueprint: web service + free Postgres, DATABASE_URL wired automatically
- sw.js / manifest.json - phone install (PWA)

## Notes
- Render free Postgres: free for 90 days, then it expires unless you upgrade / recreate it. If it ever expires, create a new free Postgres in Render, copy its Internal Database URL into the web service env var DATABASE_URL, redeploy. Your site code does not change.
- Never put DATABASE_URL in GitHub / in the HTML. It lives only as a Render env var.
- Local test without Postgres: `python server.py` falls back to local data.json (for testing only, not used on Render).
