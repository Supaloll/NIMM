# -*- coding: utf-8 -*-
"""Veille documentaire : recherche par le SENS (Exa) et sujets suivis dans le temps.

DEUX PARTIES, ET UNE IDÉE
1. Un client Exa. Contrairement à Brave ou Tavily, qui cherchent des mots, Exa
   cherche des documents PROCHES PAR LE SENS d'un texte de référence. C'est le
   geste même de la veille : « trouve-moi ce qui ressemble à ça, mais publié
   depuis ».
2. Des sujets de veille : un libellé, un texte de référence, une périodicité.
   Le travailleur de fond les relève à échéance, écarte ce qui a déjà été vu,
   verse les nouveautés dans la base de connaissances et le dit au journal.

POURQUOI ÇA VAUT LE COUP DANS NIMM
NIMM sait déjà planifier (les ricochets) et déjà ingérer des documents. La
veille ne fait que relier les deux : c'est le seul morceau qui manquait pour
qu'une question posée une fois continue de travailler toute seule.

PRUDENCE
Tout ce module échoue en silence et rend des messages en français. Une veille
qui casse ne doit jamais empêcher NIMM de fonctionner.
"""

import json
from datetime import datetime, timedelta

_EXA_BASE = 'https://api.exa.ai'
_DELAI = 30.0
_MAX_SUJETS = 30
_MAX_VUS = 400          # empreintes d'articles déjà vus, par sujet

PERIODES = {
    'quotidienne': 1,
    'hebdomadaire': 7,
    'mensuelle': 30,
}


# ────────────────────────────── client Exa ──────────────────────────────

def _cle_exa(api_keys=None):
    cle = ((api_keys or {}).get('exa') or '').strip()
    if cle:
        return cle
    try:
        from core.database import get_api_keys
        return (get_api_keys().get('exa') or '').strip()
    except Exception:
        return ''


def _appel_exa(chemin, corps, api_keys=None):
    """Rend (données, erreur_en_français). Ne lève jamais."""
    import httpx
    cle = _cle_exa(api_keys)
    if not cle:
        return None, "Aucune clé Exa enregistrée dans les réglages."
    try:
        with httpx.Client(timeout=_DELAI) as client:
            r = client.post(f'{_EXA_BASE}/{chemin}', json=corps,
                            headers={'x-api-key': cle, 'Content-Type': 'application/json'})
            if r.status_code in (401, 403):
                return None, "Exa refuse la clé d'API."
            if r.status_code == 429:
                return None, "Quota Exa atteint ou trop d'appels rapprochés."
            if r.status_code >= 400:
                return None, f"Erreur Exa {r.status_code}."
            return r.json(), ''
    except Exception as e:
        return None, f"Exa injoignable ({e})."


def _lire_resultats(data):
    """Normalise la réponse d'Exa en une liste de dicts NIMM.

    Le champ « results » est la forme documentée, mais on accepte aussi une
    liste nue : refuser une variante légitime reviendrait à perdre la veille
    d'une semaine sans le dire.
    """
    if isinstance(data, list):
        brut = data
    elif isinstance(data, dict):
        brut = data.get('results') or data.get('data') or []
    else:
        return []
    sortie = []
    for r in brut:
        if not isinstance(r, dict):
            continue
        sortie.append({
            'titre': (r.get('title') or '').strip() or '(sans titre)',
            'url': (r.get('url') or r.get('id') or '').strip(),
            'date': (r.get('publishedDate') or '')[:10],
            'auteur': (r.get('author') or '').strip(),
            'extrait': ((r.get('summary') or r.get('text') or '')).strip()[:4000],
            'score': r.get('score'),
        })
    return [r for r in sortie if r['url']]


def _bloc_contenus(nb_caracteres=2000, resume=False):
    c = {'text': {'maxCharacters': nb_caracteres}}
    if resume:
        c['summary'] = {'query': 'De quoi parle ce document, en trois phrases ?'}
    return c


def exa_search(requete, nb=8, depuis_jours=None, domaines_exclus=None,
               categorie='', api_keys=None):
    """Recherche par le sens. Rend (résultats, erreur)."""
    if not (requete or '').strip():
        return [], "Requête vide."
    corps = {'query': requete.strip(), 'numResults': max(1, min(25, int(nb))),
             'type': 'auto', 'contents': _bloc_contenus()}
    if depuis_jours:
        corps['startPublishedDate'] = (
            datetime.now() - timedelta(days=int(depuis_jours))).strftime('%Y-%m-%dT00:00:00.000Z')
    if domaines_exclus:
        corps['excludeDomains'] = list(domaines_exclus)
    if categorie:
        corps['category'] = categorie
    data, err = _appel_exa('search', corps, api_keys)
    return (_lire_resultats(data), '') if not err else ([], err)


def exa_similar(url, nb=8, depuis_jours=None, api_keys=None):
    """Documents proches d'une page donnée — « encore comme celui-ci »."""
    if not (url or '').strip():
        return [], "Aucune adresse fournie."
    corps = {'url': url.strip(), 'numResults': max(1, min(25, int(nb))),
             'contents': _bloc_contenus()}
    if depuis_jours:
        corps['startPublishedDate'] = (
            datetime.now() - timedelta(days=int(depuis_jours))).strftime('%Y-%m-%dT00:00:00.000Z')
    data, err = _appel_exa('findSimilar', corps, api_keys)
    return (_lire_resultats(data), '') if not err else ([], err)


# ────────────────────────── sujets de veille ──────────────────────────

def _lire(cle, defaut):
    try:
        from core.database import get_setting
        v = json.loads(get_setting(cle, defaut))
        return v
    except Exception:
        return json.loads(defaut)


def _ecrire(cle, valeur):
    try:
        from core.database import set_setting
        set_setting(cle, json.dumps(valeur, ensure_ascii=False))
        return True
    except Exception:
        return False


def list_sujets():
    v = _lire('veille_sujets', '[]')
    return v if isinstance(v, list) else []


def add_sujet(libelle, requete, periode='hebdomadaire', url_reference='', nb=8):
    """Ajoute un sujet suivi. `url_reference` remplace la requête si fournie :
    on cherche alors ce qui RESSEMBLE à cette page."""
    import uuid
    sujets = list_sujets()
    sujet = {
        'id': uuid.uuid4().hex,
        'libelle': (libelle or requete or 'Veille')[:200],
        'requete': (requete or '').strip()[:500],
        'url_reference': (url_reference or '').strip()[:500],
        'periode': periode if periode in PERIODES else 'hebdomadaire',
        'nb': max(1, min(25, int(nb or 8))),
        'actif': True,
        'cree_le': datetime.now().isoformat(timespec='seconds'),
        'dernier_run': '',
        'dernier_statut': '',
        'nb_trouves': 0,
    }
    sujets.append(sujet)
    _ecrire('veille_sujets', sujets[:_MAX_SUJETS])
    return sujet


def update_sujet(sujet_id, **champs):
    sujets = list_sujets()
    for s in sujets:
        if s.get('id') == sujet_id:
            for k, v in champs.items():
                if k in s or k in ('dernier_run', 'dernier_statut', 'nb_trouves'):
                    s[k] = v
            _ecrire('veille_sujets', sujets)
            return s
    return {}


def remove_sujet(sujet_id):
    sujets = [s for s in list_sujets() if s.get('id') != sujet_id]
    _ecrire('veille_sujets', sujets)
    return sujets


def _vus(sujet_id):
    v = _lire('veille_vus_' + sujet_id, '[]')
    return set(v) if isinstance(v, list) else set()


def _marquer_vus(sujet_id, urls):
    deja = list(_vus(sujet_id))
    deja.extend(u for u in urls if u not in deja)
    _ecrire('veille_vus_' + sujet_id, deja[-_MAX_VUS:])


def veille_due(sujet, maintenant=None):
    """Ce sujet doit-il être relevé maintenant ? Fonction PURE, donc testable
    sans horloge ni réseau — le même choix que pour les ricochets planifiés."""
    if not sujet.get('actif', True):
        return False
    maintenant = maintenant or datetime.now()
    jours = PERIODES.get(sujet.get('periode'), 7)
    dernier = (sujet.get('dernier_run') or '').strip()
    if not dernier:
        return True            # jamais relevé : on relève tout de suite
    try:
        d = datetime.fromisoformat(dernier)
    except ValueError:
        return True            # date illisible : on relève plutôt que de bloquer
    if d > maintenant:
        return True            # horloge reculée : ne pas rester coincé des jours
    return (maintenant - d) >= timedelta(days=jours)


def relever_sujet(sujet, api_keys=None, ingerer=True):
    """Relève un sujet : cherche, écarte le déjà-vu, verse le neuf dans la base.

    Rend (nouveautés, message). Le message est écrit pour être écouté, pas lu
    en diagonale.
    """
    sid = sujet.get('id') or ''
    jours = PERIODES.get(sujet.get('periode'), 7)
    # On ratisse un peu plus large que la période : un article publié la veille
    # du dernier relevé n'aurait sinon jamais été vu.
    fenetre = jours * 2
    if (sujet.get('url_reference') or '').strip():
        resultats, err = exa_similar(sujet['url_reference'], sujet.get('nb', 8),
                                     fenetre, api_keys)
    else:
        resultats, err = exa_search(sujet.get('requete', ''), sujet.get('nb', 8),
                                    fenetre, api_keys=api_keys)
    if err:
        return [], f"Veille « {sujet.get('libelle', '?')} » : {err}"

    deja = _vus(sid)
    nouveaux = [r for r in resultats if r['url'] not in deja]
    _marquer_vus(sid, [r['url'] for r in resultats])

    if not nouveaux:
        return [], (f"Veille « {sujet.get('libelle', '?')} » : rien de nouveau "
                    f"({len(resultats)} résultat(s), tous déjà vus).")

    if ingerer:
        for r in nouveaux:
            if not r.get('extrait'):
                continue
            try:
                from modules.enrichissement import ingest_text
                ingest_text(f"[Veille] {r['titre']}", r['extrait'], source=r['url'])
            except Exception:
                pass       # une ingestion ratée ne doit pas perdre le relevé

    titres = ' ; '.join(r['titre'][:70] for r in nouveaux[:3])
    suite = '' if len(nouveaux) <= 3 else f" et {len(nouveaux) - 3} autre(s)"
    return nouveaux, (f"Veille « {sujet.get('libelle', '?')} » : {len(nouveaux)} "
                      f"nouveauté(s) — {titres}{suite}.")


def relever_les_dus(api_keys=None, maintenant=None):
    """Passe tous les sujets échus. Appelé par le travailleur de fond."""
    messages = []
    for sujet in list_sujets():
        if not veille_due(sujet, maintenant):
            continue
        nouveaux, message = relever_sujet(sujet, api_keys)
        update_sujet(sujet['id'],
                     dernier_run=(maintenant or datetime.now()).isoformat(timespec='seconds'),
                     dernier_statut=message, nb_trouves=len(nouveaux))
        messages.append(message)
        try:
            from core.database import add_diagnostic
            add_diagnostic('veille', message)
        except Exception:
            pass
    return messages
