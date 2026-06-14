# -*- coding: utf-8 -*-
"""
Test hors-ligne de l'export de conversation en Markdown.

Vérifie :
  1. export_thread_markdown() renvoie un Markdown contenant le titre,
     les messages utilisateur/assistant avec leurs libellés, et les accents.
  2. Le nom de fichier proposé conserve les accents et retire les caractères
     interdits.
  3. Un thread_id inconnu renvoie une 404.
"""
import os
import sys
import tempfile
import asyncio

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.database as db


def setup_module(_module=None):
    tmpdir = tempfile.mkdtemp(prefix="nimm_test_export_")
    db.DATA_DIR = tmpdir
    db.set_user_context('test_export')
    db.init_db('test_export')


def test_export_markdown_content():
    from main import export_thread_markdown
    from fastapi import HTTPException

    thread_id = 'th-export-1'
    db.create_thread(thread_id, 'Discussion café ☕', 'chat')
    db.add_message(thread_id, 'user', "Bonjour, comment vas-tu ?")
    db.add_message(thread_id, 'assistant', "Très bien, merci ! Et toi ?")

    resp = asyncio.run(export_thread_markdown(thread_id))

    body = resp.body.decode('utf-8')
    assert '# Discussion café ☕' in body
    assert '**Vous** :' in body
    assert '**NIMM** :' in body
    assert 'Bonjour, comment vas-tu ?' in body
    assert 'Très bien, merci ! Et toi ?' in body
    assert resp.media_type.startswith('text/markdown')

    disposition = resp.headers['content-disposition']
    assert 'attachment' in disposition
    assert 'Discussion café' in disposition  # accents conservés
    assert '☕' not in disposition           # caractères non-filename retirés


def test_export_unknown_thread_404():
    from main import export_thread_markdown
    from fastapi import HTTPException

    try:
        asyncio.run(export_thread_markdown('inconnu'))
        assert False, "404 attendue"
    except HTTPException as e:
        assert e.status_code == 404
