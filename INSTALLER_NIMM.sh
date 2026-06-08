#!/bin/bash
# ============================================
# NIMM — INSTALLER_NIMM.sh
# Installation automatique pour macOS
# ============================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo " =========================================="
echo "   NIMM — Installation (macOS)"
echo " =========================================="
echo ""
echo " Dossier : $SCRIPT_DIR"
echo ""

# ── Dossier data/ ──────────────────────────────────────────────────────────────
if [ ! -d "$SCRIPT_DIR/data" ]; then
    mkdir -p "$SCRIPT_DIR/data"
    echo " [OK] Dossier data/ créé."
fi

# ══════════════════════════════════════════════════════════════════════════════
# ETAPE 1 — Homebrew
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo " ------------------------------------------"
echo " Etape 1/6 : Homebrew (gestionnaire de paquets)"
echo " ------------------------------------------"

if command -v brew >/dev/null 2>&1; then
    echo " [OK] Homebrew détecté."
else
    echo " Installation de Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [ $? -ne 0 ]; then
        echo ""
        echo " [ERREUR] Homebrew n'a pas pu être installé."
        echo " Installe-le manuellement : https://brew.sh"
        echo " Puis relance ce script."
        read -p " Appuie sur Entrée pour fermer..."
        exit 1
    fi
    # Recharger le PATH pour les Macs Apple Silicon
    eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null
    eval "$(/usr/local/bin/brew shellenv)" 2>/dev/null
    echo " [OK] Homebrew installé."
fi

# ══════════════════════════════════════════════════════════════════════════════
# ETAPE 2 — Python
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo " ------------------------------------------"
echo " Etape 2/6 : Python"
echo " ------------------------------------------"

PYTHON_CMD=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
    echo " [OK] Python détecté."
else
    echo " Installation de Python via Homebrew..."
    brew install python
    if [ $? -ne 0 ]; then
        echo " [ERREUR] Python n'a pas pu être installé."
        read -p " Appuie sur Entrée pour fermer..."
        exit 1
    fi
    PYTHON_CMD="python3"
    echo " [OK] Python installé."
fi

# ══════════════════════════════════════════════════════════════════════════════
# ETAPE 3 — ffmpeg
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo " ------------------------------------------"
echo " Etape 3/6 : ffmpeg (requis pour la dictée vocale)"
echo " ------------------------------------------"

if command -v ffmpeg >/dev/null 2>&1; then
    echo " [OK] ffmpeg déjà présent."
else
    echo " Installation de ffmpeg via Homebrew..."
    brew install ffmpeg
    if [ $? -ne 0 ]; then
        echo " [AVERTISSEMENT] ffmpeg n'a pas pu être installé."
        echo " La dictée vocale ne fonctionnera pas sans lui."
        echo " Tu peux l'installer manuellement : brew install ffmpeg"
    else
        echo " [OK] ffmpeg installé."
    fi
fi

# ══════════════════════════════════════════════════════════════════════════════
# ETAPE 4 — Dépendances Python
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo " ------------------------------------------"
echo " Etape 4/6 : Dépendances Python"
echo " ------------------------------------------"
echo " Cela peut prendre 5 à 15 minutes (PyTorch ~2 Go inclus)."
echo " Ne ferme pas cette fenêtre."
echo ""

$PYTHON_CMD -m pip install --upgrade pip --quiet
$PYTHON_CMD -m pip install -r "$SCRIPT_DIR/requirements.txt"
if [ $? -ne 0 ]; then
    echo ""
    echo " [ERREUR] L'installation des dépendances a échoué."
    echo " Consulte les messages ci-dessus pour identifier le problème."
    echo " Tu peux réessayer manuellement : pip3 install -r requirements.txt"
    read -p " Appuie sur Entrée pour fermer..."
    exit 1
fi
echo " [OK] Dépendances installées."

# ══════════════════════════════════════════════════════════════════════════════
# ETAPE 5 — Whisper
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo " ------------------------------------------"
echo " Etape 5/6 : Modèle vocal Whisper (~150 Mo)"
echo " ------------------------------------------"
echo " Téléchargement du modèle de dictée vocale..."

PYTHONWARNINGS=ignore TRANSFORMERS_VERBOSITY=error \
$PYTHON_CMD -c "import whisper; whisper.load_model('base'); print('[OK] Whisper prêt.')"
if [ $? -ne 0 ]; then
    echo " [AVERTISSEMENT] Whisper n'a pas pu être téléchargé maintenant."
    echo " La dictée vocale se chargera automatiquement à la première utilisation."
fi

# ══════════════════════════════════════════════════════════════════════════════
# ETAPE 6 — Embeddings + voix
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo " ------------------------------------------"
echo " Etape 6/6 : Options"
echo " ------------------------------------------"
echo ""
echo " La recherche par sens permet à NIMM de retrouver des souvenirs"
echo " même quand tu n'utilises pas les mots exacts."
echo " Nécessite un téléchargement unique de ~470 Mo."
echo ""
read -p " Activer la recherche par sens ? (o/n) : " EMBED_CHOICE
echo ""

EMBEDDINGS_ENABLED="false"
if [[ "$EMBED_CHOICE" =~ ^[oO]$ ]]; then
    EMBEDDINGS_ENABLED="true"
    echo " Téléchargement du modèle sémantique (~470 Mo)..."
    PYTHONWARNINGS=ignore TRANSFORMERS_VERBOSITY=error HF_HUB_DISABLE_PROGRESS_BARS=0 TOKENIZERS_PARALLELISM=false \
    $PYTHON_CMD -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2'); print('[OK] Modèle sémantique téléchargé.')"
    if [ $? -ne 0 ]; then
        echo " [AVERTISSEMENT] Le téléchargement a échoué."
        echo " Tu peux l'activer plus tard depuis les Paramètres de NIMM."
        EMBEDDINGS_ENABLED="false"
    fi
else
    echo " [OK] Recherche par sens désactivée. Activable depuis les Paramètres."
fi

echo ""
echo " Quelle voix préfères-tu pour NIMM ?"
echo "  [1] Denise — voix féminine, accent français  (recommandé)"
echo "  [2] Henri  — voix masculine, accent français (recommandé)"
echo "  [3] Je choisirai plus tard dans les Paramètres"
echo ""
read -p " Ton choix (1/2/3) : " VOICE_CHOICE

case "$VOICE_CHOICE" in
    1) TTS_VOICE="edge:fr-FR-DeniseNeural" ; echo " [OK] Voix : Denise." ;;
    2) TTS_VOICE="edge:fr-FR-HenriNeural"  ; echo " [OK] Voix : Henri."  ;;
    *) TTS_VOICE="edge:fr-FR-DeniseNeural" ; echo " [OK] Voix par défaut : Denise." ;;
esac

# ── Configuration initiale en base ────────────────────────────────────────────
echo ""
echo " Enregistrement de la configuration..."
$PYTHON_CMD "$SCRIPT_DIR/setup_defaults.py" "$TTS_VOICE" "$EMBEDDINGS_ENABLED"
if [ $? -ne 0 ]; then
    echo " [AVERTISSEMENT] Configuration non enregistrée. Paramétrable au premier lancement."
fi

# ── Raccourci bureau ───────────────────────────────────────────────────────────
echo ""
DESKTOP="$HOME/Desktop"
# Support macOS français (Bureau)
if [ -d "$HOME/Bureau" ]; then
    DESKTOP="$HOME/Bureau"
fi

SHORTCUT="$DESKTOP/NIMM.command"
echo "#!/bin/bash" > "$SHORTCUT"
echo "cd \"$SCRIPT_DIR\" && bash \"$SCRIPT_DIR/LANCER_NIMM.sh\"" >> "$SHORTCUT"
chmod +x "$SHORTCUT"

if [ -f "$SHORTCUT" ]; then
    echo " [OK] Raccourci créé sur le bureau."
else
    echo " [AVERTISSEMENT] Raccourci non créé."
    echo " Lance NIMM avec : bash $SCRIPT_DIR/LANCER_NIMM.sh"
fi

# ── Rendre les scripts exécutables ────────────────────────────────────────────
chmod +x "$SCRIPT_DIR/LANCER_NIMM.sh"
chmod +x "$SCRIPT_DIR/INSTALLER_NIMM.sh"

# ══════════════════════════════════════════════════════════════════════════════
# FIN
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo " =========================================="
echo "   Installation terminée ! Lancement..."
echo " =========================================="
echo ""
sleep 2
bash "$SCRIPT_DIR/LANCER_NIMM.sh"
