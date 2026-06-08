# -*- coding: utf-8 -*-
"""
test_memory_proches.py — Tests mémoire proches + réponses orphelines NIMM

Vérifie la capture des faits sur les proches, les multi-faits,
et les réponses courtes sans sujet explicite (bug "12 ans").

Prérequis : NIMM doit tourner (lance LANCER_NIMM.bat d'abord)
Exécution : python -X utf8 tests/test_memory_proches.py

Groupes :
  G1 — Déclarations courtes, 1 fait direct          → 1 TAG attendu
  G2 — Fait sur un proche (sujet != Laurent)         → 1 TAG sur ce proche
  G3 — Message multi-faits                           → N TAGs attendus
  G4 — Série séquentielle (2 messages, même fil)    → TAGs après les 2 messages
  G5 — Réponse orpheline (sans sujet explicite)     → TAG attendu malgré l'absence d'ANCRE

Effet de bord voulu : les TAGs générés peuplent nimm.db avec les vraies données Laurent.
"""

import sys, requests, time
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

BASE         = "http://localhost:8080"
USER_NAME    = "Laurent"
WAIT_EXTRACT = 2.5   # secondes après le dernier message du cas

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
# ══════════════════════════════════════════════════════════════════════════════
# Chaque cas peut avoir :
#   msg             : str       — message unique
#   messages        : list[str] — séquence de messages dans le même fil
#   expect_tag      : bool      — True = au moins 1 TAG attendu, False = 0 TAG
#   expect_min_tags : int       — nb minimum de TAGs attendus (défaut 1 si expect_tag=True)
#   expect_sujet    : str|None  — filtrer les TAGs sur ce sujet (None = tous sujets)
# ══════════════════════════════════════════════════════════════════════════════

CASES = [

    # ── G1 — Déclarations courtes, 1 fait direct ─────────────────────────────
    {
        "id": "G1-01", "groupe": "G1",
        "label": "Âge déclaré",
        "msg":   "J'ai 46 ans.",
        "expect_tag":   True,
        "expect_sujet": "Laurent",
        "note": "V-ÉTAT pur → C1 → TAG Laurent|age|46",
    },
    {
        "id": "G1-02", "groupe": "G1",
        "label": "Taille déclarée",
        "msg":   "Je mesure 1m83.",
        "expect_tag":   True,
        "expect_sujet": "Laurent",
        "note": "V-ÉTAT pur → C1 → TAG Laurent|taille|1m83",
    },
    {
        "id": "G1-03", "groupe": "G1",
        "label": "Métier déclaré",
        "msg":   "Je suis chauffeur poids lourd.",
        "expect_tag":   True,
        "expect_sujet": "Laurent",
        "note": "V-ÉTAT pur → C1 → TAG Laurent|metier|chauffeur poids lourd",
    },
    {
        "id": "G1-04", "groupe": "G1",
        "label": "Épouse nommée",
        "msg":   "Ma femme s'appelle Nadia.",
        "expect_tag":   True,
        "expect_sujet": "Laurent",
        "note": "V-ÉTAT relation → C1 → TAG Laurent|epouse|Nadia",
    },

    # ── G2 — Fait sur un proche (sujet != Laurent) ───────────────────────────
    {
        "id": "G2-01", "groupe": "G2",
        "label": "Âge de Maya",
        "msg":   "Maya a 12 ans.",
        "expect_tag":   True,
        "expect_sujet": "Maya",
        "note": "V-ÉTAT sur proche → sujet=Maya → TAG Maya|age|12",
    },
    {
        "id": "G2-02", "groupe": "G2",
        "label": "Expérience couture Nadia",
        "msg":   "Nadia fait de la couture depuis 10 ans.",
        "expect_tag":   True,
        "expect_sujet": "Nadia",
        "note": "V-ÉTAT sur proche avec durée → sujet=Nadia → TAG attendu",
    },
    {
        "id": "G2-03", "groupe": "G2",
        "label": "Relation fille Maïssane",
        "msg":   "Maïssane est ma fille.",
        "expect_tag":   True,
        "expect_sujet": "Laurent",
        "note": "V-ÉTAT relation → TAG Laurent|fille|Maïssane",
    },

    # ── G3 — Message multi-faits (N TAGs attendus) ───────────────────────────
    {
        "id": "G3-01", "groupe": "G3",
        "label": "Épouse + 3 filles (≥2 TAGs)",
        "msg":   "Je suis marié à Nadia et j'ai trois filles : Innès, Maïssane et Maya.",
        "expect_tag":       True,
        "expect_min_tags":  2,
        "expect_sujet":     None,
        "note": "4 faits mémorisables → au moins 2 TAGs attendus (tous sujets)",
    },
    {
        "id": "G3-02", "groupe": "G3",
        "label": "Début métier + permis CE (≥2 TAGs)",
        "msg":   "Je fais ce métier depuis 1999 et j'ai mon permis CE depuis 1998.",
        "expect_tag":       True,
        "expect_min_tags":  2,
        "expect_sujet":     "Laurent",
        "note": "2 V-ÉTAT ancrables dans la même phrase → 2 TAGs attendus",
    },
    {
        "id": "G3-03", "groupe": "G3",
        "label": "Profil physique complet (≥3 TAGs)",
        "msg":   "J'ai 46 ans, je mesure 1m83 et je pèse 84kg.",
        "expect_tag":       True,
        "expect_min_tags":  3,
        "expect_sujet":     "Laurent",
        "note": "3 V-ÉTAT dans la même phrase → 3 TAGs attendus",
    },

    # ── G4 — Série séquentielle (2 messages, même fil) ───────────────────────
    {
        "id": "G4-01", "groupe": "G4",
        "label": "Fille Maya puis âge par pronom",
        "messages": [
            "J'ai une fille qui s'appelle Maya.",
            "Elle a 12 ans.",
        ],
        "expect_tag":   True,
        "expect_sujet": "Maya",
        "note": "Msg2 pronom 'elle' → LLM doit résoudre sujet=Maya → TAG Maya|age|12",
    },
    {
        "id": "G4-02", "groupe": "G4",
        "label": "Guitare puis ancienneté",
        "messages": [
            "Je joue de la guitare.",
            "Ça fait environ 15 ans que je pratique.",
        ],
        "expect_tag":       True,
        "expect_min_tags":  1,
        "expect_sujet":     "Laurent",
        "note": "Complément de durée en msg2 → au moins 1 TAG attendu",
    },

    # ── G5 — Réponse orpheline (sans sujet explicite dans le message) ─────────
    {
        "id": "G5-01", "groupe": "G5",
        "label": "Bug original : '12 ans' seul après contexte Maya",
        "messages": [
            "Je cherche un roman pour ma fille Maya.",
            "12 ans",
        ],
        "expect_tag":   True,
        "expect_sujet": "Maya",
        "note": "Bug réel : chiffre seul en réponse → LLM doit capturer Maya|age|12 depuis le contexte",
    },
    {
        "id": "G5-02", "groupe": "G5",
        "label": "Durée orpheline après contexte Nadia couture",
        "messages": [
            "Nadia a monté une micro-entreprise de couture.",
            "10 ans d'expérience.",
        ],
        "expect_tag":   True,
        "expect_sujet": "Nadia",
        "note": "Complément sans verbe ni sujet → LLM doit relier à Nadia + couture",
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
                      timeout=90)
    r.raise_for_status()
    return r.json()

def snapshot_all_memory() -> set:
    """Retourne un set de clés 'sujet|predicat|objet' pour toute la mémoire."""
    r = requests.get(f"{BASE}/api/memory/triplets", timeout=10)
    r.raise_for_status()
    return set(
        f"{m.get('sujet')}|{m.get('predicat')}|{m.get('objet')}"
        for m in r.json()
    )

def get_all_memory_raw() -> list:
    r = requests.get(f"{BASE}/api/memory/triplets", timeout=10)
    r.raise_for_status()
    return r.json()


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

    messages     = case.get("messages") or [case["msg"]]
    expect_tag   = case.get("expect_tag", True)
    expect_min   = case.get("expect_min_tags", 1 if expect_tag else 0)
    expect_sujet = case.get("expect_sujet", USER_NAME)  # None = tous sujets

    tid = create_thread(f"[PROCHES] {case['id']}")

    # Ancrage du prénom
    send_message(tid, f"Je m'appelle {USER_NAME}.")

    # Snapshot avant
    mem_before = snapshot_all_memory()

    # Envoi séquentiel
    last_resp = None
    for i, msg in enumerate(messages):
        last_resp = send_message(tid, msg)
        if i < len(messages) - 1:
            time.sleep(WAIT_EXTRACT)   # pause entre messages intermédiaires
    time.sleep(WAIT_EXTRACT)           # pause finale pour laisser l'extraction s'achever

    # DOMINANT
    dominant = (last_resp or {}).get("dominant", "")
    result["dominant"] = dominant if dominant else "—"
    result["dominant_ok"] = bool(dominant and dominant not in ("", "?"))

    # Snapshot après
    mem_after_raw = get_all_memory_raw()
    mem_after_set = set(
        f"{m.get('sujet')}|{m.get('predicat')}|{m.get('objet')}"
        for m in mem_after_raw
    )
    new_keys = mem_after_set - mem_before

    # Filtrage par sujet attendu
    if expect_sujet is None:
        new_mems = [
            m for m in mem_after_raw
            if f"{m.get('sujet')}|{m.get('predicat')}|{m.get('objet')}" in new_keys
        ]
    else:
        new_mems = [
            m for m in mem_after_raw
            if f"{m.get('sujet')}|{m.get('predicat')}|{m.get('objet')}" in new_keys
            and expect_sujet.lower() in str(m.get('sujet', '')).lower()
        ]
    result["new_tags"] = new_mems

    # Verdict
    if not expect_tag:
        if not new_mems:
            result["passed"] = True
            result["detail"] = "0 TAG — correct"
        else:
            tags_str = " | ".join(
                f"{m.get('sujet')}.{m.get('predicat')}={m.get('objet')}"
                for m in new_mems
            )
            result["detail"] = f"TAGs générés à tort : {tags_str}"
    else:
        n = len(new_mems)
        if n >= expect_min:
            result["passed"] = True
            tags_str = " | ".join(
                f"{m.get('sujet')}.{m.get('predicat')}={m.get('objet')}"
                for m in new_mems
            )
            result["detail"] = f"{n} TAG(s) : {tags_str}"
        elif n > 0:
            tags_str = " | ".join(
                f"{m.get('sujet')}.{m.get('predicat')}={m.get('objet')}"
                for m in new_mems
            )
            result["passed"] = False
            result["detail"] = f"Seulement {n}/{expect_min} TAG(s) : {tags_str}"
        else:
            sujet_label = expect_sujet if expect_sujet else "tout sujet"
            result["passed"] = False
            result["detail"] = f"0 TAG pour '{sujet_label}' — attendu ≥{expect_min}"

    # Passe mémoire explicite avant suppression — simule le comportement UI
    try:
        requests.post(f"{BASE}/api/threads/{tid}/memorize", timeout=30)
        time.sleep(WAIT_EXTRACT)
    except Exception:
        pass

    # Re-snapshot après la passe mémoire
    mem_after_raw2 = get_all_memory_raw()
    mem_after_set2 = set(
        f"{m.get('sujet')}|{m.get('predicat')}|{m.get('objet')}"
        for m in mem_after_raw2
    )
    new_keys2 = mem_after_set2 - mem_before

    if expect_sujet is None:
        new_mems2 = [
            m for m in mem_after_raw2
            if f"{m.get('sujet')}|{m.get('predicat')}|{m.get('objet')}" in new_keys2
        ]
    else:
        new_mems2 = [
            m for m in mem_after_raw2
            if f"{m.get('sujet')}|{m.get('predicat')}|{m.get('objet')}" in new_keys2
            and expect_sujet.lower() in str(m.get('sujet', '')).lower()
        ]

    # Si la passe fenêtre a rattrapé des tags manqués → mettre à jour le résultat
    if not result["passed"] and len(new_mems2) >= expect_min and len(new_mems2) > 0:
        result["passed"] = True
        result["new_tags"] = new_mems2
        tags_str = " | ".join(
            f"{m.get('sujet')}.{m.get('predicat')}={m.get('objet')}"
            for m in new_mems2
        )
        result["detail"] = f"[PASSE FENÊTRE] {len(new_mems2)} TAG(s) : {tags_str}"
    elif result["passed"] and new_mems2:
        result["new_tags"] = new_mems2

    delete_thread(tid)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

GROUP_LABELS = {
    "G1": "Déclarations courtes → 1 TAG",
    "G2": "Fait sur un proche (sujet != Laurent)",
    "G3": "Multi-faits → N TAGs attendus",
    "G4": "Série séquentielle (2 messages)",
    "G5": "Réponse orpheline (sans sujet explicite)",
}

def main():
    sep = "=" * 68

    print(f"\n{BOLD}{sep}")
    print("  NIMM — MÉMOIRE PROCHES + RÉPONSES ORPHELINES")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"  {len(CASES)} cas · 5 groupes")
    print(f"  Les TAGs générés peuplent nimm.db (données réelles Laurent)")
    print(f"{sep}{RESET}\n")

    if not ping():
        print(f"{RED}{BOLD}NIMM ne répond pas sur {BASE}.{RESET}")
        sys.exit(1)
    ok(f"NIMM actif sur {BASE}\n")

    results       = []
    groupe_actuel = None

    for case in CASES:
        if case["groupe"] != groupe_actuel:
            groupe_actuel = case["groupe"]
            print(f"\n{BOLD}── {groupe_actuel} — {GROUP_LABELS.get(groupe_actuel, '')} ──{RESET}")

        messages  = case.get("messages") or [case.get("msg", "")]
        nb_msgs   = len(messages)
        seq_label = f" [{nb_msgs} msgs]" if nb_msgs > 1 else ""
        print(f"\n{BOLD}[{case['id']}] {case['label']}{seq_label}{RESET}")

        for i, m in enumerate(messages):
            prefix = f"Msg{i+1}" if nb_msgs > 1 else "Msg "
            info(f"{prefix} : « {m} »")
        info(f"Note : {case['note']}")

        r = run_case(case)
        results.append(r)

        if r["passed"]:
            ok(r["detail"])
        else:
            fail(r["detail"])

        dom_icon = GREEN if r["dominant_ok"] else RED
        print(f"  {dom_icon}DOM  %%DOMINANT%% = {r['dominant']}{RESET}")

    # ── Rapport final ─────────────────────────────────────────────────────────
    print(f"\n\n{BOLD}{sep}")
    print("  RAPPORT FINAL")
    print(f"{sep}{RESET}")

    passed_mem = sum(1 for r in results if r["passed"])
    passed_dom = sum(1 for r in results if r["dominant_ok"])
    total      = len(results)

    print(f"\n  {'ID':<8} {'Label':<42} {'Mémoire':<12} {'DOM'}")
    print(f"  {'─'*8} {'─'*42} {'─'*12} {'─'*5}")
    for r in results:
        m_icon = f"{GREEN}OK{RESET}        " if r["passed"] else f"{RED}ERR{RESET}       "
        d_icon = f"{GREEN}OK{RESET}" if r["dominant_ok"] else f"{RED}—{RESET}"
        print(f"  {r['id']:<8} {r['label']:<42} {m_icon} {d_icon}")

    print(f"\n  Mémoire  : {passed_mem}/{total}")
    print(f"  Dominant : {passed_dom}/{total}")

    print(f"\n  Détail par groupe :")
    groupes: dict = {}
    for r in results:
        g = r["groupe"]
        if g not in groupes:
            groupes[g] = {"total": 0, "passed": 0}
        groupes[g]["total"] += 1
        if r["passed"]:
            groupes[g]["passed"] += 1
    for g, s in groupes.items():
        icon = GREEN if s["passed"] == s["total"] else RED
        print(f"  {icon}  {g} : {s['passed']}/{s['total']} — {GROUP_LABELS.get(g, '')}{RESET}")

    if passed_mem == total:
        print(f"\n{GREEN}{BOLD}  ✅ Tous les cas mémoire OK.{RESET}")
    else:
        missed = total - passed_mem
        print(f"\n{RED}{BOLD}  ⚠️  {missed} cas non conforme(s) :{RESET}")
        for r in results:
            if not r["passed"]:
                print(f"  {RED}  → [{r['id']}] {r['label']} : {r['detail']}{RESET}")

    print(f"\n{sep}\n")


if __name__ == "__main__":
    main()
