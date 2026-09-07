# -*- coding: utf-8 -*-
"""Relevé de décisions — transformer un compte rendu en liste exploitable.

Après chaque réunion, retrouver qui fait quoi et pour quand demande de relire
tout le compte rendu. Ce module le fait une fois : il produit un document à
diffuser et une note courte pour le carnet du fil.

LE RISQUE, ET LA RÉPONSE
Relever des décisions, c'est INTERPRÉTER — et sur des notes prises à la volée,
c'est reconstituer. Une décision attribuée au mauvais responsable est pire que
pas de décision du tout : elle sera relayée, et personne n'ira vérifier. D'où
trois garde-fous, qui sont l'essentiel de ce module :

  1. Rien n'est deviné. Un responsable absent reste « non précisé ». Le modèle
     a l'instruction explicite de ne jamais attribuer par déduction.
  2. Chaque relevé porte la CITATION du passage dont il vient, copiée mot pour
     mot. C'est ce qui rend le document vérifiable sans rouvrir la source.
  3. Décisions, actions et simples informations sont distinguées : un compte
     rendu mélange les trois, et on ne les traite pas de la même façon.

PRÉSENTATION : un tableau récapitulatif, puis le détail.

Le tableau porte ce qui a des colonnes — intitulé, type, responsable, échéance —
et il est correctement balisé : ligne d'en-tête marquée, en-tête de colonne et
en-tête de ligne. Ainsi structuré, un lecteur d'écran annonce l'intitulé de la
colonne à chaque cellule, et le tableau est le bon outil, aussi bien à l'œil
qu'en braille. (Le support des tableaux a dû être ajouté à `file_writer` pour
cela : ni le HTML ni le DOCX ne les produisaient.)

Les citations, elles, viennent après, en liste. Non par principe, mais parce
qu'un extrait de trente mots dans une cellule déforme le tableau sans rien
gagner.
"""

import json
import re
from datetime import datetime

_MAX_TEXTE = 30000        # au-delà, on prévient plutôt que de tronquer en silence

PROMPT_RELEVE = (
    "Tu relèves les décisions et les actions d'un compte rendu de réunion, ou de "
    "notes prises pendant une séance.\n\n"
    "Réponds UNIQUEMENT par un tableau JSON, sans une ligne avant ni après. "
    "Chaque entrée porte exactement ces cinq champs :\n"
    '{"type": "...", "intitule": "...", "responsable": "...", "echeance": "...", '
    '"citation": "..."}\n\n'
    "type — l'un de ces trois mots exactement :\n"
    "  decision    ce qui a été acté, tranché, voté\n"
    "  action      ce que quelqu'un doit faire\n"
    "  information ce qui a été dit sans engager personne\n\n"
    "intitule — une phrase. À l'infinitif pour une action.\n\n"
    "responsable — le nom ou la fonction TELS QU'ILS APPARAISSENT dans le texte. "
    "Si personne n'est nommé, écris exactement : non précisé\n"
    "N'ATTRIBUE JAMAIS par déduction. Si le texte dit « il faudra relancer la "
    "commission » sans dire qui, le responsable est « non précisé » — même si le "
    "contexte te semble évident.\n\n"
    "echeance — la date ou le délai TELS QU'ILS APPARAISSENT. Si rien n'est dit, "
    "écris exactement : non précisée\n\n"
    "citation — le passage EXACT du texte d'où vient ce relevé, 30 mots au plus, "
    "copié mot pour mot et jamais reformulé. C'est ce qui permettra de vérifier "
    "ton relevé sans relire la source.\n\n"
    "Ne relève que ce qui est dans le texte. Si le texte ne contient aucune "
    "décision ni action, réponds par un tableau vide : []\n"
)


def parser_releve(brut: str) -> list:
    """Extrait le tableau JSON d'une réponse de modèle, avec indulgence.

    Les fournisseurs encadrent volontiers le JSON de ``` ou d'une phrase
    d'introduction, malgré la consigne. On cherche donc le premier tableau
    plutôt que d'exiger une réponse parfaite — et si rien n'est exploitable,
    on rend une liste vide au lieu de lever : un relevé raté ne doit pas
    casser la conversation.
    """
    if not brut:
        return []
    texte = brut.strip()
    if '```' in texte:
        blocs = re.findall(r'```(?:json)?\s*(.*?)```', texte, re.S)
        if blocs:
            texte = blocs[0].strip()
    debut, fin = texte.find('['), texte.rfind(']')
    if debut == -1 or fin == -1 or fin < debut:
        return []
    try:
        brut_liste = json.loads(texte[debut:fin + 1])
    except Exception:
        return []
    if not isinstance(brut_liste, list):
        return []

    propres = []
    for e in brut_liste:
        if not isinstance(e, dict):
            continue
        intitule = str(e.get('intitule') or '').strip()
        if not intitule:
            continue          # une entrée sans intitulé ne veut rien dire
        t = str(e.get('type') or '').strip().lower()
        if t not in ('decision', 'action', 'information'):
            t = 'information'
        propres.append({
            'type':        t,
            'intitule':    intitule,
            'responsable': str(e.get('responsable') or '').strip() or 'non précisé',
            'echeance':    str(e.get('echeance') or '').strip() or 'non précisée',
            'citation':    str(e.get('citation') or '').strip(),
        })
    return propres


async def relever(texte: str, settings: dict, contexte: str = '') -> tuple:
    """Rend (relevés, avertissement). N'échoue jamais silencieusement."""
    from core.engine import call_llm
    texte = (texte or '').strip()
    if not texte:
        return [], 'Aucun texte à dépouiller.'

    avertissement = ''
    if len(texte) > _MAX_TEXTE:
        # Tronquer sans le dire donnerait un relevé incomplet qu'on croirait
        # complet — le pire des deux mondes.
        texte = texte[:_MAX_TEXTE]
        avertissement = ("Le texte dépassait %d caractères : seul le début a été "
                         "dépouillé. Le relevé est donc incomplet."
                         % _MAX_TEXTE)

    message = ((contexte + chr(10) + chr(10)) if contexte else '') + texte
    try:
        reponse = await call_llm(
            messages=[{'role': 'user', 'content': message}],
            provider=settings.get('provider', ''),
            model=settings.get('model'),
            system_prompt=PROMPT_RELEVE,
            max_tokens=4000,
            temperature=0.0,          # un relevé n'a pas à être créatif
            api_keys=settings.get('api_keys', {}),
        )
    except Exception as e:
        return [], 'Le relevé a échoué : %s' % e
    return parser_releve(reponse), avertissement


_TITRES = {
    'decision':    'Décisions',
    'action':      'Actions à mener',
    'information': "Points d'information",
}


def rendre_markdown(titre: str, releves: list, source: str = '',
                    avertissement: str = '') -> str:
    """Le document à diffuser. Markdown : file_writer en fait un docx à vrais titres."""
    n = {k: sum(1 for r in releves if r['type'] == k) for k in _TITRES}
    lignes = ['# Relevé de décisions — %s' % titre, '']
    lignes.append('Établi le %s%s.' % (datetime.now().strftime('%d/%m/%Y'),
                                       (' à partir de %s' % source) if source else ''))
    lignes.append('')
    lignes.append('%d élément(s) relevé(s) : %d décision(s), %d action(s), '
                  '%d point(s) d\'information.'
                  % (len(releves), n['decision'], n['action'], n['information']))
    if avertissement:
        lignes += ['', 'Avertissement : ' + avertissement]
    lignes.append('')
    lignes.append("Chaque relevé est suivi de l'extrait dont il provient, pour "
                  "être vérifié sans rouvrir le compte rendu. « Non précisé » "
                  "signifie que le texte ne le disait pas : rien n'a été deviné.")

    # Le tableau récapitulatif : l'intitulé en première colonne, car c'est lui
    # qui identifie la ligne — c'est cette colonne que file_writer marque comme
    # en-tête de ligne.
    if releves:
        lignes += ['', '## Récapitulatif', '']
        lignes.append('| Intitulé | Nature | Responsable | Échéance |')
        lignes.append('|---|---|---|---|')
        for r in releves:
            nature = {'decision': 'Décision', 'action': 'Action',
                      'information': 'Information'}[r['type']]
            resp = '—' if r['type'] == 'information' else r['responsable']
            ech = '—' if r['type'] == 'information' else r['echeance']
            lignes.append('| %s | %s | %s | %s |' % (
                r['intitule'].replace('|', '/'), nature,
                resp.replace('|', '/'), ech.replace('|', '/')))

    # Puis les extraits, qui n'ont pas leur place dans une cellule.
    avec_citation = [r for r in releves if r['citation']]
    if avec_citation:
        lignes += ['', '## Extraits justificatifs']
        for r in avec_citation:
            lignes += ['', '### ' + r['intitule'], '« %s »' % r['citation']]

    if not releves:
        lignes += ['', "Aucune décision ni action n'a été relevée dans ce texte."]
    return chr(10).join(lignes) + chr(10)


def rendre_note_carnet(titre: str, releves: list) -> str:
    """La note qui reste attachée au fil : courte, sinon elle ne sera pas relue."""
    if not releves:
        return 'Relevé de décisions (%s) : aucune décision ni action relevée.' % titre
    n_d = sum(1 for r in releves if r['type'] == 'decision')
    actions = [r for r in releves if r['type'] == 'action']
    debut = ('Relevé de décisions (%s) : %d décision(s), %d action(s).'
             % (titre, n_d, len(actions)))
    if not actions:
        return debut
    suite = []
    for r in actions[:3]:
        qui = r['responsable']
        quand = r['echeance']
        suite.append('%s — %s%s' % (
            r['intitule'], qui,
            ('' if quand.startswith('non précis') else ', %s' % quand)))
    reste = (' (+%d autre(s))' % (len(actions) - 3)) if len(actions) > 3 else ''
    return debut + ' À faire : ' + ' ; '.join(suite) + reste + '.'
