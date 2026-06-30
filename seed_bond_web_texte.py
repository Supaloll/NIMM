"""
seed_bond_web_texte.py — Bond "Conversion d'une page web en texte accessible"

Prérequis :
    pip install beautifulsoup4 --break-system-packages
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

LABEL = "Conversion d'une page web ou fichier HTML en texte accessible"

TEXT = """Quand utiliser ce bond : quand l'utilisateur a un fichier HTML local
(page sauvegardée, export web, rapport HTML) et veut en extraire le contenu
textuel lisible au lecteur d'écran, sans les balises, scripts et styles.
Ou quand il veut vérifier la structure sémantique d'une page HTML locale.

Prérequis (une seule fois) :
    pip install beautifulsoup4 --break-system-packages

Ce bond traite des fichiers HTML locaux uniquement (pas de téléchargement web).

Méthode :

1. Demander le chemin du fichier HTML si non fourni.

2. Lire et analyser le fichier avec BeautifulSoup :
   from bs4 import BeautifulSoup
   with open(chemin, encoding='utf-8', errors='replace') as f:
       soup = BeautifulSoup(f.read(), 'html.parser')

3. Supprimer les éléments non pertinents :
   for tag in soup(['script', 'style', 'nav', 'footer', 'head']):
       tag.decompose()

4. Extraire la structure sémantique et le texte :
   - Titre de la page : soup.title.string si présent
   - Titres h1 à h6 : les afficher avec leur niveau
     "Titre niveau 1 : [texte]", "Titre niveau 2 : [texte]"
   - Paragraphes : texte brut
   - Liens : afficher le texte du lien et l'URL
     "Lien : [texte du lien] → [href]"
   - Images : afficher l'attribut alt
     "Image : [alt text]" ou "Image sans description" si alt est vide
   - Listes : chaque élément sur une ligne avec son numéro ou "Point :"
   - Tableaux : utiliser le bond "Extraction de tableaux" si détectés

5. Produire un résumé de la structure avant le texte complet :
   "Structure : X titres, Y paragraphes, Z liens, W images (dont V sans description)"

6. Si le fichier est volumineux (> 50 Ko), proposer d'extraire uniquement
   la partie principale (balise <main> ou <article> si présente).

Format de sortie : texte brut sans markdown, sections séparées par une ligne vide.

Règles importantes :
- Signaler toutes les images sans attribut alt : c'est une barrière d'accessibilité.
- Si la page n'a pas de balise <html lang="fr"> ou équivalente, le noter.
- Ne jamais télécharger d'URL distante depuis ce bond (sécurité réseau).
- Pour les fichiers encodés en latin-1 ou windows-1252, réessayer avec cet encodage
  si utf-8 échoue.
"""

META = {
    "description": "Extraire le texte d'un fichier HTML local en format lisible au lecteur d'écran, avec rapport de structure.",
    "mots_cles": [
        "html", "page web", "site", "extraire", "texte", "accessible",
        "convertir", "balises", "liens", "images", "alt", "structure",
        "beautifulsoup", "nettoyer", "lecteur écran",
    ],
    "valide": True,
    "valide_par_laurent": True,
    "version": 1,
}


def main():
    existing = list_prompts("skill")
    for sid, sk in (existing.items() if isinstance(existing, dict) else {}):
        lbl = (sk.get("label") or "").lower()
        if "html" in lbl and ("texte" in lbl or "accessible" in lbl):
            print(f"Bond similaire déjà présent (id={sid}) : {sk.get('label')}")
            return
    entry = save_prompt(None, LABEL, TEXT, type="skill", meta=META)
    if entry:
        print(f"Bond créé : {LABEL}")
    else:
        print("Erreur lors de la création.")


if __name__ == "__main__":
    main()
