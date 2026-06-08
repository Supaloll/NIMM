"""
test_human_vs_nimm.py
─────────────────────
Fait dialoguer un LLM "utilisateur" avec NIMM.
Objectif : détecter les dérives thématiques.

Config : fichier .env à la racine du projet
  USER_PROVIDER=deepseek          # ou mistral
  USER_API_KEY=sk-...
  USER_MODEL=deepseek-chat        # ou mistral-small-latest
  MAX_TURNS=12
  DELAY_SECONDS=2
  NIMM_MASK=lia
  NIMM_URL=http://localhost:8080
  SCENARIO_FILE=tests/scenario_human.txt
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

# ── Configuration ──────────────────────────────────────────
NIMM_URL       = os.getenv("NIMM_URL",       "http://localhost:8080")
USER_PROVIDER  = os.getenv("USER_PROVIDER",  "deepseek")
USER_API_KEY   = os.getenv("USER_API_KEY",   "")
USER_MODEL     = os.getenv("USER_MODEL",     "deepseek-chat")
MAX_TURNS      = int(os.getenv("MAX_TURNS",  "12"))
DELAY_SECONDS  = int(os.getenv("DELAY_SECONDS", "2"))
NIMM_MASK      = os.getenv("NIMM_MASK",      "lia")
SCENARIO_FILE  = os.getenv("SCENARIO_FILE",  "tests/scenario_human.txt")

# ── Provider endpoints ─────────────────────────────────────
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
}

# ── Logs ───────────────────────────────────────────────────
LOG_DIR = Path("tests/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"conv_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"


def log(line: str):
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_scenario() -> str:
    path = Path(SCENARIO_FILE)
    if not path.exists():
        print(f"[ERREUR] Fichier scenario introuvable : {SCENARIO_FILE}")
        sys.exit(1)
    return path.read_text(encoding="utf-8").strip()


# ── Verification NIMM ──────────────────────────────────────
def check_nimm():
    try:
        r = httpx.get(f"{NIMM_URL}/api/ping", timeout=5)
        r.raise_for_status()
    except Exception:
        print(f"[ERREUR] NIMM inaccessible sur {NIMM_URL}. Lance le serveur d'abord.")
        sys.exit(1)


# ── Thread NIMM ────────────────────────────────────────────
def create_thread() -> str:
    r = httpx.post(
        f"{NIMM_URL}/api/threads",
        json={"name": f"[TEST] Human vs NIMM -- {datetime.now().strftime('%d/%m %H:%M')}"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    return str(data.get("thread_id") or data.get("id") or data["thread_id"])


def send_to_nimm(message: str, thread_id: str) -> str:
    r = httpx.post(
        f"{NIMM_URL}/api/chat",
        json={"message": message, "thread_id": thread_id, "mask": NIMM_MASK},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    return data.get("reply", "").strip()


# ── LLM utilisateur ────────────────────────────────────────
def call_user_llm(history: list, system_prompt: str) -> str:
    if USER_PROVIDER not in PROVIDER_CONFIG:
        print(f"[ERREUR] Provider inconnu : {USER_PROVIDER}")
        sys.exit(1)

    cfg = PROVIDER_CONFIG[USER_PROVIDER]
    if not USER_API_KEY:
        print("[ERREUR] USER_API_KEY manquante dans le .env")
        sys.exit(1)

    payload = {
        "model": USER_MODEL,
        "max_tokens": 200,
        "temperature": 0.8,
        "messages": [{"role": "system", "content": system_prompt}] + history,
    }
    headers = {
        "Content-Type": "application/json",
        cfg["header"]: f"{cfg['prefix']} {USER_API_KEY}",
    }

    r = httpx.post(cfg["url"], json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"].strip()


# ── Boucle principale ──────────────────────────────────────
def run():
    check_nimm()
    scenario = load_scenario()
    thread_id = create_thread()

    log("=" * 60)
    log(f"TEST HUMAN VS NIMM -- {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    log(f"Masque NIMM : {NIMM_MASK} | Modele utilisateur : {USER_MODEL}")
    log(f"Thread NIMM : {thread_id}")
    log(f"Scenario : {SCENARIO_FILE}")
    log(f"Turns max : {MAX_TURNS} | Delai : {DELAY_SECONDS}s")
    log("=" * 60)
    log("")

    # Historique pour le LLM utilisateur (format messages API)
    user_history = []

    for turn in range(1, MAX_TURNS + 1):
        log(f"-- Tour {turn}/{MAX_TURNS} " + "-" * 40)

        # Le LLM utilisateur genere son message
        # On lui rappelle le numero de tour pour qu'il suive son agenda
        turn_hint = f"\n\n[Tour actuel : {turn}/{MAX_TURNS}. Suis ton agenda naturellement.]"
        try:
            user_msg = call_user_llm(user_history, scenario + turn_hint)
        except Exception as e:
            log(f"[ERREUR LLM utilisateur] {e}")
            break

        log(f"[Humain Laurent] {user_msg}")
        log("")

        # Envoie a NIMM
        try:
            nimm_reply = send_to_nimm(user_msg, thread_id)
        except Exception as e:
            log(f"[ERREUR NIMM] {e}")
            break

        log(f"[NIMM {NIMM_MASK.capitalize()}] {nimm_reply}")
        log("")

        # Met a jour l'historique du LLM utilisateur
        user_history.append({"role": "user",      "content": user_msg})
        user_history.append({"role": "assistant",  "content": nimm_reply})

        if turn < MAX_TURNS:
            time.sleep(DELAY_SECONDS)

    log("")
    log("=" * 60)
    log(f"FIN DU TEST -- {MAX_TURNS} tours -- Thread conserve : {thread_id}")
    log(f"Log sauvegarde : {LOG_FILE}")
    log("=" * 60)


if __name__ == "__main__":
    run()
