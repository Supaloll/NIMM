# -*- coding: utf-8 -*-
import sys
import sqlite3
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')

DB = 'data/nimm_laurent.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("RESTAURATION DES RELATIONS PERE-FILLE (convention NIMM)")
print("=" * 70)

# Les triplets supprimes etaient CORRECTS selon la convention NIMM :
#   sujet | predicat | objet  =  "sujet A POUR predicat objet"
#   Laurent | enfant | Maissane  =  "Laurent A POUR enfant Maissane"  (correct)
#   Maissane | parent | Laurent  =  "Maissane A POUR parent Laurent"  (correct)
# Ces deux formes sont les reciproques de la MEME relation pere-fille.

# --- Recuperer les colonnes de la table memory pour inserer correctement ---
cur.execute('PRAGMA table_info(memory)')
cols = [r[1] for r in cur.fetchall()]
print('Colonnes:', cols)

# --- Verifier si les cles existent deja ---
for key in ('mem_56c05cbf', 'inf_52bbb3fe'):
    cur.execute("SELECT COUNT(*) FROM memory WHERE key=?", (key,))
    n = cur.fetchone()[0]
    print(f"CLE {key}: {'existe deja' if n else 'libre'}")

# --- Reinserer les deux triplets ---
# Valeurs d'origine (reconstructibles depuis le dump initial)
restaurations = [
    {
        'key': 'mem_56c05cbf',
        'type': 'relation',
        'sujet': 'Laurent',
        'predicat': 'enfant',
        'objet': 'Maïssane',
        'valeur': 'Maïssane',
        'confiance': 0.9,
        'valence': None,
        'sensibilite': 'normal',
        'cumulatif': 0,
        'categorie': 'famille',
        'profondeur': 1,
        'type_temporal': 'permanent',
        'expiration': None,
        'timestamp': '2026-07-24T17:46:28.806445',
        'repetitions': 0,
        'poids': 0.9,
        'embedding': None,
        'memoire_type': 'identite',
        'last_reinforced': '2026-07-24T17:46:28.806445',
        'contexte': '',
        'registre': 'defaut',
    },
    {
        'key': 'inf_52bbb3fe',
        'type': 'relation',
        'sujet': 'Maïssane',
        'predicat': 'parent',
        'objet': 'Laurent',
        'valeur': 'Laurent',
        'confiance': 0.77,
        'valence': None,
        'sensibilite': 'normal',
        'cumulatif': 0,
        'categorie': 'famille',
        'profondeur': 1,
        'type_temporal': 'permanent',
        'expiration': None,
        'timestamp': '2026-07-02T21:24:22.984769',
        'repetitions': 0,
        'poids': 0.77,
        'embedding': None,
        'memoire_type': 'identite',
        'last_reinforced': '2026-07-02T21:24:22.984769',
        'contexte': '',
        'registre': 'defaut',
    },
]

for rec in restaurations:
    key = rec['key']
    cur.execute("SELECT COUNT(*) FROM memory WHERE key=?", (key,))
    if cur.fetchone()[0] > 0:
        print(f"SKIP {key} (deja present)")
        continue
    # Construire la requete INSERT dynamiquement
    colonnes = list(rec.keys())
    placeholders = ','.join(['?'] * len(colonnes))
    sql = f"INSERT INTO memory ({','.join(colonnes)}) VALUES ({placeholders})"
    cur.execute(sql, [rec[c] for c in colonnes])
    print(f"RESTAURE {key} | {rec['sujet']} | {rec['predicat']} | {rec['objet']} | conf={rec['confiance']}")

conn.commit()

# --- Verification ---
print("\nVERIFICATION RELATIONS MAISSANE:")
cur.execute("""SELECT key, sujet, predicat, objet, confiance FROM memory
            WHERE (sujet='Laurent' AND predicat='enfant' AND objet='Maïssane')
               OR (sujet='Maïssane' AND predicat='parent' AND objet='Laurent')
               OR (sujet='Maïssane' AND predicat='enfant_de' AND objet='Laurent')""")
for r in cur.fetchall():
    print(f"  {r['key']} | {r['sujet']} | {r['predicat']} | {r['objet']} | conf={r['confiance']}")

# Verifier que la FTS est coherente
print("\nVERIFICATION FTS (index de recherche):")
cur.execute("""SELECT m.key, m.sujet, m.predicat, m.objet, f.texte
            FROM memory m LEFT JOIN memory_fts f ON f.key = m.key
            WHERE m.key IN ('mem_56c05cbf', 'inf_52bbb3fe')""")
for r in cur.fetchall():
    print(f"  {r['key']} | FTS texte: '{r['texte']}'")

conn.close()
print("\nOK: restauration terminee")