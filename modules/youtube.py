# -*- coding: utf-8 -*-
"""Lecture du TEXTE d'une video — ses sous-titres, pas ses images.

POURQUOI CE MODULE EXISTE
NIMM savait deja « regarder » une video : `describe_video_gemini` l'envoie a
Gemini, qui la decrit avec des reperes de temps. Mais cela demande une cle, des
jetons payants, moins de 18 Mo en local — et rend une DESCRIPTION, jamais le
texte.

Or dans une conference, un tutoriel ou une interview, l'essentiel est DIT avant
d'etre montre. YouTube publie ce texte : les sous-titres. Les lire ne coute
rien, ne demande aucune cle, ne depend d'aucun modele, et le resultat se range
dans la base de connaissances comme n'importe quel document.

CE QUE CE MODULE NE FAIT PAS
Il ne telecharge PAS la video. On demande a yt-dlp la LISTE des pistes de
sous-titres, puis on lit une seule piste : un fichier de texte de quelques
dizaines de kilo-octets. Aucune image ne circule.

L'ORDRE DE PREFERENCE DES PISTES
Une piste ECRITE A LA MAIN par l'auteur passe toujours avant une piste generee
automatiquement : elle porte la ponctuation et les noms propres. Ensuite
seulement viennent les pistes automatiques, souvent fautives sur les noms.

PRUDENCE
Aucune fonction ne leve : les erreurs reviennent en francais dans le resultat.
yt-dlp n'est PAS importe en tete du module : sur une machine ou il manque, NIMM
doit continuer de demarrer — et le dire en francais plutot que de refuser.
"""

import html
import json
import re
import sys

from modules import net_guard

# Domaines reconnus d'emblee. Un autre site accepte par yt-dlp fonctionne
# aussi : ce filtre sert au MESSAGE, pas a interdire.
_DOMAINE_VIDEO = re.compile(
    r'^(?:https?://)?(?:www\.|m\.|music\.)?'
    r'(?:youtube\.com|youtu\.be|youtube-nocookie\.com)(?:/|$)',
    re.IGNORECASE)

_LANGUES_DEFAUT = ('fr', 'en')
_BLOC_SECONDES = 30          # regroupement des repliques en blocs horodates
_DELAI = 30.0                # secondes
_MAX_CARACTERES = 200_000    # au-dela, on tronque ET on le dit

# Formats de piste, du plus simple a lire au plus complique. json3 est du JSON
# structure : pas d'analyse de blocs horaires, donc pas de piege de format.
_FORMES_PREFEREES = ('json3', 'vtt', 'srv3', 'srt', 'ttml')

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Balises de mise en forme des sous-titres (<c>, <00:00:01.000>, <i>…).
_BALISE = re.compile(r'<[^>]{0,40}>')
_ACCOLADES = re.compile(r'\{[^}]{0,40}\}')


# ══════════════════════════════════════════════════════════════════
# DISPONIBILITE
# ══════════════════════════════════════════════════════════════════

def disponible():
    """yt-dlp est-il installe ? On ne l'importe pas en tete de module, pour que
    NIMM demarre meme sans lui — cette sonde le dit sans rien casser."""
    try:
        import yt_dlp  # noqa: F401
        return True
    except Exception:
        return False


def options():
    """Ce que l'interface peut annoncer sans rien tenter."""
    return {
        'disponible': disponible(),
        'langues_preferees': list(_LANGUES_DEFAUT),
        # Le francais d'abord, l'anglais ensuite : la quasi-totalite des
        # videos suivies par Laurent ont l'une des deux pistes.
        'note': ("Les sous-titres d'une vidéo se lisent sans clé d'API et sans "
                 "télécharger l'image : le texte seul, horodaté."
                 if disponible() else
                 "La lecture des sous-titres demande yt-dlp, qui n'est pas "
                 "installé sur cette machine (pip install yt-dlp)."),
    }


# ══════════════════════════════════════════════════════════════════
# OUTILS INTERNES (fonctions pures — testables sans reseau)
# ══════════════════════════════════════════════════════════════════

def est_lien_video(url):
    """Vrai si le lien ressemble a une video connue (YouTube et variantes)."""
    return bool(_DOMAINE_VIDEO.match((url or '').strip()))


def _normaliser(url):
    """Accepte un lien colle sans « https:// » — c'est le cas le plus courant
    quand on copie depuis un mobile."""
    url = (url or '').strip()
    if not url:
        return ''
    if not url.lower().startswith(('http://', 'https://')):
        url = 'https://' + url.lstrip('/')
    return url


def _propre(texte):
    """Espaces multiples et espaces insecables ramenes a un seul espace."""
    return re.sub(r'\s+', ' ', (texte or '').replace('\u00a0', ' ')).strip()


def _sans_balises(ligne):
    """Une replique de sous-titre, debarrassee de sa mise en forme.

    Les entites HTML (&amp;, &#39;, &gt;…) sont decodees : YouTube en laisse
    dans les pistes VTT, et « &amp; » se lit mal, a l'oreille comme au braille.
    """
    sans_balises = _ACCOLADES.sub('', _BALISE.sub('', ligne or ''))
    return _propre(html.unescape(sans_balises))


def _horodatage(secondes):
    """832 -> « 13:52 ». Lisible a l'oreille comme au lecteur d'ecran."""
    secondes = max(0, int(secondes or 0))
    h, reste = divmod(secondes, 3600)
    m, s = divmod(reste, 60)
    if h:
        return '%d:%02d:%02d' % (h, m, s)
    return '%02d:%02d' % (m, s)


def _ms_depuis_horodatage(texte):
    """« 00:01:23.456 » ou « 01:23.456 » -> 83456 millisecondes. 0 si illisible."""
    texte = (texte or '').strip().replace(',', '.')
    morceaux = texte.split(':')
    if not morceaux or len(morceaux) > 3:
        return 0
    try:
        nombres = [float(x) for x in morceaux]
    except ValueError:
        return 0
    while len(nombres) < 3:
        nombres.insert(0, 0.0)
    h, m, s = nombres
    return int(round((h * 3600 + m * 60 + s) * 1000))


def _repliques_json3(contenu):
    """Repliques d'une piste json3 : [(millisecondes, texte), …]."""
    try:
        donnees = json.loads(contenu or '{}')
    except Exception:
        return []
    sortie = []
    for evenement in (donnees.get('events') or []):
        if not isinstance(evenement, dict):
            continue
        morceaux = evenement.get('segs') or []
        texte = ''.join(m.get('utf8', '') for m in morceaux
                        if isinstance(m, dict))
        texte = _propre(texte)
        if texte:
            sortie.append((int(evenement.get('tStartMs') or 0), texte))
    return sortie


def _repliques_vtt(contenu):
    """Repliques d'une piste VTT/SRT : [(millisecondes, texte), …].

    Volontairement tolerant : un fichier VTT de YouTube melange lignes vides,
    numerotation de replique, en-tetes et styles en ligne. On saute ce qu'on ne
    comprend pas plutot que d'echouer sur un detail de forme.
    """
    sortie = []
    horodatage = None
    tampon = []

    def _vider():
        if tampon and horodatage is not None:
            texte = _propre(' '.join(tampon))
            if texte:
                sortie.append((horodatage, texte))

    for ligne in (contenu or '').splitlines():
        brut = ligne.replace(chr(0xFEFF), '').strip()
        if '-->' in brut:
            _vider()
            horodatage = _ms_depuis_horodatage(brut.split('-->')[0].strip())
            tampon = []
            continue
        if not brut:
            _vider()
            tampon = []
            continue
        haut = brut.upper()
        if haut.startswith(('WEBVTT', 'NOTE', 'KIND:', 'LANGUAGE:', 'STYLE')):
            continue
        if brut.isdigit() and not tampon:
            continue                      # numerotation de replique (SRT)
        if horodatage is None:
            continue
        propre = _sans_balises(brut)
        if propre:
            tampon.append(propre)
    _vider()
    return sortie


def _repliques(contenu, extension):
    """Choisit l'analyseur d'apres le format annonce, et se rabat sur la forme
    du contenu : un format mal annonce ne doit pas perdre la piste."""
    contenu = contenu or ''
    if extension == 'json3' or contenu.lstrip()[:1] == '{':
        return _repliques_json3(contenu)
    return _repliques_vtt(contenu)


def _assembler(repliques, bloc_secondes=_BLOC_SECONDES):
    """Regroupe les repliques en blocs horodates d'environ 30 secondes.

    Sans regroupement, on obtient une ligne par phrase — des milliers de lignes
    pour une conference. Avec, on obtient quelques dizaines de reperes que le
    modele peut citer (« vers 12:30 ») et qui restent utilisables a l'oreille.
    """
    blocs = []
    debut = None
    tampon = []
    for millisecondes, texte in repliques:
        seconde = millisecondes // 1000
        if debut is None:
            debut = seconde
        # On FERME le bloc AVANT d'y ajouter la replique suivante : sinon la
        # replique qui declenche la coupure se retrouve collee au bloc
        # precedent, et son horodatage ne veut plus rien dire.
        elif seconde - debut >= bloc_secondes and tampon:
            blocs.append((debut, ' '.join(tampon)))
            debut, tampon = seconde, []
        tampon.append(texte)
    if tampon:
        blocs.append((debut or 0, ' '.join(tampon)))
    return chr(10).join('[%s] %s' % (_horodatage(s), t) for s, t in blocs)


def _codes_candidats(table, voulue):
    """Codes de piste a essayer pour une langue : l'exact, puis la variante
    d'origine, puis les variantes regionales (fr-FR, fr-CA…)."""
    voulue = (voulue or '').lower()
    if not voulue:
        return []
    codes = list((table or {}).keys())
    exact = [c for c in codes if c.lower() == voulue]
    origine = [c for c in codes
               if c.lower().endswith('-orig') and c.lower().startswith(voulue)]
    region = [c for c in codes
              if c.lower().startswith(voulue + '-') and c not in origine]
    return exact + origine + region


def _meilleure_forme(pistes):
    """La piste au format le plus simple a lire, ou {} si aucune exploitable."""
    pistes = [p for p in (pistes or []) if isinstance(p, dict) and p.get('url')]
    if not pistes:
        return {}
    for forme in _FORMES_PREFEREES:
        for piste in pistes:
            if (piste.get('ext') or '').lower() == forme:
                return piste
    return pistes[0]


def _choisir_piste(manuels, automatiques, langues):
    """Piste retenue : ecrite a la main d'abord, sinon generee automatiquement.

    Rend {} si aucune langue demandee n'est disponible — c'est un cas NORMAL,
    pas une panne : beaucoup de videos n'ont aucun sous-titre.
    """
    for table, auto in ((manuels or {}, False), (automatiques or {}, True)):
        for voulue in langues:
            for code in _codes_candidats(table, voulue):
                forme = _meilleure_forme(table.get(code))
                if forme:
                    return {'code': code, 'url': forme['url'],
                            'ext': (forme.get('ext') or '').lower(),
                            'auto': auto}
    return {}


def _lister_pistes(manuels, automatiques):
    """Resume lisible de ce qui est disponible, pour expliquer un echec."""
    def _noms(table, marque):
        return ['%s%s' % (c, marque) for c in sorted((table or {}).keys())]
    return _noms(manuels, '') + _noms(automatiques, ' (auto)')


def _infos(url):
    """Fiche de la video (titre, chaine, duree, pistes) — SANS rien telecharger.

    `noplaylist` : sur un lien de chaine ou de playlist, on prend la premiere
    video. Repondre par une erreur serait plus juste techniquement, mais moins
    utile que de lire ce qui a ete colle.
    """
    import yt_dlp
    reglages = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'socket_timeout': _DELAI,
    }
    with yt_dlp.YoutubeDL(reglages) as ydl:
        return ydl.extract_info(url, download=False) or {}


def _telecharger_piste(piste):
    """Le fichier de texte de la piste : quelques dizaines de kilo-octets."""
    import requests
    reponse = requests.get(piste['url'],
                           headers={'User-Agent': _UA,
                                    'Accept-Language': 'fr,en;q=0.8'},
                           timeout=_DELAI)
    reponse.raise_for_status()
    reponse.encoding = 'utf-8'
    return reponse.text or ''


def lire_sous_titres(url, langues=None):
    """Le texte horodate des sous-titres d'une video.

    Rend un dictionnaire, jamais une exception :
      {'ok': True,  'titre', 'chaine', 'duree', 'langue', 'auto', 'texte', …}
      {'ok': False, 'erreur', 'titre', 'pistes'} pour un echec explique.

    `langues` : ordre de preference (par defaut le francais, puis l'anglais).
    """
    url = _normaliser(url)
    if not url:
        return {'ok': False, 'erreur': "Aucun lien de vidéo fourni."}

    # Le lien vient de l'utilisateur ou d'un modele : meme garde que partout
    # ailleurs dans NIMM, avant la moindre sortie reseau.
    try:
        net_guard.assert_public_url(url)
    except Exception:
        return {'ok': False,
                'erreur': "Lien refusé : il ne pointe pas vers une adresse publique."}

    if not disponible():
        return {'ok': False,
                'erreur': ("La lecture des sous-titres demande yt-dlp, qui n'est "
                           "pas installé sur cette machine (pip install yt-dlp).")}

    demandees = tuple(langues or _LANGUES_DEFAUT)
    try:
        info = _infos(url)
    except Exception as e:
        # Distinguer les deux cas : coller le lien d'un article ne doit pas
        # renvoyer une erreur technique incomprehensible.
        motif = ("Ce lien ne ressemble pas à une vidéo connue et n'a pas pu "
                 "être lu" if not est_lien_video(url)
                 else "Vidéo injoignable ou protégée")
        return {'ok': False,
                'erreur': ("%s (%s)." % (motif, _propre(str(e))[:200]))}

    titre = _propre(info.get('title') or '')
    chaine = _propre(info.get('channel') or info.get('uploader') or '')
    duree = info.get('duration')
    secondes = int(duree) if isinstance(duree, (int, float)) else 0
    resultat = {'titre': titre, 'chaine': chaine, 'duree': secondes,
                'duree_texte': _horodatage(secondes) if secondes else ''}

    if info.get('is_live'):
        resultat['ok'] = False
        resultat['erreur'] = ("Cette vidéo est en direct : ses sous-titres ne "
                              "sont pas encore stabilisés.")
        return resultat

    piste = _choisir_piste(info.get('subtitles'),
                           info.get('automatic_captions'), demandees)
    if not piste:
        dispo = _lister_pistes(info.get('subtitles'),
                               info.get('automatic_captions'))
        detail = (" Langues proposées : %s." % ', '.join(dispo[:12])) if dispo else ''
        resultat['ok'] = False
        resultat['pistes'] = dispo
        resultat['erreur'] = ("Cette vidéo n'a pas de sous-titres dans les langues "
                              "demandées (%s).%s"
                              % (', '.join(demandees) or 'aucune', detail))
        return resultat

    try:
        contenu = _telecharger_piste(piste)
    except Exception as e:
        resultat['ok'] = False
        resultat['erreur'] = ("Sous-titres annoncés mais illisibles (%s)."
                              % _propre(str(e))[:200])
        return resultat

    repliques = _repliques(contenu, piste['ext'])
    if not repliques:
        resultat['ok'] = False
        resultat['erreur'] = ("La piste de sous-titres était vide ou dans un "
                              "format inattendu.")
        return resultat

    texte = _assembler(repliques)
    tronque = len(texte) > _MAX_CARACTERES
    if tronque:
        texte = texte[:_MAX_CARACTERES]

    resultat.update({
        'ok': True,
        'texte': texte,
        'langue': piste['code'],
        'auto': piste['auto'],
        'repliques': len(repliques),
        'caracteres': len(texte),
        'tronque': tronque,
    })
    return resultat


def lire_et_verser(url, langues=None, expiration=None):
    """Lit les sous-titres d'une video ET les range dans la base de
    connaissances, pour qu'ils deviennent interrogeables comme un document.

    Separation nette : `lire_sous_titres` ne touche a rien, celle-ci ecrit.
    Un echec de lecture n'ecrit RIEN — jamais de document vide dans la base.
    `expiration` : None = permanent (c'est le cas d'un tutoriel ou d'une
    conference, qui ne periment pas).
    """
    resultat = lire_sous_titres(url, langues=langues)
    if not resultat.get('ok'):
        return resultat

    titre = resultat.get('titre') or 'Vidéo sans titre'
    entete = ['# %s' % titre]
    if resultat.get('chaine'):
        entete.append('Chaîne : %s' % resultat['chaine'])
    entete.append('Source : %s' % url)
    entete.append('Langue des sous-titres : %s%s'
                  % (resultat.get('langue') or '?',
                     ' (générée automatiquement)' if resultat.get('auto') else ''))
    document = chr(10).join(entete) + chr(10) * 2 + resultat['texte']

    try:
        from modules.enrichissement import ingest_text
        compte = ingest_text('%s (sous-titres)' % titre, document,
                             source=url, expiration=expiration)
    except Exception as e:
        resultat['verse'] = False
        resultat['verse_erreur'] = ("Lecture réussie, mais versement impossible "
                                    "(%s)." % e)
        return resultat

    resultat['verse'] = bool(isinstance(compte, dict) and compte.get('ok'))
    resultat['passages'] = (compte or {}).get('passages') if resultat['verse'] else 0
    return resultat


# ══════════════════════════════════════════════════════════════════
# MISE A JOUR DE yt-dlp — LE SEUL PAQUET DE NIMM QUI PERIME
# ══════════════════════════════════════════════════════════════════
#
# POURQUOI CE PAQUET-LA ET PAS LES AUTRES
# yt-dlp parle a des sites tiers qui changent leurs defenses. Une version
# ancienne ne « bugue » pas : elle CESSE de fonctionner, d'un coup, sans
# prevenir. C'est le contraire de numpy, fastapi, whisper ou trafilatura, dont
# une version ancienne tourne des annees sans le moindre souci.
#
# D'ou la regle de conception, non negociable : NIMM ne met a jour QUE yt-dlp,
# et jamais tout requirements.txt. Une mise a jour automatique du fichier
# entier retelechargerait des gigabytes et ferait tomber des versions epinglees.
#
# CE QUE CE BLOC NE FAIT PAS
# La detection n'installe RIEN. Elle interroge le catalogue PyPI (quelques
# kilo-octets) et compare. L'installation est une action SEPAREE, declenchee
# par un clic de l'utilisateur — jamais toute seule.

_PYPI_URL = 'https://pypi.org/pypi/yt-dlp/json'
_DELAI_PYPI = 15.0
_MAJ_TIMEOUT_S = 300
_CACHE_SECONDES = 6 * 3600      # au plus une interrogation PyPI toutes les 6 h

# Cache EN MEMOIRE : rien n'est ecrit sur disque. Une interrogation par
# session suffit ; le bouton peut forcer.
_CACHE_MAJ = {'quand': 0.0, 'resultat': None}


def version_installee():
    """La version de yt-dlp EN PLACE SUR LE DISQUE, ou '' s'il est absent.

    `importlib.metadata` lit le paquet installe : elle dit la verite meme juste
    apres une mise a jour, alors qu'un `import yt_dlp` rendrait encore
    l'ancienne version gardee en memoire par Python.
    """
    try:
        from importlib.metadata import version as _v
        return (_v('yt-dlp') or '').strip()
    except Exception:
        pass
    try:
        import yt_dlp
        return (getattr(yt_dlp.version, '__version__', '') or '').strip()
    except Exception:
        return ''


def version_en_memoire():
    """La version que CE processus utilise vraiment, ou '' si elle n'est pas
    encore chargee.

    Apres une mise a jour, elle reste l'ancienne JUSQU'AU REDEMARRAGE : Python
    garde le module deja importe. Le dire evite la fausse impression qu'un clic
    a tout change.
    """
    module = sys.modules.get('yt_dlp')
    if module is None:
        return ''
    return (getattr(getattr(module, 'version', None), '__version__', '') or '').strip()


def _version_nombres(texte):
    """« 2026.08.19 » -> (2026, 8, 19). Des NOMBRES, pas du texte.

    Piege verifie en vrai : yt-dlp s'annonce « 2026.08.19 » tandis que PyPI
    publie « 2026.8.19 ». Comparer les chaines telles quelles ferait croire a
    une nouveaute... pour toujours. Un zero de tete n'a aucun sens dans un
    numero de version : on compare ce qu'il represente.
    """
    nombres = []
    for morceau in (texte or '').split('.'):
        chiffres = ''.join(c for c in morceau if c.isdigit())
        nombres.append(int(chiffres) if chiffres else 0)
    return tuple(nombres)


def _infos_pypi():
    """Derniere version publiee : {'version', 'date', 'taille'}.

    Leve en cas de panne reseau — c'est l'appelant qui decide du message.
    """
    import requests
    reponse = requests.get(_PYPI_URL, timeout=_DELAI_PYPI,
                           headers={'Accept': 'application/json',
                                    'User-Agent': _UA})
    reponse.raise_for_status()
    donnees = reponse.json()
    info = donnees.get('info') or {}
    fichiers = donnees.get('urls') or []
    dernier = fichiers[0] if fichiers else {}
    return {
        'version': (info.get('version') or '').strip(),
        'date': (dernier.get('upload_time') or '')[:10],
        'taille': dernier.get('size'),
    }


def maj_disponible(verifier=False):
    """Une version plus recente de yt-dlp est-elle publiee ? N'INSTALLE RIEN.

    Rend un dictionnaire, jamais une exception :
      {'ok', 'installee', 'derniere', 'date_derniere', 'a_jour', 'poids_mo',
       'en_memoire', 'message', 'erreur'}

    `a_jour` vaut None quand on n'a PAS PU savoir (panne reseau). C'est
    volontaire : annoncer « tu es a jour » sans avoir pu verifier serait un
    mensonge — et c'est exactement le genre de mensonge que NIMM s'interdit
    ailleurs (voir le test de la description d'image).
    """
    import time
    maintenant = time.time()
    if (not verifier and _CACHE_MAJ['resultat'] is not None
            and maintenant - _CACHE_MAJ['quand'] < _CACHE_SECONDES):
        return _CACHE_MAJ['resultat']

    installee = version_installee()
    resultat = {'ok': True, 'installee': installee,
                'en_memoire': version_en_memoire(),
                'derniere': '', 'date_derniere': '', 'a_jour': None,
                'poids_mo': None, 'message': '', 'erreur': ''}

    if not installee or not disponible():
        resultat['ok'] = False
        resultat['a_jour'] = False
        resultat['erreur'] = ("yt-dlp n'est pas installe : la lecture du texte "
                              "des videos est indisponible.")
        resultat['message'] = resultat['erreur']
        return resultat

    try:
        publiee = _infos_pypi()
    except Exception as e:
        resultat['erreur'] = ("Verification impossible (%s)."
                              % _propre(str(e))[:160])
        resultat['message'] = ("Impossible de verifier la version de yt-dlp "
                               "pour l'instant. La version installee reste "
                               "utilisable.")
        _CACHE_MAJ['quand'], _CACHE_MAJ['resultat'] = maintenant, resultat
        return resultat

    resultat['derniere'] = publiee['version']
    resultat['date_derniere'] = publiee['date']
    if publiee.get('taille'):
        resultat['poids_mo'] = round(publiee['taille'] / 1048576, 1)

    resultat['a_jour'] = (_version_nombres(installee)
                          >= _version_nombres(publiee['version']))
    if resultat['a_jour']:
        resultat['message'] = "yt-dlp est a jour (%s)." % installee
    else:
        resultat['message'] = ("Une nouvelle version de yt-dlp est disponible : "
                               "%s, publiee le %s. La version installee est %s."
                               % (publiee['version'],
                                  publiee['date'] or 'date inconnue',
                                  installee))
    _CACHE_MAJ['quand'], _CACHE_MAJ['resultat'] = maintenant, resultat
    return resultat


def mettre_a_jour():
    """Installe la derniere version de yt-dlp. SUR UN CLIC, jamais tout seul.

    Rend {'ok', 'avant', 'apres', 'message', 'detail'}. Ne leve jamais.

    DEUX PRECAUTIONS QUI VIENNENT DU CODE DEJA ECRIT
    - `sys.executable -m pip` et NON « pip » : la machine a deux Python, et le
      pip du PATH n'est pas forcement celui qui fait tourner NIMM. Installer
      dans le mauvais donnerait un paquet bien present — et que NIMM ne verrait
      jamais. Le piege est deja documente dans modules/memory.py, et il s'est
      manifeste en vrai le 25/09/2026.
    - Rien n'est casse si l'installation echoue : l'ancienne version reste en
      place et continue de fonctionner. On le DIT, sans dramatiser.

    La commande vaut aussi pour une PREMIERE installation : `--upgrade` installe
    ce qui manque et met a jour ce qui est ancien.
    """
    import subprocess
    avant = version_installee()
    commande = [sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp']
    print('[YTDLP] Mise a jour demandee depuis l interface...')
    try:
        r = subprocess.run(commande, capture_output=True, text=True,
                           timeout=_MAJ_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'avant': avant, 'apres': avant, 'detail': '',
                'message': ("Mise a jour abandonnee : delai depasse (%d s). "
                            "L'ancienne version reste en place."
                            % _MAJ_TIMEOUT_S)}
    except Exception as e:
        return {'ok': False, 'avant': avant, 'apres': avant,
                'detail': _propre(str(e))[:400],
                'message': ("Mise a jour impossible (%s). L'ancienne version "
                            "reste en place." % _propre(str(e))[:160])}

    apres = version_installee()
    if r.returncode != 0 or not apres:
        detail = ((r.stderr or '') + (r.stdout or '')).strip()[-500:]
        print('[YTDLP] Echec (code %d)' % r.returncode)
        return {'ok': False, 'avant': avant, 'apres': avant, 'detail': detail,
                'message': ("La mise a jour a echoue (code %d). L'ancienne "
                            "version reste en place : NIMM continue de "
                            "fonctionner." % r.returncode)}

    # Le cache disait peut-etre « a jour » : il vient d'etre perime.
    _CACHE_MAJ['quand'], _CACHE_MAJ['resultat'] = 0.0, None

    if not avant:
        message = ("yt-dlp %s vient d'etre installe. La lecture du texte des "
                   "videos sera active au prochain demarrage de NIMM." % apres)
    elif apres != avant:
        message = ("yt-dlp est passe de %s a %s. La nouvelle version sera "
                   "active au prochain demarrage de NIMM — Python garde "
                   "l'ancienne en memoire jusque-la." % (avant, apres))
    else:
        message = "yt-dlp etait deja a la derniere version (%s)." % apres
    print('[YTDLP] Termine : %s -> %s' % (avant or 'absent', apres))
    return {'ok': True, 'avant': avant, 'apres': apres, 'detail': '',
            'message': message}
