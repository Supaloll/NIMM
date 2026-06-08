"""
test_mma_confusion.py
─────────────────────
Simule une soirée MMA réaliste où les mêmes noms reviennent
dans des contextes différents (analyse, attente, résultats laconiques).
Reproduit la confusion constatée avec Salahdine / Ngannou / Diaz.

Deux objectifs :
  1. Vérifier que la fiche bibliothèque (Appel C) ancre correctement les faits
  2. Observer si le LLM se perd en cours de conversation (%%BILAN%% inline)

Usage :
    python tests/test_mma_confusion.py
    python tests/test_mma_confusion.py --base-url http://192.168.1.x:8080
"""

import asyncio
import argparse
import json
import httpx

BASE_URL = "http://localhost:8080"

MESSAGES = [
    # ── Pré-soirée : analyse de la carte, tous les noms dès le début ──
    (
        "Bon, ce soir c'est la grande soirée Netflix. La carte est bizarre quand même. "
        "T'as Salahdine en co-main, Ngannou en main event, et Diaz quelque part au milieu. "
        "Trois styles complètement différents. Salahdine c'est de la technique pure, "
        "Ngannou c'est de la dynamite ambulante, et Diaz c'est un guerrier qui vit dans la douleur. "
        "Franchement je sais pas lequel va me donner le plus de frissons ce soir."
    ),

    # ── Comparaison des styles, toujours les trois noms ──
    (
        "Je me posais la question : si Salahdine et Ngannou étaient dans la même catégorie, "
        "qui gagnerait ? Salahdine il est tellement technique mais Ngannou il assomme n'importe qui "
        "d'un seul coup. Et Diaz lui il rentrerait dans les deux à coups de trash-talk avant même "
        "de commencer. La carte de ce soir c'est vraiment trois philosophies du combat."
    ),

    # ── Confusion sur l'ordre des combats ──
    (
        "Attends, ils ont changé l'ordre. Ngannou passe avant Diaz apparemment. "
        "Je comprends pas leur logique, Diaz ça aurait été un meilleur cliffhanger pour la fin. "
        "Du coup ce soir c'est : Salahdine, puis Ngannou, puis Diaz. "
        "Enfin je crois, avec Netflix on sait jamais ils font leur sauce dans leur coin."
    ),

    # ── Salahdine entre dans la cage ──
    (
        "C'est parti, Salahdine est dans la cage. Son adversaire Cross il a l'air costaud. "
        "J'attends Ngannou avec impatience mais bon on va d'abord voir ce que Salahdine a dans le ventre. "
        "L'ambiance est folle, le public il est chaud pour le Français."
    ),

    # ── Pendant le combat de Salahdine, digression sur Ngannou ──
    (
        "Salahdine il contrôle bien mais Cross il résiste. "
        "Au fait, t'as vu l'interview de Ngannou cette semaine ? Il a dit qu'il allait montrer "
        "un nouveau côté de son jeu ce soir, moins bourrin, plus technique. On verra. "
        "Diaz lui il a rien dit comme d'hab, il fait son truc dans son coin."
    ),

    # ── Résultat Salahdine — laconique ──
    (
        "KO. Premier round. Salahdine a tout réglé."
    ),

    # ── Célébration rapide puis on passe à autre chose ──
    (
        "La punchline au micro elle était dingue : 'c'est pas le rêve américain que je vis, "
        "c'est le rêve français'. Le gars il assure même au micro. "
        "Bon, maintenant on attend Ngannou. Mais d'abord il y a le combat de Diaz qui passe. "
        "Diaz contre qui déjà ? J'ai pas suivi."
    ),

    # ── Discussion Diaz avant son combat ──
    (
        "Diaz il entre dans la cage maintenant. Son style c'est tellement particulier, "
        "il marche vers l'adversaire les mains basses, il encaisse tout, et il revient toujours. "
        "Comme Ngannou mais en version endurcissement plutôt que puissance. "
        "Et Salahdine lui il ferait pas ça, il resterait à distance et placerait ses techniques."
    ),

    # ── Résultat Diaz — laconique ──
    (
        "Diaz a perdu aux points. Décision partagée, c'était serré."
    ),

    # ── Transition vers Ngannou, re-mention de Salahdine ──
    (
        "Bon, Diaz il vieillit un peu. Beau combat quand même. "
        "Et là c'est l'heure de Ngannou. La soirée a bien commencé avec Salahdine, "
        "j'espère que Ngannou va mettre le feu pareil. Son adversaire c'est Lins, un Brésilien solide. "
        "Mais franchement face à la puissance de Ngannou je lui donne pas longtemps."
    ),

    # ── Pendant le combat de Ngannou ──
    (
        "Ngannou il prend son temps, il cherche l'ouverture. Lins il essaie de tenir à la cage. "
        "C'est tendu. Au fait, tu sais si Salahdine il va défendre son titre bientôt ? "
        "Après ce KO ce soir il mérite une grosse affiche."
    ),

    # ── Résultat Ngannou — laconique ──
    (
        "Crochet gauche. KO. C'est plié pour Ngannou."
    ),

    # ── Bilan final de la soirée ──
    (
        "Soirée parfaite au final. Trois combats, trois fins nettes. "
        "Salahdine KO au premier, Diaz aux points, Ngannou KO aussi. "
        "La carte Netflix elle a tenu ses promesses même si l'ordre était bizarre. "
        "Je vais me coucher, 5h du mat demain pour la route."
    ),
]


async def send_message(client: httpx.AsyncClient, thread_id: str, message: str, idx: int) -> str:
    print(f"\n{'─'*60}")
    print(f"[MSG {idx+1}/{len(MESSAGES)}] Utilisateur :")
    print(f"  {message[:120]}{'...' if len(message) > 120 else ''}")

    resp = await client.post(
        f"{BASE_URL}/api/chat",
        json={"message": message, "thread_id": thread_id},
        timeout=90.0,
    )
    resp.raise_for_status()
    data = resp.json()
    reply = data.get("reply") or data.get("response") or str(data)

    print(f"\n[NIMM] {reply[:300]}{'...' if len(reply) > 300 else ''}")

    # Détecter si le LLM redemande un résultat déjà annoncé (signe de confusion)
    confusion_signals = [
        "salahdine a gagné", "salahdine il a gagné", "il a gagné", "il a mis ko",
        "tu confirmes", "c'est bien lui", "c'est confirmé", "t'as dit",
        "il a bien gagné", "parnasse a gagné"
    ]
    reply_lower = reply.lower()
    if any(sig in reply_lower for sig in confusion_signals):
        print(f"  ⚠️  SIGNAL CONFUSION DÉTECTÉ dans la réponse #{idx+1}")

    return reply


async def archive_thread(client: httpx.AsyncClient, thread_id: str) -> dict:
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
    resp = await client.get(f"{BASE_URL}/api/bibliotheque", timeout=30.0)
    resp.raise_for_status()
    for e in resp.json():
        if e.get("id") == entry_id:
            return e
    return {}


def print_verdict(entry: dict):
    print(f"\n{'═'*60}")
    print("RAPPORT DE VALIDATION — FICHE BIBLIOTHÈQUE")
    print(f"{'═'*60}\n")

    titre  = entry.get("titre", "(sans titre)")
    resume = entry.get("resume_texte", "(vide)")
    print(f"Titre   : {titre}")
    print(f"\nRésumé :\n{resume}")

    print(f"\n{'─'*60}")
    print("VÉRIFICATION DES FAITS CONFIRMÉS :\n")

    faits = [
        ("Salahdine KO Cross au 1er round",     ["salahdine", "ko", "premier"]),
        ("Punchline 'rêve français'",            ["rêve français", "reve francais"]),
        ("Diaz perd aux points / décision",      ["diaz", "points", "décision", "decision"]),
        ("Ngannou KO Lins (crochet gauche)",     ["ngannou", "ko", "lins"]),
        ("Soirée sur Netflix",                   ["netflix"]),
        ("Réveil 5h / route le lendemain",       ["5h", "route"]),
    ]

    resume_lower = resume.lower()
    for label, mots_cles in faits:
        ok = any(m in resume_lower for m in mots_cles)
        print(f"  {'✅' if ok else '❌'} {label}")

    print(f"\n{'─'*60}")
    print("POINT CRITIQUE — Salahdine ne doit PAS être présenté comme incertain :")
    if "salahdine" in resume_lower and ("gagné" in resume_lower or "ko" in resume_lower or "vainqueur" in resume_lower):
        print("  ✅ Salahdine mentionné comme vainqueur dans la fiche")
    else:
        print("  ❌ Salahdine absent ou résultat flou dans la fiche")

    print(f"\n{'═'*60}")


async def main(base_url: str):
    global BASE_URL
    BASE_URL = base_url

    async with httpx.AsyncClient() as client:
        print(f"[SETUP] Connexion à {BASE_URL}")

        resp = await client.post(
            f"{BASE_URL}/api/threads",
            json={"name": "Test confusion MMA — Salahdine/Ngannou/Diaz"},
            timeout=15.0,
        )
        resp.raise_for_status()
        thread = resp.json()
        thread_id = thread.get("thread_id") or thread.get("id")
        print(f"[SETUP] Fil créé : {thread_id}")

        for idx, message in enumerate(MESSAGES):
            await send_message(client, thread_id, message, idx)
            await asyncio.sleep(1.5)

        archive_result = await archive_thread(client, thread_id)
        entry_id = archive_result.get("id")
        print(f"[ARCHIVE] Fiche créée (id={entry_id}) — titre : {archive_result.get('titre')}")

        entry = await get_bibliotheque_entry(client, entry_id) if entry_id else {}
        print_verdict(entry)

        print(f"\n[INFO] Fil de test conservé : {thread_id}")
        print("       Ouvre ce fil dans NIMM pour lire les réponses complètes et détecter les confusions.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test confusion MMA — noms multiples")
    parser.add_argument("--base-url", default="http://localhost:8080")
    args = parser.parse_args()
    asyncio.run(main(args.base_url))
