"""
seed_skill_axe.py — Insère la fiche skill "Audit d'accessibilité WCAG (axe-core)"
dans la Promptothèque de NIMM.

Exécuter une seule fois depuis la racine du projet :
    python seed_skill_axe.py

Le skill sera ensuite retrouvé par CoaNIMM via find_skill() quand une demande
d'audit d'accessibilité sera détectée.
"""

import sys
import os

# S'assurer qu'on est bien à la racine du projet
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from core.database import save_prompt, list_prompts, get_all_users, set_user_context
except ImportError as e:
    print(f"Erreur d'import : {e}")
    print("Vérifiez que vous lancez ce script depuis la racine du projet NIMM.")
    sys.exit(1)

_users = get_all_users()
if not _users:
    print("Aucun utilisateur trouvé. Lancez NIMM au moins une fois.")
    sys.exit(1)
set_user_context(_users[0]["id"])
print(f"Contexte utilisateur : {_users[0].get('name', _users[0]['id'])}")

SKILL_LABEL = "Audit d'accessibilité WCAG d'un site web (axe-core)"

SKILL_TEXT = """Quand utiliser ce skill : quand on te demande de vérifier, analyser ou auditer
l'accessibilité d'un site ou d'une page web, de détecter des problèmes WCAG, de tester
si un site est conforme aux normes d'accessibilité numérique.

Méthode :
1. Appeler nimm_axe_audit(url) avec l'URL complète (http:// ou https://).
   Le helper charge la page dans un navigateur headless, exécute axe-core et retourne
   les violations classées par niveau d'impact.

2. Présenter les résultats de façon claire et accessible :
   - Commencer par le nombre total de violations et un résumé par niveau.
   - Pour chaque niveau (critique, grave, modérée, mineure) : lister les violations
     avec leur identifiant de règle, une description lisible, le critère WCAG concerné
     et le nombre d'éléments affectés.
   - Terminer par un rappel que les outils automatisés couvrent 30 à 40 % des critères
     WCAG, et qu'une évaluation humaine est nécessaire pour le reste.

3. Proposer des pistes de correction pour les violations critiques et graves.
   Rester factuel, ne pas fabriquer de règles WCAG inexistantes.

Limites à mentionner :
- axe-core ne teste pas les pages nécessitant une authentification.
- Les pages très chargées en JavaScript ou les Single Page Applications peuvent
  nécessiter un temps de chargement suffisant (le helper attend networkidle).
- Les contrastes de couleur, les textes alternatifs manquants et les structures
  de formulaires sont parmi les violations les plus fréquentes et les plus impactantes.
"""

SKILL_META = {
    "description": (
        "Auditer l'accessibilité WCAG d'une URL via axe-core : détecter les violations "
        "automatiquement détectables et les présenter par niveau d'impact."
    ),
    "mots_cles": [
        "accessibilité", "wcag", "axe", "axe-core", "audit", "a11y",
        "handicap", "aria", "contraste", "lecteur d'écran", "braille",
        "site web", "conformité", "wcag 2.1", "wcag 2.2", "rgaa",
        "critères", "violations", "vérifier", "tester"
    ],
    "helper": "nimm_axe_audit(url: str) -> str",
    "valide": True,
    "version": 1,
}


def main():
    # Vérifier si un skill axe-core existe déjà
    existing = list_prompts("skill")
    for sid, sk in (existing.items() if isinstance(existing, dict) else {}):
        if "axe" in (sk.get("label") or "").lower() or "accessibilité" in (sk.get("label") or "").lower():
            print(f"Un skill similaire existe déjà (id={sid}) : {sk.get('label')}")
            print("Supprimez-le d'abord si vous voulez le remplacer.")
            return

    entry = save_prompt(None, SKILL_LABEL, SKILL_TEXT, type="skill", meta=SKILL_META)
    if entry:
        skill_id = entry.get("id") or entry.get("prompt_id") or "?"
        print(f"Skill créé avec succès (id={skill_id}) : {SKILL_LABEL}")
    else:
        print("Erreur lors de la création du skill.")


if __name__ == "__main__":
    main()
