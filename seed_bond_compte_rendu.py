"""
seed_bond_compte_rendu.py — Bond "Mise en forme de compte-rendu de réunion"

Pas de dépendance externe.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from core.database import save_prompt, list_prompts, get_all_users, set_user_context
except ImportError as e:
    print(f"Erreur d'import : {e}")
    sys.exit(1)

_users = get_all_users()
if not _users:
    print("Aucun utilisateur trouvé. Lancez NIMM au moins une fois.")
    sys.exit(1)
set_user_context(_users[0]["id"])
print(f"Contexte utilisateur : {_users[0].get('name', _users[0]['id'])}")

LABEL = "Mise en forme de compte-rendu de réunion (texte braille-friendly)"

TEXT = """Quand utiliser ce bond : quand l'utilisateur a des notes de réunion brutes —
dictées, tapées rapidement, désordonnées — et veut les transformer en un compte-rendu
structuré, lisible au lecteur d'écran ou sur plage braille.

Ce bond ne génère pas de code Python : il guide CoaNIMM pour traiter le texte
directement via le LLM, sans exécuter de script.

Méthode :

1. Si l'utilisateur fournit ses notes dans le message, les lire attentivement.
   Si les notes sont dans un fichier, demander le chemin et lire le fichier avec
   open(chemin, encoding='utf-8').read() puis afficher le contenu pour traitement.

2. Identifier dans les notes brutes :
   - La date et l'heure de la réunion (si mentionnées)
   - Les participants (noms, fonctions si présents)
   - L'ordre du jour ou les thèmes abordés
   - Les décisions prises (chercher les formulations "on a décidé", "il est convenu",
     "validation de", "accord sur")
   - Les actions à venir avec leur responsable et échéance si précisés
   - Les points restés en suspens ou à reporter

3. Produire le compte-rendu selon cette structure en texte brut :

   Date et heure : ...
   Participants : ...

   Thèmes abordés :
   [Pour chaque thème : une phrase de résumé de ce qui a été dit]

   Décisions prises :
   [Une décision par ligne, formulée à l'infinitif : "Valider le budget de..."]

   Actions à venir :
   [Une action par ligne : "Qui : faire quoi, avant le date"]

   Points en suspens :
   [Ce qui n'a pas été tranché]

4. Règles de forme strictes (accessibilité braille) :
   - Aucun astérisque, aucun tiret de liste, aucun dièse (#)
   - Sections séparées par une ligne vide
   - Phrases courtes (moins de 25 mots)
   - Noms propres écrits complètement (pas d'initiales seules)
   - Abréviations évitées ou explicitées

5. Proposer ensuite de sauvegarder le compte-rendu dans un fichier .txt
   dans le dossier de travail CoaNIMM si l'utilisateur le souhaite.

Règles importantes :
- Ne pas inventer de participants, décisions ou actions qui ne sont pas dans les notes.
- Si une information est ambiguë, la noter comme "à confirmer".
- Si les notes sont en partie illisibles ou tronquées, le signaler.
"""

META = {
    "description": "Transformer des notes de réunion brutes en compte-rendu structuré, lisible sur plage braille.",
    "mots_cles": [
        "réunion", "compte-rendu", "notes", "résumé", "procès-verbal",
        "ordre du jour", "décisions", "actions", "participants", "mise en forme",
        "structurer", "rédiger", "braille", "accessible",
    ],
    "valide": True,
    "valide_par_laurent": True,
    "version": 1,
}


def main():
    existing = list_prompts("skill")
    for sid, sk in (existing.items() if isinstance(existing, dict) else {}):
        lbl = (sk.get("label") or "").lower()
        if "compte-rendu" in lbl or "réunion" in lbl:
            print(f"Bond similaire déjà présent (id={sid}) : {sk.get('label')}")
            return
    entry = save_prompt(None, LABEL, TEXT, type="skill", meta=META)
    if entry:
        print(f"Bond créé : {LABEL}")
    else:
        print("Erreur lors de la création.")


if __name__ == "__main__":
    main()
