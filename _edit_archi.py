# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('ARCHITECTURE.md', 'r', encoding='utf-8') as f:
    content = f.read()

old = "| 20/06/2026 | **CoaNIMM — fiabilité des prompts libres, sécurité (confinement), opérations Fichiers/Documents, accessibilité PDF**."

new = """| 25/06/2026 | **Mémoire — un seul partenaire actif à la fois**. [modules/memory.py] `_PARTENAIRE_PREDICATS` (groupe de synonymes conjoint/epoux/epouse/mari/femme/compagnon/compagne/partenaire) + `_purger_partenaires_concurrents(sujet, nouvel_objet, existing)` : supprime tout ancien lien de couple du sujet vers un objet différent avant d'écrire un nouveau lien — empêche la coexistence de deux partenaires (ex : `conjoint=Nadia` et `epouse=Maïssane` simultanément). Branché dans `save_inline_memory` (branche création d'un nouveau triplet, avant écriture) et dans `_save_symmetric` (purge dans les deux sens — sujet→objet et objet→sujet — avant de créer la réciproque). Corrige un cas réel : triplet orphelin `Maïssane/conjoint/Laurent` + son inverse inféré `Laurent/conjoint/Maïssane` se régénérant en boucle au démarrage via le moteur de symétrie (`run_inference_engine`), faute de garde-fou à l'écriture. Note : le moteur d'inférence lui-même (`_add()`) n'a pas encore ce garde-fou — angle mort résiduel, accepté pour l'instant. |
| 20/06/2026 | **CoaNIMM — fiabilité des prompts libres, sécurité (confinement), opérations Fichiers/Documents, accessibilité PDF**."""

count = content.count(old)
print(f"FOUND: {count} occurrence(s)")

if count == 0:
    print("ERR: texte non trouve")
    sys.exit(1)

content = content.replace(old, new, 1)
print("DONE: remplacement effectue")

with open('ARCHITECTURE.md', 'w', encoding='utf-8') as f:
    f.write(content)
