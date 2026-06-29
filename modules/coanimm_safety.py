# -*- coding: utf-8 -*-
"""
CoaNIMM — garde-fous de sécurité pour l'exécution de code généré.

Deux mécanismes complémentaires, selon la politique choisie par l'utilisateur
(« bloquer le pire, confirmer le reste, confiner les écritures ») :

1) classify_for_execution(code) — analyse statique (AST) AVANT exécution :
     - 'blocked'            : capacités refusées d'office (eval, exec, os.system,
                              os.popen, ctypes, winreg, win32api, win32security) ;
     - 'needs_confirmation' : capacités autorisées seulement après accord explicite
                              de l'utilisateur (subprocess, socket, smtplib, ftplib,
                              paramiko, requests/urllib/http — accès réseau).
   NB : un import dynamique (__import__) peut contourner l'analyse statique ; le
   garde-fou runtime (ci-dessous) reste la protection de fond pour les écritures.

2) build_guard_prologue(allowed_dirs, allow_network) — code injecté EN TÊTE du
   script exécuté. Il confine au RUNTIME les écritures, suppressions et
   déplacements aux seuls dossiers autorisés (workspace + dossiers validés par
   l'utilisateur + dossier temporaire système). Les LECTURES restent libres.
   Toute écriture hors zone lève PermissionError avec un message clair.
"""
import ast


# ──────────────────────────────────────────
# 1) Analyse statique : classer le code avant de l'exécuter
# ──────────────────────────────────────────

_BLOCK_IMPORTS = {
    'ctypes':        "utilise ctypes (fonctions système de très bas niveau)",
    'winreg':        "lit ou modifie le registre Windows",
    'win32api':      "accède directement à l'API Windows",
    'win32security': "modifie des paramètres de sécurité Windows",
}

_CONFIRM_IMPORTS = {
    'subprocess': "peut lancer d'autres programmes sur ton ordinateur",
    'socket':     "peut ouvrir des connexions réseau",
    'smtplib':    "peut envoyer des e-mails",
    'ftplib':     "peut se connecter à un serveur FTP",
    'paramiko':   "peut se connecter en SSH",
    'telnetlib':  "peut ouvrir une connexion réseau",
    'requests':   "peut accéder à Internet",
    'urllib':     "peut accéder à Internet",
    'http':       "peut accéder à Internet",
}

# Appels shell bloqués d'office (obj, attribut)
_BLOCK_ATTR_CALLS = {
    ('os', 'system'): "lance une commande shell via os.system()",
    ('os', 'popen'):  "lance une commande shell via os.popen()",
}


def classify_for_execution(code: str) -> dict:
    """Retourne {'blocked': [{'message':...}], 'needs_confirmation': [{'message':...}]}.

    'blocked' non vide ⇒ refuser l'exécution.
    'needs_confirmation' non vide ⇒ exiger un accord explicite (allow_risky).
    """
    blocked, needs = [], []

    def add(lst, msg):
        if msg not in [x['message'] for x in lst]:
            lst.append({'message': msg})

    try:
        tree = ast.parse(code or '')
    except SyntaxError:
        return {'blocked': blocked, 'needs_confirmation': needs}

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = ([node.module] if isinstance(node, ast.ImportFrom)
                     else [a.name for a in node.names])
            for nm in (names or []):
                if not nm:
                    continue
                root = nm.split('.')[0]
                if root in _BLOCK_IMPORTS:
                    add(blocked, _BLOCK_IMPORTS[root])
                elif root in _CONFIRM_IMPORTS:
                    add(needs, _CONFIRM_IMPORTS[root])
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in ('eval', 'exec'):
                add(blocked, f"exécute du code dynamique avec {f.id}() (risque élevé)")
            elif isinstance(f, ast.Attribute):
                obj = f.value.id if isinstance(f.value, ast.Name) else None
                key = (obj, f.attr)
                if key in _BLOCK_ATTR_CALLS:
                    add(blocked, _BLOCK_ATTR_CALLS[key])

    return {'blocked': blocked, 'needs_confirmation': needs}


# ──────────────────────────────────────────
# 1bis) Capacités déclarées : projection LISIBLE de l'analyse statique
# ──────────────────────────────────────────
#
# capabilities_of() ne bloque RIEN : il déclare ce qu'un script fait, pour l'afficher
# et (plus tard) le faire approuver capacité par capacité. Une seule source de vérité :
# il réutilise la même analyse AST que classify_for_execution.

CAPABILITY_LABELS = {
    'ecriture':       "écrit, déplace ou supprime des fichiers",
    'recherche':      "consulte une ressource (recherche web/GitHub, lecture d'une page, base de connaissances, sous-tâche IA) via NIMM, sans sortir du bac à sable",
    'image':          "génère une image",
    'reseau':         "ouvre des connexions réseau brutes",
    'programme':      "lance d'autres programmes",
    'email':          "envoie des e-mails",
    'systeme':        "accède à des fonctions système de bas niveau",
    'shell':          "lance des commandes shell",
    'code_dynamique': "exécute du code dynamique (eval/exec)",
}

# imports -> capacité normalisée (réseau NIMM via helpers = 'recherche', distinct du réseau brut)
_CAP_IMPORTS = {
    'ctypes': 'systeme', 'winreg': 'systeme', 'win32api': 'systeme', 'win32security': 'systeme',
    'subprocess': 'programme',
    'socket': 'reseau', 'requests': 'reseau', 'urllib': 'reseau', 'http': 'reseau',
    'ftplib': 'reseau', 'paramiko': 'reseau', 'telnetlib': 'reseau',
    'smtplib': 'email',
}
# Appels aux helpers NIMM injectés (réseau confiné via localhost) -> capacités douces
_CAP_HELPER_CALLS = {
    'nimm_web_search': 'recherche', 'nimm_github_search': 'recherche',
    'nimm_search_documents': 'recherche', 'nimm_read_url': 'recherche',
    'nimm_ask_llm': 'recherche', 'nimm_translate': 'recherche', 'nimm_expurgate': 'recherche', 'nimm_expurgate_doc': 'recherche', 'nimm_codestral_fim': 'recherche', 'nimm_ocr_document': 'recherche', 'nimm_mistral_speak': 'recherche',
    'nimm_describe_image': 'recherche', 'nimm_simplify': 'recherche', 'nimm_anonymize': 'recherche',
    'nimm_audio_overview': 'recherche',
    'nimm_generate_image': 'image', 'nimm_coloring_page': 'image',
    'nimm_wikipedia': 'recherche', 'nimm_wikidata': 'recherche',
    'nimm_sirene': 'recherche', 'nimm_datagouv': 'recherche', 'nimm_meteo': 'recherche',
    'nimm_mistral_agent': 'recherche', 'nimm_mistral_list_agents': 'recherche',
    # nimm_qr_code : bénin (local uniquement, pas de réseau externe)
}
# Appels (obj, attr) qui écrivent/déplacent/suppriment
_WRITE_ATTR_CALLS = {
    ('shutil', 'move'), ('shutil', 'copy'), ('shutil', 'copy2'), ('shutil', 'copyfile'),
    ('shutil', 'copytree'), ('shutil', 'rmtree'),
    ('os', 'rename'), ('os', 'replace'), ('os', 'remove'), ('os', 'unlink'),
    ('os', 'mkdir'), ('os', 'makedirs'), ('os', 'rmdir'),
}
# Méthodes pathlib.Path d'écriture (heuristique : on déclare 'ecriture' par prudence)
_WRITE_PATH_METHODS = {'write_text', 'write_bytes', 'mkdir', 'unlink', 'rename', 'replace', 'rmdir', 'touch'}

def _open_is_write(call) -> bool:
    mode = None
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        mode = call.args[1].value
    for kw in call.keywords:
        if kw.arg == 'mode' and isinstance(kw.value, ast.Constant):
            mode = kw.value.value
    return isinstance(mode, str) and any(c in mode for c in ('w', 'a', 'x', '+'))

def capabilities_of(code: str) -> list:
    """Liste TRIÉE des capacités sensibles d'un script (lecture seule, ne bloque rien).
    Projection de la même analyse AST que classify_for_execution."""
    caps = set()
    try:
        tree = ast.parse(code or '')
    except SyntaxError:
        return []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = ([node.module] if isinstance(node, ast.ImportFrom)
                     else [a.name for a in node.names])
            for nm in (names or []):
                root = (nm or '').split('.')[0]
                if root in _CAP_IMPORTS:
                    caps.add(_CAP_IMPORTS[root])
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                if f.id in ('eval', 'exec'):
                    caps.add('code_dynamique')
                elif f.id in _CAP_HELPER_CALLS:
                    caps.add(_CAP_HELPER_CALLS[f.id])
                elif f.id == 'open' and _open_is_write(node):
                    caps.add('ecriture')
            elif isinstance(f, ast.Attribute):
                obj = f.value.id if isinstance(f.value, ast.Name) else None
                if (obj, f.attr) in (('os', 'system'), ('os', 'popen')):
                    caps.add('shell')
                elif (obj, f.attr) in _WRITE_ATTR_CALLS:
                    caps.add('ecriture')
                elif f.attr in _WRITE_PATH_METHODS:
                    caps.add('ecriture')
    return sorted(caps)


# ──────────────────────────────────────────
# 2) Garde-fou runtime : confiner les écritures aux dossiers autorisés
# ──────────────────────────────────────────

def build_guard_prologue(allowed_dirs, allow_network: bool = False) -> str:
    """Construit le code Python injecté en tête du script exécuté.

    `allowed_dirs` : itérable de dossiers (chemins absolus) où l'écriture est
    permise. Le dossier courant (workspace) et le dossier temporaire système y
    sont ajoutés automatiquement. Si `allow_network` est faux, l'ouverture de
    sockets est bloquée (ceinture + bretelles avec l'analyse statique).
    """
    dirs = [str(d) for d in (allowed_dirs or []) if d]
    literal = "[" + ", ".join(repr(d) for d in dirs) + "]"
    net_block = "" if allow_network else _NET_BLOCK_SNIPPET
    return _GUARD_TEMPLATE.replace("__ALLOWED_DIRS__", literal).replace("__NET_BLOCK__", net_block)


_NET_BLOCK_SNIPPET = (
    "try:\n"
    "    import socket as _nimm_sock\n"
    "    _nimm_conn0 = _nimm_sock.socket.connect\n"
    "    _NIMM_LOCAL = ('127.0.0.1', 'localhost', '::1', '0.0.0.0', '')\n"
    "    def _nimm_connect(self, address):\n"
    "        _h = address[0] if isinstance(address, (tuple, list)) else address\n"
    "        if str(_h) not in _NIMM_LOCAL:\n"
    "            raise PermissionError('CoaNIMM a bloque une connexion reseau vers ' + str(_h) + ' (non autorise pour ce script).')\n"
    "        return _nimm_conn0(self, address)\n"
    "    _nimm_sock.socket.connect = _nimm_connect\n"
    "except Exception:\n"
    "    pass\n"
)


_GUARD_TEMPLATE = '''\
# === Garde-fou CoaNIMM (écritures confinées) — injecté automatiquement ===
import builtins as _nimm_b, os as _nimm_os, tempfile as _nimm_tf
_NIMM_ALLOWED = __ALLOWED_DIRS__
def _nimm_real(p):
    try:
        return _nimm_os.path.realpath(_nimm_os.path.abspath(p if isinstance(p, str) else _nimm_os.fspath(p)))
    except Exception:
        return None
_NIMM_BASES = []
for _d in list(_NIMM_ALLOWED) + [_nimm_os.getcwd(), _nimm_tf.gettempdir()]:
    _r = _nimm_real(_d)
    if _r:
        _NIMM_BASES.append(_r)
def _nimm_ok(path):
    rp = _nimm_real(path)
    if rp is None:
        return False
    for _base in _NIMM_BASES:
        if rp == _base or rp.startswith(_base + _nimm_os.sep):
            return True
    return False
def _nimm_deny(path, what):
    raise PermissionError(
        "CoaNIMM a bloque " + what + " hors des dossiers autorises : " + str(path)
        + ". Ajoute ce dossier dans les Dossiers autorises de CoaNIMM si c'est voulu.")
# builtins.open (couvre aussi pathlib.Path.open / write_text / write_bytes)
_nimm_open0 = _nimm_b.open
def _nimm_open(file, mode='r', *a, **k):
    if not isinstance(file, int):
        _m = mode if isinstance(mode, str) else 'r'
        if any(_c in _m for _c in ('w', 'a', 'x', '+')):
            if not _nimm_ok(file):
                _nimm_deny(file, "une ecriture de fichier")
    return _nimm_open0(file, mode, *a, **k)
_nimm_b.open = _nimm_open
# io.open (utilisé par pathlib.Path.open / write_text / write_bytes)
import io as _nimm_io
_nimm_io.open = _nimm_open
# os.open (bas niveau)
_nimm_osopen0 = _nimm_os.open
_NIMM_WFLAGS = _nimm_os.O_WRONLY | _nimm_os.O_RDWR | _nimm_os.O_CREAT | _nimm_os.O_APPEND | getattr(_nimm_os, 'O_TRUNC', 0)
def _nimm_osopen(path, flags, *a, **k):
    if (flags & _NIMM_WFLAGS) and not _nimm_ok(path):
        _nimm_deny(path, "une ecriture de fichier")
    return _nimm_osopen0(path, flags, *a, **k)
_nimm_os.open = _nimm_osopen
# Suppressions / créations (1 chemin)
def _nimm_wrap1(name, what):
    _orig = getattr(_nimm_os, name, None)
    if _orig is None:
        return
    def _w(path, *a, **k):
        if not _nimm_ok(path):
            _nimm_deny(path, what)
        return _orig(path, *a, **k)
    setattr(_nimm_os, name, _w)
for _n in ('remove', 'unlink', 'rmdir', 'removedirs', 'mkdir', 'makedirs'):
    _nimm_wrap1(_n, "une operation sur fichier ou dossier")
# Renommer / remplacer (source ET destination)
def _nimm_wrap2(name):
    _orig = getattr(_nimm_os, name, None)
    if _orig is None:
        return
    def _w(src, dst, *a, **k):
        if not _nimm_ok(src):
            _nimm_deny(src, "un deplacement")
        if not _nimm_ok(dst):
            _nimm_deny(dst, "un deplacement")
        return _orig(src, dst, *a, **k)
    setattr(_nimm_os, name, _w)
for _n in ('rename', 'replace'):
    _nimm_wrap2(_n)
# shutil
import shutil as _nimm_sh
def _nimm_sh_dst(name):
    _orig = getattr(_nimm_sh, name, None)
    if _orig is None:
        return
    def _w(src, dst, *a, **k):
        if not _nimm_ok(dst):
            _nimm_deny(dst, "une copie ou un deplacement")
        if name == 'move' and not _nimm_ok(src):
            _nimm_deny(src, "un deplacement")
        return _orig(src, dst, *a, **k)
    setattr(_nimm_sh, name, _w)
for _n in ('move', 'copy', 'copy2', 'copyfile', 'copytree'):
    _nimm_sh_dst(_n)
_nimm_rmtree0 = getattr(_nimm_sh, 'rmtree', None)
if _nimm_rmtree0 is not None:
    def _nimm_rmtree(path, *a, **k):
        if not _nimm_ok(path):
            _nimm_deny(path, "la suppression d'un dossier entier")
        return _nimm_rmtree0(path, *a, **k)
    _nimm_sh.rmtree = _nimm_rmtree
__NET_BLOCK__# === fin garde-fou CoaNIMM ===
'''


# ──────────────────────────────────────────
# 3) Risques pour AFFICHAGE (UI) — dérivés du MÊME classifieur que le blocage
# ──────────────────────────────────────────

# Opérations confinées mais notables (informationnel : le garde-fou les limite
# déjà aux dossiers autorisés, mais on les signale à l'utilisateur).
_WARN_DELETE_CALLS = {
    ('shutil', 'rmtree'): "supprime un dossier entier et son contenu (dans les dossiers autorisés uniquement)",
    ('os', 'remove'):     "supprime des fichiers (dans les dossiers autorisés uniquement)",
    ('os', 'unlink'):     "supprime des fichiers (dans les dossiers autorisés uniquement)",
    ('os', 'rmdir'):      "supprime des dossiers (dans les dossiers autorisés uniquement)",
}


def _scan_delete_warnings(code: str) -> list:
    out, seen = [], set()
    try:
        tree = ast.parse(code or '')
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            obj = node.func.value.id if isinstance(node.func.value, ast.Name) else None
            key = (obj, node.func.attr)
            if key in _WARN_DELETE_CALLS and key not in seen:
                seen.add(key)
                out.append(_WARN_DELETE_CALLS[key])
    return out


def risks_for_display(code: str) -> list:
    """Liste d'avertissements pour l'interface, dérivée de classify_for_execution
    (donc cohérente avec ce qui est réellement bloqué / à confirmer) + les
    suppressions notables. Format : [{'level': 'danger'|'warning', 'message': str}]."""
    c = classify_for_execution(code)
    out = []
    for r in c.get('blocked', []):
        out.append({'level': 'danger', 'message': r['message']})
    for r in c.get('needs_confirmation', []):
        out.append({'level': 'warning', 'message': r['message']})
    return out
