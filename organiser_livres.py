# -*- coding: utf-8 -*-
"""
Organisateur de livres audio — e:\fernando\téléchargements\livres
Lancer : python organiser_livres.py
Affiche le plan complet, puis demande une confirmation avant d'agir.
"""
import os, re, shutil, unicodedata, sys

BOOKS_DIR = r"e:\fernando\téléchargements\livres"

# ─── Utilitaires ────────────────────────────────────────────────────────────

def sans_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn').lower()

def lire_txt(chemin):
    for enc in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252'):
        try:
            return open(chemin, encoding=enc, errors='replace').read()
        except Exception:
            continue
    return ''

def trouver_txt(dossier):
    """Cherche un .txt dans le dossier lui-même, puis dans ses sous-dossiers."""
    for f in sorted(os.listdir(dossier)):
        if f.lower().endswith('.txt'):
            return os.path.join(dossier, f)
    for item in sorted(os.listdir(dossier)):
        sub = os.path.join(dossier, item)
        if os.path.isdir(sub):
            for f in sorted(os.listdir(sub)):
                if f.lower().endswith('.txt'):
                    return os.path.join(sub, f)
    return None

def extraire_auteur(contenu, nom_attendu):
    """
    Extrait le ou les auteurs depuis le contenu du .txt.
    Essaie plusieurs formats. Retourne (prenom, nom) ou (None, None).
    """
    # Normaliser le nom attendu pour comparaison
    nom_norm = sans_accents(nom_attendu.split('.')[0])

    patterns_auteur = [
        r'[Aa]uteurs?\s*[:\-]\s*(.+)',
        r'[Aa]uthor\s*[:\-]\s*(.+)',
        r'[Éé]crit\s+par\s*[:\-]?\s*(.+)',
        r'[Pp]ar\s*[:\-]\s*(.+)',
        r'[Ww]ritten\s+by\s*[:\-]\s*(.+)',
    ]

    candidats = []
    for ligne in contenu.splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        for pat in patterns_auteur:
            m = re.match(pat, ligne)
            if m:
                candidats.append(m.group(1).strip())
                break

    # Si aucun pattern ne correspond, essayer les premières lignes non vides
    if not candidats:
        lignes_nv = [l.strip() for l in contenu.splitlines() if l.strip()][:5]
        candidats = lignes_nv

    # Choisir le meilleur candidat : celui dont le nom correspond à nom_attendu
    for c in candidats:
        # Nettoyer les parenthèses, points etc.
        c_propre = re.sub(r'\s*\(.*?\)', '', c).strip()
        # Peut contenir "Prénom NOM" ou "NOM Prénom" ou "NOM, Prénom"
        if sans_accents(c_propre.split()[0] if c_propre.split() else '') == nom_norm or \
           any(sans_accents(mot) == nom_norm for mot in c_propre.split()):
            return c_propre
    # Fallback : premier candidat
    return candidats[0] if candidats else None

def normaliser_nom_auteur(auteur_brut):
    """
    Transforme 'DUPONT Jean' ou 'Jean DUPONT' ou 'DUPONT, Jean'
    en 'Dupont Jean' (Nom Prénom avec majuscules normales).
    """
    if not auteur_brut:
        return None
    # Supprimer virgule
    auteur_brut = auteur_brut.replace(',', ' ').strip()
    mots = auteur_brut.split()
    if not mots:
        return None
    # Heuristique : si le premier mot est tout en majuscules → NOM Prénom
    if mots[0].isupper() and len(mots) >= 2:
        nom = mots[0].capitalize()
        prenom = ' '.join(m.capitalize() for m in mots[1:])
        return f"{nom} {prenom}"
    # Sinon capitaliser chaque mot
    return ' '.join(m.capitalize() for m in mots)

def est_a_traiter(nom):
    """Vrai si le dossier est de la forme AUTEUR.I - Titre."""
    return bool(re.match(r'^[A-Za-zÀ-ÿ_]+\.[A-Z]', nom)) and ' - ' in nom

def parse_dossier(nom):
    """Découpe 'AUTEUR.I - Titre' en (partie_auteur, titre_brut)."""
    idx = nom.find(' - ')
    if idx < 0:
        return nom, nom
    return nom[:idx].strip(), nom[idx+3:].strip()

SERIE_PATTERNS = [
    r'^(.+?)\s*[-–]\s*[Tt]ome\s*(\d+)',
    r'^(.+?)\s*[Tt]ome\s*(\d+)',
    r'^(.+?)\s*[-–]\s*[Vv]olume\s*(\d+)',
    r'^(.+?)\s*[-–]\s*[Vv]ol\.?\s*(\d+)',
    r'^(.+?)\s*[-–]\s*T(\d+)\b',
    r'^(.+?)\s*[-–]\s*[Ll]ivre\s*(\d+)',
    r'^(.+?)\s*[-–]\s*[Pp]artie\s*(\d+)',
    r'^(.+?)\s*[-–]\s*[Éé]pisode\s*(\d+)',
]

def detecter_serie(titre):
    """Retourne (nom_serie, numero) ou (None, None)."""
    for pat in SERIE_PATTERNS:
        m = re.match(pat, titre, re.IGNORECASE)
        if m:
            return m.group(1).strip(), int(m.group(2))
    return None, None

def nettoyer_nom(nom):
    """Supprime les caractères invalides pour un nom de dossier Windows."""
    return re.sub(r'[<>:"/\\|?*]', '-', nom).strip().strip('.')

# ─── Scan ───────────────────────────────────────────────────────────────────

print(f"\nDossier source : {BOOKS_DIR}\n")

try:
    tous = sorted(os.listdir(BOOKS_DIR))
except Exception as e:
    print(f"ERREUR : impossible d'accéder au dossier : {e}")
    sys.exit(1)

dossiers = [d for d in tous if os.path.isdir(os.path.join(BOOKS_DIR, d))]
a_traiter = [d for d in dossiers if est_a_traiter(d)]
deja_classes = [d for d in dossiers if not est_a_traiter(d)]

print(f"Dossiers trouvés     : {len(dossiers)}")
print(f"Déjà classés (ignorés) : {len(deja_classes)}")
print(f"À traiter            : {len(a_traiter)}")
print()

# ─── Construction du plan ───────────────────────────────────────────────────

plan = []   # liste de dicts
erreurs = []

for nom_dossier in a_traiter:
    chemin_src = os.path.join(BOOKS_DIR, nom_dossier)
    partie_auteur, titre_brut = parse_dossier(nom_dossier)

    # Chercher le .txt
    txt_path = trouver_txt(chemin_src)
    auteur_final = None

    if txt_path:
        contenu = lire_txt(txt_path)
        auteur_brut = extraire_auteur(contenu, partie_auteur)
        auteur_final = normaliser_nom_auteur(auteur_brut)

    if not auteur_final:
        # Fallback : utiliser la partie auteur du nom de dossier
        nom_seul = partie_auteur.split('.')[0].capitalize()
        auteur_final = nom_seul  # sans prénom
        erreurs.append(f"  ⚠  Prénom introuvable pour '{nom_dossier}' → utilisera '{auteur_final}' (sans prénom)")

    auteur_final = nettoyer_nom(auteur_final)
    titre_propre = nettoyer_nom(titre_brut)

    # Détecter série
    nom_serie, num_tome = detecter_serie(titre_propre)

    # Construire le chemin cible
    dossier_auteur = os.path.join(BOOKS_DIR, auteur_final)
    if nom_serie:
        dossier_cible = os.path.join(dossier_auteur, nettoyer_nom(nom_serie),
                                     f"Tome {num_tome:02d}")
    else:
        dossier_cible = os.path.join(dossier_auteur, titre_propre)

    # Trouver le sous-dossier contenant réellement les fichiers audio
    # (dans certains cas c'est le dossier lui-même, dans d'autres un sous-dossier)
    sous_dossiers = [x for x in os.listdir(chemin_src)
                     if os.path.isdir(os.path.join(chemin_src, x))]
    mp3s_directs = [x for x in os.listdir(chemin_src) if x.lower().endswith('.mp3')]

    if mp3s_directs:
        # Les mp3 sont directement dans le dossier source
        source_fichiers = chemin_src
        mode = 'dossier_direct'
    elif len(sous_dossiers) == 1:
        # Un seul sous-dossier → c'est lui qui contient les fichiers
        source_fichiers = os.path.join(chemin_src, sous_dossiers[0])
        mode = 'sous_dossier'
    else:
        # Plusieurs sous-dossiers ou aucun — déplacer tout le dossier
        source_fichiers = chemin_src
        mode = 'dossier_direct'

    plan.append({
        'nom_src'      : nom_dossier,
        'chemin_src'   : chemin_src,
        'source_fichiers': source_fichiers,
        'mode'         : mode,
        'auteur'       : auteur_final,
        'titre'        : titre_propre,
        'serie'        : nom_serie,
        'num_tome'     : num_tome,
        'dossier_cible': dossier_cible,
    })

# ─── Affichage du plan ──────────────────────────────────────────────────────

print("=" * 70)
print("PLAN DE RÉORGANISATION")
print("=" * 70)

for i, p in enumerate(plan, 1):
    src_rel = p['nom_src']
    cible_rel = os.path.relpath(p['dossier_cible'], BOOKS_DIR)
    serie_info = f" [série : {p['serie']}, tome {p['num_tome']}]" if p['serie'] else ""
    print(f"\n{i:3}. {src_rel}")
    print(f"     → {cible_rel}{serie_info}")

if erreurs:
    print("\nAVERTISSEMENTS (prénom non trouvé) :")
    for e in erreurs:
        print(e)

# Regroupements détectés
auteurs_groupes = {}
for p in plan:
    auteurs_groupes.setdefault(p['auteur'], []).append(p['titre'])
regroupements = {a: livres for a, livres in auteurs_groupes.items() if len(livres) > 1}
if regroupements:
    print(f"\nREGROUPEMENTS ({len(regroupements)} auteur(s) avec plusieurs livres) :")
    for auteur, livres in sorted(regroupements.items()):
        print(f"  {auteur} : {len(livres)} livres")

print(f"\n{len(plan)} dossier(s) à traiter.")

# ─── Confirmation ───────────────────────────────────────────────────────────


# ─── Exécution ──────────────────────────────────────────────────────────────

print("\nExécution en cours…\n")
ok = 0
echecs = []

for p in plan:
    try:
        cible = p['dossier_cible']
        os.makedirs(cible, exist_ok=True)

        src = p['source_fichiers']

        if p['mode'] == 'sous_dossier':
            # Déplacer le contenu du sous-dossier dans la cible
            for item in os.listdir(src):
                item_src = os.path.join(src, item)
                item_dst = os.path.join(cible, item)
                if os.path.exists(item_dst):
                    item_dst = os.path.join(cible, f"_doublon_{item}")
                shutil.move(item_src, item_dst)
            # Supprimer le dossier source devenu vide (si possible)
            try:
                shutil.rmtree(p['chemin_src'])
            except Exception:
                pass
        else:
            # Déplacer tout le dossier source vers la cible
            for item in os.listdir(src):
                item_src = os.path.join(src, item)
                item_dst = os.path.join(cible, item)
                if os.path.exists(item_dst):
                    item_dst = os.path.join(cible, f"_doublon_{item}")
                shutil.move(item_src, item_dst)
            try:
                shutil.rmtree(p['chemin_src'])
            except Exception:
                pass

        print(f"  ✓ {p['nom_src']}")
        print(f"    → {os.path.relpath(cible, BOOKS_DIR)}")
        ok += 1

    except Exception as e:
        print(f"  ✗ ERREUR sur '{p['nom_src']}' : {e}")
        echecs.append((p['nom_src'], str(e)))

print(f"\n{'='*70}")
print(f"Terminé : {ok} déplacé(s), {len(echecs)} erreur(s).")
if echecs:
    print("Erreurs :")
    for nom, err in echecs:
        print(f"  {nom} : {err}")
