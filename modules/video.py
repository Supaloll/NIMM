# -*- coding: utf-8 -*-
"""Génération vidéo par Veo 3.1 (Gemini).

POURQUOI CE MODULE EST BÂTI AUTREMENT QUE LES AUTRES
Veo est une opération LONGUE : de onze secondes à six minutes selon l'heure.
On ne peut donc pas attendre la réponse dans une requête HTTP. Le déroulé est
en trois temps, et le module expose les trois séparément :

  1. `lancer()`   → rend le nom d'une opération, tout de suite ;
  2. `etat()`     → dit où en est cette opération, aussi souvent qu'on veut ;
  3. `telecharger()` → rapatrie la vidéo une fois l'opération terminée.

DEUX CONTRAINTES QUI ONT DICTÉ LA CONCEPTION
  - **Google efface la vidéo de ses serveurs au bout de deux jours.** Le
    téléchargement local n'est donc pas un confort, c'est la seule façon de
    garder ce qu'on a produit. NIMM télécharge dès que l'opération est finie.
  - **En Europe, `personGeneration` ne peut valoir que `allow_adult`** pour
    Veo 3 et 3.1. C'est posé par défaut : laisser Google refuser après six
    minutes d'attente serait une perte de temps évitable.

PRUDENCE
Aucune fonction ne lève : les erreurs reviennent en français dans le résultat.
"""

_BASE = 'https://generativelanguage.googleapis.com/v1beta'
_DELAI = 120.0
_DELAI_TELECHARGEMENT = 600.0

# Identifiants relevés dans la liste officielle des modèles (ai.google.dev,
# page « Models », section « Generative media models »). À ne PAS déduire de la
# prose : les tables de paramètres parlent d'un « Veo 3.1 Fast » dont aucun
# identifiant n'est publié — le modèle réellement appelable à côté de Veo 3.1
# est Veo 3.1 Lite, et lui ne fait pas de 4K.
MODELES = {
    'veo31': {
        'id': 'veo-3.1-generate-preview',
        'libelle': 'Veo 3.1 — qualité',
        'description': ("Vidéo de 4, 6 ou 8 secondes avec son généré. "
                        "Jusqu'en 4K, mais alors 8 secondes obligatoires."),
        'resolutions': ('720p', '1080p', '4k'),
    },
    'veo31lite': {
        'id': 'veo-3.1-lite-generate-preview',
        'libelle': 'Veo 3.1 Lite — économique',
        'description': ("Le moins coûteux, pour produire en volume. "
                        "Pas de 4K : 720p ou 1080p."),
        'resolutions': ('720p', '1080p'),
    },
}

RATIOS = ('16:9', '9:16')
DUREES = ('4', '6', '8')

LIBELLES_RATIOS = {'16:9': 'Paysage (16:9)', '9:16': 'Portrait (9:16)'}


def options(api_keys=None):
    """Ce qui est réglable, avec les règles de Google écrites en clair."""
    cle = ((api_keys or {}).get('gemini') or '').strip()
    return {
        'cle_presente': bool(cle),
        'note': ("Clé Gemini enregistrée : la vidéo est ouverte. Compte de onze "
                 "secondes à six minutes d'attente par vidéo."
                 if cle else
                 "Aucune clé Gemini enregistrée : la vidéo reste fermée. C'est la "
                 "même clé que pour le texte, l'image et la musique."),
        'modeles': [{'nom': n, 'id': m['id'], 'libelle': m['libelle'],
                     'description': m['description'],
                     'resolutions': list(m['resolutions'])}
                    for n, m in MODELES.items()],
        'ratios': [{'valeur': r, 'libelle': LIBELLES_RATIOS.get(r, r)} for r in RATIOS],
        'durees': list(DUREES),
        'avertissement': ("Google efface la vidéo de ses serveurs au bout de deux "
                          "jours : NIMM la télécharge sur ta machine dès qu'elle "
                          "est prête."),
    }


def regles(duree, resolution, resolutions_modele=None):
    """Corrige un couple durée/résolution impossible, et DIT ce qui a changé.

    Fonction PURE, donc testable sans réseau. Deux règles, tirées de la
    documentation de Google :
      - tous les modèles n'ont pas les mêmes résolutions (Veo 3.1 Lite ne fait
        pas de 4K) ;
      - 1080p et 4K exigent 8 secondes.
    Envoyer 4 secondes en 4K, c'est six minutes d'attente pour un refus. Autant
    corriger avant de partir — mais jamais en silence : chaque correction
    revient dans la note, et les notes se cumulent.
    """
    notes = []
    duree = str(duree or '8')
    resolution = (resolution or '720p').lower()
    if resolution not in ('720p', '1080p', '4k'):
        resolution = '720p'
    if duree not in DUREES:
        duree = '8'

    dispo = tuple(resolutions_modele or ('720p', '1080p', '4k'))
    if resolution not in dispo:
        demandee, resolution = resolution, dispo[-1]
        notes.append(f"Résolution ramenée à {resolution} : ce modèle ne propose "
                     f"pas le {demandee}.")

    if resolution in ('1080p', '4k') and duree != '8':
        duree = '8'
        notes.append(f"Durée portée à 8 secondes : Google n'accepte que cette "
                     f"durée en {resolution}.")

    return duree, resolution, ' '.join(notes)


async def lancer(prompt, modele='veo31', ratio='16:9', duree='8',
                 resolution='720p', api_keys=None, negatif=''):
    """Démarre une génération. Rend {'operation', 'note', ...} ou {'erreur'}."""
    prompt = (prompt or '').strip()
    if not prompt:
        return {'erreur': "Décris la vidéo que tu veux : le modèle part de ta consigne."}

    conf = MODELES.get(modele) or MODELES['veo31']
    cle = ((api_keys or {}).get('gemini') or '').strip()
    if not cle:
        return {'erreur': "Aucune clé Gemini enregistrée : la vidéo a besoin de la "
                          "même clé que le texte."}

    if ratio not in RATIOS:
        ratio = '16:9'
    duree, resolution, note = regles(duree, resolution, conf['resolutions'])

    parametres = {
        'aspectRatio': ratio,
        'durationSeconds': duree,
        'resolution': resolution,
        # Europe : Veo 3.x n'accepte que cette valeur ici. Posée d'avance plutôt
        # que découverte au bout de six minutes d'attente.
        'personGeneration': 'allow_adult',
    }
    if (negatif or '').strip():
        parametres['negativePrompt'] = negatif.strip()[:500]

    import httpx
    try:
        async with httpx.AsyncClient(timeout=_DELAI) as client:
            r = await client.post(
                f"{_BASE}/models/{conf['id']}:predictLongRunning",
                headers={'x-goog-api-key': cle, 'Content-Type': 'application/json'},
                json={'instances': [{'prompt': prompt}], 'parameters': parametres})
    except Exception as e:
        return {'erreur': f"Lancement impossible : {e}"}

    if r.status_code >= 400:
        return {'erreur': f"Gemini a répondu {r.status_code} : {(r.text or '')[:400]}"}
    try:
        data = r.json()
    except Exception:
        return {'erreur': "Réponse illisible de Gemini."}

    nom = (data or {}).get('name') or ''
    if not nom:
        return {'erreur': "Gemini n'a pas rendu d'identifiant d'opération."}
    return {'operation': nom, 'modele': conf['id'], 'libelle': conf['libelle'],
            'ratio': ratio, 'duree': duree, 'resolution': resolution,
            'prompt': prompt, 'note': note}


def _uri_video(data):
    """Adresse de la vidéo dans une opération terminée, formes tolérées."""
    rep = (data or {}).get('response') or {}
    for chemin in (('generateVideoResponse', 'generatedSamples'),
                   ('generatedSamples',),
                   ('generatedVideos',)):
        noeud = rep
        for cle in chemin:
            noeud = (noeud or {}).get(cle) if isinstance(noeud, dict) else None
        if isinstance(noeud, list) and noeud:
            video = (noeud[0] or {}).get('video') or noeud[0]
            if isinstance(video, dict):
                uri = video.get('uri') or video.get('url') or ''
                if uri:
                    return uri
    return ''


async def etat(operation, api_keys=None):
    """Où en est l'opération ? Rend {'fait', 'uri', 'erreur', 'message'}."""
    operation = (operation or '').strip().lstrip('/')
    if not operation:
        return {'fait': False, 'erreur': "Aucune opération à suivre."}
    cle = ((api_keys or {}).get('gemini') or '').strip()
    if not cle:
        return {'fait': False, 'erreur': "Aucune clé Gemini enregistrée."}

    import httpx
    try:
        async with httpx.AsyncClient(timeout=_DELAI) as client:
            r = await client.get(f"{_BASE}/{operation}",
                                 headers={'x-goog-api-key': cle})
    except Exception as e:
        # Une panne réseau passagère n'est PAS un échec de la génération :
        # l'opération continue chez Google, on redemandera au prochain tour.
        return {'fait': False, 'message': f"État indisponible pour l'instant ({e})."}

    if r.status_code >= 400:
        return {'fait': False, 'erreur': f"Suivi impossible ({r.status_code}) : "
                                         f"{(r.text or '')[:300]}"}
    try:
        data = r.json()
    except Exception:
        return {'fait': False, 'message': "Réponse d'état illisible."}

    if not data.get('done'):
        return {'fait': False, 'message': "Génération en cours."}
    if data.get('error'):
        detail = (data['error'] or {}).get('message', '')
        return {'fait': True, 'erreur': f"La génération a échoué : {detail[:300]}"}

    uri = _uri_video(data)
    if not uri:
        return {'fait': True, 'erreur': ("L'opération est terminée mais sans vidéo. "
                                         "Veo bloque parfois un rendu pour raison de "
                                         "sécurité — dans ce cas tu n'es pas facturé.")}
    return {'fait': True, 'uri': uri, 'message': "Vidéo prête."}


async def telecharger(uri, api_keys=None):
    """Rapatrie la vidéo. Rend (octets, erreur_en_français)."""
    if not (uri or '').strip():
        return b'', "Aucune adresse de vidéo."
    cle = ((api_keys or {}).get('gemini') or '').strip()
    if not cle:
        return b'', "Aucune clé Gemini enregistrée."
    import httpx
    try:
        async with httpx.AsyncClient(timeout=_DELAI_TELECHARGEMENT,
                                     follow_redirects=True) as client:
            r = await client.get(uri, headers={'x-goog-api-key': cle})
    except Exception as e:
        return b'', f"Téléchargement impossible : {e}"
    if r.status_code >= 400:
        return b'', f"Téléchargement refusé ({r.status_code})."
    if not r.content:
        return b'', "Le fichier reçu est vide."
    return r.content, ''
