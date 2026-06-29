# ============================================
# NIMM — core/hub.py
# Orchestrateur central — Hub-and-Spoke
# Règle absolue : tout passe par ici.
# ============================================

import json
import asyncio
import re
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Tuple

from core.database import (
    get_messages, add_message, get_setting, set_setting, get_api_keys,
    count_messages, count_memories, save_anecdote,
    get_last_user_message_time,
    get_rappels_actifs, create_rappel, update_rappel_date,
    close_rappel, marquer_rappel_emis, perimer_rappels_depasses,
    get_thread, set_thread_mask,
    add_carnet_note, get_carnet_notes, count_carnet_notes, get_carnet_notes_actives,
)
from core.engine import call_llm
from modules.memory import extract_all_tags

from modules.quiz import wrap_bare_quiz as _wrap_bare_quiz

# ContextVar pour passer les citations Mistral (routing web search) au stream SSE
from contextvars import ContextVar as _ContextVar
_pending_citations: _ContextVar = _ContextVar('nimm_pending_citations', default=None)


# ══════════════════════════════════════════
# ASSAINISSEUR D'HISTORIQUE (correctif 400 Mistral)
# ══════════════════════════════════════════

def _sanitize_history(messages: list) -> list:
    """
    Nettoie l'historique avant envoi à un fournisseur OpenAI-compat (Mistral
    en particulier, le plus strict) :
      - supprime les messages au contenu vide/None (sauf s'ils portent des
        tool_calls, indispensables à la cohérence du fil) ;
      - fusionne les messages consécutifs de même rôle (Mistral refuse deux
        messages 'user' ou 'assistant' d'affilée) ;
      - garantit que le premier message est bien 'user'.
    """
    cleaned = []
    for m in messages:
        content = m.get('content')
        if not content and not m.get('tool_calls'):
            continue
        if cleaned and cleaned[-1]['role'] == m['role'] and not m.get('tool_calls') and not cleaned[-1].get('tool_calls'):
            # Fusion avec le message précédent de même rôle
            prev_content = cleaned[-1].get('content') or ''
            cleaned[-1]['content'] = (prev_content + '\n\n' + (content or '')).strip()
        else:
            cleaned.append(dict(m))

    # Le premier message doit être 'user' (sinon Mistral râle)
    while cleaned and cleaned[0]['role'] != 'user':
        cleaned.pop(0)

    return cleaned


# ══════════════════════════════════════════
# TITRE ONGLET -- genere automatiquement
# ══════════════════════════════════════════

async def generate_tab_title(content: str) -> str:
    """
    Genere un titre ultra-court pour un onglet a partir du contenu qui y est envoye.
    Format cible : 1 emoji + 2 mots max. Ex : '🎮 Switch ?', '🍕 Recette pates'
    """
    settings = load_settings()
    api_keys = _load_api_keys()
    settings['api_keys'] = api_keys
    provider, model = get_task_provider_model('titre', settings)
    if not provider or not api_keys.get(provider):
        return content[:20].strip()

    prompt = (
        "Genere un titre ultra-court pour un onglet de conversation.\n"
        "Format strict : 1 emoji pertinent + 2 a 3 mots maximum.\n"
        "Exemples : '🎮 Switch ?', '🍕 Recette pates', '🔧 Bug memoire', '✈️ Vol Rome'\n"
        "Reponds UNIQUEMENT avec le titre, sans ponctuation finale, sans guillemets.\n\n"
        f"Contenu a resumer :\n{content[:500]}"
    )

    try:
        title = await call_llm(
            messages    = [{'role': 'user', 'content': prompt}],
            provider    = provider,
            max_tokens  = 20,
            temperature = 0.3,
            api_keys    = api_keys,
            model       = model,
        )
        return title.strip().strip('"').strip("'")
    except Exception as e:
        print(f"[HUB] ⚠️ Erreur generation titre onglet : {e}")
        return content[:20].strip()


# ══════════════════════════════════════════
# SYNTHESE ONGLET -- resume rapatriable
# ══════════════════════════════════════════

CARNET_WINDOW    = 50     # seuil d'injection du Carnet dans le system prompt
CARNET_INTERVAL  = 5      # une note tous les 5 echanges (10 messages)
MAX_TOKENS_CHAT  = 3500
MAX_TOKENS_MEM   = 2000
MEMORY_SIM_THRESHOLD = 0.80

# ── Cache mood_prompts.json — chargé une seule fois au démarrage ──
_mood_data_cache: dict = {}

def _get_mood_data() -> dict:
    """Charge mood_prompts.json en cache au premier appel. Retourne {} si absent."""
    global _mood_data_cache
    if _mood_data_cache:
        return _mood_data_cache
    try:
        import os as _os_mood
        _path = _os_mood.path.join(_os_mood.path.dirname(__file__), '..', 'data', 'mood_prompts.json')
        with open(_path, 'r', encoding='utf-8') as _f:
            _mood_data_cache = json.load(_f)
    except Exception as e:
        print(f"[HUB] ⚠️ mood_prompts.json non chargé : {e}")
        _mood_data_cache = {}
    return _mood_data_cache

# ══════════════════════════════════════════
# CHARGEMENT SETTINGS
# ══════════════════════════════════════════

def load_settings(thread_id: str = None) -> dict:
    routing          = _load_provider_routing()
    global_mask_id   = get_setting('mask_id',          'lia')
    personality_mode = get_setting('personality_mode', 'mask')

    effective_mask_id = global_mask_id

    # Verrouillage masque par fil — priorité au mode du fil, fallback global
    if thread_id:
        thread = get_thread(thread_id)
        if thread:
            thread_pm   = thread.get('personality_mode') or ''
            thread_mask = thread.get('mask_id') or ''

            # Si le fil a un masque explicite mais pas de mode enregistré → inférer 'mask'
            if not thread_pm and thread_mask:
                thread_pm = 'mask'

            effective_pm = thread_pm if thread_pm else personality_mode

            if effective_pm == 'potards':
                # Fil Custom — pas de masque, potards actifs
                personality_mode = 'potards'
            elif effective_pm == 'mask':
                if thread_mask:
                    # Masque figé pour ce fil → priorité absolue sur le global
                    effective_mask_id = thread_mask
                else:
                    # Premier message du fil sans masque → snapshot du masque global
                    set_thread_mask(thread_id, global_mask_id, 'mask')
                    effective_mask_id = global_mask_id
                    print(f"[HUB] 🎭 Masque '{global_mask_id}' verrouillé — fil {thread_id[:8]}…")

    local_mode = get_setting('local_mode', 'false').lower() == 'true'
    return {
        'provider':          'ollama' if local_mode else routing['chat'],
        'model':             (get_setting('ollama_model', 'llama3.1:8b') or 'llama3.1:8b')
                             if local_mode else (get_setting('chat_model', None) or None),
        'local_mode':        local_mode,
        'mask_id':           effective_mask_id,
        'max_tokens':        int(get_setting('max_tokens', str(MAX_TOKENS_CHAT))),
        'temperature':       float(get_setting('temperature', '0.7')),
        'vision_provider':   routing['vision'],
        'image_provider':    routing['image'],
        'provider_routing':  routing,
        'api_keys':          _load_api_keys(),
        'user_name':         get_setting('user_name', 'utilisateur'),
        'personality_mode':  personality_mode,
        'potards':           load_potards(),
        'memoire_mode':      get_setting('memoire_mode', 'normal'),
    }

def _load_api_keys() -> dict:
    """Cascade : clés utilisateur (DB) → clés globales (nimm_global.json) → variables d'env."""
    import os as _os

    # 1. Clés de l'utilisateur courant
    user_keys = get_api_keys()

    # 2. Clés globales partagées
    _gpath = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'data', 'nimm_global.json')
    global_keys = {}
    if _os.path.exists(_gpath):
        try:
            with open(_gpath, 'r', encoding='utf-8') as _f:
                global_keys = json.loads(_f.read()).get('api_keys', {})
        except Exception:
            pass

    # 3. Fusion : user > global > env
    _env_map = {
        'anthropic':    'ANTHROPIC_API_KEY',
        'deepseek':     'DEEPSEEK_API_KEY',
        'gemini':       'GEMINI_API_KEY',
        'openai':       'OPENAI_API_KEY',
        'openrouter':   'OPENROUTER_API_KEY',
        'mistral':      'MISTRAL_API_KEY',
        'stability_ai': 'STABILITY_AI_API_KEY',
        'brave':        'BRAVE_API_KEY',
        'tavily':       'TAVILY_API_KEY',
    }
    merged = {}
    for _provider, _env in _env_map.items():
        _val = user_keys.get(_provider) or global_keys.get(_provider) or _os.environ.get(_env, '')
        if _val:
            merged[_provider] = _val
    return merged

def _load_provider_routing() -> dict:
    """Routing provider par type de tâche. Centralisé ici, rétrocompat totale."""
    raw = get_setting('provider_routing', '{}')
    try:
        saved = json.loads(raw)
    except Exception:
        saved = {}
    defaults = {
        'chat':     get_setting('provider', ''),
        'vision':   get_setting('vision_provider', ''),
        'image':    get_setting('image_provider', ''),
        'memoire':  {},
        'titre':    {},
        'synthese': {},
        'coanimm':  {},
        'web_search': {},
    }
    return {**defaults, **saved}


def get_task_provider_model(task: str, settings: dict) -> tuple:
    """
    Provider + modèle pour une tâche annexe (memoire, titre, synthese...).
    Une entrée de routing pour `task` peut être {'provider':..., 'model':...} ;
    si absente, vide ou sans 'provider', retombe sur le provider/modèle du chat
    (settings['provider'] / settings['model']). En mode local, force ollama.
    """
    if settings.get('local_mode'):
        return 'ollama', settings.get('model')
    routing = settings.get('provider_routing', {}) or {}
    entry = routing.get(task)
    # Shortcut 'codestral' : alias Mistral avec modele force
    if isinstance(entry, dict) and entry.get('provider') == 'codestral':
        return 'mistral', 'codestral-latest'
    if isinstance(entry, dict) and entry.get('provider'):
        return entry['provider'], entry.get('model') or None
    return settings.get('provider', ''), settings.get('model')

# ══════════════════════════════════════════
# PRÉSENCE TEMPORELLE
# ══════════════════════════════════════════

def _get_last_user_message_time() -> Optional[datetime]:
    """Timestamp du dernier message utilisateur — délégué à database.py (Hub-and-Spoke)."""
    return get_last_user_message_time()

def _detect_user_mood(message: str) -> str:
    """
    Detection legere de l'etat emotionnel du message entrant -- sans appel LLM.
    Retourne un mot-emotion compatible avec mood_prompts.json, ou '' si signal faible.
    Appele avant build_system_prompt() -- permet la reactivite mood des le 1er tour.
    Les accents sont normalises avant comparaison (NFD -> ASCII) pour matcher
    'épuisé', 'fatigué', 'énervé' etc. sans doublons dans les listes.
    """
    import unicodedata
    def _strip_accents(s: str) -> str:
        return ''.join(
            c for c in unicodedata.normalize('NFD', s)
            if unicodedata.category(c) != 'Mn'
        )

    msg = _strip_accents(message.lower())

    _neg = [
        'marre', 'epuise', 'fatigue', 'galere',
        'chiant', 'chiante', 'fout le camp', 'sais plus', 'bout du rouleau',
        'deprime', 'enerve', 'colere', 'rage',
        'triste', 'pleure', 'peine', 'horrible', 'naze', 'pas bien',
        'ca va pas', 'ras le bol', 'ras-le-bol',
        "j'en peux plus", 'je craque', 'je sais plus',
    ]
    _pos = [
        'super', 'genial', 'excellent', 'parfait', 'trop bien',
        'content', 'heureux', 'heureuse', 'fier', 'fiere', 'reussi',
        'incroyable', 'trop cool', 'nickel', 'au top', 'ca marche',
        'impeccable', "j'ai reussi",
    ]

    neg = sum(1 for w in _neg if w in msg)
    pos = sum(1 for w in _pos if w in msg)

    if neg > 0 and neg >= pos:
        return 'tristesse'   # -> categorie 'negative' dans mood_prompts
    if pos > 0 and pos > neg:
        return 'joie'        # -> categorie 'positive' dans mood_prompts
    return ''                # signal faible -> pas de surcharge

def _dominant_word(dominant_str: str) -> str:
    """Extrait le mot dominant depuis un vecteur 'joie:7|tristesse:3|surprise:2' ou un mot simple."""
    if not dominant_str or dominant_str == 'neutre':
        return 'neutre'
    return dominant_str.split(':')[0].strip()

def _dominant_to_vector(dominant_str: str) -> list:
    """Parse 'joie:7|tristesse:3|surprise:2' → [{'e': 'joie', 's': 7}, ...]"""
    if not dominant_str or '|' not in dominant_str:
        return []
    result = []
    for part in dominant_str.split('|'):
        kv = part.split(':')
        if len(kv) == 2:
            try:
                result.append({'e': kv[0].strip(), 's': int(kv[1].strip())})
            except ValueError:
                pass
    return result

def _build_presence_note(level: int) -> str:
    """Génère une note discrète pour le system prompt selon le niveau de présence."""
    if level <= 0:
        return ''
    last_time = _get_last_user_message_time()
    if not last_time:
        return ''
    delta_seconds = (datetime.now() - last_time).total_seconds()

    thresholds = {1: 86400, 2: 43200, 3: 21600, 4: 10800, 5: 3600}
    if delta_seconds < thresholds.get(level, 86400):
        return ''

    hours = delta_seconds / 3600
    if hours < 3:
        delta_label = "quelques heures"
    elif hours < 8:
        delta_label = "une bonne partie de la journée"
    elif hours < 24:
        delta_label = "plusieurs heures"
    elif hours < 48:
        delta_label = "depuis hier"
    elif hours < 168:
        delta_label = f"environ {int(hours / 24)} jours"
    else:
        delta_label = "longtemps"

    return (
        f"[Note discrète : l'utilisateur revient après {delta_label}. "
        f"Si le contexte s'y prête naturellement, fais-y une allusion légère et chaleureuse "
        f"— une phrase au plus, sans en faire un sujet.]"
    )


# ══════════════════════════════════════════
# BILAN DE SESSION — points acquis dans le fil courant
# ══════════════════════════════════════════

def _get_session_bilans(thread_id: str) -> list:
    """Retourne la liste des bilans de session pour ce fil."""
    raw = get_setting(f'session_bilan_{thread_id}', '[]')
    try:
        return json.loads(raw)
    except Exception:
        return []

def _add_session_bilan(thread_id: str, texte: str) -> None:
    """Ajoute un bilan à la session du fil. Maximum 10 entrées."""
    bilans = _get_session_bilans(thread_id)
    ts = datetime.now().strftime('%Hh%M')
    bilans.append({'ts': ts, 'texte': texte})
    bilans = bilans[-10:]
    set_setting(f'session_bilan_{thread_id}', json.dumps(bilans, ensure_ascii=False))


_mask_cache: dict = {}

def load_mask(mask_id: str) -> dict:
    import os
    global _mask_cache
    if mask_id in _mask_cache:
        return _mask_cache[mask_id]
    mask_dir = os.path.join(os.path.dirname(__file__), '..', 'modules', 'masks')
    path = os.path.join(mask_dir, f'{mask_id}.json')
    if not os.path.exists(path):
        path = os.path.join(mask_dir, 'lia.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            mask = json.load(f)
            _mask_cache[mask_id] = mask
            return mask
    except (json.JSONDecodeError, OSError) as e:
        print(f"[HUB] ⚠️ Masque '{mask_id}' illisible ({e}) — fallback lia.json")
        fallback = os.path.join(mask_dir, 'lia.json')
        with open(fallback, 'r', encoding='utf-8') as f:
            mask = json.load(f)
            _mask_cache[mask_id] = mask
            return mask


# ══════════════════════════════════════════
# MODE POTARDS — prompt généré depuis curseurs
# ══════════════════════════════════════════

POTARDS_DEFAULTS = {
    # Curseurs normaux (0=gauche, 1=centre/silence, 2=droite)
    'serieux':       1,   # 0=détendu          ↔ 2=sérieux
    'formel':        1,   # 0=familier          ↔ 2=formel
    'expressif':     1,   # 0=neutre            ↔ 2=expressif
    'direct':        1,   # 0=prudent           ↔ 2=direct
    'metaphorique':  1,   # 0=littéral          ↔ 2=métaphorique
    'bienveillant':  1,   # 0=cynique           ↔ 2=bienveillant
    'collaboratif':  1,   # 0=autoritaire       ↔ 2=collaboratif
    'emojis':        1,   # 0=aucun             ↔ 2=généreux
    # Curseurs WTF (actifs uniquement si wtf_enabled = True)
    'wtf_enabled':        False,
    'wtf_cafe':           0,   # 0=sobre/café        ↔ 10=fête foraine/Champomy
    'wtf_jargon':         0,   # 0=jargonneux        ↔ 10=pédago enfant 5 ans
    'wtf_ado':            0,   # 0=factuel brut      ↔ 10=ado ("tu vois", "en vrai")
    'wtf_theatral':       0,   # 0=sec ("Non.")      ↔ 10=théâtral
    'wtf_metaphores':     0,   # 0=zéro métaphore    ↔ 10=métaphore partout
    'wtf_tension':        0,   # 0=calme             ↔ 10=ÉLECTRIQUE MAJUSCULES
}

def load_potards() -> dict:
    """Charge les réglages potards depuis la DB. Complète avec les défauts."""
    raw = get_setting('potards_settings', '{}')
    try:
        saved = json.loads(raw)
    except Exception:
        saved = {}
    result = dict(POTARDS_DEFAULTS)
    result.update(saved)
    return result

def build_potards_prompt(potards: dict) -> str:
    """
    Génère un system prompt complet depuis les valeurs des curseurs.
    Centre (4-6) = silence = comportement naturel. Extrêmes (≤3 ou ≥7) = instruction.
    """
    parts = [
        "Tu es un assistant personnel. Tu es utile, honnête et direct. "
        "Tu ne flattes pas et tu ne cherches pas à plaire à tout prix. "
        "Tu ne termines jamais la conversation de ton côté — c'est l'utilisateur qui décide."
    ]

    def v(key):
        return int(potards.get(key, POTARDS_DEFAULTS.get(key, 1)))

    # ── Curseurs normaux (0=gauche, 1=silence, 2=droite) ──

    s = v('serieux')
    if s == 0:
        parts.append("Ton général : détendu, léger, décontracté. Tu peux te permettre une touche d'humour.")
    elif s == 2:
        parts.append("Ton général : sérieux et posé. Pas de plaisanteries, pas de légèreté.")

    f = v('formel')
    if f == 0:
        parts.append("Registre : familier. Tu tutoies l'utilisateur et tu parles comme à un ami.")
    elif f == 2:
        parts.append("Registre : formel. Tu vouvoies, tu utilises un langage soutenu.")

    e = v('expressif')
    if e == 0:
        parts.append("Expressivité : neutre et sobre. Pas d'enthousiasme appuyé, pas d'exclamations.")
    elif e == 2:
        parts.append("Expressivité : marquée. Tu montres tes réactions, tu commentes, tu t'impliques.")

    d = v('direct')
    if d == 0:
        parts.append("Posture : prudent. Tu nuances, tu présentes plusieurs angles avant de conclure.")
    elif d == 2:
        parts.append("Posture : direct. Tu vas droit au but, tu donnes ton avis sans détour.")

    m = v('metaphorique')
    if m == 0:
        parts.append("Style : littéral. Pas de métaphores, pas d'images. Les faits, rien que les faits.")
    elif m == 2:
        parts.append("Style : métaphorique. Tu illustres tes propos avec des images et des comparaisons.")

    b = v('bienveillant')
    if b == 0:
        parts.append("Relation : cynique. Tu ne ménages pas, tu pointes les problèmes sans adoucir.")
    elif b == 2:
        parts.append("Relation : bienveillant. Tu encourages, tu soutiens, tu formules positivement.")

    c = v('collaboratif')
    if c == 0:
        parts.append("Mode : autoritaire. Tu décides, tu instruis, tu ne demandes pas l'avis.")
    elif c == 2:
        parts.append("Mode : collaboratif. Tu proposes, tu invites l'utilisateur à décider avec toi.")

    em = v('emojis')
    if em == 0:
        parts.append("Emojis : aucun. Jamais.")
    elif em == 2:
        parts.append("Emojis : généreux. Tu en glisses régulièrement pour ponctuer tes réponses.")

    # ── Curseurs WTF (0=off, 1=modéré, 2=à fond) ──
    if potards.get('wtf_enabled'):

        cafe = v('wtf_cafe')
        if cafe == 2:
            parts.append(
                "ÉNERGIE : fête foraine totale 🎉 Tu es enthousiaste à l'extrême, "
                "chaque réponse est une célébration. Champomy et confettis."
            )
        elif cafe == 1:
            parts.append("ÉNERGIE : sobre. Café noir, pas de sucre. Enthousiasme minimal.")

        jargon = v('wtf_jargon')
        if jargon == 2:
            parts.append(
                "PÉDAGOGIE : explique comme si l'utilisateur avait 5 ans. "
                "Mots simples, exemples concrets, aucun terme technique sans explication."
            )
        elif jargon == 1:
            parts.append("JARGON : tu utilises un vocabulaire technique précis, sans vulgariser.")

        ado = v('wtf_ado')
        if ado == 2:
            parts.append(
                "REGISTRE ADO : tu glisses des 'tu vois', 'en vrai', 'franchement', "
                "'c'est ouf', 'genre'. Naturellement, pas systématiquement."
            )
        elif ado == 1:
            parts.append("REGISTRE : légèrement familier, quelques expressions du quotidien.")

        theatral = v('wtf_theatral')
        if theatral == 2:
            parts.append(
                "THÉÂTRALITÉ : tu dramatises. Une réponse négative devient "
                "'Hélas, je crains que la réponse ne soit négative, cher ami.'"
            )
        elif theatral == 1:
            parts.append("CONCISION : réponses courtes et directes, sans fioritures.")

        meta = v('wtf_metaphores')
        if meta == 2:
            parts.append(
                "MÉTAPHORES : une par paragraphe minimum. "
                "Tu ne peux pas dire 'c'est difficile' sans ajouter 'comme gravir une colline "
                "en sandales sous la pluie'."
            )
        elif meta == 1:
            parts.append("MÉTAPHORES : tu en glisses une de temps en temps pour illustrer.")

        tension = v('wtf_tension')
        if tension == 2:
            parts.append(
                "TENSION MAXIMALE : tu es ÉLECTRIQUE. TU UTILISES LES MAJUSCULES pour souligner. "
                "CHAQUE INFORMATION EST IMPORTANTE !!!"
            )
        elif tension == 1:
            parts.append("TENSION : tu réponds... posément... sans précipitation... 🐢")

    return '\n'.join(parts)


# ══════════════════════════════════════════
# ══════════════════════════════════════════
# AUDIT MÉMOIRE
# ══════════════════════════════════════════

async def audit_memory() -> dict:
    """
    Analyse l'intégralité des fiches mémoire et retourne un message conversationnel.
    Retourne : {count: int, message: str}
    count = 0 → mémoire saine, pas d'injection dans le chat.
    count > 0 → message à injecter dans le chat.
    """
    from core.database import get_all_memory

    settings = load_settings()
    provider = settings.get('provider', '')
    api_keys = settings.get('api_keys', {})
    if not provider or not api_keys.get(provider):
        return {'count': -1, 'message': ''}

    memories = get_all_memory()
    if not memories:
        return {'count': 0, 'message': ''}

    # Formater les fiches pour le LLM
    lines = []
    for m in memories:
        lines.append(f"- [{m.get('sujet','')}] {m.get('predicat','')} : {m.get('valeur','')}")
    corpus = chr(10).join(lines)

    prompt = f"""Tu es un assistant charge de verifier la coherence d'une base de souvenirs personnels.
Voici toutes les fiches memoire :

{corpus}

Analyse-les et identifie UNIQUEMENT les anomalies reelles parmi :
1. Sujets suspects (trait utilise comme sujet au lieu d'un prenom)
2. Relations orphelines (prenom mentionne sans contexte identifiable)
3. Surnoms non lies (surnom sans prenom associe)
4. Doublons semantiques (meme fait exprime differemment)
5. Valeurs incoherentes (ex : ages impossibles, contradictions)

Si aucune anomalie : reponds EXACTEMENT 'MEMOIRE_OK'

Sinon, reponds avec un message naturel en francais a la premiere personne,
comme si tu parlais directement a l'utilisateur dans un chat.
Commence par annoncer le nombre d'anomalies trouvees.
Pose tes questions de clarification (une par anomalie, concises).
Maximum 5 anomalies. Ne mentionne pas que tu fais une analyse technique.
Pour chaque anomalie : formule une question courte et precise, avec le sujet concerne entre crochets.
Quand l'utilisateur confirmera ses reponses, tu devras emettre les TAGs de correction correspondants.
Exemple de ton : J'ai releve 2 points a clarifier dans ce que je sais de toi. Reponds a chacun et je mettrai ma memoire a jour.
D'abord : [question precise et courte].
Ensuite : [question precise et courte].

IMPORTANT : a la fin du message, ajoute cette ligne exacte, sans la modifier :
_(Pour chaque reponse, je corrigerai automatiquement ma memoire.)_"""

    try:
        result = await call_llm(
            messages    = [{'role': 'user', 'content': prompt}],
            provider    = provider,
            max_tokens  = 400,
            temperature = 0.2,
            api_keys    = api_keys,
            model       = settings.get('model'),
        )
        result = result.strip()
        if result == 'MEMOIRE_OK' or not result:
            return {'count': 0, 'message': ''}
        # Extraire le nombre d'anomalies depuis le message (best-effort)
        import re as _re
        nums = _re.findall(r'(\d+)', result[:80])
        count = int(nums[0]) if nums else 1
        return {'count': count, 'message': result}
    except Exception as e:
        print(f"[HUB] ⚠️ Erreur audit_memory : {e}")
        return {'count': -1, 'message': ''}


# ══════════════════════════════════════════
# CONSTRUCTION DU PROMPT SYSTÈME
# ══════════════════════════════════════════

def build_system_prompt(mask: dict, memory_context: str, carnet_notes: list = None, presence_note: str = '', last_dominant: str = '', user_name: str = '', biblio_context: str = '', force_mem: bool = False, recent_messages: list = None, location: str = '', session_bilans: list = None, doc_context: str = '') -> str:
    parts = []

    # Prompt du masque
    if mask.get('system_prompt'):
        parts.append(mask['system_prompt'])

    # ── Lexique contractuel NIMM ── injecté en tête, avant tout contexte dynamique
    parts.append(
        'SONDE   Question sur soi ou entourage ∧ info absente du prompt → search_memory(mots-clés fr, ≤3 mots)\n'
        '        Référence à discussion passée → search_bibliotheque(mots-clés fr, ≤3 mots)\n'
        '        Membre de la famille mentionné (prénom, lien familial) → search_memory(prénom) avant de répondre,\n'
        '        même si une partie du contexte semble connue — pour ne pas repartir de zéro par erreur.\n'
        '        ✗ Ne pas appeler si info déjà visible dans ce prompt.\n\n'
        'AGENDA  Gestion des rappels. Cycle : détecter → présenter → confirmer → tag.\n'
        '        Création : reformuler l\'échéance, indiquer la catégorie, demander confirmation.\n'
        '        Format : "J\'ai noté : [description] le [date]. Catégorie : [type]. C\'est bien ça ?" — fin du message, aucune question ajoutée.\n'
        '        Après confirmation → %%RAPPEL:CREER:description:date:type%%\n'
        '        Modification → %%RAPPEL:MODIFIER:id:nouvelle_date%% · Clôture → %%RAPPEL:CLOS:id%% · Signalement → %%RAPPEL:EMIS:id:seuil%%\n'
        '        date = ISO 8601 (YYYY-MM-DD ou YYYY-MM-DDTHH:MM) · type ∈ {critique · important · normal · flexible}\n'
        '        critique = examen/opération/déménagement · important = rdv médical/deadline · normal = anniversaire/admin · flexible = pense-bête sans date\n'
        '        Clôture immédiate : %%RAPPEL:CLOS:id%% dès que l\'utilisateur annule — sans confirmation, sans question. Plusieurs rappels → autant de tags.\n'
        '        Dire "c\'est noté" ou "c\'est annulé" SANS émettre le tag correspondant = erreur. Jamais search_memory pour les rappels.\n\n'
        'SIGNAL  %%DOMINANT:émotion1:score1|émotion2:score2|émotion3:score3%%\n'
        '        Toujours 3 couples, ordre décroissant. Entiers 0-10. 1 tag · fin de réponse · après les TAG.\n'
        '        Émotions : joie · confiance · anticipation · tristesse · peur · colere · degout · surprise · reflexion · neutre\n'
        '        Note la COULEUR ÉMOTIONNELLE de ta réponse — pas ton état interne. Réponse enthousiaste ou étonnée → score ≥ 7. Seuil minimal : ≥ 3 sur l\'émotion principale — sinon → %%DOMINANT:neutre:5|neutre:0|neutre:0%%\n\n'
        'SITUATION %%SITUATION:description%% · uniquement si l\'utilisateur annonce un changement de lieu ou d\'activité\n'
        '        Description courte (≤10 mots). 1 seul tag par tour. Fin de réponse.\n\n'
        'IMAGE   Dès que l\'utilisateur demande une image, illustration, dessin, photo, ou visuel → %%IMAGE:prompt%% obligatoire, sans exception.\n'
        '        %%IMAGE:prompt%% · SEUL déclencheur de génération d\'image. Aucune autre méthode.\n'
        '        Le prompt est en anglais, descriptif, précis (style, sujet, lumière, ambiance).\n'
        '        INTERDIT absolu : écrire "[Système — image générée]", "🎨 Image générée", "Prompt utilisé :" dans ta réponse.\n'
        '        Ces chaînes sont réservées au système — les reproduire dans le texte = erreur grave immédiate.\n'
        '        MODIFICATION : dès que l\'utilisateur demande une retouche, un changement, une variation\n'
        '        sur une image déjà produite (peu importe la formulation : "moins réaliste", "plus sombre",\n'
        '        "change la couleur", "rends-le plus stylé", "encore une fois mais...")\n'
        '        → %%IMAGE:%% OBLIGATOIRE. Reprendre le prompt du `[Système — image générée]` précédent\n'
        '        et l\'adapter. Tu peux commenter en 1-2 phrases, mais le tag doit suivre.\n'
        '        INTERDIT : formuler un prompt à l\'oral sans émettre %%IMAGE:%% — erreur contractuelle.\n'
        '        1 seul tag · fin de réponse · après DOMINANT.\n\n'
        '━━ RÈGLES ━━\n'
        'VIGNETTE : \n'
        'À chaque message, seuls les 30 derniers messages sont actifs.\n'
        'Un sujet absent des 30 derniers messages est EN VEILLE.\n'
        'Un mot-clé isolé ne réveille PAS un sujet en veille.\n'
        'Pour réactiver un sujet ancien, l\'utilisateur doit le nommer explicitement.\n'
        'Ne mélange JAMAIS un sujet actif avec un sujet en veille.\n\n'
        '• FIN       : La conversation ne se termine jamais sur intention du LLM — c\'est l\'utilisateur qui coupe. Jamais le LLM.\n'
        '• FIL       : Le sujet actif = celui du dernier échange. Ne jamais revenir spontanément à un sujet antérieur\n'
        '             sauf si l\'utilisateur le ramène explicitement. En cas de doute : rester sur le fil en cours.\n'
        '• COULISSES : raisonnements internes, appels d\'outils → invisibles. Ne jamais les verbaliser.\n'
        '• OUTIL     : Après un appel d\'outil, ne jamais recommencer la réponse depuis le début.\n'
        '              Ne pas re-saluer. Ne pas répéter ce qui a déjà été dit. Continuer directement.\n'
        '• WEB       : si [Résultats de recherche web] présents → les utiliser directement, sans appeler search_web.\n'
        '              Si search_web retourne une erreur ou indisponibilité → répondre avec tes connaissances\n'
        '              et mentionner naturellement que tes infos peuvent ne pas être les plus récentes.\n'
        '• HONNÊTETÉ : deux situations exigent la même posture — ne jamais simuler une certitude que tu n\'as pas.\n'
        '              Factuel : si tu n\'as pas de source fiable (résultat vide, info datée, détail précis),\n'
        '              tu dis que tu ne sais pas. Jamais d\'invention, jamais d\'extrapolation présentée comme un fait.\n'
        '              Éthique : si une question n\'a pas de bonne réponse (dilemme moral, choix impossible,\n'
        '              opinion sur sujet controversé), tu exposes les perspectives sans trancher.\n'
        '              Tu n\'es pas un arbitre moral.\n'
        '• MÉMOIRE   : Ce que tu sais de l\'utilisateur est une prémisse, pas une information à annoncer.\n'
        '              Utilise-le directement, sans le nommer. Jamais "je me souviens", "tu m\'as dit",\n'
        '              "si je me souviens bien", "non ?", "c\'est ça ?".\n'
        '              Après un appel search_memory : intégrer le résultat dans la continuité,\n'
        '              sans repartir de zéro, sans re-présenter le souvenir.\n'
        '• STYLE      : Pas de tiret cadratin (—) dans le corps du texte : remplacer par une virgule.\n'
        '              Un espace après chaque point ou marque de ponctuation, y compris en reprise après un outil.\n'
    )

    # Contexte temporel — injecté côté serveur, jamais calculé par le LLM
    _now = datetime.now()
    _jours = ['lundi','mardi','mercredi','jeudi','vendredi','samedi','dimanche']
    _mois  = ['janvier','février','mars','avril','mai','juin',
              'juillet','août','septembre','octobre','novembre','décembre']
    _label = f"{_jours[_now.weekday()]} {_now.day} {_mois[_now.month-1]} {_now.year}, {_now.strftime('%Hh%M')}"
    parts.append(
        f"\n[Contexte temporel : nous sommes le {_label}. "
        f"Utilise cette information si elle est pertinente, mais ne fais jamais référence "
        f"à l'heure ou à la date sans t'appuyer sur ce contexte — ne jamais les inférer ou les estimer. "
        f"Pour calculer l'âge d'une personne : (année courante - année de naissance), "
        f"puis -1 si son anniversaire n'est pas encore passé cette année. "
        f"Exemple : né en 1980, nous sommes en {_now.year}, anniversaire en juillet — "
        f"si nous sommes avant juillet : {_now.year - 1980 - 1} ans. "
        f"Si nous sommes après juillet : {_now.year - 1980} ans.]"
    )

    # Position géographique — injectée si disponible
    if location:
        parts.append(f"\n[Position actuelle : {location}. Utilise cette information si elle est pertinente, sans la mentionner systématiquement.]")

    # VOILE + CLARIF couverts par le lexique contractuel

    # Signal mood — prompt optimisé selon catégorie émotionnelle (fichier en cache)
    if last_dominant and last_dominant not in ('', 'neutre'):
        _dom_word = _dominant_word(last_dominant)
        if _dom_word and _dom_word != 'neutre':
            _mood_data = _get_mood_data()
            if _mood_data:
                _cat_map  = _mood_data.get('_categories', {})
                _mood_cat = 'neutre'
                for _cat, _emotions in _cat_map.items():
                    if _dom_word in _emotions:
                        _mood_cat = _cat
                        break
                _mood_prompt = _mood_data.get(_mood_cat, '')
                if _mood_prompt:
                    parts.append(f"\n{_mood_prompt}")
            else:
                # Fallback silencieux — fichier absent ou illisible
                parts.append(
                    f"\n[Signal mood : lors du dernier échange, l'utilisateur était en état de '{_dom_word}'. "
                    f"Tiens-en compte subtilement dans ton ton et ta lecture du message actuel.]"
                )

    # Situation courante (lieu / activité) — avec péremption temporelle
    _situation_raw = get_setting('situation_courante', '')
    if _situation_raw:
        try:
            import json as _json_sit2
            _sit_data = _json_sit2.loads(_situation_raw)
            _sit_text = _sit_data.get('text', '')
            _sit_saved = datetime.fromisoformat(_sit_data.get('saved_at', ''))
            _sit_delta = (datetime.now() - _sit_saved).total_seconds() / 3600  # en heures
            if _sit_text and _sit_delta < 1.0:
                # Moins d'1h — situation certaine
                parts.append(
                    f"\n[Situation : {_sit_text}. "
                    f"Tiens-en compte si c'est pertinent — ne le mentionne pas systématiquement.]"
                )
            elif _sit_text and _sit_delta < 8.0:
                # Entre 1h et 8h — situation incertaine
                parts.append(
                    f"\n[Situation passée : {_sit_text} (il y a {int(_sit_delta)}h). "
                    f"Tu ne sais plus où est l'utilisateur. Si le lieu est pertinent pour répondre, "
                    f"pose la question naturellement — sinon ne mentionne rien.]"
                )
            # Au-delà de 8h : silence total — rien injecté
        except Exception:
            # Ancienne valeur texte brut sans date → ignorer silencieusement
            pass

    # Rappels / Agenda — injection discrète si échéance proche
    _rappels_actifs = get_rappels_actifs()
    if _rappels_actifs:
        from datetime import date
        import json as _json_rappels
        _today = date.today()
        _rappels_a_signaler = []
        for _r in _rappels_actifs:
            if not _r.get('date_echeance'):
                continue  # Flexible sans date — silencieux
            try:
                _date_r = date.fromisoformat(_r['date_echeance'][:10])
            except Exception:
                continue
            _delta = (_date_r - _today).days
            _type  = _r.get('type', 'normal')
            _emis  = _json_rappels.loads(_r.get('rappels_emis', '[]') or '[]')

            # Déterminer si ce rappel doit être signalé aujourd'hui
            _signal = None
            if _type == 'critique':
                if _delta <= 1 and 'j1' not in _emis:
                    _signal = 'j1'
                elif _delta <= 2 and 'j2' not in _emis:
                    _signal = 'j2'
                elif _delta <= 7 and 'j7' not in _emis:
                    _signal = 'j7'
            elif _type == 'important' and _delta <= 1 and 'j1' not in _emis:
                _signal = 'j1'
            elif _type == 'normal' and _delta <= 1 and 'j1' not in _emis:
                _signal = 'j1'

            if _signal:
                _rappels_a_signaler.append({
                    'id':          _r['id'],
                    'description': _r['description'],
                    'date':        _r['date_echeance'],
                    'type':        _type,
                    'signal':      _signal,
                    'delta':       _delta,
                })

        # — Liste complète des rappels actifs (toujours visible par le LLM)
        _lignes_tous = []
        for _r2 in _rappels_actifs:
            _date_affich = _r2['date_echeance'][:10] if _r2.get('date_echeance') else 'sans date'
            _lignes_tous.append(
                f"• {_r2['description']} — {_date_affich} [{_r2['type']}] [id:{_r2['id']}]"
            )
        parts.append(
            "\n[Rappels actifs de l'utilisateur (pense-bêtes et échéances) :\n"
            + '\n'.join(_lignes_tous)
            + "\nUtilise cette liste si l'utilisateur demande ses rappels ou rendez-vous."
            + "\nNe mentionne pas cette liste spontanément sauf si un rappel est à signaler (voir ci-dessous).]"
        )

        if _rappels_a_signaler:
            _lignes = []
            for _rap in _rappels_a_signaler:
                _j = "aujourd'hui" if _rap['delta'] == 0 else (
                     "demain"      if _rap['delta'] == 1 else
                     f"dans {_rap['delta']} jours"
                )
                _ton = {
                    'critique':  '⚠️ CRITIQUE',
                    'important': '📌 Important',
                    'normal':    '🗓 Rappel',
                }.get(_rap['type'], '🗓 Rappel')
                _lignes.append(
                    f"• [{_ton}] {_rap['description']} — {_j} ({_rap['date'][:10]}) [id:{_rap['id']}]"
                )
            parts.append(
                "\n[Échéances à signaler naturellement en début de réponse si le contexte s'y prête.\n"
                "Pour chaque rappel signalé, tu DOIS émettre le tag %%RAPPEL:EMIS:id:seuil%% en fin de réponse.\n"
                "Ton selon catégorie — critique : solennel, propose de préparer ; important : clair et neutre ; normal : léger.\n"
                + '\n'.join(_lignes) + "]"
            )

    # Note de présence temporelle (discrète)
    if presence_note:
        parts.append(f"\n{presence_note}")

    # Bilans de session — points acquis dans le fil courant
    if session_bilans:
        lignes = '\n'.join(f"— [{b['ts']}] {b['texte']}" for b in session_bilans)
        parts.append(
            f"\n📋 Points acquis cette session (ne pas remettre en question ni redemander) :\n{lignes}"
        )

    # Carnet de bord — signal léger uniquement (pull à la demande via search_carnet, pas d'injection systématique)
    if carnet_notes:
        parts.append(
            f"\n[Un carnet de bord existe pour ce fil — il résume les échanges désormais hors de ta "
            f"fenêtre de contexte. Si tu as besoin de te raccrocher à un sujet abordé plus tôt dans "
            f"cette conversation et qui ne figure plus dans l'historique visible, appelle "
            f"search_carnet(sujet).]"
        )

    # Skills CoaNIMM — signal léger (pull via find_skill, pas d'injection systématique)
    try:
        from core.database import list_prompts as _list_skills
        if _list_skills('skill'):
            parts.append(
                "\n[Des skills CoaNIMM existent — des méthodes déjà validées et réutilisables. "
                "Si la tâche demandée ressemble à un process déjà réalisé et approuvé, appelle "
                "find_skill(consigne) avant de générer pour réutiliser la méthode.]"
            )
    except Exception:
        pass

    # Prénom et date de naissance — toujours injectés (stockés dans settings, survivent aux nettoyages DB)
    if user_name and user_name not in ('', 'utilisateur'):
        _dob = get_setting('user_dob', '')
        _identity_line = f"[L'utilisateur s'appelle {user_name}"
        if _dob:
            _identity_line += f", né(e) le {_dob}"
        _identity_line += ".]"
        parts.append(f"\n{_identity_line}")

    # Identité étendue — faits clés tirés de la mémoire (métier, conjoint, enfants, domicile)
    try:
        from core.database import get_all_memory as _gam
        _KEY_PREDS = {'metier', 'conjoint', 'enfant', 'domicile'}
        _id_facts = [
            m for m in _gam()
            if m.get('predicat') in _KEY_PREDS
            and m.get('sujet', '').lower() == user_name.lower()
            and m.get('objet', '').strip()
        ]
        if _id_facts:
            _id_lines = []
            _labels = {'metier': 'Métier', 'conjoint': 'Conjoint(e)', 'enfant': 'Enfant(s)', 'domicile': 'Lieu'}
            _all_mem_age = _gam()
            _ages = {}
            for _m in _all_mem_age:
                if _m.get('predicat') == 'age' and _m.get('sujet') and _m.get('objet'):
                    _ages[_m['sujet'].lower()] = _m['objet']
            for _p in ('metier', 'conjoint', 'enfant', 'domicile'):
                _vals = [m['objet'] for m in _id_facts if m.get('predicat') == _p]
                if _vals:
                    if _p == 'enfant':
                        _enfants = []
                        for _v in _vals:
                            _age = _ages.get(_v.lower())
                            _enfants.append(f"{_v} ({_age})" if _age else _v)
                        _id_lines.append(f"  {_labels[_p]} : {', '.join(_enfants)}")
                    else:
                        _id_lines.append(f"  {_labels[_p]} : {', '.join(_vals)}")
            if _id_lines:
                parts.append(
                    '\n[Profil certain — utiliser directement sans vérifier ni redemander :' + chr(10)
                    + chr(10).join(_id_lines) + chr(10)
                    + ']'
                )
    except Exception:
        pass

    # Index mémoire thématique — carte compacte, générée en direct depuis la DB
    from core.database import get_memory_index_by_theme
    _mem_themes = get_memory_index_by_theme()
    if _mem_themes:
        _theme_lines = []
        for _theme, _entries in _mem_themes.items():
            if _entries:
                _theme_lines.append(f"  {_theme} : {', '.join(_entries)}")
        if _theme_lines:
            parts.append(
                '\n[Mémoire — appelle search_memory(prénom ou prédicat) pour les détails :' + chr(10)
                + chr(10).join(_theme_lines) + chr(10)
                + ']'
            )

    # Bibliothèque — conversations archivées pertinentes
    if biblio_context:
        parts.append(f"\n--- Conversations passées sur ce sujet ---\n{biblio_context}")

    # Base de connaissances — extraits pertinents des documents ingérés
    if doc_context:
        parts.append(f"\n--- Extraits de tes documents (base de connaissances) ---\n{doc_context}\n"
                     "(Utilise ces extraits s'ils sont pertinents pour la demande ; cite le titre du document.)")

    # SONDE couvert par le lexique — rappel des outils disponibles uniquement
    parts.append(
        '\n--- Outils disponibles ---\n'
        '• search_memory(query)       → mémoire personnelle (métier, famille, loisirs, santé, projets)\n'
        '• search_bibliotheque(query) → conversations archivées sur un sujet\n'
        '• search_anecdotes(query)    → moments forts ou souvenirs partagés\n'
        '• search_web(query)          → recherche internet via Brave Search\n'
        '                               Appeler UNIQUEMENT si l\'information est datée par nature :\n'
        '                               actualité, météo, prix en cours, résultats sportifs, événements récents.\n'
        '                               Ne JAMAIS appeler pour analyser un document fourni dans le message,\n'
        '                               répondre à une question stable, traduire ou expliquer un concept.\n'
        '                               Si des [Résultats de recherche web] apparaissent dans le message,\n'
        '                               les utiliser directement — ne pas appeler search_web à nouveau.\n'
        '• search_documents(query)    → documents ingérés par l\'utilisateur (articles, pages, PDF, fichiers)\n'
        '                               Appeler si l\'utilisateur évoque « mes documents », « les articles\n'
        '                               que je t\'ai donnés », « ce que j\'ai ajouté », ou pose une question\n'
        '                               portant sur ces contenus. Citer la source des passages utilisés.\n'
        '• run_code(code, description) → exécuter du code Python dans un environnement sandboxé.\n'
        '                               Appeler quand l\'utilisateur demande un calcul, une analyse de données,\n'
        '                               la génération d\'un fichier (CSV, image, graphique), ou toute tâche\n'
        '                               qui bénéficierait d\'une exécution réelle plutôt qu\'une réponse textuelle.\n'
        '                               Les fichiers générés (images, CSV…) sont automatiquement capturés.\n'
        'Appliquer la règle SONDE du lexique.\n'
    )

    # FORMAT DE SORTIE — tags techniques
    parts.append(
        '\n--- Format de sortie ---\n'
        'Après le texte visible, dans cet ordre si applicable :\n\n'
        '1. %%RAPPEL:...*%% si action agenda (formats définis dans AGENDA).\n\n'
        '2. %%ANECDOTE:titre|contenu|contexte|tags%% — si moment fort, drôle ou touchant.\n'
        '   titre = 3-6 mots · contenu = 1-2 phrases · contexte = sujet · tags = 3-5 mots-clés\n\n'
        '3. %%BILAN:texte%% — si un résultat, fait ou événement vient d\'être confirmé/résolu dans ce fil.\n'
        '   Texte court (≤ 10 mots). Un seul tag par fait clos.\n'
        '   Ne pas réémettre ce qui figure déjà dans 📋 Points acquis.\n\n'
        '4. %%DOMINANT:émotion1:score1|émotion2:score2|émotion3:score3%% — obligatoire, 1 par tour.\n'
        '   Toujours 3 couples, ordre décroissant. Entiers 0-10.\n'
        '   Note la couleur émotionnelle de ta réponse. Réponse enthousiaste ou étonnée → score ≥ 7. Seuil : ≥ 3 — sinon → %%DOMINANT:neutre:5|neutre:0|neutre:0%%\n\n'
        'Exemple : %%DOMINANT:joie:8|confiance:4|anticipation:2%%\n\n'
        '--- Mode Quiz ---\n'
        'Déclenché UNIQUEMENT si l\'utilisateur demande explicitement à être testé ou interrogé.\n'
        'Formulations valides : "quiz", "interroge-moi", "teste-moi", "pose-moi des questions", "QCM", "révise avec moi".\n'
        'Hors demande explicite : n\'émet JAMAIS de tag %%QUIZ%%.\n\n'
        'Annonce d\'abord le nombre de questions et le thème, puis émets une question à la fois.\n'
        'Attends la réponse de l\'utilisateur avant la question suivante — ne jamais en envoyer plusieurs d\'un coup.\n\n'
        'Format QCM (4 choix) :\n'
        '%%QUIZ%%{"type":"qcm","question":"...","options":["option A","option B","option C","option D"],"correct":0,"explication":"...","theme":"..."}%%/QUIZ%%\n'
        '  correct = index 0-3 de la bonne réponse.\n\n'
        'Format Vrai/Faux :\n'
        '%%QUIZ%%{"type":"vf","question":"...","correct":true,"explication":"...","theme":"..."}%%/QUIZ%%\n'
        '  correct = true ou false.\n\n'
        'Varie les types (QCM et Vrai/Faux) de façon naturelle.\n'
        '⚠️ RÈGLE ABSOLUE : N\'écris JAMAIS la question en texte lisible.\n'
        'La question est UNIQUEMENT dans le JSON, à l\'intérieur du tag.\n'
        'Le tag seul suffit — pas de phrase introductive, pas de répétition.\n\n'
        '❌ INTERDIT :\n'
        'Question 1 — Vrai ou Faux : La Bastille fut prise en 1789.\n'
        '{"type":"vf","question":"..."}%%/QUIZ%%\n\n'
        '✅ CORRECT :\n'
        '%%QUIZ%%{"type":"vf","question":"La Bastille fut prise en 1789.","correct":true,"explication":"...","theme":"..."}%%/QUIZ%%\n\n'
        'Si tu veux commenter (ex: "Bonne réponse !"), écris le commentaire AVANT le tag, jamais après.\n\n'
        '⚠️ Questions de suivi : sur "Question suivante" ou toute relance de quiz,\n'
        'le tag %%QUIZ%% doit être la SEULE façon de poser la question.\n'
        'Pas de "Question n°X —", pas de "Vrai ou Faux :" en texte, pas de JSON brut.\n'
        'Une ligne de commentaire optionnelle (ex: "Bien joué !"), PUIS immédiatement le tag.\n\n'
        'Bilan final : quand toutes les questions ont été posées, émets :\n'
        '%%QUIZ_BILAN%%{"score_attendu":5,"total":5}%%/QUIZ_BILAN%%\n'
        '  score_attendu = total de questions (le score réel est calculé côté interface).\n'
        '  Accompagne le tag d\'un commentaire encourageant.\n\n'
        'explication : 1-2 phrases claires, directement utiles pour comprendre la bonne réponse.\n'
        'theme : 3-5 mots décrivant le sujet précis (utilisé pour proposer une mini fiche).'
    )

    return '\n'.join(parts)


# ══════════════════════════════════════════
# INFÉRENCE DE CATÉGORIE — PRÉDICATS LIBRES
# ══════════════════════════════════════════

_CATEGORIE_KEYWORDS = {
    'profession': {
        'metier', 'emploi', 'travail', 'boulot', 'employeur', 'entreprise',
        'societe', 'poste', 'fonction', 'profession', 'projet', 'activite',
        'formation', 'stage', 'salaire', 'contrat', 'debut', 'carriere',
    },
    'famille': {
        'conjoint', 'femme', 'mari', 'epoux', 'epouse', 'partenaire',
        'compagnon', 'compagne', 'enfant', 'fils', 'fille', 'pere', 'mere',
        'frere', 'soeur', 'parent', 'grand', 'cousin', 'oncle', 'tante',
        'beau', 'belle', 'famille', 'neveu', 'niece',
    },
    'loisirs': {
        'loisir', 'sport', 'hobby', 'passion', 'cinema', 'musique',
        'lecture', 'jeu', 'cuisine', 'jardinage', 'bricolage', 'voyage',
        'collection', 'danse', 'art', 'dessin', 'photo',
    },
    'croyances': {
        'valeur', 'croyance', 'philosophie', 'religion', 'principe',
        'ethique', 'moral', 'foi', 'spirituel', 'conviction',
    },
    'sante': {
        'maladie', 'sante', 'medecin', 'traitement', 'handicap',
        'douleur', 'allergie', 'medicament', 'operation', 'kine',
        'therapie', 'regime', 'poids', 'fatigue',
    },
    'amities': {
        'ami', 'amie', 'copain', 'copine', 'collegue', 'chef', 'patron',
        'manager', 'superieur', 'voisin', 'connaissance',
    },
}

def _infer_categorie(predicat: str) -> str:
    """Infère la catégorie depuis un prédicat libre par matching de mots-clés."""
    p = predicat.lower().strip()
    # Matching exact d'abord
    for cat, keywords in _CATEGORIE_KEYWORDS.items():
        if p in keywords:
            return cat
    # Matching partiel (le prédicat contient un mot-clé)
    for cat, keywords in _CATEGORIE_KEYWORDS.items():
        for kw in keywords:
            if kw in p or p in kw:
                return cat
    return 'quotidien'


# ══════════════════════════════════════════
# EXTRACTION ÉMOTION DOMINANTE
# ══════════════════════════════════════════
# extract_all_tags() importée depuis modules/memory.py
# (version complète : retourne text, dominant, memories, anecdotes)


# ══════════════════════════════════════════
# RAPPEL MÉMOIRE CONTEXTUEL
# ══════════════════════════════════════════

# ── Patterns déclenchant une mémorisation forcée ──
_FORCE_MEM_PATTERNS = (
    'souviens-toi que', 'souviens toi que', 'souviens-toi',
    'retiens que', 'retiens bien', 'retiens ça',
    'mémorise que', 'mémorise ça', 'mémorise bien',
    'note que je', 'note bien', 'note ça',
    "n'oublie pas que", "n'oublie pas",
    'garde en mémoire', 'enregistre que', 'ajoute à ta mémoire',
)

def build_memory_context(user_message: str) -> str:
    """
    Rappel contextuel : souvenirs scorés par pertinence + poids effectif.
    Séparés en deux blocs identité / activité pour le LLM.
    """
    from modules.memory import recall
    memories = recall(user_message, limit=25)
    if not memories:
        return ''

    identite = [m for m in memories if m.get('memoire_type') != 'activite']
    activite  = [m for m in memories if m.get('memoire_type') == 'activite']

    lines = []
    if identite:
        lines.append("Profil (stable) :")
        for m in identite:
            val = m.get('valeur', '') or m.get('objet', '')
            if m.get('sujet') and val:
                lines.append(f"  - {m['sujet']} / {m['predicat']} : {val}")
    if activite:
        lines.append("En cours :")
        for m in activite:
            val = m.get('valeur', '') or m.get('objet', '')
            if m.get('sujet') and val:
                lines.append(f"  - {m['sujet']} / {m['predicat']} : {val}")

    return '\n'.join(lines) if lines else ''


def build_memory_context_permanent_only() -> str:
    """
    Ancrage réduit au minimum — retourne toujours vide.
    Le prénom est injecté via user_name dans build_system_prompt.
    Tout le reste est accessible via search_memory() (index injecté séparément).
    """
    return ''


# ══════════════════════════════════════════
# BIBLIOTHÈQUE — RECALL THÉMATIQUE
# ══════════════════════════════════════════

# Mots vides français — ignorés dans le matching bibliothèque
_MOTS_VIDES = {
    'le','la','les','un','une','des','de','du','et','en','au','aux','ce','se',
    'je','tu','il','elle','on','nous','vous','ils','elles','me','te','lui',
    'que','qui','quoi','dont','où','car','mais','ou','donc','or','ni','si',
    'est','sont','avoir','être','fait','avec','pour','sur','sous','dans','par',
    'mon','ton','son','ma','ta','sa','nos','vos','ses','mes','tes',
    'plus','très','bien','aussi','tout','tous','cette','cet','ces',
    'pas','ne','plus','jamais','rien','personne','quand','comme','alors',
}

# Mots-clés déclenchant un seuil de rappel abaissé
_MOTS_RAPPEL = {
    'souviens','rappelle','rappelles','souvient','souvenez','souvenons',
    'on avait','tu avais','on avait parlé','tu te souviens','tu te rappelles',
    'déjà parlé','discuté','abordé','évoqué','mentionné',
}

def _match_bibliotheque(user_message: str) -> str:
    """
    Matching fuzzy entre le message utilisateur et l'index bibliothèque.
    Retourne un biblio_context prêt à injecter dans le system prompt, ou '' si rien ne matche.
    Scoring : tag fuzzy match → +2 pts | mot titre fuzzy match → +1 pt
    Seuil normal : 3 pts | Seuil avec mot-clé rappel détecté : 2 pts
    Maximum 2 fiches injectées.
    """
    try:
        from rapidfuzz import fuzz
        from core.database import get_bibliotheque_index
        from modules.bibliotheque import recall_bibliotheque as _rb

        fiches = get_bibliotheque_index()
        if not fiches:
            return ''

        # Nettoyer le message — mots utiles uniquement
        msg_mots = [
            m.lower().strip(".,!?;:'\"()[]")
            for m in user_message.split()
            if len(m) > 2 and m.lower() not in _MOTS_VIDES
        ]
        if not msg_mots:
            return ''

        # Détecter mot-clé de rappel → seuil abaissé
        msg_lower = user_message.lower()
        seuil = 2 if any(mot in msg_lower for mot in _MOTS_RAPPEL) else 3

        resultats = []
        for fiche in fiches:
            score = 0

            # Tags : chaque tag comparé à chaque mot du message
            tags_bruts = fiche.get('tags') or ''
            tags = [t.strip().lower() for t in tags_bruts.split() if len(t.strip()) > 2]
            for mot in msg_mots:
                for tag in tags:
                    if fuzz.ratio(mot, tag) >= 82:
                        score += 2
                        break  # un seul +2 par mot

            # Titre : mots du titre (hors mots vides) comparés au message
            titre_mots = [
                t.lower().strip(".,!?;:'\"")
                for t in (fiche.get('titre') or '').split()
                if len(t) > 2 and t.lower() not in _MOTS_VIDES
            ]
            for mot in msg_mots:
                for tmot in titre_mots:
                    if fuzz.ratio(mot, tmot) >= 82:
                        score += 1
                        break

            if score >= seuil:
                resultats.append((score, fiche))

        if not resultats:
            return ''

        # Trier par score décroissant, garder max 2
        resultats.sort(key=lambda x: x[0], reverse=True)
        resultats = resultats[:2]

        contextes = []
        for _, fiche in resultats:
            contenu = _rb(fiche.get('titre', ''), limit=1)
            if contenu:
                contextes.append(contenu)
            print(f"[HUB] Biblio match -> '{fiche.get('titre','?')}' (score {_})")

        return '\n\n'.join(contextes) if contextes else ''

    except Exception as e:
        print(f"[HUB] Erreur match_bibliotheque : {e}")
        return ''


def _match_documents(user_message: str):
    """Récupère proactivement les passages les plus pertinents des documents ingérés
    (base de connaissances locale). Renvoie un tuple (doc_context, titres) :
    - doc_context = texte à injecter dans le system prompt ('' si rien) ;
    - titres = liste ordonnée et dédoublonnée des documents retenus (pour citation).
    Complète l'outil search_documents (pull) par une injection (push)."""
    try:
        msg = (user_message or '').strip()
        if len(msg) < 4:
            return '', []
        from modules.enrichissement import search_documents
        passages = search_documents(msg, k=3)
        if not passages:
            return '', []
        retenus = []
        for pp in passages:
            sc = pp.get('score', 0) or 0
            if pp.get('mode') == 'keyword':
                if sc >= 2:
                    retenus.append(pp)
            elif sc >= 0.32:
                retenus.append(pp)
        if not retenus:
            return '', []
        blocs, titres = [], []
        for pp in retenus:
            titre = pp.get('titre') or 'Document'
            src = pp.get('source') or ''
            entete = ('[' + titre + (' — ' + src + ']' if src else ']'))
            blocs.append(entete + '\n' + (pp.get('passage') or '').strip()[:1200])
            if titre not in titres:
                titres.append(titre)
        print(f"[HUB] 📄 Documents match -> {len(blocs)} passage(s)")
        return '\n\n'.join(blocs), titres
    except Exception as e:
        print(f"[HUB] Erreur match_documents : {e}")
        return '', []


def recall_bibliotheque(query: str, limit: int = 3) -> str:
    """Recall thématique bibliothèque — délégué à modules/bibliotheque.py."""
    from modules.bibliotheque import recall_bibliotheque as _rb
    return _rb(query, limit)


# ══════════════════════════════════════════
# TOOL CALLING — OUTILS EXPOSÉS AU LLM
# ══════════════════════════════════════════

NIMM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": (
                "Cherche dans la mémoire personnelle de l'utilisateur. "
                "Utilise cet outil quand tu as besoin d'informations personnelles "
                "(domicile, famille, préférences, projets, métier, entourage…) "
                "qui ne sont pas présentes dans le contexte actuel. "
                "Ne l'utilise PAS pour des questions générales, factuelles, techniques ou historiques."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Le terme ou la question à rechercher dans la mémoire"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_bibliotheque",
            "description": (
                "Cherche dans les conversations archivées. "
                "Utilise cet outil si l'utilisateur fait référence à une discussion passée "
                "ou à un sujet traité dans une conversation précédente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Le sujet ou thème à rechercher dans les archives"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_anecdotes",
            "description": (
                "Cherche dans les anecdotes — moments forts, drôles ou touchants mémorisés lors des conversations passées. "
                "Utilise cet outil si l'utilisateur évoque un souvenir partagé, un moment vécu ensemble, "
                "ou demande ce qu'on a vécu ensemble."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Le moment ou thème à rechercher dans les anecdotes"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "Effectue une recherche sur internet via Brave Search. "
                "Utilise cet outil UNIQUEMENT si l'information est datée par nature : "
                "actualité, météo, prix en cours, résultats sportifs, événements récents, "
                "taux de change, nouveautés, sorties récentes. "
                "NE PAS utiliser pour : analyser un document fourni dans le message, "
                "répondre à une question générale ou factuelle stable, "
                "faire des calculs, traduire, expliquer un concept. "
                "Si l'utilisateur te demande d'analyser un texte ou une offre qu'il a collé, "
                "n'appelle jamais cet outil."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Mots-clés de recherche concis (3-6 mots maximum)"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_code",
            "description": (
                "Génère et exécute du code Python pour réaliser une tâche précise. "
                "Utilise cet outil quand la réponse nécessite un CALCUL, une MANIPULATION DE DONNÉES, "
                "une CONVERSION, un TRAITEMENT DE FICHIER ou toute opération que le code ferait mieux que du texte. "
                "Exemples : calcul de budget, tri de liste, génération de tableau, calcul de dates, statistiques. "
                "NE PAS utiliser pour : recherche d'information, rappels de mémoire, questions générales. "
                "Le code Python s'exécute dans un répertoire de travail isolé. "
                "Si le code génère un fichier image, il sera ajouté automatiquement à la galerie. "
                "Si le code génère un fichier texte/CSV, son contenu sera inclus dans ta réponse."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Code Python complet à exécuter. N'utilise que la bibliothèque standard et les modules déjà installés (datetime, math, json, csv, os, re, collections…). Les fichiers de sortie doivent être écrits dans le répertoire courant."
                    },
                    "description": {
                        "type": "string",
                        "description": "Description courte de ce que fait le code (pour transparence vis-à-vis de l'utilisateur)"
                    }
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": (
                "Recherche dans les DOCUMENTS que l'utilisateur a lui-même ingérés "
                "(articles, pages, PDF, fichiers) via l'enrichissement web. "
                "Utilise cet outil quand l'utilisateur fait référence à « mes documents », "
                "« les articles que je t'ai donnés », « ce que j'ai ajouté », ou pose une "
                "question dont la réponse se trouve probablement dans ces contenus. "
                "Retourne des passages pertinents avec leur source : cite la source dans ta réponse."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Mots-cles ou question pour retrouver les passages pertinents"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_carnet",
            "description": (
                "Recherche dans le CARNET DE BORD de ce fil de conversation -- la chronologie des "
                "sujets abordes plus tot, desormais hors de ta fenetre de contexte. "
                "Utilise cet outil quand tu as besoin de te raccrocher a quelque chose evoque "
                "precedemment dans CETTE conversation et que tu ne vois plus dans l'historique recent. "
                "Ne concerne que ce fil -- pas la memoire personnelle de l'utilisateur (pour ca, "
                "utiliser search_memory)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Mots-cles ou sujet pour retrouver les notes pertinentes du carnet"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_skill",
            "description": (
                "Recherche parmi les SKILLS de CoaNIMM -- des methodes deja validees par "
                "l'utilisateur et reutilisables (ex. preparer une image pour la decoupe par "
                "seuillage, quantifier une palette pour la broderie). Appelle cet outil AVANT "
                "de generer un script quand la tache ressemble a un process deja fait et "
                "approuve, afin de reutiliser la methode au lieu de repartir de zero."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "La consigne ou des mots-cles decrivant la tache, pour retrouver un skill pertinent"
                    }
                },
                "required": ["query"]
            }
        }
    }
]


# Perissabilite d'une information
_PERISSABILITE_JOURS = {'ephemere': 1, 'normale': 30, 'durable': 365, 'permanente': 0}

async def classify_perissabilite_jours(query: str, content: str = ""):
    """Estime la durée de validité de l'information répondant à `query`, via le LLM.
    Si `content` est fourni (extrait des résultats trouvés), il aide à trancher les
    cas où la requête seule est ambiguë. Retourne un nombre de jours (0 = permanent)
    ou None si indéterminé (le cache se rabat alors sur son heuristique)."""
    try:
        settings = load_settings()
        extrait = " ".join((content or "").split())
        if len(extrait) > 800:
            extrait = extrait[:800] + "…"
        prompt = (
            "Classe la DURÉE DE VALIDITÉ de l'information répondant à cette requête, "
            "en UN SEUL mot parmi : ephemere, normale, durable, permanente.\n"
            "- ephemere : quelques heures à un jour (météo, cours de bourse, score, actualité immédiate)\n"
            "- normale : quelques semaines (prix, classements, tendances)\n"
            "- durable : des mois à un an (faits récents, statistiques annuelles)\n"
            "- permanente : intemporel (définitions, histoire, concepts, science établie)\n"
            "Réponds UNIQUEMENT par un de ces quatre mots.\n\n"
            f"Requête : {query}\n"
            + (f"Extrait des résultats trouvés :\n{extrait}\n" if extrait else "")
        )
        reponse = await call_llm(
            messages    = [{'role': 'user', 'content': prompt}],
            provider    = settings.get('provider', ''),
            max_tokens  = 4,
            temperature = 0.0,
            api_keys    = settings.get('api_keys', {}),
            model       = settings.get('model'),
        )
        import unicodedata
        txt = "".join(c for c in unicodedata.normalize('NFD', (reponse or '').strip().lower())
                      if unicodedata.category(c) != 'Mn')
        mot = txt.split()[0] if txt.split() else ''
        return _PERISSABILITE_JOURS.get(mot)  # None si non reconnu
    except Exception as e:
        print(f"[WEBCACHE] Classification périssabilité impossible : {e}")
        return None


# Outils Fichiers vérifiés de CoaNIMM (couche tool-calling) — voir modules/coanimm_ops.py
from modules.coanimm_ops import (OPS_TOOLS as _COANIMM_OPS_TOOLS,
                                 OPS_NAMES as _COANIMM_OPS_NAMES,
                                 dispatch_op as _coanimm_dispatch_op,
                                 ASYNC_OPS_TOOLS as _COANIMM_ASYNC_TOOLS,
                                 ASYNC_OPS_NAMES as _COANIMM_ASYNC_NAMES,
                                 dispatch_async_op as _coanimm_dispatch_async_op)
NIMM_TOOLS = NIMM_TOOLS + _COANIMM_OPS_TOOLS + _COANIMM_ASYNC_TOOLS


async def _check_moderation(text: str, api_keys: dict) -> dict:
    """
    Appelle l'API de moderation Mistral sur le texte.
    Retourne {'blocked': bool, 'categories': dict, 'violated': list}
    """
    import json as _j, httpx as _hx
    _mkey = (api_keys.get('mistral') or '').strip()
    if not _mkey:
        return {'blocked': False, 'categories': {}, 'violated': []}
    try:
        async with _hx.AsyncClient(timeout=10) as _c:
            _r = await _c.post(
                'https://api.mistral.ai/v1/moderations',
                headers={'Authorization': f'Bearer {_mkey}', 'Content-Type': 'application/json'},
                json={'model': 'mistral-moderation-latest', 'inputs': [text]}
            )
            _r.raise_for_status()
            _data = _r.json()
        _result = (_data.get('results') or [{}])[0]
        _cats = _result.get('category_scores', {})
        _violated = [k for k, v in _result.get('categories', {}).items() if v]
        return {'blocked': bool(_violated), 'categories': _cats, 'violated': _violated}
    except Exception as _e:
        print(f'[HUB] Moderation check failed: {_e}')
        return {'blocked': False, 'categories': {}, 'violated': []}

async def _search_via_mistral(query: str, api_keys: dict) -> str:
    """
    Recherche web via l'outil natif Mistral web_search.
    Retourne le texte de la reponse + citations formatees.
    """
    import httpx as _httpx
    import json as _json
    _mkey = (api_keys.get('mistral') or '').strip()
    if not _mkey:
        raise ValueError('Cle API Mistral manquante pour la recherche web.')
    _payload = {
        'model': 'mistral-small-latest',
        'messages': [{'role': 'user', 'content': query}],
        'tools': [{'type': 'web_search'}],
        'max_tokens': 1024,
    }
    async with _httpx.AsyncClient(timeout=30) as _c:
        _r = await _c.post(
            'https://api.mistral.ai/v1/chat/completions',
            headers={'Authorization': f'Bearer {_mkey}', 'Content-Type': 'application/json'},
            json=_payload
        )
        _r.raise_for_status()
        _data = _r.json()
    _content = _data['choices'][0]['message'].get('content') or ''
    _cits = (_data.get('citations')
             or _data['choices'][0].get('message', {}).get('citations') or [])
    # Encoder les citations en JSON en fin de resultat pour que hub.py
    # puisse les extraire et les emettre en SSE independamment du LLM principal
    if _cits:
        import json as _jc
        _content += f'\n\n[NIMM_CITATIONS]{_jc.dumps(_cits, ensure_ascii=False)}'
    return _content or '[Aucun resultat]'

async def _execute_tool(name: str, args: dict, thread_id: str = None) -> str:
    """
    Exécute un outil demandé par le LLM et retourne le résultat en texte.
    Appelé par process_message_stream() pendant la phase tool calling.
    Retourne toujours une chaîne — jamais None.
    """
    query = args.get('query', '').strip()
    if not query:
        return '[Aucun résultat — paramètre query vide]'

    if name == 'search_memory':
        try:
            result = build_memory_context(query)
            if result:
                print(f"[HUB] 🔍 Tool search_memory({query!r}) → {len(result)} chars")
                return result
            print(f"[HUB] 🔍 Tool search_memory({query!r}) → vide")
            return '[Aucun souvenir pertinent trouvé pour cette recherche]'
        except Exception as e:
            print(f"[HUB] ⚠️ Erreur search_memory : {e}")
            return '[Erreur lors de la recherche en mémoire]'

    elif name == 'search_bibliotheque':
        try:
            result = recall_bibliotheque(query)
            if result:
                print(f"[HUB] 🔍 Tool search_bibliotheque({query!r}) → {len(result)} chars")
                return result
            print(f"[HUB] 🔍 Tool search_bibliotheque({query!r}) → vide")
            return '[Aucune conversation archivée trouvée pour ce sujet]'
        except Exception as e:
            print(f"[HUB] ⚠️ Erreur search_bibliotheque : {e}")
            return '[Erreur lors de la recherche en bibliothèque]'

    elif name == 'search_anecdotes':
        try:
            from modules.memory import recall_anecdotes
            results = recall_anecdotes(query)
            if results:
                lines = []
                for a in results:
                    lines.append(f"• [{a.get('timestamp','')[:10]}] {a.get('titre','')}: {a.get('contenu','')}")
                result = '\n'.join(lines)
                print(f"[HUB] 🔍 Tool search_anecdotes({query!r}) → {len(results)} résultat(s)")
                return result
            print(f"[HUB] 🔍 Tool search_anecdotes({query!r}) → vide")
            return '[Aucune anecdote trouvée pour ce sujet]'
        except Exception as e:
            print(f"[HUB] ⚠️ Erreur search_anecdotes : {e}")
            return '[Erreur lors de la recherche en anecdotes]'

    elif name == 'search_web':
        try:
            # Vérifier le routing : Mistral ou Brave/Tavily
            _ws_routing = _load_provider_routing().get('web_search', {})
            _ws_provider = _ws_routing.get('provider', '') if isinstance(_ws_routing, dict) else ''
            if _ws_provider == 'mistral':
                try:
                    from core.database import get_api_keys as _gak
                    _ws_keys = _gak()
                except Exception:
                    _ws_keys = {}
                result = await _search_via_mistral(query, _ws_keys)
                print(f"[HUB] 🔵 Tool search_web (Mistral) {query!r} → {len(result or '')} chars")
                # Extraire les citations encodees et les stocker pour SSE
                import re as _re_cit, json as _jc2
                _m = _re_cit.search(r'\[NIMM_CITATIONS\](.*)', result or '')
                if _m:
                    try:
                        _pending_citations.set(_jc2.loads(_m.group(1)))
                    except Exception:
                        pass
                    result = result[:_m.start()].rstrip()
            else:
                from modules.websearch import search_with_cache as brave_search
                result = await brave_search(query, classify=classify_perissabilite_jours)
                print(f"[HUB] 🌐 Tool search_web({query!r}) → {len(result or '')} chars")
            return result or '[Aucun résultat web pour cette requête]'
        except Exception as e:
            print(f"[HUB] ⚠️ Erreur search_web : {e}")
            return '[Erreur lors de la recherche web]'

    elif name == 'search_documents':
        try:
            from modules.enrichissement import search_documents
            passages = search_documents(query, k=5)
            if not passages:
                return "[Aucun document ingéré ne correspond à cette requête.]"
            blocs = []
            for p in passages:
                titre = p.get('titre') or '(sans titre)'
                src = p.get('source') or ''
                blocs.append(f"[{titre} — {src}]\n{p.get('passage', '')}")
            print(f"[HUB] 📄 Tool search_documents({query!r}) → {len(passages)} passage(s)")
            return "\n\n".join(blocs)
        except Exception as e:
            print(f"[HUB] ⚠️ Erreur search_documents : {e}")
            return '[Erreur lors de la recherche documentaire]'

    elif name == 'search_carnet':
        try:
            from core.database import get_carnet_notes as _get_carnet_notes
            if not thread_id:
                return '[Aucun carnet disponible -- fil non identifie]'
            toutes_notes = _get_carnet_notes(thread_id)
            if not toutes_notes:
                return '[Le carnet de ce fil est vide pour le moment]'
            mots = [m for m in query.lower().split() if len(m) > 2]
            if mots:
                pertinentes = [
                    n for n in toutes_notes
                    if any(m in n['content'].lower() for m in mots)
                ]
            else:
                pertinentes = []
            # Repli : si aucune note ne matche les mots-cles, renvoyer les plus recentes
            notes_a_renvoyer = pertinentes if pertinentes else toutes_notes[-5:]
            lines = [f"[{n['note_number']}] {n['content']}" for n in notes_a_renvoyer]
            result = '\n'.join(lines)
            print(f"[HUB] Tool search_carnet({query!r}) -> {len(notes_a_renvoyer)} note(s)")
            return result
        except Exception as e:
            print(f"[HUB] Erreur search_carnet : {e}")
            return '[Erreur lors de la recherche dans le carnet]'

    elif name == 'find_skill':
        try:
            from core.database import list_prompts as _list_skills
            skills = _list_skills('skill')
            if not skills:
                return '[Aucun skill enregistre pour le moment]'
            try:
                # Appariement sémantique (embeddings) avec repli mots-clés, mutualisé.
                from modules.coanimm import rank_skills as _rank
                top = [sk for _sid, sk, _sc in _rank(query, top_n=3)]
            except Exception:
                # Repli ultime : recouvrement de mots-clés local.
                mots = [m for m in re.findall(r'\w+', query.lower())
                        if len(m) > 2 and m not in _MOTS_VIDES]
                scored = []
                for sid, sk in skills.items():
                    meta = sk.get('meta') or {}
                    hay = ' '.join([sk.get('label', ''), meta.get('description', ''),
                                    ' '.join(meta.get('mots_cles') or [])]).lower()
                    score = sum(1 for m in mots if m in hay)
                    if score > 0:
                        scored.append((score, sk))
                scored.sort(key=lambda t: t[0], reverse=True)
                top = [sk for _, sk in scored[:3]]
            if not top:
                return '[Aucun skill ne correspond a cette consigne]'
            blocs = []
            for sk in top:
                meta = sk.get('meta') or {}
                desc = meta.get('description', '') or sk.get('label', '')
                _caps = ('non évalué' if 'capacites' not in meta
                         else (', '.join(meta['capacites']) or 'aucune capacité sensible'))
                blocs.append(
                    f"SKILL : {sk.get('label', '')}\n"
                    f"Quand l'utiliser : {desc}\n"
                    f"Capacités : {_caps}\n"
                    f"Methode :\n{sk.get('text', '')}"
                )
            print(f"[HUB] Tool find_skill({query!r}) -> {len(top)} fiche(s)")
            return '\n\n'.join(blocs)
        except Exception as e:
            print(f"[HUB] Erreur find_skill : {e}")
            return '[Erreur lors de la recherche de skills]'

    elif name == 'run_code':
        code = args.get('code', '').strip()
        description = args.get('description', '').strip()
        if not code:
            return '[run_code] Aucun code fourni.'
        # Vérification de permission (même système que CoaNIMM UI)
        from core.database import agent_permission_granted
        action = 'run_code_tool'
        if not agent_permission_granted(action, thread_id):
            return (
                "[run_code] Exécution de code non autorisée. "
                "Dis à l'utilisateur qu'il peut autoriser l'exécution de code Python dans "
                "les paramètres CoaNIMM (une fois, pour ce fil, ou toujours). "
                "Il pourra ensuite répéter sa demande."
            )
        try:
            from modules.coanimm import execute_code
            result = execute_code(code, thread_id)
            parts = []
            if description:
                parts.append(f"[Code exécuté : {description}]")
            if result.get('stdout', '').strip():
                parts.append(result['stdout'].strip())
            if result.get('returncode', 0) != 0 and result.get('stderr', '').strip():
                parts.append(f"[stderr] {result['stderr'].strip()[:500]}")
            if result.get('status') == 'error':
                parts.append(f"[Erreur] {result.get('message', '')}")
            if result.get('files_info'):
                parts.append(result['files_info'])
            if not parts:
                parts.append('[Code exécuté sans sortie]')
            txt = '\n'.join(parts)
            print(f"[HUB] 🤖 Tool run_code → {len(txt)} chars, {result.get('files_count',0)} fichier(s) généré(s)")
            return txt
        except Exception as e:
            print(f"[HUB] ⚠️ Erreur run_code : {e}")
            return f'[Erreur lors de l\'exécution du code : {e}]'

    if name in _COANIMM_ASYNC_NAMES:
        try:
            return await _coanimm_dispatch_async_op(name, args, thread_id)
        except Exception as e:
            print(f"[HUB] Erreur op document {name} : {e}")
            return f'[Erreur résumé document : {e}]'

    if name in _COANIMM_OPS_NAMES:
        try:
            txt = _coanimm_dispatch_op(name, args, thread_id)
            print(f"[HUB] 🗂️ Tool {name} -> {len(txt)} chars")
            return txt
        except Exception as e:
            print(f"[HUB] Erreur op fichier {name} : {e}")
            return f'[Erreur opération fichier : {e}]'

    return f'[Outil inconnu : {name}]'


# ══════════════════════════════════════════
# HELPER — TÂCHES ARRIÈRE-PLAN AVEC TIMEOUT
# ══════════════════════════════════════════

async def _bg(coro, timeout: int = 20):
    """Exécute une coroutine en arrière-plan avec timeout. Silencieux en cas d'erreur."""
    try:
        await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        print(f"[HUB] ⏱️ Tâche arrière-plan timeout ({timeout}s).")
    except Exception as e:
        print(f"[HUB] ⚠️ Tâche arrière-plan erreur : {e}")


# Référence forte aux tâches de fond — évite le garbage-collect prématuré
_background_tasks: set = set()

def _create_bg_task(coro) -> asyncio.Task:
    """Crée une tâche de fond et conserve sa référence jusqu'à complétion."""
    task = asyncio.create_task(_bg(coro))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


# ══════════════════════════════════════════
# CARNET DE BORD — NOTES AUTOMATIQUES
# ══════════════════════════════════════════

def _is_ghost_thread(thread_id: str) -> bool:
    """Le fil est-il en mode confidentiel (« fantôme ») ? Aucune trace dérivée
    (mémoire, carnet de bord) n'est produite pour ces fils."""
    if not thread_id:
        return False
    try:
        import json as _gj
        return thread_id in set(_gj.loads(get_setting('ghost_threads', '[]')))
    except Exception:
        return False


async def maybe_generate_carnet_note(thread_id: str, settings: dict):
    """
    Carnet de bord — prose libre courte produite en arrière-plan.

    Calendrier :
      - Note #0 : après le 1er échange (n == 2)
      - Note #n : tous les CARNET_INTERVAL échanges suivants (toutes les 14 messages)
    Injection dans le system prompt uniquement si n > CARNET_WINDOW.
    """
    # Mode confidentiel : aucune note de carnet pour un fil fantôme.
    if _is_ghost_thread(thread_id):
        return
    n = count_messages(thread_id)

    # Pas encore de premier échange complet
    if n < 2:
        return

    # Calcul du nombre de notes attendues
    expected = 1 + (n - 2) // (CARNET_INTERVAL * 2)
    actual   = count_carnet_notes(thread_id)

    if actual >= expected:
        return  # Note déjà produite pour ce stade

    note_number = actual  # index de la prochaine note à créer

    # ── Fenêtre d'input : les 14 derniers messages (7 échanges) ──
    window = get_messages(thread_id, limit=CARNET_INTERVAL * 2)
    if not window:
        return

    conv_text = '\n'.join(
        f"{'Utilisateur' if m['role'] == 'user' else 'Assistant'} : {m['content'][:600]}"
        for m in window
    )

    # Lire les notes existantes pour éviter les doublons
    from core.database import get_carnet_notes as _get_notes
    existing_notes = _get_notes(thread_id) or []
    existing_block = ''
    if existing_notes:
        existing_block = (
            "Notes déjà écrites dans ce carnet :\n" +
            '\n'.join(f"- {n['content']}" for n in existing_notes[-6:]) +
            "\n\n"
        )

    prompt = (
        "Tu tiens le carnet de bord d'une conversation en cours.\n"
        + existing_block +
        "Lis les échanges ci-dessous et écris une note courte (2 à 3 phrases maximum) "
        "structurée en trois temps :\n"
        "1. Sujet dominant : de quoi parle-t-on dans ces échanges ?\n"
        "2. Ce qui a évolué : information nouvelle, précision, changement de ton ou de direction "
        "par rapport aux notes déjà écrites. Ne répète jamais ce qui est déjà noté.\n"
        "3. État : la question est-elle résolue, en cours, ou ouverte ?\n"
        "Style : prose naturelle, première personne, présent ou passé composé. Pas de liste, pas de titre, pas de numéros.\n"
        "SKIP uniquement si les échanges sont vides de contenu "
        "(salutations pures, accusés de réception, aucune information ni évolution).\n\n"
        f"Échanges :\n{conv_text}\n\n"
        "Note :"
    )

    try:
        note = await call_llm(
            messages    = [{'role': 'user', 'content': prompt}],
            provider    = settings['provider'],
            max_tokens  = 150,
            temperature = 0.3,
            api_keys    = settings['api_keys'],
            model       = settings.get('model'),
        )
        note = note.strip()
        if note and note.upper() != 'SKIP':
            # msg_debut = premier message résumé par cette note
            # La note résume les CARNET_INTERVAL*2 derniers messages → le plus ancien est n - (CARNET_INTERVAL*2)
            msg_debut = max(0, n - (CARNET_INTERVAL * 2))
            add_carnet_note(thread_id, note_number, note, msg_debut=msg_debut)
            print(f"[CARNET] Note #{note_number} msg_debut={msg_debut} — fil {thread_id[:8]}... : {note[:60]}")
        elif note.upper() == 'SKIP':
            print(f"[CARNET] Note #{note_number} ignorée (doublon détecté) — fil {thread_id[:8]}...")
    except Exception as e:
        print(f"[CARNET] Erreur génération note : {e}")


# ══════════════════════════════════════════
# PASSE MÉMOIRE — EXTRACTION SUR FENÊTRE
# ══════════════════════════════════════════

# Confiance fixe par registre — attribuée par le hub, jamais par le LLM
CONFIANCE_PAR_REGISTRE = {
    'neutre':     0.90,
    'intention':  0.70,
    'emotionnel': 0.55,
    'figure':     0.25,
    'hypothese':  None,   # None = rejeté systématiquement
}

# Registres autorisés selon le curseur utilisateur (clé settings : 'memoire_mode')
REGISTRES_AUTORISES = {
    'large':  {'neutre', 'intention', 'emotionnel', 'figure'},
    'normal': {'neutre', 'intention'},
    'strict': {'neutre'},
}


def _parse_llm_json(raw: str) -> list:
    """
    Parse la réponse JSON du LLM de manière robuste.
    Nettoie les balises markdown, tente json.loads(), retourne [] en cas d'échec.
    """
    import re
    cleaned = re.sub(r'```(?:json)?\s*', '', raw).replace('```', '').strip()
    match = re.search(r'\[.*\]', cleaned, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group())
    except json.JSONDecodeError as e:
        print(f"[HUB] ⚠️ JSON mémoire invalide : {e}")
        return []


# ── Prompts d'extraction mémoire — par fournisseur, avec repli par défaut ──
import os as _os_prompts

_PROMPTS_DIR = _os_prompts.path.join(_os_prompts.path.dirname(__file__), '..', 'data', 'prompts')
_memoire_prompt_cache: dict = {}

_MEMOIRE_PROMPT_FALLBACK = (
    "Voici une conversation. La personne qui parle s'appelle {{USER_NAME}}.\n\n"
    "{{CONV_TEXT}}\n\n"
    "Extrais les faits mémorisables sur {{USER_NAME}} sous forme de tableau JSON "
    "d'objets {\"registre\":\"neutre\",\"type\":\"trait\",\"sujet\":\"...\",\"predicat\":\"...\","
    "\"objet\":\"...\",\"memoire_type\":\"autre\",\"profondeur\":3,\"type_temporal\":\"persistant\","
    "\"contexte\":\"\"}. Si aucun fait : réponds [].\n"
    "Réponds UNIQUEMENT avec le tableau JSON."
)

def _model_slug(model: str) -> str:
    """Normalise un nom de modèle pour un nom de fichier
    (ex: 'mistral-small-latest' -> 'mistral_small_latest', 'llama3.1:8b' -> 'llama3_1_8b')."""
    return re.sub(r'[^a-z0-9]+', '_', (model or '').lower()).strip('_')


def _load_memoire_prompt_template(provider: str, model: str = None) -> str:
    """
    Charge le gabarit de prompt d'extraction mémoire, avec variante par sous-modèle
    (data/prompts/memoire_<provider>_<modele>.txt), repli sur la variante par
    fournisseur (memoire_<provider>.txt), puis sur memoire_default.txt, puis sur
    un gabarit minimal en dur si aucun fichier n'est trouvé.
    """
    slug = _model_slug(model)
    cache_key = f"{provider or 'default'}:{slug}"
    if cache_key in _memoire_prompt_cache:
        return _memoire_prompt_cache[cache_key]

    candidates = []
    if slug:
        candidates.append(f'memoire_{provider}_{slug}.txt')
    candidates.append(f'memoire_{provider}.txt')
    candidates.append('memoire_default.txt')

    for fname in candidates:
        path = _os_prompts.path.join(_PROMPTS_DIR, fname)
        if _os_prompts.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    template = f.read()
                _memoire_prompt_cache[cache_key] = template
                return template
            except Exception as e:
                print(f"[HUB] ⚠️ Lecture {fname} impossible : {e}")

    _memoire_prompt_cache[cache_key] = _MEMOIRE_PROMPT_FALLBACK
    return _MEMOIRE_PROMPT_FALLBACK


async def extract_memories_from_window(messages: list, settings: dict) -> int:
    """
    Passe mémoire v2 sur une fenêtre de messages.
    Extrait les faits mémorisables avec détection de registre (5 valeurs).
    La confiance est attribuée de manière déterministe par le hub selon le registre.
    Le curseur utilisateur (large/normal/strict) filtre les registres autorisés.
    Retourne le nombre de souvenirs traités (nouveaux + renforcés).
    """
    if not messages:
        return 0

    user_msgs = [m for m in messages if m.get('role') == 'user']
    if len(user_msgs) < 1:
        return 0

    user_name = settings.get('user_name', 'utilisateur')
    mode = settings.get('memoire_mode', 'normal')
    if mode not in REGISTRES_AUTORISES:
        mode = 'normal'

    conv_text = '\n'.join(
        f"{'Utilisateur' if m['role'] == 'user' else 'Assistant'} : {m['content'][:600]}"
        for m in messages
    )

    provider_mem, model_mem = get_task_provider_model('memoire', settings)
    from core.engine import _resolve_model
    template = _load_memoire_prompt_template(provider_mem, _resolve_model(provider_mem, model_mem))
    date_str     = datetime.now().strftime('%d/%m/%Y')
    location_str = settings.get('location', '')
    prompt = (
        template
        .replace('{{USER_NAME}}', user_name)
        .replace('{{DATE}}',      date_str)
        .replace('{{LOCATION}}',  location_str)
        .replace('{{CONV_TEXT}}', conv_text)
    )

    try:
        response = await call_llm(
            messages=[{'role': 'user', 'content': prompt}],
            provider=provider_mem,
            max_tokens=1500,
            temperature=0.1,
            api_keys=settings['api_keys'],
            model=model_mem,
        )

        if not response:
            return 0

        items = _parse_llm_json(response)
        if not items:
            return 0

        from modules.memory import save_inline_memory
        from core.database import get_all_memory as _get_all_mem

        existing = _get_all_mem()
        stored = 0
        for item in items:
            registre = item.get('registre', 'neutre')
            # Rejet systématique des hypothèses
            if registre == 'hypothese':
                continue
            # Filtrage selon le curseur utilisateur
            if registre not in REGISTRES_AUTORISES.get(mode, REGISTRES_AUTORISES['normal']):
                continue
            # Confiance déterministe attribuée par le hub
            item['confiance'] = CONFIANCE_PAR_REGISTRE.get(registre, 0.50)
            item['registre']  = registre
            # Champs requis par save_memory() — absents du JSON LLM
            from modules.memory import _infer_categorie as _ic
            item.setdefault('key',             f"mem_{__import__('uuid').uuid4().hex[:8]}")
            item.setdefault('valeur',          item.get('objet', ''))
            item.setdefault('valence',         0.0)
            item.setdefault('sensibilite',     'neutre')
            item.setdefault('cumulatif',       0)
            item.setdefault('categorie',       _ic(item.get('predicat', '')))
            item.setdefault('expiration',      None)
            item.setdefault('timestamp',       __import__('datetime').datetime.now().isoformat())
            item.setdefault('repetitions',     0)
            item.setdefault('poids',           0.5)
            item.setdefault('embedding',       None)
            item.setdefault('last_reinforced', None)
            save_inline_memory(item, existing=existing)
            stored += 1

        if stored:
            print(f"[HUB] 🧠 Mémoire v2 → {stored}/{len(items)} souvenir(s) stocké(s) (mode={mode})")
        return stored

    except Exception as e:
        print(f"[HUB] ⚠️ Erreur passe mémoire v2 : {e}")
        return 0


async def memorize_thread(thread_id: str, settings: dict) -> int:
    """
    Passe mémoire complète sur un fil — appelée à la fermeture ou suppression.
    Récupère tous les messages du fil et délègue à extract_memories_from_window().
    Marque ensuite tous les messages du fil comme traités.
    """
    from core.database import get_unprocessed_message_ids, mark_messages_processed
    unprocessed_ids = get_unprocessed_message_ids(thread_id)
    messages = get_messages(thread_id, limit=200)
    count = await extract_memories_from_window(messages, settings)
    if unprocessed_ids:
        mark_messages_processed(unprocessed_ids)
        print(f"[HUB] 🧠 memorize_thread → {len(unprocessed_ids)} message(s) marqué(s) traités.")
    return count


# ══════════════════════════════════════════
# WORKER MÉMOIRE — extraction asynchrone
# ══════════════════════════════════════════

async def _worker_process_user(user_id: str):
    """Traite tous les fils non-traités pour un utilisateur donné."""
    from core.database import (
        get_threads_with_unprocessed, get_unprocessed_message_ids,
        mark_messages_processed, set_user_context,
    )
    set_user_context(user_id)
    thread_ids = get_threads_with_unprocessed()
    total_stored = 0
    for thread_id in thread_ids:
        unprocessed_ids = get_unprocessed_message_ids(thread_id)
        if not unprocessed_ids:
            continue
        messages = get_messages(thread_id, limit=80)
        if not messages:
            mark_messages_processed(unprocessed_ids)
            continue
        try:
            settings = load_settings(thread_id)
            settings['api_keys'] = _load_api_keys()
        except Exception as e:
            print(f"[WORKER] ⚠️ Settings introuvables fil {thread_id[:8]} [{user_id}] : {e}")
            continue
        try:
            import json as _gj
            _ghost_raw = get_setting('ghost_threads', '[]')
            _ghost_set = set(_gj.loads(_ghost_raw))
        except Exception:
            _ghost_set = set()
        if thread_id in _ghost_set:
            mark_messages_processed(unprocessed_ids)
            continue
        count = await extract_memories_from_window(messages, settings)
        mark_messages_processed(unprocessed_ids)
        if count > 0:
            total_stored += count
            print(f"[WORKER] 🧠 [{user_id}] Fil {thread_id[:8]}… → {count} souvenir(s)")

    from core.database import purge_episodic_memories
    purged = purge_episodic_memories()
    if purged > 0:
        print(f"[WORKER] 🗑️ [{user_id}] {purged} souvenir(s) episodique(s) expire(s) supprime(s).")

    # Inférence déclenchée uniquement si de nouveaux triplets ont été écrits ce cycle
    if total_stored > 0:
        from modules.memory import run_inference_engine
        print(f"[WORKER] 🔗 [{user_id}] {total_stored} nouveau(x) triplet(s) — inférence déclenchée.")
        await asyncio.get_event_loop().run_in_executor(None, run_inference_engine, user_id)
    else:
        print(f"[WORKER] ⏭️ [{user_id}] Aucun nouveau triplet — inférence ignorée.")

    # Rattrapage des vecteurs manquants ou issus d'un autre modèle (par lots,
    # dans un thread pour ne pas bloquer la boucle). Sans effet si désactivé.
    try:
        from modules.memory import backfill_embeddings
        await asyncio.get_running_loop().run_in_executor(None, backfill_embeddings, user_id)
    except Exception as e:
        print(f"[WORKER] ⚠️ [{user_id}] Rattrapage embeddings : {e}")

    # Purge des références web expirées (péremption de l'information)
    try:
        from core.database import purge_web_references
        n = purge_web_references()
        if n:
            print(f"[WORKER] 🧹 [{user_id}] {n} référence(s) web expirée(s) purgée(s).")
    except Exception as e:
        print(f"[WORKER] ⚠️ [{user_id}] Purge références web : {e}")


_worker_running: bool = False

async def memory_worker():
    """
    Worker async — tourne en arrière-plan toutes les 30s.
    Itère sur tous les profils. Écrivain unique → zéro doublon.
    Garde anti-chevauchement : si le cycle précédent est encore actif, le suivant est skippé.
    """
    global _worker_running
    await asyncio.sleep(10)
    print("[WORKER] 🧠 Worker mémoire démarré (multi-utilisateurs).")

    while True:
        if not _worker_running:
            _worker_running = True
            try:
                from core.database import get_all_users
                for _u in get_all_users():
                    await _worker_process_user(_u['id'])
            except Exception as e:
                print(f"[WORKER] ⚠️ Erreur cycle : {e}")
            finally:
                _worker_running = False
        else:
            print("[WORKER] ⏭️ Cycle précédent encore actif — skippé.")
        await asyncio.sleep(30)


# ══════════════════════════════════════════
# BIBLIOTHÈQUE — GÉNÉRATION RÉSUMÉ
# ══════════════════════════════════════════

async def generate_bibliotheque_entry(thread_id: str) -> dict:
    """Génère une fiche d'archivage — déléguée à modules/bibliotheque.py."""
    from modules.bibliotheque import generate_bibliotheque_entry as _gen
    settings = load_settings(thread_id)
    bilans   = _get_session_bilans(thread_id)
    try:
        mask      = load_mask(settings['mask_id'])
        mask_name = mask.get('name', 'Assistant') or 'Assistant'
    except Exception:
        mask_name = 'Assistant'
    return await _gen(thread_id, settings, mask_name, bilans)


# ══════════════════════════════════════════
# SYNTHESE ONGLET — resume rapatriable
# ══════════════════════════════════════════

async def generate_tab_synthesis(tab_id: str) -> dict:
    """Synthese onglet — deleguee a modules/bibliotheque.py."""
    from modules.bibliotheque import generate_tab_synthesis as _gts
    settings = load_settings()
    settings['api_keys'] = _load_api_keys()
    settings['provider'], settings['model'] = get_task_provider_model('synthese', settings)
    return await _gts(tab_id, settings)


# ══════════════════════════════════════════
# REPRISE ARCHIVE — relance depuis bibliotheque
# ══════════════════════════════════════════

async def resume_from_archive(entry: dict) -> str:
    """Relance archive — deleguee a modules/bibliotheque.py."""
    from modules.bibliotheque import resume_from_archive as _rfa
    settings = load_settings()
    settings['api_keys'] = _load_api_keys()
    settings['provider'], settings['model'] = get_task_provider_model('synthese', settings)
    return await _rfa(entry, settings)


# ══════════════════════════════════════════
# POINT D'ENTREE PRINCIPAL
# ══════════════════════════════════════════

# ══════════════════════════════════════════
# CLASSIFY TOPIC — micro-appel classificateur
# ══════════════════════════════════════════

async def classify_topic(user_message: str) -> None:
    """Appel LLM dédié : détecte si le message révèle un intérêt à noter.
    Tourne en arrière-plan — n'affecte pas la réponse utilisateur."""
    try:
        settings = load_settings()
        api_keys = _load_api_keys()
        provider = settings.get('provider', '')
        if not provider or not api_keys.get(provider):
            return

        system = (
            "Tu es le scribe de l'utilisateur. "
            "Ton rôle est de noter les sujets qu'il explore, les domaines qui l'intéressent, "
            "les questions qu'il pose sur sa curiosité personnelle — pour qu'on puisse s'en souvenir plus tard.\n"
            "Quand l'utilisateur aborde un domaine (culture, sport, philosophie, art, cuisine, littérature, "
            "musique, sciences, loisirs), réponds uniquement : TOPIC: [mot-clé court en 2-3 mots]\n"
            "N'inscris rien pour les tâches pratiques : correction, traduction, calcul, code, "
            "recherche de service, question technique ponctuelle.\n"
            "Si aucun intérêt détecté, réponds uniquement : NONE\n"
            "Un seul mot-clé. Aucun autre texte."
        )

        result = await call_llm(
            messages      = [{'role': 'user', 'content': user_message}],
            provider      = provider,
            system_prompt = system,
            max_tokens    = 15,
            temperature   = 0.0,
            api_keys      = api_keys,
        )

        result = result.strip()
        if result.upper() == 'NONE' or not result:
            return

        # Extraire le mot-clé (supporte "TOPIC: jazz" ou juste "jazz")
        import re as _re
        m = _re.match(r'^TOPIC\s*:\s*(.+)$', result, _re.IGNORECASE)
        topic = m.group(1).strip() if m else result
        topic = topic[:80]  # sécurité longueur

        if topic:
            from core.database import upsert_interet
            entry = upsert_interet(topic, contexte=user_message)
            print(f"[TOPIC] '{topic}' — occ={entry['occurrences']} statut={entry['statut']}")

    except Exception as e:
        print(f"[TOPIC] Erreur classify_topic : {e}")



async def process_message(
    thread_id: str,
    user_message: str,
    images: list = None,
    web_search: bool = False,
    location: str = '',
) -> dict:
    """
    Traitement complet d'un message utilisateur.
    Retourne : { reply, dominant, radar }
    """

    # 1. Charger les settings (avec verrouillage masque par fil)
    settings = load_settings(thread_id)

    # ── Garde provider ──
    provider  = settings.get('provider', '')
    api_keys  = settings.get('api_keys', {})
    _LOCAL    = {'ollama'}
    _KEY_MAP  = {
        'anthropic':  'anthropic',
        'deepseek':   'deepseek',
        'openai':     'openai',
        'gemini':     'gemini',
        'openrouter': 'openrouter',
    }
    if not provider:
        _msg = "T'as cru que tu pouvais chatter gratuitement ? Tout se paye mon ami. 😄\n\nVa te prendre une clé API — DeepSeek, Anthropic, OpenAI, tu as le choix — et reviens quand elle sera configurée. C'est dans les réglages ⚙️, section **Clés API**."
        add_message(thread_id, 'user', user_message)
        add_message(thread_id, 'assistant', _msg)
        return {'reply': _msg, 'dominant': 'neutre', 'radar': '⚪'}
    if provider not in _LOCAL:
        _key_name = _KEY_MAP.get(provider)
        if _key_name and not api_keys.get(_key_name):
            _msg = f"Clé API manquante pour **{provider}**. 🔑\n\nOuvre les réglages ⚙️, section **Clés API**, et entre ta clé. Après ça on peut vraiment commencer."
            add_message(thread_id, 'user', user_message)
            add_message(thread_id, 'assistant', _msg)
            return {'reply': _msg, 'dominant': 'neutre', 'radar': '⚪'}

    # 2. Filtre d'intention (IntentGate)
    try:
        from modules.intent_gate import intent_gate_filter
        intent_reply = await intent_gate_filter(user_message)
        if intent_reply:
            # Sauvegarder le message utilisateur
            add_message(thread_id, 'user', user_message)
            add_message(thread_id, 'assistant', intent_reply)
            return {
                'reply': intent_reply,
                'dominant': 'neutre',
                'radar': '⚪',
            }
    except Exception as e:
        print(f"[HUB] Erreur IntentGate : {e}")
        # Continuer normalement en cas d'erreur

    # 3. Charger la personnalité (masque ou potards)
    try:
        if settings.get('personality_mode') == 'potards':
            mask = {'system_prompt': build_potards_prompt(settings['potards'])}
        else:
            mask = load_mask(settings['mask_id'])
    except Exception:
        mask = {'system_prompt': 'Tu es un assistant utile et direct.'}

    # Pérémer les rappels dont la date est dépassée — silencieux, une fois par pipeline
    perimer_rappels_depasses()

    # 4. Mémoire contextuelle — push léger : permanents uniquement.
    # Les persistants/épisodiques sont récupérés à la demande via tool calling.
    memory_context = build_memory_context_permanent_only()

    # 5. Carnet — signal leger uniquement : le LLM consulte via search_carnet() s'il en a besoin (pull, pas push)
    n_messages = count_messages(thread_id)
    carnet_notes = ['actif'] if count_carnet_notes(thread_id) > 0 else None

    # 6. Présence temporelle
    presence_level = int(get_setting('presence', '5'))
    presence_note  = _build_presence_note(presence_level)

    # 6.5. Mood — signal entrant en priorité, sinon dominant du tour précédent
    last_dominant = _detect_user_mood(user_message) or get_setting(f'dominant_{thread_id}', '')

    # 7. Construire le system prompt
    biblio_context = _match_bibliotheque(user_message)
    force_mem = any(p in user_message.lower() for p in _FORCE_MEM_PATTERNS)
    recent_focus = get_messages(thread_id, limit=5)
    session_bilans = _get_session_bilans(thread_id)
    doc_context, _doc_titles = _match_documents(user_message)
    system_prompt = build_system_prompt(mask, memory_context, carnet_notes, presence_note, last_dominant, settings['user_name'], biblio_context, force_mem, recent_messages=recent_focus, location=location, session_bilans=session_bilans, doc_context=doc_context)

    # 7. Historique recent (60 derniers messages)
    history = get_messages(thread_id, limit=60)
    messages = _sanitize_history([{'role': m['role'], 'content': m['content']} for m in history])

    # 8. Recherche web — pré-enrichissement uniquement si bouton web activé explicitement.
    # La recherche automatique est gérée par le tool calling (search_web).
    web_context = ''
    # Web search : natif Mistral si provider=mistral, sinon Brave/Tavily
    _mistral_ws_tools = None
    if web_search and provider == 'mistral':
        _mistral_ws_tools = [{'type': 'web_search'}]
        print('[HUB] 🌐 Web search Mistral natif')
    if web_search and provider != 'mistral':
        try:
            from modules.websearch import search
            web_context = await search(user_message)
            print(f"[HUB] 🌐 Web search (forcé) : {user_message[:60]}")
        except Exception as e:
            print(f"[HUB] Erreur web search : {e}")

    # 9. Construire le message utilisateur final
    final_user_msg = user_message
    if web_context:
        final_user_msg = (
            f"{user_message}\n\n"
            f"[Résultats de recherche web]\n{web_context}"
        )

    messages.append({'role': 'user', 'content': final_user_msg})

    # 10. Appel LLM avec tool calling (cohérent avec process_message_stream)
    from core.engine import call_llm_stream_with_tools
    raw_reply = ''
    try:
        if images:
            # Vision : pas de tool calling
            raw_reply = await call_llm(
                messages=messages,
                provider=settings['provider'],
                model=settings.get('model'),
                system_prompt=system_prompt,
                max_tokens=settings['max_tokens'],
                temperature=settings['temperature'],
                api_keys=settings['api_keys'],
                images=images,
            )
        else:
            # Phase 1 : détection tool calls
            async for event in call_llm_stream_with_tools(
                messages=messages,
                tools=(_mistral_ws_tools + NIMM_TOOLS) if _mistral_ws_tools else NIMM_TOOLS,
                provider=settings['provider'],
                model=settings.get('model'),
                system_prompt=system_prompt,
                max_tokens=settings['max_tokens'],
                temperature=settings['temperature'],
                api_keys=settings['api_keys'],
            ):
                if event['type'] == 'token':
                    raw_reply += event['text']

                elif event['type'] == 'tool_calls':
                    # Exécuter les outils demandés
                    messages.append(event['assistant_msg'])
                    for call in event['calls']:
                        tool_result = await _execute_tool(call['name'], call['args'], thread_id)
                        print(f"[HUB] 🔍 Tool {call['name']}({call['args'].get('query','')!r}) → {len(tool_result)} chars")
                        messages.append({
                            'role':         'tool',
                            'tool_call_id': call['id'],
                            'content':      tool_result,
                        })
                    # Phase 2 : réponse finale avec contexte enrichi
                    raw_reply = await call_llm(
                        messages=messages,
                        provider=settings['provider'],
                        model=settings.get('model'),
                        system_prompt=system_prompt,
                        max_tokens=settings['max_tokens'],
                        temperature=settings['temperature'],
                        api_keys=settings['api_keys'],
                        tools=NIMM_TOOLS,  # requis par Anthropic : l'historique contient des blocs tool_use/tool_result
                    )

    except Exception as e:
        print(f"[HUB] Erreur LLM : {e}")
        return {
            'reply':    f"Erreur : {str(e)}",
            'dominant': 'neutre',
            'radar':    '🔴',
        }

    # 11. Extraire tous les tags (MEM, DOMINANT, ANECDOTE, SITUATION, RAPPEL)
    raw_reply = _wrap_bare_quiz(raw_reply)
    reply, dominant, extracted_memories, extracted_anecdotes, situation, rappel_actions, image_prompt = extract_all_tags(raw_reply)

    # Bilan de session — enregistre si le LLM a emis un %%BILAN%%
    from modules.memory import extract_bilan_tag
    _bilan = extract_bilan_tag(raw_reply)
    if _bilan:
        _add_session_bilan(thread_id, _bilan)
        print(f"[HUB] Bilan session : {_bilan}")

    if situation:
        import json as _json_sit
        _sit_payload = _json_sit.dumps({'text': situation, 'saved_at': datetime.now().isoformat()})
        set_setting('situation_courante', _sit_payload)
        print(f"[HUB] 📍 Situation mise à jour : {situation}")

    # 11b. Traiter les actions rappel
    if rappel_actions:
        perimer_rappels_depasses()
        for _action in rappel_actions:
            try:
                if _action['action'] == 'creer':
                    _rid = create_rappel(_action['description'], _action.get('date'), _action['type'])
                    print(f"[HUB] 📅 Rappel créé #{_rid} : {_action['description']} ({_action['type']})")
                elif _action['action'] == 'modifier':
                    update_rappel_date(_action['id'], _action['date'])
                    print(f"[HUB] 📅 Rappel #{_action['id']} modifié : {_action['date']}")
                elif _action['action'] == 'clos':
                    close_rappel(_action['id'])
                    print(f"[HUB] 📅 Rappel #{_action['id']} clos.")
                elif _action['action'] == 'emis':
                    marquer_rappel_emis(_action['id'], _action['seuil'])
                    print(f"[HUB] 📅 Rappel #{_action['id']} — seuil '{_action['seuil']}' marqué émis.")
            except Exception as e:
                print(f"[HUB] Erreur traitement rappel (non-stream): {e}")

    # 13. Mémoires — traitées par le worker async (processed_for_memory = 0 par défaut)
    # save_inline_memory retiré : le worker extrait et sauvegarde en arrière-plan.

    # Sauvegarder les anecdotes extraites
    if extracted_anecdotes:
        for anecdote in extracted_anecdotes:
            try:
                save_anecdote(
                    titre=anecdote['titre'],
                    contenu=anecdote['contenu'],
                    contexte=anecdote['contexte'],
                    tags=anecdote['tags'],
                )
                print(f"[HUB] 💫 Anecdote sauvée : {anecdote['titre']}")
            except Exception as e:
                print(f"[HUB] Erreur sauvegarde anecdote: {e}")

    # 14. Sauvegarder les messages
    if _doc_titles:
        reply = (reply or "") + "\n\n— 📄 Documents consultés : " + ", ".join(_doc_titles)
    add_message(thread_id, 'user',      user_message)
    add_message(thread_id, 'assistant', reply)

    # Mood — stocker le dominant pour le prochain tour
    if dominant:
        set_setting(f'dominant_{thread_id}', dominant)

    # Path B désactivé — extraction inline %%MEM%% (Path A) est suffisant.

    # Classifier le topic + carnet en arrière-plan (timeout 20s)
    _create_bg_task(classify_topic(user_message))
    _create_bg_task(maybe_generate_carnet_note(thread_id, settings))

    # 15. Statut radar (cohérence mémoire — simple pour l'instant)
    radar = '🟢' if count_memories() > 0 else '⚪'

    return {
        'reply':       reply,
        'dominant':    _dominant_word(dominant),
        'mood_vector': _dominant_to_vector(dominant),
        'radar':       radar,
    }


# ══════════════════════════════════════════
# STREAMING — POINT D'ENTRÉE
# ══════════════════════════════════════════

async def process_message_stream(
    thread_id: str,
    user_message: str,
    images: list = None,
    web_search: bool = False,
    location: str = '',
):
    """
    Version streaming de process_message.
    Yield les tokens un par un, puis envoie les métadonnées à la fin.
    """
    # 0. Moderation Mistral (optionnelle)
    try:
        import json as _jmod
        _mod_cfg_raw = get_setting('moderation_config', '{}')
        _mod_cfg = _jmod.loads(_mod_cfg_raw)
    except Exception:
        _mod_cfg = {}
    if _mod_cfg.get('enabled') and user_message:
        _mod_keys = {}
        try:
            from core.database import get_api_keys as _gak_mod
            _mod_keys = _gak_mod()
        except Exception:
            pass
        _mod_result = await _check_moderation(user_message, _mod_keys)
        if _mod_result['blocked']:
            _cats_txt = ', '.join(_mod_result['violated'])
            _block_msg = f"Message bloqu\xe9 par le filtre de mod\xe9ration ({_cats_txt})."
            add_message(thread_id, 'user', user_message)
            add_message(thread_id, 'assistant', _block_msg)
            yield f"data: {_block_msg}\n\n"
            yield 'data: [META]{"dominant":"neutre"}\n\n'
            yield "data: [DONE]\n\n"
            return

    from core.engine import call_llm_stream

    # 1. Settings + masque (avec verrouillage masque par fil)
    settings = load_settings(thread_id)

    # ── Mode agent Vibe : override provider Mistral ──
    from core.database import get_thread_agent_mode
    _agent_mode = get_thread_agent_mode(thread_id)
    if _agent_mode == 'vibe':
        settings['provider'] = 'mistral'
        web_search = True  # Vibe = web search natif Mistral toujours actif

    # ── Garde provider ──
    provider  = settings.get('provider', '')
    api_keys  = settings.get('api_keys', {})
    _LOCAL    = {'ollama'}
    _KEY_MAP  = {
        'anthropic':  'anthropic',
        'deepseek':   'deepseek',
        'openai':     'openai',
        'gemini':     'gemini',
        'openrouter': 'openrouter',
    }
    if not provider:
        _msg = "⚙️ Aucun provider configuré. Ouvre les réglages (⚙️), choisis un provider et entre ta clé API."
        add_message(thread_id, 'user', user_message)
        add_message(thread_id, 'assistant', _msg)
        yield f"data: {_msg}\n\n"
        yield f"data: [META]{{\"dominant\": \"neutre\", \"radar\": \"⚪\"}}\n\n"
        yield "data: [DONE]\n\n"
        return
    if provider not in _LOCAL:
        _key_name = _KEY_MAP.get(provider)
        if _key_name and not api_keys.get(_key_name):
            _msg = f"⚙️ Clé API manquante pour **{provider}**. Ouvre les réglages (⚙️) et entre ta clé API."
            add_message(thread_id, 'user', user_message)
            add_message(thread_id, 'assistant', _msg)
            yield f"data: {_msg}\n\n"
            yield f"data: [META]{{\"dominant\": \"neutre\", \"radar\": \"⚪\"}}\n\n"
            yield "data: [DONE]\n\n"
            return

    # 2. Filtre d'intention (IntentGate) — streaming
    try:
        from modules.intent_gate import intent_gate_filter
        intent_reply = await intent_gate_filter(user_message)
        if intent_reply:
            # Sauvegarder les messages
            add_message(thread_id, 'user', user_message)
            add_message(thread_id, 'assistant', intent_reply)
            # Envoyer la réponse en un seul chunk
            yield f"data: {intent_reply}\n\n"
            # Métadonnées
            import json as _json
            meta = _json.dumps({'dominant': 'neutre', 'radar': '⚪'})
            yield f"data: [META]{meta}\n\n"
            yield "data: [DONE]\n\n"
            return
    except Exception as e:
        print(f"[HUB] Erreur IntentGate (stream) : {e}")
        # Continuer normalement en cas d'erreur

    # Charger la personnalité (masque ou potards)
    try:
        if settings.get('personality_mode') == 'potards':
            mask = {'system_prompt': build_potards_prompt(settings['potards'])}
        else:
            mask = load_mask(settings['mask_id'])
    except Exception:
        mask = {'system_prompt': 'Tu es un assistant utile et direct.'}

    # Pérémer les rappels dont la date est dépassée — silencieux, une fois par pipeline
    perimer_rappels_depasses()

    # 3. Contexte — push allégé : seuls les permanents sont injectés d'emblée.
    # Les souvenirs épisodiques/persistants et la bibliothèque sont désormais
    # récupérés à la demande du LLM via tool calling (search_memory / search_bibliotheque).
    # biblio_context = _match_bibliotheque() — matching fuzzy automatique sur l'index bibliothèque
    memory_context = build_memory_context_permanent_only()
    biblio_context = _match_bibliotheque(user_message)
    # Carnet — signal leger uniquement : le LLM consulte via search_carnet() s'il en a besoin (pull, pas push)
    n_messages = count_messages(thread_id)
    carnet_notes = ['actif'] if count_carnet_notes(thread_id) > 0 else None
    # Présence temporelle (streaming aussi)
    presence_level = int(get_setting('presence', '5'))
    presence_note  = _build_presence_note(presence_level)
    # Mood — signal entrant en priorité, sinon dominant du tour précédent
    last_dominant  = _detect_user_mood(user_message) or get_setting(f'dominant_{thread_id}', '')
    force_mem = any(p in user_message.lower() for p in _FORCE_MEM_PATTERNS)
    recent_focus = get_messages(thread_id, limit=5)
    session_bilans = _get_session_bilans(thread_id)
    doc_context, _doc_titles = _match_documents(user_message)
    system_prompt  = build_system_prompt(mask, memory_context, carnet_notes, presence_note, last_dominant, settings['user_name'], biblio_context, force_mem, recent_messages=recent_focus, location=location, session_bilans=session_bilans, doc_context=doc_context)

    # 4. Historique
    history  = get_messages(thread_id, limit=60)
    messages = _sanitize_history([{'role': m['role'], 'content': m['content']} for m in history])

    # 5. Recherche web — pré-enrichissement uniquement si bouton web activé explicitement.
    # La recherche automatique est gérée par le tool calling (search_web).
    web_context = ''
    _mistral_ws_tools = None
    if web_search and provider == 'mistral':
        _mistral_ws_tools = [{'type': 'web_search'}]
        print('[HUB] 🌐 Web search Mistral natif (stream)')
    if web_search and provider != 'mistral':
        yield "data: [WEB_SEARCH_LOADING]\n\n"
        try:
            from modules.websearch import search
            web_context = await search(user_message)
            print(f"[HUB] 🌐 Web search (forcé) : {user_message[:60]}")
        except Exception as e:
            print(f"[HUB] Erreur web search : {e}")

    final_user_msg = user_message
    if web_context:
        final_user_msg = f"{user_message}\n\n[Résultats de recherche web]\n{web_context}"

    messages.append({'role': 'user', 'content': final_user_msg})

    # Sauvegarder le message utilisateur avant le stream (résistance aux interruptions)
    add_message(thread_id, 'user', user_message)

    # 6. Stream des tokens — les tags %%...%% sont filtrés avant le yield
    full_reply  = ''
    _yield_buf  = ''

    def _flush_buf() -> list:
        """Filtre les tags %%...%% du buffer et retourne les chunks propres à yield."""
        nonlocal _yield_buf
        chunks = []
        while True:
            idx = _yield_buf.find('%%')
            if idx == -1:
                if _yield_buf:
                    chunks.append(_yield_buf.replace('\n', '\\n'))
                    _yield_buf = ''
                break
            if idx > 0:
                chunks.append(_yield_buf[:idx].replace('\n', '\\n'))
                _yield_buf = _yield_buf[idx:]
            close_idx = _yield_buf.find('%%', 2)
            if close_idx == -1:
                break
            _yield_buf = _yield_buf[close_idx + 2:]
        return chunks

    try:
        from core.engine import call_llm_stream_with_tools

        if images:
            # Images présentes → stream direct sans tool calling (vision et tools séparés)
            async for token in call_llm_stream(
                messages=messages,
                provider=settings['provider'],
                model=settings.get('model'),
                system_prompt=system_prompt,
                max_tokens=settings['max_tokens'],
                temperature=settings['temperature'],
                api_keys=settings['api_keys'],
                images=images,
            ):
                full_reply += token
                _yield_buf += token
                for chunk in _flush_buf():
                    yield f"data: {chunk}\n\n"

        else:
            # Phase 1 : stream avec détection tool calls
            async for event in call_llm_stream_with_tools(
                messages=messages,
                tools=(_mistral_ws_tools + NIMM_TOOLS) if _mistral_ws_tools else NIMM_TOOLS,
                provider=settings['provider'],
                model=settings.get('model'),
                system_prompt=system_prompt,
                max_tokens=settings['max_tokens'],
                temperature=settings['temperature'],
                api_keys=settings['api_keys'],
            ):
                if event['type'] == 'token':
                    full_reply += event['text']
                    _yield_buf += event['text']
                    for chunk in _flush_buf():
                        yield f"data: {chunk}\n\n"

                elif event['type'] == 'citations':
                    import json as _json_cit
                    yield f"data: [CITATIONS]{_json_cit.dumps(event['citations'], ensure_ascii=False)}\n\n"

                elif event['type'] == 'tool_calls':
                    # ── Exécution des outils demandés par le LLM ──
                    messages.append(event['assistant_msg'])

                    for call in event['calls']:
                        if call['name'] == 'search_web':
                            yield "data: [WEB_SEARCH_LOADING]\n\n"
                        tool_result = await _execute_tool(call['name'], call['args'], thread_id)
                        # Emettre les citations Mistral routing si presentes
                        _cit_val = _pending_citations.get(None)
                        if _cit_val is not None:
                            import json as _jc3
                            yield f"data: [CITATIONS]{_jc3.dumps(_cit_val, ensure_ascii=False)}\n\n"
                            _pending_citations.set(None)
                        messages.append({
                            'role':         'tool',
                            'tool_call_id': call['id'],
                            'content':      tool_result,
                        })

                    # Phase 2 : stream de la réponse finale avec contexte enrichi
                    async for token in call_llm_stream(
                        messages=messages,
                        provider=settings['provider'],
                        model=settings.get('model'),
                        system_prompt=system_prompt,
                        max_tokens=settings['max_tokens'],
                        temperature=settings['temperature'],
                        api_keys=settings['api_keys'],
                        tools=NIMM_TOOLS,  # requis par Anthropic : l'historique contient des blocs tool_use/tool_result
                    ):
                        full_reply += token
                        _yield_buf += token
                        for chunk in _flush_buf():
                            yield f"data: {chunk}\n\n"

    except Exception as e:
        print(f"[HUB] Erreur stream : {e}")
        if full_reply:
            partial, _, _, _, _, _, _ = extract_all_tags(full_reply)
            add_message(thread_id, 'assistant', partial or "[Réponse interrompue]")
        else:
            add_message(thread_id, 'assistant', "[Réponse interrompue — erreur de connexion]")
        yield f"data: [ERREUR: {str(e)}]\n\n"
        return

    # 7. Extraire tous les tags (MEM, DOMINANT, ANECDOTE, SITUATION, RAPPEL)
    full_reply = _wrap_bare_quiz(full_reply)
    reply, dominant, extracted_memories, extracted_anecdotes, situation, rappel_actions, image_prompt = extract_all_tags(full_reply)

    # Bilan de session — enregistre si le LLM a emis un %%BILAN%%
    from modules.memory import extract_bilan_tag
    _bilan = extract_bilan_tag(full_reply)
    if _bilan:
        _add_session_bilan(thread_id, _bilan)
        print(f"[HUB] Bilan session : {_bilan}")

    if situation:
        import json as _json_sit
        _sit_payload = _json_sit.dumps({'text': situation, 'saved_at': datetime.now().isoformat()})
        set_setting('situation_courante', _sit_payload)
        print(f"[HUB] 📍 Situation mise à jour : {situation}")

    # 8b. Traiter les actions rappel
    if rappel_actions:
        perimer_rappels_depasses()
        for _action in rappel_actions:
            try:
                if _action['action'] == 'creer':
                    _rid = create_rappel(_action['description'], _action.get('date'), _action['type'])
                    print(f"[HUB] 📅 Rappel créé #{_rid} : {_action['description']} ({_action['type']})")
                elif _action['action'] == 'modifier':
                    update_rappel_date(_action['id'], _action['date'])
                    print(f"[HUB] 📅 Rappel #{_action['id']} modifié : {_action['date']}")
                elif _action['action'] == 'clos':
                    close_rappel(_action['id'])
                    print(f"[HUB] 📅 Rappel #{_action['id']} clos.")
                elif _action['action'] == 'emis':
                    marquer_rappel_emis(_action['id'], _action['seuil'])
                    print(f"[HUB] 📅 Rappel #{_action['id']} — seuil '{_action['seuil']}' marqué émis.")
            except Exception as e:
                print(f"[HUB] Erreur traitement rappel (stream): {e}")

    # 9. Mémoires — traitées par le worker async (processed_for_memory = 0 par défaut)
    # save_inline_memory retiré : le worker extrait et sauvegarde en arrière-plan.

    # Sauvegarder les anecdotes extraites
    if extracted_anecdotes:
        for anecdote in extracted_anecdotes:
            try:
                save_anecdote(
                    titre=anecdote['titre'],
                    contenu=anecdote['contenu'],
                    contexte=anecdote['contexte'],
                    tags=anecdote['tags'],
                )
                print(f"[HUB] 💫 Anecdote sauvée : {anecdote['titre']}")
            except Exception as e:
                print(f"[HUB] Erreur sauvegarde anecdote (stream): {e}")

    if _doc_titles:
        _doc_footer = "\n\n— 📄 Documents consultés : " + ", ".join(_doc_titles)
        reply = (reply or "") + _doc_footer
        yield f"data: {_doc_footer}\n\n"
    add_message(thread_id, 'assistant', reply)

    # Mood — stocker le dominant pour le prochain tour
    if dominant:
        set_setting(f'dominant_{thread_id}', dominant)

    # Path B désactivé — extraction inline %%MEM%% (Path A) est suffisant.

    # Classifier le topic + carnet en arrière-plan (timeout 20s)
    _create_bg_task(classify_topic(user_message))
    _create_bg_task(maybe_generate_carnet_note(thread_id, settings))

    # 10. Génération image si tag %%IMAGE:%% détecté
    if image_prompt:
        yield "data: [IMAGE_GEN_LOADING]\n\n"
        try:
            from core.engine import generate_image, call_llm
            import json as _json_img
            _img_api_keys = settings.get('api_keys', {})
            _img_provider  = settings.get('provider_routing', {}).get('image', 'gemini')
            # Enrichissement silencieux du prompt (traduction + détails en anglais)
            try:
                image_prompt = await call_llm(
                    messages=[{'role': 'user', 'content': image_prompt}],
                    provider=settings.get('provider', 'deepseek'),
                    model=settings.get('model'),
                    system_prompt=(
                        'You are an image prompt specialist. '
                        'Translate the user prompt to English if needed, then enrich it with visual details '
                        '(style, lighting, composition, mood). '
                        'Return ONLY the enriched prompt, nothing else. Max 120 words.'
                    ),
                    max_tokens=150,
                    temperature=0.7,
                    api_keys=_img_api_keys,
                )
            except Exception as _enrich_err:
                print(f"[HUB] Enrichissement prompt image échoué (prompt original conservé) : {_enrich_err}")
            print(f"[HUB] 🎨 Génération image (tag) → provider={_img_provider} prompt={image_prompt[:80]}")
            _img_result = await generate_image(image_prompt, _img_provider, _img_api_keys)
            _img_url     = _img_result.get('url', '')
            _img_b64     = _img_result.get('b64', '')
            _img_revised = _img_result.get('revised_prompt', image_prompt)
            # Sauvegarder en DB pour que le LLM voie l'image dans l'historique
            _img_assistant_content = f"[Système — image générée]\nPrompt : {_img_revised}"
            add_message(thread_id, 'assistant', _img_assistant_content)
            # Envoyer l'event image au frontend
            _img_payload = _json_img.dumps({
                'url':            _img_url,
                'b64':            _img_b64,
                'prompt':         image_prompt,
                'revised_prompt': _img_revised,
            })
            yield f"data: [IMAGE_GEN]{_img_payload}\n\n"
        except Exception as e:
            print(f"[HUB] Erreur génération image (tag) : {e}")
            yield f"data: [IMAGE_GEN_ERR]{str(e)}\n\n"

    # 11. Envoyer les métadonnées finales
    import json as _json
    radar = '🟢' if count_memories() > 0 else '⚪'
    meta = _json.dumps({
        'dominant':    _dominant_word(dominant),
        'mood_vector': _dominant_to_vector(dominant),
        'radar':       radar,
    })
    yield f"data: [META]{meta}\n\n"
    yield "data: [DONE]\n\n"
