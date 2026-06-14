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
from fastapi import FastAPI, HTTPException, UploadFile, File, Body, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict

import os as _os_main
import base64 as _base64
import httpx as _httpx

from core.database import (
    init_db, get_threads, get_thread, create_thread, delete_thread, set_thread_mask,
    update_thread_name, get_messages, add_message, count_messages,
    get_setting, set_setting, get_all_memory, delete_memory,
    update_memory_value, save_memory,
    get_cost_summary, reset_wallet, update_wallet_rates, update_wallet_solde,
    check_auto_resets,
    set_user_context, get_current_user,
    get_all_users, create_user, delete_user, update_user,
    save_image, get_images, rename_image, delete_image
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
    name: str

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
    update_thread_name(thread_id, req.name)
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
    from modules.enrichissement import ingest_file
    from core.hub import load_settings
    data = await file.read()
    settings = load_settings()
    # En mode local, on force l'OCR local (Tesseract) : on n'envoie pas la clé Mistral.
    mistral_key = None if settings.get('local_mode') else (settings.get('api_keys') or {}).get('mistral')
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
    raw = get_setting('api_keys', '{}')
    try:
        keys = json.loads(raw)
    except Exception:
        keys = {}
    # Retourner seulement si présente (booléen) — jamais la clé elle-même
    return {p: bool(keys.get(p)) for p in ['anthropic','deepseek','gemini','openai','openrouter','mistral','stability_ai','brave','tavily']}

@app.post("/api/settings/api-keys")
async def save_api_keys(req: ApiKeysSetting):
    raw = get_setting('api_keys', '{}')
    try:
        existing = json.loads(raw)
    except Exception:
        existing = {}
    updates = req.dict(exclude_none=True)
    existing.update({k: v for k, v in updates.items() if v})
    set_setting('api_keys', json.dumps(existing))
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


# ══════════════════════════════════════════
# TTS
# ══════════════════════════════════════════

from fastapi.responses import StreamingResponse
import io

class TTSRequest(BaseModel):
    text:  str
    voice: Optional[str] = 'ff_siwis'

@app.post("/api/tts/speak")
async def tts_speak(req: TTSRequest):
    if not req.text.strip():
        raise HTTPException(400, "Texte vide.")
    try:
        import asyncio
        from modules.tts import synthesize
        loop = asyncio.get_running_loop()
        audio_bytes, media_type = await loop.run_in_executor(
            None, synthesize, req.text, req.voice or 'ff_siwis'
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
        api_keys = _json.loads(get_setting('api_keys', '{}'))
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
        api_keys = json.loads(get_setting('api_keys', '{}'))
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
        api_keys = _json.loads(get_setting('api_keys', '{}'))
    except Exception:
        pass
    try:
        from core.engine import edit_gemini_image
        result = await edit_gemini_image(req.prompt, req.b64, api_keys)
        return {"b64": result.get('b64', ''), "prompt": req.prompt}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/stt/transcribe")
async def stt_transcribe(file: UploadFile = File(...)):
    """
    Reçoit un blob audio (webm/wav) enregistré côté client,
    le passe à Whisper dans un thread séparé pour ne pas bloquer l'event loop.
    """
    import asyncio, tempfile, os
    stt = get_stt()

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
        result = await loop.run_in_executor(None, stt.transcribe_file, tmp_path)
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
    return get_all_users()

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
            data = req.b64
            if ',' in data:
                data = data.split(',', 1)[1]
            with open(filepath, 'wb') as f:
                f.write(_base64.b64decode(data))
        elif req.url:
            async with _httpx.AsyncClient(timeout=30) as client:
                r = await client.get(req.url)
                r.raise_for_status()
                with open(filepath, 'wb') as f:
                    f.write(r.content)
        else:
            raise HTTPException(400, "b64 ou url requis")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Erreur sauvegarde image : {e}")
    img_id = save_image(filename, req.prompt, req.thread_id)
    return {"id": img_id, "filename": filename}

@app.get("/api/images")
async def images_list():
    """Liste toutes les images sauvegardées."""
    return get_images()

@app.get("/api/images/file/{filename}")
async def images_file(filename: str):
    """Sert le fichier image depuis data/images/."""
    # Sécurité : nom de fichier simple, pas de traversée de chemin
    if '/' in filename or '\\' in filename or '..' in filename:
        raise HTTPException(400, "Nom de fichier invalide")
    filepath = os.path.join(_IMAGES_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, "Image non trouvée")
    return FileResponse(filepath, media_type="image/png")

@app.patch("/api/images/{img_id}")
async def images_rename(img_id: int, req: ImageRenameRequest):
    """Renomme une image sur disque et en DB."""
    images = get_images()
    current = next((i for i in images if i['id'] == img_id), None)
    if not current:
        raise HTTPException(404, "Image non trouvée")
    new_filename = req.filename.strip()
    if not new_filename.endswith('.png'):
        new_filename += '.png'
    old_path = os.path.join(_IMAGES_DIR, current['filename'])
    new_path = os.path.join(_IMAGES_DIR, new_filename)
    if os.path.exists(old_path):
        os.rename(old_path, new_path)
    rename_image(img_id, new_filename)
    return {"status": "ok", "filename": new_filename}

@app.delete("/api/images/{img_id}")
async def images_delete(img_id: int):
    """Supprime une image (DB + disque)."""
    filename = delete_image(img_id)
    if not filename:
        raise HTTPException(404, "Image non trouvée")
    filepath = os.path.join(_IMAGES_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
    return {"status": "ok"}


# ══════════════════════════════════════════
# LANCEMENT DIRECT
# ══════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
