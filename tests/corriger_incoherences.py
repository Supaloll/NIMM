# -*- coding: utf-8 -*-
import sys
import sqlite3
sys.stdout.reconfigure(encoding='utf-8')

DB = 'data/nimm_laurent.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("=" * 70)
print("CORRECTION DES INCOHERENCES - nimm_laurent.db")
print("=" * 70)

# ---------- 0. Verifier les references 'maman' pour ne rien oublier ----------
print("\n[0] VERIFICATION DES REFERENCES 'maman'")
cur.execute("SELECT key, sujet, predicat, objet, valeur FROM memory WHERE sujet='maman' OR objet='maman' OR valeur='maman'")
refs = cur.fetchall()
print(f"  References 'maman' trouvees: {len(refs)}")
for r in refs:
    print(f"    {r['key']} | {r['sujet']} | {r['predicat']} | {r['objet']} | val={r['valeur']}")

# ---------- 1. Suppression des souvenirs incohérents ----------
DELETES = [
    # Maïssane serait parent de Laurent (inversion parent/enfant)
    ("inf_52bbb3fe", "Maïssane", "parent", "Laurent"),
    # Laurent serait enfant de Maïssane (inversion)
    ("mem_56c05cbf", "Laurent", "enfant", "Maïssane"),
    # Laurent conjoint de Maïssane KHALLAH (= sa fille, entite non fusionnee)
    ("inf_ee4813ba", "Laurent", "conjoint", "Maïssane KHALLAH"),
    ("mem_5bd10e2d", "Maïssane KHALLAH", "conjoint", "Laurent"),
    # Laurent parent de maman (inversion)
    ("mem_a53c33a2", "Laurent", "parent", "maman"),
    # Triplet tautologique Laurent | maman | mère de Laurent
    ("mem_489078d2", "Laurent", "maman", "mère de Laurent"),
    # Triplet tautologique Laurent | famille | famille
    ("mem_92e2269c", "Laurent", "famille", "famille"),
    # Relation sociale de Maya attribuee a Laurent
    ("mem_2b964750", "Laurent", "relation_sociale", "principale du collège de Maya"),
    # PDF enregistre comme vehicule
    ("mem_23debe3c", "Laurent", "vehicule", "document PDF 2026-07-Baumgart pour mutuelle Laurent.pdf"),
]

print("\n[1] SUPPRESSION DES SOUVENIRS INCOHERENTS")
total_del = 0
for key, sujet, predicat, objet in DELETES:
    # Verifier que la ligne existe et correspond exactement
    cur.execute("SELECT key FROM memory WHERE key=? AND sujet=? AND predicat=? AND objet=?",
                (key, sujet, predicat, objet))
    found = cur.fetchall()
    if len(found) == 1:
        cur.execute("DELETE FROM memory WHERE key=?", (key,))
        total_del += 1
        print(f"  SUPPRIME  {key} | {sujet} | {predicat} | {objet}")
    else:
        print(f"  ATTENTION non trouve ({len(found)}): {key} | {sujet} | {predicat} | {objet}")

print(f"  Total suppressions: {total_del}/{len(DELETES)}")

# ---------- 2. Fusion entite 'maman' -> 'Jeannette' ----------
print("\n[2] FUSION ENTITE 'maman' -> 'Jeannette'")
# Le triplet 'maman | enfant | Laurent' est coherent, on le renomme
# Le triplet 'maman | qualite | pas trop animaux' est coherent, on le renomme
cur.execute("SELECT COUNT(*) FROM memory WHERE sujet='maman'")
count_maman_sujet = cur.fetchone()[0]
print(f"  Sujets 'maman' a renommer: {count_maman_sujet}")

if count_maman_sujet > 0:
    cur.execute("UPDATE memory SET sujet='Jeannette' WHERE sujet='maman'")
    print(f"  DONE: {count_maman_sujet} sujet(s) 'maman' -> 'Jeannette'")
else:
    print("  AUCUN sujet 'maman' trouve")

# ---------- 3. Fusion entites 'camion' -> 'camion de Laurent' ----------
print("\n[3] FUSION ENTITES CAMION + CORRECTION PREDICAT")
cur.execute("SELECT key, sujet, predicat, objet FROM memory WHERE sujet IN ('camion', 'camion de Laurent')")
camions = cur.fetchall()
print(f"  Souvenirs camion trouves: {len(camions)}")
for r in camions:
    print(f"    {r['key']} | {r['sujet']} | {r['predicat']} | {r['objet']}")

# a) 'camion | probleme_sante | bruit moteur' -> 'camion de Laurent | probleme | bruit moteur'
cur.execute("SELECT COUNT(*) FROM memory WHERE sujet='camion' AND predicat='probleme_sante' AND objet='bruit moteur'")
count_camion1 = cur.fetchone()[0]
if count_camion1 == 1:
    cur.execute("UPDATE memory SET sujet='camion de Laurent', predicat='probleme' WHERE sujet='camion' AND predicat='probleme_sante' AND objet='bruit moteur'")
    print(f"  DONE: camion | probleme_sante | bruit moteur -> camion de Laurent | probleme | bruit moteur")
else:
    print(f"  ATTENTION: {count_camion1} occurrence(s) pour camion|probleme_sante|bruit moteur")

# b) 'camion de Laurent | probleme_sante | bruit côté moteur' -> 'camion de Laurent | probleme | bruit côté moteur'
cur.execute("SELECT COUNT(*) FROM memory WHERE sujet='camion de Laurent' AND predicat='probleme_sante' AND objet='bruit côté moteur'")
count_camion2 = cur.fetchone()[0]
if count_camion2 == 1:
    cur.execute("UPDATE memory SET predicat='probleme' WHERE sujet='camion de Laurent' AND predicat='probleme_sante' AND objet='bruit côté moteur'")
    print(f"  DONE: camion de Laurent | probleme_sante | bruit côté moteur -> probleme")
else:
    print(f"  ATTENTION: {count_camion2} occurrence(s) pour camion de Laurent|probleme_sante|bruit côté moteur")

# ---------- 4. Verification finale ----------
print("\n[4] VERIFICATION FINALE")
conn.commit()

# Verifier qu'il ne reste plus de contradictions
cur.execute("""SELECT COUNT(*) FROM memory WHERE (sujet='Laurent' AND predicat='enfant' AND objet='Maïssane')
            OR (sujet='Maïssane' AND predicat='parent' AND objet='Laurent')
            OR (sujet='Laurent' AND predicat='conjoint' AND objet='Maïssane KHALLAH')
            OR (sujet='Maïssane KHALLAH' AND predicat='conjoint' AND objet='Laurent')
            OR (sujet='Laurent' AND predicat='parent' AND objet='maman')
            OR (sujet='maman' AND predicat='enfant' AND objet='Laurent')""")
reste = cur.fetchone()[0]
print(f"  Contradictions restantes: {reste}")

# Afficher les relations familiales restantes
print("\n  Relations familiales apres correction:")
cur.execute("SELECT sujet, predicat, objet, confiance FROM memory WHERE "
            "(sujet='Laurent' AND predicat IN ('enfant','conjoint','mere','parent','prenom_mere')) "
            "OR (sujet IN ('Maïssane','Maya','Innès','Nadia','Jeannette') AND predicat IN ('parent','conjoint','enfant','enfant_de')) "
            "ORDER BY sujet, predicat")
for r in cur.fetchall():
    print(f"    {r['sujet']} | {r['predicat']} | {r['objet']} | conf={r['confiance']}")

# Compter les souvenirs restants
cur.execute("SELECT COUNT(*) FROM memory")
print(f"\n  Total souvenirs: {cur.fetchone()[0]}")

# Verifier qu'il ne reste plus d'entites 'maman' ou 'Maïssane KHALLAH'
cur.execute("SELECT DISTINCT sujet FROM memory WHERE sujet IN ('maman', 'Maïssane KHALLAH')")
restes_entites = cur.fetchall()
print(f"  Entites 'maman'/'Maïssane KHALLAH' restantes: {len(restes_entites)}")

conn.commit()
conn.close()
print("\nOK: corrections terminees")