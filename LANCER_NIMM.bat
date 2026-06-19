@echo off
cd /d "%~dp0"
set "NIMM_DIR=%~dp0"
if "%NIMM_DIR:~-1%"=="\" set "NIMM_DIR=%NIMM_DIR:~0,-1%"

:: Mise a jour desactivee -- utiliser le bouton Mise a jour dans les reglages

:: Libere le port 8080 si un ancien processus tourne encore
FOR /F "tokens=5" %%P IN ('netstat -aon ^| findstr ":8080 "') DO taskkill /F /PID %%P 2>nul

echo [NIMM] Demarrage...
tailscale serve --bg http://localhost:8080 >nul 2>&1
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process 'py' -ArgumentList @('-m','uvicorn','main:app','--host','0.0.0.0','--port','8080') -WorkingDirectory '%NIMM_DIR%' -WindowStyle Hidden"

timeout /t 4 /nobreak >nul
start http://localhost:8080
