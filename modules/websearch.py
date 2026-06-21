# ============================================
# NIMM — modules/websearch.py
# Recherche web Brave Search API
# Clé gratuite : https://brave.com/search/api/
# Quota gratuit : 2 000 requêtes / mois — débit : 1 requête / seconde
# ============================================

import asyncio
import html
import json
import re
import unicodedata
import warnings
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

from modules import net_guard

BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_TIMEOUT = 8  # secondes

# Tavily — moteur de recherche pensé pour les LLM (résultats déjà nettoyés).
TAVILY_API_URL = "https://api.tavily.com/search"
TAVILY_TIMEOUT = 12  # secondes


def _choose_engine(pref: str, brave_key: str, tavily_key: str):
    """Choisit le moteur : préférence explicite si sa clé existe, sinon repli.
    'auto' privilégie Tavily (meilleur pour un LLM) s'il a une clé."""
    pref = (pref or 'auto').lower()
    if pref == 'tavily' and tavily_key:
        return 'tavily'
    if pref == 'brave' and brave_key:
        return 'brave'
    if tavily_key:
        return 'tavily'
    if brave_key:
        return 'brave'
    return None

# Langue appliquée par défaut quand rien n'est précisé.
DEFAULT_LANG = "fr"

# --- Vérification simple des liens (mode léger, sans extraction) ---
# Teste que chaque URL répond ; n'écarte que les liens disparus (404/410).
VERIFY_URLS    = True
VERIFY_TIMEOUT = 4
VERIFY_WORKERS = 8

# --- Enrichissement : extraction des paragraphes pertinents ---
# Pour chaque résultat, récupère la page et renvoie les paragraphes qui
# correspondent le mieux aux mots-clés de la requête. Comme la page est
# téléchargée, cette étape vérifie aussi la validité du lien (elle remplace
# alors le contrôle HEAD). Plus coûteuse : menée en parallèle, délai borné.
ENRICH_PARAGRAPHS = True   # interrupteur global
ENRICH_TIMEOUT    = 10     # secondes, par page
ENRICH_WORKERS    = 5      # pages traitées en parallèle
ENRICH_MAX_PARAS  = 2      # paragraphes renvoyés par page
ENRICH_MIN_LEN    = 40     # longueur mini d'un paragraphe retenu (caractères)
ENRICH_MAX_LEN    = 600    # longueur maxi d'un paragraphe renvoyé
ENRICH_MAX_BYTES  = 2_000_000  # taille maxi de page analysée
ENRICH_VERIFY_TLS = False  # comme le module scrap4me : tolère les certificats
                           # imparfaits pour joindre davantage de sites.

# --- Cache des recherches (références web) ---
# Réutilise un résultat déjà obtenu pour une requête proche, tant qu'il n'est pas
# périmé : gain de temps + mémoire des recherches passées. Zone séparée de la
# mémoire personnelle (table web_reference). Chaque entrée porte une expiration
# fonction de la périssabilité de l'information.
WEBCACHE_ENABLED      = True
WEBCACHE_SIM_MIN      = 0.85  # similarité de requête mini pour réutiliser (mode vecteurs)
WEBCACHE_TTL_DEFAULT  = 30    # jours — information « normale »
WEBCACHE_TTL_EPHEMERE = 1     # jour  — information éphémère (météo, cours, actualité…)

# Marqueurs d'information éphémère (comparés sans accents, en minuscules).
_MOTS_EPHEMERES = {
    "meteo", "temperature", "pluie", "neige", "vent", "cours", "bourse",
    "action", "cotation", "prix", "tarif", "promo", "solde", "score", "match",
    "resultat", "actualite", "news", "aujourd", "demain", "hier", "ce soir",
    "cette semaine", "maintenant", "horaire", "trafic", "taux", "change",
    "classement", "live", "direct",
}

# En-tête de navigateur : beaucoup de sites refusent les requêtes anonymes.
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/124.0 Safari/537.36")

# Préréglages langue -> paramètres Brave (country / search_lang / ui_lang).
_LANG_PRESETS = {
    "fr": {"country": "FR", "search_lang": "fr", "ui_lang": "fr-FR"},
    "en": {"country": "US", "search_lang": "en", "ui_lang": "en-US"},
    "gb": {"country": "GB", "search_lang": "en", "ui_lang": "en-GB"},
    "es": {"country": "ES", "search_lang": "es", "ui_lang": "es-ES"},
    "de": {"country": "DE", "search_lang": "de", "ui_lang": "de-DE"},
    "it": {"country": "IT", "search_lang": "it", "ui_lang": "it-IT"},
    "pt": {"country": "PT", "search_lang": "pt", "ui_lang": "pt-PT"},
}

# Journalisation du contenu des requêtes (False = confidentiel par défaut).
_LOG_QUERIES = False

_STRIP_PREFIX = re.compile(
    r'^(va(s)?\s+sur\s+(internet|le\s+web)|'
    r'fais\s+(une\s+)?recherche\s+(sur\s+)?|'
    r'cherche\s+(sur\s+(internet|le\s+web)\s*)?|'
    r'recherche\s+(sur\s+(internet|le\s+web)\s*)?|'
    r'trouve[-\s]moi\s+|'
    r'google[-\s]moi\s+|'
    r'cherche[-\s]moi\s+)',
    re.IGNORECASE
)

_LANG_DIRECTIVE = re.compile(
    r'(?:^|\s)(?:lang|langue)\s*:\s*([a-zA-Z]{2,3}|\*)',
    re.IGNORECASE
)

# Mots vides (déjà normalisés : sans accents, en minuscules).
_FR_STOPWORDS = {
    "le", "la", "les", "un", "une", "des", "du", "de", "au", "aux", "et", "ou",
    "en", "dans", "sur", "sous", "pour", "par", "avec", "sans", "ce", "cet",
    "cette", "ces", "que", "qui", "quoi", "dont", "ou", "est", "sont", "etre",
    "avoir", "son", "sa", "ses", "leur", "leurs", "nos", "vos", "mon", "ma",
    "mes", "ton", "ta", "tes", "il", "elle", "ils", "elles", "on", "nous",
    "vous", "je", "tu", "se", "ne", "pas", "plus", "moins", "tres", "comme",
    "mais", "donc", "car", "the", "of", "and", "to", "in", "for", "on", "with",
    "a", "an", "is", "are",
}


def _norm(s: str) -> str:
    """Minuscule + suppression des accents + apostrophes/tirets normalisés."""
    if not s:
        return ""
    s = s.lower()
    s = "".join(ch for ch in unicodedata.normalize("NFD", s)
                if unicodedata.category(ch) != "Mn")
    s = s.replace("\u2019", "'").replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", s).strip()


def _compact(s: str, max_len: int = ENRICH_MAX_LEN) -> str:
    """Compacte les espaces et tronque proprement."""
    if not s:
        return ""
    s = re.sub(r"\s+", " ", str(s)).strip()
    if len(s) > max_len:
        return s[: max_len - 1].rstrip() + "…"
    return s


def _keywords(text: str):
    """Mots-clés utiles de la requête (normalisés, hors mots vides)."""
    toks = re.findall(r"[a-z0-9]+", _norm(text))
    seen, out = set(), []
    for t in toks:
        if len(t) >= 3 and t not in _FR_STOPWORDS and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _extract_lang(query: str):
    """Détecte une directive « lang:xx » ; retourne (code|None, requête nettoyée)."""
    m = _LANG_DIRECTIVE.search(query)
    if not m:
        return None, query
    lang = m.group(1).lower()
    cleaned = (query[:m.start()] + " " + query[m.end():]).strip()
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    return lang, cleaned


def _lang_params(lang: str) -> dict:
    if not lang:
        lang = DEFAULT_LANG
    lang = lang.lower()
    if lang in ("any", "all", "*"):
        return {}
    preset = _LANG_PRESETS.get(lang)
    if preset:
        return dict(preset)
    return {"search_lang": lang}


def _clean_query(query: str) -> str:
    """Nettoie la requête (préfixes conversationnels) et tronque à 380 car."""
    q = query.strip()
    q = _STRIP_PREFIX.sub('', q).strip()
    return q[:380].strip()


def _check_url(url: str) -> str:
    """Mode léger : 'live', 'dead' ou 'unknown' (n'écarte que 404/410)."""
    if not url:
        return "unknown"
    if not net_guard.is_public_url(url):
        return "unknown"  # cible interne / tailnet : refus anti-SSRF
    headers = {"User-Agent": _BROWSER_UA}
    try:
        resp = net_guard.safe_request("HEAD", url, headers=headers, timeout=VERIFY_TIMEOUT)
        if resp.status_code in (403, 405, 501):
            resp = net_guard.safe_request("GET", url, headers=headers,
                                          timeout=VERIFY_TIMEOUT, stream=True)
            resp.close()
    except (requests.exceptions.RequestException, PermissionError):
        return "unknown"
    code = resp.status_code
    if code in (404, 410):
        return "dead"
    if 200 <= code < 400:
        return "live"
    return "unknown"


def _page_paragraphs(content: bytes):
    """Extrait les paragraphes lisibles d'une page HTML.

    Retire les zones non informatives (scripts, navigation, pied de page…),
    puis collecte le texte des <p> et, en complément, des <li>."""
    soup = BeautifulSoup(content[:ENRICH_MAX_BYTES], "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header",
                     "footer", "aside", "form", "template"]):
        tag.decompose()

    paras, seen = [], set()

    def _add(node_text):
        t = _compact(node_text)
        if len(t) >= ENRICH_MIN_LEN:
            key = _norm(t)[:120]
            if key not in seen:
                seen.add(key)
                paras.append(t)

    for p in soup.find_all("p"):
        _add(p.get_text(" ", strip=True))
    if len(paras) < 3:  # pages structurées en listes
        for li in soup.find_all("li"):
            _add(li.get_text(" ", strip=True))
    return paras


def _best_paragraphs(paras, keywords, max_paras=ENRICH_MAX_PARAS):
    """Classe les paragraphes par correspondance avec les mots-clés.

    Score = (mots-clés distincts présents) * 10 + (occurrences totales, plafond 10).
    Ne renvoie que des paragraphes contenant au moins un mot-clé."""
    if not paras:
        return []
    if not keywords:
        return paras[:max_paras]  # requête sans mot-clé exploitable
    scored = []
    kw_set = set(keywords)
    for idx, p in enumerate(paras):
        n = _norm(p)
        distinct = sum(1 for k in kw_set if k in n)
        if distinct == 0:
            continue
        total = sum(n.count(k) for k in keywords)
        score = distinct * 10 + min(total, 10)
        scored.append((score, idx, p))  # idx préserve l'ordre à score égal
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [p for _, _, p in scored[:max_paras]]


def _scrape_url(url: str, keywords):
    """Récupère une page et en extrait les meilleurs paragraphes.

    Retourne (statut, paragraphes) avec statut dans {'live','dead','unknown'}."""
    if not url:
        return "unknown", []
    if not net_guard.is_public_url(url):
        return "unknown", []  # cible interne / tailnet : refus anti-SSRF
    headers = {"User-Agent": _BROWSER_UA, "Accept-Language": "fr,en;q=0.8"}
    try:
        resp = net_guard.safe_request("GET", url, headers=headers,
                                      timeout=ENRICH_TIMEOUT, verify=ENRICH_VERIFY_TLS)
    except (requests.exceptions.RequestException, PermissionError):
        return "unknown", []
    code = resp.status_code
    if code in (404, 410):
        return "dead", []
    if not (200 <= code < 400):
        return "unknown", []
    ctype = resp.headers.get("Content-Type", "").lower()
    if "html" not in ctype and "xml" not in ctype:
        return "live", []  # vivant mais non extractible (PDF, image…)
    try:
        paras = _page_paragraphs(resp.content)
        best = _best_paragraphs(paras, keywords)
    except Exception:
        return "live", []
    return "live", best


def _brave_search(query: str, max_results: int, api_key: str, timeout: int,
                  lang: str, verify: bool, enrich: bool):
    """Appel synchrone Brave Search API — exécuté dans un thread séparé.

    Retourne (succes, texte). succes == True dès que l'appel Brave aboutit
    (HTTP 200), même sans résultat : la requête est alors comptée au quota.
    """
    headers = {
        "Accept":               "application/json",
        "Accept-Encoding":      "gzip",
        "X-Subscription-Token": api_key,
    }
    # On demande un peu plus de candidats si l'on filtre/écarte des liens,
    # sans coût supplémentaire (toujours une seule requête Brave).
    over = verify or enrich
    candidate_count = min(max_results + 5, 20) if over else min(max_results, 20)
    params = {
        "q":                 query,
        "count":             candidate_count,
        "text_decorations":  False,
    }
    params.update(_lang_params(lang))

    try:
        resp = requests.get(BRAVE_API_URL, headers=headers, params=params, timeout=timeout)
    except requests.exceptions.Timeout:
        return False, f"⚠️ Délai dépassé ({timeout}s) : le serveur Brave n'a pas répondu à temps."
    except requests.exceptions.ConnectionError:
        return False, "⚠️ Erreur réseau : impossible de joindre l'API Brave."
    except requests.exceptions.RequestException as e:
        return False, f"⚠️ Erreur réseau Brave : {e}"

    if resp.status_code == 401:
        return False, "⚠️ Clé API Brave invalide ou expirée (HTTP 401) — vérifie-la dans ⚙️ Paramètres."
    if resp.status_code == 429:
        return False, ("⚠️ Quota ou débit Brave dépassé (HTTP 429) — "
                       "palier gratuit : 1 requête/seconde, 2 000/mois.")
    if resp.status_code == 422:
        return False, "⚠️ Requête refusée par Brave (HTTP 422) — paramètres invalides."
    if not resp.ok:
        return False, f"⚠️ Erreur Brave : HTTP {resp.status_code}."

    try:
        data = resp.json()
    except ValueError:
        return False, "⚠️ Réponse Brave illisible (JSON invalide)."

    raw = []
    for r in data.get("web", {}).get("results", []):
        title       = html.unescape(r.get("title", "")).strip()
        description = " ".join(html.unescape(r.get("description", "")).split())
        url         = r.get("url", "")
        if title or description:
            raw.append((title, description, url))

    if not raw:
        return True, "Aucun résultat trouvé."

    # ---- Enrichissement (extraction de paragraphes) : prioritaire sur verify ----
    if enrich:
        keywords = _keywords(query)
        urls = [item[2] for item in raw]
        with ThreadPoolExecutor(max_workers=ENRICH_WORKERS) as ex:
            outcomes = list(ex.map(lambda u: _scrape_url(u, keywords), urls))
        blocks = []
        for (title, description, url), (status, paras) in zip(raw, outcomes):
            if status == "dead":
                continue
            if paras:
                body = "\n".join(f"• {p}" for p in paras)
                blocks.append(f"**{title}**\n{url}\n{body}")
            elif status == "live":
                blocks.append(f"**{title}**\n{description}\n{url}\n(extrait indisponible)")
            else:  # unknown
                blocks.append(f"**{title}**\n{description}\n{url}\n(page non récupérée)")
            if len(blocks) >= max_results:
                break
        if not blocks:
            return True, "Aucun résultat exploitable (liens inaccessibles écartés)."
        return True, "\n\n".join(blocks)

    # ---- Vérification simple (HEAD) ----
    if verify:
        urls = [item[2] for item in raw]
        with ThreadPoolExecutor(max_workers=VERIFY_WORKERS) as ex:
            statuses = list(ex.map(_check_url, urls))
        checked = []
        for (title, description, url), status in zip(raw, statuses):
            if status == "dead":
                continue
            checked.append((title, description, url, status))
        if not checked:
            return True, "Aucun résultat valide trouvé (liens inaccessibles écartés)."
        raw = checked[:max_results]
    else:
        raw = [(t, d, u, "live") for (t, d, u) in raw][:max_results]

    results = []
    for title, description, url, status in raw:
        block = f"**{title}**\n{description}\n{url}"
        if status != "live":
            block += "\n(lien non vérifié)"
        results.append(block)
    return True, "\n\n".join(results)


def _tavily_search(query: str, max_results: int, api_key: str, timeout: int):
    """Recherche via l'API Tavily. Retourne (ok, texte_formaté).
    Tavily renvoie un contenu déjà extrait par résultat → pas de scraping."""
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": True,
    }
    try:
        resp = requests.post(TAVILY_API_URL, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[WEB] Erreur Tavily : {e}")
        return False, "⚠️ Recherche Tavily indisponible pour le moment."

    results = data.get("results", []) or []
    if not results:
        return True, "Aucun résultat."

    blocs = []
    answer = (data.get("answer") or "").strip()
    if answer:
        blocs.append(f"Synthèse Tavily : {answer}")
    for r in results:
        titre   = (r.get("title") or "").strip()
        url     = (r.get("url") or "").strip()
        contenu = _compact((r.get("content") or "").strip())
        blocs.append(f"{titre}\n{url}\n{contenu}")
    return True, "\n\n".join(blocs)


async def search(query: str, max_results: int = 5, lang: str = None,
                 verify: bool = None, enrich: bool = None) -> str:
    """
    Recherche Brave Search — non-bloquante via run_in_executor.

    Langue (priorité) : paramètre `lang` > directive « lang:xx » > français.
    `lang:any` / `all` / `*` => recherche mondiale.

    Enrichissement : si activé (ENRICH_PARAGRAPHS / enrich=True), chaque page
    est récupérée et ses paragraphes les plus proches des mots-clés sont
    renvoyés. Cette étape valide aussi les liens (remplace le contrôle HEAD).
    `verify` ne sert qu'en mode léger, quand l'enrichissement est désactivé.

    Le quota Brave n'est incrémenté que lorsque l'appel API a abouti.
    """
    from core.database import get_api_keys
    keys = get_api_keys()
    brave_key  = (keys.get('brave')  or '').strip()
    tavily_key = (keys.get('tavily') or '').strip()
    try:
        pref = (get_setting('search_provider', 'auto') or 'auto').strip().lower()
    except Exception:
        pref = 'auto'

    engine = _choose_engine(pref, brave_key, tavily_key)
    if engine is None:
        return ("⚠️ Aucune clé de recherche configurée — ajoute une clé Brave ou Tavily "
                "dans ⚙️ Paramètres (brave.com/search/api ou tavily.com).")

    inline_lang, query_wo_lang = _extract_lang(query)
    effective_lang = lang or inline_lang or DEFAULT_LANG
    do_enrich = ENRICH_PARAGRAPHS if enrich is None else enrich
    do_verify = (VERIFY_URLS if verify is None else verify) and not do_enrich
    clean = _clean_query(query_wo_lang)

    if not ENRICH_VERIFY_TLS:
        try:
            from urllib3.exceptions import InsecureRequestWarning
            warnings.simplefilter("ignore", InsecureRequestWarning)
        except Exception:
            pass

    if _LOG_QUERIES:
        print(f"[WEB] Requête {engine} : «{clean}» (langue={effective_lang}, "
              f"enrich={do_enrich}, vérif={do_verify}, original : «{query[:60]}»)")
    else:
        print(f"[WEB] Requête {engine} envoyée ({len(clean)} caractères, "
              f"langue={effective_lang}, enrich={do_enrich}, vérif={do_verify}).")

    loop = asyncio.get_running_loop()
    if engine == 'tavily':
        ok, result = await loop.run_in_executor(
            None, _tavily_search, clean, max_results, tavily_key, TAVILY_TIMEOUT
        )
        cost_provider, cost_model = 'tavily', 'tavily-search'
    else:
        ok, result = await loop.run_in_executor(
            None, _brave_search, clean, max_results, brave_key, BRAVE_TIMEOUT,
            effective_lang, do_verify, do_enrich
        )
        cost_provider, cost_model = 'brave', 'brave-search'

    if ok:
        try:
            from core.database import log_cost
            log_cost(cost_provider, cost_model, 0, 0)
        except Exception:
            pass

    return result


# ════════════════════════════════════════════════════════════════════
# CACHE DES RECHERCHES (références web)
# ════════════════════════════════════════════════════════════════════

def _strip_accents_lower(s: str) -> str:
    import unicodedata
    s = (s or "").lower()
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")

def _norm_query(q: str) -> str:
    return " ".join(_strip_accents_lower(q).split())

def _ttl_jours(query: str) -> int:
    """Durée de vie (jours) selon la périssabilité estimée de la requête."""
    n = _norm_query(query)
    if any(mot in n for mot in _MOTS_EPHEMERES):
        return WEBCACHE_TTL_EPHEMERE
    return WEBCACHE_TTL_DEFAULT

def _query_vector(query: str):
    """Embedding de la requête via le modèle mémoire, ou None si indisponible."""
    try:
        from modules.memory import _embed
        return _embed(query)
    except Exception:
        return None

def _cache_lookup(norm: str, qvec):
    """Retourne le contenu mémorisé d'une recherche proche et non périmée, sinon None."""
    from core.database import get_active_web_references
    try:
        refs = get_active_web_references()
    except Exception:
        return None
    if qvec is not None:
        from modules.memory import _parse_embedding, _cosine
        best, best_s = None, 0.0
        for r in refs:
            rv, _m = _parse_embedding(r.get('embedding'))
            if rv is None:
                continue
            s = _cosine(qvec, rv)
            if s > best_s:
                best_s, best = s, r
        if best is not None and best_s >= WEBCACHE_SIM_MIN:
            return best['content']
        return None
    # Repli sans embeddings : correspondance exacte de requête normalisée.
    for r in refs:
        if r.get('query_norm') == norm:
            return r['content']
    return None

def _save_reference(query: str, norm: str, content: str, qvec, expiration):
    """Écrit une référence en base (expiration = ISO ou None pour permanent)."""
    from core.database import save_web_reference
    emb = None
    if qvec is not None:
        try:
            from modules.memory import _serialize_embedding
            emb = _serialize_embedding(qvec)
        except Exception:
            emb = None
    try:
        save_web_reference(query, norm, content, emb, expiration, source="recherche")
    except Exception as e:
        print(f"[WEBCACHE] Stockage impossible : {e}")

# Tâches de fond (stockage + classification), gardées pour éviter le GC prématuré.
_bg_tasks = set()

def _schedule_store(coro):
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    t = loop.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)

async def _store_task(query: str, norm: str, content: str, qvec, classify):
    """Classe la périssabilité (LLM via `classify`, repli heuristique) puis stocke.
    Exécutée en arrière-plan : n'ajoute aucune latence à la recherche."""
    import asyncio
    from datetime import datetime, timedelta
    ttl = None
    if classify is not None:
        try:
            ttl = await asyncio.wait_for(classify(query, content), timeout=10)
        except Exception:
            ttl = None
    if ttl is None:
        ttl = _ttl_jours(query)  # repli : heuristique par mots-clés
    # ttl == 0 → information permanente, pas d'expiration.
    expiration = None if ttl == 0 else (datetime.now() + timedelta(days=ttl)).isoformat()
    _save_reference(query, norm, content, qvec, expiration)

async def search_with_cache(query: str, max_results: int = 5, classify=None) -> str:
    """
    Comme `search()`, mais :
      - réutilise un résultat déjà obtenu pour une requête proche et NON périmée
        (gain de temps, mémoire des recherches passées) ;
      - mémorise les nouveaux résultats EN ARRIÈRE-PLAN (zéro latence ajoutée),
        avec une expiration fonction de la périssabilité estimée.

    `classify` (optionnel) : coroutine `classify(query, content) -> jours | 0 | None`.
      jours > 0 = durée de vie ; 0 = permanent ; None = indéterminé (repli
      heuristique éphémère/normale). Fournie par hub (classement LLM, qui peut
      s'appuyer sur un extrait du contenu) ; appelée uniquement en défaut de cache.

    Si les embeddings sont indisponibles, repli sur une correspondance exacte de
    requête. Tout échec du cache laisse la recherche normale se poursuivre.
    """
    if not WEBCACHE_ENABLED:
        return await search(query, max_results)

    norm = _norm_query(query)
    qvec = _query_vector(query)

    cached = _cache_lookup(norm, qvec)
    if cached is not None:
        print("[WEBCACHE] ♻️ Réutilisation d'une recherche mémorisée.")
        return cached

    result = await search(query, max_results)

    # On ne mémorise que les vraies réponses (ni erreur, ni absence de résultat),
    # et on le fait en arrière-plan pour ne pas retarder la réponse.
    indesirable = (not result) or result.startswith("⚠️") or result.startswith("Aucun résultat")
    if not indesirable:
        _schedule_store(_store_task(query, norm, result, qvec, classify))
    return result
