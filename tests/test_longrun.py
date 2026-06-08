# -*- coding: utf-8 -*-
"""
test_longrun.py — Stress test longitudinal NIMM
Simule une conversation longue jusqu'au declenchement du compactage OS,
puis verifie que les faits ancres en debut de fil sont toujours restitues.

Usage : python tests/test_longrun.py [--db chemin/vers/nimm.db]
NIMM doit tourner sur localhost:8080.
"""

import requests
import sqlite3
import time
import sys
import argparse
from datetime import datetime

BASE = "http://localhost:8080"
POLL_INTERVAL   = 3    # secondes entre chaque check OS
BATCH_SIZE      = 5    # messages par rafale
WAIT_AFTER_MSG  = 1.2  # secondes entre messages (evite de saturer)
MAX_BATCHES     = 40   # securite anti-boucle infinie

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def ok(msg):    print(f"  {GREEN}OK {msg}{RESET}")
def fail(msg):  print(f"  {RED}ERR {msg}{RESET}")
def warn(msg):  print(f"  {YELLOW}WARN {msg}{RESET}")
def info(msg):  print(f"  {CYAN}INFO {msg}{RESET}")
def dim(msg):   print(f"  {DIM}{msg}{RESET}")

# ─── Faits ancres en Phase 1 ───────────────────────────────────────────────────
# Ces infos doivent etre restituees apres compactage.

ANCHOR_FACTS = [
    ("Je m'appelle Laurent. Je suis routier de metier.", ["Laurent", "routier"]),
    ("J'ai trois filles : Maissane (17 ans), Maya (12 ans) et Innes (22 ans).", ["Maissane", "Maya", "Innes"]),
    ("Ma compagne s'appelle Nadia. Elle tient une boutique de couture qui s'appelle LIMM.", ["Nadia", "LIMM"]),
    ("Je travaille sur un projet d'IA personnel que j'appelle NIMM. C'est un assistant de famille.", ["NIMM"]),
    ("J'habite dans l'Aude, dans un village qui s'appelle Ferrals-les-Corbieres.", ["Ferrals", "Aude"]),
    ("Mon plat prefere c'est la choucroute alsacienne.", ["choucroute"]),
    ("Je suis alsacien d'origine, meme si j'habite dans le Sud depuis longtemps.", ["alsacien"]),
    ("Je n'aime pas les interfaces compliquees. Je veux que tout soit simple et naturel.", ["simple", "naturel"]),
]

# ─── Messages de remplissage ───────────────────────────────────────────────────
# Varies, realistes, sans rapport avec les faits ancres.

FILLER_TOPICS = [
    "C'est quoi la difference entre le cafe arabica et le robusta ?",
    "Explique-moi rapidement comment fonctionne un moteur diesel.",
    "Quelle est la capitale du Perou ?",
    "C'est quoi la regle du jeu d'echecs en ce qui concerne le roque ?",
    "Pourquoi le ciel est-il bleu ?",
    "Donne-moi une recette rapide de sauce tomate maison.",
    "Quelle est la difference entre le droit civil et le droit penal ?",
    "Comment fonctionne un panneau solaire ?",
    "C'est quoi le principe de la fermentation lacto-acide ?",
    "Pourquoi les feuilles des arbres changent de couleur en automne ?",
    "Explique-moi ce qu'est une API REST en deux phrases.",
    "Quelle est la distance entre la Terre et la Lune ?",
    "C'est quoi la difference entre l'empathie et la sympathie ?",
    "Donne-moi 3 conseils pour bien dormir.",
    "Pourquoi les chats ronronnent-ils ?",
    "Comment calcule-t-on un pourcentage ?",
    "C'est quoi le principe de la distillation ?",
    "Quelle est la duree de vie moyenne d'un chene ?",
    "Explique-moi ce qu'est l'inflation en termes simples.",
    "C'est quoi la difference entre le satin et le velours ?",
    "Pourquoi les oceans sont-ils sales ?",
    "C'est quoi un haiku ?",
    "Comment fonctionne un refrigerateur ?",
    "Quelle est la difference entre une bacterie et un virus ?",
    "C'est quoi le paradoxe de Fermi ?",
    "Donne-moi un exemple de metaphore filee.",
    "Pourquoi dit-on qu'il ne faut pas melanger alcool et medicaments ?",
    "C'est quoi la difference entre le nord magnetique et le nord geographique ?",
    "Comment fonctionne le son ? Pourquoi peut-on l'entendre ?",
    "Qu'est-ce que la resilience en psychologie ?",
    "C'est quoi la regle des 80/20 (Pareto) ?",
    "Pourquoi les flammes sont-elles chaudes ?",
    "Donne-moi la difference entre un dialecte et une langue.",
    "Qu'est-ce que le PIB d'un pays ?",
    "C'est quoi la difference entre l'intuition et le raisonnement ?",
    "Pourquoi les avions peuvent-ils voler ?",
    "C'est quoi le principe de la boussole ?",
    "Donne-moi un exemple de sophisme courant.",
    "Qu'est-ce que la loi de l'offre et de la demande ?",
    "Pourquoi certains aliments deviennent marron quand on les coupe ?",
    "C'est quoi la difference entre la vitesse et la velocite ?",
    "Comment fonctionne une pompe a chaleur ?",
    "Quelle est la difference entre un roman et une nouvelle ?",
    "Pourquoi les etoiles scintillent-elles ?",
    "Donne-moi 3 techniques pour memoriser plus facilement.",
    "C'est quoi la difference entre l'humilite et la modestie ?",
    "Pourquoi les pieuvres sont-elles considerees comme intelligentes ?",
    "Qu'est-ce que la blockchain en deux phrases ?",
    "C'est quoi la difference entre une hypothese et une theorie ?",
    "Pourquoi certaines personnes sont-elles daltoniens ?",
    "Donne-moi un exemple concret de biais cognitif.",
    "C'est quoi la difference entre la duree et le temps ?",
    "Pourquoi les baleines chantent-elles ?",
    "Comment fonctionne un transistor ?",
    "Quelle est la difference entre l'induction et la deduction ?",
    "C'est quoi le principe de la radioactivite ?",
    "Pourquoi certains fromages ont-ils des trous ?",
    "Donne-moi la definition du stoicisme en une phrase.",
    "C'est quoi la difference entre la prose et la poesie ?",
    "Pourquoi les chiens font-ils la fete quand on rentre a la maison ?",
    "Comment fonctionne le Wi-Fi ?",
    "Quelle est la difference entre l'art abstrait et l'art figuratif ?",
    "C'est quoi la difference entre la memoire RAM et le stockage SSD ?",
    "Pourquoi le pain leve-t-il a la cuisson ?",
    "Donne-moi un exemple de paradoxe connu.",
    "C'est quoi la loi de Murphy ?",
    "Pourquoi les miroirs inversent-ils gauche et droite mais pas haut et bas ?",
    "Comment fonctionne un scanner medical IRM ?",
    "Quelle est la difference entre la norme et la valeur ?",
    "C'est quoi le principe de relativite d'Einstein en deux phrases ?",
    "Pourquoi certains sons sont-ils desagreables a entendre ?",
]

# ─── Questions de recall post-compaction ───────────────────────────────────────

RECALL_QUESTIONS = [
    ("Tu te souviens de mon prenom et de mon metier ?", ["Laurent", "routier"]),
    ("Comment s'appellent mes filles ?", ["Maissane", "Maya", "Innes"]),
    ("Tu te rappelles comment s'appelle la boutique de ma compagne ?", ["LIMM"]),
    ("C'est quoi le projet sur lequel je travaille en ce moment ?", ["NIMM"]),
    ("Tu sais dans quel departement j'habite ?", ["Aude", "Ferrals"]),
]

# ─── DB helpers ───────────────────────────────────────────────────────────────

def get_max_history(db_path):
    """Lit MAX_HISTORY depuis les settings NIMM."""
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key='max_history'")
        row = c.fetchone()
        conn.close()
        return int(row[0]) if row else 150
    except Exception:
        return 150

def count_messages(thread_id, db_path):
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM messages WHERE thread_id=?", (thread_id,))
        count = c.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0

def get_os(thread_id, db_path):
    """Retourne le contenu de l'OS si genere, sinon None."""
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT os FROM conversations WHERE thread_id=?", (thread_id,))
        row = c.fetchone()
        conn.close()
        return row[0] if row and row[0] and len(row[0].strip()) > 20 else None
    except Exception:
        return None

def get_memory_count(name, db_path):
    """Compte les souvenirs lies a un nom dans la DB."""
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM memory WHERE sujet LIKE ? OR objet LIKE ? OR valeur LIKE ?",
            (f"%{name}%", f"%{name}%", f"%{name}%")
        )
        count = c.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return -1

# ─── API helpers ──────────────────────────────────────────────────────────────

def ping():
    try:
        return requests.get(f"{BASE}/api/ping", timeout=5).status_code == 200
    except Exception:
        return False

def create_thread(name):
    r = requests.post(f"{BASE}/api/threads", json={"name": name}, timeout=10)
    r.raise_for_status()
    return r.json()["thread_id"]

def send_message(thread_id, content):
    r = requests.post(f"{BASE}/api/chat",
                      json={"thread_id": thread_id, "message": content},
                      timeout=90)
    r.raise_for_status()
    resp = r.json()
    return (
        resp.get("response") or
        resp.get("message") or
        resp.get("content") or ""
    )

def delete_thread(thread_id):
    try:
        requests.delete(f"{BASE}/api/threads/{thread_id}", timeout=10)
    except Exception:
        pass

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Stress test longitudinal NIMM")
    parser.add_argument("--db", default="data/nimm.db", help="Chemin vers nimm.db")
    args = parser.parse_args()
    db_path = args.db

    print(f"\n{BOLD}{'='*62}")
    print("  NIMM — STRESS TEST LONGITUDINAL (compactage OS)")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"{'='*62}{RESET}\n")

    # Verification serveur
    print("Verification serveur...")
    if not ping():
        print(f"{RED}{BOLD}NIMM ne repond pas sur {BASE}. Lance NIMM d'abord.{RESET}\n")
        sys.exit(1)
    ok(f"NIMM actif sur {BASE}")

    # Lire MAX_HISTORY
    max_history = get_max_history(db_path)
    threshold   = int(max_history * 0.8)
    info(f"MAX_HISTORY = {max_history} -> seuil OS a ~{threshold} messages")
    print()

    # Timeline pour le rapport final
    timeline = []
    recall_results = []

    # ── Phase 1 : Creation du fil ──────────────────────────────────────────────
    print(f"{BOLD}{'-'*62}")
    print("  PHASE 1 — ANCRAGE DES FAITS")
    print(f"{'-'*62}{RESET}")

    thread_id = create_thread("[TEST-LONGRUN] Conversation longue")
    ok(f"Fil cree : {thread_id[:16]}...")
    t_start = datetime.now()

    # Envoyer les faits ancres
    for i, (msg, _) in enumerate(ANCHOR_FACTS):
        try:
            resp = send_message(thread_id, msg)
            n = count_messages(thread_id, db_path)
            dim(f"[MSG {n:03d}] {msg[:60]}...")
            time.sleep(WAIT_AFTER_MSG)
        except Exception as e:
            fail(f"Erreur Phase 1 message {i+1} : {e}")

    time.sleep(4)  # laisser l'extraction memoire se faire
    mem_count_initial = get_memory_count("Laurent", db_path)
    ok(f"Phase 1 terminee — {count_messages(thread_id, db_path)} messages — {mem_count_initial} souvenir(s) 'Laurent' en DB")
    timeline.append(("Phase 1 terminee", count_messages(thread_id, db_path), datetime.now()))

    # ── Phase 2 : Remplissage ─────────────────────────────────────────────────
    print(f"\n{BOLD}{'-'*62}")
    print("  PHASE 2 — REMPLISSAGE CONVERSATIONNEL")
    print(f"{'-'*62}{RESET}")
    info(f"Envoi de messages jusqu'au seuil OS (~{threshold} messages au total)")
    info(f"Rafales de {BATCH_SIZE} messages — check OS toutes les rafales\n")

    os_detected   = False
    os_content    = None
    filler_idx    = 0
    batch_count   = 0

    while not os_detected and batch_count < MAX_BATCHES:
        batch_count += 1
        n_current = count_messages(thread_id, db_path)

        if n_current >= threshold + 10:
            warn(f"Seuil depasse ({n_current} messages) mais OS non detecte — on continue encore un peu...")
            if batch_count > MAX_BATCHES - 5:
                warn("Limite de securite atteinte — arret du remplissage.")
                break

        # Envoyer une rafale
        print(f"  {DIM}Rafale #{batch_count:02d} — {n_current} messages en DB...{RESET}")
        for _ in range(BATCH_SIZE):
            topic = FILLER_TOPICS[filler_idx % len(FILLER_TOPICS)]
            filler_idx += 1
            try:
                send_message(thread_id, topic)
                time.sleep(WAIT_AFTER_MSG)
            except Exception as e:
                warn(f"Erreur envoi filler : {e}")

        n_after = count_messages(thread_id, db_path)
        time.sleep(POLL_INTERVAL)

        # Check OS
        os_content = get_os(thread_id, db_path)
        if os_content:
            os_detected = True
            ok(f"OS DETECTE apres {n_after} messages !")
            timeline.append(("OS genere", n_after, datetime.now()))
        else:
            dim(f"  -> {n_after} messages — OS pas encore genere")

    if not os_detected:
        warn("OS non detecte apres toutes les rafales.")
        warn("Verifie que maybe_generate_os() est bien appele dans hub.py.")
        timeline.append(("OS non detecte", count_messages(thread_id, db_path), datetime.now()))

    # ── Phase 3 : Recall post-compaction ──────────────────────────────────────
    print(f"\n{BOLD}{'-'*62}")
    print("  PHASE 3 — RECALL POST-COMPACTION")
    print(f"{'-'*62}{RESET}")
    info("Test : le LLM se souvient-il des faits du debut du fil ?")

    time.sleep(3)

    for question, keywords in RECALL_QUESTIONS:
        print(f"\n  Test << {question} >>")
        try:
            resp = send_message(thread_id, question)
            resp_lower = resp.lower()
            found    = [k for k in keywords if k.lower() in resp_lower]
            missing  = [k for k in keywords if k.lower() not in resp_lower]

            if not missing:
                ok(f"Recall OK — tous les mots-cles trouves : {keywords}")
                recall_results.append((question, True, found, []))
            elif found:
                warn(f"Recall partiel — trouves : {found} | manquants : {missing}")
                recall_results.append((question, None, found, missing))
            else:
                fail(f"Recall echoue — aucun mot-cle trouve : {keywords}")
                recall_results.append((question, False, [], missing))

            dim(f"  Reponse complete : {resp.strip()}")
        except Exception as e:
            fail(f"Erreur recall : {e}")
            recall_results.append((question, False, [], keywords))

        time.sleep(WAIT_AFTER_MSG)

    timeline.append(("Recall termine", count_messages(thread_id, db_path), datetime.now()))

    # ── Nettoyage ─────────────────────────────────────────────────────────────
    print(f"\n{CYAN}Nettoyage...{RESET}")
    delete_thread(thread_id)
    ok("Fil supprime")

    # ── Rapport final ─────────────────────────────────────────────────────────
    t_end     = datetime.now()
    duree_min = (t_end - t_start).seconds // 60
    duree_sec = (t_end - t_start).seconds % 60

    print(f"\n{BOLD}{'='*62}")
    print("  RAPPORT FINAL")
    print(f"{'='*62}{RESET}")

    print(f"\n  {BOLD}Timeline{RESET}")
    for label, n_msg, t in timeline:
        delta = (t - t_start).seconds
        print(f"    {delta:>4}s — {label} ({n_msg} messages)")
    print(f"  Duree totale : {duree_min}min {duree_sec}s")

    print(f"\n  {BOLD}Memoire{RESET}")
    mem_count_final = get_memory_count("Laurent", db_path)
    info(f"Souvenirs 'Laurent' en DB : {mem_count_initial} -> {mem_count_final}")

    print(f"\n  {BOLD}OS (Operating Summary){RESET}")
    if os_detected and os_content:
        ok("OS genere avec succes")
        print(f"\n{DIM}  +--- Contenu OS ---")
        for line in os_content.strip().split("\n")[:15]:
            print(f"  | {line}")
        if os_content.count("\n") > 15:
            print(f"  | ... ({os_content.count(chr(10))} lignes total)")
        print(f"  +------------------{RESET}")
    else:
        fail("OS non genere — le compactage n'a pas eu lieu")

    print(f"\n  {BOLD}Recall post-compaction{RESET}")
    ok_count   = sum(1 for _, s, _, _ in recall_results if s is True)
    part_count = sum(1 for _, s, _, _ in recall_results if s is None)
    fail_count = sum(1 for _, s, _, _ in recall_results if s is False)

    for question, success, found, missing in recall_results:
        if success is True:
            print(f"    {GREEN}OK {question}{RESET}")
        elif success is None:
            print(f"    {YELLOW}WARN {question}{RESET}")
            print(f"        -> trouves: {found} | manquants: {missing}")
        else:
            print(f"    {RED}ERR {question}{RESET}")
            print(f"        -> manquants: {missing}")

    print(f"\n  Score recall : {ok_count}/{len(recall_results)} parfaits")
    if part_count:
        print(f"  Partiels     : {part_count}/{len(recall_results)}")
    if fail_count:
        print(f"  Echecs       : {fail_count}/{len(recall_results)}")

    print(f"\n{'='*62}\n")


if __name__ == "__main__":
    main()
