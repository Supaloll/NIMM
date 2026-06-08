@echo off
chcp 1252 >nul
cd /d "%~dp0"
setlocal enabledelayedexpansion
title Installation de NIMM
mode con cols=90 lines=40
color 0A
set "PYTHONWARNINGS=ignore"
set "TRANSFORMERS_VERBOSITY=error"
set "HF_HUB_DISABLE_PROGRESS_BARS=0"
set "TOKENIZERS_PARALLELISM=false"

echo.
echo  NIMM - Installation
echo  -------------------
echo.
echo  Dossier : %~dp0
echo.

:: Dossier data/
if not exist "%~dp0data\" (
    mkdir "%~dp0data"
    echo  [OK] Dossier data/ cree.
)

:: ETAPE 1 - Python
echo  Etape 1 sur 6 : Python

set "PYTHON_CMD="
python --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    echo  [OK] Python detecte.
    goto :python_ok
)
py --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py"
    echo  [OK] Python detecte via py.
    goto :python_ok
)

echo  Python introuvable. Installation via winget...
winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo.
    echo  [ERREUR] Impossible d'installer Python automatiquement.
    echo  Installe Python 3.11 manuellement : https://www.python.org/downloads/
    echo  Puis relance cet installateur.
    pause
    exit /b 1
)
set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%PATH%"
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERREUR] Python installe mais toujours introuvable dans le PATH.
    echo  Ferme cette fenetre, ouvre-en une nouvelle et relance INSTALLER_NIMM.bat.
    pause
    exit /b 1
)
set "PYTHON_CMD=python"
echo  [OK] Python installe et operationnel.

:python_ok

:: ETAPE 2 - ffmpeg
echo.
echo  Etape 2 sur 6 : ffmpeg (requis pour la dictee vocale)

ffmpeg -version >nul 2>&1
if not errorlevel 1 (
    echo  [OK] ffmpeg deja present.
    goto :ffmpeg_ok
)
echo  Installation de ffmpeg via winget...
winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo.
    echo  [AVERTISSEMENT] ffmpeg n'a pas pu etre installe automatiquement.
    echo  La dictee vocale ne fonctionnera pas sans lui.
    echo  Tu peux l'installer manuellement plus tard : https://ffmpeg.org/download.html
    echo  L'installation de NIMM continue...
) else (
    for /f "delims=" %%F in ('where ffmpeg 2^>nul') do set "FFMPEG_PATH=%%F"
    if not defined FFMPEG_PATH (
        set "PATH=%ProgramFiles%\ffmpeg\bin;%PATH%"
    )
    echo  [OK] ffmpeg installe.
)

:ffmpeg_ok

:: ETAPE 3 - Dependances Python
echo.
echo  Etape 3 sur 6 : Dependances Python
echo  Cela peut prendre 5 a 15 minutes (PyTorch ~2 Go inclus).
echo  Ne ferme pas cette fenetre.
echo.
%PYTHON_CMD% -m pip install --upgrade pip --quiet
if errorlevel 1 (
    echo  [AVERTISSEMENT] Mise a jour de pip echouee, on continue avec la version actuelle.
)
%PYTHON_CMD% -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo  [ERREUR] L'installation des dependances a echoue.
    echo  Consulte les messages ci-dessus pour identifier le probleme.
    echo  Tu peux reessayer manuellement : pip install -r requirements.txt
    pause
    exit /b 1
)
echo  [OK] Dependances installees.

:: ETAPE 4 - Modele Whisper
echo.
echo  Etape 4 sur 6 : Modele vocal Whisper (environ 150 Mo)
echo  Telechargement du modele de dictee vocale...
%PYTHON_CMD% -c "import whisper; whisper.load_model('base'); print('[OK] Whisper pret.')"
if errorlevel 1 (
    echo  [AVERTISSEMENT] Whisper n'a pas pu etre telecharge maintenant.
    echo  La dictee vocale se chargera automatiquement a la premiere utilisation.
)

:: ETAPE 5 - Recherche semantique (optionnel)
echo.
echo  Etape 5 sur 6 : Recherche par sens (optionnel)
echo.
echo  La recherche par sens permet a NIMM de retrouver des souvenirs
echo  meme quand tu n'utilises pas les mots exacts.
echo  Exemple : "ou j'habite ?" retrouve "domicile" ou "adresse".
echo.
echo  Necessite un telechargement unique de ~470 Mo.
echo  Sans cette option, la recherche par mots-cles reste active.
echo.
choice /c ON /n /m "  Activer la recherche par sens ? (O=Oui  N=Non) : "
if errorlevel 2 goto :embed_non
if errorlevel 1 goto :embed_oui

:embed_oui
set "EMBEDDINGS_ENABLED=true"
echo.
echo  Telechargement du modele semantique (~470 Mo)...
echo  Cela peut prendre quelques minutes selon ta connexion.
%PYTHON_CMD% -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2'); print('[OK] Modele semantique telecharge.')"
if errorlevel 1 (
    echo.
    echo  [AVERTISSEMENT] Le telechargement a echoue.
    echo  Tu peux l'activer plus tard depuis les Parametres de NIMM.
    set "EMBEDDINGS_ENABLED=false"
)
goto :choix_voix

:embed_non
set "EMBEDDINGS_ENABLED=false"
echo  [OK] Recherche par sens desactivee. Activable depuis les Parametres.

:choix_voix
:: Choix de la voix TTS par defaut
echo.
echo  Quelle voix preferes-tu pour NIMM ?
echo   [1] Denise - voix feminine, accent francais  (recommande)
echo   [2] Henri  - voix masculine, accent francais (recommande)
echo   [3] Je choisirai plus tard dans les Parametres
echo.
choice /c 123 /n /m "  Ton choix (1/2/3) : "
if errorlevel 3 goto :voix_3
if errorlevel 2 goto :voix_2
if errorlevel 1 goto :voix_1

:voix_1
set "TTS_VOICE=edge:fr-FR-DeniseNeural"
echo  [OK] Voix : Denise.
goto :config_write

:voix_2
set "TTS_VOICE=edge:fr-FR-HenriNeural"
echo  [OK] Voix : Henri.
goto :config_write

:voix_3
set "TTS_VOICE=edge:fr-FR-DeniseNeural"
echo  [OK] Voix par defaut : Denise (modifiable dans les Parametres).

:config_write
:: Ecriture de la configuration initiale
echo.
echo  Enregistrement de la configuration...
%PYTHON_CMD% "%~dp0setup_defaults.py" "%TTS_VOICE%" "%EMBEDDINGS_ENABLED%"
if errorlevel 1 (
    echo  [AVERTISSEMENT] Configuration non enregistree. Parametrable au premier lancement.
)

:: ETAPE 6 - Raccourci bureau
echo.
echo  Etape 6 sur 6 : Raccourci bureau
set "NIMM_DIR=%~dp0"
if "%NIMM_DIR:~-1%"=="\" set "NIMM_DIR=%NIMM_DIR:~0,-1%"
set "TARGET=%NIMM_DIR%\LANCER_NIMM.bat"
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP=%%D"
set "SHORTCUT=%DESKTOP%\NIMM.lnk"
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%TARGET%'; $s.WorkingDirectory = '%NIMM_DIR%'; $s.IconLocation = '%NIMM_DIR%\bretzel.ico'; $s.Save()"
if exist "%SHORTCUT%" (
    echo  [OK] Raccourci cree sur le bureau.
) else (
    echo  [AVERTISSEMENT] Raccourci non cree.
    echo  Fais un clic droit sur LANCER_NIMM.bat et choisis "Creer un raccourci".
)

:: FIN
echo.
echo  Installation terminee !
echo.
echo  NIMM s'ouvre dans votre navigateur.
echo  Cette fenetre se ferme seule dans 10 secondes.
echo.
timeout /t 10 /nobreak >nul
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath 'python' -ArgumentList '-m','uvicorn','main:app','--host','0.0.0.0','--port','8080' -WorkingDirectory '%NIMM_DIR%' -WindowStyle Hidden -RedirectStandardOutput '%NIMM_DIR%\nimm.log' -RedirectStandardError '%NIMM_DIR%\nimm_error.log'"
timeout /t 6 /nobreak >nul
start http://localhost:8080
pause
