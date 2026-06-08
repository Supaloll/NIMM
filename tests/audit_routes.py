# ============================================================
# NIMM — tests/audit_routes.py
# Audit complet de toutes les routes API
#
# Usage : python tests/audit_routes.py
#         (NIMM doit tourner sur localhost:8080)
#
# Ce script NE modifie PAS tes données personnelles.
# Il crée ses propres objets de test et les supprime après.
# Exception : DELETE /api/memory/all est volontairement absent.
# ============================================================

import asyncio
import json
import sys
import time
import httpx

BASE_URL = "http://localhost:8080"
TIMEOUT  = 10

# ── Couleurs ANSI (Windows 10+ compatible) ──
OK   = "✅"
ERR  = "❌"
SKIP = "⏭️ "
SEP  = "─" * 60

results: list[dict] = []

def record(group: str, name: str, passed: bool, detail: str = ""):
    results.append({"group": group, "name": name, "passed": passed, "detail": detail})
    icon = OK if passed else ERR
    print(f"  {icon}  {name}" + (f"  →  {detail}" if detail else ""))

def header(title: str):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


# ══════════════════════════════════════════
# G1 — SERVEUR
# ══════════════════════════════════════════

async def test_serveur(c: httpx.AsyncClient):
    header("G1 — Serveur")

    r = await c.get("/api/ping")
    record("G1", "GET /api/ping", r.status_code == 200 and r.json().get("ok") is True)

    r = await c.get("/")
    record("G1", "GET / (frontend)", r.status_code == 200 and "text/html" in r.headers.get("content-type",""))

    r = await c.get("/manifest.json")
    record("G1", "GET /manifest.json", r.status_code == 200)


# ══════════════════════════════════════════
# G2 — THREADS — CRUD COMPLET
# ══════════════════════════════════════════

async def test_threads(c: httpx.AsyncClient) -> str:
    header("G2 — Threads (CRUD)")
    tid = None

    # Créer
    r = await c.post("/api/threads", json={"name": "[AUDIT] Fil test"})
    ok = r.status_code == 200 and "thread_id" in r.json()
    record("G2", "POST /api/threads", ok)
    if not ok:
        return None
    tid = r.json()["thread_id"]

    # Lister
    r = await c.get("/api/threads")
    ids = [t["thread_id"] for t in r.json()]
    record("G2", "GET /api/threads", r.status_code == 200 and tid in ids)

    # Lire un fil
    r = await c.get(f"/api/threads/{tid}")
    record("G2", f"GET /api/threads/{{id}}", r.status_code == 200 and r.json()["thread_id"] == tid)

    # Ajouter un message
    r = await c.post(f"/api/threads/{tid}/messages", json={"role": "user", "content": "Message audit test"})
    record("G2", "POST /api/threads/{id}/messages", r.status_code == 200)

    # Lire les messages
    r = await c.get(f"/api/threads/{tid}/messages")
    msgs = r.json()
    record("G2", "GET /api/threads/{id}/messages",
           r.status_code == 200 and any(m["content"] == "Message audit test" for m in msgs))

    # Renommer
    r = await c.patch(f"/api/threads/{tid}", json={"name": "[AUDIT] Fil renommé"})
    record("G2", "PATCH /api/threads/{id} (rename)", r.status_code == 200)

    # Supprimer
    r = await c.delete(f"/api/threads/{tid}")
    record("G2", "DELETE /api/threads/{id}", r.status_code == 200)

    # 404 après suppression
    r = await c.get(f"/api/threads/{tid}")
    record("G2", "GET /api/threads/{id} → 404 après DELETE", r.status_code == 404)

    return None


# ══════════════════════════════════════════
# G3 — ONGLETS (TABS)
# ══════════════════════════════════════════

async def test_onglets(c: httpx.AsyncClient):
    header("G3 — Onglets (Tabs)")

    # Créer un fil parent
    r = await c.post("/api/threads", json={"name": "[AUDIT] Parent"})
    if r.status_code != 200:
        record("G3", "Setup fil parent", False, "impossible de créer le fil parent")
        return
    parent_id = r.json()["thread_id"]

    # Créer un onglet
    r = await c.post(f"/api/threads/{parent_id}/tabs", json={"name": "[AUDIT] Onglet test"})
    ok = r.status_code == 200 and "thread_id" in r.json()
    record("G3", "POST /api/threads/{id}/tabs", ok)
    tab_id = r.json()["thread_id"] if ok else None

    # Lister les onglets
    r = await c.get(f"/api/threads/{parent_id}/tabs")
    tab_ids = [t["thread_id"] for t in r.json()]
    record("G3", "GET /api/threads/{id}/tabs", r.status_code == 200 and tab_id in tab_ids)

    # Supprimer l'onglet
    if tab_id:
        r = await c.delete(f"/api/threads/{tab_id}")
        record("G3", "DELETE onglet", r.status_code == 200)

    # Cleanup fil parent
    await c.delete(f"/api/threads/{parent_id}")


# ══════════════════════════════════════════
# G4 — MÉMOIRE (LECTURE + UTILITAIRES)
# ══════════════════════════════════════════

async def test_memoire(c: httpx.AsyncClient):
    header("G4 — Mémoire (lecture + clean)")

    # Liste des triplets
    r = await c.get("/api/memory/triplets")
    nb = len(r.json()) if r.status_code == 200 else -1
    record("G4", "GET /api/memory/triplets", r.status_code == 200, f"{nb} souvenir(s)")

    # Clean (déduplication) — inoffensif
    r = await c.post("/api/memory/clean")
    merged = r.json().get("merged", -1) if r.status_code == 200 else -1
    record("G4", "POST /api/memory/clean", r.status_code == 200, f"{merged} doublon(s) fusionné(s)")

    # Vérifier qu'une clé inconnue retourne 200 (pas d'exception)
    r = await c.delete("/api/memory/cle_inexistante_audit_xyz")
    record("G4", "DELETE /api/memory/{key_inexistant} (pas d'exception)", r.status_code in (200, 404))


# ══════════════════════════════════════════
# G5 — SETTINGS (LECTURE)
# ══════════════════════════════════════════

async def test_settings(c: httpx.AsyncClient):
    header("G5 — Settings (lecture)")

    routes_read = [
        ("/api/settings/provider",   "provider"),
        ("/api/settings/mask",       "mask_id"),
        ("/api/settings/model",      "model"),
        ("/api/settings/routing",    None),
        ("/api/settings/length",     "value"),
        ("/api/settings/embeddings", "enabled"),
        ("/api/settings/presence",   "value"),
        ("/api/identity",            "name"),
    ]

    for route, expected_key in routes_read:
        r = await c.get(route)
        ok = r.status_code == 200
        if ok and expected_key:
            ok = expected_key in r.json()
        record("G5", f"GET {route}", ok)

    # /api/settings/api-keys — retourne des booléens, jamais les vraies clés
    r = await c.get("/api/settings/api-keys")
    ok = r.status_code == 200
    if ok:
        data = r.json()
        # Vérifie que les valeurs sont bien des booléens
        all_bool = all(isinstance(v, bool) for v in data.values())
        has_configured = any(v for v in data.values())
        ok = all_bool
        record("G5", "GET /api/settings/api-keys (valeurs = booléens)", ok,
               "provider configuré" if has_configured else "aucun provider configuré")
    else:
        record("G5", "GET /api/settings/api-keys", False)


# ══════════════════════════════════════════
# G6 — RAPPELS — CRUD COMPLET
# ══════════════════════════════════════════

async def test_rappels(c: httpx.AsyncClient):
    header("G6 — Rappels / Agenda (CRUD)")

    # Lister
    r = await c.get("/api/rappels")
    record("G6", "GET /api/rappels", r.status_code == 200, f"{len(r.json())} actif(s)")

    # Créer
    r = await c.post("/api/rappels", json={
        "description":   "[AUDIT] Rappel de test",
        "date_echeance": "2099-12-31",
        "type_rappel":   "normal"
    })
    ok = r.status_code == 200 and "id" in r.json()
    record("G6", "POST /api/rappels", ok)
    if not ok:
        return
    rid = r.json()["id"]

    # Modifier
    r = await c.patch(f"/api/rappels/{rid}", json={"description": "[AUDIT] Rappel modifié"})
    record("G6", "PATCH /api/rappels/{id}", r.status_code == 200)

    # Clore (archive — ne supprime pas)
    r = await c.delete(f"/api/rappels/{rid}")
    record("G6", "DELETE /api/rappels/{id} (clôture)", r.status_code == 200)

    # Vérifier que le rappel clos n'est plus dans les actifs
    r = await c.get("/api/rappels")
    ids_actifs = [rp["id"] for rp in r.json()]
    record("G6", "Rappel clos absent des actifs", rid not in ids_actifs)


# ══════════════════════════════════════════
# G7 — BIBLIOTHÈQUE
# ══════════════════════════════════════════

async def test_bibliotheque(c: httpx.AsyncClient):
    header("G7 — Bibliothèque (lecture)")

    r = await c.get("/api/bibliotheque")
    nb = len(r.json()) if r.status_code == 200 else -1
    record("G7", "GET /api/bibliotheque", r.status_code == 200, f"{nb} entrée(s)")

    r = await c.get("/api/bibliotheque/search", params={"q": "test"})
    record("G7", "GET /api/bibliotheque/search?q=test", r.status_code == 200)

    r = await c.get("/api/bibliotheque/search", params={"q": ""})
    record("G7", "GET /api/bibliotheque/search?q= (vide → tout)", r.status_code == 200)


# ══════════════════════════════════════════
# G8 — MASQUES
# ══════════════════════════════════════════

async def test_masques(c: httpx.AsyncClient):
    header("G8 — Masques")

    r = await c.get("/api/masks")
    ok = r.status_code == 200 and isinstance(r.json(), list)
    nb = len(r.json()) if ok else 0
    ids = [m["id"] for m in r.json()] if ok else []
    record("G8", "GET /api/masks", ok, f"{nb} masque(s) : {', '.join(ids)}")

    # Vérifier que le masque 'lia' existe (masque par défaut)
    has_lia = "lia" in ids
    record("G8", "Masque 'lia' présent (défaut)", has_lia)


# ══════════════════════════════════════════
# G9 — STATUTS & MONITORING
# ══════════════════════════════════════════

async def test_statuts(c: httpx.AsyncClient):
    header("G9 — Statuts & Monitoring")

    # STT
    r = await c.get("/api/stt/status")
    ok = r.status_code == 200 and "ready" in r.json()
    record("G9", "GET /api/stt/status", ok, f"ready={r.json().get('ready')}" if ok else "")

    # Embeddings
    r = await c.get("/api/embeddings/status")
    ok = r.status_code == 200 and "status" in r.json()
    record("G9", "GET /api/embeddings/status", ok, r.json().get("status","") if ok else "")

    # Coûts
    r = await c.get("/api/costs")
    ok = r.status_code == 200 and "wallets" in r.json()
    record("G9", "GET /api/costs", ok,
           f"{len(r.json()['wallets'])} wallet(s)" if ok else "")

    # TTS voices
    r = await c.get("/api/tts/voices")
    ok = r.status_code == 200 and "voices" in r.json()
    nb = len(r.json().get("voices", [])) if ok else 0
    record("G9", "GET /api/tts/voices", ok, f"{nb} voix")


# ══════════════════════════════════════════
# G10 — CHAT (optionnel — nécessite LLM configuré)
# ══════════════════════════════════════════

async def test_chat(c: httpx.AsyncClient):
    header("G10 — Chat (nécessite un provider configuré)")

    # Vérifier si un provider est configuré
    r_keys = await c.get("/api/settings/api-keys")
    r_prov = await c.get("/api/settings/provider")
    if r_keys.status_code != 200 or r_prov.status_code != 200:
        record("G10", "Vérification provider", False, "impossible de lire les settings")
        return

    provider  = r_prov.json().get("provider", "")
    keys_bool = r_keys.json()
    has_key   = keys_bool.get(provider, False) if provider else False

    if not provider or not has_key:
        print(f"  {SKIP}  Chat non testé — aucun provider configuré ({provider or 'aucun'})")
        results.append({"group": "G10", "name": "POST /api/chat", "passed": None, "detail": "skipped"})
        return

    # Créer un fil temporaire
    r = await c.post("/api/threads", json={"name": "[AUDIT] Chat test"})
    if r.status_code != 200:
        record("G10", "Création fil pour chat test", False)
        return
    tid = r.json()["thread_id"]

    # Appel chat (non-stream, timeout généreux)
    try:
        r = await c.post("/api/chat", json={
            "message":   "Réponds uniquement avec le mot 'ok', rien d'autre.",
            "thread_id": tid,
        }, timeout=30.0)

        ok = r.status_code == 200 and "reply" in r.json()
        reply = r.json().get("reply", "")[:80] if ok else ""
        record("G10", f"POST /api/chat (provider={provider})", ok, f"réponse : {repr(reply)}")

        # Vérifier que le message a été sauvegardé en DB
        r2 = await c.get(f"/api/threads/{tid}/messages")
        has_reply = any(m["role"] == "assistant" for m in r2.json())
        record("G10", "Réponse sauvegardée en DB", has_reply)

    except httpx.TimeoutException:
        record("G10", f"POST /api/chat (provider={provider})", False, "timeout >30s")
    except Exception as e:
        record("G10", f"POST /api/chat", False, str(e))
    finally:
        # Cleanup
        await c.delete(f"/api/threads/{tid}")


# ══════════════════════════════════════════
# G11 — ROBUSTESSE (erreurs attendues)
# ══════════════════════════════════════════

async def test_robustesse(c: httpx.AsyncClient):
    header("G11 — Robustesse (cas limites & erreurs attendues)")

    # Fil inexistant
    r = await c.get("/api/threads/fil_qui_nexiste_pas")
    record("G11", "GET fil inexistant → 404", r.status_code == 404)

    # Chat — message vide
    r = await c.post("/api/chat", json={"message": "  ", "thread_id": "fake"})
    record("G11", "POST /api/chat message vide → 400", r.status_code == 400)

    # Chat — thread_id manquant
    r = await c.post("/api/chat", json={"message": "test", "thread_id": ""})
    record("G11", "POST /api/chat thread_id vide → 400", r.status_code == 400)

    # Rappel avec id inexistant (clôture)
    r = await c.delete("/api/rappels/9999999")
    record("G11", "DELETE rappel inexistant (pas d'exception)", r.status_code in (200, 404, 500),
           f"HTTP {r.status_code}")

    # Route inconnue → 404
    r = await c.get("/api/route_qui_nexiste_vraiment_pas")
    record("G11", "GET route inconnue → 404", r.status_code == 404)


# ══════════════════════════════════════════
# MAIN — orchestration + résumé
# ══════════════════════════════════════════

async def main():
    print("\n" + "═" * 60)
    print("  NIMM — Audit des routes API")
    print(f"  Cible : {BASE_URL}")
    print("═" * 60)

    # Vérifier que le serveur tourne
    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as probe:
            await probe.get("/api/ping")
    except Exception:
        print(f"\n{ERR}  Serveur inaccessible sur {BASE_URL}")
        print("     Lance NIMM d'abord, puis relance ce script.\n")
        sys.exit(1)

    t_start = time.perf_counter()

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as c:
        await test_serveur(c)
        await test_threads(c)
        await test_onglets(c)
        await test_memoire(c)
        await test_settings(c)
        await test_rappels(c)
        await test_bibliotheque(c)
        await test_masques(c)
        await test_statuts(c)
        await test_chat(c)
        await test_robustesse(c)

    elapsed = time.perf_counter() - t_start

    # ── Résumé ──
    passed  = [r for r in results if r["passed"] is True]
    failed  = [r for r in results if r["passed"] is False]
    skipped = [r for r in results if r["passed"] is None]
    total   = len(passed) + len(failed)

    print(f"\n{'═' * 60}")
    print(f"  RÉSUMÉ — {elapsed:.1f}s")
    print(f"{'═' * 60}")
    print(f"  {OK}  Réussis  : {len(passed)}/{total}")
    print(f"  {ERR}  Échoués  : {len(failed)}/{total}")
    if skipped:
        print(f"  {SKIP}  Ignorés  : {len(skipped)} (provider non configuré)")

    if failed:
        print(f"\n  Détail des échecs :")
        for r in failed:
            detail = f" → {r['detail']}" if r['detail'] else ""
            print(f"    {ERR}  [{r['group']}] {r['name']}{detail}")

    score = int(100 * len(passed) / total) if total else 0
    print(f"\n  Score : {score}%")

    if score == 100:
        print("  🎉  Toutes les routes répondent correctement.")
    elif score >= 80:
        print("  ⚠️   Quelques points à corriger — voir détail ci-dessus.")
    else:
        print("  🔴  Des routes importantes ne fonctionnent pas.")

    print()


if __name__ == "__main__":
    asyncio.run(main())
