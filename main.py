# ============================================
# NIMM — main.py
# Point d'entrée FastAPI + toutes les routes
# ============================================

import uuid
import json
import os
import re
import asyncio
import threading
import time
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File, Body, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict

import os as _os_main
import base64 as _base64
import httpx as _httpx

from core.database import (
    init_db, get_threads, get_thread, create_thread, delete_thread, set_thread_mask,
    update_thread_name, update_thread_tags, get_messages, add_message, count_messages,
    get_setting, set_setting, get_api_keys as _db_get_api_keys, set_api_keys as _db_set_api_keys,
    get_all_memory, delete_memory,
    update_memory_value, save_memory,
    get_cost_summary, reset_wallet, update_wallet_rates, update_wallet_solde,
    check_auto_resets,
    set_user_context, get_current_user,
    get_all_users, create_user, delete_user, update_user,
    save_image, get_images, rename_image, delete_image,
    get_external_key, set_external_key, list_external_keys, delete_external_key,
    list_presets, save_preset, delete_preset, apply_preset,
    list_prompts, save_prompt, delete_prompt
)
from core.hub import process_message, memory_worker


# ══════════════════════════════════════════
# DÉMARRAGE
# ══════════════════════════════════════════

_last_ping = time.time()

def _watchdog():
    """Arrête le serveur si aucun ping reçu depuis 15 secondes."""
    while True:
        time.sleep(5)
        if time.time() - _last_ping > 15:
            print("[NIMM] Fenêtre fermée — arrêt du serveur.")
            os._exit(0)

def _warmup_embeddings():
    """Préchauffage du modèle embeddings en arrière-plan au démarrage."""
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print("[WARMUP] Thread embeddings demarre...")
    try:
        from core.database import get_setting, _load_users
        if not _load_users():
            print("[WARMUP] Embeddings désactivé — aucun utilisateur.")
            return
        enabled = get_setting('embeddings_enabled', 'false')
        print(f"[WARMUP] embeddings_enabled = {enabled}")
        if enabled.lower() != 'true':
            print("[WARMUP] Embeddings desactive, abandon.")
            return
        print("[WARMUP] Embeddings actives, chargement...")
        from modules.memory import _get_model
        print("[WARMUP] Appel _get_model()...")
        model = _get_model()
        print(f"[WARMUP] Resultat _get_model() = {model}")
        if model is not None:
            print("[WARMUP] OK -> modele charge dans _embed_model")
        else:
            print("[WARMUP] ERR -> _get_model a retourne None")
    except Exception as e:
        print(f"[WARMUP] Exception dans le thread : {e}")
        import traceback
        traceback.print_exc()

def _run_decay():
    """Applique le decay mémoire une fois au démarrage — thread daemon."""
    import time
    time.sleep(2)  # Laisse les DB s'initialiser
    from core.database import _load_users
    from modules.memory import apply_decay_on_startup
    users = _load_users()
    if not users:
        print("[DECAY] Aucun utilisateur — decay ignoré au démarrage.")
        return
    for u in users:
        apply_decay_on_startup(user_id=u['id'])

def _run_inference():
    """Lance le moteur d'inférence mémoire en thread daemon."""
    import time
    time.sleep(3)  # Laisse le serveur finir son démarrage
    from core.database import _load_users
    from modules.memory import run_inference_engine
    users = _load_users()
    if not users:
        print("[INFERENCE] Aucun utilisateur — moteur d'inférence ignoré au démarrage.")
        return
    run_inference_engine(user_id=users[0]['id'])

def _slugify(name: str) -> str:
    """Convertit un prénom en id technique : 'Éric' → 'eric', 'Laurent' → 'laurent'."""
    import unicodedata
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_str = nfkd.encode('ascii', 'ignore').decode('ascii')
    return ascii_str.lower().strip()

def _cleanup_data_dir():
    """Nettoie le dossier data/ au démarrage :
    - Supprime les DB parasites (undefined, null, id inconnu)
    - Crée une DB propre pour chaque utilisateur dans users.json
    """
    import glob
    from core.database import DATA_DIR, _load_users, get_db_path

    os.makedirs(DATA_DIR, exist_ok=True)

    # Charger les utilisateurs connus
    users = _load_users()
    valid_ids = {u['id'] for u in users}

    # ── Étape 1 : DB parasites ──
    # Supprimer toute DB dont l'id ne correspond à aucun utilisateur connu
    PARASITES = {'undefined', 'null', 'none', ''}
    for pattern in ('nimm_*.db', 'nimm_*.db-wal', 'nimm_*.db-shm'):
        for filepath in glob.glob(os.path.join(DATA_DIR, pattern)):
            fname = os.path.basename(filepath)
            part = fname.replace('nimm_', '').split('.')[0]
            if part in PARASITES:
                os.remove(filepath)
                print(f"[CLEANUP] DB parasite supprimée : {fname}")
            elif valid_ids and part not in valid_ids:
                os.remove(filepath)
                print(f"[CLEANUP] DB orpheline supprimée : {fname}")

    # ── Étape 2 : créer les DB manquantes ──
    for user in users:
        db_path = get_db_path(user['id'])
        if not os.path.exists(db_path):
            init_db(user['id'])
            print(f"[CLEANUP] DB créée pour : {user['id']}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    _cleanup_data_dir()
    # N'initialiser la DB que si un utilisateur existe dans users.json
    # Évite de créer nimm_laurent.db fantôme sur les machines des autres
    from core.database import _load_users
    existing_users = _load_users()
    if existing_users:
        for u in existing_users:
            init_db(u['id'])
        print(f"[NIMM] DB initialisées pour {len(existing_users)} utilisateur(s).")
    else:
        print("[NIMM] Aucun utilisateur — DB non créée (onboarding en attente).")
    if existing_users:
        check_auto_resets()
    else:
        print("[NIMM] check_auto_resets ignoré — pas d'utilisateur.")
    threading.Thread(target=_warmup_stt,        daemon=True).start()
    threading.Thread(target=_warmup_embeddings, daemon=True).start()
    server_mode = get_setting('server_mode', 'false').lower() == 'true'
    if not server_mode:
        # threading.Thread(target=_watchdog, daemon=True).start()
        print("[NIMM] Watchdog désactivé.")
    else:
        print("[NIMM] Watchdog désarmé (mode serveur).")
    threading.Thread(target=_run_decay,        daemon=True).start()
    threading.Thread(target=_run_inference,    daemon=True).start()
    asyncio.create_task(memory_worker())
    yield

app = FastAPI(title="NIMM", lifespan=lifespan)

@app.middleware("http")
async def _user_ctx_middleware(request, call_next):
    """Pose le contexte utilisateur pour toutes les routes depuis le header X-User-ID."""
    user_id = request.headers.get('x-user-id', '') or ''
    if user_id:
        set_user_context(user_id)
    return await call_next(request)

def _sec_host_allowed(host: str) -> bool:
    """Host/Origine autorisé : local, nom tailnet (.ts.net), ou NIMM_ALLOWED_HOSTS."""
    if not host:
        return True  # client local sans en-tête Host : on n'enferme pas
    h = host.strip().lower()
    if h.startswith('['):
        h = h[1:].split(']')[0]
    elif h.count(':') == 1:
        h = h.split(':')[0]
    if h in ('127.0.0.1', 'localhost', '::1'):
        return True
    if h.endswith('.ts.net'):
        return True
    extra = [x.strip().lower() for x in _os_main.environ.get('NIMM_ALLOWED_HOSTS', '').split(',') if x.strip()]
    return h in extra

@app.middleware("http")
async def _security_middleware(request, call_next):
    """Anti DNS-rebinding / CSRF + capture de l'identité Tailscale.
    Le binding sur 127.0.0.1 limite déjà l'accès distant à `tailscale serve`."""
    if not _sec_host_allowed(request.headers.get('host', '')):
        return JSONResponse({'detail': 'Host non autorisé.'}, status_code=400)
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        origin = request.headers.get('origin')
        if origin:
            from urllib.parse import urlparse as _up
            if not _sec_host_allowed(_up(origin).netloc):
                return JSONResponse({'detail': 'Origine non autorisée.'}, status_code=403)
    # Identité fournie par `tailscale serve`
    ts_user = request.headers.get('tailscale-user-login') or ''
    try:
        request.state.tailscale_user = ts_user
    except Exception:
        pass
    # Verrou de session (anti-pollution mémoire) sur les écritures de chat.
    # Distant : seul le porteur de l'identité Tailscale liée peut écrire dans sa session.
    # Local : un profil à PIN exige un jeton de déverrouillage valide.
    if request.method == 'POST':
        _p = request.url.path
        if _p.startswith('/api/chat') or _p.endswith('/messages'):
            import core.database as _dbsec
            _target = request.headers.get('x-user-id', '') or ''
            _bound = _dbsec.find_user_by_ts_login(ts_user) if ts_user else None
            if _bound is not None:
                if _target and _target != _bound:
                    return JSONResponse({'detail': 'tailscale_identity_mismatch'}, status_code=403)
            elif _target and _dbsec.user_has_pin(_target):
                if not _dbsec.check_unlock_token(_target, request.headers.get('x-unlock-token', '')):
                    return JSONResponse({'detail': 'session_locked', 'user': _target}, status_code=403)
    return await call_next(request)

# Fichiers statiques
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), 'frontend')
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# Timestamp de demarrage -- injecte dans les URLs statiques pour invalider le cache navigateur
import time as _time
_STATIC_VERSION = str(int(_time.time()))


# ══════════════════════════════════════════
# FRONTEND
# ══════════════════════════════════════════

@app.get("/manifest.json")
async def serve_manifest():
    return FileResponse(os.path.join(FRONTEND_DIR, 'manifest.json'), media_type='application/manifest+json')

@app.get("/")
async def root():
    from fastapi.responses import HTMLResponse
    with open(os.path.join(FRONTEND_DIR, 'index.html'), encoding='utf-8') as _f:
        html = _f.read()
    html = html.replace('/static/styles.css"', f'/static/styles.css?v={_STATIC_VERSION}"')
    html = html.replace('/static/app.js"',    f'/static/app.js?v={_STATIC_VERSION}"')
    return HTMLResponse(content=html)

@app.get("/api/embeddings/status")
async def embeddings_status():
    """Retourne l'état du modèle embeddings : disabled / loading / ready / error.
    Lecture seule — ne déclenche jamais le chargement."""
    from core.database import get_setting
    if get_setting('embeddings_enabled', 'false').lower() != 'true':
        return {"status": "disabled"}
    import modules.memory as _mem
    if _mem._embed_model is not None:
        return {"status": "ready"}
    if _mem._embed_error is not None:
        return {"status": "error", "detail": _mem._embed_error}
    return {"status": "loading"}


@app.post("/api/embeddings/warmup")
async def warmup_embeddings():
    """Déclenche le chargement embeddings dans un thread — non bloquant."""
    import asyncio
    from core.database import get_setting
    if get_setting('embeddings_enabled', 'false').lower() != 'true':
        return {"status": "disabled"}
    from modules import memory as _mem
    if _mem._embed_model is not None:
        return {"status": "ready"}
    def _load():
        from modules.memory import _get_model
        _get_model()
    # run_in_executor renvoie déjà un futur : inutile de l'envelopper dans
    # create_task (qui attend une coroutine, pas un Future — l'ancien appel
    # levait une TypeError), et on n'instancie plus un ThreadPoolExecutor
    # jetable jamais fermé. Pool de threads par défaut.
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _load)
    return {"status": "loading"}


@app.get("/api/ping")
async def ping():
    global _last_ping
    _last_ping = time.time()
    return {"ok": True}


# ══════════════════════════════════════════
# MODÈLES PYDANTIC
# ══════════════════════════════════════════

class ChatRequest(BaseModel):
    message:    str
    thread_id:  str
    images:     Optional[List[dict]] = None
    web_search: Optional[bool] = False
    location:   Optional[str] = None
    user_id:    Optional[str] = None

class ThreadCreate(BaseModel):
    name:             str
    mode:             Optional[str] = 'chat'
    mask_id:          Optional[str] = None
    personality_mode: Optional[str] = None

class ThreadRename(BaseModel):
    name: Optional[str] = None
    tags: Optional[str] = None

class MessageCreate(BaseModel):
    role:    str
    content: str

class SettingValue(BaseModel):
    value: str

class ProviderSetting(BaseModel):
    provider: str

class MaskSetting(BaseModel):
    mask_id: str

class MaskSaveRequest(BaseModel):
    name:  str
    emoji: Optional[str] = None

class LengthSetting(BaseModel):
    value: int

class PresenceSetting(BaseModel):
    value: int

class IdentityRequest(BaseModel):
    name: str

class OnboardingRequest(BaseModel):
    name: str
    dob:  Optional[str] = None

class MemoryEdit(BaseModel):
    valeur: str

class TabCreate(BaseModel):
    name:      str
    thread_id: Optional[str] = None

class ApiKeysSetting(BaseModel):
    anthropic:     Optional[str] = None
    deepseek:      Optional[str] = None
    gemini:        Optional[str] = None
    openai:        Optional[str] = None
    openrouter:    Optional[str] = None
    mistral:       Optional[str] = None
    stability_ai:  Optional[str] = None
    brave:         Optional[str] = None
    tavily:        Optional[str] = None

class VisionProviderSetting(BaseModel):
    provider: str

class ModelSetting(BaseModel):
    model: str

class RoutingSetting(BaseModel):
    chat:     Optional[str] = None
    vision:   Optional[str] = None
    image:    Optional[str] = None
    memoire:  Optional[Dict[str, str]] = None
    titre:    Optional[Dict[str, str]] = None
    synthese: Optional[Dict[str, str]] = None


# ══════════════════════════════════════════
# CHAT
# ══════════════════════════════════════════

@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    from fastapi.responses import StreamingResponse as SR
    from core.hub import process_message_stream
    set_user_context(req.user_id or get_current_user())
    if not req.message.strip() and not req.images:
        raise HTTPException(400, "Message vide.")
    if not req.thread_id:
        raise HTTPException(400, "thread_id manquant.")

    return SR(
        process_message_stream(
            thread_id=req.thread_id,
            user_message=req.message,
            images=req.images,
            web_search=req.web_search or False,
            location=req.location or '',
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )

@app.delete("/api/chat/{thread_id}/last_assistant")
async def delete_last_assistant_route(thread_id: str):
    """Supprime le dernier message assistant avant régénération."""
    from core.database import delete_last_assistant
    return {"deleted": delete_last_assistant(thread_id)}

@app.delete("/api/chat/{thread_id}/last_pair")
async def delete_last_pair_route(thread_id: str):
    """Supprime la dernière paire user+assistant avant modification d'un message."""
    from core.database import delete_last_pair
    return delete_last_pair(thread_id)

@app.get("/api/search/text")
async def search_text_route(q: str = "", k: int = 20):
    """Recherche textuelle brute (mot exact) dans l'historique des messages."""
    from core.database import search_messages_text
    return {"resultats": search_messages_text(q, k)}

class ForkRequest(BaseModel):
    up_to: int  # index 0-based du message inclus dans le fork

@app.post("/api/chat/{thread_id}/fork")
async def fork_thread_route(thread_id: str, req: ForkRequest):
    """Crée un nouveau fil en copiant les messages 0..up_to du fil source."""
    import uuid
    from core.database import get_messages_up_to, get_thread, create_thread, add_message
    src = get_thread(thread_id)
    src_name = src.get('name', 'Conversation') if src else 'Conversation'
    new_id   = str(uuid.uuid4())
    new_name = f"↕ {src_name}"
    create_thread(new_id, new_name)
    msgs = get_messages_up_to(thread_id, req.up_to)
    for m in msgs:
        add_message(new_id, m['role'], m['content'])
    return {"thread_id": new_id, "name": new_name}

@app.post("/api/chat/{thread_id}/continue")
async def continue_thread_route(thread_id: str):
    """Continue le dernier message assistant tronqué par max_tokens."""
    from fastapi.responses import StreamingResponse as SR
    from core.database import get_messages, append_to_last_assistant
    import core.hub as hub
    import core.engine as engine

    msgs = get_messages(thread_id)
    if not msgs:
        raise HTTPException(404, "Fil vide.")

    settings = hub.load_settings(thread_id)
    provider  = settings.get('provider', '')
    model     = settings.get('model')
    api_keys  = settings.get('api_keys', {})

    try:
        if settings.get('personality_mode') == 'potards':
            mask = {'system_prompt': hub.build_potards_prompt(settings.get('potards', {}))}
        else:
            mask = hub.load_mask(settings.get('mask_id', ''))
    except Exception:
        mask = {'system_prompt': 'Tu es un assistant utile.'}

    system_prompt = mask.get('system_prompt', '')
    # Ajouter un user turn de continuation — non sauvegardé en DB
    continuation_msgs = msgs + [{'role': 'user', 'content': 'Continue.'}]

    async def _stream():
        accumulated = ''
        try:
            async for token in engine.call_llm_stream(
                messages=continuation_msgs,
                provider=provider,
                model=model,
                system_prompt=system_prompt,
                max_tokens=settings.get('max_tokens', 1024),
                temperature=settings.get('temperature', 0.7),
                api_keys=api_keys,
            ):
                accumulated += token
                yield f"data: {token}\n\n"
        except Exception as e:
            yield f"data: [ERREUR: {e}]\n\n"
        if accumulated:
            append_to_last_assistant(thread_id, accumulated)
        yield "data: [DONE]\n\n"

    return SR(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.post("/api/threads/{thread_id}/summary")
async def summary_route(thread_id: str):
    """Génère un résumé du fil courant via le LLM configuré."""
    from core.database import get_messages
    import core.hub as hub
    import core.engine as engine

    msgs = get_messages(thread_id, limit=60)
    if not msgs:
        return {"summary": "Ce fil est vide."}

    conv_text = "\n".join(
        f"{'Moi' if m['role']=='user' else 'NIMM'} : {m['content'][:400]}"
        for m in msgs
    )
    settings  = hub.load_settings(thread_id)
    provider, model = hub.get_task_provider_model('coanimm', settings)
    try:
        summary = await engine.call_llm(
            messages=[{'role': 'user', 'content': conv_text}],
            provider=provider,
            model=model,
            system_prompt=(
                "Résume cette conversation en 4 à 6 phrases courtes, en français, "
                "en texte brut sans mise en forme. Commence directement par les points essentiels."
            ),
            max_tokens=300,
            temperature=0.3,
            api_keys=settings['api_keys'],
        )
    except Exception as e:
        summary = f"Erreur de génération : {e}"
    return {"summary": summary}

class ExportRequest(BaseModel):
    items: list   # [{role, content}]
    format: str   # txt | docx | pdf | rtf | odt | epub | mp3

@app.post("/api/export")
async def export_route(req: ExportRequest):
    """Génère un fichier exporté (txt, docx, pdf, rtf, odt, epub, mp3)."""
    from modules.export_nimm import export_messages
    from fastapi.responses import Response
    try:
        data, filename, mime = await export_messages(req.items, req.format)
        return Response(
            content=data,
            media_type=mime,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except (ValueError, RuntimeError) as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/chat")
async def chat(req: ChatRequest):
    set_user_context(req.user_id or get_current_user())
    if not req.message.strip() and not req.images:
        raise HTTPException(400, "Message vide.")
    if not req.thread_id:
        raise HTTPException(400, "thread_id manquant.")

    result = await process_message(
        thread_id=req.thread_id,
        user_message=req.message,
        images=req.images,
        web_search=req.web_search or False,
        location=req.location or '',
    )
    return result


# ══════════════════════════════════════════
# FILS (THREADS)
# ══════════════════════════════════════════

@app.get("/api/threads")
async def list_threads():
    try:
        return get_threads()
    except (RuntimeError, Exception):
        return []

@app.post("/api/threads")
async def new_thread(req: ThreadCreate):
    thread_id = str(uuid.uuid4())
    create_thread(thread_id, req.name, req.mode)
    if req.mask_id and req.personality_mode:
        set_thread_mask(thread_id, req.mask_id, req.personality_mode)
    elif req.mask_id:
        set_thread_mask(thread_id, req.mask_id, 'mask')
    elif req.personality_mode == 'potards':
        set_thread_mask(thread_id, '', 'potards')
    return get_thread(thread_id)

@app.get("/api/threads/{thread_id}")
async def get_one_thread(thread_id: str):
    t = get_thread(thread_id)
    if not t:
        raise HTTPException(404, "Fil introuvable.")
    return t

@app.post("/api/threads/{thread_id}/memorize")
async def memorize_thread_route(thread_id: str):
    """Déclenche une passe mémoire silencieuse sur un fil — appelée avant fermeture ou suppression."""
    from core.hub import memorize_thread, load_settings
    settings = load_settings()
    provider = settings.get('provider', '')
    api_keys = settings.get('api_keys', {})
    if not provider or not api_keys.get(provider):
        return {"status": "skipped", "reason": "no provider"}
    try:
        count = await memorize_thread(thread_id, settings)
        return {"status": "ok", "saved": count}
    except Exception as e:
        print(f"[MAIN] ⚠️ Erreur memorize_thread : {e}")
        return {"status": "error"}

@app.delete("/api/threads/{thread_id}")
async def remove_thread(thread_id: str):
    delete_thread(thread_id)
    set_setting(f'session_bilan_{thread_id}', '')
    set_setting(f'ghost_threads', _remove_from_ghost_list(thread_id))
    return {"status": "ok"}

def _remove_from_ghost_list(thread_id: str) -> str:
    """Retire un thread_id de la liste ghost_threads lors de sa suppression."""
    raw = get_setting('ghost_threads', '[]')
    try:
        ghost_list = json.loads(raw)
        ghost_list = [t for t in ghost_list if t != thread_id]
        return json.dumps(ghost_list)
    except Exception:
        return '[]'

@app.patch("/api/threads/{thread_id}")
async def rename_thread(thread_id: str, req: ThreadRename):
    if req.name is not None:
        update_thread_name(thread_id, req.name)
    if req.tags is not None:
        update_thread_tags(thread_id, req.tags)
    return {"status": "ok"}


# ══════════════════════════════════════════
# MESSAGES
# ══════════════════════════════════════════

@app.get("/api/threads/{thread_id}/messages")
async def list_messages(thread_id: str):
    return get_messages(thread_id)

@app.post("/api/threads/{thread_id}/messages")
async def save_message(thread_id: str, req: MessageCreate):
    add_message(thread_id, req.role, req.content)
    return {"status": "ok"}


@app.get("/api/threads/{thread_id}/carnet")
async def get_thread_carnet(thread_id: str):
    """Retourne les notes du carnet de bord pour un fil donné."""
    from core.database import get_carnet_notes
    return get_carnet_notes(thread_id)


@app.get("/api/threads/{thread_id}/export")
async def export_thread_markdown(thread_id: str):
    """Exporte un fil (ou onglet) en Markdown téléchargeable."""
    from fastapi import Response
    thread = get_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Fil introuvable.")
    messages = get_messages(thread_id, limit=10000)

    titre = thread.get('name') or 'Conversation NIMM'
    lignes = [f"# {titre}", "", f"_Exporté le {datetime.now().strftime('%d/%m/%Y à %H:%M')}_", ""]
    role_labels = {"user": "**Vous**", "assistant": "**NIMM**"}
    for m in messages:
        label = role_labels.get(m['role'], f"**{m['role']}**")
        lignes.append(f"{label} :")
        lignes.append("")
        lignes.append(m['content'] or "")
        lignes.append("")
        lignes.append("---")
        lignes.append("")
    contenu = "\n".join(lignes)

    nom_fichier = re.sub(r'[^\w\-éèàâêîôûüçÉÈÀÂÊÎÔÛÜÇ ]', '', titre).strip() or 'conversation'
    return Response(
        content=contenu,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}.md"'}
    )


# ══════════════════════════════════════════
# ONGLETS (TABS)
# Les onglets sont des threads enfants.
# ══════════════════════════════════════════

@app.get("/api/threads/{thread_id}/tabs")
async def list_tabs(thread_id: str):
    all_threads = get_threads()
    # Les onglets ont leur parent_id dans le champ mode (convention : "tab:{parent_id}")
    tabs = [
        t for t in all_threads
        if t.get('mode', '').startswith(f'tab:{thread_id}')
    ]
    return tabs

@app.post("/api/threads/{thread_id}/tabs")
async def create_tab(thread_id: str, req: TabCreate):
    tab_id = str(uuid.uuid4())
    create_thread(tab_id, req.name, f'tab:{thread_id}')
    return get_thread(tab_id)

@app.post("/api/threads/{thread_id}/title")
async def generate_title(thread_id: str, req: dict = Body(default={})):
    """Genere un titre court pour un onglet et le met a jour en base."""
    from core.hub import generate_tab_title
    content = req.get('content', '')
    if not content:
        raise HTTPException(400, "Contenu requis.")
    title = await generate_tab_title(content)
    update_thread_name(thread_id, title)
    return {"name": title}

@app.post("/api/threads/{thread_id}/synthesize")
async def synthesize_tab(thread_id: str):
    """Genere une synthese courte du contenu d'un onglet. Ne stocke rien."""
    from core.hub import generate_tab_synthesis
    result = await generate_tab_synthesis(thread_id)
    if not result:
        raise HTTPException(500, "Impossible de generer la synthese.")
    return result

@app.post("/api/threads/{thread_id}/mode")
async def set_thread_mode(thread_id: str, mode: str):
    from core.database import get_conn
    conn = get_conn()
    conn.execute('UPDATE threads SET mode = ? WHERE thread_id = ?', (mode, thread_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}


# ══════════════════════════════════════════
# MODE FANTÔME — désactive la mémoire par fil
# ══════════════════════════════════════════

@app.get("/api/threads/{thread_id}/ghost")
async def get_ghost_mode(thread_id: str):
    import json as _j
    raw = get_setting('ghost_threads', '[]')
    try:
        ghosts = _j.loads(raw)
    except Exception:
        ghosts = []
    return {"ghost": thread_id in ghosts}

@app.post("/api/threads/{thread_id}/ghost")
async def toggle_ghost_mode(thread_id: str):
    import json as _j
    raw = get_setting('ghost_threads', '[]')
    try:
        ghosts = set(_j.loads(raw))
    except Exception:
        ghosts = set()
    if thread_id in ghosts:
        ghosts.discard(thread_id)
        active = False
    else:
        ghosts.add(thread_id)
        active = True
    set_setting('ghost_threads', _j.dumps(list(ghosts)))
    return {"ghost": active}


# ══════════════════════════════════════════
# MÉMOIRE
# ══════════════════════════════════════════

@app.get("/api/memory/triplets")
async def memory_triplets():
    memories = get_all_memory()
    # Formater pour le frontend
    result = []
    for m in memories:
        result.append({
            'key':           m.get('key'),
            'type_mem':      m.get('type', 'trait').upper(),
            'sujet':         m.get('sujet', ''),
            'predicat':      m.get('predicat', ''),
            'valeur':        m.get('valeur', ''),
            'categorie':     m.get('categorie', 'quotidien'),
            'profondeur':    m.get('profondeur', 3),
            'type_temporal': m.get('type_temporal', 'persistant'),
            'confiance':     m.get('confiance', 1.0),
            'poids':         m.get('poids', 1.0),
            'memoire_type':  m.get('memoire_type', 'identite'),
        })
    return result

@app.put("/api/memory/{key}")
async def edit_memory(key: str, req: MemoryEdit):
    update_memory_value(key, req.valeur)
    from modules.memory import lock_memory
    lock_memory(key)
    return {"status": "ok"}

@app.post("/api/memory/audit")
async def audit_memory_route():
    """Lance l'audit memoire -- retourne {count, message}."""
    from core.hub import audit_memory
    return await audit_memory()


@app.post("/api/memory/clean")
async def clean_memory():
    """Déduplique la mémoire : fusionne les triplets sujet+predicat identiques."""
    from core.database import get_all_memory, save_memory, delete_memory
    memories = get_all_memory()
    groups = {}
    for m in memories:
        k = (m.get('sujet','').lower().strip(), m.get('predicat','').lower().strip())
        if k not in groups:
            groups[k] = []
        groups[k].append(m)

    merged = 0
    for k, group in groups.items():
        if len(group) < 2:
            continue
        # Garder celui avec le poids le plus élevé
        group.sort(key=lambda x: float(x.get('poids', 0)), reverse=True)
        keeper = dict(group[0])
        keeper['repetitions'] = sum(int(m.get('repetitions', 0)) for m in group)
        keeper['poids'] = min(float(keeper['poids']), 5.0)
        # Supprimer tous les doublons
        for m in group[1:]:
            delete_memory(m['key'])
        # Sauvegarder le survivant mis à jour
        save_memory(keeper)
        merged += len(group) - 1

    return {"merged": merged}


@app.delete("/api/memory/{key}")
async def remove_memory(key: str):
    delete_memory(key)
    return {"status": "ok"}


@app.get("/api/memory/index-theme")
async def memory_index_theme():
    """Retourne l'index thématique de la mémoire."""
    from core.database import get_memory_index_by_theme
    return get_memory_index_by_theme()

@app.get("/api/anecdotes")
async def list_anecdotes():
    """Retourne toutes les anecdotes."""
    from core.database import get_all_anecdotes
    return get_all_anecdotes()

@app.delete("/api/anecdotes/{anecdote_id}")
async def remove_anecdote(anecdote_id: int):
    from core.database import delete_anecdote
    delete_anecdote(anecdote_id)
    return {"status": "ok"}

@app.delete("/api/threads/{thread_id}/carnet/{note_number}")
async def remove_carnet_note(thread_id: str, note_number: int):
    from core.database import delete_carnet_note
    delete_carnet_note(thread_id, note_number)
    return {"status": "ok"}

@app.delete("/api/memory/all")
async def clear_all_memory_route():
    """Vide toute la memoire + rebuild FTS5."""
    from core.database import clear_all_memory
    clear_all_memory()
    return {"status": "ok"}


# ══════════════════════════════════════════
# ENRICHISSEMENT WEB (ingestion → zone de référence)
# ══════════════════════════════════════════
class EnrichText(BaseModel):
    titre: str = ""
    texte: str

class EnrichUrl(BaseModel):
    url: str

@app.get("/api/enrich/list")
async def enrich_list():
    from modules.enrichissement import list_references
    return list_references()

@app.post("/api/enrich/text")
async def enrich_text(req: EnrichText):
    import asyncio, functools, contextvars
    from modules.enrichissement import ingest_text
    fn = functools.partial(ingest_text, req.titre, req.texte, source="texte")
    ctx = contextvars.copy_context()  # propage le contexte utilisateur au thread
    return await asyncio.get_running_loop().run_in_executor(None, lambda: ctx.run(fn))

@app.post("/api/enrich/url")
async def enrich_url(req: EnrichUrl):
    """Scrape + ingère une URL. Le réseau est bloquant → exécuté dans un thread."""
    import asyncio, functools, contextvars
    from modules.enrichissement import ingest_url
    fn = functools.partial(ingest_url, req.url)
    ctx = contextvars.copy_context()  # propage le contexte utilisateur au thread
    return await asyncio.get_running_loop().run_in_executor(None, lambda: ctx.run(fn))

@app.delete("/api/enrich/{ref_id}")
async def enrich_delete(ref_id: int):
    from core.database import delete_web_reference
    return {"ok": delete_web_reference(ref_id)}

@app.post("/api/enrich/file")
async def enrich_file(file: UploadFile = File(...), force_ocr: bool = Form(False)):
    """Ingère un fichier joint (PDF, .docx, .rtf, .odt, .epub, .html, image, texte).
    PDF image / image → OCR. `force_ocr` court-circuite l'extraction de texte des PDF.
    Traitement bloquant (lecture, OCR) → exécuté dans un thread."""
    import os, tempfile, asyncio, functools, contextvars
    from modules.enrichissement import ingest_file, mistral_key_from_settings
    from core.hub import load_settings
    data = await file.read()
    settings = load_settings()
    # En mode local, on force l'OCR local (Tesseract) : on n'envoie pas la clé Mistral.
    mistral_key = mistral_key_from_settings(settings)
    suffix = os.path.splitext(file.filename or '')[1]
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    try:
        fn = functools.partial(ingest_file, tmp.name, file.filename,
                               mistral_key=mistral_key, force_ocr=force_ocr)
        ctx = contextvars.copy_context()  # propage le contexte utilisateur au thread
        return await asyncio.get_running_loop().run_in_executor(None, lambda: ctx.run(fn))
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


# ══════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════

@app.get("/api/settings/provider")
async def get_provider():
    return {"provider": get_setting('provider', 'anthropic')}

@app.post("/api/settings/provider")
async def set_provider(req: ProviderSetting):
    set_setting('provider', req.provider)
    return {"status": "ok"}

@app.get("/api/settings/mask")
async def get_mask():
    return {"mask_id": get_setting('mask_id', 'lia')}

@app.post("/api/settings/mask")
async def set_mask(req: MaskSetting):
    set_setting('mask_id', req.mask_id)
    return {"status": "ok"}

@app.get("/api/settings/model")
async def get_model_setting():
    return {"model": get_setting('chat_model', '')}

@app.post("/api/settings/model")
async def set_model_setting(req: ModelSetting):
    set_setting('chat_model', req.model)
    return {"status": "ok"}

@app.get("/api/settings/vision-provider")
async def get_vision_provider():
    return {"provider": get_setting('vision_provider', 'anthropic')}

@app.post("/api/settings/vision-provider")
async def set_vision_provider(req: VisionProviderSetting):
    set_setting('vision_provider', req.provider)
    return {"status": "ok"}

@app.get("/api/settings/routing")
async def get_routing():
    from core.hub import _load_provider_routing
    return _load_provider_routing()

@app.post("/api/settings/routing")
async def save_routing(req: RoutingSetting):
    # Lire l'existant
    raw = get_setting('provider_routing', '{}')
    try:
        current = json.loads(raw)
    except Exception:
        current = {}
    # Fusionner uniquement les champs fournis
    updates = req.dict(exclude_none=True)
    current.update(updates)
    set_setting('provider_routing', json.dumps(current))
    # Rétrocompat : sync les clés individuelles
    if 'chat'   in updates: set_setting('provider',        updates['chat'])
    if 'vision' in updates: set_setting('vision_provider', updates['vision'])
    if 'image'  in updates: set_setting('image_provider',  updates['image'])
    return {"status": "ok", "routing": current}

class PresetSaveRequest(BaseModel):
    name: str

@app.get("/api/presets")
async def get_presets():
    """Liste les préréglages enregistrés (nom -> config + date)."""
    return {"presets": list_presets()}

@app.post("/api/presets")
async def post_preset(req: PresetSaveRequest):
    """Enregistre (ou remplace) un preset à partir des réglages actuels."""
    name = (req.name or '').strip()
    if not name:
        raise HTTPException(400, "Nom de préréglage requis.")
    config = save_preset(name)
    return {"status": "ok", "name": name, "config": config}

@app.delete("/api/presets/{name}")
async def delete_preset_route(name: str):
    delete_preset(name)
    return {"status": "ok"}

@app.post("/api/presets/{name}/apply")
async def apply_preset_route(name: str):
    """Réapplique un preset enregistré aux réglages courants."""
    config = apply_preset(name)
    if config is None:
        raise HTTPException(404, "Préréglage introuvable.")
    return {"status": "ok", "config": config}

class PromptSaveRequest(BaseModel):
    id: Optional[str] = None
    label: str
    text: str
    type: Optional[str] = 'prompt'
    meta: Optional[dict] = None

@app.get("/api/prompts")
async def get_prompts(type: Optional[str] = None):
    """Liste les éléments de la Promptothèque (prompts, gabarits, scripts, tâches agent).
    Filtre optionnel par type via ?type=..."""
    return {"prompts": list_prompts(type)}

@app.post("/api/prompts")
async def post_prompt(req: PromptSaveRequest):
    """Enregistre (ou met à jour) un élément de la Promptothèque."""
    label = (req.label or '').strip()
    text = (req.text or '').strip()
    if not label or not text:
        raise HTTPException(400, "Libellé et texte requis.")
    type_ = (req.type or 'prompt').strip() or 'prompt'
    if type_ not in ('prompt', 'gabarit', 'script', 'tache_agent'):
        raise HTTPException(400, "Type invalide (prompt, gabarit, script ou tache_agent).")
    prompt = save_prompt(req.id, label, text, type_, req.meta)
    return {"status": "ok", "prompt": prompt}

@app.delete("/api/prompts/{prompt_id}")
async def delete_prompt_route(prompt_id: str):
    delete_prompt(prompt_id)
    return {"status": "ok"}


# ══════════════════════════════════════════
# COANIMM — agent d'exécution
# ══════════════════════════════════════════

def _ephemeral_scope(scope):
    """Sécurité (anti auto-grant RCE) : aucune permission d'exécution n'est
    rendue durable via les routes d'exécution. Tout 'project'/'always' reçu dans
    la requête est ramené à 'once' (exécute maintenant, ne persiste rien). Les
    accords durables par identité seront gérés à part, après cartographie."""
    return 'once' if scope in ('project', 'always') else scope


class CoanimmRunScriptRequest(BaseModel):
    script_id: str
    args: Optional[List[str]] = None
    thread_id: Optional[str] = None
    confirm_scope: Optional[str] = None  # 'once' | 'project' | 'always'

@app.post("/api/coanimm/run_script")
async def coanimm_run_script(req: CoanimmRunScriptRequest):
    """Exécute un script de la Promptothèque (type='script') dans le bac à sable
    CoaNIMM. Renvoie 'permission_required' si l'utilisateur doit d'abord accorder
    l'exécution (une fois / pour ce fil / toujours)."""
    from modules.coanimm import run_script
    if req.confirm_scope not in (None, 'once', 'project', 'always'):
        raise HTTPException(400, "confirm_scope invalide (once, project ou always).")
    return run_script(req.script_id, req.args, req.thread_id, _ephemeral_scope(req.confirm_scope))

class CoanimmPlanRequest(BaseModel):
    consigne: str
    thread_id: Optional[str] = None
    override_provider: Optional[str] = None

@app.post("/api/coanimm/plan")
async def coanimm_plan(req: CoanimmPlanRequest):
    """Génère un plan en langage naturel (sans code) pour validation par l'utilisateur."""
    from modules.coanimm import generate_plan
    if not req.consigne.strip():
        return {'status': 'error', 'message': 'La consigne est vide.'}
    try:
        result = await generate_plan(req.consigne, req.thread_id,
                                     provider_override=req.override_provider)
        return {'status': 'ok', 'plan': result['plan'], 'needs_explore': result['needs_explore']}
    except Exception as e:
        detail = str(e) or type(e).__name__
        return {'status': 'error', 'message': f"Erreur lors de la planification : {detail}"}

class CoanimmExploreRequest(BaseModel):
    consigne: str
    thread_id: Optional[str] = None
    confirm_scope: Optional[str] = None

@app.post("/api/coanimm/explore")
async def coanimm_explore(req: CoanimmExploreRequest):
    """Génère et exécute un script d'exploration (lecture seule) du disque."""
    from modules.coanimm import explore_directory
    if req.confirm_scope not in (None, 'once', 'project', 'always'):
        raise HTTPException(400, "confirm_scope invalide.")
    return await explore_directory(req.consigne, req.thread_id, _ephemeral_scope(req.confirm_scope))

class CoanimmGenerateRequest(BaseModel):
    consigne: str
    thread_id: Optional[str] = None
    confirm_scope: Optional[str] = None

@app.post("/api/coanimm/generate_and_run")
async def coanimm_generate_and_run(req: CoanimmGenerateRequest):
    """Génère un script Python à partir d'une consigne puis l'exécute dans le bac à sable."""
    from modules.coanimm import run_generated
    if req.confirm_scope not in (None, 'once', 'project', 'always'):
        raise HTTPException(400, "confirm_scope invalide.")
    return await run_generated(req.consigne, req.thread_id, _ephemeral_scope(req.confirm_scope))

class CoanimmGenerateOnlyRequest(BaseModel):
    consigne: str
    thread_id: Optional[str] = None
    explore_stdout: Optional[str] = None   # résultat d'exploration éventuel
    override_provider: Optional[str] = None

@app.post("/api/coanimm/generate")
async def coanimm_generate(req: CoanimmGenerateOnlyRequest):
    """Génère un script Python à partir d'une consigne (sans l'exécuter)."""
    from modules.coanimm import generate_code, _analyze_code_risks
    consigne = req.consigne
    if req.explore_stdout:
        consigne = f"{req.consigne}\n\n[Résultat d'exploration]\n{req.explore_stdout}"
    try:
        code = await generate_code(consigne, req.thread_id,
                                  provider_override=req.override_provider)
        risks = _analyze_code_risks(code)
        return {'status': 'ok', 'code': code, 'risks': risks}
    except Exception as e:
        import traceback
        detail = traceback.format_exc()
        print('[COANIMM][ERREUR]', detail)
        return JSONResponse({'status': 'error',
                             'message': str(e),
                             'detail': ''})  # derniers 800 car. du traceback

class CoanimmRunCodeDirectRequest(BaseModel):
    code: str
    thread_id: Optional[str] = None
    confirm_scope: Optional[str] = None  # 'once' | 'project' | 'always'
    allow_risky: Optional[bool] = False  # l'utilisateur a confirmé une capacité à risque (subprocess/réseau)
    once_caps: Optional[list] = None  # capacités accordées POUR CE LANCEMENT seulement (non persistées)

@app.post("/api/coanimm/run_code_direct")
async def coanimm_run_code_direct(req: CoanimmRunCodeDirectRequest):
    """Exécute du code Python brut (modifié par l'utilisateur) dans le bac à sable."""
    from modules.coanimm import execute_code, GENERATED_ACTION
    import core.database as _db
    if not req.code.strip():
        return {'status': 'error', 'message': 'Le code est vide.'}
    scope = _ephemeral_scope(req.confirm_scope)  # anti auto-grant RCE : pas de persistance via exécution
    if scope is None and not _db.agent_permission_granted(GENERATED_ACTION, req.thread_id):
        return {'status': 'permission_required', 'action': GENERATED_ACTION,
                'label': "exécuter le code Python"}
    return execute_code(req.code, req.thread_id)


class CoanimmGenerateImageRequest(BaseModel):
    prompt: str
    thread_id: Optional[str] = None


@app.get("/api/coanimm/test_stream")
async def coanimm_test_stream():
    """Endpoint de diagnostic : stream 5 lignes de test."""
    from fastapi.responses import StreamingResponse as SR
    import asyncio, json
    async def gen():
        for i in range(1, 6):
            yield f"data: {json.dumps({'type': 'line', 'text': f'Ligne de test {i}/5'})}\n\n"
            await asyncio.sleep(0.3)
        yield f"data: {json.dumps({'type': 'done', 'returncode': 0, 'files_list': []})}\n\n"
    return SR(gen(), media_type="text/event-stream",
              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


_COANIMM_RUNS = {}  # thread_id -> process CoaNIMM en cours (pour annulation)

@app.post("/api/coanimm/run_code_stream")
async def coanimm_run_code_stream(req: CoanimmRunCodeDirectRequest):
    """Exécute du code Python et diffuse la sortie ligne par ligne (SSE)."""
    from fastapi.responses import StreamingResponse as SR
    from modules.coanimm import (GENERATED_ACTION, _workspace_dir, _build_prologue,
                                  _check_syntax, _scan_new_files, _route_new_files,
                                  TIMEOUT_SECONDS)
    import asyncio, tempfile, sys, os
    import core.database as _db

    if not req.code.strip():
        return JSONResponse({"status": "error", "message": "Le code est vide."})
    scope = _ephemeral_scope(req.confirm_scope)  # anti auto-grant RCE : pas de persistance via exécution
    if scope is None and not _db.agent_permission_granted(GENERATED_ACTION, req.thread_id):
        return JSONResponse({"status": "permission_required", "action": GENERATED_ACTION,
                             "label": "exécuter le code Python"})

    syntax_err = _check_syntax(req.code)
    if syntax_err:
        return JSONResponse({"status": "error", "message": syntax_err})

    from modules.coanimm_safety import classify_for_execution, build_guard_prologue, capabilities_of, CAPABILITY_LABELS
    _risks = classify_for_execution(req.code)
    _all_caps = sorted(capabilities_of(req.code))
    _caps_labels = [CAPABILITY_LABELS.get(c, c) for c in _all_caps]
    if _risks["blocked"]:
        try:
            _db.add_coanimm_security_log({"status": "bloqué", "capabilities": _caps_labels,
                "reasons": [r["message"] for r in _risks["blocked"]]})
        except Exception:
            pass
        return JSONResponse({"status": "error",
            "message": "Exécution refusée pour sécurité : ce script " + " ; ".join(r["message"] for r in _risks["blocked"]) + ".",
            "blocked": _risks["blocked"]})
    # Capacités déjà accordées durablement -> on ne redemande pas (rétro-compatible :
    # si rien n'est accordé, _missing == _caps et le comportement reste identique).
    _caps_needing = set(capabilities_of(req.code)) & {"reseau", "programme", "email"}
    _granted_caps = set(_db.list_coanimm_capabilities())
    _once_caps = set(getattr(req, "once_caps", None) or []) & {"reseau", "programme", "email"}
    _effective_caps = _granted_caps | _once_caps  # durables + « pour cette fois »
    _missing_caps = _caps_needing - _effective_caps
    if _risks["needs_confirmation"] and not getattr(req, "allow_risky", False) and _missing_caps:
        return JSONResponse({"status": "confirmation_required",
            "reasons": _risks["needs_confirmation"],
            "missing_capabilities": sorted(_missing_caps),
            "message": "Ce script " + " ; ".join(r["message"] for r in _risks["needs_confirmation"]) + ". Confirmer l'exécution ?"})

    workdir = _workspace_dir(req.thread_id)
    os.makedirs(workdir, exist_ok=True)
    prologue = _build_prologue(req.thread_id, workdir)
    _allowed = _db.list_coanimm_paths()
    guard = build_guard_prologue(_allowed, allow_network=(bool(getattr(req, "allow_risky", False)) or ("reseau" in _effective_caps)))
    full_code = guard + "\n" + ((prologue + "\n" + req.code) if prologue else req.code)
    before = set(os.listdir(workdir)) if os.path.isdir(workdir) else set()

    fd, script_path = tempfile.mkstemp(suffix=".py", dir=workdir)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(full_code)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8:replace"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # le garde-fou bloquerait les .pyc

    async def stream_exec():
        proc = None
        _run_key = req.thread_id or "_global"
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-u", script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # mélanger stderr dans stdout
                cwd=workdir,
                env=env,
            )
            _COANIMM_RUNS[_run_key] = proc
            collected_lines = []
            interaction_question = None
            async def _read_and_stream():
                nonlocal interaction_question
                async for raw_line in proc.stdout:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                    collected_lines.append(line)
                    if line.startswith("__NIMM_DEMANDE__:"):
                        interaction_question = line[len("__NIMM_DEMANDE__:"):].strip()
                    yield f"data: {json.dumps({'type': 'line', 'text': line})}\n\n"
                await proc.wait()
            timed_out = False
            try:
                async for chunk in _read_and_stream():
                    yield chunk
                # wait_for pour le timeout global
                await asyncio.wait_for(proc.wait(), timeout=TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                timed_out = True
                try: proc.kill()
                except Exception: pass
                yield f"data: {json.dumps({'type': 'error', 'message': f'Délai dépassé ({TIMEOUT_SECONDS}s). Le script a été interrompu.'})}\n\n"
            if timed_out: return

            new_files = _scan_new_files(workdir, before)
            files_info, files_list = _route_new_files(new_files, req.thread_id)
            _n = len(files_list)
            if proc.returncode == 0:
                if _n:
                    _noms = ", ".join(f['filename'] for f in files_list)
                    _summary = f"Terminé. {_n} fichier{'s' if _n > 1 else ''} produit{'s' if _n > 1 else ''} : {_noms}."
                else:
                    _summary = "Terminé sans erreur. Aucun fichier produit."
            else:
                _last = ""
                for _ln in reversed(collected_lines):
                    if _ln.strip():
                        _last = _ln.strip(); break
                _summary = f"Terminé avec une erreur (code {proc.returncode})."
                if _last:
                    _summary += " Dernier message : " + _last[:200]
            try:
                _db.add_coanimm_security_log({
                    'status': 'ok' if proc.returncode == 0 else 'erreur',
                    'returncode': proc.returncode,
                    'capabilities': _caps_labels,
                    'network': ('reseau' in _effective_caps),
                    'folders': (_allowed if 'ecriture' in _all_caps else []),
                    'files': [f.get('filename', '') for f in files_list],
                })
            except Exception:
                pass
            done_payload = {'type': 'done', 'returncode': proc.returncode, 'files_list': files_list, 'summary': _summary}
            if interaction_question:
                done_payload['interaction_needed'] = {
                    'question': interaction_question,
                    'output_so_far': '\n'.join(collected_lines),
                }
            yield f"data: {json.dumps(done_payload)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            try:
                if proc is not None and proc.returncode is None:
                    proc.kill()
            except Exception:
                pass
            _COANIMM_RUNS.pop(_run_key, None)
            try:
                os.unlink(script_path)
            except Exception:
                pass

    return SR(stream_exec(), media_type="text/event-stream",
              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

class CoanimmCancelRequest(BaseModel):
    thread_id: Optional[str] = None

@app.post("/api/coanimm/cancel")
async def coanimm_cancel(req: CoanimmCancelRequest):
    """Tue le script CoaNIMM en cours d'exécution pour ce fil, s'il y en a un."""
    key = req.thread_id or "_global"
    proc = _COANIMM_RUNS.get(key)
    if proc is None:
        return {"status": "ok", "cancelled": False, "message": "Aucun script en cours."}
    try:
        proc.kill()
    except Exception as ex:
        return {"status": "error", "message": str(ex)}
    return {"status": "ok", "cancelled": True}


class CoanimmContinueRequest(BaseModel):
    thread_id: Optional[str] = None
    consigne_originale: str
    output_precedent: str
    question_posee: str
    reponse_utilisateur: str
    override_provider: Optional[str] = None

@app.post("/api/coanimm/continue")
async def coanimm_continue(req: CoanimmContinueRequest):
    """Reprend une exécution CoaNIMM après une interaction utilisateur.
    Génère un nouveau script qui tient compte de la réponse et du contexte précédent."""
    from modules.coanimm import generate_code, _analyze_code_risks
    context = (
        f"Consigne originale : {req.consigne_originale}\n\n"
        f"[Résultat de l'étape précédente]\n{req.output_precedent}\n\n"
        f"[Question posée à l'utilisateur]\n{req.question_posee}\n\n"
        f"[Réponse de l'utilisateur]\n{req.reponse_utilisateur}\n\n"
        f"Continue la tâche en tenant compte de cette réponse. "
        f"Ne réaffiche pas ce qui a déjà été fait. "
        f"Si la réponse est négative (non, annuler...), affiche un message et termine proprement."
    )
    try:
        code = await generate_code(context, req.thread_id,
                                   provider_override=req.override_provider)
        risks = _analyze_code_risks(code)
        return {'status': 'ok', 'code': code, 'risks': risks}
    except Exception as e:
        import traceback
        detail = traceback.format_exc()
        print('[COANIMM][ERREUR]', detail)
        return JSONResponse({'status': 'error', 'message': str(e), 'detail': ''})


class CoanimmRepairRequest(BaseModel):
    code: str
    error_output: str
    consigne: Optional[str] = None
    thread_id: Optional[str] = None
    override_provider: Optional[str] = None

@app.post("/api/coanimm/repair")
async def coanimm_repair(req: CoanimmRepairRequest):
    """Corrige un script CoaNIMM qui a planté, à partir de sa sortie d'erreur,
    et renvoie le code corrigé (sans l'exécuter). Utilisé par la boucle
    d'auto-réparation côté interface après un returncode non nul."""
    from modules.coanimm import repair_code, _analyze_code_risks
    if not req.code.strip():
        return {'status': 'error', 'message': 'Aucun code à réparer.'}
    try:
        code = await repair_code(req.code, req.error_output or '', req.consigne or '',
                                 req.thread_id, provider_override=req.override_provider)
        risks = _analyze_code_risks(code)
        return {'status': 'ok', 'code': code, 'risks': risks}
    except Exception as e:
        import traceback
        detail = traceback.format_exc()
        print('[COANIMM][ERREUR]', detail)
        return JSONResponse({'status': 'error', 'message': str(e), 'detail': ''})


@app.post("/api/coanimm/generate_image")
async def coanimm_generate_image_endpoint(req: CoanimmGenerateImageRequest):
    """Génère une image via le provider configuré et la sauvegarde dans le workspace CoaNIMM."""
    from core.engine import generate_image
    from core.hub import load_settings, get_task_provider_model
    from modules.coanimm import _workspace_dir
    import base64, time, mimetypes
    import core.database as _dbtool
    if "image" in _dbtool.list_coanimm_disabled_tools():
        return {"status": "error", "message": "Outil désactivé dans les réglages CoaNIMM : génération d'image."}
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(400, "Le prompt est vide.")
    settings   = load_settings(req.thread_id)
    api_keys   = settings.get("api_keys", {})
    img_provider = settings.get("provider_routing", {}).get("image", "gemini")
    try:
        result = await generate_image(req.prompt, img_provider, api_keys)
    except Exception as e:
        return {"status": "error", "message": str(e)}
    workdir  = _workspace_dir(req.thread_id)
    filename = f"nimm_img_{int(time.time())}.png"
    filepath = os.path.join(workdir, filename)
    try:
        if result.get("b64"):
            import base64 as _b64
            with open(filepath, "wb") as _f:
                _f.write(_b64.b64decode(result["b64"]))
        elif result.get("url"):
            import urllib.request as _ur
            _ur.urlretrieve(result["url"], filepath)
        else:
            return {"status": "error", "message": "Aucune donnée image reçue du provider."}
    except Exception as e:
        return {"status": "error", "message": f"Sauvegarde image échouée : {e}"}
    print(f"[COANIMM] Image générée → {filepath}")
    return {"status": "ok", "filepath": filepath, "filename": filename,
            "url": f"/api/coanimm/files/{filename}"}

class CoanimmSuggestNameRequest(BaseModel):
    consigne: str
    thread_id: Optional[str] = None

@app.post("/api/coanimm/suggest_name")
async def coanimm_suggest_name(req: CoanimmSuggestNameRequest):
    """Génère un nom court et explicite pour le script CoaNIMM."""
    from core.engine import call_llm
    from core.hub import load_settings, get_task_provider_model
    if not req.consigne.strip():
        return {"status": "ok", "name": ""}
    settings = load_settings(req.thread_id)
    provider, model = get_task_provider_model("coanimm", settings)
    api_keys = settings.get("api_keys", {})
    try:
        name = await call_llm(
            messages=[{"role": "user", "content": req.consigne}],
            provider=provider, model=model, api_keys=api_keys,
            system_prompt=(
                "Tu reçois une consigne d'automatisation. "
                "Réponds UNIQUEMENT avec un nom de script court (4 à 7 mots), "
                "clair et en français, sans ponctuation ni guillemets. "
                "Exemple de consigne : 'liste les PDF du bureau' → 'Lister les PDF du bureau'"
            ),
            max_tokens=20,
            temperature=0.3,
        )
        return {"status": "ok", "name": name.strip().strip('"').strip("'")}
    except Exception as e:
        return {"status": "ok", "name": ""}  # silencieux, le champ reste vide

class CoanimmSaveSkillRequest(BaseModel):
    consigne: str
    script: str
    thread_id: Optional[str] = None

@app.post("/api/coanimm/save_skill")
async def coanimm_save_skill(req: CoanimmSaveSkillRequest):
    """Capture la méthode d'un script validé par l'utilisateur comme fiche skill
    réutilisable. La fiche est rédigée par le LLM (SKILL_WRITER) ; le nom est auto-généré.
    Renvoie {status: created|skip|error}."""
    from modules.coanimm import write_skill
    if not (req.consigne or "").strip() and not (req.script or "").strip():
        return {"status": "error", "message": "Rien à mémoriser : consigne et script vides."}
    try:
        return await write_skill(req.consigne, req.script, req.thread_id)
    except Exception as e:
        import traceback
        print("[COANIMM][ERREUR] save_skill", traceback.format_exc())
        return JSONResponse({"status": "error", "message": str(e), "detail": ""})

class CoanimmWebSearchRequest(BaseModel):
    query: str
    thread_id: Optional[str] = None

@app.post("/api/coanimm/web_search")
async def coanimm_web_search(req: CoanimmWebSearchRequest):
    """Recherche web pour un script CoaNIMM confiné (Étape D). Réutilise l'infra Brave/
    Tavily existante (endpoint FIXE). Le script passe une REQUÊTE, jamais une URL ; le
    sous-processus ne sort jamais (il appelle ce localhost). Résultat borné en taille."""
    import core.database as _dbtool
    if "web" in _dbtool.list_coanimm_disabled_tools():
        return {"status": "ok", "result": "[Outil recherche web désactivé dans les réglages CoaNIMM]"}
    from modules.websearch import search
    q = (req.query or "").strip()
    if not q:
        return {"status": "ok", "result": "(requête vide)"}
    try:
        result = await search(q, max_results=5)
    except Exception as e:
        return {"status": "ok", "result": f"[Erreur recherche web : {e}]"}
    return {"status": "ok", "result": (result or "")[:4000]}

@app.post("/api/coanimm/github_search")
async def coanimm_github_search(req: CoanimmWebSearchRequest):
    """Recherche GitHub pour un script CoaNIMM confiné (Étape D). Endpoint FIXE
    api.github.com ; le script passe une REQUÊTE, jamais une URL. Recherche de code si
    GITHUB_TOKEN présent (en-tête d'env), sinon recherche de dépôts (API publique).
    Résultat borné en taille."""
    import core.database as _dbtool
    if "github" in _dbtool.list_coanimm_disabled_tools():
        return {"status": "ok", "result": "[Outil recherche GitHub désactivé dans les réglages CoaNIMM]"}
    import os as _os, asyncio as _aio
    import requests as _rq
    q = (req.query or "").strip()
    if not q:
        return {"status": "ok", "result": "(requête vide)"}
    token = (_os.getenv("GITHUB_TOKEN", "") or "").strip()
    def _do():
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "NIMM-CoaNIMM"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            url, code_mode = "https://api.github.com/search/code", True
        else:
            url, code_mode = "https://api.github.com/search/repositories", False
        try:
            r = _rq.get(url, params={"q": q, "per_page": 5}, headers=headers, timeout=15)
        except Exception as e:
            return f"[Erreur réseau GitHub : {e}]"
        if r.status_code != 200:
            return f"[GitHub a répondu {r.status_code}]"
        try:
            items = (r.json() or {}).get("items", [])[:5]
        except Exception:
            return "[Réponse GitHub illisible]"
        if not items:
            return "[Aucun résultat GitHub]"
        lines = []
        for it in items:
            if code_mode:
                repo = (it.get("repository") or {}).get("full_name", "?")
                lines.append(f"- {repo} : {it.get('path', '?')}\n  {it.get('html_url', '')}")
            else:
                desc = (it.get("description") or "").strip()
                lines.append(f"- {it.get('full_name', '?')} (etoiles {it.get('stargazers_count', 0)}) : {desc}\n  {it.get('html_url', '')}")
        return "\n".join(lines)
    result = await _aio.get_event_loop().run_in_executor(None, _do)
    return {"status": "ok", "result": (result or "")[:4000]}

@app.get("/api/coanimm/files/{filename}")
async def coanimm_download_file(filename: str, thread_id: str = None):
    """Télécharge un fichier produit par CoaNIMM depuis le workspace."""
    from modules.coanimm import _workspace_dir
    import mimetypes
    workdir = _workspace_dir(thread_id)
    filepath = os.path.join(workdir, os.path.basename(filename))
    if not os.path.isfile(filepath):
        raise HTTPException(404, f"Fichier introuvable : {filename}")
    mime, _ = mimetypes.guess_type(filepath)
    mime = mime or "application/octet-stream"
    return FileResponse(
        filepath,
        media_type=mime,
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

class CoanimmPathRequest(BaseModel):
    path: str

@app.get("/api/coanimm/paths")
async def coanimm_paths_list():
    """Liste les dossiers autorisés en écriture pour CoaNIMM."""
    import core.database as _db
    return {"paths": _db.list_coanimm_paths()}

@app.post("/api/coanimm/paths")
async def coanimm_paths_add(req: CoanimmPathRequest):
    """Autorise un dossier en écriture (doit exister)."""
    import core.database as _db, os as _os
    p = (req.path or "").strip()
    if not p:
        return {"status": "error", "message": "Chemin vide."}
    if not _os.path.isdir(p):
        return {"status": "error", "message": "Ce dossier n'existe pas : " + p}
    return {"status": "ok", "paths": _db.add_coanimm_path(p)}

@app.delete("/api/coanimm/paths")
async def coanimm_paths_remove(req: CoanimmPathRequest):
    """Retire un dossier autorisé."""
    import core.database as _db
    return {"status": "ok", "paths": _db.remove_coanimm_path(req.path or "")}


class CoanimmHistoryAdd(BaseModel):
    consigne: str
    status: Optional[str] = "ok"
    summary: Optional[str] = ""
    returncode: Optional[int] = None
    files_count: Optional[int] = 0

@app.get("/api/coanimm/history")
async def coanimm_history_list():
    """Journal global des tâches CoaNIMM (indépendant du fil)."""
    import core.database as _db
    return {"history": _db.list_coanimm_history()}

@app.post("/api/coanimm/history")
async def coanimm_history_add(req: CoanimmHistoryAdd):
    """Enregistre une tâche CoaNIMM terminée dans le journal."""
    import core.database as _db
    hist = _db.add_coanimm_history(req.consigne, req.status or "ok", req.summary or "",
                                   req.returncode, req.files_count or 0)
    return {"status": "ok", "history": hist}

@app.delete("/api/coanimm/history")
async def coanimm_history_clear():
    """Vide le journal des tâches CoaNIMM."""
    import core.database as _db
    _db.clear_coanimm_history()
    return {"status": "ok", "history": []}

class CoanimmWfFromHistoryReq(BaseModel):
    consignes: list = []

@app.post("/api/coanimm/workflow_from_history")
async def coanimm_workflow_from_history(req: CoanimmWfFromHistoryReq):
    """Fait correspondre des consignes (tâches de l'historique) aux skills validés
    les plus proches, pour PRÉ-composer un workflow. N'enregistre rien : renvoie la
    correspondance ; l'utilisateur valide ensuite dans le compositeur de workflow."""
    from modules.coanimm import match_skills_for_consignes
    return {"status": "ok", "matches": match_skills_for_consignes(req.consignes or [])}

class CoanimmCapabilityRequest(BaseModel):
    capability: str

@app.get("/api/coanimm/capabilities")
async def coanimm_capabilities_list():
    """Capacités accordées durablement + liste des capacités accordables (libellés)."""
    import core.database as _db
    from modules.coanimm_safety import CAPABILITY_LABELS
    grantable = [{"capability": c, "label": CAPABILITY_LABELS.get(c, c)}
                 for c in sorted(_db._COANIMM_GRANTABLE_CAPS)]
    return {"granted": _db.list_coanimm_capabilities(), "grantable": grantable,
            "is_owner": _db.is_current_user_admin()}

@app.post("/api/coanimm/capabilities")
async def coanimm_capabilities_add(req: CoanimmCapabilityRequest):
    """Accorde durablement une capacité (réseau / programme / e-mail). Réservé au propriétaire (admin)."""
    import core.database as _db
    if not _db.is_current_user_admin():
        raise HTTPException(403, detail="Seul le propriétaire (profil administrateur) peut accorder durablement une capacité. Tu peux l'autoriser « pour cette fois » au moment de l'exécution.")
    return {"status": "ok", "granted": _db.add_coanimm_capability(req.capability or "")}

@app.delete("/api/coanimm/capabilities")
async def coanimm_capabilities_remove(req: CoanimmCapabilityRequest):
    """Retire une capacité accordée. Réservé au propriétaire (admin)."""
    import core.database as _db
    if not _db.is_current_user_admin():
        raise HTTPException(403, detail="Seul le propriétaire (profil administrateur) peut retirer une capacité accordée durablement.")
    return {"status": "ok", "granted": _db.remove_coanimm_capability(req.capability or "")}

class CoanimmPreviewReq(BaseModel):
    code: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/preview")
async def coanimm_preview(req: CoanimmPreviewReq):
    """Analyse STATIQUE d'un script avant exécution (n'exécute rien) : capacités,
    dossiers d'écriture autorisés, actions bloquées/sensibles. Aperçu accessible."""
    import core.database as _db
    from modules.coanimm_safety import classify_for_execution, capabilities_of, CAPABILITY_LABELS
    code = req.code or ""
    risks = classify_for_execution(code)
    caps = capabilities_of(code)
    return {
        "capabilities": [{"capability": c, "label": CAPABILITY_LABELS.get(c, c)} for c in caps],
        "allowed_paths": (_db.list_coanimm_paths() if "ecriture" in caps else []),
        "blocked": [r.get("message", "") for r in risks.get("blocked", [])],
        "needs_confirmation": [r.get("message", "") for r in risks.get("needs_confirmation", [])],
    }

class CoanimmSkillUpdateReq(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    mots_cles: Optional[list] = None
    corps: Optional[str] = None

@app.post("/api/coanimm/skills/{skill_id}/update")
async def coanimm_skill_update(skill_id: str, req: CoanimmSkillUpdateReq):
    """Met à jour un skill validé (incrémente la version ; script et capacités préservés)."""
    from modules.coanimm import update_skill
    res = update_skill(skill_id, req.label, req.description, req.mots_cles, req.corps)
    if res.get("status") == "error":
        raise HTTPException(404, res.get("message", "Skill introuvable."))
    return res

@app.delete("/api/coanimm/skills/{skill_id}")
async def coanimm_skill_delete(skill_id: str):
    """Supprime un skill validé."""
    import core.database as _db
    _db.delete_prompt(skill_id)
    return {"status": "ok"}

@app.delete("/api/coanimm/workspace")
async def coanimm_workspace_purge():
    """Vide l'espace de travail CoaNIMM (fichiers produits). Action explicite."""
    from modules.coanimm import purge_workspace
    return purge_workspace()

# ── Journal de sécurité CoaNIMM (audit des exécutions) ──
@app.get("/api/coanimm/security_log")
async def coanimm_security_log_list():
    """Journal d'audit des exécutions CoaNIMM (date, capacités, dossiers, fichiers…)."""
    import core.database as _db
    return {"log": _db.list_coanimm_security_log(), "is_owner": _db.is_current_user_admin()}

@app.delete("/api/coanimm/security_log")
async def coanimm_security_log_clear():
    """Efface le journal de sécurité. Réservé au propriétaire (administrateur)."""
    import core.database as _db
    if not _db.is_current_user_admin():
        raise HTTPException(403, detail="Seul le propriétaire (administrateur) peut effacer le journal de sécurité.")
    _db.clear_coanimm_security_log()
    return {"status": "ok", "log": []}

# ── Catalogue d'outils CoaNIMM (activables/désactivables) ──
_COANIMM_TOOLS = [
    {"tool": "web", "label": "Recherche web", "category": "Recherche & web"},
    {"tool": "github", "label": "Recherche GitHub", "category": "Recherche & web"},
    {"tool": "read_url", "label": "Lire une page web", "category": "Recherche & web"},
    {"tool": "doc_search", "label": "Consulter la base de connaissances", "category": "Documents"},
    {"tool": "extract_text", "label": "Extraire le texte d'un document", "category": "Documents"},
    {"tool": "make_document", "label": "Créer un document accessible (docx/pdf/epub/pptx)", "category": "Documents"},
    {"tool": "merge_pdf", "label": "Fusionner des PDF", "category": "Documents"},
    {"tool": "split_pdf", "label": "Découper / extraire des pages PDF", "category": "Documents"},
    {"tool": "pdf_from_images", "label": "PDF à partir d'images", "category": "Documents"},
    {"tool": "read_table", "label": "Lire un tableau (CSV/TSV)", "category": "Documents"},
    {"tool": "transcribe", "label": "Transcrire un audio", "category": "Audio & voix"},
    {"tool": "speak", "label": "Donner la voix (texte → audio)", "category": "Audio & voix"},
    {"tool": "audio_overview", "label": "Résumé audio (2 voix)", "category": "Audio & voix"},
    {"tool": "make_daisy", "label": "Livre audio DAISY 2.02 (Victor Reader, AMIS…)", "category": "Audio & voix"},
    {"tool": "ask_llm", "label": "Sous-tâche IA", "category": "Texte & langue"},
    {"tool": "translate", "label": "Traduire", "category": "Texte & langue"},
    {"tool": "expurgate", "label": "Expurger / adapter pour enfants", "category": "Texte & langue"},
    {"tool": "simplify", "label": "Simplifier (FALC)", "category": "Texte & langue"},
    {"tool": "anonymize", "label": "Anonymiser un texte", "category": "Texte & langue"},
    {"tool": "image", "label": "Génération d'image", "category": "Images"},
    {"tool": "coloring", "label": "Coloriage (enfants)", "category": "Images"},
    {"tool": "describe_image", "label": "Décrire une image", "category": "Images"},
    {"tool": "resize_image", "label": "Redimensionner / convertir une image", "category": "Images"},
    {"tool": "qr_code", "label": "Générer un QR code (texte, URL, vCard, Wi-Fi…)", "category": "Utilitaires"},
    {"tool": "wikipedia", "label": "Rechercher sur Wikipedia / Wikimédia", "category": "Recherche & web"},
    {"tool": "wikidata", "label": "Interroger Wikidata (données structurées)", "category": "Recherche & web"},
    {"tool": "sirene", "label": "Annuaire entreprises (INSEE Sirene)", "category": "Recherche & web"},
    {"tool": "datagouv", "label": "Recherche data.gouv.fr", "category": "Recherche & web"},
    {"tool": "meteo", "label": "Météo (Open-Meteo, sans clé)", "category": "Recherche & web"},
]

class CoanimmToolToggleReq(BaseModel):
    tool: str
    enabled: bool = True

@app.get("/api/coanimm/tools")
async def coanimm_tools_list():
    """Liste les outils de l'agent et leur état (activé/désactivé)."""
    import core.database as _db
    disabled = set(_db.list_coanimm_disabled_tools())
    tools = [{"tool": t["tool"], "label": t["label"], "category": t.get("category", "Autres"),
              "enabled": t["tool"] not in disabled}
             for t in _COANIMM_TOOLS]
    return {"tools": tools}

@app.post("/api/coanimm/tools")
async def coanimm_tools_toggle(req: CoanimmToolToggleReq):
    """Active ou désactive un outil de l'agent."""
    import core.database as _db
    if req.tool not in {t["tool"] for t in _COANIMM_TOOLS}:
        raise HTTPException(400, "Outil inconnu.")
    return {"status": "ok", "disabled": _db.set_coanimm_tool_enabled(req.tool, req.enabled)}

# ── Outils CoaNIMM additionnels (lecture seule / local) ──
class CoanimmDocSearchReq(BaseModel):
    query: str = ""
    thread_id: Optional[str] = None
class CoanimmExtractTextReq(BaseModel):
    path: str = ""
    thread_id: Optional[str] = None
class CoanimmAskLlmReq(BaseModel):
    prompt: str = ""
    system: str = ""
    thread_id: Optional[str] = None
class CoanimmReadUrlReq(BaseModel):
    url: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/doc_search")
async def coanimm_doc_search(req: CoanimmDocSearchReq):
    """Interroge la base de connaissances (RAG) pour un script CoaNIMM. Local."""
    import core.database as _db
    if "doc_search" in _db.list_coanimm_disabled_tools():
        return {"result": "[Outil base de connaissances désactivé dans les réglages CoaNIMM]"}
    from modules.enrichissement import search_documents
    q = (req.query or "").strip()
    if not q:
        return {"result": "(requête vide)"}
    passages = search_documents(q, k=5)
    if not passages:
        return {"result": "[Aucun document ne correspond à cette requête.]"}
    blocs = []
    for pp in passages:
        titre = pp.get("titre") or "Document"
        src = pp.get("source") or ""
        blocs.append(f"[{titre} — {src}]\n{pp.get('passage', '')}")
    return {"result": "\n\n".join(blocs)[:6000]}

@app.post("/api/coanimm/extract_text")
async def coanimm_extract_text(req: CoanimmExtractTextReq):
    """Extrait le texte d'un document (PDF/Word/ODT/RTF/EPUB/HTML/image+OCR). Lecture seule."""
    import core.database as _db, os as _os, asyncio as _aio, functools as _ft
    if "extract_text" in _db.list_coanimm_disabled_tools():
        return {"result": "[Outil extraction de texte désactivé dans les réglages CoaNIMM]"}
    path = (req.path or "").strip()
    if not path or not _os.path.isfile(path):
        return {"result": f"[Fichier introuvable : {path}]"}
    try:
        from modules.enrichissement import extract_any, mistral_key_from_settings
        from core.hub import load_settings
        settings = load_settings(req.thread_id)
        mkey = mistral_key_from_settings(settings)
        text = await _aio.get_event_loop().run_in_executor(
            None, _ft.partial(extract_any, path, _os.path.basename(path), mistral_key=mkey))
    except Exception as e:
        return {"result": f"[Erreur extraction : {e}]"}
    return {"result": (text or "")[:200000]}

@app.post("/api/coanimm/ask_llm")
async def coanimm_ask_llm(req: CoanimmAskLlmReq):
    """Sous-tâche IA pour un script CoaNIMM : résumer/classer/traduire. Provider configuré."""
    import core.database as _db
    if "ask_llm" in _db.list_coanimm_disabled_tools():
        return {"result": "[Outil sous-tâche IA désactivé dans les réglages CoaNIMM]"}
    prompt = (req.prompt or "").strip()
    if not prompt:
        return {"result": "(prompt vide)"}
    try:
        from core.engine import call_llm
        from core.hub import load_settings
        settings = load_settings(req.thread_id)
        out = await call_llm(
            messages=[{"role": "user", "content": prompt[:12000]}],
            provider=settings.get("provider", "deepseek"),
            model=settings.get("model"),
            system_prompt=(req.system or "Tu es un assistant concis et factuel.")[:2000],
            max_tokens=1500,
            temperature=0.3,
            api_keys=settings.get("api_keys", {}),
        )
    except Exception as e:
        return {"result": f"[Erreur sous-tâche IA : {e}]"}
    return {"result": (out or "")[:8000]}

@app.post("/api/coanimm/read_url")
async def coanimm_read_url(req: CoanimmReadUrlReq):
    """Extrait le texte principal d'une URL précise (anti-SSRF via net_guard)."""
    import core.database as _db, asyncio as _aio, functools as _ft
    if "read_url" in _db.list_coanimm_disabled_tools():
        return {"result": "[Outil lecture de page web désactivé dans les réglages CoaNIMM]"}
    url = (req.url or "").strip()
    if not url:
        return {"result": "(URL vide)"}
    try:
        from modules.enrichissement import extract_url
        titre, texte = await _aio.get_event_loop().run_in_executor(
            None, _ft.partial(extract_url, url))
    except Exception as e:
        return {"result": f"[Erreur lecture URL : {e}]"}
    if not texte:
        return {"result": "[Aucun contenu exploitable à cette adresse.]"}
    head = (f"# {titre}\n" if titre else "")
    return {"result": (head + texte)[:8000]}

class CoanimmTranslateReq(BaseModel):
    text: str = ""
    target_lang: str = "anglais"
    thread_id: Optional[str] = None
class CoanimmExpurgateReq(BaseModel):
    text: str = ""
    consigne: str = ""
    thread_id: Optional[str] = None
class CoanimmColoringReq(BaseModel):
    subject: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/translate")
async def coanimm_translate(req: CoanimmTranslateReq):
    """Traduit un texte (provider configuré). Local au serveur NIMM."""
    import core.database as _db
    if "translate" in _db.list_coanimm_disabled_tools():
        return {"result": "[Outil traduction désactivé dans les réglages CoaNIMM]"}
    text = (req.text or "").strip()
    if not text:
        return {"result": "(texte vide)"}
    try:
        from core.engine import call_llm
        from core.hub import load_settings
        settings = load_settings(req.thread_id)
        out = await call_llm(
            messages=[{"role": "user", "content": text[:12000]}],
            provider=settings.get("provider", "deepseek"),
            model=settings.get("model"),
            system_prompt=f"Traduis fidèlement le texte de l'utilisateur en {req.target_lang or 'anglais'}. Conserve le sens, le registre et la mise en forme. Réponds UNIQUEMENT par la traduction, sans commentaire.",
            max_tokens=2000, temperature=0.2,
            api_keys=settings.get("api_keys", {}),
        )
    except Exception as e:
        return {"result": f"[Erreur traduction : {e}]"}
    return {"result": (out or "")[:12000]}

@app.post("/api/coanimm/expurgate")
async def coanimm_expurgate(req: CoanimmExpurgateReq):
    """Produit une version adaptée aux enfants d'un texte (expurgée, éventuellement abrégée)."""
    import core.database as _db
    if "expurgate" in _db.list_coanimm_disabled_tools():
        return {"result": "[Outil expurgation désactivé dans les réglages CoaNIMM]"}
    text = (req.text or "").strip()
    if not text:
        return {"result": "(texte vide)"}
    consigne = (req.consigne or "").strip()
    _sys = ("Tu adaptes un texte pour le rendre adapté aux enfants. Produis une version "
            "expurgée et, si demandé, abrégée : retire ou adoucis les scènes de violence "
            "explicite, de sexualité, d'horreur graphique, de cruauté, ainsi que le langage "
            "grossier, tout en PRÉSERVANT l'histoire, son fil, ses personnages et sa valeur "
            "littéraire. N'ajoute aucun contenu inventé. Conserve la langue d'origine. "
            "Réponds UNIQUEMENT par le texte adapté, sans préambule ni commentaire.")
    if consigne:
        _sys += " Consigne supplémentaire de l'utilisateur : " + consigne[:500]
    try:
        from core.engine import call_llm
        from core.hub import load_settings
        settings = load_settings(req.thread_id)
        out = await call_llm(
            messages=[{"role": "user", "content": text[:14000]}],
            provider=settings.get("provider", "deepseek"),
            model=settings.get("model"),
            system_prompt=_sys,
            max_tokens=3000, temperature=0.3,
            api_keys=settings.get("api_keys", {}),
        )
    except Exception as e:
        return {"result": f"[Erreur expurgation : {e}]"}
    return {"result": (out or "")[:16000]}

@app.post("/api/coanimm/coloring_page")
async def coanimm_coloring_page(req: CoanimmColoringReq):
    """Génère un coloriage (dessin au trait N&B) sur un sujet, sauvegardé dans le workspace."""
    import core.database as _db, os as _os, time as _time
    if "coloring" in _db.list_coanimm_disabled_tools():
        return {"status": "error", "message": "Outil coloriage désactivé dans les réglages CoaNIMM."}
    subject = (req.subject or "").strip()
    if not subject:
        return {"status": "error", "message": "Le sujet est vide."}
    from core.engine import generate_image
    from core.hub import load_settings
    from modules.coanimm import _workspace_dir
    settings = load_settings(req.thread_id)
    api_keys = settings.get("api_keys", {})
    img_provider = settings.get("provider_routing", {}).get("image", "gemini")
    prompt = ("Coloring book page, black and white line art, bold clean outlines, no shading, "
              "no grayscale, pure white background, simple and friendly, suitable for young children: " + subject)
    try:
        result = await generate_image(prompt, img_provider, api_keys)
    except Exception as e:
        return {"status": "error", "message": str(e)}
    workdir = _workspace_dir(req.thread_id)
    filename = f"coloriage_{int(_time.time())}.png"
    filepath = _os.path.join(workdir, filename)
    try:
        if result.get("b64"):
            import base64 as _b64
            with open(filepath, "wb") as _f:
                _f.write(_b64.b64decode(result["b64"]))
        elif result.get("url"):
            import urllib.request as _ur
            _ur.urlretrieve(result["url"], filepath)
        else:
            return {"status": "error", "message": "Aucune donnée image reçue du provider."}
    except Exception as e:
        return {"status": "error", "message": f"Sauvegarde échouée : {e}"}
    print(f"[COANIMM] Coloriage généré → {filepath}")
    return {"status": "ok", "filepath": filepath, "filename": filename}

class CoanimmMakeDocReq(BaseModel):
    title: str = ""
    sections: list = []
    fmt: str = "docx"
    lang: str = "fr"
    thread_id: Optional[str] = None

@app.post("/api/coanimm/make_document")
async def coanimm_make_document(req: CoanimmMakeDocReq):
    """Crée un document ACCESSIBLE (docx/pdf/epub/html/txt) dans le workspace CoaNIMM."""
    import core.database as _db, os as _os, time as _time, re as _re
    if "make_document" in _db.list_coanimm_disabled_tools():
        return {"status": "error", "message": "Outil création de document désactivé dans les réglages CoaNIMM."}
    try:
        from modules.accessible_doc import build_document
        from modules.coanimm import _workspace_dir
        data, ext = build_document(req.title or "Document", req.sections or [], fmt=req.fmt or "docx", lang=req.lang or "fr")
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": f"Erreur création document : {e}"}
    workdir = _workspace_dir(req.thread_id)
    _os.makedirs(workdir, exist_ok=True)
    base = _re.sub(r"[^\w\-]+", "_", (req.title or "document").strip())[:50] or "document"
    filename = f"{base}_{int(_time.time())}.{ext}"
    filepath = _os.path.join(workdir, filename)
    try:
        with open(filepath, "wb") as _f:
            _f.write(data)
    except Exception as e:
        return {"status": "error", "message": f"Sauvegarde échouée : {e}"}
    print(f"[COANIMM] Document généré → {filepath}")
    return {"status": "ok", "filepath": filepath, "filename": filename}

class CoanimmMakeDaisyReq(BaseModel):
    title: str = ""
    sections: list = []
    lang: str = "fr"
    voice: str = ""
    style: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/make_daisy")
async def coanimm_make_daisy(req: CoanimmMakeDaisyReq):
    """Crée un livre DAISY 2.02 (ZIP .daisy) dans le workspace CoaNIMM."""
    import core.database as _db, os as _os, time as _time, re as _re
    if "make_daisy" in _db.list_coanimm_disabled_tools():
        return {"status": "error", "message": "Outil DAISY désactivé dans les réglages CoaNIMM."}
    voice = (req.voice or "").strip()
    style = (req.style or "").strip()
    if not voice:
        voice = get_setting("tts_voice", "ff_siwis")
    if not style and voice.startswith("gemini:"):
        style = get_setting("gemini_tts_style", "")
    try:
        from modules.daisy import build_daisy
        from modules.coanimm import _workspace_dir
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None,
            lambda: build_daisy(
                req.title or "Document",
                req.sections or [],
                lang=req.lang or "fr",
                voice=voice,
                style=style,
            )
        )
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": f"Erreur création DAISY : {e}"}
    workdir = _workspace_dir(req.thread_id)
    _os.makedirs(workdir, exist_ok=True)
    base = _re.sub(r"[^\w\-]+", "_", (req.title or "livre").strip())[:50] or "livre"
    filename = f"{base}_{int(_time.time())}.daisy"
    filepath = _os.path.join(workdir, filename)
    try:
        with open(filepath, "wb") as _f:
            _f.write(data)
    except Exception as e:
        return {"status": "error", "message": f"Sauvegarde échouée : {e}"}
    print(f"[COANIMM] Livre DAISY 2.02 généré → {filepath}")
    return {"status": "ok", "filepath": filepath, "filename": filename}

class CoanimmTranscribeReq(BaseModel):
    path: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/transcribe")
async def coanimm_transcribe(req: CoanimmTranscribeReq):
    """Transcrit un fichier audio (Whisper local) pour un script CoaNIMM. Lecture seule, local."""
    import core.database as _db, os as _os, asyncio as _aio, functools as _ft
    if "transcribe" in _db.list_coanimm_disabled_tools():
        return {"result": "[Outil transcription désactivé dans les réglages CoaNIMM]"}
    path = (req.path or "").strip()
    if not path or not _os.path.isfile(path):
        return {"result": f"[Fichier introuvable : {path}]"}
    try:
        stt = get_stt()
        res = await _aio.get_event_loop().run_in_executor(None, _ft.partial(stt.transcribe_file, path))
    except Exception as e:
        return {"result": f"[Erreur transcription : {e}]"}
    if isinstance(res, dict):
        if res.get("status") == "ok":
            return {"result": (res.get("text", "") or "")[:16000]}
        return {"result": "[Erreur transcription : " + str(res.get("message") or res.get("error") or "?") + "]"}
    return {"result": str(res)[:16000]}

class CoanimmSpeakReq(BaseModel):
    text: str = ""
    voice: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/speak")
async def coanimm_speak(req: CoanimmSpeakReq):
    """Synthétise un texte en audio (TTS) et l'enregistre dans le workspace CoaNIMM."""
    import core.database as _db, os as _os, time as _time, asyncio as _aio, functools as _ft
    if "speak" in _db.list_coanimm_disabled_tools():
        return {"status": "error", "message": "Outil synthèse vocale désactivé dans les réglages CoaNIMM."}
    text = (req.text or "").strip()
    if not text:
        return {"status": "error", "message": "Le texte est vide."}
    try:
        from modules.tts import synthesize, DEFAULT_VOICE
        from modules.coanimm import _workspace_dir
        voice = (req.voice or "").strip() or DEFAULT_VOICE
        data, media = await _aio.get_event_loop().run_in_executor(
            None, _ft.partial(synthesize, text[:8000], voice))
    except Exception as e:
        return {"status": "error", "message": f"Erreur synthèse vocale : {e}"}
    if not data:
        return {"status": "error", "message": "La synthèse n'a produit aucun son (voix indisponible ?)."}
    ext = "mp3" if media == "audio/mpeg" else "wav"
    workdir = _workspace_dir(req.thread_id)
    _os.makedirs(workdir, exist_ok=True)
    filename = f"audio_{int(_time.time())}.{ext}"
    filepath = _os.path.join(workdir, filename)
    try:
        with open(filepath, "wb") as _f:
            _f.write(data)
    except Exception as e:
        return {"status": "error", "message": f"Sauvegarde échouée : {e}"}
    print(f"[COANIMM] Audio généré → {filepath}")
    return {"status": "ok", "filepath": filepath, "filename": filename}

class CoanimmDescribeImageReq(BaseModel):
    path: str = ""
    prompt: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/describe_image")
async def coanimm_describe_image(req: CoanimmDescribeImageReq):
    """Décrit une image (texte alternatif accessible) via le modèle de vision. Lecture seule."""
    import core.database as _db, os as _os, base64 as _b64
    if "describe_image" in _db.list_coanimm_disabled_tools():
        return {"result": "[Outil description d'image désactivé dans les réglages CoaNIMM]"}
    path = (req.path or "").strip()
    if not path or not _os.path.isfile(path):
        return {"result": f"[Fichier introuvable : {path}]"}
    try:
        with open(path, "rb") as _f:
            raw = _f.read()
        ext = _os.path.splitext(path)[1].lower().lstrip(".")
        media = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                 "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
        b64 = _b64.b64encode(raw).decode("ascii")
        from core.engine import call_vision
        from core.hub import load_settings
        settings = load_settings(req.thread_id)
        vprov = settings.get("provider_routing", {}).get("vision", "gemini")
        prompt = (req.prompt or "").strip() or "Décris cette image de façon précise et concise, comme un texte alternatif accessible, en français."
        out = await call_vision(b64, media, prompt, vprov, settings.get("api_keys", {}))
    except Exception as e:
        return {"result": f"[Erreur description image : {e}]"}
    return {"result": (out or "")[:6000]}

class CoanimmSimplifyReq(BaseModel):
    text: str = ""
    niveau: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/simplify")
async def coanimm_simplify(req: CoanimmSimplifyReq):
    """Réécrit un texte en langage simple (FALC — Facile À Lire et à Comprendre)."""
    import core.database as _db
    if "simplify" in _db.list_coanimm_disabled_tools():
        return {"result": "[Outil simplification désactivé dans les réglages CoaNIMM]"}
    text = (req.text or "").strip()
    if not text:
        return {"result": "(texte vide)"}
    _sys = ("Réécris le texte de l'utilisateur en FRANÇAIS FACILE À LIRE ET À COMPRENDRE (FALC) : "
            "phrases courtes (une idée par phrase), mots simples et courants, voix active, pas de jargon "
            "ni d'abréviations, explique les mots difficiles entre parenthèses, garde le sens et les "
            "informations importantes. Réponds UNIQUEMENT par le texte simplifié.")
    if (req.niveau or "").strip():
        _sys += " Niveau visé : " + req.niveau.strip()[:200] + "."
    try:
        from core.engine import call_llm
        from core.hub import load_settings
        settings = load_settings(req.thread_id)
        out = await call_llm(
            messages=[{"role": "user", "content": text[:12000]}],
            provider=settings.get("provider", "deepseek"),
            model=settings.get("model"),
            system_prompt=_sys, max_tokens=2500, temperature=0.3,
            api_keys=settings.get("api_keys", {}),
        )
    except Exception as e:
        return {"result": f"[Erreur simplification : {e}]"}
    return {"result": (out or "")[:14000]}

class CoanimmResizeImageReq(BaseModel):
    path: str = ""
    max_width: int = 1200
    fmt: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/resize_image")
async def coanimm_resize_image(req: CoanimmResizeImageReq):
    """Redimensionne et/ou convertit une image, l'enregistre dans le workspace CoaNIMM."""
    import core.database as _db, os as _os, time as _time
    if "resize_image" in _db.list_coanimm_disabled_tools():
        return {"status": "error", "message": "Outil redimensionnement d'image désactivé dans les réglages CoaNIMM."}
    path = (req.path or "").strip()
    if not path or not _os.path.isfile(path):
        return {"status": "error", "message": f"Fichier introuvable : {path}"}
    try:
        from PIL import Image
        from modules.coanimm import _workspace_dir
        img = Image.open(path)
        mw = max(16, int(req.max_width or 1200))
        if img.width > mw:
            ratio = mw / float(img.width)
            img = img.resize((mw, max(1, int(img.height * ratio))))
        fmt = (req.fmt or "").strip().lower().lstrip(".") or (_os.path.splitext(path)[1].lower().lstrip(".") or "png")
        _map = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP", "gif": "GIF", "bmp": "BMP", "tiff": "TIFF"}
        pilfmt = _map.get(fmt, "PNG")
        if pilfmt == "JPEG" and img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        workdir = _workspace_dir(req.thread_id)
        _os.makedirs(workdir, exist_ok=True)
        ext = "jpg" if pilfmt == "JPEG" else fmt
        filename = f"image_{int(_time.time())}.{ext}"
        filepath = _os.path.join(workdir, filename)
        img.save(filepath, format=pilfmt)
    except Exception as e:
        return {"status": "error", "message": f"Erreur redimensionnement : {e}"}
    print(f"[COANIMM] Image redimensionnée → {filepath}")
    return {"status": "ok", "filepath": filepath, "filename": filename}

class CoanimmAnonymizeReq(BaseModel):
    text: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/anonymize")
async def coanimm_anonymize(req: CoanimmAnonymizeReq):
    """Masque les données personnelles d'un texte (anonymisation)."""
    import core.database as _db
    if "anonymize" in _db.list_coanimm_disabled_tools():
        return {"result": "[Outil anonymisation désactivé dans les réglages CoaNIMM]"}
    text = (req.text or "").strip()
    if not text:
        return {"result": "(texte vide)"}
    _sys = ("Anonymise le texte de l'utilisateur : remplace les données personnelles "
            "(noms et prénoms de personnes, adresses postales, e-mails, numéros de téléphone, "
            "numéros de sécurité sociale, IBAN, dates de naissance, immatriculations) par des "
            "marqueurs génériques entre crochets : [NOM], [EMAIL], [TÉLÉPHONE], [ADRESSE], [DATE], etc. "
            "Garde le reste du texte intact et lisible. Réponds UNIQUEMENT par le texte anonymisé.")
    try:
        from core.engine import call_llm
        from core.hub import load_settings
        settings = load_settings(req.thread_id)
        out = await call_llm(
            messages=[{"role": "user", "content": text[:12000]}],
            provider=settings.get("provider", "deepseek"), model=settings.get("model"),
            system_prompt=_sys, max_tokens=2500, temperature=0.1,
            api_keys=settings.get("api_keys", {}),
        )
    except Exception as e:
        return {"result": f"[Erreur anonymisation : {e}]"}
    return {"result": (out or "")[:14000]}

class CoanimmMergePdfReq(BaseModel):
    paths: list = []
    name: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/merge_pdf")
async def coanimm_merge_pdf(req: CoanimmMergePdfReq):
    """Fusionne plusieurs PDF en un seul, enregistré dans le workspace CoaNIMM."""
    import core.database as _db, os as _os, time as _time, re as _re
    if "merge_pdf" in _db.list_coanimm_disabled_tools():
        return {"status": "error", "message": "Outil fusion PDF désactivé dans les réglages CoaNIMM."}
    paths = [pp for pp in (req.paths or []) if isinstance(pp, str) and pp.strip()]
    valid = [pp for pp in paths if _os.path.isfile(pp)]
    if not valid:
        return {"status": "error", "message": "Aucun fichier PDF valide fourni."}
    try:
        from pypdf import PdfWriter
        from modules.coanimm import _workspace_dir
        w = PdfWriter()
        for _pp in valid:
            w.append(_pp)
        workdir = _workspace_dir(req.thread_id)
        _os.makedirs(workdir, exist_ok=True)
        base = _re.sub(r"[^\w\-]+", "_", (req.name or "fusion").strip())[:50] or "fusion"
        filename = f"{base}_{int(_time.time())}.pdf"
        filepath = _os.path.join(workdir, filename)
        with open(filepath, "wb") as _f:
            w.write(_f)
    except Exception as e:
        return {"status": "error", "message": f"Erreur fusion PDF : {e}"}
    print(f"[COANIMM] PDF fusionné ({len(valid)}) → {filepath}")
    return {"status": "ok", "filepath": filepath, "filename": filename, "count": len(valid)}

class CoanimmSplitPdfReq(BaseModel):
    path: str = ""
    pages: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/split_pdf")
async def coanimm_split_pdf(req: CoanimmSplitPdfReq):
    """Extrait des pages d'un PDF (ex. pages='1-3,5') dans un nouveau PDF."""
    import core.database as _db, os as _os, time as _time, re as _re
    if "split_pdf" in _db.list_coanimm_disabled_tools():
        return {"status": "error", "message": "Outil découpe PDF désactivé dans les réglages CoaNIMM."}
    path = (req.path or "").strip()
    if not path or not _os.path.isfile(path):
        return {"status": "error", "message": f"Fichier introuvable : {path}"}
    try:
        from pypdf import PdfReader, PdfWriter
        from modules.coanimm import _workspace_dir
        reader = PdfReader(path)
        total = len(reader.pages)
        idx = []
        for part in (req.pages or "").split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                _a, _, _b = part.partition("-")
                try:
                    _a = int(_a); _b = int(_b)
                except Exception:
                    continue
                for _n in range(_a, _b + 1):
                    if 1 <= _n <= total:
                        idx.append(_n - 1)
            else:
                try:
                    _n = int(part)
                    if 1 <= _n <= total:
                        idx.append(_n - 1)
                except Exception:
                    continue
        if not idx:
            return {"status": "error", "message": f"Aucune page valide (le PDF a {total} page(s)). Exemple : pages='1-3,5'."}
        writer = PdfWriter()
        for _i in idx:
            writer.add_page(reader.pages[_i])
        workdir = _workspace_dir(req.thread_id)
        _os.makedirs(workdir, exist_ok=True)
        base = _re.sub(r"[^\w\-]+", "_", _os.path.splitext(_os.path.basename(path))[0])[:40] or "extrait"
        filename = f"{base}_pages_{int(_time.time())}.pdf"
        filepath = _os.path.join(workdir, filename)
        with open(filepath, "wb") as _f:
            writer.write(_f)
    except Exception as e:
        return {"status": "error", "message": f"Erreur découpe PDF : {e}"}
    return {"status": "ok", "filepath": filepath, "filename": filename, "count": len(idx)}

class CoanimmPdfFromImagesReq(BaseModel):
    paths: list = []
    name: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/pdf_from_images")
async def coanimm_pdf_from_images(req: CoanimmPdfFromImagesReq):
    """Assemble une liste d'images en un PDF (une image par page)."""
    import core.database as _db, os as _os, time as _time, re as _re
    if "pdf_from_images" in _db.list_coanimm_disabled_tools():
        return {"status": "error", "message": "Outil PDF depuis images désactivé dans les réglages CoaNIMM."}
    paths = [pp for pp in (req.paths or []) if isinstance(pp, str) and _os.path.isfile(pp)]
    if not paths:
        return {"status": "error", "message": "Aucune image valide fournie."}
    try:
        from PIL import Image
        from modules.coanimm import _workspace_dir
        imgs = [Image.open(pp).convert("RGB") for pp in paths]
        workdir = _workspace_dir(req.thread_id)
        _os.makedirs(workdir, exist_ok=True)
        base = _re.sub(r"[^\w\-]+", "_", (req.name or "document").strip())[:40] or "document"
        filename = f"{base}_{int(_time.time())}.pdf"
        filepath = _os.path.join(workdir, filename)
        imgs[0].save(filepath, "PDF", save_all=True, append_images=imgs[1:])
    except Exception as e:
        return {"status": "error", "message": f"Erreur création PDF : {e}"}
    return {"status": "ok", "filepath": filepath, "filename": filename, "count": len(paths)}

class CoanimmReadTableReq(BaseModel):
    path: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/read_table")
async def coanimm_read_table(req: CoanimmReadTableReq):
    """Lit un fichier CSV/TSV et le renvoie en tableau Markdown lisible. Lecture seule."""
    import core.database as _db, os as _os, csv as _csv
    if "read_table" in _db.list_coanimm_disabled_tools():
        return {"result": "[Outil lecture de tableau désactivé dans les réglages CoaNIMM]"}
    path = (req.path or "").strip()
    if not path or not _os.path.isfile(path):
        return {"result": f"[Fichier introuvable : {path}]"}
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as _f:
            sample = _f.read(4096)
        delim = ","
        for _d in [";", "\t", "|", ","]:
            if _d in sample:
                delim = _d
                break
        rows = []
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as _f:
            for _i, _row in enumerate(_csv.reader(_f, delimiter=delim)):
                if _i >= 200:
                    break
                rows.append(_row)
    except Exception as e:
        return {"result": f"[Erreur lecture tableau : {e}]"}
    if not rows:
        return {"result": "[Fichier vide]"}
    ncol = max(len(r) for r in rows)
    def _esc(c):
        return str(c).replace("|", "\\|").replace("\n", " ").strip()
    head = (list(rows[0]) + [""] * ncol)[:ncol]
    out = ["| " + " | ".join(_esc(c) for c in head) + " |",
           "| " + " | ".join("---" for _ in range(ncol)) + " |"]
    for _r in rows[1:]:
        _r = (list(_r) + [""] * ncol)[:ncol]
        out.append("| " + " | ".join(_esc(c) for c in _r) + " |")
    return {"result": ("\n".join(out))[:8000]}

class CoanimmAudioOverviewReq(BaseModel):
    content: str = ""
    voice1: str = ""
    voice2: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/audio_overview")
async def coanimm_audio_overview(req: CoanimmAudioOverviewReq):
    """Résumé audio façon NotebookLM : génère un dialogue à 2 voix puis le synthétise (Gemini TTS multi-locuteurs)."""
    import core.database as _db, os as _os, time as _time, asyncio as _aio, functools as _ft
    if "audio_overview" in _db.list_coanimm_disabled_tools():
        return {"status": "error", "message": "Outil résumé audio désactivé dans les réglages CoaNIMM."}
    content = (req.content or "").strip()
    if not content:
        return {"status": "error", "message": "Le contenu est vide."}
    h1, h2 = "Hôte", "Invité"
    try:
        from core.engine import call_llm
        from core.hub import load_settings
        settings = load_settings(req.thread_id)
        _sys = ("Tu écris le script d'un court podcast en français : un dialogue naturel et vivant entre "
                f"deux personnes nommées {h1} et {h2}, qui présentent et discutent le contenu fourni par "
                f"l'utilisateur. Format STRICT : chaque réplique sur sa ligne, préfixée par \"{h1}:\" ou \"{h2}:\". "
                "12 à 18 répliques, ton clair et accessible, pas de didascalies ni de texte hors dialogue. "
                f"Commence par \"{h1}:\".")
        transcript = await call_llm(
            messages=[{"role": "user", "content": content[:12000]}],
            provider=settings.get("provider", "deepseek"), model=settings.get("model"),
            system_prompt=_sys, max_tokens=2000, temperature=0.7,
            api_keys=settings.get("api_keys", {}))
    except Exception as e:
        return {"status": "error", "message": f"Erreur génération du script : {e}"}
    transcript = (transcript or "").strip()
    if not transcript:
        return {"status": "error", "message": "Le script généré est vide."}
    try:
        from modules.tts import synthesize_gemini_multi
        from modules.coanimm import _workspace_dir
        _prompt = f"Lis ce dialogue de podcast entre {h1} et {h2} :\n\n" + transcript
        wav = await _aio.get_event_loop().run_in_executor(
            None, _ft.partial(synthesize_gemini_multi, _prompt,
                              [(h1, (req.voice1 or "Charon")), (h2, (req.voice2 or "Aoede"))]))
    except Exception as e:
        return {"status": "error", "message": f"Erreur synthèse audio : {e}"}
    if not wav:
        return {"status": "error", "message": "Synthèse audio échouée (clé Gemini manquante, modèle TTS indisponible ou quota ?)."}
    workdir = _workspace_dir(req.thread_id)
    _os.makedirs(workdir, exist_ok=True)
    filename = f"resume_audio_{int(_time.time())}.wav"
    filepath = _os.path.join(workdir, filename)
    try:
        with open(filepath, "wb") as _f:
            _f.write(wav)
    except Exception as e:
        return {"status": "error", "message": f"Sauvegarde échouée : {e}"}
    print(f"[COANIMM] Résumé audio généré → {filepath}")
    return {"status": "ok", "filepath": filepath, "filename": filename, "transcript": transcript[:4000]}

@app.get("/api/settings/gemini-tts-model")
async def get_gemini_tts_model():
    return {"model": get_setting("gemini_tts_model", "gemini-2.5-flash-preview-tts")}

@app.post("/api/settings/gemini-tts-model")
async def set_gemini_tts_model(req: dict):
    m = (req.get("model") or "").strip() or "gemini-2.5-flash-preview-tts"
    set_setting("gemini_tts_model", m)
    return {"status": "ok", "model": m}

@app.get("/api/settings/gemini-tts-style")
async def get_gemini_tts_style():
    return {"style": get_setting("gemini_tts_style", "")}

@app.post("/api/settings/gemini-tts-style")
async def set_gemini_tts_style(req: dict):
    s = (req.get("style") or "").strip()
    set_setting("gemini_tts_style", s)
    return {"status": "ok"}


# ── WORKFLOWS ──────────────────────────────────────────────────────────────────

class CoanimmWorkflowRequest(BaseModel):
    label: str
    etapes: list   # [{skill_id, label}]

@app.get("/api/coanimm/workflows")
async def coanimm_workflows_list():
    """Liste les workflows enregistrés."""
    from modules.coanimm import list_workflows
    return {"workflows": list_workflows()}

@app.post("/api/coanimm/workflows")
async def coanimm_workflows_save(req: CoanimmWorkflowRequest):
    """Enregistre un nouveau workflow (séquence de skills validés)."""
    from modules.coanimm import save_workflow
    return save_workflow(req.label or "", req.etapes or [])

@app.post("/api/coanimm/workflows/{workflow_id}/run")
async def coanimm_workflows_run(workflow_id: str, thread_id: str = ""):
    """Exécute un workflow pas à pas."""
    from modules.coanimm import run_workflow
    return await run_workflow(workflow_id, thread_id or None)

@app.delete("/api/coanimm/workflows/{workflow_id}")
async def coanimm_workflows_delete(workflow_id: str):
    """Supprime un workflow."""
    import core.database as _db
    _db.delete_prompt(workflow_id)
    return {"status": "ok"}


@app.get("/api/search")
async def search_conversations_route(q: str = "", k: int = 8):
    """Recherche par sens dans l'historique des conversations (embeddings)."""
    from modules.recherche import search_conversations
    return {"resultats": search_conversations(q, k)}

@app.get("/api/settings/length")
async def get_length():
    return {"value": int(get_setting('max_tokens', '3500'))}

@app.post("/api/settings/length")
async def set_length(req: LengthSetting):
    set_setting('max_tokens', str(req.value))
    return {"status": "ok"}

@app.get("/api/settings/embeddings")
async def get_embeddings():
    return {"enabled": get_setting('embeddings_enabled', 'false') == 'true'}

@app.post("/api/settings/embeddings")
async def set_embeddings(req: dict):
    val = 'true' if req.get('enabled') else 'false'
    set_setting('embeddings_enabled', val)
    return {"status": "ok"}

@app.get("/api/settings/local-mode")
async def get_local_mode():
    return {
        "enabled": get_setting('local_mode', 'false') == 'true',
        "ollama_model": get_setting('ollama_model', 'llama3.1:8b'),
    }

@app.post("/api/settings/local-mode")
async def set_local_mode(req: dict):
    if 'enabled' in req:
        set_setting('local_mode', 'true' if req.get('enabled') else 'false')
    if req.get('ollama_model'):
        set_setting('ollama_model', str(req['ollama_model']).strip())
    return {"status": "ok"}

@app.get("/api/settings/stt-turbo")
async def get_stt_turbo():
    return {"enabled": get_setting('stt_turbo', 'false') == 'true'}

@app.post("/api/settings/stt-turbo")
async def set_stt_turbo(req: dict):
    val = req.get('value')
    if val is None:
        val = 'true' if req.get('enabled') else 'false'
    set_setting('stt_turbo', 'true' if str(val).lower() in ('true', '1') else 'false')
    return {"status": "ok"}

@app.get("/api/settings/user-genre")
async def get_user_genre():
    return {"genre": get_setting('user_genre', '')}

@app.post("/api/settings/user-genre")
async def set_user_genre(req: dict):
    g = (req.get('genre') or '').strip().lower()
    if g not in ('masculin', 'feminin', ''):
        g = ''
    set_setting('user_genre', g)
    return {"status": "ok"}

@app.get("/api/settings/search-provider")
async def get_search_provider():
    return {"provider": get_setting('search_provider', 'auto')}

@app.post("/api/settings/search-provider")
async def set_search_provider(req: dict):
    p = (req.get('provider') or 'auto').strip().lower()
    if p not in ('auto', 'brave', 'tavily'):
        p = 'auto'
    set_setting('search_provider', p)
    return {"status": "ok"}

@app.get("/api/stt/dict")
async def get_stt_dict():
    import json as _j
    raw = get_setting('stt_dict', '[]')
    try:
        return {"entries": _j.loads(raw)}
    except Exception:
        return {"entries": []}

@app.post("/api/stt/dict")
async def save_stt_dict(req: dict = Body(...)):
    import json as _j
    entries = req.get('entries', [])
    set_setting('stt_dict', _j.dumps(entries, ensure_ascii=False))
    return {"status": "ok"}

@app.get("/api/settings/stt-turbo")
async def get_stt_turbo():
    return {"enabled": get_setting('stt_turbo_enabled', 'false').lower() == 'true'}

@app.post("/api/settings/stt-turbo")
async def set_stt_turbo(req: SettingValue):
    if req.value not in ('true', 'false'):
        raise HTTPException(400, "Valeur invalide (true/false)")
    set_setting('stt_turbo_enabled', req.value)
    return {"status": "ok"}

@app.get("/api/settings/stt")
async def get_stt_settings():
    return {
        "enabled": get_setting('stt_enabled', 'true').lower() == 'true',
        "model":   get_setting('stt_model', 'base'),
    }

@app.post("/api/settings/stt")
async def set_stt_settings(req: dict):
    if 'enabled' in req:
        set_setting('stt_enabled', 'true' if req.get('enabled') else 'false')
    if req.get('model') in ('tiny', 'base', 'small', 'medium', 'large'):
        set_setting('stt_model', req['model'])
    return {"status": "ok"}

@app.get("/api/settings/presence")
async def get_presence():
    return {"value": int(get_setting('presence', '5'))}

@app.post("/api/settings/presence")
async def set_presence(req: PresenceSetting):
    set_setting('presence', str(req.value))
    return {"status": "ok"}

@app.get("/api/settings/memoire-mode")
async def get_memoire_mode():
    return {"value": get_setting('memoire_mode', 'normal')}

@app.post("/api/settings/memoire-mode")
async def set_memoire_mode(req: SettingValue):
    if req.value not in ('large', 'normal', 'strict'):
        raise HTTPException(status_code=400, detail="Valeur invalide")
    set_setting('memoire_mode', req.value)
    return {"status": "ok"}

@app.get("/api/settings/api-keys")
async def get_api_keys():
    keys = _db_get_api_keys()
    # Retourner seulement si présente (booléen) — jamais la clé elle-même
    return {p: bool(keys.get(p)) for p in ['anthropic','deepseek','gemini','openai','openrouter','mistral','stability_ai','brave','tavily']}

@app.post("/api/settings/api-keys")
async def save_api_keys(req: ApiKeysSetting):
    existing = _db_get_api_keys()
    updates = req.dict(exclude_none=True)
    existing.update({k: v for k, v in updates.items() if v})
    _db_set_api_keys(existing)
    return {"status": "ok"}


@app.get("/api/settings/global-keys")
async def get_global_keys():
    """Retourne la présence (booléen) des clés globales — jamais les valeurs."""
    import os as _os
    _gpath = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'data', 'nimm_global.json')
    global_keys = {}
    if _os.path.exists(_gpath):
        try:
            with open(_gpath, 'r', encoding='utf-8') as _f:
                global_keys = json.loads(_f.read()).get('api_keys', {})
        except Exception as _e:
            print(f"[GLOBAL-KEYS] Lecture impossible ({_gpath}) : {_e}")
    providers = ['anthropic','deepseek','gemini','openai','openrouter','mistral','stability_ai','brave','tavily']
    return {p: bool(global_keys.get(p)) for p in providers}

@app.post("/api/settings/global-keys")
async def save_global_keys(req: ApiKeysSetting):
    """Sauvegarde les clés globales dans nimm_global.json (admin uniquement)."""
    import os as _os
    _gpath = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'data', 'nimm_global.json')
    existing = {}
    if _os.path.exists(_gpath):
        try:
            with open(_gpath, 'r', encoding='utf-8') as _f:
                existing = json.loads(_f.read())
        except Exception as _e:
            # Fichier présent mais illisible : on refuse d'écrire, pour ne pas
            # écraser un contenu existant (potentiellement récupérable).
            print(f"[GLOBAL-KEYS] Lecture impossible avant écriture ({_gpath}) : {_e}")
            raise HTTPException(500, detail="Fichier de clés globales illisible — écriture annulée pour éviter une perte de données.")
    current_keys = existing.get('api_keys', {})
    updates = req.dict(exclude_none=True)
    current_keys.update({k: v for k, v in updates.items() if v})
    existing['api_keys'] = current_keys
    with open(_gpath, 'w', encoding='utf-8') as _f:
        _f.write(json.dumps(existing, ensure_ascii=False, indent=2))
    return {"status": "ok"}

@app.get("/api/settings/personality-mode")
async def get_personality_mode():
    return {"mode": get_setting('personality_mode', 'mask')}

@app.post("/api/settings/personality-mode")
async def set_personality_mode(req: dict = Body(...)):
    mode = req.get('mode', 'mask')
    if mode not in ('mask', 'potards'):
        raise HTTPException(status_code=400, detail="Mode invalide")
    set_setting('personality_mode', mode)
    return {"status": "ok"}

@app.get("/api/settings/potards")
async def get_potards():
    from core.hub import load_potards
    return load_potards()

@app.post("/api/settings/potards")
async def save_potards(req: dict = Body(...)):
    raw = get_setting('potards_settings', '{}')
    try:
        existing = json.loads(raw)
    except Exception:
        existing = {}
    existing.update(req)
    set_setting('potards_settings', json.dumps(existing))
    return {"status": "ok"}


# ══════════════════════════════════════════
# BIBLIOTHÈQUE
# ══════════════════════════════════════════

class BibliothequeCreate(BaseModel):
    thread_id: str

class BibliothequeEdit(BaseModel):
    titre:           Optional[str] = None
    sujet_principal: Optional[str] = None
    tags:            Optional[str] = None

@app.post("/api/bibliotheque")
async def archive_thread(req: BibliothequeCreate):
    """Génère un résumé narratif du fil et le sauvegarde dans la bibliothèque."""
    from core.hub import generate_bibliotheque_entry
    from core.database import save_bibliotheque_entry

    entry = await generate_bibliotheque_entry(req.thread_id)
    if not entry:
        raise HTTPException(500, "Impossible de générer le résumé.")

    entry_id = save_bibliotheque_entry(
        titre            = entry.get('titre', 'Sans titre'),
        sujet_principal  = entry.get('sujet_principal', ''),
        tags             = entry.get('tags', ''),
        resume_texte     = entry.get('resume_texte', ''),
        thread_id_source = req.thread_id,
        date_conversation= entry.get('date_conversation', ''),
        os_json          = entry.get('os_json', ''),
        os_riche         = entry.get('os_riche', ''),
        categories       = entry.get('categories', ''),
        status           = 'active',
        mask_id          = entry.get('mask_id', 'lia'),
    )
    return {"status": "ok", "id": entry_id, "titre": entry.get('titre')}

@app.get("/api/bibliotheque")
async def list_bibliotheque():
    """Retourne toutes les entrées de la bibliothèque."""
    from core.database import get_bibliotheque_entries
    return get_bibliotheque_entries()

@app.get("/api/bibliotheque/search")
async def search_bibliotheque_route(q: str = ''):
    """Recherche dans la bibliothèque."""
    from core.database import search_bibliotheque, get_bibliotheque_entries
    if not q.strip():
        return get_bibliotheque_entries()
    return search_bibliotheque(q.strip())

@app.patch("/api/bibliotheque/{entry_id}")
async def edit_bibliotheque_entry(entry_id: int, req: BibliothequeEdit):
    """Édite le titre, sujet ou tags d'une entrée."""
    from core.database import get_conn
    conn = get_conn()
    updates = {k: v for k, v in req.dict().items() if v is not None}
    if not updates:
        raise HTTPException(400, "Rien à mettre à jour.")
    fields = ', '.join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [entry_id]
    conn.execute(f"UPDATE bibliotheque SET {fields} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.delete("/api/bibliotheque/{entry_id}")
async def delete_bibliotheque_route(entry_id: int):
    """Supprime une entree de la bibliotheque."""
    from core.database import delete_bibliotheque_entry
    delete_bibliotheque_entry(entry_id)
    return {"status": "ok"}


@app.post("/api/bibliotheque/{entry_id}/reprendre")
async def reprendre_archive(entry_id: int):
    """
    Cree un nouveau fil a partir d'une entree de la bibliotheque.
    Insere le resume archive + une question de relance comme messages assistant.
    Retourne { thread_id }.
    """
    from core.database import get_bibliotheque_by_ids, create_thread, add_message, get_thread
    from core.hub import resume_from_archive

    # 1. Recuperer la fiche
    entries = get_bibliotheque_by_ids([entry_id])
    if not entries:
        raise HTTPException(404, "Entree introuvable.")
    entry = entries[0]

    # 2. Creer un nouveau thread avec le masque de la conversation d'origine
    new_thread_id = str(uuid.uuid4())
    titre = entry.get('titre', 'Reprise archive')
    create_thread(new_thread_id, f"📚 {titre}")
    _mask_id = entry.get('mask_id') or 'lia'
    set_thread_mask(new_thread_id, _mask_id, 'mask')

    # 3. Inserer le resume comme message assistant
    resume_texte = entry.get('resume_texte', '')
    nl = chr(10)
    msg_resume = "📚 **Archive — " + titre + "**" + nl + nl + resume_texte
    add_message(new_thread_id, 'assistant', msg_resume)

    # 4. Generer et inserer la question de relance
    relance = await resume_from_archive(entry)
    add_message(new_thread_id, 'assistant', relance)

    return {"thread_id": new_thread_id}


# ══════════════════════════════════════════
# RAPPELS / AGENDA
# ══════════════════════════════════════════

from core.database import (
    create_rappel, update_rappel_date, close_rappel,
    get_rappels_actifs, get_all_rappels
)

class RappelCreate(BaseModel):
    description:   str
    date_echeance: Optional[str] = None
    type_rappel:   str = 'normal'

class RappelUpdate(BaseModel):
    description:   Optional[str] = None
    date_echeance: Optional[str] = None
    type_rappel:   Optional[str] = None

@app.get("/api/rappels")
async def list_rappels(all: bool = False):
    """Retourne les rappels actifs (ou tous si ?all=true)."""
    if all:
        return get_all_rappels()
    return get_rappels_actifs()

@app.post("/api/rappels")
async def add_rappel(req: RappelCreate):
    """Crée un rappel depuis la modale agenda."""
    rid = create_rappel(req.description.strip(), req.date_echeance or None, req.type_rappel)
    return {"status": "ok", "id": rid}

@app.patch("/api/rappels/{rappel_id}")
async def edit_rappel(rappel_id: int, req: RappelUpdate):
    """Modifie description, date ou type d'un rappel existant."""
    from core.database import get_conn
    conn = get_conn()
    updates = {k: v for k, v in req.dict().items() if v is not None}
    if not updates:
        raise HTTPException(400, "Rien à mettre à jour.")
    # Renommage champ pour correspondre à la colonne DB
    if 'type_rappel' in updates:
        updates['type'] = updates.pop('type_rappel')
    fields = ', '.join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [rappel_id]
    conn.execute(f"UPDATE rappels SET {fields} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.delete("/api/rappels/{rappel_id}")
async def clos_rappel(rappel_id: int):
    """Marque un rappel comme clos (ne supprime pas — archive)."""
    close_rappel(rappel_id)
    return {"status": "ok"}


# ══════════════════════════════════════════
# MASQUES
# ══════════════════════════════════════════

@app.get("/api/masks")
async def list_masks():
    """Retourne la liste des masques disponibles depuis modules/masks/."""
    masks_dir = os.path.join(os.path.dirname(__file__), 'modules', 'masks')
    result = []
    try:
        for fname in sorted(os.listdir(masks_dir)):
            if not fname.endswith('.json'):
                continue
            mask_id = fname[:-5]  # retire .json
            fpath = os.path.join(masks_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                name  = data.get('name',  mask_id.capitalize())
                emoji = data.get('emoji', '')
                label = f"{name} {emoji}".strip()
                result.append({'id': mask_id, 'label': label})
            except Exception:
                result.append({'id': mask_id, 'label': mask_id.capitalize()})
    except Exception as e:
        return []
    return result


@app.post("/api/masks/save")
async def save_mask_from_potards(req: MaskSaveRequest):
    """Crée un masque personnalisé (fichier JSON) à partir de l'état actuel
    des curseurs (potards), pour pouvoir le réutiliser ensuite tel quel."""
    from core.hub import load_potards, build_potards_prompt

    name = req.name.strip()
    if not name:
        raise HTTPException(400, "Nom manquant.")
    emoji = (req.emoji or '🎛️').strip() or '🎛️'

    import unicodedata
    mask_id = unicodedata.normalize('NFD', name.lower())
    mask_id = ''.join(c for c in mask_id if unicodedata.category(c) != 'Mn')
    mask_id = re.sub(r'\s+', '_', mask_id)
    mask_id = re.sub(r'[^a-z0-9_]', '', mask_id) or 'masque_perso'

    masks_dir = os.path.join(os.path.dirname(__file__), 'modules', 'masks')
    os.makedirs(masks_dir, exist_ok=True)

    # Éviter d'écraser un masque existant sous le même id
    base_id = mask_id
    n = 2
    while os.path.exists(os.path.join(masks_dir, f'{mask_id}.json')):
        mask_id = f'{base_id}_{n}'
        n += 1

    potards = load_potards()
    system_prompt = build_potards_prompt(potards)

    data = {
        'name':          name,
        'emoji':         emoji,
        'id':            mask_id,
        'nom':           name,
        'system_prompt': system_prompt,
    }
    with open(os.path.join(masks_dir, f'{mask_id}.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return {'id': mask_id, 'label': f"{name} {emoji}".strip()}


# ══════════════════════════════════════════
# IDENTITÉ UTILISATEUR
# ══════════════════════════════════════════

@app.post("/api/identity")
async def set_identity(req: IdentityRequest):
    set_setting('user_name', req.name)
    return {"status": "ok"}

@app.post("/api/onboarding")
async def set_onboarding(req: OnboardingRequest):
    """Premier lancement — sauvegarde le profil de base en mémoire (verrouillé)."""
    from modules.memory import lock_memory
    from core.database import _load_users, _save_users

    name = req.name.strip()
    user_id = _slugify(name)

    # Créer le profil dans users.json s'il n'existe pas encore
    users = _load_users()
    if not any(u['id'] == user_id for u in users):
        users.append({'id': user_id, 'name': name, 'emoji': '👤', 'admin': True})
        _save_users(users)
        print(f"[ONBOARDING] Profil créé : {user_id} ({name})")

    # Basculer le contexte sur ce nouvel utilisateur et initialiser sa DB
    set_user_context(user_id)
    init_db(user_id)

    set_setting('user_name', name)

    now = datetime.now().isoformat()

    def _rec(type_, predicat, objet, categorie, profondeur, type_temporal):
        key = f"mem_{uuid.uuid4().hex[:8]}"
        return {
            'key':             key,
            'type':            type_,
            'sujet':           name,
            'predicat':        predicat,
            'objet':           objet,
            'valeur':          objet,
            'confiance':       1.0,
            'valence':         0.0,
            'sensibilite':     'neutre',
            'cumulatif':       0,
            'categorie':       categorie,
            'profondeur':      profondeur,
            'type_temporal':   type_temporal,
            'expiration':      None,
            'timestamp':       now,
            'repetitions':     0,
            'poids':           2.0,
            'embedding':       None,
            'memoire_type':    'identite',
            'last_reinforced': None,
            'contexte':        None,
            'registre':        None,
        }

    records = []
    if req.dob:
        set_setting('user_dob', req.dob)
        records.append(_rec('evenement', 'anniversaire', req.dob, 'famille', 3, 'permanent'))

    for record in records:
        save_memory(record)
        lock_memory(record['key'])

    return {"status": "ok", "saved": len(records)}

@app.get("/api/identity")
async def get_identity():
    try:
        return {"name": get_setting('user_name', '')}
    except (RuntimeError, Exception):
        return {"name": ""}

@app.get("/api/session/identity")
async def session_identity(request: Request):
    """Identité Tailscale de la requête et profil NIMM lié (pour l'écran de démarrage)."""
    import core.database as _db
    ts = getattr(request.state, 'tailscale_user', '') or ''
    return {"ts_user": ts, "mapped_user": (_db.find_user_by_ts_login(ts) if ts else None)}


# ══════════════════════════════════════════
# TTS
# ══════════════════════════════════════════

from fastapi.responses import StreamingResponse
import io

class TTSRequest(BaseModel):
    text:  str
    voice: Optional[str] = 'ff_siwis'
    style: Optional[str] = None

@app.post("/api/tts/speak")
async def tts_speak(req: TTSRequest):
    if not req.text.strip():
        raise HTTPException(400, "Texte vide.")
    try:
        import asyncio
        from modules.tts import synthesize
        loop = asyncio.get_running_loop()
        voice = req.voice or 'ff_siwis'
        # Style : priorité au champ de la requête, sinon réglage persisté (voix Gemini seulement)
        style = (req.style or "").strip()
        if not style and voice.startswith('gemini:'):
            style = get_setting("gemini_tts_style", "")
        audio_bytes, media_type = await loop.run_in_executor(
            None, synthesize, req.text, voice, style
        )
        ext = 'mp3' if 'mpeg' in media_type else 'wav'
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type=media_type,
            headers={"Content-Disposition": f"inline; filename=nimm.{ext}"}
        )
    except FileNotFoundError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Erreur TTS : {e}")

@app.get("/api/tts/voices")
async def tts_voices():
    try:
        from modules.tts import list_voices
        return {"voices": list_voices()}
    except Exception as e:
        return {"voices": [], "error": str(e)}


# ══════════════════════════════════════════
# UPLOAD — Image / PDF
# ══════════════════════════════════════════
@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    data     = await file.read()
    filename = (file.filename or '').lower()
    api_keys = {}
    try:
        import json as _json
        api_keys = _db_get_api_keys()
    except Exception:
        pass

    # PDF
    if filename.endswith('.pdf'):
        from modules.pdf_reader import extract_text
        text = extract_text(data)
        return {"type": "pdf", "text": f"[PDF : {file.filename}]\n{text[:4000]}"}

    # Image
    elif filename.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
        import base64
        from core.engine import call_vision
        from core.hub import _load_provider_routing
        b64 = base64.b64encode(data).decode()
        mt  = file.content_type or 'image/jpeg'
        vision_provider = _load_provider_routing().get('vision', 'gemini')
        try:
            desc = await call_vision(
                b64, mt,
                "Décris précisément le contenu de cette image en français.",
                vision_provider,
                api_keys
            )
            # b64 conservé pour permettre la retouche via Gemini
            return {"type": "image", "text": f"[Image : {file.filename}]\n{desc}", "b64": b64, "mime_type": mt}
        except Exception as e:
            return {"type": "error", "text": f"[Erreur analyse image : {e}]"}

    elif filename.endswith((
        '.md', '.txt', '.csv', '.py', '.json', '.js', '.ts', '.jsx', '.tsx',
        '.html', '.htm', '.css', '.xml', '.yaml', '.yml', '.toml', '.ini',
        '.sh', '.bat', '.ps1', '.sql', '.log', '.c', '.cpp', '.h', '.java',
        '.rs', '.go', '.rb', '.php', '.swift', '.kt', '.r', '.m'
    )):
        text = data.decode('utf-8', errors='replace')
        return {"type": "text", "text": f"[Fichier : {file.filename}]\n{text[:4000]}"}

    else:
        return {"type": "error", "text": "[Format non supporté — utilise une image (jpg/png/webp), un PDF ou un fichier texte/code (.py, .json, .txt, .md…)]"}


# ══════════════════════════════════════════
# GÉNÉRATION IMAGE
# ══════════════════════════════════════════

class ImageGenRequest(BaseModel):
    prompt:   str
    provider: Optional[str] = 'dall-e'

@app.post("/api/image/generate")
async def image_generate(req: ImageGenRequest):
    if not req.prompt.strip():
        raise HTTPException(400, "Prompt vide.")
    api_keys = {}
    try:
        api_keys = _db_get_api_keys()
    except Exception:
        pass
    # Lire le provider image configuré (priorité sur le paramètre de la requête)
    from core.hub import _load_provider_routing
    provider = _load_provider_routing().get('image', req.provider or 'dall-e')
    try:
        from core.engine import generate_image
        result = await generate_image(req.prompt, provider, api_keys)
        return result
    except Exception as e:
        raise HTTPException(500, f"Erreur génération image : {e}")


# ══════════════════════════════════════════
# STT
# ══════════════════════════════════════════

# Instance globale du module STT
_stt_instance = None
_stt_ready    = False

def get_stt():
    global _stt_instance
    if _stt_instance is None:
        from modules.stt import STTModule
        _stt_instance = STTModule(hub=None)
        # _stt_ready reste False — mis à True uniquement après chargement Whisper
    return _stt_instance

def _warmup_stt():
    """Préchauffage Whisper en arrière-plan au démarrage.
    _stt_ready n'est True que lorsque le modèle Whisper est effectivement chargé.
    Respecte le réglage stt_enabled : si False, skip le chargement.
    """
    global _stt_ready
    try:
        from core.database import get_setting
        stt_enabled = get_setting('stt_enabled', 'true').lower() == 'true'
        if not stt_enabled:
            print("[NIMM] STT désactivé dans les réglages -- Whisper non chargé.")
            return
        stt = get_stt()
        stt._get_model()       # charge le modèle Whisper maintenant, dans ce thread
        _stt_ready = True
        print("[NIMM] STT pret.")
    except Exception as e:
        print(f"[NIMM] STT warmup echoue : {e}")

@app.get("/api/stt/status")
async def stt_status():
    """Indique si Whisper est chargé et prêt."""
    return {"ready": _stt_ready}

class ImageEditRequest(BaseModel):
    prompt: str
    b64:    str

@app.post("/api/image/edit")
async def image_edit(req: ImageEditRequest):
    """Retouche une image existante via Gemini."""
    api_keys = {}
    try:
        import json as _json
        api_keys = _db_get_api_keys()
    except Exception:
        pass
    try:
        from core.engine import edit_gemini_image
        result = await edit_gemini_image(req.prompt, req.b64, api_keys)
        return {"b64": result.get('b64', ''), "prompt": req.prompt}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/stt/transcribe")
async def stt_transcribe(
    file:      UploadFile = File(...),
    thread_id: str        = Form(None),
    turbo:     str        = Form(None),
):
    """
    Reçoit un blob audio (webm/wav) enregistré côté client,
    le passe à Whisper dans un thread séparé pour ne pas bloquer l'event loop.
    Si turbo=true et thread_id fourni, injecte les notes du carnet comme
    initial_prompt pour améliorer la précision de la transcription.
    """
    import asyncio, tempfile, os
    stt = get_stt()

    # Construire le contexte carnet si mode turbo actif
    initial_prompt = None
    if turbo == 'true' and thread_id:
        try:
            from core.database import get_carnet_notes
            notes = get_carnet_notes(thread_id)
            if notes:
                # Les 3 dernières notes — résumé compact du contexte récent
                extrait = ' '.join(n['content'] for n in notes[-3:])
                initial_prompt = extrait[:300]
                print(f"[STT-TURBO] Contexte carnet : {initial_prompt[:80]}...")
        except Exception as e:
            print(f"[STT-TURBO] Erreur récupération carnet : {e}")

    # Sauvegarder le blob dans un fichier temporaire
    suffix = '.webm'
    if file.filename and '.' in file.filename:
        suffix = '.' + file.filename.rsplit('.', 1)[-1]

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, stt.transcribe_file, tmp_path, initial_prompt
        )
        return result

    except Exception as e:
        print(f"[STT] Erreur upload/transcription : {e}")
        return {"status": "erreur", "text": "", "error": str(e)}

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)



# ══════════════════════════════════════════
# COMPACTAGE CONTEXTE
# ══════════════════════════════════════════

@app.post("/api/threads/{thread_id}/compacter")
async def compacter(thread_id: str):
    # L'OS est généré automatiquement par hub.py
    # Cette route existe pour compatibilité frontend
    return {"status": "ok"}


# ══════════════════════════════════════════
# SUIVI DES COÛTS
# ══════════════════════════════════════════

class WalletUpdate(BaseModel):
    solde_depart: float

class RatesUpdate(BaseModel):
    rate_in:  float
    rate_out: float

@app.get("/api/costs")
async def costs_summary():
    """
    Retourne l'état des wallets providers pour lesquels une clé API est
    configurée (Ollama et Brave Search restent toujours affichés : Ollama
    est local/gratuit, Brave a un palier gratuit sans clé)."""
    from core.hub import load_settings
    settings = load_settings()
    api_keys = settings.get('api_keys', {}) or {}

    def _a_une_cle(provider: str) -> bool:
        if provider in ('ollama', 'brave'):
            return True
        key_name = 'stability_ai' if provider == 'stability-ai' else provider
        return bool(api_keys.get(key_name))

    wallets = [w for w in get_cost_summary() if _a_une_cle(w['provider'])]
    return {"wallets": wallets}

@app.post("/api/costs/reset/{provider}")
async def costs_reset(provider: str):
    """Reset manuel des compteurs d'un provider."""
    reset_wallet(provider)
    return {"status": "ok", "provider": provider}

@app.post("/api/costs/wallet/{provider}")
async def costs_wallet_update(provider: str, req: WalletUpdate):
    """Définit le solde de départ (tirelire) d'un provider."""
    update_wallet_solde(provider, req.solde_depart)
    return {"status": "ok", "provider": provider, "solde_depart": req.solde_depart}

@app.post("/api/costs/rates/{provider}")
async def costs_rates_update(provider: str, req: RatesUpdate):
    """Met à jour les tarifs ($/1M tokens) d'un provider."""
    update_wallet_rates(provider, req.rate_in, req.rate_out)
    return {"status": "ok", "provider": provider, "rate_in": req.rate_in, "rate_out": req.rate_out}

@app.get("/api/costs/credits")
async def costs_credits():
    """
    Interroge en temps réel le solde restant des providers dont l'API
    l'expose (OpenRouter, DeepSeek, Stability AI). Les autres providers
    renvoient {'available': False, 'reason': '...'}.
    """
    from core.engine import get_provider_credit, PROVIDERS_WITH_CREDIT
    from core.hub import load_settings
    settings = load_settings()
    api_keys = settings.get('api_keys', {})

    results = {}
    for provider in PROVIDERS_WITH_CREDIT:
        results[provider] = await get_provider_credit(provider, api_keys)
    return {"credits": results}


# ══════════════════════════════════════════
# MISE À JOUR AUTOMATIQUE
# ══════════════════════════════════════════

@app.get("/update")
async def update_page():
    """Page de mise à jour autonome — pour les installations sans bouton natif."""
    from fastapi.responses import HTMLResponse
    html = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mise à jour NIMM</title>
<style>
  body { font-family: system-ui, sans-serif; background: #1a1a2e; color: #e0e0e0;
         display: flex; align-items: center; justify-content: center;
         min-height: 100vh; margin: 0; }
  .card { background: #16213e; border-radius: 16px; padding: 2.5rem 3rem;
          text-align: center; max-width: 420px; box-shadow: 0 8px 32px #0005; }
  h1 { font-size: 1.4rem; margin-bottom: .4rem; }
  p  { color: #aaa; font-size: .9rem; margin-bottom: 2rem; }
  button { background: #4f8ef7; color: #fff; border: none; border-radius: 10px;
           padding: .85rem 2rem; font-size: 1rem; cursor: pointer;
           transition: background .2s; width: 100%; }
  button:hover:not(:disabled) { background: #3a7aed; }
  button:disabled { background: #555; cursor: default; }
  #status { margin-top: 1.2rem; font-size: .9rem; min-height: 1.4em; }
</style>
</head>
<body>
<div class="card">
  <h1>🔄 Mise à jour NIMM</h1>
  <p>Télécharge la dernière version depuis GitHub<br>et remplace les fichiers automatiquement.</p>
  <button id="btn">Vérifier et installer les mises à jour</button>
  <div id="status"></div>
</div>
<script>
document.getElementById('btn').addEventListener('click', async () => {
  const btn = document.getElementById('btn');
  const st  = document.getElementById('status');
  btn.disabled = true;
  btn.textContent = 'Téléchargement en cours…';
  st.textContent  = '';
  try {
    const r = await fetch('/api/update', { method: 'POST' });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      st.textContent  = '❌ Erreur : ' + (err.detail || r.status);
      btn.disabled    = false;
      btn.textContent = 'Réessayer';
      return;
    }
    st.textContent = '✅ Mise à jour appliquée ! Rechargement dans 3 secondes…';
    setTimeout(() => location.reload(), 3000);
  } catch (e) {
    st.textContent  = '❌ Impossible de joindre le serveur.';
    btn.disabled    = false;
    btn.textContent = 'Réessayer';
  }
});
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.post("/api/update")
async def do_update():
    """Télécharge la dernière version depuis GitHub et remplace les fichiers."""
    import zipfile, shutil, tempfile, pathlib

    GITHUB_REPO  = "Supaloll/NIMM"
    SKIP_DIRS    = {"data", ".git"}

    try:
        import httpx
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            r = await client.get(
                f"https://github.com/{GITHUB_REPO}/archive/refs/heads/main.zip",
                headers={"Accept": "application/zip"}
            )
            r.raise_for_status()
    except Exception as e:
        raise HTTPException(503, detail=f"Impossible de contacter GitHub : {e}")

    base = pathlib.Path(__file__).parent

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = pathlib.Path(tmp_str)
        zip_path = tmp / "update.zip"
        zip_path.write_bytes(r.content)

        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp / "src")

        extracted = [d for d in (tmp / "src").iterdir() if d.is_dir()]
        if not extracted:
            raise HTTPException(500, detail="Archive GitHub invalide")
        src = extracted[0]

        for item in src.rglob("*"):
            rel  = item.relative_to(src)
            parts = rel.parts
            if not parts or parts[0] in SKIP_DIRS:
                continue
            dst = base / rel
            if item.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dst)

    return {"status": "ok"}


# ══════════════════════════════════════════
# OLLAMA — PROXY MODÈLES
# ══════════════════════════════════════════

@app.get("/api/ollama/models")
async def ollama_models():
    """Proxy vers Ollama — évite les blocages CORS côté navigateur."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get("http://localhost:11434/api/tags")
            data = r.json()
            names = [m["name"] for m in (data.get("models") or [])]
            return {"models": names}
    except Exception as e:
        return {"models": [], "error": str(e)}


# ══════════════════════════════════════════
# UTILISATEURS
# ══════════════════════════════════════════

class UserCreate(BaseModel):
    id:    str
    name:  str
    emoji: Optional[str] = '👤'
    admin: Optional[bool] = False

class UserUpdate(BaseModel):
    name:  Optional[str] = None
    emoji: Optional[str] = None
    admin: Optional[bool] = None

@app.get("/api/users")
async def list_users():
    # Ne jamais exposer pin_hash/pin_salt — seulement la présence d'un PIN.
    out = []
    for u in get_all_users():
        out.append({
            'id': u.get('id'), 'name': u.get('name'),
            'emoji': u.get('emoji', '👤'), 'admin': u.get('admin', False),
            'has_pin': bool(u.get('pin_hash')),
            'ts_login': u.get('ts_login', ''),
        })
    return out

class PinSet(BaseModel):
    pin: str = ''
    current_pin: Optional[str] = None

@app.post("/api/users/{user_id}/set-pin")
async def set_pin(user_id: str, req: PinSet):
    import core.database as _db
    # Si un PIN existe déjà, exiger l'actuel pour le changer ou le retirer.
    if _db.user_has_pin(user_id) and not _db.verify_user_pin(user_id, req.current_pin or ''):
        raise HTTPException(403, "PIN actuel incorrect.")
    _db.set_user_pin(user_id, req.pin or '')
    return {"status": "ok", "has_pin": _db.user_has_pin(user_id)}

class PinUnlock(BaseModel):
    pin: str

@app.post("/api/users/{user_id}/unlock")
async def unlock_session(user_id: str, req: PinUnlock):
    import core.database as _db
    if _db.user_has_pin(user_id) and not _db.verify_user_pin(user_id, req.pin or ''):
        raise HTTPException(401, "PIN incorrect.")
    return {"status": "ok", "token": _db.unlock_token(user_id)}

class TsLogin(BaseModel):
    ts_login: str = ''

@app.post("/api/users/{user_id}/ts-login")
async def set_ts_login(user_id: str, req: TsLogin):
    import core.database as _db
    _db.set_user_ts_login(user_id, req.ts_login or '')
    return {"status": "ok"}

@app.post("/api/users")
async def add_user(req: UserCreate):
    try:
        user = create_user(req.id, req.name, req.emoji or '👤', req.admin or False)
        return user
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.delete("/api/users/{user_id}")
async def remove_user(user_id: str):
    try:
        delete_user(user_id)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.patch("/api/users/{user_id}")
async def edit_user(user_id: str, req: UserUpdate):
    try:
        user = update_user(user_id, req.name, req.emoji, req.admin)
        return user
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.get("/api/settings/server-mode")
async def get_server_mode():
    return {"enabled": get_setting('server_mode', 'false').lower() == 'true'}

@app.post("/api/settings/server-mode")
async def set_server_mode(req: SettingValue):
    if req.value not in ('true', 'false'):
        raise HTTPException(400, "Valeur invalide (true/false)")
    set_setting('server_mode', req.value)
    return {"status": "ok"}


# ══════════════════════════════════════════
# ══════════════════════════════════════════
# SERVICES EXTERNES — registre + clés API
# ══════════════════════════════════════════

_EXT_SERVICES = [
    # Services français (données publiques)
    {"id": "sirene",       "label": "INSEE Sirene 3.11",        "category": "France",    "needs_key": True,  "key_label": "Bearer token INSEE",     "url": "https://api.insee.fr/",                 "desc": "Annuaire entreprises SIRET/SIREN/nom"},
    {"id": "legifrance",   "label": "Légifrance (DILA)",        "category": "France",    "needs_key": True,  "key_label": "Clé PISTE (client_key)",  "url": "https://piste.gouv.fr/",                "desc": "Textes de loi, codes, jurisprudence"},
    {"id": "meteo_france", "label": "Météo-France Publique",    "category": "France",    "needs_key": True,  "key_label": "Clé API Météo-France",    "url": "https://portail-api.meteofrance.fr/",   "desc": "Observations et prévisions officielles"},
    {"id": "datagouv",     "label": "data.gouv.fr",             "category": "France",    "needs_key": False, "key_label": "",                        "url": "https://www.data.gouv.fr/api/1/",       "desc": "Open data officiel français"},
    # Données scientifiques / académiques
    {"id": "pubmed",       "label": "PubMed / NCBI",            "category": "Science",   "needs_key": False, "key_label": "Clé NCBI (optionnelle)",  "url": "https://eutils.ncbi.nlm.nih.gov/",      "desc": "Articles médicaux et scientifiques"},
    {"id": "europeana",    "label": "Europeana",                "category": "Culture",   "needs_key": True,  "key_label": "API Key",                 "url": "https://api.europeana.eu/",             "desc": "Patrimoine culturel européen numérisé"},
    {"id": "bnf",          "label": "BnF / Gallica",            "category": "Culture",   "needs_key": False, "key_label": "",                        "url": "https://gallica.bnf.fr/api/",           "desc": "Fonds numérisés Bibliothèque nationale"},
    {"id": "openlib",      "label": "Open Library (IA)",        "category": "Culture",   "needs_key": False, "key_label": "",                        "url": "https://openlibrary.org/",              "desc": "Base mondiale de livres — Internet Archive"},
    # Outils web / géo / actualités
    {"id": "opencage",     "label": "OpenCage Geocoding",       "category": "Géo",       "needs_key": True,  "key_label": "API Key",                 "url": "https://opencagedata.com/",             "desc": "Géocodage : adresses ↔ coordonnées GPS"},
    {"id": "newsapi",      "label": "NewsAPI",                  "category": "Actualités","needs_key": True,  "key_label": "API Key",                 "url": "https://newsapi.org/",                  "desc": "Actualités mondiales (100 req/jour gratuit)"},
    {"id": "deepl",        "label": "DeepL",                    "category": "Langue",    "needs_key": True,  "key_label": "Auth Key",                "url": "https://www.deepl.com/pro-api",         "desc": "Traduction professionnelle (500 000 car/mois gratuit)"},
    {"id": "wolfram",      "label": "Wolfram Alpha",            "category": "Science",   "needs_key": True,  "key_label": "App ID",                  "url": "https://products.wolframalpha.com/api/","desc": "Calculs, science, données factuelles"},
]

class ExtKeyReq(BaseModel):
    service_id: str
    key: str = ""
    label: str = ""

@app.get("/api/settings/ext-keys")
async def ext_keys_list():
    """Liste les services référencés et indique lesquels ont une clé configurée."""
    configured = {r["service_id"] for r in list_external_keys()}
    return {"services": [
        {**svc, "configured": svc["id"] in configured}
        for svc in _EXT_SERVICES
    ]}

@app.post("/api/settings/ext-keys")
async def ext_keys_set(req: ExtKeyReq):
    """Enregistre (ou supprime si key vide) une clé API externe."""
    svc_ids = {s["id"] for s in _EXT_SERVICES}
    if req.service_id not in svc_ids:
        raise HTTPException(400, f"Service inconnu : {req.service_id}")
    set_external_key(req.service_id, req.key.strip(), req.label)
    return {"status": "ok", "service_id": req.service_id, "configured": bool(req.key.strip())}

@app.delete("/api/settings/ext-keys/{service_id}")
async def ext_keys_delete(service_id: str):
    """Supprime une clé API externe."""
    delete_external_key(service_id)
    return {"status": "ok"}


# ── Outils CoaNIMM : Sirene / data.gouv / météo ──

class CoanimmSireneReq(BaseModel):
    query: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/sirene")
async def coanimm_sirene(req: CoanimmSireneReq):
    """Recherche une entreprise dans l'annuaire INSEE Sirene (SIRET/SIREN/dénomination)."""
    import core.database as _db
    if "sirene" in _db.list_coanimm_disabled_tools():
        return {"result": "[Outil Sirene désactivé]"}
    query = (req.query or "").strip()
    if not query:
        return {"result": "[Requête vide]"}
    bearer = get_external_key("sirene")
    if not bearer:
        return {"result": "[Clé INSEE Sirene non configurée — renseigner dans Paramètres > Services externes]"}
    try:
        headers = {"Authorization": f"Bearer {bearer}", "Accept": "application/json"}
        # Détecter si c'est un SIRET (14 chiffres), SIREN (9 chiffres) ou nom
        clean = query.replace(" ", "").replace("\u00a0", "")
        if clean.isdigit() and len(clean) == 14:
            url = f"https://api.insee.fr/api-sirene/3.11/siret/{clean}"
            async with _httpx.AsyncClient(timeout=10.0, headers=headers) as client:
                r = await client.get(url)
            if r.status_code == 404: return {"result": f"SIRET {clean} introuvable."}
            if r.status_code != 200: return {"result": f"Erreur INSEE : {r.status_code}"}
            d = r.json().get("etablissement", {})
            nom = (d.get("uniteLegale") or {}).get("denominationUniteLegale") or (d.get("uniteLegale") or {}).get("nomUniteLegale", "?")
            adr = " ".join(filter(None, [
                (d.get("adresseEtablissement") or {}).get("numeroVoieEtablissement", ""),
                (d.get("adresseEtablissement") or {}).get("typeVoieEtablissement", ""),
                (d.get("adresseEtablissement") or {}).get("libelleVoieEtablissement", ""),
                (d.get("adresseEtablissement") or {}).get("codePostalEtablissement", ""),
                (d.get("adresseEtablissement") or {}).get("libelleCommuneEtablissement", ""),
            ]))
            act = (d.get("uniteLegale") or {}).get("activitePrincipaleUniteLegale", "")
            return {"result": f"**{nom}**\nSIRET : {clean}\nAdresse : {adr}\nActivité (NAF) : {act}"}
        elif clean.isdigit() and len(clean) == 9:
            url = f"https://api.insee.fr/api-sirene/3.11/siren/{clean}"
            async with _httpx.AsyncClient(timeout=10.0, headers=headers) as client:
                r = await client.get(url)
            if r.status_code != 200: return {"result": f"SIREN {clean} introuvable (code {r.status_code})."}
            d = r.json().get("uniteLegale", {})
            nom = d.get("denominationUniteLegale") or d.get("nomUniteLegale", "?")
            act = d.get("activitePrincipaleUniteLegale", "")
            eff = d.get("trancheEffectifsUniteLegale", "")
            return {"result": f"**{nom}**\nSIREN : {clean}\nActivité (NAF) : {act}\nTranche effectifs : {eff}"}
        else:
            url = "https://api.insee.fr/api-sirene/3.11/siret"
            params = {"q": f"denominationUniteLegale:{query}* OR nomUniteLegale:{query}*",
                      "nombre": "5", "champs": "siret,denominationUniteLegale,nomUniteLegale,activitePrincipaleUniteLegale,codePostalEtablissement,libelleCommuneEtablissement"}
            async with _httpx.AsyncClient(timeout=10.0, headers=headers) as client:
                r = await client.get(url, params=params)
            if r.status_code != 200: return {"result": f"Erreur recherche Sirene : {r.status_code}"}
            etabs = r.json().get("etablissements", [])
            if not etabs: return {"result": f"Aucune entreprise trouvée pour \u00ab\u00a0{query}\u00a0\u00bb."}
            lines_out = [f"Résultats Sirene pour \u00ab\u00a0{query}\u00a0\u00bb :"]
            for e in etabs[:5]:
                ul = e.get("uniteLegale") or {}
                nom = ul.get("denominationUniteLegale") or ul.get("nomUniteLegale", "?")
                siret = e.get("siret", "")
                cp = e.get("codePostalEtablissement", "")
                ville = e.get("libelleCommuneEtablissement", "")
                naf = ul.get("activitePrincipaleUniteLegale", "")
                lines_out.append(f"\u2022 {nom} — SIRET {siret} — {cp} {ville} — NAF {naf}")
            return {"result": "\n".join(lines_out)}
    except Exception as e:
        return {"result": f"[Erreur Sirene : {e}]"}


class CoanimmDatagouvReq(BaseModel):
    query: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/datagouv")
async def coanimm_datagouv(req: CoanimmDatagouvReq):
    """Recherche des jeux de données sur data.gouv.fr."""
    import core.database as _db
    if "datagouv" in _db.list_coanimm_disabled_tools():
        return {"result": "[Outil data.gouv désactivé]"}
    query = (req.query or "").strip()
    if not query:
        return {"result": "[Requête vide]"}
    try:
        async with _httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "NIMM/1.0"}) as client:
            r = await client.get("https://www.data.gouv.fr/api/1/datasets/",
                                 params={"q": query, "page_size": "5", "sort": "reuse_count"})
            if r.status_code != 200:
                return {"result": f"Erreur data.gouv : {r.status_code}"}
            data = r.json()
        datasets = (data.get("data") or [])
        if not datasets:
            return {"result": f"Aucun jeu de données trouvé pour \u00ab\u00a0{query}\u00a0\u00bb."}
        lines_out = [f"Jeux de données data.gouv.fr pour \u00ab\u00a0{query}\u00a0\u00bb :"]
        for ds in datasets[:5]:
            title = ds.get("title", "?")
            org   = (ds.get("organization") or {}).get("name", ds.get("owner") or "")
            descr = (ds.get("description") or "")[:120].replace("\n", " ")
            url   = f"https://www.data.gouv.fr/fr/datasets/{ds.get('id', '')}"
            reuses = ds.get("metrics", {}).get("reuses", 0)
            lines_out.append(f"\u2022 **{title}**" + (f" ({org})" if org else "") + f"\n  {descr}...\n  {url} ({reuses} réutilisations)")
        return {"result": "\n\n".join(lines_out)}
    except Exception as e:
        return {"result": f"[Erreur data.gouv : {e}]"}


class CoanimmMeteoReq(BaseModel):
    location: str = ""
    days: int = 3
    thread_id: Optional[str] = None

@app.post("/api/coanimm/meteo")
async def coanimm_meteo(req: CoanimmMeteoReq):
    """Météo pour une ville ou des coordonnées, via Open-Meteo (sans clé API)."""
    import core.database as _db, urllib.parse as _up
    if "meteo" in _db.list_coanimm_disabled_tools():
        return {"result": "[Outil météo désactivé]"}
    location = (req.location or "").strip()
    if not location:
        return {"result": "[Lieu non précisé]"}
    _WMO = {0:"dégagé",1:"principalement dégagé",2:"partiellement nuageux",3:"couvert",
            45:"brouillard",48:"brouillard givrant",51:"bruine légère",53:"bruine modérée",
            55:"bruine dense",61:"pluie légère",63:"pluie modérée",65:"pluie forte",
            71:"neige légère",73:"neige modérée",75:"neige forte",
            80:"averses légères",81:"averses modérées",82:"averses violentes",
            95:"orage",96:"orage + grêle",99:"orage + forte grêle"}
    try:
        async with _httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "NIMM/1.0"}) as client:
            # Géocodage via Nominatim (OSM)
            geo = await client.get("https://nominatim.openstreetmap.org/search",
                                   params={"q": location, "format": "json", "limit": "1"})
            places = geo.json()
            if not places:
                return {"result": f"Lieu introuvable : {location}"}
            lat  = float(places[0]["lat"])
            lon  = float(places[0]["lon"])
            name = places[0].get("display_name", location).split(",")[0]
            days = max(1, min(int(req.days or 3), 7))
            # Open-Meteo forecast
            wx = await client.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": lat, "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                "timezone": "auto", "forecast_days": days})
            wd = wx.json().get("daily", {})
        dates  = wd.get("time", [])
        t_max  = wd.get("temperature_2m_max", [])
        t_min  = wd.get("temperature_2m_min", [])
        precip = wd.get("precipitation_sum", [])
        codes  = wd.get("weathercode", [])
        lines_out = [f"Météo à **{name}** pour {days} jour(s) :"]
        for i, d in enumerate(dates):
            wmo = _WMO.get(int(codes[i]) if i < len(codes) else 0, "?")
            prec = f"{precip[i]:.1f} mm" if i < len(precip) else "?"
            tmax = f"{t_max[i]:.0f}°C" if i < len(t_max) else "?"
            tmin = f"{t_min[i]:.0f}°C" if i < len(t_min) else "?"
            lines_out.append(f"  {d} : {tmax}/{tmin} — {wmo} — {prec} pluie")
        lines_out.append(f"Source : Open-Meteo (lat={lat:.2f}, lon={lon:.2f})")
        return {"result": "\n".join(lines_out)}
    except Exception as e:
        return {"result": f"[Erreur météo : {e}]"}


# ═══════════════════
# QR CODES + WIKIMEDIA
# ═══════════════════

class CoanimmQrCodeReq(BaseModel):
    content: str = ""
    qr_type: str = "text"        # text | url | vcard | wifi | email | sms | geo
    name: str = ""               # vCard : nom complet
    vcard_phone: str = ""
    vcard_email: str = ""
    vcard_org: str = ""
    vcard_url: str = ""
    vcard_note: str = ""
    wifi_ssid: str = ""
    wifi_password: str = ""
    wifi_security: str = "WPA"   # WPA | WEP | nopass
    thread_id: Optional[str] = None

@app.post("/api/coanimm/qr_code")
async def coanimm_qr_code(req: CoanimmQrCodeReq):
    """Génère un QR code et l’enregistre dans le workspace CoaNIMM."""
    import core.database as _db, os as _os, time as _time
    if "qr_code" in _db.list_coanimm_disabled_tools():
        return {"status": "error", "message": "Outil QR code désactivé dans les réglages CoaNIMM."}
    try:
        import qrcode
        from modules.coanimm import _workspace_dir
        qr_type = (req.qr_type or "text").lower().strip()
        if qr_type == "vcard":
            parts_v = ["BEGIN:VCARD", "VERSION:3.0"]
            if req.name:        parts_v.append(f"FN:{req.name}")
            if req.vcard_phone: parts_v.append(f"TEL:{req.vcard_phone}")
            if req.vcard_email: parts_v.append(f"EMAIL:{req.vcard_email}")
            if req.vcard_org:   parts_v.append(f"ORG:{req.vcard_org}")
            if req.vcard_url:   parts_v.append(f"URL:{req.vcard_url}")
            if req.vcard_note:  parts_v.append(f"NOTE:{req.vcard_note}")
            parts_v.append("END:VCARD")
            data = "\n".join(parts_v)
        elif qr_type == "wifi":
            ssid = req.wifi_ssid or req.content
            pwd  = req.wifi_password
            sec  = req.wifi_security or "WPA"
            data = f"WIFI:T:{sec};S:{ssid};P:{pwd};;"
        elif qr_type == "email":
            data = f"mailto:{req.content}"
        elif qr_type == "sms":
            data = f"sms:{req.content}"
        elif qr_type == "geo":
            data = f"geo:{req.content}"
        else:
            data = req.content
        if not data.strip():
            return {"status": "error", "message": "Contenu vide pour le QR code."}
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        workdir = _workspace_dir(req.thread_id)
        _os.makedirs(workdir, exist_ok=True)
        filename = f"qr_{qr_type}_{int(_time.time())}.png"
        filepath = _os.path.join(workdir, filename)
        img.save(filepath)
    except Exception as e:
        return {"status": "error", "message": f"Erreur QR code : {e}"}
    print(f"[COANIMM] QR code ({qr_type}) -> {filepath}")
    return {"status": "ok", "filepath": filepath, "filename": filename, "qr_type": qr_type}


class CoanimmWikipediaReq(BaseModel):
    query: str = ""
    lang: str = "fr"
    sentences: int = 5
    thread_id: Optional[str] = None

@app.post("/api/coanimm/wikipedia")
async def coanimm_wikipedia(req: CoanimmWikipediaReq):
    """Recherche un article Wikipedia et retourne un résumé accessible."""
    import core.database as _db, urllib.parse as _up, re as _re
    if "wikipedia" in _db.list_coanimm_disabled_tools():
        return {"result": "[Outil Wikipedia désactivé]"}
    query = (req.query or "").strip()
    if not query:
        return {"result": "[Requ\u00eate vide]"}
    lang = (req.lang or "fr").strip().lower()[:5]
    try:
        async with _httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "NIMM/1.0"}) as client:
            r = await client.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={"action": "query", "list": "search", "srsearch": query,
                        "srlimit": "1", "format": "json"})
            results = (r.json().get("query") or {}).get("search") or []
            if not results:
                return {"result": f"Aucun article Wikipedia trouv\u00e9 pour \u00ab\u00a0{query}\u00a0\u00bb."}
            title = results[0]["title"]
            r2 = await client.get(
                f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{_up.quote(title.replace(' ', '_'))}",
                headers={"User-Agent": "NIMM/1.0"})
            if r2.status_code != 200:
                return {"result": f"Article Wikipedia \u00ab\u00a0{title}\u00a0\u00bb introuvable."}
            s = r2.json()
        extract     = s.get("extract") or ""
        description = s.get("description") or ""
        url = (s.get("content_urls") or {}).get("desktop", {}).get("page", "")
        sents = _re.split(r'(?<=[.!?])\s+', extract.strip())
        n = max(1, min(int(req.sentences or 5), 20))
        text = " ".join(sents[:n])
        result = f"**{title}**"
        if description: result += f" ({description})"
        result += f"\n\n{text}"
        if url: result += f"\n\nSource\u00a0: {url}"
        return {"result": result, "title": title, "url": url}
    except Exception as e:
        return {"result": f"[Erreur Wikipedia\u00a0: {e}]"}


class CoanimmWikidataReq(BaseModel):
    query: str = ""
    thread_id: Optional[str] = None

@app.post("/api/coanimm/wikidata")
async def coanimm_wikidata(req: CoanimmWikidataReq):
    """Recherche une entité Wikidata et retourne ses propriétés principales."""
    import core.database as _db
    if "wikidata" in _db.list_coanimm_disabled_tools():
        return {"result": "[Outil Wikidata désactivé]"}
    query = (req.query or "").strip()
    if not query:
        return {"result": "[Requ\u00eate vide]"}
    WD = "https://www.wikidata.org/w/api.php"
    try:
        async with _httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "NIMM/1.0"}) as client:
            r = await client.get(WD, params={
                "action": "wbsearchentities", "search": query,
                "language": "fr", "limit": "3", "format": "json"})
            results = r.json().get("search") or []
            if not results:
                return {"result": f"Aucune entit\u00e9 Wikidata trouv\u00e9e pour \u00ab\u00a0{query}\u00a0\u00bb."}
            lines_out = [f"R\u00e9sultats Wikidata pour \u00ab\u00a0{query}\u00a0\u00bb\u00a0:"]
            for it in results[:3]:
                qid_   = it.get("id", "")
                label_ = it.get("label", qid_)
                desc_  = it.get("description", "")
                lines_out.append(
                    f"\u2022 {label_} ({qid_})" + (f"\u00a0\u2014 {desc_}" if desc_ else "")
                    + f"\n  https://www.wikidata.org/wiki/{qid_}")
            first_qid = results[0].get("id")
            if first_qid:
                r2 = await client.get(WD, params={
                    "action": "wbgetentities", "ids": first_qid,
                    "languages": "fr|en", "props": "claims", "format": "json"})
                claims = ((r2.json().get("entities") or {}).get(first_qid) or {}).get("claims") or {}
                key_props = {
                    "P31": "Type", "P17": "Pays", "P571": "Fondé le",
                    "P569": "Naissance", "P570": "Décès",
                    "P19": "Lieu de naissance", "P106": "Profession",
                }
                prop_lines = []
                for pid, plabel in key_props.items():
                    if pid not in claims: continue
                    sv = (claims[pid][0].get("mainsnak") or {}).get("datavalue") or {}
                    vtype = sv.get("type"); val = sv.get("value")
                    if vtype == "string":
                        prop_lines.append(f"  {plabel}\u00a0: {val}")
                    elif vtype == "wikibase-entityid":
                        eid = (val or {}).get("id", "?")
                        prop_lines.append(f"  {plabel}\u00a0: {eid}")
                    elif vtype == "time" and isinstance(val, dict):
                        t = val.get("time", "")[:11].lstrip("+")
                        prop_lines.append(f"  {plabel}\u00a0: {t}")
                if prop_lines:
                    lbl0 = results[0].get("label", first_qid)
                    lines_out.append(f"\nPropri\u00e9t\u00e9s de {lbl0}\u00a0:")
                    lines_out.extend(prop_lines)
        return {"result": "\n".join(lines_out)}
    except Exception as e:
        return {"result": f"[Erreur Wikidata\u00a0: {e}]"}


# GALERIE IMAGES
# ══════════════════════════════════════════

_IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'images')
os.makedirs(_IMAGES_DIR, exist_ok=True)

class ImageSaveRequest(BaseModel):
    b64:       str = ''
    url:       str = ''
    prompt:    str = ''
    thread_id: str = ''

class ImageRenameRequest(BaseModel):
    filename: str

@app.post("/api/images/save")
async def images_save(req: ImageSaveRequest):
    """Sauvegarde une image (b64 ou url) sur disque + DB. Retourne id + filename."""
    import re as _re
    ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:20]
    filename = f"nimm_{ts}.png"
    filepath = os.path.join(_IMAGES_DIR, filename)
    try:
        if req.b64:
            b64_data = req.b64
            if ',' in b64_data:
                b64_data = b64_data.split(',', 1)[1]
            img_bytes = _base64.b64decode(b64_data)
            with open(filepath, 'wb') as f:
                f.write(img_bytes)
        elif req.url:
            async with _httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(req.url)
                r.raise_for_status()
                with open(filepath, 'wb') as f:
                    f.write(r.content)
        else:
            raise HTTPException(400, "b64 ou url requis")
        img_id = save_image(filename, req.prompt, req.thread_id)
        return {"id": img_id, "filename": filename}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/images")
async def images_list():
    """Retourne toutes les images de la galerie."""
    return get_images()


@app.get("/api/images/file/{filename}")
async def images_file(filename: str):
    """Sert un fichier image depuis le dossier data/images/."""
    filepath = os.path.join(_IMAGES_DIR, filename)
    if not os.path.isfile(filepath):
        raise HTTPException(404, "Image introuvable")
    return FileResponse(filepath)


@app.patch("/api/images/{img_id}")
async def images_rename(img_id: int, req: ImageRenameRequest):
    """Renomme une image (nom DB uniquement)."""
    ok = rename_image(img_id, req.filename)
    if not ok:
        raise HTTPException(404, "Image introuvable")
    return {"status": "ok", "filename": req.filename}


@app.delete("/api/images/{img_id}")
async def images_delete(img_id: int):
    """Supprime une image (DB + fichier disque)."""
    filename = delete_image(img_id)
    if not filename:
        raise HTTPException(404, "Image introuvable")
    filepath = os.path.join(_IMAGES_DIR, filename)
    if os.path.isfile(filepath):
        os.remove(filepath)
    return {"status": "ok"}
