"""
test_mma_bilans.py
──────────────────
Simule une soirée MMA : plusieurs combats, digressions famille entre les posts.
Vérifie que la fiche bibliothèque reflète fidèlement les %%BILAN%% du fil.

Usage :
    python test_mma_bilans.py
    python test_mma_bilans.py --base-url http://192.168.1.x:8080

Dépendances : httpx (pip install httpx)
"""

import asyncio
import argparse
import json
import httpx

BASE_URL = "http://localhost:8080"

# ──────────────────────────────────────────────────────────
# Scénario : soirée UFC — 4 combats + 3 digressions famille
# L'utilisateur décrit chaque combat APRÈS avoir reçu la
# réponse de NIMM au message précédent (conversation réelle).
# ──────────────────────────────────────────────────────────
MESSAGES = [
    # --- Ouverture ---
    (
        "Bon, c'est parti pour la soirée UFC ! Je suis installé avec ma bière, "
        "Nadia est allée se coucher tôt ce soir, j'ai le salon pour moi. "
        "Premier combat dans dix minutes, Adesanya vs Pereira 4. "
        "Tu connais ces deux-là ? C'est la quatrième fois qu'ils se croisent."
    ),

    # --- Digression famille 1 ---
    (
        "Avant le début, je te dis : Maïssane a eu ses résultats de brevet blanc aujourd'hui. "
        "Elle a eu 14 de moyenne, on est vraiment contents avec Nadia. "
        "Bon, le combat commence, c'est tendu dès la première reprise."
    ),

    # --- Résultat combat 1 ---
    (
        "Incroyable ! Pereira vient de mettre Adesanya KO au premier round, "
        "un crochet du droit qui a tout réglé en moins de deux minutes. "
        "Adesanya n'a pas vu venir, il était pourtant bien placé en début de reprise. "
        "C'est la deuxième fois que Pereira le finit par KO — le gars est une machine. "
        "Pour moi, Pereira est clairement le meilleur light-heavyweight du moment."
    ),

    # --- Combat 2 : annonce ---
    (
        "Deuxième combat : Holloway vs Gaethje pour le titre BMF. "
        "Ces deux-là vont se rentrer dedans, c'est sûr. "
        "Je me refais une bière, le frigo est à l'autre bout du couloir à cette heure-là c'est une expédition."
    ),

    # --- Digression famille 2 ---
    (
        "En attendant le début, j'ai reçu un message de mon frère Sébastien. "
        "Il m'annonce qu'il vient nous rendre visite le week-end prochain avec sa femme. "
        "Ça fait au moins six mois qu'on s'était pas vus, ça va faire plaisir."
    ),

    # --- Résultat combat 2 ---
    (
        "Combat de fou. Holloway a encaissé toute la nuit mais il a tenu, "
        "puis il a fini par stopper Gaethje à la troisième reprise avec une série de coups au corps "
        "qui ont mis Gaethje à genoux. Décision unanime des juges en faveur de Holloway. "
        "Holloway conserve le titre BMF — et honnêtement il le mérite, "
        "il a montré un mental en acier cette nuit."
    ),

    # --- Combat 3 ---
    (
        "Troisième combat : O'Malley vs Merab pour le titre coq. "
        "Je suis partagé — O'Malley est spectaculaire mais Merab a un moteur de dingue, "
        "il épuise tout le monde. Ça va durer les cinq rounds j'en suis sûr."
    ),

    # --- Digression famille 3 ---
    (
        "Ma fille Inès m'a envoyé un vocal pendant la pause. "
        "Elle me dit qu'elle vient de s'abonner à Netflix pour regarder une série documentaire sur les arts martiaux. "
        "Coïncidence sympa pour une soirée MMA ! "
        "En tout cas elle va bien, elle est bien installée dans son appart."
    ),

    # --- Résultat combat 3 ---
    (
        "J'avais raison, ça a duré cinq rounds. Merab a fait ce qu'il fait toujours : "
        "il a mis une pression constante, Suga Sean n'arrivait pas à placer son jeu de jambes habituel. "
        "Victoire de Merab par décision unanime — O'Malley perd son titre. "
        "Franchement Merab champion coq, c'est mérité, il bosse comme un forcené."
    ),

    # --- Combat principal : annonce ---
    (
        "Combat principal : Jon Jones vs Stipe Miocic pour le titre lourd. "
        "Jones est revenu de blessure, ça fait longtemps qu'on l'a pas vu. "
        "Stipe a 42 ans et il est encore là — respect total pour le bonhomme."
    ),

    # --- Résultat combat principal ---
    (
        "Jones a dominé du début à la fin. Il a mis Stipe au sol dès le deuxième round "
        "et l'a contrôlé avec son wrestling, puis soumission par rear naked choke à la troisième reprise. "
        "Jones conserve son titre — et pour moi c'est toujours le GOAT, point final. "
        "Soirée parfaite, quatre combats, quatre KO ou soumissions. "
        "Je vais me coucher, demain c'est réveil à 5h pour la route."
    ),
]


async def send_message(client: httpx.AsyncClient, thread_id: str, message: str, idx: int) -> str:
    """Envoie un message via /api/chat et retourne la réponse du LLM."""
    print(f"\n{'─'*60}")
    print(f"[MSG {idx+1}/{len(MESSAGES)}] Utilisateur :")
    print(f"  {message[:120]}{'...' if len(message) > 120 else ''}")

    resp = await client.post(
        f"{BASE_URL}/api/chat",
        json={"message": message, "thread_id": thread_id},
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()

    reply = data.get("reply") or data.get("response") or str(data)
    bilans = data.get("bilan") or []

    print(f"\n[NIMM] {reply[:200]}{'...' if len(reply) > 200 else ''}")

    # Afficher les %%BILAN%% détectés s'ils sont exposés dans la réponse
    if bilans:
        print(f"  ↳ BILAN détecté : {bilans}")

    return reply


async def archive_thread(client: httpx.AsyncClient, thread_id: str) -> dict:
    """Déclenche la génération de la fiche bibliothèque."""
    print(f"\n{'═'*60}")
    print("[ARCHIVE] Génération de la fiche bibliothèque...")
    resp = await client.post(
        f"{BASE_URL}/api/bibliotheque",
        json={"thread_id": thread_id},
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()


async def get_bibliotheque_entry(client: httpx.AsyncClient, entry_id: int) -> dict:
    """Récupère toutes les entrées et filtre par id."""
    resp = await client.get(f"{BASE_URL}/api/bibliotheque", timeout=30.0)
    resp.raise_for_status()
    entries = resp.json()
    for e in entries:
        if e.get("id") == entry_id:
            return e
    return {}


async def get_session_bilans(client: httpx.AsyncClient, thread_id: str) -> list:
    """Lit les bilans de session via /api/settings."""
    resp = await client.get(
        f"{BASE_URL}/api/settings/session_bilan_{thread_id}",
        timeout=10.0,
    )
    if resp.status_code == 200:
        data = resp.json()
        raw = data.get("value", "[]")
        try:
            return json.loads(raw)
        except Exception:
            return []
    return []


def print_verdict(bilans: list, entry: dict):
    """Affiche le bilan de validation."""
    print(f"\n{'═'*60}")
    print("RAPPORT DE VALIDATION — ANCRAGE DES BILANS")
    print(f"{'═'*60}\n")

    if not bilans:
        print("⚠️  Aucun %%BILAN%% détecté dans ce fil.")
        print("   → Vérifier que le LLM émet bien les tags %%BILAN%%.")
        return

    print(f"✅  {len(bilans)} bilan(s) détecté(s) dans le fil :\n")
    for b in bilans:
        print(f"   [{b.get('ts','?')}] {b.get('texte','?')}")

    print(f"\n{'─'*60}")
    print("FICHE BIBLIOTHÈQUE GÉNÉRÉE :\n")

    titre = entry.get("titre", "(sans titre)")
    resume = entry.get("resume_texte", "(vide)")
    print(f"Titre   : {titre}")
    print(f"\nRésumé :\n{resume}")

    print(f"\n{'─'*60}")
    print("VÉRIFICATION MANUELLE :")
    print("Chaque fait ci-dessous doit apparaître dans le résumé ci-dessus.")
    print("(Chercher la sémantique, pas le mot exact)\n")

    # Faits-clés attendus dans le résumé
    faits_attendus = [
        "Pereira KO Adesanya",
        "Holloway bat Gaethje",
        "Merab bat O'Malley",
        "Jones bat Stipe",
        "Maïssane 14 de moyenne brevet",
        "Inès abonnement Netflix",
        "Sébastien visite week-end prochain",
    ]

    resume_lower = resume.lower()
    for fait in faits_attendus:
        mots = fait.lower().split()
        # Cherche si la majorité des mots-clés sont présents
        matches = sum(1 for m in mots if m in resume_lower)
        ok = "✅" if matches >= len(mots) // 2 + 1 else "❌"
        print(f"  {ok} {fait}")

    print(f"\n{'═'*60}")


async def main(base_url: str):
    global BASE_URL
    BASE_URL = base_url

    async with httpx.AsyncClient() as client:
        # 1. Créer un fil dédié
        print(f"[SETUP] Connexion à {BASE_URL}")
        resp = await client.post(
            f"{BASE_URL}/api/threads",
            json={"name": "Test soirée MMA — bilans"},
            timeout=15.0,
        )
        resp.raise_for_status()
        thread = resp.json()
        thread_id = thread.get("thread_id") or thread.get("id")
        print(f"[SETUP] Fil créé : {thread_id}")

        # 2. Dérouler la conversation message par message
        for idx, message in enumerate(MESSAGES):
            await send_message(client, thread_id, message, idx)
            # Pause courte pour ne pas saturer le serveur
            await asyncio.sleep(1.5)

        # 3. Lire les bilans accumulés
        bilans = await get_session_bilans(client, thread_id)
        print(f"\n[BILANS] {len(bilans)} bilan(s) estampillés dans ce fil.")

        # 4. Archiver le fil → déclenche generate_bibliotheque_entry()
        archive_result = await archive_thread(client, thread_id)
        entry_id = archive_result.get("id")
        print(f"[ARCHIVE] Fiche créée (id={entry_id}) — titre : {archive_result.get('titre')}")

        # 5. Récupérer la fiche complète
        entry = await get_bibliotheque_entry(client, entry_id) if entry_id else {}

        # 6. Afficher le verdict
        print_verdict(bilans, entry)

        print(f"\n[INFO] Fil de test conservé : {thread_id}")
        print("       Tu peux l'ouvrir dans l'interface pour vérifier les messages complets.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test ancrage bilans MMA")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8080",
        help="URL de base de NIMM (ex: http://192.168.1.10:8080)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.base_url))
