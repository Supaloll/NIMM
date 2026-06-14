# -*- coding: utf-8 -*-
"""
Test hors-ligne des étiquettes (tags) sur les fils de conversation.

Vérifie :
  1. Un fil nouvellement créé a des tags vides ('').
  2. update_thread_tags() enregistre les étiquettes.
  3. get_thread() et get_threads() reflètent la mise à jour.
  4. update_thread_tags('') vide les étiquettes.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.database as db


def setup_module(_module=None):
    tmpdir = tempfile.mkdtemp(prefix="nimm_test_tags_")
    db.DATA_DIR = tmpdir
    db.set_user_context('test_tags')
    db.init_db('test_tags')


def test_tags_par_defaut_vides():
    db.create_thread('fil_1', 'Premier fil')
    fil = db.get_thread('fil_1')
    assert fil['tags'] == ''


def test_update_thread_tags():
    db.create_thread('fil_2', 'Deuxième fil')
    db.update_thread_tags('fil_2', 'projet, urgent')
    fil = db.get_thread('fil_2')
    assert fil['tags'] == 'projet, urgent'

    # Reflété dans la liste des fils
    fils = db.get_threads()
    fil2 = next(f for f in fils if f['thread_id'] == 'fil_2')
    assert fil2['tags'] == 'projet, urgent'


def test_update_thread_tags_vide():
    db.create_thread('fil_3', 'Troisième fil')
    db.update_thread_tags('fil_3', 'a-supprimer')
    db.update_thread_tags('fil_3', '')
    fil = db.get_thread('fil_3')
    assert fil['tags'] == ''
