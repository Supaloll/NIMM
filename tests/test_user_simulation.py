# -*- coding: utf-8 -*-
"""
test_user_simulation.py — Audit comportemental NIMM
Simule plusieurs profils utilisateur via l'API HTTP réelle.
NIMM doit tourner sur localhost:8080 avant de lancer ce script.
Aucune écriture directe en DB — tout passe par les routes.
"""

import requests
import time
import json
import sys
from datetime import datetime

BASE = "http://localhost:8080"
WAIT_EXTRACTION = 4  # secondes pour laisser l'extraction asynchrone se faire

# ─── Couleurs terminal ─────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}OK {msg}{RESET}")
def fail(msg): print(f"  {RED}ERR {msg}{RESET}")
def warn(msg): print(f"  {YELLOW}WARN {msg}{RESET}")
def info(msg): print(f"  {CYAN}INFO {msg}{RESET}")

# ─── Scenarios utilisateur ─────────────────────────────────────────────────────

SCENARIOS = [
    {
        "label": "Profil A — Adulte direct (style Laurent)",
        "name":  "Laurent",
        "thread_name": "[TEST] Laurent direct",
        "sequence": [
            "Salut, je m'appelle Laurent. Je suis routier et j'adore la choucroute.",
            "J'ai trois filles : Maissane, Maya et Innes.",
            "En ce moment je bosse sur un projet IA que j'appelle NIMM.",
            "C'est quoi selon toi le plus gros defi dans le developpement d'un assistant IA personnel ?",
        ],
        "recall_msg": "Tu te souviens de mon prenom et de mon metier ?",
        "recall_checks": ["Laurent", "routier"],
    },
    {
        "label": "Profil B — Ado decontractee (style Maissane)",
        "name":  "Mei",
        "thread_name": "[TEST] Mei ado",
        "sequence": [
            "yo c'est Mei, j'ai 17 ans et je suis en terminale",
            "jsuis trop stresse par le bac philo lkjsdflk",
            "mon truc prefere c'est la musique et les mangas",
            "t'as des conseils pour apprendre a gerer le stress des exams ?",
        ],
        "recall_msg": "tu te rappelles ce que j'aime comme passe-temps ?",
        "recall_checks": ["musique", "manga"],
    },
    {
        "label": "Profil C — Utilisatrice couture (style Nadia)",
        "name":  "Nadia",
        "thread_name": "[TEST] Nadia couture",
        "sequence": [
            "Bonjour, je suis Nadia, j'ai une boutique de couture qui s'appelle LIMM.",
            "Je cherche des idees de modeles pour une robe de soiree en soie.",
            "J'aime beaucoup les cols benitiers et les manches legeres.",
            "Quelle difference entre la mousseline et le crepe georgette ?",
        ],
        "recall_msg": "Tu te souviens du nom de ma boutique ?",
        "recall_checks": ["LIMM"],
    },
    {
        "label": "Profil D — Enfant devoirs (style Maya)",
        "name":  "Maya",
        "thread_name": "[TEST] Maya devoirs",
        "sequence": [
            "salut ! je m'appelle Maya, j'ai 12 ans et je suis en 6eme",
            "j'ai un devoir sur les volcans pour demain",
            "c'est quoi la difference entre un volcan effusif et un volcan explosif ?",
            "est-ce que le Vesuve c'est un volcan explosif ?",
        ],
        "recall_msg": "tu sais quelle classe je fais ?",
        "recall_checks": ["6"],
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

def send_message(thread_id, content):
    payload = {"thread_id": thread_id, "message": content}
    r = requests.post(f"{BASE}/api/chat", json=payload, timeout=60)
    r.raise_for_status()
    return r.json()

def get_memory():
    r = requests.get(f"{BASE}/api/memory/triplets", timeout=10)
    r.raise_for_status()
    return r.json()

def delete_thread(thread_id):
    try:
        requests.delete(f"{BASE}/api/threads/{thread_id}", timeout=10)
    except Exception:
        pass

# ─── Verifications reponse ─────────────────────────────────────────────────────

def check_response(response_text, label):
    issues = []
    if not response_text or len(response_text.strip()) < 10:
        issues.append("reponse vide ou trop courte")
    if "%%MEM%%" in response_text:
        issues.append("tag %%MEM%% visible dans la reponse (fuite de tag)")
    if "%%DOMINANT%%" in response_text:
        issues.append("tag %%DOMINANT%% visible dans la reponse (fuite de tag)")
    if response_text.strip().startswith("{") and "error" in response_text.lower():
        issues.append("reponse semble etre une erreur JSON")
    return issues

def extract_response_text(response_json):
    """Extrait le texte de la reponse selon le format retourne par /api/chat"""
    if isinstance(response_json, dict):
        return (
            response_json.get("response") or
            response_json.get("message") or
            response_json.get("content") or
            str(response_json)
        )
    return str(response_json)

# ─── Runner principal ─────────────────────────────────────────────────────────

def run_scenario(scenario):
    results = {
        "label": scenario["label"],
        "passed": 0,
        "failed": 0,
        "warnings": 0,
        "thread_id": None,
        "details": [],
    }

    print(f"\n{BOLD}{CYAN}{'-'*60}{RESET}")
    print(f"{BOLD}{scenario['label']}{RESET}")
    print(f"{'-'*60}")

    # 1. Creer le fil
    try:
        thread_id = create_thread(scenario["thread_name"])
        results["thread_id"] = thread_id
        ok(f"Fil cree : {thread_id[:12]}...")
        results["passed"] += 1
    except Exception as e:
        fail(f"Impossible de creer le fil : {e}")
        results["failed"] += 1
        return results

    # 2. Sequence de messages
    responses = []
    for i, msg in enumerate(scenario["sequence"]):
        try:
            resp = send_message(thread_id, msg)
            text = extract_response_text(resp)
            issues = check_response(text, f"msg {i+1}")

            if issues:
                for issue in issues:
                    fail(f"Message {i+1} — {issue}")
                    results["failed"] += 1
            else:
                ok(f"Message {i+1} — reponse propre ({len(text)} chars)")
                results["passed"] += 1

            responses.append(text)
            info(f"Apercu : {text[:80].strip()}...")

        except Exception as e:
            fail(f"Message {i+1} — erreur HTTP : {e}")
            results["failed"] += 1

    # 3. Attendre l'extraction memoire asynchrone
    print(f"\n  Attente extraction memoire ({WAIT_EXTRACTION}s)...")
    time.sleep(WAIT_EXTRACTION)

    # 4. Verifier que des memoires ont ete creees
    try:
        memory = get_memory()
        name = scenario["name"]
        # Chercher des souvenirs lies a cet utilisateur
        relevant = [m for m in memory if name.lower() in str(m).lower()]
        if relevant:
            ok(f"Memoire extraite — {len(relevant)} souvenir(s) lie(s) a {name}")
            results["passed"] += 1
            for m in relevant[:3]:
                info(f"  -> {m.get('sujet','?')} / {m.get('predicat','?')} / {m.get('objet','?')}")
        else:
            warn(f"Aucun souvenir trouve pour '{name}' — extraction peut-etre en retard ou bloquee")
            results["warnings"] += 1
    except Exception as e:
        fail(f"Erreur lecture memoire : {e}")
        results["failed"] += 1

    # 5. Test de recall
    print(f"\n  Test recall : << {scenario['recall_msg']} >>")
    try:
        resp = send_message(thread_id, scenario["recall_msg"])
        text = extract_response_text(resp)
        issues = check_response(text, "recall")

        if issues:
            for issue in issues:
                fail(f"Recall — {issue}")
                results["failed"] += 1
        else:
            # Verifier que les mots-cles attendus sont dans la reponse
            text_lower = text.lower()
            recall_ok = all(k.lower() in text_lower for k in scenario["recall_checks"])
            if recall_ok:
                ok(f"Recall reussi — mots cles trouves : {scenario['recall_checks']}")
                results["passed"] += 1
            else:
                manquants = [k for k in scenario["recall_checks"] if k.lower() not in text_lower]
                warn(f"Recall partiel — mots manquants : {manquants}")
                warn(f"Reponse obtenue : {text[:120]}...")
                results["warnings"] += 1

    except Exception as e:
        fail(f"Recall — erreur HTTP : {e}")
        results["failed"] += 1

    return results


def main():
    print(f"\n{BOLD}{'='*60}")
    print("  NIMM — AUDIT COMPORTEMENTAL UTILISATEUR")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"{'='*60}{RESET}\n")

    # Verifier que NIMM tourne
    print("Verification serveur NIMM...")
    if not ping():
        print(f"{RED}{BOLD}NIMM ne repond pas sur {BASE}.{RESET}")
        print("Lance NIMM avec LANCER_NIMM.bat ou uvicorn, puis relance ce script.")
        sys.exit(1)
    ok(f"NIMM actif sur {BASE}")

    all_results = []
    created_threads = []

    for scenario in SCENARIOS:
        result = run_scenario(scenario)
        all_results.append(result)
        if result["thread_id"]:
            created_threads.append(result["thread_id"])

    # ─── Nettoyage ──────────────────────────────────────────────────────────────
    print(f"\n{CYAN}Nettoyage des fils de test...{RESET}")
    for tid in created_threads:
        delete_thread(tid)
        info(f"Fil {tid[:12]}... supprime")

    # ─── Rapport final ──────────────────────────────────────────────────────────
    print(f"\n{BOLD}{'='*60}")
    print("  RAPPORT FINAL")
    print(f"{'='*60}{RESET}")

    total_passed   = sum(r["passed"]   for r in all_results)
    total_failed   = sum(r["failed"]   for r in all_results)
    total_warnings = sum(r["warnings"] for r in all_results)
    total_checks   = total_passed + total_failed + total_warnings

    for r in all_results:
        score = r["passed"]
        total = r["passed"] + r["failed"] + r["warnings"]
        badge = GREEN if r["failed"] == 0 else (YELLOW if r["warnings"] > r["failed"] else RED)
        symbol = "OK" if r["failed"] == 0 else ("WARN" if r["warnings"] > r["failed"] else "ERR")
        print(f"  {badge}{symbol} {r['label']}{RESET}")
        print(f"      OK {r['passed']}  ERR {r['failed']}  WARN {r['warnings']}")

    print(f"\n{BOLD}  TOTAL : {total_passed}/{total_checks} checks OK")
    print(f"  Echecs : {total_failed}  |  Avertissements : {total_warnings}{RESET}")

    if total_failed == 0 and total_warnings == 0:
        print(f"\n{GREEN}{BOLD}  Score parfait — NIMM repond correctement a tous les profils.{RESET}")
    elif total_failed == 0:
        print(f"\n{YELLOW}{BOLD}  Quelques avertissements — voir details ci-dessus.{RESET}")
    else:
        print(f"\n{RED}{BOLD}  Des problemes ont ete detectes — voir details ci-dessus.{RESET}")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
