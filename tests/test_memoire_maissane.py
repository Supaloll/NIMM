# ============================================================
# NIMM — tests/test_memoire_maissane.py
# Test de résistance mémoire — Maïssane (5 niveaux de précision)
#
# Usage :
#   Depuis le dossier racine de NIMM :
#   python tests/test_memoire_maissane.py
#
# Prérequis :
#   - NIMM tourne sur http://localhost:8080
#   - Profil Laurent actif
#   - pip install requests (standard, déjà présent)
# ============================================================

import sqlite3
import time
import json
import os
import sys
import uuid
import requests
from datetime import datetime

# ── Config ──────────────────────────────────────────────────
BASE_URL  = "http://localhost:8080"
USER_ID   = "laurent"
DB_PATH   = os.path.join(os.path.dirname(__file__), '..', 'data', 'nimm_laurent.db')
HEADERS   = {"Content-Type": "application/json", "x-user-id": USER_ID}

# Délai entre chaque message (secondes) — laisse le worker async traiter
DELAI_ENTRE_MESSAGES = 8
# Délai final après le dernier message avant lecture DB
DELAI_FINAL = 15

# ── Messages de test (niveaux 1 → 5) ─────────────────────────
MESSAGES = [
    # Niveau 1 — Faits bruts simples
    {
        "niveau": 1,
        "label": "Faits simples (âge, bac, lycée)",
        "texte": (
            "Ma fille Maïssane a 18 ans et elle passe le bac cette semaine. "
            "Elle est en Terminale au lycée Bartholdi à Colmar."
        ),
        "attendu": [
            ("Maïssane", "age", "18"),
            ("Maïssane", "ecole", "Bartholdi"),
        ],
    },
    # Niveau 2 — Faits chiffrés
    {
        "niveau": 2,
        "label": "Faits chiffrés (années de pratique, compétitions)",
        "texte": (
            "Maïssane fait du judo depuis 6 ans au club Colmar Judo. "
            "Cette saison elle a participé à 4 compétitions."
        ),
        "attendu": [
            ("Maïssane", "sport", "judo"),
            ("Maïssane", "sport", "6"),       # '6 ans' quelque part dans la valeur
            ("Maïssane", "sport", "4"),        # '4 compétitions' quelque part
        ],
    },
    # Niveau 3 — Traits de caractère
    {
        "niveau": 3,
        "label": "Traits de caractère (douce, émotive, agressivité)",
        "texte": (
            "Maïssane est une fille très douce et assez émotive. "
            "Sur le tapis elle manque parfois d'agressivité, ça lui coûte des points."
        ),
        "attendu": [
            ("Maïssane", "trait", "douce"),
            ("Maïssane", "trait", "émotive"),
            ("Maïssane", "trait", "agressivité"),
        ],
    },
    # Niveau 4 — Nuances techniques
    {
        "niveau": 4,
        "label": "Nuances techniques (ippon vs décision)",
        "texte": (
            "Elle gagne rarement par ippon. "
            "La plupart de ses victoires viennent aux points, par décision des arbitres."
        ),
        "attendu": [
            ("Maïssane", None, "ippon"),       # prédicat inconnu, on cherche le mot
            ("Maïssane", None, "décision"),
        ],
    },
    # Niveau 5 — Anecdote narrative
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
            ("Maïssane", None, "département"),  # 'départementale'
            ("Maïssane", None, "fier"),
        ],
    },
]


# ── Helpers ──────────────────────────────────────────────────

def _print_sep(char="─", n=60):
    print(char * n)

def _print_titre(texte):
    _print_sep("═")
    print(f"  {texte}")
    _print_sep("═")

def creer_fil():
    """Crée un fil de test dédié dans NIMM."""
    nom = f"[TEST] Mémoire Maïssane — {datetime.now().strftime('%d/%m %H:%M')}"
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
        print(f"❌ Réponse inattendue de /api/threads : {data}")
        sys.exit(1)
    print(f"✅ Fil créé : {nom}")
    print(f"   ID : {thread_id}")
    return thread_id

def envoyer_message(thread_id, texte, niveau):
    """Envoie un message à NIMM via /api/chat et affiche la réponse courte."""
    print(f"\n📤 Niveau {niveau} → envoi...")
    print(f"   « {texte[:80]}{'...' if len(texte) > 80 else ''} »")
    r = requests.post(
        f"{BASE_URL}/api/chat",
        headers=HEADERS,
        json={"message": texte, "thread_id": thread_id, "user_id": USER_ID},
        timeout=60,
    )
    r.raise_for_status()
    reponse = r.json()
    contenu = reponse.get("response", reponse.get("content", ""))
    if isinstance(contenu, list):
        contenu = " ".join(c.get("text", "") for c in contenu)
    print(f"   ↩ NIMM : « {str(contenu)[:100]}{'...' if len(str(contenu)) > 100 else ''} »")
    return True

def lire_memoire():
    """Lit directement la DB SQLite et retourne tous les triplets de Maïssane."""
    if not os.path.exists(DB_PATH):
        print(f"❌ DB introuvable : {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT sujet, predicat, objet, valeur, poids, type_temporal, timestamp
        FROM memory
        WHERE LOWER(sujet) LIKE '%ma%ssane%' OR LOWER(sujet) LIKE '%maissane%'
           OR LOWER(sujet) LIKE 'ma%ssane'
        ORDER BY timestamp DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def verifier_attendu(triplets, sujet_attendu, predicat_attendu, mot_cle):
    """
    Cherche si un triplet correspond à l'attendu.
    - sujet_attendu : toujours 'Maïssane' (comparaison souple)
    - predicat_attendu : None = on ne filtre pas le prédicat
    - mot_cle : doit apparaître dans objet ou valeur (insensible casse, accents ignorés)
    """
    def _norm(s):
        if not s:
            return ""
        s = s.lower()
        # Simplification accents pour comparaison souple
        for a, b in [("é","e"),("è","e"),("ê","e"),("à","a"),("î","i"),("ô","o"),("û","u"),("ï","i")]:
            s = s.replace(a, b)
        return s

    mot_norm = _norm(mot_cle)

    for t in triplets:
        sujet_ok = _norm(sujet_attendu) in _norm(t.get("sujet", ""))
        pred_ok  = (predicat_attendu is None) or (_norm(predicat_attendu) in _norm(t.get("predicat", "")))
        valeur_txt = f"{t.get('objet','')} {t.get('valeur','')}".strip()
        valeur_ok = mot_norm in _norm(valeur_txt)

        if sujet_ok and pred_ok and valeur_ok:
            return True, t
    return False, None

def afficher_rapport(resultats_par_niveau, tous_triplets):
    """Affiche le rapport final."""
    _print_titre("RAPPORT FINAL — RÉSISTANCE MÉMOIRE MAÏSSANE")

    total_ok  = 0
    total_ko  = 0

    for niveau, label, assertions in resultats_par_niveau:
        print(f"\n  Niveau {niveau} — {label}")
        _print_sep("·", 55)
        for sujet, predicat, mot_cle, found, triplet in assertions:
            if found:
                total_ok += 1
                pred_str = triplet.get("predicat", "?")
                val_str  = triplet.get("objet") or triplet.get("valeur") or "?"
                print(f"  ✅ '{mot_cle}' → [{pred_str}] = {val_str[:60]}")
            else:
                total_ko += 1
                pred_hint = f" (prédicat: {predicat})" if predicat else ""
                print(f"  ❌ '{mot_cle}'{pred_hint} → NON capturé")

    _print_sep("═")
    pct = int(100 * total_ok / (total_ok + total_ko)) if (total_ok + total_ko) else 0
    print(f"\n  Score : {total_ok}/{total_ok + total_ko} attendus capturés ({pct}%)")
    _print_sep()

    # Tous les triplets Maïssane stockés (bonus)
    print(f"\n  Triplets Maïssane en DB ({len(tous_triplets)} total) :")
    _print_sep("·", 55)
    if tous_triplets:
        for t in tous_triplets:
            poids = t.get("poids", "?")
            print(f"  [{t.get('predicat','?')}] = {(t.get('objet') or t.get('valeur') or '?')[:60]}  (poids:{poids})")
    else:
        print("  (aucun)")
    _print_sep("═")


# ── Main ─────────────────────────────────────────────────────

def main():
    _print_titre("NIMM — TEST RÉSISTANCE MÉMOIRE MAÏSSANE")
    print(f"  URL    : {BASE_URL}")
    print(f"  User   : {USER_ID}")
    print(f"  DB     : {os.path.abspath(DB_PATH)}")
    print(f"  Début  : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

    # ── 1. Créer le fil
    _print_sep()
    thread_id = creer_fil()

    # ── 2. Envoyer les messages niveau par niveau
    _print_sep()
    print("  Envoi des messages (délai entre chaque : {}s)".format(DELAI_ENTRE_MESSAGES))

    for msg in MESSAGES:
        envoyer_message(thread_id, msg["texte"], msg["niveau"])
        if msg["niveau"] < len(MESSAGES):
            print(f"   ⏳ Attente {DELAI_ENTRE_MESSAGES}s (worker async)...")
            time.sleep(DELAI_ENTRE_MESSAGES)

    # ── 3. Attente finale
    print(f"\n⏳ Attente finale {DELAI_FINAL}s (worker traite le dernier message)...")
    time.sleep(DELAI_FINAL)

    # ── 4. Lecture DB
    _print_sep()
    print("📖 Lecture de la mémoire en DB...")
    tous_triplets = lire_memoire()
    print(f"   {len(tous_triplets)} triplet(s) trouvé(s) pour Maïssane")

    # ── 5. Vérification assertions
    resultats_par_niveau = []
    for msg in MESSAGES:
        assertions = []
        for (sujet, predicat, mot_cle) in msg["attendu"]:
            found, triplet = verifier_attendu(tous_triplets, sujet, predicat, mot_cle)
            assertions.append((sujet, predicat, mot_cle, found, triplet))
        resultats_par_niveau.append((msg["niveau"], msg["label"], assertions))

    # ── 6. Rapport
    afficher_rapport(resultats_par_niveau, tous_triplets)

    print(f"\n  Fin : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"  Fil de test conservé dans NIMM (ID : {thread_id})")
    print(f"  Tu peux le supprimer manuellement depuis l'interface.\n")


if __name__ == "__main__":
    main()
