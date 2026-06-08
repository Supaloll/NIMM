#!/bin/bash
# ============================================
# NIMM — LANCER_NIMM.sh
# Lance le serveur en arrière-plan et ouvre le navigateur
# ============================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Vérifier si le serveur tourne déjà
if lsof -i :8080 -t >/dev/null 2>&1; then
    echo "[NIMM] Serveur déjà actif."
else
    echo "[NIMM] Démarrage du serveur..."
    nohup python3 -m uvicorn main:app --host 0.0.0.0 --port 8080 >> "$SCRIPT_DIR/nimm.log" 2>&1 &
    echo "[NIMM] Attente démarrage..."
    sleep 4
fi

echo "[NIMM] Ouverture du navigateur..."
open http://localhost:8080
