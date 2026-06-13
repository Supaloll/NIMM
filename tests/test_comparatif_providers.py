# ============================================================
# NIMM — tests/test_comparatif_providers.py
# Comparatif résistance mémoire — plusieurs providers LLM
#
# Usage :
#   Depuis le dossier racine de NIMM :
#   python tests/test_comparatif_providers.py
#
# Le script :
#   1. Sauvegarde le provider/modèle actuel
#   2. Pour chaque provider configuré :
#      - Vide la mémoire
#      - Bascule provider + modèle
#      - Envoie les 5 messages de test
#      - Lit la DB et vérifie les assertions
#   3. Restaure le provider/modèle d'origine
#   4. Affiche le tableau comparatif final
# ============================================================

import sqlite3
import time
import os
import sys
import requests
from datetime import datetime

# ── Config ──────────────────────────────────────────────────
BASE_URL = "http://localhost:8080"
USER_ID  = "laurent"
DB_PATH  = os.path.join(os.path.dirname(__file__), '..', 'data', 'nimm_laurent.db')
HEADERS  = {"Content-Type": "application/json", "x-user-id": USER_ID}

# Délai entre messages (secondes) — laisse le worker async traiter
DELAI_ENTRE_MESSAGES = 10
# Délai final après le dernier message
DELAI_FINAL = 18

# ── Providers à tester ───────────────────────────────────────
# Format : (label_affichage, provider_id, model_id)
# model_id = None → garde le modèle déjà configuré dans NIMM
PROVIDERS = [
    ("Mistral Small",   "mistral",    "mistral-small-latest"),
]

# ── Messages de test (niveaux 1 → 5) ────────────────────────
MESSAGES = [
    {
        "niveau": 1,
        "label": "Faits simples (âge, bac, lycée)",
        "texte": (
            "Ma fille Maïssane a 18 ans et elle passe le bac cette semaine. "
            "Elle est en Terminale au lycée Bartholdi à Colmar."
        ),
        "attendu": [
            ("Maïssane", "age",    "18"),
            ("Maïssane", "ecole",  "Bartholdi"),
            ("Maïssane", None,     "bac"),
        ],
    },
    {
        "niveau": 2,
        "label": "Faits chiffrés (années pratique, compétitions)",
        "texte": (
            "Maïssane fait du judo depuis 6 ans au club Colmar Judo. "
            "Cette saison elle a participé à 4 compétitions."
        ),
        "attendu": [
            ("Maïssane", None, "judo"),
            ("Maïssane", None, "6"),
            ("Maïssane", None, "4"),
        ],
    },
    {
        "niveau": 3,
        "label": "Traits de caractère (douce, émotive, agressivité)",
        "texte": (
            "Maïssane est une fille très douce et assez émotive. "
            "Sur le tapis elle manque parfois d'agressivité, ça lui coûte des points."
        ),
        "attendu": [
            ("Maïssane", None, "douce"),
            ("Maïssane", None, "emotive"),
            ("Maïssane", None, "agressivite"),
        ],
    },
    {
        "niveau": 4,
        "label": "Nuances techniques (ippon vs décision)",
        "texte": (
            "Elle gagne rarement par ippon. "
            "La plupart de ses victoires viennent aux points, par décision des arbitres."
        ),
        "attendu": [
            ("Maïssane", None, "ippon"),
            ("Maïssane", None, "decision"),
        ],
    },
    {
        "niveau": 5,
        "label": "Anecdote narrative (finale perdue, fair-play)",
        "texte": (
            "La semaine dernière Maïssane a perdu une finale départementale d'un seul point. "
            "Elle était dévastée mais elle a serré la main de son adversaire sans rien dire. "
            "Je suis vraiment fier d'elle."
        ),
        "attendu": [
            ("Maïssane", None, "finale"),
            ("Maïssane", None, "departement"),
            ("Maïssane", None, "fier"),
        ],
    },
]

# Toutes les assertions à plat (pour le tableau final)
TOUTES_ASSERTIONS = [
    (msg["niveau"], mot_cle)
    for msg in MESSAGES
    for (_, _, mot_cle) in msg["attendu"]
]


# ── Helpers API ──────────────────────────────────────────────

def _print_sep(char="─", n=62):
    print(char * n)

def _print_titre(texte):
    _print_sep("═")
    print(f"  {texte}")
    _print_sep("═")

def get_provider_actuel():
    r = requests.get(f"{BASE_URL}/api/settings/provider", headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json().get("provider", "")

def get_model_actuel():
    r = requests.get(f"{BASE_URL}/api/settings/model", headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json().get("model", "")

def set_provider(provider_id):
    r = requests.post(
        f"{BASE_URL}/api/settings/provider",
        headers=HEADERS,
        json={"provider": provider_id},
        timeout=10,
    )
    r.raise_for_status()

def set_model(model_id):
    if not model_id:
        return
    r = requests.post(
        f"{BASE_URL}/api/settings/model",
        headers=HEADERS,
        json={"model": model_id},
        timeout=10,
    )
    r.raise_for_status()

def vider_memoire():
    """Vide toute la mémoire via DELETE /api/memory/all."""
    r = requests.delete(f"{BASE_URL}/api/memory/all", headers=HEADERS, timeout=15)
    r.raise_for_status()

def creer_fil(label_provider):
    nom = f"[TEST] {label_provider} — {datetime.now().strftime('%d/%m %H:%M')}"
    r = requests.post(
        f"{BASE_URL}/api/threads",
        headers=HEADERS,
        json={"name": nom, "mode": "chat"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    thread_id = data.get("thread_id") or data.get("id")
    if not thread_id:
        print(f"  ❌ Réponse inattendue /api/threads : {data}")
        sys.exit(1)
    return thread_id

def envoyer_message(thread_id, texte, niveau):
    r = requests.post(
        f"{BASE_URL}/api/chat",
        headers=HEADERS,
        json={"message": texte, "thread_id": thread_id, "user_id": USER_ID},
        timeout=90,
    )
    r.raise_for_status()
    reponse = r.json()
    contenu = reponse.get("response", reponse.get("content", ""))
    if isinstance(contenu, list):
        contenu = " ".join(c.get("text", "") for c in contenu)
    extrait = str(contenu)[:80]
    print(f"  N{niveau} ↩ « {extrait}{'...' if len(str(contenu)) > 80 else ''} »")


# ── Helpers DB ───────────────────────────────────────────────

def lire_memoire_maissane():
    if not os.path.exists(DB_PATH):
        print(f"  ❌ DB introuvable : {DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT sujet, predicat, objet, valeur, poids, type_temporal
        FROM memory
        WHERE LOWER(sujet) LIKE '%ma%ssane%'
           OR LOWER(sujet) LIKE '%maissane%'
           OR LOWER(sujet) LIKE 'ma%ssane'
        ORDER BY rowid DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def _norm(s):
    if not s:
        return ""
    s = s.lower()
    for a, b in [("é","e"),("è","e"),("ê","e"),("à","a"),("î","i"),
                 ("ô","o"),("û","u"),("ï","i"),("â","a"),("ù","u")]:
        s = s.replace(a, b)
    return s

def verifier(triplets, sujet_attendu, predicat_attendu, mot_cle):
    """
    Cherche le mot_cle dans sujet, prédicat, objet ou valeur.
    Recherche large : on veut mesurer ce que le LLM a capturé,
    peu importe le prédicat utilisé.
    """
    mot = _norm(mot_cle)
    for t in triplets:
        # Vérification sujet
        if _norm(sujet_attendu) not in _norm(t.get("sujet", "")):
            continue
        # Vérification prédicat (si précisé)
        if predicat_attendu and _norm(predicat_attendu) not in _norm(t.get("predicat", "")):
            continue
        # Le mot-clé peut être dans prédicat, objet ou valeur
        texte_complet = " ".join([
            t.get("predicat", ""),
            t.get("objet", ""),
            t.get("valeur", ""),
        ])
        if mot in _norm(texte_complet):
            return True, t
    return False, None


# ── Passe unique pour un provider ────────────────────────────

def tester_provider(label, provider_id, model_id):
    _print_sep("·")
    print(f"\n  🔧 Provider : {label}")
    print(f"     provider={provider_id}  model={model_id or '(inchangé)'}")

    # Vider mémoire
    print("  🗑  Vidage mémoire...")
    vider_memoire()
    time.sleep(2)

    # Basculer provider + modèle
    set_provider(provider_id)
    if model_id:
        set_model(model_id)
    print(f"  ✅ Basculé sur {provider_id} / {model_id or 'modèle existant'}")

    # Créer fil
    thread_id = creer_fil(label)

    # Envoyer messages
    print(f"  📤 Envoi des 5 messages (délai {DELAI_ENTRE_MESSAGES}s entre chaque)...")
    for i, msg in enumerate(MESSAGES):
        envoyer_message(thread_id, msg["texte"], msg["niveau"])
        if i < len(MESSAGES) - 1:
            time.sleep(DELAI_ENTRE_MESSAGES)

    # Attente finale
    print(f"  ⏳ Attente finale {DELAI_FINAL}s...")
    time.sleep(DELAI_FINAL)

    # Lire DB
    triplets = lire_memoire_maissane()
    print(f"  📖 {len(triplets)} triplet(s) Maïssane en DB")

    # Vérifier assertions
    resultats = {}  # mot_cle → (found, triplet)
    for msg in MESSAGES:
        for (sujet, predicat, mot_cle) in msg["attendu"]:
            found, triplet = verifier(triplets, sujet, predicat, mot_cle)
            resultats[mot_cle] = (found, triplet)

    return resultats, triplets


# ── Rapport comparatif ───────────────────────────────────────

def afficher_rapport(resultats_par_provider, triplets_par_provider):
    _print_titre("RAPPORT COMPARATIF — RÉSISTANCE MÉMOIRE MAÏSSANE")

    labels = [label for label, _, _ in PROVIDERS]

    # Largeur colonnes
    col_w = 20

    # En-tête
    ligne_header = f"  {'Assertion':<22}"
    for label in labels:
        ligne_header += f"  {label[:col_w]:<{col_w}}"
    print(ligne_header)
    _print_sep("·", 62)

    niveau_courant = 0
    for msg in MESSAGES:
        if msg["niveau"] != niveau_courant:
            niveau_courant = msg["niveau"]
            print(f"\n  Niveau {niveau_courant} — {msg['label']}")
        for (_, _, mot_cle) in msg["attendu"]:
            ligne = f"    {mot_cle:<20}"
            for label, _, _ in PROVIDERS:
                found, triplet = resultats_par_provider[label].get(mot_cle, (False, None))
                if found:
                    pred = triplet.get("predicat", "?")[:14]
                    ligne += f"  ✅ [{pred}]{'':<{col_w - len(pred) - 5}}"
                else:
                    ligne += f"  {'❌':<{col_w}}"
            print(ligne)

    # Scores
    _print_sep()
    ligne_score = f"  {'SCORE':<22}"
    for label, _, _ in PROVIDERS:
        res = resultats_par_provider[label]
        ok  = sum(1 for (f, _) in res.values() if f)
        tot = len(res)
        pct = int(100 * ok / tot) if tot else 0
        ligne_score += f"  {ok}/{tot} ({pct}%){'':<{col_w - 10}}"
    print(ligne_score)
    _print_sep("═")

    # Détail triplets par provider
    for label, _, _ in PROVIDERS:
        triplets = triplets_par_provider[label]
        print(f"\n  Triplets capturés — {label} ({len(triplets)} total) :")
        _print_sep("·", 55)
        if triplets:
            for t in triplets:
                val = (t.get("objet") or t.get("valeur") or "?")[:50]
                print(f"    [{t.get('predicat','?')}] = {val}  (poids:{t.get('poids','?')})")
        else:
            print("    (aucun)")

    _print_sep("═")


# ── Main ─────────────────────────────────────────────────────

def main():
    _print_titre("NIMM — COMPARATIF PROVIDERS — MÉMOIRE MAÏSSANE")
    print(f"  URL    : {BASE_URL}")
    print(f"  User   : {USER_ID}")
    print(f"  DB     : {os.path.abspath(DB_PATH)}")
    print(f"  Début  : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"  Providers testés : {', '.join(l for l,_,_ in PROVIDERS)}")

    # Sauvegarder l'état actuel
    _print_sep()
    print("  💾 Sauvegarde provider/modèle actuel...")
    provider_origine = get_provider_actuel()
    model_origine    = get_model_actuel()
    print(f"     provider={provider_origine}  model={model_origine or '(vide)'}")

    resultats_par_provider = {}
    triplets_par_provider  = {}

    try:
        for (label, provider_id, model_id) in PROVIDERS:
            resultats, triplets = tester_provider(label, provider_id, model_id)
            resultats_par_provider[label] = resultats
            triplets_par_provider[label]  = triplets
            print(f"  ✅ Passe {label} terminée.\n")

    finally:
        # Restaurer quoi qu'il arrive
        _print_sep()
        print(f"  🔄 Restauration : provider={provider_origine}  model={model_origine or '(vide)'}")
        try:
            set_provider(provider_origine)
            if model_origine:
                set_model(model_origine)
            print("  ✅ Restauré.")
        except Exception as e:
            print(f"  ⚠️  Erreur restauration : {e}")

    # Rapport
    afficher_rapport(resultats_par_provider, triplets_par_provider)

    print(f"\n  Fin : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("  Les fils de test sont conservés dans NIMM — supprime-les manuellement.\n")


if __name__ == "__main__":
    main()
