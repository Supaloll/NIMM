# -*- coding: utf-8 -*-
# ============================================
# NIMM — tests/test_rule_density.py
# Axe 2 : Densite des instructions
# Question : a partir de combien de regles simultanees
# DeepSeek commence-t-il a en "oublier" ?
#
# Protocole :
# - On part de 1 regle et on monte jusqu'a 15
# - Chaque regle est simple et mesurable par pattern
# - On mesure le taux de conformite global ET par regle
# - On detecte le seuil a partir duquel des regles "tombent"
#
# Execution : python -X utf8 tests/test_rule_density.py
# ============================================

import sys, os, json, asyncio, time, re
sys.stdout.reconfigure(encoding='utf-8')

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.database import init_db, get_setting
from core.engine   import call_llm

init_db()

GREEN  = '\033[92m'; RED = '\033[91m'; YELLOW = '\033[93m'
CYAN   = '\033[96m'; RESET = '\033[0m'; BOLD = '\033[1m'

def _load_config():
    try:    api_keys = json.loads(get_setting('api_keys', '{}'))
    except: api_keys = {}
    try:
        routing  = json.loads(get_setting('routing', '{}'))
        provider = routing.get('chat', '')
    except: provider = ''
    if not provider:
        for p in ('deepseek','anthropic','gemini','openai','mistral'):
            if api_keys.get(p): provider = p; break
    return provider, api_keys

PROVIDER, API_KEYS = _load_config()
if not PROVIDER:
    print(RED + 'ERR: Aucun provider configure.' + RESET); sys.exit(1)
print(CYAN + '\nProvider : ' + PROVIDER + RESET)

TIMEOUT = 30

# ══════════════════════════════════════════
# 15 REGLES SIMPLES ET MESURABLES PAR PATTERN
# Ordonnees du plus naturel au plus contraignant
# ══════════════════════════════════════════

ALL_RULES = [
    {
        'id': 'R01', 'label': 'Repondre en francais',
        'instruction': 'Reponds toujours en francais.',
        'check': lambda r: not re.search(r'\b(the|is|are|this|that|you|and|for)\b', r),
        'invert': False,
    },
    {
        'id': 'R02', 'label': 'Tutoyer',
        'instruction': "Tutoie toujours l'utilisateur, jamais de vouvoiement.",
        'check': lambda r: not re.search(r'(?i)\b(vous|votre|vos)\b', r),
        'invert': False,
    },
    {
        'id': 'R03', 'label': 'Pas de liste',
        'instruction': "N'utilise jamais de listes a puces ou tirets. Texte continu uniquement.",
        'check': lambda r: not re.search(r'(?m)^[\s]*[-•*]\s', r),
        'invert': False,
    },
    {
        'id': 'R04', 'label': 'Max 3 phrases',
        'instruction': 'Reponds en 3 phrases maximum.',
        'check': lambda r: _count_sentences(r) <= 3,
        'invert': False,
    },
    {
        'id': 'R05', 'label': 'Terminer par question',
        'instruction': 'Termine toujours ta reponse par une question.',
        'check': lambda r: bool(re.search(r'\?\s*$', r.strip())),
        'invert': False,
    },
    {
        'id': 'R06', 'label': 'Pas de markdown gras',
        'instruction': "N'utilise jamais le markdown gras (**texte**).",
        'check': lambda r: not re.search(r'\*\*[^*]+\*\*', r),
        'invert': False,
    },
    {
        'id': 'R07', 'label': 'Commencer par prenom',
        'instruction': "Commence toujours ta reponse par le prenom de l'utilisateur : Laurent.",
        'check': lambda r: r.strip().startswith('Laurent'),
        'invert': False,
    },
    {
        'id': 'R08', 'label': 'Pas de chiffres en debut de ligne',
        'instruction': "N'utilise jamais de numerotation (1. 2. 3.) dans tes reponses.",
        'check': lambda r: not re.search(r'(?m)^\s*\d+[\.\)]\s', r),
        'invert': False,
    },
    {
        'id': 'R09', 'label': 'Toujours une analogie',
        'instruction': 'Inclus toujours une analogie ou comparaison dans ta reponse.',
        'check': lambda r: bool(re.search(r'(?i)(comme|tel que|similaire|analogue|ressemble|c\'est un peu comme|imagine que|pareil)', r)),
        'invert': False,
    },
    {
        'id': 'R10', 'label': 'Pas de mot "donc"',
        'instruction': 'N\'utilise jamais le mot "donc" dans tes reponses.',
        'check': lambda r: not re.search(r'(?i)\bdonc\b', r),
        'invert': False,
    },
    {
        'id': 'R11', 'label': 'Pas de mot "important"',
        'instruction': 'N\'utilise jamais le mot "important" ou "important(e)(s)" dans tes reponses.',
        'check': lambda r: not re.search(r'(?i)\bimportant[es]?\b', r),
        'invert': False,
    },
    {
        'id': 'R12', 'label': 'Mentionner la meteo',
        'instruction': 'Inclus toujours une reference a la meteo ou au temps qu\'il fait quelque part.',
        'check': lambda r: bool(re.search(r'(?i)(meteo|soleil|pluie|nuage|vent|temperature|chaud|froid|ciel|orage)', r)),
        'invert': False,
    },
    {
        'id': 'R13', 'label': 'Pas de "je" en debut de phrase',
        'instruction': 'Ne commence jamais une phrase par le mot "Je".',
        'check': lambda r: not re.search(r'(?m)(^|[.!?]\s+)Je\b', r),
        'invert': False,
    },
    {
        'id': 'R14', 'label': 'Pas de titre markdown',
        'instruction': "N'utilise jamais de titres markdown (# ou ##).",
        'check': lambda r: not re.search(r'(?m)^#+\s', r),
        'invert': False,
    },
    {
        'id': 'R15', 'label': 'Finir par un emoji',
        'instruction': 'Termine toujours ta reponse par un emoji.',
        'check': lambda r: bool(re.search(
            r'[\U0001F300-\U0001F9FF\U00002600-\U000027BF]\s*$', r.strip())),
        'invert': False,
    },
]

# Paliers de densité testés
DENSITIES = [1, 2, 3, 5, 7, 10, 12, 15]

# Messages de test (neutres, variés, poussent vers les violations)
TEST_MESSAGES = [
    "Explique-moi comment fonctionne un moteur diesel.",
    "Quels sont les avantages du teletravail ?",
    "Donne-moi des conseils pour mieux dormir.",
    "C'est quoi la difference entre RAM et disque dur ?",
    "Parle-moi de la cuisine francaise.",
]

def _count_sentences(text):
    text = re.sub(r'\b(M|Mme|Dr|Prof|etc|vs|ex|Mr)\.\s', r'\1_ ', text)
    return max(1, len(re.findall(r'[^.!?]+[.!?]+', text)))

def build_system(rules_subset):
    lines = ["Tu es un assistant IA. Tu respectes ces regles sans exception :"]
    for i, r in enumerate(rules_subset):
        lines.append(str(i+1) + ". " + r['instruction'])
    return "\n".join(lines)

async def call_safe(system, user_msg):
    try:
        return await asyncio.wait_for(
            call_llm(
                messages      = [{'role': 'user', 'content': user_msg}],
                provider      = PROVIDER,
                system_prompt = system,
                max_tokens    = 300,
                temperature   = 0.3,
                api_keys      = API_KEYS,
            ),
            timeout = TIMEOUT,
        )
    except asyncio.TimeoutError:
        return '__TIMEOUT__'
    except Exception as e:
        return '__ERR__'

def evaluate(rules_subset, response):
    if response.startswith('__'):
        return {r['id']: None for r in rules_subset}
    return {r['id']: r['check'](response) for r in rules_subset}

async def run_density(n_rules):
    rules_subset = ALL_RULES[:n_rules]
    system = build_system(rules_subset)
    per_rule = {r['id']: 0 for r in rules_subset}
    errors = 0
    n = len(TEST_MESSAGES)

    for msg in TEST_MESSAGES:
        sys.stdout.write('.')
        sys.stdout.flush()
        resp = await call_safe(system, msg)
        evals = evaluate(rules_subset, resp)
        for rid, passed in evals.items():
            if passed is None: errors += 1
            elif passed:       per_rule[rid] += 1

    return per_rule, errors, n

# ══════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════
async def main():
    n_msgs = len(TEST_MESSAGES)
    total  = sum(DENSITIES) * n_msgs
    print(BOLD + '\n' + '=' * 70 + RESET)
    print(BOLD + '  NIMM — Test densite des instructions (Axe 2)' + RESET)
    print('  Paliers : ' + str(DENSITIES) + ' regles')
    print('  ' + str(n_msgs) + ' messages test par palier')
    print('  Chaque point = 1 message teste')
    print(BOLD + '=' * 70 + RESET + '\n')

    all_results = {}

    for n_rules in DENSITIES:
        sys.stdout.write('  N={:>2} regles  '.format(n_rules))
        sys.stdout.flush()
        t0 = time.time()
        per_rule, errors, n = await run_density(n_rules)
        elapsed = time.time() - t0
        all_results[n_rules] = per_rule

        # Score global pour ce palier
        total_hold  = sum(per_rule.values())
        total_tests = n_rules * n
        pct = int(100 * total_hold / total_tests) if total_tests else 0

        if   pct == 100: color = GREEN
        elif pct >= 75:  color = YELLOW
        else:            color = RED

        err_s = (' (' + RED + str(errors) + ' err' + RESET + ')') if errors else ''
        print('  ' + color + '{:3d}%'.format(pct) + RESET +
              ' global  ({:.0f}s)'.format(elapsed) + err_s)

    # ── RAPPORT ──────────────────────────────────────────────────────────────
    N = len(TEST_MESSAGES)

    def pct_str(score, n):
        if score is None: return YELLOW + ' --- ' + RESET
        p = int(100 * score / n)
        if   p == 100: return GREEN  + '100%' + RESET
        elif p >= 60:  return YELLOW + '{:3d}%'.format(p) + RESET
        else:          return RED    + '{:3d}%'.format(p) + RESET

    print('\n\n' + BOLD + '=' * 70 + RESET)
    print(BOLD + '  RAPPORT — Conformite par regle selon nombre de regles actives' + RESET)
    print('  Score = nb HOLD sur ' + str(N) + ' messages')
    print(BOLD + '=' * 70 + RESET + '\n')

    # En-tête densités
    header = '  {:<22}'.format('Regle')
    for d in DENSITIES:
        header += '{:>7}'.format('N=' + str(d))
    print(header)
    print('  ' + '-' * (22 + 7 * len(DENSITIES)))

    # Une ligne par règle
    for rule in ALL_RULES:
        row = '  {:<22}'.format(rule['id'] + ' ' + rule['label'][:16])
        for d in DENSITIES:
            if rule['id'] in all_results[d]:
                s = all_results[d][rule['id']]
                row += '{:>7}'.format(pct_str(s, N))
            else:
                row += '{:>7}'.format('    -')
        print(row)

    # Ligne totaux globaux
    print('  ' + '-' * (22 + 7 * len(DENSITIES)))
    row = '  {:<22}'.format('GLOBAL')
    for d in DENSITIES:
        total_h = sum(all_results[d].values())
        total_t = d * N
        p = int(100 * total_h / total_t) if total_t else 0
        if   p == 100: c = GREEN
        elif p >= 75:  c = YELLOW
        else:          c = RED
        row += c + '{:>6}%'.format(p) + RESET
    print(row)

    # ── Détection du seuil ────────────────────────────────────────────────────
    print('\n\n  ' + BOLD + 'SEUIL DE DEGRADATION' + RESET)
    print('  ' + '-' * 60)

    globals_by_d = {}
    for d in DENSITIES:
        th = sum(all_results[d].values())
        tt = d * N
        globals_by_d[d] = int(100 * th / tt) if tt else 0

    baseline   = globals_by_d[DENSITIES[0]]
    seuil      = None
    seuil_fort = None

    for i, d in enumerate(DENSITIES[1:], 1):
        if globals_by_d[d] < baseline - 10 and seuil is None:
            seuil = d
        if globals_by_d[d] < baseline - 25 and seuil_fort is None:
            seuil_fort = d

    if seuil:
        print('  ' + YELLOW + 'Degradation legere  (>10%) detectee a N=' + str(seuil) + RESET)
    if seuil_fort:
        print('  ' + RED    + 'Degradation forte   (>25%) detectee a N=' + str(seuil_fort) + RESET)
    if not seuil:
        print('  ' + GREEN  + 'Aucune degradation significative detectee' + RESET)

    # Quelles règles tombent en premier ?
    print('\n  ' + BOLD + 'REGLES LES PLUS FRAGILES (celles qui tombent en premier)' + RESET)
    print('  ' + '-' * 60)

    rule_fragility = []
    for rule in ALL_RULES:
        scores = []
        for d in DENSITIES:
            if rule['id'] in all_results[d]:
                scores.append((d, int(100 * all_results[d][rule['id']] / N)))
        # Chercher le premier palier où le score tombe sous 80%
        first_drop = None
        for d, p in scores:
            if p < 80:
                first_drop = (d, p)
                break
        rule_fragility.append((rule, first_drop, scores))

    # Trier : celles qui tombent d'abord
    dropped   = [(r, fd, sc) for r, fd, sc in rule_fragility if fd is not None]
    held      = [(r, fd, sc) for r, fd, sc in rule_fragility if fd is None]
    dropped.sort(key=lambda x: (x[1][0], x[1][1]))

    if dropped:
        print('  Tombent sous 80% :')
        for rule, (drop_d, drop_p), _ in dropped:
            print('  ' + RED + '  ' + rule['id'] + ' ' + rule['label'] +
                  ' — chute a N=' + str(drop_d) + ' (' + str(drop_p) + '%)' + RESET)
    if held:
        print('  Tiennent sur toute la plage :')
        for rule, _, _ in held:
            print('  ' + GREEN + '  ' + rule['id'] + ' ' + rule['label'] + RESET)

    print('\n' + BOLD + '=' * 70 + RESET + '\n')

if __name__ == '__main__':
    asyncio.run(main())
