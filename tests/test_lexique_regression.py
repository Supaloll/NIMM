# -*- coding: utf-8 -*-
"""
test_lexique_regression.py — Régression lexique contractuel NIMM
Vérifie les comportements clés après simplification du prompt système.

Prérequis : NIMM doit tourner (lance LANCER_NIMM.bat d'abord)
Exécution : python -X utf8 tests/test_lexique_regression.py

Groupes testés :
  G1 — Déclarations simples           → TAG attendu
  G2 — Requêtes pures                 → 0 TAG
  G3 — Pièges V-DOUTE                 → 0 TAG
  G4 — Pièges ÉPISODIQUE              → 0 TAG
  G5 — Pièges métaphore / fiction     → 0 TAG
  G6 — Force-TAG                      → TAG obligatoire
  G7 — Messages mixtes ÉTAT + REQUÊTE → TAG pour la partie ÉTAT seulement
  G8 — DOMINANT                       → présent à chaque tour (tous les cas)
"""

import sys, os, requests, time
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

BASE         = "http://localhost:8080"
USER_NAME    = "Thomas"
WAIT_EXTRACT = 1.5  # secondes après le message de test

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}OK   {msg}{RESET}")
def fail(msg): print(f"  {RED}ERR  {msg}{RESET}")
def info(msg): print(f"  {CYAN}     {msg}{RESET}")


# ══════════════════════════════════════════════════════════════════════════════
# CAS DE TEST
# expect_tag : True  = au moins 1 souvenir attendu en DB
#              False = aucun nouveau souvenir en DB
# ══════════════════════════════════════════════════════════════════════════════

CASES = [

    # ── G1 — Déclarations simples ─────────────────────────────────────────────
    {
        "id": "G1-01", "groupe": "G1",
        "label": "Métier déclaré",
        "msg":   "Je suis chauffeur routier.",
        "expect_tag": True,
        "note": "V-ÉTAT pur — être → C1 → TAG attendu",
    },
    {
        "id": "G1-02", "groupe": "G1",
        "label": "Relation familiale",
        "msg":   "Mon fils s'appelle Théo.",
        "expect_tag": True,
        "note": "V-ÉTAT — avoir/appeler → C1 → TAG attendu",
    },
    {
        "id": "G1-03", "groupe": "G1",
        "label": "Domicile depuis N ans",
        "msg":   "J'habite à Marseille depuis 5 ans.",
        "expect_tag": True,
        "note": "V-ÉTAT + durée ancrante → C1 → TAG attendu",
    },
    {
        "id": "G1-04", "groupe": "G1",
        "label": "Déclaration en forme de question",
        "msg":   "Tu savais que j'adore les westerns ?",
        "expect_tag": True,
        "note": "Forme interrogative mais V-ÉTAT réel → C1 → TAG attendu",
    },

    # ── G2 — Requêtes pures ───────────────────────────────────────────────────
    {
        "id": "G2-01", "groupe": "G2",
        "label": "Question factuelle",
        "msg":   "C'est quoi la différence entre un semi-remorque et un porteur ?",
        "expect_tag": False,
        "note": "V-REQUÊTE — question factuelle → C5 → 0 TAG",
    },
    {
        "id": "G2-02", "groupe": "G2",
        "label": "Recherche de service",
        "msg":   "Trouve-moi une aire de repos sur l'A7 vers Lyon.",
        "expect_tag": False,
        "note": "V-REQUÊTE impératif → C5 → 0 TAG",
    },
    {
        "id": "G2-03", "groupe": "G2",
        "label": "Demande d'explication",
        "msg":   "Tu peux m'expliquer comment fonctionne le chronotachygraphe ?",
        "expect_tag": False,
        "note": "V-REQUÊTE — pouvoir + expliquer → C5 → 0 TAG",
    },
    {
        "id": "G2-04", "groupe": "G2",
        "label": "Requête familière sans verbe classique",
        "msg":   "T'as pas un itinéraire pour éviter les bouchons sur le périph ?",
        "expect_tag": False,
        "note": "Requête indirecte → V-REQUÊTE → C5 → 0 TAG",
    },

    # ── G3 — Pièges V-DOUTE ───────────────────────────────────────────────────
    {
        "id": "G3-01", "groupe": "G3",
        "label": "Conditionnel + un jour",
        "msg":   "J'aimerais bien visiter le Japon un jour.",
        "expect_tag": False,
        "note": "V-DOUTE — conditionnel + 'un jour' → C4 → 0 TAG",
    },
    {
        "id": "G3-02", "groupe": "G3",
        "label": "Marqueur d'incertitude explicite",
        "msg":   "Peut-être que je vais changer de boulot.",
        "expect_tag": False,
        "note": "V-DOUTE — 'peut-être' → C4 → 0 TAG",
    },
    {
        "id": "G3-03", "groupe": "G3",
        "label": "Vouloir + un jour (piège V-INTENTION)",
        "msg":   "Je voudrais bien apprendre à jouer de la guitare un jour.",
        "expect_tag": False,
        "note": "V-INTENTION + conditionnel + 'un jour' → V-DOUTE → 0 TAG",
    },

    # ── G4 — Pièges ÉPISODIQUE ────────────────────────────────────────────────
    {
        "id": "G4-01", "groupe": "G4",
        "label": "État du moment",
        "msg":   "Je suis sur l'autoroute en ce moment.",
        "expect_tag": False,
        "note": "ÉPISODIQUE — 'en ce moment' → temporalité courte → 0 TAG",
    },
    {
        "id": "G4-02", "groupe": "G4",
        "label": "État du jour",
        "msg":   "Je suis crevé aujourd'hui.",
        "expect_tag": False,
        "note": "ÉPISODIQUE — 'aujourd'hui' → état temporaire → 0 TAG",
    },
    {
        "id": "G4-03", "groupe": "G4",
        "label": "Activité ce matin",
        "msg":   "Ce matin j'ai chargé à Lille.",
        "expect_tag": False,
        "note": "ÉPISODIQUE — 'ce matin' → événement ponctuel non ancrable → 0 TAG",
    },

    # ── G5 — Pièges métaphore / fiction ──────────────────────────────────────
    {
        "id": "G5-01", "groupe": "G5",
        "label": "Métaphore évidente",
        "msg":   "Je suis une vraie machine à café le matin.",
        "expect_tag": False,
        "note": "RÉEL = non — métaphore → 0 TAG",
    },
    {
        "id": "G5-02", "groupe": "G5",
        "label": "Fiction explicite",
        "msg":   "Dans mon roman, le héros s'appelle Max et il est détective.",
        "expect_tag": False,
        "note": "RÉEL = non — fiction explicite → 0 TAG",
    },
    {
        "id": "G5-03", "groupe": "G5",
        "label": "Hyperbole",
        "msg":   "J'ai conduit pendant 1000 ans aujourd'hui tellement c'était long.",
        "expect_tag": False,
        "note": "RÉEL = non — hyperbole claire → 0 TAG",
    },

    # ── G6 — Force-TAG ────────────────────────────────────────────────────────
    {
        "id": "G6-01", "groupe": "G6",
        "label": "Souviens-toi explicite",
        "msg":   "Souviens-toi que j'ai un labrador qui s'appelle Odin.",
        "expect_tag": True,
        "note": "Force-TAG — 'souviens-toi' → TAG obligatoire",
    },
    {
        "id": "G6-02", "groupe": "G6",
        "label": "Note bien",
        "msg":   "Note bien : mon anniversaire c'est le 12 mars.",
        "expect_tag": True,
        "note": "Force-TAG — 'note' → TAG obligatoire",
    },

    # ── G7 — Mixtes ÉTAT + REQUÊTE ────────────────────────────────────────────
    {
        "id": "G7-01", "groupe": "G7",
        "label": "Déclaration + recherche",
        "msg":   "J'ai deux enfants et je cherche une école primaire à Bordeaux.",
        "expect_tag": True,
        "note": "V-ÉTAT (deux enfants) → TAG · V-REQUÊTE (cherche école) → 0 TAG. TAG attendu.",
    },
    {
        "id": "G7-02", "groupe": "G7",
        "label": "Métier + demande d'explication",
        "msg":   "Je suis mécanicien et je veux que tu m'expliques les boîtes DSG.",
        "expect_tag": True,
        "note": "V-ÉTAT (mécanicien) → TAG · V-REQUÊTE (expliquer DSG) → 0 TAG. TAG attendu.",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS HTTP
# ══════════════════════════════════════════════════════════════════════════════

def ping():
    try:
        return requests.get(f"{BASE}/api/ping", timeout=5).status_code == 200
    except Exception:
        return False

def create_thread(name):
    r = requests.post(f"{BASE}/api/threads", json={"name": name}, timeout=10)
    r.raise_for_status()
    return r.json()["thread_id"]

def delete_thread(tid):
    try:
        requests.delete(f"{BASE}/api/threads/{tid}", timeout=10)
    except Exception:
        pass

def send_message(tid, content):
    r = requests.post(f"{BASE}/api/chat",
                      json={"thread_id": tid, "message": content},
                      timeout=60)
    r.raise_for_status()
    return r.json()

def get_memory_for(name: str) -> list:
    r = requests.get(f"{BASE}/api/memory/triplets", timeout=10)
    r.raise_for_status()
    return [m for m in r.json()
            if name.lower() in str(m.get("sujet", "")).lower()]


# ══════════════════════════════════════════════════════════════════════════════
# RUNNER — un cas
# ══════════════════════════════════════════════════════════════════════════════

def run_case(case: dict) -> dict:
    result = {
        "id":          case["id"],
        "groupe":      case["groupe"],
        "label":       case["label"],
        "passed":      False,
        "dominant_ok": False,
        "dominant":    "?",
        "detail":      "",
        "new_tags":    [],
    }

    tid = create_thread(f"[REG] {case['id']}")

    # Ancrage du prénom
    send_message(tid, f"Je m'appelle {USER_NAME}.")

    # Snapshot mémoire avant
    mem_before = set(
        f"{m.get('sujet')}|{m.get('predicat')}|{m.get('objet')}"
        for m in get_memory_for(USER_NAME)
    )

    # Message à tester
    resp = send_message(tid, case["msg"])
    time.sleep(WAIT_EXTRACT)

    # DOMINANT check
    dominant = resp.get("dominant", "")
    result["dominant"] = dominant if dominant else "—"
    result["dominant_ok"] = bool(dominant and dominant not in ("", "?"))

    # Snapshot mémoire après
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

    # Verdict mémoire
    if case["expect_tag"] is False:
        if not new_keys:
            result["passed"] = True
            result["detail"] = "0 TAG — correct"
        else:
            result["passed"] = False
            tags_str = " | ".join(f"{m.get('predicat')}={m.get('objet')}" for m in new_mems)
            result["detail"] = f"TAG(s) généré(s) à tort : {tags_str}"
    else:
        if new_keys:
            result["passed"] = True
            tags_str = " | ".join(f"{m.get('predicat')}={m.get('objet')}" for m in new_mems)
            result["detail"] = f"TAG(s) correct(s) : {tags_str}"
        else:
            result["passed"] = False
            result["detail"] = "Aucun TAG — la déclaration aurait dû être mémorisée"

    delete_thread(tid)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    sep = "=" * 65

    print(f"\n{BOLD}{sep}")
    print("  NIMM — RÉGRESSION LEXIQUE — post-simplification prompt")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"  {len(CASES)} cas · 8 groupes")
    print(f"{sep}{RESET}\n")

    if not ping():
        print(f"{RED}{BOLD}NIMM ne répond pas sur {BASE}.{RESET}")
        sys.exit(1)
    ok(f"NIMM actif sur {BASE}\n")

    results     = []
    groupe_actuel = None

    for case in CASES:
        if case["groupe"] != groupe_actuel:
            groupe_actuel = case["groupe"]
            labels = {
                "G1": "Déclarations simples → TAG attendu",
                "G2": "Requêtes pures → 0 TAG",
                "G3": "Pièges V-DOUTE → 0 TAG",
                "G4": "Pièges ÉPISODIQUE → 0 TAG",
                "G5": "Pièges métaphore / fiction → 0 TAG",
                "G6": "Force-TAG → TAG obligatoire",
                "G7": "Mixtes ÉTAT + REQUÊTE → TAG partial",
            }
            print(f"\n{BOLD}── {groupe_actuel} — {labels.get(groupe_actuel, '')} ──{RESET}")

        print(f"\n{BOLD}[{case['id']}] {case['label']}{RESET}")
        info(f"Msg  : « {case['msg']} »")
        info(f"Note : {case['note']}")

        r = run_case(case)
        results.append(r)

        if r["passed"]:
            ok(r["detail"])
        else:
            fail(r["detail"])
            if r["new_tags"]:
                for m in r["new_tags"]:
                    info(f"  → {m.get('sujet')} / {m.get('predicat')} = {m.get('objet')}")

        dom_icon = GREEN if r["dominant_ok"] else RED
        print(f"  {dom_icon}DOM  %%DOMINANT%% = {r['dominant']}{RESET}")

    # ── Rapport ───────────────────────────────────────────────────────────────
    print(f"\n\n{BOLD}{sep}")
    print("  RAPPORT FINAL")
    print(f"{sep}{RESET}")

    passed_mem  = sum(1 for r in results if r["passed"])
    passed_dom  = sum(1 for r in results if r["dominant_ok"])
    total       = len(results)

    print(f"\n  {'ID':<8} {'Label':<38} {'Mémoire':<10} {'Dominant'}")
    print(f"  {'─'*8} {'─'*38} {'─'*10} {'─'*10}")
    for r in results:
        m_icon = f"{GREEN}OK{RESET}      " if r["passed"] else f"{RED}ERR{RESET}     "
        d_icon = f"{GREEN}OK{RESET}" if r["dominant_ok"] else f"{RED}—{RESET}"
        print(f"  {r['id']:<8} {r['label']:<38} {m_icon} {d_icon}  {DIM}{r['dominant']}{RESET}")

    print(f"\n  Mémoire  : {passed_mem}/{total}")
    print(f"  Dominant : {passed_dom}/{total}")

    if passed_mem == total and passed_dom == total:
        print(f"\n{GREEN}{BOLD}  ✅ Régression OK — lexique simplifié conforme.{RESET}")
    else:
        missed = total - passed_mem
        no_dom = total - passed_dom
        if missed:
            print(f"\n{RED}{BOLD}  ⚠️  {missed} cas mémoire non conforme(s) — vérifier le lexique.{RESET}")
        if no_dom:
            print(f"{RED}{BOLD}  ⚠️  {no_dom} DOMINANT manquant(s) — vérifier SIGNAL dans le lexique.{RESET}")

    print(f"\n{sep}\n")


if __name__ == "__main__":
    main()
