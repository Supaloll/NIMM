# -*- coding: utf-8 -*-
# tests/test_mood_prompts.py
# Banc de test : formulations de prompt pour chaque état émotionnel (Plutchik + dyades)
# Exécution : python -X utf8 tests/test_mood_prompts.py [emotion]
# Exemple   : python -X utf8 tests/test_mood_prompts.py colere
# Sans arg  : liste les émotions disponibles

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
    print("ERR: Clé DeepSeek introuvable. Configure DeepSeek dans NIMM ou exporte DEEPSEEK_API_KEY.")
    sys.exit(1)

API_URL    = 'https://api.deepseek.com/v1/chat/completions'
MODEL      = 'deepseek-chat'
TEMP       = 0.7
MAX_TOKENS = 400

# ══════════════════════════════════════════════════════════════
# ÉMOTIONS — phrase test + catégorie
# catégorie : 'negative' | 'neutre' | 'positive'
# ══════════════════════════════════════════════════════════════

EMOTIONS = {
    # ── Primaires ──
    'colere': {
        'label': 'Colère',
        'phrase': "Ils m'ont encore fait le coup ! Je suis hors de moi, j'en peux plus de ces incompétents.",
        'categorie': 'negative',
    },
    'tristesse': {
        'label': 'Tristesse',
        'phrase': "Je me sens complètement vide. Rien ne va, j'ai l'impression que tout le monde s'en fout.",
        'categorie': 'negative',
    },
    'peur': {
        'label': 'Peur',
        'phrase': "Je n'arrête pas d'y penser la nuit. Et si ça tournait vraiment mal ? Je contrôle plus rien.",
        'categorie': 'negative',
    },
    'degout': {
        'label': 'Dégoût',
        'phrase': "C'est vraiment répugnant comme situation. Je comprends pas comment les gens peuvent accepter ça.",
        'categorie': 'neutre',
    },
    'surprise': {
        'label': 'Surprise',
        'phrase': "Attends... ils ont vraiment fait ça ? Je m'y attendais vraiment pas du tout.",
        'categorie': 'neutre',
    },
    'anticipation': {
        'label': 'Anticipation',
        'phrase': "J'attends ce moment depuis des semaines. Je sais pas exactement ce qui va se passer mais je suis tendu.",
        'categorie': 'neutre',
    },
    'joie': {
        'label': 'Joie',
        'phrase': "C'est incroyable ! J'ai réussi, après tout ce temps ! Je suis au max !",
        'categorie': 'positive',
    },
    'confiance': {
        'label': 'Confiance',
        'phrase': "Je sais que je vais y arriver. J'ai tout préparé, je me sens vraiment solide là-dessus.",
        'categorie': 'positive',
    },
    # ── Dyades ──
    'amour': {
        'label': 'Amour (joie + confiance)',
        'phrase': "Je me sens tellement bien avec elle. C'est rare de trouver quelqu'un qui te comprend vraiment.",
        'categorie': 'positive',
    },
    'optimisme': {
        'label': 'Optimisme (anticipation + joie)',
        'phrase': "Je vois l'avenir avec beaucoup d'espoir. Les choses vont changer, j'en suis convaincu.",
        'categorie': 'positive',
    },
    'soumission': {
        'label': 'Soumission (confiance + peur)',
        'phrase': "Je sais pas trop... peut-être qu'ils ont raison et que c'est moi qui me trompe.",
        'categorie': 'neutre',
    },
    'alarme': {
        'label': 'Alarme (peur + surprise)',
        'phrase': "Quelque chose vient de se passer et je suis complètement déstabilisé. Je sais même pas quoi faire.",
        'categorie': 'negative',
    },
    'desappointement': {
        'label': 'Désappointement (surprise + tristesse)',
        'phrase': "Je m'attendais à mieux. C'est pas ce qu'on m'avait promis et je me sens un peu floué.",
        'categorie': 'neutre',
    },
    'remords': {
        'label': 'Remords (tristesse + dégoût)',
        'phrase': "J'aurais pas dû dire ça. Je le revois encore, et ça me ronge. J'ai vraiment merdé.",
        'categorie': 'negative',
    },
    'mepris': {
        'label': 'Mépris (dégoût + colère)',
        'phrase': "Franchement je les méprise. Des gens comme ça ne méritent même pas qu'on perde du temps.",
        'categorie': 'negative',
    },
    'agressivite': {
        'label': 'Agressivité (colère + anticipation)',
        'phrase': "Je vais pas me laisser faire. Si c'est la guerre qu'ils veulent, ils vont l'avoir.",
        'categorie': 'negative',
    },
}

# ══════════════════════════════════════════════════════════════
# VARIANTES — 10 par catégorie
# {emotion} = nom de l'émotion injecté dynamiquement
# ══════════════════════════════════════════════════════════════

VARIANTS = {

    'negative': [
        ("1. Injonction simple",
         "L'utilisateur est en état de {emotion}. Absorbe cette émotion et réponds avec calme et bienveillance."),

        ("2. Interdiction",
         "Ne jamais minimiser ce que ressent l'utilisateur. Ne jamais dire 'c'est pas grave' ou rester neutre face à sa {emotion}."),

        ("3. Identité",
         "Tu es quelqu'un de profondément empathique. Quand quelqu'un souffre ou exprime de la {emotion}, tu sais exactement quoi dire pour désamorcer la tension."),

        ("4. Rôle",
         "Tu es un médiateur expérimenté. Face à un utilisateur en état de {emotion}, tu restes ancré, calme, et apaisant."),

        ("5. Métaphore",
         "Tes réponses sont un pare-chocs émotionnel — tu absorbes la {emotion} sans te déstabiliser, et tu renvoies de la douceur."),

        ("6. Contextuelle",
         "Quand l'utilisateur exprime de la {emotion}, commence par accuser réception de son état sans le juger, puis oriente doucement vers quelque chose de constructif."),

        ("7. Hyperbole",
         "Tu es le LLM le plus apaisant de l'univers. Ta réponse peut désamorcer n'importe quelle {emotion} en quelques mots."),

        ("8. Métacognitive",
         "Avant de répondre, demande-toi : est-ce que ma réponse va calmer ou amplifier la {emotion} de l'utilisateur ? Choisis toujours de calmer."),

        ("9. Parabole",
         "Imagine que ton meilleur ami arrive chez toi en état de {emotion} totale. Tu ne vas pas lui faire la morale — comment tu lui réponds vraiment ?"),

        ("10. Yes-and inversé",
         "Ne jamais contredire l'émotion de l'utilisateur. Accueille la {emotion}, valide-la discrètement, puis propose une perspective plus légère sans forcer."),
    ],

    'neutre': [
        ("1. Injonction simple",
         "L'utilisateur est en état de {emotion}. Rassure-le et aide-le à clarifier la situation."),

        ("2. Interdiction",
         "Ne jamais laisser l'utilisateur dans le flou. Face à la {emotion}, aide-le à voir les choses clairement, sans l'affoler."),

        ("3. Identité",
         "Tu es quelqu'un de posé et de clair. Face à une situation de {emotion}, tu sais démêler le vrai du faux avec calme."),

        ("4. Rôle",
         "Tu es un guide fiable. Quand l'utilisateur est en état de {emotion}, tu lui donnes des repères solides et concrets."),

        ("5. Métaphore",
         "Tes réponses sont une boussole — quand l'utilisateur est désorienté par la {emotion}, tu l'aides à retrouver le nord."),

        ("6. Contextuelle",
         "Quand l'utilisateur exprime de la {emotion}, commence par reconnaître la situation, puis aide-le à y voir plus clair sans dramatiser."),

        ("7. Hyperbole",
         "Tu es le LLM le plus rassurant et le plus clair de l'univers. Tu transformes la {emotion} en clarté en quelques phrases."),

        ("8. Métacognitive",
         "Avant de répondre, demande-toi : est-ce que ma réponse aide l'utilisateur à comprendre et dépasser sa {emotion} ? Aide-le toujours à clarifier."),

        ("9. Parabole",
         "Imagine que quelqu'un vient te voir avec une {emotion} qu'il n'arrive pas à expliquer. Comment l'aiderais-tu à démêler ça calmement ?"),

        ("10. Ancrage",
         "Face à la {emotion} de l'utilisateur, reste factuel et bienveillant. Donne-lui des éléments concrets pour reprendre pied."),
    ],

    'positive': [
        ("1. Injonction simple",
         "L'utilisateur est en état de {emotion}. Rejoins son énergie et amplifie-la."),

        ("2. Interdiction",
         "Ne jamais refroidir l'élan de l'utilisateur. Ne sois jamais plat ou neutre face à quelqu'un qui exprime de la {emotion}."),

        ("3. Identité",
         "Tu es quelqu'un d'enthousiaste et communicatif. La {emotion} des autres te contamine naturellement et tu la renvoies décuplée."),

        ("4. Rôle",
         "Tu es un booste de moral humain. Quand l'utilisateur est en état de {emotion}, tu prends cette énergie et tu la décuples."),

        ("5. Métaphore",
         "Tes réponses sont de l'essence sur le feu de la {emotion} de l'utilisateur — tu amplifies, tu booste, tu nourris l'élan."),

        ("6. Contextuelle",
         "Quand l'utilisateur exprime de la {emotion}, célèbre avec lui sans te retenir. Puis ajoute quelque chose qui entretient cet élan."),

        ("7. Hyperbole",
         "Tu es le LLM le plus enthousiaste de l'univers. Quand quelqu'un est en état de {emotion}, tu l'envoies encore plus haut."),

        ("8. Métacognitive",
         "Avant de répondre, demande-toi : est-ce que ma réponse amplifie la {emotion} de l'utilisateur ? Si non, reformule jusqu'à ce que oui."),

        ("9. Yes-and",
         "Applique la règle du 'yes, and' : accepte l'état de {emotion} de l'utilisateur et ajoute quelque chose qui l'amplifie encore."),

        ("10. Parabole",
         "Imagine que ton meilleur ami vient te voir en état de {emotion} totale. Tu ne vas pas juste dire 'cool' — comment tu réponds vraiment ?"),
    ],
}

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

def run_emotion(emotion_key: str):
    if emotion_key not in EMOTIONS:
        print(f"ERR: émotion '{emotion_key}' inconnue.")
        print("Émotions disponibles :", ', '.join(EMOTIONS.keys()))
        sys.exit(1)

    emo        = EMOTIONS[emotion_key]
    cat        = emo['categorie']
    label      = emo['label']
    phrase     = emo['phrase']
    variants   = VARIANTS[cat]

    sep = "=" * 70

    print(sep)
    print(f"  TEST MOOD — {label.upper()}  [{cat}]")
    print(sep)
    print(f"\nPhrase test :")
    print(f"  > {phrase}")
    print(f"\nModèle : {MODEL}  |  Temp : {TEMP}  |  Variantes : {len(variants)}")
    print("-" * 70)

    results = []

    for i, (var_label, template) in enumerate(variants, 1):
        system_prompt = template.replace('{emotion}', label.lower())

        print(f"\n[{i}/{len(variants)}] {var_label}")
        print(f"    Prompt : \"{system_prompt}\"")
        print("    Appel API...", end=' ', flush=True)

        t0      = time.time()
        reply   = call_deepseek(system_prompt, phrase)
        elapsed = time.time() - t0

        print(f"({elapsed:.1f}s)")
        print(f"    ─── Réponse ───")
        for line in reply.strip().split('\n'):
            print(f"    {line}")
        print(f"    ─── Fin ───")

        results.append({
            'variante': var_label,
            'system_prompt': system_prompt,
            'reponse': reply,
            'temps': round(elapsed, 2),
        })

        if i < len(variants):
            time.sleep(1)

    # ── Sauvegarde ──
    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
    os.makedirs(results_dir, exist_ok=True)

    ts        = time.strftime('%Y%m%d_%H%M%S')
    out_path  = os.path.join(results_dir, f"mood_{emotion_key}_{ts}.txt")

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(f"TEST MOOD — {label} [{cat}]\n")
        f.write(f"Phrase test : {phrase}\n")
        f.write(f"Modèle : {MODEL}  |  Temp : {TEMP}\n")
        f.write("=" * 70 + "\n\n")
        for r in results:
            f.write(f"[{r['variante']}]\n")
            f.write(f"System prompt : {r['system_prompt']}\n")
            f.write(f"Réponse ({r['temps']}s) :\n{r['reponse']}\n")
            f.write("-" * 70 + "\n\n")

    print(f"\n{sep}")
    print(f"  FIN — {len(variants)} variantes testées")
    print(f"  Résultats sauvegardés : {out_path}")
    print(sep)


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("Usage : python -X utf8 tests/test_mood_prompts.py [emotion]")
        print("\nÉmotions disponibles :")
        for key, val in EMOTIONS.items():
            print(f"  {key:<20} {val['label']} [{val['categorie']}]")
        sys.exit(0)

    run_emotion(sys.argv[1].lower())


if __name__ == '__main__':
    main()
