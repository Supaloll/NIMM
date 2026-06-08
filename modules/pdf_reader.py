# -*- coding: utf-8 -*-
"""Module PDF — Extraction de texte depuis un fichier PDF."""
import io

def extract_text(data: bytes) -> str:
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(data))
        pages  = [page.extract_text() or '' for page in reader.pages]
        text   = '\n'.join(pages).strip()
        return text if text else '[PDF sans texte extractible]'
    except Exception as e:
        return f'[Erreur extraction PDF : {e}]'