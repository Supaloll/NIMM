# -*- coding: utf-8 -*-
"""
CoaNIMM — opérations Fichiers vérifiées (couche tool-calling).

Au lieu de régénérer du code Python à chaque fois, le modèle appelle ces
opérations sûres par leur nom. Toutes celles qui MODIFIENT le disque (renommer,
déplacer, supprimer, créer un dossier) sont confinées aux dossiers autorisés par
l'utilisateur (core.database.list_coanimm_paths). Le listage est en lecture seule.

Extensible : pour ajouter une famille (Documents, Images, Voix), créer une
fonction op_*, une entrée dans OPS_TOOLS, un nom dans OPS_NAMES et un cas dans
dispatch_op — rien d'autre à câbler.
"""
import os


def _real(p):
    try:
        return os.path.realpath(os.path.abspath(p))
    except Exception:
        return None


def _within(path, allowed_dirs):
    """Vrai si `path` est dans l'un des dossiers autorisés (ou l'un d'eux)."""
    rp = _real(path)
    if rp is None:
        return False
    for base in (allowed_dirs or []):
        b = _real(base)
        if b and (rp == b or rp.startswith(b + os.sep)):
            return True
    return False


def _err(msg):
    return f"[Refusé] {msg}"


# ──────────────────────────────────────────
# Opérations
# ──────────────────────────────────────────

def op_list_files(directory, allowed_dirs=None):
    """Liste le contenu d'un dossier (lecture seule, autorisée partout)."""
    d = os.path.abspath(os.path.expanduser((directory or '').strip()))
    if not d:
        return "[Erreur] Aucun dossier indiqué."
    if not os.path.isdir(d):
        return f"[Erreur] Dossier introuvable : {d}"
    try:
        entries = sorted(os.listdir(d))
    except Exception as e:
        return f"[Erreur] Lecture impossible : {e}"
    if not entries:
        return f"Le dossier {d} est vide."
    lines = []
    for name in entries[:200]:
        full = os.path.join(d, name)
        if os.path.isdir(full):
            lines.append(f"- {name} (dossier)")
        else:
            try:
                size = os.path.getsize(full)
            except Exception:
                size = 0
            lines.append(f"- {name} (fichier, {size} octets)")
    more = '' if len(entries) <= 200 else f"\n… et {len(entries) - 200} autres."
    return f"Contenu de {d} ({len(entries)} éléments) :\n" + "\n".join(lines) + more


def op_make_dir(path, allowed_dirs):
    p = os.path.abspath(os.path.expanduser((path or '').strip()))
    if not _within(p, allowed_dirs):
        return _err(f"création de dossier hors des dossiers autorisés : {p}")
    try:
        os.makedirs(p, exist_ok=True)
        return f"Dossier créé (ou déjà présent) : {p}"
    except Exception as e:
        return f"[Erreur] Création impossible : {e}"


def op_rename(path, new_name, allowed_dirs):
    p = os.path.abspath(os.path.expanduser((path or '').strip()))
    nn = (new_name or '').strip()
    if not nn or (os.sep in nn) or (os.altsep and os.altsep in nn):
        return _err("le nouveau nom doit être un simple nom, sans chemin ni séparateur.")
    if not os.path.exists(p):
        return f"[Erreur] Introuvable : {p}"
    dest = os.path.join(os.path.dirname(p), nn)
    if not _within(p, allowed_dirs) or not _within(dest, allowed_dirs):
        return _err(f"renommage hors des dossiers autorisés : {p}")
    if os.path.exists(dest):
        return f"[Erreur] Un élément porte déjà ce nom : {dest}"
    try:
        os.rename(p, dest)
        return f"Renommé : {p} → {dest}"
    except Exception as e:
        return f"[Erreur] Renommage impossible : {e}"


def op_move(source, destination_folder, allowed_dirs):
    src = os.path.abspath(os.path.expanduser((source or '').strip()))
    dst_dir = os.path.abspath(os.path.expanduser((destination_folder or '').strip()))
    if not os.path.exists(src):
        return f"[Erreur] Source introuvable : {src}"
    if not os.path.isdir(dst_dir):
        return f"[Erreur] Dossier de destination introuvable : {dst_dir}"
    dest = os.path.join(dst_dir, os.path.basename(src))
    if not _within(src, allowed_dirs) or not _within(dest, allowed_dirs):
        return _err("déplacement hors des dossiers autorisés (la source et la destination doivent être autorisées).")
    if os.path.exists(dest):
        return f"[Erreur] La destination existe déjà : {dest}"
    try:
        import shutil
        shutil.move(src, dest)
        return f"Déplacé : {src} → {dest}"
    except Exception as e:
        return f"[Erreur] Déplacement impossible : {e}"


def op_delete(path, allowed_dirs):
    p = os.path.abspath(os.path.expanduser((path or '').strip()))
    if not _within(p, allowed_dirs):
        return _err(f"suppression hors des dossiers autorisés : {p}")
    if not os.path.exists(p):
        return f"[Erreur] Introuvable : {p}"
    try:
        if os.path.isdir(p):
            if os.listdir(p):
                return _err("ce dossier n'est pas vide ; supprime d'abord son contenu (sécurité).")
            os.rmdir(p)
            return f"Dossier vide supprimé : {p}"
        os.remove(p)
        return f"Fichier supprimé : {p}"
    except Exception as e:
        return f"[Erreur] Suppression impossible : {e}"


def op_extract_text(path, allow_cloud=False, thread_id=None):
    """Extrait le texte d'un document et le renvoie (lecture seule).

    Réutilise modules.enrichissement.extract_any (PDF/Word/RTF/ODT/EPUB/HTML/image
    + OCR). Politique cloud-sur-confirmation : si un OCR cloud (Mistral) est requis
    et non encore autorisé, renvoie un message demandant la confirmation.
    """
    p = os.path.abspath(os.path.expanduser((path or '').strip()))
    if not os.path.isfile(p):
        return f"[Erreur] Fichier introuvable : {p}"
    try:
        import core.hub as hub, modules.enrichissement as enr
        mistral_key = enr.mistral_key_from_settings(hub.load_settings(thread_id))
    except Exception:
        mistral_key = None
    try:
        import modules.enrichissement as enr
        res = enr.extract_any(p, os.path.basename(p), mistral_key=mistral_key,
                              allow_cloud=bool(allow_cloud))
    except Exception as e:
        return f"[Erreur] Extraction impossible : {e}"
    st = res.get('status')
    if st == 'confirmation_required':
        return ("[Confirmation requise] " + res.get('reason', '') +
                " Demande explicitement à l'utilisateur s'il accepte cet envoi au cloud ; "
                "s'il accepte, rappelle extract_document_text avec allow_cloud=true. "
                "S'il refuse et qu'aucun OCR local n'est installé, l'extraction sera impossible.")
    if st == 'error':
        return "[Erreur] " + res.get('message', 'extraction impossible.')
    text = (res.get('text') or '')
    if not text.strip():
        return f"Aucun texte extractible dans {os.path.basename(p)}."
    _MAX = 6000
    if len(text) > _MAX:
        text = text[:_MAX] + "\n…[texte tronqué, document plus long]"
    return f"Texte extrait de {os.path.basename(p)} (méthode : {res.get('method','?')}) :\n\n" + text


# ──────────────────────────────────────────
# Câblage tool-calling
# ──────────────────────────────────────────

OPS_NAMES = {'list_files', 'rename_file', 'move_file', 'delete_file', 'make_folder', 'extract_document_text'}


def _allowed_bases_from_db():
    import core.database as db
    return [b for b in (_real(p) for p in db.list_coanimm_paths()) if b]


def dispatch_op(name, args, thread_id=None):
    """Exécute une opération Fichiers et renvoie un compte rendu texte (pour le LLM)."""
    args = args or {}
    if name == 'list_files':
        return op_list_files(args.get('directory', ''))
    if name == 'extract_document_text':
        return op_extract_text(args.get('path', ''), args.get('allow_cloud', False), thread_id)
    try:
        allowed = _allowed_bases_from_db()
    except Exception:
        allowed = []
    if name == 'make_folder':
        return op_make_dir(args.get('path', ''), allowed)
    if name == 'rename_file':
        return op_rename(args.get('path', ''), args.get('new_name', ''), allowed)
    if name == 'move_file':
        return op_move(args.get('source', ''), args.get('destination_folder', ''), allowed)
    if name == 'delete_file':
        return op_delete(args.get('path', ''), allowed)
    return f"[Opération fichier inconnue : {name}]"


def _tool(name, description, properties, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required}}}


_CONFINE = (" N'agit que dans les dossiers que l'utilisateur a explicitement autorisés "
            "pour CoaNIMM ; sinon l'opération est refusée et il faut lui demander d'ajouter "
            "le dossier dans « Dossiers autorisés ».")

OPS_TOOLS = [
    _tool("list_files",
          "Liste les fichiers et sous-dossiers d'un dossier du disque (lecture seule). "
          "Utilise-le pour savoir ce que contient un dossier avant d'agir.",
          {"directory": {"type": "string", "description": "Chemin complet du dossier à lister."}},
          ["directory"]),
    _tool("rename_file",
          "Renomme un fichier ou un dossier (même emplacement, nouveau nom)." + _CONFINE,
          {"path": {"type": "string", "description": "Chemin complet de l'élément à renommer."},
           "new_name": {"type": "string", "description": "Nouveau nom simple (sans chemin)."}},
          ["path", "new_name"]),
    _tool("move_file",
          "Déplace un fichier ou un dossier vers un autre dossier." + _CONFINE,
          {"source": {"type": "string", "description": "Chemin complet de l'élément à déplacer."},
           "destination_folder": {"type": "string", "description": "Chemin complet du dossier de destination."}},
          ["source", "destination_folder"]),
    _tool("delete_file",
          "Supprime un fichier (ou un dossier vide)." + _CONFINE,
          {"path": {"type": "string", "description": "Chemin complet de l'élément à supprimer."}},
          ["path"]),
    _tool("make_folder",
          "Crée un nouveau dossier." + _CONFINE,
          {"path": {"type": "string", "description": "Chemin complet du dossier à créer."}},
          ["path"]),
    _tool("extract_document_text",
          "Extrait le texte d'un document (PDF, Word, RTF, ODT, EPUB, HTML, ou image scannée) et te le rend. "
          "Lecture seule, fonctionne sur n'importe quel fichier indiqué par l'utilisateur. "
          "Si le document est scanné et nécessite un OCR cloud (Mistral), l'outil demande d'abord confirmation : "
          "ne mets allow_cloud à true qu'APRÈS un accord explicite de l'utilisateur pour envoyer le contenu au cloud.",
          {"path": {"type": "string", "description": "Chemin complet du fichier à lire."},
           "allow_cloud": {"type": "boolean", "description": "true uniquement si l'utilisateur a explicitement accepté l'envoi du contenu à l'OCR cloud Mistral. false par défaut."}},
          ["path"]),
]


# ──────────────────────────────────────────
# Famille Documents — résumé (asynchrone : appelle un LLM)
# ──────────────────────────────────────────

def _needs_cloud_confirm(provider, local_mode, allow_cloud):
    """Vrai si résumer enverrait le contenu vers un LLM cloud sans accord préalable."""
    is_local = bool(local_mode) or (str(provider) == 'ollama')
    return (not is_local) and (not allow_cloud)


async def op_summarize(path, allow_cloud=False, thread_id=None):
    """Extrait puis résume un document. Ne renvoie QUE le résumé (le texte intégral
    ne transite pas par la conversation). Politique « cloud sur confirmation » :
    l'OCR cloud (extract_any) ET l'envoi au LLM de synthèse cloud exigent allow_cloud=true.
    En mode local (Ollama), le contenu reste sur la machine, sans confirmation."""
    p = os.path.abspath(os.path.expanduser((path or '').strip()))
    if not os.path.isfile(p):
        return f"[Erreur] Fichier introuvable : {p}"
    try:
        import core.hub as hub
        settings = hub.load_settings(thread_id)
    except Exception as e:
        return f"[Erreur] Configuration indisponible : {e}"
    local_mode = bool(settings.get('local_mode'))
    import modules.enrichissement as _enr0
    mistral_key = _enr0.mistral_key_from_settings(settings)

    try:
        import modules.enrichissement as enr
        res = enr.extract_any(p, os.path.basename(p), mistral_key=mistral_key, allow_cloud=bool(allow_cloud))
    except Exception as e:
        return f"[Erreur] Extraction impossible : {e}"
    if res.get('status') == 'confirmation_required':
        return ("[Confirmation requise] " + res.get('reason', '') +
                " Pour l'OCR cloud, rappelle summarize_document avec allow_cloud=true après accord explicite de l'utilisateur.")
    if res.get('status') == 'error':
        return "[Erreur] " + res.get('message', '')
    text = (res.get('text') or '').strip()
    if not text:
        return f"Aucun texte à résumer dans {os.path.basename(p)}."

    try:
        provider, model = hub.get_task_provider_model('synthese', settings)
    except Exception:
        provider, model = (settings.get('provider') or 'anthropic'), None

    if _needs_cloud_confirm(provider, local_mode, allow_cloud):
        return ("[Confirmation requise] Pour résumer ce document, son texte serait envoyé au modèle « "
                + str(provider) + " » (cloud). Demande l'accord explicite de l'utilisateur puis rappelle "
                "summarize_document avec allow_cloud=true. En mode local (Ollama), le résumé resterait sur la machine.")

    try:
        import core.engine as engine
        summary = await engine.call_llm(
            messages=[{'role': 'user', 'content': "Document à résumer :\n\n" + text[:12000]}],
            provider=provider, model=model,
            system_prompt=("Tu résumes fidèlement un document en français, en TEXTE BRUT lisible sur une "
                           "plage braille : aucune mise en forme markdown, pas de puces, des phrases claires. "
                           "Donne les points essentiels et les informations clés, sans rien inventer."),
            max_tokens=900, temperature=0.3,
            api_keys=settings.get('api_keys') or {},
        )
    except Exception as e:
        return f"[Erreur] Résumé impossible : {e}"
    lieu = "en local" if (local_mode or str(provider) == 'ollama') else f"via {provider}"
    return f"Résumé de {os.path.basename(p)} ({lieu}) :\n\n" + (summary or '').strip()


ASYNC_OPS_NAMES = {'summarize_document'}

ASYNC_OPS_TOOLS = [
    _tool("summarize_document",
          "Résume un document (PDF, Word, RTF, ODT, EPUB, HTML, image scannée). Extrait le texte "
          "puis le résume, et ne renvoie QUE le résumé (le texte intégral ne passe pas dans la conversation). "
          "Si le résumé nécessite un envoi au cloud (OCR Mistral ou LLM de synthèse cloud), l'outil demande "
          "d'abord confirmation : ne mets allow_cloud à true qu'APRÈS un accord explicite de l'utilisateur. "
          "En mode local, le contenu reste sur la machine.",
          {"path": {"type": "string", "description": "Chemin complet du document à résumer."},
           "allow_cloud": {"type": "boolean", "description": "true uniquement si l'utilisateur a explicitement accepté l'envoi du contenu au cloud. false par défaut."}},
          ["path"]),
]


async def dispatch_async_op(name, args, thread_id=None):
    """Dispatch des opérations Documents asynchrones (appel LLM)."""
    args = args or {}
    if name == 'summarize_document':
        return await op_summarize(args.get('path', ''), args.get('allow_cloud', False), thread_id)
    return f"[Opération asynchrone inconnue : {name}]"
