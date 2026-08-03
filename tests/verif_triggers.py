# -*- coding: utf-8 -*-
import sys
import sqlite3
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/nimm_laurent.db')
cur = conn.cursor()

cur.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger'")
rows = cur.fetchall()
print('TRIGGERS:', len(rows))
for r in rows:
    print('---', r[0], '---')
    print(r[1])
    print()

conn.close()