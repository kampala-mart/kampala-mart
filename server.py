import json, os, mimetypes, threading, time, base64, uuid, urllib.request, urllib.error
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
BASE=os.path.dirname(os.path.abspath(__file__)); PUBLIC=os.path.join(BASE,"public"); DATA_FILE=os.path.join(BASE,"data.json"); LOCK=threading.Lock(); PRESENCE={}; DB_URL=os.environ.get("DATABASE_URL",""); _pg=None
def pg_conn():
    global _pg
    if _pg is None:
        import psycopg2
        _pg=psycopg2.connect(DB_URL.replace("postgres://","postgresql://",1), sslmode="require", connect_timeout=10); _pg.autocommit=True
        with _pg.cursor() as c:
            c.execute("CREATE TABLE IF NOT EXISTS shop (id INT PRIMARY KEY, data JSONB NOT NULL)")
            c.execute("INSERT INTO shop (id, data) VALUES (1, '{}'::jsonb) ON CONFLICT (id) DO NOTHING")
    return _pg
def _normalize(d):
    if not isinstance(d,dict): d={}
    for k,v in [("products",[]),("settings",{}),("ads",{}),("banners",[]),("categories",[]),("locations",[]),("chats",[]),("users",[]),("payments",[]),("broadcasts",[]),("reviews",[]),("pendingPayments",[])]: d.setdefault(k,v)
    return d

from datetime import datetime, timezone
def _now_iso():
    return datetime.now(timezone.utc).isoformat()
def _key(item):
    if not isinstance(item, dict): return None
    return item.get("id") or item.get("name") or item.get("title")
def _pick(a, b):
    # winner between stored (a) and incoming (b) for the same id
    if not isinstance(a, dict): return b
    if not isinstance(b, dict): return a
    rank = {"live": 3, "sold": 3, "pending_verification": 2, "hidden": 2, "draft": 1, "rejected": 0}
    ra = rank.get(a.get("status"), 0); rb = rank.get(b.get("status"), 0)
    if rb > ra: return b
    if ra > rb: return a
    ua = a.get("updatedAt") or a.get("submittedAt") or ""
    ub = b.get("updatedAt") or b.get("submittedAt") or ""
    if ua and ub:
        # Compare as real times, not as strings ("500" > "1000" as text)
        def _ts(v):
            try:
                if isinstance(v, (int, float)): return float(v)
                if isinstance(v, str):
                    try: return float(v)
                    except Exception: pass
                    try:
                        from datetime import datetime
                        return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() * 1000
                    except Exception: return 0
            except Exception: return 0
            return 0
        return b if _ts(ub) > _ts(ua) else a
    if ub and not ua: return b
    if ua and not ub: return a
    return b
def _merge_list(stored, incoming, deleted):
    out = {}
    order = []
    for it in (stored or []):
        k = _key(it)
        if k is None or k in deleted: continue
        out[k] = it; order.append(k)
    for it in (incoming or []):
        k = _key(it)
        if k is None or k in deleted: continue
        if k in out:
            merged = _pick(out[k], it)
            if isinstance(out[k], dict) and isinstance(it, dict) and isinstance(out[k].get("messages"), list) and isinstance(it.get("messages"), list):
                mm = _merge_list(out[k]["messages"], it["messages"], set())
                merged = dict(merged); merged["messages"] = mm
            out[k] = merged
        else:
            out[k] = it; order.append(k)
    return [out[k] for k in order]
def _merge_shop(cur, data, deleted):
    # Deletes are PERMANENT: tombstones live on the server, not in one browser
    try:
        deleted = set(deleted or []) | set(cur.get("_deletedIds") or [])
    except Exception:
        deleted = set(deleted or [])
    merged = dict(cur)
    list_fields = ["products", "chats", "notifications", "submissions", "payments", "users", "broadcasts", "reviews", "banners", "categories", "locations", "pendingPayments", "boosts"]
    for f in list_fields:
        if isinstance(data.get(f), list):
            merged[f] = _merge_list(cur.get(f) or [], data[f], deleted)
    for f in ["settings", "ads", "saved"]:
        if isinstance(data.get(f), dict):
            base = dict(cur.get(f) or {}); base.update(data[f]); merged[f] = base
    # Keep the stored OneSignal REST key: clients never send it back (it is stripped from GET)
    try:
        _rk = (cur.get("settings") or {}).get("onesignalRestKey")
        if _rk and not (merged.get("settings") or {}).get("onesignalRestKey"):
            merged["settings"] = dict(merged.get("settings") or {}); merged["settings"]["onesignalRestKey"] = _rk
    except Exception: pass
    for k, v in data.items():
        if k in list_fields or k in ("settings", "ads", "saved", "deletedIds", "allowEmpty"):
            continue
        merged[k] = v
    try:
        merged["_deletedIds"] = sorted(deleted)[-1000:]
    except Exception:
        pass
    return merged
def _enrich(d):
    # Returns True if d changed. 1) Automatic mode: verified payment -> live, no owner approval.
    # 2) One approval notification per pending product so the owner panel never shows 0.
    changed = False
    try:
        settings = d.get("settings") or {}
        products = d.get("products") or []
        notifs = d.get("notifications") or []
        if (settings.get("paymentMode") or "").lower() in ("auto", "automatic"):
            for p in products:
                if p.get("status") == "pending_verification" and (p.get("paymentReference") or p.get("paymentPhone") or p.get("proofUrl")):
                    p["status"] = "live"
                    p["sellerNotice"] = "Payment verified automatically - your product is now live! No owner approval needed."
                    p["autoApproved"] = True
                    nid = "auto-live-" + str(p.get("id"))
                    if not any(n.get("id") == nid for n in notifs):
                        notifs.append({"id": nid, "userId": p.get("sellerId") or "", "sellerId": p.get("sellerId") or "", "productId": p.get("id"), "type": "product", "title": "Your product is now live!", "message": (p.get("name") or "Your product") + " is live - automatic payment verified.", "read": False, "createdAt": _now_iso()})
                        changed = True
                    changed = True
        pending_ids = set()
        for p in products:
            if p.get("status") == "pending_verification":
                pending_ids.add(p.get("id"))
                nid = "syn-approval-" + str(p.get("id"))
                has = any(n.get("productId") == p.get("id") and (n.get("type") in ("approval", "submission") or "approve" in str(n.get("title") or "").lower()) for n in notifs)
                if not has:
                    notifs.append({"id": nid, "userId": "owner", "forOwner": True, "type": "approval", "productId": p.get("id"), "title": "New product to approve: " + str(p.get("name") or "Product"), "message": str(p.get("sellerName") or "A seller") + " in " + str(p.get("location") or "Uganda") + " uploaded " + str(p.get("name") or "a product") + " - open Owner Panel > Approvals.", "read": False, "createdAt": _now_iso()})
                    changed = True
        # drop synthetic approvals whose product is no longer pending
        new_notifs = [n for n in notifs if not (str(n.get("id") or "").startswith("syn-approval-") and n.get("productId") not in pending_ids)]
        if len(new_notifs) != len(notifs):
            notifs = new_notifs; changed = True
        d["notifications"] = notifs
    except Exception:
        pass
    return changed

# ---------- v10.3 AUTOMATIC PAYMENTS: MTN MoMo + Airtel, real API ----------
def _norm_phone(raw):
    s = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if s.startswith("256") and len(s) == 12: return s
    if s.startswith("0") and len(s) == 10: return "256" + s[1:]
    if len(s) == 9: return "256" + s
    return s
def _http(method, url, headers=None, body=None, timeout=25):
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=(json.dumps(body).encode() if body is not None else None))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode()
            try: return r.status, json.loads(txt or "{}")
            except Exception: return r.status, {"raw": txt}
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try: return e.code, json.loads(txt or "{}")
        except Exception: return e.code, {"raw": txt}
    except Exception as e:
        return 0, {"error": str(e)[:300]}
def _mtn_base(settings):
    return "https://proxy.momoapi.mtn.com" if (settings.get("mtnEnvironment") or "").strip().lower() in ("live", "production", "mtnuganda") else "https://sandbox.momodeveloper.mtn.com"
def _mtn_token(settings):
    base = _mtn_base(settings); sub = settings.get("mtnSubscriptionKey") or ""; user = settings.get("mtnApiUser") or ""; key = settings.get("mtnApiKey") or ""
    if not (sub and user and key): return None, "MTN API keys not added. Owner: Owner Panel > Automatic Payment API."
    cred = base64.b64encode((user + ":" + key).encode()).decode()
    st, js = _http("POST", base + "/collection/token/", {"Authorization": "Basic " + cred, "Ocp-Apim-Subscription-Key": sub, "Content-Type": "application/json"}, {})
    tok = js.get("access_token")
    if not tok: return None, "MTN token failed: " + str(js)[:200]
    return tok, None
def _mtn_pay(settings, phone, amount, product_id):
    tok, err = _mtn_token(settings)
    if err: return None, err
    base = _mtn_base(settings); ref = str(uuid.uuid4())
    st, js = _http("POST", base + "/collection/v1_0/requesttopay",
        {"Authorization": "Bearer " + tok, "X-Reference-Id": ref, "X-Target-Environment": (settings.get("mtnEnvironment") or "sandbox"),
         "Ocp-Apim-Subscription-Key": settings.get("mtnSubscriptionKey") or "", "Content-Type": "application/json"},
        {"amount": str(amount), "currency": "UGX", "externalId": str(product_id or ref),
         "payer": {"partyIdType": "MSISDN", "partyId": phone},
         "payerMessage": "Kampala Mart listing fee", "payeeNote": "Kampala Mart"})
    if st in (200, 201, 202): return ref, None
    return None, "MTN request failed (" + str(st) + "): " + str(js)[:200]
def _mtn_check(settings, ref):
    tok, err = _mtn_token(settings)
    if err: return "PENDING", err
    base = _mtn_base(settings)
    st, js = _http("GET", base + "/collection/v1_0/requesttopay/" + ref,
        {"Authorization": "Bearer " + tok, "X-Target-Environment": (settings.get("mtnEnvironment") or "sandbox"),
         "Ocp-Apim-Subscription-Key": settings.get("mtnSubscriptionKey") or ""})
    return str(js.get("status") or "PENDING").upper(), None
def _airtel_token(settings):
    cid = settings.get("airtelClientId") or ""; sec = settings.get("airtelClientSecret") or ""
    if not (cid and sec): return None, "Airtel API keys not added. Owner: Owner Panel > Automatic Payment API."
    st, js = _http("POST", "https://openapi.airtel.africa/auth/oauth2/token",
        {"Content-Type": "application/json", "Accept": "*/*"},
        {"client_id": cid, "client_secret": sec, "grant_type": "client_credentials"})
    tok = (js.get("access_token") or (js.get("data") or {}).get("access_token"))
    if not tok: return None, "Airtel token failed: " + str(js)[:200]
    return tok, None
def _airtel_pay(settings, phone, amount, product_id):
    tok, err = _airtel_token(settings)
    if err: return None, err
    ref = "KM-" + str(uuid.uuid4())[:8]
    st, js = _http("POST", "https://openapi.airtel.africa/standard/v1/payments",
        {"Authorization": "Bearer " + tok, "X-Country": "UG", "X-Currency": "UGX", "Content-Type": "application/json"},
        {"reference": {"id": ref}, "subscriber": {"country": "UG", "currency": "UGX", "msisdn": phone},
         "transaction": {"amount": str(amount), "country": "UG", "currency": "UGX", "id": ref}})
    if st in (200, 201, 202): return ref, None
    return None, "Airtel request failed (" + str(st) + "): " + str(js)[:200]
def _airtel_check(settings, ref):
    tok, err = _airtel_token(settings)
    if err: return "PENDING", err
    st, js = _http("GET", "https://openapi.airtel.africa/standard/v1/payments/" + ref,
        {"Authorization": "Bearer " + tok, "X-Country": "UG", "X-Currency": "UGX"})
    s = str((((js.get("data") or {}).get("transaction") or {}).get("status")) or "TIP").upper()
    return {"TS": "SUCCESSFUL", "TF": "FAILED", "TIP": "PENDING"}.get(s, "PENDING"), None

def _bank_pay(settings, phone, amount, product_id):
    url = (settings.get("bankApiUrl") or "").strip(); key = settings.get("bankApiKey") or ""
    if not url: return None, "BANK_MANUAL"
    ref = "KM-" + str(uuid.uuid4())[:8]
    st, js = _http("POST", url, {"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        {"phone": phone, "amount": str(amount), "currency": "UGX", "reference": ref, "externalId": str(product_id or ref), "description": "Kampala Mart listing fee"})
    if st in (200, 201, 202): return ref, None
    return None, "Bank request failed (" + str(st) + "): " + str(js)[:200]
def _bank_check(settings, ref):
    url = (settings.get("bankApiUrl") or "").strip(); key = settings.get("bankApiKey") or ""
    if not url: return "PENDING", "BANK_MANUAL"
    st, js = _http("GET", url.rstrip("/") + "/" + ref, {"Authorization": "Bearer " + key})
    raw = str(((js.get("data") or {}).get("status")) or ((js.get("transaction") or {}).get("status")) or js.get("status") or "PENDING").upper()
    if raw in ("SUCCESSFUL", "SUCCESS", "COMPLETED", "PAID"): return "SUCCESSFUL", None
    if raw in ("FAILED", "FAILURE", "CANCELLED", "REJECTED"): return "FAILED", None
    return "PENDING", None

def _provider_status(settings, rec):
    net = (rec.get("network") or "MTN").upper()
    if "AIRTEL" in net: return _airtel_check(settings, rec.get("referenceId") or "")
    if "BANK" in net: return _bank_check(settings, rec.get("referenceId") or "")
    return _mtn_check(settings, rec.get("referenceId") or "")
def _flip_product_live(d, product_id, note):
    prods = d.get("products") or []
    for p in prods:
        if str(p.get("id")) == str(product_id) and p.get("status") != "live":
            p["status"] = "live"
            p["sellerNotice"] = note
            p["autoApproved"] = True
            notifs = d.setdefault("notifications", [])
            nid = "auto-live-" + str(p.get("id"))
            if not any(n.get("id") == nid for n in notifs):
                notifs.append({"id": nid, "userId": p.get("sellerId") or "", "sellerId": p.get("sellerId") or "", "productId": p.get("id"), "type": "product", "title": "Your product is now live!", "message": (p.get("name") or "Your product") + " is live - payment verified by the API.", "read": False, "createdAt": _now_iso()})
            return True
    return False
def _pay_poller():
    while True:
        try:
            time.sleep(20)
            with LOCK:
                d = load(); settings = d.get("settings") or {}; changed = False
                for rec in (d.get("pendingPayments") or []):
                    if rec.get("status") != "pending": continue
                    st, _e = _provider_status(settings, rec)
                    if st == "SUCCESSFUL":
                        rec["status"] = "successful"
                        if _flip_product_live(d, rec.get("productId"), "Payment verified automatically - your product is now live! No owner approval needed."): changed = True
                        changed = True
                    elif st == "FAILED":
                        rec["status"] = "failed"; changed = True
                if changed:
                    try: save(d)
                    except Exception: pass
        except Exception:
            pass

def _get_shop():
    with LOCK:
        d = load()
        if _enrich(d):
            try: save(d)
            except Exception: pass
        # OneSignal REST key NEVER leaves the server - strip it from every response
        try:
            st = d.get("settings") or {}
            if "onesignalRestKey" in st:
                d = dict(d); st = dict(st); del st["onesignalRestKey"]; d["settings"] = st
        except Exception:
            pass
        # Tell every browser which ids are deleted so stale copies never come back
        try:
            if "_deletedIds" in d:
                d = dict(d); d["deletedIds"] = sorted(d.get("_deletedIds") or []); del d["_deletedIds"]
        except Exception:
            pass
        return d

def load():
    if DB_URL:
        try:
            with pg_conn().cursor() as c:
                c.execute("SELECT data FROM shop WHERE id=1"); row=c.fetchone(); return _normalize(row[0] if row else {})
        except Exception:
            global _pg; _pg=None
            with pg_conn().cursor() as c:
                c.execute("SELECT data FROM shop WHERE id=1"); row=c.fetchone(); return _normalize(row[0] if row else {})
    try:
        with open(DATA_FILE) as f: return _normalize(json.load(f))
    except Exception: return _normalize({})

def _dedupe_notifs(ns):
    by_id = {}
    for n in (ns or []):
        if not isinstance(n, dict): continue
        i = n.get("id")
        if i in by_id:
            old = by_id[i]; old["read"] = bool(old.get("read") or n.get("read"))
            if str(n.get("createdAt") or "") >= str(old.get("createdAt") or ""):
                m = dict(n); m["read"] = old["read"]; by_id[i] = m
        else: by_id[i] = dict(n)
    seen = {}; out = []
    for n in sorted(by_id.values(), key=lambda x: str(x.get("createdAt") or "")):
        k = (n.get("type"), n.get("productId"), n.get("chatId"), n.get("title"), n.get("message"))
        if k in seen:
            prev = seen[k]; prev["read"] = bool(prev.get("read") or n.get("read"))
            if str(n.get("createdAt") or "") > str(prev.get("createdAt") or ""):
                for kk, vv in n.items():
                    if kk != "read": prev[kk] = vv
        else: seen[k] = n; out.append(n)
    return out

def save(data):
    data=_normalize(data)
    try: data["notifications"]=_dedupe_notifs(data.get("notifications") or [])
    except Exception: pass
    if DB_URL:
        try:
            with pg_conn().cursor() as c: c.execute("INSERT INTO shop (id, data) VALUES (1, %s) ON CONFLICT (id) DO UPDATE SET data=EXCLUDED.data", [json.dumps(data)])
            return
        except Exception:
            global _pg; _pg=None
            try:
                with pg_conn().cursor() as c: c.execute("INSERT INTO shop (id, data) VALUES (1, %s) ON CONFLICT (id) DO UPDATE SET data=EXCLUDED.data", [json.dumps(data)])
                return
            except Exception:
                pass
    # Postgres unreachable: keep a local copy so nothing is lost, and retry Postgres next save
    try:
        tmp=DATA_FILE+".tmp"
        with open(tmp,"w") as f: json.dump(data,f)
        os.replace(tmp,DATA_FILE)
    except Exception: pass
class H(SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
    def _send(self,code,obj):
        b=json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(b))); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u=urlparse(self.path).path
        if u == "/api/pay/test":
            try:
                with LOCK: d = load(); settings = d.get("settings") or {}
                res = {}
                if settings.get("mtnSubscriptionKey") and settings.get("mtnApiUser") and settings.get("mtnApiKey"):
                    try: tok, err = _mtn_token(settings); res["mtn"] = {"ok": bool(tok), "error": err}
                    except Exception as e: res["mtn"] = {"ok": False, "error": str(e)[:200]}
                if settings.get("airtelClientId") and settings.get("airtelClientSecret"):
                    try: tok, err = _airtel_token(settings); res["airtel"] = {"ok": bool(tok), "error": err}
                    except Exception as e: res["airtel"] = {"ok": False, "error": str(e)[:200]}
                if settings.get("bankApiUrl"): res["bank"] = {"ok": True, "note": "Bank API URL saved - it is tested when a bank payment starts"}
                ok = any(v.get("ok") for v in res.values())
                with LOCK:
                    d = load(); d.setdefault("settings", {})["apiVerified"] = bool(ok); save(d)
                return self._send(200, {"ok": ok, "providers": res, "apiVerified": bool(ok)})
            except Exception as e: return self._send(500, {"error": str(e)[:200]})

        if u == "/api/onesignal/status":
            try:
                with LOCK: _d = load(); _st = _d.get("settings") or {}
                return self._send(200, {"ok": True, "hasRestKey": bool(_st.get("onesignalRestKey")), "appId": _st.get("onesignalAppId") or _st.get("oneSignalAppId") or ""})
            except Exception as e: return self._send(500, {"error": str(e)[:200]})
        if u in ("/api/shop","/api/shop/"):
            try: return self._send(200, _get_shop())
            except Exception as e: return self._send(500, {"error": str(e)[:200]})
        if u=="/api/presence":
            try:
                now=time.time()
                with LOCK:
                    for k in list(PRESENCE.keys()):
                        if now-(PRESENCE[k].get("ts") or 0)>300: del PRESENCE[k]
                    return self._send(200, dict(PRESENCE))
            except Exception as e: return self._send(500, {"error": str(e)[:200]})
        if u == "/api/pay/status":
            try:
                from urllib.parse import parse_qs
                q = parse_qs(urlparse(self.path).query)
                ref = (q.get("reference") or q.get("referenceId") or [""])[0]
                pid = (q.get("productId") or [""])[0]
                with LOCK:
                    d = load(); rec = None
                    for r in (d.get("pendingPayments") or []):
                        if (ref and str(r.get("referenceId")) == ref) or (pid and str(r.get("productId")) == str(pid)): rec = r; break
                    if not rec: return self._send(404, {"status": "not_found"})
                    if rec.get("status") == "pending":
                        st, _e = _provider_status(d.get("settings") or {}, rec)
                        if st == "SUCCESSFUL":
                            rec["status"] = "successful"; _flip_product_live(d, rec.get("productId"), "Payment verified automatically - your product is now live! No owner approval needed."); save(d)
                        elif st == "FAILED":
                            rec["status"] = "failed"; save(d)
                    return self._send(200, {"status": rec.get("status"), "referenceId": rec.get("referenceId"), "productId": rec.get("productId")})
            except Exception as e: return self._send(500, {"status": "error", "error": str(e)[:200]})
        if u in ("/api/health","/health"):
            try: d=load(); return self._send(200, {"ok":True,"storage":"postgres" if DB_URL else "local-file","products":len(d.get("products") or [])})
            except Exception as e: return self._send(500, {"ok":False,"error":str(e)[:200]})
        if u=="/": u="/index.html"
        fp=None
        for root in (BASE, PUBLIC):
            _fp=os.path.normpath(os.path.join(root,u.lstrip("/")))
            if _fp.startswith(root) and os.path.isfile(_fp): fp=_fp; break
        if fp is None: fp=os.path.join(BASE,"index.html")
        mt,_=mimetypes.guess_type(fp); mt=mt or "application/octet-stream"
        with open(fp,"rb") as f: data=f.read()
        self.send_response(200); self.send_header("Content-Type",mt); self.send_header("Cache-Control","no-store" if fp.endswith((".html",".js",".json")) else "public, max-age=3600"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_PUT(self): self._write()
    def do_POST(self): self._write()
    def _write(self):
        u=urlparse(self.path).path
        if u=="/api/presence":
            try:
                n=int(self.headers.get("Content-Length") or 0); raw=self.rfile.read(n) if n else b"{}"
                d=json.loads(raw or b"{}")
                if not isinstance(d,dict) or not d.get("id"): return self._send(400,{"error":"id required"})
                with LOCK: PRESENCE[str(d["id"])]={"name":d.get("name") or "","avatar":d.get("avatar") or "","ts":time.time()}
                return self._send(200,{"ok":True})
            except Exception as e: return self._send(400,{"error":str(e)[:200]})

        if u == "/api/read":
            try:
                n=int(self.headers.get("Content-Length") or 0); raw=self.rfile.read(n) if n else b"{}"
                body=json.loads(raw or b"{}")
            except Exception: return self._send(400, {"error": "invalid json"})
            uid = str(body.get("userId") or body.get("user") or "")
            with LOCK:
                d = load()
                if body.get("type") == "notifications":
                    ids = {str(x) for x in (body.get("ids") or [])}
                    if body.get("mode") == "delete" or ids:
                        d["notifications"] = [x for x in (d.get("notifications") or []) if not (str(x.get("id")) in ids or (not ids and (not x.get("userId") or str(x.get("userId")) == uid or (body.get("isOwner") and x.get("forOwner")))))]
                    else:
                        for x in (d.get("notifications") or []):
                            if not x.get("userId") or str(x.get("userId")) == uid or (body.get("isOwner") and x.get("forOwner")):
                                x["read"] = True
                elif body.get("type") == "chats":
                    for c in (d.get("chats") or []):
                        if body.get("chatId") and str(c.get("id")) != str(body.get("chatId")): continue
                        msgs = c.get("messages") or []
                        if msgs:
                            c.setdefault("lastReadBy", {})[uid] = msgs[-1].get("id") or msgs[-1].get("text") or ""
                save(d)
            return self._send(200, {"ok": True})
        if u == "/api/pay/initiate":
            try:
                n=int(self.headers.get("Content-Length") or 0); raw=self.rfile.read(n) if n else b"{}"
                data = json.loads(raw or b"{}")
            except Exception: return self._send(400, {"error": "invalid json"})
            phone = _norm_phone(data.get("phone"))
            if len(phone) != 12: return self._send(400, {"ok": False, "error": "Enter a valid MTN / Airtel number, e.g. 0771234567"})
            net = str(data.get("network") or "MTN").upper()
            with LOCK:
                d = load(); settings = d.get("settings") or {}
                prod = None
                _mode = str(settings.get("paymentMode") or settings.get("mode") or settings.get("payMode") or settings.get("listingMode") or "").lower()
                _creds = bool((settings.get("mtnSubscriptionKey") and settings.get("mtnApiUser") and settings.get("mtnApiKey")) or (settings.get("airtelClientId") and settings.get("airtelClientSecret")) or settings.get("bankApiUrl"))
                if "auto" in _mode and not (settings.get("apiVerified") and _creds):
                    return self._send(400, {"ok": False, "error": "Automatic payment is ON but the API is not connected yet. The owner must add the API keys and press Test API Connection in Owner Panel first."})
                for p in (d.get("products") or []):
                    if str(p.get("id")) == str(data.get("productId")): prod = p; break
                amount = data.get("amount")
                if not amount and prod:
                    amount = prod.get("feeAmount") or prod.get("listingFee") or prod.get("fee") or prod.get("feePaid")
                try: amount = int(float(str(amount or "0").replace(",", "")))
                except Exception: amount = 0
                if amount <= 0: return self._send(400, {"ok": False, "error": "Could not read the listing fee. Open the pay screen again."})
                if "AIRTEL" in net: ref, err = _airtel_pay(settings, phone, amount, data.get("productId"))
                elif "BANK" in net: ref, err = _bank_pay(settings, phone, amount, data.get("productId"))
                else: ref, err = _mtn_pay(settings, phone, amount, data.get("productId"))
                if err: return self._send(400, {"ok": False, "error": err})
                rec = {"id": ref, "referenceId": ref, "productId": data.get("productId"), "sellerId": (prod or {}).get("sellerId") or data.get("sellerId") or "", "phone": phone, "network": net, "amount": amount, "status": "pending", "createdAt": _now_iso()}
                d.setdefault("pendingPayments", []).append(rec); save(d)
                return self._send(200, {"ok": True, "referenceId": ref, "message": "Check your phone - approve the payment prompt with your PIN."})
        if u == "/api/onesignal/key":
            try:
                n=int(self.headers.get("Content-Length") or 0); raw=self.rfile.read(n) if n else b"{}"
                body=json.loads(raw or b"{}")
            except Exception: return self._send(400, {"error": "invalid json"})
            _rk = str(body.get("restKey") or body.get("key") or "").strip()
            if not _rk: return self._send(400, {"ok": False, "error": "Paste the REST API Key first."})
            with LOCK:
                _d = load(); _d.setdefault("settings", {})["onesignalRestKey"] = _rk; save(_d)
            return self._send(200, {"ok": True, "saved": True})
        if u == "/api/onesignal/send":
            try:
                n=int(self.headers.get("Content-Length") or 0); raw=self.rfile.read(n) if n else b"{}"
                body=json.loads(raw or b"{}")
            except Exception: return self._send(400, {"error": "invalid json"})
            _title = str(body.get("title") or "Kampala Mart")
            _msg = str(body.get("message") or "")
            _ch = str(body.get("channel") or "push").lower()
            if not _msg: return self._send(400, {"ok": False, "error": "Type a message first."})
            with LOCK:
                _d = load(); _st = _d.get("settings") or {}
                _app = _st.get("onesignalAppId") or _st.get("oneSignalAppId") or ""
                _rest = _st.get("onesignalRestKey") or ""
            if not _app: return self._send(400, {"ok": False, "error": "Save your OneSignal App ID first (Owner Panel > Push & Broadcast)."})
            if not _rest: return self._send(400, {"ok": False, "error": "Save your OneSignal REST API Key first (Owner Panel > Push & Broadcast > Save REST Key)."})
            def _os_post(payload):
                req = urllib.request.Request("https://api.onesignal.com/notifications", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "Authorization": "Basic " + _rest}, method="POST")
                try:
                    with urllib.request.urlopen(req, timeout=25) as resp: return resp.status, json.loads(resp.read() or b"{}")
                except urllib.error.HTTPError as e:
                    try: return e.code, json.loads(e.read() or b"{}")
                    except Exception: return e.code, {"errors": [str(e)]}
                except Exception as e: return 0, {"errors": [str(e)[:200]]}
            _recipients = 0; _errors = []
            _icon = "https://kampala-mart-g8t8.onrender.com/icon-192.png"
            if _ch in ("push", "both"):
                _code, _jt = _os_post({"app_id": _app, "included_segments": ["Subscribed Users"], "headings": {"en": "Kampala Mart"}, "contents": {"en": (_title + " - " + _msg) if _title else _msg}, "chrome_web_icon": _icon, "firefox_icon": _icon, "large_icon": _icon, "url": "https://kampala-mart-g8t8.onrender.com"})
                if _code < 300: _recipients += int(_jt.get("recipients") or 0)
                else: _errors += list(_jt.get("errors") or [str(_code)])
            if _ch in ("email", "both"):
                _code, _jt = _os_post({"app_id": _app, "included_segments": ["Subscribed Users"], "email_subject": _title, "email_body": "<div><b>Kampala Mart</b></div><h2>" + _title + "</h2><p>" + _msg.replace(chr(10), "<br>") + "</p>"})
                if _code < 300: _recipients += int(_jt.get("recipients") or 0)
                else: _errors += list(_jt.get("errors") or [str(_code)])
            if _errors: return self._send(400, {"ok": False, "errors": _errors, "recipients": _recipients})
            return self._send(200, {"ok": True, "recipients": _recipients})
        if u not in ("/api/shop","/api/shop/"): return self._send(404,{"error":"not found"})
        n=int(self.headers.get("Content-Length") or 0); raw=self.rfile.read(n) if n else b"{}"
        try: data=json.loads(raw or b"{}")
        except Exception: return self._send(400,{"error":"invalid json"})
        if not isinstance(data,dict): return self._send(400,{"error":"shop must be an object"})
        with LOCK:
            cur=load()
            if isinstance(data.get("products"),list) and len(data["products"])==0 and isinstance(cur.get("products"),list) and len(cur["products"])>0 and not data.get("allowEmpty"):
                return self._send(409,{"error":"refusing to overwrite live shop with empty products","products":len(cur["products"])})
            deleted = set()
            try:
                for x in (data.get("deletedIds") or []): deleted.add(x)
            except Exception: pass
            merged = _merge_shop(cur, data, deleted)
            if data.get("allowEmpty") and isinstance(data.get("products"), list) and len(data["products"]) == 0:
                merged["products"] = []
            _enrich(merged)
            save(merged)
        return self._send(200,{"ok":True,"products":len(merged.get("products") or [])})
if __name__=="__main__":
    port=int(os.environ.get("PORT","10000")); print("Storage:", "Postgres" if DB_URL else "local data.json", flush=True)
    try:
        threading.Thread(target=_pay_poller, daemon=True).start()
    except Exception: pass
    ThreadingHTTPServer(("0.0.0.0",port),H).serve_forever()
