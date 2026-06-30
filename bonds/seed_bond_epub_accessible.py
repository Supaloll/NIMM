"""
seed_bond_epub_accessible.py — Bond "Créer un EPUB3 accessible"

Prérequis :
    pip install ebooklib --break-system-packages
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

LABEL = "Créer un livre numérique EPUB3 accessible"

TEXT = """Quand utiliser ce bond : quand l'utilisateur veut créer un livre numérique
au format EPUB3 — le format le plus accessible pour les lecteurs d'écran, les
plages braille et les liseuses comme Thorium Reader (qui gère EPUB3 Accessibility).
EPUB3 bien formé permet la navigation par chapitres, titres, notes, et supporte
les médias overlay (audio synchronisé).

Prérequis (une seule fois) :
    pip install ebooklib --break-system-packages

Méthode :

1. Recueillir la structure du livre :
   - Titre, auteur, langue (fr par défaut), description courte
   - Liste des chapitres avec leur titre et contenu texte
   - Images éventuelles avec alt text pour chacune
   - Notes de bas de page ou références si présentes

2. Créer le livre avec ebooklib :
   from ebooklib import epub
   book = epub.EpubBook()
   book.set_identifier('id-unique-' + str(int(__import__('time').time())))
   book.set_title("Titre du livre")
   book.set_language('fr')
   book.add_author("Nom de l'auteur")
   book.add_metadata('DC', 'description', "Description courte du livre")

3. Métadonnées d'accessibilité EPUB3 (obligatoires pour conformité) :
   book.add_metadata(None, 'meta', '', {'property': 'schema:accessMode', 'content': 'textual'})
   book.add_metadata(None, 'meta', '', {'property': 'schema:accessModeSufficient', 'content': 'textual'})
   book.add_metadata(None, 'meta', '', {'property': 'schema:accessibilityFeature', 'content': 'structuralNavigation'})
   book.add_metadata(None, 'meta', '', {'property': 'schema:accessibilityFeature', 'content': 'tableOfContents'})
   book.add_metadata(None, 'meta', '', {'property': 'schema:accessibilityHazard', 'content': 'none'})
   book.add_metadata(None, 'meta', '', {'property': 'schema:accessibilitySummary',
       'content': 'Ce document est conforme EPUB3 Accessibility 1.1.'})

4. Créer chaque chapitre comme un fichier XHTML sémantique :
   chapitre = epub.EpubHtml(title="Titre du chapitre", file_name="chap01.xhtml", lang="fr")
   chapitre.content = ("<?xml version='1.0' encoding='utf-8'?>\n"
   <!DOCTYPE html>
   <html xmlns="http://www.w3.org/1999/xhtml" xml:lang="fr" lang="fr">
   <head><title>Titre du chapitre</title></head>
   <body>
     <section epub:type="chapter" role="doc-chapter" aria-labelledby="ch1-titre">
       <h1 id="ch1-titre">Titre du chapitre</h1>
       <p>Contenu du chapitre...</p>
     </section>
   </body>
   "   </html>").encode('utf-8')
   book.add_item(chapitre)

5. Créer la table des matières et la navigation :
   book.toc = [epub.Link('chap01.xhtml', 'Chapitre 1', 'chap01'),
               epub.Link('chap02.xhtml', 'Chapitre 2', 'chap02')]
   book.add_item(epub.EpubNcx())   # navigation EPUB2 (compatibilité)
   book.add_item(epub.EpubNav())   # navigation EPUB3

6. Définir l'ordre de lecture (spine) :
   book.spine = ['nav'] + liste_des_chapitres

7. Sauvegarder :
   epub.write_epub(chemin_sortie, book, {})
   print(f"EPUB3 accessible généré : {chemin_sortie}")

8. Règles d'accessibilité pour le contenu XHTML de chaque chapitre :
   - epub:type sur les sections (chapter, preface, appendix, footnote...)
   - role ARIA correspondant (doc-chapter, doc-preface, doc-footnote...)
   - aria-labelledby pointant vers le titre h1 de chaque section
   - Chaque <img> avec alt non vide, ou alt="" si purement décorative
   - Liens avec texte descriptif
   - Langue déclarée sur chaque chapitre (lang="fr")
   - Pas de mise en page par tableaux (utiliser CSS si besoin)

Règles importantes :
- Tester le fichier EPUB avec Thorium Reader (gratuit, Windows/Mac/Linux)
  ou ACE by DAISY (outil de validation EPUB Accessibility).
- Les notes de bas de page doivent utiliser epub:type="footnote" et être
  liées depuis le texte par <a epub:type="noteref" href="#note1">[1]</a>.
- Si le livre contient des formules mathématiques, utiliser MathML dans le XHTML.
- Pour les images complexes (graphiques, cartes), fournir une longdesc en plus
  de l'alt text court.
"""

META = {
    "description": "Créer un livre numérique EPUB3 accessible avec métadonnées d'accessibilité, navigation sémantique et conformité EPUB Accessibility 1.1.",
    "mots_cles": [
        "epub", "epub3", "livre", "livre numérique", "ebook", "accessible",
        "thorium", "daisy", "navigation", "chapitres", "liseuse",
        "ebooklib", "créer", "générer", "braille", "lecteur écran",
    ],
    "valide": True,
    "valide_par_laurent": True,
    "version": 1,
}


def main():
    existing = list_prompts("skill")
    for sid, sk in (existing.items() if isinstance(existing, dict) else {}):
        lbl = (sk.get("label") or "").lower()
        if "epub" in lbl:
            print(f"Bond similaire déjà présent (id={sid}) : {sk.get('label')}")
            return
    entry = save_prompt(None, LABEL, TEXT, type="skill", meta=META)
    if entry:
        print(f"Bond créé : {LABEL}")
    else:
        print("Erreur lors de la création.")


if __name__ == "__main__":
    main()
