# -*- coding: utf-8 -*-
"""
Test hors-ligne du moteur d'exécution CoaNIMM (modules/coanimm.py).

Vérifie :
  1. Sans permission, run_script() renvoie 'permission_required'.
  2. confirm_scope='once' exécute sans rien persister (nouvelle demande au tour
     suivant => de nouveau 'permission_required').
  3. confirm_scope='project' exécute et persiste pour ce thread_id uniquement.
  4. confirm_scope='always' exécute et persiste pour tous les fils.
  5. Un script introuvable renvoie 'error'.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.database as db
import modules.coanimm as coanimm


def setup_module(_module=None):
    tmpdir = tempfile.mkdtemp(prefix="nimm_test_coanimm_")
    db.DATA_DIR = tmpdir
    db.set_user_context('test_coanimm')
    db.init_db('test_coanimm')


SCRIPT_CODE = "print('bonjour depuis coanimm')"


def _save_script():
    entry = db.save_prompt(None, 'Mon script', SCRIPT_CODE, type='script')
    return entry['id']


def test_permission_required_sans_accord():
    script_id = _save_script()
    result = coanimm.run_script(script_id, thread_id='fil_1')
    assert result['status'] == 'permission_required'
    assert result['action'] == f'exec_script:{script_id}'
    print("OK  permission_required sans accord préalable")


def test_confirm_once_ne_persiste_pas():
    script_id = _save_script()
    result = coanimm.run_script(script_id, thread_id='fil_1', confirm_scope='once')
    assert result['status'] == 'ok'
    assert 'bonjour depuis coanimm' in result['stdout']
    assert result['returncode'] == 0

    # Pas persisté : un nouvel appel sans confirm_scope redemande l'accord.
    result2 = coanimm.run_script(script_id, thread_id='fil_1')
    assert result2['status'] == 'permission_required'
    print("OK  confirm_scope='once' exécute sans persister")


def test_confirm_project_persiste_pour_ce_fil():
    script_id = _save_script()
    result = coanimm.run_script(script_id, thread_id='fil_2', confirm_scope='project')
    assert result['status'] == 'ok'

    # Accordé pour ce fil : plus besoin de demander.
    result2 = coanimm.run_script(script_id, thread_id='fil_2')
    assert result2['status'] == 'ok'

    # Mais pas pour un autre fil.
    result3 = coanimm.run_script(script_id, thread_id='fil_3')
    assert result3['status'] == 'permission_required'
    print("OK  confirm_scope='project' limité au fil concerné")


def test_confirm_always_persiste_partout():
    script_id = _save_script()
    result = coanimm.run_script(script_id, thread_id='fil_4', confirm_scope='always')
    assert result['status'] == 'ok'

    # Accordé pour tous les fils, y compris sans thread_id.
    result2 = coanimm.run_script(script_id, thread_id='fil_5')
    assert result2['status'] == 'ok'
    result3 = coanimm.run_script(script_id)
    assert result3['status'] == 'ok'
    print("OK  confirm_scope='always' s'applique à tous les fils")


def test_script_introuvable():
    result = coanimm.run_script('id_inexistant', confirm_scope='once')
    assert result['status'] == 'error'
    print("OK  script introuvable => erreur explicite")


if __name__ == '__main__':
    setup_module()
    test_permission_required_sans_accord()
    test_confirm_once_ne_persiste_pas()
    test_confirm_project_persiste_pour_ce_fil()
    test_confirm_always_persiste_partout()
    test_script_introuvable()
    print("\nTous les tests passent.\n")
