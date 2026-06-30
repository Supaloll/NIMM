"""
seed_bond_tableau_pdf.py — Bond "Extraction de tableaux PDF en texte lisible"

Prérequis :
    pip install pdfplumber --break-system-packages
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

LABEL = "Extraction de tableaux PDF en texte lisible (lecteur d'écran)"

TEXT = """Quand utiliser ce bond : quand l'utilisateur veut lire un tableau contenu dans
un PDF — grille de données, tableau récapitulatif, liste de prix, planning, résultats —
et qu'il a besoin d'une version en texte linéaire lisible par un lecteur d'écran ou
une plage braille. Les tableaux PDF sont visuels et inaccessibles tels quels.

Prérequis (une seule fois) :
    pip install pdfplumber --break-system-packages

Méthode :

1. Demander le chemin du fichier PDF si non fourni.
   Demander aussi si un numéro de page est visé, ou si tous les tableaux sont à extraire.

2. Ouvrir le PDF avec pdfplumber et extraire les tableaux :
   import pdfplumber
   with pdfplumber.open(chemin) as pdf:
       pages = [pdf.pages[n-1]] if num_page else pdf.pages
       for i, page in enumerate(pages):
           tables = page.extract_tables()
           for j, table in enumerate(tables):
               print(f"--- Tableau {j+1} (page {i+1}) ---")
               for row in table:
                   cellules = [str(c or "").strip() for c in row]
                   print(" | ".join(cellules))
               print()

3. Si aucun tableau n'est détecté, essayer extract_text() et signaler
   que la structure tabulaire n'a pas pu être identifiée automatiquement —
   proposer d'extraire le texte brut à la place.

4. Pour chaque tableau extrait, produire une version lisible supplémentaire :
   - Si la première ligne ressemble à des en-têtes (valeurs non vides),
     reformuler chaque ligne suivante sous forme de phrase :
     "Colonne1 : valeur1, Colonne2 : valeur2, ..."
   - Limiter à 50 lignes par tableau et signaler la troncature si dépassé.

5. Afficher le résultat complet. CoaNIMM lit la sortie et peut commenter,
   filtrer ou reformuler à la demande de l'utilisateur.

Règles importantes :
- Ne jamais inventer des valeurs manquantes : afficher "(vide)" si une cellule est nulle.
- Signaler clairement si le PDF est numérisé (image) et non extractible par pdfplumber.
- Si le tableau contient des fusions de cellules (merged cells), les signaler
  car pdfplumber peut les mal interpréter.
- Proposer en fin de traitement d'exporter le résultat dans un fichier .txt
  si l'utilisateur le souhaite.
"""

META = {
    "description": "Extraire les tableaux d'un PDF en texte linéaire lisible par lecteur d'écran ou plage braille.",
    "mots_cles": [
        "tableau", "table", "pdf", "colonnes", "lignes", "extraction", "grille",
        "données", "lecture", "accessible", "braille", "cellules", "planning",
        "liste", "résultats", "plage braille",
    ],
    "valide": True,
    "valide_par_laurent": True,
    "version": 1,
}


def main():
    existing = list_prompts("skill")
    for sid, sk in (existing.items() if isinstance(existing, dict) else {}):
        lbl = (sk.get("label") or "").lower()
        if "tableau" in lbl and "pdf" in lbl:
            print(f"Bond similaire déjà présent (id={sid}) : {sk.get('label')}")
            return
    entry = save_prompt(None, LABEL, TEXT, type="skill", meta=META)
    if entry:
        print(f"Bond créé : {LABEL}")
    else:
        print("Erreur lors de la création.")


if __name__ == "__main__":
    main()
