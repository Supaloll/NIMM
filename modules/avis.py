# -*- coding: utf-8 -*-
"""Aider à rédiger un avis — structurer un projet, ou relire un brouillon sur le fond.

Deux usages, une même règle : NIMM ne prend JAMAIS position à la place de
l'auteur.

STRUCTURER — à partir du texte examiné (document de la conversation, documents
de la base) et des NOTES de l'auteur, NIMM monte un projet d'avis selon la trame
attendue (data/prompts/avis_trame.txt, modifiable). La saisine et la
présentation viennent du texte examiné ; les observations, les demandes et le
sens de l'avis viennent UNIQUEMENT des notes. Ce que les notes ne disent pas
reste « [À compléter] » : un projet d'avis qui invente une position est pire
qu'un projet incomplet, parce qu'il sera relu en diagonale et signé.

RELIRE — sur un brouillon d'avis, NIMM fait une relecture critique de
l'ARGUMENTATION, pas de l'orthographe : affirmation non étayée, contradiction,
demande imprécise, incohérence entre les observations et le sens de l'avis,
disposition du texte examiné qui n'est pas traitée. Chaque remarque cite le
passage du brouillon qu'elle vise, vérifié mot pour mot.

Les articles du texte examiné que le projet ou le brouillon ne commente pas
sont relevés par le CODE, pas par le modèle : c'est un décompte, il doit être
exact.

Registre : institutionnel. « Le CNCPH demande », « recommande », « souhaite » —
jamais « exige » ; pas de vocabulaire de négociation ; « a minima ».
"""

import os
import re
from datetime import datetime

from modules.citations import (MENTION_NON_VERIFIEE, chaine, citation_verifiee,
                               extraire_json, formater_sources, liste_de_dicts)

SENS_ADMIS = ('favorable', 'favorable avec réserves', 'défavorable')
A_COMPLETER = '[À compléter]'

_TRAME_DEFAUT = [
    ('saisine', 'Saisine', "Le texte examiné, l'administration qui saisit, la date de saisine."),
    ('presentation', 'Présentation du texte', 'Ce que le texte prévoit, en quelques points.'),
    ('observations_generales', 'Observations générales', "Appréciations d'ensemble, tirées des notes."),
    ('observations_articles', 'Observations article par article', "Pour chaque article commenté dans les notes."),
    ('demandes', 'Demandes de modification', 'Modifications demandées, tirées des notes.'),
    ('avis', 'Avis', "Sens de l'avis et motif, tels que les notes les donnent."),
]
_FICHIER_TRAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                              'data', 'prompts', 'avis_trame.txt')


def charger_trame(chemin: str = _FICHIER_TRAME) -> list:
    """Trame (identifiant, titre, consigne). Fichier absent ou illisible → trame par défaut.

    Un identifiant inconnu est ignoré, un identifiant manquant est rajouté à la
    fin : une trame mal éditée ne doit pas faire disparaître la rubrique « Avis ».
    """
    connus = {i for i, _, _ in _TRAME_DEFAUT}
    lue = []
    try:
        with open(chemin, encoding='utf-8') as f:
            for ligne in f:
                ligne = ligne.strip()
                if not ligne or ligne.startswith('#') or ligne.count('|') < 2:
                    continue
                ident, titre, consigne = [p.strip() for p in ligne.split('|', 2)]
                if ident in connus and ident not in {x[0] for x in lue}:
                    lue.append((ident, titre or ident, consigne))
    except Exception:
        return list(_TRAME_DEFAUT)
    for t in _TRAME_DEFAUT:
        if t[0] not in {x[0] for x in lue}:
            lue.append(t)
    return lue


# ── Articles : un décompte, donc du code ──────────────────────────────────

_NUM = (r'((?:[LRDA]\.?\s*)?(?:\d+(?:[-–.]\d+)*|premier|1er|unique)'
        r'(?:\s+(?:bis|ter|quater|quinquies))?)\b')
_RE_ARTICLE_TETE = re.compile(r'^\s*(?:Article|ARTICLE|Art\.)\s+' + _NUM, re.M)
_RE_ARTICLE_MENTION = re.compile(r'\b(?:articles?|art\.)\s+' + _NUM, re.I)


def _norm_article(a: str) -> str:
    a = re.sub(r'\s+', ' ', a.strip().lower()).replace('–', '-')
    a = re.sub(r'^([lrda])\.?\s*', r'\1', a)
    return {'premier': '1', '1er': '1'}.get(a, a)


def articles_du_texte(texte: str) -> list:
    """Articles qui ouvrent une ligne du texte examiné, dans l'ordre, sans doublon."""
    vus, sortie = set(), []
    for m in _RE_ARTICLE_TETE.finditer(texte or ''):
        n = _norm_article(m.group(1))
        if n not in vus:
            vus.add(n)
            sortie.append(m.group(1).strip())
    return sortie


def articles_mentionnes(texte: str) -> set:
    return {_norm_article(m.group(1)) for m in _RE_ARTICLE_MENTION.finditer(texte or '')}


def articles_non_commentes(texte_examine: str, commentaire: str) -> list:
    mention = articles_mentionnes(commentaire)
    return [a for a in articles_du_texte(texte_examine) if _norm_article(a) not in mention]


def _intitule_article(a: str) -> str:
    a = (a or '').strip()
    if not a:
        return 'Article non précisé'
    return a if a.lower().startswith('art') else 'Article ' + a


# ── STRUCTURER ────────────────────────────────────────────────────────────

def prompt_structurer(trame=None) -> str:
    trame = trame or charger_trame()
    rubriques = chr(10).join('  - %s (%s) : %s' % (t, i, c) for i, t, c in trame)
    return (
        "Tu aides à rédiger un projet d'avis d'une instance consultative sur un texte "
        "réglementaire. Tu reçois le TEXTE EXAMINÉ (un ou plusieurs documents) et les "
        "NOTES de l'auteur de l'avis.\n\n"
        "Trame attendue :\n" + rubriques + "\n\n"
        "Réponds UNIQUEMENT par un objet JSON, sans une ligne avant ni après :\n"
        '{"saisine": {"texte_examine": "...", "auteur": "...", "date": "...", "citation": "..."},\n'
        ' "presentation": [{"point": "...", "citation": "..."}],\n'
        ' "observations_generales": [{"observation": "...", "appui_notes": "..."}],\n'
        ' "observations_articles": [{"article": "...", "observation": "...", '
        '"appui_notes": "...", "citation": "..."}],\n'
        ' "demandes": [{"demande": "...", "article": "...", "appui_notes": "..."}],\n'
        ' "avis": {"sens": "...", "motif": "...", "appui_notes": "..."}}\n\n'
        "RÈGLES — elles priment sur tout le reste :\n"
        "1. Tu ne prends JAMAIS position à la place de l'auteur. Les observations, les "
        "demandes et le sens de l'avis viennent UNIQUEMENT de ses notes. Même si une "
        "critique du texte te paraît évidente, si elle n'est pas dans les notes, tu ne "
        "l'écris pas.\n"
        "2. appui_notes — le passage EXACT des notes d'où vient l'élément, copié mot "
        "pour mot et jamais reformulé. Il sera vérifié automatiquement.\n"
        "3. citation — le passage EXACT du texte examiné (article, alinéa), 30 mots au "
        "plus, copié mot pour mot. Il sera vérifié automatiquement.\n"
        "4. saisine : uniquement ce que disent les documents. Ce qui manque reste vide.\n"
        "5. avis.sens : exactement « favorable », « favorable avec réserves » ou "
        "« défavorable », SEULEMENT si les notes le disent ; sinon une chaîne vide.\n"
        "6. Registre institutionnel et sobre : « le CNCPH demande », « recommande », "
        "« souhaite » — jamais « exige » ; pas de vocabulaire de négociation ; "
        "« a minima » plutôt que « au minimum ». Phrases complètes, prêtes à être "
        "reprises dans l'avis.\n"
        "7. Une rubrique sans contenu reste vide : [] ou \"\".\n"
    )


def parser_structure(brut) -> dict:
    """Structure propre, quels que soient les écarts du modèle. Jamais d'exception."""
    d = extraire_json(brut, dict) or {}
    s = d.get('saisine') if isinstance(d.get('saisine'), dict) else {}
    a = d.get('avis') if isinstance(d.get('avis'), dict) else {}

    def propres(cle, principal, champs):
        return [{c: chaine(e.get(c)) for c in champs}
                for e in liste_de_dicts(d.get(cle)) if chaine(e.get(principal))]

    sens = chaine(a.get('sens')).lower()
    return {
        'saisine': {c: chaine(s.get(c)) for c in ('texte_examine', 'auteur', 'date', 'citation')},
        'presentation': propres('presentation', 'point', ('point', 'citation')),
        'observations_generales': propres('observations_generales', 'observation',
                                          ('observation', 'appui_notes')),
        'observations_articles': propres('observations_articles', 'observation',
                                         ('article', 'observation', 'appui_notes', 'citation')),
        'demandes': propres('demandes', 'demande', ('demande', 'article', 'appui_notes')),
        # Un sens hors liste n'est pas « corrigé » : il est écarté, l'avis reste à compléter.
        'avis': {'sens': sens if sens in SENS_ADMIS else '',
                 'motif': chaine(a.get('motif')), 'appui_notes': chaine(a.get('appui_notes'))},
    }


def verifier_structure(st: dict, textes_examines: list, notes: str) -> int:
    """Marque chaque appui ; rend le nombre de passages non retrouvés."""
    n = 0

    def marque(e, champ, textes, cle):
        nonlocal n
        v = e.get(champ, '')
        e[cle] = bool(v) and citation_verifiee(v, textes)
        if v and not e[cle]:
            n += 1

    if st['saisine'].get('citation'):
        marque(st['saisine'], 'citation', textes_examines, 'citation_ok')
    for e in st['presentation']:
        marque(e, 'citation', textes_examines, 'citation_ok')
    for cle in ('observations_generales', 'observations_articles', 'demandes'):
        for e in st[cle]:
            marque(e, 'appui_notes', [notes], 'notes_ok')
            if e.get('citation'):
                marque(e, 'citation', textes_examines, 'citation_ok')
    marque(st['avis'], 'appui_notes', [notes], 'notes_ok')
    return n


async def structurer(sources: list, notes: str, settings: dict) -> tuple:
    """Rend (structure, erreur). N'échoue jamais silencieusement."""
    from core.engine import call_llm
    message = ('TEXTE EXAMINÉ' + chr(10) + (formater_sources(sources) or '(non fourni)')
               + chr(10) * 2 + "NOTES DE L'AUTEUR" + chr(10)
               + ((notes or '').strip() or '(aucune note fournie)'))
    try:
        reponse = await call_llm(
            messages=[{'role': 'user', 'content': message}],
            provider=settings.get('provider', ''), model=settings.get('model'),
            system_prompt=prompt_structurer(), max_tokens=8000, temperature=0.0,
            api_keys=settings.get('api_keys', {}))
    except Exception as e:
        return parser_structure(None), "La structuration de l'avis a échoué : %s" % e
    st = parser_structure(reponse)
    verifier_structure(st, [s['texte'] for s in sources], notes or '')
    return st, ''


def _appui(e, champ, ok, etiquette):
    v = e.get(champ)
    if not v:
        return None
    ligne = '%s : « %s »' % (etiquette, v)
    if not e.get(ok, True):
        ligne += ' — ' + MENTION_NON_VERIFIEE + '.'
    return ligne


POSITION_NON_RETROUVEE = '[Position non retrouvée dans vos notes — à vérifier ou à retirer]'


def _pos(texte: str, e: dict) -> str:
    """Une position que les notes ne portent pas est signalée DANS le corps de l'avis.

    L'annexe ne suffit pas : c'est le corps qu'on relit et qu'on signe. Une
    position inventée par le modèle doit sauter aux yeux là où elle est écrite.
    """
    return texte if e.get('notes_ok') else texte + ' ' + POSITION_NON_RETROUVEE


def _court(t: str, n: int = 120) -> str:
    return t if len(t) <= n else t[:n - 1] + '…'


def rendre_projet(titre: str, st: dict, sources: list, notes: str,
                  avertissements=None, trame=None) -> str:
    """Le projet d'avis : propre et reprenable, les appuis en annexe."""
    trame = trame or charger_trame()
    L = ["# Projet d'avis — %s" % titre, '']
    L.append("Projet établi par NIMM le %s à partir de : %s%s." % (
        datetime.now().strftime('%d/%m/%Y'),
        ' ; '.join(s['titre'] for s in sources) or 'aucun texte examiné',
        ", et des notes de l'auteur" if (notes or '').strip() else ''))
    L.append('')
    L.append("Les positions exprimées viennent uniquement des notes de l'auteur : NIMM "
             "n'en a ajouté aucune. Ce que les notes ne disaient pas est marqué « %s ». "
             "L'annexe donne, pour chaque élément, le passage dont il provient." % A_COMPLETER)
    for a in (avertissements or []):
        L += ['', 'Avertissement : ' + a]
    if not (notes or '').strip():
        L += ['', "Aucune note n'a été fournie : seules la saisine et la présentation "
              "du texte ont pu être rédigées."]

    for ident, titre_r, _ in trame:
        L += ['', '## ' + titre_r, '']
        if ident == 'saisine':
            s = st['saisine']
            L.append('Texte examiné : %s.' % (s['texte_examine'] or A_COMPLETER))
            L.append("Administration à l'origine de la saisine : %s." % (s['auteur'] or A_COMPLETER))
            L.append('Date de saisine : %s.' % (s['date'] or A_COMPLETER))
        elif ident == 'presentation':
            L += [e['point'] for e in st['presentation']] or [A_COMPLETER]
        elif ident == 'observations_generales':
            L += [_pos(e['observation'], e) for e in st['observations_generales']] or [A_COMPLETER]
        elif ident == 'observations_articles':
            if not st['observations_articles']:
                L.append(A_COMPLETER)
            for e in st['observations_articles']:
                L += ['### ' + _intitule_article(e['article']), _pos(e['observation'], e), '']
        elif ident == 'demandes':
            if not st['demandes']:
                L.append(A_COMPLETER)
            for i, e in enumerate(st['demandes'], 1):
                L.append('%d. %s' % (i, _pos(e['demande'] + ((' (%s)' % e['article'])
                                                          if e['article'] else ''), e)))
        elif ident == 'avis':
            a = st['avis']
            L.append(_pos('Le CNCPH émet un avis %s.' % a['sens'], a) if a['sens']
                     else "Sens de l'avis : %s (les notes ne le précisent pas)." % A_COMPLETER)
            if a['motif']:
                L.append(a['motif'])

    # Annexe : la traçabilité, hors du corps de l'avis pour qu'il reste reprenable.
    L += ['', '## Annexe — origine de chaque élément']
    blocs = []
    for e in st['presentation']:
        blocs.append((e['point'], [_appui(e, 'citation', 'citation_ok', 'Texte examiné')]))
    for e in st['observations_generales']:
        blocs.append((e['observation'], [_appui(e, 'appui_notes', 'notes_ok', 'Notes')]))
    for e in st['observations_articles']:
        blocs.append((e['observation'], [_appui(e, 'appui_notes', 'notes_ok', 'Notes'),
                                         _appui(e, 'citation', 'citation_ok', 'Texte examiné')]))
    for e in st['demandes']:
        blocs.append((e['demande'], [_appui(e, 'appui_notes', 'notes_ok', 'Notes')]))
    if st['avis']['sens']:
        blocs.append(("Sens de l'avis : " + st['avis']['sens'],
                      [_appui(st['avis'], 'appui_notes', 'notes_ok', 'Notes')]))
    for intitule, appuis in blocs:
        appuis = [a for a in appuis if a]
        L += ['', '### ' + _court(intitule)]
        L += appuis or ["Aucun passage d'origine indiqué — " + MENTION_NON_VERIFIEE + '.']
    if not blocs:
        L += ['', 'Aucun élément à justifier.']

    restants = articles_non_commentes(
        chr(10).join(s['texte'] for s in sources),
        chr(10).join(_intitule_article(e['article']) + ' ' + e['observation']
                     for e in st['observations_articles']))
    if restants:
        L += ['', '## Articles du texte sans observation', '',
              "Relevé automatique, à titre de contrôle : ces articles du texte examiné "
              "ne font l'objet d'aucune observation dans le projet."]
        L += ['- Article ' + a for a in restants]
    return chr(10).join(L) + chr(10)


def note_carnet_projet(titre: str, st: dict) -> str:
    sens = st['avis']['sens'] or 'sens à compléter'
    return ("Projet d'avis (%s) : %s ; %d observation(s) générale(s), %d observation(s) "
            "d'article, %d demande(s) de modification."
            % (titre, sens, len(st['observations_generales']),
               len(st['observations_articles']), len(st['demandes'])))


# ── RELIRE ────────────────────────────────────────────────────────────────

NATURES = (
    'affirmation non étayée', 'argument contestable', 'contradiction',
    'demande imprécise', "incohérence avec le sens de l'avis",
    'référence à vérifier', 'argument manquant',
)

PROMPT_RELIRE = (
    "Tu relis de façon critique le BROUILLON d'un avis d'une instance consultative sur "
    "un texte réglementaire (le TEXTE EXAMINÉ). Tu relis l'ARGUMENTATION : la solidité "
    "des affirmations, la cohérence entre les observations, les demandes et le sens de "
    "l'avis, la précision des demandes, ce que le texte examiné contient et que le "
    "brouillon ne traite pas. Tu ne relèves NI l'orthographe, NI la grammaire, NI le "
    "style. Pas de compliments : seulement ce qui peut être renforcé.\n\n"
    "Réponds UNIQUEMENT par un objet JSON, sans une ligne avant ni après :\n"
    '{"sens_annonce": "...", "remarques": [{"nature": "...", "passage": "...", '
    '"remarque": "...", "piste": "...", "appui_texte": "..."}]}\n\n'
    "nature — exactement l'une de : " + ', '.join('« %s »' % n for n in NATURES) + ".\n"
    "passage — le passage EXACT du brouillon visé, 40 mots au plus, copié mot pour mot. "
    "Vide seulement pour « argument manquant ». Il sera vérifié automatiquement.\n"
    "remarque — ce qui fragilise l'argumentation, en une ou deux phrases.\n"
    "piste — comment le renforcer, sans réécrire le paragraphe.\n"
    "appui_texte — si la remarque s'appuie sur le texte examiné, le passage EXACT de ce "
    "texte, copié mot pour mot ; sinon vide. Obligatoire pour « argument manquant » et "
    "« référence à vérifier ».\n"
    "sens_annonce — le sens de l'avis tel que le brouillon l'annonce, ou vide.\n\n"
    "RÈGLES : rien n'est deviné. Ne prête pas au brouillon ce qu'il ne dit pas, ni au "
    "texte examiné ce qu'il ne contient pas. Une affirmation n'est « non étayée » que si "
    "le brouillon ne donne ni source, ni article, ni fait à l'appui.\n"
)


def parser_relecture(brut) -> dict:
    d = extraire_json(brut, dict) or {}
    rem = []
    for e in liste_de_dicts(d.get('remarques')):
        if not chaine(e.get('remarque')):
            continue
        nat = chaine(e.get('nature')).lower()
        rem.append({'nature': nat if nat in NATURES else 'argument contestable',
                    'passage': chaine(e.get('passage')), 'remarque': chaine(e.get('remarque')),
                    'piste': chaine(e.get('piste')), 'appui_texte': chaine(e.get('appui_texte'))})
    return {'sens_annonce': chaine(d.get('sens_annonce')), 'remarques': rem}


def verifier_relecture(rel: dict, brouillon: str, textes_examines: list) -> int:
    n = 0
    for e in rel['remarques']:
        e['passage_ok'] = bool(e['passage']) and citation_verifiee(e['passage'], [brouillon])
        e['appui_ok'] = bool(e['appui_texte']) and citation_verifiee(e['appui_texte'], textes_examines)
        n += int(bool(e['passage']) and not e['passage_ok'])
        n += int(bool(e['appui_texte']) and not e['appui_ok'])
    return n


async def relire(sources: list, brouillon: str, settings: dict) -> tuple:
    """Rend (relecture, erreur). N'échoue jamais silencieusement."""
    from core.engine import call_llm
    if not (brouillon or '').strip():
        return parser_relecture(None), 'Aucun brouillon à relire.'
    message = ('TEXTE EXAMINÉ' + chr(10) + (formater_sources(sources) or '(non fourni)')
               + chr(10) * 2 + "BROUILLON DE L'AVIS" + chr(10) + brouillon.strip())
    try:
        reponse = await call_llm(
            messages=[{'role': 'user', 'content': message}],
            provider=settings.get('provider', ''), model=settings.get('model'),
            system_prompt=PROMPT_RELIRE, max_tokens=6000, temperature=0.0,
            api_keys=settings.get('api_keys', {}))
    except Exception as e:
        return parser_relecture(None), 'La relecture a échoué : %s' % e
    rel = parser_relecture(reponse)
    verifier_relecture(rel, brouillon, [s['texte'] for s in sources])
    return rel, ''


def rendre_relecture(titre: str, rel: dict, sources: list, brouillon: str,
                     source_brouillon: str = '', avertissements=None) -> str:
    L = ['# Relecture critique — %s' % titre, '']
    L.append('Établie le %s. Brouillon relu : %s. Texte examiné : %s.' % (
        datetime.now().strftime('%d/%m/%Y'), source_brouillon or 'texte fourni',
        ' ; '.join(s['titre'] for s in sources) or 'non fourni'))
    L += ['', "Cette relecture porte sur l'argumentation, pas sur l'orthographe ni le "
          "style. Chaque remarque cite le passage du brouillon qu'elle vise ; les "
          "passages ont été comparés automatiquement au brouillon et au texte examiné."]
    for a in (avertissements or []):
        L += ['', 'Avertissement : ' + a]
    if rel['sens_annonce']:
        L += ['', "Sens de l'avis annoncé par le brouillon : %s." % rel['sens_annonce']]
    comptes = [(n, sum(1 for e in rel['remarques'] if e['nature'] == n)) for n in NATURES]
    comptes = [(n, c) for n, c in comptes if c]
    L += ['', '%d remarque(s)%s' % (len(rel['remarques']), (' : ' + ', '.join(
        '%d %s' % (c, n) for n, c in comptes) + '.') if comptes else '.')]

    restants = articles_non_commentes(chr(10).join(s['texte'] for s in sources), brouillon)
    if restants:
        L += ['', '## Articles du texte examiné absents du brouillon', '',
              "Relevé automatique : ces articles ne sont mentionnés nulle part dans le "
              "brouillon. Ce n'est pas forcément un oubli — à vous de juger."]
        L += ['- Article ' + a for a in restants]

    for n, _ in comptes:
        L += ['', '## ' + n[0].upper() + n[1:]]
        for e in [x for x in rel['remarques'] if x['nature'] == n]:
            L += ['', '### ' + _court(e['passage'] or e['remarque'])]
            if e['passage']:
                L.append('Passage : « %s »%s' % (
                    e['passage'], '' if e['passage_ok']
                    else ' — passage non retrouvé dans le brouillon, à vérifier.'))
            L.append('Remarque : ' + e['remarque'])
            if e['piste']:
                L.append('Piste : ' + e['piste'])
            if e['appui_texte']:
                L.append('Dans le texte examiné : « %s »%s' % (
                    e['appui_texte'], '' if e['appui_ok'] else ' — ' + MENTION_NON_VERIFIEE + '.'))
    if not rel['remarques']:
        L += ['', "Aucune remarque sur l'argumentation."]
    return chr(10).join(L) + chr(10)


def note_carnet_relecture(titre: str, rel: dict) -> str:
    if not rel['remarques']:
        return "Relecture d'avis (%s) : aucune remarque sur l'argumentation." % titre
    nat = {}
    for e in rel['remarques']:
        nat[e['nature']] = nat.get(e['nature'], 0) + 1
    return "Relecture d'avis (%s) : %d remarque(s) — %s." % (
        titre, len(rel['remarques']), ', '.join('%d %s' % (c, n) for n, c in nat.items()))
