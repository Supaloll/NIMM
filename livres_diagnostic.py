"""
Diagnostic : affiche la structure des 10 premiers dossiers à traiter
et le contenu de leurs fichiers .txt
Lancer : python livres_diagnostic.py
"""
import os, re

BOOKS_DIR = r"e:\fernando\téléchargements\livres"

# Dossiers à traiter : contiennent un point suivi d'initiales, puis " - "
def est_a_traiter(nom):
    return bool(re.match(r'^[^.]+\.[A-Z]', nom, re.IGNORECASE)) and ' - ' in nom

def trouver_txt(dossier):
    """Cherche un .txt dans le dossier et ses sous-dossiers immédiats."""
    for f in os.listdir(dossier):
        if f.lower().endswith('.txt'):
            return os.path.join(dossier, f)
    for item in os.listdir(dossier):
        sub = os.path.join(dossier, item)
        if os.path.isdir(sub):
            for f in os.listdir(sub):
                if f.lower().endswith('.txt'):
                    return os.path.join(sub, f)
    return None

def lire_txt(chemin):
    for enc in ['utf-8', 'latin-1', 'cp1252']:
        try:
            return open(chemin, encoding=enc).read()
        except Exception:
            continue
    return "(impossible à lire)"

print(f"Dossier : {BOOKS_DIR}\n")
try:
    items = sorted(os.listdir(BOOKS_DIR))
except Exception as e:
    print(f"ERREUR : {e}"); exit(1)

dossiers = [i for i in items if os.path.isdir(os.path.join(BOOKS_DIR, i))]
a_traiter = [d for d in dossiers if est_a_traiter(d)]
deja_classes = [d for d in dossiers if not est_a_traiter(d)]

print(f"Total dossiers : {len(dossiers)}")
print(f"Déjà classés   : {len(deja_classes)}")
print(f"À traiter      : {len(a_traiter)}")
print()

print("=" * 60)
print("CONTENU DES 10 PREMIERS DOSSIERS À TRAITER")
print("=" * 60)

for nom in a_traiter[:10]:
    chemin = os.path.join(BOOKS_DIR, nom)
    print(f"\nDOSSIER : {nom}")

    # Contenu du premier niveau
    try:
        contenu = os.listdir(chemin)
        sous_dossiers = [x for x in contenu if os.path.isdir(os.path.join(chemin, x))]
        fichiers = [x for x in contenu if not os.path.isdir(os.path.join(chemin, x))]
        print(f"  Sous-dossiers : {sous_dossiers}")
        print(f"  Fichiers directs : {fichiers}")
    except Exception as e:
        print(f"  ERREUR lecture : {e}")
        continue

    # Fichier .txt
    txt = trouver_txt(chemin)
    if txt:
        print(f"  Fichier .txt : {os.path.relpath(txt, chemin)}")
        contenu_txt = lire_txt(txt)
        # Afficher les 20 premières lignes non vides
        lignes = [l.strip() for l in contenu_txt.splitlines() if l.strip()][:20]
        for l in lignes:
            print(f"    | {l}")
    else:
        print("  Fichier .txt : AUCUN TROUVÉ")

print("\n" + "=" * 60)
print("5 EXEMPLES DE DOSSIERS DÉJÀ CLASSÉS :")
for nom in deja_classes[:5]:
    print(f"  {nom}")
