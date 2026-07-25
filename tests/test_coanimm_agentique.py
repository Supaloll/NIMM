# -*- coding: utf-8 -*-
"""Tests de la chaîne agentique CoaNIMM — moteur de ricochets, paramètre
d'entrée, journalisation et outils de chat.

Tout est SIMULÉ (aucun accès LLM, réseau ou base réelle) : on remplace db,
_execute, critique_result, repair_code et adapt_step_code par des doublures.
Exécution : python tests/test_coanimm_agentique.py  (depuis la racine du projet)
Sortie : une ligne « OK » par scénario, « TOUS LES TESTS PASSENT » à la fin.
"""
import asyncio
import os
import sys
import tempfile
import types

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import modules.coanimm as C            # noqa: E402
import modules.coanimm_ops as O        # noqa: E402
import core.database as real_db        # noqa: E402

WORKDIR = tempfile.mkdtemp(prefix='nimm_wf_test_')

_REAL_CRITIQUE_RESULT = C.critique_result   # capturée avant tout mock (test du réglage)

PASSED = []


def ok(nom):
    PASSED.append(nom)
    print(f"OK — {nom}")


def make_env(granted=None, wf_caps=None, two_steps=False):
    """Installe des doublures fraîches et renvoie les journaux (hist, seclog, stats)."""
    hist, seclog, stats = [], [], []
    skills = {
        'sk1': {'label': 'Bond A', 'meta': {'valide_par_laurent': True, 'script': "print('a')",
                                            'consigne_origine': 'faire A', 'capacites': []}},
        'sk2': {'label': 'Bond B', 'meta': {'valide_par_laurent': True, 'script': "print('b')",
                                            'consigne_origine': 'faire B', 'capacites': []}},
    }
    etapes = [{'skill_id': 'sk1', 'label': 'Bond A'}]
    if two_steps:
        etapes.append({'skill_id': 'sk2', 'label': 'Bond B'})
    wfs = {'wf': {'label': 'Ricochet test', 'created_at': '2026-07-24',
                  'meta': {'etapes': etapes, 'capacites': list(wf_caps or [])}}}

    def add_hist(consigne, status, summary, returncode=None, files_count=0, extra=None):
        e = {'consigne': consigne, 'status': status, 'summary': summary,
             'files_count': files_count}
        for k, v in (extra or {}).items():
            e.setdefault(k, v)
        hist.append(e)

    fake = types.SimpleNamespace(
        list_prompts=lambda t=None: dict(skills) if t == 'skill' else dict(wfs),
        list_coanimm_capabilities=lambda: list(granted or []),
        save_prompt=lambda *a, **k: stats.append((a, k)),
        add_coanimm_history=add_hist,
        add_coanimm_security_log=lambda e: seclog.append(e),
    )
    C.db = fake
    real_db.list_prompts = fake.list_prompts       # repris par les imports locaux (_find_ricochet)
    C._workspace_dir = lambda tid=None: WORKDIR
    C._find_relevant_skill = lambda c: None
    C._bump_skill_stat = lambda sid, okk: None

    async def crit_ok(*a, **k):
        return {'verdict': 'ok', 'motif': '', 'conseil': ''}
    C.critique_result = crit_ok

    async def noadapt(code, consigne, parametre, tid=None, provider_override=None):
        return code
    C.adapt_step_code = noadapt

    async def rep(code, fb, consigne='', tid=None, provider_override=None):
        return "print('répare')"
    C.repair_code = rep

    C._execute = lambda code, args, wd, tid=None, granted_caps=None: {
        'status': 'ok', 'stdout': 'out:' + code, 'stderr': '', 'returncode': 0}
    return hist, seclog, stats


def run_wf(param=''):
    async def _r():
        return [e async for e in C.run_workflow_stream('wf', parametre=param)]
    return asyncio.run(_r())


# ── 1. Moteur de ricochets ─────────────────────────────────────────────

def test_succes_direct():
    make_env()
    evts = run_wf()
    seq = [e['type'] for e in evts]
    assert seq == ['start', 'step_start', 'step_done', 'done'], seq
    assert evts[-1]['status'] == 'ok'
    assert evts[-1]['steps'][0]['output'].startswith('out:'), "la sortie d'étape doit venir de stdout"
    ok("moteur : succès direct, bilan d'étape depuis stdout")


def test_echec_puis_reparation():
    make_env()
    calls = {'n': 0}

    def ex(code, args, wd, tid=None, granted_caps=None):
        calls['n'] += 1
        if calls['n'] == 1:
            return {'status': 'ok', 'stdout': '', 'stderr': 'Boom', 'returncode': 1}
        return {'status': 'ok', 'stdout': 'réparé', 'stderr': '', 'returncode': 0}
    C._execute = ex
    evts = run_wf()
    seq = [e['type'] for e in evts]
    assert seq == ['start', 'step_start', 'step_repair', 'step_done', 'done'], seq
    assert evts[-1]['status'] == 'ok'
    ok("moteur : échec → réparation → succès")


def test_critique_puis_correction():
    make_env()
    crit = {'n': 0}

    async def c(*a, **k):
        crit['n'] += 1
        if crit['n'] == 1:
            return {'verdict': 'insuffisant', 'motif': 'fichier vide', 'conseil': 'écrire le contenu'}
        return {'verdict': 'ok'}
    C.critique_result = c
    evts = run_wf()
    seq = [e['type'] for e in evts]
    assert seq == ['start', 'step_start', 'step_critique', 'step_done', 'done'], seq
    assert evts[2]['motif'] == 'fichier vide'
    ok("moteur : critique insuffisante → correction → succès")


def test_capacite_manquante():
    make_env(granted=[], wf_caps=['reseau'])
    evts = run_wf()
    assert [e['type'] for e in evts] == ['done']
    assert evts[0]['missing_capabilities'] == ['reseau']
    ok("moteur : capacité manquante → refus avant toute exécution")


def test_arret_sur_erreur():
    make_env(two_steps=True)
    C._execute = lambda code, args, wd, tid=None, granted_caps=None: {
        'status': 'ok', 'stdout': '', 'stderr': 'Persistant', 'returncode': 1}
    evts = run_wf()
    assert evts[-1]['status'] == 'error'
    assert len(evts[-1]['steps']) == 1, "l'étape 2 ne doit jamais être lancée"
    ok("moteur : échec persistant → arrêt, étape suivante non lancée")


def test_wrapper_non_stream():
    make_env()
    res = asyncio.run(C.run_workflow('wf'))
    assert res['status'] == 'ok' and 'steps' in res
    ok("moteur : run_workflow (non-stream) renvoie le payload final")


# ── 2. Entrée du ricochet (paramètre) ──────────────────────────────────

def test_adaptation_appelee():
    make_env()
    appels = []

    async def ad(code, consigne, parametre, tid=None, provider_override=None):
        appels.append(parametre)
        return "print('adapté')"
    C.adapt_step_code = ad
    evts = run_wf('rapport janvier')
    seq = [e['type'] for e in evts]
    assert seq == ['start', 'step_start', 'step_adapt', 'step_done', 'done'], seq
    assert appels == ['rapport janvier']
    assert 'adapté' in evts[-1]['steps'][0]['output']
    ok("entrée : adaptation appelée et script adapté exécuté")


def test_sans_entree_pas_dadaptation():
    make_env()
    appels = []

    async def ad(code, consigne, parametre, tid=None, provider_override=None):
        appels.append(parametre)
        return code
    C.adapt_step_code = ad
    evts = run_wf('')
    assert [e['type'] for e in evts] == ['start', 'step_start', 'step_done', 'done']
    assert not appels
    ok("entrée : champ vide → aucune adaptation, script d'origine")


def test_adaptation_invalide_repli():
    make_env()

    async def ad(code, consigne, parametre, tid=None, provider_override=None):
        return "def broken(:"
    C.adapt_step_code = ad
    evts = run_wf('x')
    assert evts[-1]['status'] == 'ok'
    assert "out:print('a')" == evts[-1]['steps'][0]['output'], "repli attendu sur le script validé"
    ok("entrée : adaptation invalide → repli sur le script validé")


# ── 3. Journalisation ──────────────────────────────────────────────────

def test_journalisation_succes():
    hist, seclog, _ = make_env()
    run_wf('dossier X')
    assert hist[-1]['consigne'] == '[Ricochet] Ricochet test — entrée : dossier X'
    assert hist[-1]['status'] == 'ok'
    assert hist[-1]['kind'] == 'workflow' and hist[-1]['workflow_id'] == 'wf'
    assert hist[-1]['parametre'] == 'dossier X'
    assert seclog[-1]['workflow'] == 'Ricochet test' and seclog[-1]['status'] == 'ok'
    ok("journal : succès journalisé (historique relançable + sécurité)")


def test_journalisation_refus_capacite():
    hist, seclog, _ = make_env(granted=[], wf_caps=['reseau'])
    run_wf()
    assert hist[-1]['status'] == 'error' and 'capacités non autorisées' in hist[-1]['summary']
    assert seclog[-1]['status'] == 'erreur' and seclog[-1]['reasons']
    ok("journal : refus de capacité journalisé")


def test_journalisation_echec_etape():
    hist, _seclog, _ = make_env()
    C._execute = lambda code, args, wd, tid=None, granted_caps=None: {
        'status': 'ok', 'stdout': '', 'stderr': 'boom', 'returncode': 1}
    run_wf()
    assert hist[-1]['status'] == 'error' and 'Arrêt' in hist[-1]['summary']
    ok("journal : échec d'étape journalisé")


# ── 4. Outils de chat (coanimm_ops) ────────────────────────────────────

def test_chat_liste():
    make_env()
    out = asyncio.run(O.op_list_ricochets())
    assert 'Ricochet test' in out and 'Bond A' in out
    ok("chat : list_ricochets liste les ricochets")


def test_chat_resolution_nom():
    make_env()

    async def fake_run(wid, tid=None, parametre=''):
        return {'status': 'ok', 'message': f'{wid} terminé.', 'steps': [{'label': 'Bond A', 'status': 'ok'}], 'files_info': ''}
    C.run_workflow = fake_run
    assert 'wf terminé' in asyncio.run(O.op_run_ricochet('ricochet test'))
    assert 'wf terminé' in asyncio.run(O.op_run_ricochet('ricochet'))
    out = asyncio.run(O.op_run_ricochet('inexistant'))
    assert 'introuvable' in out and 'Ricochet test' in out
    ok("chat : résolution de nom exacte, partielle, introuvable")


def test_chat_dispatch():
    make_env()

    async def fake_run(wid, tid=None, parametre=''):
        return {'status': 'ok', 'message': f'{wid} via dispatch ({parametre}).', 'steps': [], 'files_info': ''}
    C.run_workflow = fake_run
    out = asyncio.run(O.dispatch_async_op('run_ricochet', {'nom': 'Ricochet test', 'entree': 'S30'}))
    assert 'wf via dispatch (S30)' in out
    assert {'run_ricochet', 'list_ricochets'} <= O.ASYNC_OPS_NAMES
    noms = [t.get('function', {}).get('name') for t in O.ASYNC_OPS_TOOLS]
    assert 'run_ricochet' in noms and 'list_ricochets' in noms
    ok("chat : dispatch + outils déclarés au modèle")


# ── 5. Fiabilité des ricochets + réglage critique ──────────────────────

def test_fiabilite_ricochet():
    _h, _s, stats = make_env()
    run_wf()
    wf_updates = [k for a, k in stats if k.get('type') == 'workflow']
    assert wf_updates and int(wf_updates[-1]['meta'].get('runs_ok', 0)) == 1, stats
    _h, _s, stats = make_env()
    C._execute = lambda code, args, wd, tid=None, granted_caps=None: {
        'status': 'ok', 'stdout': '', 'stderr': 'boom', 'returncode': 1}
    run_wf()
    wf_updates = [k for a, k in stats if k.get('type') == 'workflow']
    assert wf_updates and int(wf_updates[-1]['meta'].get('runs_err', 0)) == 1, stats
    ok("fiabilité : compteurs runs_ok/runs_err du ricochet incrémentés")


def test_critique_desactivable():
    make_env()
    C.db.get_setting = lambda k, d=None: '0'   # réglage : critique désactivée
    res = asyncio.run(_REAL_CRITIQUE_RESULT('consigne', 'code', {'stdout': '', 'files_list': []}))
    assert res['verdict'] == 'ok' and res.get('desactive') is True, res
    ok("réglage : critique désactivée → verdict ok immédiat, sans appel IA")


# ── 6. Planification (schedule_due, fonction pure) ─────────────────────

def test_echeances():
    import datetime as dt
    lundi_10h = dt.datetime(2026, 7, 20, 10, 0)   # un lundi
    base = {'actif': True, 'jour': None, 'heure': 9, 'minute': 30, 'dernier_run': ''}
    assert C.schedule_due(dict(base), lundi_10h) is True                       # 9h30 passée, jamais lancée
    assert C.schedule_due(dict(base, heure=11), lundi_10h) is False            # pas encore l'heure
    assert C.schedule_due(dict(base, actif=False), lundi_10h) is False         # désactivée
    assert C.schedule_due(dict(base, jour=0), lundi_10h) is True               # lundi = 0, on est lundi
    assert C.schedule_due(dict(base, jour=3), lundi_10h) is False              # jeudi ≠ lundi
    assert C.schedule_due(dict(base, dernier_run='2026-07-20T09:31:00'), lundi_10h) is False  # déjà lancée
    assert C.schedule_due(dict(base, dernier_run='2026-07-19T09:31:00'), lundi_10h) is True   # lancée hier
    assert C.schedule_due(dict(base, heure='zz'), lundi_10h) is False          # heure invalide → jamais
    ok("planification : 8 cas d'échéance (heure, jour, actif, dernier_run, invalide)")


def test_worker_marque_a_notifier():
    """Un tick du planificateur exécute l'échéance et marque le run à annoncer."""
    scheds = [{'id': 's1', 'workflow_id': 'wf', 'label': 'Ricochet test', 'jour': None,
               'heure': 0, 'minute': 0, 'parametre': 'X', 'actif': True,
               'dernier_run': '', 'dernier_statut': ''}]
    majs = []

    def upd(sid, **champs):
        majs.append((sid, champs))
        for s in scheds:
            if s['id'] == sid:
                s.update(champs)
        return scheds

    C.db = types.SimpleNamespace(list_coanimm_schedules=lambda: [dict(s) for s in scheds],
                                 update_coanimm_schedule=upd)

    async def fake_run(wid, tid=None, parametre=''):
        return {'status': 'ok', 'message': 'Terminé (1 étapes).'}
    C.run_workflow = fake_run

    async def un_tick():
        # rejoue le corps d'un tick sans la boucle infinie
        for s in C.db.list_coanimm_schedules():
            if not C.schedule_due(s):
                continue
            C.db.update_coanimm_schedule(s['id'], dernier_run='2026-07-24T09:00:00',
                                         dernier_statut='en cours')
            res = await C.run_workflow(s['workflow_id'], None, parametre=s.get('parametre', ''))
            C.db.update_coanimm_schedule(s['id'], dernier_statut=res.get('status', 'error'),
                                         dernier_message=(res.get('message') or '')[:300],
                                         notifie=False)
    asyncio.run(un_tick())
    assert majs[0][1]['dernier_statut'] == 'en cours', "dernier_run posé AVANT l'exécution"
    assert majs[-1][1] == {'dernier_statut': 'ok', 'dernier_message': 'Terminé (1 étapes).',
                           'notifie': False}, majs[-1]
    # après notification, plus rien à annoncer
    upd('s1', notifie=True)
    assert scheds[0]['notifie'] is True
    ok("planification : exécution marquée à annoncer, puis consommée")


# ── 7. Scripts enregistrés : boucle agentique ──────────────────────────

def _env_script(exec_fn):
    """Doublures pour run_script_agentique : un script enregistré 'sc1'."""
    scripts = {'sc1': {'label': 'Mon script', 'text': "print('orig')", 'meta': {}}}
    C.db = types.SimpleNamespace(
        list_prompts=lambda t=None: dict(scripts) if t == 'script' else {},
        grant_agent_permission=lambda *a, **k: None,
        agent_permission_granted=lambda *a, **k: True,
    )
    C._workspace_dir = lambda tid=None: WORKDIR
    C._scan_new_files = lambda wd, before: []
    C._route_new_files = lambda files, tid=None: ('', [])
    C._execute = exec_fn

    async def rep(code, fb, consigne='', tid=None, provider_override=None):
        return "print('corrigé')"
    C.repair_code = rep


def test_script_reparation():
    calls = {'n': 0}

    def ex(code, args, wd, tid=None, granted_caps=None):
        calls['n'] += 1
        if calls['n'] == 1:
            return {'status': 'ok', 'stdout': '', 'stderr': 'Boom', 'returncode': 1}
        return {'status': 'ok', 'stdout': 'ok après correction', 'stderr': '', 'returncode': 0}
    _env_script(ex)

    async def crit_ok(*a, **k):
        return {'verdict': 'ok'}
    C.critique_result = crit_ok
    res = asyncio.run(C.run_script_agentique('sc1'))
    assert res['returncode'] == 0 and calls['n'] == 2, res
    assert res.get('code_corrige') == "print('corrigé')", "le code corrigé est proposé, pas enregistré"
    ok("script enregistré : échec → correction → succès (script en base inchangé)")


def test_script_permission_inchangee():
    _env_script(lambda code, args, wd, tid=None, granted_caps=None: {
        'status': 'ok', 'stdout': '', 'stderr': '', 'returncode': 0})
    C.db.agent_permission_granted = lambda *a, **k: False
    res = asyncio.run(C.run_script_agentique('sc1'))
    assert res['status'] == 'permission_required', res
    ok("script enregistré : permission requise → renvoyée telle quelle, rien n'est exécuté")


def test_script_blocage_securite_pas_de_retry():
    calls = {'n': 0}

    def ex(code, args, wd, tid=None, granted_caps=None):
        calls['n'] += 1
        return {'status': 'error', 'message': 'refusé', 'blocked': [{'message': 'shell'}],
                'stdout': '', 'stderr': '', 'returncode': 1}
    _env_script(ex)
    res = asyncio.run(C.run_script_agentique('sc1'))
    assert calls['n'] == 1, "un blocage sécurité ne doit jamais être réessayé"
    assert res.get('blocked')
    ok("script enregistré : blocage sécurité → aucun nouvel essai")


if __name__ == '__main__':
    for fn in [test_succes_direct, test_echec_puis_reparation, test_critique_puis_correction,
               test_capacite_manquante, test_arret_sur_erreur, test_wrapper_non_stream,
               test_adaptation_appelee, test_sans_entree_pas_dadaptation, test_adaptation_invalide_repli,
               test_journalisation_succes, test_journalisation_refus_capacite, test_journalisation_echec_etape,
               test_chat_liste, test_chat_resolution_nom, test_chat_dispatch,
               test_fiabilite_ricochet, test_critique_desactivable, test_echeances,
               test_worker_marque_a_notifier,
               test_script_reparation, test_script_permission_inchangee,
               test_script_blocage_securite_pas_de_retry]:
        fn()
    print(f"\nTOUS LES TESTS PASSENT ({len(PASSED)} scénarios).")
