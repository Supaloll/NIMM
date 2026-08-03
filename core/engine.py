# ============================================
# NIMM — core/engine.py
# Moteur LLM multi-providers
# Providers : Anthropic / DeepSeek / Gemini / OpenAI / Ollama / OpenRouter
# ============================================

import os
import re
import json
import httpx
from typing import Optional

def _anthropic_cache_enabled() -> bool:
    """Mise en cache automatique des prompts Anthropic (réglage, actif par défaut).

    Un seul champ `cache_control` au niveau supérieur : l'API pose elle-même le point
    de rupture sur le dernier bloc cachable et l'avance au fil de la conversation.
    Idéal ici — NIMM renvoie à chaque tour un long system prompt + 80 messages.
    """
    try:
        from core.database import get_setting
        return str(get_setting('anthropic_cache_active', '1')) not in ('0', 'false', 'False')
    except Exception:
        return True


def _anthropic_mcp_servers() -> list:
    """Serveurs MCP distants actifs, au format attendu par le connecteur.

    Anthropic se connecte lui-même aux serveurs et expose leurs outils au modèle.
    Renvoie [] si aucun n'est configuré : dans ce cas AUCUN champ n'est ajouté au
    payload, et rien ne change pour les autres fournisseurs.
    """
    try:
        from core.database import list_mcp_servers
        out = []
        for s in list_mcp_servers(inclure_jeton=True):
            if not s.get('actif', True) or not s.get('url'):
                continue
            srv = {'type': 'url', 'url': s['url'], 'name': s.get('name', 'mcp')}
            if s.get('jeton'):
                srv['authorization_token'] = s['jeton']
            out.append(srv)
        return out
    except Exception as e:
        print(f"[ENGINE] Serveurs MCP ignorés : {e}")
        return []


def _anthropic_desactiver_cache(raison: str) -> None:
    """Coupe la mise en cache après un refus de l'API, pour ne pas casser le chat.

    Le champ `cache_control` part sur TOUS les appels Anthropic : si l'API le
    refusait (compte, version, plateforme), plus aucune conversation ne passerait.
    On le désactive donc durablement au premier refus, et on le dit clairement.
    """
    try:
        from core.database import set_setting
        set_setting('anthropic_cache_active', '0')
    except Exception:
        pass
    _m = ("Mise en cache des prompts refusée par l'API (" + raison
          + ") — désactivée automatiquement. Réactivable dans les réglages.")
    print(f"[ENGINE] ⚠️ {_m}")
    try:
        from core.database import add_diagnostic
        add_diagnostic('coûts', _m)
    except Exception:
        pass


def _anthropic_cache_fallback(exc) -> bool:
    """Vrai si l'erreur vient du champ de cache : on réessaie alors sans lui."""
    try:
        import httpx as _h
        if not isinstance(exc, _h.HTTPStatusError) or exc.response.status_code != 400:
            return False
        corps = (exc.response.text or '').lower()
    except Exception:
        return False
    if 'cache_control' in corps or 'cache control' in corps:
        _anthropic_desactiver_cache('400 sur cache_control')
        return True
    return False


# Une réponse coupée net n'est pas visible quand on lit à la synthèse vocale ou en
# braille : on l'annonce explicitement en fin de texte plutôt que de laisser croire
# que le modèle a fini de parler.
_AVIS_STOP = {
    'max_tokens': "\n\n⚠️ Réponse interrompue : la limite de longueur a été atteinte. "
                  "Demande « continue » pour la suite.",
    'refusal':    "\n\n⚠️ Le modèle a préféré ne pas poursuivre cette réponse.",
    'pause_turn': "\n\n⏸️ Tour mis en pause par le fournisseur (recherche longue). "
                  "Relance pour obtenir la suite.",
}


def _avis_stop_reason(stop_reason: str) -> str:
    """Message à ajouter à la réponse selon la raison d'arrêt ('' si fin normale)."""
    return _AVIS_STOP.get((stop_reason or '').strip(), '')


# Certains modèles (Llama et dérivés notamment) écrivent leurs appels d'outils
# EN TEXTE au lieu du champ structuré : « <function=nom>{"arg": …}</function> ».
# Sans traitement, l'utilisateur voit passer ce charabia à la place d'une réponse.
_RE_APPEL_TEXTE = re.compile(
    r'<function\s*=\s*([A-Za-z0-9_\-]+)\s*>\s*(\{.*?\})\s*(?:</function>)?',
    re.DOTALL)


def _contient_appel_texte(texte: str) -> bool:
    return bool(texte) and '<function=' in texte


def _parse_appels_texte(texte: str) -> list:
    """Extrait les appels d'outils écrits en texte. Renvoie [{'id','name','args'}]."""
    appels = []
    for i, m in enumerate(_RE_APPEL_TEXTE.finditer(texte or '')):
        nom = m.group(1).strip()
        try:
            args = json.loads(m.group(2))
        except Exception:
            continue                      # JSON illisible : on ignore cet appel
        if isinstance(args, dict):
            appels.append({'id': f'txt_{i}_{nom}', 'name': nom, 'args': args})
    return appels


# Une panne de fournisseur affichait son message technique brut, en anglais, lu tel
# quel par la synthèse vocale. On la traduit, et on distingue ce qui est
# RÉCUPÉRABLE (essayer un autre fournisseur a du sens) de ce qui ne l'est pas
# (clé absente : changer de fournisseur ne réglera rien).
def classer_erreur_fournisseur(exc, provider: str = '') -> dict:
    """{'categorie', 'message', 'recuperable'} à partir d'une exception d'appel."""
    txt = ''
    code = 0
    try:
        rep = getattr(exc, 'response', None)
        if rep is not None:
            code = int(getattr(rep, 'status_code', 0) or 0)
            txt = (getattr(rep, 'text', '') or '')[:800]
    except Exception:
        pass
    txt = (txt + ' ' + str(exc)).lower()
    nom = provider or 'le fournisseur'

    if code == 401 or 'invalid x-api-key' in txt or 'invalid api key' in txt or 'unauthorized' in txt:
        return {'categorie': 'clé', 'recuperable': False,
                'message': f"La clé API de {nom} est refusée. Vérifie-la dans les réglages."}
    if code == 402 or 'credit balance' in txt or 'insufficient' in txt or 'quota' in txt:
        return {'categorie': 'crédit', 'recuperable': True,
                'message': f"Le crédit de {nom} est épuisé."}
    if code == 429 or 'rate limit' in txt or 'too many requests' in txt:
        return {'categorie': 'débit', 'recuperable': True,
                'message': f"{nom} limite le débit : trop de requêtes en peu de temps."}
    if code in (500, 502, 503, 529) or 'overloaded' in txt or 'service unavailable' in txt:
        return {'categorie': 'surcharge', 'recuperable': True,
                'message': f"{nom} est momentanément surchargé ou indisponible."}
    if 'timeout' in txt or 'timed out' in txt:
        return {'categorie': 'délai', 'recuperable': True,
                'message': f"{nom} n'a pas répondu dans le délai imparti."}
    if 'connect' in txt or 'network' in txt or 'name resolution' in txt:
        return {'categorie': 'réseau', 'recuperable': True,
                'message': "La connexion réseau a échoué."}
    return {'categorie': 'erreur', 'recuperable': False,
            'message': f"Erreur inattendue de {nom} : {str(exc)[:200]}"}


# ══════════════════════════════════════════
# FOURNISSEURS COMPATIBLES OpenAI
# ══════════════════════════════════════════
#
# POURQUOI CETTE TABLE
# L'adresse de base et le modèle de repli de ces fournisseurs étaient recopiés
# à TROIS endroits : l'appel direct, le flux, et le flux avec outils. Trois
# copies, c'est la garantie qu'un ajout n'en touche que deux — un fournisseur
# qui répond en direct mais reste muet en flux, sans erreur nulle part.
# Source unique désormais : ajouter un fournisseur, c'est ajouter une ligne ici.
#
# `outils` dit si le fournisseur sait exécuter des appels d'outils. Groq et
# Cerebras servent des modèles à poids ouverts dont le support varie d'un modèle
# à l'autre : on ne le promet donc pas, et NIMM retombe proprement sur un flux
# sans outils plutôt que d'envoyer une requête qui serait ignorée.
FOURNISSEURS_OPENAI_COMPAT = {
    'deepseek':   {'base': 'https://api.deepseek.com/v1',     'modele': 'deepseek-v4-flash',
                   'outils': True},
    'openai':     {'base': 'https://api.openai.com/v1',       'modele': 'gpt-4o-mini',
                   'outils': True},
    'openrouter': {'base': 'https://openrouter.ai/api/v1',    'modele': 'openai/gpt-4o-mini',
                   'outils': True},
    'mistral':    {'base': 'https://api.mistral.ai/v1',       'modele': 'mistral-small-latest',
                   'outils': True},
    # Inférence à très faible latence. Le temps avant le PREMIER mot compte
    # double quand la réponse est écoutée plutôt que lue.
    'groq':       {'base': 'https://api.groq.com/openai/v1',  'modele': 'llama-3.3-70b-versatile',
                   'outils': False},
    'cerebras':   {'base': 'https://api.cerebras.ai/v1',      'modele': 'llama-3.3-70b',
                   'outils': False},
}

def _base_openai_compat(provider: str) -> str:
    return FOURNISSEURS_OPENAI_COMPAT.get(provider, {}).get('base', '')

def _modele_openai_compat(provider: str) -> str:
    return FOURNISSEURS_OPENAI_COMPAT.get(provider, {}).get('modele', '')


def fournisseur_de_secours(provider_courant: str, api_keys: dict = None) -> str:
    """Premier fournisseur configuré autre que celui qui vient d'échouer, ou ''."""
    ordre = ['mistral', 'anthropic', 'openai', 'gemini', 'deepseek', 'openrouter',
             'groq', 'cerebras']
    for p in ordre:
        if p == (provider_courant or '').lower():
            continue
        if get_api_key(p, api_keys):
            return p
    return ''


# Certains modèles de raisonnement n'acceptent NI les appels d'outils NI les
# paramètres d'échantillonnage (deepseek-reasoner : « Not Supported Features:
# Function Calling, FIM ; Not Supported Parameters: temperature, top_p… »).
# Leur envoyer quand même produit au mieux une requête ignorée, au pire un refus.
_MODELES_SANS_OUTILS = ('deepseek-reasoner',)


# Les modèles de raisonnement OpenAI (série o) refusent `max_tokens` — il faut
# `max_completion_tokens` — et n'acceptent pas `temperature`. Le catalogue de
# modèles interrogé en direct les propose désormais : sans garde, les choisir
# produirait une erreur 400 incompréhensible.
def _modele_raisonnement_openai(model: str) -> bool:
    import re as _re_o
    return bool(_re_o.match(r'^o\d', (model or '').lower()))


# Les caches de contexte sont AUTOMATIQUES chez Gemini (séries 2.5+) et DeepSeek :
# rien à activer, et 90 % de remise sur les tokens servis par le cache. Mais chacun
# le rapporte dans ses propres champs. Ne pas les distinguer surévalue la dépense
# — symétrique du défaut inverse trouvé sur le cache Anthropic.
_REMISE_CACHE = 0.1        # tokens relus = 10 % du prix plein


def _gemini_tokens_entree(meta: dict) -> int:
    """Tokens d'entrée Gemini en équivalent plein tarif (`cachedContentTokenCount`
    est inclus dans `promptTokenCount` et facturé 10 %)."""
    m = meta or {}
    total = int(m.get('promptTokenCount', 0) or 0)
    caches = int(m.get('cachedContentTokenCount', 0) or 0)
    caches = min(caches, total)
    return int(round((total - caches) + _REMISE_CACHE * caches))


def _oai_tokens_entree(usage: dict) -> int:
    """Idem pour les fournisseurs compatibles OpenAI. DeepSeek éclate l'entrée en
    `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` ; ailleurs on retombe
    sur `prompt_tokens`."""
    u = usage or {}
    hit = int(u.get('prompt_cache_hit_tokens', 0) or 0)
    miss = int(u.get('prompt_cache_miss_tokens', 0) or 0)
    if hit or miss:
        return int(round(miss + _REMISE_CACHE * hit))
    return int(u.get('prompt_tokens', 0) or 0)


def _gemini_tokens_sortie(meta: dict) -> int:
    """Tokens de sortie FACTURÉS par Gemini = réponse + PENSÉE.

    La « pensée » est active par défaut sur les séries 3.x et 2.5, et sa
    tarification s'ajoute à celle de la réponse (`thoughtsTokenCount` est distinct
    de `candidatesTokenCount`). Ne compter que la réponse sous-évalue la dépense.
    """
    m = meta or {}
    return int(m.get('candidatesTokenCount', 0) or 0) + int(m.get('thoughtsTokenCount', 0) or 0)


def _modele_sans_outils(model: str) -> bool:
    m = (model or '').lower()
    return any(m.startswith(x) for x in _MODELES_SANS_OUTILS)


def _anthropic_billable_input(usage: dict) -> int:
    """Tokens d'entrée FACTURABLES, exprimés en équivalent « tokens plein tarif ».

    Avec la mise en cache, `input_tokens` ne compte que le non-caché : l'écriture de
    cache coûte 1,25× et la relecture 0,1×. Sans cette pondération, le tableau des
    coûts sous-estimerait l'écriture et surestimerait massivement la relecture.
    """
    u = usage or {}
    base = int(u.get('input_tokens', 0) or 0)
    creation = int(u.get('cache_creation_input_tokens', 0) or 0)
    read = int(u.get('cache_read_input_tokens', 0) or 0)
    return int(round(base + 1.25 * creation + 0.1 * read))


def _log(provider: str, model: str, tokens_in: int, tokens_out: int, pipeline: str = 'chat'):
    """Log silencieux — ne bloque jamais le pipeline si DB indisponible."""
    try:
        from core.database import log_cost
        log_cost(provider, model or '', tokens_in, tokens_out, pipeline)
    except Exception:
        pass

# ── Clés API (priorité : base de données > .env) ──
def get_api_key(provider: str, db_keys: dict = None) -> Optional[str]:
    if db_keys and db_keys.get(provider):
        return db_keys[provider]
    env_map = {
        'anthropic':  'ANTHROPIC_API_KEY',
        'deepseek':   'DEEPSEEK_API_KEY',
        'gemini':     'GEMINI_API_KEY',
        'openai':     'OPENAI_API_KEY',
        'openrouter': 'OPENROUTER_API_KEY',
        'mistral':    'MISTRAL_API_KEY',
        'tavily':     'TAVILY_API_KEY',
        'groq':       'GROQ_API_KEY',
        'cerebras':   'CEREBRAS_API_KEY',
    }
    return os.getenv(env_map.get(provider, ''))


# ══════════════════════════════════════════
# APPEL LLM PRINCIPAL
# ══════════════════════════════════════════

_PROVIDER_DEFAULT_MODEL = {
    'anthropic':  'claude-sonnet-4-6',
    'deepseek':   'deepseek-v4-flash',
    'openai':     'gpt-4o-mini',
    'openrouter': 'openai/gpt-4o-mini',
    'mistral':    'mistral-small-latest',
    'gemini':     'gemini-3.5-flash',
    'ollama':     'llama3.1:8b',
    'groq':       'llama-3.3-70b-versatile',
    'cerebras':   'llama-3.3-70b',
}

# Préfixe de nom de modèle → fournisseur propriétaire (détection d'incohérence)
_MODEL_OWNER = {
    'claude': 'anthropic', 'deepseek': 'deepseek', 'gpt': 'openai',
    'o1': 'openai', 'o3': 'openai', 'o4': 'openai',
    'mistral': 'mistral', 'ministral': 'mistral', 'pixtral': 'mistral', 'codestral': 'mistral', 'pixtral': 'mistral',
    'magistral': 'mistral', 'voxtral': 'mistral', 'devstral': 'mistral', 'codestral': 'mistral',
    'gemini': 'gemini',
}


def _resolve_model(provider, model):
    """Évite les 400 « modèle invalide » au changement de fournisseur : si le modèle
    sélectionné appartient visiblement à un autre fournisseur, on retombe sur le
    modèle par défaut du fournisseur courant. Les modèles inconnus (tags Ollama,
    modèles OpenRouter en vendor/x) sont laissés intacts."""
    provider = (provider or '').lower()
    if not model:
        return _PROVIDER_DEFAULT_MODEL.get(provider)
    if provider == 'openrouter':
        return model
    ml = model.lower()
    for prefix, owner in _MODEL_OWNER.items():
        if ml.startswith(prefix):
            return model if owner == provider else _PROVIDER_DEFAULT_MODEL.get(provider, model)
    return model


# ══════════════════════════════════════════
#  Comptage de tokens et catalogue de modèles
# ══════════════════════════════════════════

# Fournisseurs compatibles OpenAI acceptant response_format json_schema. Ailleurs on
# n'envoie RIEN : un paramètre inconnu ferait échouer l'appel, et l'appelant garde de
# toute façon son analyse de repli.
_JSON_SCHEMA_PROVIDERS = {'openai', 'mistral', 'openrouter'}


def _oai_response_format(provider_name: str, output_schema: dict):
    """Bloc response_format pour un provider OpenAI-compat, ou None si non supporté."""
    if not output_schema or (provider_name or '').lower() not in _JSON_SCHEMA_PROVIDERS:
        return None
    return {'response_format': {
        'type': 'json_schema',
        'json_schema': {'name': 'reponse', 'strict': True, 'schema': output_schema},
    }}


async def count_tokens(provider: str, text: str, model: str = None, api_keys: dict = None) -> int:
    """Tokens d'entrée d'un texte chez `provider`, SANS envoyer la requête.

    Anthropic et Gemini exposent un point de comptage ; ailleurs on renvoie -1
    (« inconnu »), jamais une estimation inventée.
    """
    provider = (provider or '').lower()
    if provider == 'anthropic':
        return await count_tokens_anthropic([{'role': 'user', 'content': text or ''}],
                                            model=model, api_keys=api_keys)
    if provider == 'gemini':
        api_key = get_api_key('gemini', api_keys)
        if not api_key:
            return -1
        m = _resolve_model('gemini', model)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f'https://generativelanguage.googleapis.com/v1beta/models/{m}:countTokens?key={api_key}',
                    json={'contents': [{'parts': [{'text': text or ''}]}]})
                r.raise_for_status()
                return int(r.json().get('totalTokens', -1))
        except Exception as e:
            print(f"[ENGINE] Comptage de tokens Gemini indisponible : {e}")
            return -1
    return -1


async def answer_with_citations_anthropic(passages: list, question: str, model: str = None,
                                api_keys: dict = None, max_tokens: int = 2000) -> str:
    """Répond à `question` À PARTIR des passages fournis, en citant la phrase exacte.

    Chaque passage devient un document citable distinct : Claude rattache alors
    chaque affirmation à sa source, et le texte cité est extrait par l'API (donc
    garanti présent dans le document, contrairement à une citation demandée par
    prompt). Décisif pour vérifier une réponse qu'on ne peut pas relire soi-même.

    NB : les citations sont incompatibles avec les sorties structurées — ne jamais
    combiner `citations` et `output_config.format` (erreur 400).
    """
    api_key = get_api_key('anthropic', api_keys)
    if not api_key:
        return "[Citations : clé Anthropic non configurée.]"
    if not passages:
        return "[Aucun passage pertinent dans la base de connaissances.]"
    contenu = []
    for p in passages[:8]:
        texte = (p.get('passage') or '').strip()
        if not texte:
            continue
        contenu.append({
            'type': 'document',
            'source': {'type': 'text', 'media_type': 'text/plain', 'data': texte},
            'title': (p.get('titre') or 'Document')[:200],
            'context': (p.get('source') or '')[:500],   # transmis, mais non citable
            'citations': {'enabled': True},
        })
    if not contenu:
        return "[Aucun passage exploitable.]"
    contenu.append({'type': 'text', 'text': (question or '').strip()
                    or "Que disent ces documents ?"})
    payload = {'model': _resolve_model('anthropic', model), 'max_tokens': max_tokens,
               'messages': [{'role': 'user', 'content': contenu}]}
    if _anthropic_cache_enabled():
        payload['cache_control'] = {'type': 'ephemeral'}
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                'https://api.anthropic.com/v1/messages',
                headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01',
                         'content-type': 'application/json'},
                json=payload)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return f"[Réponse citée impossible ({e})]"
    usage = data.get('usage', {})
    _log('anthropic', payload['model'], _anthropic_billable_input(usage),
         usage.get('output_tokens', 0), 'citations')
    txt, cites = [], []
    for b in data.get('content', []):
        if b.get('type') != 'text':
            continue
        txt.append(b.get('text', ''))
        for c in (b.get('citations') or []):
            paire = ((c.get('document_title') or 'Document'),
                     (c.get('cited_text') or '').strip().replace('\n', ' ')[:200])
            if paire[1] and paire not in cites:
                cites.append(paire)
    sortie = ''.join(txt) + _avis_stop_reason(data.get('stop_reason', ''))
    if cites:
        sortie += '\n\nPassages cités :\n' + '\n'.join(
            f"- {t} : « {e} »" for t, e in cites[:15])
    return sortie


VERIFY_SYSTEM_PROMPT = (
    "Tu vérifies un texte à l'aide de recherches web. Procède ainsi :\n"
    "1. Repère les affirmations FACTUELLES et vérifiables (dates, chiffres, noms, "
    "événements). Ignore les opinions, les conseils et les formulations vagues.\n"
    "2. Cherche sur le web pour les confronter.\n"
    "3. Rends un verdict COURT et lisible à voix haute, dans cet ordre : d'abord ce "
    "qui est ERRONÉ ou douteux, ensuite ce qui est confirmé, enfin ce que tu n'as pas "
    "pu vérifier. Une ligne par point, sans tableau ni mise en forme complexe.\n"
    "Si tout est correct, dis-le en une phrase. Si le texte ne contient aucune "
    "affirmation vérifiable, dis-le simplement. Ne réécris jamais le texte."
)


async def verify_claims_anthropic(texte: str, model: str = None, api_keys: dict = None,
                                  max_tokens: int = 1500) -> dict:
    """Vérifie les affirmations factuelles d'un texte par recherche web.

    Rendu pour quelqu'un qui ne peut pas survoler une réponse du regard : les
    erreurs d'abord, sources listées ensuite. Renvoie {'verdict', 'sources'}.
    """
    api_key = get_api_key('anthropic', api_keys)
    if not api_key:
        return {'verdict': "[Vérification : clé Anthropic non configurée.]", 'sources': []}
    texte = (texte or '').strip()
    if len(texte) < 40:
        return {'verdict': "[Texte trop court pour être vérifié.]", 'sources': []}
    payload = {
        'model': _resolve_model('anthropic', model),
        'max_tokens': max_tokens,
        'system': VERIFY_SYSTEM_PROMPT,
        'messages': [{'role': 'user',
                      'content': "Vérifie ce texte :\n\n" + texte[:6000]}],
        'tools': [{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 4}],
    }
    if _anthropic_cache_enabled():
        payload['cache_control'] = {'type': 'ephemeral'}
    txt, sources, vus = [], [], set()
    entete = {'x-api-key': api_key, 'anthropic-version': '2023-06-01',
              'content-type': 'application/json'}
    # La recherche web est un outil SERVEUR : le tour peut rendre la main en
    # « pause_turn » avant d'avoir rédigé sa conclusion. Il faut alors relancer
    # en renvoyant ce qui a déjà été produit — sinon on n'obtient aucun verdict.
    stop = ''
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            for _tour in range(4):
                r = await client.post('https://api.anthropic.com/v1/messages',
                                      headers=entete, json=payload)
                r.raise_for_status()
                data = r.json()
                usage = data.get('usage', {})
                _log('anthropic', payload['model'], _anthropic_billable_input(usage),
                     usage.get('output_tokens', 0), 'verification')
                contenu = data.get('content', []) or []
                for b in contenu:
                    if b.get('type') != 'text':
                        continue
                    txt.append(b.get('text', ''))
                    for c in (b.get('citations') or []):
                        url = c.get('url', '')
                        if url and url not in vus:
                            vus.add(url)
                            sources.append({'url': url, 'title': c.get('title') or url,
                                            'snippet': (c.get('cited_text') or '')[:200]})
                stop = data.get('stop_reason', '')
                if stop != 'pause_turn':
                    break
                # On relance en conservant le contexte déjà produit.
                payload['messages'] = payload['messages'] + [
                    {'role': 'assistant', 'content': contenu}]
    except Exception as e:
        return {'verdict': f"[Vérification impossible ({e})]", 'sources': sources}

    verdict = (''.join(txt) + _avis_stop_reason(stop)).strip()
    if not verdict:
        verdict = ("Aucune affirmation vérifiable n'a pu être évaluée dans ce message "
                   "(il ne contient peut-être pas de fait à contrôler).")
    return {'verdict': verdict, 'sources': sources}


# Reprendre une réponse tronquée en envoyant « Continue. » fait redémarrer le
# modèle : préambule (« Bien sûr, je reprends… »), redites, parfois une phrase
# recommencée. Trois fournisseurs savent reprendre EXACTEMENT où ils se sont
# arrêtés — en leur donnant le début de leur propre réponse à poursuivre.
#   • Anthropic : préremplissage natif (dernier message = assistant).
#   • Mistral et DeepSeek : champ `prefix` sur le dernier message assistant
#     (DeepSeek exige son point d'entrée bêta).
_PREFIXE_SUPPORTE = {'anthropic', 'mistral', 'deepseek'}


def supporte_prefixe(provider: str) -> bool:
    return (provider or '').lower() in _PREFIXE_SUPPORTE


async def continuer_reponse_stream(messages: list, prefixe: str, provider: str,
                                   model: str = None, system_prompt: str = None,
                                   max_tokens: int = 1024, temperature: float = 0.7,
                                   api_keys: dict = None):
    """Poursuit une réponse tronquée, sans couture quand le fournisseur le permet.

    Repli sur un tour « Continue. » pour les autres : le comportement d'avant.
    """
    provider = (provider or '').lower()
    prefixe = (prefixe or '').strip()

    if not prefixe or not supporte_prefixe(provider):
        async for t in call_llm_stream(
                messages=messages + [{'role': 'user', 'content': 'Continue.'}],
                provider=provider, model=model, system_prompt=system_prompt,
                max_tokens=max_tokens, temperature=temperature, api_keys=api_keys):
            yield t
        return

    if provider == 'anthropic':
        # Le dernier message étant de l'assistant, Claude le poursuit tel quel.
        async for t in _call_anthropic_stream(
                messages + [{'role': 'assistant', 'content': prefixe}],
                _resolve_model('anthropic', model), system_prompt, max_tokens,
                temperature, api_keys, None):
            yield t
        return

    # Mistral / DeepSeek : dernier message assistant marqué `prefix`.
    api_key = get_api_key(provider, api_keys)
    if not api_key:
        raise ValueError(f"Clé API {provider} manquante.")
    base = ('https://api.deepseek.com/beta' if provider == 'deepseek'
            else 'https://api.mistral.ai/v1')
    oai = ([{'role': 'system', 'content': system_prompt}] if system_prompt else [])
    oai += [{'role': m['role'], 'content': m.get('content', '')}
            for m in messages if m.get('role') != 'system']
    oai.append({'role': 'assistant', 'content': prefixe, 'prefix': True})
    payload = {'model': _resolve_model(provider, model), 'messages': oai,
               'max_tokens': max_tokens, 'temperature': temperature, 'stream': True}
    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream('POST', f'{base}/chat/completions',
                                 headers={'Authorization': f'Bearer {api_key}',
                                          'Content-Type': 'application/json'},
                                 json=payload) as r:
            r.raise_for_status()
            async for ligne in r.aiter_lines():
                if not ligne.startswith('data:'):
                    continue
                bout = ligne[5:].strip()
                if bout == '[DONE]':
                    break
                try:
                    d = json.loads(bout)
                    ch = (d.get('choices') or [{}])[0]
                    morceau = (ch.get('delta') or {}).get('content', '')
                    if morceau:
                        yield morceau
                    if ch.get('finish_reason') == 'length':
                        yield {'__truncated__': True}
                except Exception:
                    continue


_GEMINI_CACHE_MIN_TOKENS = 2048   # plancher imposé par l'API (2.5) ; 4096 sur 3.5


async def create_cache_gemini(contenu: str, titre: str = '', consigne: str = '',
                              duree_h: float = 1.0, model: str = None,
                              api_keys: dict = None) -> dict:
    """Épingle un long texte chez Gemini pour l'interroger ensuite à tarif réduit.

    C'est le cache EXPLICITE, à ne pas confondre avec le cache implicite déjà
    exploité ailleurs : ici on paie une fois la lecture, puis chaque question
    ne coûte plus qu'une fraction. Utile pour « je charge une étude de cent
    pages et je pose dix questions dessus ».
    """
    api_key = get_api_key('gemini', api_keys)
    if not api_key:
        return {'ok': False, 'erreur': "Clé Gemini non configurée."}
    contenu = (contenu or '').strip()
    if not contenu:
        return {'ok': False, 'erreur': "Rien à épingler : le contenu est vide."}

    m = _resolve_model('gemini', model)
    nb = await count_tokens('gemini', contenu, model=m, api_keys=api_keys)
    if nb != -1 and nb < _GEMINI_CACHE_MIN_TOKENS:
        return {'ok': False, 'nb_tokens': nb, 'erreur': (
            "Document trop court pour être épinglé : Gemini exige au moins "
            f"{_GEMINI_CACHE_MIN_TOKENS} jetons, celui-ci en fait environ {nb}. "
            "Pour un texte de cette taille, une lecture normale coûte moins cher "
            "que la mise en cache.")}

    ttl = max(60, int(float(duree_h or 1.0) * 3600))
    payload = {
        'model': f'models/{m}',
        'contents': [{'role': 'user', 'parts': [{'text': contenu}]}],
        'ttl': f'{ttl}s',
        'displayName': (titre or 'Document NIMM')[:120],
    }
    if (consigne or '').strip():
        payload['systemInstruction'] = {'parts': [{'text': consigne.strip()}]}
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(
                f'https://generativelanguage.googleapis.com/v1beta/cachedContents?key={api_key}',
                json=payload)
            if r.status_code >= 400:
                return {'ok': False, 'erreur': _gemini_message_erreur(r)}
            data = r.json()
    except Exception as e:
        return {'ok': False, 'erreur': f"Mise en cache impossible ({e})"}

    return {
        'ok': True,
        'name': data.get('name', ''),
        'model': m,
        'titre': data.get('displayName', titre),
        'expire': data.get('expireTime', ''),
        'nb_tokens': int((data.get('usageMetadata') or {}).get('totalTokenCount') or nb or 0),
    }


def _gemini_message_erreur(r) -> str:
    """Traduit une erreur HTTP Gemini en une phrase lisible à la synthèse vocale."""
    try:
        det = (r.json().get('error') or {}).get('message') or ''
    except Exception:
        det = (r.text or '')[:300]
    if r.status_code == 400 and 'token' in det.lower():
        return ("Gemini refuse : le contenu est trop court pour un cache explicite "
                f"(minimum {_GEMINI_CACHE_MIN_TOKENS} jetons).")
    if r.status_code in (401, 403):
        return "Gemini refuse la clé d'API (401/403)."
    if r.status_code == 404:
        return "Ce cache n'existe plus : il a sans doute expiré."
    if r.status_code == 429:
        return "Gemini est saturé ou le quota est atteint (429). Réessaie plus tard."
    return f"Erreur Gemini {r.status_code} : {det[:200]}"


async def ask_cache_gemini(cache_name: str, question: str, model: str = None,
                           api_keys: dict = None, max_tokens: int = 4000) -> str:
    """Pose une question à un document déjà épinglé (cache explicite Gemini)."""
    api_key = get_api_key('gemini', api_keys)
    if not api_key:
        return "[Clé Gemini non configurée.]"
    if not (cache_name or '').strip():
        return "[Aucun document épinglé indiqué.]"
    m = _resolve_model('gemini', model)
    payload = {'contents': [{'role': 'user', 'parts': [{'text': question or ''}]}],
               'cachedContent': cache_name,
               'generationConfig': {'maxOutputTokens': max_tokens}}
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(
                f'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}',
                json=payload)
            if r.status_code >= 400:
                return f"[{_gemini_message_erreur(r)}]"
            data = r.json()
    except Exception as e:
        return f"[Interrogation impossible ({e})]"

    meta = data.get('usageMetadata', {}) or {}
    _log('gemini', m, _gemini_tokens_entree(meta), _gemini_tokens_sortie(meta), 'cache')
    cand = (data.get('candidates') or [{}])[0]
    texte = ''.join(p.get('text', '') for p in (cand.get('content', {}).get('parts') or [])
                    if 'text' in p)
    if cand.get('finishReason') == 'MAX_TOKENS':
        texte += "\n\n⚠️ Réponse interrompue : la limite de longueur a été atteinte."
    return texte.strip() or "[Aucune réponse produite.]"


async def list_caches_gemini(api_keys: dict = None) -> list:
    """Liste les documents épinglés côté Gemini (métadonnées seules : le contenu
    n'est pas relisible, c'est une garantie de l'API)."""
    api_key = get_api_key('gemini', api_keys)
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(
                f'https://generativelanguage.googleapis.com/v1beta/cachedContents?key={api_key}')
            r.raise_for_status()
            items = r.json().get('cachedContents') or []
    except Exception:
        return []
    return [{'name': c.get('name', ''), 'titre': c.get('displayName', ''),
             'model': (c.get('model', '') or '').replace('models/', ''),
             'expire': c.get('expireTime', ''),
             'nb_tokens': int((c.get('usageMetadata') or {}).get('totalTokenCount') or 0)}
            for c in items]


async def delete_cache_gemini(cache_name: str, api_keys: dict = None) -> bool:
    """Libère un document épinglé (on cesse de payer le stockage)."""
    api_key = get_api_key('gemini', api_keys)
    if not api_key or not (cache_name or '').strip():
        return False
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.delete(
                f'https://generativelanguage.googleapis.com/v1beta/{cache_name}?key={api_key}')
            return r.status_code < 400 or r.status_code == 404
    except Exception:
        return False


async def describe_audio_gemini(source: str, question: str = '', model: str = None,
                                api_keys: dict = None, max_tokens: int = 3000) -> str:
    """Décrit un fichier AUDIO : au-delà des paroles, ce qui s'entend.

    Différent d'une transcription (Whisper le fait déjà, en local) : ici on veut
    qui parle, le ton, les bruits, la musique, les silences — tout ce qu'un
    document sonore porte et qu'un texte brut perd.
    """
    api_key = get_api_key('gemini', api_keys)
    if not api_key:
        return "[Audio : clé Gemini non configurée.]"
    src_txt = (source or '').strip()
    if not src_txt:
        return "[Audio : aucun fichier ni lien fourni.]"

    consigne = (question or '').strip() or (
        "Décris ce document sonore : qui parle et sur quel ton, ce qui est dit "
        "(transcris les passages importants), les bruits de fond, la musique, les "
        "silences marquants. Donne des repères de temps (minute:seconde). Sépare "
        "clairement la TRANSCRIPTION de tes OBSERVATIONS. N'invente rien.")

    if src_txt.lower().startswith(('http://', 'https://')):
        partie = {'file_data': {'file_uri': src_txt}}
    else:
        import base64 as _b64, os as _os, mimetypes as _mt
        if not _os.path.isfile(src_txt):
            return f"[Audio introuvable : {src_txt}]"
        if _os.path.getsize(src_txt) > 18 * 1024 * 1024:
            return ("[Audio trop volumineux pour un envoi direct (plus de 18 Mo). "
                    "Fournis un lien, ou découpe-le.]")
        mime = _mt.guess_type(src_txt)[0] or 'audio/mpeg'
        with open(src_txt, 'rb') as fh:
            partie = {'inline_data': {'mime_type': mime,
                                      'data': _b64.standard_b64encode(fh.read()).decode()}}

    m = _resolve_model('gemini', model)
    payload = {'contents': [{'parts': [partie, {'text': consigne}]}],
               'generationConfig': {'maxOutputTokens': max_tokens}}
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post(
                f'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}',
                json=payload)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return f"[Audio : description impossible ({e})]"

    meta = data.get('usageMetadata', {}) or {}
    _log('gemini', m, _gemini_tokens_entree(meta), _gemini_tokens_sortie(meta), 'audio')
    cand = (data.get('candidates') or [{}])[0]
    texte = ''.join(p.get('text', '') for p in (cand.get('content', {}).get('parts') or [])
                    if 'text' in p)
    if cand.get('finishReason') == 'MAX_TOKENS':
        texte += "\n\n⚠️ Description interrompue : la limite de longueur a été atteinte."
    return texte.strip() or "[Aucune description produite.]"


async def describe_video_gemini(source: str, question: str = '', model: str = None,
                                api_keys: dict = None, max_tokens: int = 3000) -> str:
    """Décrit une vidéo — fichier local ou lien YouTube — avec repères de temps.

    Une vidéo est le contenu le plus opaque qui soit quand on ne voit pas : la
    bande-son ne dit presque jamais ce qui est montré. Gemini accepte une vidéo
    en ligne (moins de 20 Mo) ou une URL YouTube telle quelle.
    """
    api_key = get_api_key('gemini', api_keys)
    if not api_key:
        return "[Vidéo : clé Gemini non configurée.]"
    src_txt = (source or '').strip()
    if not src_txt:
        return "[Vidéo : aucun fichier ni lien fourni.]"

    consigne = (question or '').strip() or (
        "Décris cette vidéo pour quelqu'un qui ne la voit pas : ce qui est montré, "
        "le texte affiché à l'écran, les personnes et leurs actions. Donne des repères "
        "de temps (minute:seconde) pour pouvoir s'y retrouver. Sépare clairement ce qui "
        "est VU de ce qui est DIT. Sois factuel, n'invente rien.")

    if src_txt.lower().startswith(('http://', 'https://')):
        partie = {'file_data': {'file_uri': src_txt}}
    else:
        import base64 as _b64, os as _os, mimetypes as _mt
        if not _os.path.isfile(src_txt):
            return f"[Vidéo introuvable : {src_txt}]"
        if _os.path.getsize(src_txt) > 18 * 1024 * 1024:
            return ("[Vidéo trop volumineuse pour un envoi direct (plus de 18 Mo). "
                    "Fournis un lien, ou découpe-la.]")
        mime = _mt.guess_type(src_txt)[0] or 'video/mp4'
        with open(src_txt, 'rb') as fh:
            partie = {'inline_data': {'mime_type': mime,
                                      'data': _b64.standard_b64encode(fh.read()).decode()}}

    m = _resolve_model('gemini', model)
    payload = {'contents': [{'parts': [partie, {'text': consigne}]}],
               'generationConfig': {'maxOutputTokens': max_tokens}}
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post(
                f'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}',
                json=payload)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return f"[Vidéo : description impossible ({e})]"

    meta = data.get('usageMetadata', {}) or {}
    _log('gemini', m, _gemini_tokens_entree(meta), _gemini_tokens_sortie(meta), 'video')
    cand = (data.get('candidates') or [{}])[0]
    texte = ''.join(p.get('text', '') for p in (cand.get('content', {}).get('parts') or [])
                    if 'text' in p)
    if cand.get('finishReason') == 'MAX_TOKENS':
        texte += ("\n\n⚠️ Description interrompue : la limite de longueur a été atteinte.")
    return texte.strip() or "[Aucune description produite.]"


async def analyze_pdf_anthropic(pdf_bytes: bytes, question: str = '', model: str = None,
                                api_keys: dict = None, max_tokens: int = 4000) -> str:
    """Envoie un PDF NATIVEMENT à Claude (compréhension VISUELLE de la page).

    Différent de l'extraction de texte locale : le modèle voit la mise en page, les
    tableaux, les schémas et le texte des pages scannées. Précieux pour décrire un
    document à quelqu'un qui ne le voit pas. Anthropic uniquement.
    """
    api_key = get_api_key('anthropic', api_keys)
    if not api_key:
        return "[PDF : cle Anthropic non configuree — utilise l'extraction locale ou l'OCR.]"
    import base64 as _b64
    model = _resolve_model('anthropic', model)
    consigne = (question or '').strip() or (
        "Décris ce document de façon structurée et accessible : titre, plan, contenu des "
        "tableaux et des figures. Sois factuel et complet.")
    payload = {
        'model': model,
        'max_tokens': max_tokens,
        'messages': [{'role': 'user', 'content': [
            {'type': 'document',
             'source': {'type': 'base64', 'media_type': 'application/pdf',
                        'data': _b64.standard_b64encode(pdf_bytes).decode()},
             # Citations : chaque affirmation est rattachée à la page d'origine.
             # Indispensable pour vérifier une lecture qu'on ne peut pas contrôler
             # visuellement. cited_text n'est pas facturé en sortie.
             'citations': {'enabled': True}},
            {'type': 'text', 'text': consigne},
        ]}],
    }
    if _anthropic_cache_enabled():
        payload['cache_control'] = {'type': 'ephemeral'}
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(
                'https://api.anthropic.com/v1/messages',
                headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01',
                         'content-type': 'application/json'},
                json=payload)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return f"[PDF : lecture visuelle impossible ({e})]"
    usage = data.get('usage', {})
    _log('anthropic', model, _anthropic_billable_input(usage), usage.get('output_tokens', 0), 'pdf')
    _txt, _pages = [], []
    for b in data.get('content', []):
        if b.get('type') != 'text':
            continue
        _txt.append(b.get('text', ''))
        for c in (b.get('citations') or []):
            p1 = c.get('start_page_number')
            p2 = c.get('end_page_number')
            if p1 is None:
                continue
            libelle = f"page {p1}" if (p2 is None or p2 <= p1 + 1) else f"pages {p1} à {p2 - 1}"
            extrait = (c.get('cited_text') or '').strip().replace('\n', ' ')[:150]
            paire = (libelle, extrait)
            if paire not in _pages:
                _pages.append(paire)
    sortie = ''.join(_txt) + _avis_stop_reason(data.get('stop_reason', ''))
    if _pages:
        sortie += '\n\nPassages cités :\n' + '\n'.join(
            f"- {lib} : « {ext} »" for lib, ext in _pages[:20])
    return sortie


async def count_tokens_anthropic(messages: list, model: str = None, system_prompt: str = None,
                                 tools: list = None, api_keys: dict = None) -> int:
    """Nombre de tokens d'entrée d'une requête, SANS l'envoyer (donc sans la payer).

    Renvoie -1 si le comptage est indisponible (pas de clé, réseau, API) : l'appelant
    doit traiter -1 comme « inconnu » et ne rien afficher plutôt qu'un chiffre faux.
    """
    api_key = get_api_key('anthropic', api_keys)
    if not api_key:
        return -1
    payload = {
        'model': _resolve_model('anthropic', model),
        'messages': _oai_msgs_to_anthropic(messages),
    }
    if system_prompt:
        payload['system'] = system_prompt
    if tools:
        payload['tools'] = _oai_tools_to_anthropic(tools)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                'https://api.anthropic.com/v1/messages/count_tokens',
                headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01',
                         'content-type': 'application/json'},
                json=payload)
            r.raise_for_status()
            return int(r.json().get('input_tokens', -1))
    except Exception as e:
        print(f"[ENGINE] Comptage de tokens indisponible : {e}")
        return -1


# Catalogue interrogé chez le fournisseur, avec cache mémoire (les listes codées en
# dur vieillissent à chaque sortie de modèle).
_MODELS_CACHE = {}          # provider -> (timestamp, [ {id, label} ])
_MODELS_TTL_SECONDS = 3600


def _models_endpoint(provider: str, api_key: str):
    """(url, headers, extracteur) pour lister les modèles, ou None si non supporté."""
    def _ids(data, key='data', field='id'):
        return [m.get(field, '') for m in (data.get(key) or []) if isinstance(m, dict)]

    if provider == 'anthropic':
        return ('https://api.anthropic.com/v1/models',
                {'x-api-key': api_key, 'anthropic-version': '2023-06-01'},
                lambda d: [(m.get('id', ''), m.get('display_name', '') or m.get('id', ''))
                           for m in (d.get('data') or [])])
    if provider == 'openai':
        return ('https://api.openai.com/v1/models',
                {'Authorization': f'Bearer {api_key}'},
                lambda d: [(i, i) for i in _ids(d)])
    if provider == 'deepseek':
        return ('https://api.deepseek.com/models',
                {'Authorization': f'Bearer {api_key}'},
                lambda d: [(i, i) for i in _ids(d)])
    if provider in ('groq', 'cerebras'):
        # Catalogue interrogé en direct : ces deux-là servent des modèles à
        # poids ouverts qui changent souvent. Rien n'est figé dans le code.
        return (_base_openai_compat(provider) + '/models',
                {'Authorization': f'Bearer {api_key}'},
                lambda d: [(i, i) for i in _ids(d)])
    if provider == 'mistral':
        return ('https://api.mistral.ai/v1/models',
                {'Authorization': f'Bearer {api_key}'},
                lambda d: [(i, i) for i in _ids(d)])
    if provider == 'openrouter':
        return ('https://openrouter.ai/api/v1/models',
                {'Authorization': f'Bearer {api_key}'},
                lambda d: [(m.get('id', ''), m.get('name', '') or m.get('id', ''))
                           for m in (d.get('data') or [])])
    if provider == 'gemini':
        return (f'https://generativelanguage.googleapis.com/v1beta/models?key={api_key}',
                {},
                lambda d: [((m.get('name', '') or '').replace('models/', ''),
                            m.get('displayName', '') or (m.get('name', '') or '').replace('models/', ''))
                           for m in (d.get('models') or [])])
    if provider == 'ollama':
        base = os.getenv('OLLAMA_HOST', 'http://localhost:11434').rstrip('/')
        return (f'{base}/api/tags', {},
                lambda d: [(m.get('name', ''), m.get('name', '')) for m in (d.get('models') or [])])
    return None


async def list_models(provider: str, api_keys: dict = None, force: bool = False) -> list:
    """Modèles réellement disponibles chez `provider` : [{'id', 'label'}].

    Interroge le fournisseur (cache 1 h). Renvoie [] si indisponible — l'appelant
    garde alors sa liste de repli codée en dur : jamais de sélecteur vide.
    """
    import time as _time
    provider = (provider or '').lower()
    now = _time.time()
    if not force and provider in _MODELS_CACHE:
        ts, cached = _MODELS_CACHE[provider]
        if now - ts < _MODELS_TTL_SECONDS:
            return cached
    api_key = get_api_key(provider, api_keys) or ''
    if provider != 'ollama' and not api_key:
        return []
    spec = _models_endpoint(provider, api_key)
    if not spec:
        return []
    url, headers, extract = spec
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            pairs = extract(r.json())
    except Exception as e:
        print(f"[ENGINE] Catalogue de modèles indisponible ({provider}) : {e}")
        return []
    models = [{'id': i, 'label': lbl or i} for i, lbl in pairs if i]
    models.sort(key=lambda m: m['id'])
    _MODELS_CACHE[provider] = (now, models)
    return models


async def call_llm(
    messages: list,
    provider: str = 'anthropic',
    model: str = None,
    system_prompt: str = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    api_keys: dict = None,
    images: list = None,        # [{"data": base64, "media_type": "image/jpeg"}]
    tools: list = None,
    output_schema: dict = None,   # JSON Schema : réponse garantie conforme (Anthropic)
    thinking_budget: int = 0,     # > 0 : réflexion étendue, budget en tokens (Anthropic)
) -> str:
    """
    Point d'entrée unique pour tous les providers.
    Retourne le texte de la réponse.

    `output_schema` et `thinking_budget` ne sont honorés que par Anthropic ; les
    autres providers les ignorent silencieusement (l'appelant doit garder son
    analyse de repli — voir critique_result).
    """
    provider = provider.lower()
    model = _resolve_model(provider, model)

    if provider == 'anthropic':
        return await _call_anthropic(messages, model, system_prompt, max_tokens, temperature, api_keys, images,
                                     tools=tools, output_schema=output_schema, thinking_budget=thinking_budget)
    elif provider == 'deepseek':
        return await _call_openai_compat(messages, model or 'deepseek-v4-flash', system_prompt, max_tokens, temperature, api_keys, 'deepseek', _base_openai_compat('deepseek'), images=images, output_schema=output_schema)
    elif provider == 'gemini':
        return await _call_gemini(messages, model, system_prompt, max_tokens, temperature, api_keys, tools=tools)
    elif provider == 'openai':
        return await _call_openai_compat(messages, model or 'gpt-4o', system_prompt, max_tokens, temperature, api_keys, 'openai', _base_openai_compat('openai'), images=images, output_schema=output_schema)
    elif provider == 'openrouter':
        return await _call_openai_compat(messages, model or 'mistralai/mistral-7b-instruct', system_prompt, max_tokens, temperature, api_keys, 'openrouter', _base_openai_compat('openrouter'), images=images, output_schema=output_schema)
    elif provider == 'mistral':
        return await _call_openai_compat(messages, model or 'mistral-small-latest', system_prompt, max_tokens, temperature, api_keys, 'mistral', _base_openai_compat('mistral'), images=images, tools=tools, output_schema=output_schema)
    elif provider in ('groq', 'cerebras'):
        return await _call_openai_compat(messages, model or _modele_openai_compat(provider),
                                         system_prompt, max_tokens, temperature, api_keys,
                                         provider, _base_openai_compat(provider),
                                         images=images, output_schema=output_schema)
    elif provider == 'ollama':
        return await _call_ollama(messages, model or 'llama3', system_prompt, max_tokens, temperature)
    else:
        raise ValueError(f"Provider inconnu : {provider}")


# ══════════════════════════════════════════
# ANTHROPIC
# ══════════════════════════════════════════

def _oai_tools_to_anthropic(tools):
    """Schéma d'outils OpenAI → Anthropic (input_schema = parameters)."""
    out = []
    for t in tools or []:
        fn = t.get('function', t)
        out.append({
            'name':         fn.get('name', ''),
            'description':  fn.get('description', ''),
            'input_schema': fn.get('parameters', {'type': 'object', 'properties': {}}),
        })
    return out


def _oai_msgs_to_anthropic(messages):
    """Messages OpenAI (tool_calls d'assistant, messages 'tool') → format Anthropic :
    blocs tool_use dans l'assistant, tool_result regroupés dans un message user."""
    out = []
    for m in messages:
        role = m.get('role')
        if role == 'system':
            continue
        if role == 'assistant' and m.get('tool_calls'):
            blocks = []
            if m.get('content'):
                blocks.append({'type': 'text', 'text': m['content']})
            for tc in m['tool_calls']:
                fn = tc.get('function', {})
                args = fn.get('arguments', {})
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except Exception: args = {}
                blocks.append({'type': 'tool_use', 'id': tc.get('id', ''),
                               'name': fn.get('name', ''), 'input': args})
            out.append({'role': 'assistant', 'content': blocks})
        elif role == 'tool':
            block = {'type': 'tool_result', 'tool_use_id': m.get('tool_call_id', ''),
                     'content': m.get('content', '')}
            if (out and out[-1]['role'] == 'user' and isinstance(out[-1]['content'], list)
                    and out[-1]['content'] and out[-1]['content'][0].get('type') == 'tool_result'):
                out[-1]['content'].append(block)
            else:
                out.append({'role': 'user', 'content': [block]})
        else:
            out.append({'role': role, 'content': m.get('content', '')})
    return out


async def _call_anthropic(messages, model, system_prompt, max_tokens, temperature, api_keys, images, tools=None,
                          output_schema=None, thinking_budget=0):
    api_key = get_api_key('anthropic', api_keys)
    if not api_key:
        raise ValueError("Clé API Anthropic manquante.")

    model = model or _PROVIDER_DEFAULT_MODEL['anthropic']

    # Construire les messages au format Anthropic (gère tool_use / tool_result)
    anthropic_messages = _oai_msgs_to_anthropic(messages)

    # Injecter les images dans le dernier message user si présentes
    if images and anthropic_messages:
        last = anthropic_messages[-1]
        if last['role'] == 'user' and isinstance(last['content'], str):
            content_blocks = []
            for img in images:
                content_blocks.append({
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': img['media_type'],
                        'data': img['data']
                    }
                })
            content_blocks.append({'type': 'text', 'text': last['content']})
            last['content'] = content_blocks

    payload = {
        'model':      model,
        'max_tokens': max_tokens,
        'temperature': temperature,
        'messages':   anthropic_messages,
    }
    if system_prompt:
        payload['system'] = system_prompt
    if tools:
        payload['tools'] = _oai_tools_to_anthropic(tools)
    if _anthropic_cache_enabled():
        payload['cache_control'] = {'type': 'ephemeral'}
    _mcp = _anthropic_mcp_servers()
    if _mcp:
        payload['mcp_servers'] = _mcp
    if output_schema:
        # Décodage contraint : la réponse est un JSON valide conforme au schéma.
        payload['output_config'] = {'format': {'type': 'json_schema', 'schema': output_schema}}
    if thinking_budget and int(thinking_budget) > 0:
        # La réflexion étendue exige temperature = 1 et max_tokens > budget.
        payload['thinking'] = {'type': 'enabled', 'budget_tokens': int(thinking_budget)}
        payload['temperature'] = 1
        payload['max_tokens'] = max(int(max_tokens), int(thinking_budget) + 1024)

    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key':         api_key,
                'anthropic-version': '2023-06-01',
                'content-type':      'application/json',
                **({'anthropic-beta': 'mcp-client-2025-11-20'} if _mcp else {}),
            },
            json=payload
        )
        try:
            r.raise_for_status()
        except Exception as _e:
            if not _anthropic_cache_fallback(_e):
                raise
            payload.pop('cache_control', None)
            r = await client.post(
                'https://api.anthropic.com/v1/messages',
                headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01',
                         'content-type': 'application/json',
                         **({'anthropic-beta': 'mcp-client-2025-11-20'} if _mcp else {})},
                json=payload)
            r.raise_for_status()
        data = r.json()
        usage = data.get('usage', {})
        _log('anthropic', model, _anthropic_billable_input(usage), usage.get('output_tokens', 0))
        _texte = ''.join(b.get('text', '') for b in data.get('content', []) if b.get('type') == 'text')
        return _texte + _avis_stop_reason(data.get('stop_reason', ''))


async def _anthropic_tools_turn(messages, tools, model, system_prompt, max_tokens, temperature, api_keys):
    """Phase 1 Anthropic : un appel avec outils, DIFFUSÉ EN CONTINU.

    Historiquement cet appel n'était pas streamé : le texte n'arrivait qu'une fois
    la réponse entièrement générée, d'où un long silence avant que la synthèse
    vocale ne démarre — alors que les fournisseurs OpenAI-compat, eux, diffusaient
    au fil de l'eau. Même contrat d'événements qu'avant :
      {'type':'token','text':…}  au fil de l'eau
      {'type':'tool_calls', 'calls':[…], 'assistant_msg':{…}}  si outils demandés
      {'type':'truncated'}  si la limite de longueur est atteinte
    """
    api_key = get_api_key('anthropic', api_keys)
    if not api_key:
        raise ValueError("Clé API Anthropic manquante.")
    model = model or _PROVIDER_DEFAULT_MODEL['anthropic']

    payload = {
        'model':       model,
        'max_tokens':  max_tokens,
        'temperature': temperature,
        'messages':    _oai_msgs_to_anthropic(messages),
        'tools':       _oai_tools_to_anthropic(tools),
        'stream':      True,
    }
    if system_prompt:
        payload['system'] = system_prompt
    if _anthropic_cache_enabled():
        payload['cache_control'] = {'type': 'ephemeral'}

    texte_total = []
    appel_en_texte = False
    blocs_outils = {}      # index du bloc → {'id', 'name', 'json'}
    tokens_in = tokens_out = 0
    stop_reason = ''

    async with httpx.AsyncClient(timeout=300) as client:
        if 'cache_control' in payload and not _anthropic_cache_enabled():
            payload.pop('cache_control', None)
        async with client.stream(
            'POST',
            'https://api.anthropic.com/v1/messages',
            headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01',
                     'content-type': 'application/json'},
            json=payload
        ) as r:
            if r.status_code == 400 and 'cache_control' in payload:
                await r.aread()
                _err = httpx.HTTPStatusError('400', request=r.request, response=r)
                if _anthropic_cache_fallback(_err):
                    payload.pop('cache_control', None)
                    async for _ev in _anthropic_tools_turn(
                            messages, tools, model, system_prompt, max_tokens,
                            temperature, api_keys):
                        yield _ev
                    return
            r.raise_for_status()
            async for ligne in r.aiter_lines():
                if not ligne.startswith('data:'):
                    continue
                try:
                    d = json.loads(ligne[5:].strip())
                except Exception:
                    continue
                evt = d.get('type', '')
                if evt == 'message_start':
                    tokens_in = _anthropic_billable_input(
                        d.get('message', {}).get('usage', {}))
                elif evt == 'content_block_start':
                    bloc = d.get('content_block', {}) or {}
                    if bloc.get('type') == 'tool_use':
                        blocs_outils[d.get('index')] = {
                            'id': bloc.get('id', ''), 'name': bloc.get('name', ''), 'json': ''}
                elif evt == 'content_block_delta':
                    delta = d.get('delta', {}) or {}
                    if delta.get('type') == 'text_delta':
                        morceau = delta.get('text', '')
                        if morceau:
                            texte_total.append(morceau)
                            # Si le modèle se met à écrire son appel d'outil en
                            # texte, on cesse d'afficher : le repli le convertira.
                            if not appel_en_texte and _contient_appel_texte(''.join(texte_total)):
                                appel_en_texte = True
                                _m = ("Le modèle a écrit son appel d'outil en texte au lieu "
                                      "d'utiliser le format prévu — converti automatiquement.")
                                print(f"[ENGINE] ⚠️ {_m}")
                                try:
                                    from core.database import add_diagnostic
                                    add_diagnostic('outils', _m)
                                except Exception:
                                    pass
                            if not appel_en_texte:
                                yield {'type': 'token', 'text': morceau}
                    elif delta.get('type') == 'input_json_delta':
                        b = blocs_outils.get(d.get('index'))
                        if b is not None:
                            b['json'] += delta.get('partial_json', '')
                elif evt == 'message_delta':
                    tokens_out = (d.get('usage', {}) or {}).get('output_tokens', tokens_out)
                    stop_reason = (d.get('delta', {}) or {}).get('stop_reason', stop_reason)

    _log('anthropic', model, tokens_in, tokens_out)

    if not blocs_outils and appel_en_texte:
        _appels = _parse_appels_texte(''.join(texte_total))
        if _appels:
            yield {'type': 'tool_calls', 'calls': _appels,
                   'assistant_msg': {'role': 'assistant', 'content': None,
                                     'tool_calls': [
                                         {'id': c['id'], 'type': 'function',
                                          'function': {'name': c['name'],
                                                       'arguments': json.dumps(c['args'], ensure_ascii=False)}}
                                         for c in _appels]}}
            return

    if blocs_outils:
        calls, oai_tcs = [], []
        for b in blocs_outils.values():
            try:
                args = json.loads(b['json']) if b['json'].strip() else {}
            except Exception:
                args = {}
            calls.append({'name': b['name'], 'args': args, 'id': b['id']})
            oai_tcs.append({'id': b['id'], 'type': 'function',
                            'function': {'name': b['name'],
                                         'arguments': json.dumps(args, ensure_ascii=False)}})
        yield {'type': 'tool_calls', 'calls': calls,
               'assistant_msg': {'role': 'assistant', 'content': ''.join(texte_total),
                                 'tool_calls': oai_tcs}}
    elif stop_reason == 'max_tokens':
        yield {'type': 'truncated'}
    else:
        avis = _avis_stop_reason(stop_reason)
        if avis:
            yield {'type': 'token', 'text': avis}


# ══════════════════════════════════════════
# OPENAI-COMPATIBLE (DeepSeek / OpenAI / OpenRouter)
# ══════════════════════════════════════════

async def _call_openai_compat(messages, model, system_prompt, max_tokens, temperature, api_keys, provider_name, base_url, images=None, tools=None, output_schema=None):
    api_key = get_api_key(provider_name, api_keys)
    if not api_key:
        raise ValueError(f"Clé API {provider_name} manquante.")

    oai_messages = []
    if system_prompt:
        oai_messages.append({'role': 'system', 'content': system_prompt})
    for m in messages:
        if m.get('role') != 'system':
            # Passer le message complet — préserve tool_calls et tool_call_id
            oai_messages.append(m)

    # Vision : injecter les images dans le dernier message utilisateur (format OpenAI image_url).
    if images:
        for msg in reversed(oai_messages):
            if msg.get('role') == 'user':
                txt = msg.get('content') if isinstance(msg.get('content'), str) else ''
                content = [{'type': 'text', 'text': txt}] if txt else []
                for img in images:
                    content.append({
                        'type': 'image_url',
                        'image_url': {'url': f"data:{img['media_type']};base64,{img['data']}"}
                    })
                msg['content'] = content
                break

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type':  'application/json',
    }
    if provider_name == 'openrouter':
        headers['HTTP-Referer'] = 'https://nimm.local'
        headers['X-Title']      = 'NIMM'

    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            f'{base_url}/chat/completions',
            headers=headers,
            json={
                'model':       model,
                'messages':    oai_messages,
                'max_tokens':  max_tokens,
                'temperature': temperature,
                **({'tools': tools} if tools else {}),
                **(_oai_response_format(provider_name, output_schema) or {}),
            }
        )
        r.raise_for_status()
        data = r.json()
        usage = data.get('usage', {})
        _log(provider_name, model, _oai_tokens_entree(usage), usage.get('completion_tokens', 0))
        content = data['choices'][0]['message']['content'] or ''
        citations = (data.get('citations')
                     or data['choices'][0].get('message', {}).get('citations') or [])
        if citations:
            footer = '\n\n---\n**Sources**\n'
            for _i, _c in enumerate(citations, 1):
                _url   = _c.get('url', '')
                _title = _c.get('title') or _c.get('snippet', _url)[:60] or _url
                footer += f'{_i}. [{_title}]({_url})\n'
            content = content + footer
        return content


# ══════════════════════════════════════════
# GEMINI
# ══════════════════════════════════════════

def _oai_tools_to_gemini(tools):
    """Schéma d'outils OpenAI → Gemini (functionDeclarations).
    Les schémas de paramètres NIMM (type/properties/required/description) sont
    acceptés tels quels par Gemini."""
    decls = []
    for t in tools or []:
        fn   = t.get('function', t)
        decl = {'name': fn.get('name', ''), 'description': fn.get('description', '')}
        params = fn.get('parameters')
        if params and params.get('properties'):
            decl['parameters'] = params
        decls.append(decl)
    return [{'functionDeclarations': decls}]


def _oai_msgs_to_gemini(messages):
    """Messages OpenAI (tool_calls d'assistant, messages 'tool') → contents Gemini.
    Un tool_call devient un part functionCall dans un content 'model' ; un message
    'tool' devient un part functionResponse dans un content 'user'. Gemini exige le
    nom de la fonction dans functionResponse : on le retrouve via la carte id→nom
    bâtie à partir des tool_calls de l'assistant."""
    out = []
    id_to_name = {}
    for m in messages:
        role = m.get('role')
        if role == 'system':
            continue
        if role == 'assistant' and m.get('tool_calls'):
            parts = []
            if m.get('content'):
                parts.append({'text': m['content']})
            for tc in m['tool_calls']:
                fn   = tc.get('function', {})
                name = fn.get('name', '')
                args = fn.get('arguments', {})
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except Exception: args = {}
                id_to_name[tc.get('id', '')] = name
                parts.append({'functionCall': {'name': name, 'args': args or {}}})
            out.append({'role': 'model', 'parts': parts})
        elif role == 'tool':
            name = id_to_name.get(m.get('tool_call_id', ''), '')
            out.append({'role': 'user', 'parts': [{
                'functionResponse': {
                    'name':     name,
                    'response': {'result': m.get('content', '')},
                }
            }]})
        else:
            gem_role = 'user' if role == 'user' else 'model'
            out.append({'role': gem_role, 'parts': [{'text': m.get('content', '') or ''}]})
    return out


async def _call_gemini(messages, model, system_prompt, max_tokens, temperature, api_keys, tools=None):
    api_key = get_api_key('gemini', api_keys)
    if not api_key:
        raise ValueError("Clé API Gemini manquante.")

    model = model or 'gemini-3.5-flash'

    payload = {
        'contents': _oai_msgs_to_gemini(messages),
        'generationConfig': {
            'maxOutputTokens': max_tokens,
            'temperature':     temperature,
        }
    }
    if tools:
        payload['tools'] = _oai_tools_to_gemini(tools)
    if system_prompt:
        payload['systemInstruction'] = {'parts': [{'text': system_prompt}]}

    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}',
            json=payload
        )
        r.raise_for_status()
        data = r.json()
        meta = data.get('usageMetadata', {})
        _log('gemini', model, _gemini_tokens_entree(meta), _gemini_tokens_sortie(meta))
        parts = (data.get('candidates') or [{}])[0].get('content', {}).get('parts', []) or []
        return ''.join(p.get('text', '') for p in parts if 'text' in p)


async def _gemini_tools_turn(messages, tools, model, system_prompt, max_tokens, temperature, api_keys):
    """Phase 1 Gemini : un appel avec outils, DIFFUSÉ EN CONTINU.

    Utilise `streamGenerateContent?alt=sse` : le texte arrive au fil de l'eau, au
    lieu d'attendre la génération complète. Les appels de fonction et les sources
    du grounding ne sont émis qu'une fois le flux terminé (ils n'arrivent pas
    fragmentés). Contrat d'événements identique aux autres fournisseurs.
    Si tools contient {'google_search': {}}, active le grounding natif Google Search."""
    api_key = get_api_key('gemini', api_keys)
    if not api_key:
        raise ValueError("Clé API Gemini manquante.")
    model = model or 'gemini-3.5-flash'

    _grounding = any(isinstance(t, dict) and 'google_search' in t for t in (tools or []))

    payload = {
        'contents': _oai_msgs_to_gemini(messages),
        'generationConfig': {
            'maxOutputTokens': max_tokens,
            'temperature':     temperature,
        }
    }
    if _grounding:
        # Google Search Grounding : incompatible avec functionDeclarations
        payload['tools'] = [{'google_search': {}}]
    else:
        payload['tools'] = _oai_tools_to_gemini(tools)
    if system_prompt:
        payload['systemInstruction'] = {'parts': [{'text': system_prompt}]}

    texte, fcalls, citations = [], [], []
    prompt_tokens = cand_tokens = 0
    finish_reason = ''

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            'POST',
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse&key={api_key}',
            json=payload
        ) as r:
            r.raise_for_status()
            async for ligne in r.aiter_lines():
                if not ligne.startswith('data:'):
                    continue
                try:
                    d = json.loads(ligne[5:].strip())
                except Exception:
                    continue
                meta = d.get('usageMetadata', {}) or {}
                prompt_tokens = _gemini_tokens_entree(meta) or prompt_tokens
                cand_tokens = _gemini_tokens_sortie(meta) or cand_tokens
                cand = (d.get('candidates') or [{}])[0]
                finish_reason = cand.get('finishReason', finish_reason) or finish_reason
                for p in (cand.get('content', {}).get('parts', []) or []):
                    if 'text' in p and p['text']:
                        texte.append(p['text'])
                        yield {'type': 'token', 'text': p['text']}
                    elif 'functionCall' in p:
                        fcalls.append(p['functionCall'])
                gm = cand.get('groundingMetadata', {}) or {}
                queries = gm.get('webSearchQueries', []) or []
                for c in (gm.get('groundingChunks', []) or []):
                    uri = c.get('web', {}).get('uri', '')
                    if uri and not any(x['url'] == uri for x in citations):
                        citations.append({'url': uri,
                                          'title': c.get('web', {}).get('title', ''),
                                          'snippet': '',
                                          'query': queries[0] if queries else ''})

    _log('gemini', model, prompt_tokens, cand_tokens)

    if _grounding:
        if citations:
            yield {'type': 'citations', 'citations': citations}
        if finish_reason == 'MAX_TOKENS':
            yield {'type': 'truncated'}
        return

    if fcalls:
        calls, oai_tcs = [], []
        for i, fc in enumerate(fcalls):
            name = fc.get('name', '')
            args = fc.get('args', {}) or {}
            cid  = f"gemini_{i}_{name}"
            calls.append({'name': name, 'args': args, 'id': cid})
            oai_tcs.append({
                'id': cid, 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}
            })
        assistant_msg = {'role': 'assistant', 'content': ''.join(texte), 'tool_calls': oai_tcs}
        yield {'type': 'tool_calls', 'calls': calls, 'assistant_msg': assistant_msg}
    elif finish_reason == 'MAX_TOKENS':
        yield {'type': 'truncated'}


# ══════════════════════════════════════════
# OLLAMA (local)
# ══════════════════════════════════════════

def _oai_msgs_to_ollama(messages):
    """Convertit des messages au format OpenAI (y compris tool_calls d'assistant et
    messages 'tool') vers le format Ollama (arguments en objet, pas d'id)."""
    out = []
    for m in messages:
        role = m.get('role')
        if role == 'system':
            continue
        if role == 'assistant' and m.get('tool_calls'):
            tcs = []
            for tc in m['tool_calls']:
                fn = tc.get('function', {})
                args = fn.get('arguments', {})
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except Exception: args = {}
                tcs.append({'function': {'name': fn.get('name', ''), 'arguments': args}})
            out.append({'role': 'assistant', 'content': m.get('content') or '', 'tool_calls': tcs})
        elif role == 'tool':
            out.append({'role': 'tool', 'content': m.get('content', '')})
        else:
            out.append({'role': role, 'content': m.get('content', '')})
    return out


async def _call_ollama(messages, model, system_prompt, max_tokens, temperature):
    ollama_messages = []
    if system_prompt:
        ollama_messages.append({'role': 'system', 'content': system_prompt})
    ollama_messages.extend(_oai_msgs_to_ollama(messages))

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            'http://localhost:11434/api/chat',
            json={
                'model':    model,
                'messages': ollama_messages,
                'stream':   False,
                'options':  {
                    'num_predict': max_tokens,
                    'temperature': temperature,
                }
            }
        )
        r.raise_for_status()
        data = r.json()
        _log('ollama', model or 'llama3', data.get('prompt_eval_count', 0), data.get('eval_count', 0))
        return data['message']['content']


async def _ollama_tools_turn(messages, tools, model, system_prompt, max_tokens, temperature):
    """Phase 1 Ollama : un appel avec outils, DIFFUSÉ EN CONTINU.

    Ollama répond en NDJSON (un objet JSON par ligne). Les appels d'outils, eux,
    n'arrivent pas fragmentés : on les récolte au fil des lignes. Même contrat
    d'événements que les autres fournisseurs."""
    ollama_messages = []
    if system_prompt:
        ollama_messages.append({'role': 'system', 'content': system_prompt})
    ollama_messages.extend(_oai_msgs_to_ollama(messages))

    texte, tcs = [], []
    prompt_tokens = eval_tokens = 0
    done_reason = ''

    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream(
            'POST',
            'http://localhost:11434/api/chat',
            json={
                'model':    model or 'llama3.1',
                'messages': ollama_messages,
                'tools':    tools,
                'stream':   True,
                'options':  {'num_predict': max_tokens, 'temperature': temperature},
            }
        ) as r:
            r.raise_for_status()
            async for ligne in r.aiter_lines():
                ligne = (ligne or '').strip()
                if not ligne:
                    continue
                try:
                    d = json.loads(ligne)
                except Exception:
                    continue
                msg = d.get('message', {}) or {}
                morceau = msg.get('content', '')
                if morceau:
                    texte.append(morceau)
                    yield {'type': 'token', 'text': morceau}
                if msg.get('tool_calls'):
                    tcs.extend(msg['tool_calls'])
                if d.get('done'):
                    prompt_tokens = d.get('prompt_eval_count', 0) or 0
                    eval_tokens = d.get('eval_count', 0) or 0
                    done_reason = d.get('done_reason', '') or ''

    _log('ollama', model or 'llama3.1', prompt_tokens, eval_tokens)

    if tcs:
        calls, oai_tcs = [], []
        for i, tc in enumerate(tcs):
            fn   = tc.get('function', {})
            name = fn.get('name', '')
            args = fn.get('arguments', {})
            if isinstance(args, str):
                try: args = json.loads(args)
                except Exception: args = {}
            cid = f"ollama_{i}_{name}"
            calls.append({'name': name, 'args': args, 'id': cid})
            oai_tcs.append({
                'id': cid, 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}
            })
        assistant_msg = {'role': 'assistant', 'content': ''.join(texte), 'tool_calls': oai_tcs}
        yield {'type': 'tool_calls', 'calls': calls, 'assistant_msg': assistant_msg}
    elif done_reason == 'length':
        yield {'type': 'truncated'}


# ══════════════════════════════════════════
# EXTRACTION JSON (utilitaire partagé)
# ══════════════════════════════════════════

def extract_json(text: str) -> Optional[dict]:
    """
    Extrait le premier bloc JSON valide d'une réponse LLM.
    Utilisé par le module mémoire et d'autres modules.
    """
    import re
    # Chercher un bloc ```json ... ```
    match = re.search(r'```json\s*([\s\S]*?)```', text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Chercher accolades directes
    match = re.search(r'(\{[\s\S]*\})', text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return None


# ══════════════════════════════════════════
# GEMINI VISION
# ══════════════════════════════════════════

async def call_gemini_vision(image_b64: str, media_type: str, prompt: str, api_keys: dict) -> str:
    """Analyse une image via Gemini Vision."""
    api_key = get_api_key('gemini', api_keys)
    if not api_key:
        raise ValueError("Clé API Gemini manquante.")
    payload = {
        'contents': [{
            'role': 'user',
            'parts': [
                {'inline_data': {'mime_type': media_type, 'data': image_b64}},
                {'text': prompt}
            ]
        }],
        'generationConfig': {'maxOutputTokens': 1024, 'temperature': 0.2}
    }
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}',
            json=payload
        )
        r.raise_for_status()
        data = r.json()
        return data['candidates'][0]['content']['parts'][0]['text']


async def call_vision(image_b64: str, media_type: str, prompt: str,
                      vision_provider: str, api_keys: dict,
                      vision_model: str = None) -> str:
    """
    Analyse d'image — routage selon vision_provider.
    Gemini : API dédiée. Anthropic/OpenAI/Ollama : call_llm avec images.
    vision_model : modèle spécifique (ex. pixtral-large-latest) ; None = défaut du provider.
    """
    provider = vision_provider.lower() if vision_provider else 'gemini'

    if provider in ('gemini', 'auto', ''):
        return await call_gemini_vision(image_b64, media_type, prompt, api_keys)

    elif provider in ('anthropic', 'openai', 'ollama'):
        images = [{'data': image_b64, 'media_type': media_type}]
        return await call_llm(
            messages=[{'role': 'user', 'content': prompt}],
            provider=provider,
            model=None,
            system_prompt='Tu es un assistant qui décrit précisément des images en français.',
            max_tokens=1024,
            temperature=0.2,
            api_keys=api_keys,
            images=images,
        )

    elif provider == 'mistral':
        # Pixtral : modèle vision dédié (les modèles texte Mistral ne gèrent pas les images)
        _pixtral_model = vision_model or 'pixtral-12b-2409'
        images = [{'data': image_b64, 'media_type': media_type}]
        return await call_llm(
            messages=[{'role': 'user', 'content': prompt}],
            provider='mistral',
            model=_pixtral_model,
            system_prompt='Tu es un assistant qui décrit précisément des images en français.',
            max_tokens=1024,
            temperature=0.2,
            api_keys=api_keys,
            images=images,
        )

    else:
        # Fallback Gemini si provider inconnu
        return await call_gemini_vision(image_b64, media_type, prompt, api_keys)


# ══════════════════════════════════════════
# STREAMING
# ══════════════════════════════════════════

async def _call_openai_compat_stream(messages, model, system_prompt, max_tokens, temperature, api_keys, provider_name, base_url, tools=None):
    """Stream tokens via API OpenAI-compatible (DeepSeek, OpenAI, OpenRouter)."""
    api_key = get_api_key(provider_name, api_keys)
    if not api_key:
        raise ValueError(f"Clé API {provider_name} manquante.")
    oai_messages = []
    if system_prompt:
        oai_messages.append({'role': 'system', 'content': system_prompt})
    for m in messages:
        if m.get('role') != 'system':
            # Passer le message complet — préserve tool_calls (assistant) et tool_call_id (tool)
            oai_messages.append(m)
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type':  'application/json',
    }
    if provider_name == 'openrouter':
        headers['HTTP-Referer'] = 'https://nimm.local'
        headers['X-Title']      = 'NIMM'
    _stream_acc  = ''
    _dsml_stream = False
    _usage_tokens = None  # {'tokens_in': N, 'tokens_out': M} si l'API retourne l'usage réel

    _finish_reason = None
    # La chaîne de pensée (deepseek-reasoner et similaires) était accumulée
    # dans une AUTRE fonction : ce nom était donc indéfini ici, et toute
    # réponse diffusée en OpenAI-compatible levait un NameError à la toute
    # fin — après l'affichage, ce qui la rendait discrète.
    _raisonnement_acc = ''
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            'POST',
            f'{base_url}/chat/completions',
            headers=headers,
            json={
                'model':       model,
                'messages':    oai_messages,
                'max_tokens':  max_tokens,
                'temperature': temperature,
                'stream':      True,
                'stream_options': {'include_usage': True},
                **({'tools': tools} if tools else {}),
            }
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith('data:'):
                    continue
                chunk = line[5:].strip()
                if chunk == '[DONE]':
                    break
                try:
                    import json as _json
                    data = _json.loads(chunk)
                    # Chunk de fin avec usage réel (stream_options: include_usage)
                    if data.get('usage') and not data.get('choices'):
                        u = data['usage']
                        _usage_tokens = {
                            'tokens_in':  _oai_tokens_entree(u),
                            'tokens_out': u.get('completion_tokens', 0),
                        }
                        continue
                    if data.get('choices'):
                        _fr = data['choices'][0].get('finish_reason')
                        if _fr:
                            _finish_reason = _fr
                    token = data['choices'][0]['delta'].get('content', '') if data.get('choices') else ''
                    _delta = data['choices'][0]['delta'] if data.get('choices') else {}
                    _rais = _delta.get('reasoning_content') or _delta.get('reasoning') or ''
                    if _rais:
                        _raisonnement_acc += _rais
                    # Certaines APIs incluent usage dans le dernier chunk avec choices
                    if data.get('usage') and data.get('choices'):
                        u = data['usage']
                        _usage_tokens = {
                            'tokens_in':  _oai_tokens_entree(u),
                            'tokens_out': u.get('completion_tokens', 0),
                        }
                    if token:
                        _stream_acc += token
                        if not _dsml_stream and '\uff5c\uff5cDSML\uff5c\uff5c' in _stream_acc:
                            _dsml_stream = True
                        if not _dsml_stream:
                            yield token
                    _cits = (data.get('citations') or
                             (data['choices'][0].get('message', {}).get('citations') if data.get('choices') else None) or [])
                    if _cits:
                        _f = '\n\n---\n**Sources**\n'
                        for _i, _c in enumerate(_cits, 1):
                            _u = _c.get('url', '')
                            _t = _c.get('title') or _c.get('snippet', _u)[:60] or _u
                            _f += f'{_i}. [{_t}]({_u})\n'
                        yield _f
                except Exception:
                    continue
    # Émettre le sentinel d'usage (tokens réels si disponibles)
    if _usage_tokens and (_usage_tokens['tokens_in'] or _usage_tokens['tokens_out']):
        yield {'__usage__': True, **_usage_tokens}
    if _raisonnement_acc.strip():
        yield {'__raisonnement__': _raisonnement_acc.strip()}
    if _finish_reason == 'length':
        yield {'__truncated__': True}

async def _call_anthropic_stream(messages, model, system_prompt, max_tokens, temperature, api_keys, images, tools=None):
    """Stream tokens via API Anthropic."""
    api_key = get_api_key('anthropic', api_keys)
    if not api_key:
        raise ValueError("Clé API Anthropic manquante.")
    model = model or _PROVIDER_DEFAULT_MODEL['anthropic']
    # Conversion OpenAI -> Anthropic : gère les messages 'tool' (rôle inexistant
    # côté Anthropic) et les tool_calls de l'assistant, sinon 400 Bad Request
    # dès qu'un outil (search_web, search_memory…) a été utilisé en phase 1.
    anthropic_messages = _oai_msgs_to_anthropic(messages)
    if images and anthropic_messages:
        last = anthropic_messages[-1]
        if last['role'] == 'user' and isinstance(last['content'], str):
            content_blocks = []
            for img in images:
                content_blocks.append({
                    'type': 'image',
                    'source': {'type': 'base64', 'media_type': img['media_type'], 'data': img['data']}
                })
            content_blocks.append({'type': 'text', 'text': last['content']})
            last['content'] = content_blocks
    payload = {
        'model':      model,
        'max_tokens': max_tokens,
        'temperature': temperature,
        'messages':   anthropic_messages,
        'stream':     True,
    }
    if system_prompt:
        payload['system'] = system_prompt
    if tools:
        payload['tools'] = _oai_tools_to_anthropic(tools)
    if _anthropic_cache_enabled():
        payload['cache_control'] = {'type': 'ephemeral'}
    async with httpx.AsyncClient(timeout=120) as client:
        # Le flux ne se rejoue pas : on retire le champ de cache AVANT d'ouvrir le
        # flux s'il a déjà été refusé une fois (le repli l'a alors désactivé).
        if 'cache_control' in payload and not _anthropic_cache_enabled():
            payload.pop('cache_control', None)
        async with client.stream(
            'POST',
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key':         api_key,
                'anthropic-version': '2023-06-01',
                'content-type':      'application/json',
            },
            json=payload
        ) as r:
            if r.status_code == 400 and 'cache_control' in payload:
                await r.aread()
                import httpx as _hx
                _err = _hx.HTTPStatusError('400', request=r.request, response=r)
                if _anthropic_cache_fallback(_err):
                    # Cache refusé : désactivé pour de bon, on relance ce tour sans lui.
                    payload.pop('cache_control', None)
                    async for _tok in _call_anthropic_stream(
                            messages, model, system_prompt, max_tokens, temperature,
                            api_keys, images, tools=tools):
                        yield _tok
                    return
            r.raise_for_status()
            _ant_tokens_in  = 0
            _ant_tokens_out = 0
            async for line in r.aiter_lines():
                if not line.startswith('data:'):
                    continue
                chunk = line[5:].strip()
                try:
                    import json as _json
                    data = _json.loads(chunk)
                    evt = data.get('type', '')
                    if evt == 'message_start':
                        u = data.get('message', {}).get('usage', {})
                        _ant_tokens_in = _anthropic_billable_input(u)
                    elif evt == 'message_delta':
                        u = data.get('usage', {})
                        _ant_tokens_out = u.get('output_tokens', 0)
                        _sr = (data.get('delta') or {}).get('stop_reason', '')
                        if _sr == 'max_tokens':
                            # Sentinelle : hub la traduit en [TRUNCATED] et le
                            # frontend affiche le bouton « Continuer ».
                            yield {'__truncated__': True}
                        else:
                            _avis = _avis_stop_reason(_sr)
                            if _avis:
                                yield _avis
                    elif evt == 'content_block_delta':
                        token = data.get('delta', {}).get('text', '')
                        if token:
                            yield token
                except Exception:
                    continue
    # Émettre sentinel usage Anthropic
    if _ant_tokens_in or _ant_tokens_out:
        yield {'__usage__': True, 'tokens_in': _ant_tokens_in, 'tokens_out': _ant_tokens_out}

async def call_llm_stream(
    messages: list,
    provider: str = 'anthropic',
    model: str = None,
    system_prompt: str = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    api_keys: dict = None,
    images: list = None,
    tools: list = None,
    pipeline: str = 'chat',
):
    """Stream de tokens — génère les tokens un par un."""
    provider = provider.lower()
    model = _resolve_model(provider, model)
    _accumulated = []

    _real_usage = None  # Rempli si l'API retourne l'usage exact

    try:
        if provider == 'anthropic':
            async for token in _call_anthropic_stream(messages, model, system_prompt, max_tokens, temperature, api_keys, images, tools=tools):
                if isinstance(token, dict):
                    if token.get('__usage__'):
                        _real_usage = token
                    else:
                        yield token      # sentinelle (troncature) : transmise, non accumulée
                else:
                    _accumulated.append(token)
                    yield token
        elif provider in FOURNISSEURS_OPENAI_COMPAT:
            async for token in _call_openai_compat_stream(
                messages, model or _modele_openai_compat(provider), system_prompt,
                max_tokens, temperature, api_keys, provider,
                _base_openai_compat(provider), tools=tools
            ):
                if isinstance(token, dict):
                    if token.get('__usage__'):
                        _real_usage = token
                    else:
                        yield token      # sentinelle (troncature) : transmise, non accumulée
                else:
                    _accumulated.append(token)
                    yield token
        else:
            # Fallback : appel normal (déjà loggé dans call_llm)
            result = await call_llm(messages, provider, model, system_prompt, max_tokens, temperature, api_keys, images, tools=tools)
            _accumulated.append(result)
            yield result
            return  # call_llm a déjà loggé — on sort avant le _log stream
    finally:
        # Usage réel si disponible, sinon estimation caractères/4
        if _real_usage:
            tokens_in  = _real_usage.get('tokens_in', 0)
            tokens_out = _real_usage.get('tokens_out', 0)
        elif _accumulated and provider in ('anthropic', 'deepseek', 'openai', 'openrouter', 'mistral', 'gemini'):
            in_text   = (system_prompt or '') + ' '.join(str(m.get('content', '')) for m in messages)
            out_text  = ''.join(str(t) for t in _accumulated)
            tokens_in  = max(1, len(in_text) // 4)
            tokens_out = max(1, len(out_text) // 4)
        else:
            tokens_in = tokens_out = 0
        if tokens_in or tokens_out:
            _log(provider, model or '', tokens_in, tokens_out, pipeline)
            yield {'type': 'usage', 'tokens_in': tokens_in, 'tokens_out': tokens_out,
                   'provider': provider, 'model': model or '', 'estimated': not bool(_real_usage)}


# ══════════════════════════════════════════
# STREAM AVEC TOOL CALLING (DeepSeek / OpenAI-compat)
# ══════════════════════════════════════════

async def call_llm_stream_with_tools(
    messages: list,
    tools: list,
    provider: str = 'deepseek',
    model: str = None,
    system_prompt: str = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    api_keys: dict = None,
):
    """
    Stream avec détection de tool calls (DeepSeek / OpenAI-compat uniquement).

    Yield des événements typés :
      {"type": "token", "text": "..."}         → token normal, à envoyer au frontend
      {"type": "tool_calls", "calls": [...],
       "assistant_msg": {...}}                  → outil demandé, arrêter le stream

    Pour le provider encore non supporté (Gemini) :
    → fallback silencieux : yield uniquement des tokens normaux (pas de tool calling).
    """
    provider = provider.lower()
    model = _resolve_model(provider, model)

    if provider == 'ollama':
        async for ev in _ollama_tools_turn(messages, tools, model, system_prompt, max_tokens, temperature):
            yield ev
        return

    if provider == 'anthropic':
        async for ev in _anthropic_tools_turn(messages, tools, model, system_prompt, max_tokens, temperature, api_keys):
            yield ev
        return

    if provider == 'gemini':
        async for ev in _gemini_tools_turn(messages, tools, model, system_prompt, max_tokens, temperature, api_keys):
            yield ev
        return

    _SUPPORTED = {p for p, c in FOURNISSEURS_OPENAI_COMPAT.items() if c.get('outils')}
    if provider not in _SUPPORTED:
        # Fallback : stream normal sans tools (providers sans tool-calling)
        async for token in call_llm_stream(
            messages=messages,
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            api_keys=api_keys,
        ):
            if not isinstance(token, dict):
                yield {"type": "token", "text": token}
        return

    # ── Fournisseurs compatibles OpenAI : adresses et modèles de repli dans
    #    FOURNISSEURS_OPENAI_COMPAT, source unique (voir en tête de module).
    api_key  = get_api_key(provider, api_keys)
    if not api_key:
        raise ValueError(f"Clé API {provider} manquante.")

    base_url = _base_openai_compat(provider)
    _model   = model or _modele_openai_compat(provider)

    oai_messages = []
    if system_prompt:
        oai_messages.append({'role': 'system', 'content': system_prompt})
    for m in messages:
        if m['role'] != 'system':
            oai_messages.append({'role': m['role'], 'content': m['content']})

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type':  'application/json',
    }
    if provider == 'openrouter':
        headers['HTTP-Referer'] = 'https://nimm.local'
        headers['X-Title']      = 'NIMM'

    # Les built-in tools Mistral (web_search) ne supportent pas tool_choice
    _only_builtins = tools and all(
        t.get('type') != 'function' for t in tools
    )
    _sans_outils = _modele_sans_outils(_model)
    _raisonneur_oai = _modele_raisonnement_openai(_model)
    payload = {
        'model':    _model,
        'messages': oai_messages,
        'stream':   True,
    }
    # La série o d'OpenAI n'accepte que max_completion_tokens.
    payload['max_completion_tokens' if _raisonneur_oai else 'max_tokens'] = max_tokens
    if not _sans_outils and not _raisonneur_oai:
        payload['temperature'] = temperature
        payload['tools'] = tools
        if not _only_builtins:
            payload['tool_choice'] = 'auto'
    else:
        print(f"[ENGINE] {_model} : modèle de raisonnement — outils et température non transmis.")

    # Accumulateurs pour reconstruire les tool_calls fragmentés
    _tool_calls_acc = {}   # index → {"id": str, "name": str, "arguments": str}
    _finish_reason  = None
    _raw_acc        = ''   # accumule le content brut pour détecter le DSML
    _raisonnement_acc = ''  # chaîne de pensée (deepseek-reasoner et similaires)
    _dsml_detected  = False

    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            'POST',
            f'{base_url}/chat/completions',
            headers=headers,
            json=payload,
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith('data:'):
                    continue
                chunk = line[5:].strip()
                if chunk == '[DONE]':
                    break

                try:
                    import json as _json
                    data    = _json.loads(chunk)
                    choice  = data['choices'][0]
                    delta   = choice.get('delta', {})
                    _finish_reason = choice.get('finish_reason') or _finish_reason

                    # ── Token normal ──
                    # DeepSeek peut écrire ses tool_calls en DSML dans le content
                    # au lieu du champ structuré tool_calls. On accumule tout le
                    # content brut ; dès qu'un bloc DSML est détecté on coupe le
                    # flux visible et on laisse le post-traitement gérer.
                    # Chaîne de pensée des modèles de raisonnement : elle arrive
                    # dans un champ SÉPARÉ et était purement perdue. Elle est déjà
                    # payée — autant la rendre consultable.
                    _rais = delta.get('reasoning_content', '')
                    if _rais:
                        _raisonnement_acc += _rais

                    text = delta.get('content', '')
                    if text:
                        _raw_acc += text
                        if not _dsml_detected and '\uff5c\uff5cDSML\uff5c\uff5c' in _raw_acc:
                            _dsml_detected = True
                        if not _dsml_detected and _contient_appel_texte(_raw_acc):
                            _dsml_detected = True   # appel d'outil en texte : on coupe l'affichage
                        if not _dsml_detected:
                            import re as _re
                            clean = _re.sub(r'<｜[^｜>]*(?:｜[^>]*)?>?', '', text)
                            if clean:
                                yield {"type": "token", "text": clean}

                    # ── Citations Mistral web search ──
                    _cits = (data.get('citations') or
                             choice.get('delta', {}).get('citations') or
                             choice.get('message', {}).get('citations') or [])
                    if _cits:
                        yield {"type": "citations", "citations": _cits}

                    # ── Accumulation des tool_calls fragmentés ──
                    for tc in delta.get('tool_calls', []):
                        idx = tc.get('index', 0)
                        if idx not in _tool_calls_acc:
                            _tool_calls_acc[idx] = {
                                'id':        tc.get('id', ''),
                                'name':      tc.get('function', {}).get('name', ''),
                                'arguments': '',
                            }
                        else:
                            if tc.get('id'):
                                _tool_calls_acc[idx]['id'] = tc['id']
                            if tc.get('function', {}).get('name'):
                                _tool_calls_acc[idx]['name'] = tc['function']['name']
                        _tool_calls_acc[idx]['arguments'] += tc.get('function', {}).get('arguments', '')

                except Exception:
                    continue

    # ── Repli : appel d'outil écrit en texte (« <function=nom>{…} ») ──
    if not _tool_calls_acc and _contient_appel_texte(_raw_acc):
        _appels = _parse_appels_texte(_raw_acc)
        if _appels:
            yield {'type': 'tool_calls', 'calls': _appels,
                   'assistant_msg': {'role': 'assistant', 'content': None,
                                     'tool_calls': [
                                         {'id': c['id'], 'type': 'function',
                                          'function': {'name': c['name'],
                                                       'arguments': json.dumps(c['args'], ensure_ascii=False)}}
                                         for c in _appels]}}
            return

    # ── Fallback DSML : DeepSeek a mis le tool_call dans le content ──
    if not _tool_calls_acc and _dsml_detected:
        import re as _re
        import json as _json
        calls = []
        for m in _re.finditer(
            r'<tool_call>\s*<tool_name>\s*([^<]+?)\s*</tool_name>\s*<parameters>(.*?)</parameters>\s*</tool_call>',
            _raw_acc, _re.DOTALL
        ):
            tool_name = m.group(1).strip()
            params_text = m.group(2).strip()
            args = {}
            for p in _re.finditer(
                r'<parameter name="([^"]+)"[^>]*>(.*?)</parameter>',
                params_text, _re.DOTALL
            ):
                args[p.group(1)] = p.group(2).strip()
            calls.append({'id': f'dsml_{tool_name}', 'name': tool_name, 'args': args})
        if calls:
            assistant_msg = {
                'role': 'assistant',
                'content': None,
                'tool_calls': [
                    {
                        'id': c['id'],
                        'type': 'function',
                        'function': {
                            'name': c['name'],
                            'arguments': json.dumps(c['args'], ensure_ascii=False),
                        }
                    }
                    for c in calls
                ]
            }
            yield {"type": "tool_calls", "calls": calls, "assistant_msg": assistant_msg}

    # ── Si des tool_calls ont été accumulés ──
    # Note : DeepSeek retourne finish_reason='length' ou 'stop' même avec tool_calls,
    # on ne peut donc pas se fier uniquement à finish_reason.
    if _tool_calls_acc:
        calls = []
        for idx in sorted(_tool_calls_acc.keys()):
            tc = _tool_calls_acc[idx]
            try:
                import json as _json
                args = _json.loads(tc['arguments']) if tc['arguments'] else {}
            except Exception:
                args = {}
            calls.append({
                'id':   tc['id'],
                'name': tc['name'],
                'args': args,
            })

        # Message assistant reconstitué (nécessaire pour l'historique OpenAI)
        assistant_msg = {
            'role':       'assistant',
            'content':    None,
            'tool_calls': [
                {
                    'id':   c['id'],
                    'type': 'function',
                    'function': {
                        'name':      c['name'],
                        'arguments': json.dumps(c['args'], ensure_ascii=False),
                    }
                }
                for c in calls
            ]
        }

        yield {"type": "tool_calls", "calls": calls, "assistant_msg": assistant_msg}


# ══════════════════════════════════════════
# GÉNÉRATION IMAGE
# ══════════════════════════════════════════

async def generate_image(prompt: str, provider: str, api_keys: dict) -> dict:
    """
    Génère une image à partir d'un prompt texte.
    Retourne { 'url': str, 'b64': str, 'provider': str }
    'url' est prioritaire si présent, sinon 'b64' (base64 PNG).
    Provider principal : gemini. Fallback automatique : dall-e-3 si gemini échoue.
    """
    provider = (provider or 'gemini').lower()

    if provider == 'dall-e':
        return await _generate_dalle(prompt, api_keys)
    elif provider == 'mistral':
        return await _generate_mistral_image(prompt, api_keys)
    elif provider == 'stability-ai':
        return await _generate_stability(prompt, api_keys)
    elif provider == 'local':
        return await _generate_local(prompt)
    else:
        # Gemini en principal, dall-e-3 en fallback automatique
        try:
            return await _generate_gemini_image(prompt, api_keys)
        except Exception as _gemini_err:
            print(f"[ENGINE] ⚠️ Gemini image échoué ({_gemini_err}) — fallback dall-e-3")
            if api_keys.get('openai'):
                return await _generate_dalle(prompt, api_keys)
            raise _gemini_err


async def _generate_mistral_image(prompt: str, api_keys: dict) -> dict:
    """
    Generation d'image via l'API Agents Mistral (tool image_generation).
    Retourne {'b64': str, 'provider': 'mistral'}.
    """
    import httpx as _hx, base64 as _b64, json as _j
    _key = (api_keys.get('mistral') or '').strip()
    if not _key:
        raise ValueError("Cle API Mistral manquante pour la generation d'image.")

    # 1. Creer un agent ephemere avec l'outil image_generation
    async with _hx.AsyncClient(timeout=60) as _c:
        _ar = await _c.post(
            'https://api.mistral.ai/v1/beta/agents',
            headers={'Authorization': f'Bearer {_key}', 'Content-Type': 'application/json'},
            json={
                'model': 'mistral-medium-latest',
                'name': 'nimm-image-agent',
                'description': 'Agent NIMM pour la generation d image',
                'tools': [{'type': 'image_generation'}],
                'instructions': 'Tu es un agent de generation d image. Genere toujours une image en reponse.'
            }
        )
        _ar.raise_for_status()
        _agent_id = _ar.json().get('id')
        if not _agent_id:
            raise ValueError(f"Erreur creation agent Mistral image: {_ar.text}")

        # 2. Ouvrir une conversation et envoyer le prompt
        _cr = await _c.post(
            f'https://api.mistral.ai/v1/beta/conversations',
            headers={'Authorization': f'Bearer {_key}', 'Content-Type': 'application/json'},
            json={
                'agent_id': _agent_id,
                'inputs': prompt,
                'stream': False
            }
        )
        _cr.raise_for_status()
        _conv = _cr.json()

        # 3. Extraire les fichiers images de la reponse
        _outputs = _conv.get('outputs', [])
        _file_id = None
        for _out in _outputs:
            if _out.get('type') == 'image_url':
                return {'url': _out.get('image_url', {}).get('url', ''), 'provider': 'mistral'}
            if _out.get('type') == 'tool_result':
                for _item in (_out.get('content') or []):
                    if isinstance(_item, dict) and _item.get('type') == 'image_url':
                        return {'url': _item.get('image_url', {}).get('url', ''), 'provider': 'mistral'}
                    if isinstance(_item, dict) and _item.get('file_id'):
                        _file_id = _item['file_id']

        if not _file_id:
            # chercher dans les messages
            for _msg in (_conv.get('messages') or []):
                for _item in (_msg.get('content') or []):
                    if isinstance(_item, dict) and _item.get('type') == 'image_url':
                        return {'url': _item.get('image_url', {}).get('url', ''), 'provider': 'mistral'}
                    if isinstance(_item, dict) and _item.get('file_id'):
                        _file_id = _item['file_id']

        if not _file_id:
            raise ValueError(f"Aucune image dans la reponse Mistral: {_j.dumps(_conv)[:300]}")

        # 4. Telecharger le fichier
        _fr = await _c.get(
            f'https://api.mistral.ai/v1/files/{_file_id}/content',
            headers={'Authorization': f'Bearer {_key}'}
        )
        _fr.raise_for_status()
        _b64_str = _b64.b64encode(_fr.content).decode()
        return {'b64': _b64_str, 'provider': 'mistral'}


async def _generate_dalle(prompt: str, api_keys: dict) -> dict:
    """dall-e-3 via OpenAI API."""
    api_key = get_api_key('openai', api_keys)
    if not api_key:
        raise ValueError("Clé API OpenAI manquante (nécessaire pour la génération d'image).")

    payload = {
        'model':           'dall-e-3',
        'prompt':          prompt,
        'n':               1,
        'size':            '1024x1024',
        'response_format': 'url',
    }
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            'https://api.openai.com/v1/images/generations',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type':  'application/json',
            },
            json=payload,
        )
        if not r.is_success:
            detail = r.text[:500]
            raise ValueError(f"OpenAI dall-e-3 {r.status_code} : {detail}")
        data = r.json()
        url            = data['data'][0].get('url', '')
        revised_prompt = data['data'][0].get('revised_prompt', prompt)
        return {'url': url, 'b64': '', 'provider': 'dall-e', 'revised_prompt': revised_prompt}


async def _generate_stability(prompt: str, api_keys: dict) -> dict:
    """Stability AI — SDXL."""
    api_key = get_api_key('stability_ai', api_keys)
    if not api_key:
        raise ValueError("Clé API Stability AI manquante.")

    import base64
    payload = {
        'text_prompts': [{'text': prompt, 'weight': 1.0}],
        'cfg_scale':    7,
        'height':       1024,
        'width':        1024,
        'steps':        30,
        'samples':      1,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            'https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type':  'application/json',
                'Accept':        'application/json',
            },
            json=payload,
        )
        r.raise_for_status()
        data   = r.json()
        b64    = data['artifacts'][0]['base64']
        return {'url': '', 'b64': b64, 'provider': 'stability-ai'}


async def _generate_gemini_image(prompt: str, api_keys: dict) -> dict:
    """Generation d'image via Gemini 3.1 Flash Image (Nano Banana 2)."""
    api_key = get_api_key('gemini', api_keys)
    if not api_key:
        raise ValueError("Cle API Gemini manquante (necessaire pour la generation d'image).")

    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image:generateContent?key={api_key}',
            headers={'Content-Type': 'application/json'},
            json={
                'contents': [{'parts': [{'text': prompt}]}],
                'generationConfig': {'responseModalities': ['IMAGE']},
            },
        )
        if not r.is_success:
            detail = r.text[:500]
            raise ValueError(f"Gemini image {r.status_code} : {detail}")
        data = r.json()
        b64  = data['candidates'][0]['content']['parts'][0]['inlineData']['data']
        return {'url': '', 'b64': b64, 'provider': 'gemini', 'revised_prompt': prompt}


async def edit_gemini_image(prompt: str, image_b64: str, api_keys: dict) -> dict:
    """Retouche d'une image existante via Gemini 3.1 Flash Image."""
    api_key = get_api_key('gemini', api_keys)
    if not api_key:
        raise ValueError("Clé API Gemini manquante pour la retouche d'image.")

    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image:generateContent?key={api_key}',
            headers={'Content-Type': 'application/json'},
            json={
                'contents': [{
                    'parts': [
                        {'text': prompt},
                        {'inlineData': {'mimeType': 'image/png', 'data': image_b64}},
                    ]
                }],
                'generationConfig': {'responseModalities': ['IMAGE']},
            },
        )
        if not r.is_success:
            detail = r.text[:500]
            raise ValueError(f"Gemini image edit {r.status_code} : {detail}")
        data = r.json()
        b64  = data['candidates'][0]['content']['parts'][0]['inlineData']['data']
        return {'url': '', 'b64': b64, 'provider': 'gemini', 'revised_prompt': prompt}


async def _generate_local(prompt: str) -> dict:
    """Stub ComfyUI/A1111 local — endpoint configurable."""
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            'http://127.0.0.1:7860/sdapi/v1/txt2img',
            json={'prompt': prompt, 'steps': 20, 'width': 512, 'height': 512},
        )
        r.raise_for_status()
        data = r.json()
        b64  = data['images'][0]
        return {'url': '', 'b64': b64, 'provider': 'local'}


# ══════════════════════════════════════════
# CRÉDIT RESTANT — providers exposant un solde
# ══════════════════════════════════════════

# Providers pour lesquels l'API expose un solde/crédit restant interrogeable.
PROVIDERS_WITH_CREDIT = ('openrouter', 'deepseek', 'stability-ai')


async def get_provider_credit(provider: str, api_keys: dict) -> dict:
    """
    Interroge l'API du provider pour son solde/crédit restant, si l'API
    l'expose. Retourne :
      - {'available': True, 'balance': float, 'currency': str}
      - {'available': False, 'reason': str}  (pas de clé, provider non
        supporté, ou erreur réseau/API — `reason` reste court et sûr à
        afficher)
    """
    # La clé Stability AI est stockée sous 'stability_ai' (underscore) côté
    # api_keys, alors que le provider de crédit est 'stability-ai' (tiret).
    key_name = 'stability_ai' if provider == 'stability-ai' else provider
    key = (api_keys or {}).get(key_name)
    if not key:
        return {'available': False, 'reason': 'no_key'}

    if provider not in PROVIDERS_WITH_CREDIT:
        return {'available': False, 'reason': 'unsupported_provider'}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if provider == 'openrouter':
                r = await client.get(
                    'https://openrouter.ai/api/v1/credits',
                    headers={'Authorization': f'Bearer {key}'},
                )
                r.raise_for_status()
                data  = r.json().get('data', {})
                total = data.get('total_credits', 0) or 0
                used  = data.get('total_usage', 0) or 0
                return {'available': True, 'balance': round(total - used, 4), 'currency': 'USD'}

            if provider == 'deepseek':
                r = await client.get(
                    'https://api.deepseek.com/user/balance',
                    headers={'Authorization': f'Bearer {key}'},
                )
                r.raise_for_status()
                infos = r.json().get('balance_infos') or []
                if not infos:
                    return {'available': False, 'reason': 'empty_response'}
                info = infos[0]
                return {
                    'available': True,
                    'balance':   float(info.get('total_balance', 0)),
                    'currency':  info.get('currency', 'USD'),
                }

            if provider == 'stability-ai':
                r = await client.get(
                    'https://api.stability.ai/v1/user/balance',
                    headers={'Authorization': f'Bearer {key}'},
                )
                r.raise_for_status()
                data = r.json()
                return {'available': True, 'balance': float(data.get('credits', 0)), 'currency': 'crédits'}
    except Exception as e:
        return {'available': False, 'reason': str(e)[:120]}

    return {'available': False, 'reason': 'Provider non reconnu'}
