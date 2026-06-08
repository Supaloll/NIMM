"""
test_worker_memoire.py
──────────────────────
Valide le fonctionnement du worker mémoire async.

Principe :
  1. Vide la mémoire (sauf prenom) pour partir d'une base propre
  2. Envoie N messages avec des faits mémorisables clairs
  3. Vérifie que le LLM de chat n'émet PLUS de %%MEM%% dans ses réponses
  4. Attend 40s (cycle worker 30s + marge)
  5. Vérifie que les souvenirs ont bien été extraits dans /api/memory/triplets

Critère de succès :
  - 0 tag %%MEM%% dans les réponses du LLM de chat
  - Au moins SEUIL_MIN faits attendus présents en mémoire après le délai

Usage :
    python tests/test_worker_memoire.py
    python tests/test_worker_memoire.py --base-url http://192.168.1.x:8080
    python tests/test_worker_memoire.py --skip-clear   (conserve la mémoire existante)
"""

import asyncio
import argparse
import time
import httpx

BASE_URL  = "http://localhost:8080"
DELAI_S   = 40      # secondes d'attente pour le worker
SEUIL_MIN = 3       # nombre minimum de faits attendus pour passer le test

# ── Conversation avec des faits mémorisables variés ──────────────────────────
MESSAGES = [
    (
        "Bonjour ! Je m'appelle Laurent, je suis chauffeur poids lourd depuis quinze ans. "
        "Je fais des longues distances, souvent la nuit."
    ),
    (
        "Ma femme s'appelle Nadia. On a trois filles : Maïssane, Inès et Maya. "
        "Maïssane vient d'avoir ses résultats de brevet blanc — 14 de moyenne, on est fiers d'elle."
    ),
    (
        "J'habite à Ferrals-les-Corbières, dans l'Aude. Un petit village tranquille. "
        "J'ai un Volvo FH, c'est mon outil de travail depuis trois ans."
    ),
    (
        "J'aime beaucoup le MMA — je regarde tous les événements UFC dès que je peux. "
        "J'aime aussi la cuisine, surtout les plats du sud, le cassoulet, les grillades."
    ),
    (
        "Mon frère s'appelle Sébastien, il habite à Lyon. "
        "On se voit pas souvent mais on s'appelle régulièrement."
    ),
]

# ── Faits attendus en mémoire après le cycle worker ──────────────────────────
# Format : (label lisible, sujet partiel, prédicat attendu)
FAITS_ATTENDUS = [
    ("Métier de Laurent",        "laurent", "metier"),
    ("Conjoint de Laurent",      "laurent", "conjoint"),
    ("Enfant (Maïssane)",        "laurent", "enfant"),
    ("Domicile de Laurent",      "laurent", "domicile"),
    ("Frère Sébastien",          "laurent", "frere"),
    ("Goût MMA",                 "laurent", "aime"),
    ("Maïssane / études",        "maïssane", "etudes"),
]


# ─────────────────────────────────────────────────────────────────────────────

async def clear_memory(client: httpx.AsyncClient):
    """Vide la mémoire via /api/memory/all (sauf prenom — géré par clear_memory.py)."""
    print("[SETUP] Vidage mémoire via DELETE /api/memory/all ...")
    try:
        resp = await client.delete(f"{BASE_URL}/api/memory/all", timeout=15.0)
        resp.raise_for_status()
        print("[SETUP] Mémoire vidée.")
    except Exception as e:
        print(f"[SETUP] ⚠️  Impossible de vider la mémoire : {e}")
        print("         Continuer avec la mémoire existante.")


async def send_message(client: httpx.AsyncClient, thread_id: str,
                       message: str, idx: int) -> str:
    print(f"\n{'─'*60}")
    print(f"[MSG {idx+1}/{len(MESSAGES)}] → {message[:100]}{'...' if len(message) > 100 else ''}")

    resp = await client.post(
        f"{BASE_URL}/api/chat",
        json={"message": message, "thread_id": thread_id},
        timeout=90.0,
    )
    resp.raise_for_status()
    data   = resp.json()
    reply  = data.get("reply") or data.get("response") or str(data)

    print(f"[NIMM] {reply[:200]}{'...' if len(reply) > 200 else ''}")
    return reply


def check_no_mem_tags(replies: list[str]) -> tuple[bool, int]:
    """Vérifie qu'aucune réponse ne contient %%MEM:..."""
    count = 0
    for r in replies:
        if "%%MEM:" in r:
            count += 1
    return count == 0, count


async def get_memory(client: httpx.AsyncClient) -> list:
    """Récupère tous les triplets mémoire."""
    resp = await client.get(f"{BASE_URL}/api/memory/triplets", timeout=15.0)
    resp.raise_for_status()
    return resp.json()


def check_faits(memories: list) -> list[tuple]:
    """
    Pour chaque fait attendu, cherche une correspondance souple
    (sujet contient + prédicat exact ou contient).
    Retourne la liste des résultats : (label, found, valeur_trouvée).
    """
    results = []
    for label, sujet_partiel, predicat in FAITS_ATTENDUS:
        found = False
        valeur = ""
        for m in memories:
            s = (m.get("sujet") or "").lower()
            p = (m.get("predicat") or "").lower()
            v = (m.get("valeur") or "").lower()
            if sujet_partiel in s and predicat in p:
                found = True
                valeur = m.get("valeur") or ""
                break
        results.append((label, found, valeur))
    return results


def print_rapport(replies: list[str], results: list[tuple], elapsed: float):
    ok_mem, nb_mem_tags = check_no_mem_tags(replies)
    nb_found = sum(1 for _, f, _ in results if f)
    succes   = ok_mem and nb_found >= SEUIL_MIN

    print(f"\n{'═'*60}")
    print("RAPPORT — TEST WORKER MÉMOIRE")
    print(f"{'═'*60}\n")

    # ── Critère 1 : absence de %%MEM%% dans les réponses ──
    print("1. %%MEM%% absent des réponses LLM de chat :")
    if ok_mem:
        print("   ✅ Aucun tag %%MEM%% détecté — Path A bien retiré.")
    else:
        print(f"   ❌ {nb_mem_tags} réponse(s) contiennent encore %%MEM%% !")
        print("      → Vérifier build_system_prompt() dans hub.py.")

    # ── Critère 2 : faits extraits par le worker ──
    print(f"\n2. Faits extraits par le worker (délai d'attente : {elapsed:.0f}s) :")
    for label, found, valeur in results:
        mark = "✅" if found else "❌"
        detail = f" → '{valeur}'" if found and valeur else ""
        print(f"   {mark} {label}{detail}")

    print(f"\n   Score : {nb_found}/{len(FAITS_ATTENDUS)} "
          f"(seuil minimum : {SEUIL_MIN})")

    # ── Verdict final ──
    print(f"\n{'─'*60}")
    if succes:
        print("✅  TEST PASSÉ — le worker mémoire fonctionne correctement.")
    else:
        if not ok_mem:
            print("❌  ÉCHEC — des tags %%MEM%% subsistent dans les réponses.")
        if nb_found < SEUIL_MIN:
            print(f"❌  ÉCHEC — seulement {nb_found} fait(s) extrait(s) "
                  f"(minimum attendu : {SEUIL_MIN}).")
        print("\n   Pistes de diagnostic :")
        print("   • Vérifier les logs serveur : [WORKER] doit apparaître.")
        print("   • Vérifier que NIMM tourne depuis > 40s avant la fin du test.")
        print("   • Vérifier que le provider est configuré et la clé API valide.")
    print(f"{'═'*60}\n")


async def main(base_url: str, skip_clear: bool):
    global BASE_URL
    BASE_URL = base_url

    async with httpx.AsyncClient() as client:
        print(f"[SETUP] Connexion à {BASE_URL}")

        # 0. Vider la mémoire (base propre)
        if not skip_clear:
            await clear_memory(client)

        # 1. Créer un fil dédié
        resp = await client.post(
            f"{BASE_URL}/api/threads",
            json={"name": "Test worker mémoire"},
            timeout=15.0,
        )
        resp.raise_for_status()
        thread    = resp.json()
        thread_id = thread.get("thread_id") or thread.get("id")
        print(f"[SETUP] Fil créé : {thread_id}\n")

        # 2. Envoyer les messages — collecter les réponses
        replies = []
        for idx, message in enumerate(MESSAGES):
            reply = await send_message(client, thread_id, message, idx)
            replies.append(reply)
            await asyncio.sleep(2.0)

        # 3. Vérifier immédiatement l'absence de %%MEM%%
        ok_now, _ = check_no_mem_tags(replies)
        if ok_now:
            print(f"\n[CHECK] ✅ Aucun %%MEM%% dans les réponses — parfait.")
        else:
            print(f"\n[CHECK] ⚠️  Des %%MEM%% ont été détectés — possible régression.")

        # 4. Attendre le cycle du worker
        print(f"\n[WORKER] Attente de {DELAI_S}s pour le cycle du worker mémoire", end="", flush=True)
        t0 = time.time()
        for _ in range(DELAI_S):
            await asyncio.sleep(1)
            print(".", end="", flush=True)
        elapsed = time.time() - t0
        print(f" {elapsed:.1f}s\n")

        # 5. Lire la mémoire et vérifier les faits
        memories = await get_memory(client)
        print(f"[MEMORY] {len(memories)} triplet(s) en base.")
        results = check_faits(memories)

        # 6. Rapport final
        print_rapport(replies, results, elapsed)

        print(f"[INFO] Fil de test conservé : {thread_id}")
        print("       Lance tests/clear_memory.py pour nettoyer après validation.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test worker mémoire async NIMM")
    parser.add_argument("--base-url",    default="http://localhost:8080")
    parser.add_argument("--skip-clear",  action="store_true",
                        help="Ne pas vider la mémoire avant le test")
    args = parser.parse_args()
    asyncio.run(main(args.base_url, args.skip_clear))
