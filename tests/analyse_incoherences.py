# -*- coding: utf-8 -*-
import sys
import sqlite3
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/nimm_laurent.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("SELECT key, type, sujet, predicat, objet, valeur, confiance, timestamp FROM memory")
rows = cur.fetchall()

# --- Construire un index: sujet -> [(predicat, objet, confiance, type)] ---
from collections import defaultdict
index = defaultdict(list)
for r in rows:
    sujet = (r['sujet'] or '').strip()
    predicat = (r['predicat'] or '').strip()
    objet = (r['objet'] or '').strip()
    index[sujet].append((predicat, objet, r['confiance'], r['type']))

print("=" * 70)
print("ANALYSE DES INCOHERENCES - BASE nimm_laurent.db")
print("=" * 70)

# --- 1. Relations familiales de Laurent ---
print("\n[1] RELATIONS FAMILIALES DECLAREES")
print("-" * 70)
for predicat, objet, conf, typ in index.get('Laurent', []):
    if predicat in ('enfant', 'conjoint', 'parent', 'mere', 'maman', 'compte_joint', 'famille', 'relation_sociale', 'prenom_mere'):
        print(f"  Laurent | {predicat} | {objet} | conf={conf}")

print("\n  -> Enfants declares de Laurent:", [o for p, o, c, t in index.get('Laurent', []) if p == 'enfant'])
print("  -> Conjoints declares de Laurent:", [o for p, o, c, t in index.get('Laurent', []) if p == 'conjoint'])

# --- 2. Relation inverse : qui declare Laurent comme parent / conjoint ---
print("\n[2] QUI DECLARE LAURENT COMME PARENT / CONJOINT")
print("-" * 70)
for sujet, triples in index.items():
    for predicat, objet, conf, typ in triples:
        if objet == 'Laurent' and predicat in ('parent', 'conjoint', 'enfant', 'enfant_de', 'mere', 'prenom_mere'):
            print(f"  {sujet} | {predicat} | {objet} | conf={conf}")

# --- 3. Detection des contradictions conjoint vs enfant ---
print("\n[3] CONTRADICTIONS CONJOINT vs ENFANT")
print("-" * 70)
conjoints_laurent = set(o for p, o, c, t in index.get('Laurent', []) if p == 'conjoint')
enfants_laurent = set(o for p, o, c, t in index.get('Laurent', []) if p == 'enfant')

print(f"  Conjoints de Laurent : {conjoints_laurent}")
print(f"  Enfants de Laurent   : {enfants_laurent}")

# Verifier si un conjoint est aussi un enfant (ou vice-versa)
for c in conjoints_laurent:
    for e in enfants_laurent:
        # Normaliser les noms (retirer espaces, comparer en minuscule)
        c_norm = c.lower().replace(' ', '')
        e_norm = e.lower().replace(' ', '')
        if c in e or e in c or c_norm == e_norm or c_norm in e_norm or e_norm in c_norm:
            print(f"  !! CONTRADICTION : '{c}' est declare conjoint de Laurent MAIS '{e}' est declare enfant de Laurent")
            # Chercher les triplets exacts
            for p, o, conf, typ in index.get('Laurent', []):
                if p == 'conjoint' and o == c:
                    print(f"     -> Laurent | conjoint | {o} | conf={conf}")
            for p, o, conf, typ in index.get('Laurent', []):
                if p == 'enfant' and o == e:
                    print(f"     -> Laurent | enfant | {o} | conf={conf}")
            # Chercher les triplets inverses
            for sujet, triples in index.items():
                for p, o, conf, typ in triples:
                    if o == 'Laurent' and p in ('conjoint', 'parent', 'enfant_de', 'enfant'):
                        print(f"     -> {sujet} | {p} | {o} | conf={conf}")

# --- 4. Entites dupliquees (Maissane vs Maissane KHALLAH) ---
print("\n[4] ENTITES DUPLIQUEES / FUSION MANQUANTE")
print("-" * 70)
for sujet, triples in sorted(index.items()):
    # Chercher des sujets qui pourraient etre la meme personne
    pass

# Verifier specifiquement Maissane et Maissane KHALLAH
for nom in ['Maissane', 'Maissane KHALLAH']:
    if nom in index:
        print(f"  Entite: '{nom}'")
        for p, o, conf, typ in index[nom]:
            print(f"    {p} | {o} | conf={conf} | {typ}")

# --- 5. Autres anomalies ---
print("\n[5] AUTRES ANOMALIES")
print("-" * 70)

# a) Predicat 'vehicule' avec un document PDF
for p, o, conf, typ in index.get('Laurent', []):
    if p == 'vehicule':
        print(f"  !! 'vehicule' contient un document PDF: Laurent | vehicule | {o}")

# b) 'probleme_sante' sur des sujets non-humains
for sujet, triples in index.items():
    for p, o, conf, typ in triples:
        if p == 'probleme_sante' and sujet not in ('Laurent', 'Maissane', 'Maya', 'Innes', 'Nadia', 'Dr Jean-Luc Baumgart'):
            print(f"  !! 'probleme_sante' applique a '{sujet}' (non-humain?) : {sujet} | {p} | {o}")

# c) Triplets vides de sens
for sujet, triples in index.items():
    for p, o, conf, typ in triples:
        if o == p:
            print(f"  !! Triplet tautologique: {sujet} | {p} | {o}")

# d) 'relation_sociale' attribuee a Laurent mais concernant Maya
for p, o, conf, typ in index.get('Laurent', []):
    if p == 'relation_sociale' and 'Maya' in o:
        print(f"  !! Relation sociale de Maya attribuee a Laurent: Laurent | {p} | {o}")

# e) 'maman' et 'mere' - deux entrees pour la meme relation
meres = [o for p, o, c, t in index.get('Laurent', []) if p in ('mere', 'parent', 'maman', 'prenom_mere')]
print(f"\n  Entrees 'mere/parent/maman' pour Laurent: {meres}")

# f) References a 'maman' comme sujet separe
if 'maman' in index:
    print(f"\n  Entite 'maman' separee:")
    for p, o, conf, typ in index['maman']:
        print(f"    maman | {p} | {o} | conf={conf}")

# g) Check date naissance Laurent sans annee
for p, o, conf, typ in index.get('Laurent', []):
    if p == 'date_naissance':
        print(f"\n  Date naissance Laurent: '{o}' (pas d'annee) | age declare: ", end='')
        for p2, o2, c2, t2 in index.get('Laurent', []):
            if p2 == 'age':
                print(f"{o2}")

# h) References 'camion' vs 'camion de Laurent'
camions = [s for s in index if 'camion' in s.lower()]
print(f"\n  Entites 'camion': {camions}")

# i) Filles
if 'filles' in index:
    print(f"\n  Entite 'filles' (groupe):")
    for p, o, conf, typ in index['filles']:
        print(f"    filles | {p} | {o} | conf={conf}")

# j) 'famille' tautologique
if 'famille' in index:
    print(f"\n  Entite 'famille':")
    for p, o, conf, typ in index['famille']:
        print(f"    famille | {p} | {o} | conf={conf}")

conn.close()