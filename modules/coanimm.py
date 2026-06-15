# -*- coding: utf-8 -*-
"""
CoaNIMM — agent d'exécution pour NIMM.

Exécute les scripts Python enregistrés dans la Promptothèque (type='script') dans un
répertoire de travail dédié et sandboxé (data/coanimm_workspace/), sous contrôle de
permissions explicites — voir core.database.agent_permission_granted :

  - 'once'    : exécute une seule fois sans rien enregistrer ;
  - 'project' : autorise pour le fil de conversation courant (thread_id) ;
  - 'always'  : autorise pour toujours, tous fils confondus.

Si aucune permission n'est accordée et qu'aucun confirm_scope n'est fourni,
run_script() renvoie {'status': 'permission_required', ...} : c'est au frontend de
demander à l'utilisateur, puis de rappeler avec confirm_scope.
"""
import os
import subprocess
import sys
import tempfile

import core.database as db

WORKSPACE_DIRNAME = 'coanimm_workspace'
TIMEOUT_SECONDS = 30


def _workspace_dir(thread_id: str = None) -> str:
    """Répertoire de travail sandboxé pour CoaNIMM, par fil de conversation."""
    base = os.path.join(db.DATA_DIR, WORKSPACE_DIRNAME)
    if thread_id:
        base = os.path.join(base, thread_id)
    os.makedirs(base, exist_ok=True)
    return base


def run_script(script_id: str, args: list = None, thread_id: str = None, confirm_scope: str = None) -> dict:
    """Exécute le script `script_id` de la Promptothèque (type='script').

    Retourne :
      - {'status': 'permission_required', 'action': ..., 'label': ...} si l'accord
        de l'utilisateur est requis et n'a pas encore été donné ;
      - {'status': 'ok', 'stdout':..., 'stderr':..., 'returncode':...} si exécuté ;
      - {'status': 'error', 'message': ...} en cas d'erreur (script introuvable,
        délai dépassé...).
    """
    prompts = db.list_prompts('script')
    entry = prompts.get(script_id)
    if not entry:
        return {'status': 'error', 'message': 'Script introuvable dans la Promptothèque.'}

    action = f'exec_script:{script_id}'

    if confirm_scope in ('project', 'always'):
        db.grant_agent_permission(action, confirm_scope, thread_id)

    if confirm_scope is None and not db.agent_permission_granted(action, thread_id):
        return {
            'status': 'permission_required',
            'action': action,
            'label': entry.get('label', script_id),
        }

    workdir = _workspace_dir(thread_id)
    code = entry.get('text', '')

    fd, script_path = tempfile.mkstemp(suffix='.py', dir=workdir)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(code)
        proc = subprocess.run(
            [sys.executable, script_path, *(args or [])],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        return {
            'status': 'ok',
            'stdout': proc.stdout,
            'stderr': proc.stderr,
            'returncode': proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'message': f'Le script a dépassé le délai de {TIMEOUT_SECONDS} s.'}
    finally:
        try:
            os.remove(script_path)
        except OSError:
            pass
