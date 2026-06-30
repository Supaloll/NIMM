"""
seed_bond_resume_doc.py — Bond "Résumé accessible d'un document"

Prérequis :
    pip install pdfplumber python-docx --break-system-packages
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

LABEL = "Résumé accessible d'un document (PDF, DOCX, TXT)"

TEXT = """Quand utiliser ce bond : quand l'utilisateur veut résumer, synthétiser ou extraire
les idées principales d'un fichier document (PDF, Word .docx, ou texte brut).
Le résumé produit doit être lisible sur plage braille : sans markdown, sans astérisques,
sans titres avec dièse, en phrases courtes et paragraphes séparés par une ligne vide.

Prérequis à vérifier (une seule fois) :
    pip install pdfplumber python-docx --break-system-packages

Méthode :

1. Demander le chemin complet du fichier si l'utilisateur ne l'a pas fourni.
   Exemples valides : C:/Documents/rapport.pdf, /home/user/note.txt

2. Détecter le type de fichier par son extension (.pdf, .docx, .txt, .md, .html).

3. Extraire le texte brut selon le type :
   - PDF : utiliser pdfplumber
     import pdfplumber
     with pdfplumber.open(chemin) as pdf:
         texte = "\\n\\n".join(p.extract_text() or "" for p in pdf.pages)
   - DOCX : utiliser python-docx
     from docx import Document
     doc = Document(chemin)
     texte = "\\n".join(p.text for p in doc.paragraphs if p.text.strip())
   - TXT / MD / HTML : open(chemin, encoding='utf-8').read()
     Pour HTML : retirer les balises avec re.sub('<[^>]+>', '', html)

4. Si le texte dépasse 6000 caractères, ne garder que les 3000 premiers et les
   1500 derniers, en signalant que le document a été tronqué pour le résumé.

5. Afficher le texte extrait avec le préfixe :
   print("TEXTE_EXTRAIT:", texte[:5000])
   Puis afficher la consigne de résumé :
   print("CONSIGNE: Résume ce texte en français, en phrases courtes, sans markdown,
   adapté à une lecture sur plage braille.")

6. CoaNIMM lit la sortie et produit le résumé dans sa réponse, en respectant :
   - Pas d'astérisques, pas de tirets en début de ligne, pas de titres avec #
   - Paragraphes séparés par une ligne vide
   - Longueur cible : 150 à 300 mots selon la complexité du document

Règles importantes :
- Ne jamais inventer du contenu : résumer uniquement ce qui est dans le texte extrait.
- Si le fichier est protégé ou illisible, le signaler clairement.
- Si la langue du document n'est pas le français, le mentionner avant le résumé.
- Pour les PDF numérisés (images), signaler que l'OCR n'est pas disponible et que
  le texte ne peut pas être extrait directement.
"""

META = {
    "description": "Lire et résumer un document (PDF, DOCX, TXT) en texte brut accessible, sans markdown.",
    "mots_cles": [
        "résumé", "résumer", "synthèse", "document", "pdf", "docx", "word",
        "texte", "lire", "extraire", "fiche", "note", "rapport", "fichier",
        "synthétiser", "condensé", "braille", "accessible",
    ],
    "valide": True,
    "valide_par_laurent": True,
    "version": 1,
}


def main():
    existing = list_prompts("skill")
    for sid, sk in (existing.items() if isinstance(existing, dict) else {}):
        lbl = (sk.get("label") or "").lower()
        if "résumé" in lbl and "document" in lbl:
            print(f"Bond similaire déjà présent (id={sid}) : {sk.get('label')}")
            return
    entry = save_prompt(None, LABEL, TEXT, type="skill", meta=META)
    if entry:
        print(f"Bond créé : {LABEL}")
    else:
        print("Erreur lors de la création.")


if __name__ == "__main__":
    main()
