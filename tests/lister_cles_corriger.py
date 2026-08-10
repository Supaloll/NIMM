# -*- coding: utf-8 -*-
import sys
import sqlite3
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/nimm_laurent.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Cibles potentielles
cibles = [
    ("Maïssane", "parent", "Laurent"),
    ("Maïssane", "enfant_de", "Laurent"),
    ("Laurent", "enfant", "Maïssane"),
    ("Laurent", "conjoint", "Maïssane KHALLAH"),
    ("Maïssane KHALLAH", "conjoint", "Laurent"),
    ("Laurent", "parent", "maman"),
    ("Laurent", "maman", "mère de Laurent"),
    ("Laurent", "famille", "famille"),
    ("maman", "enfant", "Laurent"),
    ("maman", "qualite", "pas trop animaux"),
    ("Laurent", "relation_sociale", "principale du collège de Maya"),
    ("Laurent", "vehicule", "document PDF 2026-07-Baumgart pour mutuelle Laurent.pdf"),
]

print("SOUVENIRS CIBLES AVEC CLES:")
print("=" * 80)
for sujet, predicat, objet in cibles:
    cur.execute(
        "SELECT key, type, sujet, predicat, objet, confiance, timestamp FROM memory WHERE sujet=? AND predicat=? AND objet=?",
        (sujet, predicat, objet)
    )
    rows = cur.fetchall()
    if rows:
        for r in rows:
            print(f"  KEY={r['key']} | [{r['type']}] {r['sujet']} | {r['predicat']} | {r['objet']} | conf={r['confiance']} | {r['timestamp']}")
    else:
        print(f"  (non trouve) {sujet} | {predicat} | {objet}")

conn.close()