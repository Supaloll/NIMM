"""
Enrichissement web — ingestion de contenu dans la zone de référence (`web_reference`).

Plusieurs portes d'entrée (texte collé, URL, et plus tard PDF / .docx / OCR Mistral),
un seul cœur commun : normaliser → vectoriser → ranger dans la zone de référence,
TOUJOURS séparée de la mémoire personnelle.

Phase 1 : adaptateurs « texte collé » et « URL » (étage léger via trafilatura,
sans navigateur ; le repli JavaScript façon Playwright viendra en phase 2).

Par défaut, le contenu ingéré est PERMANENT (pas d'expiration) : on l'ajoute pour
le conserver. La classification de périssabilité reste possible plus tard.
"""


def _norm(s):
    return " ".join((s or "").split())


def _embedding_for(texte):
    """Vecteur (sérialisé) pour la recherche par sens, ou None si embeddings indisponibles."""
    try:
        from modules.memory import _embed, _serialize_embedding
        v = _embed(texte)
        return _serialize_embedding(v) if v is not None else None
    except Exception:
        return None


def _chunk_text(text, target=1100, overlap=150):
    """Découpe un texte en passages d'environ `target` caractères, par paragraphes,
    avec un léger chevauchement pour ne pas couper les idées."""
    text = (text or "").strip()
    if not text:
        return []
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) + 1 > target:
            chunks.append(cur)
            cur = (cur[-overlap:] + " " + p) if overlap else p
        else:
            cur = (cur + "\n" + p) if cur else p
    if cur:
        chunks.append(cur)
    # Redécoupe les passages anormalement longs (paragraphe massif sans saut de ligne).
    final = []
    for c in chunks:
        if len(c) <= target * 1.6:
            final.append(c)
        else:
            step = max(1, target - overlap)
            for i in range(0, len(c), step):
                final.append(c[i:i + target])
    return final


def ingest_text(titre, texte, source="texte", expiration=None):
    """Range un contenu dans la zone de référence ET l'indexe en passages
    (pour « interroge mes documents »). `expiration` None = permanent.
    """
    from core.database import save_web_reference, save_reference_chunks
    titre = _norm(titre) or ("Texte collé" if source == "texte" else source)
    texte = (texte or "").strip()
    if not texte:
        return {"ok": False, "erreur": "Contenu vide."}
    cle = (titre + " — " + texte[:200]).strip()
    emb = _embedding_for(cle)
    try:
        ref_id = save_web_reference(titre, _norm(titre).lower(), texte, emb, expiration, source=source)
    except Exception as e:
        print(f"[ENRICH] Échec d'enregistrement : {e}")
        return {"ok": False, "erreur": "Échec de l'enregistrement du document."}
    # Découpage + vectorisation des passages pour la recherche par sens.
    n_passages = 0
    try:
        from modules.memory import _embed, _serialize_embedding
        rows = []
        for i, c in enumerate(_chunk_text(texte)):
            v = _embed(c)
            rows.append((i, c, _serialize_embedding(v) if v is not None else None))
        if rows:
            save_reference_chunks(ref_id, titre, source, rows)
            n_passages = len(rows)
    except Exception as e:
        print(f"[ENRICH] Découpage/vectorisation impossible : {e}")
    return {"ok": True, "titre": titre, "longueur": len(texte), "passages": n_passages}


def search_documents(query, k=5):
    """Recherche par sens dans les passages des documents ingérés.
    Retourne une liste de dicts {titre, source, passage, score}, [] si rien
    (ou si les embeddings sont indisponibles)."""
    try:
        from modules.memory import _embed, _parse_embedding, _cosine
    except Exception:
        return []
    qv = _embed(query)
    if qv is None:
        return []
    from core.database import get_all_reference_chunks
    scored = []
    for ch in get_all_reference_chunks():
        rv, _m = _parse_embedding(ch.get("embedding"))
        if rv is None:
            continue
        scored.append((_cosine(qv, rv), ch))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{
        "titre":   ch.get("titre"),
        "source":  ch.get("source"),
        "passage": ch.get("content"),
        "score":   round(float(s), 3),
    } for (s, ch) in scored[:k]]


_SEUIL_TEXTE = 200  # en deçà (caractères), on tente le rendu navigateur (page JavaScript)
_SEUIL_PDF_IMAGE = 40  # un PDF qui rend moins que ça est tenu pour scanné/image → OCR


def _render_playwright(url, timeout_ms=20000):
    """Rend une page via un navigateur headless (Playwright). None si indisponible.
    Headless : aucune fenêtre. Repli réservé aux pages dont le contenu est en JS."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    from modules import net_guard
    if not net_guard.is_public_url(url):
        print(f"[ENRICH] Rendu refusé (cible interne / tailnet) : {url}")
        return None
    try:
        with sync_playwright() as p:
            navigateur = p.chromium.launch(headless=True)
            page = navigateur.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            html = page.content()
            navigateur.close()
        return html
    except Exception as e:
        print(f"[ENRICH] Rendu Playwright impossible : {e}")
        return None


def extract_url(url, allow_browser=True):
    """Récupère et extrait le contenu principal d'une URL.

    Étage léger (trafilatura, sans navigateur) d'abord ; si le texte est trop
    maigre (page JavaScript), repli sur un rendu navigateur headless.
    Retourne (titre, texte), ou (None, None) si rien d'exploitable.
    """
    try:
        import trafilatura
    except Exception:
        raise RuntimeError("trafilatura n'est pas installé (pip install trafilatura).")
    from modules import net_guard
    net_guard.assert_public_url(url)  # anti-SSRF : refuse loopback/privé/tailnet
    downloaded = trafilatura.fetch_url(url)
    html = downloaded
    texte = trafilatura.extract(
        downloaded, include_comments=False, include_tables=True, favor_recall=True
    ) if downloaded else None
    # Repli navigateur si l'étage léger ne ramène pas assez de texte.
    if allow_browser and (not texte or len(texte) < _SEUIL_TEXTE):
        rendu = _render_playwright(url)
        if rendu:
            t2 = trafilatura.extract(
                rendu, include_comments=False, include_tables=True, favor_recall=True
            )
            if t2 and len(t2) > len(texte or ""):
                texte, html = t2, rendu
    titre = None
    if html:
        try:
            meta = trafilatura.extract_metadata(html)
            if meta and getattr(meta, "title", None):
                titre = meta.title
        except Exception:
            pass
    return (titre or url), (texte or None)


def ingest_url(url, expiration=None):
    """Scrape une URL (étage léger) et range son contenu. Retourne un compte rendu."""
    url = _norm(url)
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "erreur": "URL invalide (doit commencer par http:// ou https://)."}
    try:
        titre, texte = extract_url(url)
    except Exception as e:
        print(f"[ENRICH] Échec récupération URL : {e}")
        return {"ok": False, "erreur": "Impossible de récupérer cette page."}
    if not texte:
        return {"ok": False, "erreur": "Aucun texte exploitable extrait (page en JavaScript ?)."}
    res = ingest_text(titre, texte, source=url, expiration=expiration)
    res["url"] = url
    return res


def list_references():
    """Références actives, pour le panneau. Les plus récentes d'abord."""
    from core.database import get_active_web_references
    refs = get_active_web_references()
    out = []
    for r in refs:
        out.append({
            "id":          r.get("id"),
            "titre":       r.get("query"),
            "source":      r.get("source") or "recherche",
            "captured_at": r.get("captured_at"),
            "expiration":  r.get("expiration"),
            "apercu":      (r.get("content") or "")[:160],
        })
    out.sort(key=lambda x: x.get("captured_at") or "", reverse=True)
    return out


# ════════════════════════════════════════════════════════════════════
# ADAPTATEURS FICHIERS — PDF (texte / image→OCR), .docx, image, texte
# ════════════════════════════════════════════════════════════════════

_EXT_IMAGE = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff"}
_EXT_TEXTE = {"txt", "md", "csv"}


def mistral_key_from_settings(settings):
    """Clé OCR Mistral selon les réglages, ou None en mode local
    (en mode local, rien n'est envoyé au cloud)."""
    settings = settings or {}
    if settings.get("local_mode"):
        return None
    return (settings.get("api_keys") or {}).get("mistral")


def extract_pdf_text(path):
    """Texte sélectionnable d'un PDF (pypdf). Vide si le PDF est une image."""
    try:
        from pypdf import PdfReader
    except Exception:
        raise RuntimeError("pypdf n'est pas installé (pip install pypdf).")
    reader = PdfReader(path)
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            pass
    return "\n\n".join(p for p in parts if p.strip())


def extract_docx(path):
    """Texte d'un .docx (python-docx)."""
    try:
        import docx
    except Exception:
        raise RuntimeError("python-docx n'est pas installé (pip install python-docx).")
    d = docx.Document(path)
    return "\n".join(p.text for p in d.paragraphs if p.text.strip())


def extract_rtf(path):
    """Texte d'un .rtf (striprtf)."""
    try:
        from striprtf.striprtf import rtf_to_text
    except Exception:
        raise RuntimeError("striprtf n'est pas installé (pip install striprtf).")
    with open(path, encoding="utf-8", errors="replace") as f:
        return (rtf_to_text(f.read()) or "").strip()


def extract_odt(path):
    """Texte d'un .odt (OpenDocument) — zip dont le corps est dans content.xml.
    Pas de dépendance nouvelle : on réutilise BeautifulSoup."""
    import zipfile, warnings
    from bs4 import BeautifulSoup
    try:
        from bs4 import XMLParsedAsHTMLWarning
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    except Exception:
        pass
    with zipfile.ZipFile(path) as z:
        data = z.read("content.xml").decode("utf-8", errors="replace")
    return BeautifulSoup(data, "html.parser").get_text("\n").strip()


def extract_epub(path):
    """Texte d'un .epub — zip de fichiers (X)HTML. Pas de dépendance nouvelle."""
    import zipfile
    from bs4 import BeautifulSoup
    parts = []
    with zipfile.ZipFile(path) as z:
        noms = sorted(n for n in z.namelist()
                      if n.lower().endswith((".xhtml", ".html", ".htm")))
        for n in noms:
            try:
                html = z.read(n).decode("utf-8", errors="replace")
            except Exception:
                continue
            txt = BeautifulSoup(html, "html.parser").get_text("\n").strip()
            if txt:
                parts.append(txt)
    return "\n\n".join(parts).strip()


def extract_html_file(path):
    """Texte principal d'un fichier .html/.htm local (via trafilatura, déjà dépendance)."""
    import trafilatura
    with open(path, encoding="utf-8", errors="replace") as f:
        html = f.read()
    return (trafilatura.extract(html, include_comments=False,
                                include_tables=True, favor_recall=True) or "").strip()


def ocr_mistral(path, api_key, is_image=False):
    """OCR via l'API Mistral (cloud UE). Retourne le texte (markdown).

    Gère les PDF (y compris scannés/images) et les images. Nécessite la clé
    Mistral et le paquet `mistralai`.
    """
    if not api_key:
        raise RuntimeError("Clé API Mistral manquante (à renseigner dans les paramètres).")
    try:
        from mistralai import Mistral
    except Exception:
        raise RuntimeError("mistralai n'est pas installé (pip install mistralai).")
    import os
    client = Mistral(api_key=api_key)
    with open(path, "rb") as f:
        contenu = f.read()
    uploaded = client.files.upload(
        file={"file_name": os.path.basename(path), "content": contenu}, purpose="ocr"
    )
    signed = client.files.get_signed_url(file_id=uploaded.id)
    doc_type = "image_url" if is_image else "document_url"
    document = {"type": doc_type, doc_type: signed.url}
    resp = client.ocr.process(model="mistral-ocr-latest", document=document)
    pages = getattr(resp, "pages", []) or []
    return "\n\n".join((getattr(p, "markdown", "") or "") for p in pages).strip()


def ocr_local(path, is_image=False, lang="fra+eng"):
    """OCR LOCAL via Tesseract — plan B sans clé API, rien ne quitte la machine.

    Nécessite : pytesseract + Pillow (pip), le binaire système `tesseract-ocr`
    (avec la langue `fra`), et pour les PDF `pdf2image` (pip) + `poppler` (système).
    Qualité moindre que Mistral sur les mises en page complexes, mais sans clé.
    """
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        raise RuntimeError("OCR local indisponible : pip install pytesseract pillow.")

    def _img_ocr(img):
        try:
            return pytesseract.image_to_string(img, lang=lang).strip()
        except pytesseract.TesseractNotFoundError:
            raise RuntimeError("Binaire Tesseract introuvable : installe « tesseract-ocr » "
                               "(et la langue fra) sur la machine.")
        except Exception:
            # Langue indisponible (ex. pack fra non installé) → repli sur l'anglais.
            try:
                return pytesseract.image_to_string(img).strip()
            except Exception as e:
                raise RuntimeError("OCR local en échec : " + str(e))

    if is_image:
        return _img_ocr(Image.open(path))
    try:
        from pdf2image import convert_from_path
    except Exception:
        raise RuntimeError("OCR local des PDF indisponible : pip install pdf2image (+ poppler système).")
    pages = convert_from_path(path)
    return "\n\n".join(_img_ocr(p) for p in pages).strip()


def _ocr(path, mistral_key, is_image=False):
    """Choisit l'OCR : Mistral si une clé est dispo (meilleure qualité),
    sinon Tesseract en local (sans clé). Erreur explicite si aucun n'est dispo."""
    if mistral_key:
        return ocr_mistral(path, mistral_key, is_image=is_image)
    try:
        return ocr_local(path, is_image=is_image)
    except RuntimeError as e:
        raise RuntimeError(
            "Aucun OCR disponible. Renseigne une clé API Mistral dans les paramètres, "
            "ou installe l'OCR local (Tesseract). Détail : " + str(e)
        )


def extract_any(path, filename, mistral_key=None, force_ocr=False, allow_cloud=False):
    """Extrait le texte d'un fichier SANS le stocker (contrairement à ingest_file).

    Politique « cloud sur confirmation » : si le document nécessite un OCR et qu'une
    clé Mistral est disponible, l'envoi au cloud n'a lieu que si allow_cloud=True ;
    sinon on renvoie {'status':'confirmation_required', ...}. Sans clé Mistral, l'OCR
    local (Tesseract) est utilisé directement (rien ne quitte la machine).

    Retourne l'un de :
      {'status':'ok', 'text':..., 'method':...}
      {'status':'confirmation_required', 'reason':...}
      {'status':'error', 'message':...}
    """
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()

    def _do_ocr(is_image):
        # OCR requis : appliquer la politique cloud-sur-confirmation.
        if mistral_key and not allow_cloud:
            return ('confirm', None)
        if mistral_key and allow_cloud:
            return ('ok', ocr_mistral(path, mistral_key, is_image=is_image))
        return ('ok', ocr_local(path, is_image=is_image))  # pas de clé -> OCR local

    try:
        if ext == "docx":
            return {'status': 'ok', 'text': extract_docx(path), 'method': 'Word'}
        if ext == "pdf":
            if force_ocr:
                kind, txt = _do_ocr(False)
            else:
                txt = extract_pdf_text(path)
                if len((txt or "").strip()) >= _SEUIL_PDF_IMAGE:
                    return {'status': 'ok', 'text': txt, 'method': 'PDF (texte)'}
                kind, txt = _do_ocr(False)  # PDF scanné -> OCR
            if kind == 'confirm':
                return {'status': 'confirmation_required',
                        'reason': "Ce PDF est scanné (pas de texte sélectionnable). Pour le lire, son image sera envoyée à l'OCR Mistral (cloud)."}
            return {'status': 'ok', 'text': txt, 'method': 'PDF (OCR)'}
        if ext in _EXT_IMAGE:
            kind, txt = _do_ocr(True)
            if kind == 'confirm':
                return {'status': 'confirmation_required',
                        'reason': "Cette image sera envoyée à l'OCR Mistral (cloud) pour en extraire le texte."}
            return {'status': 'ok', 'text': txt, 'method': 'image (OCR)'}
        if ext == "rtf":
            return {'status': 'ok', 'text': extract_rtf(path), 'method': 'RTF'}
        if ext == "odt":
            return {'status': 'ok', 'text': extract_odt(path), 'method': 'ODT'}
        if ext == "epub":
            return {'status': 'ok', 'text': extract_epub(path), 'method': 'EPUB'}
        if ext in ("html", "htm"):
            return {'status': 'ok', 'text': extract_html_file(path), 'method': 'HTML'}
        if ext in _EXT_TEXTE:
            with open(path, encoding="utf-8", errors="replace") as f:
                return {'status': 'ok', 'text': f.read(), 'method': 'texte'}
        return {'status': 'error', 'message': f"Format non pris en charge : .{ext}"}
    except RuntimeError as e:
        return {'status': 'error', 'message': str(e)}
    except Exception as e:
        return {'status': 'error', 'message': f"Impossible de lire ce fichier : {e}"}


def ingest_file(path, filename, mistral_key=None, expiration=None, force_ocr=False):
    """Ingestion d'un fichier vers la zone de référence.

    .docx → texte ; .pdf → texte sélectionnable, sinon OCR Mistral (PDF image) ;
    image → OCR Mistral ; .txt/.md/.csv → lecture directe.
    """
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    try:
        if ext == "docx":
            texte = extract_docx(path)
        elif ext == "pdf":
            if force_ocr:
                texte = _ocr(path, mistral_key, is_image=False)
            else:
                texte = extract_pdf_text(path)
                if len((texte or "").strip()) < _SEUIL_PDF_IMAGE:
                    texte = _ocr(path, mistral_key, is_image=False)  # PDF scanné / image
        elif ext in _EXT_IMAGE:
            texte = _ocr(path, mistral_key, is_image=True)
        elif ext == "rtf":
            texte = extract_rtf(path)
        elif ext == "odt":
            texte = extract_odt(path)
        elif ext == "epub":
            texte = extract_epub(path)
        elif ext in ("html", "htm"):
            texte = extract_html_file(path)
        elif ext in _EXT_TEXTE:
            with open(path, encoding="utf-8", errors="replace") as f:
                texte = f.read()
        else:
            return {"ok": False, "erreur": f"Format non pris en charge : .{ext}"}
    except RuntimeError as e:
        # Messages déjà clairs (clé OCR manquante, dépendance, Tesseract introuvable…).
        return {"ok": False, "erreur": str(e)}
    except Exception as e:
        print(f"[ENRICH] Échec lecture fichier : {e}")
        return {"ok": False, "erreur": "Impossible de lire ce fichier."}
    return ingest_text(filename, texte, source="fichier:" + filename, expiration=expiration)
