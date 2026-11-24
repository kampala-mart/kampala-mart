# Kampala Mart - v7.1: Save button is OWNER-ONLY now

## What v7.1 fixes (v7 issue)
- v7 floating "Save to Cloud" button showed for EVERYONE. v7.1: it only appears while the Owner Panel is open (after your Owner PIN unlocks it). Buyers and sellers never see it.
- The silent auto-save still runs for everyone - it must, so a seller's pending product reaches you for approval. It only saves when the shop actually changes, and a visitor cannot add/delete/approve anything with it.
- Keeps v7: outside-React save (proven by Console PUT {"ok":true}), v6 crash-proof Cloud panel.

## Upload (same as before, ONCE)
1. GitHub: delete ALL files, extract this zip ONCE into an EMPTY folder, upload all files. No _1 files.
2. Render > kampala-mart > Manual Deploy > Deploy latest commit > wait Live.
3. HARD REFRESH: Ctrl+Shift+R (phone: clear site data).
4. Test: as a normal visitor, no green button anywhere. Open Owner Panel with your PIN - green Save button appears bottom-right. Approve a product, tap it, check /api/shop in another tab.
5. DO NOT touch Environment Variables - DATABASE_URL stays as is.
