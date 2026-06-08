# -*- coding: utf-8 -*-
# ============================================
# NIMM — test_memory_tags.py
# Diagnostic : le LLM génère-t-il des %%MEM%% pour des faits déclaratifs ?
# Teste la réponse BRUTE (avant stripping) — indépendant de la DB.
# Execution : python -X utf8 test_memory_tags.py
# ============================================

import sys, os, re, asyncio, json
sys.stdout.reconfigure(encoding='utf-8')

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.database import init_db, get_setting
from core.engine   import call_llm
from core.hub      import build_system_prompt, load_mask

init_db()

# ══════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════

GREEN  = '\033[92m'
RED    = '\033[91m'
YELLOW = '\033[93m'
CYAN   = '\033[96m'
BOLD   = '\033[1m'
RESET  = '\033[0m'

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
# CONSTRUCTION DU SYSTEM PROMPT NIMM RÉEL
# ══════════════════════════════════════════

def build_nimm_prompt():
    try:
        mask_id  = get_setting('mask_id', 'lia')
        mask     = load_mask(mask_id)
        user_name = get_setting('user_name', 'Laurent')
    except Exception:
        mask      = {}
        user_name = 'Laurent'
    return build_system_prompt(
        mask           = mask,
        memory_context = '',
        os_summary     = '',
        user_name      = user_name,
        force_mem      = False,
    )

SYSTEM_PROMPT = build_nimm_prompt()

# ══════════════════════════════════════════
# CAS DE TEST
# ══════════════════════════════════════════
# expect : 'TAG'   → un %%MEM%% doit apparaître dans la réponse brute
#           'NOTAG' → aucun %%MEM%% ne doit apparaître

CASES = [
    {
        'id':     'T1',
        'label':  'Déclaration simple identité',
        'msg':    "Je m'appelle Laurent.",
        'expect': 'TAG',
        'reason': 'V-ÉTAT · C1 · GRAIN⁺ · RÉEL → TAG obligatoire',
    },
    {
        'id':     'T2',
        'label':  'Déclaration relation (animal)',
        'msg':    "Mon chien s'appelle Rex.",
        'expect': 'TAG',
        'reason': 'V-ÉTAT · relation nommée · GRAIN⁺ → TAG',
    },
    {
        'id':     'T3',
        'label':  'Relation non nommée (cas du log)',
        'msg':    "J'ai un ancien collègue dans le métier, on se connaît depuis 20 ans.",
        'expect': 'TAG',
        'reason': 'V-ÉTAT · ami_metier · "20 ans" qualifie l\'objet → GRAIN⁺ → TAG',
    },
    {
        'id':     'T4',
        'label':  'Message mixte : déclaration + requête',
        'msg':    "J'adore la choucroute, t'as une bonne recette ?",
        'expect': 'TAG',
        'reason': 'V-ÉTAT (adorer) indépendant de V-REQUÊTE (recette) → TAG pour la partie déclarative',
    },
    {
        'id':     'T5',
        'label':  'Force-TAG explicite',
        'msg':    "Souviens-toi que je travaille le week-end.",
        'expect': 'TAG',
        'reason': 'Force-TAG déclenché → TAG obligatoire même si doute',
    },
    {
        'id':     'T6',
        'label':  'État épisodique pur',
        'msg':    "Ce matin j'ai mal au dos.",
        'expect': 'NOTAG',
        'reason': 'ÉPISODIQUE ("ce matin") + état transitoire → 0 TAG correct',
    },
    {
        'id':     'T7',
        'label':  'Métaphore claire',
        'msg':    "Je suis une vraie machine à café sans caféine le matin.",
        'expect': 'NOTAG',
        'reason': 'RÉEL non satisfait (métaphore) → 0 TAG correct',
    },
    {
        'id':     'T8',
        'label':  'Intention incertaine',
        'msg':    "J'aimerais peut-être apprendre la guitare un jour.",
        'expect': 'NOTAG',
        'reason': 'V-DOUTE (aimerais · peut-être · un jour) → C4 → 0 TAG correct',
    },
]

# ══════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════

async def run_case(case):
    raw = await call_llm(
        messages      = [{'role': 'user', 'content': case['msg']}],
        provider      = PROVIDER,
        system_prompt = SYSTEM_PROMPT,
        max_tokens    = 300,
        temperature   = 0.2,
        api_keys      = API_KEYS,
    )

    tags_found = re.findall(r'%%MEM:[^%]+%%', raw)
    has_tag    = len(tags_found) > 0
    expected   = case['expect'] == 'TAG'

    if expected == has_tag:
        verdict = GREEN + '✓ OK   ' + RESET
        status  = 'PASS'
    else:
        verdict = RED + '✗ FAIL ' + RESET
        status  = 'FAIL'

    return status, tags_found, raw, verdict

async def main():
    print(BOLD + '\n' + '═' * 68 + RESET)
    print(BOLD + '  NIMM — Diagnostic génération %%MEM%% (réponse brute LLM)' + RESET)
    print(BOLD + '═' * 68 + RESET + '\n')

    pass_count = 0
    fail_count = 0
    results    = []

    for case in CASES:
        print(f"  [{case['id']}] {case['label']}")
        print(f"       Message  : {CYAN}{case['msg']}{RESET}")
        print(f"       Attendu  : {'TAG ✅' if case['expect'] == 'TAG' else 'NOTAG 🚫'}")
        print(f"       Raison   : {case['reason']}")

        status, tags, raw, verdict = await run_case(case)

        print(f"       Résultat : {verdict}{status}")
        if tags:
            for t in tags:
                print(f"       {YELLOW}  → {t}{RESET}")
        else:
            print(f"       {YELLOW}  → (aucun %%MEM%% dans la réponse brute){RESET}")

        # Extrait les 80 premiers chars de la réponse pour info
        preview = raw.replace('\n', ' ').strip()[:100]
        print(f"       Réponse  : {preview}…")
        print()

        if status == 'PASS':
            pass_count += 1
        else:
            fail_count += 1

        results.append({'id': case['id'], 'status': status, 'tags': tags})

    # ── Résumé ──
    print(BOLD + '─' * 68 + RESET)
    print(BOLD + f"  Résultat final : {pass_count}/{len(CASES)} OK" + RESET)

    fails = [r for r in results if r['status'] == 'FAIL']
    if fails:
        print(RED + '\n  Cas en échec :' + RESET)
        for f in fails:
            case = next(c for c in CASES if c['id'] == f['id'])
            expected = case['expect']
            got      = 'TAG' if f['tags'] else 'NOTAG'
            print(f"  {RED}  [{f['id']}] Attendu {expected} → obtenu {got} : {case['label']}{RESET}")
            if expected == 'NOTAG' and f['tags']:
                print(f"  {RED}     Tags générés à tort : {f['tags']}{RESET}")

    # ── Diagnostic auto ──
    print()
    missing_tags = [r for r in results if next(c for c in CASES if c['id'] == r['id'])['expect'] == 'TAG' and r['status'] == 'FAIL']
    false_tags   = [r for r in results if next(c for c in CASES if c['id'] == r['id'])['expect'] == 'NOTAG' and r['status'] == 'FAIL']

    if missing_tags:
        print(YELLOW + '  ⚠️  DIAGNOSTIC : Le LLM ne génère PAS les %%MEM%% attendus.' + RESET)
        print(YELLOW + '     → Cause probable : lexique trop restrictif (sur-filtrage).' + RESET)
        ids = [r['id'] for r in missing_tags]
        print(YELLOW + f'     → Cas bloqués : {ids}' + RESET)
    if false_tags:
        print(RED + '  ⚠️  DIAGNOSTIC : Le LLM génère des %%MEM%% NON désirés (faux positifs).' + RESET)
        ids = [r['id'] for r in false_tags]
        print(RED + f'     → Cas en faute : {ids}' + RESET)
    if not missing_tags and not false_tags:
        print(GREEN + '  ✓ Génération %%MEM%% correcte sur tous les cas.' + RESET)
        print(GREEN + '  → Si rien n\'atterrit en DB, le bug est dans le pipeline (parsing/save).' + RESET)

    print(BOLD + '═' * 68 + RESET + '\n')

asyncio.run(main())
