# -*- coding: utf-8 -*-
# ============================================
# NIMM — tests/test_memory_extraction.py
# Stress test extraction memoire (tags %%MEM%%)
# Approche : import direct modules, appel LLM reel,
# parse des tags — aucune ecriture en base.
# 7 categories, 30 cas de test.
# Execution : python -X utf8 tests/test_memory_extraction.py
# ============================================

import sys, os, json, asyncio, re, time
sys.stdout.reconfigure(encoding='utf-8')

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ══════════════════════════════════════════
# COULEURS
# ══════════════════════════════════════════
GREEN  = '\033[92m'
RED    = '\033[91m'
YELLOW = '\033[93m'
CYAN   = '\033[96m'
RESET  = '\033[0m'
BOLD   = '\033[1m'

PASS_S = GREEN + 'PASS' + RESET
FAIL_S = RED   + 'FAIL' + RESET
OBS_S  = YELLOW+ 'OBS ' + RESET

_stats = {'pass': 0, 'fail': 0, 'obs': 0}

def ok(label, detail=''):
    _stats['pass'] += 1
    line = '  [' + PASS_S + '] ' + label
    if detail:
        line += '\n         ' + GREEN + detail + RESET
    print(line)

def nok(label, detail=''):
    _stats['fail'] += 1
    line = '  [' + FAIL_S + '] ' + label
    if detail:
        line += '\n         ' + RED + detail + RESET
    print(line)

def obs_print(label, detail=''):
    _stats['obs'] += 1
    line = '  [' + OBS_S + '] ' + label
    if detail:
        line += '\n         ' + YELLOW + detail + RESET
    print(line)

# ══════════════════════════════════════════
# CONFIG — lire provider + cles depuis nimm.db
# ══════════════════════════════════════════

from core.database import init_db, get_setting

init_db()

def _load_config():
    try:
        raw_keys = get_setting('api_keys', '{}')
        api_keys = json.loads(raw_keys)
    except Exception:
        api_keys = {}

    try:
        raw_routing = get_setting('routing', '{}')
        routing = json.loads(raw_routing)
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
    print('\n' + RED + 'ERR' + RESET + ' Aucun provider configure dans NIMM.')
    print('     Configure un provider dans les parametres avant de lancer les tests.')
    sys.exit(1)

print('\n' + CYAN + 'Provider detecte : ' + PROVIDER + RESET)

# ══════════════════════════════════════════
# IMPORTS NIMM
# ══════════════════════════════════════════

from core.hub    import build_system_prompt, load_mask
from core.engine import call_llm

MASK      = load_mask('lia')
USER_NAME = get_setting('user_name', 'Laurent') or 'Laurent'

# ══════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════

_MEM_RE = re.compile(r'%%MEM:([^%]+)%%')

def parse_mem_tags(response):
    tags = []
    for match in _MEM_RE.finditer(response):
        parts = match.group(1).split('|')
        if len(parts) >= 4:
            tags.append({
                'type':     parts[0] if len(parts) > 0 else '?',
                'sujet':    parts[1] if len(parts) > 1 else '?',
                'predicat': parts[2] if len(parts) > 2 else '?',
                'objet':    parts[3] if len(parts) > 3 else '?',
                'raw':      match.group(0),
            })
    return tags

async def ask(user_msg, prior_exchange=None, force_mem=False):
    system = build_system_prompt(
        mask           = MASK,
        memory_context = '',
        os_summary     = '',
        user_name      = USER_NAME,
        force_mem      = force_mem,
    )
    messages = list(prior_exchange or [])
    messages.append({'role': 'user', 'content': user_msg})

    response = await call_llm(
        messages      = messages,
        provider      = PROVIDER,
        system_prompt = system,
        max_tokens    = 300,
        temperature   = 0.3,
        api_keys      = API_KEYS,
    )
    tags = parse_mem_tags(response)
    return response, tags

# ══════════════════════════════════════════
# CAS DE TEST
# expected : 'capture' | 'ignore' | 'observe'
# prior    : echange simule avant le message (cat B)
# force_mem: True pour cat F
# ══════════════════════════════════════════

TESTS = [

    # ── CAT A — Declarations directes (doit TOUJOURS capturer) ──────────────
    dict(id='A01', cat='A', expected='capture',
         desc="Metier declare directement",
         msg="Je suis chauffeur poids lourd.",
         prior=None, force_mem=False),

    dict(id='A02', cat='A', expected='capture',
         desc="Conjoint nomme directement",
         msg="Ma femme s'appelle Nadia.",
         prior=None, force_mem=False),

    dict(id='A03', cat='A', expected='capture',
         desc="Domicile declare",
         msg="J'habite a Ferrals-les-Corbieres, dans l'Aude.",
         prior=None, force_mem=False),

    dict(id='A04', cat='A', expected='capture',
         desc="Loisir declare",
         msg="Dans mes loisirs, j'adore la randonnee en montagne.",
         prior=None, force_mem=False),

    dict(id='A05', cat='A', expected='capture',
         desc="Projet declare",
         msg="Je travaille en ce moment sur un projet d'IA qui s'appelle NIMM.",
         prior=None, force_mem=False),

    # ── CAT B — Reponses a une question du LLM (fix Bloc #11) ───────────────
    dict(id='B01', cat='B', expected='capture',
         desc="Metier donne en reponse a une question",
         prior=[
             {'role': 'user',      'content': "T'as l'air cale en tech — c'est ton metier ?"},
             {'role': 'assistant', 'content': "Bonne question ! Tu fais quoi dans la vraie vie ?"},
         ],
         msg="Je suis chauffeur poids lourd, la tech c'est juste une passion.",
         force_mem=False),

    dict(id='B02', cat='B', expected='capture',
         desc="Prenom donne en reponse",
         prior=[
             {'role': 'user',      'content': "Salut !"},
             {'role': 'assistant', 'content': "Salut ! Comment tu t'appelles ?"},
         ],
         msg="Je m'appelle Laurent.",
         force_mem=False),

    dict(id='B03', cat='B', expected='capture',
         desc="Domicile donne en reponse a question geo",
         prior=[
             {'role': 'user',      'content': "Tu connais bien le sud de la France ?"},
             {'role': 'assistant', 'content': "Un peu ! T'habites dans quelle region ?"},
         ],
         msg="Je vis dans l'Aude, a Ferrals-les-Corbieres.",
         force_mem=False),

    dict(id='B04', cat='B', expected='capture',
         desc="Info famille en reponse a question directe",
         prior=[
             {'role': 'user',      'content': "C'est quoi ton quotidien ?"},
             {'role': 'assistant', 'content': "Je vois — t'as de la famille, des enfants ?"},
         ],
         msg="Oui, trois filles : Maissane, Maya et Innes.",
         force_mem=False),

    # ── CAT C — Formulations argotiques / relachees (doit capturer) ──────────
    dict(id='C01', cat='C', expected='capture',
         desc="Metier en argot routier",
         msg="Cote boulot j'suis dans le transport, je roule en 44 tonnes.",
         prior=None, force_mem=False),

    dict(id='C02', cat='C', expected='capture',
         desc="Conjoint avec tournure orale",
         msg="Ma moitie c'est Nadia, elle gere une boite de couture.",
         prior=None, force_mem=False),

    dict(id='C03', cat='C', expected='capture',
         desc="Domicile formule familierement",
         msg="On vit dans un bled dans l'Aude, Ferrals, tu connais pas forcement.",
         prior=None, force_mem=False),

    dict(id='C04', cat='C', expected='capture',
         desc="Loisir mentionne en passant",
         msg="Le week-end quand j'peux, je sors randonner un peu dans les Corbieres.",
         prior=None, force_mem=False),

    dict(id='C05', cat='C', expected='capture',
         desc="Projet mentionne de facon informelle",
         msg="Je bidouille un truc depuis quelques mois, une appli IA pour ma famille.",
         prior=None, force_mem=False),

    # ── CAT D — Second degre / metaphores (ne doit PAS capturer) ────────────
    dict(id='D01', cat='D', expected='ignore',
         desc="Metaphore identitaire evidente",
         msg="Je suis une vraie machine a cafe le matin, sans cafe je suis rien.",
         prior=None, force_mem=False),

    dict(id='D02', cat='D', expected='ignore',
         desc="Hyperbole humoristique",
         msg="Je suis le roi du monde depuis que j'ai fini ce projet !",
         prior=None, force_mem=False),

    dict(id='D03', cat='D', expected='ignore',
         desc="Expression d'epuisement (pas un fait identitaire)",
         msg="Je suis mort de fatigue la, cette semaine m'a acheve.",
         prior=None, force_mem=False),

    dict(id='D04', cat='D', expected='capture',
         desc="Second degre + declaration reelle explicite (le LLM doit capturer le vrai metier)",
         msg="Evidemment que je suis pilote de chasse — dans la realite je conduis un camion, hein.",
         prior=None, force_mem=False),

    dict(id='D05', cat='D', expected='ignore',
         desc="Fiction / jeu de role explicite",
         msg="Dans le JDR qu'on fait ce soir, mon perso s'appelle Ragnar, c'est un forgeron nain.",
         prior=None, force_mem=False),

    # ── CAT E — Recherches pures (ne doit PAS capturer) ─────────────────────
    dict(id='E01', cat='E', expected='ignore',
         desc="Recherche directe",
         msg="Cherche-moi les horaires de la mairie de Ferrals.",
         prior=None, force_mem=False),

    dict(id='E02', cat='E', expected='ignore',
         desc="Question encyclopedique",
         msg="C'est quoi la difference entre un semi-remorque et un porteur ?",
         prior=None, force_mem=False),

    dict(id='E03', cat='E', expected='ignore',
         desc="Recherche avec intention claire",
         msg="Trouve-moi un bon restaurant dans l'Aude pour ce week-end.",
         prior=None, force_mem=False),

    dict(id='E04', cat='E', expected='ignore',
         desc="Demande de calcul",
         msg="Combien ca fait 450 km a 80 km/h en heures de route ?",
         prior=None, force_mem=False),

    # ── CAT F — Commande explicite (fix Bloc #11 — doit TOUJOURS capturer) ──
    dict(id='F01', cat='F', expected='capture', force_mem=True,
         desc="souviens-toi que (metier)",
         msg="Souviens-toi que je suis chauffeur poids lourd.",
         prior=None),

    dict(id='F02', cat='F', expected='capture', force_mem=True,
         desc="retiens que (conjoint)",
         msg="Retiens que ma femme s'appelle Nadia.",
         prior=None),

    dict(id='F03', cat='F', expected='capture', force_mem=True,
         desc="memorise que (projet)",
         msg="Memorise que je travaille sur un projet IA qui s'appelle NIMM.",
         prior=None),

    dict(id='F04', cat='F', expected='capture', force_mem=True,
         desc="n'oublie pas que (domicile)",
         msg="N'oublie pas que j'habite dans l'Aude, a Ferrals.",
         prior=None),

    # ── CAT G — Zones grises / ambiguites (observation) ─────────────────────
    dict(id='G01', cat='G', expected='observe',
         desc="Info personnelle noyee dans du texte",
         msg="J'ai passe la journee sur la route, 600 km depuis Perpignan. Rentre creve.",
         prior=None, force_mem=False),

    dict(id='G02', cat='G', expected='observe',
         desc="Habitude quotidienne",
         msg="Le matin j'ecoute toujours la radio dans le camion, ca aide a rester eveille.",
         prior=None, force_mem=False),

    dict(id='G03', cat='G', expected='observe',
         desc="Info avec negation / changement",
         msg="Je ne suis plus ouvrier, j'ai change de voie il y a longtemps.",
         prior=None, force_mem=False),

    dict(id='G04', cat='G', expected='observe',
         desc="Hypothetique / conditionnel",
         msg="Si j'avais pas ete chauffeur, j'aurais surement fait de l'informatique.",
         prior=None, force_mem=False),

    dict(id='G05', cat='G', expected='observe',
         desc="Valeur personnelle implicite",
         msg="Je supporte pas les gens qui mentent, c'est ce que je tolere le moins.",
         prior=None, force_mem=False),
]

# ══════════════════════════════════════════
# RAPPORT
# ══════════════════════════════════════════

CAT_LABELS = {
    'A': 'Declarations directes        (doit capturer)',
    'B': 'Reponses a questions         (doit capturer — fix Bloc #11)',
    'C': 'Formulations argotiques      (doit capturer)',
    'D': 'Second degre / metaphores    (doit ignorer)',
    'E': 'Recherches pures             (doit ignorer)',
    'F': 'Commande explicite           (doit capturer — fix Bloc #11)',
    'G': 'Zones grises / ambiguites    (observation)',
}

async def run_all():
    results = []
    total   = len(TESTS)

    print('\n' + CYAN + '=' * 68 + RESET)
    print(BOLD + '  NIMM — Stress test extraction memoire  (' + str(total) + ' cas)' + RESET)
    print(CYAN + '=' * 68 + RESET + '\n')

    for i, t in enumerate(TESTS):
        label = '[' + t['id'] + '] ' + t['desc']
        sys.stdout.write('  {:02d}/{:02d}  {:<54} '.format(i + 1, total, label))
        sys.stdout.flush()

        t0 = time.time()
        try:
            _, tags = await ask(
                user_msg       = t['msg'],
                prior_exchange = t.get('prior'),
                force_mem      = t.get('force_mem', False),
            )
            err = None
        except Exception as e:
            elapsed = time.time() - t0
            print('ERR ({:.1f}s)'.format(elapsed))
            results.append(dict(t, status='ERROR', tags=[], error=str(e)))
            continue

        elapsed  = time.time() - t0
        captured = len(tags) > 0
        exp      = t['expected']

        if   exp == 'capture': status = 'PASS' if captured     else 'FAIL'
        elif exp == 'ignore':  status = 'PASS' if not captured else 'FAIL'
        else:                  status = 'OBS'

        icon = 'OK' if status == 'PASS' else ('!!!' if status == 'FAIL' else 'OBS')
        print('{:<3}  ({:.1f}s)'.format(icon, elapsed))
        results.append(dict(t, status=status, tags=tags))

    # ── Rapport detaille ─────────────────────────────────────────────────────
    print('\n\n' + '=' * 68)
    print(BOLD + '  RAPPORT DETAILLE' + RESET)
    print('=' * 68)

    cats = {}
    for r in results:
        cats.setdefault(r['cat'], []).append(r)

    total_pass = total_fail = total_obs = total_err = 0

    for cat, label in CAT_LABELS.items():
        if cat not in cats:
            continue
        print('\n  ' + BOLD + 'Cat. ' + cat + RESET + ' — ' + label)
        print('  ' + '-' * 64)

        for r in cats[cat]:
            st = r['status']
            if   st == 'PASS':  icon = GREEN + 'OK  ' + RESET; total_pass += 1
            elif st == 'FAIL':  icon = RED   + 'FAIL' + RESET; total_fail += 1
            elif st == 'OBS':   icon = YELLOW+ 'OBS ' + RESET; total_obs  += 1
            else:               icon = RED   + 'ERR ' + RESET; total_err  += 1

            captured = len(r.get('tags', [])) > 0
            cap_str  = str(len(r['tags'])) + ' tag(s)' if captured else 'rien'
            print('  [' + icon + '] [' + r['id'] + '] ' + r['desc'])
            print('         attendu={:<7}  resultat={:<8}  ({})'.format(
                r['expected'],
                'capture' if captured else 'ignore',
                cap_str,
            ))
            for tag in r.get('tags', []):
                print('         -> ' + tag['sujet'] + ' | ' + tag['predicat'] + ' | ' + tag['objet'])

    # ── Resume ───────────────────────────────────────────────────────────────
    total_scored = total_pass + total_fail
    score_pct    = int(100 * total_pass / total_scored) if total_scored else 0

    print('\n' + '=' * 68)
    summary = BOLD + '  RESULTAT : {}/{} ({}%)'.format(total_pass, total_scored, score_pct) + RESET
    if total_obs:
        summary += '  —  {} observation(s)'.format(total_obs)
    if total_err:
        summary += '  —  ' + RED + str(total_err) + ' erreur(s)' + RESET
    print(summary)

    if total_fail:
        print('  ' + RED + str(total_fail) + ' cas a corriger :' + RESET)
        for r in results:
            if r['status'] == 'FAIL':
                captured = len(r.get('tags', [])) > 0
                verdict  = 'capture a tort' if captured else 'non capture'
                print('    [' + r['id'] + '] ' + r['desc'] + '  -> ' + verdict)
    else:
        print('  ' + GREEN + 'Tous les cas notes sont corrects' + RESET)

    print('=' * 68 + '\n')

# ══════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════

if __name__ == '__main__':
    asyncio.run(run_all())
