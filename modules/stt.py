# -*- coding: utf-8 -*-
"""
Module STT — Speech-to-Text via Whisper local.
Architecture v2 : enregistrement côté client (MediaRecorder),
transcription côté serveur (Whisper).
Fonctionne sur mobile (Tailscale) et PC.
"""
import whisper
import tempfile
import os

# Pointer ffmpeg vers imageio-ffmpeg (pas besoin d'installation systeme)
try:
    import imageio_ffmpeg
    _ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    _ffmpeg_dir = os.path.dirname(_ffmpeg_exe)
    os.environ['PATH'] = _ffmpeg_dir + os.pathsep + os.environ.get('PATH', '')

    # Creer un alias ffmpeg.exe si le binaire a un nom different
    _ffmpeg_alias = os.path.join(_ffmpeg_dir, 'ffmpeg.exe')
    if not os.path.exists(_ffmpeg_alias) and os.path.basename(_ffmpeg_exe) != 'ffmpeg.exe':
        import shutil
        shutil.copy2(_ffmpeg_exe, _ffmpeg_alias)
        print(f"[STT] Alias ffmpeg.exe cree -> {os.path.basename(_ffmpeg_exe)}")
except ImportError:
    pass


class STTModule:
    MODEL_SIZE = "base"  # fallback si DB inaccessible

    def __init__(self, hub):
        self.hub         = hub
        self.module_name = "stt"
        self._model      = None
        # Lire le modele configure depuis la DB
        try:
            from core.database import get_setting
            configured = get_setting('stt_model', self.MODEL_SIZE)
            if configured in ('tiny', 'base', 'small', 'medium', 'large'):
                self.MODEL_SIZE = configured
        except Exception:
            pass  # fallback sur base

    def _get_model(self):
        if self._model is None:
            print("[STT] Chargement Whisper...")
            self._model = whisper.load_model(self.MODEL_SIZE)
            print("[STT] Whisper prêt.")
        return self._model

    def transcribe_file(self, path: str, initial_prompt: str = None) -> dict:
        """
        Transcrit un fichier audio (webm, wav, mp3…) via Whisper.
        Appelé depuis main.py dans un run_in_executor pour ne pas bloquer l'event loop.
        """
        try:
            kwargs = dict(
                language="fr",
                fp16=False,
                beam_size=8,
                condition_on_previous_text=False,
                no_speech_threshold=0.3,
            )
            if initial_prompt:
                kwargs["initial_prompt"] = initial_prompt[:300]
            result = self._get_model().transcribe(path, **kwargs)
            text   = result["text"].strip()
            print(f"[STT] {text[:80]}")
            return {"status": "ok", "text": text}
        except Exception as e:
            print(f"[STT] Erreur transcription : {e}")
            return {"status": "erreur", "text": "", "error": str(e)}
