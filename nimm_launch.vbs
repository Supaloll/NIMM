Dim WshShell, scriptDir

Set WshShell = CreateObject("WScript.Shell")

' Dossier du script (dynamique — fonctionne quel que soit l'emplacement)
scriptDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))

' Lancer uvicorn en arriere-plan — fenetre invisible (0)
WshShell.Run "cmd /c cd /d """ & scriptDir & """ && python -m uvicorn main:app --host 0.0.0.0 --port 8080 >> """ & scriptDir & "nimm.log"" 2>&1", 0, False

' Attendre que le serveur demarre
WScript.Sleep 4000

' Ouvrir le navigateur
WshShell.Run "http://localhost:8080", 1, False