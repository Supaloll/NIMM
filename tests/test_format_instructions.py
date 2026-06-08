# -*- coding: utf-8 -*-
# ============================================
# NIMM — tests/test_format_instructions.py
# Axe 1 : Format des instructions
# 3 dimensions × 5 règles × 10 messages test
# - Langue       : FR / EN
# - Format       : prose / markdown bullets / markdown titres
# - Position     : début / milieu / fin du system prompt
# Execution : python -X utf8 tests/test_format_instructions.py
# ============================================

import sys, os, json, asyncio, time, re
sys.stdout.reconfigure(encoding='utf-8')

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.database import init_db, get_setting
from core.engine   import call_llm

init_db()

# ══════════════════════════════════════════
# COULEURS
# ══════════════════════════════════════════
GREEN  = '\033[92m'
RED    = '\033[91m'
YELLOW = '\033[93m'
CYAN   = '\033[96m'
RESET  = '\033[0m'
BOLD   = '\033[1m'

def _load_config():
    try:    api_keys = json.loads(get_setting('api_keys', '{}'))
    except: api_keys = {}
    try:
        routing  = json.loads(get_setting('routing', '{}'))
        provider = routing.get('chat', '')
    except: provider = ''
    if not provider:
        for p in ('deepseek','anthropic','gemini','openai','mistral'):
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
# RÈGLES DE TEST
# Chaque règle a : une instruction FR, une EN,
# et 10 messages qui DOIVENT déclencher la règle.
# L'évaluateur juge si la règle a été respectée.
# ══════════════════════════════════════════

RULES = [
    {
        'id':    'R1',
        'label': 'Pas de formule therapeutique',
        'fr':    'Ne commence jamais une reponse par "Je comprends que".',
        'en':    'Never start a response with "I understand that".',
        'check': 'pattern',
        'pattern': r'(?i)^(je comprends que|i understand that)',
        'violation_means': 'started with therapeutic formula',
        'messages': [
            "Je suis vraiment stresse en ce moment.",
            "J'ai eu une grosse dispute avec ma femme.",
            "Je me sens depassé par les evenements.",
            "Mon boulot me pompe toute mon energie.",
            "J'ai du mal a dormir depuis quelques semaines.",
            "Je suis anxieux pour mon entretien demain.",
            "Tout va de travers en ce moment.",
            "Je me sens seul parfois.",
            "J'ai peur de pas etre a la hauteur.",
            "C'est dur d'etre loin de ma famille.",
        ],
    },
    {
        'id':    'R2',
        'label': 'Reponse courte max 2 phrases',
        'fr':    'Reponds toujours en 2 phrases maximum. Jamais plus.',
        'en':    'Always reply in 2 sentences maximum. Never more.',
        'check': 'llm_judge',
        'violation_means': 'response contains more than 2 sentences',
        'messages': [
            "Explique-moi comment fonctionne un moteur diesel.",
            "C'est quoi la difference entre TCP et UDP ?",
            "Pourquoi le ciel est bleu ?",
            "Comment on fait du pain ?",
            "Qu'est-ce que la relativite generale ?",
            "Explique-moi le machine learning.",
            "C'est quoi un semi-remorque ?",
            "Comment fonctionne un VPN ?",
            "Pourquoi les avions volent ?",
            "C'est quoi la photosynthese ?",
        ],
    },
    {
        'id':    'R3',
        'label': 'Toujours tutoyer',
        'fr':    "Tutoie toujours l'utilisateur. N'utilise jamais le vouvoiement.",
        'en':    'Always use informal "tu" form. Never use formal "vous".',
        'check': 'pattern',
        'pattern': r'(?i)\b(vous|votre|vos|avez-vous|etes-vous|faites-vous)\b',
        'violation_means': 'used formal "vous" form',
        'messages': [
            "Bonjour, comment puis-je vous contacter ?",
            "Vous pouvez m'aider ?",
            "Qu'est-ce que vous pensez de ca ?",
            "Vous avez une idee ?",
            "Comment vous feriez ca ?",
            "Vous connaissez ce sujet ?",
            "Ca vous semble faisable ?",
            "Vous avez le temps ?",
            "Vous etes disponible ?",
            "Qu'est-ce que vous recommandez ?",
        ],
    },
    {
        'id':    'R4',
        'label': 'Ne jamais utiliser de listes a puces',
        'fr':    "N'utilise jamais de listes a puces ou de tirets dans tes reponses. Texte continu uniquement.",
        'en':    'Never use bullet points or dashes in your responses. Continuous text only.',
        'check': 'pattern',
        'pattern': r'(?m)^[\s]*[-•*]\s',
        'violation_means': 'used bullet points or dashes',
        'messages': [
            "Quels sont les avantages du travail en equipe ?",
            "Cite-moi les etapes pour changer un pneu.",
            "Quels sont les ingredients d'une pizza margherita ?",
            "Liste les capitales europeennes.",
            "Quels sont les symptomes d'un rhume ?",
            "Donne-moi 5 conseils pour mieux dormir.",
            "Quelles sont les regles du football ?",
            "Quels documents faut-il pour un passeport ?",
            "Cite les planetes du systeme solaire.",
            "Quelles sont les etapes d'un entretien d'embauche ?",
        ],
    },
    {
        'id':    'R5',
        'label': 'Terminer par une question',
        'fr':    "Termine toujours ta reponse par une question pour relancer la conversation.",
        'en':    'Always end your response with a question to keep the conversation going.',
        'check': 'pattern',
        'pattern': r'\?(?:\s*["\']?\s*)?$',
        'violation_means': 'did not end response with a question mark',
        'messages': [
            "C'est quoi le bresil ?",
            "Parle-moi de la Tour Eiffel.",
            "Explique-moi ce qu'est Python.",
            "C'est quoi un camion benne ?",
            "Parle-moi des Corbieres.",
            "Qu'est-ce que l'IA ?",
            "C'est quoi NIMM ?",
            "Parle-moi du judo.",
            "C'est quoi DeepSeek ?",
            "Qu'est-ce qu'un LLM ?",
        ],
    },
]

# ══════════════════════════════════════════
# DIMENSIONS DE FORMAT
# ══════════════════════════════════════════

# Dimension A — Langue
LANGS = [
    {'id': 'FR', 'label': 'Francais',         'key': 'fr'},
    {'id': 'EN', 'label': 'Anglais',           'key': 'en'},
]

# Dimension B — Format de mise en forme
FORMATS = [
    {'id': 'PROSE',   'label': 'Prose simple',       'wrap': lambda r: r},
    {'id': 'BULLETS', 'label': 'Markdown bullets',   'wrap': lambda r: '## Instructions\n- ' + r},
    {'id': 'TITLE',   'label': 'Markdown titre+texte','wrap': lambda r: '## Regle importante\n' + r},
]

# Dimension C — Position dans le system prompt
PADDING = "Tu es un assistant IA utile et concis. Tu reponds en francais. " * 8  # ~rembourrage neutre

POSITIONS = [
    {
        'id':    'DEBUT',
        'label': 'Debut du prompt',
        'build': lambda rule_text: rule_text + '\n\n' + PADDING,
    },
    {
        'id':    'MILIEU',
        'label': 'Milieu du prompt',
        'build': lambda rule_text: PADDING[:len(PADDING)//2] + '\n\n' + rule_text + '\n\n' + PADDING[len(PADDING)//2:],
    },
    {
        'id':    'FIN',
        'label': 'Fin du prompt',
        'build': lambda rule_text: PADDING + '\n\n' + rule_text,
    },
]

# ══════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════

async def call(system, user_msg, max_tokens=300):
    return await call_llm(
        messages      = [{'role': 'user', 'content': user_msg}],
        provider      = PROVIDER,
        system_prompt = system,
        max_tokens    = max_tokens,
        temperature   = 0.3,
        api_keys      = API_KEYS,
    )

async def judge_llm(rule_desc, violation_means, response):
    system = (
        "Tu es un evaluateur strict. Reponds UNIQUEMENT par HOLD ou BREAK.\n"
        "HOLD = la regle a ete respectee.\n"
        "BREAK = la regle a ete violee.\n"
        "Un seul mot, rien d'autre."
    )
    prompt = (
        "Regle : " + rule_desc + "\n"
        "Violation = " + violation_means + "\n"
        "Reponse a evaluer :\n" + response + "\n\n"
        "HOLD ou BREAK ?"
    )
    verdict = await call(system, prompt, max_tokens=10)
    return 'HOLD' if 'HOLD' in verdict.upper() else 'BREAK'

def judge_pattern(pattern, response, violation_means):
    # Pour R5 (doit terminer par ?), on inverse la logique
    if 'did not end' in violation_means or 'terminer' in violation_means.lower():
        return 'HOLD' if re.search(pattern, response.strip()) else 'BREAK'
    # Pour les autres (ne doit PAS contenir le pattern)
    return 'BREAK' if re.search(pattern, response) else 'HOLD'

async def evaluate(rule, response):
    if rule['check'] == 'pattern':
        return judge_pattern(rule['pattern'], response, rule['violation_means'])
    else:
        return await judge_llm(rule['fr'], rule['violation_means'], response)

# ══════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════

async def run_dimension_lang(rule):
    """Dimension A : FR vs EN, position=DEBUT, format=PROSE."""
    scores = {}
    for lang in LANGS:
        instruction = rule[lang['key']]
        system = instruction + '\n\n' + PADDING
        holds = 0
        for msg in rule['messages']:
            resp = await call(system, msg)
            v = await evaluate(rule, resp)
            if v == 'HOLD':
                holds += 1
        scores[lang['id']] = holds
    return scores

async def run_dimension_format(rule):
    """Dimension B : PROSE vs BULLETS vs TITLE, langue=FR, position=DEBUT."""
    scores = {}
    for fmt in FORMATS:
        instruction = fmt['wrap'](rule['fr'])
        system = instruction + '\n\n' + PADDING
        holds = 0
        for msg in rule['messages']:
            resp = await call(system, msg)
            v = await evaluate(rule, resp)
            if v == 'HOLD':
                holds += 1
        scores[fmt['id']] = holds
    return scores

async def run_dimension_position(rule):
    """Dimension C : DEBUT vs MILIEU vs FIN, langue=FR, format=PROSE."""
    scores = {}
    for pos in POSITIONS:
        system = pos['build'](rule['fr'])
        holds = 0
        for msg in rule['messages']:
            resp = await call(system, msg)
            v = await evaluate(rule, resp)
            if v == 'HOLD':
                holds += 1
        scores[pos['id']] = holds
    return scores

# ══════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════

async def main():
    n_msgs  = len(RULES[0]['messages'])
    n_lang  = len(LANGS)
    n_fmt   = len(FORMATS)
    n_pos   = len(POSITIONS)
    n_rules = len(RULES)
    total   = n_rules * (n_lang + n_fmt + n_pos) * n_msgs

    print(BOLD + '\n' + '=' * 70 + RESET)
    print(BOLD + '  NIMM — Test format des instructions (Axe 1)' + RESET)
    print('  ' + str(n_rules) + ' regles × (2 langues + 3 formats + 3 positions) × ' + str(n_msgs) + ' messages')
    print('  Total appels LLM : ~' + str(total) + ' (+ evaluations)')
    print(BOLD + '=' * 70 + RESET + '\n')

    results_lang   = {}
    results_format = {}
    results_pos    = {}

    for i, rule in enumerate(RULES):
        print(CYAN + '  [' + rule['id'] + '] ' + rule['label'] + RESET)

        sys.stdout.write('      Langue   (FR vs EN)  ... ')
        sys.stdout.flush()
        t0 = time.time()
        results_lang[rule['id']] = await run_dimension_lang(rule)
        print('OK ({:.0f}s)'.format(time.time() - t0))

        sys.stdout.write('      Format   (prose/bullets/titres) ... ')
        sys.stdout.flush()
        t0 = time.time()
        results_format[rule['id']] = await run_dimension_format(rule)
        print('OK ({:.0f}s)'.format(time.time() - t0))

        sys.stdout.write('      Position (debut/milieu/fin) ... ')
        sys.stdout.flush()
        t0 = time.time()
        results_pos[rule['id']] = await run_dimension_position(rule)
        print('OK ({:.0f}s)'.format(time.time() - t0))

    # ── RAPPORT ──────────────────────────────────────────────────────────────
    N = n_msgs  # 10 messages par combinaison

    def pct(score):
        p = int(100 * score / N)
        if   p == 100: return GREEN  + '{:3d}%'.format(p) + RESET
        elif p >= 70:  return YELLOW + '{:3d}%'.format(p) + RESET
        else:          return RED    + '{:3d}%'.format(p) + RESET

    print('\n\n' + BOLD + '=' * 70 + RESET)
    print(BOLD + '  RAPPORT DÉTAILLÉ — Score = nb HOLD sur ' + str(N) + ' messages' + RESET)
    print(BOLD + '=' * 70 + RESET)

    # ── A — Langue ────────────────────────────────────────────────────────────
    print('\n  ' + BOLD + 'A — LANGUE (FR vs EN)' + RESET)
    print('  ' + '-' * 52)
    print('  {:<30}  {:>6}  {:>6}  Meilleure'.format('Regle', 'FR', 'EN'))
    print('  ' + '-' * 52)
    lang_totals = {'FR': 0, 'EN': 0}
    for rule in RULES:
        s = results_lang[rule['id']]
        best = max(s, key=s.get)
        lang_totals['FR'] += s['FR']
        lang_totals['EN'] += s['EN']
        print('  {:<30}  {:>6}  {:>6}  {}'.format(
            rule['id'] + ' ' + rule['label'][:24],
            pct(s['FR']), pct(s['EN']), best
        ))
    print('  ' + '-' * 52)
    print('  {:<30}  {:>6}  {:>6}'.format(
        'TOTAL',
        pct(lang_totals['FR'] // n_rules),
        pct(lang_totals['EN'] // n_rules),
    ))

    # ── B — Format ────────────────────────────────────────────────────────────
    print('\n  ' + BOLD + 'B — FORMAT (Prose / Bullets / Titre markdown)' + RESET)
    print('  ' + '-' * 62)
    print('  {:<30}  {:>6}  {:>8}  {:>7}  Meilleure'.format('Regle', 'Prose', 'Bullets', 'Titre'))
    print('  ' + '-' * 62)
    fmt_totals = {'PROSE': 0, 'BULLETS': 0, 'TITLE': 0}
    for rule in RULES:
        s = results_format[rule['id']]
        best = max(s, key=s.get)
        for k in fmt_totals: fmt_totals[k] += s[k]
        print('  {:<30}  {:>6}  {:>8}  {:>7}  {}'.format(
            rule['id'] + ' ' + rule['label'][:24],
            pct(s['PROSE']), pct(s['BULLETS']), pct(s['TITLE']), best
        ))
    print('  ' + '-' * 62)
    print('  {:<30}  {:>6}  {:>8}  {:>7}'.format(
        'TOTAL',
        pct(fmt_totals['PROSE']   // n_rules),
        pct(fmt_totals['BULLETS'] // n_rules),
        pct(fmt_totals['TITLE']   // n_rules),
    ))

    # ── C — Position ──────────────────────────────────────────────────────────
    print('\n  ' + BOLD + 'C — POSITION (Debut / Milieu / Fin)' + RESET)
    print('  ' + '-' * 60)
    print('  {:<30}  {:>6}  {:>7}  {:>5}  Meilleure'.format('Regle', 'Debut', 'Milieu', 'Fin'))
    print('  ' + '-' * 60)
    pos_totals = {'DEBUT': 0, 'MILIEU': 0, 'FIN': 0}
    for rule in RULES:
        s = results_pos[rule['id']]
        best = max(s, key=s.get)
        for k in pos_totals: pos_totals[k] += s[k]
        print('  {:<30}  {:>6}  {:>7}  {:>5}  {}'.format(
            rule['id'] + ' ' + rule['label'][:24],
            pct(s['DEBUT']), pct(s['MILIEU']), pct(s['FIN']), best
        ))
    print('  ' + '-' * 60)
    print('  {:<30}  {:>6}  {:>7}  {:>5}'.format(
        'TOTAL',
        pct(pos_totals['DEBUT']  // n_rules),
        pct(pos_totals['MILIEU'] // n_rules),
        pct(pos_totals['FIN']    // n_rules),
    ))

    # ── SYNTHESE ──────────────────────────────────────────────────────────────
    print('\n\n  ' + BOLD + 'SYNTHESE — Recommandations' + RESET)
    print('  ' + '-' * 60)

    best_lang = max(lang_totals, key=lang_totals.get)
    best_fmt  = max(fmt_totals,  key=fmt_totals.get)
    best_pos  = max(pos_totals,  key=pos_totals.get)

    print('  Langue   optimale : ' + CYAN + best_lang + RESET)
    print('  Format   optimal  : ' + CYAN + best_fmt  + RESET)
    print('  Position optimale : ' + CYAN + best_pos  + RESET)
    print('\n  ' + BOLD + 'Combinaison recommandee : ' + best_lang + ' + ' + best_fmt + ' + ' + best_pos + RESET)
    print('\n' + BOLD + '=' * 70 + RESET + '\n')

if __name__ == '__main__':
    asyncio.run(main())
