#!/usr/bin/env bash
# ============================================
# NIMM — LANCER_NIMM.sh
# Lance le serveur et ouvre le navigateur
# macOS / Linux
# ============================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

HOST="127.0.0.1"
PORT="${NIMM_PORT:-8080}"
URL="http://${HOST}:${PORT}"
LOG_FILE="$SCRIPT_DIR/nimm.log"

# Utilise le Python du venv si l'installation l'a créé.
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON_CMD="$SCRIPT_DIR/.venv/bin/python"
else
    PYTHON_CMD="${PYTHON_CMD:-python3}"
fi

if ! command -v "$PYTHON_CMD" >/dev/null 2>&1 && [ ! -x "$PYTHON_CMD" ]; then
    echo "[NIMM] Python 3 introuvable."
    echo "[NIMM] Lance d'abord INSTALLER_NIMM.sh."
    exit 1
fi

is_running() {
    if command -v curl >/dev/null 2>&1; then
        curl -fsS --max-time 1 "$URL/" >/dev/null 2>&1
        return $?
    fi

    # Fallback sans curl : vérifie simplement le port.
    if command -v lsof >/dev/null 2>&1; then
        lsof -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1
        return $?
    fi

    if command -v ss >/dev/null 2>&1; then
        ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT "
        return $?
    fi

    return 1
}

if is_running; then
    echo "[NIMM] Serveur déjà actif sur $URL."
else
    echo "[NIMM] Démarrage du serveur..."
    nohup "$PYTHON_CMD" -m uvicorn main:app \
        --host "$HOST" \
        --port "$PORT" \
        >> "$LOG_FILE" 2>&1 &
    SERVER_PID=$!

    echo "[NIMM] PID : $SERVER_PID"
    echo "[NIMM] Attente du démarrage..."

    READY=0
    for _ in $(seq 1 30); do
        if is_running; then
            READY=1
            break
        fi
        sleep 1
    done

    if [ "$READY" -ne 1 ]; then
        echo "[NIMM] [ERREUR] Le serveur ne répond pas."
        echo "[NIMM] Consulte : $LOG_FILE"
        exit 1
    fi
fi

echo "[NIMM] Ouverture du navigateur : $URL"

case "$(uname -s)" in
    Darwin)
        open "$URL" >/dev/null 2>&1 || echo "[NIMM] Ouvre manuellement $URL"
        ;;
    Linux)
        if command -v xdg-open >/dev/null 2>&1; then
            xdg-open "$URL" >/dev/null 2>&1 &
        elif command -v gio >/dev/null 2>&1; then
            gio open "$URL" >/dev/null 2>&1 &
        else
            echo "[NIMM] Aucun ouvreur graphique trouvé."
            echo "[NIMM] Ouvre manuellement : $URL"
        fi
        ;;
    *)
        echo "[NIMM] Ouvre manuellement : $URL"
        ;;
esac
