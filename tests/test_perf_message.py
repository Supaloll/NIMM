"""
Script de diagnostic manuel — mesure le temps de réponse de NIMM en appelant
directement /api/chat/stream, sans passer par un navigateur (PC ou mobile).

Objectif : isoler le temps "pur serveur" du temps perçu côté client, pour
savoir si un ralentissement vient du pipeline NIMM, du réseau, ou du navigateur.

Usage : NIMM doit déjà tourner (py -m uvicorn main:app --port 8080).
    python tests/test_perf_message.py
    python tests/test_perf_message.py "Quelle est la capitale du Portugal ?"
"""
import sys
import time
import uuid
import getpass
import httpx

BASE_URL = "http://localhost:8080"
MESSAGE_DEFAUT = "Raconte-moi une blague courte."


def trouver_utilisateur():
    """Récupère le premier profil disponible (id) — comme le fait le frontend au login."""
    r = httpx.get(f"{BASE_URL}/api/users", timeout=10)
    r.raise_for_status()
    data = r.json()
    users = data.get("users", data) if isinstance(data, dict) else data
    if not users:
        raise RuntimeError("Aucun profil utilisateur trouvé sur ce NIMM.")
    return users[0]["id"]


def creer_fil(entetes):
    """Crée un fil de discussion temporaire pour le test."""
    r = httpx.post(f"{BASE_URL}/api/threads", json={"name": "test_perf"}, headers=entetes, timeout=10)
    r.raise_for_status()
    data = r.json()
    return data.get("id") or data.get("thread_id")


def deverrouiller_si_besoin(user_id, entetes):
    """Demande le PIN et récupère un jeton de déverrouillage si le profil est protégé.
    Le PIN n'est jamais écrit sur disque ni affiché à l'écran."""
    r = httpx.get(f"{BASE_URL}/api/users", timeout=10)
    r.raise_for_status()
    data = r.json()
    users = data.get("users", data) if isinstance(data, dict) else data
    profil = next((u for u in users if u["id"] == user_id), None)
    if not profil or not profil.get("has_pin"):
        return
    pin = getpass.getpass(f"[TEST] PIN pour le profil '{user_id}' : ")
    r = httpx.post(f"{BASE_URL}/api/users/{user_id}/unlock", json={"pin": pin}, timeout=10)
    r.raise_for_status()
    token = r.json().get("token", "")
    entetes["X-Unlock-Token"] = token
    print("[TEST] Session déverrouillée.")


def mesurer(message: str):
    user_id = trouver_utilisateur()
    entetes = {"X-User-ID": user_id}
    print(f"[TEST] Profil utilisé : {user_id}")
    deverrouiller_si_besoin(user_id, entetes)

    thread_id = creer_fil(entetes)
    print(f"[TEST] Fil créé : {thread_id}")
    print(f"[TEST] Message envoyé : {message!r}")
    print(f"[TEST] Démarrage à {time.strftime('%H:%M:%S')}")

    t_debut = time.perf_counter()
    t_premier_octet = None
    n_chunks = 0

    with httpx.stream(
        "POST",
        f"{BASE_URL}/api/chat/stream",
        json={"thread_id": thread_id, "message": message},
        headers=entetes,
        timeout=60.0,
    ) as r:
        r.raise_for_status()
        for ligne in r.iter_lines():
            if not ligne:
                continue
            if t_premier_octet is None:
                t_premier_octet = time.perf_counter()
                print(f"[TEST] Premier octet reçu après {t_premier_octet - t_debut:.2f}s")
            n_chunks += 1
            if ligne.startswith("data: [DONE]"):
                break

    t_fin = time.perf_counter()
    print(f"[TEST] Fin à {time.strftime('%H:%M:%S')}")
    print(f"[TEST] {n_chunks} morceaux reçus")
    print(f"[TEST] Temps total : {t_fin - t_debut:.2f}s")
    if t_premier_octet:
        print(f"[TEST] Temps jusqu'au 1er octet : {t_premier_octet - t_debut:.2f}s")
        print(f"[TEST] Temps de streaming (après 1er octet) : {t_fin - t_premier_octet:.2f}s")


def lister_fils():
    """Liste tous les fils du profil (authentifié), pour diagnostiquer les fils
    'invisibles' dans la sidebar sans passer par le navigateur."""
    user_id = trouver_utilisateur()
    entetes = {"X-User-ID": user_id}
    deverrouiller_si_besoin(user_id, entetes)

    r = httpx.get(f"{BASE_URL}/api/threads", headers=entetes, timeout=10)
    r.raise_for_status()
    fils = r.json()
    print(f"[TEST] {len(fils)} fil(s) trouvé(s) pour le profil '{user_id}' :\n")
    for f in fils:
        print(f"  - id={f.get('thread_id')}  mode={f.get('mode')!r}  "
              f"updated_at={f.get('updated_at')}  name={f.get('name')!r}")


def tester_titre(thread_id):
    """Appelle directement /api/threads/{id}/title et affiche la réponse brute —
    pour voir ce que le LLM renvoie vraiment pour la génération de titre."""
    user_id = trouver_utilisateur()
    entetes = {"X-User-ID": user_id}
    deverrouiller_si_besoin(user_id, entetes)

    contenu_test = "Raconte-moi une blague courte."
    print(f"[TEST] Appel POST /api/threads/{thread_id}/title avec content={contenu_test!r}")
    r = httpx.post(
        f"{BASE_URL}/api/threads/{thread_id}/title",
        json={"content": contenu_test},
        headers=entetes,
        timeout=30,
    )
    print(f"[TEST] Statut HTTP : {r.status_code}")
    print(f"[TEST] Corps brut  : {r.text!r}")


def reparer_fils_vides():
    """Redonne le placeholder '💬 Nouveau fil' à tous les fils au nom vide
    (dégât laissé par le bug du titre vide, avant le correctif)."""
    user_id = trouver_utilisateur()
    entetes = {"X-User-ID": user_id}
    deverrouiller_si_besoin(user_id, entetes)

    r = httpx.get(f"{BASE_URL}/api/threads", headers=entetes, timeout=10)
    r.raise_for_status()
    fils = r.json()
    casses = [f for f in fils if not (f.get("name") or "").strip()]
    if not casses:
        print("[TEST] Aucun fil au nom vide trouvé — rien à réparer.")
        return
    print(f"[TEST] {len(casses)} fil(s) à réparer :")
    for f in casses:
        tid = f["thread_id"]
        rr = httpx.patch(
            f"{BASE_URL}/api/threads/{tid}",
            json={"name": "💬 Nouveau fil"},
            headers=entetes,
            timeout=10,
        )
        statut = "OK" if rr.status_code == 200 else f"ERREUR {rr.status_code}"
        print(f"  - {tid} → {statut}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        lister_fils()
    elif len(sys.argv) > 2 and sys.argv[1] == "--title":
        tester_titre(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == "--repair":
        reparer_fils_vides()
    else:
        msg = sys.argv[1] if len(sys.argv) > 1 else MESSAGE_DEFAUT
        mesurer(msg)
