# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('frontend/styles.css', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Chercher les lignes avec -webkit-appearance
for i, line in enumerate(lines):
    if '-webkit-appearance: none;' in line:
        # Voir si la ligne suivante a deja appearance: none
        if i + 1 < len(lines) and 'appearance: none;' in lines[i + 1]:
            print(f"Ligne {i+1}: deja complete (appearance: none present)")
        else:
            print(f"Ligne {i+1}: MANQUE appearance: none -> {repr(line)}")
            # Ajouter appearance: none apres
            lines.insert(i + 1, '    appearance: none;\n')
            print(f"  -> Ajoute a la ligne {i+2}")

with open('frontend/styles.css', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("OK: fichier sauvegarde")
