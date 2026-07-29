# -*- coding: utf-8 -*-
"""Catalogue des services externes de NIMM — source unique de vérité.

POURQUOI CE FICHIER EXISTE
La liste des fournisseurs était écrite EN DUR à trois endroits du frontend :
le formulaire des clés, la grille des clés globales et la fonction
d'enregistrement. Résultat, en branchant Exa, Cohere, Voyage et Jina, leurs
clés n'avaient nulle part où être saisies — les fonctions étaient là, mais
inatteignables.

Désormais tout part d'ici : ajouter un service, c'est ajouter une ligne. Le
formulaire, la grille, l'enregistrement et la visibilité `data-needs-key`
s'alignent d'eux-mêmes.

CONVENTION
`id` sert à la fois de clé dans le magasin des clés d'API, de suffixe
d'identifiant HTML (les tirets bas deviennent des traits d'union) et de valeur
`data-needs-key`. Ne pas le changer sans migrer les réglages existants.
"""

# famille : sert à regrouper le formulaire, et à l'annoncer au lecteur d'écran
FAMILLES = [
    ('conversation', 'Modèles de conversation'),
    ('recherche', 'Recherche et veille'),
    ('pertinence', 'Pertinence de la base de connaissances'),
    ('creation', 'Image, son et vidéo'),
]

SERVICES = [
    # ── modèles de conversation ──
    {'id': 'anthropic', 'nom': 'Anthropic (Claude)', 'famille': 'conversation',
     'exemple': 'sk-ant-…', 'console': 'https://console.anthropic.com/',
     'role': "Conversation, vérification des faits, lecture visuelle de PDF, "
             "serveurs MCP, traitement par lots."},
    {'id': 'mistral', 'nom': 'Mistral', 'famille': 'conversation',
     'exemple': '…', 'console': 'https://console.mistral.ai/',
     'role': "Conversation, agent Vibe, reconnaissance de texte (OCR), voix, "
             "traitement par lots."},
    {'id': 'gemini', 'nom': 'Google Gemini', 'famille': 'conversation',
     'exemple': 'AIza…', 'console': 'https://aistudio.google.com/apikey',
     'role': "Conversation, description de vidéo et de son, documents épinglés, "
             "traitement par lots. Cette clé ouvre aussi la musique (Lyria), "
             "l'image (Nano Banana, réglable) et la vidéo (Veo)."},
    {'id': 'openai', 'nom': 'OpenAI', 'famille': 'conversation',
     'exemple': 'sk-…', 'console': 'https://platform.openai.com/api-keys',
     'role': "Conversation, modèles de raisonnement de la série o."},
    {'id': 'deepseek', 'nom': 'DeepSeek', 'famille': 'conversation',
     'exemple': 'sk-…', 'console': 'https://platform.deepseek.com/',
     'role': "Conversation économique, modèle de raisonnement à pensée visible."},
    {'id': 'openrouter', 'nom': 'OpenRouter', 'famille': 'conversation',
     'exemple': 'sk-or-…', 'console': 'https://openrouter.ai/keys',
     'role': "Passerelle vers des centaines de modèles (Qwen, Kimi, GLM, MiniMax…) "
             "avec une seule clé."},

    # ── recherche et veille ──
    {'id': 'brave', 'nom': 'Brave Search', 'famille': 'recherche',
     'exemple': 'BSA…', 'console': 'https://brave.com/search/api/',
     'role': "Recherche web par mots-clés."},
    {'id': 'tavily', 'nom': 'Tavily', 'famille': 'recherche',
     'exemple': 'tvly-…', 'console': 'https://app.tavily.com/',
     'role': "Recherche web pensée pour les agents, avec extraits."},
    {'id': 'exa', 'nom': 'Exa', 'famille': 'recherche',
     'exemple': '…', 'console': 'https://dashboard.exa.ai/',
     'role': "Recherche par le SENS plutôt que par mots-clés, et veille "
             "automatique sur des sujets suivis. Sait aussi lire une page web "
             "proprement pour la verser dans ta base."},

    # ── pertinence ──
    {'id': 'cohere', 'nom': 'Cohere', 'famille': 'pertinence',
     'exemple': '…', 'console': 'https://dashboard.cohere.com/api-keys',
     'role': "Réordonnancement des passages de ta base de connaissances."},
    {'id': 'voyage', 'nom': 'Voyage AI', 'famille': 'pertinence',
     'exemple': 'pa-…', 'console': 'https://dashboard.voyageai.com/',
     'role': "Réordonnancement, bon en multilingue."},
    {'id': 'jina', 'nom': 'Jina', 'famille': 'pertinence',
     'exemple': 'jina_…', 'console': 'https://jina.ai/api-dashboard/',
     'role': "Réordonnancement multilingue."},

    # ── création ──
    {'id': 'stability_ai', 'nom': 'Stability AI', 'famille': 'creation',
     'exemple': 'sk-…', 'console': 'https://platform.stability.ai/account/keys',
     'role': "Génération d'images."},
]

_PAR_ID = {s['id']: s for s in SERVICES}


def service(service_id):
    return _PAR_ID.get(service_id, {})


def ids():
    return [s['id'] for s in SERVICES]


def html_id(service_id):
    """`stability_ai` → `stability-ai` : les identifiants HTML n'aiment pas les
    tirets bas dans cette base de code, et la convention est déjà en place."""
    return (service_id or '').replace('_', '-')


def catalogue(cles=None):
    """Catalogue enrichi de l'état de configuration, SANS jamais rendre les clés.

    Le frontend n'a aucun besoin de connaître les secrets pour afficher un
    formulaire : il lui suffit de savoir si la case est remplie.
    """
    cles = cles or {}
    sortie = []
    for s in SERVICES:
        d = dict(s)
        d['html_id'] = html_id(s['id'])
        d['configure'] = bool((cles.get(s['id']) or '').strip())
        sortie.append(d)
    return sortie


def par_famille(cles=None):
    """Catalogue regroupé, dans l'ordre déclaré des familles."""
    plein = catalogue(cles)
    groupes = []
    for cle_famille, libelle in FAMILLES:
        membres = [s for s in plein if s['famille'] == cle_famille]
        if membres:
            groupes.append({'famille': cle_famille, 'libelle': libelle,
                            'services': membres})
    # Un service dont la famille serait mal orthographiée ne doit pas disparaître
    connues = {f for f, _ in FAMILLES}
    orphelins = [s for s in plein if s['famille'] not in connues]
    if orphelins:
        groupes.append({'famille': 'autres', 'libelle': 'Autres services',
                        'services': orphelins})
    return groupes
