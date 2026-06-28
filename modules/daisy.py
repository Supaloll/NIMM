"""Génération de livres DAISY 2.02 accessibles.

Produit un fichier ZIP (extension .daisy) contenant :
  - ncc.html       : Navigation Control Center (index, métadonnées)
  - sectionN.htm   : contenu XHTML avec IDs sur chaque paragraphe
  - sectionN.smil  : synchronisation texte ↔ audio
  - sectionN.mp3   : audio synthétisé (MP3 CBR 64kbps mono)

Utilisé par l'outil CoaNIMM `nimm_make_daisy`.

Format : DAISY 2.02 (DTB — Digital Talking Book), compatible Victor Reader,
AMIS, EasyReader, BrailleNote, etc.

Entrée : `title` (str), `sections` (liste de dicts), `lang` (str),
         `voice` (str — voix TTS, préfixe 'gemini:' recommandé),
         `style` (str — consigne de style Gemini TTS).

Chaque section : {'titre': str, 'texte': str}. Le texte est découpé en
paragraphes (séparés par ligne vide). Chaque paragraphe → un <par> SMIL.
"""

import io
import re
import uuid
import zipfile
import html as _html
from datetime import datetime


# ── Helpers ──────────────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    """Identifiant sûr depuis un texte."""
    return re.sub(r'[^a-z0-9]', '_', text.lower())[:40] or 'section'


def _paragraphes(texte: str) -> list[str]:
    """Découpe un texte en paragraphes (séparés par ligne vide)."""
    paras = [p.strip() for p in re.split(r'\n{2,}', texte or '')]
    return [p for p in paras if p]


def _fmt_time(seconds: float) -> str:
    """Formate un nombre de secondes en 'npt=H:MM:SS.mmm'."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"npt={h}:{m:02d}:{s:06.3f}"


def _pcm_to_mp3(pcm_bytes: bytes, sample_rate: int = 24000,
                bitrate: int = 64) -> bytes:
    """Encode du PCM 16-bit mono en MP3 CBR via lameenc."""
    try:
        import lameenc
    except ImportError:
        raise RuntimeError(
            "lameenc est requis pour la génération DAISY MP3. "
            "Installe-le avec : pip install lameenc"
        )
    enc = lameenc.Encoder()
    enc.set_bit_rate(bitrate)
    enc.set_in_sample_rate(sample_rate)
    enc.set_channels(1)
    enc.set_quality(5)        # 5 = bon compromis qualité/vitesse
    enc.silence_encoder()     # supprime les logs LAME vers stderr
    return enc.encode(pcm_bytes) + enc.flush()


def _synthesize_section(text: str, voice: str, style: str, api_key: str = "") -> tuple[bytes, float]:
    """Synthétise un texte → (mp3_bytes, durée_secondes).

    Retourne (b'', 0.0) si la synthèse échoue ou si aucune voix TTS
    n'est disponible (mode texte seul).
    """
    if not text.strip():
        return b'', 0.0
    try:
        from modules.tts import synthesize
        audio_bytes, media_type = synthesize(text, voice, style, api_key=api_key)
        if not audio_bytes:
            return b'', 0.0

        if 'wav' in media_type:
            # Extraire le PCM depuis le WAV (sauter les 44 octets d'en-tête)
            pcm = audio_bytes[44:]
            duration = len(pcm) / (24000 * 2)   # 24 kHz, 16-bit mono
            mp3 = _pcm_to_mp3(pcm, sample_rate=24000)
        else:
            # Audio déjà encodé (edge TTS → mp3) : durée estimée à 128kbps
            mp3 = audio_bytes
            duration = len(mp3) * 8 / (64 * 1000)

        return mp3, duration
    except Exception as e:
        print(f"[DAISY] Synthèse échouée : {e}")
        return b'', 0.0


# ── Générateurs de fichiers ───────────────────────────────────────────────────

def _build_section_html(sec_id: str, titre: str,
                        paras: list[str], para_ids: list[str],
                        lang: str) -> str:
    """Génère le fichier .htm d'une section."""
    titre_e = _html.escape(titre)
    paras_html = '\n'.join(
        f'    <p id="{pid}">{_html.escape(p)}</p>'
        for pid, p in zip(para_ids, paras)
    )
    return (
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f'<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"\n'
        f'  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}" lang="{lang}">\n'
        f'<head>\n'
        f'  <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>\n'
        f'  <title>{titre_e}</title>\n'
        f'</head>\n'
        f'<body>\n'
        f'  <h1 id="h_{sec_id}">{titre_e}</h1>\n'
        f'{paras_html}\n'
        f'</body>\n'
        f'</html>\n'
    )


def _build_smil(sec_id: str, titre: str, htm_file: str, mp3_file: str,
                para_ids: list[str], durations: list[float],
                total_dur: float) -> str:
    """Génère le fichier .smil d'une section."""
    titre_e = _html.escape(titre)
    pars = []
    offset = 0.0
    for pid, dur in zip(para_ids, durations):
        if dur <= 0:
            continue
        end = offset + dur
        pars.append(
            f'    <par id="par_{pid}" endsync="last">\n'
            f'      <text src="{htm_file}#{pid}"/>\n'
            f'      <audio src="{mp3_file}"'
            f' clip-begin="{_fmt_time(offset)}"'
            f' clip-end="{_fmt_time(end)}"/>\n'
            f'    </par>'
        )
        offset = end

    seq_dur = f'{total_dur:.3f}s'
    body = '\n'.join(pars) if pars else (
        f'    <par id="par_h_{sec_id}" endsync="last">\n'
        f'      <text src="{htm_file}#h_{sec_id}"/>\n'
        f'    </par>'
    )
    return (
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f'<!DOCTYPE smil PUBLIC "-//W3C//DTD SMIL 1.0//EN"\n'
        f'  "http://www.w3.org/TR/REC-smil/SMIL10.dtd">\n'
        f'<smil>\n'
        f'<head>\n'
        f'  <meta name="dc:title" content="{titre_e}"/>\n'
        f'  <meta name="dc:format" content="Daisy 2.02"/>\n'
        f'  <layout/>\n'
        f'</head>\n'
        f'<body>\n'
        f'  <seq dur="{seq_dur}">\n'
        f'{body}\n'
        f'  </seq>\n'
        f'</body>\n'
        f'</smil>\n'
    )


def _build_ncc(title: str, lang: str, sections_nav: list[dict],
               total_time: float, uid: str) -> str:
    """Génère le fichier ncc.html."""
    title_e = _html.escape(title)
    h, m = int(total_time // 3600), int((total_time % 3600) // 60)
    s = int(total_time % 60)
    total_str = f'{h}:{m:02d}:{s:02d}'
    date_str = datetime.now().strftime('%Y-%m-%d')
    depth = 1

    navs = []
    for nav in sections_nav:
        smil_f  = nav['smil_file']
        first_p = nav['first_par_id']
        titre_e = _html.escape(nav['titre'])
        navs.append(
            f'  <h1 class="section"><a href="{smil_f}#par_{first_p}">'
            f'{titre_e}</a></h1>'
        )

    return (
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f'<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"\n'
        f'  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}" lang="{lang}">\n'
        f'<head>\n'
        f'  <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>\n'
        f'  <meta name="dc:title" content="{title_e}"/>\n'
        f'  <meta name="dc:language" content="{lang}"/>\n'
        f'  <meta name="dc:date" content="{date_str}"/>\n'
        f'  <meta name="dc:format" content="Daisy 2.02"/>\n'
        f'  <meta name="dc:identifier" content="{uid}"/>\n'
        f'  <meta name="ncc:generator" content="NIMM CoaNIMM"/>\n'
        f'  <meta name="ncc:depth" content="{depth}"/>\n'
        f'  <meta name="ncc:totalTime" content="{total_str}"/>\n'
        f'  <meta name="ncc:tocItems" content="{len(sections_nav)}"/>\n'
        f'  <title>{title_e}</title>\n'
        f'</head>\n'
        f'<body>\n'
        + '\n'.join(navs) + '\n'
        f'</body>\n'
        f'</html>\n'
    )


# ── Point d'entrée ─────────────────────────────────────────────────────────

def build_daisy(title: str, sections: list, lang: str = 'fr',
                voice: str = '', style: str = '', api_key: str = '') -> bytes:
    """Construit un livre DAISY 2.02 et retourne le ZIP en bytes.

    Args:
        title    : titre du livre.
        sections : liste de dicts {'titre': str, 'texte': str}.
        lang     : code langue BCP47 ('fr', 'fr-FR', 'en', …).
        voice    : voix TTS ('gemini:Kore', 'ff_siwis', …). Vide = voix par défaut.
        style    : consigne de style Gemini TTS (optionnel).

    Returns:
        bytes du fichier ZIP (extension .daisy recommandée).
    """
    from modules.accessible_doc import _norm_sections
    sections = _norm_sections(sections)
    if not voice:
        voice = 'ff_siwis'

    uid = str(uuid.uuid4())
    buf = io.BytesIO()
    total_time = 0.0
    sections_nav = []

    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for idx, sec in enumerate(sections, start=1):
            sec_id   = f's{idx:03d}'
            titre    = sec.get('titre') or f'Section {idx}'
            texte    = sec.get('texte') or ''
            paras    = _paragraphes(texte)
            if not paras:
                paras = [titre]

            htm_file = f'{sec_id}.htm'
            mp3_file = f'{sec_id}.mp3'
            smil_file = f'{sec_id}.smil'

            # IDs des paragraphes
            para_ids = [f'{sec_id}_p{i:03d}' for i in range(len(paras))]

            # Synthèse audio : un MP3 par section (tout le texte concaténé)
            full_text = f'{titre}. {" ".join(paras)}'
            mp3_bytes, sec_dur = _synthesize_section(full_text, voice, style, api_key=api_key)

            # Durées par paragraphe (proportionnelles aux longueurs)
            if sec_dur > 0 and paras:
                lengths = [len(p) for p in paras]
                total_len = sum(lengths) or 1
                # +len(titre)+2 pour l'intro du titre dans full_text
                titre_dur = sec_dur * (len(titre) + 2) / (total_len + len(titre) + 2)
                remaining = sec_dur - titre_dur
                para_durs = [remaining * l / total_len for l in lengths]
            else:
                para_durs = [0.0] * len(paras)

            total_time += sec_dur

            # Fichier HTML de section
            htm_content = _build_section_html(
                sec_id, titre, paras, para_ids, lang)
            zf.writestr(htm_file, htm_content.encode('utf-8'))

            # Fichier SMIL
            smil_content = _build_smil(
                sec_id, titre, htm_file, mp3_file,
                para_ids, para_durs, sec_dur)
            zf.writestr(smil_file, smil_content.encode('utf-8'))

            # Fichier MP3 (vide si pas de TTS disponible)
            if mp3_bytes:
                zf.writestr(mp3_file, mp3_bytes)

            # Navigation
            sections_nav.append({
                'titre'       : titre,
                'smil_file'   : smil_file,
                'first_par_id': para_ids[0] if para_ids else f'h_{sec_id}',
            })

        # NCC
        ncc_content = _build_ncc(title, lang, sections_nav, total_time, uid)
        zf.writestr('ncc.html', ncc_content.encode('utf-8'))

    return buf.getvalue()
