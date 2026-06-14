# -*- coding: utf-8 -*-
"""
Test hors-ligne de la bibliothèque de prompts réutilisables.

Vérifie :
  1. save_prompt() sans id génère un identifiant et enregistre label/text/date.
  2. list_prompts() retourne le prompt enregistré.
  3. save_prompt() avec un id existant met à jour label/text sans changer l'id
     ni la date de création.
  4. delete_prompt() retire le prompt de la liste.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.database as db


def setup_module(_module=None):
    tmpdir = tempfile.mkdtemp(prefix="nimm_test_prompts_")
    db.DATA_DIR = tmpdir
    db.set_user_context('test_prompts')
    db.init_db('test_prompts')


def test_save_and_list_prompt():
    entry = db.save_prompt(None, 'Relance client', "Bonjour {{prenom}}, je reviens vers vous au sujet de {{sujet}}.")
    assert entry['label'] == 'Relance client'
    assert '{{prenom}}' in entry['text']
    assert 'id' in entry and entry['id']
    assert 'created_at' in entry

    prompts = db.list_prompts()
    assert entry['id'] in prompts
    assert prompts[entry['id']]['label'] == 'Relance client'
    print("OK  save_prompt + list_prompts")


def test_update_existing_prompt():
    entry = db.save_prompt(None, 'Brouillon', "Texte initial")
    prompt_id = entry['id']
    created_at = entry['created_at']

    updated = db.save_prompt(prompt_id, 'Brouillon modifié', "Texte mis à jour avec {{variable}}")
    assert updated['id'] == prompt_id
    assert updated['label'] == 'Brouillon modifié'
    assert updated['text'] == "Texte mis à jour avec {{variable}}"
    assert updated['created_at'] == created_at

    prompts = db.list_prompts()
    assert prompts[prompt_id]['label'] == 'Brouillon modifié'
    print("OK  save_prompt met à jour un prompt existant")


def test_delete_prompt():
    entry = db.save_prompt(None, 'À supprimer', "Contenu temporaire")
    prompt_id = entry['id']
    assert prompt_id in db.list_prompts()

    db.delete_prompt(prompt_id)
    assert prompt_id not in db.list_prompts()
    print("OK  delete_prompt")


if __name__ == '__main__':
    setup_module()
    test_save_and_list_prompt()
    test_update_existing_prompt()
    test_delete_prompt()
    print("\nTous les tests passent.\n")
