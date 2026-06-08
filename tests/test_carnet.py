"""
test_carnet.py
──────────────
Test du Carnet de bord NIMM en 3 phases.

Phase 1 — Contenu riche  : 8 échanges LLM-driven, messages longs avec infos personnelles.
           Objectif : vérifier la mémoire inline + Note #0 (tour 1) + Note #1 (tour 8).

Phase 2 — Rembourrage    : 36 échanges courts sans LLM côté utilisateur.
           Objectif : dépasser CARNET_WINDOW (80 messages) pour activer l'injection.

Phase 3 — Vérification   : 1 échange LLM demandant un détail du tout début (hors fenêtre).
           Objectif : confirmer que NIMM s'en souvient grâce au carnet injecté.

Lecture des notes : GET /api/threads/{thread_id}/carnet

Config : fichier .env à la racine du projet
  USER_PROVIDER=deepseek
  USER_API_KEY=sk-...
  USER_MODEL=deepseek-chat
  NIMM_URL=http://localhost:8080
  NIMM_MASK=lia
  DELAY_SECONDS=1
"""

import os
import sys
import time
import json
import httpx
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────────
NIMM_URL      = os.getenv("NIMM_URL",       "http://localhost:8080")
USER_PROVIDER = os.getenv("USER_PROVIDER",  "deepseek")
USER_API_KEY  = os.getenv("USER_API_KEY",   "")
USER_MODEL    = os.getenv("USER_MODEL",     "deepseek-chat")
NIMM_MASK     = os.getenv("NIMM_MASK",      "lia")
DELAY_SECONDS = int(os.getenv("DELAY_SECONDS", "1"))

PHASE1_TURNS  = 8    # échanges riches LLM
PHASE2_TURNS  = 36   # échanges courts sans LLM (total ~80 messages après phase 1)
CARNET_WINDOW = 80   # seuil d'injection (doit correspondre à CARNET_WINDOW dans hub.py)

PROVIDER_CONFIG = {
    "deepseek": {
        "url":    "https://api.deepseek.com/v1/chat/completions",
        "header": "Authorization",
        "prefix": "Bearer",
    },
    "mistral": {
        "url":    "https://api.mistral.ai/v1/chat/completions",
        "header": "Authorization",
        "prefix": "Bearer",
    },
    "openai": {
        "url":    "https://api.openai.com/v1/chat/completions",
        "header": "Authorization",
        "prefix": "Bearer",
    },
}

# ── Logs ───────────────────────────────────────────────────────────────────────
LOG_DIR  = Path("tests/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"carnet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

def log(line: str = ""):
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def sep(title: str = ""):
    line = f"── {title} " + "─" * max(0, 58 - len(title)) if title else "─" * 60
    log(line)

# ── Scénario Phase 1 ───────────────────────────────────────────────────────────
# Le LLM joue "Laurent" et glisse naturellement des infos personnelles.
# Ces infos doivent déclencher la mémoire inline ET les premières notes du carnet.

SCENARIO_PHASE1 = """Tu joues le rôle de Laurent, un homme de 47 ans qui parle à son assistante IA personnelle.
Tu t'exprimes naturellement, comme à l'oral, parfois en phrases courtes, parfois en petits paragraphes.

Informations sur Laurent à placer naturellement au fil des 8 messages :
- Métier : chauffeur poids lourd longue distance depuis 22 ans, camion Mercedes Actros
- Famille : femme Isabelle (comptable), fils Tom (19 ans, apprenti mécanicien), fille Zoé (14 ans, passionnée de dessin)
- Habitudes : se lève à 4h30, café noir obligatoire le matin, écoute du rock français sur la route (Téléphone, Indochine)
- Santé : mal de dos chronique depuis 3 ans, kinésithérapie tous les 15 jours
- Projet : cherche une maison dans les Corbières (sud de la France) avec grand jardin et garage double
- Loisirs : pêche à la truite, jardinage, bricole ses motos le week-end
- Véhicule perso : une vieille Honda CB 750 de 1979 qu'il restaure depuis 2 ans
- Préférences : déteste les réunions Zoom, aime les repas en famille le dimanche

Consignes :
- Parle naturellement, ne liste pas les infos comme un CV.
- Mélange les sujets : une question pratique, un état d'âme, une info partagée en passant.
- Messages entre 3 et 6 phrases. Parfois plus long si tu racontes quelque chose.
- Tu peux poser des questions à l'assistante de temps en temps.
- Varie le ton : parfois léger, parfois un peu fatigué, parfois enthousiaste.
- Tu peux aborder un seul ou deux sujets par message — ne tout pas déballer d'un coup.
"""

# ── Messages de rembourrage Phase 2 ───────────────────────────────────────────
PADDING_MESSAGES = [
    "D'accord, merci.",
    "Oui c'est ça.",
    "Tu peux continuer.",
    "Hmm, intéressant.",
    "Ok je note.",
    "Et sinon ?",
    "C'est logique.",
    "Bien reçu.",
    "Je vois.",
    "Ça marche pour moi.",
    "C'est noté.",
    "Pas de souci.",
    "Bonne idée.",
    "Je réfléchis.",
    "On continue ?",
    "Vas-y.",
    "Ok.",
    "Merci.",
    "Parfait.",
    "Je suis là.",
]

# ── Message Phase 3 — test injection ──────────────────────────────────────────
SCENARIO_PHASE3 = """Tu joues Laurent. Tu as eu une longue conversation avec ton assistante.
Pose-lui une question précise sur un détail que tu lui as mentionné au TOUT DÉBUT de la conversation :
demande-lui de rappeler le prénom de ta femme, l'âge de tes enfants, ou le modèle exact de ton camion.
Formule ça naturellement, comme si tu testais sa mémoire : "Au fait, tu te souviens de... ?"
Un seul message court (1-2 phrases)."""

# ── Helpers NIMM ──────────────────────────────────────────────────────────────
def check_nimm():
    try:
        r = httpx.get(f"{NIMM_URL}/api/ping", timeout=5)
        r.raise_for_status()
    except Exception:
        log(f"[ERREUR] NIMM inaccessible sur {NIMM_URL}. Lance le serveur d'abord.")
        sys.exit(1)

def create_thread() -> str:
    r = httpx.post(
        f"{NIMM_URL}/api/threads",
        json={"name": f"[TEST CARNET] {datetime.now().strftime('%d/%m %H:%M')}"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    return str(data.get("thread_id") or data.get("id"))

def send_to_nimm(message: str, thread_id: str) -> str:
    r = httpx.post(
        f"{NIMM_URL}/api/chat",
        json={"message": message, "thread_id": thread_id, "mask": NIMM_MASK},
        timeout=90,
    )
    r.raise_for_status()
    return r.json().get("reply", "").strip()

def get_carnet(thread_id: str) -> dict:
    try:
        r = httpx.get(f"{NIMM_URL}/api/threads/{thread_id}/carnet", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e), "notes": []}

# ── LLM utilisateur ───────────────────────────────────────────────────────────
def call_user_llm(history: list, system_prompt: str, turn_hint: str = "") -> str:
    if USER_PROVIDER not in PROVIDER_CONFIG:
        log(f"[ERREUR] Provider inconnu : {USER_PROVIDER}")
        sys.exit(1)
    if not USER_API_KEY:
        log("[ERREUR] USER_API_KEY manquante dans le .env")
        sys.exit(1)

    cfg = PROVIDER_CONFIG[USER_PROVIDER]
    prompt = system_prompt + (f"\n\n[Tour actuel : {turn_hint}]" if turn_hint else "")

    payload = {
        "model": USER_MODEL,
        "max_tokens": 300,
        "temperature": 0.85,
        "messages": [{"role": "system", "content": prompt}] + history,
    }
    headers = {
        "Content-Type": "application/json",
        cfg["header"]: f"{cfg['prefix']} {USER_API_KEY}",
    }

    r = httpx.post(cfg["url"], json=payload, headers=headers, timeout=40)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

# ── Phases ────────────────────────────────────────────────────────────────────
def phase1(thread_id: str) -> list:
    """8 échanges LLM riches. Retourne l'historique pour la phase 3."""
    sep(f"PHASE 1 — Contenu riche ({PHASE1_TURNS} échanges LLM)")
    log()
    history = []

    for turn in range(1, PHASE1_TURNS + 1):
        turn_hint = f"{turn}/{PHASE1_TURNS} — glisse naturellement 1 ou 2 infos personnelles"
        try:
            user_msg = call_user_llm(history, SCENARIO_PHASE1, turn_hint)
        except Exception as e:
            log(f"  [ERREUR LLM utilisateur] {e}")
            break

        log(f"  [Laurent — tour {turn}]")
        log(f"  {user_msg}")
        log()

        try:
            nimm_reply = send_to_nimm(user_msg, thread_id)
        except Exception as e:
            log(f"  [ERREUR NIMM] {e}")
            break

        log(f"  [NIMM]")
        log(f"  {nimm_reply}")
        log()

        history.append({"role": "user",      "content": user_msg})
        history.append({"role": "assistant",  "content": nimm_reply})

        # Snapshot carnet après tour 1 (Note #0 doit exister) et tour 8 (Note #1)
        if turn in (1, PHASE1_TURNS):
            time.sleep(2)  # laisser la tâche background se terminer
            snap = get_carnet(thread_id)
            log(f"  ── Carnet après tour {turn} : {snap.get('note_count', '?')} note(s) / {snap.get('message_count', '?')} messages ──")
            for n in snap.get("notes", []):
                log(f"     Note #{n['note_number']} : {n['content']}")
            log()

        if turn < PHASE1_TURNS:
            time.sleep(DELAY_SECONDS)

    return history

def phase2(thread_id: str):
    """36 échanges courts sans LLM côté user pour dépasser CARNET_WINDOW."""
    sep(f"PHASE 2 — Rembourrage ({PHASE2_TURNS} échanges courts)")
    log(f"  Objectif : dépasser {CARNET_WINDOW} messages pour activer l'injection du carnet.")
    log()

    for i in range(PHASE2_TURNS):
        msg = PADDING_MESSAGES[i % len(PADDING_MESSAGES)]
        try:
            nimm_reply = send_to_nimm(msg, thread_id)
            # Affichage minimal pour ne pas polluer les logs
            if (i + 1) % 6 == 0 or i == PHASE2_TURNS - 1:
                snap = get_carnet(thread_id)
                log(f"  [Padding {i+1}/{PHASE2_TURNS}] messages en base : {snap.get('message_count', '?')} | notes carnet : {snap.get('note_count', '?')}")
        except Exception as e:
            log(f"  [ERREUR NIMM padding {i+1}] {e}")

        time.sleep(0.5)

    log()

def phase3(thread_id: str, history: list):
    """1 échange LLM pour vérifier l'injection du carnet hors fenêtre."""
    sep("PHASE 3 — Vérification injection carnet")
    log()

    snap = get_carnet(thread_id)
    n_msgs = snap.get("message_count", 0)
    n_notes = snap.get("note_count", 0)
    injected = n_msgs > CARNET_WINDOW

    log(f"  État : {n_msgs} messages | {n_notes} notes | injection active : {'✅ OUI' if injected else '❌ NON (seuil non atteint)'}")
    log()

    if not injected:
        log("  ⚠️  Le seuil CARNET_WINDOW n'est pas atteint — l'injection ne sera pas testée.")
        log(f"     Augmente PHASE2_TURNS dans le script (actuellement {PHASE2_TURNS}).")
        return

    try:
        user_msg = call_user_llm(history[-6:], SCENARIO_PHASE3)
    except Exception as e:
        log(f"  [ERREUR LLM utilisateur] {e}")
        return

    log(f"  [Laurent — question mémoire]")
    log(f"  {user_msg}")
    log()

    try:
        nimm_reply = send_to_nimm(user_msg, thread_id)
    except Exception as e:
        log(f"  [ERREUR NIMM] {e}")
        return

    log(f"  [NIMM — réponse]")
    log(f"  {nimm_reply}")
    log()

# ── Rapport final ─────────────────────────────────────────────────────────────
def rapport_final(thread_id: str):
    sep("RAPPORT FINAL")
    log()

    snap = get_carnet(thread_id)
    if "error" in snap:
        log(f"  Impossible de lire le carnet : {snap['error']}")
        log("  Vérifie les logs serveur pour les lignes [CARNET] 📓")
    else:
        log(f"  Thread    : {thread_id}")
        log(f"  Messages  : {snap.get('message_count', '?')}")
        log(f"  Notes     : {snap.get('note_count', '?')}")
        log()
        log("  ── Toutes les notes du carnet ──")
        notes = snap.get("notes", [])
        if notes:
            for n in notes:
                log(f"  [{n['note_number']}] {n['content']}")
        else:
            log("  (aucune note — vérifie les logs serveur)")

    log()
    log(f"  Log sauvegardé : {LOG_FILE}")
    sep()

# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    check_nimm()

    log()
    sep("TEST CARNET DE BORD NIMM")
    log(f"  Date     : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    log(f"  Provider : {USER_PROVIDER} / {USER_MODEL}")
    log(f"  NIMM     : {NIMM_URL} — masque : {NIMM_MASK}")
    log(f"  Phases   : P1={PHASE1_TURNS} échanges LLM | P2={PHASE2_TURNS} padding | P3=1 vérification")
    log(f"  Seuil    : injection carnet si > {CARNET_WINDOW} messages")
    sep()
    log()

    thread_id = create_thread()
    log(f"  Thread créé : {thread_id}")
    log()

    history = phase1(thread_id)
    phase2(thread_id)
    phase3(thread_id, history)
    rapport_final(thread_id)


if __name__ == "__main__":
    run()
