# tests/test_nimm_express.py
# Tests express post-corrections — NIMM avril 2026
# Exécution : python tests/test_nimm_express.py

import sys, os, json, uuid
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import init_db, get_conn, save_memory, count_memories, get_all_memory, get_memories_by_keys

init_db()

passed = 0
failed = 0

def ok(label):
    global passed
    passed += 1
    print(f"  OK {label}")

def fail(label, detail=''):
    global failed
    failed += 1
    print(f"  ERR {label}" + (f" — {detail}" if detail else ''))


# ══════════════════════════════════════
print("\n-- TEST 1 : WAL mode SQLite --")
# ══════════════════════════════════════
conn = get_conn()
row = conn.execute("PRAGMA journal_mode").fetchone()
conn.close()
if row and row[0].lower() == 'wal':
    ok("journal_mode = WAL")
else:
    fail("journal_mode != WAL", str(row))


# ══════════════════════════════════════
print("\n-- TEST 2 : Pas de double incrementation repetitions --")
# ══════════════════════════════════════
key = f"test_{uuid.uuid4().hex[:8]}"
record = {
    'key': key, 'type': 'trait', 'sujet': 'TestUser',
    'predicat': 'test_predicat', 'objet': 'valeur_a', 'valeur': 'valeur_a',
    'confiance': 1.0, 'valence': 0.0, 'sensibilite': 'neutre', 'cumulatif': 0,
    'categorie': 'quotidien', 'profondeur': 4, 'type_temporal': 'persistant',
    'expiration': None, 'timestamp': '2026-04-22T10:00:00', 'repetitions': 0,
    'poids': 1.0, 'embedding': None, 'memoire_type': 'identite', 'last_reinforced': None,
}
save_memory(record)  # insertion initiale

# Simuler un renforcement : on passe repetitions=1 (deja incremente par memory.py)
record2 = {**record, 'repetitions': 1, 'poids': 1.3, 'objet': 'valeur_b', 'valeur': 'valeur_b'}
save_memory(record2)

result = get_memories_by_keys([key])
if result:
    rep = result[0]['repetitions']
    if rep == 1:
        ok("repetitions = 1 (pas de double incrementation)")
    else:
        fail(f"repetitions = {rep} (attendu 1 -- double incrementation toujours presente)")
else:
    fail("Souvenir introuvable apres sauvegarde")

# Nettoyage
conn = get_conn()
conn.execute("DELETE FROM memory WHERE key = ?", (key,))
conn.execute("DELETE FROM memory_fts WHERE key = ?", (key,))
conn.commit()
conn.close()


# ══════════════════════════════════════
print("\n-- TEST 3 : count_memories() --")
# ══════════════════════════════════════
n = count_memories()
if isinstance(n, int) and n >= 0:
    ok(f"count_memories() retourne {n} (int valide)")
else:
    fail("count_memories() ne retourne pas un int", str(n))


# ══════════════════════════════════════
print("\n-- TEST 4 : _is_valid rejette les sujets generiques --")
# ══════════════════════════════════════
from modules.memory import _is_valid
cas = [
    ({'sujet': 'utilisateur', 'predicat': 'metier', 'objet': 'chauffeur'}, False),
    ({'sujet': 'je',          'predicat': 'metier', 'objet': 'chauffeur'}, False),
    ({'sujet': '',            'predicat': 'metier', 'objet': 'chauffeur'}, False),
    ({'sujet': 'Laurent',     'predicat': 'metier', 'objet': 'chauffeur'}, True),
    ({'sujet': 'Nadia',       'predicat': 'conjoint', 'objet': 'Laurent'}, True),
    ({'sujet': 'Laurent',     'predicat': 'metier', 'objet': ''},          False),
]
for s, expected in cas:
    result = _is_valid(s)
    if result == expected:
        ok(f"_is_valid({s['sujet']!r}) = {result}")
    else:
        fail(f"_is_valid({s['sujet']!r}) = {result}, attendu {expected}")


# ══════════════════════════════════════
print("\n-- TEST 5 : save_inline_memory avec existing pre-charge --")
# ══════════════════════════════════════
from modules.memory import save_inline_memory
key2 = f"test_{uuid.uuid4().hex[:8]}"
rec = {
    'key': key2, 'type': 'trait', 'sujet': 'Laurent',
    'predicat': 'loisir_principal', 'objet': 'piscine', 'valeur': 'piscine',
    'confiance': 0.9, 'valence': 0.0, 'sensibilite': 'neutre', 'cumulatif': 0,
    'categorie': 'loisirs', 'profondeur': 4, 'type_temporal': 'persistant',
    'expiration': None, 'timestamp': '2026-04-22T10:00:00', 'repetitions': 0,
    'poids': 1.0, 'embedding': None, 'memoire_type': 'identite', 'last_reinforced': None,
}
existing = get_all_memory()
try:
    save_inline_memory(rec, user_msg='', existing=existing)
    ok("save_inline_memory accepte existing= sans erreur")
except TypeError as e:
    fail("save_inline_memory rejette le parametre existing", str(e))

# Nettoyage
conn = get_conn()
conn.execute("DELETE FROM memory WHERE sujet = 'Laurent' AND predicat = 'loisir_principal'")
conn.execute("DELETE FROM memory_fts WHERE key = ?", (key2,))
conn.commit()
conn.close()


# ══════════════════════════════════════
print("\n-- TEST 6 : biblio_context injecte dans build_system_prompt --")
# ══════════════════════════════════════
from core.hub import build_system_prompt
mask = {'system_prompt': 'Tu es un assistant.'}
result = build_system_prompt(
    mask=mask,
    memory_context='',
    os_summary='',
    biblio_context='Conversations archivees sur ce sujet :\n  - [2026-04-01] Test archivage'
)
if 'Conversations archivees' in result:
    ok("biblio_context present dans le system prompt")
else:
    fail("biblio_context absent du system prompt -- non injecte")


# ══════════════════════════════════════
print("\n-- TEST 7 : FTS5 bibliotheque indexe titre + tags --")
# ══════════════════════════════════════
from core.database import save_bibliotheque_entry, search_bibliotheque_fts, delete_bibliotheque_entry
entry_id = save_bibliotheque_entry(
    titre='Projet NIMM architecture hub',
    sujet_principal='architecture logicielle',
    tags='hub, spoke, memoire, python',
    resume_texte="Discussion sur l'architecture du projet.",
    thread_id_source='test_thread',
    date_conversation='2026-04-22',
    os_json='{"sujet": "architecture", "mots_cles": ["hub", "python"]}',
    status='active',
)
# Chercher par titre (pas dans os_json)
ids = search_bibliotheque_fts('NIMM architecture', limit=5)
if entry_id in ids:
    ok(f"FTS5 bibliotheque trouve l'entree par son titre (id={entry_id})")
else:
    fail(f"FTS5 bibliotheque ne trouve pas l'entree par son titre", f"ids={ids}")
# Chercher par tag
ids2 = search_bibliotheque_fts('hub spoke memoire python', limit=5)
if entry_id in ids2:
    ok("FTS5 bibliotheque trouve l'entree par ses tags")
else:
    fail("FTS5 bibliotheque ne trouve pas l'entree par ses tags", f"ids={ids2}")
# Nettoyage
delete_bibliotheque_entry(entry_id)


# ══════════════════════════════════════
print("\n-- TEST 8 : Intent gate -- messages vides bloques, trivials passent --")
# ══════════════════════════════════════
import asyncio
from modules.intent_gate import intent_gate_filter

async def _run_gate_tests():
    cas = [
        ('',        True,  "message vide -> bloque"),
        (' ',       True,  "message espace -> bloque"),
        ('a',       True,  "message 1 char -> bloque"),
        ('Salut !', False, "salutation -> passe au LLM"),
        ('Merci',   False, "remerciement -> passe au LLM"),
        ('Au revoir', False, "au revoir -> passe au LLM"),
        ('Quel temps fait-il ce soir ?', False, "question reelle -> passe au LLM"),
    ]
    for msg, expect_blocked, label in cas:
        result = await intent_gate_filter(msg)
        # bloque = retourne quelque chose (meme None pour vide) OU ne retourne pas None
        # Logique : vide -> process_intent retourne dict avec response=None -> filter retourne None
        # Donc dans tous les cas intent_gate_filter retourne None -- la distinction est dans process_intent
        from modules.intent_gate import process_intent
        pi = process_intent(msg)
        is_blocked = pi is not None
        if is_blocked == expect_blocked:
            ok(label)
        else:
            fail(label, f"process_intent={pi}")

asyncio.run(_run_gate_tests())


# ══════════════════════════════════════
print(f"\n{'='*45}")
print(f"  Resultat : {passed} OK  {failed} ERR  ({passed+failed} tests)")
print(f"{'='*45}\n")
sys.exit(0 if failed == 0 else 1)
