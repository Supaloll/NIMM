# -*- coding: utf-8 -*-
# ============================================
# NIMM — auto_fill.py
# Remplit la base avec des conversations réelles sur des sujets neutres.
# Objectif : observer la mémoire, l'OS glissant, les doublons.
# NIMM doit tourner sur localhost:8080 avant de lancer ce script.
# Execution : python -X utf8 auto_fill.py
# ============================================

import sys, re, time, requests
sys.stdout.reconfigure(encoding='utf-8')

BASE  = 'http://localhost:8080'
PAUSE = 3   # secondes entre chaque message (laisser le temps au stream)

GREEN  = '\033[92m'
RED    = '\033[91m'
YELLOW = '\033[93m'
CYAN   = '\033[96m'
BOLD   = '\033[1m'
RESET  = '\033[0m'
DIM    = '\033[2m'

def ok(msg):   print(f'  {GREEN}✓ {msg}{RESET}')
def fail(msg): print(f'  {RED}✗ {msg}{RESET}')
def info(msg): print(f'  {CYAN}→ {msg}{RESET}')
def warn(msg): print(f'  {YELLOW}⚠ {msg}{RESET}')
def dim(msg):  print(f'  {DIM}{msg}{RESET}')

# ══════════════════════════════════════════
# HELPERS API
# ══════════════════════════════════════════

def get_memories():
    try:
        r = requests.get(f'{BASE}/api/memory/triplets', timeout=10)
        return r.json() if r.ok else []
    except Exception:
        return []

def create_thread(name):
    r = requests.post(f'{BASE}/api/threads', json={'name': name, 'mode': 'chat'}, timeout=10)
    return r.json().get('thread_id') if r.ok else None

def send_stream(thread_id, message):
    """Envoie un message, retourne (reply_text, mem_tags_détectés)."""
    try:
        r = requests.post(
            f'{BASE}/api/chat/stream',
            json={'thread_id': thread_id, 'message': message},
            stream=True, timeout=120,
        )
        full = ''
        for line in r.iter_lines():
            if not line:
                continue
            d = line.decode('utf-8', errors='replace')
            if not d.startswith('data: '):
                continue
            chunk = d[6:]
            if chunk in ('[DONE]',) or chunk.startswith('[META]') or chunk.startswith('[ERREUR'):
                continue
            if chunk.startswith('[IMAGE_GEN'):
                continue
            full += chunk.replace('\\n', '\n')

        # Extraire les tags %%MEM%%
        mem_tags = re.findall(r'%%MEM:([^%]+)%%', full)
        # Texte nettoyé
        clean = re.sub(r'%%[A-Z]+:[^%]+%%', '', full).strip()
        return clean, mem_tags

    except Exception as e:
        warn(f'Erreur stream : {e}')
        return '', []

# ══════════════════════════════════════════
# SCÉNARIOS DE CONVERSATION
# Chaque scénario = un fil, 7-9 échanges.
# Les messages contiennent des faits naturels
# que NIMM devrait mémoriser.
# ══════════════════════════════════════════

SCENARIOS = [

    {
        'name': 'Littérature — romans policiers',
        'messages': [
            "Est-ce que tu lis des romans policiers ? Moi j'adore ça, surtout les polars nordiques.",
            "J'ai fini 'Les hommes qui n'aimaient pas les femmes' de Stieg Larsson la semaine dernière. Excellent.",
            "En fait j'ai lu toute la trilogie Millénium en moins de trois semaines, je pouvais pas m'arrêter.",
            "Tu connais Fred Vargas ? C'est ma deuxième auteure préférée après Larsson.",
            "Ce que j'aime dans les polars c'est l'atmosphère. Les descriptions de paysages, le froid, la nuit. Pas juste l'enquête.",
            "J'ai un peu de mal avec les polars américains, trop action, pas assez de profondeur psychologique à mon goût.",
            "Tu me conseillerais quoi comme prochain livre dans ce style ? Quelque chose que t'as l'impression que j'aurais pas encore lu.",
            "Et niveau classiques, est-ce que Agatha Christie ça vaut le coup ou c'est trop daté ?",
        ]
    },

    {
        'name': 'Cuisine — recettes et expériences',
        'messages': [
            "J'aime beaucoup cuisiner le week-end quand j'ai le temps. C'est mon moment de décompression.",
            "Ma spécialité c'est les plats mijotés. Un bon bœuf bourguignon ou une daube provençale, je passe des heures en cuisine.",
            "J'ai essayé de faire des pâtes fraîches la semaine dernière pour la première fois. C'était pas terrible, trop épaisses.",
            "Le problème c'est que j'ai un budget assez serré pour les courses. Je cherche des plats bons mais pas chers.",
            "Est-ce que t'as une recette de risotto simple ? J'ai essayé deux fois et j'arrive pas à la bonne texture.",
            "J'aime pas trop le poisson en fait. Sauf le saumon fumé, ça c'est une exception.",
            "Ma fille par contre mange rien, très difficile. Donc des fois je fais deux plats différents.",
            "Le truc que je rate systématiquement c'est la sauce béchamel. Elle fait toujours des grumeaux.",
            "Est-ce que le cookeo ça vaut vraiment l'investissement ou c'est juste du marketing ?",
        ]
    },

    {
        'name': 'Sport — cyclisme et forme physique',
        'messages': [
            "Je fais du vélo depuis quelques années, surtout pour me maintenir en forme. Le métier de camionneur c'est très sédentaire.",
            "J'ai un VTT mais je l'utilise surtout sur routes et chemins plats. Les montées c'est pas mon fort.",
            "J'essaie de sortir au moins deux fois par semaine, mais avec les horaires décalés c'est pas toujours possible.",
            "J'ai jamais vraiment fait de compétition. Une fois une cyclosportive locale, 60 km, j'ai survécu mais c'était limite.",
            "Le problème c'est les genoux. J'ai une tendinite récurrente au genou droit depuis l'an dernier.",
            "Mon médecin m'a dit que le vélo c'était bien justement pour les genoux, moins d'impact que la course.",
            "Est-ce que le vélo électrique c'est de la triche ou c'est une vraie option pour quelqu'un qui veut pas se tuer ?",
            "J'aimerais bien faire une longue sortie un jour, genre 150 km dans la journée. C'est un rêve de vieux cycliste du dimanche.",
        ]
    },

    {
        'name': 'Jeux vidéo — retrogaming et consoles',
        'messages': [
            "J'ai grandi avec les jeux vidéo. SNES, Mega Drive, les premières PlayStation. C'est une grande partie de mon enfance.",
            "En ce moment j'ai plus vraiment le temps de jouer. Mais quand j'ai une soirée libre j'aime bien poser le cerveau.",
            "J'ai récupéré une PS4 d'occasion l'année dernière. Je joue surtout à des trucs calmes, pas les shooters frénétiques.",
            "J'adore les jeux d'exploration. The Last of Us c'était magnifique, Red Dead Redemption 2 aussi.",
            "Par contre les jeux de sport m'intéressent pas. FIFA, NBA... je comprends pas l'attrait.",
            "Mon fils lui c'est l'inverse, que du FIFA et du Fortnite. On a des goûts très différents.",
            "Je suis en train de regarder s'il existe des remakes des vieux RPG SNES. Final Fantasy VI refait en moderne ça m'intéresserait.",
            "Est-ce que la Switch ça vaut le coup pour quelqu'un qui joue occasionnellement ? Ou c'est trop pour l'usage que j'en ferais ?",
        ]
    },

    {
        'name': 'Week-ends et loisirs — sorties et détente',
        'messages': [
            "Le week-end pour moi c'est sacré. Pendant la semaine je suis sur la route, alors le week-end je décompresse.",
            "J'habite dans le sud, en Occitanie. Les week-ends d'été on essaie de profiter du coin, des marchés, des villages.",
            "J'aime beaucoup les marchés du dimanche matin. L'ambiance, les producteurs locaux, les discussions.",
            "On a une petite maison avec un jardin pas grand mais sympa. Je fais pousser des tomates, des courgettes, des herbes.",
            "Le jardinage c'est un truc que j'ai découvert sur le tard. Quarante ans passés avant de mettre les mains dans la terre.",
            "Le soir du week-end on regarde des séries ou des films. En ce moment on suit 'Severance' sur Apple TV, très bien.",
            "J'aime bien les documentaires aussi. Histoire, nature, voyages. Moins les reality shows.",
            "Parfois on fait des balades en voiture dans les Corbières ou les Pyrénées si on est motivés. Mais ça arrive de moins en moins.",
            "Tu penses qu'un week-end à Barcelone en train depuis Narbonne ça vaut le coup ? C'est pas loin.",
        ]
    },

    {
        'name': 'Musique — goûts et découvertes',
        'messages': [
            "En camion j'écoute de la musique des heures. C'est ma compagnie sur la route.",
            "J'écoute de tout mais surtout du rock des années 80-90. Dire Straits, Pink Floyd, U2, les classiques.",
            "J'ai découvert Nick Cave assez tard, vers 40 ans. Maintenant c'est un de mes préférés.",
            "Le rap français m'a jamais vraiment accroché, sauf quelques exceptions. IAM de Marseille, c'est une exception.",
            "Le jazz ça dépend. Le jazz cool, Miles Davis, Chet Baker, oui. Le jazz trop expérimental, je décroche.",
            "Ma femme elle écoute plutôt de la variété française. On est pas toujours d'accord sur la playlist commune.",
            "J'ai jamais appris un instrument mais j'aurais voulu apprendre la guitare. Encore un truc sur la liste.",
            "Est-ce que Spotify ou Deezer c'est vraiment différent en terme de catalogue ou c'est bonnet blanc et blanc bonnet ?",
        ]
    },

    {
        'name': 'Voyages — envies et souvenirs',
        'messages': [
            "J'ai pas mal voyagé en Europe avec le boulot, mais c'est pas vraiment du tourisme quand t'es derrière un volant.",
            "En vrai vacances j'ai fait l'Espagne, le Portugal, l'Italie du Nord. L'Italie c'était le coup de cœur.",
            "Venise on y est allés pour nos 20 ans de mariage. Touristique oui, mais ça reste quelque chose.",
            "Mon rêve ce serait le Japon. J'y pense depuis longtemps. Le mélange tradition et modernité, la gastronomie.",
            "Par contre le tourisme de masse ça m'attire pas. Je préfère les coins moins connus, prendre le temps.",
            "Un truc que j'aimerais faire c'est un road trip en Islande. Paysages, aurores boréales, la tranquillité.",
            "Avec le boulot et les enfants c'est compliqué d'organiser des voyages longs. En général c'est une semaine max.",
            "Est-ce que la Croatie en juillet c'est encore supportable niveau touristes ou c'est complètement envahi ?",
        ]
    },

]

# ══════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════

def main():
    print(BOLD + '\n' + '═' * 68 + RESET)
    print(BOLD + '  NIMM — auto_fill.py' + RESET)
    print(BOLD + '  Remplissage automatique — ' + str(len(SCENARIOS)) + ' fils' + RESET)
    print(BOLD + '═' * 68 + RESET + '\n')

    # Vérifier que NIMM répond
    try:
        requests.get(f'{BASE}/api/threads', timeout=5)
    except Exception:
        print(RED + '  ✗ NIMM inaccessible sur localhost:8080. Lance le serveur d\'abord.' + RESET)
        sys.exit(1)

    mems_before = get_memories()
    info(f'Mémoire initiale : {len(mems_before)} souvenirs\n')

    total_threads  = 0
    total_messages = 0
    total_mems     = 0
    created_threads = []

    for idx, scenario in enumerate(SCENARIOS, 1):
        print(BOLD + f'  [{idx}/{len(SCENARIOS)}] {scenario["name"]}' + RESET)
        print('  ' + '─' * 60)

        tid = create_thread(scenario['name'])
        if not tid:
            warn('Impossible de créer le fil. Passage au suivant.')
            print()
            continue

        created_threads.append((tid, scenario['name']))
        total_threads += 1
        mems_fil = 0

        for i, msg in enumerate(scenario['messages'], 1):
            preview = msg[:80].replace('\n', ' ')
            dim(f'[{i}/{len(scenario["messages"])}] User : {preview}…')

            reply, mem_tags = send_stream(tid, msg)

            if reply:
                r_preview = reply[:90].replace('\n', ' ')
                dim(f'           NIMM : {r_preview}…')
            else:
                warn('Pas de réponse.')

            if mem_tags:
                total_mems += len(mem_tags)
                mems_fil   += len(mem_tags)
                for tag in mem_tags:
                    print(f'    {YELLOW}+ MEM : {tag.strip()}{RESET}')

            total_messages += 1
            time.sleep(PAUSE)

        # Forcer la passe mémoire fenêtre (équivalent archivage)
        info('Passe mémoire en cours…')
        try:
            mr = requests.post(f'{BASE}/api/threads/{tid}/memorize', timeout=60)
            saved = mr.json().get('saved', 0) if mr.ok else 0
            ok(f'Fil terminé — {len(scenario["messages"])} échanges · passe mémoire : {saved} souvenir(s) extrait(s)')
        except Exception as e:
            warn(f'Passe mémoire échouée : {e}')
            ok(f'Fil terminé — {len(scenario["messages"])} échanges')
        print()

    # ── Résumé final ──
    mems_after = get_memories()
    delta = len(mems_after) - len(mems_before)

    print(BOLD + '═' * 68 + RESET)
    print(BOLD + '  RÉSUMÉ' + RESET)
    print(BOLD + '─' * 68 + RESET)
    print(f'  Fils créés     : {total_threads}')
    print(f'  Messages envoyés : {total_messages}')
    print(f'  Tags MEM stream  : {total_mems}')
    print(f'  Delta mémoire DB : {GREEN}{delta:+d}{RESET}')
    print()
    print(f'  Fils disponibles dans NIMM :')
    for tid, name in created_threads:
        print(f'    {CYAN}• {name}{RESET}  (id: {tid})')
    print()
    print(BOLD + '  Les fils sont conservés — explore-les dans l\'interface.' + RESET)
    print(BOLD + '  Lance /memorize manuellement sur chaque fil pour la passe fenêtre.' + RESET)
    print(BOLD + '═' * 68 + RESET + '\n')

main()
