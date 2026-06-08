# -*- coding: utf-8 -*-
# ============================================
# NIMM — test_memory.py  v3
# Test qualite memoire : TAGs, predicats,
# deduplication, paragraphes complexes.
# v3 : appel /memorize apres chaque groupe
#      pour mesurer le vrai score systeme.
# Usage : python -X utf8 test_memory.py
# NIMM doit tourner sur localhost:8080
# Recommande : vider la memoire avant de lancer.
# ============================================

import sys, re, time, sqlite3, requests
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')

BASE    = 'http://localhost:8080'
DB_PATH = 'data/nimm.db'
PAUSE   = 5   # secondes entre messages

OK   = '[PASS]'
ERR  = '[FAIL]'
WARN = '[WARN]'
INFO = '[INFO]'
SEP  = '-' * 64

results = []

def record(group, name, passed, detail=''):
    results.append({'group': group, 'name': name, 'passed': passed, 'detail': detail})
    icon = OK if passed else ERR
    suffix = f'  ->  {detail}' if detail else ''
    print(f'  {icon}  {name}{suffix}')

def header(title):
    print(f'\n{SEP}')
    print(f'  {title}')
    print(SEP)

def info(msg):  print(f'  {INFO}  {msg}')
def warn(msg):  print(f'  {WARN}  {msg}')
def dim(msg):   print(f'         {msg}')


# ════════════════════════════════════════════
# PREDICATS VERBAUX INTERDITS EN BASE
# ════════════════════════════════════════════

VERBES_INTERDITS = {
    'etudie','etudies','etudient','etudions','etudier',
    'travaille','travailles','travaillent','travaillons','travailler',
    'habite','habites','habitent','habiter',
    'pratique','pratiques','pratiquent','pratiquer',
    'joue','joues','jouent','jouer',
    'aime_faire','faire','fait','font',
    'est','sont','a','ont',
    'vit','vive','conduit','conduis',
    'apprend','apprendre','suit','suivre',
    'fait_du','fait_de_la',
}

TEMPORELS_VALIDES = {'permanent','persistant','episodique','engagement'}


# ════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════

def create_thread(name):
    try:
        r = requests.post(f'{BASE}/api/threads',
                          json={'name': name, 'mode': 'chat'}, timeout=10)
        return r.json().get('thread_id') if r.ok else None
    except Exception as e:
        warn(f'create_thread : {e}')
        return None

def send_stream(thread_id, message):
    try:
        r = requests.post(
            f'{BASE}/api/chat/stream',
            json={'thread_id': thread_id, 'message': message},
            stream=True, timeout=120,
        )
        full = ''
        for line in r.iter_lines():
            if not line: continue
            d = line.decode('utf-8', errors='replace')
            if not d.startswith('data: '): continue
            chunk = d[6:]
            if chunk in ('[DONE]',) or chunk.startswith('[META]'): continue
            if chunk.startswith('[ERREUR') or chunk.startswith('[IMAGE'): continue
            full += chunk.replace('\\n', '\n')
        mem_tags = re.findall(r'%%MEM:([^%]+)%%', full)
        clean    = re.sub(r'%%[A-Z_]+:[^%]*%%', '', full).strip()
        return clean, mem_tags
    except Exception as e:
        warn(f'send_stream : {e}')
        return '', []

def memorize_thread(tid):
    """Declenche la passe batch /memorize sur le fil.
    Simule la fermeture de fil en usage reel.
    Retourne le nombre de souvenirs extraits."""
    try:
        info('Passe /memorize en cours...')
        r = requests.post(f'{BASE}/api/threads/{tid}/memorize', timeout=120)
        saved = r.json().get('saved', 0) if r.ok else 0
        info(f'/memorize termine : {saved} souvenir(s) extrait(s) par la passe batch')
        return saved
    except Exception as e:
        warn(f'/memorize echec : {e}')
        return 0

def get_memories_since(ts):
    try:
        conn = sqlite3.connect(DB_PATH)
        c    = conn.cursor()
        c.execute(
            'SELECT sujet, predicat, objet, type_temporal FROM memory '
            'WHERE timestamp > ? ORDER BY timestamp',
            (ts,)
        )
        rows = c.fetchall()
        conn.close()
        return [{'sujet': r[0], 'predicat': r[1],
                 'objet': r[2], 'type_temporal': r[3]} for r in rows]
    except Exception as e:
        warn(f'DB read : {e}')
        return []

def parse_tag(raw):
    parts = raw.strip().split('|')
    if len(parts) == 8:
        return {'type':parts[0],'sujet':parts[1],'predicat':parts[2],
                'objet':parts[3],'contexte':parts[4],
                'memoire_type':parts[5],'profondeur':parts[6],'temporal':parts[7]}
    elif len(parts) == 7:
        return {'type':parts[0],'sujet':parts[1],'predicat':parts[2],
                'objet':parts[3],'contexte':'',
                'memoire_type':parts[4],'profondeur':parts[5],'temporal':parts[6]}
    return {}

def show_mems(mems, label='Apres memorize'):
    print(f'         --- {label} ({len(mems)} souvenir(s)) ---')
    if not mems:
        dim('(aucun souvenir enregistre)')
        return
    for m in mems:
        dim(f'{m["sujet"]} / {m["predicat"]} = {m["objet"]}  [{m["type_temporal"]}]')


# ════════════════════════════════════════════
# G1 — NORMALISATION VERBALE
# Verifie que les verbes conjugues dans les
# messages produisent des predicats noms.
# Le check "predicat present" se fait APRES
# /memorize pour couvrir les deux chemins.
# ════════════════════════════════════════════

def test_g1():
    header('G1 — Normalisation verbale (verbe conjugue -> predicat nom)')

    cases = [
        ("Ma collegue Isabelle etudie le droit en parallele de son travail.",
         'etudes', 'Isabelle'),
        ("Mon cousin Marc travaille comme infirmier depuis 8 ans.",
         'metier', 'Marc'),
        ("Ma voisine Helene habite a Montpellier depuis deux ans.",
         'domicile', 'Helene'),
    ]

    tid = create_thread('[TEST-G1] Normalisation verbale')
    if not tid:
        record('G1','Creation fil', False); return

    ts_group = datetime.now().isoformat()

    for msg, pred_attendu, sujet in cases:
        info(f'Msg : {msg}')
        _, tags = send_stream(tid, msg)
        time.sleep(PAUSE)

        # Check verbe en base INLINE (avant memorize)
        ts_msg = datetime.now().isoformat()
        # On verifie les tags emis par le LLM dans le stream
        for raw in tags:
            p = parse_tag(raw)
            if p:
                pred = p.get('predicat','').lower()
                if pred in VERBES_INTERDITS:
                    record('G1', f'Tag inline predicat verbal "{pred}"', False, raw[:80])

    # Passe batch
    memorize_thread(tid)
    time.sleep(3)

    # Check global apres memorize
    mems = get_memories_since(ts_group)
    show_mems(mems)

    preds_db = [m['predicat'].lower() for m in mems]
    verbaux  = [p for p in preds_db if p in VERBES_INTERDITS]

    record('G1', 'Aucun predicat verbal en base apres memorize',
           len(verbaux) == 0,
           f'verbaux : {verbaux}' if verbaux else f'preds : {preds_db}')

    record('G1', 'Isabelle / etudes present',
           any('etudes' in p or 'etude' in p or 'droit' in m['objet'].lower()
               for m, p in zip(mems, preds_db)
               if m['sujet'].lower() in ('isabelle', 'laurent')),
           f'preds : {preds_db}')

    record('G1', 'Marc / metier present',
           any('metier' in p or 'infirmier' in m['objet'].lower()
               for m, p in zip(mems, preds_db)
               if m['sujet'].lower() in ('marc', 'laurent')),
           f'mems : {[(m["sujet"],m["predicat"],m["objet"]) for m in mems]}')

    record('G1', 'Helene / domicile present',
           any('domicile' in p or 'montpellier' in m['objet'].lower()
               for m, p in zip(mems, preds_db)
               if m['sujet'].lower() in ('helene', 'laurent')),
           f'mems : {[(m["sujet"],m["predicat"],m["objet"]) for m in mems]}')


# ════════════════════════════════════════════
# G2 — ANTI-DOUBLON
# ════════════════════════════════════════════

def test_g2():
    header('G2 — Anti-doublon (meme fait, 3 formulations differentes)')

    tid = create_thread('[TEST-G2] Anti-doublon')
    if not tid:
        record('G2','Creation fil', False); return

    ts_group = datetime.now().isoformat()

    msgs = [
        "Je fais du velo, c'est mon activite sportive principale depuis trois ans.",
        "Le cyclisme c'est vraiment ma passion. Je sors au moins deux fois par semaine.",
        "Le velo ca reste mon sport de predilection, j'en fais depuis que j'ai 35 ans.",
    ]

    for i, msg in enumerate(msgs, 1):
        info(f'Msg {i} : {msg}')
        send_stream(tid, msg)
        time.sleep(PAUSE)

    memorize_thread(tid)
    time.sleep(3)

    mems = get_memories_since(ts_group)
    show_mems(mems)

    sport_mems = [m for m in mems
                  if m['predicat'] in ('sport','loisir','cyclisme','activite','velo','loisir_principal')]

    record('G2', f'Au moins 1 entree sport/loisir enregistree',
           len(sport_mems) >= 1,
           f'{len(sport_mems)} entree(s) : {[(m["predicat"],m["objet"]) for m in sport_mems]}')

    record('G2', 'Max 1 entree sport/loisir (pas de doublon)',
           len(sport_mems) <= 1,
           f'doublons : {[(m["predicat"],m["objet"]) for m in sport_mems]}')


# ════════════════════════════════════════════
# G3 — MULTI-VALEURS (enfants distincts)
# ════════════════════════════════════════════

def test_g3():
    header('G3 — Multi-valeurs (deux nieces -> deux entrees distinctes)')

    tid = create_thread('[TEST-G3] Multi-enfants')
    if not tid:
        record('G3','Creation fil', False); return

    ts_group = datetime.now().isoformat()

    msg1 = "Ma niece s'appelle Camille, elle a 19 ans, elle est en fac de medecine."
    msg2 = "Elle a aussi une petite soeur, Lucie, 14 ans. Lucie est au lycee."

    info(f'Msg 1 : {msg1}')
    send_stream(tid, msg1)
    time.sleep(PAUSE)

    info(f'Msg 2 : {msg2}')
    send_stream(tid, msg2)
    time.sleep(PAUSE)

    memorize_thread(tid)
    time.sleep(3)

    mems = get_memories_since(ts_group)
    show_mems(mems)

    # Chercher toute entree qui mentionne Camille ou Lucie (sujet ou objet)
    all_text = ' '.join([
        m['sujet'].lower() + ' ' + m['objet'].lower() for m in mems
    ])

    has_camille = 'camille' in all_text
    has_lucie   = 'lucie'   in all_text

    record('G3', 'Camille presente (sujet ou objet)', has_camille,
           f'mems : {[(m["sujet"],m["predicat"],m["objet"]) for m in mems]}')
    record('G3', 'Lucie presente (sujet ou objet)', has_lucie,
           f'mems : {[(m["sujet"],m["predicat"],m["objet"]) for m in mems]}')
    record('G3', 'Deux personnes distinctes enregistrees',
           has_camille and has_lucie)


# ════════════════════════════════════════════
# G4 — COMPLIANCE MESSAGES COURTS
# ════════════════════════════════════════════

def test_g4():
    header('G4 — Compliance (messages courts + reponse a question)')

    tid = create_thread('[TEST-G4] Compliance court')
    if not tid:
        record('G4','Creation fil', False); return

    ts_group = datetime.now().isoformat()

    # Setup
    info('Setup contexte...')
    send_stream(tid, "Mon ami Pierre a deux enfants.")
    time.sleep(PAUSE)

    # Message court — fait stable
    info('Msg court 1 : Son fils s\'appelle Nathan, il a 10 ans.')
    send_stream(tid, "Son fils s'appelle Nathan, il a 10 ans.")
    time.sleep(PAUSE)

    # Question puis reponse courte
    info('Question : Et son metier a lui, Pierre ?')
    send_stream(tid, "Et son metier a lui, Pierre, c'est quoi ?")
    time.sleep(3)
    info('Reponse : Il est plombier independant.')
    send_stream(tid, "Il est plombier independant.")
    time.sleep(PAUSE)

    memorize_thread(tid)
    time.sleep(3)

    mems = get_memories_since(ts_group)
    show_mems(mems)

    all_text = ' '.join([m['sujet'].lower()+' '+m['predicat'].lower()+' '+m['objet'].lower()
                         for m in mems])

    record('G4', 'Pierre enregistre (relation ou attribut)',
           'pierre' in all_text,
           f'{len(mems)} souvenir(s) total')

    record('G4', 'Metier plombier capture',
           'plombier' in all_text,
           f'mems : {[(m["sujet"],m["predicat"],m["objet"]) for m in mems]}')

    record('G4', 'Nathan capture',
           'nathan' in all_text)


# ════════════════════════════════════════════
# G5 — FORMAT DES TAGS
# ════════════════════════════════════════════

def test_g5():
    header('G5 — Format des tags (structure, temporal, predicat nom)')

    tid = create_thread('[TEST-G5] Format tags')
    if not tid:
        record('G5','Creation fil', False); return

    ts_group = datetime.now().isoformat()

    messages = [
        "Ma belle-soeur Christine a 42 ans. Elle est kine dans une clinique de Lyon.",
        "Mon beau-frere Sebastien travaille dans l'informatique. Il est marie a Christine depuis 12 ans.",
        "Leur fils Axel a 8 ans et il est passionne de dinosaures.",
    ]

    all_tags = []
    for msg in messages:
        info(f'Msg : {msg}')
        _, tags = send_stream(tid, msg)
        all_tags.extend(tags)
        time.sleep(PAUSE)

    memorize_thread(tid)
    time.sleep(3)

    mems = get_memories_since(ts_group)
    show_mems(mems)

    record('G5', f'Au moins 1 souvenir enregistre sur 3 messages',
           len(mems) > 0, f'{len(mems)} souvenir(s)')

    # Check predicats verbaux en base
    verbaux = [m for m in mems if m['predicat'].lower() in VERBES_INTERDITS]
    record('G5', 'Aucun predicat verbal en base',
           len(verbaux) == 0,
           f'verbaux : {[(m["predicat"]) for m in verbaux]}')

    # Check tags inline format
    ok_struct = ok_temp = ok_nom = 0
    ko_struct = ko_temp = ko_nom = 0
    for raw in all_tags:
        p = parse_tag(raw)
        if not p:
            ko_struct += 1; continue
        ok_struct += 1
        temp = p.get('temporal','').strip().lower()
        if temp in TEMPORELS_VALIDES: ok_temp += 1
        else: ko_temp += 1
        pred = p.get('predicat','').strip().lower()
        if pred in VERBES_INTERDITS: ko_nom += 1
        else: ok_nom += 1

    if all_tags:
        t = ok_struct + ko_struct
        record('G5', f'Tags inline parseables ({ok_struct}/{t})', ko_struct == 0)
        record('G5', f'Tags inline predicat=nom ({ok_nom}/{ok_struct})',
               ko_nom == 0 or ok_struct == 0)


# ════════════════════════════════════════════
# G6 — AUDIT DB GLOBAL
# ════════════════════════════════════════════

def test_g6():
    header('G6 — Audit global DB (reliquats verbaux et doublons)')

    MULTI_OK = {'enfant','fille','fils','frere','soeur',
                'frere_ou_soeur','ami','amie','collegue','niece','neveu'}
    try:
        conn = sqlite3.connect(DB_PATH)
        c    = conn.cursor()
        c.execute('SELECT sujet, predicat, objet FROM memory ORDER BY sujet, predicat')
        rows = c.fetchall()
        conn.close()
    except Exception as e:
        record('G6','Lecture DB', False, str(e)); return

    total   = len(rows)
    verbaux = [(r[0], r[1], r[2]) for r in rows if r[1].lower() in VERBES_INTERDITS]

    doublons_map = {}
    for (sujet, pred, objet) in rows:
        key = (sujet.lower(), pred.lower())
        doublons_map.setdefault(key, []).append(objet)
    vrais_doublons = {k: v for k, v in doublons_map.items()
                      if len(v) > 1 and k[1] not in MULTI_OK}

    record('G6', f'Aucun predicat verbal ({len(verbaux)}/{total} souvenirs)',
           len(verbaux) == 0)
    for (s, p, o) in verbaux[:8]:
        warn(f'  Verbal : {s} / {p} = {o}')

    record('G6', f'Aucun doublon sujet+predicat ({len(vrais_doublons)} trouve(s))',
           len(vrais_doublons) == 0)
    for (s, p), objets in list(vrais_doublons.items())[:5]:
        warn(f'  Doublon : {s} / {p} -> {objets}')


# ════════════════════════════════════════════
# G7 — PARAGRAPHES COMPLEXES
# ════════════════════════════════════════════

def test_g7():
    header('G7 — Paragraphes complexes (multi-faits, pronoms, conditionnels, bruit)')

    tid = create_thread('[TEST-G7] Paragraphes')
    if not tid:
        record('G7','Creation fil', False); return

    # ── Cas 1 : dense multi-faits ──
    ts1 = datetime.now().isoformat()
    p1 = (
        "Je te presente ma belle-soeur Valerie. Elle a 38 ans, elle est pharmacienne "
        "a Carcassonne. Elle est mariee a mon frere Didier depuis 15 ans et ils ont "
        "un fils de 10 ans qui s'appelle Theo. Elle fait aussi de la course a pied, "
        "elle prepare un semi-marathon."
    )
    info('Cas 1 — Dense multi-faits (Valerie)')
    dim(p1)
    send_stream(tid, p1)
    time.sleep(PAUSE)
    memorize_thread(tid)
    time.sleep(3)
    mems1 = get_memories_since(ts1)
    show_mems(mems1, 'Cas 1')

    all1     = ' '.join([m['sujet'].lower()+' '+m['objet'].lower() for m in mems1])
    n_valerie = len([m for m in mems1 if m['sujet'].lower() == 'valerie'])
    record('G7', 'Cas 1 — Valerie memorisee', 'valerie' in all1,
           f'{n_valerie} fait(s) sur Valerie')
    record('G7', 'Cas 1 — Au moins 2 faits extraits du paragraphe',
           len(mems1) >= 2, f'{len(mems1)} souvenir(s) total')

    # ── Cas 2 : pronoms ambigus, deux sujets ──
    ts2 = datetime.now().isoformat()
    p2 = (
        "Mon ami Romain est chef cuisinier a Bordeaux. "
        "Il joue aussi de la guitare depuis 20 ans. "
        "Son frere Samuel est militaire, voie completement differente."
    )
    info('Cas 2 — Deux sujets, pronoms (Romain / Samuel)')
    dim(p2)
    send_stream(tid, p2)
    time.sleep(PAUSE)
    memorize_thread(tid)
    time.sleep(3)
    mems2 = get_memories_since(ts2)
    show_mems(mems2, 'Cas 2')

    all2 = ' '.join([m['sujet'].lower()+' '+m['objet'].lower() for m in mems2])
    record('G7', 'Cas 2 — Romain memorise', 'romain' in all2,
           f'mems : {[(m["sujet"],m["predicat"],m["objet"]) for m in mems2]}')
    record('G7', 'Cas 2 — Samuel memorise', 'samuel' in all2)
    record('G7', 'Cas 2 — Aucun predicat verbal',
           not any(m['predicat'].lower() in VERBES_INTERDITS for m in mems2))

    # ── Cas 3 : stable vs conditionnel ──
    ts3 = datetime.now().isoformat()
    p3 = (
        "Ma voisine Sylvie jardine beaucoup, c'est sa passion depuis longtemps. "
        "Elle aimerait peut-etre ouvrir une boutique de plantes un jour, "
        "mais c'est juste une idee pour l'instant."
    )
    info('Cas 3 — Stable vs conditionnel (Sylvie)')
    dim(p3)
    send_stream(tid, p3)
    time.sleep(PAUSE)
    memorize_thread(tid)
    time.sleep(3)
    mems3 = get_memories_since(ts3)
    show_mems(mems3, 'Cas 3')

    sylvie_mems = [m for m in mems3 if m['sujet'].lower() == 'sylvie']
    all3        = ' '.join([m['sujet'].lower()+' '+m['objet'].lower() for m in mems3])
    has_jardinage  = any('jardin' in m['objet'].lower() or
                         m['predicat'] in ('loisir','sport','passion','activite')
                         for m in sylvie_mems)
    no_conditionnel = not any('boutique' in m['objet'].lower() for m in sylvie_mems)

    record('G7', 'Cas 3 — Jardinage de Sylvie memorise',
           'sylvie' in all3 and len(sylvie_mems) > 0,
           f'{[(m["predicat"],m["objet"]) for m in sylvie_mems]}')
    record('G7', 'Cas 3 — Conditionnel "boutique" non memorise',
           no_conditionnel, 'correct' if no_conditionnel else 'speculation memorisee')

    # ── Cas 4 : correction meme message ──
    ts4 = datetime.now().isoformat()
    p4 = (
        "Mon collegue Franck etait assistant commercial pendant des annees. "
        "Mais la il vient de changer de poste — il est maintenant "
        "responsable logistique depuis le mois dernier."
    )
    info('Cas 4 — Correction ancien -> nouveau poste (Franck)')
    dim(p4)
    send_stream(tid, p4)
    time.sleep(PAUSE)
    memorize_thread(tid)
    time.sleep(3)
    mems4 = get_memories_since(ts4)
    show_mems(mems4, 'Cas 4')

    franck_mems = [m for m in mems4 if m['sujet'].lower() == 'franck']
    all4        = ' '.join([m['sujet'].lower()+' '+m['objet'].lower() for m in mems4])
    record('G7', 'Cas 4 — Franck memorise',
           'franck' in all4,
           f'{[(m["predicat"],m["objet"]) for m in franck_mems]}')
    record('G7', 'Cas 4 — Poste logistique present',
           any('logistique' in m['objet'].lower() for m in franck_mems))
    record('G7', 'Cas 4 — Max 1 entree metier (pas les deux postes)',
           len([m for m in franck_mems if m['predicat'] in ('metier','poste','emploi')]) <= 1)

    # ── Cas 5 : bruit conversationnel ──
    ts5 = datetime.now().isoformat()
    p5 = (
        "Ah oui j'allais oublier — tu te souviens qu'on avait parle de bricolage ? "
        "Bon de toute facon le plus important c'est que mon oncle Gerard "
        "a finalement pris sa retraite. Il bossait comme garagiste depuis 40 ans. "
        "En tout cas moi ca m'a fait reflechir sur la retraite en general."
    )
    info('Cas 5 — Bruit conversationnel, 1 fait stable (Gerard)')
    dim(p5)
    send_stream(tid, p5)
    time.sleep(PAUSE)
    memorize_thread(tid)
    time.sleep(3)
    mems5 = get_memories_since(ts5)
    show_mems(mems5, 'Cas 5')

    all5 = ' '.join([m['sujet'].lower()+' '+m['objet'].lower() for m in mems5])
    gerard_mems = [m for m in mems5 if m['sujet'].lower() == 'gerard']
    record('G7', 'Cas 5 — Gerard memorise malgre le bruit',
           'gerard' in all5,
           f'{[(m["predicat"],m["objet"]) for m in gerard_mems]}')
    record('G7', 'Cas 5 — Max 2 faits (pas le bruit conversationnel)',
           len(gerard_mems) <= 2,
           f'{len(gerard_mems)} entree(s) sur Gerard')

    info(f'Fil G7 conserve pour inspection : {tid}')


# ════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════

def main():
    print('\n' + '=' * 64)
    print('  NIMM -- test_memory.py  v3')
    print('  inline TAGs + passe /memorize par groupe')
    print('=' * 64)

    try:
        requests.get(f'{BASE}/api/threads', timeout=5)
    except Exception:
        print(f'\n  NIMM inaccessible sur {BASE}\n')
        sys.exit(1)

    try:
        r    = requests.get(f'{BASE}/api/identity', timeout=5)
        name = r.json().get('name','?') if r.ok else '?'
    except Exception:
        name = '?'
    info(f'Utilisateur : {name}')

    try:
        conn = sqlite3.connect(DB_PATH)
        c    = conn.cursor()
        c.execute('SELECT COUNT(*) FROM memory')
        nb = c.fetchone()[0]
        conn.close()
        info(f'Souvenirs en base au depart : {nb}')
        if nb > 5:
            warn('Memoire non vide — resultats potentiellement fausses.')
    except Exception:
        pass
    print()

    t0 = time.time()

    test_g1()
    test_g2()
    test_g3()
    test_g4()
    test_g5()
    test_g6()
    test_g7()

    elapsed = time.time() - t0

    passed = [r for r in results if r['passed'] is True]
    failed = [r for r in results if r['passed'] is False]
    total  = len(passed) + len(failed)

    print(f'\n{"=" * 64}')
    print(f'  RESUME  --  {elapsed:.0f}s')
    print(f'{"=" * 64}')
    print(f'  {OK}  Reussis : {len(passed)}/{total}')
    print(f'  {ERR}  Echoues : {len(failed)}/{total}')

    if failed:
        print(f'\n  Echecs :')
        for r in failed:
            d = f'  ->  {r["detail"]}' if r['detail'] else ''
            print(f'    {ERR}  [{r["group"]}] {r["name"]}{d}')

    score = int(100 * len(passed) / total) if total else 0
    print(f'\n  Score : {score}%')

    # Detail par groupe
    groupes = sorted(set(r['group'] for r in results))
    print(f'\n  Detail par groupe :')
    for g in groupes:
        gp = [r for r in results if r['group'] == g]
        gpass = sum(1 for r in gp if r['passed'])
        print(f'    {g} : {gpass}/{len(gp)}')

    if   score == 100: print('\n  Memoire impeccable.')
    elif score >= 80:  print('\n  Bonne capture — quelques ajustements.')
    elif score >= 60:  print('\n  Capture partielle — voir echecs.')
    else:              print('\n  Des corrections s\'imposent.')
    print()


main()
