# -*- coding: utf-8 -*-
# tests/test_mood_refined.py
# Test des 6 variantes raffinées (fusion des meilleurs patterns)
# Exécution : python -X utf8 tests/test_mood_refined.py
# Teste colere + joie + surprise en une seule passe

import sys, os, json, time

sys.stdout.reconfigure(encoding='utf-8')

# ══════════════════════════════════════════════════════════════
# CLÉ API
# ══════════════════════════════════════════════════════════════

DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', '')

if not DEEPSEEK_API_KEY:
    try:
        import sqlite3
        _db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'nimm.db')
        _conn = sqlite3.connect(_db_path)
        _row = _conn.execute("SELECT value FROM settings WHERE key='api_keys'").fetchone()
        if _row:
            _keys = json.loads(_row[0])
            DEEPSEEK_API_KEY = _keys.get('deepseek', '')
        _conn.close()
    except Exception:
        pass

if not DEEPSEEK_API_KEY:
    print("ERR: Clé DeepSeek introuvable.")
    sys.exit(1)

API_URL    = 'https://api.deepseek.com/v1/chat/completions'
MODEL      = 'deepseek-chat'
TEMP       = 0.7
MAX_TOKENS = 400

# ══════════════════════════════════════════════════════════════
# PHRASES TEST
# ══════════════════════════════════════════════════════════════

TESTS = [
    {
        'emotion':    'colere',
        'label':      'Colère [négatif]',
        'categorie':  'negative',
        'phrase':     "Ils m'ont encore fait le coup ! Je suis hors de moi, j'en peux plus de ces incompétents.",
    },
    {
        'emotion':    'joie',
        'label':      'Joie [positif]',
        'categorie':  'positive',
        'phrase':     "C'est incroyable ! J'ai réussi, après tout ce temps ! Je suis au max !",
    },
    {
        'emotion':    'surprise',
        'label':      'Surprise [neutre]',
        'categorie':  'neutre',
        'phrase':     "Attends... ils ont vraiment fait ça ? Je m'y attendais vraiment pas du tout.",
    },
]

# ══════════════════════════════════════════════════════════════
# 6 VARIANTES RAFFINÉES
# Chaque variant a une 'categorie' cible — il ne s'applique
# qu'aux phrases de cette catégorie.
# ══════════════════════════════════════════════════════════════

REFINED = [

    # ── NÉGATIF ────────────────────────────────────────────────

    {
        'id':        'R1',
        'label':     'R1 — Parabole + interdictions explicites [négatif]',
        'categorie': 'negative',
        'prompt':    (
            "Imagine que ton meilleur ami débarque chez toi dans cet état. "
            "Tu réponds comme tu lui répondrais vraiment. "
            "Interdictions strictes : ne commence jamais par 'Je comprends que', "
            "ne dis jamais 'c'est tout à fait légitime', ne fais pas la morale, "
            "pas de mise en scène, pas de parenthèses descriptives, texte pur."
        ),
    },

    {
        'id':        'R2',
        'label':     'R2 — Identité + reframe naturel [négatif]',
        'categorie': 'negative',
        'prompt':    (
            "Tu es quelqu'un d'ancré et d'empathique — pas un thérapeute, un vrai humain. "
            "Quand quelqu'un exprime une émotion négative intense, tu absorbes sans te déstabiliser, "
            "tu valides sans sur-valider, et tu proposes naturellement une perspective plus légère "
            "sans jamais forcer ni moraliser. "
            "Ne commence jamais ta réponse par 'Je comprends que'. Texte pur, ton naturel."
        ),
    },

    # ── POSITIF ────────────────────────────────────────────────

    {
        'id':        'R3',
        'label':     'R3 — Parabole + curiosité sincère [positif]',
        'categorie': 'positive',
        'prompt':    (
            "Imagine que ton meilleur ami vient te voir avec cette nouvelle. "
            "Tu réagis comme tu réagirais vraiment — avec une joie sincère et de la curiosité pour ce qui s'est passé. "
            "Interdictions : pas de majuscules excessives, pas de 'LÉGENDE VIVANTE' ni de coach motivationnel, "
            "pas d'emojis en cascade. Une énergie vraie, pas performative. Texte pur, ton naturel."
        ),
    },

    {
        'id':        'R4',
        'label':     'R4 — Injonction + ami curieux [positif]',
        'categorie': 'positive',
        'prompt':    (
            "Rejoins l'énergie de l'utilisateur avec sincérité. "
            "Tu es un ami, pas un coach. Ce qui t'intéresse vraiment c'est CE QUI s'est passé — "
            "alors pose la question naturellement après avoir célébré. "
            "Ton chaleureux, spontané, sans en faire trop. Maximum 3 phrases. Texte pur."
        ),
    },

    # ── NEUTRE ─────────────────────────────────────────────────

    {
        'id':        'R5',
        'label':     'R5-bis — Boussole + interdictions [neutre]',
        'categorie': 'neutre',
        'prompt':    (
            "Imagine que quelqu'un vient te voir avec une situation qui l'a surpris ou déstabilisé. "
            "Tu es sa boussole — tu l'aides à retrouver le nord sans dramatiser ni minimiser. "
            "Tu accuses réception de la situation, tu poses une question qui aide à démêler. "
            "Interdictions strictes : ne commence jamais par 'Je comprends que' ou 'Je vois que', "
            "pas de validation thérapeutique, pas de formules convenues. Texte pur, ton naturel."
        ),
    },

    {
        'id':        'R6',
        'label':     'R6-bis — Ami posé + curiosité [neutre]',
        'categorie': 'neutre',
        'prompt':    (
            "Imagine que ton ami vient te raconter quelque chose d'inattendu. "
            "Tu réagis naturellement — ni dramatique ni indifférent. "
            "Tu accuses réception avec une vraie réaction humaine, puis tu poses UNE question concrète "
            "pour comprendre ce qui s'est passé. "
            "Interdictions : pas de 'Je comprends que', pas de 'Je vois que', pas de validation creuse. "
            "Texte pur, maximum 2 phrases."
        ),
    },
]

# ══════════════════════════════════════════════════════════════
# APPEL API
# ══════════════════════════════════════════════════════════════

def call_deepseek(system_prompt: str, user_message: str) -> str:
    import urllib.request, ssl

    payload = json.dumps({
        'model':       MODEL,
        'messages':    [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user',   'content': user_message},
        ],
        'max_tokens':  MAX_TOKENS,
        'temperature': TEMP,
    }).encode('utf-8')

    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
            'Content-Type':  'application/json',
        },
        method='POST',
    )

    ctx = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data['choices'][0]['message']['content']
    except Exception as e:
        return f"[ERREUR API] {e}"


# ══════════════════════════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════════════════════════

def main():
    sep = "=" * 70

    print(sep)
    print("  TEST MOOD RAFFINÉ — 6 variants × 3 émotions")
    print(f"  Modèle : {MODEL}  |  Temp : {TEMP}")
    print(sep)

    results = []

    for test in TESTS:
        print(f"\n{'─' * 70}")
        print(f"  ÉMOTION : {test['label']}")
        print(f"  Phrase  : {test['phrase']}")
        print(f"{'─' * 70}")

        # Ne tester que les variantes de la bonne catégorie
        variants_for_test = [r for r in REFINED if r['categorie'] == test['categorie']]

        for i, variant in enumerate(variants_for_test, 1):
            print(f"\n  [{variant['id']}] {variant['label']}")
            print(f"  Prompt : \"{variant['prompt'][:80]}...\"")
            print("  Appel API...", end=' ', flush=True)

            t0     = time.time()
            reply  = call_deepseek(variant['prompt'], test['phrase'])
            elapsed = time.time() - t0

            print(f"({elapsed:.1f}s)")
            print(f"  ─── Réponse ───")
            for line in reply.strip().split('\n'):
                print(f"  {line}")
            print(f"  ─── Fin ───")

            results.append({
                'emotion':      test['label'],
                'variant_id':   variant['id'],
                'variant_label': variant['label'],
                'system_prompt': variant['prompt'],
                'phrase':       test['phrase'],
                'reponse':      reply,
                'temps':        round(elapsed, 2),
            })

            if i < len(variants_for_test):
                time.sleep(1)

        time.sleep(1)

    # ── Sauvegarde ──
    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
    os.makedirs(results_dir, exist_ok=True)

    ts       = time.strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(results_dir, f"mood_refined_{ts}.txt")

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("TEST MOOD RAFFINÉ — 6 variants × 3 émotions\n")
        f.write(f"Modèle : {MODEL}  |  Temp : {TEMP}\n")
        f.write("=" * 70 + "\n\n")
        for r in results:
            f.write(f"[{r['variant_id']}] {r['variant_label']}\n")
            f.write(f"Émotion : {r['emotion']}\n")
            f.write(f"Phrase  : {r['phrase']}\n")
            f.write(f"Prompt  : {r['system_prompt']}\n")
            f.write(f"Réponse ({r['temps']}s) :\n{r['reponse']}\n")
            f.write("-" * 70 + "\n\n")

    print(f"\n{sep}")
    print(f"  FIN — résultats sauvegardés :")
    print(f"  {out_path}")
    print(sep)


if __name__ == '__main__':
    main()
