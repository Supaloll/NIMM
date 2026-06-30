"""
seed_bond_alttext_image.py — Bond "Description accessible d'image par IA (alt text)"

Pas de dépendance externe (utilise le LLM multimodal déjà dans NIMM).
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

LABEL = "Description accessible d'image par IA (génération d'alt text)"

TEXT = """Quand utiliser ce bond : quand l'utilisateur a une ou plusieurs images
(photo, graphique, schéma, capture d'écran, carte, infographie) et a besoin d'une
description textuelle précise pour l'accessibilité — un alt text court, une
longdesc détaillée, ou les deux. Utilise le LLM multimodal du fil courant
(Gemini ou Claude, qui savent analyser des images).

Ce bond ne génère pas de code Python : il guide CoaNIMM pour préparer et
envoyer l'image au LLM et formater la réponse.

Prérequis :
- Le fil doit utiliser un modèle multimodal : Gemini (recommandé), Claude,
  ou GPT-4V. Si le fil est configuré avec un modèle texte seul (Mistral,
  DeepSeek), demander à l'utilisateur de changer de fournisseur.

Méthode :

1. Demander à l'utilisateur :
   - Le chemin ou l'URL de l'image (ou qu'il la joigne directement au message)
   - Le contexte d'utilisation (dans une présentation ? un site web ? un document ?)
   - S'il faut un alt text court (< 125 caractères) ou une description longue

2. Si l'image est un fichier local, la lire en base64 pour transmission :
   import base64
   with open(chemin_image, 'rb') as f:
       b64 = base64.b64encode(f.read()).decode('utf-8')
   print(f"IMAGE_BASE64:{b64}")
   print(f"TYPE:{chemin_image.rsplit('.',1)[-1].lower()}")
   — CoaNIMM transmet ensuite l'image au LLM dans son prochain message.

3. Consigne à donner au LLM multimodal pour chaque image :
   "Décris cette image pour une personne non-voyante. Produis :
   1. ALT TEXT (max 125 caractères) : description concise du sujet principal,
      sans commencer par 'Image de' ou 'Photo de'.
   2. DESCRIPTION LONGUE (3 à 6 phrases) : décris de gauche à droite et de
      haut en bas. Mentionne les couleurs principales, les textes visibles,
      les relations spatiales entre les éléments, le contexte général.
   3. TYPE : photo / graphique / schéma / capture d'écran / carte / infographie
   4. DÉCORATIVE : oui/non (si oui, alt='' est recommandé)"

4. Pour les graphiques et infographies, demander en plus :
   "Résume les données clés du graphique en une ou deux phrases,
   comme si tu l'expliquais oralement à quelqu'un qui ne le voit pas."

5. Pour un lot d'images (plusieurs fichiers dans un dossier) :
   import os, glob
   images = glob.glob(os.path.join(dossier, '*.png'))
   images += glob.glob(os.path.join(dossier, '*.jpg'))
   — Traiter une par une et produire un fichier alttext_[nom].txt par image.

6. Formater la sortie pour intégration directe :
   - Pour HTML : <img src="..." alt="[ALT TEXT]">
   - Pour PPTX : attribut 'descr' de la shape (voir bond PowerPoint accessible)
   - Pour EPUB : attribut alt de la balise <img>
   - Pour Word : propriété alt text de l'image (via python-docx)

Règles de qualité pour un bon alt text :
- Ne pas commencer par "Image de", "Photo de", "Illustration montrant"
  (le lecteur d'écran dit déjà "image" avant de lire l'alt).
- Être précis sur les personnes visibles (sans identifier si non publiques),
  les textes visibles dans l'image, les actions représentées.
- Pour les graphiques : indiquer le type (barres, courbes, camembert),
  la tendance principale, les valeurs extrêmes.
- Pour les captures d'écran : décrire l'interface et ce qui est mis en valeur.
- alt="" uniquement si l'image est purement décorative (aucune info).

Règles importantes :
- Modèles multimodaux recommandés dans NIMM : Gemini 2.0 Flash ou Pro,
  Claude Sonnet ou Opus (vision activée).
- Mistral, DeepSeek et les modèles texte seul ne peuvent pas traiter les images.
- Pour les images contenant des données personnelles (visages, documents d'identité),
  demander confirmation avant traitement.
"""

META = {
    "description": "Générer automatiquement un alt text et une description longue pour une image, via le LLM multimodal (Gemini, Claude).",
    "mots_cles": [
        "alt text", "description", "image", "photo", "accessible", "accessibilité",
        "graphique", "infographie", "schéma", "capture écran", "longdesc",
        "multimodal", "gemini", "claude", "vision", "non-voyant", "braille",
    ],
    "valide": True,
    "valide_par_laurent": True,
    "version": 1,
}


def main():
    existing = list_prompts("skill")
    for sid, sk in (existing.items() if isinstance(existing, dict) else {}):
        lbl = (sk.get("label") or "").lower()
        if "alt text" in lbl or ("image" in lbl and "description" in lbl):
            print(f"Bond similaire déjà présent (id={sid}) : {sk.get('label')}")
            return
    entry = save_prompt(None, LABEL, TEXT, type="skill", meta=META)
    if entry:
        print(f"Bond créé : {LABEL}")
    else:
        print("Erreur lors de la création.")


if __name__ == "__main__":
    main()
