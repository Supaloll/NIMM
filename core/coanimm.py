# -*- coding: utf-8 -*-
"""
CoaNIMM — agent d'exécution pour NIMM.

Exécute des scripts Python dans un répertoire de travail dédié et sandboxé
(data/coanimm_workspace/), sous contrôle de permissions explicites — voir
core.database.agent_permission_granted :

  - 'once'    : exécute une seule fois sans rien enregistrer ;
  - 'project' : autorise pour le fil de conversation courant (thread_id) ;
  - 'always'  : autorise pour toujours, tous fils confondus.

Si aucune permission n'est accordée et qu'aucun confirm_scope n'est fourni, les
fonctions ci-dessous renvoient {'status': 'permission_required', ...} : c'est au
frontend de demander à l'utilisateur, puis de rappeler avec confirm_scope.

Deux modes :
  - run_script()    : exécute un script enregistré dans la Promptothèque (type='script').
  - run_generated() : génère un script Python à partir d'une consigne en langage
                       naturel (via le LLM configuré), puis l'exécute.
"""
import os
import re
import subprocess
import sys
import tempfile

import core.database as db

WORKSPACE_DIRNAME = 'coanimm_workspace'
TIMEOUT_SECONDS = 30

# Extensions reconnues pour le routage automatique des fichiers générés
_IMAGE_EXTS  = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
_TEXT_EXTS   = {'.txt', '.md', '.csv', '.json', '.html', '.xml', '.log'}
_MAX_TEXT_INLINE = 4000   # chars max injectés dans le résultat outil

GENERATED_ACTION = 'exec_generated_code'

GENERATE_SYSTEM_PROMPT = (
    "Tu es CoaNIMM, l'agent d'exécution de NIMM, un assistant personnel local-first.\n"
    "À partir d'une consigne en langage naturel, génère un script Python autonome qui "
    "réalise cette tâche.\n"
    "Réponds UNIQUEMENT avec le code Python, sans balises markdown (```), sans "
    "explication avant ou après.\n"
    "Le script s'exécute dans un répertoire de travail isolé et dédié à cette tâche : "
    "n'utilise que la bibliothèque standard et les modules déjà installés, et écris "
    "tes éventuels fichiers de sortie dans le répertoire courant."
)


def _sanitize_dirname(name: str) -> str:
    """Nettoie un nom de fil pour en faire un nom de dossier valide (Windows compris)."""
    name = (name or '').strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = name.strip(' .')
    return name[:60] or 'sans_titre'


def _workspace_dir(thread_id: str = None) -> str:
    """Répertoire de travail sandboxé pour CoaNIMM, par fil de conversation.

    Le dossier reprend le nom du fil (plus lisible qu'un identifiant opaque),
    suffixé par les 8 premiers caractères de son identifiant pour éviter toute
    collision entre fils de même nom.
    """
    base = os.path.join(db.DATA_DIR, WORKSPACE_DIRNAME)
    if thread_id:
        thread = db.get_thread(thread_id)
        name = thread.get('name') if thread else None
        folder = f"{_sanitize_dirname(name)}_{thread_id[:8]}" if name else thread_id
        base = os.path.join(base, folder)
    os.makedirs(base, exist_ok=True)
    return base


def _strip_code_fences(text: str) -> str:
    """Retire d'éventuelles balises ```python ... ``` autour du code généré."""
    text = (text or '').strip()
    if text.startswith('```'):
        lines = text.splitlines()
        if lines and lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith('```'):
            lines = lines[:-1]
        text = '\n'.join(lines)
    return text.strip()


def _execute(code: str, args: list, workdir: str) -> dict:
    """Écrit `code` dans un fichier temporaire de `workdir` et l'exécute.

    Retourne {'status':'ok', 'stdout':..., 'stderr':..., 'returncode':...} ou
    {'status':'error', 'message':...} en cas de délai dépassé.
    """
    fd, script_path = tempfile.mkstemp(suffix='.py', dir=workdir)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(code)
        # Sous Windows, le sous-processus hérite d'un stdout/stderr en cp1252
        # ("charmap") par défaut : tout print() contenant un emoji (ex: 📁) y
        # provoque un UnicodeEncodeError. On force l'UTF-8 pour le script généré,
        # avec remplacement plutôt que crash pour la capture si besoin.
        env = dict(os.environ)
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'
        proc = subprocess.run(
            [sys.executable, script_path, *(args or [])],
            cwd=workdir,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env,
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
    return _execute(entry.get('text', ''), args, workdir)


async def generate_code(consigne: str, thread_id: str = None) -> str:
    """Demande au LLM configuré (cf. core.hub.load_settings) de générer un script
    Python à partir d'une consigne en langage naturel. Renvoie le code, sans balises
    markdown."""
    import core.engine as engine
    import core.hub as hub

    settings = hub.load_settings(thread_id)
    provider, model = hub.get_task_provider_model('coanimm', settings)
    response = await engine.call_llm(
        messages=[{'role': 'user', 'content': consigne}],
        provider=provider,
        model=model,
        system_prompt=GENERATE_SYSTEM_PROMPT,
        max_tokens=1024,
        temperature=0.2,
        api_keys=settings['api_keys'],
    )
    return _strip_code_fences(response)


def _scan_new_files(workdir: str, before: set) -> list:
    """Retourne la liste des fichiers créés dans workdir depuis le snapshot `before`."""
    try:
        after = set(os.listdir(workdir))
    except OSError:
        return []
    new = after - before
    results = []
    for fname in sorted(new):
        # Ignorer les scripts temporaires (.py) générés par _execute
        if fname.endswith('.py'):
            continue
        ext = os.path.splitext(fname)[1].lower()
        fpath = os.path.join(workdir, fname)
        results.append({'filename': fname, 'path': fpath, 'ext': ext})
    return results


def _route_new_files(new_files: list, thread_id: str = None) -> str:
    """Route les fichiers générés :
      - Images → galerie NIMM (save_image en DB)
      - Texte/CSV (≤ _MAX_TEXT_INLINE chars) → retourné inline
    Retourne un bloc texte à injecter dans le résultat de l'outil, ou '' si rien."""
    if not new_files:
        return ''
    lines = []
    for f in new_files:
        fname = f['filename']
        ext   = f['ext']
        fpath = f['path']
        if ext in _IMAGE_EXTS:
            try:
                db.save_image(fname, prompt=f'[CoaNIMM] {fname}', thread_id=thread_id or '')
                lines.append(f"🖼️ Image générée et ajoutée à la galerie : {fname}")
            except Exception as e:
                lines.append(f"⚠️ Image générée ({fname}) mais non sauvegardée en galerie : {e}")
        elif ext in _TEXT_EXTS:
            try:
                size = os.path.getsize(fpath)
                if size == 0:
                    lines.append(f"📄 Fichier généré (vide) : {fname}")
                elif size <= _MAX_TEXT_INLINE:
                    with open(fpath, encoding='utf-8', errors='replace') as fh:
                        content = fh.read()
                    lines.append(f"📄 Fichier généré : {fname}\n```\n{content}\n```")
                else:
                    lines.append(f"📄 Fichier généré (trop volumineux pour affichage inline, {size} octets) : {fname}")
            except Exception as e:
                lines.append(f"📄 Fichier généré ({fname}) — lecture impossible : {e}")
        else:
            lines.append(f"📎 Fichier généré : {fname}")
    return '\n'.join(lines)


def execute_code(code: str, thread_id: str = None) -> dict:
    """Exécute du code Python généré par le LLM (via tool calling).

    Capture automatiquement les fichiers créés dans le workspace :
    - Images → galerie NIMM
    - Texte/CSV → retournés inline dans le résultat

    Retourne {'status':'ok'|'error', 'stdout':..., 'stderr':..., 'files_info':..., ...}
    """
    workdir = _workspace_dir(thread_id)
    before  = set(os.listdir(workdir)) if os.path.isdir(workdir) else set()
    result  = _execute(code, None, workdir)
    new_files = _scan_new_files(workdir, before)
    result['files_info'] = _route_new_files(new_files, thread_id)
    result['files_count'] = len(new_files)
    return result


async def run_generated(consigne: str, thread_id: str = None, confirm_scope: str = None) -> dict:
    """Génère un script Python à partir de `consigne` puis l'exécute.

    Retourne :
      - {'status': 'permission_required', 'action': ..., 'label': ...} si l'accord
        de l'utilisateur est requis et n'a pas encore été donné ;
      - {'status': 'ok', 'stdout':..., 'stderr':..., 'returncode':..., 'code':...}
        si exécuté (le code généré est renvoyé pour transparence) ;
      - {'status': 'error', 'message': ...} en cas d'erreur (consigne vide,
        génération impossible, délai dépassé...).
    """
    if not consigne or not consigne.strip():
        return {'status': 'error', 'message': 'La consigne est vide.'}

    action = GENERATED_ACTION

    if confirm_scope in ('project', 'always'):
        db.grant_agent_permission(action, confirm_scope, thread_id)

    if confirm_scope is None and not db.agent_permission_granted(action, thread_id):
        return {
            'status': 'permission_required',
            'action': action,
            'label': "Génération et exécution d'un script à partir d'une consigne libre",
        }

    try:
        code = await generate_code(consigne, thread_id)
    except Exception as e:
        return {'status': 'error', 'message': f"Erreur lors de la génération du code : {e}"}

    if not code.strip():
        return {'status': 'error', 'message': "Le modèle n'a renvoyé aucun code."}

    workdir = _workspace_dir(thread_id)
    result = _execute(code, None, workdir)
    result['code'] = code
    return result
