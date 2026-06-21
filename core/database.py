# ============================================
# NIMM — core/database.py
# Gestion SQLite : conversations + mémoire
# ============================================

import sqlite3
import os
import json
import uuid
from datetime import datetime
from contextvars import ContextVar

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
_user_ctx: ContextVar[str] = ContextVar('nimm_user', default='')

def set_user_context(user_id: str):
    """Définit l'utilisateur actif pour ce contexte asyncio."""
    _user_ctx.set(user_id)

def get_current_user() -> str:
    """Retourne l'identifiant de l'utilisateur actif.
    Retourne '' par défaut (pas de 'laurent' fantôme) pour éviter
    de créer une DB 'laurent' involontairement."""
    return _user_ctx.get()

def get_db_path(user_id: str = None) -> str:
    """Chemin vers la DB de l'utilisateur (courant si non précisé).
    Retourne None si aucun utilisateur n'est défini (évite de créer nimm_.db fantôme)."""
    uid = user_id or _user_ctx.get()
    if not uid:
        return None
    return os.path.join(DATA_DIR, f'nimm_{uid}.db')

def get_conn(user_id: str = None):
    db_path = get_db_path(user_id)
    if db_path is None:
        raise RuntimeError("Aucun utilisateur defini — impossible d'ouvrir une connexion DB. "
                           "Appeler set_user_context() ou passer user_id avant.")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

# ══════════════════════════════════════════
# GESTION DES PROFILS UTILISATEURS
# ══════════════════════════════════════════

_USERS_FILE = os.path.join(DATA_DIR, 'users.json')

def _load_users() -> list:
    if not os.path.exists(_USERS_FILE):
        return []
    try:
        with open(_USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def _save_users(users: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def get_all_users() -> list:
    """Retourne la liste de tous les profils."""
    return _load_users()

def create_user(user_id: str, name: str, emoji: str = '👤', admin: bool = False) -> dict:
    """Crée un nouveau profil et initialise sa DB.
    N'appelle PAS set_setting('user_name', ...) — c'est l'onboarding qui le fait,
    pour éviter que le frontend saute l'écran d'onboarding."""
    users = _load_users()
    if any(u['id'] == user_id for u in users):
        raise ValueError(f"Profil '{user_id}' déjà existant.")
    user = {'id': user_id, 'name': name, 'emoji': emoji, 'admin': admin}
    users.append(user)
    _save_users(users)
    init_db(user_id)
    # Parametres par defaut pour le nouveau profil
    set_setting('provider',    'deepseek')
    set_setting('model',       'deepseek-chat')
    set_setting('mask',        'lia')
    print(f'[DB] Profil créé : {user_id} ({name})')
    return user

def delete_user(user_id: str):
    """Supprime un profil (fichier users.json uniquement — DB conservée)."""
    all_users = _load_users()
    admins = [u for u in all_users if u.get('admin')]
    if len(admins) == 1 and admins[0]['id'] == user_id:
        raise ValueError("Impossible de supprimer le dernier administrateur.")
    users = [u for u in all_users if u['id'] != user_id]
    _save_users(users)
    print(f'[DB] Profil supprimé : {user_id}')

def update_user(user_id: str, name: str = None, emoji: str = None, admin: bool = None) -> dict:
    """Met à jour le nom, l'emoji ou le flag admin d'un profil."""
    users = _load_users()
    for u in users:
        if u['id'] == user_id:
            if name  is not None: u['name']  = name
            if emoji is not None: u['emoji'] = emoji
            if admin is not None: u['admin'] = admin
            _save_users(users)
            return u
    raise ValueError(f"Profil '{user_id}' introuvable.")

# ══════════════════════════════════════════
# VERROU DE SESSION — PIN local (haché) + identité Tailscale
# ══════════════════════════════════════════
#
# But : empêcher la POLLUTION de mémoire quand on bascule par erreur sur la
# session d'un autre profil sur le PC partagé. Local : PIN par profil (haché,
# jamais en clair). Distant : un profil peut être lié à une identité Tailscale,
# et seul le porteur de cette identité peut écrire dans cette session.
# INERTE par défaut : sans pin_hash ni ts_login, aucun comportement ne change.

import hashlib as _hashlib, hmac as _hmac, secrets as _secrets, base64 as _b64

_UNLOCK_SECRET_FILE = os.path.join(DATA_DIR, '.nimm_unlock_secret')


def _unlock_secret() -> bytes:
    """Secret serveur (généré une fois) pour signer les jetons de déverrouillage."""
    try:
        if os.path.exists(_UNLOCK_SECRET_FILE):
            with open(_UNLOCK_SECRET_FILE, 'rb') as f:
                data = f.read().strip()
            if data:
                return data
    except Exception:
        pass
    sec = _secrets.token_bytes(32)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(_UNLOCK_SECRET_FILE, 'wb') as f:
            f.write(sec)
        try:
            os.chmod(_UNLOCK_SECRET_FILE, 0o600)
        except Exception:
            pass
    except Exception:
        pass
    return sec


def _hash_pin(pin: str, salt: bytes) -> str:
    dk = _hashlib.pbkdf2_hmac('sha256', (pin or '').encode('utf-8'), salt, 120000)
    return _b64.b64encode(dk).decode('ascii')


def set_user_pin(user_id: str, pin: str) -> None:
    """Définit (pin non vide) ou retire (pin vide) le PIN d'un profil.
    Stocké haché (PBKDF2 + sel) dans users.json — jamais en clair."""
    users = _load_users()
    for u in users:
        if u['id'] == user_id:
            if pin:
                salt = _secrets.token_bytes(16)
                u['pin_salt'] = _b64.b64encode(salt).decode('ascii')
                u['pin_hash'] = _hash_pin(pin, salt)
            else:
                u.pop('pin_salt', None)
                u.pop('pin_hash', None)
            _save_users(users)
            return
    raise ValueError(f"Profil '{user_id}' introuvable.")


def user_has_pin(user_id: str) -> bool:
    for u in _load_users():
        if u['id'] == user_id:
            return bool(u.get('pin_hash'))
    return False


def verify_user_pin(user_id: str, pin: str) -> bool:
    """True si le PIN correspond, ou si le profil n'a pas de PIN défini."""
    for u in _load_users():
        if u['id'] == user_id:
            ph, ps = u.get('pin_hash'), u.get('pin_salt')
            if not ph or not ps:
                return True  # pas de verrou
            try:
                salt = _b64.b64decode(ps)
            except Exception:
                return False
            return _hmac.compare_digest(_hash_pin(pin or '', salt), ph)
    return False


def unlock_token(user_id: str) -> str:
    """Jeton opaque prouvant que le PIN de user_id a été fourni (HMAC du secret)."""
    return _hmac.new(_unlock_secret(), (user_id or '').encode('utf-8'),
                     _hashlib.sha256).hexdigest()


def check_unlock_token(user_id: str, token: str) -> bool:
    if not token:
        return False
    return _hmac.compare_digest(token, unlock_token(user_id))


def set_user_ts_login(user_id: str, ts_login: str) -> None:
    """Lie (ou délie si vide) un profil à une identité Tailscale (Tailscale-User-Login)."""
    users = _load_users()
    for u in users:
        if u['id'] == user_id:
            if ts_login:
                u['ts_login'] = ts_login
            else:
                u.pop('ts_login', None)
            _save_users(users)
            return
    raise ValueError(f"Profil '{user_id}' introuvable.")


def find_user_by_ts_login(ts_login: str):
    """id du profil lié à cette identité Tailscale, ou None."""
    if not ts_login:
        return None
    for u in _load_users():
        if u.get('ts_login') and u['ts_login'].lower() == ts_login.lower():
            return u['id']
    return None


def init_bibliotheque(conn):
    """Crée la table bibliothèque si elle n'existe pas."""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS bibliotheque (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            titre            TEXT    NOT NULL,
            sujet_principal  TEXT    DEFAULT '',
            tags             TEXT    DEFAULT '',
            resume_texte     TEXT    DEFAULT '',
            os_json          TEXT    DEFAULT '',
            os_riche         TEXT    DEFAULT '',
            categories       TEXT    DEFAULT '',
            status           TEXT    DEFAULT 'active',
            thread_id_source TEXT    DEFAULT '',
            date_conversation TEXT   DEFAULT '',
            date_creation    TEXT    NOT NULL
        )
    ''')
    conn.commit()

    # ── Migrations douces — colonnes ajoutées après la création initiale ──
    for col, definition in [
        ('os_riche',   'TEXT DEFAULT ""'),
        ('categories', 'TEXT DEFAULT ""'),
        ('mask_id',    'TEXT DEFAULT "lia"'),
    ]:
        try:
            conn.execute(f'ALTER TABLE bibliotheque ADD COLUMN {col} {definition}')
            conn.commit()
            print(f'[DB] Colonne bibliotheque.{col} ajoutée.')
        except Exception:
            pass  # Colonne déjà présente

    # ── FTS5 — recherche thématique bibliothèque ──
    conn.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS bibliotheque_fts USING fts5(
            id    UNINDEXED,
            texte,
            tokenize = 'unicode61 remove_diacritics 1'
        )
    ''')

    # ── Triggers — synchronisation bibliotheque ↔ bibliotheque_fts ──
    conn.execute('''
        CREATE TRIGGER IF NOT EXISTS bibliotheque_fts_insert
        AFTER INSERT ON bibliotheque BEGIN
            INSERT INTO bibliotheque_fts(id, texte)
            VALUES (NEW.id,
                COALESCE(NEW.titre, '') || ' ' ||
                COALESCE(NEW.tags, '') || ' ' ||
                COALESCE(NEW.sujet_principal, '') || ' ' ||
                COALESCE(NEW.os_json, '') || ' ' ||
                COALESCE(NEW.os_riche, ''));
        END
    ''')
    conn.execute('''
        CREATE TRIGGER IF NOT EXISTS bibliotheque_fts_update
        AFTER UPDATE ON bibliotheque BEGIN
            DELETE FROM bibliotheque_fts WHERE id = OLD.id;
            INSERT INTO bibliotheque_fts(id, texte)
            VALUES (NEW.id,
                COALESCE(NEW.titre, '') || ' ' ||
                COALESCE(NEW.tags, '') || ' ' ||
                COALESCE(NEW.sujet_principal, '') || ' ' ||
                COALESCE(NEW.os_json, '') || ' ' ||
                COALESCE(NEW.os_riche, ''));
        END
    ''')
    conn.execute('''
        CREATE TRIGGER IF NOT EXISTS bibliotheque_fts_delete
        AFTER DELETE ON bibliotheque BEGIN
            DELETE FROM bibliotheque_fts WHERE id = OLD.id;
        END
    ''')
    conn.commit()


def save_bibliotheque_entry(titre: str, sujet_principal: str, tags: str,
                             resume_texte: str, thread_id_source: str,
                             date_conversation: str = '',
                             os_json: str = '',
                             os_riche: str = '',
                             categories: str = '',
                             status: str = 'active',
                             mask_id: str = 'lia') -> int:
    """Sauvegarde une entrée dans la bibliothèque. Retourne l'id créé."""
    conn = get_conn()
    now  = datetime.now().isoformat()
    cur  = conn.execute(
        '''INSERT INTO bibliotheque
           (titre, sujet_principal, tags, resume_texte, os_json, os_riche, categories,
            status, thread_id_source, date_conversation, date_creation, mask_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (titre, sujet_principal, tags, resume_texte, os_json, os_riche, categories,
         status, thread_id_source, date_conversation, now, mask_id)
    )
    conn.commit()
    entry_id = cur.lastrowid
    conn.close()
    return entry_id


# ══════════════════════════════════════════
# INTÉRÊTS — antichambre topics
# ══════════════════════════════════════════

def upsert_interet(topic: str, contexte: str = '') -> dict:
    """Crée ou incrémente un intérêt.
    Cooldown 24h : une même session ne compte que pour 1 occurrence.
    Retourne le dict de l'entrée après mise à jour."""
    from datetime import timedelta
    conn = get_conn()
    now  = datetime.now()
    row  = conn.execute(
        'SELECT * FROM interets WHERE topic = ?', (topic,)
    ).fetchone()

    if row is None:
        # Première mention — création
        conn.execute(
            '''INSERT INTO interets (topic, contexte, occurrences, statut,
               premiere_mention, derniere_mention)
               VALUES (?, ?, 1, 'antichambre', ?, ?)''',
            (topic, contexte[:300], now.isoformat(), now.isoformat())
        )
        conn.commit()
    else:
        # Cooldown 24h — on n'incrémente pas si mention < 24h
        derniere = datetime.fromisoformat(row['derniere_mention'])
        if (now - derniere) >= timedelta(hours=24):
            new_occ    = row['occurrences'] + 1
            new_statut = 'confirme' if new_occ >= 3 else row['statut']
            conn.execute(
                '''UPDATE interets
                   SET occurrences = ?, statut = ?,
                       derniere_mention = ?, contexte = ?
                   WHERE topic = ?''',
                (new_occ, new_statut, now.isoformat(), contexte[:300], topic)
            )
            conn.commit()

    result = dict(conn.execute(
        'SELECT * FROM interets WHERE topic = ?', (topic,)
    ).fetchone())
    conn.close()
    return result


def get_interets_confirmes() -> list:
    """Retourne les intérêts confirmés (occurrences >= 3) pour injection contexte."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM interets WHERE statut = 'confirme' ORDER BY occurrences DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def purge_old_interets(jours: int = 30) -> int:
    """Supprime les intérêts en antichambre non réévoqués depuis `jours` jours.
    Les intérêts confirmés ne sont jamais purgés automatiquement.
    Retourne le nombre de lignes supprimées."""
    from datetime import timedelta
    conn    = get_conn()
    seuil   = (datetime.now() - timedelta(days=jours)).isoformat()
    deleted = conn.execute(
        """DELETE FROM interets
           WHERE statut = 'antichambre' AND derniere_mention < ?""",
        (seuil,)
    ).rowcount
    conn.commit()
    conn.close()
    return deleted


def get_bibliotheque_index() -> list:
    """Retourne l'index léger de toutes les fiches : id, titre, tags, categories, date_conversation."""
    conn = get_conn()
    rows = conn.execute(
        'SELECT id, titre, tags, categories, date_conversation FROM bibliotheque ORDER BY date_creation DESC'
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_bibliotheque_entries(limit: int = 100) -> list:
    """Retourne les entrées les plus récentes."""
    conn = get_conn()
    rows = conn.execute(
        'SELECT * FROM bibliotheque ORDER BY date_creation DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_bibliotheque(query: str) -> list:
    """Recherche dans titre, sujet_principal et tags."""
    conn  = get_conn()
    like  = f'%{query}%'
    rows  = conn.execute(
        '''SELECT * FROM bibliotheque
           WHERE titre LIKE ? OR sujet_principal LIKE ? OR tags LIKE ? OR resume_texte LIKE ?
           ORDER BY date_creation DESC LIMIT 50''',
        (like, like, like, like)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_bibliotheque_entry(entry_id: int) -> bool:
    """Supprime une entrée par id."""
    conn = get_conn()
    conn.execute('DELETE FROM bibliotheque WHERE id = ?', (entry_id,))
    conn.commit()
    conn.close()
    return True


def set_bibliotheque_status(entry_id: int, status: str):
    """Met à jour le statut d'une entrée (active / remplacee)."""
    conn = get_conn()
    conn.execute(
        'UPDATE bibliotheque SET status = ? WHERE id = ?', (status, entry_id)
    )
    conn.commit()
    conn.close()


def get_bibliotheque_active_entries(limit: int = 50) -> list:
    """Retourne uniquement les entrées actives (status = active)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM bibliotheque WHERE status = 'active' ORDER BY date_creation DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_bibliotheque_fts(query: str, limit: int = 10) -> list:
    """Recherche FTS5 dans os_json — retourne les ids des entrées actives correspondantes."""
    fts_q = _fts5_query(query)
    if not fts_q:
        return []
    try:
        conn = get_conn()
        rows = conn.execute(
            '''SELECT f.id FROM bibliotheque_fts f
               JOIN bibliotheque b ON b.id = f.id
               WHERE bibliotheque_fts MATCH ? AND b.status = 'active'
               ORDER BY f.rank LIMIT ?''',
            (fts_q, limit)
        ).fetchall()
        conn.close()
        return [r['id'] for r in rows]
    except Exception as e:
        print(f"[DB] FTS5 bibliothèque error : {e}")
        return []


def get_bibliotheque_by_ids(ids: list) -> list:
    """Retourne les entrées complètes pour une liste d'ids."""
    if not ids:
        return []
    conn = get_conn()
    placeholders = ','.join('?' * len(ids))
    rows = conn.execute(
        f'SELECT * FROM bibliotheque WHERE id IN ({placeholders})',
        ids
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════
# GALERIE IMAGES
# ══════════════════════════════════════════

def save_image(filename: str, prompt: str = '', thread_id: str = '') -> int:
    """Enregistre une image en DB. Retourne l'id inséré."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        'INSERT INTO images (filename, prompt, thread_id) VALUES (?, ?, ?)',
        (filename, prompt, thread_id)
    )
    conn.commit()
    img_id = c.lastrowid
    conn.close()
    return img_id

def get_images() -> list:
    """Retourne toutes les images, ordre antéchronologique."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT id, filename, prompt, thread_id, created_at FROM images ORDER BY created_at DESC')
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def rename_image(img_id: int, new_filename: str) -> bool:
    """Renomme une image en DB. Retourne True si trouvée."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE images SET filename = ? WHERE id = ?', (new_filename, img_id))
    conn.commit()
    updated = c.rowcount > 0
    conn.close()
    return updated

def delete_image(img_id: int) -> str:
    """Supprime l'entrée DB et le fichier disque. Retourne le filename ou '' si absent."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT filename FROM images WHERE id = ?', (img_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return ''
    filename = row['filename']
    c.execute('DELETE FROM images WHERE id = ?', (img_id,))
    conn.commit()
    conn.close()
    return filename

def init_db(user_id: str = None):
    os.makedirs(DATA_DIR, exist_ok=True)
    if user_id:
        set_user_context(user_id)
    conn = get_conn()
    c = conn.cursor()

    # ── Fils de conversation ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS threads (
            thread_id   TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            mode        TEXT DEFAULT 'chat',
            created_at  TEXT DEFAULT (datetime('now')),
            updated_at  TEXT DEFAULT (datetime('now')),
            tags        TEXT DEFAULT ''
        )
    ''')

    # Migration douce — ajoute la colonne si la table existait avant
    try:
        c.execute("ALTER TABLE threads ADD COLUMN tags TEXT DEFAULT ''")
        conn.commit()
        print("[DB] Colonne tags (threads) ajoutée.")
    except Exception:
        pass  # Colonne déjà présente — normal au redémarrage

    # ── Messages ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id              TEXT NOT NULL,
            role                   TEXT NOT NULL,
            content                TEXT NOT NULL,
            created_at             TEXT DEFAULT (datetime('now')),
            processed_for_memory   INTEGER DEFAULT 0,
            FOREIGN KEY (thread_id) REFERENCES threads(thread_id)
        )
    ''')

    # Migration douce — ajoute la colonne si la table existait avant
    try:
        c.execute('ALTER TABLE messages ADD COLUMN processed_for_memory INTEGER DEFAULT 0')
        conn.commit()
        print("[DB] Colonne processed_for_memory ajoutée.")
    except Exception:
        pass  # Colonne déjà présente — normal au redémarrage

    # Migration douce — embedding pour la recherche dans les conversations
    try:
        c.execute('ALTER TABLE messages ADD COLUMN embedding TEXT')
        conn.commit()
        print("[DB] Colonne embedding (messages) ajoutée.")
    except Exception:
        pass  # Colonne déjà présente — normal au redémarrage

    # ── Résumé OS (Operating Summary) — table conservée pour rétrocompat, plus écrite ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            thread_id   TEXT PRIMARY KEY,
            os          TEXT,
            updated_at  TEXT DEFAULT (datetime('now'))
        )
    ''')

    # ── Carnet de bord ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS carnet (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id   TEXT NOT NULL,
            note_number INTEGER NOT NULL,
            content     TEXT NOT NULL,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    ''')

    # ── Mémoire ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS memory (
            key          TEXT PRIMARY KEY,
            type         TEXT,
            sujet        TEXT,
            predicat     TEXT,
            objet        TEXT,
            valeur       TEXT,
            confiance    REAL DEFAULT 1.0,
            valence      REAL DEFAULT 0.0,
            sensibilite  TEXT DEFAULT 'neutre',
            cumulatif    INTEGER DEFAULT 0,
            categorie    TEXT DEFAULT 'quotidien',
            profondeur   INTEGER DEFAULT 3,
            type_temporal TEXT DEFAULT 'persistant',
            expiration   TEXT,
            timestamp    TEXT DEFAULT (datetime('now')),
            repetitions  INTEGER DEFAULT 0,
            poids        REAL DEFAULT 1.0,
            embedding    TEXT
        )
    ''')

    # ── Paramètres globaux ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key    TEXT PRIMARY KEY,
            value  TEXT
        )
    ''')

    # ── Bibliothèque ──
    init_bibliotheque(conn)

    # ── Intérêts (antichambre topics) ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS interets (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            topic            TEXT NOT NULL UNIQUE,
            contexte         TEXT DEFAULT '',
            occurrences      INTEGER DEFAULT 1,
            statut           TEXT DEFAULT 'antichambre',
            premiere_mention TEXT DEFAULT (datetime('now')),
            derniere_mention TEXT DEFAULT (datetime('now'))
        )
    ''')

    # ── Rappels / Agenda ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS rappels (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            description   TEXT    NOT NULL,
            date_echeance TEXT,
            type          TEXT    NOT NULL DEFAULT 'normal',
            statut        TEXT    NOT NULL DEFAULT 'actif',
            rappels_emis  TEXT    NOT NULL DEFAULT '[]',
            date_creation TEXT    DEFAULT (datetime('now'))
        )
    ''')

    # ── Galerie images ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS images (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            filename    TEXT    NOT NULL,
            prompt      TEXT    DEFAULT '',
            thread_id   TEXT    DEFAULT '',
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    ''')
    # Migration douce — crée la table si elle n'existait pas
    try:
        c.execute("SELECT id FROM images LIMIT 1")
    except Exception:
        pass

    # ── Index FTS5 — recherche mémoire rapide ──
    c.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            key    UNINDEXED,
            texte,
            tokenize = 'unicode61 remove_diacritics 1'
        )
    ''')

    # ── Triggers — synchronisation memory ↔ memory_fts ──
    c.execute('''
        CREATE TRIGGER IF NOT EXISTS memory_fts_insert
        AFTER INSERT ON memory BEGIN
            INSERT INTO memory_fts(key, texte)
            VALUES (
                NEW.key,
                COALESCE(NEW.sujet,'') || ' ' || COALESCE(NEW.predicat,'') || ' ' ||
                COALESCE(NEW.objet,'') || ' ' || COALESCE(NEW.valeur,'')
            );
        END
    ''')

    c.execute('''
        CREATE TRIGGER IF NOT EXISTS memory_fts_update
        AFTER UPDATE ON memory BEGIN
            DELETE FROM memory_fts WHERE key = OLD.key;
            INSERT INTO memory_fts(key, texte)
            VALUES (
                NEW.key,
                COALESCE(NEW.sujet,'') || ' ' || COALESCE(NEW.predicat,'') || ' ' ||
                COALESCE(NEW.objet,'') || ' ' || COALESCE(NEW.valeur,'')
            );
        END
    ''')

    c.execute('''
        CREATE TRIGGER IF NOT EXISTS memory_fts_delete
        AFTER DELETE ON memory BEGIN
            DELETE FROM memory_fts WHERE key = OLD.key;
        END
    ''')

    conn.commit()

    # Migration — colonnes ajoutées en v3
    for col, definition in [
        ('memoire_type',    "TEXT NOT NULL DEFAULT 'identite'"),
        ('last_reinforced', "TEXT"),
        ('contexte',        "TEXT DEFAULT ''"),
    ]:
        try:
            conn.execute(f'ALTER TABLE memory ADD COLUMN {col} {definition}')
            conn.commit()
            print(f"[DB] Colonne '{col}' ajoutée.")
        except Exception:
            pass  # Colonne déjà présente

    # Migration — colonnes mémoire v2
    try:
        conn.execute("ALTER TABLE memory ADD COLUMN registre TEXT DEFAULT 'neutre'")
        conn.commit()
        print("[DB] Colonne 'registre' ajoutée (mémoire v2).")
    except Exception:
        pass  # Colonne déjà présente
    
    # Peupler FTS5 depuis les souvenirs existants (migration silencieuse)
    try:
        conn.execute('''
            INSERT OR IGNORE INTO memory_fts(key, texte)
            SELECT
                key,
                COALESCE(sujet,'') || ' ' || COALESCE(predicat,'') || ' ' ||
                COALESCE(objet,'') || ' ' || COALESCE(valeur,'')
            FROM memory
        ''')
        conn.commit()
    except Exception as e:
        print(f"[DB] Migration FTS5 : {e}")

    # Migration — colonnes bibliothèque ajoutées v3
    for col, definition in [
        ('os_json',  "TEXT DEFAULT ''"),
        ('status',   "TEXT DEFAULT 'active'"),
        ('mask_id',  "TEXT DEFAULT 'lia'"),
    ]:
        try:
            conn.execute(f'ALTER TABLE bibliotheque ADD COLUMN {col} {definition}')
            conn.commit()
            print(f"[DB] Bibliothèque : colonne '{col}' ajoutée.")
        except Exception:
            pass  # Colonne déjà présente

    # Migration — verrouillage masque par fil
    for col, definition in [
        ('mask_id',          "TEXT DEFAULT ''"),
        ('personality_mode', "TEXT DEFAULT ''"),
    ]:
        try:
            conn.execute(f'ALTER TABLE threads ADD COLUMN {col} {definition}')
            conn.commit()
            print(f"[DB] Threads : colonne '{col}' ajoutée.")
        except Exception:
            pass  # Colonne déjà présente

    # Réindexer le FTS5 bibliothèque (titre + tags + sujet + os_json)
    try:
        conn.execute('DELETE FROM bibliotheque_fts')
        conn.execute('''
            INSERT INTO bibliotheque_fts(id, texte)
            SELECT id,
                COALESCE(titre, '') || ' ' ||
                COALESCE(tags, '') || ' ' ||
                COALESCE(sujet_principal, '') || ' ' ||
                COALESCE(os_json, '')
            FROM bibliotheque
        ''')
        conn.commit()
    except Exception as e:
        print(f"[DB] Migration FTS5 bibliothèque : {e}")

    # ── Anecdotes — moments partagés, complicité conversationnelle ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS anecdotes (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            titre             TEXT    NOT NULL,
            contenu           TEXT    DEFAULT '',
            contexte          TEXT    DEFAULT '',
            tags              TEXT    DEFAULT '',
            timestamp         TEXT    DEFAULT (datetime('now')),
            evocations        INTEGER DEFAULT 0,
            derniere_evocation TEXT   DEFAULT NULL
        )
    ''')

    # ── FTS5 — recherche anecdotes ──
    c.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS anecdotes_fts USING fts5(
            id    UNINDEXED,
            texte,
            tokenize = 'unicode61 remove_diacritics 1'
        )
    ''')

    # ── Triggers — synchronisation anecdotes ↔ anecdotes_fts ──
    c.execute('''
        CREATE TRIGGER IF NOT EXISTS anecdotes_fts_insert
        AFTER INSERT ON anecdotes BEGIN
            INSERT INTO anecdotes_fts(id, texte)
            VALUES (NEW.id,
                COALESCE(NEW.titre, '') || ' ' ||
                COALESCE(NEW.contenu, '') || ' ' ||
                COALESCE(NEW.tags, '') || ' ' ||
                COALESCE(NEW.contexte, ''));
        END
    ''')
    c.execute('''
        CREATE TRIGGER IF NOT EXISTS anecdotes_fts_update
        AFTER UPDATE ON anecdotes BEGIN
            DELETE FROM anecdotes_fts WHERE id = OLD.id;
            INSERT INTO anecdotes_fts(id, texte)
            VALUES (NEW.id,
                COALESCE(NEW.titre, '') || ' ' ||
                COALESCE(NEW.contenu, '') || ' ' ||
                COALESCE(NEW.tags, '') || ' ' ||
                COALESCE(NEW.contexte, ''));
        END
    ''')
    c.execute('''
        CREATE TRIGGER IF NOT EXISTS anecdotes_fts_delete
        AFTER DELETE ON anecdotes BEGIN
            DELETE FROM anecdotes_fts WHERE id = OLD.id;
        END
    ''')

    # ── Suivi des coûts — tirelires par provider ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS cost_wallets (
            provider        TEXT PRIMARY KEY,
            display_name    TEXT NOT NULL,
            wallet_type     TEXT NOT NULL DEFAULT 'tirelire',
            solde_depart    REAL DEFAULT 0.0,
            solde_restant   REAL DEFAULT 0.0,
            rate_in         REAL DEFAULT 0.0,
            rate_out        REAL DEFAULT 0.0,
            tokens_in_total INTEGER DEFAULT 0,
            tokens_out_total INTEGER DEFAULT 0,
            requests_total  INTEGER DEFAULT 0,
            reset_policy    TEXT DEFAULT 'manual',
            last_reset      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        )
    ''')

    # ── Suivi des coûts — log par appel ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS cost_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT DEFAULT (datetime('now')),
            provider    TEXT NOT NULL,
            model       TEXT DEFAULT '',
            tokens_in   INTEGER DEFAULT 0,
            tokens_out  INTEGER DEFAULT 0,
            cost_usd    REAL DEFAULT 0.0,
            pipeline    TEXT DEFAULT 'chat'
        )
    ''')

    conn.commit()

    # ── Initialisation des wallets par défaut (si absents) ──
    default_wallets = [
        # (provider, display_name, wallet_type, rate_in, rate_out, reset_policy)
        ('anthropic',  'Anthropic',    'tirelire',          3.00,  15.00, 'manual'),
        ('deepseek',   'DeepSeek',     'tirelire',          0.27,   1.10, 'manual'),
        ('gemini',     'Gemini',       'compteur_requetes', 0.075,  0.30, 'daily'),
        ('openai',     'OpenAI',       'tirelire',          2.50,  10.00, 'manual'),
        ('openrouter', 'OpenRouter',   'tirelire',          0.50,   1.50, 'manual'),
        ('mistral',    'Mistral',      'compteur_tokens',   0.10,   0.30, 'monthly'),
        ('ollama',     'Ollama',       'compteur_tokens',   0.0,    0.0,  'never'),
        ('brave',      'Brave Search', 'compteur_requetes', 0.0,    0.0,  'monthly'),
        ('tavily',     'Tavily',       'compteur_requetes', 0.0,    0.0,  'monthly'),
    ]
    for (prov, name, wtype, r_in, r_out, policy) in default_wallets:
        conn.execute('''
            INSERT OR IGNORE INTO cost_wallets
            (provider, display_name, wallet_type, rate_in, rate_out, reset_policy)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (prov, name, wtype, r_in, r_out, policy))
    conn.commit()

    db_path = get_db_path()
    db_name = os.path.basename(db_path) if db_path else "nimm.db"
    conn.close()
    print(f"[DB] {db_name} initialisée.")


# ══════════════════════════════════════════
# ANECDOTES
# ══════════════════════════════════════════

def save_anecdote(titre: str, contenu: str, contexte: str, tags: str) -> int:
    """Sauvegarde une anecdote. Retourne l'id créé."""
    conn = get_conn()
    now  = datetime.now().isoformat()
    cur  = conn.execute(
        '''INSERT INTO anecdotes (titre, contenu, contexte, tags, timestamp)
           VALUES (?, ?, ?, ?, ?)''',
        (titre, contenu, contexte, tags, now)
    )
    conn.commit()
    entry_id = cur.lastrowid
    conn.close()
    return entry_id


def get_all_anecdotes() -> list:
    """Retourne toutes les anecdotes, triées par date décroissante."""
    conn = get_conn()
    rows = conn.execute(
        'SELECT id, titre, contenu, contexte, tags, timestamp FROM anecdotes ORDER BY timestamp DESC'
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_anecdote(anecdote_id: int):
    """Supprime une anecdote par son id."""
    conn = get_conn()
    conn.execute('DELETE FROM anecdotes WHERE id = ?', (anecdote_id,))
    conn.commit()
    conn.close()

def delete_carnet_note(thread_id: str, note_number: int):
    """Supprime une note du carnet de bord."""
    conn = get_conn()
    conn.execute('DELETE FROM carnet WHERE thread_id = ? AND note_number = ?', (thread_id, note_number))
    conn.commit()
    conn.close()

def search_anecdotes_db(query: str, limit: int = 5) -> list:
    """Recherche FTS5 dans les anecdotes. Retourne les entrées complètes."""
    fts_q = _fts5_query(query)
    if not fts_q:
        return []
    try:
        conn = get_conn()
        rows = conn.execute(
            '''SELECT a.* FROM anecdotes_fts f
               JOIN anecdotes a ON a.id = f.id
               WHERE anecdotes_fts MATCH ?
               ORDER BY f.rank LIMIT ?''',
            (fts_q, limit)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB] FTS5 anecdotes error : {e}")
        return []


def increment_anecdote_evocation(anecdote_id: int):
    """Incrémente le compteur d'évocations et met à jour la date."""
    conn = get_conn()
    now  = datetime.now().isoformat()
    conn.execute(
        '''UPDATE anecdotes
           SET evocations = evocations + 1, derniere_evocation = ?
           WHERE id = ?''',
        (now, anecdote_id)
    )
    conn.commit()
    conn.close()


def _fts5_query(query: str) -> str:
    """Construit une requête FTS5 avec prefix matching sur chaque mot."""
    import re
    tokens = re.split(r'[\s\W]+', query.lower())
    tokens = [re.sub(r'["*()\:^]', '', t) for t in tokens if len(t) > 1]
    if not tokens:
        return ''
    return ' OR '.join(f'{t}*' for t in tokens)


def search_memory_fts(query: str, limit: int = 50) -> list:
    """Recherche FTS5 — retourne les clés des souvenirs correspondants."""
    fts_q = _fts5_query(query)
    if not fts_q:
        return []
    try:
        conn = get_conn()
        rows = conn.execute(
            'SELECT key FROM memory_fts WHERE memory_fts MATCH ? ORDER BY rank LIMIT ?',
            (fts_q, limit)
        ).fetchall()
        conn.close()
        return [r['key'] for r in rows]
    except Exception as e:
        print(f"[DB] FTS5 search error : {e}")
        return []


def get_memories_by_keys(keys: list) -> list:
    """Retourne les souvenirs complets pour une liste de clés."""
    if not keys:
        return []
    conn = get_conn()
    placeholders = ','.join('?' * len(keys))
    rows = conn.execute(
        f'SELECT * FROM memory WHERE key IN ({placeholders})',
        keys
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_permanent_memories() -> list:
    """Retourne tous les souvenirs permanents (toujours injectés)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM memory WHERE type_temporal = 'permanent'"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_embeddings() -> list:
    """Retourne [(key, embedding)] pour les souvenirs vectorisés.
    Sert à la recherche par sens : permet de parcourir tous les vecteurs sans
    charger les enregistrements complets."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT key, embedding FROM memory WHERE embedding IS NOT NULL AND embedding != ''"
    ).fetchall()
    conn.close()
    return [(r['key'], r['embedding']) for r in rows]


# ══════════════════════════════════════════
# RÉFÉRENCES WEB — cache des recherches scrapées
# Zone SÉPARÉE de la mémoire personnelle (ne pollue pas le profil).
# Chaque entrée porte une expiration = périssabilité de l'information.
# ══════════════════════════════════════════

def _ensure_web_reference_table(conn):
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS web_reference (
               id          INTEGER PRIMARY KEY AUTOINCREMENT,
               query       TEXT NOT NULL,
               query_norm  TEXT,
               content     TEXT NOT NULL,
               embedding   TEXT,
               captured_at TEXT NOT NULL,
               expiration  TEXT,
               source      TEXT
           )'''
    )
    # Migration : ajoute `source` aux bases créées avant l'introduction de la colonne.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(web_reference)").fetchall()]
    if 'source' not in cols:
        conn.execute("ALTER TABLE web_reference ADD COLUMN source TEXT")

def save_web_reference(query, query_norm, content, embedding, expiration, source=None):
    """Enregistre une référence web. `expiration` = ISO ou None (jamais).
    `source` distingue l'origine : 'recherche' (cache auto) ou une URL / 'texte' (ingéré)."""
    from datetime import datetime
    conn = get_conn()
    _ensure_web_reference_table(conn)
    cur = conn.execute(
        '''INSERT INTO web_reference (query, query_norm, content, embedding, captured_at, expiration, source)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (query, query_norm, content, embedding, datetime.now().isoformat(), expiration, source)
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid

def get_active_web_references() -> list:
    """Références non expirées (expiration nulle ou future)."""
    from datetime import datetime
    conn = get_conn()
    _ensure_web_reference_table(conn)
    now = datetime.now().isoformat()
    rows = conn.execute(
        "SELECT * FROM web_reference WHERE expiration IS NULL OR expiration > ?", (now,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def purge_web_references() -> int:
    """Supprime les références expirées. Retourne le nombre supprimé."""
    from datetime import datetime
    conn = get_conn()
    _ensure_web_reference_table(conn)
    now = datetime.now().isoformat()
    cur = conn.execute(
        "DELETE FROM web_reference WHERE expiration IS NOT NULL AND expiration <= ?", (now,)
    )
    n = cur.rowcount
    conn.commit()
    conn.close()
    return n

def delete_web_reference(ref_id) -> bool:
    """Supprime une référence par son id (et ses passages). True si une ligne supprimée."""
    conn = get_conn()
    _ensure_web_reference_table(conn)
    cur = conn.execute("DELETE FROM web_reference WHERE id = ?", (ref_id,))
    n = cur.rowcount
    conn.commit()
    conn.close()
    try:
        delete_reference_chunks(ref_id)
    except Exception:
        pass
    return n > 0


# ══════════════════════════════════════════
# PASSAGES DE RÉFÉRENCE — découpage des documents ingérés pour la recherche
# (« interroge mes documents »). Séparé de la mémoire personnelle.
# ══════════════════════════════════════════

def _ensure_reference_chunk_table(conn):
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS reference_chunk (
               id         INTEGER PRIMARY KEY AUTOINCREMENT,
               ref_id     INTEGER,
               titre      TEXT,
               source     TEXT,
               ordinal    INTEGER,
               content    TEXT NOT NULL,
               embedding  TEXT,
               created_at TEXT
           )'''
    )

def save_reference_chunks(ref_id, titre, source, chunks):
    """`chunks` = liste de tuples (ordinal, content, embedding_sérialisé|None)."""
    from datetime import datetime
    conn = get_conn()
    _ensure_reference_chunk_table(conn)
    now = datetime.now().isoformat()
    conn.executemany(
        '''INSERT INTO reference_chunk (ref_id, titre, source, ordinal, content, embedding, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        [(ref_id, titre, source, o, c, e, now) for (o, c, e) in chunks]
    )
    conn.commit()
    conn.close()

def get_all_reference_chunks() -> list:
    """Tous les passages (pour la recherche par sens). Liste de dicts."""
    conn = get_conn()
    _ensure_reference_chunk_table(conn)
    rows = conn.execute(
        "SELECT id, ref_id, titre, source, ordinal, content, embedding FROM reference_chunk"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_reference_chunks(ref_id):
    """Supprime les passages d'un document."""
    conn = get_conn()
    _ensure_reference_chunk_table(conn)
    conn.execute("DELETE FROM reference_chunk WHERE ref_id = ?", (ref_id,))
    conn.commit()
    conn.close()


def get_memory_index_by_theme() -> dict:
    """
    Retourne un index thématique de la mémoire.
    - Tiers (famille, amis…) : noms propres groupés par thème → search_memory(prénom)
    - Utilisateur : liste de prédicats disponibles → search_memory(prédicat)
    Généré en direct depuis la DB — se met à jour automatiquement.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT categorie, sujet, predicat FROM memory "
        "WHERE sujet IS NOT NULL AND sujet != '' AND predicat != 'prenom' "
        "AND objet IS NOT NULL AND objet != '' "
        "ORDER BY categorie, sujet"
    ).fetchall()
    conn.close()

    THEME_LABELS = {
        'famille':    'Famille',
        'sante':      'Santé',
        'profession': 'Travail',
        'loisirs':    'Loisirs',
        'projets':    'Projets',
        'croyances':  'Valeurs',
        'amities':    'Amis',
        'quotidien':  'Quotidien',
        'etudes':     'Études',
    }

    # Prédicats structurels non affichés dans l'index
    _PREDS_SILENT = {
        'date_naissance', 'anciennete_debut', 'age',
        'taille_cm', 'poids_kg', 'groupe_sanguin',
    }

    def _is_name(s: str) -> bool:
        """Vrai si s ressemble à un nom propre — pas une date, pas un âge."""
        if not s or len(s) > 25:
            return False
        if any(c.isdigit() for c in s):
            return False
        if len(s.split()) > 3:
            return False
        return s[0].isupper()

    _uid = get_current_user().lower()

    themes     = {}   # noms propres tiers, groupés par thème
    user_preds = set()  # prédicats disponibles pour l'utilisateur

    for r in rows:
        cat   = (r['categorie'] or 'quotidien').lower()
        label = THEME_LABELS.get(cat, cat.capitalize())
        sujet = (r['sujet'] or '').strip()
        pred  = (r['predicat'] or '').strip()

        if sujet.lower() == _uid:
            # Entrées de l'utilisateur → prédicats disponibles
            if pred and pred not in _PREDS_SILENT:
                user_preds.add(pred)
        elif _is_name(sujet):
            # Tiers identifiés → noms propres par thème
            if label not in themes:
                themes[label] = set()
            themes[label].add(sujet)

    result = {k: sorted(v)[:8] for k, v in themes.items() if v}
    if user_preds:
        result['Profil'] = sorted(user_preds)[:15]

    return result


def get_memory_index() -> list:
    """Retourne les sujets distincts + prédicats disponibles (hors prenom) — pour l'index LLM."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT sujet, GROUP_CONCAT(DISTINCT predicat) as predicats "
        "FROM memory "
        "WHERE sujet IS NOT NULL AND sujet != '' AND predicat != 'prenom' "
        "GROUP BY sujet "
        "ORDER BY sujet"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════
# THREADS
# ══════════════════════════════════════════

def create_thread(thread_id: str, name: str, mode: str = 'chat'):
    conn = get_conn()
    conn.execute(
        'INSERT INTO threads (thread_id, name, mode) VALUES (?, ?, ?)',
        (thread_id, name, mode)
    )
    conn.commit()
    conn.close()

def get_threads():
    conn = get_conn()
    rows = conn.execute(
        'SELECT * FROM threads ORDER BY updated_at DESC'
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_thread(thread_id: str):
    conn = get_conn()
    row = conn.execute(
        'SELECT * FROM threads WHERE thread_id = ?', (thread_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def set_thread_mask(thread_id: str, mask_id: str, personality_mode: str):
    """Verrouille le masque actif sur un fil (appelé au premier message)."""
    conn = get_conn()
    conn.execute(
        'UPDATE threads SET mask_id = ?, personality_mode = ? WHERE thread_id = ?',
        (mask_id, personality_mode, thread_id)
    )
    conn.commit()
    conn.close()

def delete_thread(thread_id: str):
    conn = get_conn()
    conn.execute('DELETE FROM messages WHERE thread_id = ?', (thread_id,))
    conn.execute('DELETE FROM conversations WHERE thread_id = ?', (thread_id,))
    conn.execute('DELETE FROM carnet WHERE thread_id = ?', (thread_id,))
    conn.execute('DELETE FROM threads WHERE thread_id = ?', (thread_id,))
    conn.execute("DELETE FROM settings WHERE key = ?", (f'os_last_count_{thread_id}',))
    conn.execute("DELETE FROM settings WHERE key = ?", (f'dominant_{thread_id}',))
    conn.commit()
    conn.close()

def update_thread_name(thread_id: str, name: str):
    conn = get_conn()
    conn.execute(
        'UPDATE threads SET name = ?, updated_at = ? WHERE thread_id = ?',
        (name, datetime.now().isoformat(), thread_id)
    )
    conn.commit()
    conn.close()

def update_thread_tags(thread_id: str, tags: str):
    """Enregistre les étiquettes d'un fil (chaîne libre, ex: 'projet, urgent')."""
    conn = get_conn()
    conn.execute(
        'UPDATE threads SET tags = ? WHERE thread_id = ?',
        (tags or '', thread_id)
    )
    conn.commit()
    conn.close()

def touch_thread(thread_id: str):
    conn = get_conn()
    conn.execute(
        'UPDATE threads SET updated_at = ? WHERE thread_id = ?',
        (datetime.now().isoformat(), thread_id)
    )
    conn.commit()
    conn.close()


# ══════════════════════════════════════════
# MESSAGES
# ══════════════════════════════════════════

def add_message(thread_id: str, role: str, content: str):
    conn = get_conn()
    conn.execute(
        'INSERT INTO messages (thread_id, role, content) VALUES (?, ?, ?)',
        (thread_id, role, content)
    )
    conn.commit()
    conn.close()
    touch_thread(thread_id)

def get_messages(thread_id: str, limit: int = 200):
    conn = get_conn()
    rows = conn.execute(
        'SELECT role, content, created_at FROM messages '
        'WHERE thread_id = ? ORDER BY id ASC LIMIT ?',
        (thread_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_messages_up_to(thread_id: str, up_to: int) -> list:
    """Retourne les messages d'un fil, du premier jusqu'à la position up_to incluse (0-indexé)."""
    conn = get_conn()
    rows = conn.execute(
        'SELECT role, content FROM messages '
        'WHERE thread_id = ? ORDER BY id ASC LIMIT ?',
        (thread_id, up_to + 1)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def count_messages(thread_id: str) -> int:
    conn = get_conn()
    n = conn.execute(
        'SELECT COUNT(*) FROM messages WHERE thread_id = ?', (thread_id,)
    ).fetchone()[0]
    conn.close()
    return n


# ══════════════════════════════════════════
# RECHERCHE DANS LES CONVERSATIONS (embeddings)
# ══════════════════════════════════════════

def save_message_embedding(message_id: int, embedding: str) -> None:
    """Enregistre l'embedding (sérialisé) d'un message existant."""
    conn = get_conn()
    conn.execute('UPDATE messages SET embedding = ? WHERE id = ?', (embedding, message_id))
    conn.commit()
    conn.close()

def get_messages_missing_embedding(limit: int = 50) -> list:
    """Messages sans embedding (texte non vide), pour rattrapage progressif."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, content FROM messages "
        "WHERE (embedding IS NULL OR embedding = '') AND content IS NOT NULL AND content != '' "
        "ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_message_embeddings() -> list:
    """Tous les messages disposant d'un embedding, avec le nom de leur fil."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT m.id, m.thread_id, m.role, m.content, m.created_at, m.embedding, t.name AS thread_name "
        "FROM messages m JOIN threads t ON t.thread_id = m.thread_id "
        "WHERE m.embedding IS NOT NULL AND m.embedding != ''"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def count_memories() -> int:
    """Retourne le nombre total de souvenirs — pour le radar uniquement."""
    conn = get_conn()
    n = conn.execute('SELECT COUNT(*) FROM memory').fetchone()[0]
    conn.close()
    return n


def search_messages_text(query: str, limit: int = 20) -> list:
    """Recherche textuelle brute dans tous les messages (LIKE insensible à la casse).
    Retourne les messages correspondants, les plus récents en premier."""
    if not query or not query.strip():
        return []
    conn = get_conn()
    rows = conn.execute(
        "SELECT m.id, m.thread_id, m.role, m.content, m.created_at, t.name AS thread_name "
        "FROM messages m JOIN threads t ON t.thread_id = m.thread_id "
        "WHERE LOWER(m.content) LIKE LOWER(?) "
        "ORDER BY m.id DESC LIMIT ?",
        (f'%{query.strip()}%', limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_last_assistant(thread_id: str) -> bool:
    """Supprime uniquement le dernier message assistant (régénération sans modifier le message user)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM messages WHERE thread_id = ? AND role = 'assistant' ORDER BY id DESC LIMIT 1",
        (thread_id,)
    ).fetchone()
    deleted = False
    if row:
        conn.execute("DELETE FROM messages WHERE id = ?", (row['id'],))
        conn.commit()
        deleted = True
    conn.close()
    return deleted


def delete_last_pair(thread_id: str) -> dict:
    """Supprime la dernière paire user+assistant (modification d'un message utilisateur)."""
    conn = get_conn()
    deleted = {'assistant': False, 'user': False}
    row = conn.execute(
        "SELECT id FROM messages WHERE thread_id = ? AND role = 'assistant' ORDER BY id DESC LIMIT 1",
        (thread_id,)
    ).fetchone()
    if row:
        conn.execute("DELETE FROM messages WHERE id = ?", (row['id'],))
        deleted['assistant'] = True
    row = conn.execute(
        "SELECT id FROM messages WHERE thread_id = ? AND role = 'user' ORDER BY id DESC LIMIT 1",
        (thread_id,)
    ).fetchone()
    if row:
        conn.execute("DELETE FROM messages WHERE id = ?", (row['id'],))
        deleted['user'] = True
    conn.commit()
    conn.close()
    return deleted


def append_to_last_assistant(thread_id: str, extra: str) -> bool:
    """Ajoute du texte à la suite du dernier message assistant (continuation après max_tokens)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, content FROM messages WHERE thread_id = ? AND role = 'assistant' ORDER BY id DESC LIMIT 1",
        (thread_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute(
        "UPDATE messages SET content = ? WHERE id = ?",
        (row['content'] + extra, row['id'])
    )
    conn.commit()
    conn.close()
    return True


# ══════════════════════════════════════════
# WORKER MÉMOIRE — fonctions de traçabilité
# ══════════════════════════════════════════

def get_threads_with_unprocessed() -> list:
    """Retourne les thread_id ayant au moins un message processed_for_memory = 0."""
    conn = get_conn()
    rows = conn.execute(
        'SELECT DISTINCT thread_id FROM messages WHERE processed_for_memory = 0'
    ).fetchall()
    conn.close()
    return [r['thread_id'] for r in rows]

def get_unprocessed_message_ids(thread_id: str) -> list:
    """Retourne les id des messages non encore traités pour la mémoire dans un fil."""
    conn = get_conn()
    rows = conn.execute(
        'SELECT id FROM messages WHERE thread_id = ? AND processed_for_memory = 0',
        (thread_id,)
    ).fetchall()
    conn.close()
    return [r['id'] for r in rows]

def mark_messages_processed(ids: list) -> None:
    """Passe processed_for_memory = 1 pour les ids fournis."""
    if not ids:
        return
    conn = get_conn()
    placeholders = ','.join('?' * len(ids))
    conn.execute(
        f'UPDATE messages SET processed_for_memory = 1 WHERE id IN ({placeholders})',
        ids
    )
    conn.commit()
    conn.close()


# ══════════════════════════════════════════
# SUIVI DES COÛTS
# ══════════════════════════════════════════

# Tarifs de référence ($/1M tokens) — modifiables via update_wallet_rate()
TARIFS_DEFAUT = {
    'anthropic':  {'in': 3.00,  'out': 15.00},
    'deepseek':   {'in': 0.27,  'out': 1.10},
    'gemini':     {'in': 0.075, 'out': 0.30},
    'openai':     {'in': 2.50,  'out': 10.00},
    'openrouter': {'in': 0.50,  'out': 1.50},
    'mistral':    {'in': 0.10,  'out': 0.30},
    'ollama':     {'in': 0.0,   'out': 0.0},
    'brave':      {'in': 0.0,   'out': 0.0},
    'tavily':     {'in': 0.0,   'out': 0.0},
}

def log_cost(provider: str, model: str, tokens_in: int, tokens_out: int,
             pipeline: str = 'chat'):
    """Enregistre un appel LLM et déduit le coût du wallet du provider."""
    from datetime import datetime
    conn = get_conn()

    # Récupérer les tarifs du wallet (ou tarifs par défaut)
    row = conn.execute(
        'SELECT rate_in, rate_out, wallet_type FROM cost_wallets WHERE provider = ?',
        (provider,)
    ).fetchone()
    if row:
        rate_in, rate_out = row['rate_in'], row['rate_out']
        wallet_type = row['wallet_type']
    else:
        t = TARIFS_DEFAUT.get(provider, {'in': 0.0, 'out': 0.0})
        rate_in, rate_out = t['in'], t['out']
        wallet_type = 'tirelire'

    cost_usd = (tokens_in * rate_in + tokens_out * rate_out) / 1_000_000

    # Log de l'appel
    conn.execute('''
        INSERT INTO cost_log (timestamp, provider, model, tokens_in, tokens_out, cost_usd, pipeline)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (datetime.now().isoformat(), provider, model or '', tokens_in, tokens_out, cost_usd, pipeline))

    # Mise à jour du wallet
    conn.execute('''
        UPDATE cost_wallets SET
            tokens_in_total  = tokens_in_total  + ?,
            tokens_out_total = tokens_out_total + ?,
            requests_total   = requests_total   + 1,
            solde_restant    = CASE WHEN wallet_type = 'tirelire'
                               THEN MAX(0.0, solde_restant - ?)
                               ELSE solde_restant END,
            updated_at       = ?
        WHERE provider = ?
    ''', (tokens_in, tokens_out, cost_usd, datetime.now().isoformat(), provider))

    conn.commit()
    conn.close()


def get_cost_summary() -> list:
    """Retourne tous les wallets avec leur état actuel."""
    conn = get_conn()
    rows = conn.execute(
        'SELECT * FROM cost_wallets ORDER BY provider'
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def reset_wallet(provider: str):
    """Remet à zéro les compteurs d'un provider (reset manuel ou automatique)."""
    from datetime import datetime
    conn = get_conn()
    conn.execute('''
        UPDATE cost_wallets SET
            tokens_in_total  = 0,
            tokens_out_total = 0,
            requests_total   = 0,
            solde_restant    = solde_depart,
            last_reset       = ?,
            updated_at       = ?
        WHERE provider = ?
    ''', (datetime.now().isoformat(), datetime.now().isoformat(), provider))
    conn.commit()
    conn.close()


def update_wallet_rates(provider: str, rate_in: float, rate_out: float):
    """Met à jour les tarifs d'un provider."""
    from datetime import datetime
    conn = get_conn()
    conn.execute('''
        UPDATE cost_wallets SET rate_in = ?, rate_out = ?, updated_at = ?
        WHERE provider = ?
    ''', (rate_in, rate_out, datetime.now().isoformat(), provider))
    conn.commit()
    conn.close()


def update_wallet_solde(provider: str, solde_depart: float):
    """Définit le solde de départ (tirelire) d'un provider."""
    from datetime import datetime
    conn = get_conn()
    conn.execute('''
        UPDATE cost_wallets SET
            solde_depart  = ?,
            solde_restant = ?,
            updated_at    = ?
        WHERE provider = ?
    ''', (solde_depart, solde_depart, datetime.now().isoformat(), provider))
    conn.commit()
    conn.close()


def check_auto_resets():
    """Vérifie et applique les resets automatiques (monthly → Mistral, daily → Gemini).
    À appeler au démarrage du serveur."""
    from datetime import datetime, date
    now = datetime.now()
    conn = get_conn()
    rows = conn.execute(
        "SELECT provider, reset_policy, last_reset FROM cost_wallets"
    ).fetchall()
    conn.close()

    for row in rows:
        policy = row['reset_policy']
        last   = row['last_reset']
        try:
            last_dt = datetime.fromisoformat(last)
        except Exception:
            continue

        should_reset = False
        if policy == 'monthly':
            # Reset si on est dans un nouveau mois calendaire
            if (now.year, now.month) > (last_dt.year, last_dt.month):
                should_reset = True
        elif policy == 'daily':
            # Reset si on est un nouveau jour
            if now.date() > last_dt.date():
                should_reset = True

        if should_reset:
            reset_wallet(row['provider'])
            print(f"[COSTS] Reset automatique : {row['provider']} ({policy})")


def get_last_user_message_time():
    """Timestamp du dernier message utilisateur — toutes conversations confondues.
    Retourne un objet datetime ou None. Passe par database.py — pas d'accès SQLite direct."""
    from datetime import datetime
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT MAX(created_at) FROM messages WHERE role = 'user'"
        ).fetchone()
        conn.close()
        if row and row[0]:
            return datetime.fromisoformat(row[0])
    except Exception:
        conn.close()
    return None


# ══════════════════════════════════════════
# OS (Operating Summary) — conservé pour rétrocompat, plus utilisé
# ══════════════════════════════════════════

def get_os(thread_id: str) -> str | None:
    conn = get_conn()
    row = conn.execute(
        'SELECT os FROM conversations WHERE thread_id = ?', (thread_id,)
    ).fetchone()
    conn.close()
    return row['os'] if row else None

def set_os(thread_id: str, summary: str):
    conn = get_conn()
    conn.execute(
        '''INSERT INTO conversations (thread_id, os, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(thread_id) DO UPDATE SET os = excluded.os,
           updated_at = excluded.updated_at''',
        (thread_id, summary, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


# ══════════════════════════════════════════
# CARNET DE BORD
# ══════════════════════════════════════════

def add_carnet_note(thread_id: str, note_number: int, content: str, msg_debut: int = 0):
    """Ajoute une note au carnet du fil.
    msg_debut : numéro du premier message résumé par cette note.
    Utilisé pour l'injection glissante (ne montrer la note que quand ce message
    est sorti de la fenêtre active)."""
    conn = get_conn()
    # Migration douce : ajouter la colonne si absente (bases existantes)
    try:
        conn.execute('ALTER TABLE carnet ADD COLUMN msg_debut INTEGER DEFAULT 0')
        conn.commit()
    except Exception:
        pass  # Colonne déjà présente
    conn.execute(
        '''INSERT INTO carnet (thread_id, note_number, content, msg_debut)
           VALUES (?, ?, ?, ?)''',
        (thread_id, note_number, content, msg_debut)
    )
    conn.commit()
    conn.close()

def get_carnet_notes(thread_id: str) -> list:
    """Retourne toutes les notes du carnet, triées par note_number."""
    conn = get_conn()
    rows = conn.execute(
        'SELECT note_number, content FROM carnet WHERE thread_id = ? ORDER BY note_number ASC',
        (thread_id,)
    ).fetchall()
    conn.close()
    return [{'note_number': r['note_number'], 'content': r['content']} for r in rows]

def count_carnet_notes(thread_id: str) -> int:
    """Retourne le nombre de notes existantes pour ce fil."""
    conn = get_conn()
    row = conn.execute(
        'SELECT COUNT(*) as n FROM carnet WHERE thread_id = ?', (thread_id,)
    ).fetchone()
    conn.close()
    return row['n'] if row else 0

def get_carnet_notes_actives(thread_id: str, n_messages: int, fenetre: int = 60) -> list:
    """Retourne uniquement les notes dont les messages résumés sont sortis de la fenêtre active.
    Une note est active si : msg_debut < n_messages - fenetre.
    Les notes sans msg_debut (valeur 0, bases existantes) sont toujours injectées."""
    conn = get_conn()
    seuil = max(0, n_messages - fenetre)
    rows = conn.execute(
        '''SELECT note_number, content, msg_debut FROM carnet
           WHERE thread_id = ?
             AND (msg_debut = 0 OR msg_debut < ?)
           ORDER BY note_number ASC''',
        (thread_id, seuil)
    ).fetchall()
    conn.close()
    return [{'note_number': r['note_number'], 'content': r['content']} for r in rows]


# ══════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════

def get_setting(key: str, default=None):
    try:
        conn = get_conn()
        row = conn.execute(
            'SELECT value FROM settings WHERE key = ?', (key,)
        ).fetchone()
        conn.close()
        return row['value'] if row else default
    except RuntimeError:
        return default

def set_setting(key: str, value: str):
    conn = get_conn()
    conn.execute(
        '''INSERT INTO settings (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value''',
        (key, value)
    )
    conn.commit()
    conn.close()


# ══════════════════════════════════════════
# CLÉS API — CHIFFREMENT AU REPOS (Fernet)
# ══════════════════════════════════════════
#
# Les clés API de l'utilisateur sont stockées CHIFFRÉES dans settings['api_keys'].
# get_api_keys()/set_api_keys() chiffrent/déchiffrent de façon transparente : tout le
# reste du code passe par elles et ne voit jamais ni la clé Fernet, ni le token.
# Migration douce : une valeur encore en clair (JSON hérité) est rechiffrée à la
# première lecture, sans perte. Modèle de menace local « accident, pas adversaire ».

_API_KEYS_KEYFILE = os.path.join(DATA_DIR, '.nimm_api_keyfile')


def _api_keys_fernet():
    """Clé Fernet serveur (générée une fois), stockée dans data/.nimm_api_keyfile (0600).
    Même patron que _unlock_secret()."""
    from cryptography.fernet import Fernet
    try:
        if os.path.exists(_API_KEYS_KEYFILE):
            with open(_API_KEYS_KEYFILE, 'rb') as f:
                data = f.read().strip()
            if data:
                return Fernet(data)
    except Exception:
        pass
    key = Fernet.generate_key()
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(_API_KEYS_KEYFILE, 'wb') as f:
            f.write(key)
        try:
            os.chmod(_API_KEYS_KEYFILE, 0o600)
        except Exception:
            pass
    except Exception:
        pass
    return Fernet(key)


def get_api_keys() -> dict:
    """Retourne les clés API utilisateur déchiffrées (dict).

    Migration douce : si la valeur stockée est encore du JSON en clair (installations
    antérieures au chiffrement), elle est lue puis rechiffrée en place — aucune clé
    n'est perdue."""
    raw = get_setting('api_keys', '')
    if not raw:
        return {}
    # 1. Tenter le déchiffrement Fernet (cas normal une fois migré).
    try:
        plain = _api_keys_fernet().decrypt(raw.encode('utf-8')).decode('utf-8')
        return json.loads(plain)
    except Exception:
        pass  # soit valeur en clair héritée, soit cryptography indisponible
    # 2. Valeur héritée en clair : la lire, puis la rechiffrer en place.
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
    except Exception:
        return {}
    try:
        set_api_keys(data)
    except Exception:
        pass
    return data


def set_api_keys(keys: dict) -> None:
    """Chiffre (Fernet) et stocke les clés API utilisateur dans settings['api_keys']."""
    payload = json.dumps(keys or {}, ensure_ascii=False)
    try:
        token = _api_keys_fernet().encrypt(payload.encode('utf-8')).decode('utf-8')
        set_setting('api_keys', token)
    except Exception:
        # cryptography indisponible : préserver le comportement legacy plutôt que
        # de perdre les clés (le déchiffrement relira ce JSON en clair).
        set_setting('api_keys', payload)


# ══════════════════════════════════════════
# PRÉRÉGLAGES (presets de configuration)
# ══════════════════════════════════════════

# Clés de `settings` qui composent un preset (provider/modèle, routage par
# tâche, masque, mode local, niveau de mémorisation, longueur des réponses…).
PRESET_KEYS = [
    'provider', 'chat_model', 'vision_provider', 'image_provider',
    'provider_routing', 'mask_id', 'local_mode', 'ollama_model',
    'memoire_mode', 'max_tokens', 'search_provider', 'presence',
]

def list_presets() -> dict:
    """Retourne {nom: {config: {...}, created_at: ...}} pour tous les presets."""
    raw = get_setting('presets', '{}')
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_preset(name: str) -> dict:
    """Enregistre (ou remplace) un preset à partir des réglages actuels.
    Retourne la config enregistrée."""
    presets = list_presets()
    config = {}
    for k in PRESET_KEYS:
        v = get_setting(k)
        if v is not None:
            config[k] = v
    presets[name] = {
        'config': config,
        'created_at': datetime.now().isoformat(timespec='seconds'),
    }
    set_setting('presets', json.dumps(presets, ensure_ascii=False))
    return config

def delete_preset(name: str) -> None:
    presets = list_presets()
    if name in presets:
        del presets[name]
        set_setting('presets', json.dumps(presets, ensure_ascii=False))

def apply_preset(name: str):
    """Réapplique un preset enregistré. Retourne sa config, ou None si absent."""
    presets = list_presets()
    entry = presets.get(name)
    if not entry:
        return None
    for k, v in entry.get('config', {}).items():
        set_setting(k, v)
    return entry.get('config', {})


# ══════════════════════════════════════════
# BIBLIOTHÈQUE DE PROMPTS (avec variables {{...}})
# ══════════════════════════════════════════

def list_prompts(type: str = None) -> dict:
    """Retourne {id: {label, text, type, created_at, meta?}} pour les éléments de la
    Promptothèque. Les entrées créées avant l'ajout du champ 'type' sont traitées comme
    'prompt'. Filtre optionnel par type."""
    raw = get_setting('prompt_library', '{}')
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
    except Exception:
        return {}
    for entry in data.values():
        entry.setdefault('type', 'prompt')
    if type:
        return {k: v for k, v in data.items() if v.get('type', 'prompt') == type}
    return data

def save_prompt(prompt_id: str, label: str, text: str, type: str = 'prompt', meta: dict = None) -> dict:
    """Enregistre (ou met à jour si prompt_id existe) un élément de la Promptothèque.
    Retourne {id, label, text, type, created_at, meta?}."""
    prompts = list_prompts()
    if prompt_id and prompt_id in prompts:
        entry = prompts[prompt_id]
        entry['label'] = label
        entry['text'] = text
        entry['type'] = type or entry.get('type', 'prompt')
        if meta is not None:
            entry['meta'] = meta
    else:
        prompt_id = prompt_id or uuid.uuid4().hex
        entry = {
            'label': label,
            'text': text,
            'type': type or 'prompt',
            'created_at': datetime.now().isoformat(timespec='seconds'),
        }
        if meta is not None:
            entry['meta'] = meta
        prompts[prompt_id] = entry
    set_setting('prompt_library', json.dumps(prompts, ensure_ascii=False))
    result = dict(entry)
    result['id'] = prompt_id
    return result

def delete_prompt(prompt_id: str) -> None:
    prompts = list_prompts()
    if prompt_id in prompts:
        del prompts[prompt_id]
        set_setting('prompt_library', json.dumps(prompts, ensure_ascii=False))


# ══════════════════════════════════════════
# COANIMM — DOSSIERS AUTORISÉS EN ÉCRITURE
# ══════════════════════════════════════════
#
# CoaNIMM confine par défaut ses écritures et suppressions à son workspace. Pour
# qu'un script (ou une opération Fichiers) puisse agir ailleurs — par exemple le
# dossier Téléchargements — l'utilisateur doit l'autoriser explicitement. La liste
# est stockée en chemins absolus dans les settings.

def list_coanimm_paths() -> list:
    """Retourne la liste des dossiers (chemins absolus) autorisés en écriture pour CoaNIMM."""
    raw = get_setting('coanimm_allowed_paths', '[]')
    try:
        data = json.loads(raw)
        return [str(p) for p in data] if isinstance(data, list) else []
    except Exception:
        return []

def add_coanimm_path(path: str) -> list:
    """Ajoute un dossier autorisé (normalisé en chemin absolu). Retourne la liste à jour."""
    p = os.path.abspath((path or '').strip())
    if not p or not (path or '').strip():
        return list_coanimm_paths()
    paths = list_coanimm_paths()
    if p not in paths:
        paths.append(p)
        set_setting('coanimm_allowed_paths', json.dumps(paths, ensure_ascii=False))
    return paths

def remove_coanimm_path(path: str) -> list:
    """Retire un dossier autorisé. Retourne la liste à jour."""
    p = os.path.abspath((path or '').strip())
    paths = [x for x in list_coanimm_paths() if x != p]
    set_setting('coanimm_allowed_paths', json.dumps(paths, ensure_ascii=False))
    return paths


# ══════════════════════════════════════════
# PERMISSIONS AGENT (CoaNIMM)
# ══════════════════════════════════════════
#
# Une "action" est une chaîne libre (ex: 'exec_script:<id>') que CoaNIMM doit
# pouvoir réaliser sans confirmation. L'accord peut être donné :
#   - 'once'    : pour cette seule exécution, jamais persisté ;
#   - 'project' : pour le fil de conversation courant (thread_id) ;
#   - 'always'  : pour toujours, tous fils confondus.

def list_agent_grants() -> dict:
    """Retourne {'always': [actions...], 'threads': {thread_id: [actions...]}}."""
    raw = get_setting('agent_permissions', '{}')
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    data.setdefault('always', [])
    data.setdefault('threads', {})
    return data

def agent_permission_granted(action: str, thread_id: str = None) -> bool:
    grants = list_agent_grants()
    if action in grants['always']:
        return True
    if thread_id and action in grants['threads'].get(thread_id, []):
        return True
    return False

def grant_agent_permission(action: str, scope: str, thread_id: str = None) -> None:
    """Enregistre un accord durable. scope='once' n'est jamais persisté (no-op)."""
    grants = list_agent_grants()
    if scope == 'always':
        if action not in grants['always']:
            grants['always'].append(action)
    elif scope == 'project':
        if not thread_id:
            return
        lst = grants['threads'].setdefault(thread_id, [])
        if action not in lst:
            lst.append(action)
    else:
        return
    set_setting('agent_permissions', json.dumps(grants, ensure_ascii=False))

def revoke_agent_permission(action: str, thread_id: str = None) -> None:
    grants = list_agent_grants()
    changed = False
    if action in grants['always']:
        grants['always'].remove(action)
        changed = True
    if thread_id and action in grants['threads'].get(thread_id, []):
        grants['threads'][thread_id].remove(action)
        changed = True
    if changed:
        set_setting('agent_permissions', json.dumps(grants, ensure_ascii=False))


# ══════════════════════════════════════════
# MÉMOIRE
# ══════════════════════════════════════════

def save_memory(record: dict):
    conn = get_conn()
    conn.execute('''
        INSERT INTO memory (
            key, type, sujet, predicat, objet, valeur,
            confiance, valence, sensibilite, cumulatif,
            categorie, profondeur, type_temporal, expiration,
            timestamp, repetitions, poids, embedding,
            memoire_type, last_reinforced, contexte, registre
        ) VALUES (
            :key, :type, :sujet, :predicat, :objet, :valeur,
            :confiance, :valence, :sensibilite, :cumulatif,
            :categorie, :profondeur, :type_temporal, :expiration,
            :timestamp, :repetitions, :poids, :embedding,
            :memoire_type, :last_reinforced, :contexte, :registre
        )
        ON CONFLICT(key) DO UPDATE SET
            valeur          = excluded.valeur,
            objet           = excluded.objet,
            confiance       = excluded.confiance,
            repetitions     = excluded.repetitions,
            poids           = excluded.poids,
            embedding       = excluded.embedding,
            timestamp       = excluded.timestamp,
            memoire_type    = excluded.memoire_type,
            last_reinforced = excluded.last_reinforced,
            contexte        = excluded.contexte,
            registre        = excluded.registre
    ''', record)
    conn.commit()
    conn.close()

def get_all_memory():
    conn = get_conn()
    rows = conn.execute('SELECT * FROM memory ORDER BY poids DESC').fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_memory(key: str):
    conn = get_conn()
    conn.execute('DELETE FROM memory WHERE key = ?', (key,))
    conn.commit()
    conn.close()

def purge_episodic_memories() -> int:
    """
    Supprime les souvenirs episodiques non renforces selon leur profondeur :
    - profondeur >= 4 : expire apres 7 jours
    - profondeur 3    : expire apres 30 jours
    Seuls les triplets avec repetitions <= 1 sont concernes.
    """
    from datetime import datetime, timedelta
    conn = get_conn()
    now = datetime.now()
    cutoff_7  = (now - timedelta(days=7)).isoformat()
    cutoff_30 = (now - timedelta(days=30)).isoformat()
    cur = conn.execute(
        """DELETE FROM memory
           WHERE type_temporal = 'episodique'
           AND repetitions <= 1
           AND (
               (profondeur >= 4 AND timestamp < ?)
            OR (profondeur = 3  AND timestamp < ?)
           )""",
        (cutoff_7, cutoff_30)
    )
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted

def update_memory_value(key: str, valeur: str):
    conn = get_conn()
    conn.execute(
        'UPDATE memory SET valeur = ? WHERE key = ?', (valeur, key)
    )
    conn.commit()
    conn.close()


# ══════════════════════════════════════════
# RAPPELS / AGENDA
# ══════════════════════════════════════════

def create_rappel(description: str, date_echeance: str | None, type_rappel: str) -> int:
    """Crée un rappel. Retourne l'id créé."""
    conn = get_conn()
    cur = conn.execute(
        '''INSERT INTO rappels (description, date_echeance, type, statut, rappels_emis)
           VALUES (?, ?, ?, 'actif', '[]')''',
        (description, date_echeance, type_rappel)
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid

def update_rappel_date(rappel_id: int, date_echeance: str) -> bool:
    """Met à jour la date/heure d'un rappel existant."""
    conn = get_conn()
    conn.execute(
        'UPDATE rappels SET date_echeance = ? WHERE id = ?',
        (date_echeance, rappel_id)
    )
    conn.commit()
    conn.close()
    return True

def close_rappel(rappel_id: int) -> bool:
    """Marque un rappel comme clos (utilisateur confirme que c'est passé)."""
    conn = get_conn()
    conn.execute(
        "UPDATE rappels SET statut = 'clos' WHERE id = ?",
        (rappel_id,)
    )
    conn.commit()
    conn.close()
    return True

def get_rappels_actifs() -> list:
    """Retourne tous les rappels actifs, triés par date."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM rappels WHERE statut = 'actif'
           ORDER BY date_echeance ASC NULLS LAST"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_rappels() -> list:
    """Retourne tous les rappels (actifs + clos + périmés)."""
    conn = get_conn()
    rows = conn.execute(
        'SELECT * FROM rappels ORDER BY date_echeance ASC NULLS LAST'
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def marquer_rappel_emis(rappel_id: int, seuil: str):
    """Ajoute un seuil à rappels_emis. Ex: seuil='j7'."""
    import json
    conn = get_conn()
    row = conn.execute('SELECT rappels_emis FROM rappels WHERE id = ?', (rappel_id,)).fetchone()
    if row:
        emis = json.loads(row['rappels_emis'] or '[]')
        if seuil not in emis:
            emis.append(seuil)
        conn.execute(
            'UPDATE rappels SET rappels_emis = ? WHERE id = ?',
            (json.dumps(emis), rappel_id)
        )
        conn.commit()
    conn.close()

def perimer_rappels_depasses():
    """Passe en 'perime' tous les rappels dont la date est dépassée."""
    from datetime import datetime
    now = datetime.now().strftime('%Y-%m-%d')
    conn = get_conn()
    conn.execute(
        """UPDATE rappels SET statut = 'perime'
           WHERE statut = 'actif'
           AND date_echeance IS NOT NULL
           AND date_echeance < ?""",
        (now,)
    )
    conn.commit()
    conn.close()

def clear_all_memory():
    """Vide toutes les entrées mémoire + rebuild FTS5."""
    conn = get_conn()
    conn.execute("DELETE FROM memory")
    conn.execute("INSERT INTO memory_fts(memory_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()
    print("[DB] Memoire videe + FTS5 rebuilt.")
