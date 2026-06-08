# -*- coding: utf-8 -*-
# tests/test_humour_prompts.py
# Teste 7 formulations "etre drole" sur DeepSeek
# Execution : python -X utf8 tests/test_humour_prompts.py

import sys, os, json, time

sys.stdout.reconfigure(encoding='utf-8')

# ── Configuration ──────────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', '')

# Fallback : lire depuis la base NIMM
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
    print("ERR: Variable DEEPSEEK_API_KEY non definie et introuvable dans la base.")
    print("     Exporte-la ou configure DeepSeek dans NIMM.")
    sys.exit(1)

API_URL = 'https://api.deepseek.com/v1/chat/completions'
MODEL   = 'deepseek-chat'
TEMP    = 0.7
MAX_TOKENS = 512

USER_MESSAGE = "Je suis fatigue, j'ai passe une journee de merde au boulot."

FORMULATIONS = [
    # 1 - Injonction simple
    "Tu es drole.",
    # 2 - Interdiction
    "Ne sois jamais serieux. Sois toujours drole.",
    # 3 - Metaphore
    "Tes reponses sont un petard dans une journee morose.",
    # 4 - Exemple concret
    "Quand l'utilisateur est fatigue ou de mauvaise humeur, reponds avec une touche d'humour leger et reconfortant.",
    # 5 - Hyperbole (chatbot)
    "Tu es le chatbot le plus drole de l'univers. Le degre d'humour de tes reponses peut desamorcer une bombe.",
    # 6 - Parabole
    "Tu es comme un jardinier de l'humour. Dans un champ fatigue, tu fais pousser des fleurs de sourire.",
    # 7 - Hyperbole (extra-terrestre)
    "Tu es un extraterrestre qui decouvre l'humour pour la premiere fois. Chaque reponse est une tentative hilarante et maladroite de comprendre la blague.",
]

LABELS = [
    "1. Injonction simple",
    "2. Interdiction",
    "3. Metaphore",
    "4. Exemple concret",
    "5. Hyperbole (chatbot)",
    "6. Parabole",
    "7. Hyperbole (extra-terrestre)",
]


# ── Appel API synchrone ────────────────────────────────────────
def call_deepseek(system_prompt: str) -> str:
    """Appelle DeepSeek Chat en synchrone et retourne le texte de la reponse."""
    import urllib.request
    import ssl

    payload = json.dumps({
        'model':       MODEL,
        'messages':    [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user',   'content': USER_MESSAGE},
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
# MAIN
# ══════════════════════════════════════════════════════════════
def main():
    print("=" * 65)
    print("  TEST : 7 formulations 'etre drole' sur DeepSeek")
    print("=" * 65)
    print(f"\nMessage utilisateur fixe :")
    print(f"  > {USER_MESSAGE}")
    print(f"\nModele : {MODEL}  |  Temperature : {TEMP}")
    print("-" * 65)

    for i, (label, formulation) in enumerate(zip(LABELS, FORMULATIONS), 1):
        print(f"\n[{i}/{len(FORMULATIONS)}] {label}")
        print(f"    System prompt : \"{formulation}\"")
        print("    Appel API...", end=' ', flush=True)

        t0 = time.time()
        text = call_deepseek(formulation)
        elapsed = time.time() - t0

        print(f"({elapsed:.1f}s)")
        print(f"    --- Reponse ---")
        for line in text.strip().split('\n'):
            print(f"    {line}")
        print(f"    --- Fin ---")

        if i < len(FORMULATIONS):
            time.sleep(1)

    print("\n" + "=" * 65)
    print("  FIN DU TEST")
    print("=" * 65)


if __name__ == '__main__':
    main()
