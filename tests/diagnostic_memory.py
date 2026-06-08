import sqlite3, os
DB = os.path.join('data', 'nimm_laurent.db')
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT sujet, predicat, objet, type_temporal, poids FROM memory ORDER BY sujet, predicat"
).fetchall()
print(f"Total : {len(rows)} lignes\n")
for r in rows:
    print(f"{r['sujet']} | {r['predicat']} | {r['objet']} | {r['type_temporal']} | poids={r['poids']}")
conn.close()
