# -*- coding: utf-8 -*-
"""Règles communes du volet « travail institutionnel » : rien n'est deviné, tout est cité.

Préparer une réunion, rédiger un avis, suivre un texte réglementaire : trois
fonctions qui lisent des documents reçus et en tirent des éléments qu'on va
relayer — en commission, dans un avis, à un collègue. Le risque commun est le
même que pour le relevé de décisions (modules/decisions.py) : un élément
inventé, ou une citation reformulée, sera repris sans que personne n'aille
vérifier.

Ce module apporte ce que le relevé n'avait pas : la VÉRIFICATION. Demander au
modèle de citer « mot pour mot » ne garantit rien — un modèle reformule de
bonne foi. On contrôle donc chaque extrait contre le texte réel. Un extrait
introuvable n'est pas supprimé (l'élément peut être juste) : il est marqué
« extrait non retrouvé dans les documents — à vérifier », et le document le dit.

Il rassemble aussi les sources : le document attaché à la conversation, plus
autant de documents de la base de connaissances que l'utilisateur en nomme.
"""

import json
import re
import unicodedata

MAX_TOTAL = 60000          # au-delà, on prévient plutôt que de tronquer en silence
MENTION_NON_VERIFIEE = "extrait non retrouvé dans les documents — à vérifier"

_GUILLEMETS = '«»“”„"‟‹›'
_APOSTROPHES = '’‘‛`´'


def normaliser(texte: str) -> str:
    """Forme de comparaison : casse, espaces, guillemets et apostrophes neutralisés.

    Un modèle qui recopie fidèlement un passage change souvent, sans le vouloir,
    une apostrophe typographique en apostrophe droite, ou ajoute des guillemets.
    Ce n'est pas une reformulation : on ne doit pas le lui reprocher.
    """
    t = unicodedata.normalize('NFKC', str(texte or ''))
    for c in _APOSTROPHES:
        t = t.replace(c, "'")
    for c in _GUILLEMETS:
        t = t.replace(c, ' ')
    t = t.replace(' ', ' ').replace(' ', ' ')
    t = re.sub(r'\s+', ' ', t)
    return t.strip().lower()


def citation_verifiee(citation: str, textes) -> bool:
    """La citation figure-t-elle mot pour mot dans l'un des textes ?

    Une coupure signalée par « … », « ... » ou « […] » est admise : chaque
    morceau doit alors se trouver, dans l'ordre, dans un même texte. Les
    morceaux de moins de 12 caractères ne prouvent rien et sont ignorés — mais
    une citation faite UNIQUEMENT de tels morceaux n'est pas vérifiée.
    """
    c = str(citation or '').strip()
    if not c:
        return False
    morceaux = [normaliser(m) for m in re.split(r'\[\s*(?:…|\.\.\.)\s*\]|…|\.\.\.', c)]
    morceaux = [m.strip(' .,;:') for m in morceaux]
    morceaux = [m for m in morceaux if len(m) >= 12]
    if not morceaux:
        return False
    for t in (textes if isinstance(textes, (list, tuple)) else [textes]):
        tn = normaliser(t)
        pos = 0
        for m in morceaux:
            i = tn.find(m, pos)
            if i == -1:
                break
            pos = i + len(m)
        else:
            return True
    return False


def extraire_json(brut, attendu=dict):
    """Premier objet (ou tableau) JSON d'une réponse de modèle, avec indulgence.

    Les fournisseurs encadrent le JSON de ``` ou de bavardage malgré la
    consigne. Rien d'exploitable → None : une analyse ratée ne doit jamais
    casser la conversation.
    """
    if not brut:
        return None
    texte = str(brut).strip()
    blocs = re.findall(r'```(?:json)?\s*(.*?)```', texte, re.S)
    if blocs:
        texte = blocs[0].strip()
    ouvrant, fermant = ('{', '}') if attendu is dict else ('[', ']')
    debut, fin = texte.find(ouvrant), texte.rfind(fermant)
    if debut == -1 or fin <= debut:
        return None
    try:
        val = json.loads(texte[debut:fin + 1])
    except Exception:
        return None
    return val if isinstance(val, attendu) else None


def chaine(v, defaut: str = '') -> str:
    """Valeur de champ propre : jamais None, jamais de retour à la ligne parasite."""
    s = str(v if v is not None else '').strip()
    return re.sub(r'\s+', ' ', s) or defaut


def liste_de_dicts(v) -> list:
    return [e for e in (v or []) if isinstance(e, dict)] if isinstance(v, list) else []


def documents_disponibles() -> list:
    """Titres des documents de la base de connaissances (pour les messages d'aide)."""
    try:
        from core.database import list_documents_base
        return [d['titre'] for d in list_documents_base()]
    except Exception:
        return []


def trouver_document_base(nom: str):
    """Document de la base dont le titre correspond le mieux à `nom`, ou None.

    Égalité d'abord, puis inclusion (« avis RPA » retrouve « Projet d'avis RPA
    v3 »). Si plusieurs titres contiennent le nom, le plus récent l'emporte —
    list_documents_base les rend du plus récent au plus ancien.
    """
    from core.database import list_documents_base, get_document_base
    cible = normaliser(nom)
    if not cible:
        return None
    docs = list_documents_base()
    for d in docs:
        if normaliser(d['titre']) == cible:
            return get_document_base(d['id']) or None
    for d in docs:
        if cible in normaliser(d['titre']):
            return get_document_base(d['id']) or None
    return None


def rassembler_sources(thread_id: str, documents=None, texte: str = '',
                       inclure_document_du_fil: bool = True,
                       max_total: int = MAX_TOTAL) -> tuple:
    """Rend (sources, avertissements).

    sources : liste de {titre, texte}, dans l'ordre : texte fourni, document du
    fil, puis documents de la base dans l'ordre où ils ont été nommés.
    avertissements : phrases à reprendre telles quelles dans le document produit
    (document introuvable, texte tronqué). Rien n'est perdu sans être dit.
    """
    sources, avert = [], []
    texte = (texte or '').strip()
    if texte:
        sources.append({'titre': 'texte fourni dans la conversation', 'texte': texte})
    if inclure_document_du_fil and thread_id:
        try:
            from core.database import get_thread_document
            doc = get_thread_document(thread_id) or {}
        except Exception:
            doc = {}
        if (doc.get('texte') or '').strip():
            sources.append({'titre': doc.get('titre') or 'document de la conversation',
                            'texte': doc['texte'].strip()})
    for nom in (documents or []):
        nom = str(nom or '').strip()
        if not nom:
            continue
        try:
            d = trouver_document_base(nom)
        except Exception:
            d = None
        if not d or not (d.get('texte') or '').strip():
            avert.append("Document « %s » introuvable dans la base de connaissances : "
                         "il n'a pas été pris en compte." % nom)
            continue
        if any(s['titre'] == d['titre'] for s in sources):
            continue
        sources.append({'titre': d['titre'], 'texte': d['texte'].strip()})

    # Budget de lecture : on garde les documents entiers tant que possible, et
    # on DIT lequel a été coupé.
    reste, gardes = max_total, []
    for s in sources:
        if reste <= 0:
            avert.append("Document « %s » non lu : la limite de %d caractères était "
                         "atteinte. L'analyse est donc incomplète." % (s['titre'], max_total))
            continue
        if len(s['texte']) > reste:
            avert.append("Document « %s » tronqué : seuls ses %d premiers caractères "
                         "ont été lus. L'analyse est donc incomplète." % (s['titre'], reste))
            s = {'titre': s['titre'], 'texte': s['texte'][:reste]}
        gardes.append(s)
        reste -= len(s['texte'])
    return gardes, avert


def formater_sources(sources: list) -> str:
    """Les documents tels que le modèle les reçoit, chacun sous son titre."""
    return (chr(10) * 2).join('=== Document : %s ===%s%s' % (s['titre'], chr(10), s['texte'])
                              for s in sources)


def marquer_citations(elements: list, textes, champ: str = 'citation') -> int:
    """Ajoute `verifiee` (bool) à chaque élément ; rend le nombre de non vérifiées."""
    n = 0
    for e in elements:
        ok = citation_verifiee(e.get(champ, ''), textes) if e.get(champ) else False
        e['verifiee'] = ok
        if e.get(champ) and not ok:
            n += 1
    return n


def rendre_citation(e: dict, champ: str = 'citation') -> str:
    """Ligne markdown d'un extrait, avec sa mention s'il n'a pas été retrouvé."""
    c = e.get(champ) or ''
    if not c:
        return 'Extrait : aucun.'
    ligne = '« %s »' % c
    if e.get('document'):
        ligne += ' (%s)' % e['document']
    if not e.get('verifiee', True):
        ligne += ' — ' + MENTION_NON_VERIFIEE + '.'
    return ligne
