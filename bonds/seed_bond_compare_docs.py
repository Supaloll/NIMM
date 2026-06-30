"""
seed_bond_compare_docs.py — Bond "Comparaison de deux versions d'un document"

Pas de dépendance externe (difflib intégré à Python).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

LABEL = "Comparaison de deux versions d'un document (diff accessible)"

TEXT = """Quand utiliser ce bond : quand l'utilisateur veut comparer deux versions d'un même
document texte — une ancienne et une nouvelle version — pour identifier ce qui a changé,
été ajouté ou supprimé. Produit un rapport de différences lisible au lecteur d'écran.

Fonctionne avec : .txt, .md, .html, .csv, .py et tout fichier texte brut.
Pour les .pdf et .docx, extraire d'abord le texte (voir bond "Résumé accessible").

Pas de dépendance externe : utilise le module difflib intégré à Python.

Méthode :

1. Demander les chemins des deux fichiers si non fournis.
   Appeler le premier "version originale" et le second "nouvelle version".

2. Lire les deux fichiers :
   with open(chemin1, encoding='utf-8', errors='replace') as f:
       lignes1 = f.readlines()
   with open(chemin2, encoding='utf-8', errors='replace') as f:
       lignes2 = f.readlines()

3. Calculer le diff avec difflib :
   import difflib
   diff = list(difflib.unified_diff(lignes1, lignes2,
               fromfile='Version originale', tofile='Nouvelle version', lineterm=''))

4. Transformer le diff brut en texte lisible et accessible :
   - Les lignes supprimées (commençant par "-") : afficher "SUPPRIMÉ : [texte]"
   - Les lignes ajoutées (commençant par "+") : afficher "AJOUTÉ : [texte]"
   - Les lignes contextuelles (commençant par " ") : ne pas afficher
     (sauf si l'utilisateur demande le contexte)
   - Les en-têtes "---" et "+++" : afficher le nom des fichiers comparés
   - Les marqueurs "@@ ... @@" : afficher "Bloc de modifications :"

5. Produire un résumé chiffré avant la liste des changements :
   "Résumé : X lignes supprimées, Y lignes ajoutées, Z lignes inchangées."

6. Si aucune différence n'est trouvée, le dire clairement :
   "Les deux fichiers sont identiques."

7. Si les différences sont très nombreuses (plus de 100 modifications),
   ne montrer que les 50 premières et proposer de sauvegarder le diff complet
   dans un fichier .txt.

Format de sortie : texte brut, une modification par ligne, pas de tableau.

Règles importantes :
- Toujours préciser clairement ce qui est "original" et ce qui est "nouveau".
- Si les fichiers sont encodés différemment, le signaler et essayer latin-1 en fallback.
- Pour les fichiers volumineux (> 500 lignes), avertir que l'analyse peut prendre
  quelques secondes.
"""

META = {
    "description": "Comparer deux versions d'un document texte et lister les ajouts, suppressions en format accessible.",
    "mots_cles": [
        "comparer", "comparaison", "différences", "modifications", "changements",
        "deux versions", "diff", "avant après", "ajouts", "suppressions",
        "document", "texte", "version", "révision",
    ],
    "valide": True,
    "valide_par_laurent": True,
    "version": 1,
}


def main():
    existing = list_prompts("skill")
    for sid, sk in (existing.items() if isinstance(existing, dict) else {}):
        lbl = (sk.get("label") or "").lower()
        if "compar" in lbl and ("doc" in lbl or "version" in lbl):
            print(f"Bond similaire déjà présent (id={sid}) : {sk.get('label')}")
            return
    entry = save_prompt(None, LABEL, TEXT, type="skill", meta=META)
    if entry:
        print(f"Bond créé : {LABEL}")
    else:
        print("Erreur lors de la création.")


if __name__ == "__main__":
    main()
