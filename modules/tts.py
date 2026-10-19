# ============================================
# NIMM — modules/tts.py
# Synthèse vocale — Kokoro-ONNX + Piper TTS + Edge TTS
# Routage automatique via préfixe voix :
#   "ff_siwis"              → Kokoro
#   "piper:nom_voix"        → Piper (piper_voices/)
#   "edge:fr-FR-DeniseNeural" → Edge TTS (Microsoft, en ligne)
#   texte ALLEMAND détecté  → voix Edge allemande du même genre
#                             (de-DE-KatjaNeural / de-DE-ConradNeural)
# ============================================

import io
import re
import threading
import numpy as np
import soundfile as sf
from pathlib import Path
from typing import Optional

# ── Toutes les voix Kokoro avec labels et drapeaux ──
VOICE_LABELS = {
    'af_alloy':      {'label': 'Alloy',      'lang': '🇺🇸 EN'},
    'af_aoede':      {'label': 'Aoede',      'lang': '🇺🇸 EN'},
    'af_bella':      {'label': 'Bella',      'lang': '🇺🇸 EN'},
    'af_heart':      {'label': 'Heart',      'lang': '🇺🇸 EN'},
    'af_jessica':    {'label': 'Jessica',    'lang': '🇺🇸 EN'},
    'af_kore':       {'label': 'Kore',       'lang': '🇺🇸 EN'},
    'af_nicole':     {'label': 'Nicole',     'lang': '🇺🇸 EN'},
    'af_nova':       {'label': 'Nova',       'lang': '🇺🇸 EN'},
    'af_river':      {'label': 'River',      'lang': '🇺🇸 EN'},
    'af_sarah':      {'label': 'Sarah',      'lang': '🇺🇸 EN'},
    'af_sky':        {'label': 'Sky',        'lang': '🇺🇸 EN'},
    'am_adam':       {'label': 'Adam',       'lang': '🇺🇸 EN'},
    'am_echo':       {'label': 'Echo',       'lang': '🇺🇸 EN'},
    'am_eric':       {'label': 'Eric',       'lang': '🇺🇸 EN'},
    'am_fenrir':     {'label': 'Fenrir',     'lang': '🇺🇸 EN'},
    'am_liam':       {'label': 'Liam',       'lang': '🇺🇸 EN'},
    'am_michael':    {'label': 'Michael',    'lang': '🇺🇸 EN'},
    'am_onyx':       {'label': 'Onyx',       'lang': '🇺🇸 EN'},
    'am_puck':       {'label': 'Puck',       'lang': '🇺🇸 EN'},
    'am_santa':      {'label': 'Santa',      'lang': '🇺🇸 EN'},
    'bf_alice':      {'label': 'Alice',      'lang': '🇬🇧 EN'},
    'bf_emma':       {'label': 'Emma',       'lang': '🇬🇧 EN'},
    'bf_isabella':   {'label': 'Isabella',   'lang': '🇬🇧 EN'},
    'bf_lily':       {'label': 'Lily',       'lang': '🇬🇧 EN'},
    'bm_daniel':     {'label': 'Daniel',     'lang': '🇬🇧 EN'},
    'bm_fable':      {'label': 'Fable',      'lang': '🇬🇧 EN'},
    'bm_george':     {'label': 'George',     'lang': '🇬🇧 EN'},
    'bm_lewis':      {'label': 'Lewis',      'lang': '🇬🇧 EN'},
    'ef_dora':       {'label': 'Dora',       'lang': '🇪🇸 ES'},
    'em_alex':       {'label': 'Alex',       'lang': '🇪🇸 ES'},
    'em_santa':      {'label': 'Santa',      'lang': '🇪🇸 ES'},
    'ff_siwis':      {'label': 'Siwis ⭐',   'lang': '🇫🇷 FR'},
    'hf_alpha':      {'label': 'Alpha',      'lang': '🇮🇳 HI'},
    'hf_beta':       {'label': 'Beta',       'lang': '🇮🇳 HI'},
    'hm_omega':      {'label': 'Omega',      'lang': '🇮🇳 HI'},
    'hm_psi':        {'label': 'Psi',        'lang': '🇮🇳 HI'},
    'if_sara':       {'label': 'Sara',       'lang': '🇮🇹 IT'},
    'im_nicola':     {'label': 'Nicola',     'lang': '🇮🇹 IT'},
    'jf_alpha':      {'label': 'Alpha',      'lang': '🇯🇵 JA'},
    'jf_gongitsune': {'label': 'Gongitsune', 'lang': '🇯🇵 JA'},
    'jf_nezumi':     {'label': 'Nezumi',     'lang': '🇯🇵 JA'},
    'jf_tebukuro':   {'label': 'Tebukuro',   'lang': '🇯🇵 JA'},
    'jm_kumo':       {'label': 'Kumo',       'lang': '🇯🇵 JA'},
    'pf_dora':       {'label': 'Dora',       'lang': '🇧🇷 PT'},
    'pm_alex':       {'label': 'Alex',       'lang': '🇧🇷 PT'},
    'pm_santa':      {'label': 'Santa',      'lang': '🇧🇷 PT'},
    'zf_xiaobei':    {'label': 'Xiaobei',    'lang': '🇨🇳 ZH'},
    'zf_xiaoni':     {'label': 'Xiaoni',     'lang': '🇨🇳 ZH'},
    'zf_xiaoxiao':   {'label': 'Xiaoxiao',   'lang': '🇨🇳 ZH'},
    'zf_xiaoyi':     {'label': 'Xiaoyi',     'lang': '🇨🇳 ZH'},
    'zm_yunjian':    {'label': 'Yunjian',    'lang': '🇨🇳 ZH'},
    'zm_yunxi':      {'label': 'Yunxi',      'lang': '🇨🇳 ZH'},
    'zm_yunxia':     {'label': 'Yunxia',     'lang': '🇨🇳 ZH'},
    'zm_yunyang':    {'label': 'Yunyang',    'lang': '🇨🇳 ZH'},
}

DEFAULT_VOICE = 'edge:fr-FR-DeniseNeural'
SILENCE_MS    = 120

BASE_DIR      = Path(__file__).parent.parent
MODEL_PATH    = BASE_DIR / 'kokoro-v1.0.onnx'
VOICES_PATH   = BASE_DIR / 'voices-v1.0.bin'
PIPER_DIR     = BASE_DIR / 'piper_voices'


# ══════════════════════════════════════════
# UTILITAIRES COMMUNS
# ══════════════════════════════════════════

def _clean_text(text: str) -> str:
    """Nettoie le texte avant synthèse — retire markdown, tags %%, balises HTML, didascalies."""
    # Supprimer les émojis (plans Unicode supplémentaires + symboles courants)
    import re as _re
    text = _re.sub(r'[\U00010000-\U0010ffff]', '', text)  # émojis Supplementary planes
    text = _re.sub(r'[\u2600-\u27BF\u2B00-\u2BFF\u3000-\u303F]', '', text)  # symboles misc
    text = _re.sub(r'[\uFE00-\uFE0F\u200D\uFEFF]', '', text)  # variation selectors, ZWJ
    import unicodedata
    # Normalisation NFC
    text = unicodedata.normalize('NFC', text)
    # Tags NIMM — complets et partiels (sécurité si chunk mal découpé)
    text = re.sub(r'%%[^%]*%%', '', text)
    text = re.sub(r'%%.*$', '', text, flags=re.MULTILINE)
    # HTML — séparateurs et sauts → pause (. pour marquer une coupure propre)
    text = re.sub(r'<hr\s*/?>', '. ', text, flags=re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', ', ', text, flags=re.IGNORECASE)
    # HTML — items de liste → phrase terminée par un point
    text = re.sub(r'<li[^>]*>(.*?)</li>', lambda m: m.group(1).strip().rstrip('.,;:') + '. ', text, flags=re.IGNORECASE | re.DOTALL)
    # HTML — toutes les autres balises → supprimées
    text = re.sub(r'<[^>]{1,80}>', '', text)
    # Items de liste Markdown (•, -, *, chiffre.) en début de ligne → phrase terminée par un point
    text = re.sub(r'(?m)^[\s]*[•\-\*][\s]+(.*?)$', lambda m: m.group(1).strip().rstrip('.,;:') + '. ', text)
    text = re.sub(r'(?m)^[\s]*\d+[\.\)]\s+(.*?)$', lambda m: m.group(1).strip().rstrip('.,;:') + '. ', text)
    # Sauts de ligne et retours chariot → pause (après traitement des listes)
    text = re.sub(r'\\n|[\r\n]+', ' ', text)
    # Tiret cadratin → virgule (pause naturelle à la lecture)
    text = re.sub(r'\s*—\s*', ', ', text)
    # Markdown résiduel
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'#{1,6}\s', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'\[[^\]]{2,80}\]', '', text)
    # Espace manquant après ponctuation (ex: "fin.Début" → "fin. Début")
    text = re.sub(r'([.!?])([A-ZÀ-Ÿa-zà-ÿ])', r'\1 \2', text)
    # Espaces multiples
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def _split_sentences(text: str) -> list:
    """Découpe le texte en phrases sur . ! ?"""
    parts = re.split(r'(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()]


def _make_silence(sample_rate: int, ms: int) -> np.ndarray:
    """Génère un tableau numpy de silence."""
    return np.zeros(int(sample_rate * ms / 1000), dtype=np.float32)


# ══════════════════════════════════════════
# KOKORO
# ══════════════════════════════════════════

_kokoro   = None
_kk_lock  = threading.Lock()
_kk_ready = False


def _load_kokoro():
    global _kokoro, _kk_ready
    try:
        from kokoro_onnx import Kokoro
        with _kk_lock:
            _kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))
        _kk_ready = True
        print("[TTS/Kokoro] Chargé ✓")
    except Exception as e:
        print(f"[TTS/Kokoro] Erreur chargement : {e}")

threading.Thread(target=_load_kokoro, daemon=True).start()


def synthesize_kokoro(text: str, voice: str = DEFAULT_VOICE) -> Optional[bytes]:
    """Synthèse Kokoro — phrase par phrase, lang=fr-fr."""
    if not _kk_ready or _kokoro is None:
        raise FileNotFoundError("Kokoro non disponible (chargement en cours ou fichiers manquants).")

    text = _clean_text(text)
    if not text:
        return None

    phrases   = _split_sentences(text)
    all_audio = []
    sample_rate = None

    with _kk_lock:
        for phrase in phrases:
            if not phrase:
                continue
            try:
                samples, sr = _kokoro.create(phrase, voice=voice, speed=1.0, lang='fr-fr')
                if sample_rate is None:
                    sample_rate = sr
                all_audio.append(samples)
                all_audio.append(_make_silence(sr, SILENCE_MS))
            except Exception as e:
                print(f"[TTS/Kokoro] Erreur phrase '{phrase[:30]}' : {e}")

    if not all_audio or sample_rate is None:
        return None

    buf = io.BytesIO()
    sf.write(buf, np.concatenate(all_audio), sample_rate, format='WAV')
    buf.seek(0)
    return buf.read()


# ══════════════════════════════════════════
# PIPER
# ══════════════════════════════════════════

_piper_cache = {}          # { voice_id: PiperVoice }
_piper_lock  = threading.Lock()
_piper_ready = False


def _scan_piper_voices() -> dict:
    """Scanne piper_voices/ et retourne { voice_id: chemin_onnx }."""
    voices = {}
    if not PIPER_DIR.exists():
        return voices
    for f in sorted(PIPER_DIR.glob('*.onnx')):
        if f.with_suffix('.onnx.json').exists() or Path(str(f) + '.json').exists():
            voices[f.stem] = str(f)
    return voices


def _get_piper_voice(voice_id: str):
    """Charge et met en cache une instance PiperVoice."""
    with _piper_lock:
        if voice_id not in _piper_cache:
            from piper import PiperVoice
            model_path = PIPER_DIR / f'{voice_id}.onnx'
            if not model_path.exists():
                raise FileNotFoundError(f"Voix Piper introuvable : {voice_id}.onnx")
            _piper_cache[voice_id] = PiperVoice.load(str(model_path))
            print(f"[TTS/Piper] Voix '{voice_id}' chargée ✓")
        return _piper_cache[voice_id]


def _preload_piper():
    """Précharge la première voix Piper disponible au démarrage."""
    global _piper_ready
    voices = _scan_piper_voices()
    if not voices:
        print("[TTS/Piper] Aucune voix dans piper_voices/ — moteur disponible dès ajout d'un modèle.")
        _piper_ready = True
        return
    first_id = next(iter(voices))
    try:
        _get_piper_voice(first_id)
        _piper_ready = True
        print(f"[TTS/Piper] Prêt ✓ (voix par défaut : {first_id})")
    except Exception as e:
        print(f"[TTS/Piper] Erreur préchargement : {e}")
        _piper_ready = True  # disponible quand même pour les autres voix

threading.Thread(target=_preload_piper, daemon=True).start()


def synthesize_piper(text: str, voice_id: str) -> Optional[bytes]:
    """Synthèse Piper — via phonemize/phoneme_ids_to_audio, sans wave module."""
    text = _clean_text(text)
    if not text:
        return None

    piper_voice = _get_piper_voice(voice_id)
    sample_rate = piper_voice.config.sample_rate

    phrases   = _split_sentences(text)
    all_audio = []

    for phrase in phrases:
        if not phrase:
            continue
        try:
            # Convertir le texte en phonèmes
            phonemes_list = piper_voice.phonemize(phrase)
            # Aplatir la liste de listes de phonèmes
            all_phoneme_ids = []
            for phonemes in phonemes_list:
                ids = piper_voice.phonemes_to_ids(phonemes)
                all_phoneme_ids.extend(ids)
            
            # Générer l'audio directement en float32
            samples = piper_voice.phoneme_ids_to_audio(all_phoneme_ids)
            # Vérifier le type (déjà float32 normalement)
            if samples.dtype == np.int16:
                samples = samples.astype(np.float32) / 32768.0
            elif samples.dtype != np.float32:
                samples = samples.astype(np.float32)
            
            all_audio.append(samples)
            all_audio.append(_make_silence(sample_rate, SILENCE_MS))
        except Exception as e:
            print(f"[TTS/Piper] Erreur phrase '{phrase[:30]}' : {e}")

    if not all_audio:
        return None

    out = io.BytesIO()
    sf.write(out, np.concatenate(all_audio), sample_rate, format='WAV')
    out.seek(0)
    return out.read()


# ══════════════════════════════════════════
# EDGE TTS (Microsoft — en ligne, MP3)
# ══════════════════════════════════════════

# Voix françaises Edge avec notation qualité
EDGE_VOICES_FR = [
    {'id': 'fr-FR-DeniseNeural',               'label': 'Denise',   'note': '⭐⭐⭐⭐⭐', 'region': '🇫🇷 FR'},
    {'id': 'fr-FR-HenriNeural',                'label': 'Henri',    'note': '⭐⭐⭐⭐⭐', 'region': '🇫🇷 FR'},
    {'id': 'fr-FR-VivienneMultilingualNeural',  'label': 'Vivienne', 'note': '⭐⭐⭐⭐',  'region': '🇫🇷 FR'},
    {'id': 'fr-FR-RemyMultilingualNeural',      'label': 'Rémy',     'note': '⭐⭐⭐⭐',  'region': '🇫🇷 FR'},
    {'id': 'fr-FR-EloiseNeural',                'label': 'Éloïse',   'note': '⭐⭐⭐⭐',  'region': '🇫🇷 FR'},
    {'id': 'fr-BE-CharlineNeural',              'label': 'Charline', 'note': '⭐⭐⭐',   'region': '🇧🇪 BE'},
    {'id': 'fr-BE-GerardNeural',                'label': 'Gérard',   'note': '⭐⭐⭐',   'region': '🇧🇪 BE'},
    {'id': 'fr-CH-ArianeNeural',                'label': 'Ariane',   'note': '⭐⭐⭐',   'region': '🇨🇭 CH'},
    {'id': 'fr-CH-FabriceNeural',               'label': 'Fabrice',  'note': '⭐⭐⭐',   'region': '🇨🇭 CH'},
    {'id': 'fr-CA-SylvieNeural',                'label': 'Sylvie',   'note': '⭐⭐⭐',   'region': '🇨🇦 CA'},
    {'id': 'fr-CA-AntoineNeural',               'label': 'Antoine',  'note': '⭐⭐⭐',   'region': '🇨🇦 CA'},
    {'id': 'fr-CA-ThierryNeural',               'label': 'Thierry',  'note': '⭐⭐⭐',   'region': '🇨🇦 CA'},
]


async def _edge_async(text: str, voice: str) -> Optional[bytes]:
    """Coroutine edge-tts — retourne les bytes MP3."""
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice)
        audio = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
        return audio if audio else None
    except Exception as e:
        print(f"[TTS/Edge] Erreur : {e}")
        return None


def synthesize_edge(text: str, voice: str) -> Optional[bytes]:
    """Synthèse Edge TTS — s'exécute dans un thread isolé pour éviter les conflits asyncio."""
    import asyncio
    import threading

    text = _clean_text(text)
    if not text:
        return None

    result    = [None]
    exc       = [None]

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result[0] = loop.run_until_complete(_edge_async(text, voice))
        except Exception as e:
            exc[0] = e
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=30)

    if exc[0]:
        raise exc[0]
    return result[0]


# ══════════════════════════════════════════
# GEMINI TTS (API Google — voix naturelles, mono & multi-locuteurs)
# ══════════════════════════════════════════

GEMINI_VOICES = [
    ('Zephyr', 'lumineuse'), ('Puck', 'enjouée'), ('Charon', 'informative'),
    ('Kore', 'ferme'), ('Fenrir', 'vive'), ('Leda', 'jeune'), ('Orus', 'ferme'),
    ('Aoede', 'légère'), ('Callirrhoe', 'décontractée'), ('Autonoe', 'lumineuse'),
    ('Enceladus', 'soufflée'), ('Iapetus', 'claire'), ('Umbriel', 'décontractée'),
    ('Algieba', 'douce'), ('Despina', 'douce'), ('Erinome', 'claire'),
    ('Algenib', 'rauque'), ('Rasalgethi', 'informative'), ('Laomedeia', 'enjouée'),
    ('Achernar', 'douce'), ('Alnilam', 'ferme'), ('Schedar', 'posée'),
    ('Gacrux', 'mûre'), ('Pulcherrima', 'directe'), ('Achird', 'amicale'),
    ('Zubenelgenubi', 'familière'), ('Vindemiatrix', 'douce'), ('Sadachbia', 'vive'),
    ('Sadaltager', 'savante'), ('Sulafat', 'chaleureuse'),
]


def _gemini_tts_model():
    try:
        from core.database import get_setting
        return get_setting('gemini_tts_model', 'gemini-2.5-flash-preview-tts') or 'gemini-2.5-flash-preview-tts'
    except Exception:
        return 'gemini-2.5-flash-preview-tts'


def _gemini_api_key():
    try:
        from core.database import get_api_keys
        keys = get_api_keys() or {}
        return (keys.get('gemini') or keys.get('google') or '').strip()
    except Exception:
        return ''


def _pcm_to_wav(pcm, rate=24000, channels=1, sampwidth=2):
    import io, wave
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _gemini_tts_request(body, api_key, model, retries=2):
    """POST à l'API Gemini TTS. Retourne le PCM (bytes) ou None. Retry sur 500 (cf. doc Google)."""
    import urllib.request, urllib.error, json as _json, base64, time as _t
    url = "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent?key=" + api_key
    data = _json.dumps(body).encode('utf-8')
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=180) as r:
                res = _json.loads(r.read())
            parts = (res.get('candidates') or [{}])[0].get('content', {}).get('parts', [])
            for pp in parts:
                inline = pp.get('inlineData') or pp.get('inline_data')
                if inline and inline.get('data'):
                    return base64.b64decode(inline['data'])
            print('[TTS/Gemini] Réponse sans audio.')
            return None
        except urllib.error.HTTPError as e:
            if e.code == 500 and attempt < retries:
                _t.sleep(1.0)
                continue
            try:
                _m = e.read()[:200]
            except Exception:
                _m = b''
            print('[TTS/Gemini] HTTP ' + str(e.code) + ' : ' + str(_m))
            return None
        except Exception as e:
            print('[TTS/Gemini] Erreur : ' + str(e))
            return None
    return None


def synthesize_gemini(text, voice_name='Kore', style='', api_key=''):
    """Synthèse mono-locuteur via l'API Gemini TTS. Retourne du WAV (24 kHz) ou None.

    api_key : transmise par l'appelant (lue dans le contexte asyncio, AVANT le
    thread executor — cf. main.py). Repli sur _gemini_api_key() pour les appels
    directs hors requête HTTP (tests, scripts), où le contexte utilisateur peut
    déjà être posé sur le thread principal."""
    text = _clean_text(text)
    if not text:
        return None
    api_key = (api_key or '').strip() or _gemini_api_key()
    if not api_key:
        print('[TTS/Gemini] Aucune clé API Gemini configurée.')
        return None
    prompt = (style.strip() + '\n\n' + text) if (style and style.strip()) else text
    body = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'responseModalities': ['AUDIO'],
            'speechConfig': {'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': voice_name}}},
        },
    }
    pcm = _gemini_tts_request(body, api_key, _gemini_tts_model())
    return _pcm_to_wav(pcm) if pcm else None


def synthesize_gemini_multi(transcript, speakers, style='', api_key=''):
    """Synthèse multi-locuteurs (jusqu'à 2). speakers = [(nom, voix), ...]. WAV ou None.

    api_key : même règle que synthesize_gemini() — transmise par l'appelant en
    priorité, repli sur _gemini_api_key() sinon."""
    transcript = _clean_text(transcript)
    if not transcript:
        return None
    api_key = (api_key or '').strip() or _gemini_api_key()
    if not api_key:
        print('[TTS/Gemini] Aucune clé API Gemini configurée.')
        return None
    speakers = (speakers or [])[:2]
    if not speakers:
        return None
    cfgs = [{'speaker': str(nom), 'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': vx}}}
            for (nom, vx) in speakers]
    prompt = (style.strip() + '\n\n' + transcript) if (style and style.strip()) else transcript
    body = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'responseModalities': ['AUDIO'],
            'speechConfig': {'multiSpeakerVoiceConfig': {'speakerVoiceConfigs': cfgs}},
        },
    }
    pcm = _gemini_tts_request(body, api_key, _gemini_tts_model())
    return _pcm_to_wav(pcm) if pcm else None


# ══════════════════════════════════════════
# PRONONCIATION ALLEMANDE AUTOMATIQUE
# ══════════════════════════════════════════
# Une réponse peut contenir un passage allemand (Maya fait des ponts
# français/allemand). Lue par une voix française, une phrase allemande
# s'entend tout de suite : le ü, le ö et le ß n'ont pas d'équivalent.
#
# La détection est un jeu de règles EXPLICITE, pas un modèle : elle doit être
# vérifiable hors ligne, et un faux positif se paie cher — une phrase
# française lue avec l'accent allemand. Trois signaux suffisent :
#   1. les caractères ä ö ü ß, qui n'existent pas en français (signal fort) ;
#   2. au moins 3 mots-outils allemands, et la moitié des mots du texte ;
#   3. au moins 2 mots-outils allemands dans un texte de 4 mots ou moins.
# DEUX ÉTAGES, essayés dans cet ordre :
#   1. la phrase est MIXTE (un morceau allemand au milieu d'une phrase
#      française) : `segmenter_par_langue()` la découpe en morceaux, chacun est
#      synthétisé avec SA voix, puis les MP3 sont recollés — c'est le cas
#      d'école « En allemand, « Ich habe Hunger » veut dire j'ai faim », lu
#      avec les deux accents au bon endroit ;
#   2. sinon (phrase entièrement allemande, ou moteur sans découpage) : la
#      voix bascule d'un bloc.
# Le seuil de détection reste volontairement haut : un faux positif se paie
# plus cher (toute une phrase française à l'accent allemand) qu'un court
# passage laissé en français.
#
# La substitution se fait DANS LE MÊME MOTEUR, et seulement si ce moteur a
# une voix allemande : c'est le cas d'Edge (voix par défaut et voix de
# masque). Kokoro n'a pas de voix DE dans son catalogue, piper_voices/ ne
# contient que du français, et Gemini / Voxtral / Mistral sont multilingues —
# ces moteurs ne sont pas touchés.

LETTRES_ALLEMANDES = 'äöüß'

# Mots-outils et mots courants SANS ambiguïté avec le français. Écartés pour
# cause d'homographe : en anglais (`in`, `an`, `so`, `man`, `was`, `will`,
# `tag`, `warm`, `hand`, `blind`) et en français (`du` de « du pain », `sein`
# de « du sein » : sans cette précaution, « le cancer du sein » était classé
# allemand). « die » est gardé : très fréquent en allemand, rare en français.
MOTS_ALLEMANDS = frozenset({
    'der', 'die', 'das', 'den', 'dem', 'ein', 'eine', 'einen',
    'einem', 'einer', 'eines', 'und', 'oder', 'aber', 'nicht', 'kein',
    'keine', 'keinen', 'ich', 'dich', 'dir', 'mir', 'euch', 'ihr', 'mein',
    'meine', 'dein', 'deine', 'seine', 'ist', 'sind', 'bist', 'bin', 'habe',
    'hast', 'hat', 'geht', 'gehe', 'gehen', 'komme', 'kommst', 'kommt',
    'mache', 'machst', 'machen', 'weiß', 'wissen', 'kenne', 'kennst',
    'brauche', 'brauchst', 'finde', 'findest', 'glaube', 'denke', 'esse',
    'hunger', 'durst', 'deutsch', 'wetter', 'sagt', 'erklärt',
    'essen', 'isst', 'trinke', 'helfen', 'hilfst', 'spielt', 'spielen',
    'haben', 'hatte', 'kann', 'kannst', 'können', 'muss', 'musst',
    'möchte', 'möchtest', 'soll', 'werden', 'wird', 'würde', 'war', 'wenn',
    'weil', 'dass', 'auch', 'noch', 'schon', 'nur', 'sehr', 'immer',
    'wieder', 'jetzt', 'heute', 'gestern', 'morgen', 'mit', 'für', 'von',
    'bei', 'nach', 'über', 'unter', 'zwischen', 'auf', 'aus', 'durch',
    'gegen', 'ohne', 'wie', 'wer', 'wohin', 'warum', 'bitte', 'danke',
    'hallo', 'guten', 'wiedersehen', 'tschüss', 'willkommen', 'vielen',
    'dank', 'grüße', 'entschuldigung', 'richtig', 'falsch', 'gut',
    'schlecht', 'sprechen',
    'spricht', 'lernen', 'lerne', 'üben', 'verstehen', 'sagen', 'fragen',
    'antworten', 'schreiben', 'schreibe', 'schreibst', 'lesen', 'hören',
    'satz', 'sätze', 'im', 'perfekt', 'präsens', 'beispiel', 'aufgabe',
    'wort', 'wörter',
    'schule', 'lehrer', 'lehrerin', 'kind', 'mädchen', 'junge', 'hund',
    'katze', 'haus', 'wohnung', 'wasser', 'brot', 'buch', 'bücher',
    'vokabeln', 'wortschatz', 'hausaufgabe', 'klassenzimmer', 'heft',
    'stunde', 'prüfung', 'nummer', 'tabelle',
    'eins', 'zwei', 'drei', 'vier', 'fünf', 'sechs', 'sieben', 'acht',
    'neun', 'zehn', 'ja', 'nein',
})

# Correspondance de voix, par moteur : la voix allemande garde le GENRE de la
# voix française, pour que le personnage ne change pas de timbre au milieu
# d'une réponse.
VOIX_DE_PAR_MOTEUR = {
    'edge': {'feminin': 'de-DE-KatjaNeural', 'masculin': 'de-DE-ConradNeural'},
}

# Voix Edge FRANÇAISES masculines connues (toutes les autres sont féminines).
EDGE_VOIX_FR_MASCULINES = frozenset({
    'fr-FR-HenriNeural', 'fr-FR-RemyMultilingualNeural', 'fr-BE-GerardNeural',
    'fr-CH-FabriceNeural', 'fr-CA-AntoineNeural', 'fr-CA-ThierryNeural',
})


def detecter_allemand(texte: str) -> bool:
    """Dit si un texte est majoritairement allemand (voir le bloc ci-dessus).

    Fonction PURE : aucun réseau, aucune base, aucun état — donc testable
    hors ligne. Un texte vide ne déclenche rien.
    """
    if not texte:
        return False
    bas = texte.lower()
    if any(c in bas for c in LETTRES_ALLEMANDES):
        return True
    mots = re.findall(r'[^\W\d_]+', bas)
    if not mots:
        return False
    allemands = sum(1 for m in mots if m in MOTS_ALLEMANDS)
    if allemands >= 3 and allemands * 2 >= len(mots):
        return True
    return allemands >= 2 and len(mots) <= 4


def _voix_allemande(voice: str) -> Optional[str]:
    """Voix allemande équivalente à `voice`, ou None s'il n'y en a pas.

    Seule une voix Edge FRANÇAISE est convertie : une voix Edge d'une autre
    langue traduit un choix explicite, on n'y touche pas — et un moteur sans
    voix allemande n'a pas besoin de changement.
    """
    if not voice or not voice.startswith('edge:'):
        return None
    nom = voice[5:]
    if not nom.startswith('fr-'):
        return None
    genre = 'masculin' if nom in EDGE_VOIX_FR_MASCULINES else 'feminin'
    voix_de = VOIX_DE_PAR_MOTEUR['edge'].get(genre)
    return 'edge:' + voix_de if voix_de else None


# ── Découper une phrase MIXTE en morceaux de langue ────────────────────────
# « En allemand, « Ich habe Hunger » veut dire j'ai faim. » n'est ni française
# ni allemande : elle contient un morceau de chaque. La lire d'une seule voix
# la trahit forcément. On la découpe donc en morceaux, chacun avec SA voix, et
# on recolle l'audio dans le même moteur (MP3 Edge, cf. plus bas).

# Mots-outils et vocabulaire français : ils servent de BORNE. Un mot inconnu
# collé à un morceau allemand est absorbé par ce morceau (« Hunger » dans
# « Ich habe Hunger »), mais un mot français ne l'est jamais.
# Écrits SANS ACCENT : la comparaison passe par `_cle_fr()`, qui neutralise les
# accents français (é è ê à ç…) mais PAS ä ö ü ß, gardés comme marqueurs de
# l'allemand.
MOTS_FRANCAIS = frozenset({
    # déterminants et pronoms
    'le', 'la', 'les', 'un', 'une', 'des', 'du', 'de', 'au', 'aux', 'ce',
    'cet', 'cette', 'ces', 'mon', 'ma', 'mes', 'ton', 'ta', 'tes', 'son',
    'sa', 'ses', 'notre', 'nos', 'votre', 'vos', 'leur', 'leurs', 'je',
    'tu', 'il', 'elle', 'on', 'nous', 'vous', 'ils', 'elles', 'me', 'te',
    'se', 'moi', 'toi', 'lui', 'eux', 'qui', 'que', 'quoi', 'dont', 'y',
    'ca', 'cela', 'ceci',
    # verbes courants
    'est', 'sont', 'etait', 'etaient', 'etais', 'ete', 'etre', 'a', 'ai',
    'as', 'ont', 'avait', 'avaient', 'avoir', 'avons', 'avez', 'fait',
    'faire', 'fais', 'dit', 'dire', 'dis', 'dites', 'veut', 'veux',
    'veulent', 'vouloir', 'peut', 'peux', 'pouvez', 'pouvoir', 'doit',
    'dois', 'devez', 'devoir', 'sait', 'sais', 'savoir', 'voit', 'vois',
    'voir', 'va', 'vas', 'aller', 'vient', 'viens', 'venir', 'prend',
    'prendre', 'met', 'mettre', 'appelle', 'appeler', 'trouve', 'trouver',
    'pense', 'penser', 'crois', 'croire', 'parle', 'parler', 'parlent',
    'apprend', 'apprends', 'apprendre', 'ecrit', 'ecrire', 'lis', 'lire',
    'ecoute', 'ecouter', 'comprend', 'comprends', 'comprendre', 'traduit',
    'traduire', 'signifie', 'signifier', 'repond', 'repondre', 'demande',
    'demander', 'explique', 'expliquer', 'mange', 'manger', 'boit', 'boire',
    # mots-outils
    'et', 'ou', 'mais', 'donc', 'or', 'ni', 'car', 'quand', 'comment',
    'pourquoi', 'parce', 'puisque', 'si', 'tres', 'bien', 'tout', 'tous',
    'toute', 'toutes', 'aussi', 'encore', 'deja', 'toujours', 'jamais',
    'plus', 'moins', 'trop', 'peu', 'beaucoup', 'ici', 'la', 'alors',
    'ensuite', 'apres', 'avant', 'dans', 'sur', 'sous', 'avec', 'sans',
    'chez', 'entre', 'pour', 'par', 'vers', 'contre', 'pendant', 'depuis',
    'ne', 'pas', 'non', 'oui', 'aujourd', 'hui', 'meme', 'autre', 'autres',
    'chaque', 'quelque', 'quelques', 'plusieurs', 'rien',
    # adjectifs et vocabulaire de classe
    'grand', 'grande', 'petit', 'petite', 'bon', 'bonne', 'mauvais',
    'mauvaise', 'beau', 'belle', 'nouveau', 'nouvelle', 'vieux', 'vieille',
    'jeune', 'francais', 'francaise', 'allemand', 'allemande', 'anglais',
    'anglaise', 'mot', 'mots', 'phrase', 'phrases', 'exemple', 'exemples',
    'exercice', 'exercices', 'reponse', 'reponses', 'question', 'questions',
    'lecon', 'lecons', 'professeur', 'prof', 'eleve', 'eleves', 'classe',
    'ecole', 'cours', 'devoir', 'devoirs', 'grammaire', 'regle', 'regles',
    'chose', 'choses', 'fois', 'verbe', 'verbes', 'sujet', 'texte', 'ligne',
    'lignes', 'nom', 'adjectif', 'traduction',
})

_ACCENTS_FR = str.maketrans('áàâãéèêëíìîïóòôõúùûçñœæ', 'aaaaeeeeiiiioooouuucnoa')

MIN_MOTS_ALLEMAND = 2   # en dessous, on ne détache pas de morceau
MAX_EXTENSION     = 2   # mots inconnus absorbés au plus, de chaque côté


def _cle_fr(mot: str) -> str:
    """Forme de comparaison française : minuscules, accents français retirés."""
    return mot.lower().translate(_ACCENTS_FR)


def _est_allemand(mot: str) -> bool:
    """Un mot est allemand s'il est connu, ou s'il porte un caractère allemand."""
    bas = mot.lower()
    return bas in MOTS_ALLEMANDS or any(c in bas for c in LETTRES_ALLEMANDES)


def segmenter_par_langue(texte: str) -> list:
    """Découpe `texte` en morceaux (texte, langue) — langue vaut 'de' ou 'fr'.

    Fonction PURE, testable hors ligne. La concaténation des morceaux rend
    EXACTEMENT le texte d'entrée : rien ne se perd au passage.

    Quatre étapes :
      1. chaque mot est marqué allemand ou non (liste, ou caractère ä ö ü ß) ;
      2. un mot non allemand ENCADRÉ par deux mots allemands devient allemand
         (« du » dans « Kannst du mir helfen ? ») ;
      3. on obtient des suites de mots allemands, ÉTENDUES aux mots inconnus
         qui les touchent (au plus MAX_EXTENSION de chaque côté) ;
      4. une suite devient un morceau si elle compte au moins MIN_MOTS_ALLEMAND
         mots allemands, ou si elle porte un ä ö ü ß. Un mot allemand isolé au
         milieu d'une phrase française reste donc français — sauf « Übung »,
         qu'un umlaut suffit à détacher.
    """
    if not texte or not texte.strip():
        return []
    mots = list(re.finditer(r'[^\W\d_]+', texte))
    if not mots:
        return [(texte, 'fr')]
    allemand = [_est_allemand(m.group(0)) for m in mots]

    # (2) enveloppement
    for i in range(1, len(mots) - 1):
        if not allemand[i] and allemand[i - 1] and allemand[i + 1]:
            allemand[i] = True

    # (3) suites de mots allemands contigus
    suites, debut = [], None
    for i, est in enumerate(allemand):
        if est and debut is None:
            debut = i
        elif not est and debut is not None:
            suites.append([debut, i - 1])
            debut = None
    if debut is not None:
        suites.append([debut, len(mots) - 1])

    etendues = []
    for d, f in suites:
        reste_g = reste_d = MAX_EXTENSION
        while (d > 0 and reste_g and not allemand[d - 1]
               and _cle_fr(mots[d - 1].group(0)) not in MOTS_FRANCAIS):
            d -= 1
            reste_g -= 1
        while (f < len(mots) - 1 and reste_d and not allemand[f + 1]
               and _cle_fr(mots[f + 1].group(0)) not in MOTS_FRANCAIS):
            f += 1
            reste_d -= 1
        etendues.append([d, f])

    # deux suites peuvent se rejoindre après extension : on les fusionne
    fusion = []
    for d, f in etendues:
        if fusion and d <= fusion[-1][1] + 1:
            fusion[-1][1] = max(fusion[-1][1], f)
        else:
            fusion.append([d, f])

    # (4) seuil : de vrais mots allemands, ou un caractère allemand
    retenues = []
    for d, f in fusion:
        nb = sum(1 for i in range(d, f + 1) if allemand[i])
        texte_suite = texte[mots[d].start():mots[f].end()].lower()
        if nb >= MIN_MOTS_ALLEMAND or any(c in texte_suite for c in LETTRES_ALLEMANDES):
            retenues.append((d, f))
    if not retenues:
        return [(texte, 'fr')]

    # morceaux : allemand aux bornes retenues, français partout ailleurs
    morceaux, curseur = [], 0
    for d, f in retenues:
        debut_txt, fin_txt = mots[d].start(), mots[f].end()
        if debut_txt > curseur:
            morceaux.append((texte[curseur:debut_txt], 'fr'))
        morceaux.append((texte[debut_txt:fin_txt], 'de'))
        curseur = fin_txt
    if curseur < len(texte):
        morceaux.append((texte[curseur:], 'fr'))
    morceaux = [(t, lg) for t, lg in morceaux if t.strip()]

    # La ponctuation ne se prononce pas : un morceau sans AUCUNE lettre ne
    # mérite pas sa propre voix — il rejoint son voisin de gauche, ou celui de
    # droite s'il ouvre le texte. Sans cela, le point final de
    # « Der Hund ist groß. » faisait un second morceau, et une voix française
    # était appelée pour lire un point.
    propres = []
    for t, lg in morceaux:
        if re.search(r'[^\W\d_]', t):
            propres.append([t, lg])
        elif propres:
            propres[-1][0] += t
        else:
            propres.append([t, lg])
    if len(propres) > 1 and not re.search(r'[^\W\d_]', propres[0][0]):
        propres[1][0] = propres[0][0] + propres[1][0]
        propres.pop(0)
    morceaux = [(t, lg) for t, lg in propres if re.search(r'[^\W\d_]', t)]
    return morceaux or [(texte, 'fr')]


def _assembler_segments_edge(segments: list, voice: str, voice_de: str) -> Optional[bytes]:
    """Synthétise chaque morceau avec SA voix, puis recolle les MP3.

    Les MP3 d'Edge commencent directement sur une trame, sans en-tête ID3
    (vérifié) : deux flux de même format se recollent bout à bout, un simple
    `b''.join` suffit. Retourne None dès qu'un morceau échoue — l'appelant
    retombe alors sur la synthèse en voix unique, jamais sur du silence.
    """
    morceaux = []
    for segment, langue in segments:
        voix_segment = voice_de[5:] if langue == 'de' else voice[5:]
        audio = synthesize_edge(segment, voix_segment)
        if not audio:
            return None
        morceaux.append(audio)
    return b''.join(morceaux) if morceaux else None


# ══════════════════════════════════════════
# ROUTEUR PRINCIPAL
# ══════════════════════════════════════════

def synthesize(text: str, voice: str = DEFAULT_VOICE, style: str = '', api_key: str = '') -> tuple[Optional[bytes], str]:
    """
    Point d'entrée unique. Retourne (bytes, media_type).
    Si voice est vide et qu'une clé Gemini est disponible, utilise une voix Gemini par défaut.
    Voix préfixée 'piper:'  → Piper  (audio/wav)
    Voix préfixée 'edge:'   → Edge   (audio/mpeg)
    Voix préfixée 'gemini:' → Gemini TTS (audio/wav) — style optionnel
    Tout le reste           → Kokoro (audio/wav)

    Un passage ALLEMAND fait lire le texte par la voix allemande du même
    moteur (cf. bloc « prononciation allemande » plus haut) — même si le
    masque déclare une voix française. Deux étages :
      - phrase MIXTE (un morceau allemand au milieu d'une phrase française) :
        chaque morceau reçoit SA voix, puis les MP3 sont recollés (Edge seul) ;
      - sinon, phrase entièrement allemande : la voix bascule d'un bloc.
    Si un morceau échoue, la synthèse en voix unique prend le relais : jamais
    de silence à la place d'une réponse.
    """
    _voix_de = _voix_allemande(voice)
    if _voix_de:
        if voice.startswith('edge:'):
            _segments = segmenter_par_langue(text)
            if len(_segments) > 1:
                _audio = _assembler_segments_edge(_segments, voice, _voix_de)
                if _audio:
                    print("[TTS] Phrase mixte (%s) -> %d morceaux"
                          % ('+'.join(l for _, l in _segments), len(_segments)))
                    return _audio, 'audio/mpeg'
        if detecter_allemand(text):
            print(f"[TTS] Passage allemand detecte -> voix {_voix_de}")
            voice = _voix_de

    if voice.startswith('piper:'):
        return synthesize_piper(text, voice[6:]), 'audio/wav'
    if voice.startswith('edge:'):
        return synthesize_edge(text, voice[5:]), 'audio/mpeg'
    if voice.startswith('gemini:'):
        return synthesize_gemini(text, voice[7:], style=style, api_key=api_key), 'audio/wav'
    if voice.startswith('voxtral:'):
        return synthesize_voxtral(text, voice[8:], api_key=api_key), 'audio/mpeg'
    if voice.startswith('mistral:'):
        return synthesize_mistral_speech(text, voice_id=voice[8:], api_key=api_key), 'audio/mpeg'
    if voice.startswith('mistral-clone:'):
        return synthesize_mistral_speech(text, ref_audio_b64=voice[14:], api_key=api_key), 'audio/mpeg'
    return synthesize_kokoro(text, voice), 'audio/wav'


def list_voices() -> list:
    """Toutes les voix proposées dans le sélecteur, tous moteurs confondus.

    SIX familles, et non trois : Kokoro et Piper (locaux), Edge, Gemini,
    Voxtral (voix clonées chez Mistral) et Mistral Speech (voix preset).
    Le libellé porte le moteur et une note, pour que le choix reste lisible
    dans une liste déroulante longue.

    Cette liste énumérait effectivement trois moteurs à l'origine ; le
    docstring n'avait pas suivi, et il a suffi à faire croire à un manque
    inexistant lors d'un audit. Le tenir à jour n'est donc pas cosmétique.
    """
    result = []

    # ── Kokoro ── (⭐⭐⭐ — local, multilingue)
    for vid, info in VOICE_LABELS.items():
        result.append({
            'id':     vid,
            'label':  f"🟡 Kokoro ⭐⭐⭐ — {info['lang']} {info['label']}",
            'lang':   info['lang'],
            'engine': 'kokoro',
        })

    # ── Piper ── (⭐⭐⭐⭐ — local, FR natif)
    for voice_id in _scan_piper_voices():
        result.append({
            'id':     f'piper:{voice_id}',
            'label':  f'🟣 Piper ⭐⭐⭐⭐ — {voice_id}',
            'lang':   '🇫🇷 FR',
            'engine': 'piper',
        })

    # ── Edge TTS ── (⭐⭐⭐ à ⭐⭐⭐⭐⭐ — en ligne, FR natif)
    for v in EDGE_VOICES_FR:
        result.append({
            'id':     f"edge:{v['id']}",
            'label':  f"🔵 Edge {v['note']} — {v['region']} {v['label']}",
            'lang':   v['region'],
            'engine': 'edge',
        })

    # ── Gemini TTS ── (⭐⭐⭐⭐⭐ — en ligne, clé Google requise, 70+ langues, multi-locuteurs)
    for _gname, _gdesc in GEMINI_VOICES:
        result.append({
            'id':     f'gemini:{_gname}',
            'label':  f'✨ Gemini ⭐⭐⭐⭐⭐ — {_gname} ({_gdesc})',
            'lang':   '🌐',
            'engine': 'gemini',
        })

    # ── Voxtral TTS ── (⭐⭐⭐⭐⭐ — Mistral, clonage de voix personnalisé)
    try:
        from core.database import list_voice_profiles
        for _vp in list_voice_profiles():
            _badge = ' ⭐ [par défaut]' if _vp.get('is_default') else ''
            result.append({
                'id':         f"voxtral:{_vp['mistral_voice_id']}",
                'label':      f"🟠 Voxtral ⭐⭐⭐⭐⭐ — {_vp['name']}{_badge}",
                'lang':       f"{_vp.get('language','fr').upper()}",
                'engine':     'voxtral',
                'profile_id': _vp['id'],
            })
    except Exception:
        pass

    # -- Mistral Audio Speech (voix preset)
    try:
        for _mv in list_mistral_voices():
            _mvid = _mv.get('voice_id') or _mv.get('id') or ''
            _mvlabel = _mv.get('name') or _mv.get('display_name') or _mvid
            if _mvid:
                result.append({
                    'id':     'mistral:' + _mvid,
                    'label':  '🟠 Mistral Speech ⭐⭐⭐⭐⭐ — ' + _mvlabel,
                    'lang':   '🌐',
                    'engine': 'mistral',
                })
    except Exception:
        pass

    return result


# ══════════════════════════════════════════
# VOXTRAL TTS (Mistral — voice cloning)
# ══════════════════════════════════════════

def synthesize_voxtral(text: str, mistral_voice_id: str, api_key: str = '') -> Optional[bytes]:
    """
    Synthèse vocale via Mistral Voxtral TTS.
    voice_id = identifiant de voix stocké chez Mistral.
    Retourne des bytes MP3.
    """
    import json, urllib.request
    if not api_key:
        try:
            from core.database import get_api_keys
            api_key = (get_api_keys().get('mistral') or '').strip()
        except Exception:
            api_key = ''
    if not api_key:
        raise RuntimeError("Clé API Mistral non configurée — impossible d'utiliser Voxtral TTS.")

    body = json.dumps({
        'model': 'voxtral-mini-tts-2603',
        'voice_id': mistral_voice_id,
        'input': text,
        'response_format': 'mp3',
    }).encode('utf-8')

    req = urllib.request.Request(
        'https://api.mistral.ai/v1/audio/speech',
        data=body,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
    )
    import base64 as _b64
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
        # Mistral retourne {"audio_data": "<base64>"}
        audio_b64 = data.get('audio_data', '')
        if not audio_b64:
            raise RuntimeError(f'Mistral TTS : pas de audio_data dans la réponse : {data}')
        return _b64.b64decode(audio_b64)


# ==========================================
# MISTRAL AUDIO SPEECH (preset + zero-shot cloning)
# ==========================================

def list_mistral_voices(api_key: str = '') -> list:
    """
    Retourne la liste des voix Mistral preset (GET /v1/audio/voices).
    Retourne [] si cle absente ou API indisponible.
    """
    import json, urllib.request
    if not api_key:
        try:
            from core.database import get_api_keys
            api_key = (get_api_keys().get('mistral') or '').strip()
        except Exception:
            api_key = ''
    if not api_key:
        return []
    try:
        req = urllib.request.Request(
            'https://api.mistral.ai/v1/audio/voices',
            headers={'Authorization': f'Bearer {api_key}'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()).get('voices', [])
    except Exception:
        return []


def synthesize_mistral_speech(
    text: str,
    voice_id: str = '',
    ref_audio_b64: str = '',
    fmt: str = 'mp3',
    api_key: str = ''
) -> Optional[bytes]:
    """
    TTS Mistral : voix preset (voice_id) ou clonage zero-shot (ref_audio_b64).
    Retourne des bytes MP3.
    """
    import json, urllib.request, base64 as _b64
    if not api_key:
        try:
            from core.database import get_api_keys
            api_key = (get_api_keys().get('mistral') or '').strip()
        except Exception:
            api_key = ''
    if not api_key:
        raise RuntimeError('Cle API Mistral non configuree.')
    payload: dict = {
        'input': text,
        'model': 'voxtral-mini-tts-2603',
        'response_format': fmt,
    }
    if voice_id:
        payload['voice_id'] = voice_id
    if ref_audio_b64:
        payload['ref_audio'] = ref_audio_b64
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        'https://api.mistral.ai/v1/audio/speech',
        data=body,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        rdata = json.loads(resp.read())
        audio_b64 = rdata.get('audio_data', '')
        if not audio_b64:
            raise RuntimeError(f'Mistral Audio Speech : pas de audio_data : {rdata}')
        return _b64.b64decode(audio_b64)
