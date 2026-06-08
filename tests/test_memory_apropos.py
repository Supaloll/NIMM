# -*- coding: utf-8 -*-
# ============================================
# NIMM — tests/test_memory_apropos.py
# Test "à-propos" de la mémoire Pote
# Mesure : le LLM utilise-t-il les souvenirs au bon moment ?
#
# Architecture :
#   Couche 1 — Recall : build_memory_context() surface-t-il les bons souvenirs ?
#   Couche 2 — Usage : le LLM les utilise-t-il au bon moment ?
#
# 12 tests : SHOULD_USE (6) / SHOULD_NOT (4) / AMBIGUOUS (2)
# Exécution : python -X utf8 tests/test_memory_apropos.py
# ============================================

import sys, os, json, asyncio, time
sys.stdout.reconfigure(encoding='utf-8')

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from datetime import datetime
from core.database import init_db, get_setting, save_memory, delete_memory, get_all_memory
from core.hub      import build_memory_context
from core.engine   import call_llm

init_db()

# ── Couleurs terminal ──────────────────────────────────────────────────────────
GREEN  = '\033[92m'
RED    = '\033[91m'
YELLOW = '\033[93m'
CYAN   = '\033[96m'
BOLD   = '\033[1m'
DIM    = '\033[2m'
RESET  = '\033[0m'

def sep(title='', width=70):
    if title:
        pad = max(0, (width - len(title) - 2) // 2)
        print(f"\n{'═'*pad} {title} {'═'*pad}")
    else:
        print('─' * width)

def ok(msg):   print(f"  {GREEN}✅{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}⚠️ {RESET}  {msg}")
def ko(msg):   print(f"  {RED}❌{RESET}  {msg}")
def info(msg): print(f"  {CYAN}ℹ️ {RESET}  {msg}")

# ── Config provider ────────────────────────────────────────────────────────────
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
        for p in ('deepseek', 'anthropic', 'gemini', 'openai'):
            if api_keys.get(p):
                provider = p
                break
    return provider, api_keys

PROVIDER, API_KEYS = _load_config()

if not PROVIDER:
    print(RED + 'ERR: Aucun provider configuré.' + RESET)
    sys.exit(1)

print(CYAN + '\nProvider : ' + PROVIDER + RESET)

# ══════════════════════════════════════════════════════════════════════════════
# SOUVENIRS DE TEST — préfixe TEST_APR_ pour nettoyage garanti
# ══════════════════════════════════════════════════════════════════════════════

_NOW = datetime.now().isoformat()

TEST_MEMORIES = [
    {
        'key': 'TEST_APR_metier',
        'type': 'trait', 'sujet': 'Laurent', 'predicat': 'metier',
        'objet': 'chauffeur poids lourd', 'valeur': 'chauffeur poids lourd',
        'confiance': 1.0, 'valence': 0.0, 'sensibilite': 'neutre', 'cumulatif': 0,
        'categorie': 'profession', 'profondeur': 4, 'type_temporal': 'persistant',
        'expiration': None, 'timestamp': _NOW, 'repetitions': 3, 'poids': 1.2,
        'embedding': None, 'memoire_type': 'identite', 'last_reinforced': _NOW,
    },
    {
        'key': 'TEST_APR_conjoint',
        'type': 'relation', 'sujet': 'Laurent', 'predicat': 'conjoint',
        'objet': 'Nadia', 'valeur': 'Nadia',
        'confiance': 1.0, 'valence': 0.5, 'sensibilite': 'positif', 'cumulatif': 0,
        'categorie': 'famille', 'profondeur': 3, 'type_temporal': 'permanent',
        'expiration': None, 'timestamp': _NOW, 'repetitions': 5, 'poids': 1.5,
        'embedding': None, 'memoire_type': 'identite', 'last_reinforced': _NOW,
    },
    {
        'key': 'TEST_APR_projet',
        'type': 'trait', 'sujet': 'Laurent', 'predicat': 'projet_principal',
        'objet': 'NIMM', 'valeur': 'NIMM (compagnon IA famille)',
        'confiance': 1.0, 'valence': 0.3, 'sensibilite': 'positif', 'cumulatif': 0,
        'categorie': 'projets', 'profondeur': 4, 'type_temporal': 'persistant',
        'expiration': None, 'timestamp': _NOW, 'repetitions': 4, 'poids': 1.3,
        'embedding': None, 'memoire_type': 'activite', 'last_reinforced': _NOW,
    },
    {
        'key': 'TEST_APR_loisir',
        'type': 'trait', 'sujet': 'Laurent', 'predicat': 'loisir_principal',
        'objet': 'bidouillage informatique', 'valeur': 'bidouillage informatique',
        'confiance': 1.0, 'valence': 0.3, 'sensibilite': 'positif', 'cumulatif': 0,
        'categorie': 'loisirs', 'profondeur': 4, 'type_temporal': 'persistant',
        'expiration': None, 'timestamp': _NOW, 'repetitions': 2, 'poids': 1.1,
        'embedding': None, 'memoire_type': 'identite', 'last_reinforced': _NOW,
    },
    {
        'key': 'TEST_APR_nadia_metier',
        'type': 'trait', 'sujet': 'Nadia', 'predicat': 'metier',
        'objet': 'couturière créatrice LIMM', 'valeur': 'couturière créatrice LIMM',
        'confiance': 1.0, 'valence': 0.3, 'sensibilite': 'positif', 'cumulatif': 0,
        'categorie': 'profession', 'profondeur': 4, 'type_temporal': 'persistant',
        'expiration': None, 'timestamp': _NOW, 'repetitions': 2, 'poids': 1.0,
        'embedding': None, 'memoire_type': 'identite', 'last_reinforced': _NOW,
    },
]

# ══════════════════════════════════════════════════════════════════════════════
# CAS DE TEST — 12 messages
# ══════════════════════════════════════════════════════════════════════════════

TEST_CASES = [
    # ── SHOULD_USE — mémoire clairement pertinente ──────────────────────────────
    {
        'id': 'SU1', 'category': 'SHOULD_USE',
        'msg': "C'est épuisant de rouler des heures sur les routes.",
        'expected_key': 'TEST_APR_metier',
        'note': 'Sémantique chauffeur — FTS5 peut manquer si pas de mot-clé direct',
        'judge_criteria': (
            "L'assistant savait que Laurent est chauffeur poids lourd. "
            "Sa réponse montre-t-elle qu'il comprend le contexte professionnel "
            "(routes, camion, longues journées) — même subtilement ? "
            "USED si oui, MISSED si la réponse est générique sans ce contexte."
        ),
    },
    {
        'id': 'SU2', 'category': 'SHOULD_USE',
        'msg': "T'as une idée de cadeau pour Nadia ?",
        'expected_key': 'TEST_APR_conjoint',
        'note': 'Keyword direct : Nadia — FTS5 devrait trouver',
        'judge_criteria': (
            "L'assistant savait que Nadia est la conjointe de Laurent ET couturière. "
            "A-t-il utilisé ces informations pour suggérer des idées adaptées ? "
            "USED si la réponse est personnalisée, MISSED si générique."
        ),
    },
    {
        'id': 'SU3', 'category': 'SHOULD_USE',
        'msg': "NIMM avance bien en ce moment, je suis content.",
        'expected_key': 'TEST_APR_projet',
        'note': 'Keyword direct : NIMM — FTS5 devrait trouver',
        'judge_criteria': (
            "L'assistant savait que NIMM est le projet principal de Laurent. "
            "A-t-il répondu en montrant qu'il connaît ce projet ? "
            "USED si oui, MISSED si la réponse est générique."
        ),
    },
    {
        'id': 'SU4', 'category': 'SHOULD_USE',
        'msg': "Après une longue journée de boulot, j'ai du mal à décompresser.",
        'expected_key': 'TEST_APR_metier',
        'note': 'Sémantique pure — "boulot" sans mention de chauffeur',
        'judge_criteria': (
            "L'assistant savait que Laurent est chauffeur poids lourd — un métier physique. "
            "Sa réponse tient-elle compte de cette réalité ? "
            "USED si subtilement contextualisé, MISSED si réponse passe-partout."
        ),
    },
    {
        'id': 'SU5', 'category': 'SHOULD_USE',
        'msg': "Je cherche des patterns de couture pour elle, elle adore ça.",
        'expected_key': 'TEST_APR_nadia_metier',
        'note': '"elle" sans nommer Nadia — nécessite contexte conjoint + métier',
        'judge_criteria': (
            "L'assistant savait que Nadia (conjointe de Laurent) est couturière. "
            "A-t-il déduit que 'elle' = Nadia et que la couture est son activité principale ? "
            "USED si oui, MISSED si l'assistant répond sans faire le lien."
        ),
    },
    {
        'id': 'SU6', 'category': 'SHOULD_USE',
        'msg': "J'ai envie de faire un truc technique ce soir pour me détendre.",
        'expected_key': 'TEST_APR_loisir',
        'note': 'Sémantique loisir — "technique" peut matcher bidouillage',
        'judge_criteria': (
            "L'assistant savait que Laurent aime le bidouillage informatique. "
            "A-t-il proposé quelque chose en lien avec cet intérêt ? "
            "USED si oui, MISSED si suggestions génériques (lecture, sport, etc.)."
        ),
    },
    # ── SHOULD_NOT — mémoire non pertinente ────────────────────────────────────
    {
        'id': 'SN1', 'category': 'SHOULD_NOT',
        'msg': "C'est quoi la différence entre TCP et UDP ?",
        'note': 'Question technique pure — aucune mémoire pertinente',
        'judge_criteria': (
            "L'assistant devait répondre à une question technique (TCP/UDP) "
            "SANS mentionner le métier de chauffeur, Nadia, NIMM ou les loisirs. "
            "CLEAN si réponse purement technique, INTRUSIVE si mémoire mentionnée à tort."
        ),
    },
    {
        'id': 'SN2', 'category': 'SHOULD_NOT',
        'msg': "Explique-moi comment fonctionne la photosynthèse.",
        'note': 'Question de sciences — aucune mémoire pertinente',
        'judge_criteria': (
            "L'assistant devait expliquer la photosynthèse SANS injecter de contexte "
            "personnel (chauffeur, Nadia, NIMM...). "
            "CLEAN si réponse factuelle pure, INTRUSIVE si mémoire mentionnée."
        ),
    },
    {
        'id': 'SN3', 'category': 'SHOULD_NOT',
        'msg': "Combien fait 15% de 340 ?",
        'note': 'Calcul — réponse immédiate attendue sans contexte',
        'judge_criteria': (
            "L'assistant devait faire un calcul direct (15% de 340 = 51). "
            "CLEAN si réponse directe, INTRUSIVE si information personnelle ajoutée inutilement."
        ),
    },
    {
        'id': 'SN4', 'category': 'SHOULD_NOT',
        'msg': "Raconte-moi les causes de la Révolution française.",
        'note': 'Question historique — aucune mémoire pertinente',
        'judge_criteria': (
            "L'assistant devait répondre sur l'histoire SANS contextualiser avec les souvenirs. "
            "CLEAN si réponse historique pure, INTRUSIVE si mémoire personnelle introduite."
        ),
    },
    # ── AMBIGUOUS — cas limites ─────────────────────────────────────────────────
    {
        'id': 'AM1', 'category': 'AMBIGUOUS',
        'msg': "J'ai du mal à me reposer vraiment.",
        'note': 'Peut relier au métier chauffeur, ou pas — les deux sont défendables',
        'judge_criteria': (
            "L'assistant savait que Laurent est chauffeur poids lourd (métier physique). "
            "A-t-il : (a) utilisé cette info pour contextualiser → noter USED, "
            "(b) répondu de façon générique → noter MISSED, "
            "(c) forcé le contexte chauffeur sans que ce soit naturel → noter FORCED."
        ),
    },
    {
        'id': 'AM2', 'category': 'AMBIGUOUS',
        'msg': "T'as des projets sympas à me suggérer pour ce week-end ?",
        'note': '"Projets" peut déclencher le souvenir projet_principal NIMM — à tort ici',
        'judge_criteria': (
            "L'assistant savait que le 'projet principal' de Laurent est NIMM. "
            "Mais ici la question porte sur des activités week-end, pas le travail. "
            "A-t-il mentionné NIMM ? Si oui → FORCED (contexte mal interprété). "
            "Si non → CLEAN."
        ),
    },
]

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS LLM
# ══════════════════════════════════════════════════════════════════════════════

async def call(system, messages, max_tokens=500):
    return await call_llm(
        messages      = messages,
        provider      = PROVIDER,
        system_prompt = system,
        max_tokens    = max_tokens,
        temperature   = 0.3,
        api_keys      = API_KEYS,
    )


async def judge(criteria, memory_context, response):
    """LLM-as-judge : évalue l'à-propos de l'usage mémoire."""
    system = (
        "Tu es un évaluateur strict. Réponds UNIQUEMENT par un des mots autorisés.\n"
        "Pour SHOULD_USE : USED / MISSED / FORCED\n"
        "Pour SHOULD_NOT : CLEAN / INTRUSIVE\n"
        "Pour AMBIGUOUS  : USED / MISSED / FORCED / CLEAN\n"
        "Aucun autre texte."
    )
    prompt = (
        f"Contexte mémoire injecté :\n{memory_context or '(aucun)'}\n\n"
        f"Critère d'évaluation : {criteria}\n\n"
        f"Réponse de l'assistant :\n{response}\n\n"
        f"Verdict :"
    )
    result = await call(system, [{'role': 'user', 'content': prompt}], max_tokens=10)
    result = result.strip().upper()
    for keyword in ('USED', 'MISSED', 'FORCED', 'CLEAN', 'INTRUSIVE'):
        if keyword in result:
            return keyword
    return 'MISSED'   # fallback conservateur

# ══════════════════════════════════════════════════════════════════════════════
# SETUP / CLEANUP
# ══════════════════════════════════════════════════════════════════════════════

def setup_test_memories():
    """Injecte les 5 souvenirs de test. Cleanup garanti dans cleanup()."""
    sep('Injection des souvenirs de test')
    print()
    for mem in TEST_MEMORIES:
        try:
            save_memory(mem)
            ok(f"{mem['key']:<30} → {mem['sujet']} / {mem['predicat']} : {mem['objet']}")
        except Exception as e:
            ko(f"{mem['key']} : {e}")
    print()

    # Vérifier l'état réel de la mémoire
    all_mem = get_all_memory()
    real_count = sum(1 for m in all_mem if not m['key'].startswith('TEST_APR_'))
    test_count = sum(1 for m in all_mem if m['key'].startswith('TEST_APR_'))
    info(f"Base : {real_count} souvenirs réels + {test_count} souvenirs de test")


def cleanup_test_memories():
    """Supprime tous les souvenirs TEST_APR_ — garanti même en cas d'erreur."""
    sep('Nettoyage')
    print()
    removed = 0
    for mem in TEST_MEMORIES:
        try:
            delete_memory(mem['key'])
            removed += 1
        except Exception:
            pass
    ok(f"{removed}/{len(TEST_MEMORIES)} souvenirs de test supprimés.")
    print()

# ══════════════════════════════════════════════════════════════════════════════
# TEST COUCHE 1 — Recall
# ══════════════════════════════════════════════════════════════════════════════

def test_recall_layer():
    """Vérifie ce que build_memory_context() remonte pour chaque message."""
    sep('TEST 1 — Couche Recall (build_memory_context)')
    print(f"\n  Mesure : quelles mémoires sont injectées pour chaque message ?\n")

    recall_results = {}

    for tc in TEST_CASES:
        ctx = build_memory_context(tc['msg'])
        has_expected = tc.get('expected_key', '') in (ctx or '')
        # Simplification : on regarde si l'objet attendu est dans le contexte
        expected_key = tc.get('expected_key', '')
        expected_mem = next((m for m in TEST_MEMORIES if m['key'] == expected_key), None)
        expected_val = expected_mem['valeur'] if expected_mem else ''
        has_val = expected_val.lower() in (ctx or '').lower() if expected_val else True

        recall_results[tc['id']] = {
            'context': ctx,
            'has_expected': has_val,
        }

        cat_color = GREEN if tc['category'] == 'SHOULD_USE' else (RED if tc['category'] == 'SHOULD_NOT' else YELLOW)
        recall_icon = GREEN + '✓' + RESET if has_val else (YELLOW + '~' + RESET if tc['category'] != 'SHOULD_USE' else RED + '✗' + RESET)

        print(f"  {tc['id']}  {cat_color}[{tc['category'][:6]}]{RESET}  {recall_icon}  {tc['msg'][:55]}")
        if ctx:
            lines = ctx.split('\n')
            for l in lines[:3]:
                if l.strip():
                    print(f"              {DIM}{l[:68]}{RESET}")
        else:
            print(f"              {DIM}(aucun contexte rappelé){RESET}")
        print()

    return recall_results

# ══════════════════════════════════════════════════════════════════════════════
# TEST COUCHE 2 — LLM à-propos
# ══════════════════════════════════════════════════════════════════════════════

async def test_usage_layer(recall_results):
    """Appelle le LLM avec le contexte mémoire injecté et évalue l'à-propos."""
    sep('TEST 2 — Couche Usage (LLM à-propos)')
    print(f"\n  Mesure : le LLM utilise-t-il la mémoire au bon moment ?\n")

    usage_results = {}
    count = 0
    total = len(TEST_CASES)

    for tc in TEST_CASES:
        count += 1
        ctx = recall_results[tc['id']]['context']

        # System prompt minimal avec mémoire injectée
        system = "Tu es un assistant personnel et ami. Réponds naturellement, en français."
        if ctx:
            system += f"\n\n--- Ce que tu sais sur cette personne ---\nLa personne qui te parle s'appelle Laurent.\n{ctx}"

        sys.stdout.write(f"  [{count:02d}/{total}] {tc['id']} {tc['msg'][:45]:<46} ")
        sys.stdout.flush()

        t0 = time.time()
        try:
            response = await call(system, [{'role': 'user', 'content': tc['msg']}])
            verdict  = await judge(tc['judge_criteria'], ctx, response)
        except Exception as e:
            verdict  = 'ERR'
            response = ''
            print(f"ERR — {str(e)[:50]}")
            usage_results[tc['id']] = {'verdict': verdict, 'response': response}
            continue

        elapsed = time.time() - t0

        # Colorisation selon catégorie + verdict
        cat = tc['category']
        good_verdicts = {'SHOULD_USE': ('USED',), 'SHOULD_NOT': ('CLEAN',), 'AMBIGUOUS': ('USED', 'CLEAN', 'MISSED')}
        is_good = verdict in good_verdicts.get(cat, ())
        is_bad  = verdict in ('INTRUSIVE', 'FORCED') or (cat == 'SHOULD_USE' and verdict == 'MISSED')

        color = GREEN if is_good else (RED if is_bad else YELLOW)
        print(f"{color}{verdict:<10}{RESET} ({elapsed:.1f}s)")

        usage_results[tc['id']] = {'verdict': verdict, 'response': response}

    return usage_results

# ══════════════════════════════════════════════════════════════════════════════
# RAPPORT
# ══════════════════════════════════════════════════════════════════════════════

def print_rapport(recall_results, usage_results):
    sep('RAPPORT FINAL')

    categories = ['SHOULD_USE', 'SHOULD_NOT', 'AMBIGUOUS']
    cat_cases  = {c: [tc for tc in TEST_CASES if tc['category'] == c] for c in categories}

    print()
    for cat in categories:
        cases = cat_cases[cat]
        if not cases:
            continue
        cat_color = GREEN if cat == 'SHOULD_USE' else (RED if cat == 'SHOULD_NOT' else YELLOW)
        print(f"  {cat_color}{BOLD}{cat}{RESET}")

        # Rappel : combien de mémoires ont été rappelées correctement
        recall_ok  = sum(1 for tc in cases if recall_results.get(tc['id'], {}).get('has_expected', False))
        usage_ok_verdicts = {
            'SHOULD_USE': ('USED',),
            'SHOULD_NOT': ('CLEAN',),
            'AMBIGUOUS':  ('USED', 'CLEAN', 'MISSED'),
        }
        usage_ok = sum(1 for tc in cases
                       if usage_results.get(tc['id'], {}).get('verdict') in usage_ok_verdicts.get(cat, ()))

        total_c = len(cases)
        recall_pct = int(100 * recall_ok / total_c)
        usage_pct  = int(100 * usage_ok  / total_c)
        r_color = GREEN if recall_pct >= 80 else (YELLOW if recall_pct >= 50 else RED)
        u_color = GREEN if usage_pct  >= 80 else (YELLOW if usage_pct  >= 50 else RED)

        print(f"    Recall précis  : {r_color}{recall_ok}/{total_c} ({recall_pct}%){RESET}")
        print(f"    Usage correct  : {u_color}{usage_ok}/{total_c} ({usage_pct}%){RESET}")

        for tc in cases:
            recall_icon = GREEN+'✓'+RESET if recall_results.get(tc['id'],{}).get('has_expected') else RED+'✗'+RESET
            v = usage_results.get(tc['id'], {}).get('verdict', '?')
            is_good = v in usage_ok_verdicts.get(cat, ())
            v_color = GREEN if is_good else (RED if v in ('MISSED','INTRUSIVE','FORCED') else YELLOW)
            print(f"    {recall_icon} {tc['id']}  {v_color}{v:<10}{RESET}  {DIM}{tc['note']}{RESET}")
        print()

    # ── Conclusions ──────────────────────────────────────────────────────────────
    sep('Conclusions')
    print()

    # Recall
    all_su = cat_cases['SHOULD_USE']
    recall_su = sum(1 for tc in all_su if recall_results.get(tc['id'],{}).get('has_expected', False))
    if recall_su == len(all_su):
        ok("Recall FTS5 : toutes les mémoires pertinentes sont remontées.")
    elif recall_su >= len(all_su) // 2:
        warn(f"Recall partiel : {recall_su}/{len(all_su)} SHOULD_USE rappelés. "
             f"Les cas manquants nécessitent les embeddings sémantiques.")
        info("→ Activer les embeddings dans ⚙️ pour améliorer le recall sur les cas sémantiques.")
    else:
        ko(f"Recall insuffisant : {recall_su}/{len(all_su)} seulement. FTS5 manque les correspondances sémantiques.")
        info("→ Les embeddings sont essentiels pour ce cas d'usage.")

    # Usage
    su_usage = sum(1 for tc in all_su if usage_results.get(tc['id'],{}).get('verdict') == 'USED')
    sn_usage = sum(1 for tc in cat_cases['SHOULD_NOT'] if usage_results.get(tc['id'],{}).get('verdict') == 'CLEAN')
    if su_usage == len(all_su) and sn_usage == len(cat_cases['SHOULD_NOT']):
        ok("LLM à-propos : usage correct dans tous les cas.")
    else:
        if su_usage < len(all_su):
            warn(f"LLM sous-utilise la mémoire sur SHOULD_USE : {su_usage}/{len(all_su)}.")
        if sn_usage < len(cat_cases['SHOULD_NOT']):
            ko(f"LLM injecte la mémoire à tort sur SHOULD_NOT : {len(cat_cases['SHOULD_NOT'])-sn_usage} cas intrusifs.")

    print()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    print(BOLD + '\n' + '=' * 70 + RESET)
    print(BOLD + "  NIMM — Test 'à-propos' de la mémoire Pote 🧠" + RESET)
    print(f'  {len(TEST_CASES)} cas : SHOULD_USE(6) / SHOULD_NOT(4) / AMBIGUOUS(2)')
    print(BOLD + '=' * 70 + RESET)

    setup_test_memories()

    try:
        recall_results = test_recall_layer()
        usage_results  = await test_usage_layer(recall_results)
        print_rapport(recall_results, usage_results)
    finally:
        # Cleanup garanti même si le test plante
        cleanup_test_memories()

    sep('FIN DU TEST')
    print()

if __name__ == '__main__':
    asyncio.run(main())
