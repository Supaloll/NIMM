# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')
import sqlite3, os

DB = os.path.join('data', 'nimm_laurent.db')
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
c = conn.cursor()
deleted_total = 0

def delete_where(label, condition):
    global deleted_total
    rows = c.execute(f"SELECT rowid, sujet, predicat, objet FROM memory WHERE {condition}").fetchall()
    if rows:
        print(f"\n[{label}] {len(rows)} entree(s) supprimee(s) :")
        for r in rows:
            print(f"  - {r['sujet']} / {r['predicat']} -> {r['objet']}")
        c.execute(f"DELETE FROM memory WHERE {condition}")
        deleted_total += len(rows)
    else:
        print(f"[{label}] rien.")

# 1. NIMM s'est memorise lui-meme
delete_where("NIMM self-ref sujet",
    "lower(sujet) IN ('assistant', 'nimm', 'interlocuteur', 'interlocutrice')")
delete_where("NIMM self-ref objet",
    "lower(objet) IN ('assistant', 'nimm') AND predicat IN ('ami', 'ami_proche', 'relation', 'interlocuteur')")
delete_where("ami Assistant objet contient assistant",
    "sujet='Laurent' AND predicat='ami' AND lower(objet) LIKE '%assistant%'")

# 2. Relations fausses
delete_where("enfant Nadia (faux)",
    "sujet='Laurent' AND predicat='enfant' AND objet='Nadia'")
delete_where("enfant filles (agregat)",
    "sujet='Laurent' AND predicat='enfant' AND objet='filles'")
delete_where("frere Helene (doublon de soeur)",
    "sujet='Laurent' AND predicat='frere' AND objet='Helene'")
delete_where("Jeannette enfant_de (symetrie inversee)",
    "sujet='Jeannette' AND predicat='enfant_de'")

# 3. Analogie trieur de pieces (contexte absent)
delete_where("methode_travail analogie",
    "predicat='methode_travail'")

# 4. Evenements transport / repas ponctuels
delete_where("trajets",
    "predicat IN ('trajet', 'itineraire', 'destination', 'retour', 'deplacement')")
delete_where("absences pro ponctuelles",
    "predicat IN ('absence', 'absence_longue', 'intervention', 'mission', 'deposer')")
delete_where("repas et sandwichs",
    "predicat IN ('manger', 'mange', 'repas') OR lower(objet) LIKE '%sandwich%' OR lower(objet) LIKE '%intermarch%'")
delete_where("Thermoking Benfeld",
    "lower(objet) LIKE '%thermoking%' OR lower(objet) LIKE '%benfeld%'")
delete_where("itineraires Didenheim/Mulhouse",
    "lower(objet) LIKE '%didenheim%' OR (lower(objet) LIKE '%mulhouse%' AND type_temporal='episodique')")
delete_where("evenements dev (pipeline, quiz, refacto)",
    "lower(objet) LIKE '%pipeline%' OR lower(objet) LIKE '%refactor%' OR lower(objet) LIKE '%quizz%' AND type_temporal='episodique'")

# 5. Doublons sans accent
delete_where("Helene sans accent (doublon de Helene)",
    "sujet='Helene'")
delete_where("Maissane sans accent (doublon de Maissane)",
    "sujet='Maissane'")

# 6. Traits pragmatique redondants - garde le plus lourd
rows_p = c.execute("""
    SELECT rowid, predicat, objet, poids FROM memory
    WHERE sujet='Laurent' AND (predicat IN ('pragmatisme','pragmatique','approche')
    OR lower(objet) LIKE '%pragmat%')
    ORDER BY poids DESC
""").fetchall()
if len(rows_p) > 1:
    print(f"\n[Pragmatique dups] garde : {rows_p[0]['predicat']} / {rows_p[0]['objet']} (poids={rows_p[0]['poids']})")
    for r in rows_p[1:]:
        print(f"  DELETE : {r['predicat']} / {r['objet']}")
        c.execute("DELETE FROM memory WHERE rowid=?", (r['rowid'],))
        deleted_total += 1

conn.commit()
conn.close()
print(f"\nOK: Nettoyage termine - {deleted_total} entree(s) supprimee(s).")
