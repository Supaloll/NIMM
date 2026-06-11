# ============================================
# NIMM — modules/tts.py
# Synthèse vocale — Kokoro-ONNX + Piper TTS + Edge TTS
# Routage automatique via préfixe voix :
#   "ff_siwis"              → Kokoro
#   "piper:nom_voix"        → Piper (piper_voices/)
#   "edge:fr-FR-DeniseNeural" → Edge TTS (Microsoft, en ligne)
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
# ROUTEUR PRINCIPAL
# ══════════════════════════════════════════

def synthesize(text: str, voice: str = DEFAULT_VOICE) -> tuple[Optional[bytes], str]:
    """
    Point d'entrée unique. Retourne (bytes, media_type).
    Voix préfixée 'piper:' → Piper  (audio/wav)
    Voix préfixée 'edge:'  → Edge   (audio/mpeg)
    Tout le reste          → Kokoro (audio/wav)
    """
    if voice.startswith('piper:'):
        return synthesize_piper(text, voice[6:]), 'audio/wav'
    if voice.startswith('edge:'):
        return synthesize_edge(text, voice[5:]), 'audio/mpeg'
    return synthesize_kokoro(text, voice), 'audio/wav'


def list_voices() -> list:
    """Retourne toutes les voix disponibles (Kokoro + Piper + Edge)."""
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

    return result
