# -*- coding: utf-8 -*-
"""
test_c5_requete.py — Audit C5 : V-REQUÊTE ne doit jamais générer de TAG
Vérifie que le LLM ne stocke aucun souvenir à partir d'une recherche,
d'une question ou d'une requête — même répétée ou formulée avec intention.

Usage : python tests/test_c5_requete.py
NIMM doit tourner sur localhost:8080.
"""

import requests
import time
import sys
from datetime import datetime

BASE           = "http://localhost:8080"
WAIT_EXTRACT   = 1.2  # secondes après le message de test uniquement
USER_NAME      = "Nadia"   # prénom utilisé pour cibler les souvenirs en DB

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}OK   {msg}{RESET}")
def fail(msg): print(f"  {RED}ERR  {msg}{RESET}")
def warn(msg): print(f"  {YELLOW}WARN {msg}{RESET}")
def info(msg): print(f"  {CYAN}     {msg}{RESET}")

# ─── Cas de test ───────────────────────────────────────────────────────────────
# expect_tag=False → aucun nouveau souvenir ne doit apparaître après ce message
# expect_tag=True  → au moins un souvenir attendu (cas mixte ÉTAT + REQUÊTE)
# note             → explication du cas

CASES = [
    # ── Cas purs V-REQUÊTE — 0 TAG attendu ────────────────────────────────────
    {
        "id": "C5-01",
        "label": "Recherche patron couture",
        "msg": "je cherche des patrons de manches tulipe",
        "expect_tag": False,
        "note": "V-REQUÊTE pur — chercher → C5 → 0 TAG",
    },
    {
        "id": "C5-02",
        "label": "Demande de recette",
        "msg": "tu peux me trouver une recette de tarte aux pommes ?",
        "expect_tag": False,
        "note": "V-REQUÊTE pur — trouver → C5 → 0 TAG",
    },
    {
        "id": "C5-03",
        "label": "Recherche médecin",
        "msg": "j'ai besoin de trouver un médecin à Nancy",
        "expect_tag": False,
        "note": "V-REQUÊTE pur — besoin de trouver → C5 → 0 TAG",
    },
    {
        "id": "C5-04",
        "label": "Intérêt formulé comme recherche",
        "msg": "je m'intéresse aux techniques de broderie en ce moment",
        "expect_tag": False,
        "note": "V-REQUÊTE déguisé — s'intéresser à ≠ déclaration stable → C5 → 0 TAG",
    },
    {
        "id": "C5-05",
        "label": "Recherche explicite avec 'recherche'",
        "msg": "recherche-moi des informations sur les chaussures de randonnée",
        "expect_tag": False,
        "note": "V-REQUÊTE impératif — rechercher → C5 → 0 TAG",
    },
    {
        "id": "C5-06",
        "label": "Question sur un produit",
        "msg": "tu peux me montrer des modèles de robes de soirée en soie ?",
        "expect_tag": False,
        "note": "V-REQUÊTE — montrer → C5 → 0 TAG",
    },
    {
        "id": "C5-07",
        "label": "Hésitation entre deux options",
        "msg": "j'hésite entre les chaussures bleues et les chaussures rouges",
        "expect_tag": False,
        "note": "V-DOUTE — hésiter → C4 → 0 TAG (ni préférence ni déclaration)",
    },

    # ── Pièges d'inférence — le LLM ne doit PAS inférer une préférence ─────────
    {
        "id": "C5-08",
        "label": "Répétition de recherche — piège d'inférence",
        "msg": "ça fait 3 fois que je cherche des recettes végétariennes cette semaine",
        "expect_tag": False,
        "note": "Répétition ≠ préférence déclarée — C5 interdit l'inférence végétarien",
    },
    {
        "id": "C5-09",
        "label": "Recherche pour quelqu'un d'autre",
        "msg": "je cherche une idée de cadeau pour Laurent",
        "expect_tag": False,
        "note": "V-REQUÊTE — le sujet de la recherche n'est pas Nadia → 0 TAG sur Nadia",
    },
    {
        "id": "C5-10",
        "label": "Demande de conseil sur un choix futur",
        "msg": "je veux peut-être apprendre la broderie anglaise un jour",
        "expect_tag": False,
        "note": "V-DOUTE + futur hypothétique — vouloir peut-être → C4 → 0 TAG",
    },

    # ── V-INTENTION : les trois cas de "vouloir" ───────────────────────────────
    {
        "id": "C5-13",
        "label": "Vouloir sans marqueur — intention ferme",
        "msg": "je veux apprendre la broderie anglaise",
        "expect_tag": True,
        "note": "V-INTENTION sans marqueur d'incertitude → V-ÉTAT → C1 → TAG attendu",
    },
    {
        "id": "C5-14",
        "label": "Vouloir dans une requête directe",
        "msg": "je veux que tu me trouves un modèle de robe de soirée",
        "expect_tag": False,
        "note": "V-INTENTION dans requête → V-REQUÊTE → C5 → 0 TAG",
    },

    # ── Formulations indirectes de requête ─────────────────────────────────────
    {
        "id": "C5-15",
        "label": "Requête familière indirecte",
        "msg": "t'as pas un truc pour enlever les taches sur la soie ?",
        "expect_tag": False,
        "note": "Requête familière sans verbe classique → V-REQUÊTE → C5 → 0 TAG",
    },
    {
        "id": "C5-16",
        "label": "Requête conditionnelle indirecte",
        "msg": "ça m'intéresserait de savoir comment faire un col claudine",
        "expect_tag": False,
        "note": "Formulation indirecte de requête → V-REQUÊTE → C5 → 0 TAG",
    },
    {
        "id": "C5-17",
        "label": "Requête avec 'tu aurais'",
        "msg": "tu aurais une idée pour moderniser une veste en tweed ?",
        "expect_tag": False,
        "note": "Requête conditionnelle adressée à NIMM → V-REQUÊTE → C5 → 0 TAG",
    },

    # ── Requête déguisée en déclaration ────────────────────────────────────────
    {
        "id": "C5-18",
        "label": "Activité en cours ambiguë",
        "msg": "en ce moment je suis sur les manches gigot",
        "expect_tag": False,
        "note": "ÉPISODIQUE — 'en ce moment' = temporalité courte → 0 TAG correct",
    },

    # ── Déclaration déguisée en question — TAG attendu ─────────────────────────
    {
        "id": "C5-19",
        "label": "Déclaration formulée comme question",
        "msg": "tu savais que j'ai horreur des cols roulés ?",
        "expect_tag": True,
        "note": "Forme interrogative mais déclaration réelle → V-ÉTAT → C1 → TAG attendu",
    },

    # ── Temporalité — épisodique vs ancrable ───────────────────────────────────
    {
        "id": "C5-20",
        "label": "Fatigue épisodique",
        "msg": "je suis fatiguée aujourd'hui",
        "expect_tag": False,
        "note": "État temporaire du jour → épisodique → non ancrable → 0 TAG",
    },
    {
        "id": "C5-21",
        "label": "Fatigue chronique — sujet santé sensible",
        "msg": "je suis fatiguée en permanence depuis 6 mois",
        "expect_tag": False,
        "note": "Santé sensible non clarifié → prudence → CLARIF avant TAG → 0 TAG par défaut",
    },

    # ── Requête à la troisième personne sur soi ────────────────────────────────
    {
        "id": "C5-22",
        "label": "Recherche pour une cliente",
        "msg": "je cherche des patrons de robe pour une cliente qui fait du 46",
        "expect_tag": False,
        "note": "Requête pour autrui — le fait concerne la cliente, pas Nadia → 0 TAG",
    },

    # ── Cas mixtes — TAG attendu pour la partie ÉTAT uniquement ────────────────
    {
        "id": "C5-11",
        "label": "Mixte ÉTAT + REQUÊTE",
        "msg": "je fais de la couture depuis 10 ans et je cherche des patrons de manche tulipe",
        "expect_tag": True,
        "note": "V-ÉTAT (couture depuis 10 ans) → 1 TAG · V-REQUÊTE (cherche patrons) → 0 TAG",
    },
    {
        "id": "C5-12",
        "label": "Mixte ÉTAT + REQUÊTE — santé",
        "msg": "j'ai mal au dos depuis hier, tu peux me trouver un kiné ?",
        "expect_tag": True,
        "note": "V-ÉTAT (mal au dos) → 1 TAG · V-REQUÊTE (trouver kiné) → 0 TAG",
    },
]

# ─── Helpers HTTP ──────────────────────────────────────────────────────────────

def ping():
    try:
        r = requests.get(f"{BASE}/api/ping", timeout=5)
        return r.status_code == 200
    except Exception:
        return False

def create_thread(name):
    r = requests.post(f"{BASE}/api/threads", json={"name": name}, timeout=10)
    r.raise_for_status()
    return r.json()["thread_id"]

def delete_thread(thread_id):
    try:
        requests.delete(f"{BASE}/api/threads/{thread_id}", timeout=10)
    except Exception:
        pass

def send_message(thread_id, content):
    r = requests.post(f"{BASE}/api/chat",
                      json={"thread_id": thread_id, "message": content},
                      timeout=60)
    r.raise_for_status()
    return r.json()

def get_memory_for(name: str) -> list:
    """Retourne tous les souvenirs dont le sujet correspond à name."""
    r = requests.get(f"{BASE}/api/memory/triplets", timeout=10)
    r.raise_for_status()
    all_mem = r.json()
    return [m for m in all_mem if name.lower() in str(m.get("sujet", "")).lower()]

def clear_memory():
    """Vide toute la mémoire non verrouillée entre les cas."""
    try:
        requests.delete(f"{BASE}/api/memory/all", timeout=10)
    except Exception:
        pass

# ─── Runner ───────────────────────────────────────────────────────────────────

def run_case(case: dict) -> dict:
    result = {
        "id":      case["id"],
        "label":   case["label"],
        "passed":  False,
        "warning": False,
        "detail":  "",
        "new_tags": [],
    }

    # Fil isolé par cas
    thread_id = create_thread(f"[TEST-C5] {case['id']}")

    # Ancrage du prénom — sans ça, le LLM ne connaît pas le sujet
    send_message(thread_id, f"Je m'appelle {USER_NAME}.")
    # pas d'attente ici — l'ancrage ne génère pas de souvenir à mesurer

    # Snapshot avant
    mem_before = set(
        f"{m.get('sujet')}|{m.get('predicat')}|{m.get('objet')}"
        for m in get_memory_for(USER_NAME)
    )

    # Message à tester
    send_message(thread_id, case["msg"])
    time.sleep(WAIT_EXTRACT)

    # Snapshot après
    mem_after_list = get_memory_for(USER_NAME)
    mem_after = set(
        f"{m.get('sujet')}|{m.get('predicat')}|{m.get('objet')}"
        for m in mem_after_list
    )

    new_keys = mem_after - mem_before
    new_mems = [
        m for m in mem_after_list
        if f"{m.get('sujet')}|{m.get('predicat')}|{m.get('objet')}" in new_keys
    ]
    result["new_tags"] = new_mems

    if case["expect_tag"] is False:
        if not new_keys:
            result["passed"] = True
            result["detail"] = "Aucun TAG généré — correct"
        else:
            result["passed"] = False
            tags_str = " | ".join(
                f"{m.get('predicat')}={m.get('valeur')}" for m in new_mems
            )
            result["detail"] = f"TAG(s) généré(s) à tort : {tags_str}"

    elif case["expect_tag"] is True:
        if new_keys:
            result["passed"] = True
            tags_str = " | ".join(
                f"{m.get('predicat')}={m.get('objet')}" for m in new_mems
            )
            result["detail"] = f"TAG(s) généré(s) — correct : {tags_str}"
        else:
            result["passed"] = False
            result["detail"] = "Aucun TAG généré — la partie V-ÉTAT aurait dû produire un TAG"

    delete_thread(thread_id)
    return result


def main():
    print(f"\n{BOLD}{'='*62}")
    print("  NIMM — AUDIT C5 : V-REQUÊTE ne génère pas de TAG")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"{'='*62}{RESET}\n")

    if not ping():
        print(f"{RED}{BOLD}NIMM ne répond pas sur {BASE}.{RESET}")
        sys.exit(1)
    ok(f"NIMM actif sur {BASE}")
    print()

    results = []

    for case in CASES:
        print(f"{BOLD}[{case['id']}] {case['label']}{RESET}")
        info(f"Message : « {case['msg']} »")
        info(f"Note    : {case['note']}")

        r = run_case(case)
        results.append(r)

        if r["passed"]:
            ok(r["detail"])
        else:
            fail(r["detail"])
            if r["new_tags"]:
                for m in r["new_tags"]:
                    info(f"  → {m.get('sujet')} / {m.get('predicat')} = {m.get('objet')}")
        print()

    # ─── Rapport ──────────────────────────────────────────────────────────────
    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed

    print(f"{BOLD}{'='*62}")
    print("  RAPPORT FINAL")
    print(f"{'='*62}{RESET}")
    for r in results:
        badge = GREEN if r["passed"] else RED
        sym   = "OK " if r["passed"] else "ERR"
        print(f"  {badge}{sym} [{r['id']}] {r['label']}{RESET}")

    print(f"\n{BOLD}  Score : {passed}/{len(results)}{RESET}")
    if failed == 0:
        print(f"{GREEN}{BOLD}  Tous les cas C5 sont conformes.{RESET}")
    else:
        print(f"{RED}{BOLD}  {failed} cas non conforme(s) — correction lexique nécessaire.{RESET}")
    print(f"\n{'='*62}\n")


if __name__ == "__main__":
    main()
