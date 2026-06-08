# -*- coding: utf-8 -*-
# ============================================
# NIMM — clear_memory.py
# Efface toute la memoire SAUF le prenom
# de l'utilisateur (predicat = 'prenom').
# Les reglages (table settings) ne sont
# pas touches.
# Usage : python -X utf8 clear_memory.py
# ============================================

import sys, os, json, sqlite3, glob
sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')

def charger_utilisateurs():
    """Lit users.json et retourne une liste de dicts {id, name, emoji}."""
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def lister_bases_existantes():
    """Liste les fichiers nimm_*.db presents dans data/."""
    pattern = os.path.join(DATA_DIR, 'nimm_*.db')
    fichiers = glob.glob(pattern)
    ids = []
    for f in fichiers:
        nom = os.path.basename(f)
        # extraire l'id entre 'nimm_' et '.db'
        uid = nom.replace('nimm_', '').replace('.db', '')
        ids.append(uid)
    return ids

def choisir_utilisateur(utilisateurs, bases_existantes):
    """Affiche un menu et retourne l'id utilisateur choisi."""
    print('\n  Utilisateurs trouves :')
    print('  ' + '-' * 40)

    # Construire une liste complete : ceux de users.json + bases orphelines
    vus = set()
    choix = []

    for u in utilisateurs:
        uid = u['id']
        vus.add(uid)
        nom = u.get('name', uid)
        emoji = u.get('emoji', '👤')
        dispo = ' [DB trouvee]' if uid in bases_existantes else ' [pas de DB]'
        choix.append((uid, f'  {len(choix)+1}. {emoji} {nom} ({uid}){dispo}'))

    # Bases orphelines (pas dans users.json)
    for uid in bases_existantes:
        if uid not in vus:
            vus.add(uid)
            choix.append((uid, f'  {len(choix)+1}. 👤 {uid} [DB trouvee, pas dans users.json]'))

    if not choix:
        print('  Aucun utilisateur trouve.')
        return None

    for (_, ligne) in choix:
        print(ligne)

    print(f'\n  {len(choix)+1}. Saisir un nom manuellement')
    print('  0. Annuler')

    try:
        rep = input('\n  Choix : ').strip()
    except (EOFError, KeyboardInterrupt):
        print('\n  Annule.')
        return None

    if rep == '0':
        print('  Annule.')
        return None

    # Choix numerique
    try:
        idx = int(rep) - 1
        if 0 <= idx < len(choix):
            return choix[idx][0]
    except ValueError:
        pass

    # Saisie manuelle (option "Saisir un nom")
    if rep == str(len(choix) + 1):
        manuel = input('  Nom d\'utilisateur : ').strip().lower()
        if manuel:
            return manuel
        print('  Annule.')
        return None

    print('  Choix invalide.')
    return None

def main():
    print('\n  NIMM — clear_memory.py')
    print('  Efface la memoire d\'un utilisateur (conserve le prenom)')
    print('  ' + '-' * 50)

    utilisateurs = charger_utilisateurs()
    bases_existantes = lister_bases_existantes()

    uid = choisir_utilisateur(utilisateurs, bases_existantes)
    if uid is None:
        return

    db_path = os.path.join(DATA_DIR, f'nimm_{uid}.db')
    if not os.path.exists(db_path):
        print(f'\n  Base introuvable : {db_path}')
        print('  Verifie le nom ou lance NIMM une fois avec cet utilisateur.')
        return

    conn = sqlite3.connect(db_path)
    c    = conn.cursor()

    # Compter avant
    c.execute('SELECT COUNT(*) FROM memory')
    total_avant = c.fetchone()[0]

    # Identifier les entrees a conserver (predicat = 'prenom')
    c.execute("SELECT key, sujet, predicat, objet FROM memory WHERE predicat = 'prenom'")
    a_garder = c.fetchall()

    print(f'\n  Utilisateur : {uid}')
    print(f'  Base        : {db_path}')
    print(f'  Souvenirs   : {total_avant}')
    print(f'  Conserve    : {len(a_garder)} (prenom)')
    for (key, sujet, predicat, objet) in a_garder:
        print(f'    -> {sujet} / {predicat} = {objet}')

    if total_avant == 0:
        print('\n  Base deja vide. Rien a faire.')
        conn.close()
        return

    # Confirmation
    print(f'\n  {total_avant - len(a_garder)} souvenir(s) vont etre supprimes.')
    rep = input('  Confirmer ? (oui / non) : ').strip().lower()
    if rep not in ('oui', 'o', 'yes', 'y'):
        print('  Annule.')
        conn.close()
        return

    # Supprimer tout sauf prenom
    c.execute("DELETE FROM memory WHERE predicat != 'prenom'")
    conn.commit()

    c.execute('SELECT COUNT(*) FROM memory')
    total_apres = c.fetchone()[0]
    conn.close()

    print(f'\n  Supprime : {total_avant - total_apres} souvenir(s)')
    print(f'  Reste    : {total_apres} souvenir(s)')
    print('  Done.\n')

main()
