# -*- coding: utf-8 -*-
import sys
import sqlite3
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/nimm_laurent.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("SELECT key, type, sujet, predicat, objet, valeur, confiance, categorie, timestamp FROM memory ORDER BY sujet, predicat")
rows = cur.fetchall()
print(f'TOTAL: {len(rows)} souvenirs')
print('=' * 80)

for r in rows:
    sujet = r['sujet'] or ''
    predicat = r['predicat'] or ''
    objet = r['objet'] or ''
    valeur = r['valeur'] or ''
    print(f"[{r['type']}] {sujet} | {predicat} | {objet} | {valeur} | conf={r['confiance']}")

conn.close()