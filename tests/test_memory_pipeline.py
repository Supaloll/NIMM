# -*- coding: utf-8 -*-
# ============================================
# NIMM — tests/test_memory_pipeline.py
# Diagnostic pipeline complet : HTTP → stream → DB
# Vérifie que les %%MEM%% générés par le LLM atterrissent en DB.
# NIMM doit tourner sur localhost:8080 avant de lancer ce script.
# Execution : python -X utf8 tests/test_memory_pipeline.py
# ============================================

import sys, os, requests, time, json
sys.stdout.reconfigure(encoding='utf-8')

BASE  = 'http://localhost:8080'
WAIT  = 5  # secondes d'attente après chaque message (stream + save)

GREEN  = '\033[92m'
RED    = '\033[91m'
YELLOW = '\033[93m'
CYAN   = '\033[96m'
BOLD   = '\033[1m'
RESET  = '\033[0m'

def ok(msg):   print(f'  {GREEN}✓ {msg}{RESET}')
def fail(msg): print(f'  {RED}✗ {msg}{RESET}')
def info(msg): print(f'  {CYAN}→ {msg}{RESET}')
def warn(msg): print(f'  {YELLOW}⚠ {msg}{RESET}')

# ══════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════

def get_memories():
    try:
        r = requests.get(f'{BASE}/api/memory/triplets', timeout=10)
        return r.json() if r.ok else []
    except Exception as e:
        warn(f'Impossible de lire la mémoire : {e}')
        return []

def get_memory_keys(memories):
    """Retourne un set d'identifiants (sujet|predicat|objet) pour comparaison."""
    return {
        f"{m.get('sujet','').lower()}|{m.get('predicat','').lower()}|{m.get('objet','').lower()}"
        for m in memories
    }

def create_thread(name):
    r = requests.post(f'{BASE}/api/threads', json={'name': name, 'mode': 'chat'}, timeout=10)
    return r.json().get('thread_id') if r.ok else None

def delete_thread(thread_id):
    try:
        requests.delete(f'{BASE}/api/threads/{thread_id}', timeout=10)
    except Exception:
        pass

def send_message(thread_id, message):
    """Envoie un message via /api/chat/stream (chemin réel) et attend la fin."""
    try:
        r = requests.post(
            f'{BASE}/api/chat/stream',
            json={'thread_id': thread_id, 'message': message},
            stream=True,
            timeout=60,
        )
        full = ''
        for line in r.iter_lines():
            if line:
                decoded = line.decode('utf-8', errors='replace')
                if decoded.startswith('data: '):
                    chunk = decoded[6:]
                    if chunk not in ('[DONE]',) and not chunk.startswith('[META]') and not chunk.startswith('[ERREUR'):
                        full += chunk.replace('\\n', '\n')
        return full.strip()
    except Exception as e:
        warn(f'Erreur stream : {e}')
        return ''

# ══════════════════════════════════════════
# CAS DE TEST PIPELINE
# ══════════════════════════════════════════
# Ces cas DOIVENT générer de nouveaux souvenirs en DB.
# On vérifie via l'API memory/triplets avant et après.

PIPELINE_CASES = [
    {
        'id':      'P1',
        'label':   'Déclaration directe — animal nommé',
        'msg':     "Mon perroquet s'appelle Coco.",
        'check':   lambda mems: any('coco' in str(m).lower() for m in mems),
        'expect':  'Coco présent en mémoire',
    },
    {
        'id':      'P2',
        'label':   'Loisir déclaré',
        'msg':     "J'adore la pêche à la truite.",
        'check':   lambda mems: any('pêche' in str(m).lower() or 'peche' in str(m).lower() or 'truite' in str(m).lower() for m in mems),
        'expect':  'pêche ou truite présent en mémoire',
    },
    {
        'id':      'P3',
        'label':   'Relation professionnelle',
        'msg':     "Mon chef s'appelle Bernard, on bosse ensemble depuis 5 ans.",
        'check':   lambda mems: any('bernard' in str(m).lower() for m in mems),
        'expect':  'Bernard présent en mémoire',
    },
    {
        'id':      'P4',
        'label':   'Force-TAG explicite',
        'msg':     "Souviens-toi que mon code postal c'est 11200.",
        'check':   lambda mems: any('11200' in str(m) for m in mems),
        'expect':  '11200 présent en mémoire',
    },
]

# ══════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════

def main():
    print(BOLD + '\n' + '═' * 68 + RESET)
    print(BOLD + '  NIMM — Diagnostic pipeline mémoire (HTTP → stream → DB)' + RESET)
    print(BOLD + '═' * 68 + RESET + '\n')

    # Vérifier que NIMM tourne
    try:
        requests.get(f'{BASE}/api/threads', timeout=5)
    except Exception:
        print(RED + f'  ERR: NIMM ne répond pas sur {BASE}' + RESET)
        print(RED + '  Lance d\'abord : python main.py' + RESET)
        sys.exit(1)

    # Créer un fil de test dédié
    thread_name = '[DIAG-PIPELINE]'
    thread_id = create_thread(thread_name)
    if not thread_id:
        print(RED + '  ERR: Impossible de créer le fil de test.' + RESET)
        sys.exit(1)
    info(f'Fil de test créé : {thread_id}')

    # Snapshot mémoire AVANT
    mems_before = get_memories()
    keys_before = get_memory_keys(mems_before)
    info(f'Mémoire avant : {len(mems_before)} souvenirs')
    print()

    pass_count = 0
    fail_count = 0

    for case in PIPELINE_CASES:
        print(f'  [{case["id"]}] {case["label"]}')
        info(f'Message : {case["msg"]}')

        # Snapshot avant CE message
        mems_snap = get_memories()

        # Envoyer le message (chemin réel /api/chat/stream)
        reply = send_message(thread_id, case['msg'])
        if reply:
            preview = reply[:80].replace('\n', ' ')
            info(f'Réponse : {preview}…')
        else:
            warn('Pas de réponse reçue')

        # Attendre que le pipeline sauvegarde
        info(f'Attente {WAIT}s (pipeline async)…')
        time.sleep(WAIT)

        # Snapshot après
        mems_after = get_memories()
        keys_after = get_memory_keys(mems_after)
        new_keys   = keys_after - get_memory_keys(mems_snap)

        info(f'Nouveaux souvenirs : {len(new_keys)}')
        for k in new_keys:
            print(f'       {YELLOW}+ {k}{RESET}')

        # Vérification spécifique
        if case['check'](mems_after):
            ok(f'PASS — {case["expect"]}')
            pass_count += 1
        else:
            fail(f'FAIL — {case["expect"]} introuvable en DB')
            fail_count += 1
            if not new_keys:
                warn('Aucun nouveau souvenir créé → le pipeline ne sauvegarde pas.')
            else:
                warn('Des souvenirs ont été créés mais pas celui attendu.')
        print()

    # Nettoyage
    delete_thread(thread_id)
    info(f'Fil de test supprimé.')

    # ── Résumé ──
    print(BOLD + '─' * 68 + RESET)
    print(BOLD + f'  Résultat : {pass_count}/{len(PIPELINE_CASES)} OK' + RESET)

    mems_after_all = get_memories()
    delta = len(mems_after_all) - len(mems_before)
    info(f'Delta mémoire total : {delta:+d} souvenir(s)')

    print()
    if fail_count == 0:
        print(GREEN + '  ✓ Pipeline complet fonctionnel — tags générés ET sauvegardés.' + RESET)
    elif pass_count == 0:
        print(RED + '  ✗ Aucun souvenir sauvegardé — bug dans le pipeline (hub.py / memory.py).' + RESET)
        print(RED + '    Vérifie les logs console de NIMM pendant ce test pour les prints [MEMORY].' + RESET)
    else:
        print(YELLOW + f'  ⚠ Pipeline partiel — {fail_count} cas non sauvegardés.' + RESET)

    print(BOLD + '═' * 68 + RESET + '\n')

main()
