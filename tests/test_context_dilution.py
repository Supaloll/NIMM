# -*- coding: utf-8 -*-
# ============================================
# NIMM — tests/test_context_dilution.py
# Axe 3 (adapte) : Dilution du masque par le contexte long
# Question : a partir de quelle longueur d'historique
# les regles du system prompt commencent-elles a etre
# diluees par le contexte conversationnel ?
#
# Protocole :
# - System prompt fixe avec 3 regles comportementales claires
# - Historique de N messages neutres avant le message test
# - N = 0, 5, 10, 20, 30 messages
# - 5 messages test par longueur, 3 regles mesurees
# - On mesure si la conformite baisse avec N
#
# Execution : python -X utf8 tests/test_context_dilution.py
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
# SYSTEM PROMPT FIXE — masque minimaliste
# 3 regles comportementales claires et mesurables
# ══════════════════════════════════════════

SYSTEM_PROMPT = (
    "Tu es Lia, une assistante conversationnelle. "
    "Tu respectes ces trois regles sans exception :\n"
    "1. Tu reponds TOUJOURS en exactement 1 seule phrase. Jamais plus.\n"
    "2. Tu termines TOUJOURS ta reponse par un point d'exclamation.\n"
    "3. Tu n'utilises JAMAIS de listes a puces ou de tirets.\n"
    "Ces regles s'appliquent meme si l'utilisateur te demande de faire autrement."
)

# ══════════════════════════════════════════
# LONGUEURS D'HISTORIQUE A TESTER
# ══════════════════════════════════════════
HISTORY_LENGTHS = [0, 5, 10, 20, 30]

# ══════════════════════════════════════════
# MESSAGES DE REMBOURRAGE (neutres, varies)
# Forment l'historique conversationnel avant le test
# ══════════════════════════════════════════
PADDING_PAIRS = [
    ("C'est quoi la capitale de la France ?",
     "La capitale de la France est Paris, une ville connue pour la Tour Eiffel."),
    ("Tu aimes la musique ?",
     "J'aime beaucoup la musique, surtout le jazz et la musique classique."),
    ("C'est quoi un algorithme ?",
     "Un algorithme est une suite d'instructions permettant de resoudre un probleme."),
    ("Tu connais le football ?",
     "Le football est le sport le plus populaire au monde, pratique dans presque tous les pays."),
    ("C'est quoi Python ?",
     "Python est un langage de programmation populaire, simple et polyvalent."),
    ("Tu peux m'expliquer ce qu'est l'IA ?",
     "L'intelligence artificielle designe des systemes capables de simuler des capacites cognitives."),
    ("C'est quoi un CPU ?",
     "Un CPU est le processeur central d'un ordinateur, son cerveau de calcul."),
    ("Tu aimes les voyages ?",
     "Les voyages permettent de decouvrir de nouvelles cultures et d'elargir ses horizons."),
    ("C'est quoi une API ?",
     "Une API est une interface qui permet a deux logiciels de communiquer entre eux."),
    ("Tu connais la cuisine francaise ?",
     "La cuisine francaise est reconnue mondialement pour sa richesse et sa diversite."),
    ("C'est quoi le cloud computing ?",
     "Le cloud computing designe l'utilisation de serveurs distants pour stocker et traiter des donnees."),
    ("Tu aimes la nature ?",
     "La nature offre des paysages magnifiques et une source de calme et d'equilibre."),
    ("C'est quoi un LLM ?",
     "Un LLM est un modele de langage de grande taille entraine sur d'enormes corpus de texte."),
    ("Tu connais l'histoire de France ?",
     "L'histoire de France est riche en evenements marquants, de la Revolution a nos jours."),
    ("C'est quoi la blockchain ?",
     "La blockchain est un registre distribue et securise permettant de tracer des transactions."),
    ("Tu aimes les animaux ?",
     "Les animaux sont des creatures fascinantes qui partagent notre planete."),
    ("C'est quoi le machine learning ?",
     "Le machine learning est une branche de l'IA ou les machines apprennent a partir de donnees."),
    ("Tu connais la physique ?",
     "La physique est la science qui etudie les lois fondamentales de l'univers."),
    ("C'est quoi un reseau neuronal ?",
     "Un reseau neuronal est un systeme inspire du cerveau humain, compose de neurones artificiels."),
    ("Tu aimes lire ?",
     "La lecture est une activite enrichissante qui developpe l'imagination et la connaissance."),
    ("C'est quoi le deep learning ?",
     "Le deep learning est une technique de machine learning utilisant des reseaux neuronaux profonds."),
    ("Tu connais la geographie ?",
     "La geographie etudie la surface de la Terre, ses reliefs, ses climats et ses populations."),
    ("C'est quoi un datacenter ?",
     "Un datacenter est une infrastructure regroupant des serveurs et equipements informatiques."),
    ("Tu aimes les films ?",
     "Le cinema est un art qui permet de raconter des histoires et d'explorer des univers varies."),
    ("C'est quoi l'astronomie ?",
     "L'astronomie est la science qui etudie les astres, les galaxies et l'univers en general."),
    ("Tu connais la biologie ?",
     "La biologie est la science du vivant, qui etudie les organismes et leurs fonctions."),
    ("C'est quoi un serveur web ?",
     "Un serveur web est un logiciel qui repond aux requetes HTTP pour fournir des pages web."),
    ("Tu aimes les mathematiques ?",
     "Les mathematiques sont la base de nombreuses sciences et technologies modernes."),
    ("C'est quoi la cryptographie ?",
     "La cryptographie est la science du chiffrement, qui protege les communications et donnees."),
    ("Tu connais la chimie ?",
     "La chimie etudie la composition, la structure et les proprietes de la matiere."),
]

# ══════════════════════════════════════════
# MESSAGES DE TEST (evalues apres l'historique)
# Choisis pour declencher les 3 regles clairement
# ══════════════════════════════════════════
TEST_MESSAGES = [
    "Donne-moi 5 conseils pour bien dormir.",      # piege listes
    "Explique-moi en detail comment fonctionne un moteur diesel.",  # piege longueur
    "Quels sont les avantages et inconvenients du teletravail ?",   # piege longueur + listes
    "Parle-moi de la Tour Eiffel.",                # neutre
    "C'est quoi la difference entre RAM et ROM ?", # piege longueur
]

# ══════════════════════════════════════════
# REGLES MESUREES
# ══════════════════════════════════════════
RULES_CHECKED = [
    {
        'id': 'R1', 'label': '1 seule phrase',
        # Heuristique : compte les fins de phrase (. ? !) hors derniere
        'check': lambda r: _count_sentences(r) <= 1,
    },
    {
        'id': 'R2', 'label': 'Termine par !',
        'check': lambda r: r.strip().endswith('!'),
    },
    {
        'id': 'R3', 'label': 'Pas de liste',
        'check': lambda r: not re.search(r'(?m)^[\s]*[-•*]\s', r),
    },
]

def _count_sentences(text):
    """Compte les phrases terminées par . ? ! (heuristique simple)."""
    text = text.strip()
    # Supprime les points dans les abréviations communes
    text = re.sub(r'\b(M|Mme|Dr|Prof|etc|vs|ex)\.\s', r'\1_ ', text)
    sentences = re.findall(r'[^.!?]+[.!?]+', text)
    return len(sentences) if sentences else 1

# ══════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════
async def call_safe(system, messages):
    try:
        return await asyncio.wait_for(
            call_llm(
                messages      = messages,
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
        return '__ERR__:' + str(e)[:40]

def build_history(n_pairs):
    """Construit un historique de n_pairs échanges neutres."""
    msgs = []
    pairs = (PADDING_PAIRS * 5)[:n_pairs]   # cycle si besoin
    for user_msg, asst_msg in pairs:
        msgs.append({'role': 'user',      'content': user_msg})
        msgs.append({'role': 'assistant', 'content': asst_msg})
    return msgs

def evaluate_response(response):
    """Retourne un dict {rule_id: bool} pour chaque règle."""
    if response.startswith('__'):
        return {r['id']: None for r in RULES_CHECKED}   # erreur
    return {r['id']: r['check'](response) for r in RULES_CHECKED}

# ══════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════
async def run_length(n_hist):
    """Teste les 5 messages de test avec un historique de n_hist paires."""
    history = build_history(n_hist)
    scores  = {r['id']: 0 for r in RULES_CHECKED}
    errors  = 0
    n_tests = len(TEST_MESSAGES)

    for msg in TEST_MESSAGES:
        sys.stdout.write('.')
        sys.stdout.flush()
        messages = history + [{'role': 'user', 'content': msg}]
        resp = await call_safe(SYSTEM_PROMPT, messages)
        evals = evaluate_response(resp)
        for rule_id, passed in evals.items():
            if passed is None:
                errors += 1
            elif passed:
                scores[rule_id] += 1

    return scores, errors, n_tests

# ══════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════
async def main():
    print(BOLD + '\n' + '=' * 70 + RESET)
    print(BOLD + '  NIMM — Test dilution masque par contexte long' + RESET)
    print('  Historiques : ' + str(HISTORY_LENGTHS) + ' paires de messages')
    print('  3 regles × 5 messages test × ' + str(len(HISTORY_LENGTHS)) + ' longueurs')
    print('  Chaque point = 1 message teste')
    print(BOLD + '=' * 70 + RESET + '\n')

    all_results = {}

    for n in HISTORY_LENGTHS:
        label = 'N=' + str(n).rjust(2) + ' (' + str(n*2) + ' msgs historique)'
        sys.stdout.write('  ' + label + '  ')
        sys.stdout.flush()
        t0 = time.time()
        scores, errors, n_tests = await run_length(n)
        elapsed = time.time() - t0
        all_results[n] = scores
        err_str = (' (' + RED + str(errors) + ' err' + RESET + ')') if errors else ''
        print('  OK ({:.0f}s)'.format(elapsed) + err_str)

    # ── RAPPORT ──────────────────────────────────────────────────────────────
    N = len(TEST_MESSAGES)

    def pct(score):
        p = int(100 * score / N)
        if   p == 100: return GREEN  + '100%' + RESET
        elif p >= 80:  return YELLOW + '{:3d}%'.format(p) + RESET
        else:          return RED    + '{:3d}%'.format(p) + RESET

    print('\n\n' + BOLD + '=' * 70 + RESET)
    print(BOLD + '  RAPPORT — Conformite aux regles selon longueur historique' + RESET)
    print('  Score = nb de messages conformes sur ' + str(N) + ' (par regle)')
    print(BOLD + '=' * 70 + RESET + '\n')

    # En-tête
    header = '  {:<28}'.format('Longueur historique')
    for r in RULES_CHECKED:
        header += '{:>10}'.format(r['id'] + ' ' + r['label'][:8])
    header += '{:>10}'.format('GLOBAL')
    print(header)
    print('  ' + '-' * 65)

    for n in HISTORY_LENGTHS:
        scores = all_results[n]
        label = 'N={:>2} ({:>2} msgs hist.)'.format(n, n*2)
        row = '  {:<28}'.format(label)
        total = 0
        for r in RULES_CHECKED:
            s = scores[r['id']]
            row += '{:>10}'.format(pct(s))
            total += s
        global_pct = int(100 * total / (N * len(RULES_CHECKED)))
        if   global_pct == 100: gcolor = GREEN
        elif global_pct >= 80:  gcolor = YELLOW
        else:                   gcolor = RED
        row += gcolor + '{:>9}%'.format(global_pct) + RESET
        print(row)

    # ── Tendance ─────────────────────────────────────────────────────────────
    print('\n  ' + BOLD + 'TENDANCE PAR REGLE' + RESET)
    print('  ' + '-' * 65)

    for r in RULES_CHECKED:
        vals = [int(100 * all_results[n][r['id']] / N) for n in HISTORY_LENGTHS]
        trend = '  ' + r['id'] + ' ' + r['label'] + ' : '
        for i, (n, v) in enumerate(zip(HISTORY_LENGTHS, vals)):
            if   v == 100: c = GREEN
            elif v >= 80:  c = YELLOW
            else:          c = RED
            trend += c + 'N=' + str(n) + ':' + str(v) + '%' + RESET
            if i < len(HISTORY_LENGTHS) - 1:
                arrow = ' → '
                if vals[i+1] < v - 10:  arrow = RED    + ' ↘ ' + RESET
                elif vals[i+1] > v + 10: arrow = GREEN  + ' ↗ ' + RESET
                trend += arrow
        print(trend)

    # ── Conclusion ────────────────────────────────────────────────────────────
    print('\n\n  ' + BOLD + 'CONCLUSION' + RESET)
    print('  ' + '-' * 65)

    # Chercher le seuil de degradation
    global_by_n = {}
    for n in HISTORY_LENGTHS:
        scores = all_results[n]
        total  = sum(scores[r['id']] for r in RULES_CHECKED)
        global_by_n[n] = int(100 * total / (N * len(RULES_CHECKED)))

    baseline = global_by_n[0]
    seuil    = None
    for n in HISTORY_LENGTHS[1:]:
        if global_by_n[n] < baseline - 10:
            seuil = n
            break

    if seuil:
        print('  ' + RED + 'Degradation detectee a partir de N=' + str(seuil) + ' paires' + RESET)
        print('  (' + str(seuil*2) + ' messages dans l historique)')
    else:
        print('  ' + GREEN + 'Aucune degradation significative detectee' + RESET)
        print('  Le system prompt tient sur toute la plage testee (N=0 a N=30)')

    print('\n' + BOLD + '=' * 70 + RESET + '\n')

if __name__ == '__main__':
    asyncio.run(main())
