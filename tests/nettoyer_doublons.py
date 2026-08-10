# -*- coding: utf-8 -*-
import sys
import sqlite3
sys.stdout.reconfigure(encoding='utf-8')

DB = 'data/nimm_laurent.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("NETTOYAGE DES DOUBLONS")
print("=" * 70)

# --- Verifier l'etat des souvenirs camion ---
print("\n[1] SOUVENIRS CAMION ACTUELS")
cur.execute("SELECT key, sujet, predicat, objet, poids, repetitions, timestamp FROM memory WHERE sujet='camion de Laurent' ORDER BY key")
camions = cur.fetchall()
for r in camions:
    print(f"  {r['key']} | {r['sujet']} | {r['predicat']} | {r['objet']} | poids={r['poids']} | rep={r['repetitions']} | {r['timestamp']}")

# --- Detecter les doublons exacts (meme sujet+predicat+objet) ---
print("\n[2] DETECTION DES DOUBLONS EXACTS")
cur.execute("""SELECT sujet, predicat, objet, COUNT(*) as n FROM memory
            GROUP BY sujet, predicat, objet HAVING n > 1 ORDER BY n DESC""")
doublons = cur.fetchall()
if not doublons:
    print("  Aucun doublon exact trouve")
else:
    for d in doublons:
        print(f"  DOUBLON: {d['sujet']} | {d['predicat']} | {d['objet']} x{d['n']}")
        # Lister les cles concernees
        cur.execute("SELECT key, poids, repetitions, timestamp FROM memory WHERE sujet=? AND predicat=? AND objet=? ORDER BY timestamp",
                    (d['sujet'], d['predicat'], d['objet']))
        keys = cur.fetchall()
        for k in keys:
            print(f"    -> {k['key']} | poids={k['poids']} | rep={k['repetitions']} | {k['timestamp']}")

        # Garder le plus recent (le plus renforce), supprimer les autres
        garder = keys[-1]['key']
        for k in keys:
            if k['key'] != garder:
                cur.execute("DELETE FROM memory WHERE key=?", (k['key'],))
                print(f"    SUPPRIME doublon: {k['key']}")

conn.commit()

# --- Verification finale ---
print("\n[3] VERIFICATION FINALE CAMION")
cur.execute("SELECT key, sujet, predicat, objet FROM memory WHERE sujet='camion de Laurent' ORDER BY predicat, objet")
for r in cur.fetchall():
    print(f"  {r['key']} | {r['sujet']} | {r['predicat']} | {r['objet']}")

# --- Verification globale coherence ---
print("\n[4] VERIFICATION GLOBALE DES RELATIONS FAMILIALES (convention: sujet A POUR predicat objet)")
cur.execute("""SELECT sujet, predicat, objet, confiance FROM memory
            WHERE predicat IN ('parent','mere','enfant','enfant_de','conjoint','prenom_mere')
            ORDER BY sujet, predicat""")
for r in cur.fetchall():
    print(f"  {r['sujet']} | {r['predicat']} | {r['objet']} | conf={r['confiance']}")

# Compter total
cur.execute("SELECT COUNT(*) FROM memory")
print(f"\nTotal souvenirs: {cur.fetchone()[0]}")

conn.close()
print("\nOK: nettoyage termine")