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

Flux Plan→Explore→Execute :
  1. generate_plan()     : LLM décrit le plan + indique si exploration disque nécessaire
  2. explore_directory() : script lecture-seule pour informer le plan (si needs_explore)
  3. run_generated()     : génère et exécute le script final
"""
import os
import re
import subprocess
import sys
import tempfile

import core.database as db

WORKSPACE_DIRNAME = 'coanimm_workspace'
TIMEOUT_SECONDS = 180

# Extensions reconnues pour le routage automatique des fichiers générés
_IMAGE_EXTS  = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
_TEXT_EXTS   = {'.txt', '.md', '.csv', '.json', '.html', '.xml', '.log'}
_MAX_TEXT_INLINE = 4000   # chars max injectés dans le résultat outil

GENERATED_ACTION = 'exec_generated_code'
EXPLORE_ACTION   = 'explorer_disque'

PLANNING_SYSTEM_PROMPT = (
    "Tu es CoaNIMM, l'agent d'exécution de NIMM.\n"
    "L'utilisateur va te confier une tâche à automatiser. "
    "Ta réponse doit être UN TEXTE BRUT UNIQUEMENT, lisible tel quel par un utilisateur aveugle "
    "sur une plage braille. Aucune mise en forme, aucune balise, aucun symbole de formatage.\n\n"
    "INTERDICTIONS ABSOLUES dans ta réponse :\n"
    "- Pas d'astérisques, pas de gras (**texte**), pas d'italique (*texte*)\n"
    "- Pas de titres markdown (## ou ###)\n"
    "- Pas de backticks, pas de blocs de code (``` ou `code`)\n"
    "- Pas de tirets de liste (- item) ni de puces\n"
    "- Pas de PowerShell, pas de Python, pas de commandes\n"
    "- Pas de HTML\n\n"
    "FORMAT OBLIGATOIRE de ta réponse (deux blocs séparés par une ligne vide) :\n\n"
    "Bloc 1 — une seule ligne, exactement :\n"
    "  EXPLORER: oui   si la tâche nécessite de lire des dossiers ou fichiers sur le disque.\n"
    "  EXPLORER: non   si la tâche peut être planifiée sans accès disque.\n\n"
    "Bloc 2 — le plan en texte brut, 3 à 8 phrases numérotées (1. 2. 3. ...), en français. "
    "Chaque phrase décrit une étape concrète. Pas de sous-points. Pas de récapitulatif final. "
    "Arrête-toi dès que le plan est complet."
)

EXPLORE_SYSTEM_PROMPT = (
    "Tu es CoaNIMM en mode exploration (lecture seule).\n"
    "Génère un script Python qui explore le système de fichiers et affiche ce qu'il trouve. "
    "LECTURE SEULE UNIQUEMENT — les instructions suivantes sont absolument interdites : "
    "shutil.move, shutil.copy, shutil.copytree, shutil.rmtree, os.rename, os.replace, "
    "os.remove, os.unlink, os.makedirs, os.mkdir, open(..., 'w'), open(..., 'a'), "
    "open(..., 'wb'), open(..., 'ab').\n"
    "Règles habituelles : pas de triple-guillemets, pas de input(), pas de sys.stdin. "
    "Affiche un rapport clair et lisible avec print()."
)

GENERATE_SYSTEM_PROMPT = (
    "Tu es CoaNIMM, l'agent d'exécution de NIMM, un assistant personnel local-first.\n"
    "A partir d'une consigne en langage naturel, génère un script Python autonome qui "
    "réalise cette tâche.\n"
    "Réponds UNIQUEMENT avec le code Python, sans balises markdown (```), sans "
    "explication avant ou après.\n"
    "RÈGLES IMPÉRATIVES :\n"
    "1. N'utilise jamais de triple-guillemets (\"\"\" ou ''') — ni pour les docstrings, "
    "ni pour les chaînes multilignes. Utilise des commentaires # à la place.\n"
    "2. N'utilise JAMAIS input() ni sys.stdin : le script s'exécute sans terminal interactif. Si tu as besoin d'une réponse de l'utilisateur, utilise le protocole __NIMM_DEMANDE__ (règle 3).\n"
    "3. INTERACTION UTILISATEUR : si la tâche nécessite une validation ou un choix (ex : confirmer un plan avant des opérations irréversibles), le script doit :\n"
    "   a) Afficher le plan/analyse complet avec print()\n"
    "   b) Terminer par exactement ces deux lignes :\n"
    "      print('__NIMM_DEMANDE__: ta question ici')\n"
    "      import sys; sys.exit(0)\n"
    "   CoaNIMM détectera ce marqueur, montrera un champ de saisie à l'utilisateur, et relancera génération + exécution avec la réponse et tout le contexte précédent. Pour les tâches sans risque, exécute directement sans demander.\n"
    "4. Affiche chaque action avec print() au fur et à mesure (ex : 'Déplacé : ancien -> nouveau').\n"
    "Le script s'exécute dans un processus isolé.\n"
    "BIBLIOTHÈQUES DISPONIBLES : bibliothèque standard Python + reportlab (PDF), "
    "PIL/Pillow (images), pandas, openpyxl.\n"
    "HELPER INJECTÉ (disponible sans import) :\n"
    "  nimm_generate_image(prompt: str) -> str\n"
    "  Génère une image IA à partir du prompt et retourne le chemin absolu du fichier PNG "
    "dans le répertoire de travail courant. Exemple d'intégration PDF :\n"
    "    from reportlab.pdfgen import canvas\n"
    "    c = canvas.Canvas('rapport.pdf')\n"
    "    img_path = nimm_generate_image('une illustration de ...')\n"
    "    c.drawImage(img_path, 50, 600, width=200, height=150)\n"
    "    c.drawString(50, 580, 'Mon titre')\n"
    "    c.save()\n"
    "N'importe pas nimm_generate_image : elle est déjà présente dans l'environnement."
)


def _sanitize_dirname(name: str) -> str:
    """Nettoie un nom de fil pour en faire un nom de dossier valide (Windows compris)."""
    name = (name or '').strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = name.strip(' .')
    return name[:60] or 'sans_titre'


def _workspace_dir(thread_id: str = None) -> str:
    """Répertoire de travail sandboxé pour CoaNIMM, par fil de conversation."""
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


def _check_syntax(code: str):
    """Vérifie la syntaxe du code avant exécution. Retourne un message d'erreur ou None."""
    try:
        compile(code, '<generated>', 'exec')
        return None
    except SyntaxError as e:
        return f"Erreur de syntaxe ligne {e.lineno} : {e.msg}"


def _analyze_code_risks(code: str) -> list:
    """Analyse statique AST du code généré.
    Retourne une liste de {'level': 'warning'|'danger', 'message': str}.
    """
    import ast as _ast
    risks = []
    try:
        tree = _ast.parse(code)
    except SyntaxError:
        return risks

    DANGER_IMPORTS = {
        'ctypes':        "utilise des fonctions système de très bas niveau (inhabituel)",
        'winreg':        "peut lire ou modifier les paramètres système de Windows",
        'win32api':      "accède directement à l'API Windows (inhabituel)",
        'win32security': "peut modifier des paramètres de sécurité Windows",
    }
    WARN_IMPORTS = {
        'subprocess': "peut lancer d'autres programmes sur votre ordinateur",
        'socket':     "peut ouvrir des connexions réseau",
        'smtplib':    "peut envoyer des e-mails",
        'ftplib':     "peut se connecter à un serveur distant",
        'paramiko':   "peut se connecter à un serveur via SSH",
    }
    DANGER_CALLS = {
        ('os', 'system'): "lance une commande directement dans le terminal",
        ('os', 'popen'):  "lance une commande directement dans le terminal",
    }
    WARN_CALLS = {
        ('shutil', 'rmtree'): "peut supprimer un dossier entier et tout son contenu",
        ('os', 'remove'):     "peut supprimer des fichiers de votre ordinateur",
        ('os', 'unlink'):     "peut supprimer des fichiers de votre ordinateur",
        ('os', 'rmdir'):      "peut supprimer des dossiers",
    }

    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Import, _ast.ImportFrom)):
            names = ([node.module] if isinstance(node, _ast.ImportFrom)
                     else [a.name for a in node.names])
            for name in (names or []):
                if not name:
                    continue
                root = name.split('.')[0]
                if root in DANGER_IMPORTS:
                    risks.append({'level': 'danger',
                                  'message': DANGER_IMPORTS[root]})
                elif root in WARN_IMPORTS:
                    risks.append({'level': 'warning',
                                  'message': WARN_IMPORTS[root]})
        elif isinstance(node, _ast.Call):
            if isinstance(node.func, _ast.Name) and node.func.id in ('eval', 'exec'):
                risks.append({'level': 'danger',
                              'message': "exécute du code dont le contenu n'est connu qu'à l'exécution (risque élevé)"})
            elif isinstance(node.func, _ast.Attribute):
                obj = (node.func.value.id
                       if isinstance(node.func.value, _ast.Name) else None)
                key = (obj, node.func.attr)
                if key in DANGER_CALLS:
                    risks.append({'level': 'danger',
                                  'message': DANGER_CALLS[key]})
                elif key in WARN_CALLS:
                    risks.append({'level': 'warning',
                                  'message': WARN_CALLS[key]})

    seen, unique = set(), []
    for r in risks:
        k = (r['level'], r['message'])
        if k not in seen:
            seen.add(k); unique.append(r)
    return unique


def _build_prologue(thread_id: str, workdir: str) -> str:
    """Construit le code Python injecté en tête de chaque script CoaNIMM.

    Définit nimm_generate_image(prompt) qui appelle l'endpoint local
    /api/coanimm/generate_image et retourne le chemin du PNG produit.
    """
    tid = (thread_id or '').replace("'", "")
    return (
        "import urllib.request as _nimm_ur, json as _nimm_json\n"
        "def nimm_generate_image(prompt, _tid='" + tid + "'):\n"
        "    _data = _nimm_json.dumps({\"prompt\": prompt, \"thread_id\": _tid}).encode()\n"
        "    _req = _nimm_ur.Request(\n"
        "        \"http://localhost:8080/api/coanimm/generate_image\",\n"
        "        data=_data, headers={\"Content-Type\": \"application/json\"})\n"
        "    with _nimm_ur.urlopen(_req, timeout=120) as _r:\n"
        "        _res = _nimm_json.loads(_r.read())\n"
        "    if _res.get(\"status\") != \"ok\":\n"
        "        raise RuntimeError(\"nimm_generate_image : \" + _res.get(\"message\", \"?\"))\n"
        "    print(\"Image g\xc3\xa9n\xc3\xa9r\xc3\xa9e :\" + _res[\"filepath\"])\n"
        "    return _res[\"filepath\"]\n"
    )


def _execute(code: str, args: list, workdir: str, thread_id: str = None) -> dict:
    """Écrit `code` dans un fichier temporaire de `workdir` et l'exécute.

    Retourne {'status':'ok', 'stdout':..., 'stderr':..., 'returncode':...} ou
    {'status':'error', 'message':...} en cas d'erreur de syntaxe ou délai dépassé.
    """
    syntax_err = _check_syntax(code)
    if syntax_err:
        return {'status': 'error', 'message': syntax_err,
                'stdout': '', 'stderr': '', 'returncode': 1}

    # Prologue injectant les helpers CoaNIMM (nimm_generate_image, ...)
    prologue = _build_prologue(thread_id, workdir)
    full_code = prologue + '\n' + code if prologue else code
    fd, script_path = tempfile.mkstemp(suffix='.py', dir=workdir)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(full_code)
        env = dict(os.environ)
        env['PYTHONIOENCODING'] = 'utf-8:replace'
        env['PYTHONUTF8'] = '1'
        try:
            proc = subprocess.run(
                [sys.executable, script_path, *(args or [])],
                cwd=workdir,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=TIMEOUT_SECONDS,
                env=env,
            )
            return {
                'status': 'ok',
                'stdout': proc.stdout,
                'stderr': proc.stderr,
                'returncode': proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                'status': 'error',
                'message': f"Délai dépassé ({TIMEOUT_SECONDS}s). Le script a été interrompu.",
                'stdout': '', 'stderr': '', 'returncode': -1,
            }
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def run_script(script_id: str, args: list = None, thread_id: str = None,
               confirm_scope: str = None) -> dict:
    """Exécute un script enregistré dans la Promptothèque (type='script').

    Retourne 'permission_required' si l'utilisateur doit d'abord accorder
    l'exécution (once / project / always).
    """
    action = f"run_script:{script_id}"

    if confirm_scope in ('project', 'always'):
        db.grant_agent_permission(action, confirm_scope, thread_id)

    if confirm_scope is None and not db.agent_permission_granted(action, thread_id):
        prompt_entry = db.get_prompt(script_id)
        label = (prompt_entry or {}).get('label', script_id)
        return {
            'status': 'permission_required',
            'action': action,
            'label': label,
        }

    prompt_entry = db.get_prompt(script_id)
    if not prompt_entry:
        return {'status': 'error', 'message': f"Script introuvable : {script_id}"}

    code = prompt_entry.get('content', '')
    if not code.strip():
        return {'status': 'error', 'message': "Le script est vide."}

    workdir = _workspace_dir(thread_id)
    result = _execute(code, args, workdir)
    result['script_id'] = script_id
    return result


async def generate_code(consigne: str, thread_id: str = None,
                         provider_override: str = None) -> str:
    """Demande au LLM de générer un script Python à partir d'une consigne."""
    import core.engine as engine
    import core.hub as hub

    settings = hub.load_settings(thread_id)
    provider, model = hub.get_task_provider_model('coanimm', settings)
    if provider_override:
        provider, model = provider_override, None
    response = await engine.call_llm(
        messages=[{'role': 'user', 'content': consigne}],
        provider=provider,
        model=model,
        system_prompt=GENERATE_SYSTEM_PROMPT,
        max_tokens=16000,
        temperature=0.2,
        api_keys=settings['api_keys'],
    )
    return _strip_code_fences(response)


async def generate_plan(consigne: str, thread_id: str = None,
                         provider_override: str = None) -> dict:
    """Demande au LLM de décrire ce qu'il va faire (sans coder).
    Retourne {'plan': str, 'needs_explore': bool}."""
    import core.engine as engine
    import core.hub as hub

    settings = hub.load_settings(thread_id)
    provider, model = hub.get_task_provider_model('coanimm', settings)
    if provider_override:
        provider, model = provider_override, None
    raw = await engine.call_llm(
        messages=[{'role': 'user', 'content': consigne}],
        provider=provider,
        model=model,
        system_prompt=PLANNING_SYSTEM_PROMPT,
        max_tokens=800,
        temperature=0.3,
        api_keys=settings['api_keys'],
    )
    # Parser la ligne EXPLORER: oui/non
    needs_explore = False
    lines = (raw or '').strip().splitlines()
    plan_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower().startswith('explorer:'):
            needs_explore = 'oui' in stripped.lower()
        else:
            plan_lines.extend(lines[i:])
            break
    return {'plan': '\n'.join(plan_lines).strip(), 'needs_explore': needs_explore}


async def explore_directory(consigne: str, thread_id: str = None,
                            confirm_scope: str = None) -> dict:
    """Génère et exécute un script d'exploration (lecture seule).
    Retourne le même format que run_generated."""
    action = GENERATED_ACTION  # permission unifiée avec l'exécution

    if confirm_scope in ('project', 'always'):
        db.grant_agent_permission(action, confirm_scope, thread_id)

    if confirm_scope is None and not db.agent_permission_granted(action, thread_id):
        return {
            'status': 'permission_required',
            'action': action,
            'label': "Explorer le disque en lecture seule",
        }

    import core.engine as engine
    import core.hub as hub

    settings = hub.load_settings(thread_id)
    provider, model = hub.get_task_provider_model('coanimm', settings)
    try:
        raw = await engine.call_llm(
            messages=[{'role': 'user', 'content': consigne}],
            provider=provider,
            model=model,
            system_prompt=EXPLORE_SYSTEM_PROMPT,
            max_tokens=16000,
            temperature=0.2,
            api_keys=settings['api_keys'],
        )
    except Exception as e:
        detail = str(e) or type(e).__name__
        return {'status': 'error',
                'message': f"Erreur lors de la génération de l'exploration : {detail}"}

    code = _strip_code_fences(raw)
    if not code.strip():
        return {'status': 'error',
                'message': "Le modèle n'a renvoyé aucun code d'exploration."}

    syntax_err = _check_syntax(code)
    if syntax_err:
        return {'status': 'error',
                'message': f"Code d'exploration invalide : {syntax_err}", 'code': code}

    workdir = _workspace_dir(thread_id)
    result = _execute(code, None, workdir, thread_id)
    result['code'] = code
    return result


def _scan_new_files(workdir: str, before: set) -> list:
    """Retourne la liste des fichiers créés dans workdir depuis le snapshot `before`."""
    try:
        after = set(os.listdir(workdir))
    except OSError:
        return []
    new = after - before
    results = []
    for fname in sorted(new):
        if fname.endswith('.py'):
            continue
        ext = os.path.splitext(fname)[1].lower()
        fpath = os.path.join(workdir, fname)
        results.append({'filename': fname, 'path': fpath, 'ext': ext})
    return results


def _route_new_files(new_files: list, thread_id: str = None) -> tuple:
    """Route les fichiers générés vers galerie ou inline.

    Retourne (info_text: str, files_list: list).
    files_list contient des dicts {filename, ext, size, url, type} pour le frontend.
    """
    if not new_files:
        return '', []
    lines = []
    files_list = []
    for f in new_files:
        fname = f['filename']
        ext   = f['ext']
        fpath = f['path']
        try:
            size = os.path.getsize(fpath)
        except OSError:
            size = 0
        tid_param = f'?thread_id={thread_id}' if thread_id else ''
        url = f'/api/coanimm/files/{fname}{tid_param}'
        if ext in _IMAGE_EXTS:
            try:
                db.save_image(fname, prompt=f'[CoaNIMM] {fname}', thread_id=thread_id or '')
                lines.append(f"Image générée et ajoutée à la galerie : {fname}")
            except Exception as e:
                lines.append(f"Image générée ({fname}) mais non sauvegardée en galerie : {e}")
            files_list.append({'filename': fname, 'ext': ext, 'size': size,
                                'url': url, 'type': 'image'})
        elif ext in _TEXT_EXTS:
            try:
                if size == 0:
                    lines.append(f"Fichier généré (vide) : {fname}")
                elif size <= _MAX_TEXT_INLINE:
                    with open(fpath, encoding='utf-8', errors='replace') as fh:
                        text_content = fh.read()
                    lines.append(f"Fichier généré : {fname}\n```\n{text_content}\n```")
                else:
                    lines.append(
                        f"Fichier généré (trop volumineux pour affichage inline, "
                        f"{size} octets) : {fname}")
            except Exception as e:
                lines.append(f"Fichier généré ({fname}) — lecture impossible : {e}")
            files_list.append({'filename': fname, 'ext': ext, 'size': size,
                                'url': url, 'type': 'text'})
        else:
            lines.append(f"Fichier généré : {fname} ({size} octets)")
            files_list.append({'filename': fname, 'ext': ext, 'size': size,
                                'url': url, 'type': 'binary'})
    return '\n'.join(lines), files_list


def execute_code(code: str, thread_id: str = None) -> dict:
    """Exécute du code Python généré par le LLM (via tool calling)."""
    workdir = _workspace_dir(thread_id)
    before  = set(os.listdir(workdir)) if os.path.isdir(workdir) else set()
    result  = _execute(code, None, workdir, thread_id)
    new_files = _scan_new_files(workdir, before)
    result['files_info'], result['files_list'] = _route_new_files(new_files, thread_id)
    result['files_count'] = len(new_files)
    return result


async def run_generated(consigne: str, thread_id: str = None,
                        confirm_scope: str = None) -> dict:
    """Génère un script Python à partir de `consigne` puis l'exécute.

    Gère automatiquement la permission exec_generated_code et relance
    une fois si le code généré est syntaxiquement invalide (tronqué).
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
        detail = str(e) or type(e).__name__
        print(f"[COANIMM] Erreur génération : {type(e).__name__}: {e}")
        return {'status': 'error',
                'message': f"Erreur lors de la génération du code : {detail}"}

    if not code.strip():
        return {'status': 'error', 'message': "Le modèle n'a renvoyé aucun code."}

    # Retry si syntaxe invalide (code tronqué par max_tokens)
    syntax_err = _check_syntax(code)
    if syntax_err:
        print(f"[COANIMM] Code tronqué ({syntax_err}), nouvelle tentative plus concise...")
        try:
            retry_consigne = (
                consigne
                + "\n\n[IMPORTANT : ton script précédent était trop long et a été coupé. "
                "Réécris-le de façon plus concise, en éliminant les fonctions secondaires "
                "et les affichages détaillés. L'essentiel suffit.]"
            )
            code = await generate_code(retry_consigne, thread_id)
        except Exception as e:
            detail = str(e) or type(e).__name__
            print(f"[COANIMM] Erreur regénération : {type(e).__name__}: {e}")
            return {'status': 'error',
                    'message': f"Erreur lors de la regénération : {detail}"}
        syntax_err2 = _check_syntax(code)
        if syntax_err2:
            return {
                'status': 'error',
                'message': (
                    f"Le code généré est invalide même après réécriture ({syntax_err2}). "
                    "Essaie de simplifier ta demande ou de la découper en plusieurs étapes."
                ),
                'code': code,
            }

    workdir = _workspace_dir(thread_id)
    before  = set(os.listdir(workdir)) if os.path.isdir(workdir) else set()
    result  = _execute(code, None, workdir, thread_id)
    result['code'] = code
    new_files = _scan_new_files(workdir, before)
    result['files_info'], result['files_list'] = _route_new_files(new_files, thread_id)
    result['files_count'] = len(new_files)
    return result
