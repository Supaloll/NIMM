# -*- coding: utf-8 -*-
import sys
import sqlite3
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/nimm_laurent.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("VERIFICATION FTS FINALE")
print("=" * 70)

# 1. Compter les lignes memory et memory_fts
cur.execute("SELECT COUNT(*) FROM memory")
n_memory = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM memory_fts")
n_fts = cur.fetchone()[0]
print(f"Lignes memory     : {n_memory}")
print(f"Lignes memory_fts : {n_fts}")
print(f"Ecart             : {n_memory - n_fts}")

# 2. Trouver les entrees manquantes (memory sans fts)
print("\nEntrees memory SANS fts (manquantes):")
cur.execute("""SELECT m.key, m.sujet, m.predicat, m.objet
            FROM memory m LEFT JOIN memory_fts f ON f.key = m.key
            WHERE f.key IS NULL""")
manquants = cur.fetchall()
if not manquants:
    print("  Aucune - OK")
else:
    for r in manquants:
        print(f"  {r['key']} | {r['sujet']} | {r['predicat']} | {r['objet']}")

# 3. Trouver les entrees fts orphelines (fts sans memory)
print("\nEntrees fts SANS memory (orphelines):")
cur.execute("""SELECT f.key FROM memory_fts f LEFT JOIN memory m ON m.key = f.key
            WHERE m.key IS NULL""")
orphelines = cur.fetchall()
if not orphelines:
    print("  Aucune - OK")
else:
    for r in orphelines:
        print(f"  {r['key']}")

# 4. Verifier les cles restaurees
print("\nCles restaurees dans FTS:")
cur.execute("""SELECT f.key, f.texte FROM memory_fts f
            WHERE f.key IN ('mem_56c05cbf', 'inf_52bbb3fe')""")
for r in cur.fetchall():
    print(f"  {r['key']} | '{r['texte']}'")

# 5. Verifier qu'il ne reste AUCUNE reference a 'Maissane KHALLAH' ou relation incoherente
print("\nVerification 'Maissane KHALLAH' / relations incoherentes:")
cur.execute("""SELECT COUNT(*) FROM memory
            WHERE sujet='Maissane KHALLAH' OR objet='Maissane KHALLAH'
               OR (sujet='Laurent' AND predicat='conjoint' AND objet LIKE '%Maissane%')
               OR (sujet='Laurent' AND predicat='parent' AND objet='maman')
               OR (sujet='maman' AND predicat='enfant' AND objet='Laurent')""")
n = cur.fetchone()[0]
print(f"  Restant: {n} (doit etre 0)")

conn.close()
print("\nOK: verification terminee")