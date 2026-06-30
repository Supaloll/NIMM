"""
seed_bond_pdf_accessible.py — Bond "Créer un PDF accessible (tagué, structuré)"

Prérequis :
    pip install weasyprint --break-system-packages
    (WeasyPrint nécessite aussi GTK sur Windows : voir https://doc.courtbouillon.org/weasyprint)
    Alternative sans GTK : pip install fpdf2 --break-system-packages
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

LABEL = "Créer un PDF accessible (tagué, structuré, RGAA/WCAG)"

TEXT = """Quand utiliser ce bond : quand l'utilisateur veut produire un fichier PDF
qui soit réellement accessible — lisible par les lecteurs d'écran, avec une structure
sémantique (tags PDF), une langue déclarée, un ordre de lecture logique, des titres
hiérarchisés et des descriptions d'images. Répond aux exigences RGAA et WCAG 2.1 AA.

Stratégie : la meilleure façon de créer un PDF accessible en Python est de générer
d'abord un HTML sémantique propre, puis de le convertir en PDF via WeasyPrint
(qui produit des PDF avec structure de tags). C'est plus fiable que d'écrire
directement en PDF.

Prérequis (une seule fois) :
    pip install weasyprint --break-system-packages
    Sur Windows : installer aussi le runtime GTK3 (voir doc WeasyPrint)
    Alternative légère sans GTK : pip install fpdf2 --break-system-packages

Méthode — Voie principale (WeasyPrint depuis HTML) :

1. Construire le HTML accessible selon ce modèle :
   html = '''
   <!DOCTYPE html>
   <html lang="fr">
   <head>
     <meta charset="utf-8">
     <title>[TITRE DU DOCUMENT]</title>
     <style>
       body { font-family: Arial, sans-serif; font-size: 12pt;
              line-height: 1.6; color: #000; background: #fff; }
       h1 { font-size: 20pt; } h2 { font-size: 16pt; } h3 { font-size: 13pt; }
       img { max-width: 100%; }
       table { border-collapse: collapse; width: 100%; }
       th, td { border: 1px solid #000; padding: 4pt; }
       th { background: #eee; font-weight: bold; }
     </style>
   </head>
   <body>
     <h1>[Titre principal]</h1>
     <p>[Paragraphe introductif]</p>
     <h2>[Section 1]</h2>
     <p>[Contenu...]</p>
     <img src="image.png" alt="[Description textuelle complète de l'image]">
   </body>
   </html>
   '''

2. Règles HTML obligatoires pour l'accessibilité PDF :
   - lang="fr" sur la balise <html> (déclare la langue au lecteur d'écran)
   - <title> non vide (titre du document dans les métadonnées)
   - Titres hiérarchisés h1 > h2 > h3 sans sauter de niveau
   - Chaque <img> a un attribut alt non vide et descriptif
   - Les tableaux ont des <th> avec scope="col" ou scope="row"
   - Liens avec texte descriptif (pas "cliquez ici")
   - Contraste texte/fond >= 4.5:1 (noir sur blanc = parfait)

3. Convertir en PDF avec WeasyPrint :
   from weasyprint import HTML, CSS
   HTML(string=html_content).write_pdf(chemin_pdf)
   print(f"PDF accessible généré : {chemin_pdf}")

   Si WeasyPrint n'est pas disponible (GTK manquant sur Windows),
   utiliser fpdf2 comme alternative :
   from fpdf import FPDF
   pdf = FPDF()
   pdf.set_lang('fr')
   pdf.add_page()
   pdf.set_font('Helvetica', size=12)
   # Écrire le contenu manuellement section par section
   pdf.output(chemin_pdf)

4. Après génération, afficher un rapport de conformité :
   - Langue déclarée : oui/non
   - Nombre de titres h1/h2/h3
   - Images avec/sans alt text
   - Taille du fichier généré

Règles importantes :
- Toujours valider le HTML avant conversion (structure correcte).
- Ne jamais mettre de texte dans une image si ce texte porte de l'information
  essentielle — il doit aussi apparaître en texte dans le HTML.
- Pour les documents longs, générer une table des matières automatique
  en début de document avec liens internes (<a href="#section1">).
- Les PDF générés depuis Word ou LibreOffice sont souvent mieux tagués
  que ceux générés en Python pour des documents complexes :
  le signaler si le document est très long ou très mis en page.
"""

META = {
    "description": "Créer un PDF accessible avec tags de structure, langue déclarée, alt text et hiérarchie de titres (WCAG 2.1 AA).",
    "mots_cles": [
        "pdf", "accessible", "tagué", "structuré", "wcag", "rgaa",
        "lecteur écran", "tags pdf", "weasyprint", "fpdf", "créer",
        "générer", "document", "titre", "alt text", "conformité",
    ],
    "valide": True,
    "valide_par_laurent": True,
    "version": 1,
}


def main():
    existing = list_prompts("skill")
    for sid, sk in (existing.items() if isinstance(existing, dict) else {}):
        lbl = (sk.get("label") or "").lower()
        if "pdf" in lbl and "accessible" in lbl and "créer" in lbl:
            print(f"Bond similaire déjà présent (id={sid}) : {sk.get('label')}")
            return
    entry = save_prompt(None, LABEL, TEXT, type="skill", meta=META)
    if entry:
        print(f"Bond créé : {LABEL}")
    else:
        print("Erreur lors de la création.")


if __name__ == "__main__":
    main()
