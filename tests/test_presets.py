# -*- coding: utf-8 -*-
"""
Test hors-ligne des préréglages (presets) de configuration.

Vérifie :
  1. save_preset() capture les clés PRESET_KEYS courantes.
  2. list_presets() retourne le preset enregistré.
  3. apply_preset() réapplique la config (y compris après modification).
  4. apply_preset() sur un nom inconnu retourne None.
  5. delete_preset() retire le preset de la liste.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.database as db


def setup_module(_module=None):
    # DB temporaire isolée pour ne pas toucher aux vraies données.
    tmpdir = tempfile.mkdtemp(prefix="nimm_test_presets_")
    db.DATA_DIR = tmpdir
    db.set_user_context('test_presets')
    db.init_db('test_presets')


def test_save_and_list_preset():
    db.set_setting('provider', 'mistral')
    db.set_setting('chat_model', 'mistral-small-latest')
    db.set_setting('local_mode', 'false')
    db.set_setting('mask_id', 'lia')

    config = db.save_preset('Confidentiel')
    assert config['provider'] == 'mistral'
    assert config['chat_model'] == 'mistral-small-latest'
    assert config['mask_id'] == 'lia'

    presets = db.list_presets()
    assert 'Confidentiel' in presets
    assert presets['Confidentiel']['config']['provider'] == 'mistral'
    assert 'created_at' in presets['Confidentiel']
    print("OK  save_preset + list_presets")


def test_apply_preset_restores_config():
    # On change les réglages...
    db.set_setting('provider', 'anthropic')
    db.set_setting('chat_model', 'claude-x')

    # ... puis on réapplique le preset enregistré.
    config = db.apply_preset('Confidentiel')
    assert config['provider'] == 'mistral'
    assert db.get_setting('provider') == 'mistral'
    assert db.get_setting('chat_model') == 'mistral-small-latest'
    print("OK  apply_preset restaure les réglages")


def test_apply_preset_inconnu():
    assert db.apply_preset('Inexistant') is None
    print("OK  apply_preset(inconnu) -> None")


def test_delete_preset():
    db.delete_preset('Confidentiel')
    assert 'Confidentiel' not in db.list_presets()
    print("OK  delete_preset")


if __name__ == '__main__':
    setup_module()
    test_save_and_list_preset()
    test_apply_preset_restores_config()
    test_apply_preset_inconnu()
    test_delete_preset()
    print("\nTous les tests passent.\n")
