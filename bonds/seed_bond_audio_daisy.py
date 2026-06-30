"""
seed_bond_audio_daisy.py — Bond "Synthèse vocale et export audio DAISY"

Prérequis :
    pip install edge-tts --break-system-packages
    (edge-tts utilise le service TTS de Microsoft Edge, gratuit, aucune clé API)
    Option Voxtral (Mistral) : clé API Mistral requise dans NIMM
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

LABEL = "Synthèse vocale et export audio DAISY (edge-tts / Voxtral Mistral)"

TEXT = """Quand utiliser ce bond : quand l'utilisateur veut convertir un texte ou
un document en audio — pour créer un livre audio, un enregistrement de document,
une version sonore d'un compte-rendu ou d'un article — en choisissant une voix
française de qualité. Produit des fichiers MP3 par chapitre, avec un index DAISY
simplifié pour naviguer entre les sections.

Moteurs disponibles :
A) edge-tts (recommandé, gratuit, haute qualité, pas de clé API)
   pip install edge-tts --break-system-packages
   Voix françaises disponibles : fr-FR-DeniseNeural (féminine, naturelle),
   fr-FR-HenriNeural (masculine, neutre), fr-FR-EloiseNeural (féminine, douce),
   fr-BE-GerardNeural (belge), fr-CH-ArianeNeural (suisse)

B) Voxtral / Mistral TTS (si disponible dans ton compte Mistral)
   Utilise la clé API Mistral déjà configurée dans NIMM.
   Vérifier la disponibilité : consulter https://docs.mistral.ai pour les
   endpoints TTS actifs. Si disponible, utiliser via l'API REST Mistral.

C) pyttsx3 (hors-ligne, voix système Windows/Linux, qualité moindre)
   pip install pyttsx3 --break-system-packages

Méthode — Voie principale avec edge-tts :

1. Recueillir le texte source :
   - Depuis un fichier texte : open(chemin, encoding='utf-8').read()
   - Depuis une saisie directe dans le message
   - Depuis un PDF (extraire d'abord avec pdfplumber)

2. Découper le texte en chapitres ou sections :
   - Détecter les titres (lignes en majuscules, lignes courtes seules, etc.)
   - Ou découper par paragraphes si pas de structure détectable
   - Nommer chaque section : "01_introduction", "02_chapitre1", etc.

3. Générer l'audio pour chaque section avec edge-tts :
   import asyncio, edge_tts
   VOIX = "fr-FR-DeniseNeural"  # modifier selon préférence

   async def synthetiser(texte, chemin_mp3, voix=VOIX):
       communicate = edge_tts.Communicate(texte, voix)
       await communicate.save(chemin_mp3)

   for i, (titre, texte_section) in enumerate(sections):
       nom = f"{i+1:02d}_{titre[:30].replace(' ','_')}.mp3"
       chemin = os.path.join(dossier_sortie, nom)
       asyncio.run(synthetiser(texte_section, chemin))
       print(f"Généré : {chemin}")

4. Créer un fichier index DAISY simplifié (XML) :
   index = ['<?xml version="1.0" encoding="utf-8"?>',
            '<daisy-index titre="[TITRE]" date="[DATE]">']
   for i, (titre, _) in enumerate(sections):
       nom = f"{i+1:02d}_{titre[:30].replace(' ','_')}.mp3"
       index.append(f'  <section ordre="{i+1}" titre="{titre}" fichier="{nom}"/>')
   index.append('</daisy-index>')
   with open(os.path.join(dossier_sortie, 'index.xml'), 'w', encoding='utf-8') as f:
       f.write('\\n'.join(index))

5. Afficher le résumé :
   print(f"Export audio DAISY terminé dans : {dossier_sortie}")
   print(f"Sections générées : {len(sections)}")
   print(f"Voix utilisée : {VOIX}")
   print("Fichiers : " + ", ".join(noms_fichiers))

Voix à proposer à l'utilisateur (demander avant génération) :
   1. fr-FR-DeniseNeural — française, féminine, voix naturelle (défaut)
   2. fr-FR-HenriNeural — française, masculine, ton neutre
   3. fr-FR-EloiseNeural — française, féminine, ton doux
   4. fr-BE-GerardNeural — belge, masculine
   5. fr-CH-ArianeNeural — suisse, féminine
   6. Voxtral Mistral — si disponible, demander à l'utilisateur

Règles importantes :
- edge-tts nécessite une connexion internet (service Microsoft Edge).
- Pour les textes très longs (> 5000 mots), traiter par blocs de 2000 mots
  pour éviter les timeouts du service TTS.
- Si le texte contient des abréviations, les développer avant synthèse
  (ex. "M." → "Monsieur", "etc." → "et cetera") pour une meilleure prononciation.
- Toujours créer le dossier de sortie s'il n'existe pas (os.makedirs).
- Signaler à l'utilisateur que les fichiers MP3 générés peuvent être lus
  dans NVDA, JAWS, ou tout lecteur audio compatible DAISY.
"""

META = {
    "description": "Convertir un texte en audio MP3 par chapitres avec index DAISY simplifié, via edge-tts (voix françaises naturelles) ou Voxtral Mistral.",
    "mots_cles": [
        "daisy", "audio", "synthèse vocale", "tts", "voix", "mp3",
        "livre audio", "edge-tts", "voxtral", "mistral", "parole",
        "écouter", "sonore", "enregistrement", "accessibilité", "nvda",
        "fr-FR-DeniseNeural", "fr-FR-HenriNeural",
    ],
    "valide": True,
    "valide_par_laurent": True,
    "version": 1,
}


def main():
    existing = list_prompts("skill")
    for sid, sk in (existing.items() if isinstance(existing, dict) else {}):
        lbl = (sk.get("label") or "").lower()
        if "daisy" in lbl or ("audio" in lbl and "voix" in lbl):
            print(f"Bond similaire déjà présent (id={sid}) : {sk.get('label')}")
            return
    entry = save_prompt(None, LABEL, TEXT, type="skill", meta=META)
    if entry:
        print(f"Bond créé : {LABEL}")
    else:
        print("Erreur lors de la création.")


if __name__ == "__main__":
    main()
