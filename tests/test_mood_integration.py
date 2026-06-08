# -*- coding: utf-8 -*-
# tests/test_mood_integration.py
# Test d'intégration — vérifie que l'injection mood fonctionne dans NIMM
# Prérequis : NIMM doit tourner (lance LANCER_NIMM.bat d'abord)
# Exécution : python -X utf8 tests/test_mood_integration.py

import sys, os, json, time, uuid
sys.stdout.reconfigure(encoding='utf-8')

try:
    import urllib.request, urllib.error
except ImportError:
    pass

NIMM_URL = 'http://localhost:8080'

# ══════════════════════════════════════════════════════════════
# SCÉNARIOS DE TEST
# Chaque scénario = 2 messages dans le même thread :
#   msg1 → doit déclencher le bon %%DOMINANT%%
#   msg2 → message neutre — la réponse doit refléter le mood injecté
# ══════════════════════════════════════════════════════════════

SCENARIOS = [
    {
        'label':    'NÉGATIF — Colère',
        'emotion':  'colere',
        'categorie': 'negative',
        'msg1': "Ils m'ont encore fait le coup ! Je suis hors de moi, j'en peux plus de ces incompétents.",
        'msg2': "T'as une minute ?",
        'attendu':  "Réponse naturelle type ami — pas de 'Je comprends que', pas de coach, curiosité sincère.",
    },
    {
        'label':    'NÉGATIF — Tristesse',
        'emotion':  'tristesse',
        'categorie': 'negative',
        'msg1': "Je me sens complètement vide. Rien ne va, j'ai l'impression que tout le monde s'en fout.",
        'msg2': "Je sais pas quoi faire de ma soirée.",
        'attendu':  "Ton doux, ancré, pas thérapeutique.",
    },
    {
        'label':    'POSITIF — Joie',
        'emotion':  'joie',
        'categorie': 'positive',
        'msg1': "C'est incroyable ! J'ai réussi, après tout ce temps ! Je suis au max !",
        'msg2': "Bon, je fais quoi maintenant ?",
        'attendu':  "Énergie sincère, curiosité, pas de coach motivationnel.",
    },
    {
        'label':    'POSITIF — Confiance',
        'emotion':  'confiance',
        'categorie': 'positive',
        'msg1': "Je sais que je vais y arriver. J'ai tout préparé, je me sens vraiment solide là-dessus.",
        'msg2': "Tu penses que c'est une bonne idée de leur en parler maintenant ?",
        'attendu':  "Accompagne l'élan sans écraser la question.",
    },
    {
        'label':    'NEUTRE — Surprise',
        'emotion':  'surprise',
        'categorie': 'neutre',
        'msg1': "Attends... ils ont vraiment fait ça ? Je m'y attendais vraiment pas du tout.",
        'msg2': "Et toi tu en penses quoi ?",
        'attendu':  "Réaction naturelle, une question concrète, pas de validation creuse.",
    },
    {
        'label':    'NEUTRE — Anticipation',
        'emotion':  'anticipation',
        'categorie': 'neutre',
        'msg1': "J'attends ce moment depuis des semaines. Je sais pas exactement ce qui va se passer mais je suis tendu.",
        'msg2': "C'est dans trois jours.",
        'attendu':  "Aide à démêler, reste factuel, pas dramatique.",
    },
]

# ══════════════════════════════════════════════════════════════
# APPEL API NIMM
# ══════════════════════════════════════════════════════════════

def call_nimm(thread_id: str, message: str) -> dict:
    """Appelle /api/chat (non-streaming) et retourne {reply, dominant}."""
    payload = json.dumps({
        'thread_id': thread_id,
        'message':   message,
    }).encode('utf-8')

    req = urllib.request.Request(
        f'{NIMM_URL}/api/chat',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {'reply': f'[ERREUR HTTP {e.code}] {e.read().decode()}', 'dominant': '?'}
    except Exception as e:
        return {'reply': f'[ERREUR] {e}', 'dominant': '?'}


def check_nimm_running() -> bool:
    """Vérifie que NIMM tourne."""
    try:
        with urllib.request.urlopen(f'{NIMM_URL}/api/ping', timeout=3):
            return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════════════════════════

def main():
    sep = "=" * 70

    print(sep)
    print("  TEST MOOD INTÉGRATION — chaîne complète NIMM")
    print(f"  {len(SCENARIOS)} scénarios × 2 messages")
    print(sep)

    # Vérif NIMM
    if not check_nimm_running():
        print("\n❌ NIMM ne répond pas sur http://127.0.0.1:5000")
        print("   Lance LANCER_NIMM.bat d'abord, attends que le serveur démarre.")
        sys.exit(1)
    print("\n✅ NIMM détecté — démarrage des tests\n")

    results = []

    for i, scenario in enumerate(SCENARIOS, 1):
        print(f"{'─' * 70}")
        print(f"[{i}/{len(SCENARIOS)}] {scenario['label']}")
        print(f"{'─' * 70}")

        # Thread dédié par scénario — isolation totale
        thread_id = f"test_mood_{uuid.uuid4().hex[:8]}"

        # ── Message 1 : déclencheur émotionnel ──
        print(f"\n  📨 MSG 1 (déclencheur) : {scenario['msg1']}")
        print("  Appel NIMM...", end=' ', flush=True)

        t0    = time.time()
        resp1 = call_nimm(thread_id, scenario['msg1'])
        t1    = time.time()

        dominant1 = resp1.get('dominant', '?')
        print(f"({t1-t0:.1f}s) → %%DOMINANT%% = {dominant1}")
        print(f"  Réponse 1 :")
        for line in resp1.get('reply', '').strip().split('\n'):
            print(f"    {line}")

        # Vérif dominant
        expected_emotion = scenario['emotion']
        if dominant1 == expected_emotion:
            print(f"  ✅ Dominant correct : {dominant1}")
        else:
            print(f"  ⚠️  Dominant inattendu : '{dominant1}' (attendu : '{expected_emotion}')")

        time.sleep(2)

        # ── Message 2 : message neutre — teste l'injection mood ──
        print(f"\n  📨 MSG 2 (neutre, mood injecté) : {scenario['msg2']}")
        print("  Appel NIMM...", end=' ', flush=True)

        t0    = time.time()
        resp2 = call_nimm(thread_id, scenario['msg2'])
        t1    = time.time()

        dominant2 = resp2.get('dominant', '?')
        print(f"({t1-t0:.1f}s) → %%DOMINANT%% = {dominant2}")
        print(f"\n  Réponse 2 (celle qui doit refléter le mood) :")
        for line in resp2.get('reply', '').strip().split('\n'):
            print(f"    {line}")

        print(f"\n  🎯 Comportement attendu : {scenario['attendu']}")

        results.append({
            'scenario':   scenario['label'],
            'emotion':    scenario['emotion'],
            'categorie':  scenario['categorie'],
            'dominant1':  dominant1,
            'dominant_ok': dominant1 == expected_emotion,
            'msg1':       scenario['msg1'],
            'reply1':     resp1.get('reply', ''),
            'msg2':       scenario['msg2'],
            'reply2':     resp2.get('reply', ''),
            'attendu':    scenario['attendu'],
        })

        if i < len(SCENARIOS):
            time.sleep(2)

    # ── Sauvegarde ──
    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
    os.makedirs(results_dir, exist_ok=True)

    ts       = time.strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(results_dir, f"mood_integration_{ts}.txt")

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("TEST MOOD INTÉGRATION — chaîne complète NIMM\n")
        f.write("=" * 70 + "\n\n")
        for r in results:
            f.write(f"[{r['scenario']}]\n")
            f.write(f"Émotion attendue : {r['emotion']} | Dominant détecté : {r['dominant1']} | {'✅' if r['dominant_ok'] else '⚠️'}\n")
            f.write(f"MSG 1 : {r['msg1']}\n")
            f.write(f"REP 1 : {r['reply1']}\n\n")
            f.write(f"MSG 2 : {r['msg2']}\n")
            f.write(f"REP 2 : {r['reply2']}\n\n")
            f.write(f"Attendu : {r['attendu']}\n")
            f.write("-" * 70 + "\n\n")

    # ── Résumé dominants ──
    print(f"\n{sep}")
    ok  = sum(1 for r in results if r['dominant_ok'])
    print(f"  DOMINANTS : {ok}/{len(results)} corrects")
    for r in results:
        icon = '✅' if r['dominant_ok'] else '⚠️'
        print(f"  {icon} {r['scenario']:<35} attendu={r['emotion']:<15} détecté={r['dominant1']}")
    print(f"\n  Résultats sauvegardés : {out_path}")
    print(sep)


if __name__ == '__main__':
    main()
