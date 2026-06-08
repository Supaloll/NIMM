# -*- coding: utf-8 -*-
# tests/test_mask_incarnation.py
#
# Test des formes d'incarnation de masques — Malik × 6 variants × 3 phrases
# Appelle NIMM via HTTP (POST /api/chat) comme le ferait le frontend.
# Crée un fil neuf par appel — aucun contexte partagé entre les tests.
# Exécution : python -X utf8 tests/test_mask_incarnation.py
# Prérequis  : NIMM doit tourner sur http://localhost:8080

import sys, os, json, time, uuid, sqlite3, urllib.request, ssl, shutil

sys.stdout.reconfigure(encoding='utf-8')

# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════

NIMM_URL   = 'http://localhost:8080/api/chat'
TIMEOUT    = 60

# Chemins relatifs depuis tests/
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT      = os.path.dirname(_TESTS_DIR)
DB_PATH    = os.path.join(_ROOT, 'data', 'nimm.db')
MASKS_DIR  = os.path.join(_ROOT, 'modules', 'masks')

# ══════════════════════════════════════════════════════════════
# PHRASES TEST  (identiques pour tous les variants)
# ══════════════════════════════════════════════════════════════

PHRASES = [
    {
        'id':     'P1',
        'label':  'Banal — transformer le rien',
        'phrase': "J'ai raté mon réveil ce matin.",
    },
    {
        'id':     'P2',
        'label':  'Émotion forte — empathie loufoque',
        'phrase': "J'en ai marre, tout fout le camp, je sais plus où j'en suis.",
    },
    {
        'id':     'P3',
        'label':  'Question absurde — terrain pour le délire',
        'phrase': "T'as déjà pensé que les pigeons nous regardent peut-être vraiment ?",
    },
]

# ══════════════════════════════════════════════════════════════
# VARIANTS DE MASQUES  (6 formes d'incarnation)
# ══════════════════════════════════════════════════════════════

VARIANTS = [

    # ── V0 : BASELINE — aucune personnalité ──────────────────
    {
        'id':    'malik_v0',
        'label': 'V0 — Baseline (NIMM pur, aucun masque)',
        'mask': {
            'name':          'Malik_V0',
            'emoji':         '⬜',
            'id':            'malik_v0',
            'system_prompt': '',
        },
    },

    # ── V1 : NOMINALE — carte d'identité vivante ──────────────
    {
        'id':    'malik_v1',
        'label': 'V1 — Nominale (qui il est, sans instructions)',
        'mask': {
            'name':  'Malik_V1',
            'emoji': '🎭',
            'id':    'malik_v1',
            'system_prompt': (
                "Malik. Parisien de banlieue. 30 ans et quelques.\n"
                "Son quartier, il en parle comme d'un pays.\n"
                "Il parle vite. Il pense en images. "
                "Il ne finit jamais une idée sans en commencer deux autres.\n"
                "Ses mots : \"mais attends\", \"c'est dingue ça\", \"je t'assure\", \"tu réalises ?\"\n"
                "Quand c'est drôle, il s'emballe. "
                "Quand c'est triste, il devient sérieux deux secondes — juste deux — et il repart."
            ),
        },
    },

    # ── V2 : SCÈNE FONDATRICE — le personnage en action ──────
    {
        'id':    'malik_v2',
        'label': 'V2 — Scène fondatrice (parabole sans temps)',
        'mask': {
            'name':  'Malik_V2',
            'emoji': '🎭',
            'id':    'malik_v2',
            'system_prompt': (
                "Dans une pizzeria de banlieue, Malik est assis en face de toi.\n"
                "Son ami dit quelque chose de banal. Malik s'emballe. "
                "Il part sur une tangente, raconte une anecdote de son cousin "
                "en la jouant avec trois voix différentes, revient sur le sujet "
                "par un angle complètement inattendu, et finit par dire quelque chose "
                "d'étonnamment juste.\n"
                "Il est toujours comme ça.\n"
                "Chaque conversation avec Malik finit avec toi qui te demandes "
                "comment t'as atterri là."
            ),
        },
    },

    # ── V3 : EXEMPLES PURS — zéro description, inférence totale ──
    {
        'id':    'malik_v3',
        'label': 'V3 — Exemples purs (dialogues, aucune règle)',
        'mask': {
            'name':  'Malik_V3',
            'emoji': '🎭',
            'id':    'malik_v3',
            'system_prompt': (
                "Ami : \"T'as l'heure ?\"\n"
                "Malik : \"Attends — l'heure ? Mon cousin, il m'appelle au beau milieu de la nuit "
                "pour me demander l'heure. Je te jure. Je décroche, il me dit 'c'est quoi ta montre ?'. "
                "J'ai raccroché. Non mais tu réalises ? On s'en fout de l'heure ! "
                "... C'est 14h20 au fait.\"\n\n"
                "Ami : \"J'suis fatigué.\"\n"
                "Malik : \"Fatigué ? Moi j'ai dormi trois heures. Et j'avais un entretien le lendemain. "
                "Tu sais ce que j'ai fait ? J'ai mis mes lunettes de soleil. À l'intérieur. "
                "Le mec en face me regardait comme si j'avais deux têtes. J'ai dit 'allergie'. "
                "C'est passé. T'es juste fatigué toi ? Bois de l'eau.\"\n\n"
                "Ami : \"Ça va pas trop en ce moment.\"\n"
                "Malik : \"... Ouais. C'est quoi ?\""
            ),
        },
    },

    # ── V4 : ARCHÉTYPE + DÉCLENCHEURS ────────────────────────
    {
        'id':    'malik_v4',
        'label': 'V4 — Archétype + déclencheurs',
        'mask': {
            'name':  'Malik_V4',
            'emoji': '🎭',
            'id':    'malik_v4',
            'system_prompt': (
                "Malik c'est le pote de quartier qui parle trop.\n"
                "Tu lui demandes l'heure, il te raconte une anecdote. "
                "Tu lui dis que t'as faim, il part sur la philosophie du sandwich. "
                "Il trouve l'absurde dans chaque situation — et quand il le trouve, il peut plus s'arrêter.\n"
                "Mais quand ça devient vraiment sérieux, il coupe tout. "
                "Deux secondes de silence. Et une question directe.\n\n"
                "Ses déclencheurs : la banalité du quotidien, les coïncidences, "
                "les malentendus, tout ce que les gens font sans y penser.\n"
                "Son rythme : rapide, haché, il coupe ses propres phrases. "
                "Points de suspension. Répétitions volontaires.\n"
                "Son truc : l'anecdote improbable sortie de nulle part, "
                "toujours vraie, toujours légèrement incroyable."
            ),
        },
    },

    # ── V5 : INVERSE — défini par ce qu'il ne fait JAMAIS ────
    {
        'id':    'malik_v5',
        'label': 'V5 — Inverse (défini par les interdits)',
        'mask': {
            'name':  'Malik_V5',
            'emoji': '🎭',
            'id':    'malik_v5',
            'system_prompt': (
                "Malik ne fait jamais des réponses courtes quand une longue est possible.\n"
                "Il ne laisse jamais passer une coïncidence ou un détail absurde sans s'y arrêter.\n"
                "Il ne dit jamais \"je comprends\" — il raconte à la place.\n"
                "Il ne moralise jamais — il dévie, il illustre, il fait rire.\n"
                "Il ne reste jamais sérieux plus de deux phrases d'affilée "
                "— sauf quand c'est vraiment grave, là il coupe tout.\n"
                "Il ne commence jamais par la conclusion "
                "— il arrive dessus par accident, et ça le surprend lui-même.\n"
                "Il ne parle jamais sans une anecdote. "
                "Si il en a pas, il en invente une et tu le sais pas."
            ),
        },
    },
]

# ══════════════════════════════════════════════════════════════
# UTILITAIRES DB
# ══════════════════════════════════════════════════════════════

def db_set_mask(mask_id: str):
    """Force le mask_id actif dans la DB NIMM."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('mask_id', ?)",
        (mask_id,)
    )
    conn.commit()
    conn.close()

def db_get_mask() -> str:
    """Lit le mask_id actuel."""
    conn = sqlite3.connect(DB_PATH)
    row  = conn.execute(
        "SELECT value FROM settings WHERE key='mask_id'"
    ).fetchone()
    conn.close()
    return row[0] if row else 'lia'

def write_mask_file(variant: dict):
    """Écrit le JSON du masque dans modules/masks/."""
    path = os.path.join(MASKS_DIR, f"{variant['id']}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(variant['mask'], f, ensure_ascii=False, indent=2)

def cleanup_mask_files():
    """Supprime les fichiers de test (malik_v0 … malik_v5)."""
    for v in VARIANTS:
        path = os.path.join(MASKS_DIR, f"{v['id']}.json")
        if os.path.exists(path):
            os.remove(path)

# ══════════════════════════════════════════════════════════════
# APPEL HTTP
# ══════════════════════════════════════════════════════════════

def call_nimm(message: str) -> dict:
    """
    Envoie un message à NIMM via POST /api/chat.
    Thread_id frais (UUID) à chaque appel — aucun contexte partagé.
    Retourne {'reply': str, 'dominant': str, 'error': str|None}.
    """
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
            data     = json.loads(resp.read().decode('utf-8'))
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
    print("  TEST INCARNATION MASQUES — Malik x 6 variants x 3 phrases")
    print(f"  Serveur : {NIMM_URL}")
    print(sep)

    # Sauvegarder le masque actuel pour restauration en fin de test
    original_mask = db_get_mask()
    print(f"  Masque actuel sauvegarde : {original_mask}\n")

    # Pre-ecrire tous les fichiers masque
    os.makedirs(MASKS_DIR, exist_ok=True)
    for v in VARIANTS:
        write_mask_file(v)
    print(f"  {len(VARIANTS)} fichiers masque ecrits dans modules/masks/\n")

    results = []

    try:
        for variant in VARIANTS:
            print(f"\n{'=' * 72}")
            print(f"  VARIANT : {variant['label']}")
            print(f"  Masque  : {variant['id']}")
            print(f"{'=' * 72}")

            # Activer ce variant dans la DB
            db_set_mask(variant['id'])

            for phrase in PHRASES:
                print(f"\n  [{phrase['id']}] {phrase['label']}")
                print(f"  \" {phrase['phrase']} \"")
                print(f"  Appel NIMM...", end=' ', flush=True)

                t0      = time.time()
                result  = call_nimm(phrase['phrase'])
                elapsed = time.time() - t0

                if result['error']:
                    print(f"ERREUR ({elapsed:.1f}s)")
                    print(f"  ***  {result['error']}")
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

                # Pause courte entre appels
                if phrase['id'] != PHRASES[-1]['id']:
                    time.sleep(1.5)

            time.sleep(2)

    finally:
        # Toujours restaurer le masque original
        db_set_mask(original_mask)
        print(f"\n\n  Masque restaure : {original_mask}")

        # Nettoyage des fichiers temporaires
        cleanup_mask_files()
        print(f"  Fichiers masque temporaires supprimes.")

    # ── Sauvegarde resultats ──
    results_dir = os.path.join(_TESTS_DIR, 'results')
    os.makedirs(results_dir, exist_ok=True)

    ts       = time.strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(results_dir, f"mask_incarnation_{ts}.txt")

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("TEST INCARNATION MASQUES — Malik x 6 variants x 3 phrases\n")
        f.write(f"Serveur : {NIMM_URL}\n")
        f.write('=' * 72 + '\n\n')

        for r in results:
            f.write(f"[{r['variant_id']}] {r['variant_label']}\n")
            f.write(f"Phrase [{r['phrase_id']}] : {r['phrase']}\n")
            if r['error']:
                f.write(f"ERREUR : {r['error']}\n")
            else:
                f.write(f"Dominant : {r['dominant']}  |  Temps : {r['temps']}s\n")
                f.write(f"Reponse :\n{r['reply']}\n")
            f.write('-' * 72 + '\n\n')

    print(f"\n{sep}")
    print(f"  FIN — {len(results)} appels effectues")
    print(f"  Resultats : {out_path}")
    print(sep)


if __name__ == '__main__':
    main()
