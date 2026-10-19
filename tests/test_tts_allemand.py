# -*- coding: utf-8 -*-
"""
Test hors-ligne de la prononciation allemande automatique (modules/tts.py).

Vérifie :
  1. detecter_allemand() — les cas allemands passent, les cas français non.
  2. _voix_allemande() — une voix Edge française devient sa voix allemande du
     même genre ; les autres moteurs et les voix non françaises ne bougent pas.
  3. synthesize() branche vraiment la bascule (doublures : aucun réseau, aucun
     chargement de modèle).

Exécution : python tests/test_tts_allemand.py  (depuis la racine du projet)
"""
import os
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import modules.tts as T


# ── 1. Détection ────────────────────────────────────────────────────────────

# Ce qui DOIT basculer en allemand.
CAS_ALLEMANDS = [
    'Der Hund ist groß.',              # ß : signal fort
    'Die Übung war sehr gut.',         # Ü : signal fort
    'Ich habe Hunger.',
    'Ich bin müde.',
    'Guten Morgen!',
    'Wie geht es dir?',
    'Kannst du mir bitte helfen?',
    'Der Satz ist falsch.',
    'Schreibe den Satz im Perfekt.',
    'Auf Wiedersehen!',
    'Übung',                           # umlaut seul : suffit à détacher
]

# Ce qui NE DOIT PAS basculer : de vraies phrases françaises, dont les pièges
# d'homographe (« du », « sein ») et une phrase courte.
CAS_FRANCAIS = [
    '',
    'Bonjour Laurent, comment vas-tu ?',
    'Le chat dort sur le canapé, près de la fenêtre.',
    'Il parle allemand couramment et il aime ça.',
    'Cette phrase reste en français du début à la fin.',
    'Le cancer du sein se dépiste tôt.',              # piège « du » + « sein »
    # Détection GLOBALE muette, et c'est voulu : cette phrase n'est pas
    # allemande, elle est MIXTE. C'est la segmentation qui détache le morceau
    # allemand au milieu — voir CAS_SEGMENTS et le test de segmentation.
    'En allemand, « Ich habe Hunger » veut dire j’ai faim.',
]


def test_detection():
    for texte in CAS_ALLEMANDS:
        assert T.detecter_allemand(texte) is True, 'non detecte : ' + texte
    for texte in CAS_FRANCAIS:
        assert T.detecter_allemand(texte) is False, 'faux positif : ' + texte
    print('OK  detection : %d cas allemands, %d cas francais' % (len(CAS_ALLEMANDS), len(CAS_FRANCAIS)))


# ── 2. Voix équivalente ─────────────────────────────────────────────────────

def test_voix_allemande():
    # Voix Edge FRANÇAISES (dont celles des masques) : elles basculent.
    assert T._voix_allemande('edge:fr-FR-HenriNeural') == 'edge:de-DE-ConradNeural'
    assert T._voix_allemande('edge:fr-FR-DeniseNeural') == 'edge:de-DE-KatjaNeural'
    assert T._voix_allemande('edge:fr-CH-ArianeNeural') == 'edge:de-DE-KatjaNeural'
    assert T._voix_allemande('edge:fr-CA-AntoineNeural') == 'edge:de-DE-ConradNeural'
    # Voix déjà allemande, autre langue, ou autre moteur : intactes.
    assert T._voix_allemande('edge:de-DE-KatjaNeural') is None
    assert T._voix_allemande('edge:en-US-AriaNeural') is None
    assert T._voix_allemande('ff_siwis') is None
    assert T._voix_allemande('piper:fr_FR-gilles-low') is None
    assert T._voix_allemande('gemini:Kore') is None
    assert T._voix_allemande('') is None

    # Cohérence avec le catalogue : toute voix Edge FR proposée dans le
    # sélecteur doit avoir un équivalent allemand — une voix ajoutée plus tard
    # ne doit pas être oubliée en silence.
    for v in T.EDGE_VOICES_FR:
        assert T._voix_allemande('edge:' + v['id']) is not None, v['id']
    # Les voix masculines connues gardent leur genre (sinon un professeur
    # deviendrait soudain une voix féminine en lisant l'allemand).
    masculines = {'fr-FR-HenriNeural', 'fr-FR-RemyMultilingualNeural',
                  'fr-BE-GerardNeural', 'fr-CH-FabriceNeural',
                  'fr-CA-AntoineNeural', 'fr-CA-ThierryNeural'}
    assert masculines <= set(T.EDGE_VOIX_FR_MASCULINES)
    print('OK  voix allemande : Edge FR convertie, autres moteurs intacts')


# ── 3. Branchement dans le routeur ──────────────────────────────────────────

def test_synthesize_bascule_la_voix():
    appels = []

    def faux_synthetiseur(texte, voice, *args, **kwargs):
        appels.append((texte, voice))
        return b'audio'

    originaux = (T.synthesize_edge, T.synthesize_kokoro, T.synthesize_piper)
    T.synthesize_edge = faux_synthetiseur
    T.synthesize_kokoro = faux_synthetiseur
    T.synthesize_piper = faux_synthetiseur
    try:
        # Allemand + voix de masque masculine -> voix allemande masculine.
        T.synthesize('Der Hund ist groß.', 'edge:fr-FR-HenriNeural')
        assert appels[-1][1] == 'de-DE-ConradNeural', appels[-1][1]

        # Allemand + voix de masque féminine -> voix allemande féminine.
        T.synthesize('Wie geht es dir?', 'edge:fr-CH-ArianeNeural')
        assert appels[-1][1] == 'de-DE-KatjaNeural', appels[-1][1]

        # Français : la voix choisie est conservée telle quelle.
        T.synthesize('Bonjour, comment vas-tu ?', 'edge:fr-CH-ArianeNeural')
        assert appels[-1][1] == 'fr-CH-ArianeNeural', appels[-1][1]

        # Kokoro n'a pas de voix allemande : rien ne change (et rien ne casse).
        T.synthesize('Ich habe Hunger.', 'ff_siwis')
        assert appels[-1][1] == 'ff_siwis', appels[-1][1]

        # Voix Edge d'une autre langue : choix explicite, on n'y touche pas.
        T.synthesize('Ich habe Hunger.', 'edge:en-US-AriaNeural')
        assert appels[-1][1] == 'en-US-AriaNeural', appels[-1][1]
    finally:
        T.synthesize_edge, T.synthesize_kokoro, T.synthesize_piper = originaux
    print('OK  synthesize() bascule la voix, et seulement quand il faut')


# ── 4. Segmentation d'une phrase mixte (V2) ─────────────────────────────────

CAS_SEGMENTS = [
    ('Bonjour, comment vas-tu ?', ['fr']),
    ('Der Hund ist groß.', ['de']),
    ('En allemand, « Ich habe Hunger » veut dire j’ai faim.', ['fr', 'de', 'fr']),
    ('Ich habe Hunger, mais je mange.', ['de', 'fr']),
    ('Der Hund ist groß, mais il dort.', ['de', 'fr']),
    ('Kannst du mir helfen?', ['de']),         # « du » encadré -> allemand
    ('Le cancer du sein se dépiste tôt.', ['fr']),
    ('Übung', ['de']),
]


def test_segmentation():
    for texte, attendu in CAS_SEGMENTS:
        morceaux = T.segmenter_par_langue(texte)
        langues = [lg for _, lg in morceaux]
        assert langues == attendu, '%s au lieu de %s pour : %s' % (langues, attendu, texte)
        # Rien ne se perd : les morceaux recollés rendent le texte d'origine.
        assert ''.join(t for t, _ in morceaux) == texte, 'texte altere : ' + texte
        assert all(t.strip() for t, _ in morceaux), 'morceau vide : ' + texte
    print('OK  segmentation : %d cas, allemands et francais melanges' % len(CAS_SEGMENTS))


def test_listes_de_mots_disjointes():
    """Un mot ne peut pas être à la fois marqueur allemand et borne française."""
    doublons = T.MOTS_ALLEMANDS & {T._cle_fr(m) for m in T.MOTS_FRANCAIS}
    assert not doublons, 'mots dans les deux listes : ' + ', '.join(sorted(doublons))
    # Les accents français sont neutralisés, les marqueurs allemands JAMAIS.
    assert T._cle_fr('élève') == 'eleve' and T._cle_fr('très') == 'tres'
    assert T._cle_fr('Übung') == 'übung'
    print('OK  listes de mots : disjointes, accents francais neutralises, umlauts gardes')


def test_synthesize_morceaux_mixtes():
    appels = []

    def faux_synthetiseur(texte, voice, *args, **kwargs):
        appels.append((texte, voice))
        return b'MP3-' + str(len(appels)).encode('ascii')

    originaux = (T.synthesize_edge, T.synthesize_kokoro, T.synthesize_piper)
    T.synthesize_edge = faux_synthetiseur
    T.synthesize_kokoro = faux_synthetiseur
    T.synthesize_piper = faux_synthetiseur
    try:
        texte = 'En allemand, « Ich habe Hunger » veut dire j’ai faim.'
        audio, media = T.synthesize(texte, 'edge:fr-CH-ArianeNeural')
        assert media == 'audio/mpeg', media
        assert [v for _, v in appels] == ['fr-CH-ArianeNeural', 'de-DE-KatjaNeural',
                                          'fr-CH-ArianeNeural'], appels
        # Les trois MP3 sont recollés dans l'ordre, sans perte.
        assert audio == b'MP3-1MP3-2MP3-3', audio
        assert appels[1][0] == 'Ich habe Hunger', appels[1][0]
        assert ''.join(t for t, _ in appels) == texte, 'le texte doit etre conserve'
    finally:
        T.synthesize_edge, T.synthesize_kokoro, T.synthesize_piper = originaux
    print('OK  synthesize() recolle les morceaux mixtes, chacun avec sa voix')


def test_repli_si_un_morceau_echoue():
    """Un morceau perdu ne doit jamais donner du silence."""
    appels = []

    def faux_synthetiseur(texte, voice, *args, **kwargs):
        appels.append((texte, voice))
        return None if len(appels) == 2 else b'MP3'

    originaux = (T.synthesize_edge, T.synthesize_kokoro, T.synthesize_piper)
    T.synthesize_edge = faux_synthetiseur
    T.synthesize_kokoro = faux_synthetiseur
    T.synthesize_piper = faux_synthetiseur
    try:
        texte = 'En allemand, « Ich habe Hunger » veut dire j’ai faim.'
        audio, media = T.synthesize(texte, 'edge:fr-CH-ArianeNeural')
        assert audio is not None, 'repli muet'
        assert appels[-1] == (texte, 'fr-CH-ArianeNeural'), appels[-1]
        assert media == 'audio/mpeg', media
    finally:
        T.synthesize_edge, T.synthesize_kokoro, T.synthesize_piper = originaux
    print('OK  repli : un morceau en echec redonne la synthese en voix unique')


if __name__ == '__main__':
    test_detection()
    test_voix_allemande()
    test_synthesize_bascule_la_voix()
    test_segmentation()
    test_listes_de_mots_disjointes()
    test_synthesize_morceaux_mixtes()
    test_repli_si_un_morceau_echoue()
    print("\nTous les tests passent.\n")
