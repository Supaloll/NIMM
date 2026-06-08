# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')
import urllib.request, json, os

BASE = "http://localhost:8080"

def get(path, user_id=None):
    req = urllib.request.Request(f"{BASE}{path}")
    if user_id:
        req.add_header("X-User-ID", user_id)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}

print("\n" + "="*50)
print("  NIMM -- TEST MULTI-UTILISATEUR")
print("="*50)

# 1. Fichiers DB
print("\n[Fichiers DB dans data/]")
for candidate in ["data", "../data", "nimm/data"]:
    if os.path.exists(candidate):
        data_dir = candidate
        break
else:
    data_dir = "data"
if os.path.exists(data_dir):
    dbs = [f for f in os.listdir(data_dir) if f.endswith(".db") or f.endswith(".json")]
    for f in sorted(dbs):
        size = os.path.getsize(os.path.join(data_dir, f))
        ok = f.startswith('nimm_') or f == 'users.json'
        print(f"  {'OK' if ok else '??'} {f} ({size} octets)")
else:
    print("  ?? Dossier data/ non trouve")

# 2. Liste utilisateurs
print("\n[/api/users]")
users = get("/api/users")
if isinstance(users, list):
    for u in users:
        print(f"  OK {u.get('emoji','?')} {u.get('name','?')} (id={u.get('id','?')}, admin={u.get('admin',False)})")
else:
    print(f"  ERR {users}")

# 3. Isolation DB -- fils par utilisateur
print("\n[Isolation DB (fils par profil)]")
seen = set()
for uid in ["laurent"] + [u.get("id") for u in (users if isinstance(users, list) else []) if u.get("id") != "laurent"]:
    if uid in seen or uid is None:
        continue
    seen.add(uid)
    threads = get("/api/threads", user_id=uid)
    if isinstance(threads, list):
        print(f"  OK [{uid}] -> {len(threads)} fil(s)")
    else:
        print(f"  ERR [{uid}] -> {threads}")

# 4. Cles globales
print("\n[Cles globales]")
gkeys = get("/api/settings/global-keys", user_id="laurent")
if isinstance(gkeys, dict):
    for p, has in gkeys.items():
        print(f"  {'OK' if has else 'NO'} {p}")
else:
    print(f"  ERR {gkeys}")

# 5. Mode serveur
print("\n[Mode serveur]")
sm = get("/api/settings/server-mode", user_id="laurent")
if sm.get('enabled'):
    print(f"  OK Active")
else:
    print(f"  NO Desactive (watchdog actif)")

print("\n" + "="*50 + "\n")
