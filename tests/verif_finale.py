# -*- coding: utf-8 -*-
import sys
import sqlite3
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/nimm_laurent.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("VERIFICATION FINALE - ETAT APRES CORRECTION")
print("=" * 70)

# 1. Doublons camion
print("\n[1] SOUVENIRS CAMION")
cur.execute("SELECT key, sujet, predicat, objet FROM memory WHERE sujet='camion de Laurent' ORDER BY key")
for r in cur.fetchall():
    print(f"  {r['key']} | {r['sujet']} | {r['predicat']} | {r['objet']}")

# 2. Tous les probleme_sante (verifier si certains ne sont pas des problemes de sante)
print("\n[2] TOUS LES 'probleme_sante'")
cur.execute("SELECT key, sujet, predicat, objet FROM memory WHERE predicat='probleme_sante' ORDER BY sujet")
for r in cur.fetchall():
    print(f"  {r['key']} | {r['sujet']} | {r['predicat']} | {r['objet']}")

# 3. Relations familiales restantes (verifier coherence)
print("\n[3] RELATIONS FAMILIALES (coherence bidirectionnelle)")
cur.execute("""SELECT sujet, predicat, objet, confiance FROM memory 
            WHERE (predicat IN ('parent','mere','enfant','enfant_de','conjoint'))
            ORDER BY sujet, predicat""")
relations = cur.fetchall()
for r in relations:
    print(f"  {r['sujet']} | {r['predicat']} | {r['objet']} | conf={r['confiance']}")

conn.close()