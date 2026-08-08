# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('ARCHITECTURE.md', 'r', encoding='utf-8') as f:
    content = f.read()

old = """| 07/08/2026 | **Chasse à la latence, suite et fin : cause racine trouvée — DeepSeek réfléchit en cachette**."""

new = """| 07/08/2026 | **Menus "⋯" des messages : débordement d'écran corrigé des deux côtés**. Deux bugs remontés par Laurent après la correction DeepSeek. (1) Côté messages UTILISATEUR : le menu contextuel (`.copy-menu`, Copier/Modifier) s'affichait hors de l'écran, collé au bord droit. Cause : `_positionMenu()` — la fonction qui gère déjà correctement l'ouverture haut/bas et le clamp horizontal pour les messages de Lia — n'était tout simplement jamais appelée pour les messages utilisateur (`appendUserMessage`), qui n'avaient aucune logique de positionnement. CORRIGÉ : `_positionMenu()` étendue avec un paramètre `anchorRight` (ancre le coin droit du menu sur le bouton et ouvre vers la gauche, pour les messages alignés à droite) ; appel ajouté côté `appendUserMessage` avec `anchorRight=true`. En prime, `.message-actions` (conteneur du bouton côté messages utilisateur) n'avait aucune règle CSS `position` définie, ce qui pouvait faire dériver `.copy-menu` (position: absolute) vers un ancêtre positionné imprévu — ajouté `position: relative`. (2) Menu des DERNIERS messages (Lia) : une fois `_positionMenu()` en place partout, un second cas est apparu — le menu s'ouvrait vers le bas et se faisait couper par la barre de saisie (`#input-area`, fixe en bas d'écran), car le calcul de l'espace disponible se basait sur `window.innerHeight` sans tenir compte du fait que cette barre recouvre une partie de la fenêtre. CORRIGÉ : la limite basse utilisée par `_positionMenu()` est désormais le bord haut réel de `#input-area` (mesuré via `getBoundingClientRect()`), et non plus le bas brut de la fenêtre. Cache-busting appliqué deux fois ce jour (`app.js?v=20260807` puis `20260807-1`, `styles.css?v=20260807`) au fil des correctifs successifs. |"""

nl = chr(10)
new_full = new + nl + old

count = content.count(old)
print(f"FOUND: {count} occurrence(s)")
if count == 0:
    print("ERR: texte non trouve")
elif count == 1:
    content = content.replace(old, new_full, 1)
    with open('ARCHITECTURE.md', 'w', encoding='utf-8') as f:
        f.write(content)
    print("DONE: 1 remplacement effectue")
else:
    content = content.replace(old, new_full)
    with open('ARCHITECTURE.md', 'w', encoding='utf-8') as f:
        f.write(content)
    print("DONE: " + str(count) + " remplacement(s) effectue(s)")