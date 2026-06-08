@echo off
cd /d "%~dp0"
echo [NIMM_DEBUG] Demarrage du serveur en mode debug...
echo [NIMM_DEBUG] Les logs s'affichent ci-dessous.
echo [NIMM_DEBUG] Ferme cette fenetre pour arreter le serveur.
echo ================================================
:: Libere le port 8080 si un ancien processus tourne encore
FOR /F "tokens=5" %%P IN ('netstat -aon ^| findstr ":8080 "') DO taskkill /F /PID %%P 2>nul
start /min cmd /c "timeout /t 4 /nobreak > nul && start http://localhost:8080"
py -m uvicorn main:app --host 0.0.0.0 --port 8080
