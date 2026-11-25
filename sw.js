/* Kampala Mart SW v85 - network-first for pages + API so the installed app never serves a stale blank shell */
self.addEventListener('install',e=>{self.skipWaiting();});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.map(k=>caches.delete(k)))).then(()=>self.clients.claim()));});
self.addEventListener('fetch',e=>{ if(e.request.method!=='GET') return; const u=new URL(e.request.url); if(u.pathname.startsWith('/api/')||u.pathname.endsWith('.html')||u.pathname==='/'){ e.respondWith(fetch(e.request).catch(()=>caches.match('/index.html'))); } });
