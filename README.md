# Kampala Mart - Render deploy

Your design is unchanged (desktop + phone in one file). Data now lives on Render at /api/shop, so every buyer/seller sees the same shop.

## Deploy (5 min)
1. Create a free GitHub repo, upload ALL files in this folder (keep structure: server.py at root, index in public/).
2. Render.com > New + > Web Service > connect that repo.
3. Environment: Python. Build Command: leave empty. Start Command: `python server.py`
4. Deploy. Open your `https://<your-app>.onrender.com` - test: add product on phone, reload on desktop, it must appear.
5. Owner: open Owner Panel > Save to Cloud / Save This Shop once to push your current shop to Render.

## IMPORTANT - free Render disk wipes on redeploy
Free Render disk is ephemeral. Do ONE of these so products never wipe:
- Option A (easiest, recommended): Render dashboard > your service > Disks > Add Disk, Name: data, Mount Path: /opt/render/project/src, Size: 1 GB, then redeploy. data.json then survives restarts.
- Option B: use Render Postgres (free) and later point /api/shop at it - ask me and I will convert server.py.

## How sync works
- Seller upload / owner change -> app auto-saves (debounced) PUT /api/shop -> server writes data.json
- Every visitor loads GET /api/shop on open, so they see the latest shop.
- Empty saves are rejected (409) so a blank load can never wipe a live shop.

## Files
- public/index.html - your site, cleaned (no PythonAnywhere/Cloudflare/Google Sheets, no hardcoded keys)
- server.py - stdlib only, no pip installs needed, serves site + API
- render.yaml - Render service definition
- sw.js / manifest.json - phone install (PWA)
