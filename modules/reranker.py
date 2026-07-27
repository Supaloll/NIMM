# -*- coding: utf-8 -*-
"""Réordonnancement des passages de la base de connaissances.

POURQUOI CE MODULE
La recherche sémantique compare deux textes par leur « sens général ». C'est
rapide, mais grossier : deux textes français sans aucun rapport atteignent
couramment 0,5 de similarité — d'où le PDF sur l'accessibilité servi au milieu
d'une conversation bancaire. L'ancrage lexical ajouté ensuite (exiger un mot de
fond commun) est un garde-fou, pas une mesure de pertinence.

Un réordonnanceur, lui, lit la question ET le passage ensemble et répond à la
vraie question : « ce passage répond-il à CETTE demande ? ». C'est le correctif
de fond, là où l'ancrage lexical n'était qu'un pansement.

PRINCIPE DE PRUDENCE
Ce module est appelé sur le chemin chaud de la conversation. Il ne doit donc
JAMAIS ralentir ni casser NIMM :
  - s'il n'y a aucun moteur configuré, il ne fait rien et le comportement
    actuel est conservé à l'identique ;
  - toute erreur, tout dépassement de délai → on rend les passages dans leur
    ordre d'origine, sans lever d'exception ;
  - le moteur « llm » (juger avec un modèle de conversation) est utilisable
    mais JAMAIS choisi automatiquement : il ajoute une seconde d'attente à
    chaque message, ce qui se paie cher à la synthèse vocale.
"""

import json

_DELAI = 6.0          # au-delà, on renonce : mieux vaut un tri imparfait qu'une attente
_MAX_PASSAGES = 20    # borne de sécurité : on ne réordonne pas une base entière
_TAILLE_PASSAGE = 4000

_MOTEURS_CLOUD = {
    # nom : (clé de réglage NIMM, modèle par défaut)
    'cohere':  ('cohere',  'rerank-v3.5'),
    'voyage':  ('voyage',  'rerank-2.5'),
    'jina':    ('jina',    'jina-reranker-v2-base-multilingual'),
}


def _reglage(nom, defaut=''):
    try:
        from core.database import get_setting
        return get_setting(nom, defaut)
    except Exception:
        return defaut


def _vrai(valeur):
    return str(valeur).strip().lower() not in ('', '0', 'false', 'non', 'off')


def moteur_disponible(api_keys=None):
    """Quel réordonnanceur s'appliquera, et pourquoi — en une phrase lisible.

    Même logique d'annonce que pour la recherche web : le réglage explicite
    prime, et quand rien n'est configuré on le DIT plutôt que de laisser croire
    à une amélioration silencieuse.
    """
    api_keys = api_keys or {}
    mode = (_reglage('rag_rerank_mode', 'auto') or 'auto').strip().lower()

    if mode == 'off':
        return '', ("Réordonnancement désactivé : les passages sont servis dans "
                    "l'ordre de la recherche par sens.")
    if mode == 'llm':
        return 'llm', ("Réordonnancement par un modèle de conversation : le plus "
                       "fin, mais il ajoute une attente à chaque message.")
    if mode in _MOTEURS_CLOUD:
        cle, _ = _MOTEURS_CLOUD[mode]
        if (api_keys.get(cle) or '').strip():
            return mode, f"Réordonnancement par {mode.capitalize()}."
        return '', (f"Réordonnancement {mode.capitalize()} demandé, mais aucune clé "
                    f"« {cle} » n'est enregistrée : les passages restent dans "
                    "l'ordre de la recherche par sens.")
    if mode == 'local':
        url = (_reglage('rag_rerank_url', '') or '').strip()
        if url:
            return 'local', "Réordonnancement local (llama.cpp) : rien ne quitte ta machine."
        return '', ("Réordonnancement local demandé, mais aucune adresse de serveur "
                    "n'est renseignée dans les réglages.")

    # mode 'auto' : local d'abord (rien ne sort de la machine), puis une clé cloud
    if (_reglage('rag_rerank_url', '') or '').strip():
        return 'local', "Réordonnancement local (llama.cpp) : rien ne quitte ta machine."
    for nom, (cle, _) in _MOTEURS_CLOUD.items():
        if (api_keys.get(cle) or '').strip():
            return nom, f"Réordonnancement par {nom.capitalize()} (choisi automatiquement)."
    return '', ("Aucun réordonnanceur configuré : NIMM s'en tient à la recherche par "
                "sens et à l'ancrage lexical. Renseigne une adresse llama.cpp locale "
                "ou une clé Cohere, Voyage ou Jina pour améliorer la pertinence.")


def _post(url, corps, entetes=None, delai=None):
    """Appel HTTP synchrone et borné. Rend None plutôt que de lever : ce module
    ne doit jamais interrompre une conversation."""
    import httpx
    try:
        with httpx.Client(timeout=delai or _DELAI) as client:
            r = client.post(url, json=corps, headers=entetes or {})
            if r.status_code >= 400:
                return None
            return r.json()
    except Exception:
        return None


def _rerank_local(question, textes):
    """Serveur llama.cpp lancé avec --reranking (endpoint /v1/rerank)."""
    base = (_reglage('rag_rerank_url', '') or '').strip().rstrip('/')
    if not base:
        return None
    if not base.endswith('/rerank'):
        base = base + '/v1/rerank'
    data = _post(base, {'query': question, 'documents': textes,
                        'model': _reglage('rag_rerank_modele', '') or 'reranker'})
    return _lire_resultats(data)


def _rerank_cohere(question, textes, api_keys):
    cle = (api_keys.get('cohere') or '').strip()
    if not cle:
        return None
    data = _post('https://api.cohere.com/v2/rerank',
                 {'model': _reglage('rag_rerank_modele', '') or _MOTEURS_CLOUD['cohere'][1],
                  'query': question, 'documents': textes, 'top_n': len(textes)},
                 {'Authorization': f'Bearer {cle}', 'Content-Type': 'application/json'})
    return _lire_resultats(data)


def _rerank_voyage(question, textes, api_keys):
    cle = (api_keys.get('voyage') or '').strip()
    if not cle:
        return None
    data = _post('https://api.voyageai.com/v1/rerank',
                 {'model': _reglage('rag_rerank_modele', '') or _MOTEURS_CLOUD['voyage'][1],
                  'query': question, 'documents': textes},
                 {'Authorization': f'Bearer {cle}', 'Content-Type': 'application/json'})
    return _lire_resultats(data)


def _rerank_jina(question, textes, api_keys):
    cle = (api_keys.get('jina') or '').strip()
    if not cle:
        return None
    data = _post('https://api.jina.ai/v1/rerank',
                 {'model': _reglage('rag_rerank_modele', '') or _MOTEURS_CLOUD['jina'][1],
                  'query': question, 'documents': textes, 'top_n': len(textes)},
                 {'Authorization': f'Bearer {cle}', 'Content-Type': 'application/json'})
    return _lire_resultats(data)


def _lire_resultats(data):
    """Extrait [(indice, score)] d'une réponse de réordonnanceur.

    Cohere, Voyage, Jina et llama.cpp renvoient tous une liste « results » avec
    « index » et « relevance_score », mais pas toujours sous la même racine et
    parfois avec « score ». On accepte les variantes : refuser une forme
    légitime reviendrait à désactiver silencieusement la fonction.
    """
    if not isinstance(data, dict):
        return None
    brut = data.get('results') or data.get('data') or []
    if not isinstance(brut, list) or not brut:
        return None
    sortie = []
    for item in brut:
        if not isinstance(item, dict):
            continue
        idx = item.get('index')
        if idx is None:
            idx = item.get('document_index')
        sc = item.get('relevance_score')
        if sc is None:
            sc = item.get('score')
        if idx is None or sc is None:
            continue
        try:
            sortie.append((int(idx), float(sc)))
        except (TypeError, ValueError):
            continue
    return sortie or None


PROMPT_JUGE = (
    "Tu notes la PERTINENCE de passages vis-à-vis d'une question. Pour chaque "
    "passage, donne une note de 0 à 10 :\n"
    "  0 à 2  : hors sujet, même si le vocabulaire se ressemble ;\n"
    "  3 à 5  : même domaine, mais ne répond pas à la question posée ;\n"
    "  6 à 8  : contient une partie de la réponse ;\n"
    "  9 ou 10 : répond directement à la question.\n"
    "Sois sévère : un passage qui n'aide pas à répondre doit être noté bas, "
    "même s'il est bien écrit et sur un thème voisin.\n"
    'Réponds UNIQUEMENT par du JSON : {"notes": [{"i": 0, "note": 7}, ...]}'
)


async def _rerank_llm(question, textes, api_keys):
    """Dernier recours : faire juger la pertinence par un modèle de conversation.

    Coûteux en temps, donc jamais choisi automatiquement — mais il fonctionne
    sans aucune clé supplémentaire ni serveur à installer, y compris avec un
    modèle local via Ollama.
    """
    from core.engine import call_llm
    liste = '\n\n'.join(f'[{i}] {t[:1200]}' for i, t in enumerate(textes))
    try:
        rep = await call_llm(
            [{'role': 'user', 'content': f"QUESTION : {question}\n\nPASSAGES :\n{liste}"}],
            provider=(_reglage('rag_rerank_provider', '') or None) or None,
            system_prompt=PROMPT_JUGE, max_tokens=600, temperature=0,
            api_keys=api_keys)
    except Exception:
        return None
    texte = rep if isinstance(rep, str) else (rep or {}).get('content', '')
    return _lire_notes_llm(texte, len(textes))


def _lire_notes_llm(texte, nb):
    """Extrait les notes d'une réponse de modèle, même enrobée de bavardage.

    Un modèle qui répond « Voici les notes : {...} » ne doit pas faire échouer
    le réordonnancement : on isole le premier objet JSON plausible.
    """
    if not texte:
        return None
    t = texte.strip()
    i, j = t.find('{'), t.rfind('}')
    if i == -1 or j <= i:
        return None
    try:
        data = json.loads(t[i:j + 1])
    except Exception:
        return None
    notes = data.get('notes') if isinstance(data, dict) else None
    if not isinstance(notes, list):
        return None
    sortie = []
    for item in notes:
        if not isinstance(item, dict):
            continue
        try:
            idx, note = int(item.get('i')), float(item.get('note'))
        except (TypeError, ValueError):
            continue
        if 0 <= idx < nb:
            sortie.append((idx, note / 10.0))    # ramené sur 0–1 comme les autres moteurs
    return sortie or None


def seuil_pertinence():
    """En dessous, un passage est écarté. Les moteurs rendent tous un score 0–1."""
    try:
        return float(_reglage('rag_rerank_seuil', '0.30'))
    except (TypeError, ValueError):
        return 0.30


def reordonner(question, passages, api_keys=None, top_n=3):
    """Réordonne des passages par pertinence réelle. Point d'entrée unique.

    Rend (passages_retenus, moteur, note). Si aucun moteur n'est disponible ou
    si l'appel échoue, rend (passages inchangés, '', explication) — le
    comportement actuel de NIMM est alors conservé à l'identique.
    """
    api_keys = api_keys or {}
    if not passages:
        return [], '', ''
    moteur, note = moteur_disponible(api_keys)
    if not moteur:
        return passages, '', note

    passages = passages[:_MAX_PASSAGES]
    textes = [(p.get('passage') or '')[:_TAILLE_PASSAGE] for p in passages]

    if moteur == 'local':
        scores = _rerank_local(question, textes)
    elif moteur == 'cohere':
        scores = _rerank_cohere(question, textes, api_keys)
    elif moteur == 'voyage':
        scores = _rerank_voyage(question, textes, api_keys)
    elif moteur == 'jina':
        scores = _rerank_jina(question, textes, api_keys)
    elif moteur == 'llm':
        import asyncio
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            scores = asyncio.run(_rerank_llm(question, textes, api_keys))
        else:
            # Déjà dans une boucle : on ne peut pas en démarrer une seconde ici.
            # Plutôt que de bloquer la conversation, on renonce proprement.
            return passages, '', ("Réordonnancement par modèle indisponible sur ce "
                                  "chemin ; ordre de la recherche par sens conservé.")
    else:
        scores = None

    if not scores:
        return passages, '', (f"Le réordonnanceur ({moteur}) n'a pas répondu : ordre "
                              "de la recherche par sens conservé.")

    seuil = seuil_pertinence()
    scores.sort(key=lambda x: x[1], reverse=True)
    retenus, ecartes = [], []
    for idx, sc in scores:
        if idx >= len(passages):
            continue
        p = dict(passages[idx])
        p['score_rerank'] = round(sc, 3)
        (retenus if sc >= seuil else ecartes).append(p)

    if not retenus:
        return [], moteur, (f"Réordonnancement ({moteur}) : aucun des "
                            f"{len(passages)} passages n'atteint le seuil de "
                            f"pertinence ({seuil:.2f}). Aucun document n'est servi.")
    resume = (f"Réordonnancement ({moteur}) : {len(retenus)} passage(s) retenu(s) "
              f"sur {len(passages)}"
              + (f", {len(ecartes)} écarté(s) sous le seuil {seuil:.2f}" if ecartes else "")
              + ".")
    return retenus[:top_n], moteur, resume
