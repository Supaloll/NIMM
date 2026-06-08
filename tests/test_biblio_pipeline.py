# -*- coding: utf-8 -*-
# ============================================
# NIMM — tests/test_biblio_pipeline.py
# Audit pipeline Bibliothèque 📚
# Lecture seule — aucune écriture en base
# Exécution : python -X utf8 tests/test_biblio_pipeline.py
# ============================================
#
# Ce script :
#   1. Inspecte toutes les entrées bibliotheque dans la vraie DB
#   2. Affiche titre + résumé + os_json parsé pour chaque entrée
#   3. Teste le recall FTS5 sur 10 requêtes types
#   4. Simule l'injection dans build_system_prompt() et évalue la cohérence

import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.database import (
    init_db,
    get_bibliotheque_entries,
    get_bibliotheque_active_entries,
    search_bibliotheque_fts,
    get_bibliotheque_by_ids,
)
from core.hub import recall_bibliotheque

init_db()

# ── Couleurs terminal ──────────────────────────────────────────────────────────
GREEN  = '\033[92m'
RED    = '\033[91m'
YELLOW = '\033[93m'
CYAN   = '\033[96m'
BOLD   = '\033[1m'
DIM    = '\033[2m'
RESET  = '\033[0m'

def sep(title='', width=70):
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'═'*pad} {title} {'═'*pad}")
    else:
        print('─' * width)

def ok(msg):   print(f"  {GREEN}✅{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}⚠️ {RESET}  {msg}")
def ko(msg):   print(f"  {RED}❌{RESET}  {msg}")
def info(msg): print(f"  {CYAN}ℹ️ {RESET}  {msg}")

def _truncate(text, n=80):
    if not text:
        return DIM + '(vide)' + RESET
    text = str(text).replace('\n', ' ')
    return text[:n] + ('…' if len(text) > n else '')

# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 — INVENTAIRE GLOBAL
# ══════════════════════════════════════════════════════════════════════════════

def test_inventaire():
    sep('TEST 1 — Inventaire global')

    all_entries    = get_bibliotheque_entries(limit=200)
    active_entries = get_bibliotheque_active_entries(limit=200)

    total  = len(all_entries)
    active = len(active_entries)
    other  = total - active

    print(f"\n  Entrées totales  : {BOLD}{total}{RESET}")
    print(f"  Entrées actives  : {GREEN}{active}{RESET}")
    print(f"  Autres statuts   : {YELLOW if other else DIM}{other}{RESET}")

    if total == 0:
        warn("Aucune entrée en base. Archiver au moins un fil via 📚 pour alimenter la bibliothèque.")
        return []

    # Répartition par statut
    statuts = {}
    for e in all_entries:
        s = e.get('status', '?')
        statuts[s] = statuts.get(s, 0) + 1
    print(f"\n  Statuts : " + ", ".join(f"{k}={v}" for k, v in statuts.items()))

    return active_entries

# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 — CONTENU DES ENTRÉES
# ══════════════════════════════════════════════════════════════════════════════

def test_contenu(entries):
    sep('TEST 2 — Contenu des entrées actives')

    if not entries:
        warn("Pas d'entrées actives à afficher.")
        return

    for e in entries:
        eid   = e.get('id', '?')
        titre = e.get('titre', '(sans titre)')
        sujet = e.get('sujet_principal', '')
        tags  = e.get('tags', '')
        date  = e.get('date_conversation', '') or e.get('date_creation', '')[:10]
        resume = e.get('resume_texte', '')
        os_raw = e.get('os_json', '')

        print(f"\n  ┌─ #{eid} ─────────────────────────────────────────────────")
        print(f"  │ Titre   : {BOLD}{titre}{RESET}")
        print(f"  │ Sujet   : {sujet or DIM+'(vide)'+RESET}")
        print(f"  │ Tags    : {tags or DIM+'(vide)'+RESET}")
        print(f"  │ Date    : {date}")

        # os_json parsé
        os_issues = []
        if os_raw:
            try:
                os_data = json.loads(os_raw)
                fields = ['ce_qui_sest_passe', 'conclusions', 'decisions', 'point_darret', 'mots_cles']
                present = [f for f in fields if os_data.get(f)]
                missing = [f for f in fields if not os_data.get(f)]
                print(f"  │ os_json : {GREEN}{len(present)}/{len(fields)} champs remplis{RESET}", end='')
                if missing:
                    print(f"  {DIM}(manque : {', '.join(missing)}){RESET}", end='')
                print()
                # Afficher chaque champ
                for f in fields:
                    val = os_data.get(f)
                    if val:
                        if isinstance(val, list):
                            val_str = ', '.join(str(x) for x in val[:3])
                            if len(val) > 3:
                                val_str += f' (+{len(val)-3})'
                        else:
                            val_str = str(val)
                        print(f"  │   {CYAN}{f:<22}{RESET} {_truncate(val_str, 60)}")
                if missing:
                    os_issues.append(f"Champs manquants : {', '.join(missing)}")
            except json.JSONDecodeError as err:
                print(f"  │ os_json : {RED}JSON invalide — {err}{RESET}")
                os_issues.append("os_json illisible")
        else:
            print(f"  │ os_json : {YELLOW}(vide){RESET}")
            os_issues.append("os_json vide — recall FTS5 ne fonctionnera pas sur cette entrée")

        # Résumé texte
        if resume:
            print(f"  │ Résumé  : {_truncate(resume, 90)}")
        else:
            print(f"  │ Résumé  : {DIM}(vide){RESET}")
            os_issues.append("resume_texte vide")

        # Diagnostic
        if os_issues:
            for issue in os_issues:
                print(f"  │ {YELLOW}⚠️  {issue}{RESET}")
        else:
            print(f"  │ {GREEN}✅ Entrée complète et valide{RESET}")
        print(f"  └──────────────────────────────────────────────────────────")

# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 — RECALL FTS5
# ══════════════════════════════════════════════════════════════════════════════

# 10 requêtes types couvrant des cas divers :
# - Requêtes susceptibles de matcher des conversations techniques
# - Requêtes personnelles / famille
# - Requêtes sans correspondance probable

RECALL_QUERIES = [
    {'id': 'Q01', 'label': 'Serveur web',        'query': "nginx serveur web configuration"},
    {'id': 'Q02', 'label': 'Projet NIMM',         'query': "NIMM projet architecture intelligence artificielle"},
    {'id': 'Q03', 'label': 'Couture / Nadia',     'query': "couture patron Nadia tissu modèle"},
    {'id': 'Q04', 'label': 'Études bac',          'query': "bac terminale révisions lycée"},
    {'id': 'Q05', 'label': 'Python / Flask',      'query': "python flask gunicorn déploiement"},
    {'id': 'Q06', 'label': 'Famille / enfants',   'query': "famille enfants école vacances"},
    {'id': 'Q07', 'label': 'DeepSeek / prompt',   'query': "deepseek prompt test LLM"},
    {'id': 'Q08', 'label': 'Mémoire NIMM',        'query': "mémoire souvenir extraction"},
    {'id': 'Q09', 'label': 'Cuisine / recette',   'query': "recette cuisine repas dîner"},
    {'id': 'Q10', 'label': 'Camion / route',      'query': "camion route transport chauffeur"},
]

def test_recall_fts5():
    sep('TEST 3 — Recall FTS5 (10 requêtes)')

    print(f"\n  {'ID':<5} {'Requête':<38} {'Résultats'}")
    print('  ' + '─' * 66)

    recall_stats = {'hits': 0, 'misses': 0}

    for q in RECALL_QUERIES:
        ids = search_bibliotheque_fts(q['query'], limit=5)
        if ids:
            entries = get_bibliotheque_by_ids(ids)
            recall_stats['hits'] += 1
            titres = [e.get('titre', '?')[:30] for e in entries[:2]]
            result_str = GREEN + f"{len(ids)} hit(s)" + RESET + f" → {', '.join(titres)}"
        else:
            recall_stats['misses'] += 1
            result_str = DIM + "aucun résultat" + RESET

        print(f"  {q['id']}  {q['label']:<38} {result_str}")

    print()
    hits   = recall_stats['hits']
    misses = recall_stats['misses']
    total  = len(RECALL_QUERIES)
    print(f"  Hits : {GREEN}{hits}/{total}{RESET}   Misses : {YELLOW}{misses}/{total}{RESET}")

    if hits == 0:
        ko("Aucun recall — la bibliothèque est vide ou les os_json ne contiennent pas de termes indexables.")
    elif hits < total // 2:
        warn(f"Peu de recalls ({hits}/{total}) — normal si la bibliothèque est peu alimentée.")
    else:
        ok(f"Recall fonctionnel ({hits}/{total} requêtes avec résultat).")

    return recall_stats

# ══════════════════════════════════════════════════════════════════════════════
# TEST 4 — INJECTION DANS LE SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════════════

def test_injection():
    sep('TEST 4 — Qualité de l\'injection dans le system prompt')

    print(f"\n  Simulation de recall_bibliotheque() sur 4 messages réels :\n")

    test_messages = [
        "Comment tu déploies une app Flask sur un serveur Ubuntu ?",
        "T'as des idées de cadeaux pour Nadia ?",
        "Parle-moi de la mémoire dans NIMM.",
        "C'est quoi la différence entre TCP et UDP ?",
    ]

    for msg in test_messages:
        context = recall_bibliotheque(msg)
        print(f"  Message : {CYAN}{msg}{RESET}")
        if context:
            lines = context.split('\n')
            ok(f"Context injecté ({len(context)} chars) :")
            for line in lines[:6]:
                print(f"    {line}")
            if len(lines) > 6:
                print(f"    {DIM}... (+{len(lines)-6} lignes){RESET}")
        else:
            info(f"Aucun contexte bibliothèque trouvé — comportement normal si DB vide.")
        print()

# ══════════════════════════════════════════════════════════════════════════════
# TEST 5 — DIAGNOSTIC GLOBAL
# ══════════════════════════════════════════════════════════════════════════════

def test_diagnostic(entries, recall_stats):
    sep('TEST 5 — Diagnostic global')

    total_entries = len(entries)
    hits          = recall_stats.get('hits', 0)

    print()

    # Santé des entrées
    entries_with_os_json  = sum(1 for e in entries if e.get('os_json'))
    entries_with_resume   = sum(1 for e in entries if e.get('resume_texte'))
    entries_with_tags     = sum(1 for e in entries if e.get('tags'))

    print(f"  Entrées actives       : {total_entries}")
    if total_entries > 0:
        pct_os  = int(100 * entries_with_os_json / total_entries)
        pct_res = int(100 * entries_with_resume  / total_entries)
        pct_tag = int(100 * entries_with_tags    / total_entries)
        color_os  = GREEN if pct_os  >= 80 else (YELLOW if pct_os  >= 50 else RED)
        color_res = GREEN if pct_res >= 80 else (YELLOW if pct_res >= 50 else RED)
        color_tag = GREEN if pct_tag >= 80 else (YELLOW if pct_tag >= 50 else RED)
        print(f"  Avec os_json          : {color_os}{entries_with_os_json}/{total_entries} ({pct_os}%){RESET}")
        print(f"  Avec resume_texte     : {color_res}{entries_with_resume}/{total_entries} ({pct_res}%){RESET}")
        print(f"  Avec tags             : {color_tag}{entries_with_tags}/{total_entries} ({pct_tag}%){RESET}")

    print(f"\n  Recall FTS5 (10 q.)   : {GREEN if hits >= 5 else YELLOW}{hits}/10{RESET}")

    print()
    # Conclusions actionables
    if total_entries == 0:
        warn("Pipeline bibliothèque non alimenté — archiver des fils via le bouton 📚 dans l'interface.")
    elif entries_with_os_json < total_entries:
        missing_os = total_entries - entries_with_os_json
        warn(f"{missing_os} entrée(s) sans os_json — le recall FTS5 sera inopérant sur ces entrées.")
        info("Cause probable : generate_bibliotheque_entry() n'a pas généré de os_json structuré.")
        info("Vérifier les logs lors du prochain archivage.")
    else:
        ok("Pipeline bibliothèque opérationnel.")

    if hits == 0 and total_entries > 0:
        warn("Recall FTS5 à 0 malgré des entrées — os_json peut-être mal structuré ou tokenisation inadaptée.")
        info("Vérifier que os_json contient du texte libre (pas uniquement des structures JSON vides).")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print(BOLD + '\n' + '=' * 70 + RESET)
    print(BOLD + '  NIMM — Audit pipeline Bibliothèque 📚' + RESET)
    print(f'  Lecture seule — base : {os.path.abspath(os.path.join(_ROOT, "data", "nimm.db"))}')
    print(BOLD + '=' * 70 + RESET)

    entries      = test_inventaire()
    test_contenu(entries)
    recall_stats = test_recall_fts5()
    test_injection()
    test_diagnostic(entries, recall_stats)

    sep('FIN DU DIAGNOSTIC')
    print()

if __name__ == '__main__':
    main()
