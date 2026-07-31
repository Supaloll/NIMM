# -*- coding: utf-8 -*-
"""Génération musicale par Lyria 3 (Gemini).

POURQUOI CE MODULE
La clé Gemini enregistrée dans NIMM ouvre trois portes restées fermées : la
musique (Lyria), l'image (Imagen) et la vidéo (Veo). Celle-ci ouvre la musique.

DEUX MODÈLES, DEUX USAGES
  - « clip » : 30 secondes, réponse rapide, pour une idée, une boucle, un essai ;
  - « pro »  : quelques minutes, structure réelle (couplets, refrains, pont),
    et sortie WAV possible si l'on veut travailler le fichier ensuite.

CE QUE RENVOIE LE MODÈLE
Deux choses, pas une : de l'audio ET du texte (paroles, description de la
structure). Ce texte compte autant que le son ici — c'est la seule partie du
résultat qui se lit à l'afficheur braille. Le module le remonte toujours,
séparément, plutôt que de le laisser se perdre dans la réponse brute.

PRUDENCE
Une génération peut durer plusieurs minutes. Le module borne l'attente, ne lève
jamais d'exception vers l'appelant et rend ses erreurs en français.
"""

import base64

_BASE = 'https://generativelanguage.googleapis.com/v1beta/models'

# Attente longue assumée : le modèle « pro » compose plusieurs minutes de
# musique, on ne peut pas lui appliquer le délai d'une requête de chat.
_DELAI_CLIP = 180.0
_DELAI_PRO = 420.0

MODELES = {
    'clip': {
        'id': 'lyria-3-clip-preview',
        'libelle': 'Lyria 3 Clip — 30 secondes',
        'description': ("Toujours 30 secondes. Rapide : bon pour une idée, "
                        "une boucle, un habillage court."),
        'formats': ('mp3',),
        'delai': _DELAI_CLIP,
    },
    'pro': {
        'id': 'lyria-3-pro-preview',
        'libelle': 'Lyria 3 Pro — morceau complet',
        'description': ("Quelques minutes, avec couplets, refrains et pont. "
                        "La durée s'oriente depuis la consigne : « fais un "
                        "morceau de deux minutes »."),
        'formats': ('mp3', 'wav'),
        'delai': _DELAI_PRO,
    },
}

_MIMES = {'mp3': 'audio/mpeg', 'wav': 'audio/wav'}


def modeles_disponibles(api_keys=None):
    """Les modèles, et si la clé nécessaire est là — dit plutôt que deviné."""
    cle = ((api_keys or {}).get('gemini') or '').strip()
    return {
        'cle_presente': bool(cle),
        'note': ("Clé Gemini enregistrée : la génération musicale est ouverte."
                 if cle else
                 "Aucune clé Gemini enregistrée : la génération musicale reste "
                 "fermée. C'est la même clé que pour l'image et le texte."),
        'modeles': [{'nom': nom, 'id': m['id'], 'libelle': m['libelle'],
                     'description': m['description'], 'formats': list(m['formats'])}
                    for nom, m in MODELES.items()],
    }


def _extraire(data):
    """Sépare l'audio du texte dans la réponse.

    La documentation insiste sur un point qu'il serait coûteux d'ignorer :
    l'ordre des parties n'est PAS garanti. On parcourt donc tout, sans supposer
    que les paroles arrivent en premier ni que l'audio est en dernier.
    """
    audio_b64, mime, textes = '', '', []
    try:
        parts = (data.get('candidates') or [{}])[0].get('content', {}).get('parts', [])
    except (AttributeError, IndexError, TypeError):
        return '', '', ''
    for part in parts:
        if not isinstance(part, dict):
            continue
        inline = part.get('inlineData') or part.get('inline_data') or {}
        if inline and inline.get('data'):
            audio_b64 = inline.get('data') or ''
            mime = inline.get('mimeType') or inline.get('mime_type') or ''
        elif part.get('text'):
            textes.append(part['text'])
    return audio_b64, mime, '\n\n'.join(textes).strip()


def _raison_refus(data):
    """Un blocage de sécurité renvoie 200 sans audio : il faut le dire, pas
    laisser croire à une panne réseau."""
    try:
        cand = (data.get('candidates') or [{}])[0]
    except (AttributeError, IndexError, TypeError):
        return ''
    motif = (cand.get('finishReason') or '').upper()
    if motif and motif not in ('STOP', 'MAX_TOKENS', ''):
        return (f"La demande a été refusée par le modèle (motif : {motif}). "
                "Reformule la consigne — les noms d'artistes réels et les "
                "paroles existantes sont notamment refusés.")
    if (data.get('promptFeedback') or {}).get('blockReason'):
        return ("La consigne a été bloquée avant génération : "
                f"{data['promptFeedback']['blockReason']}.")
    return ''


async def generer(prompt, modele='clip', format_audio='mp3', api_keys=None,
                  images=None):
    """Génère un morceau. Rend un dict — jamais d'exception vers l'appelant.

    Succès : {'audio_b64', 'mime', 'extension', 'paroles', 'modele', 'secondes'}
    Échec  : {'erreur': "phrase en français"}
    """
    import time as _time

    prompt = (prompt or '').strip()
    if not prompt:
        return {'erreur': "Décris la musique que tu veux : le modèle part de ta "
                          "consigne, pas d'un formulaire."}

    conf = MODELES.get(modele) or MODELES['clip']
    cle = ((api_keys or {}).get('gemini') or '').strip()
    if not cle:
        return {'erreur': "Aucune clé Gemini enregistrée : la génération musicale "
                          "a besoin de la même clé que l'image et le texte."}

    fmt = (format_audio or 'mp3').lower()
    if fmt not in conf['formats']:
        # On corrige au lieu de refuser, mais on ne le fait pas en douce :
        # la réponse porte l'extension réellement obtenue.
        fmt = conf['formats'][0]

    parts = [{'text': prompt}]
    for img in (images or [])[:10]:
        donnees = (img or {}).get('b64') or ''
        if not donnees:
            continue
        if ',' in donnees:
            donnees = donnees.split(',', 1)[1]
        parts.append({'inlineData': {'mimeType': (img.get('mime') or 'image/jpeg'),
                                     'data': donnees}})

    corps = {'contents': [{'parts': parts}]}
    if fmt == 'wav':
        corps['generationConfig'] = {
            'responseModalities': ['AUDIO', 'TEXT'],
            'responseFormat': {'audio': {'mimeType': 'audio/wav'}},
        }

    # Import tardif volontaire : les vérifications ci-dessus (consigne vide, clé
    # absente) doivent répondre même là où httpx n'est pas installé.
    import httpx

    debut = _time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=conf['delai']) as client:
            r = await client.post(
                f"{_BASE}/{conf['id']}:generateContent",
                headers={'x-goog-api-key': cle, 'Content-Type': 'application/json'},
                json=corps)
    except httpx.TimeoutException:
        return {'erreur': (f"Le modèle n'a pas répondu en "
                           f"{int(conf['delai'] // 60)} minutes. Un morceau long "
                           "peut demander plus : réessaie, ou passe au format court.")}
    except Exception as e:
        return {'erreur': f"Appel impossible : {e}"}

    if r.status_code >= 400:
        detail = (r.text or '')[:400]
        return {'erreur': f"Gemini a répondu {r.status_code} : {detail}"}

    try:
        data = r.json()
    except Exception:
        return {'erreur': "Réponse illisible de Gemini."}

    audio_b64, mime, paroles = _extraire(data)
    if not audio_b64:
        return {'erreur': _raison_refus(data) or
                          "Gemini a répondu, mais sans audio exploitable."}

    extension = 'wav' if 'wav' in (mime or '').lower() else 'mp3'
    return {
        'audio_b64': audio_b64,
        'mime': mime or _MIMES.get(extension, 'audio/mpeg'),
        'extension': extension,
        'paroles': paroles,
        'modele': conf['id'],
        'libelle': conf['libelle'],
        'secondes': round(_time.perf_counter() - debut, 1),
        'prompt': prompt,
    }


def decoder(audio_b64):
    """Base64 → octets. Rend b'' plutôt que de lever sur une chaîne abîmée."""
    try:
        donnees = audio_b64
        if ',' in donnees[:100]:
            donnees = donnees.split(',', 1)[1]
        return base64.b64decode(donnees)
    except Exception:
        return b''
