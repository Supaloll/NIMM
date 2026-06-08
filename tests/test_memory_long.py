# -*- coding: utf-8 -*-
# ============================================
# NIMM — tests/test_memory_long.py
# Diagnostic : extraction mémoire sur messages longs / mixtes
# Simule le style réel de Laurent (voice-to-text, phrases longues,
# faits noyés dans une requête ou un récit).
# NIMM doit tourner sur localhost:8080 avant de lancer ce script.
# Execution : python -X utf8 tests/test_memory_long.py
# ============================================

import sys, os, requests, time
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://localhost:8080'
WAIT = 8  # messages longs → stream plus long → attente plus longue

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

def get_memories():
    try:
        r = requests.get(f'{BASE}/api/memory/triplets', timeout=10)
        return r.json() if r.ok else []
    except Exception as e:
        warn(f'Mémoire inaccessible : {e}')
        return []

def get_memory_keys(memories):
    return {
        f"{m.get('sujet','').lower()}|{m.get('predicat','').lower()}|{m.get('objet','').lower()}"
        for m in memories
    }

def create_thread(name):
    r = requests.post(f'{BASE}/api/threads', json={'name': name, 'mode': 'chat'}, timeout=10)
    return r.json().get('thread_id') if r.ok else None

def delete_thread(tid):
    try: requests.delete(f'{BASE}/api/threads/{tid}', timeout=10)
    except: pass

def send_stream(thread_id, message):
    try:
        r = requests.post(
            f'{BASE}/api/chat/stream',
            json={'thread_id': thread_id, 'message': message},
            stream=True, timeout=90,
        )
        full = ''
        for line in r.iter_lines():
            if line:
                d = line.decode('utf-8', errors='replace')
                if d.startswith('data: '):
                    chunk = d[6:]
                    if chunk not in ('[DONE]',) and not chunk.startswith('[META]') and not chunk.startswith('[ERREUR'):
                        full += chunk.replace('\\n', '\n')
        return full.strip()
    except Exception as e:
        warn(f'Erreur stream : {e}')
        return ''

# ══════════════════════════════════════════
# CAS — messages longs / style réel
# ══════════════════════════════════════════
# faits_cibles : mots-clés qui DOIVENT apparaître en mémoire

CASES = [
    {
        'id':    'L1',
        'label': 'Projet marathon — fait noyé dans une requête longue',
        'msg': (
            "J'ai décidé de me remettre sérieusement à la course à pied. "
            "Mon objectif c'est de courir un marathon l'année prochaine, j'en ai déjà fait un il y a dix ans "
            "donc je sais à peu près ce que ça demande comme préparation. "
            "J'ai 46 ans, je pèse 84 kilos, je fais environ 1m80. "
            "En ce moment je cours à peine, peut-être 2 kilomètres sans m'arrêter. "
            "Est-ce que tu peux me faire un programme d'entraînement sur 6 mois pour préparer ce marathon ?"
        ),
        'faits_cibles': ['marathon', '46', '84', '1m80', 'course'],
        'check': lambda mems: any(
            any(k in str(m).lower() for k in ['marathon', '46 ans', '84', 'course', 'running', 'sport'])
            for m in mems
        ),
        'expect': 'objectif marathon ou données physiques en mémoire',
    },
    {
        'id':    'L2',
        'label': 'Récit long avec plusieurs faits personnels',
        'msg': (
            "Je voulais te parler d'un truc qui me trotte dans la tête depuis un moment. "
            "Tu sais que je suis camionneur depuis 1999, et depuis quelques années j'ai l'impression "
            "que le métier change vraiment vite. Les nouvelles réglementations, les chronotachygraphes numériques, "
            "les camions hybrides qui commencent à pointer le bout du nez. "
            "Moi j'ai toujours conduit des semi-remorques, principalement sur des trajets longue distance, "
            "Paris-Espagne ou Paris-Italie en général. "
            "J'ai un permis CE depuis 2001 et j'ai jamais eu d'accident en 25 ans de route. "
            "C'est quelque chose dont je suis fier. Est-ce que tu penses que les camions électriques "
            "vont vraiment remplacer les diesels d'ici 10 ans ?"
        ),
        'faits_cibles': ['semi-remorque', 'CE', '2001', 'Paris', 'accident'],
        'check': lambda mems: any(
            any(k in str(m).lower() for k in ['semi', 'permis', 'ce', 'longue distance', 'accident', 'paris'])
            for m in mems
        ),
        'expect': 'type camion / permis CE / trajets en mémoire',
    },
    {
        'id':    'L3',
        'label': 'Message mixte : émotion + faits + requête (style voice-to-text)',
        'msg': (
            "Écoute je suis un peu fatigué là parce que j'ai fait une nuit blanche, "
            "ma fille Maya elle était malade donc j'ai pas dormi. "
            "Elle a 8 ans et elle a fait de la fièvre toute la nuit. "
            "Mais bon c'est la vie. En dehors de ça je voulais te demander, "
            "tu sais que j'élève des poules depuis deux ans maintenant, j'en ai sept, "
            "et j'ai un problème avec une d'entre elles qui pondait plus depuis 3 semaines. "
            "Là elle a recommencé ce matin donc c'est réglé. "
            "Mais est-ce que tu sais pourquoi les poules peuvent arrêter de pondre comme ça ?"
        ),
        'faits_cibles': ['maya', 'poules', '8 ans', 'sept', 'deux ans'],
        'check': lambda mems: any(
            any(k in str(m).lower() for k in ['poule', 'maya', '8 ans', 'huit', 'volaille', 'elevage'])
            for m in mems
        ),
        'expect': 'poules ou âge de Maya en mémoire',
    },
    {
        'id':    'L4',
        'label': 'Déclaration + correction implicite d\'un fait connu',
        'msg': (
            "Au fait, je crois que je t'ai mal dit mon métier au début. "
            "Je suis pas juste routier, je suis conducteur de transport exceptionnel, "
            "c'est-à-dire que je transporte des charges hors gabarit, des pièces d'éoliennes, "
            "des transformateurs électriques, des trucs qui dépassent les dimensions légales. "
            "C'est un boulot qui demande des autorisations spéciales, des escortes parfois, "
            "et une préparation d'itinéraire très précise. "
            "C'est pas le même métier qu'un routier classique même si le fond c'est pareil. "
            "Tu peux mettre ça à jour dans ce que tu sais de moi ?"
        ),
        'faits_cibles': ['exceptionnel', 'éolienne', 'gabarit', 'hors gabarit'],
        'check': lambda mems: any(
            any(k in str(m).lower() for k in ['exceptionnel', 'gabarit', 'eolien', 'special', 'hors gabarit'])
            for m in mems
        ),
        'expect': 'transport exceptionnel en mémoire',
    },
]

# ══════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════

def main():
    print(BOLD + '\n' + '═' * 68 + RESET)
    print(BOLD + '  NIMM — Extraction mémoire sur messages longs (style réel)' + RESET)
    print(BOLD + '═' * 68 + RESET + '\n')

    try:
        requests.get(f'{BASE}/api/threads', timeout=5)
    except Exception:
        print(RED + f'  ERR: NIMM ne répond pas sur {BASE}' + RESET)
        sys.exit(1)

    tid = create_thread('[DIAG-LONG]')
    if not tid:
        print(RED + '  ERR: Impossible de créer le fil de test.' + RESET)
        sys.exit(1)
    info(f'Fil de test : {tid}')

    mems_before = get_memories()
    info(f'Mémoire avant : {len(mems_before)} souvenirs\n')

    pass_count = 0
    fail_count = 0

    for case in CASES:
        print(f'  [{case["id"]}] {BOLD}{case["label"]}{RESET}')
        # Affiche le message tronqué
        preview = case['msg'][:120].replace('\n', ' ')
        info(f'Message ({len(case["msg"])} chars) : {preview}…')
        info(f'Faits attendus : {case["faits_cibles"]}')

        snap_before = get_memories()

        reply = send_stream(tid, case['msg'])
        if reply:
            info(f'Réponse : {reply[:100].replace(chr(10), " ")}…')
        else:
            warn('Pas de réponse reçue.')

        info(f'Attente {WAIT}s…')
        time.sleep(WAIT)

        snap_after = get_memories()
        new_keys = get_memory_keys(snap_after) - get_memory_keys(snap_before)

        if new_keys:
            info(f'{len(new_keys)} nouveau(x) souvenir(s) :')
            for k in sorted(new_keys):
                print(f'       {YELLOW}+ {k}{RESET}')
        else:
            warn('Aucun nouveau souvenir créé.')

        if case['check'](snap_after):
            ok(f'PASS — {case["expect"]}')
            pass_count += 1
        else:
            fail(f'FAIL — {case["expect"]} introuvable')
            fail_count += 1
        print()

    delete_thread(tid)
    info('Fil de test supprimé.')

    # ── Résumé ──
    print(BOLD + '─' * 68 + RESET)
    mems_after = get_memories()
    delta = len(mems_after) - len(mems_before)
    print(BOLD + f'  Résultat : {pass_count}/{len(CASES)} OK  |  Delta mémoire : {delta:+d}' + RESET)
    print()

    if fail_count == 0:
        print(GREEN + '  ✓ Le LLM extrait correctement les faits des messages longs.' + RESET)
    else:
        failed_ids = []
        for i, case in enumerate(CASES):
            # recheck based on pass/fail count logic - simpler: just flag
            pass
        if pass_count == 0:
            print(RED + '  ✗ Aucune extraction — problème général pipeline.' + RESET)
        else:
            print(YELLOW + f'  ⚠ Extraction partielle : {fail_count} cas longs non capturés.' + RESET)
            print(YELLOW + '    → Le LLM se concentre sur la requête et oublie les TAGs dans les longs messages.' + RESET)
            print(YELLOW + '    → Piste : ajouter un rappel TAG en fin de system prompt pour messages > N tokens.' + RESET)

    print(BOLD + '═' * 68 + RESET + '\n')

main()
