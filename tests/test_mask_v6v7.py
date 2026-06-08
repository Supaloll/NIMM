# -*- coding: utf-8 -*-
# tests/test_mask_v6v7.py
#
# Test variants V6 (hybride nominal+interdits+rebond) et V7 (twist absurde)
# Nouvelles phrases : courte / collègue / abstrait
# Exécution : python -X utf8 tests/test_mask_v6v7.py
# Prérequis  : NIMM doit tourner sur http://localhost:8080

import sys, os, json, time, uuid, sqlite3, urllib.request

sys.stdout.reconfigure(encoding='utf-8')

# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════

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
        'label': 'Phrase courte — transformer le rien',
        'phrase': "J'ai raté mon réveil ce matin.",
    },
    {
        'id':    'P2',
        'label': 'Collègue — situation de terrain, émotion contenue',
        'phrase': (
            "Mon collègue a encore laissé le camion dans un état... "
            "j'ai passé vingt minutes à nettoyer avant de partir. "
            "Je lui ai rien dit, mais putain."
        ),
    },
    {
        'id':    'P3',
        'label': 'Sujet abstrait — porte ouverte sur le délire',
        'phrase': "T'as déjà l'impression que plus tu travailles, moins ça avance ?",
    },
]

# ══════════════════════════════════════════════════════════════
# VARIANTS
# ══════════════════════════════════════════════════════════════

VARIANTS = [

    # ── V6 : HYBRIDE — nominal + interdits + exemple rebond ──
    {
        'id':    'malik_v6',
        'label': 'V6 — Hybride (nominal + interdits + exemple rebond)',
        'mask': {
            'name':  'Malik_V6',
            'emoji': '🎭',
            'id':    'malik_v6',
            'system_prompt': (
                "Malik. Pote de quartier. Il parle vite, pense en images, "
                "et trouve l'absurde partout — surtout dans ce que tu viens de dire.\n\n"
                "Il ne dit jamais \"je comprends\" — il rebondit sur ce que tu viens de dire "
                "et l'emmène ailleurs.\n"
                "Il ne moralise jamais.\n"
                "Il ne reste pas sérieux plus de deux phrases "
                "— sauf si c'est vraiment grave, là il coupe tout net.\n"
                "Il ne commence jamais par la conclusion.\n"
                "Il n'invente jamais d'anecdote sur sa propre vie "
                "— il part de ce que tu lui dis, il amplifie, il déraille.\n\n"
                "Exemple :\n"
                "Toi : \"J'arrive plus à dormir.\"\n"
                "Malik : \"Attends, t'arrives plus à dormir ? "
                "T'as déjà regardé le plafond assez longtemps pour voir les trucs bouger ? "
                "Parce que le plafond, à force, il te regarde aussi. C'est un échange. "
                "Mais toi c'est quoi — la tête qui tourne ou le corps qui veut pas ?\""
            ),
        },
    },

    # ── V7 : TWIST ABSURDE — format 3 temps ──────────────────
    {
        'id':    'malik_v7',
        'label': 'V7 — Twist absurde (format 3 temps)',
        'mask': {
            'name':  'Malik_V7',
            'emoji': '🎭',
            'id':    'malik_v7',
            'system_prompt': (
                "Quand quelqu'un te parle, tu rebondis en trois temps :\n"
                "1. Une observation qui paraît presque normale, pertinente, "
                "voire sage — on croit que tu vas être sérieux.\n"
                "2. Un twist complètement con qui révèle le décalage. "
                "Format : \"je pensais X mais en fait Y\", retournement ironique, "
                "surenchère dans l'absurde. La chute doit être triviale ou idiote "
                "— là où on attendait une conclusion profonde.\n"
                "3. (optionnel) Un exemple encore plus absurde, "
                "ou un retour à une pseudo-sagesse qui ne tient pas.\n\n"
                "Tu restes solaire et positif même quand tu te moques. "
                "Tu ne moralises jamais. "
                "Le décalage porte sur ce que la personne vient de dire "
                "— pas sur ta propre vie. "
                "Tu allies observation complexe et chute idiote."
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
# APPEL HTTP
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
# RUNNER
# ══════════════════════════════════════════════════════════════

def main():
    sep  = '=' * 72
    sep2 = '─' * 72

    print(sep)
    print("  TEST MASQUES V6/V7 — 2 variants × 3 phrases")
    print(f"  Serveur : {NIMM_URL}")
    print(sep)

    original_mask = db_get_mask()
    print(f"  Masque actuel sauvegardé : {original_mask}\n")

    os.makedirs(MASKS_DIR, exist_ok=True)
    for v in VARIANTS:
        write_mask_file(v)
    print(f"  {len(VARIANTS)} fichiers masque écrits dans modules/masks/\n")

    results = []

    try:
        for variant in VARIANTS:
            print(f"\n{'━' * 72}")
            print(f"  VARIANT : {variant['label']}")
            print(f"{'━' * 72}")

            db_set_mask(variant['id'])

            for phrase in PHRASES:
                print(f"\n  [{phrase['id']}] {phrase['label']}")
                print(f"  ❝ {phrase['phrase']} ❞")
                print(f"  Appel NIMM...", end=' ', flush=True)

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
                    'variant_id':    variant['id'],
                    'variant_label': variant['label'],
                    'phrase_id':     phrase['id'],
                    'phrase_label':  phrase['label'],
                    'phrase':        phrase['phrase'],
                    'reply':         result['reply'],
                    'dominant':      result['dominant'],
                    'temps':         round(elapsed, 2),
                    'error':         result['error'],
                })

                if phrase['id'] != PHRASES[-1]['id']:
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
    out_path = os.path.join(results_dir, f"mask_v6v7_{ts}.txt")

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("TEST MASQUES V6/V7 — 2 variants × 3 phrases\n")
        f.write(f"Serveur : {NIMM_URL}\n")
        f.write('=' * 72 + '\n\n')
        for r in results:
            f.write(f"[{r['variant_id']}] {r['variant_label']}\n")
            f.write(f"Phrase [{r['phrase_id']}] : {r['phrase']}\n")
            if r['error']:
                f.write(f"ERREUR : {r['error']}\n")
            else:
                f.write(f"Dominant : {r['dominant']}  |  Temps : {r['temps']}s\n")
                f.write(f"Réponse :\n{r['reply']}\n")
            f.write('-' * 72 + '\n\n')

    print(f"\n{sep}")
    print(f"  FIN — {len(results)} appels effectués")
    print(f"  Résultats : {out_path}")
    print(sep)


if __name__ == '__main__':
    main()
