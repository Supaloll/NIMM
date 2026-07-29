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


def _modele_pour(moteur, modele=None):
    """Nom de modèle à employer pour ce moteur.

    Le réglage `rag_rerank_modele` est UNIQUE alors qu'il y a plusieurs moteurs :
    tel quel, il ne vaut que pour le moteur choisi. Le banc d'essai, lui,
    interroge tous les moteurs d'affilée — il doit donc pouvoir imposer le
    modèle par défaut de chacun, sinon on enverrait « rerank-v3.5 » à Jina et on
    conclurait à tort que Jina ne répond pas.
    """
    if modele is not None:
        return (modele or '').strip() or _MOTEURS_CLOUD.get(moteur, ('', 'reranker'))[1]
    return (_reglage('rag_rerank_modele', '') or ''
            ).strip() or _MOTEURS_CLOUD.get(moteur, ('', 'reranker'))[1]


def _rerank_local(question, textes, modele=None):
    """Serveur llama.cpp lancé avec --reranking (endpoint /v1/rerank)."""
    base = (_reglage('rag_rerank_url', '') or '').strip().rstrip('/')
    if not base:
        return None
    if not base.endswith('/rerank'):
        base = base + '/v1/rerank'
    data = _post(base, {'query': question, 'documents': textes,
                        'model': _modele_pour('local', modele)})
    return _lire_resultats(data)


def _rerank_cohere(question, textes, api_keys, modele=None):
    cle = (api_keys.get('cohere') or '').strip()
    if not cle:
        return None
    data = _post('https://api.cohere.com/v2/rerank',
                 {'model': _modele_pour('cohere', modele),
                  'query': question, 'documents': textes, 'top_n': len(textes)},
                 {'Authorization': f'Bearer {cle}', 'Content-Type': 'application/json'})
    return _lire_resultats(data)


def _rerank_voyage(question, textes, api_keys, modele=None):
    cle = (api_keys.get('voyage') or '').strip()
    if not cle:
        return None
    data = _post('https://api.voyageai.com/v1/rerank',
                 {'model': _modele_pour('voyage', modele),
                  'query': question, 'documents': textes},
                 {'Authorization': f'Bearer {cle}', 'Content-Type': 'application/json'})
    return _lire_resultats(data)


def _rerank_jina(question, textes, api_keys, modele=None):
    cle = (api_keys.get('jina') or '').strip()
    if not cle:
        return None
    data = _post('https://api.jina.ai/v1/rerank',
                 {'model': _modele_pour('jina', modele),
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


# ═══════════════════════════ BANC D'ESSAI ═══════════════════════════
#
# POURQUOI
# Choisir un réordonnanceur au jugé, c'est régler à l'oreille un instrument
# qu'on n'entend pas : le seul retour disponible aujourd'hui est « la réponse
# m'a semblé meilleure ». Le banc pose la MÊME question aux mêmes passages avec
# chaque moteur configuré, et rend les trois choses qui décident vraiment :
# quels passages remontent, avec quel score, et en combien de temps.
#
# PRUDENCE
# Le banc ne modifie AUCUN réglage. Il n'écrit rien, ne remplace rien : il
# mesure. Un moteur qui tombe est rapporté comme tel, pas masqué.

MOTEURS_BANC = ('semantique', 'local', 'cohere', 'voyage', 'jina', 'llm')

LIBELLES_MOTEURS = {
    'semantique': "Sans réordonnanceur (ordre de la recherche par sens)",
    'local':      "Local llama.cpp",
    'cohere':     "Cohere",
    'voyage':     "Voyage",
    'jina':       "Jina",
    'llm':        "Modèle de conversation (juge)",
}


def moteurs_testables(api_keys=None):
    """Ce que le banc peut interroger, et pourquoi le reste est hors course.

    On rend TOUS les moteurs, y compris les indisponibles, avec leur raison :
    « Voyage : aucune clé enregistrée » est une information utile, l'absence
    silencieuse d'une ligne ne l'est pas.
    """
    api_keys = api_keys or {}
    sortie = []
    for nom in MOTEURS_BANC:
        if nom == 'semantique':
            sortie.append({'nom': nom, 'libelle': LIBELLES_MOTEURS[nom],
                           'disponible': True, 'raison': "Référence de comparaison."})
        elif nom == 'local':
            url = (_reglage('rag_rerank_url', '') or '').strip()
            sortie.append({'nom': nom, 'libelle': LIBELLES_MOTEURS[nom],
                           'disponible': bool(url),
                           'raison': ("Serveur local : rien ne quitte ta machine."
                                      if url else
                                      "Aucune adresse de serveur llama.cpp renseignée.")})
        elif nom == 'llm':
            sortie.append({'nom': nom, 'libelle': LIBELLES_MOTEURS[nom],
                           'disponible': True,
                           'raison': "Aucune clé dédiée, mais compte une seconde ou plus."})
        else:
            cle = _MOTEURS_CLOUD[nom][0]
            presente = bool((api_keys.get(cle) or '').strip())
            sortie.append({'nom': nom, 'libelle': LIBELLES_MOTEURS[nom],
                           'disponible': presente,
                           'raison': (f"Clé « {cle} » enregistrée." if presente else
                                      f"Aucune clé « {cle} » enregistrée.")})
    return sortie


def _classement_depuis_scores(scores, passages, seuil):
    """Transforme [(indice, score)] en un classement lisible et ordonné."""
    lignes = []
    for rang, (idx, sc) in enumerate(sorted(scores, key=lambda x: x[1], reverse=True), 1):
        if idx < 0 or idx >= len(passages):
            continue
        p = passages[idx]
        lignes.append({
            'rang': rang,
            'passage': idx,
            'score': round(float(sc), 3),
            'retenu': float(sc) >= seuil,
            'titre': (p.get('titre') or 'Document')[:200],
            'source': (p.get('source') or '')[:300],
        })
    return lignes


async def banc_essai(question, api_keys=None, k=10, top_n=5, moteurs=None):
    """Compare les réordonnanceurs sur une même question. Ne change aucun réglage.

    Rend un dict prêt à afficher ET un rapport en texte brut (`texte`), pour
    qu'un résultat de mesure puisse être copié, collé, relu au braille ou gardé
    dans un fichier — un tableau qui n'existe qu'à l'écran ne se compare pas
    d'une semaine à l'autre.
    """
    import time as _time
    import asyncio as _aio

    api_keys = api_keys or {}
    question = (question or '').strip()
    seuil = seuil_pertinence()
    if not question:
        return {'erreur': "Pose une question : le banc a besoin d'une demande à mesurer."}

    try:
        from modules.enrichissement import search_documents
        _k = max(1, min(_MAX_PASSAGES, int(k or 10)))
        # La recherche calcule un plongement : bloquante, elle part dans un fil.
        passages = await _aio.to_thread(search_documents, question, _k)
    except Exception as e:
        return {'erreur': f"Base de connaissances inaccessible : {e}"}
    if not passages:
        return {'erreur': "La recherche par sens ne remonte aucun passage pour cette "
                          "question : il n'y a rien à réordonner. Vérifie que des "
                          "documents sont bien ingérés."}

    textes = [(p.get('passage') or '')[:_TAILLE_PASSAGE] for p in passages]
    dispo = {m['nom']: m for m in moteurs_testables(api_keys)}
    demandes = [m for m in (moteurs or MOTEURS_BANC) if m in dispo]

    resultats = []
    for nom in demandes:
        info = dispo[nom]
        if not info['disponible']:
            resultats.append({'moteur': nom, 'libelle': info['libelle'], 'ok': False,
                              'secondes': 0.0, 'note': info['raison'], 'classement': []})
            continue

        debut = _time.perf_counter()
        scores, note = None, ''
        try:
            if nom == 'semantique':
                # Référence : l'ordre rendu par la recherche par sens, sans retouche.
                # Le score sémantique n'est PAS sur la même échelle que celui d'un
                # réordonnanceur — on le rend tel quel, sans le comparer au seuil.
                scores = [(i, float(p.get('score') or 0.0)) for i, p in enumerate(passages)]
            elif nom == 'llm':
                scores = await _rerank_llm(question, textes, api_keys)
            else:
                # Les moteurs HTTP sont synchrones : les appeler ici bloquerait la
                # boucle, donc toute la conversation, pendant que le banc mesure.
                _fn = {'local': lambda: _rerank_local(question, textes),
                       'cohere': lambda: _rerank_cohere(question, textes, api_keys),
                       'voyage': lambda: _rerank_voyage(question, textes, api_keys),
                       'jina': lambda: _rerank_jina(question, textes, api_keys)}.get(nom)
                scores = await _aio.to_thread(_fn) if _fn else None
        except Exception as e:
            scores, note = None, f"Erreur : {e}"
        secondes = round(_time.perf_counter() - debut, 2)

        if not scores:
            resultats.append({
                'moteur': nom, 'libelle': info['libelle'], 'ok': False,
                'secondes': secondes,
                'note': note or "Pas de réponse exploitable de ce moteur.",
                'classement': []})
            continue

        # Le classement sémantique garde son ordre d'origine : ses scores ne se
        # jugent pas au seuil des réordonnanceurs.
        if nom == 'semantique':
            lignes = []
            for rang, (idx, sc) in enumerate(scores, 1):
                p = passages[idx]
                lignes.append({'rang': rang, 'passage': idx, 'score': round(float(sc), 3),
                               'retenu': rang <= 3, 'titre': (p.get('titre') or 'Document')[:200],
                               'source': (p.get('source') or '')[:300]})
        else:
            lignes = _classement_depuis_scores(scores, passages, seuil)

        retenus = sum(1 for l in lignes if l['retenu'])
        resultats.append({
            'moteur': nom, 'libelle': info['libelle'], 'ok': True,
            'secondes': secondes,
            'note': (f"{retenus} passage(s) au-dessus du seuil {seuil:.2f} "
                     f"sur {len(lignes)}." if nom != 'semantique' else
                     "Ordre d'origine ; les trois premiers sont ceux que NIMM "
                     "servirait sans réordonnanceur."),
            'classement': lignes[:max(1, int(top_n or 5))]})

    rapport = {
        'question': question,
        'seuil': seuil,
        'nb_passages': len(passages),
        'passages': [{'i': i,
                      'titre': (p.get('titre') or 'Document')[:200],
                      'source': (p.get('source') or '')[:300],
                      'extrait': (p.get('passage') or '')[:400]}
                     for i, p in enumerate(passages)],
        'moteurs': resultats,
    }
    rapport['texte'] = rapport_texte(rapport)
    return rapport


def rapport_texte(rapport):
    """Rapport en texte brut : lisible en braille, copiable, comparable dans le temps."""
    if not isinstance(rapport, dict) or rapport.get('erreur'):
        return (rapport or {}).get('erreur', '')
    l = []
    l.append(f"BANC D'ESSAI DU RÉORDONNANCEUR")
    l.append(f"Question : {rapport.get('question', '')}")
    l.append(f"Passages candidats : {rapport.get('nb_passages', 0)} — "
             f"seuil de pertinence : {rapport.get('seuil', 0):.2f}")
    l.append('')
    for m in rapport.get('moteurs', []):
        l.append(f"── {m.get('libelle', m.get('moteur', ''))} — "
                 + (f"{m.get('secondes', 0):.2f} s" if m.get('ok') else "indisponible"))
        l.append(f"   {m.get('note', '')}")
        for ligne in m.get('classement', []):
            marque = '✔' if ligne.get('retenu') else '·'
            l.append(f"   {marque} {ligne.get('rang')}. [{ligne.get('score')}] "
                     f"{ligne.get('titre', '')}"
                     + (f" — {ligne.get('source')}" if ligne.get('source') else ''))
        l.append('')
    ok = [m for m in rapport.get('moteurs', []) if m.get('ok') and m.get('moteur') != 'semantique']
    if ok:
        rapide = min(ok, key=lambda m: m.get('secondes', 99))
        l.append(f"Le plus rapide des réordonnanceurs : {rapide.get('libelle')} "
                 f"({rapide.get('secondes'):.2f} s). La pertinence, elle, se juge "
                 f"en lisant les titres ci-dessus : aucun chiffre ne dira à ta "
                 f"place si le bon document est remonté.")
    else:
        l.append("Aucun réordonnanceur n'a répondu : seule la recherche par sens "
                 "est mesurée ci-dessus.")
    return '\n'.join(l)
