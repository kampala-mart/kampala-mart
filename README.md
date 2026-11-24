# Kampala Mart - v5 FIX: no more silent save failures

## What v5 fixes (v4 bug)
- v4: products lived ONLY in the tab's memory. No localStorage backup. Every save swallowed errors with .catch(()=>{}), so a failed PUT looked like success.
- v5: every change updates window.__kmLatestShop + localStorage backup km_products_backup. Autosave + Approve + Save button all use the LIVE copy, not a stale closure.
- v5: autosave failures now SHOW in Owner Panel Cloud status ("CLOUD SAVE FAILED: ...") instead of silently vanishing.
- v5: if cloud is empty, the browser restores its own backup so refresh never wipes. Cloud still wins when it has products.
- v5 server: /api/shop always returns {products: [...], ...}, never bare {}.

## Upload (same as before, ONCE)
1. GitHub: delete ALL files, extract this zip ONCE into an EMPTY folder, upload all files. No _1 files.
2. Render > kampala-mart > Manual Deploy > Deploy latest commit > wait Live.
3. HARD REFRESH: Ctrl+Shift+R (phone: clear site data).
4. Test: phone add > computer Approve > check Cloud status in Owner Panel (must say Saved to cloud) > other browser /api/shop must show the product > other browser site must show it.
5. DO NOT touch Environment Variables - DATABASE_URL stays as is.
