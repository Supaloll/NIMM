#!/usr/bin/env bash
# ============================================
# NIMM — INSTALLER_NIMM.sh
# Installation automatique — macOS / Linux
# ============================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

OS="$(uname -s)"
case "$OS" in
    Darwin) PLATFORM="macos" ;;
    Linux)  PLATFORM="linux" ;;
    *)
        echo "[ERREUR] Système non supporté : $OS"
        exit 1
        ;;
esac

echo ""
echo " =========================================="
echo "   NIMM — Installation ($PLATFORM)"
echo " =========================================="
echo ""
echo " Dossier : $SCRIPT_DIR"
echo ""

# ── Utilitaires ────────────────────────────────────────────────────────────────
die() {
    echo ""
    echo " [ERREUR] $1"
    exit 1
}

install_linux_package() {
    local package="$1"

    if command -v apt-get >/dev/null 2>&1; then
        echo " Installation de $package via apt..."
        sudo apt-get update
        sudo apt-get install -y "$package"
    elif command -v dnf >/dev/null 2>&1; then
        echo " Installation de $package via dnf..."
        sudo dnf install -y "$package"
    elif command -v yum >/dev/null 2>&1; then
        echo " Installation de $package via yum..."
        sudo yum install -y "$package"
    elif command -v pacman >/dev/null 2>&1; then
        echo " Installation de $package via pacman..."
        sudo pacman -Sy --needed --noconfirm "$package"
    elif command -v zypper >/dev/null 2>&1; then
        echo " Installation de $package via zypper..."
        sudo zypper --non-interactive install "$package"
    else
        return 1
    fi
}

# ── Dossier data/ ─────────────────────────────────────────────────────────────
if [ ! -d "$SCRIPT_DIR/data" ]; then
    mkdir -p "$SCRIPT_DIR/data"
    echo " [OK] Dossier data/ créé."
fi

# ══════════════════════════════════════════════════════════════════════════════
# ETAPE 1 — Gestionnaire de paquets / dépendances système
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo " ------------------------------------------"
echo " Etape 1/6 : Dépendances système"
echo " ------------------------------------------"

if [ "$PLATFORM" = "macos" ]; then
    if command -v brew >/dev/null 2>&1; then
        echo " [OK] Homebrew détecté."
    else
        echo " Installation de Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" ||
            die "Homebrew n'a pas pu être installé. Installe-le depuis https://brew.sh"

        # Apple Silicon + Intel
        if [ -x /opt/homebrew/bin/brew ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        elif [ -x /usr/local/bin/brew ]; then
            eval "$(/usr/local/bin/brew shellenv)"
        fi
        echo " [OK] Homebrew installé."
    fi
else
    echo " [OK] Linux détecté."
    if ! command -v sudo >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ]; then
        die "sudo est requis pour installer les dépendances système."
    fi
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
    echo " [OK] Python détecté : $("$PYTHON_CMD" --version 2>&1)"
else
    echo " Python absent — installation..."

    if [ "$PLATFORM" = "macos" ]; then
        brew install python || die "Python n'a pas pu être installé."
    else
        install_linux_package python3 || die "Impossible d'installer Python 3 avec le gestionnaire de paquets détecté."
    fi

    command -v python3 >/dev/null 2>&1 ||
        die "Python 3 reste introuvable après installation."

    PYTHON_CMD="python3"
    echo " [OK] Python installé."
fi

# ── pip / environnement virtuel ───────────────────────────────────────────────
# Utiliser un venv évite de polluer le Python système Linux/macOS.
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo " Création de l'environnement virtuel : $VENV_DIR"
    "$PYTHON_CMD" -m venv "$VENV_DIR" ||
        die "Impossible de créer l'environnement virtuel Python."
fi

PYTHON_CMD="$VENV_DIR/bin/python"
echo " [OK] Environnement Python : $VENV_DIR"

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
    echo " Installation de ffmpeg..."

    if [ "$PLATFORM" = "macos" ]; then
        brew install ffmpeg || {
            echo " [AVERTISSEMENT] ffmpeg n'a pas pu être installé."
            echo " La dictée vocale ne fonctionnera pas sans lui."
        }
    else
        install_linux_package ffmpeg || {
            echo " [AVERTISSEMENT] ffmpeg n'a pas pu être installé automatiquement."
            echo " Installe-le avec le gestionnaire de paquets de ta distribution."
        }
    fi

    if command -v ffmpeg >/dev/null 2>&1; then
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

"$PYTHON_CMD" -m pip install --upgrade pip --quiet ||
    die "Impossible de mettre pip à jour."

"$PYTHON_CMD" -m pip install -r "$SCRIPT_DIR/requirements.txt" ||
    die "L'installation des dépendances Python a échoué."

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
"$PYTHON_CMD" -c "import whisper; whisper.load_model('base'); print('[OK] Whisper prêt.')" || {
    echo " [AVERTISSEMENT] Whisper n'a pas pu être téléchargé maintenant."
    echo " La dictée vocale se chargera automatiquement à la première utilisation."
}

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

read -r -p " Activer la recherche par sens ? (o/n) : " EMBED_CHOICE
echo ""

EMBEDDINGS_ENABLED="false"
if [[ "$EMBED_CHOICE" =~ ^[oO]$ ]]; then
    EMBEDDINGS_ENABLED="true"
    echo " Téléchargement du modèle sémantique (~470 Mo)..."

    PYTHONWARNINGS=ignore \
    TRANSFORMERS_VERBOSITY=error \
    HF_HUB_DISABLE_PROGRESS_BARS=0 \
    TOKENIZERS_PARALLELISM=false \
    "$PYTHON_CMD" -c \
        "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2'); print('[OK] Modèle sémantique téléchargé.')" || {
            echo " [AVERTISSEMENT] Le téléchargement a échoué."
            echo " Tu peux l'activer plus tard depuis les Paramètres de NIMM."
            EMBEDDINGS_ENABLED="false"
        }
else
    echo " [OK] Recherche par sens désactivée. Activable depuis les Paramètres."
fi

echo ""
echo " Quelle voix préfères-tu pour NIMM ?"
echo "  [1] Denise — voix féminine, accent français"
echo "  [2] Henri  — voix masculine, accent français"
echo "  [3] Je choisirai plus tard dans les Paramètres"
echo ""

read -r -p " Ton choix (1/2/3) : " VOICE_CHOICE

case "$VOICE_CHOICE" in
    1) TTS_VOICE="edge:fr-FR-DeniseNeural"; echo " [OK] Voix : Denise." ;;
    2) TTS_VOICE="edge:fr-FR-HenriNeural";  echo " [OK] Voix : Henri." ;;
    *) TTS_VOICE="edge:fr-FR-DeniseNeural"; echo " [OK] Voix par défaut : Denise." ;;
esac

echo ""
echo " Enregistrement de la configuration..."
"$PYTHON_CMD" "$SCRIPT_DIR/setup_defaults.py" "$TTS_VOICE" "$EMBEDDINGS_ENABLED" || {
    echo " [AVERTISSEMENT] Configuration non enregistrée. Paramétrable au premier lancement."
}

# ── Lanceur / raccourci ───────────────────────────────────────────────────────
echo ""

if [ "$PLATFORM" = "macos" ]; then
    DESKTOP="$HOME/Desktop"
    [ -d "$HOME/Bureau" ] && DESKTOP="$HOME/Bureau"

    mkdir -p "$DESKTOP"
    SHORTCUT="$DESKTOP/NIMM.command"

    cat > "$SHORTCUT" <<EOF
#!/bin/bash
cd "$SCRIPT_DIR" || exit 1
exec "$SCRIPT_DIR/LANCER_NIMM.sh"
EOF
    chmod +x "$SHORTCUT"

    [ -f "$SHORTCUT" ] && echo " [OK] Raccourci macOS créé sur le bureau."
else
    # Standard XDG : ~/Desktop, ~/Bureau, ou chemin configuré par XDG.
    DESKTOP="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
    if [ ! -d "$DESKTOP" ] && [ -d "$HOME/Bureau" ]; then
        DESKTOP="$HOME/Bureau"
    fi

    mkdir -p "$DESKTOP"

    DESKTOP_FILE="$DESKTOP/NIMM.desktop"
    cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=NIMM
Comment=Compagnon IA personnel
Exec=$SCRIPT_DIR/LANCER_NIMM.sh
Path=$SCRIPT_DIR
Terminal=true
Categories=Utility;Office;
EOF
    chmod +x "$DESKTOP_FILE"

    # Certains environnements GNOME/KDE demandent une autorisation explicite.
    if command -v gio >/dev/null 2>&1; then
        gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null || true
    fi

    [ -f "$DESKTOP_FILE" ] && echo " [OK] Lanceur Linux créé : $DESKTOP_FILE"
fi

# ── Permissions ───────────────────────────────────────────────────────────────
chmod +x "$SCRIPT_DIR/LANCER_NIMM.sh" "$SCRIPT_DIR/INSTALLER_NIMM.sh"

echo ""
echo " =========================================="
echo "   Installation terminée !"
echo " =========================================="
echo ""
sleep 2
exec "$SCRIPT_DIR/LANCER_NIMM.sh"
