@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ================================================================
echo  BANC D'ESSAI - REGLE DE RETENUE DE COANIMM
echo ================================================================
echo.
echo  Ce banc mesure si coaNIMM demande une precision AU BON MOMENT :
echo  une trentaine de messages etiquetes, envoyes au vrai couple
echo  prompt + outils, sans rien ecrire dans la base.
echo.
echo  ATTENTION : appels API reels. Une trentaine de messages courts
echo  par fournisseur teste.
echo.
echo  Le rapport est ecrit dans tests\results\ au fur et a mesure.
echo ================================================================
echo.
echo  1. Verification a sec  (gratuit, aucun appel)
echo  2. Les 10 cas ambigus  (le plus informatif : coaNIMM demande-t-il ?)
echo  3. Les 30 cas          (fournisseur du profil)
echo  4. Les 30 cas sur deux fournisseurs  (deepseek et mistral)
echo.
set /p CHOIX="Ton choix (1, 2, 3 ou 4) puis Entree : "

if "%CHOIX%"=="1" py tests\banc_essai_retenue.py --a-sec
if "%CHOIX%"=="2" py tests\banc_essai_retenue.py --etiquette ambigu
if "%CHOIX%"=="3" py tests\banc_essai_retenue.py
if "%CHOIX%"=="4" py tests\banc_essai_retenue.py --fournisseurs deepseek,mistral

echo.
echo ================================================================
echo  Termine. Le rapport complet est dans tests\results\
echo  (le fichier le plus recent, nomme retenue_ suivi de la date).
echo ================================================================
pause
