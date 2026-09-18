# ==========================================
#  BilHub AI Server v25.0 — Complete Edition
#  AI + Script Loader + Editor + Heartbeat
# ==========================================
import os, time, json, secrets, urllib.request, urllib.error, random, string
from functools import wraps
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# ═══════════════════════════════════════════════════════════
# 🔑 الإعدادات
# ═══════════════════════════════════════════════════════════
GITHUB_TOKEN  = os.environ.get("GH_TOKEN", "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")
GIST_ID       = os.environ.get("GIST_ID", "a0c2720ac59618401e818340a09d370a")
GIST_FILENAME = "bilhub.json"
EDITOR_PASSWORD = os.environ.get("EDITOR_PASS", "123")
PORT = int(os.environ.get("PORT", 5000))

system_state = {"started_at": time.time(), "storage_ready": False}
editor_sessions = {}
_cache = {"data": None, "time": 0}
_heartbeats = {}
_CACHE_TTL = 3

app = Flask(__name__, static_folder='static')
CORS(app, resources={r"/*": {"origins": "*"}})

# ═══════════════════════════════════════════════════════════
# 💾 Gist Storage
# ═══════════════════════════════════════════════════════════
def gist_get():
    if _cache["data"] and time.time() - _cache["time"] < _CACHE_TTL:
        return _cache["data"]
    try:
        req = urllib.request.Request(f"https://api.github.com/gists/{GIST_ID}")
        req.add_header("User-Agent", "BilHub/1.0")
        req.add_header("Authorization", f"token {GITHUB_TOKEN}")
        with urllib.request.urlopen(req, timeout=15) as r:
            gist = json.loads(r.read().decode())
            data = json.loads(gist["files"][GIST_FILENAME]["content"])
            _cache["data"] = data
            _cache["time"] = time.time()
            system_state["storage_ready"] = True
            return data
    except Exception as e:
        print(f"⚠️ Gist read: {e}")
        return None

def gist_set(data):
    try:
        body = json.dumps({"files": {GIST_FILENAME: {"content": json.dumps(data, ensure_ascii=False)}}}).encode()
        req = urllib.request.Request(f"https://api.github.com/gists/{GIST_ID}", data=body, method="PATCH")
        req.add_header("User-Agent", "BilHub/1.0")
        req.add_header("Authorization", f"token {GITHUB_TOKEN}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        _cache["data"] = data
        _cache["time"] = time.time()
        system_state["storage_ready"] = True
        return True, None
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)

def get_data():
    d = gist_get() or {}
    for k in ["scripts", "sections", "users", "pending", "tracked"]:
        if k not in d: d[k] = {}
    if "bot_token" not in d: d["bot_token"] = ""
    if "admins" not in d: d["admins"] = []
    if "ai" not in d:
        d["ai"] = {"maps": {}, "users": {}, "live": {}}
    for k in ["maps", "users", "live"]:
        if k not in d["ai"]: d["ai"][k] = {}
    return d

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Editor-Token", "")
        if not token or token not in editor_sessions:
            return jsonify({"error": "unauthorized"}), 401
        if time.time() - editor_sessions[token] > 7200:
            del editor_sessions[token]
            return jsonify({"error": "expired"}), 401
        return f(*args, **kwargs)
    return wrapper

def sf(v, d=0, mn=0, mx=1000):
    try: return max(mn, min(mx, float(v)))
    except: return d

def si(v, d=0, mn=0, mx=1000000):
    try: return max(mn, min(mx, int(v)))
    except: return d

# ═══════════════════════════════════════════════════════════
# 🌐 Pages
# ═══════════════════════════════════════════════════════════
@app.route("/")
def home():
    return send_from_directory('static', 'ai_dashboard.html')

@app.route("/editor")
def editor_page():
    return send_from_directory('static', 'editor.html')

@app.route("/api/ping")
def api_ping():
    d = get_data()
    return jsonify({
        "ok": True,
        "message": "BilHub AI v25.0",
        "storage": system_state["storage_ready"],
        "scripts": len(d.get("scripts", {})),
        "maps": len(d["ai"]["maps"]),
        "users": len(d["ai"]["users"]),
        "online": len([v for v in d["ai"]["live"].values() if v.get("last_ping", 0) > time.time() - 90])
    })

# ═══════════════════════════════════════════════════════════
# 📜 Scripts Management
# ═══════════════════════════════════════════════════════════
@app.route("/api/scripts/list")
def api_scripts_list():
    d = get_data()
    scripts = []
    for sid, s in d.get("scripts", {}).items():
        if not s.get("enabled", True): continue
        scripts.append({
            "id": sid,
            "name": s.get("name", ""),
            "icon": s.get("icon", "📜"),
            "desc": s.get("desc", ""),
            "category": s.get("category", "عام"),
            "size": len(s.get("code", ""))
        })
    return jsonify({"ok": True, "scripts": scripts})

@app.route("/api/scripts/get/<sid>")
def api_scripts_get(sid):
    d = get_data()
    if sid not in d.get("scripts", {}):
        return jsonify({"ok": False, "error": "not_found"}), 404
    s = d["scripts"][sid]
    if not s.get("enabled", True):
        return jsonify({"ok": False, "error": "disabled"}), 403
    return jsonify({"ok": True, "code": s.get("code", ""), "name": s.get("name", ""), "id": sid})

@app.route("/api/scripts/save", methods=["POST"])
@require_auth
def api_scripts_save():
    req = request.get_json() or {}
    sid = req.get("id", "").strip()
    if not sid:
        sid = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    d = get_data()
    now = time.time()
    ex = d["scripts"].get(sid, {})
    d["scripts"][sid] = {
        "id": sid,
        "name": req.get("name", "سكربت جديد")[:60],
        "icon": req.get("icon", "📜")[:8],
        "desc": req.get("desc", "")[:200],
        "category": req.get("category", "عام")[:30],
        "code": req.get("code", ""),
        "enabled": bool(req.get("enabled", True)),
        "created": ex.get("created", now),
        "updated": now,
    }
    ok, err = gist_set(d)
    if ok:
        return jsonify({"ok": True, "id": sid})
    return jsonify({"ok": False, "error": err}), 500

@app.route("/api/scripts/delete", methods=["POST"])
@require_auth
def api_scripts_delete():
    req = request.get_json() or {}
    sid = req.get("id", "")
    d = get_data()
    if sid in d["scripts"]:
        del d["scripts"][sid]
        gist_set(d)
    return jsonify({"ok": True})

@app.route("/api/admin/scripts/all")
@require_auth
def api_admin_scripts_all():
    d = get_data()
    return jsonify({"ok": True, "scripts": d.get("scripts", {})})

@app.route("/api/admin/script/<sid>")
@require_auth
def api_admin_script(sid):
    d = get_data()
    if sid not in d.get("scripts", {}):
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "script": d["scripts"][sid]})

# ═══════════════════════════════════════════════════════════
# 💓 Heartbeat
# ═══════════════════════════════════════════════════════════
@app.route("/api/ai/heartbeat", methods=["POST"])
def api_ai_heartbeat():
    req = request.get_json() or {}
    uid = str(req.get("uid", ""))
    if not uid:
        return jsonify({"ok": False}), 400
    _heartbeats[uid] = time.time()
    return jsonify({"ok": True})

# ═══════════════════════════════════════════════════════════
# 📊 AI Report
# ═══════════════════════════════════════════════════════════
@app.route("/api/ai/report", methods=["POST"])
def api_ai_report():
    req = request.get_json() or {}
    uid = str(req.get("uid", ""))
    place_id = str(req.get("place_id", "0"))
    if not uid or place_id == "0":
        return jsonify({"ok": False, "error": "missing_data"}), 400

    name = str(req.get("name", "Unknown"))[:40]
    fps = sf(req.get("fps", 60), 60, 0, 500)
    ping = sf(req.get("ping", 50), 50, 0, 2000)
    zone = str(req.get("zone", "0_0_0"))[:30]
    pos = req.get("pos", [0, 0, 0])[:3]
    objects = si(req.get("objects", 0))
    mode = str(req.get("mode", "BALANCED"))[:20]
    ai_power = si(req.get("ai_power", 0), 0, 0, 100)
    device = req.get("device", {}) or {}
    game_name = str(req.get("game_name", ""))[:60]
    locked = si(req.get("locked", 0))
    zones_visited = req.get("zones_visited", [])
    scripts_loaded = si(req.get("scripts_loaded", 0))

    d = get_data()
    ai = d["ai"]
    now = time.time()

    if place_id not in ai["maps"]:
        ai["maps"][place_id] = {
            "name": game_name or f"Game_{place_id}",
            "zones": {},
            "global": {"fps_sum": 0, "ping_sum": 0, "samples": 0, "history": []},
            "last_updated": now, "peak_online": 0, "players_seen": 0
        }
    mp = ai["maps"][place_id]
    if game_name: mp["name"] = game_name
    mp["last_updated"] = now

    def update_zone(zk, zfps, zpos, zobj, zv=1):
        if zk not in mp["zones"]:
            mp["zones"][zk] = {"fps_sum": 0, "samples": 0, "objects": 0, "center": zpos}
        zz = mp["zones"][zk]
        zz["fps_sum"] += zfps * zv
        zz["samples"] += zv
        zz["objects"] = max(zz["objects"], zobj)
        zz["center"] = zpos
        avg = zz["fps_sum"] / zz["samples"]
        zz["avg_fps"] = round(avg, 1)
        zz["heavy"] = avg < 40
        zz["recommended_mode"] = "ECO" if avg < 30 else ("BALANCED" if avg < 50 else "TURBO")
        zz["severity"] = int(max(0, min(100, (60 - avg) * 2.5)))

    update_zone(zone, fps, pos, objects, 1)
    if isinstance(zones_visited, list):
        for zd in zones_visited[:50]:
            try:
                zk = str(zd.get("zone", ""))[:30]
                if not zk or zk == zone: continue
                zfps = sf(zd.get("avg_fps", 60), 60, 0, 500)
                zpos = zd.get("pos", pos)[:3]
                zobj = si(zd.get("objects", 0))
                zv = si(zd.get("visits", 1), 1, 1, 100)
                update_zone(zk, zfps, zpos, zobj, zv)
            except: pass

    g = mp["global"]
    g["fps_sum"] += fps; g["ping_sum"] += ping; g["samples"] += 1
    g["avg_fps"] = round(g["fps_sum"] / g["samples"], 1)
    g["avg_ping"] = round(g["ping_sum"] / g["samples"], 1)
    g.setdefault("history", []).append({"t": now, "fps": fps, "ping": ping, "online": 0})
    if len(g["history"]) > 60: g["history"] = g["history"][-60:]

    if uid not in ai["users"]:
        ai["users"][uid] = {
            "uid": uid, "name": name, "first_seen": now, "sessions": 1,
            "total_reports": 0, "games_played": {}, "device": {},
            "device_score": 0, "tier": "Unknown",
            "global_avg_fps": fps, "global_avg_ping": ping,
            "preferred_mode": mode, "total_zones_discovered": 0,
            "total_locked": 0, "total_scripts": 0,
        }
    up = ai["users"][uid]
    up["name"] = name; up["last_seen"] = now
    up["total_reports"] = up.get("total_reports", 0) + 1
    up["global_avg_fps"] = round(up.get("global_avg_fps", fps) * 0.9 + fps * 0.1, 1)
    up["global_avg_ping"] = round(up.get("global_avg_ping", ping) * 0.9 + ping * 0.1, 1)
    up["preferred_mode"] = mode
    up["total_locked"] = locked
    up["total_scripts"] = scripts_loaded

    if device:
        up["device"] = device
        score = 40
        ram = si(device.get("ram", 4), 4, 1, 128)
        cpu = str(device.get("cpu", "")).lower()
        gpu = str(device.get("gpu", "")).lower()
        if ram >= 16: score += 25
        elif ram >= 8: score += 15
        elif ram >= 4: score += 5
        if any(x in cpu for x in ["i9", "r9"]): score += 20
        elif any(x in cpu for x in ["i7", "r7"]): score += 14
        elif any(x in cpu for x in ["i5", "r5"]): score += 8
        if any(x in gpu for x in ["rtx 40", "rtx 30", "rx 6", "rx 7"]): score += 15
        elif any(x in gpu for x in ["rtx 20", "gtx 16", "rx 5"]): score += 8
        up["device_score"] = min(100, score)
        up["tier"] = "🔥 قوي" if score >= 75 else ("⚡ متوسط" if score >= 50 else "🐢 ضعيف")

    if "games_played" not in up: up["games_played"] = {}
    if place_id not in up["games_played"]:
        up["games_played"][place_id] = {
            "game_name": mp["name"], "first_played": now, "last_played": now,
            "total_reports": 0, "total_zones": {}, "zones_count": 0,
            "avg_fps": fps, "avg_ping": ping, "best_fps": fps, "worst_fps": fps,
            "total_locked": 0,
        }
    pg = up["games_played"][place_id]
    pg["last_played"] = now; pg["total_reports"] += 1
    pg["avg_fps"] = round(pg["avg_fps"] * 0.9 + fps * 0.1, 1)
    pg["avg_ping"] = round(pg["avg_ping"] * 0.9 + ping * 0.1, 1)
    pg["best_fps"] = max(pg.get("best_fps", fps), fps)
    pg["worst_fps"] = min(pg.get("worst_fps", fps), fps)
    pg["total_locked"] = locked

    def save_player_zone(zk, zfps, zpos, zobj):
        if zk not in pg["total_zones"]:
            pg["total_zones"][zk] = {
                "zone": zk, "pos": zpos, "first_seen": now, "last_seen": now,
                "visits": 0, "fps_sum": 0, "best_fps": zfps, "worst_fps": zfps,
                "objects": zobj, "avg_fps": zfps,
            }
            pg["zones_count"] = len(pg["total_zones"])
            up["total_zones_discovered"] = up.get("total_zones_discovered", 0) + 1
        pz = pg["total_zones"][zk]
        pz["visits"] += 1; pz["last_seen"] = now
        pz["fps_sum"] += zfps
        pz["avg_fps"] = round(pz["fps_sum"] / pz["visits"], 1)
        pz["best_fps"] = max(pz["best_fps"], zfps)
        pz["worst_fps"] = min(pz["worst_fps"], zfps)
        pz["objects"] = max(pz["objects"], zobj)

    save_player_zone(zone, fps, pos, objects)
    if isinstance(zones_visited, list):
        for zd in zones_visited[:50]:
            try:
                zk = str(zd.get("zone", ""))[:30]
                if not zk: continue
                save_player_zone(zk, sf(zd.get("avg_fps", 60), 60, 0, 500),
                                  zd.get("pos", pos)[:3], si(zd.get("objects", 0)))
            except: pass

    ai["live"][uid] = {
        "uid": uid, "name": name, "place_id": place_id, "game_name": mp["name"],
        "fps": fps, "ping": ping, "zone": zone, "pos": pos,
        "mode": mode, "ai_power": ai_power, "objects": objects, "locked": locked,
        "scripts": scripts_loaded,
        "last_ping": _heartbeats.get(uid, now), "tier": up.get("tier", "⚡ متوسط"),
    }
    cutoff = now - 90
    ai["live"] = {k: v for k, v in ai["live"].items() if v.get("last_ping", 0) > cutoff}

    current_online = sum(1 for v in ai["live"].values() if v["place_id"] == place_id)
    mp["peak_online"] = max(mp.get("peak_online", 0), current_online)
    mp["players_seen"] = sum(1 for u in ai["users"].values() if place_id in u.get("games_played", {}))
    if g["history"]: g["history"][-1]["online"] = current_online

    d["ai"] = ai
    gist_set(d)

    zz = mp["zones"].get(zone, {})
    return jsonify({
        "ok": True, "zone": zz,
        "recommended_mode": zz.get("recommended_mode", "BALANCED"),
        "is_heavy": zz.get("heavy", False),
        "server_recommendation": {
            "radius": 150 if zz.get("heavy") else 250,
            "lock_particles": zz.get("heavy", False),
            "lock_highlights": True,
            "quality": 1 if zz.get("heavy") else 3,
        }
    })

@app.route("/api/ai/stats")
def api_ai_stats():
    d = get_data()
    ai = d["ai"]
    now = time.time()
    live = dict(ai["live"])
    for hb_uid, hb_ts in _heartbeats.items():
        if hb_uid in live:
            live[hb_uid]["last_ping"] = hb_ts
    live = {k: v for k, v in live.items() if v.get("last_ping", 0) > now - 90}

    maps_summary = {}
    for pid, m in ai["maps"].items():
        zones_list = list(m.get("zones", {}).values())
        heavy = [z for z in zones_list if z.get("heavy")]
        maps_summary[pid] = {
            "name": m["name"],
            "avg_fps": m["global"].get("avg_fps", 0),
            "avg_ping": m["global"].get("avg_ping", 0),
            "samples": m["global"].get("samples", 0),
            "zones_count": len(zones_list),
            "heavy_count": len(heavy),
            "peak_online": m.get("peak_online", 0),
            "players_seen": m.get("players_seen", 0),
            "last_updated": m.get("last_updated", 0),
            "online": sum(1 for v in live.values() if v["place_id"] == pid),
            "history": m["global"].get("history", [])[-30:]
        }

    users_list = []
    for uid, u in ai["users"].items():
        games = u.get("games_played", {})
        users_list.append({
            "uid": uid, "name": u.get("name", "?"),
            "first_seen": u.get("first_seen", 0), "last_seen": u.get("last_seen", 0),
            "sessions": u.get("sessions", 1), "total_reports": u.get("total_reports", 0),
            "avg_fps": u.get("global_avg_fps", 0), "avg_ping": u.get("global_avg_ping", 0),
            "device": u.get("device", {}), "device_score": u.get("device_score", 0),
            "tier": u.get("tier", "Unknown"),
            "total_zones": u.get("total_zones_discovered", 0),
            "total_locked": u.get("total_locked", 0),
            "total_scripts": u.get("total_scripts", 0),
            "games_count": len(games), "games_list": list(games.keys())[:10],
        })
    users_list.sort(key=lambda x: x.get("last_seen", 0), reverse=True)

    all_zones = [z for m in ai["maps"].values() for z in m.get("zones", {}).values()]
    avg_fps = round(sum(m["global"].get("avg_fps", 0) for m in ai["maps"].values()) / max(1, len(ai["maps"])), 1)

    return jsonify({
        "ok": True,
        "summary": {
            "total_maps": len(ai["maps"]),
            "total_users": len(ai["users"]),
            "online_now": len(live),
            "total_zones": len(all_zones),
            "heavy_zones": sum(1 for z in all_zones if z.get("heavy")),
            "avg_global_fps": avg_fps,
            "total_player_zones": sum(u.get("total_zones_discovered", 0) for u in ai["users"].values()),
            "total_scripts": len(d.get("scripts", {})),
        },
        "maps": maps_summary, "live": live, "users": users_list[:200]
    })

@app.route("/api/ai/zones/<place_id>")
def api_ai_zones(place_id):
    d = get_data()
    if place_id not in d["ai"]["maps"]:
        return jsonify({"ok": False}), 404
    return jsonify({"ok": True, "map": d["ai"]["maps"][place_id]})

@app.route("/api/ai/player/<uid>")
def api_ai_player(uid):
    d = get_data()
    if uid not in d["ai"]["users"]:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "player": d["ai"]["users"][uid]})

# ═══════════════════════════════════════════════════════════
# 🔐 Editor Login
# ═══════════════════════════════════════════════════════════
@app.route("/api/editor/login", methods=["POST"])
def api_editor_login():
    data = request.get_json() or {}
    if data.get("password", "") != EDITOR_PASSWORD:
        return jsonify({"ok": False, "error": "wrong"}), 401
    token = secrets.token_urlsafe(32)
    editor_sessions[token] = time.time()
    return jsonify({"ok": True, "token": token})

# ═══════════════════════════════════════════════════════════
# 🚀 Startup
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 BilHub AI v25.0 — Complete")
    print("=" * 60)
    d = gist_get()
    if d:
        print(f"✅ متصل | {len(d.get('scripts',{}))} سكربت | {len(d.get('ai',{}).get('maps',{}))} خرائط")
    print(f"🌐 Port: {PORT}")
    print("=" * 60)
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False, threaded=True)
