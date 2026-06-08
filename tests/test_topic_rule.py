# -*- coding: utf-8 -*-
# ============================================
# NIMM — test_topic_rule.py
# Calibration de la règle %%TOPIC%%
#
# Objectif : trouver la formulation de règle
# qui fait émettre %%TOPIC%% exactement quand
# il faut, et jamais quand il ne faut pas.
#
# Structure :
#   3 formulations de règle × 22 cas
#   = 66 évaluations
#
# Cas SHOULD_TAG    (12) → %%TOPIC%% attendu
# Cas SHOULD_NOT    (8)  → %%TOPIC%% interdit
# Cas AMBIGUOUS     (2)  → non évalués auto
#
# Exécution : python -X utf8 test_topic_rule.py
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
# RÈGLES À TESTER — 4 formulations
# ══════════════════════════════════════════

RULES = [
    {
        'id':    'F1',
        'label': 'Courte / binaire',
        'text': (
            "Si la conversation porte sur l'exploration d'un domaine (culturel, "
            "intellectuel, sportif, artistique, culinaire, personnel), "
            "ajoute %%TOPIC: [mot-clé court]%% en toute fin de réponse. "
            "Sinon, n'écris jamais %%TOPIC%%.\n"
            "Exploration = l'utilisateur s'intéresse à un sujet pour lui-même.\n"
            "Tâche utilitaire = l'utilisateur veut accomplir quelque chose de précis et ponctuel.\n"
            "Maximum un seul %%TOPIC%% par réponse."
        ),
    },
    {
        'id':    'F2',
        'label': 'Avec exemples négatifs',
        'text': (
            "En fin de réponse, ajoute %%TOPIC: [mot-clé court]%% si et seulement si "
            "le message révèle un intérêt pour un domaine — l'utilisateur explore un sujet "
            "pour sa curiosité, sa culture ou son plaisir personnel.\n"
            "N'ajoute JAMAIS %%TOPIC%% pour : correction de texte, traduction, "
            "demande technique ou code, recherche de service pratique (restaurant, horaire, adresse), "
            "question factuelle isolée, tâche administrative.\n"
            "Maximum un seul %%TOPIC%% par réponse. "
            "Le mot-clé doit être court (2-3 mots max) et représenter le domaine, pas l'action."
        ),
    },
    {
        'id':    'F3',
        'label': 'Question de test interne',
        'text': (
            "Avant de répondre, pose-toi cette question : "
            "'L'utilisateur explore-t-il un domaine par curiosité ou intérêt personnel ?' "
            "Si oui → ajoute %%TOPIC: [mot-clé court]%% en toute fin de réponse. "
            "Si non (tâche, correction, recherche pratique, question technique) → n'écris pas %%TOPIC%%.\n"
            "Un seul %%TOPIC%% maximum. Mot-clé : 2-3 mots, domaine général (ex: 'littérature chinoise', "
            "'football', 'stoïcisme', 'guitare acoustique')."
        ),
    },
    {
        'id':    'F4',
        'label': 'Avec signal implicite explicité',
        'text': (
            "En fin de réponse, ajoute %%TOPIC: [mot-clé court]%% si le message révèle "
            "un intérêt pour un domaine.\n"
            "Un intérêt est révélé dans deux cas :\n"
            "1. Déclaration explicite : 'je m'intéresse à', 'je découvre', 'je commence à', "
            "'j'ai envie de', 'je lis sur'.\n"
            "2. Demande de recommandation sur un domaine culturel, intellectuel, sportif, "
            "artistique ou culinaire : 'quels sont les meilleurs X', 'par où commencer avec X', "
            "'tu connais X', 'conseille-moi sur X'.\n"
            "N'ajoute JAMAIS %%TOPIC%% pour : correction, traduction, code, calcul, "
            "recherche de service pratique (restaurant, horaire, adresse), question factuelle isolée.\n"
            "Un seul %%TOPIC%% par réponse. Mot-clé : 2-3 mots, domaine général."
        ),
    },
    {
        'id':    'F5',
        'label': 'F1 + formes implicites listées',
        'text': (
            "Si la conversation porte sur l'exploration d'un domaine (culturel, "
            "intellectuel, sportif, artistique, culinaire, personnel), "
            "ajoute %%TOPIC: [mot-clé court]%% en toute fin de réponse. "
            "Sinon, n'écris jamais %%TOPIC%%.\n"
            "Exploration = l'utilisateur s'intéresse à un sujet pour lui-même.\n"
            "Tâche utilitaire = l'utilisateur veut accomplir quelque chose de précis et ponctuel.\n"
            "Ces formulations révèlent aussi un intérêt → ajoute %%TOPIC%% : "
            "'quels sont les meilleurs X', 'parle-moi de X', "
            "'c'est quoi X', 'par où commencer avec X', 'conseille-moi sur X', "
            "'tu me conseilles X', 'le premier que tu as cité'.\n"
            "Maximum un seul %%TOPIC%% par réponse."
        ),
    },
    {
        'id':    'F6',
        'label': 'Scribe sobre',
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
        'id':    'F7',
        'label': 'Scribe immersif',
        'text': (
            "Tu es à la fois l'assistant et le greffier de l'utilisateur. "
            "Chaque fois qu'il t'adresse une question, tu réponds — et tu notes dans ton registre "
            "les sujets qui semblent l'intéresser, les domaines qu'il explore, les curiosités qui reviennent.\n"
            "Ce registre te permettra de te souvenir : 'il m'a parlé de jazz', "
            "'il cherche des livres sur les Cathares', 'il s'intéresse à la photographie argentique'.\n"
            "Pour inscrire un sujet dans ton registre, écris en toute fin de ta réponse : "
            "%%TOPIC: [domaine en 2-3 mots]%%\n"
            "N'inscris rien dans ton registre pour les demandes purement utilitaires : "
            "corriger un texte, traduire, calculer, coder, trouver un service pratique.\n"
            "Un seul %%TOPIC%% par réponse. Si tu doutes, n'inscris pas."
        ),
    },
]

# ══════════════════════════════════════════
# CAS DE TEST
# ══════════════════════════════════════════

CASES = [
    # ── SHOULD_TAG — intérêt révélé ───────────────────────────────────────────
    {
        'id':       'T01',
        'expect':   'TAG',
        'label':    'Podcasts foot / CdM',
        'msg':      "Je cherche des podcasts foot pour me mettre à jour avant la coupe du monde — noms de joueurs, clubs, transferts.",
    },
    {
        'id':       'T02',
        'expect':   'TAG',
        'label':    'François Cheng / littérature',
        'msg':      "Tu connais François Cheng ? J'aimerais lire ses œuvres, par où commencer ?",
    },
    {
        'id':       'T03',
        'expect':   'TAG',
        'label':    'Histoire Cathares',
        'msg':      "Je commence à m'intéresser à l'histoire des Cathares et du pays cathare. C'est fascinant.",
    },
    {
        'id':       'T04',
        'expect':   'TAG',
        'label':    'SF récente',
        'msg':      "Quels sont les meilleurs romans de science-fiction parus ces 5 dernières années ?",
    },
    {
        'id':       'T05',
        'expect':   'TAG',
        'label':    'Apprendre la guitare',
        'msg':      "Je veux apprendre la guitare acoustique. Je suis débutant complet, par où je commence ?",
    },
    {
        'id':       'T06',
        'expect':   'TAG',
        'label':    'Stoïcisme',
        'msg':      "Parle-moi du stoïcisme — les idées principales, les auteurs à lire.",
    },
    {
        'id':       'T07',
        'expect':   'TAG',
        'label':    'Cuisine japonaise',
        'msg':      "Je veux apprendre à cuisiner japonais à la maison. Quels plats pour débuter ?",
    },
    {
        'id':       'T08',
        'expect':   'TAG',
        'label':    'Astronomie / trous noirs',
        'msg':      "Je suis en train de lire sur les trous noirs. C'est quoi exactement un horizon des événements ?",
    },
    {
        'id':       'T09',
        'expect':   'TAG',
        'label':    'Jazz / Miles Davis',
        'msg':      "Je découvre le jazz. Je commence par Miles Davis, tu me conseilles quel album ?",
    },
    {
        'id':       'T10',
        'expect':   'TAG',
        'label':    'Randonnée / Pyrénées',
        'msg':      "Je veux faire de la randonnée dans les Pyrénées cet été. Quels massifs pour un niveau intermédiaire ?",
    },
    {
        'id':       'T11',
        'expect':   'TAG',
        'label':    'Photographie argentique',
        'msg':      "J'ai trouvé un vieux Canon AE-1 dans un grenier. J'ai envie de me mettre à la photo argentique.",
    },
    {
        'id':       'T12',
        'expect':   'TAG',
        'label':    'Bouddhisme zen',
        'msg':      "C'est quoi concrètement la méditation zen ? Différence avec le bouddhisme tibétain ?",
    },

    # ── SHOULD_NOT_TAG — tâches utilitaires ───────────────────────────────────
    {
        'id':       'N01',
        'expect':   'NO_TAG',
        'label':    'Fuite évier (réparation)',
        'msg':      "Comment réparer une fuite sous l'évier ? Le joint est usé.",
    },
    {
        'id':       'N02',
        'expect':   'NO_TAG',
        'label':    'Traduction texte',
        'msg':      "Traduis ce texte en anglais : 'La réunion est reportée à demain matin.'",
    },
    {
        'id':       'N03',
        'expect':   'NO_TAG',
        'label':    'Recherche restaurant',
        'msg':      "Cherche-moi les meilleurs restaurants dans l'Aude.",
    },
    {
        'id':       'N04',
        'expect':   'NO_TAG',
        'label':    'Epub livres scolaires (pratique)',
        'msg':      "Comment avoir les livres scolaires en format epub ? C'est pour ma fille en terminale.",
    },
    {
        'id':       'N05',
        'expect':   'NO_TAG',
        'label':    'Code Python tri à bulles',
        'msg':      "Écris-moi un tri à bulles en Python avec des commentaires.",
    },
    {
        'id':       'N06',
        'expect':   'NO_TAG',
        'label':    'Heure à Tokyo',
        'msg':      "C'est quelle heure à Tokyo en ce moment ?",
    },
    {
        'id':       'N07',
        'expect':   'NO_TAG',
        'label':    'Correction de texte',
        'msg':      "Corrige les fautes dans ce texte : 'Je suis aller au marché hier et j'ai acheter des légume.'",
    },
    {
        'id':       'N08',
        'expect':   'NO_TAG',
        'label':    'Calcul surface pièce',
        'msg':      "Ma pièce fait 4,5m sur 3,2m. C'est combien de m² ?",
    },

    # ── SHOULD_TAG — nouveaux cas patterns résistants ─────────────────────────
    {
        'id':       'T13',
        'expect':   'TAG',
        'label':    'Parle-moi de X (domaine culturel)',
        'msg':      "Parle-moi de l'impressionnisme — les peintres, les caractéristiques du mouvement.",
    },
    {
        'id':       'T14',
        'expect':   'TAG',
        'label':    'C\'est quoi X (philosophie)',
        'msg':      "C'est quoi le taoïsme ? Les grandes idées.",
    },
    {
        'id':       'T15',
        'expect':   'TAG',
        'label':    'Meilleurs X (littérature)',
        'msg':      "Quels sont les meilleurs auteurs de polar français en ce moment ?",
    },
    {
        'id':       'T16',
        'expect':   'TAG',
        'label':    'Follow-up sur proposition LLM',
        'msg':      "Le premier que tu m'as cité, tu peux me donner plus de détails dessus ?",
    },
    {
        'id':       'T17',
        'expect':   'TAG',
        'label':    'Par où commencer (sport)',
        'msg':      "Je veux me mettre à l'escalade. Par où je commence, quel matériel ?",
    },
    {
        'id':       'T18',
        'expect':   'TAG',
        'label':    'Recommandation film / cinéma',
        'msg':      "Tu me conseilles des films de Kubrick à voir en priorité ?",
    },
    # ── SHOULD_NOT_TAG — nouveaux cas limites ─────────────────────────────────
    {
        'id':       'N09',
        'expect':   'NO_TAG',
        'label':    'Parle-moi de X (pratique routier)',
        'msg':      "Parle-moi de la route A9 entre Montpellier et Perpignan, y a des travaux ?",
    },
    {
        'id':       'N10',
        'expect':   'NO_TAG',
        'label':    'C\'est quoi X (technique/code erreur)',
        'msg':      "C'est quoi le code erreur P0300 sur un moteur diesel ?",
    },
    # ── AMBIGUOUS — non évalués automatiquement ───────────────────────────────
    {
        'id':       'A01',
        'expect':   'AMBIGUOUS',
        'label':    'Capitale du Japon (factuel isolé)',
        'msg':      "C'est quoi la capitale du Japon ?",
    },
    {
        'id':       'A02',
        'expect':   'AMBIGUOUS',
        'label':    'Moteur diesel (technique ou intérêt ?)',
        'msg':      "Comment fonctionne un moteur diesel ?",
    },
]

# ══════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════

TOPIC_PATTERN = re.compile(r'%%TOPIC\s*:', re.IGNORECASE)

async def call(system, user_msg):
    return await call_llm(
        messages      = [{'role': 'user', 'content': user_msg}],
        provider      = PROVIDER,
        system_prompt = system,
        max_tokens    = 300,
        temperature   = 0.2,
        api_keys      = API_KEYS,
    )

def has_topic(response: str) -> bool:
    return bool(TOPIC_PATTERN.search(response))

def extract_topic(response: str) -> str:
    m = re.search(r'%%TOPIC\s*:\s*([^%\n]+)', response, re.IGNORECASE)
    return m.group(1).strip() if m else ''

def verdict(case, response) -> str:
    if case['expect'] == 'AMBIGUOUS':
        return 'AMBIGUOUS'
    tagged = has_topic(response)
    if case['expect'] == 'TAG':
        return 'OK' if tagged else 'MISS'
    else:  # NO_TAG
        return 'OK' if not tagged else 'SPURIOUS'

# ══════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════

async def run_all():
    # results[rule_id][case_id] = (verdict, response)
    results = {r['id']: {} for r in RULES}
    total_calls = len(RULES) * len(CASES)
    count = 0

    for rule in RULES:
        for case in CASES:
            count += 1
            label = f"{rule['id']}×{case['id']}"
            sys.stdout.write(f"  [{count:03d}/{total_calls}] {label:<12} {case['label'][:35]:<35} ")
            sys.stdout.flush()

            t0 = time.time()
            try:
                resp = await call(rule['text'], case['msg'])
                v    = verdict(case, resp)
                topic_found = extract_topic(resp) if has_topic(resp) else ''
            except Exception as e:
                resp = ''
                v    = 'ERR'
                topic_found = ''
                print(f"ERR — {str(e)[:50]}")
                results[rule['id']][case['id']] = (v, resp)
                continue

            elapsed = time.time() - t0

            if   v == 'OK':       icon = GREEN  + 'OK      ' + RESET
            elif v == 'MISS':     icon = RED    + 'MISS    ' + RESET
            elif v == 'SPURIOUS': icon = YELLOW + 'SPURIOUS' + RESET
            elif v == 'AMBIGUOUS':icon = CYAN   + 'AMBIG   ' + RESET
            else:                 icon = RED    + 'ERR     ' + RESET

            topic_display = f'→ {topic_found[:30]}' if topic_found else ''
            print(f"{icon}  ({elapsed:.1f}s)  {DIM}{topic_display}{RESET}")
            results[rule['id']][case['id']] = (v, resp)

    return results

# ══════════════════════════════════════════
# RAPPORT
# ══════════════════════════════════════════

def print_report(results):
    should_tag_ids   = [c['id'] for c in CASES if c['expect'] == 'TAG']
    should_not_ids   = [c['id'] for c in CASES if c['expect'] == 'NO_TAG']
    ambiguous_ids    = [c['id'] for c in CASES if c['expect'] == 'AMBIGUOUS']

    print('\n\n' + BOLD + '═' * 70 + RESET)
    print(BOLD + '  RAPPORT — PRÉCISION PAR FORMULATION' + RESET)
    print(BOLD + '═' * 70 + RESET)
    print(f"  {'Formulation':<30} {'TAG ok':>8} {'NO_TAG ok':>10} {'Global':>8}   Verdict")
    print('  ' + '─' * 66)

    best_global = -1
    best_rule   = None

    for rule in RULES:
        r = results[rule['id']]

        tag_ok  = sum(1 for cid in should_tag_ids   if r.get(cid, ('',''))[0] == 'OK')
        ntag_ok = sum(1 for cid in should_not_ids   if r.get(cid, ('',''))[0] == 'OK')
        total_eval = len(should_tag_ids) + len(should_not_ids)
        global_ok  = tag_ok + ntag_ok

        tag_pct  = int(100 * tag_ok  / len(should_tag_ids))  if should_tag_ids  else 0
        ntag_pct = int(100 * ntag_ok / len(should_not_ids))  if should_not_ids  else 0
        glob_pct = int(100 * global_ok / total_eval)         if total_eval      else 0

        def _color(p):
            if p == 100: return GREEN
            if p >= 75:  return YELLOW
            return RED

        row = (
            f"  {rule['id']} {rule['label']:<27}"
            f" {_color(tag_pct)}{tag_ok}/{len(should_tag_ids)} ({tag_pct:3d}%){RESET}"
            f"  {_color(ntag_pct)}{ntag_ok}/{len(should_not_ids)} ({ntag_pct:3d}%){RESET}"
            f"  {_color(glob_pct)}{global_ok}/{total_eval} ({glob_pct:3d}%){RESET}"
        )
        verdict_label = ''
        if tag_pct == 100 and ntag_pct == 100:
            verdict_label = GREEN + '  ★ PARFAIT' + RESET
        elif glob_pct >= 85:
            verdict_label = YELLOW + '  ✓ BON' + RESET
        else:
            verdict_label = RED + '  ✗ À RETRAVAILLER' + RESET

        print(row + verdict_label)

        if global_ok > best_global:
            best_global = global_ok
            best_rule   = rule

    # ── Détail des erreurs ────────────────────────────────────────────────────
    print('\n\n' + BOLD + '  ERREURS PAR CAS' + RESET)
    print('  ' + '─' * 66)

    for rule in RULES:
        errors = []
        for case in CASES:
            if case['expect'] == 'AMBIGUOUS':
                continue
            v, resp = results[rule['id']].get(case['id'], ('ERR', ''))
            if v != 'OK':
                topic = extract_topic(resp) if resp else ''
                topic_note = f" (topic émis: '{topic}')" if topic else ''
                errors.append(f"    {RED if v=='MISS' else YELLOW}{v}{RESET}  {case['id']} {case['label']}{topic_note}")
        if errors:
            print(f"\n  {BOLD}{rule['id']} — {rule['label']}{RESET}")
            for e in errors:
                print(e)
        else:
            print(f"\n  {BOLD}{rule['id']} — {rule['label']}{RESET}  {GREEN}Aucune erreur{RESET}")

    # ── Cas ambigus — affichage informatif ────────────────────────────────────
    print('\n\n' + BOLD + '  CAS AMBIGUS (observation uniquement)' + RESET)
    print('  ' + '─' * 66)
    for rule in RULES:
        print(f'\n  {BOLD}{rule["id"]}{RESET}')
        for cid in ambiguous_ids:
            v, resp = results[rule['id']].get(cid, ('ERR', ''))
            case = next(c for c in CASES if c['id'] == cid)
            topic = extract_topic(resp) if resp else ''
            tagged = '%%TOPIC%%' if topic else 'pas de tag'
            print(f"    {case['id']} {case['label']:<40} → {CYAN}{tagged}{RESET}" +
                  (f" : '{topic}'" if topic else ''))

    # ── Conclusion ────────────────────────────────────────────────────────────
    print('\n\n' + BOLD + '═' * 70 + RESET)
    if best_rule:
        print(BOLD + f'  ★ Meilleure formulation : {best_rule["id"]} — {best_rule["label"]}' + RESET)
        print()
        print('  Texte de la règle :')
        for line in best_rule['text'].split('\n'):
            print(f"    {line}")
    print('\n' + BOLD + '═' * 70 + RESET + '\n')

# ══════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════

async def main():
    n_eval = sum(1 for c in CASES if c['expect'] != 'AMBIGUOUS')
    print(BOLD + '\n' + '═' * 70 + RESET)
    print(BOLD + '  NIMM — Calibration règle %%TOPIC%%' + RESET)
    print(f'  {len(RULES)} formulations × {len(CASES)} cas ({n_eval} évalués, {len(CASES)-n_eval} ambigus)')
    print(f'  Référence : F1 (meilleure formulation académique jusqu\'ici — 67%)')
    print(BOLD + '═' * 70 + RESET + '\n')

    results = await run_all()
    print_report(results)

if __name__ == '__main__':
    asyncio.run(main())
