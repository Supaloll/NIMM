# -*- coding: utf-8 -*-
# ============================================
# NIMM — test_topic_f6_f8.py
# Duel F6 (meilleure connue) vs F8 (prompt DeepSeek)
# 2 formulations × 30 cas = 60 appels
# Exécution : python -X utf8 test_topic_f6_f8.py
# ============================================

import sys, os, json, asyncio, time, re
sys.stdout.reconfigure(encoding='utf-8')

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.database import init_db, get_setting
from core.engine   import call_llm

init_db()

GREEN  = '\033[92m'
RED    = '\033[91m'
YELLOW = '\033[93m'
CYAN   = '\033[96m'
BOLD   = '\033[1m'
DIM    = '\033[2m'
RESET  = '\033[0m'

# ══════════════════════════════════════════
# CONFIG PROVIDER
# ══════════════════════════════════════════

def _load_config():
    try:
        api_keys = json.loads(get_setting('api_keys', '{}'))
    except Exception:
        api_keys = {}
    try:
        routing  = json.loads(get_setting('routing', '{}'))
        provider = routing.get('chat', '')
    except Exception:
        provider = ''
    if not provider:
        for p in ('deepseek', 'anthropic', 'gemini', 'openai', 'mistral'):
            if api_keys.get(p):
                provider = p
                break
    return provider, api_keys

PROVIDER, API_KEYS = _load_config()

if not PROVIDER:
    print(RED + 'ERR: Aucun provider configuré.' + RESET)
    sys.exit(1)

print(CYAN + '\nProvider : ' + PROVIDER + RESET)

# ══════════════════════════════════════════
# RÈGLES
# ══════════════════════════════════════════

RULES = [
    {
        'id':    'F6',
        'label': 'Scribe sobre (référence)',
        'text': (
            "Tu es le scribe de l'utilisateur. "
            "Ton rôle est de noter les sujets qu'il explore, les domaines qui l'intéressent, "
            "les questions qu'il pose sur sa curiosité personnelle — pour qu'on puisse s'en souvenir plus tard.\n"
            "Quand l'utilisateur aborde un domaine (culture, sport, philosophie, art, cuisine, littérature, "
            "musique, sciences, loisirs), inscris-le en toute fin de réponse sous la forme : "
            "%%TOPIC: [mot-clé court]%%\n"
            "N'inscris rien pour les tâches pratiques : correction, traduction, calcul, code, "
            "recherche de service, question technique ponctuelle.\n"
            "Un seul %%TOPIC%% par réponse."
        ),
    },
    {
        'id':    'F8',
        'label': 'Scribe DeepSeek web',
        'text': (
            "Tu es le scribe de l'utilisateur.\n"
            "Ton rôle est de noter les sujets qu'il explore, même ceux liés à des conseils pratiques "
            "ou à un apprentissage personnel.\n"
            "Quand l'utilisateur parle d'un domaine qui pourrait l'intéresser sur le long terme "
            "(sport, santé, lecture, musique, philosophie, art, littérature, cuisine, loisirs, "
            "développement personnel, culture), inscris-le en toute fin de réponse sous la forme :\n"
            "%%TOPIC: [mot-clé court]%%\n"
            "Exceptions (ne rien inscrire) :\n"
            "- pure logistique sans valeur durable (\"où acheter X\", \"tarif\", \"horaire\")\n"
            "- correction de texte, traduction ponctuelle, code, calcul, recherche web très spécifique et unique\n"
            "Même une question pratique comme \"par où commencer le sport\" ou "
            "\"que lire de François Cheng\" → %%TOPIC%% obligatoire.\n"
            "Un seul %%TOPIC%% par réponse."
        ),
    },
    {
        'id':    'F9',
        'label': 'Scribe narratif / immersif',
        'text': (
            "Imagine une vieille bibliothèque silencieuse. Toi, tu es le scribe attitré d'un explorateur curieux.\n"
            "L'explorateur (l'utilisateur) te parle de ses découvertes, de ses doutes, de ses envies d'apprendre "
            "— parfois même de petits riens du quotidien qui pourraient devenir des passions.\n"
            "À la fin de chaque réponse, avant le silence, tu notes sur un carnet :\n"
            "%%TOPIC: [un mot-clé]%%\n"
            "Tu notes tout ce qui pourrait ressembler à un territoire à explorer plus tard :\n"
            "- un loisir (« par où commencer le sport »)\n"
            "- une passion naissante (« François Cheng »)\n"
            "- une curiosité (« le jazz »)\n"
            "- une quête personnelle (« améliorer ma mémoire »)\n"
            "Tu ne notes pas les tâches sans lendemain : corriger une phrase, traduire un mot, "
            "un calcul, un code, un prix, un horaire.\n"
            "Un seul sujet par réponse. Un petit mot-clé suffit. Sois fidèle."
        ),
    },
]

# ══════════════════════════════════════════
# CAS DE TEST
# ══════════════════════════════════════════

CASES = [
    # ── SHOULD_TAG ────────────────────────────────────────────────────────────
    {'id': 'T01', 'expect': 'TAG',    'label': 'Podcasts foot / CdM',              'msg': "Je cherche des podcasts foot pour me mettre à jour avant la coupe du monde — noms de joueurs, clubs, transferts."},
    {'id': 'T02', 'expect': 'TAG',    'label': 'François Cheng / littérature',     'msg': "Tu connais François Cheng ? J'aimerais lire ses œuvres, par où commencer ?"},
    {'id': 'T03', 'expect': 'TAG',    'label': 'Histoire Cathares',                'msg': "Je commence à m'intéresser à l'histoire des Cathares et du pays cathare. C'est fascinant."},
    {'id': 'T04', 'expect': 'TAG',    'label': 'SF récente',                       'msg': "Quels sont les meilleurs romans de science-fiction parus ces 5 dernières années ?"},
    {'id': 'T05', 'expect': 'TAG',    'label': 'Apprendre la guitare',             'msg': "Je veux apprendre la guitare acoustique. Je suis débutant complet, par où je commence ?"},
    {'id': 'T06', 'expect': 'TAG',    'label': 'Stoïcisme',                        'msg': "Parle-moi du stoïcisme — les idées principales, les auteurs à lire."},
    {'id': 'T07', 'expect': 'TAG',    'label': 'Cuisine japonaise',                'msg': "Je veux apprendre à cuisiner japonais à la maison. Quels plats pour débuter ?"},
    {'id': 'T08', 'expect': 'TAG',    'label': 'Astronomie / trous noirs',         'msg': "Je suis en train de lire sur les trous noirs. C'est quoi exactement un horizon des événements ?"},
    {'id': 'T09', 'expect': 'TAG',    'label': 'Jazz / Miles Davis',               'msg': "Je découvre le jazz. Je commence par Miles Davis, tu me conseilles quel album ?"},
    {'id': 'T10', 'expect': 'TAG',    'label': 'Randonnée / Pyrénées',             'msg': "Je veux faire de la randonnée dans les Pyrénées cet été. Quels massifs pour un niveau intermédiaire ?"},
    {'id': 'T11', 'expect': 'TAG',    'label': 'Photographie argentique',          'msg': "J'ai trouvé un vieux Canon AE-1 dans un grenier. J'ai envie de me mettre à la photo argentique."},
    {'id': 'T12', 'expect': 'TAG',    'label': 'Bouddhisme zen',                   'msg': "C'est quoi la méditation zen ? Différence avec le bouddhisme tibétain ?"},
    {'id': 'T13', 'expect': 'TAG',    'label': 'Impressionnisme',                  'msg': "Parle-moi de l'impressionnisme — les peintres, les caractéristiques du mouvement."},
    {'id': 'T14', 'expect': 'TAG',    'label': 'Taoïsme',                          'msg': "C'est quoi le taoïsme ? Les grandes idées."},
    {'id': 'T15', 'expect': 'TAG',    'label': 'Polar français',                   'msg': "Quels sont les meilleurs auteurs de polar français en ce moment ?"},
    {'id': 'T16', 'expect': 'TAG',    'label': 'Follow-up proposition LLM',        'msg': "Le premier que tu m'as cité, tu peux me donner plus de détails dessus ?"},
    {'id': 'T17', 'expect': 'TAG',    'label': 'Par où commencer (escalade)',       'msg': "Je veux me mettre à l'escalade. Par où je commence, quel matériel ?"},
    {'id': 'T18', 'expect': 'TAG',    'label': 'Kubrick / cinéma',                 'msg': "Tu me conseilles des films de Kubrick à voir en priorité ?"},

    # ── SHOULD_NOT_TAG ────────────────────────────────────────────────────────
    {'id': 'N01', 'expect': 'NO_TAG', 'label': 'Fuite évier (réparation)',         'msg': "Comment réparer une fuite sous l'évier ? Le joint est usé."},
    {'id': 'N02', 'expect': 'NO_TAG', 'label': 'Traduction texte',                 'msg': "Traduis ce texte en anglais : 'La réunion est reportée à demain matin.'"},
    {'id': 'N03', 'expect': 'NO_TAG', 'label': 'Recherche restaurant',             'msg': "Cherche-moi les meilleurs restaurants dans l'Aude."},
    {'id': 'N04', 'expect': 'NO_TAG', 'label': 'Epub livres scolaires',            'msg': "Comment avoir les livres scolaires en format epub ? C'est pour ma fille en terminale."},
    {'id': 'N05', 'expect': 'NO_TAG', 'label': 'Code Python tri à bulles',         'msg': "Écris-moi un tri à bulles en Python avec des commentaires."},
    {'id': 'N06', 'expect': 'NO_TAG', 'label': 'Heure à Tokyo',                    'msg': "C'est quelle heure à Tokyo en ce moment ?"},
    {'id': 'N07', 'expect': 'NO_TAG', 'label': 'Correction de texte',              'msg': "Corrige les fautes dans ce texte : 'Je suis aller au marché hier et j'ai acheter des légume.'"},
    {'id': 'N08', 'expect': 'NO_TAG', 'label': 'Calcul surface pièce',             'msg': "Ma pièce fait 4,5m sur 3,2m. C'est combien de m² ?"},
    {'id': 'N09', 'expect': 'NO_TAG', 'label': 'Route A9 / travaux',               'msg': "Parle-moi de la route A9 entre Montpellier et Perpignan, y a des travaux ?"},
    {'id': 'N10', 'expect': 'NO_TAG', 'label': 'Code erreur P0300',                'msg': "C'est quoi le code erreur P0300 sur un moteur diesel ?"},

    # ── AMBIGUOUS ─────────────────────────────────────────────────────────────
    {'id': 'A01', 'expect': 'AMBIGUOUS', 'label': 'Capitale du Japon',             'msg': "C'est quoi la capitale du Japon ?"},
    {'id': 'A02', 'expect': 'AMBIGUOUS', 'label': 'Moteur diesel (comment ça marche)', 'msg': "Comment fonctionne un moteur diesel ?"},
]

# ══════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════

TOPIC_RE = re.compile(r'%%TOPIC\s*:', re.IGNORECASE)

async def call(system, user_msg):
    return await call_llm(
        messages      = [{'role': 'user', 'content': user_msg}],
        provider      = PROVIDER,
        system_prompt = system,
        max_tokens    = 300,
        temperature   = 0.2,
        api_keys      = API_KEYS,
    )

def has_topic(r): return bool(TOPIC_RE.search(r))

def extract_topic(r):
    m = re.search(r'%%TOPIC\s*:\s*([^%\n]+)', r, re.IGNORECASE)
    return m.group(1).strip() if m else ''

def verdict(case, response):
    if case['expect'] == 'AMBIGUOUS': return 'AMBIGUOUS'
    tagged = has_topic(response)
    if case['expect'] == 'TAG':    return 'OK' if tagged else 'MISS'
    else:                          return 'OK' if not tagged else 'SPURIOUS'

# ══════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════

async def run_all():
    results = {r['id']: {} for r in RULES}
    total   = len(RULES) * len(CASES)
    count   = 0

    for rule in RULES:
        for case in CASES:
            count += 1
            label = f"{rule['id']}×{case['id']}"
            sys.stdout.write(f"  [{count:03d}/{total}] {label:<12} {case['label'][:38]:<38} ")
            sys.stdout.flush()
            t0 = time.time()
            try:
                resp = await call(rule['text'], case['msg'])
                v    = verdict(case, resp)
                topic = extract_topic(resp) if has_topic(resp) else ''
            except Exception as e:
                resp, v, topic = '', 'ERR', ''
                print(f"ERR — {str(e)[:50]}")
                results[rule['id']][case['id']] = (v, resp)
                continue

            elapsed = time.time() - t0
            if   v == 'OK':        icon = GREEN  + 'OK      ' + RESET
            elif v == 'MISS':      icon = RED    + 'MISS    ' + RESET
            elif v == 'SPURIOUS':  icon = YELLOW + 'SPURIOUS' + RESET
            elif v == 'AMBIGUOUS': icon = CYAN   + 'AMBIG   ' + RESET
            else:                  icon = RED    + 'ERR     ' + RESET

            topic_str = f'→ {topic[:35]}' if topic else ''
            print(f"{icon}  ({elapsed:.1f}s)  {DIM}{topic_str}{RESET}")
            results[rule['id']][case['id']] = (v, resp)

    return results

# ══════════════════════════════════════════
# RAPPORT
# ══════════════════════════════════════════

def print_report(results):
    tag_ids  = [c['id'] for c in CASES if c['expect'] == 'TAG']
    ntag_ids = [c['id'] for c in CASES if c['expect'] == 'NO_TAG']
    amb_ids  = [c['id'] for c in CASES if c['expect'] == 'AMBIGUOUS']

    print('\n\n' + BOLD + '═' * 70 + RESET)
    print(BOLD + '  RAPPORT — F6 vs F8 (DeepSeek web) vs F9 (narratif)' + RESET)
    print(BOLD + '═' * 70 + RESET)
    print(f"  {'Formulation':<35} {'TAG ok':>8} {'NO_TAG ok':>10} {'Global':>8}")
    print('  ' + '─' * 65)

    for rule in RULES:
        r = results[rule['id']]
        tag_ok  = sum(1 for cid in tag_ids  if r.get(cid,('',''))[0] == 'OK')
        ntag_ok = sum(1 for cid in ntag_ids if r.get(cid,('',''))[0] == 'OK')
        total_e = len(tag_ids) + len(ntag_ids)
        glob    = tag_ok + ntag_ok

        def _c(p): return GREEN if p==100 else (YELLOW if p>=75 else RED)

        tp  = int(100*tag_ok /len(tag_ids))  if tag_ids  else 0
        np_ = int(100*ntag_ok/len(ntag_ids)) if ntag_ids else 0
        gp  = int(100*glob   /total_e)       if total_e  else 0

        print(
            f"  {rule['id']} {rule['label']:<32}"
            f" {_c(tp)}{tag_ok}/{len(tag_ids)} ({tp:3d}%){RESET}"
            f"  {_c(np_)}{ntag_ok}/{len(ntag_ids)} ({np_:3d}%){RESET}"
            f"  {_c(gp)}{glob}/{total_e} ({gp:3d}%){RESET}"
        )

    # Détail erreurs
    print('\n\n' + BOLD + '  ERREURS / SPURIOUS PAR FORMULATION' + RESET)
    print('  ' + '─' * 65)
    for rule in RULES:
        errs = []
        for case in CASES:
            if case['expect'] == 'AMBIGUOUS': continue
            v, resp = results[rule['id']].get(case['id'], ('ERR',''))
            if v != 'OK':
                t = extract_topic(resp) if resp else ''
                note = f" (émis: '{t}')" if t else ''
                color = RED if v == 'MISS' else YELLOW
                errs.append(f"    {color}{v}{RESET}  {case['id']} {case['label']}{note}")
        print(f"\n  {BOLD}{rule['id']} — {rule['label']}{RESET}")
        if errs:
            for e in errs: print(e)
        else:
            print(f"    {GREEN}Aucune erreur{RESET}")

    # Ambigus
    print('\n\n' + BOLD + '  CAS AMBIGUS (observation)' + RESET)
    print('  ' + '─' * 65)
    for rule in RULES:
        print(f'\n  {BOLD}{rule["id"]}{RESET}')
        for cid in amb_ids:
            v, resp = results[rule['id']].get(cid, ('ERR',''))
            case    = next(c for c in CASES if c['id'] == cid)
            t       = extract_topic(resp) if resp else ''
            tagged  = f"%%TOPIC%% : '{t}'" if t else 'pas de tag'
            print(f"    {case['id']} {case['label']:<42} → {CYAN}{tagged}{RESET}")

    # Conclusion
    print('\n\n' + BOLD + '═' * 70 + RESET)
    best = max(RULES, key=lambda ru: sum(
        1 for cid in tag_ids+ntag_ids
        if results[ru['id']].get(cid,('',''))[0] == 'OK'
    ))
    print(BOLD + f'  ★ Meilleure : {best["id"]} — {best["label"]}' + RESET)
    print('\n' + BOLD + '═' * 70 + RESET + '\n')

# ══════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════

async def main():
    n_eval = sum(1 for c in CASES if c['expect'] != 'AMBIGUOUS')
    print(BOLD + '\n' + '═' * 70 + RESET)
    print(BOLD + '  NIMM — Duel F6 vs F8' + RESET)
    print(f'  3 formulations × {len(CASES)} cas ({n_eval} évalués, {len(CASES)-n_eval} ambigus)')
    print(f'  Référence F6 : 12/18 TAG (66%), 7/10 NO_TAG (70%), global 67%')
    print(BOLD + '═' * 70 + RESET + '\n')
    results = await run_all()
    print_report(results)

if __name__ == '__main__':
    asyncio.run(main())
