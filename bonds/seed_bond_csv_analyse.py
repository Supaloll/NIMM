"""
seed_bond_csv_analyse.py — Bond "Analyse de fichier CSV en texte lisible"

Pas de dépendance externe (module csv intégré à Python).
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

LABEL = "Analyse de fichier CSV en texte lisible (résumé + statistiques)"

TEXT = """Quand utiliser ce bond : quand l'utilisateur veut comprendre le contenu d'un
fichier CSV — un export de base de données, une liste de contacts, des résultats
chiffrés, un fichier de données tabulaires. L'objectif est de produire un résumé
textuel lisible au lecteur d'écran, sans tableau visuel.

Pas de dépendance externe nécessaire : le module csv est intégré à Python.

Méthode :

1. Demander le chemin du fichier CSV si non fourni.
   Demander aussi l'encodage si l'utilisateur le connaît (utf-8 par défaut,
   essayer latin-1 en cas d'erreur de décodage).

2. Lire le fichier et détecter automatiquement le séparateur :
   import csv
   with open(chemin, encoding='utf-8', errors='replace') as f:
       dialect = csv.Sniffer().sniff(f.read(2048))
       f.seek(0)
       reader = csv.DictReader(f, dialect=dialect)
       rows = list(reader)
   colonnes = list(rows[0].keys()) if rows else []

3. Afficher une description structurée :
   - Nombre de lignes et de colonnes
   - Liste des colonnes avec leur nom
   - Pour chaque colonne : détecter si numérique, textuelle, ou date
   - Pour les colonnes numériques : minimum, maximum, moyenne (arrondie à 2 décimales)
   - Pour les colonnes textuelles : nombre de valeurs uniques, valeur la plus fréquente
   - Afficher les 5 premières lignes sous forme de phrases :
     "Ligne 1 : ColonneA = valeur, ColonneB = valeur, ..."

4. Limiter l'analyse aux 1000 premières lignes si le fichier est volumineux,
   et le signaler.

5. Conclure par une phrase de synthèse résumant ce que contient le fichier.

Format de sortie : texte brut, pas de tableau, pas de markdown.
Chaque information sur une ligne séparée. Sections introduites par un mot-clé
suivi de deux-points (exemple "Colonnes : NomA, NomB, NomC").

Règles importantes :
- Si le fichier contient des données personnelles identifiables (noms, emails,
  numéros), le signaler à l'utilisateur avant de les afficher.
- Si le séparateur ne peut pas être détecté, essayer successivement
  virgule, point-virgule, tabulation.
- Ne jamais tenter d'interpréter le sens métier des données sans demande explicite.
"""

META = {
    "description": "Lire un fichier CSV et produire un résumé textuel lisible (colonnes, statistiques, aperçu des données).",
    "mots_cles": [
        "csv", "données", "statistiques", "colonnes", "lignes", "tableau",
        "export", "base de données", "fichier", "analyse", "résumé",
        "chiffres", "liste", "contacts", "résultats",
    ],
    "valide": True,
    "valide_par_laurent": True,
    "version": 1,
}


def main():
    existing = list_prompts("skill")
    for sid, sk in (existing.items() if isinstance(existing, dict) else {}):
        lbl = (sk.get("label") or "").lower()
        if "csv" in lbl:
            print(f"Bond similaire déjà présent (id={sid}) : {sk.get('label')}")
            return
    entry = save_prompt(None, LABEL, TEXT, type="skill", meta=META)
    if entry:
        print(f"Bond créé : {LABEL}")
    else:
        print("Erreur lors de la création.")


if __name__ == "__main__":
    main()
