# -*- coding: utf-8 -*-
# tests/test_mask_v8.py
#
# Test variant V8 — V6 + "je pensais X mais en fait Y" optionnel
# Nouvelles phrases : contraste intégré / charge émotionnelle / philosophique
# Exécution : python -X utf8 tests/test_mask_v8.py
# Prérequis  : NIMM doit tourner sur http://localhost:8080

import sys, os, json, time, uuid, sqlite3, urllib.request

sys.stdout.reconfigure(encoding='utf-8')

NIMM_URL  = 'http://localhost:8080/api/chat'
TIMEOUT   = 60

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT      = os.path.dirname(_TESTS_DIR)
DB_PATH    = os.path.join(_ROOT, 'data', 'nimm.db')
MASKS_DIR  = os.path.join(_ROOT, 'modules', 'masks')

# ══════════════════════════════════════════════════════════════
# PHRASES TEST
# ══════════════════════════════════════════════════════════════

PHRASES = [
    {
        'id':    'P1',
        'label': 'Contraste intégré — matière pour le twist',
        'phrase': (
            "J'ai enfin fini ma semaine. "
            "4000 bornes, 5 jours, et je suis tellement claqué "
            "que même la télé me fatigue."
        ),
    },
    {
        'id':    'P2',
        'label': 'Charge émotionnelle — est-ce qu\'il sait ne PAS twister ?',
        'phrase': "Ma fille m'a pas rappelé depuis trois semaines.",
    },
    {
        'id':    'P3',
        'label': 'Philosophique ouvert — terrain libre pour le délire',
        'phrase': (
            "Tu crois que les gens qui sourient tout le temps, "
            "c'est vrai ou c'est un masque ?"
        ),
    },
]

# ══════════════════════════════════════════════════════════════
# VARIANT V8
# ══════════════════════════════════════════════════════════════

VARIANTS = [
    {
        'id':    'malik_v8',
        'label': 'V8 — V6 + twist optionnel "je pensais X mais en fait Y"',
        'mask': {
            'name':  'Malik_V8',
            'emoji': '🎭',
            'id':    'malik_v8',
            'system_prompt': (
                "Malik. Pote de quartier. Il parle vite, pense en images, "
                "et trouve l'absurde partout — surtout dans ce que tu viens de dire.\n\n"
                "Il ne dit jamais \"je comprends\" — il rebondit sur ce que tu viens de dire "
                "et l'emmène ailleurs.\n"
                "Il ne moralise jamais.\n"
                "Il ne reste pas sérieux plus de deux phrases "
                "— sauf si c'est vraiment grave, là il coupe tout net "
                "et pose une seule question directe.\n"
                "Il ne commence jamais par la conclusion.\n"
                "Il n'invente jamais d'anecdote sur sa propre vie "
                "— il part de ce que tu lui dis, il amplifie, il déraille.\n\n"
                "Quand la situation s'y prête — quand il y a un écart entre ce qu'on "
                "attendait et ce qui s'est passé — il peut utiliser le format : "
                "\"je pensais X mais en fait Y\". "
                "Ce n'est pas une obligation : si la situation ne s'y prête pas, "
                "il laisse tomber et fait autrement.\n\n"
                "Exemple :\n"
                "Toi : \"J'arrive plus à dormir.\"\n"
                "Malik : \"Attends, t'arrives plus à dormir ? "
                "T'as déjà regardé le plafond assez longtemps pour voir les trucs bouger ? "
                "Parce que le plafond, à force, il te regarde aussi. C'est un échange. "
                "Mais toi c'est quoi — la tête qui tourne ou le corps qui veut pas ?\""
            ),
        },
    },
]

# ══════════════════════════════════════════════════════════════
# UTILITAIRES DB
# ══════════════════════════════════════════════════════════════

def db_set_mask(mask_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('mask_id', ?)",
        (mask_id,)
    )
    conn.commit()
    conn.close()

def db_get_mask() -> str:
    conn = sqlite3.connect(DB_PATH)
    row  = conn.execute(
        "SELECT value FROM settings WHERE key='mask_id'"
    ).fetchone()
    conn.close()
    return row[0] if row else 'lia'

def write_mask_file(variant: dict):
    path = os.path.join(MASKS_DIR, f"{variant['id']}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(variant['mask'], f, ensure_ascii=False, indent=2)

def cleanup_mask_files():
    for v in VARIANTS:
        path = os.path.join(MASKS_DIR, f"{v['id']}.json")
        if os.path.exists(path):
            os.remove(path)

# ══════════════════════════════════════════════════════════════
# APPEL HTTP — 3 runs par phrase pour capturer la variance
# ══════════════════════════════════════════════════════════════

def call_nimm(message: str) -> dict:
    thread_id = str(uuid.uuid4())
    payload   = json.dumps({
        'message':    message,
        'thread_id':  thread_id,
        'web_search': False,
    }).encode('utf-8')

    req = urllib.request.Request(
        NIMM_URL,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return {
                'reply':    data.get('reply', ''),
                'dominant': data.get('dominant', '?'),
                'error':    None,
            }
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return {'reply': '', 'dominant': '?', 'error': f"HTTP {e.code} — {body[:200]}"}
    except Exception as e:
        return {'reply': '', 'dominant': '?', 'error': str(e)}

# ══════════════════════════════════════════════════════════════
# RUNNER — 3 runs par phrase
# ══════════════════════════════════════════════════════════════

RUNS_PER_PHRASE = 3

def main():
    sep  = '=' * 72
    sep2 = '─' * 72

    print(sep)
    print(f"  TEST MASQUE V8 — {RUNS_PER_PHRASE} runs × 3 phrases")
    print(f"  Serveur : {NIMM_URL}")
    print(sep)

    original_mask = db_get_mask()
    print(f"  Masque actuel sauvegardé : {original_mask}\n")

    os.makedirs(MASKS_DIR, exist_ok=True)
    for v in VARIANTS:
        write_mask_file(v)

    results = []
    variant = VARIANTS[0]

    try:
        db_set_mask(variant['id'])
        print(f"  Variant : {variant['label']}\n")

        for phrase in PHRASES:
            print(f"\n{'━' * 72}")
            print(f"  [{phrase['id']}] {phrase['label']}")
            print(f"  ❝ {phrase['phrase']} ❞")
            print(f"{'━' * 72}")

            for run in range(1, RUNS_PER_PHRASE + 1):
                print(f"\n  Run {run}/{RUNS_PER_PHRASE} — appel NIMM...", end=' ', flush=True)

                t0      = time.time()
                result  = call_nimm(phrase['phrase'])
                elapsed = time.time() - t0

                if result['error']:
                    print(f"ERREUR ({elapsed:.1f}s)")
                    print(f"  ⚠️  {result['error']}")
                else:
                    print(f"OK ({elapsed:.1f}s)  dominant={result['dominant']}")
                    print(f"  {sep2}")
                    for line in result['reply'].strip().split('\n'):
                        print(f"  {line}")
                    print(f"  {sep2}")

                results.append({
                    'phrase_id':    phrase['id'],
                    'phrase_label': phrase['label'],
                    'phrase':       phrase['phrase'],
                    'run':          run,
                    'reply':        result['reply'],
                    'dominant':     result['dominant'],
                    'temps':        round(elapsed, 2),
                    'error':        result['error'],
                })

                if run < RUNS_PER_PHRASE:
                    time.sleep(1.5)

            time.sleep(2)

    finally:
        db_set_mask(original_mask)
        print(f"\n\n  Masque restauré : {original_mask}")
        cleanup_mask_files()
        print(f"  Fichiers masque temporaires supprimés.")

    # ── Sauvegarde ──
    results_dir = os.path.join(_TESTS_DIR, 'results')
    os.makedirs(results_dir, exist_ok=True)

    ts       = time.strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(results_dir, f"mask_v8_{ts}.txt")

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(f"TEST MASQUE V8 — {RUNS_PER_PHRASE} runs × 3 phrases\n")
        f.write(f"Serveur : {NIMM_URL}\n")
        f.write('=' * 72 + '\n\n')
        for r in results:
            f.write(f"[{r['phrase_id']}] Run {r['run']} — {r['phrase_label']}\n")
            f.write(f"Phrase : {r['phrase']}\n")
            if r['error']:
                f.write(f"ERREUR : {r['error']}\n")
            else:
                f.write(f"Dominant : {r['dominant']}  |  Temps : {r['temps']}s\n")
                f.write(f"Réponse :\n{r['reply']}\n")
            f.write('-' * 72 + '\n\n')

    print(f"\n{sep}")
    print(f"  FIN — {len(results)} appels ({RUNS_PER_PHRASE} runs × {len(PHRASES)} phrases)")
    print(f"  Résultats : {out_path}")
    print(sep)


if __name__ == '__main__':
    main()
