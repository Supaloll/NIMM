# -*- coding: utf-8 -*-
"""Conversation Live : parler à NIMM, et pouvoir le couper.

CE QUI DISTINGUE CE MODULE DE `tts.py` + `stt.py`
La chaîne classique est séquentielle : on enregistre, on transcrit, on
interroge le modèle, on synthétise, on joue. Chaque maillon attend le
précédent, et le total tourne autour de cinq secondes par tour. C'est
utilisable, mais ce n'est pas une conversation : on ne coupe pas la parole à
quelqu'un qui met cinq secondes à commencer sa phrase.

Le mode Live retire les maillons. L'audio part vers le modèle pendant qu'on
parle, la réponse revient pendant qu'elle se génère, et si l'on se remet à
parler, le modèle se tait. C'est ce dernier point — l'interruption — qui fait
la différence entre « dicter à une machine » et « parler à quelqu'un ».

DEUX MOTEURS, ET POURQUOI
  - `gemini`  : audio bidirectionnel natif (Live API), latence de l'ordre de
                la seconde, interruption gérée par le serveur de Google.
                C'est le seul qui tienne la promesse d'un vrai dialogue.
  - `chaine`  : Whisper local + le LLM du fil + la voix TTS de NIMM.
                Plus lent, mais il marche avec TOUS les fournisseurs, et sans
                clé Gemini. C'est le repli, pas une seconde option de luxe :
                sans lui, un utilisateur sans clé Gemini n'aurait rien.

CE QUI N'EST PAS NÉGOCIABLE ICI
  - **La clé ne sort pas du serveur.** L'interface parle à NIMM, NIMM parle à
    Google. Le raccourci « le navigateur se connecte directement à Google »
    est plus rapide à écrire et expose la clé dans la page : il est écarté.
  - **Tout est transcrit, des deux côtés.** Une conversation vocale qu'on ne
    peut pas relire est inutilisable sur un afficheur braille. Les deux
    transcriptions sont demandées à Google et remontées telles quelles.
  - **Rien n'est écrit sur le disque.** Une session Live est éphémère par
    construction : aucun message, aucune mémoire, aucune note de carnet. Ce
    module n'importe volontairement AUCUNE fonction d'écriture.

PRUDENCE
Aucune fonction ne lève : les erreurs reviennent en français dans le résultat.
"""

import json as _json

_BASE_WS = ('wss://generativelanguage.googleapis.com/ws/'
            'google.ai.generativelanguage.v1beta.GenerativeService.'
            'BidiGenerateContent')

# Format imposé par Google, et non négociable de notre côté :
# entrée PCM 16 bits 16 kHz, sortie PCM 16 bits 24 kHz, petit-boutiste.
TAUX_ENTREE = 16000
TAUX_SORTIE = 24000
MIME_ENTREE = 'audio/pcm;rate=16000'

# Identifiant relevé dans le tutoriel officiel « Get started using raw
# WebSockets » (ai.google.dev, mis à jour le 23/07/2026). À ne PAS déduire de
# la prose : on s'est déjà fait prendre avec un « Veo 3.1 Fast » qui n'existait
# que dans un tableau de paramètres, sans identifiant publié.
MODELE_DEFAUT = 'gemini-3.1-flash-live-preview'

# Voix pré-enregistrées de la Live API. La liste complète en compte une
# trentaine ; on n'expose que celles dont le nom est documenté de longue date,
# pour ne pas proposer un choix qui échouerait à la connexion. Le réglage
# `live_voix` permet d'en imposer une autre si Google en publie de nouvelles.
VOIX = [
    {'nom': 'Aoede',  'libelle': 'Aoede — posée'},
    {'nom': 'Kore',   'libelle': 'Kore — assurée'},
    {'nom': 'Puck',   'libelle': 'Puck — enjouée'},
    {'nom': 'Charon', 'libelle': 'Charon — informative'},
    {'nom': 'Fenrir', 'libelle': 'Fenrir — vive'},
    {'nom': 'Leda',   'libelle': 'Leda — jeune'},
    {'nom': 'Orus',   'libelle': 'Orus — ferme'},
    {'nom': 'Zephyr', 'libelle': 'Zephyr — claire'},
]
VOIX_DEFAUT = 'Aoede'

MOTEURS = {
    'gemini': {
        'libelle': 'Gemini Live — vrai dialogue',
        'description': ("Audio direct dans les deux sens. NIMM répond en une "
                        "seconde environ, et se tait dès que tu reprends la "
                        "parole. Voix de Gemini. Nécessite la clé Gemini."),
    },
    'chaine': {
        'libelle': 'Whisper + ton LLM + voix NIMM',
        'description': ("Whisper écoute en local, le fournisseur de ton choix "
                        "répond, la voix TTS de NIMM parle. Trois à six "
                        "secondes par tour : c'est un échange, pas encore un "
                        "dialogue. Marche sans clé Gemini."),
    },
}


# ══════════════════════════════════════════════════════════════════════
#  PARTIE PURE — testable sans réseau, sans clé, sans micro
# ══════════════════════════════════════════════════════════════════════

def voix_valide(nom):
    """Rend un nom de voix sûr. Un nom inconnu ne doit pas faire échouer la
    connexion : mieux vaut la voix par défaut qu'une session morte-née."""
    nom = (nom or '').strip()
    for v in VOIX:
        if v['nom'].lower() == nom.lower():
            return v['nom']
    return VOIX_DEFAUT


def consigne_vocale(user_name='', memoire='', masque='', se_souvient=True):
    """Construit l'instruction système d'une conversation PARLÉE.

    Fonction PURE. Elle diffère volontairement de celle du chat écrit :
      - à l'oral, une liste à puces ou un titre en gras ne veut rien dire ;
      - une réponse de quinze lignes est insupportable à écouter ;
      - et surtout, il faut autoriser explicitement à être coupé, sinon le
        modèle reprend sa phrase du début après chaque interruption.

    `se_souvient=False` coupe TOUT contexte : ni prénom, ni mémoire, ni
    masque. C'est le réglage « page blanche ».
    """
    bouts = [
        "Tu es NIMM. Ceci est une conversation PARLÉE, en français, en direct.",
        "",
        "Comment parler :",
        "- Des phrases courtes. Tu parles, tu ne rédiges pas.",
        "- Aucune mise en forme : pas de listes, pas de titres, pas d'astérisques,"
        " pas de numérotation. Tout sera prononcé tel quel.",
        "- Deux ou trois phrases par tour, sauf si on te demande de développer.",
        "- Tu peux hésiter, reprendre, penser à voix haute. C'est une conversation.",
        "- Si on te coupe, tu t'arrêtes et tu écoutes. Tu ne reprends jamais ta"
        " phrase interrompue depuis le début.",
        "- Si tu n'as pas compris, tu le dis et tu demandes de répéter.",
        "- Ne décris jamais ce que tu es en train de faire : tu réponds, c'est tout.",
    ]

    if se_souvient:
        if user_name and user_name not in ('', 'utilisateur'):
            bouts += ["", f"Ton interlocuteur s'appelle {user_name}. Tutoie-le."]
        if (masque or '').strip():
            bouts += ["", "Ton caractère :", masque.strip()]
        if (memoire or '').strip():
            bouts += ["", "Ce que tu sais déjà de lui :", memoire.strip()]
    else:
        bouts += ["", "Tu ne sais rien de ton interlocuteur, et c'est voulu :"
                      " ne fais semblant de rien savoir."]

    bouts += ["", "Cette conversation n'est enregistrée nulle part. Si on te le"
                  " demande, dis-le simplement."]
    return "\n".join(bouts)


def construire_setup(modele=None, voix=None, consigne='', langue='fr-FR',
                     interruption=True):
    """Le premier message du WebSocket — celui qui décide de tout le reste.

    Fonction PURE, donc vérifiable par un test sans jamais ouvrir de socket.
    C'est important : ce message ne peut pas être corrigé une fois la session
    ouverte (la configuration n'est pas modifiable à chaud), donc une faute
    ici coûte une session entière.

    Trois réglages méritent d'être justifiés :
      - `inputAudioTranscription` / `outputAudioTranscription` : demandés
        TOUS LES DEUX, toujours. Sans eux, la conversation ne laisse aucune
        trace lisible, et devient inutilisable en braille.
      - `activityHandling` : START_OF_ACTIVITY_INTERRUPTS est déjà le défaut,
        mais on l'écrit — un défaut non écrit est un défaut qui change un jour
        sans prévenir.
      - `automaticActivityDetection` : laissée active. C'est Google qui décide
        quand on a commencé et fini de parler ; le faire côté navigateur
        supposerait une détection de voix maison, moins bonne et plus lente.
    """
    setup = {
        'model': 'models/' + (modele or MODELE_DEFAUT),
        'generationConfig': {
            'responseModalities': ['AUDIO'],
            'speechConfig': {
                'voiceConfig': {
                    'prebuiltVoiceConfig': {'voiceName': voix_valide(voix)},
                },
                'languageCode': langue or 'fr-FR',
            },
        },
        # Les deux transcriptions : la promesse de lisibilité tient à ces
        # deux objets vides. Google les attend vides — c'est leur présence,
        # pas leur contenu, qui active la transcription.
        'inputAudioTranscription': {},
        'outputAudioTranscription': {},
        'realtimeInputConfig': {
            'automaticActivityDetection': {'disabled': False},
            'activityHandling': ('START_OF_ACTIVITY_INTERRUPTS' if interruption
                                 else 'NO_INTERRUPTION'),
        },
    }
    if (consigne or '').strip():
        setup['systemInstruction'] = {'parts': [{'text': consigne.strip()}]}
    return {'setup': setup}


def message_audio(donnees_b64):
    """Un morceau d'audio du micro, prêt à partir."""
    return {'realtimeInput': {'audio': {'data': donnees_b64,
                                        'mimeType': MIME_ENTREE}}}


def message_texte(texte):
    """Écrire au lieu de parler, sans quitter la session.

    Utile quand on ne peut pas parler, ou quand un mot passe mal à l'oral
    (un nom propre, une adresse). La réponse revient en voix, comme le reste.
    """
    return {'realtimeInput': {'text': (texte or '')[:8000]}}


def message_fin_audio():
    """Le micro se coupe. La session, elle, reste ouverte."""
    return {'realtimeInput': {'audioStreamEnd': True}}


def interpreter(brut):
    """Traduit un message de Google en un événement simple pour l'interface.

    Fonction PURE. Elle existe pour une raison précise : le format de Google
    est imbriqué, tolérant, et son ordre n'est PAS garanti — la documentation
    le dit explicitement pour les transcriptions. L'interface n'a pas à
    connaître cette forme ; elle reçoit des événements plats et nommés.

    Rend TOUJOURS une liste, parce qu'un seul message de Google peut contenir
    à la fois de l'audio et une transcription.
    """
    evts = []
    if isinstance(brut, (str, bytes)):
        try:
            brut = _json.loads(brut)
        except Exception:
            return [{'type': 'erreur', 'texte': "Message illisible du serveur vocal."}]
    if not isinstance(brut, dict):
        return []

    if 'setupComplete' in brut:
        evts.append({'type': 'prete'})

    sc = brut.get('serverContent') or {}
    if isinstance(sc, dict):
        # L'interruption d'abord : c'est le signal le plus urgent. L'interface
        # doit vider sa file de lecture AVANT de traiter quoi que ce soit
        # d'autre, sinon on entend la fin d'une phrase déjà annulée.
        if sc.get('interrupted'):
            evts.append({'type': 'interrompu'})

        it = sc.get('inputTranscription') or {}
        if isinstance(it, dict) and (it.get('text') or ''):
            evts.append({'type': 'transcription', 'qui': 'moi',
                         'texte': it['text']})

        ot = sc.get('outputTranscription') or {}
        if isinstance(ot, dict) and (ot.get('text') or ''):
            evts.append({'type': 'transcription', 'qui': 'nimm',
                         'texte': ot['text']})

        mt = sc.get('modelTurn') or {}
        for part in (mt.get('parts') or []):
            if not isinstance(part, dict):
                continue
            inline = part.get('inlineData') or {}
            if inline.get('data'):
                evts.append({'type': 'audio', 'donnees': inline['data'],
                             'taux': TAUX_SORTIE})
            elif part.get('text'):
                # Rare en mode AUDIO, mais pas impossible : on ne le jette pas.
                evts.append({'type': 'transcription', 'qui': 'nimm',
                             'texte': part['text']})

        if sc.get('turnComplete'):
            evts.append({'type': 'tour_fini'})

    if 'goAway' in brut:
        # Google prévient avant de fermer. Le dire est plus honnête que de
        # laisser la connexion tomber sans explication.
        reste = (brut.get('goAway') or {}).get('timeLeft') or ''
        evts.append({'type': 'bientot_fini', 'texte': str(reste)})

    if 'toolCall' in brut:
        # Aucun outil n'est déclaré dans notre configuration : si Google en
        # demande un, c'est que quelque chose a changé de son côté. On le
        # signale au lieu de rester muet — la leçon de la réponse muette.
        evts.append({'type': 'erreur',
                     'texte': "Le modèle a demandé un outil alors qu'aucun "
                              "n'est déclaré en mode Live."})
    return evts


def options(api_keys=None, moteur_defaut='gemini'):
    """Ce qui est proposé au lancement, et ce qui est réellement ouvert."""
    cle = ((api_keys or {}).get('gemini') or '').strip()
    return {
        'cle_gemini': bool(cle),
        'moteur_conseille': 'gemini' if cle else 'chaine',
        'moteur_defaut': moteur_defaut if cle else 'chaine',
        'moteurs': [{'nom': n, 'libelle': m['libelle'],
                     'description': m['description'],
                     'ouvert': (n != 'gemini') or bool(cle)}
                    for n, m in MOTEURS.items()],
        'voix': list(VOIX),
        'voix_defaut': VOIX_DEFAUT,
        'modele': MODELE_DEFAUT,
        'taux_entree': TAUX_ENTREE,
        'taux_sortie': TAUX_SORTIE,
        'note': ("Clé Gemini enregistrée : le vrai dialogue est ouvert."
                 if cle else
                 "Aucune clé Gemini : seul le mode Whisper + ton LLM est "
                 "disponible. Compte trois à six secondes par tour."),
        'confidentialite': ("Une conversation Live n'est jamais enregistrée : "
                            "ni message, ni mémoire, ni note de carnet. La "
                            "transcription reste à l'écran tant que tu ne "
                            "fermes pas, et tu décides à la fin de la garder "
                            "ou non."),
    }


# ══════════════════════════════════════════════════════════════════════
#  PARTIE RÉSEAU — la passerelle proprement dite
# ══════════════════════════════════════════════════════════════════════

def url_gemini(cle):
    """L'adresse complète, clé comprise. Isolée dans une fonction pour qu'on
    puisse la vérifier sans jamais l'écrire dans un journal."""
    return f"{_BASE_WS}?key={(cle or '').strip()}"


async def ouvrir_gemini(cle, setup):
    """Ouvre la session chez Google et envoie la configuration.

    Rend (connexion, erreur_en_français). Ne lève jamais : une clé absente,
    un réseau coupé ou une bibliothèque manquante doivent produire une phrase
    lisible, pas une trace d'exception dans la console.
    """
    if not (cle or '').strip():
        return None, ("Aucune clé Gemini enregistrée : le mode Live natif a "
                      "besoin de la même clé que le texte.")
    try:
        import websockets
    except ImportError:
        return None, ("La bibliothèque « websockets » manque. Installe-la avec "
                      "« pip install websockets », puis relance NIMM.")
    try:
        # Les morceaux d'audio sont petits mais nombreux ; la valeur par
        # défaut de la bibliothèque suffit largement. On ne fixe que le
        # ping, pour que la session ne meure pas pendant un silence.
        conn = await websockets.connect(url_gemini(cle), ping_interval=20,
                                        ping_timeout=20, max_size=None)
    except Exception as e:
        return None, f"Connexion au service vocal impossible : {e}"
    try:
        await conn.send(_json.dumps(setup))
    except Exception as e:
        try:
            await conn.close()
        except Exception:
            pass
        return None, f"Configuration de la session refusée : {e}"
    return conn, ''
