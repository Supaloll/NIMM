# -*- coding: utf-8 -*-
"""Génération d'images avec contrôles : format, résolution, modèle.

POURQUOI CE MODULE — ET POURQUOI PAS IMAGEN
NIMM affichait « Gemini (Imagen) » mais appelait en réalité `gemini-3.1-flash-image`
(Nano Banana), sans aucun réglage : ni format, ni résolution, ni choix de modèle.
La correction évidente aurait été d'ajouter le vrai Imagen. Elle est mauvaise :
Imagen est déprécié et cesse de répondre le 17 août 2026, et Google renvoie
lui-même vers Nano Banana. Coder une API condamnée à trois semaines d'échéance,
c'est programmer une panne.

Ce module donne donc ce qu'on attendait d'Imagen — le format, la taille, le
choix du modèle — mais par l'API Interactions, là où Google fait vivre ses
nouveautés.

DEUX POINTS DE PRUDENCE
  - `store: false` : l'API Interactions CONSERVE requêtes et réponses par défaut
    (55 jours en offre payante). NIMM ne laisse rien traîner chez le prestataire,
    même choix que pour l'agent Vibe.
  - la réponse est une suite d'« étapes », chacune avec des blocs typés. On les
    parcourt TOUTES : supposer que l'image est le premier bloc, c'est perdre
    l'image dès que le modèle commente son travail.
"""

_BASE = 'https://generativelanguage.googleapis.com/v1beta/interactions'
_DELAI = 180.0

MODELES = {
    'flash': {
        'id': 'gemini-3.1-flash-image',
        'libelle': 'Nano Banana (Flash) — rapide',
        'description': ("Le modèle de tous les jours. Rapide, jusqu'à 4K, "
                        "recherche Google possible pour coller au réel."),
        # '512' et non '0.5K' : c'est la valeur que l'API Interactions accepte
        # réellement pour ce palier (02/09/2026 — erreur 400 sur
        # response_format.image_size, valeurs supportées listées par Gemini).
        'tailles': ('512', '1K', '2K', '4K'),
    },
    'pro': {
        'id': 'gemini-3-pro-image',
        'libelle': 'Nano Banana Pro — qualité',
        'description': ("Plus lent et plus cher, pensé pour un rendu "
                        "professionnel et les compositions difficiles."),
        'tailles': ('1K', '2K', '4K'),
    },
    'lite': {
        'id': 'gemini-3.1-flash-lite-image',
        'libelle': 'Nano Banana Lite — économique',
        'description': "Le moins coûteux, uniquement en 1K.",
        'tailles': ('1K',),
    },
}

# Google annonce ces rapports pour les modèles image de Gemini 3.
RATIOS = ('1:1', '3:2', '2:3', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '21:9')

# Format demandé au modèle. JPEG car l'API Interactions de Gemini a cessé de
# supporter le PNG en sortie (02/09/2026 — erreur 400 "not supported for
# response_format.mime_type"). L'extension du fichier écrit sur disque suit
# de toute façon le mime RÉEL de la réponse (extension_pour), donc ce
# changement n'exige rien d'autre en aval.
_MIME_DEMANDE = 'image/jpeg'

# Extension de fichier à employer selon le format réellement rendu — c'est le
# mime de la RÉPONSE qui fait foi, pas celui qu'on a demandé.
EXTENSIONS = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}


def extension_pour(mime):
    """Extension correspondant au format reçu, .png par défaut."""
    return EXTENSIONS.get((mime or '').split(';')[0].strip().lower(), 'png')


LIBELLES_RATIOS = {
    '1:1': 'Carré (1:1)',
    '3:2': 'Paysage photo (3:2)',
    '2:3': 'Portrait photo (2:3)',
    '3:4': 'Portrait (3:4)',
    '4:3': 'Paysage (4:3)',
    '4:5': 'Portrait réseaux (4:5)',
    '5:4': 'Paysage large (5:4)',
    '9:16': 'Vertical plein écran (9:16)',
    '16:9': 'Écran large (16:9)',
    '21:9': 'Cinémascope (21:9)',
}


def options(api_keys=None):
    """Ce qui est réglable, et si la clé est là — dit plutôt que deviné."""
    cle = ((api_keys or {}).get('gemini') or '').strip()
    return {
        'cle_presente': bool(cle),
        'note': ("Clé Gemini enregistrée : format, résolution et modèle sont réglables."
                 if cle else
                 "Aucune clé Gemini enregistrée. C'est la même clé que pour le "
                 "texte, la musique et la vidéo."),
        'modeles': [{'nom': n, 'id': m['id'], 'libelle': m['libelle'],
                     'description': m['description'], 'tailles': list(m['tailles'])}
                    for n, m in MODELES.items()],
        'ratios': [{'valeur': r, 'libelle': LIBELLES_RATIOS.get(r, r)} for r in RATIOS],
    }


def _extraire(data):
    """Rend (images, textes) depuis une réponse Interactions.

    Forme documentée : `steps[].content[]`, chaque bloc portant un `type`
    (`text` ou `image`). On accepte aussi une réponse à plat et les variantes
    de nommage : refuser une forme légitime reviendrait à jeter l'image.
    """
    images, textes = [], []

    def _bloc(b):
        if not isinstance(b, dict):
            return
        t = (b.get('type') or '').lower()
        donnees = b.get('data') or b.get('b64') or ''
        if t == 'image' or (donnees and t not in ('text',)):
            if donnees:
                images.append({'b64': donnees,
                               'mime': b.get('mime_type') or b.get('mimeType') or 'image/png'})
        elif t == 'text' and b.get('text'):
            textes.append(b['text'])

    if not isinstance(data, dict):
        return [], ''
    etapes = data.get('steps')
    if isinstance(etapes, list):
        for e in etapes:
            contenu = (e or {}).get('content') if isinstance(e, dict) else None
            if isinstance(contenu, list):
                for b in contenu:
                    _bloc(b)
            elif isinstance(contenu, dict):
                _bloc(contenu)
    # Raccourci de commodité, si l'API le rend directement
    sortie = data.get('output_image')
    if isinstance(sortie, dict) and sortie.get('data') and not images:
        images.append({'b64': sortie['data'],
                       'mime': sortie.get('mime_type') or 'image/png'})
    return images, '\n\n'.join(textes).strip()


async def generer(prompt, modele='flash', ratio='1:1', taille='1K',
                  api_keys=None, images_ref=None):
    """Génère une image. Rend un dict — jamais d'exception vers l'appelant.

    Succès : {'images': [{'b64','mime'}], 'texte', 'modele', 'ratio', 'taille', 'secondes'}
    Échec  : {'erreur': "phrase en français"}
    """
    import time as _time

    prompt = (prompt or '').strip()
    if not prompt:
        return {'erreur': "Décris l'image que tu veux : le modèle part de ta consigne."}

    conf = MODELES.get(modele) or MODELES['flash']
    cle = ((api_keys or {}).get('gemini') or '').strip()
    if not cle:
        return {'erreur': "Aucune clé Gemini enregistrée : la génération d'image "
                          "a besoin de la même clé que le texte."}

    if ratio not in RATIOS:
        ratio = '1:1'
    if taille not in conf['tailles']:
        # On corrige plutôt que de refuser, mais la réponse porte la taille RÉELLE :
        # promettre du 4K et rendre du 1K sans le dire serait pire qu'un refus.
        taille = conf['tailles'][-1]

    entree = [{'type': 'text', 'text': prompt}]
    for img in (images_ref or [])[:10]:
        donnees = (img or {}).get('b64') or ''
        if not donnees:
            continue
        if ',' in donnees[:100]:
            donnees = donnees.split(',', 1)[1]
        entree.append({'type': 'image', 'data': donnees,
                       'mime_type': (img.get('mime') or 'image/png')})

    corps = {
        'model': conf['id'],
        'input': entree,
        # RGPD : rien ne reste chez le prestataire. Même choix que l'agent Vibe.
        'store': False,
        'response_format': {
            'type': 'image',
            # Le champ 'delivery' n'est PAS envoyé : demander explicitement
            # 'inline' (ou 'uri') fait échouer l'appel depuis le 02/09/2026
            # ("Image delivery mode is not supported"), alors que la doc
            # officielle le documente encore comme valide — décalage doc/API
            # côté Google, confirmé sur leur forum développeur. Omettre le
            # champ renvoie l'image inline par défaut, ce que ce module sait
            # lire de toute façon.
            # Demandé explicitement pour que l'extension du fichier écrit sur
            # disque corresponde vraiment au contenu.
            'mime_type': _MIME_DEMANDE,
            'aspect_ratio': ratio,
            'image_size': taille,
        },
    }

    import httpx
    debut = _time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=_DELAI) as client:
            r = await client.post(_BASE, headers={'x-goog-api-key': cle,
                                                  'Content-Type': 'application/json'},
                                  json=corps)
    except httpx.TimeoutException:
        return {'erreur': "Le modèle n'a pas répondu en trois minutes. Réessaie, "
                          "ou demande une résolution plus basse."}
    except Exception as e:
        return {'erreur': f"Appel impossible : {e}"}

    if r.status_code >= 400:
        return {'erreur': f"Gemini a répondu {r.status_code} : {(r.text or '')[:400]}"}
    try:
        data = r.json()
    except Exception:
        return {'erreur': "Réponse illisible de Gemini."}

    images, texte = _extraire(data)
    if not images:
        etat = (data.get('status') or '').lower()
        return {'erreur': (f"Gemini a répondu (« {etat} ») sans image. La consigne a "
                           "peut-être été refusée : reformule-la.")
                          if etat else "Gemini a répondu, mais sans image exploitable."}

    return {
        'images': images,
        'texte': texte,
        'modele': conf['id'],
        'libelle': conf['libelle'],
        'ratio': ratio,
        'taille': taille,
        'secondes': round(_time.perf_counter() - debut, 1),
        'prompt': prompt,
    }
