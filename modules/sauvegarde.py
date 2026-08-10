# ============================================
# NIMM — modules/sauvegarde.py
# Sauvegarde cohérente des bases SQLite de tous les profils vers un
# dossier synchronisé (Drive, pCloud, Dropbox, NAS… — agnostique :
# NIMM dépose un fichier, l'appli du fournisseur fait le reste)
# ============================================

import os
import sqlite3
from datetime import datetime

from core.database import get_backup_config, set_backup_config, list_user_db_paths


def run_backup() -> dict:
    """Copie chaque DB de profil vers le dossier de sauvegarde configuré.
    Copie cohérente via l'API native de sauvegarde SQLite (sûre en mode
    WAL, même si NIMM écrit dedans pendant la copie). Ne supprime jamais
    rien — aucune purge. Retourne un rapport {ok, message, details}."""
    config = get_backup_config()
    folder = (config.get('folder_path') or '').strip()
    horodatage_erreur = datetime.now().isoformat(timespec='seconds')

    if not folder:
        message = "Aucun dossier de sauvegarde configuré."
        set_backup_config(last_backup_at=horodatage_erreur, last_backup_ok=False,
                           last_backup_message=message)
        return {'ok': False, 'message': message, 'details': []}

    if not os.path.isdir(folder):
        message = f"Dossier de sauvegarde introuvable : {folder}"
        set_backup_config(last_backup_at=horodatage_erreur, last_backup_ok=False,
                           last_backup_message=message)
        return {'ok': False, 'message': message, 'details': []}

    profils = list_user_db_paths()
    if not profils:
        message = "Aucune base de profil trouvée à sauvegarder."
        set_backup_config(last_backup_at=horodatage_erreur, last_backup_ok=False,
                           last_backup_message=message)
        return {'ok': False, 'message': message, 'details': []}

    horodatage = datetime.now().strftime('%Y%m%d_%H%M%S')
    details = []
    reussites = 0

    for user_id, db_path in profils:
        if not db_path or not os.path.exists(db_path):
            details.append({'user_id': user_id, 'ok': False, 'message': 'DB source introuvable'})
            continue
        cible = os.path.join(folder, f'nimm_{user_id}_{horodatage}.db')
        source = None
        dest = None
        try:
            source = sqlite3.connect(db_path)
            dest = sqlite3.connect(cible)
            source.backup(dest)
            details.append({'user_id': user_id, 'ok': True, 'message': os.path.basename(cible)})
            reussites += 1
        except Exception as e:
            details.append({'user_id': user_id, 'ok': False, 'message': str(e)[:200]})
        finally:
            if dest is not None:
                dest.close()
            if source is not None:
                source.close()

    total = len(profils)
    ok = reussites == total
    message = f"{reussites}/{total} profil(s) sauvegardé(s)"
    if not ok:
        echecs = [d['user_id'] for d in details if not d['ok']]
        message += f" — échec : {', '.join(echecs)}"

    set_backup_config(last_backup_at=datetime.now().isoformat(timespec='seconds'),
                       last_backup_ok=ok, last_backup_message=message)

    return {'ok': ok, 'message': message, 'details': details}
