# ============================================================
# NIMM — tests/test_context_window.py
# Test de résistance de la fenêtre de contexte + OS glissant
#
# Mesure : à quel moment NIMM perd des détails du contexte initial
#
# Fonctionnement :
#   1. Envoie un bloc de 20 faits précis (personnage fictif)
#   2. Injecte des messages de remplissage SANS appel LLM (gratuit)
#   3. À chaque jalon, pose 10 questions via /api/chat (vrai LLM)
#   4. Score automatique par mots-clés
#   5. Rapport final avec tableau de dégradation
#
# Usage : python tests/test_context_window.py
# (NIMM doit tourner sur localhost:8080)
# ============================================================

import asyncio
import httpx
import sys
import time

BASE_URL = "http://localhost:8080"
TIMEOUT  = 45

# ══════════════════════════════════════════════════════════════
# CONTEXTE DE RÉFÉRENCE — 20 faits sur Camille Fontaine (fictif)
# ══════════════════════════════════════════════════════════════

CONTEXT = """\
Je vais te donner des informations sur une personne fictive. \
Mémorise tous les détails avec soin — je vais te poser des questions dessus plus tard.

PROFIL — CAMILLE FONTAINE :
- Nom complet : Camille Fontaine
- Date de naissance : 12 septembre 1991, à Nantes
- Profession : vétérinaire spécialisée en reptiles
- Adresse : 17 rue des Acacias, Bordeaux
- Compagnon : Thomas Renard, ingénieur civil, né le 3 avril 1988
- Animal de compagnie : un serpent ball python nommé Zigzag
- Hobby principal : collectionne les timbres anciens depuis l'âge de 8 ans
- Allergies : fraises et arachides
- Voiture : Citroën C3 rouge, achetée en 2019
- Code mémorable : 4729 (code de son casier au travail)
- Livre préféré : Le Comte de Monte-Cristo
- Rêve de voyage : Madagascar
- Sport : badminton, le jeudi soir au club municipal
- Frère : Sébastien, pompier à Lyon
- Prénom de la mère : Marguerite
- Couleur préférée : vert olive
- Langue étrangère maîtrisée : le portugais (couramment)
- Phobie : le bruit des ballons qui éclatent
- Salaire annuel : 42 000 euros
- Habitude matinale : boit du thé vert chaque matin avant de partir

Accuse réception en citant les 3 détails que tu trouves les plus insolites.\
"""

# ══════════════════════════════════════════════════════════════
# QUESTIONS DE VÉRIFICATION — 10 questions, 1 par fait clé
# ══════════════════════════════════════════════════════════════

QUESTIONS = [
    {"q": "Comment s'appelle le serpent de Camille Fontaine ?",
     "keywords": ["zigzag"],
     "label": "Serpent (Zigzag)"},

    {"q": "Quelle est la date de naissance de Thomas, le compagnon de Camille ?",
     "keywords": ["3 avril", "avril 1988", "3/04", "03/04", "03 avril"],
     "label": "Naissance Thomas (3 avril 1988)"},

    {"q": "Quel est le code du casier de Camille à son travail ?",
     "keywords": ["4729"],
     "label": "Code casier (4729)"},

    {"q": "Dans quelle spécialité vétérinaire Camille exerce-t-elle ?",
     "keywords": ["reptile", "serpent", "lézard"],
     "label": "Spécialité (reptiles)"},

    {"q": "Quel sport Camille pratique-t-elle et quel jour de la semaine ?",
     "keywords": ["badminton"],
     "label": "Sport (badminton, jeudi)"},

    {"q": "Comment s'appelle le frère de Camille et quelle est sa profession ?",
     "keywords": ["sébastien", "sebastien"],
     "label": "Frère (Sébastien, pompier)"},

    {"q": "À quoi Camille est-elle allergique ?",
     "keywords": ["fraise", "arachide", "cacahuète"],
     "label": "Allergies (fraises + arachides)"},

    {"q": "Quelle langue étrangère Camille parle-t-elle couramment ?",
     "keywords": ["portugais"],
     "label": "Langue (portugais)"},

    {"q": "Quel hobby Camille pratique-t-elle depuis son enfance ?",
     "keywords": ["timbre", "philatélie"],
     "label": "Hobby (timbres anciens)"},

    {"q": "Quelle est la phobie de Camille ?",
     "keywords": ["ballon", "éclat", "bruit"],
     "label": "Phobie (ballons qui éclatent)"},
]

QUESTION_BATCH = (
    "Réponds à ces 10 questions de façon très courte et précise. "
    "Format strict : une ligne par réponse, préfixée par le numéro.\n\n"
    + "\n".join(f"{i+1}. {q['q']}" for i, q in enumerate(QUESTIONS))
)

# ══════════════════════════════════════════════════════════════
# MESSAGES DE REMPLISSAGE — injectés sans appel LLM (gratuit)
# Sujets variés, sans rapport avec Camille
# ══════════════════════════════════════════════════════════════

FILLERS = [
    ("Quelle est la capitale de l'Australie ?",
     "La capitale de l'Australie est Canberra, souvent confondue avec Sydney."),
    ("Combien font 347 multiplié par 23 ?",
     "347 × 23 = 7 981."),
    ("C'est quoi la photosynthèse en deux phrases ?",
     "Les plantes utilisent la lumière solaire, le CO2 et l'eau pour produire du glucose. "
     "Elles libèrent de l'oxygène en sous-produit de cette réaction."),
    ("Pourquoi le ciel est-il bleu ?",
     "La diffusion de Rayleigh disperse davantage les longueurs d'onde courtes (bleu) "
     "que les longues (rouge) dans l'atmosphère."),
    ("Donne-moi une recette simple de crêpes.",
     "250g farine, 3 œufs, 50cl lait, 1 pincée de sel, 2 cuillères d'huile. "
     "Mélange et laisse reposer 30 min avant de faire cuire à la poêle."),
    ("C'est quoi un algorithme ?",
     "Un algorithme est une suite d'instructions précises et ordonnées "
     "permettant de résoudre un problème ou d'accomplir une tâche."),
    ("Comment fonctionne un GPS ?",
     "Il reçoit des signaux d'au moins 4 satellites et calcule sa position "
     "par triangulation en mesurant le temps de transit de chaque signal."),
    ("C'est quoi la blockchain ?",
     "Un registre distribué et immuable où les transactions sont enregistrées "
     "dans des blocs chaînés cryptographiquement sans autorité centrale."),
    ("Quelle est la distance entre la Terre et la Lune ?",
     "En moyenne 384 400 km, oscillant entre 356 500 km (périgée) "
     "et 406 700 km (apogée)."),
    ("Qui a écrit Les Misérables ?",
     "Victor Hugo, publié en 1862. C'est l'un des plus longs romans "
     "de la littérature française."),
    ("Comment fonctionne un micro-ondes ?",
     "Il émet des ondes à 2,45 GHz qui font vibrer les molécules d'eau "
     "dans les aliments, générant de la chaleur par friction moléculaire."),
    ("C'est quoi le PIB ?",
     "Le Produit Intérieur Brut mesure la valeur totale des biens et services "
     "produits dans un pays sur une période donnée."),
    ("Pourquoi les feuilles changent de couleur en automne ?",
     "La chlorophylle verte se dégrade avec la baisse de luminosité, "
     "révélant les pigments jaunes/oranges (caroténoïdes) déjà présents."),
    ("C'est quoi un disque SSD ?",
     "Un Solid State Drive utilise de la mémoire flash NAND sans pièces "
     "mécaniques — bien plus rapide et silencieux qu'un HDD classique."),
    ("Explique la loi de l'offre et de la demande.",
     "Quand la demande augmente et l'offre reste stable, le prix monte. "
     "Quand l'offre augmente et la demande reste stable, le prix baisse."),
    ("Donne-moi 3 conseils pour mieux dormir.",
     "1. Pas d'écran 1h avant de dormir. "
     "2. Heure de coucher régulière. "
     "3. Chambre fraîche entre 16 et 19°C."),
    ("C'est quoi la relativité restreinte d'Einstein ?",
     "Elle postule que les lois de la physique sont identiques pour tous "
     "les observateurs en mouvement rectiligne uniforme, et que la vitesse "
     "de la lumière est constante quel que soit l'observateur."),
    ("Comment s'appelle la peur des araignées ?",
     "L'arachnophobie. C'est l'une des phobies les plus fréquentes."),
    ("Pourquoi les avions restent en l'air ?",
     "Le profil aérodynamique de l'aile crée une différence de pression "
     "entre l'extrados et l'intrados, générant une portance qui compense la gravité."),
    ("C'est quoi un neurone ?",
     "Une cellule nerveuse qui transmet l'information via des impulsions "
     "électriques et chimiques. Le cerveau en contient ~86 milliards."),
    ("Quelle est la vitesse du son dans l'air ?",
     "Environ 343 m/s à 20°C, soit 1 235 km/h."),
    ("Comment fonctionne une pile électrique ?",
     "Elle convertit l'énergie chimique en électrique via une réaction "
     "d'oxydoréduction entre anode et cathode baignant dans un électrolyte."),
    ("C'est quoi le syndrome de l'imposteur ?",
     "Un phénomène où une personne remet en question ses compétences "
     "et réussites, craignant d'être démasquée comme incompétente "
     "malgré des preuves objectives de son succès."),
    ("Pourquoi les étoiles scintillent-elles ?",
     "Ce sont les variations de densité de l'atmosphère terrestre "
     "qui dévient la lumière. Les planètes scintillent moins car "
     "leur disque apparent est plus large."),
    ("Donne-moi la formule chimique de l'eau.",
     "H₂O — deux atomes d'hydrogène et un atome d'oxygène "
     "liés par des liaisons covalentes polaires."),
    ("C'est quoi un haïku ?",
     "Un poème japonais en 3 vers de 5, 7 et 5 syllabes, "
     "évoquant souvent la nature et l'instant présent."),
    ("Comment fonctionne l'anesthésie générale ?",
     "Les agents anesthésiques bloquent la transmission des signaux "
     "nerveux au cerveau, induisant une perte de conscience réversible."),
    ("Qu'est-ce que la permaculture ?",
     "Une approche agricole s'inspirant des écosystèmes naturels "
     "pour créer des systèmes productifs durables avec peu d'intrants."),
    ("Comment fonctionne un IRM ?",
     "Il utilise des champs magnétiques pour aligner les protons "
     "d'hydrogène dans les tissus, puis mesure leur relaxation "
     "pour créer des images médicales détaillées."),
    ("C'est quoi le droit de veto à l'ONU ?",
     "Les 5 membres permanents du Conseil de sécurité peuvent bloquer "
     "toute résolution en votant contre, même si tous les autres approuvent."),
    ("Pourquoi pleure-t-on en coupant des oignons ?",
     "L'oignon libère du sulfoxyde de S-propanethial qui se transforme "
     "en acide sulfénique, lequel réagit avec l'eau des yeux."),
    ("Comment s'appelle le plus grand océan ?",
     "L'océan Pacifique, couvrant ~165 millions de km² — plus que "
     "toutes les terres émergées réunies."),
    ("C'est quoi l'intelligence artificielle ?",
     "Des systèmes capables de réaliser des tâches nécessitant "
     "normalement l'intelligence humaine : reconnaissance, raisonnement, apprentissage."),
    ("Donne-moi 3 façons de réduire son empreinte carbone.",
     "1. Moins de viande. 2. Moins d'avion. 3. Mieux isoler son logement."),
    ("Quelle est la langue la plus parlée au monde ?",
     "Le mandarin (~920M locuteurs natifs). L'anglais est "
     "le plus parlé au total en incluant les non-natifs (~1,5 milliard)."),
    ("C'est quoi l'effet de serre ?",
     "L'atmosphère retient le rayonnement infrarouge émis par la Terre. "
     "Ce phénomène naturel est amplifié par les émissions de CO2 humaines."),
    ("Comment marche un aspirateur ?",
     "Un moteur crée une dépression par turbine. La différence de pression "
     "aspire l'air et les particules à travers un filtre."),
    ("Qu'est-ce que le cholestérol ?",
     "Une molécule lipidique essentielle aux membranes cellulaires "
     "et aux hormones. LDL = 'mauvais' (se dépose dans les artères), "
     "HDL = 'bon' (nettoie les artères)."),
    ("C'est quoi un podcast ?",
     "Un fichier audio/vidéo disponible en téléchargement ou streaming, "
     "généralement en série d'épisodes sur un thème donné."),
    ("Explique le principe des vases communicants.",
     "Dans des récipients connectés contenant le même liquide, "
     "le niveau s'équilibre à la même hauteur quelle que soit la forme."),
    ("C'est quoi un trou noir ?",
     "Une région de l'espace où la densité de masse est telle "
     "que rien — pas même la lumière — ne peut s'en échapper."),
    ("Comment s'appelle la peur du vide ?",
     "L'acrophobie (hauteurs). La peur du vide absolu "
     "est parfois appelée kénophobie."),
    ("Donne-moi 3 conseils pour apprendre une langue.",
     "1. Pratiquer 20 min/jour. 2. Consommer des contenus natifs. "
     "3. Parler avec des locuteurs dès que possible."),
    ("C'est quoi le syndrome de Stockholm ?",
     "Un phénomène psychologique où des otages développent "
     "des sentiments positifs envers leurs ravisseurs."),
    ("Comment fonctionnent les antibiotiques ?",
     "Ils ciblent des structures spécifiques aux bactéries "
     "(paroi, ribosomes, ADN) sans affecter les cellules humaines. "
     "Inefficaces contre les virus."),
    ("Quelle est la superficie de la France ?",
     "La France métropolitaine couvre ~551 695 km², "
     "le plus grand pays d'Europe occidentale."),
    ("C'est quoi la loi de Murphy ?",
     "Tout ce qui peut mal tourner tournera mal. "
     "Formulée par l'ingénieur Edward Murphy en 1949."),
    ("Comment fonctionne un moteur électrique ?",
     "Il convertit l'énergie électrique en énergie mécanique "
     "via l'interaction entre un champ magnétique et un courant électrique."),
    ("C'est quoi l'ADN ?",
     "L'acide désoxyribonucléique est la molécule qui contient "
     "les instructions génétiques de tous les organismes vivants."),
    ("Qu'est-ce que la loi de la gravitation universelle ?",
     "Newton : deux corps s'attirent avec une force proportionnelle "
     "au produit de leurs masses et inversement proportionnelle "
     "au carré de leur distance."),
    ("Comment s'appelle le processus de transformation "
     "d'une chenille en papillon ?",
     "La métamorphose. La phase intermédiaire enfermée dans un cocon "
     "s'appelle la chrysalide."),
    ("C'est quoi un oligopole ?",
     "Un marché dominé par un petit nombre de grandes entreprises "
     "qui ont chacune un pouvoir significatif sur les prix."),
    ("Donne-moi 3 caractéristiques du baroque en musique.",
     "1. Ornementation complexe. 2. Basse continue. "
     "3. Expressivité contrastée (allegro/adagio). Bach, Vivaldi, Haendel."),
    ("Pourquoi l'eau bout-elle à 100°C ?",
     "À pression atmosphérique standard (1 atm), l'eau atteint "
     "100°C avant que la pression de vapeur dépasse la pression ambiante."),
    ("C'est quoi la mémoire RAM ?",
     "La Random Access Memory est une mémoire volatile rapide "
     "qui stocke les données en cours d'utilisation par le processeur."),
    ("Comment fonctionne le vote par correspondance ?",
     "L'électeur reçoit un bulletin par courrier, le remplit "
     "et le renvoie à une adresse officielle avant la date limite."),
    ("C'est quoi la différence entre un barreau et une chambre "
     "de notaires ?",
     "Le barreau regroupe les avocats d'une juridiction. "
     "La chambre des notaires regroupe les notaires d'un département."),
    ("Qu'est-ce que le mouvement Dada ?",
     "Un mouvement artistique né en 1916 à Zurich, réaction "
     "à l'absurdité de la Première Guerre mondiale. "
     "Anti-art, provocation, hasard comme principe créatif."),
    ("C'est quoi un IBAN ?",
     "Un International Bank Account Number — un code standardisé "
     "identifiant un compte bancaire à l'international."),
    ("Comment fonctionne la réfraction de la lumière ?",
     "Quand la lumière passe d'un milieu à un autre de densité différente, "
     "elle change de direction selon la loi de Snell-Descartes."),
    ("C'est quoi la psychologie cognitive ?",
     "La branche de la psychologie qui étudie les processus mentaux : "
     "perception, mémoire, langage, raisonnement, résolution de problèmes."),
]

# ══════════════════════════════════════════════════════════════
# JALONS DE TEST
# Chaque jalon = nombre de paires de remplissage injectées
# 1 paire = 2 messages (user + assistant)
# ══════════════════════════════════════════════════════════════

CHECKPOINTS = [
    {"label": "0 — Baseline (contexte seul)",          "n_pairs": 0},
    {"label": "A — +20 messages de remplissage",        "n_pairs": 10},
    {"label": "B — +40 messages",                       "n_pairs": 20},
    {"label": "C — +60 messages",                       "n_pairs": 30},
    {"label": "D — +76 messages (fenêtre -4)",          "n_pairs": 38},
    {"label": "E — +86 messages (OS vient de démarrer)","n_pairs": 43},
    {"label": "F — +100 messages",                      "n_pairs": 50},
    {"label": "G — +120 messages",                      "n_pairs": 60},
]

SEP  = "─" * 64
SEP2 = "═" * 64


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def score_response(response: str, question: dict) -> bool:
    r = response.lower()
    return any(kw in r for kw in question["keywords"])


async def inject_fillers(c: httpx.AsyncClient, tid: str,
                         pairs: list[tuple[str, str]]):
    """Injecte des paires user/assistant directement en DB sans appel LLM."""
    for user_msg, asst_msg in pairs:
        await c.post(f"/api/threads/{tid}/messages",
                     json={"role": "user",    "content": user_msg})
        await c.post(f"/api/threads/{tid}/messages",
                     json={"role": "assistant", "content": asst_msg})


async def ask_questions(c: httpx.AsyncClient, tid: str) -> tuple[list[bool], str]:
    """
    Pose les 10 questions en un seul appel LLM.
    Retourne (liste de scores, réponse brute).
    """
    r = await c.post("/api/chat",
                     json={"message": QUESTION_BATCH, "thread_id": tid},
                     timeout=TIMEOUT)
    if r.status_code != 200:
        return [False] * len(QUESTIONS), f"[ERREUR HTTP {r.status_code}]"

    reply = r.json().get("reply", "")
    scores = [score_response(reply, q) for q in QUESTIONS]
    return scores, reply


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

async def main():
    print(f"\n{SEP2}")
    print("  NIMM — Test de la fenêtre de contexte + OS glissant")
    print(f"  Cible : {BASE_URL}")
    print(SEP2)

    # Vérifier que NIMM tourne
    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as probe:
            await probe.get("/api/ping")
    except Exception:
        print(f"\n❌  Serveur inaccessible. Lance NIMM d'abord.\n")
        sys.exit(1)

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as c:

        # ── Créer le fil de test ──
        r = await c.post("/api/threads", json={"name": "[TEST] Fenêtre contexte"})
        if r.status_code != 200:
            print("❌  Impossible de créer le fil de test.")
            sys.exit(1)
        tid = r.json()["thread_id"]
        print(f"\n  Fil créé : {tid[:8]}...")

        # ── Envoyer le contexte initial ──
        print("\n  Envoi du contexte initial (1 appel LLM)...")
        r = await c.post("/api/chat",
                         json={"message": CONTEXT, "thread_id": tid},
                         timeout=TIMEOUT)
        if r.status_code != 200:
            print(f"❌  Échec de l'envoi du contexte : HTTP {r.status_code}")
            await c.delete(f"/api/threads/{tid}")
            sys.exit(1)
        print(f"  ✅  Contexte accepté.")

        # ── Boucle de test ──
        all_results = []
        injected_total = 0
        filler_index   = 0

        for cp in CHECKPOINTS:
            target = cp["n_pairs"]
            to_inject = target - injected_total

            if to_inject > 0:
                pairs = []
                for _ in range(to_inject):
                    pairs.append(FILLERS[filler_index % len(FILLERS)])
                    filler_index += 1
                print(f"\n  ⏩  Injection de {to_inject} paires "
                      f"({to_inject * 2} messages)...", end=" ", flush=True)
                await inject_fillers(c, tid, pairs)
                injected_total += to_inject
                print("fait.")

            total_msgs = 2 + injected_total * 2  # contexte + fillers
            print(f"\n{SEP}")
            print(f"  📍  {cp['label']}")
            print(f"      Messages en DB : ~{total_msgs}  |  "
                  f"Remplissage injecté : {injected_total} paires")
            print(f"  Envoi des 10 questions (1 appel LLM)...", end=" ", flush=True)

            t0 = time.perf_counter()
            scores, reply = await ask_questions(c, tid)
            elapsed = time.perf_counter() - t0

            print(f"réponse en {elapsed:.1f}s")
            print()

            score_total = sum(scores)
            for i, (q, ok) in enumerate(zip(QUESTIONS, scores)):
                icon = "✅" if ok else "❌"
                print(f"    {icon}  Q{i+1:02d} {q['label']}")

            print(f"\n  Score : {score_total}/{len(QUESTIONS)}")

            # Afficher un extrait si des erreurs
            if score_total < len(QUESTIONS):
                preview = reply[:300].replace("\n", " ")
                print(f"  Réponse reçue (extrait) : {preview}...")

            all_results.append({
                "label":       cp["label"],
                "total_msgs":  total_msgs,
                "scores":      scores,
                "score_total": score_total,
            })

        # ── Nettoyage ──
        await c.delete(f"/api/threads/{tid}")
        print(f"\n  🗑️   Fil de test supprimé.")

    # ══════════════════════════════════════════════════════════
    # RAPPORT FINAL
    # ══════════════════════════════════════════════════════════

    print(f"\n{SEP2}")
    print("  RAPPORT FINAL — Dégradation de la mémoire contextuelle")
    print(SEP2)

    # En-tête tableau
    header = f"{'Jalon':<44} {'Msgs':>5}  {'Score':>7}  Détail"
    print(f"\n  {header}")
    print(f"  {'─'*70}")

    baseline_score = all_results[0]["score_total"] if all_results else 10

    for res in all_results:
        score = res["score_total"]
        total = len(QUESTIONS)
        pct   = int(100 * score / total)

        if score == total:
            bar = "🟢 Parfait"
        elif score >= total * 0.8:
            bar = "🟡 Léger oubli"
        elif score >= total * 0.5:
            bar = "🟠 Dégradation notable"
        else:
            bar = "🔴 Perte majeure"

        missed = [f"Q{i+1}" for i, ok in enumerate(res["scores"]) if not ok]
        missed_str = (", ".join(missed)) if missed else "aucun oubli"

        label_short = res["label"][:42]
        print(f"  {label_short:<44} {res['total_msgs']:>5}  "
              f"{score:>2}/{total} {pct:>3}%  {bar}")
        if missed:
            print(f"  {'':44}        Oubliés : {missed_str}")

    # Conclusion
    print(f"\n{SEP}")
    degraded = [r for r in all_results if r["score_total"] < baseline_score]
    if not degraded:
        print("  🎉  Aucune dégradation détectée sur toute la plage testée.")
        print("      La fenêtre de contexte est suffisante pour ces conversations.")
    else:
        first_loss = degraded[0]
        print(f"  ⚠️   Première dégradation détectée au jalon :")
        print(f"      {first_loss['label']} (~{first_loss['total_msgs']} messages)")
        lost_count = baseline_score - first_loss["score_total"]
        print(f"      {lost_count} fait(s) oublié(s) à ce stade.")

    print(f"\n  Coût estimé : {len(all_results)} appels LLM × ~30k tokens")
    print(f"  ≈ {len(all_results) * 30000 / 1_000_000 * 0.27:.3f}$ (DeepSeek)")
    print(SEP2 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
