# -*- coding: utf-8 -*-
"""Préparer une réunion à partir des documents reçus — le pendant amont du relevé de décisions.

Avant une commission, il faut avoir lu l'ordre du jour, le projet de texte, la
note de présentation, et savoir ce qu'on va dire. Ce module en tire, en une
fois : de quoi traite la réunion, les repères chiffrés et datés, une synthèse,
les points de vigilance et des questions à poser. Il produit un document à
diffuser et une note courte dans le carnet du fil.

Mêmes garde-fous que le relevé (voir modules/citations.py) :
  - rien n'est deviné : seul ce que disent les documents est rapporté ;
  - chaque élément porte l'extrait dont il vient, VÉRIFIÉ contre le texte réel ;
  - une question peut porter sur un SILENCE des documents (qui contrôle ? quel
    délai ?) — c'est souvent la plus utile — mais elle est alors marquée comme
    telle, au lieu d'être adossée à un extrait inventé.

Entrée : le document attaché à la conversation, des documents de la base de
connaissances nommés par l'utilisateur, ou ses propres notes. Pas d'audio.
Sortie : un fichier à diffuser + une note de carnet. Pas de rappel d'agenda.
"""

from datetime import datetime

from modules.citations import (chaine, extraire_json, formater_sources,
                               liste_de_dicts, marquer_citations, rendre_citation)

PROMPT_REUNION = (
    "Tu prépares une réunion à partir des documents reçus. La personne que tu aides "
    "y siège et doit savoir, en quelques minutes, de quoi il retourne et quoi dire.\n\n"
    "Réponds UNIQUEMENT par un objet JSON, sans une ligne avant ni après :\n"
    '{"objet": "...", "reperes": [...], "synthese": [...], "vigilance": [...], '
    '"questions": [...]}\n\n'
    "objet — une ou deux phrases : de quoi traite la réunion, d'après les documents.\n\n"
    "reperes — dates, échéances, chiffres, seuils, références de textes. Chaque entrée : "
    '{"libelle": "...", "valeur": "...", "document": "...", "citation": "..."}\n\n'
    "synthese — l'essentiel du contenu, 3 à 8 points. Chaque entrée : "
    '{"point": "...", "document": "...", "citation": "..."}\n\n'
    "vigilance — ce qui mérite attention : une obligation affaiblie, une dérogation, un "
    "délai court, un terme flou, une contradiction entre documents. Chaque entrée : "
    '{"point": "...", "raison": "...", "document": "...", "citation": "..."}\n\n'
    "questions — des questions à poser en séance, 3 à 8. Chaque entrée : "
    '{"question": "...", "raison": "...", "document": "...", "citation": "...", '
    '"silence": false}\n\n'
    "RÈGLES — elles priment sur tout le reste :\n"
    "1. Rien n'est deviné. Ne rapporte que ce que disent les documents. Si un "
    "document ne donne pas une date, ne la déduis pas d'un autre élément, même si la "
    "déduction te semble évidente.\n"
    "2. citation — le passage EXACT d'où vient l'élément, 30 mots au plus, copié mot "
    "pour mot et jamais reformulé. Il sera vérifié automatiquement contre le texte : "
    "une citation reformulée sera signalée comme non retrouvée.\n"
    "3. document — le titre du document d'où vient la citation, tel qu'il apparaît "
    "après « === Document : ».\n"
    "4. Une question peut porter sur ce que les documents NE disent PAS (qui contrôle, "
    "quel délai, quel recours). Mets alors \"silence\": true et une citation vide : "
    "n'invente jamais un extrait pour l'adosser.\n"
    "5. Pas de point de vigilance de principe : chacun s'appuie sur un passage précis.\n"
    "6. Une rubrique sans contenu reste un tableau vide [].\n"
)


def parser_preparation(brut) -> dict:
    """Structure propre, quels que soient les écarts du modèle. Jamais d'exception."""
    d = extraire_json(brut, dict) or {}

    def propres(cle, champ_principal, champs):
        sortie = []
        for e in liste_de_dicts(d.get(cle)):
            if not chaine(e.get(champ_principal)):
                continue              # une entrée sans son contenu principal ne veut rien dire
            item = {c: chaine(e.get(c)) for c in champs}
            if cle == 'questions':
                item['silence'] = bool(e.get('silence')) and not item['citation']
            sortie.append(item)
        return sortie

    return {
        'objet':     chaine(d.get('objet')),
        'reperes':   propres('reperes', 'libelle', ('libelle', 'valeur', 'document', 'citation')),
        'synthese':  propres('synthese', 'point', ('point', 'document', 'citation')),
        'vigilance': propres('vigilance', 'point', ('point', 'raison', 'document', 'citation')),
        'questions': propres('questions', 'question',
                             ('question', 'raison', 'document', 'citation')),
    }


def verifier(prep: dict, sources: list) -> int:
    """Marque chaque citation vérifiée ou non ; rend le nombre de non retrouvées."""
    textes = [s['texte'] for s in sources]
    return sum(marquer_citations(prep[k], textes)
               for k in ('reperes', 'synthese', 'vigilance', 'questions'))


async def preparer(sources: list, settings: dict, contexte: str = '') -> tuple:
    """Rend (préparation, erreur). N'échoue jamais silencieusement."""
    from core.engine import call_llm
    if not sources:
        return parser_preparation(None), 'Aucun document à préparer.'
    message = formater_sources(sources)
    if contexte:
        message = ('Ce que la personne attend de cette réunion (à prendre en compte '
                   'pour choisir les points de vigilance et les questions, jamais comme '
                   'une source) : ' + contexte + chr(10) * 2 + message)
    try:
        reponse = await call_llm(
            messages=[{'role': 'user', 'content': message}],
            provider=settings.get('provider', ''),
            model=settings.get('model'),
            system_prompt=PROMPT_REUNION,
            max_tokens=6000,
            temperature=0.0,
            api_keys=settings.get('api_keys', {}),
        )
    except Exception as e:
        return parser_preparation(None), 'La préparation a échoué : %s' % e
    prep = parser_preparation(reponse)
    verifier(prep, sources)
    return prep, ''


def _total(prep: dict) -> int:
    return sum(len(prep[k]) for k in ('reperes', 'synthese', 'vigilance', 'questions'))


def rendre_markdown(titre: str, prep: dict, sources: list, avertissements=None) -> str:
    """Le document à diffuser. Markdown : file_writer en fait un docx à vrais titres."""
    L = ['# Préparation de réunion — %s' % titre, '']
    L.append('Établie le %s à partir de : %s.' % (
        datetime.now().strftime('%d/%m/%Y'),
        ' ; '.join(s['titre'] for s in sources) or 'aucun document'))
    L.append('')
    L.append('%d point(s) de synthèse, %d point(s) de vigilance, %d question(s), '
             '%d repère(s).' % (len(prep['synthese']), len(prep['vigilance']),
                                len(prep['questions']), len(prep['reperes'])))
    for a in (avertissements or []):
        L += ['', 'Avertissement : ' + a]
    non_verif = sum(1 for k in ('reperes', 'synthese', 'vigilance', 'questions')
                    for e in prep[k] if e.get('citation') and not e.get('verifiee', True))
    L += ['', "Chaque élément est suivi de l'extrait dont il provient. Les extraits ont "
          "été comparés automatiquement aux documents : rien n'a été deviné, et un "
          "extrait introuvable est signalé comme tel."]
    if non_verif:
        L += ['', 'Attention : %d extrait(s) non retrouvé(s) dans les documents, à '
              'vérifier avant de les reprendre.' % non_verif]

    if prep['objet']:
        L += ['', '## Objet de la réunion', '', prep['objet']]

    if prep['reperes']:
        # Ce qui a des colonnes va dans un tableau balisé ; les extraits viennent après.
        L += ['', '## Repères', '', '| Repère | Valeur | Document |', '|---|---|---|']
        for r in prep['reperes']:
            L.append('| %s | %s | %s |' % tuple(
                (r[c] or 'non précisé').replace('|', '/') for c in ('libelle', 'valeur', 'document')))

    if prep['synthese']:
        L += ['', '## Synthèse']
        for e in prep['synthese']:
            L += ['', '### ' + e['point'], rendre_citation(e)]

    if prep['vigilance']:
        L += ['', '## Points de vigilance']
        for e in prep['vigilance']:
            L += ['', '### ' + e['point']]
            if e['raison']:
                L.append('Pourquoi : ' + e['raison'])
            L.append(rendre_citation(e))

    if prep['questions']:
        L += ['', '## Questions à poser']
        for e in prep['questions']:
            L += ['', '### ' + e['question']]
            if e['raison']:
                L.append('Pourquoi : ' + e['raison'])
            if e.get('silence'):
                L.append("Cette question porte sur un point que les documents ne "
                         "traitent pas : aucun extrait ne s'y rapporte.")
            else:
                L.append(rendre_citation(e))

    if [e for e in prep['reperes'] if e.get('citation')]:
        L += ['', '## Extraits des repères']
        for e in prep['reperes']:
            if e.get('citation'):
                L += ['', '### ' + e['libelle'], rendre_citation(e)]

    if not _total(prep):
        L += ['', "Aucun élément n'a pu être tiré de ces documents."]
    return chr(10).join(L) + chr(10)


def rendre_note_carnet(titre: str, prep: dict) -> str:
    """La note qui reste attachée au fil : courte, sinon elle ne sera pas relue."""
    if not _total(prep):
        return 'Préparation de réunion (%s) : aucun élément tiré des documents.' % titre
    debut = ('Préparation de réunion (%s) : %d point(s) de vigilance, %d question(s).'
             % (titre, len(prep['vigilance']), len(prep['questions'])))
    qs = [e['question'] for e in prep['questions'][:3]]
    if not qs:
        return debut
    reste = len(prep['questions']) - len(qs)
    fin = ' ; '.join(qs) + (' (+%d)' % reste if reste > 0 else '')
    return debut + ' Questions : ' + fin + ('' if fin.endswith(('?', '!', '.')) else '.')
