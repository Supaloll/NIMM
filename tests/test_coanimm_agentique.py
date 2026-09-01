# -*- coding: utf-8 -*-
"""Tests de la chaîne agentique CoaNIMM — moteur de ricochets, paramètre
d'entrée, journalisation et outils de chat.

Tout est SIMULÉ (aucun accès LLM, réseau ou base réelle) : on remplace db,
_execute, critique_result, repair_code et adapt_step_code par des doublures.
Exécution : python tests/test_coanimm_agentique.py  (depuis la racine du projet)
Sortie : une ligne « OK » par scénario, « TOUS LES TESTS PASSENT » à la fin.
"""
import ast
import asyncio
import re
import json
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


# ── 6 bis. Facturation de la mise en cache Anthropic ───────────────────

def test_facturation_cache():
    """La pondération doit refléter les tarifs : écriture 1,25x, relecture 0,1x.
    Sans elle, le tableau des coûts serait faux dès que le cache est actif."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'core', 'engine.py'), encoding='utf-8').read()
    i = src.find('def _anthropic_billable_input')
    j = src.find('\ndef ', i + 10)
    ns = {}
    exec(src[i:j], ns)                      # isolé : engine.py entier exige httpx
    f = ns['_anthropic_billable_input']
    assert f({'input_tokens': 100}) == 100
    assert f({'input_tokens': 0, 'cache_creation_input_tokens': 1000}) == 1250
    assert f({'input_tokens': 0, 'cache_read_input_tokens': 1000}) == 100
    assert f({'input_tokens': 50, 'cache_creation_input_tokens': 100,
              'cache_read_input_tokens': 1000}) == 275
    assert f({}) == 0 and f(None) == 0
    ok("cache Anthropic : facturation pondérée (plein tarif, écriture, relecture, mixte)")


def test_specificites_anthropic_confinees():
    """NIMM doit continuer à marcher avec les autres API : aucune nouveauté
    Anthropic ne doit fuir dans un appel Mistral, Gemini, Ollama…"""
    import re
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()

    def corps(nom):
        i = src.find(f'async def {nom}(')
        if i < 0:
            i = src.find(f'def {nom}(')
        j, k = src.find('\nasync def ', i + 10), src.find('\ndef ', i + 10)
        return src[i:min([x for x in (j, k) if x > 0] or [len(src)])]

    # 1. Les champs propres à Anthropic ne sont posés que dans ses fonctions.
    #    EXCEPTION `thinking` (correctif de Laurent, 07/08/2026) : cette clé n'est
    #    plus propre à Anthropic, et les deux fournisseurs l'emploient en sens
    #    INVERSE. Anthropic s'en sert pour ACTIVER une réflexion étendue
    #    ({'type': 'enabled', budget}) ; DeepSeek pour la DÉSACTIVER
    #    ({'type': 'disabled'}), son modèle v4 la lançant d'office — ce qui
    #    ajoutait plusieurs secondes avant le premier mot et vidait le budget de
    #    sortie en jetons invisibles (titres et résumés vides).
    #    La règle juste n'est donc plus « Anthropic seulement » mais « jamais
    #    sans savoir à qui on parle » : hors fonction Anthropic, la pose doit
    #    être gardée par un test explicite sur le fournisseur.
    for motif in ("payload['cache_control']", "payload['output_config']"):
        for m in re.finditer(re.escape(motif), src):
            debut = src.rfind('def ', 0, m.start())
            nom = src[debut:src.find('(', debut)]
            assert 'anthropic' in nom, f"{motif} posé hors Anthropic ({nom})"

    for m in re.finditer(re.escape("payload['thinking']"), src):
        debut = src.rfind('def ', 0, m.start())
        nom = src[debut:src.find('(', debut)]
        if 'anthropic' in nom:
            continue
        amont = src[max(0, m.start() - 400):m.start()]
        assert re.search(r"provider\s*==\s*'\w+'", amont), (
            f"payload['thinking'] posé dans {nom} sans garde sur le fournisseur : "
            "un fournisseur qui ignore ce champ le refusera")
    # Les deux sémantiques ne doivent pas se confondre.
    for m in re.finditer(r"payload\['thinking'\] = \{'type': 'disabled'\}", src):
        amont = src[max(0, m.start() - 400):m.start()]
        assert "'deepseek'" in amont, "réflexion désactivée sans dire pour quel fournisseur"

    # 2. Dans call_llm, chaque paramètre ne part que vers les fonctions qui le gèrent
    plat = re.sub(r'\s+', ' ', corps('call_llm'))
    for nom, args in re.findall(r'await (_call_\w+)\(([^()]*(?:\([^()]*\)[^()]*)*)\)', plat):
        if 'thinking_budget=' in args:
            assert nom == '_call_anthropic', f"thinking_budget transmis à {nom}"
        if 'output_schema=' in args:
            assert nom in ('_call_anthropic', '_call_openai_compat'), f"output_schema transmis à {nom}"

    # 3. response_format : allowlist stricte (un champ inconnu ferait échouer l'appel)
    ns = {}
    exec(src[src.find('_JSON_SCHEMA_PROVIDERS'):src.find('async def count_tokens(')], ns)
    rf = ns['_oai_response_format']
    assert rf('mistral', {'type': 'object'}) and rf('openai', {'type': 'object'})
    assert rf('deepseek', {'type': 'object'}) is None
    assert rf('ollama', {'type': 'object'}) is None
    assert rf('mistral', None) is None

    # 4. Comptage : exact là où l'API l'expose, « inconnu » ailleurs — jamais inventé
    ct = corps('count_tokens')
    assert "provider == 'anthropic'" in ct and "provider == 'gemini'" in ct
    assert ct.rstrip().endswith('return -1')
    ok("multi-fournisseurs : les spécificités Anthropic restent confinées")


def test_avis_raison_arret():
    """Une réponse coupée par la limite de longueur arrive tronquée SANS signal :
    invisible pour qui lit en braille ou à la voix. On vérifie que l'avis est émis
    pour les arrêts anormaux seulement, et jamais sur une fin normale."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    import re as _re          # la tranche exécutée contient aussi des motifs compilés
    ns = {'re': _re, 'json': __import__('json')}
    exec(src[src.find('_AVIS_STOP = {'):src.find('\ndef _anthropic_billable_input')], ns)
    f = ns['_avis_stop_reason']
    assert 'limite de longueur' in f('max_tokens')
    assert 'préféré ne pas' in f('refusal')
    assert 'pause' in f('pause_turn')
    for normal in ('end_turn', 'tool_use', '', None):
        assert f(normal) == '', f"aucun avis attendu pour {normal!r}"
    ok("raison d'arrêt : troncature et refus annoncés, fin normale silencieuse")


def test_rag_ancrage_lexical():
    """Un score sémantique élevé ne suffit pas : deux textes français sans rapport
    atteignent couramment 0,5 de similarité. Cas vécu — un PDF sur l'accessibilité
    des livres numériques servi en pleine conversation bancaire."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hub = open(os.path.join(racine, 'core', 'hub.py'), encoding='utf-8').read()
    assert 'rag_ancrage_lexical' in hub, 'ancrage lexical absent'
    assert 'Document écarté' in hub, 'un rejet doit être tracé pour pouvoir régler'
    assert "len(m) >= 4" in hub, "seuls les mots de fond servent d'ancrage"

    # Règle telle qu'implémentée
    def retenu(mots, passage, titre, score, seuil=0.5, ancrage=True):
        fond = {m for m in mots if len(m) >= 4}
        if score < seuil:
            return False
        communs = [m for m in fond if m in passage.lower() or m in titre.lower()]
        return not (ancrage and not communs)

    q = {'récapitulatif', 'économies', 'possibles', 'ultim', 'metal', 'welcome'}
    hs = "Étude sur l'accessibilité effective des sites de vente de livres numériques"
    assert not retenu(q, hs, hs, 0.55), 'le document hors sujet doit être écarté'
    q2 = {'frais', 'conversion', 'devise'}
    ok2 = "Les frais de conversion en devise étrangère sont facturés 2 %."
    assert retenu(q2, ok2, 'Guide bancaire', 0.55), 'un document pertinent doit passer'
    assert not retenu({'gbp', 'eur'}, 'Texte sans rapport.', 'Doc', 0.9), 'mots courts ignorés'
    assert retenu(q, hs, hs, 0.55, ancrage=False), 'le réglage doit pouvoir être coupé'
    assert not retenu(q2, ok2, 'Guide', 0.3), 'le seuil sémantique reste prioritaire'
    ok("base de connaissances : ancrage lexical contre les documents hors sujet")


def test_reprise_sans_couture():
    """Reprendre par un « Continue. » fait redémarrer le modèle : préambule,
    redites, phrase recommencée. Anthropic, Mistral et DeepSeek savent poursuivre
    leur propre texte — on leur redonne la fin de leur réponse."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    lignes = eng.splitlines(keepends=True)

    def corps(nom):
        for n in ast.walk(ast.parse(eng)):
            if getattr(n, 'name', '') == nom:
                return ''.join(lignes[n.lineno - 1:n.end_lineno])
        raise AssertionError(f'{nom} introuvable')

    ns = {'_PREFIXE_SUPPORTE': {'anthropic', 'mistral', 'deepseek'}}
    exec(corps('supporte_prefixe'), ns, ns)
    f = ns['supporte_prefixe']
    for oui in ('anthropic', 'mistral', 'deepseek', 'MISTRAL'):
        assert f(oui), oui
    for non in ('gemini', 'openai', 'ollama', 'openrouter', ''):
        assert not f(non), f'{non} ne supporte pas la reprise par préfixe'

    seg = corps('continuer_reponse_stream')
    assert 'if not prefixe or not supporte_prefixe(provider):' in seg, \
        'repli si non supporté OU si rien à poursuivre'
    assert "'content': 'Continue.'" in seg, "le repli garde le comportement d'avant"
    assert "{'role': 'assistant', 'content': prefixe}" in seg, 'Anthropic : préremplissage'
    assert "'prefix': True" in seg, 'Mistral et DeepSeek : champ prefix'
    assert 'https://api.deepseek.com/beta' in seg, "DeepSeek exige son point d'entrée bêta"
    assert "'__truncated__'" in seg, 'une reprise peut être tronquée à son tour'

    assert 'continuer_reponse_stream' in mn
    assert "m.get('role') == 'assistant'" in mn, 'le préfixe est la dernière réponse'
    assert 'data: [TRUNCATED]' in mn, 'le bouton doit pouvoir réapparaître'
    ok("reprise : sans couture chez trois fournisseurs, repli ailleurs")


def test_correlation_modele_agent_recherche():
    """Le bouton « recherche web » se calait sur le MODÈLE ACTIF et ignorait le
    réglage : choisir Claude puis discuter avec Gemini donnait l'ancrage Google,
    sans le dire. Et le bouton Vibe n'apparaissait que selon la PRÉSENCE d'une clé
    Mistral, alors que ce mode exige que Mistral RÉPONDE."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hub = open(os.path.join(racine, 'core', 'hub.py'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()

    assert '_choisir_recherche_web' in hub
    assert "web_search and provider ==" not in hub, \
        'plus aucun branchement direct sur le modèle actif'
    assert hub.count('_choisir_recherche_web') >= 3, 'utilisé sur les deux chemins'

    def choisir(provider, choisi, cles):
        if choisi == 'anthropic':
            return 'anthropic' if cles.get('anthropic') else 'brave'
        if choisi == 'mistral':
            if cles.get('mistral'):
                return 'mistral_natif' if provider == 'mistral' else 'mistral'
            return 'brave'
        if choisi == 'gemini':
            return 'gemini_natif' if (provider == 'gemini' and cles.get('gemini')) else 'brave'
        return 'brave'

    cles = {'anthropic': 'a', 'mistral': 'm', 'gemini': 'g'}
    assert choisir('gemini', 'anthropic', cles) == 'anthropic', 'le réglage prime'
    assert choisir('anthropic', 'mistral', cles) == 'mistral', 'le réglage prime'
    assert choisir('mistral', 'mistral', cles) == 'mistral_natif', 'un seul appel si possible'
    assert choisir('anthropic', 'gemini', cles) == 'brave', "l'ancrage exige Gemini actif"
    assert choisir('gemini', 'gemini', cles) == 'gemini_natif'
    assert choisir('gemini', 'anthropic', {'gemini': 'g'}) == 'brave', 'clé absente → repli'
    assert choisir('anthropic', '', cles) == 'brave', 'par défaut : Brave/Tavily'

    # Vibe suit le modèle actif, pas seulement la clé
    assert 'mistralActif' in app and '_providerActif' in app
    assert "_setAgentMode('')" in app, 'un mode devenu inapplicable doit être quitté'
    assert 'nécessite Mistral comme modèle actif' in app, "et l'utilisateur doit l'apprendre"
    ok("agent et recherche web : corrélés au modèle actif, réglage prioritaire")


def test_description_video():
    """Une vidéo est le contenu le plus opaque quand on ne voit pas : la bande-son
    ne dit presque jamais ce qui est montré. Gemini sait la décrire, y compris
    depuis un lien YouTube — capacité qu'aucun autre fournisseur branché n'offre."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    coa = open(os.path.join(racine, 'modules', 'coanimm.py'), encoding='utf-8').read()
    saf = open(os.path.join(racine, 'modules', 'coanimm_safety.py'), encoding='utf-8').read()

    seg = ''
    for n in ast.walk(ast.parse(eng)):
        if getattr(n, 'name', '') == 'describe_video_gemini':
            seg = ast.get_source_segment(eng, n) or ''
    assert seg, 'describe_video_gemini introuvable'
    assert "startswith(('http://', 'https://'))" in seg, 'un lien doit être accepté tel quel'
    assert "'file_data'" in seg and "'inline_data'" in seg, 'lien ET fichier local'
    assert '18 * 1024 * 1024' in seg, 'garde de taille pour l’envoi direct'
    assert 'MAX_TOKENS' in seg, 'une description tronquée doit être signalée'
    assert 'VU' in seg and 'DIT' in seg, 'séparer ce qui est vu de ce qui est dit'
    assert 'minute:seconde' in seg, 'des repères de temps pour se situer'
    assert "n'invente rien" in seg, 'consigne factuelle'

    assert '/api/coanimm/describe_video' in mn
    assert 'describe_video' in mn and 'list_coanimm_disabled_tools' in mn, 'désactivable'
    assert coa.count('nimm_describe_video') >= 3, 'helper + prologue + doc'
    assert "'nimm_describe_video': 'recherche'" in saf, 'la vidéo part au cloud'
    ok("description de vidéo : lien ou fichier, repères de temps, vu/dit séparés")


def test_visibilite_selon_les_cles():
    """Plusieurs fonctions ne valent que pour un fournisseur (MCP et vérification
    des faits = Claude). Les exposer sans la clé correspondante donne des boutons
    qui échouent, et allonge le parcours au lecteur d'écran pour rien.
    Règle unique et déclarative : data-needs-key."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()

    assert '_majVisibiliteParCle' in app and '_cleDisponible' in app
    assert "querySelectorAll('option[data-needs-key]')" in app, 'options grisées'
    assert "querySelectorAll('[data-needs-key]:not(option)')" in app, 'le reste masqué'
    assert '_majVisibiliteParCle(keys)' in app, 'appliqué au chargement des clés'

    # Les fonctions propres à un fournisseur sont bien étiquetées
    assert 'id="mcp-section" data-needs-key="anthropic"' in html
    assert 'div data-needs-key="anthropic"' in html, 'réglage de cache Anthropic'
    assert '<option value="anthropic" data-needs-key="anthropic">' in html, 'lot Claude'
    assert '<option value="mistral" data-needs-key="mistral">' in html, 'lot Mistral'

    # Règle telle qu'implémentée
    def etat(tag, need, cles):
        dispo = bool(cles.get(need) or cles.get(need.replace('-', '_')))
        return ('active' if dispo else 'grisée') if tag == 'option' \
            else ('visible' if dispo else 'masqué')

    assert etat('div', 'anthropic', {'mistral': 'm'}) == 'masqué'
    assert etat('option', 'anthropic', {'mistral': 'm'}) == 'grisée'
    assert etat('option', 'mistral', {'mistral': 'm'}) == 'active'
    assert etat('div', 'anthropic', {'anthropic': 'a'}) == 'visible'
    assert etat('div', 'anthropic', {}) == 'masqué'
    ok("visibilité : une fonction n'apparaît que si sa clé est configurée")


def test_caches_de_contexte():
    """Gemini (2.5+) et DeepSeek mettent le contexte en cache AUTOMATIQUEMENT et
    facturent les tokens relus 90 % moins cher, chacun dans ses propres champs.
    Ne pas les distinguer SURÉVALUE la dépense — l'inverse du défaut trouvé sur
    le cache Anthropic, où elle était sous-évaluée."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    lignes = src.splitlines(keepends=True)

    def corps(nom):
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.FunctionDef) and n.name == nom:
                return ''.join(lignes[n.lineno - 1:n.end_lineno])
        raise AssertionError(f'{nom} introuvable')

    ns = {'_REMISE_CACHE': 0.1}
    exec(corps('_gemini_tokens_entree'), ns)
    exec(corps('_oai_tokens_entree'), ns)
    g, o = ns['_gemini_tokens_entree'], ns['_oai_tokens_entree']

    # Gemini : le compte caché est INCLUS dans le total
    assert g({'promptTokenCount': 1000}) == 1000
    assert g({'promptTokenCount': 1000, 'cachedContentTokenCount': 800}) == 280
    assert g({'promptTokenCount': 500, 'cachedContentTokenCount': 900}) == 50, \
        'le cache ne peut pas dépasser le total'
    assert g({}) == 0 and g(None) == 0

    # DeepSeek : entrée éclatée en touché / manqué
    assert o({'prompt_cache_hit_tokens': 1200, 'prompt_cache_miss_tokens': 300}) == 420
    assert o({'prompt_tokens': 1500}) == 1500, 'fournisseur sans cache : inchangé'
    assert o({'prompt_tokens': 1500, 'prompt_cache_hit_tokens': 1200,
              'prompt_cache_miss_tokens': 300}) == 420, 'les champs de cache priment'
    assert o({}) == 0 and o(None) == 0

    # Plus aucun chemin ne doit journaliser l'entrée brute
    assert "usage.get('prompt_tokens', 0)," not in src
    assert "meta.get('promptTokenCount', 0)," not in src
    ok("caches automatiques : entrée pondérée pour Gemini et DeepSeek")


def test_specificites_gemini_et_openai():
    """Deux dépenses et un refus silencieux, trouvés en lisant les docs :
    — Gemini « pense » PAR DÉFAUT (séries 3.x et 2.5) et facture ces tokens à part ;
      ne compter que la réponse sous-évaluait la dépense.
    — Les modèles de raisonnement OpenAI (série o) refusent `max_tokens` et
      `temperature` ; le catalogue interrogé en direct les propose désormais."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    lignes = src.splitlines(keepends=True)

    def corps(nom):
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.FunctionDef) and n.name == nom:
                return ''.join(lignes[n.lineno - 1:n.end_lineno])
        raise AssertionError(f'{nom} introuvable')

    ns = {}
    exec(corps('_gemini_tokens_sortie'), ns)
    g = ns['_gemini_tokens_sortie']
    assert g({'candidatesTokenCount': 100}) == 100
    assert g({'candidatesTokenCount': 100, 'thoughtsTokenCount': 297}) == 397, \
        'les tokens de pensée sont facturés et doivent être comptés'
    assert g({}) == 0 and g(None) == 0
    assert "meta.get('candidatesTokenCount', 0))" not in src, \
        'plus aucun comptage Gemini ne doit ignorer la pensée'

    ns2 = {}
    exec(corps('_modele_raisonnement_openai'), ns2)
    o = ns2['_modele_raisonnement_openai']
    for oui in ('o1', 'o1-mini', 'o3', 'o3-mini', 'O4-preview'):
        assert o(oui), oui
    for non in ('gpt-4o', 'gpt-4o-mini', 'gpt-5', 'mistral-large-latest', ''):
        assert not o(non), f'faux positif : {non}'

    for n in ast.walk(ast.parse(src)):
        if getattr(n, 'name', '') == 'call_llm_stream_with_tools':
            seg = ast.get_source_segment(src, n)
            assert "'max_completion_tokens' if _raisonneur_oai else 'max_tokens'" in seg
            assert 'if not _sans_outils and not _raisonneur_oai:' in seg
    ok("Gemini : pensée facturée comptée ; OpenAI série o : bons paramètres")


def test_modele_de_raisonnement():
    """deepseek-reasoner : sa chaîne de pensée arrive dans un champ SÉPARÉ que NIMM
    jetait, et il n'accepte NI les appels d'outils NI les paramètres
    d'échantillonnage — que NIMM lui envoyait quand même."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    hub = open(os.path.join(racine, 'core', 'hub.py'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()

    ns = {}
    exec(eng[eng.find('_MODELES_SANS_OUTILS'):
             eng.find('\ndef _anthropic_billable_input')], ns)
    f = ns['_modele_sans_outils']
    assert f('deepseek-reasoner') and f('DeepSeek-Reasoner'), 'casse indifférente'
    for autre in ('deepseek-v4-flash', 'mistral-large-latest', 'gpt-4o', ''):
        assert not f(autre), f'garde trop large : {autre}'

    for n in ast.walk(ast.parse(eng)):
        if getattr(n, 'name', '') == 'call_llm_stream_with_tools':
            seg = ast.get_source_segment(eng, n)
            assert 'if not _sans_outils' in seg
            assert "payload['tools'] = tools" in seg
            assert "payload['temperature'] = temperature" in seg, \
                'la température aussi doit être conditionnée'

    # Chaîne de pensée : captée, émise, relayée, affichée repliée
    assert "delta.get('reasoning_content', '')" in eng
    assert "yield {'__raisonnement__'" in eng
    assert hub.count('[RAISONNEMENT]') == 2, 'relayé sur les deux chemins'
    assert "data.startsWith('[RAISONNEMENT]')" in app and '_ajouterRaisonnement' in app
    # Elle ne doit jamais repartir en entrée : l'API renvoie 400 si on la lui renvoie
    i = hub.find("elif token.get('__raisonnement__')")
    assert i > 0 and 'continue' in hub[i:i + 400], \
        'la sentinelle ne doit pas être concaténée à la réponse enregistrée'
    ok("modèle de raisonnement : pensée conservée et repliée, outils non envoyés")


def test_plan_de_la_reponse():
    """Une réponse se découvre linéairement à la voix ou en braille : on ignore où
    elle va et ce qu'il reste. Sa structure est donc annoncée AVANT la lecture,
    à partir des titres réellement rendus. Purement local : aucun appel, aucun coût."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    assert '_planDeLaReponse' in app and '_PLAN_SEUIL_MOTS' in app
    assert "querySelectorAll('h1, h2, h3, h4')" in app, \
        'les titres rendus sont aussi les repères de navigation du lecteur d\'écran'
    assert "NIMM t'a répondu — ${_plan}" in app, "l'annonce doit porter le plan"

    # Règle telle qu'implémentée
    def plan(texte, titres=(), puces=0, code=0, seuil=120):
        mots = len(texte.split()) if texte.strip() else 0
        if mots < seuil:
            return ''
        titres = [t for t in titres if t]
        if len(titres) >= 2:
            reste = f", et {len(titres) - 6} autres" if len(titres) > 6 else ''
            return f"{len(titres)} sections : {', '.join(titres[:6])}{reste}."
        parties = [f"environ {round(mots / 10) * 10} mots"]
        if puces >= 3:
            parties.append(f"{puces} points")
        if code:
            parties.append(f"{code} bloc{'s' if code > 1 else ''} de code")
        return ', '.join(parties) + '.'

    assert plan('mot ' * 50) == '', 'réponse courte : annoncer serait du bruit'
    long = 'mot ' * 300
    assert plan(long, ['Frais', 'Plafonds', 'Conseil']) == '3 sections : Frais, Plafonds, Conseil.'
    assert 'et 3 autres' in plan(long, [f'T{i}' for i in range(9)])
    assert 'sections' not in plan(long, ['Un seul titre']), 'un titre isolé ne fait pas un plan'
    r = plan(long, puces=7, code=1)
    assert 'environ 300 mots' in r and '7 points' in r and '1 bloc de code' in r
    ok("réponse longue : structure annoncée avant la lecture, silence si courte")


def test_panne_fournisseur_reprise():
    """Une panne de fournisseur affichait son message technique brut, en anglais,
    lu tel quel par la synthèse vocale, sans aucune récupération. On traduit, on
    distingue le récupérable, et on reprend avec un autre fournisseur."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    hub = open(os.path.join(racine, 'core', 'hub.py'), encoding='utf-8').read()

    ns = {'get_api_key': lambda p, k=None: (k or {}).get(p)}
    exec(eng[eng.find('def classer_erreur_fournisseur'):
             eng.find('\ndef _anthropic_billable_input')], ns)
    cl, sec = ns['classer_erreur_fournisseur'], ns['fournisseur_de_secours']

    class R:
        def __init__(s, c, t=''):
            s.status_code, s.text = c, t

    class E(Exception):
        def __init__(s, r):
            s.response = r

    assert cl(E(R(401)), 'Anthropic')['categorie'] == 'clé'
    assert cl(E(R(401)), 'Anthropic')['recuperable'] is False, \
        'une clé refusée ne se règle pas en changeant de fournisseur'
    for exc, cat in ((E(R(400, 'Your credit balance is too low')), 'crédit'),
                     (E(R(429)), 'débit'), (E(R(529, 'Overloaded')), 'surcharge'),
                     (Exception('Connection timed out'), 'délai')):
        d = cl(exc, 'Anthropic')
        assert d['categorie'] == cat and d['recuperable'] is True, cat
    m = cl(E(R(400, 'Your credit balance is too low')), 'Anthropic')['message']
    assert 'crédit' in m and 'balance' not in m, 'message à traduire en français'

    cles = {'anthropic': 'a', 'mistral': 'm'}
    assert sec('anthropic', cles) == 'mistral' and sec('mistral', cles) == 'anthropic'
    assert sec('anthropic', {'anthropic': 'a'}) == '', 'aucun autre fournisseur'

    # La reprise ne doit avoir lieu que si RIEN n'a encore été affiché
    assert 'not full_reply' in hub, 'pas de reprise après un affichage partiel'
    assert 'Je reprends avec' in hub, "le changement doit être annoncé"
    assert "add_diagnostic('fournisseur'" in hub, 'la panne doit être consignée'
    ok("panne de fournisseur : message clair, reprise sur un autre, sans doublon")


def test_historique_purge_des_appels_en_texte():
    """Un appel d'outil écrit en texte est ENREGISTRÉ comme une réponse ordinaire :
    il repart au modèle à chaque tour, qui voit le motif et le reproduit. Le défaut
    s'auto-entretient dans le fil. L'historique doit donc en être purgé."""
    import re as _re
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hub = open(os.path.join(racine, 'core', 'hub.py'), encoding='utf-8').read()
    assert '_strip_appels_texte' in hub
    assert 'content = _strip_appels_texte(content).strip()' in hub, \
        "le nettoyage doit être appliqué à l'historique envoyé au modèle"
    assert 'if not content and not m.get' in hub, \
        'un message réduit à néant doit être écarté'

    ns = {'re': _re}
    exec(hub[hub.find('_RE_APPEL_TEXTE_HIST = re.compile'):
             hub.find('\ndef _document_vraiment_utilise')], ns)
    f = ns['_strip_appels_texte']
    cas = '<function=search_web>\n{"query": "Boursorama Bank GBP frais"}'
    assert f(cas).strip() == '', 'cas vécu : doit disparaître'
    mixte = 'Je cherche.\n<function=search_web>{"query": "x"}</function>\nLa suite.'
    r = f(mixte)
    assert '<function=' not in r and 'Je cherche.' in r and 'La suite.' in r
    for normal in ('La fonction f(x) = 2x.', "Le code <function> n'existe pas."):
        assert f(normal) == normal, normal
    assert f(None) is None and f('') == ''
    ok("historique : appels d'outils en texte purgés, boucle d'imitation brisée")


def test_journal_de_fonctionnement():
    """Les décisions techniques de NIMM (document écarté, appel d'outil rattrapé,
    cache désactivé) n'existaient que dans la console — inaccessible à qui pilote
    NIMM au lecteur d'écran. Elles doivent être consignées et consultables."""
    import json as _json
    from datetime import datetime as _dt
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db = open(os.path.join(racine, 'core', 'database.py'), encoding='utf-8').read()
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()

    # Les points de diagnostic alimentent bien le journal
    assert eng.count('add_diagnostic') >= 2, 'moteur : cache refusé, appel en texte'
    assert '/api/diagnostics' in mn
    assert 'loadDiagnostics' in app and 'diagnostics-clear-btn' in app

    # Comportement du magasin : plafonné, plus récent en tête, jamais bloquant
    store = {'v': '[]'}
    ns = {'json': _json, 'datetime': _dt,
          'get_setting': lambda k, d=None: store['v'],
          'set_setting': lambda k, v: store.__setitem__('v', v)}
    exec(db[db.find('_DIAG_MAX = 80'):db.find('_COANIMM_SCHEDULES_MAX')], ns)
    add, lister = ns['add_diagnostic'], ns['list_diagnostics']
    for n in range(100):
        add('test', f'message {n}')
    j = lister()
    assert len(j) == 80 and j[0]['message'] == 'message 99'
    ns['set_setting'] = lambda k, v: (_ for _ in ()).throw(RuntimeError('disque'))
    add('test', 'malgré la panne')          # ne doit pas lever
    store['v'] = 'pas du json'
    assert lister() == [], 'journal illisible → liste vide'
    ok("journal de fonctionnement : consultable, plafonné, jamais bloquant")


def test_pied_document_honnete():
    """Le pied « Documents consultés » s'ajoutait dès qu'un document était PROPOSÉ
    au modèle, même inutilisé : une ligne annonçant une consultation qui n'avait pas
    eu lieu, sous forme de nom de fichier brut, sans lien ni citation (cas vécu)."""
    import re as _re
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hub = open(os.path.join(racine, 'core', 'hub.py'), encoding='utf-8').read()
    assert '_document_vraiment_utilise' in hub
    assert 'Mention de source omise' in hub, 'une omission doit être tracée'
    assert hub.count('add_diagnostic') >= 3, 'les décisions doivent alimenter le journal'

    # Le nettoyage d'historique doit couvrir l'ANCIEN et le NOUVEAU libellé
    i = hub.find('_DOCS_FOOTER_RE = re.compile')
    ns = {'re': _re}
    exec(hub[i:hub.find('\n\n', i)], ns)
    R = ns['_DOCS_FOOTER_RE']
    for pied in ("Réponse.\n\n— 📄 Documents consultés : Étude.pdf",
                 "Réponse.\n\n— 📄 Source : ta base de connaissances — Guide.pdf"):
        assert R.sub('', pied).strip() == 'Réponse.', pied
    assert R.sub('', 'Texte avec 📄 une émoji.') == 'Texte avec 📄 une émoji.'

    # Le pied ne s'affiche que si la réponse reprend le vocabulaire du document
    j = hub.find('def _document_vraiment_utilise')
    ns2 = {}
    exec(hub[j:hub.find('\ndef _strip_docs_footer')], ns2)
    f = ns2['_document_vraiment_utilise']
    doc = "Les frais de conversion en devise étrangère sont facturés deux pour cent."
    assert f("Les frais de conversion en devise étrangère restent facturés.", doc)
    assert not f("Voici les concerts à Londres en août.", doc), 'cas vécu : pied à omettre'
    assert not f('', doc) and not f('texte', '')
    ok("pied de document : affiché seulement si le document a servi")


def test_appel_outil_ecrit_en_texte():
    """Certains modèles écrivent leurs appels d'outils EN TEXTE
    (« <function=search_web>{…} ») au lieu du champ structuré. Sans traitement,
    l'utilisateur voit ce charabia à la place d'une réponse — cas vécu."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()

    # L'import de `re` doit précéder la compilation du motif, sinon le module
    # entier refuse de s'importer et NIMM ne démarre plus.
    arbre = ast.parse(src)
    ligne_re = next((n.lineno for n in arbre.body if isinstance(n, ast.Import)
                     and any(a.name == 're' for a in n.names)), None)
    ligne_cst = next((n.lineno for n in arbre.body if isinstance(n, ast.Assign)
                      and any(getattr(t, 'id', '') == '_RE_APPEL_TEXTE' for t in n.targets)), None)
    assert ligne_re and ligne_cst and ligne_re < ligne_cst, "import re manquant ou trop tardif"

    import re as _re
    ns = {'re': _re, 'json': __import__('json')}
    exec(src[src.find('_RE_APPEL_TEXTE = re.compile'):src.find('\ndef _anthropic_billable_input')], ns)
    parse, detecte = ns['_parse_appels_texte'], ns['_contient_appel_texte']

    reel = ('<function=search_web>\n{"query": "Boursorama Bank GBP compte devise '
            '2026 frais conversion taux"}')
    assert detecte(reel)
    r = parse(reel)
    assert len(r) == 1 and r[0]['name'] == 'search_web'
    assert r[0]['args']['query'].startswith('Boursorama')
    # deux appels, balise fermante
    r2 = parse('<function=a>{"x":1}</function> bla <function=b>{"y":"z"}</function>')
    assert [x['name'] for x in r2] == ['a', 'b']
    # robustesse : JSON illisible ignoré, texte normal intact
    assert parse('<function=c>{pas du json}') == []
    assert not detecte('Voici la réponse. La fonction f(x) = 2x.')

    # Le repli doit couvrir TOUS les chemins, Anthropic compris (cas vécu).
    chemins = {}
    for n in ast.walk(arbre):
        nom = getattr(n, 'name', '') or ''
        if nom in ('_anthropic_tools_turn', 'call_llm_stream_with_tools'):
            chemins[nom] = ast.get_source_segment(src, n) or ''
    assert len(chemins) == 2
    for nom, seg in chemins.items():
        assert '_contient_appel_texte' in seg, f"{nom} n'intercepte pas l'appel en texte"
        assert '_parse_appels_texte' in seg, f"{nom} ne le convertit pas"
    ok("appel d'outil écrit en texte : reconnu et converti sur tous les chemins")


def test_verification_relance_sur_pause():
    """La recherche web est un outil SERVEUR : le tour peut rendre la main en
    « pause_turn » avant d'avoir rédigé sa conclusion. Sans relance, la
    vérification ne rendait aucun verdict — cas vécu."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    seg = ''
    for n in ast.walk(ast.parse(src)):
        if getattr(n, 'name', '') == 'verify_claims_anthropic':
            seg = ast.get_source_segment(src, n) or ''
    assert seg, 'verify_claims_anthropic introuvable'
    assert 'pause_turn' in seg, 'la pause du tour doit être traitée'
    assert 'for _tour in range' in seg, 'il faut relancer, avec une borne'
    assert "'role': 'assistant', 'content': contenu" in seg, \
        'la relance doit renvoyer ce qui a déjà été produit'
    assert "Aucune affirmation vérifiable" in seg, \
        'un verdict vide doit être expliqué, pas laissé brut'
    assert '[Aucun verdict rendu.]' not in seg, 'message technique remplacé'
    ok("vérification : relance bornée sur pause du tour, verdict vide expliqué")


def test_verification_des_faits():
    """« Vérifier les faits » : repérer une erreur factuelle est coûteux quand on ne
    peut pas survoler un texte. Le verdict doit donc annoncer les ERREURS D'ABORD,
    rester lisible à voix haute (pas de tableau) et exposer ses sources."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()

    i = eng.find('VERIFY_SYSTEM_PROMPT')
    assert i > 0, 'prompt de vérification absent'
    bloc = eng[i:i + 1200]
    assert 'ERRONÉ' in bloc and 'confirmé' in bloc, "l'ordre erreurs → confirmé est requis"
    assert 'sans tableau' in bloc, 'la sortie doit rester lisible à voix haute'
    assert "'web_search_20250305'" in eng, 'la vérification doit chercher sur le web'

    assert '/api/verify' in mn and 'verify_claims_anthropic' in mn
    # DEUX menus construisent les actions d'un message : celui des messages
    # rechargés et celui de la réponse en cours de génération. L'entrée doit être
    # dans les deux, sinon elle disparaît sur les réponses fraîches (cas vécu).
    assert app.count('data-action="verify"') == 6, \
        'entrée + masquage + branchement, dans les DEUX menus (rechargé et streaming)'
    assert app.count('data-action="verify" data-needs-key="anthropic"') == 2, \
        "l'entrée ne doit apparaître que si une clé Anthropic existe"
    assert app.count('_verifierReponse(') >= 2, 'la fonction doit être appelée des deux menus'
    assert 'Sources de la vérification' in app, 'les sources doivent être étiquetées'
    # Rendu LÉGER : le résultat s'insère replié (une ligne), et se retire
    assert '_verifBilanCourt' in app, 'un bilan court doit résumer le verdict'
    assert "createElement('details')" in app, 'le résultat doit être replié par défaut'
    assert 'Retirer la vérification' in app, 'le résultat doit pouvoir être retiré'
    assert "querySelector('.verif-bloc')?.remove()" in app, 'une seule vérification à la fois'
    ok("vérification des faits : erreurs d'abord, résultat replié et retirable")


def test_tous_fournisseurs_diffusent():
    """TOUS les fournisseurs doivent diffuser au fil de l'eau et signaler la
    troncature. Sans streaming, rien ne s'affiche tant que la réponse n'est pas
    entièrement générée : un long silence, sans indice visuel ni sonore.
    Anthropic, Gemini et Ollama avaient ce défaut ; les OpenAI-compat non."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    arbre = ast.parse(eng)

    phases = {}
    for n in ast.walk(arbre):
        nom = getattr(n, 'name', None) or ''
        if nom.endswith('_tools_turn'):
            phases[nom] = ast.get_source_segment(eng, n) or ''
    assert {'_anthropic_tools_turn', '_gemini_tools_turn', '_ollama_tools_turn'} <= set(phases)
    for nom, seg in phases.items():
        assert 'aiter_lines' in seg or 'client.stream' in seg, f"{nom} ne diffuse pas"
        assert "'truncated'" in seg, f"{nom} ne signale pas la troncature"
        assert '_log(' in seg, f"{nom} ne journalise pas les coûts"

    # Le chemin OpenAI-compat (Mistral, DeepSeek, OpenAI, OpenRouter)
    for n in ast.walk(arbre):
        if getattr(n, 'name', None) == 'call_llm_stream_with_tools':
            seg = ast.get_source_segment(eng, n)
            assert 'aiter_lines' in seg and "'stream'" in seg
    ok(f"diffusion en continu + troncature : {len(phases)} chemins + OpenAI-compat")


def test_anthropic_diffuse_en_continu():
    """Le chat Anthropic doit diffuser au fil de l'eau, comme les fournisseurs
    OpenAI-compat. Sans streaming, rien ne s'affiche tant que la réponse n'est pas
    entièrement générée : long silence avant que la voix ne démarre."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    trouve = False
    for n in ast.walk(ast.parse(eng)):
        if getattr(n, 'name', '') != '_anthropic_tools_turn':
            continue
        trouve = True
        seg = ast.get_source_segment(eng, n)
        # stream doit valoir True dans le payload
        stream_ok = False
        for sub in ast.walk(n):
            if isinstance(sub, ast.Dict):
                cles = [k.value for k in sub.keys if isinstance(k, ast.Constant)]
                if 'stream' in cles:
                    stream_ok = ast.literal_eval(sub.values[cles.index('stream')]) is True
        assert stream_ok, "le chat Anthropic doit demander le streaming"
        assert 'aiter_lines' in seg, "la réponse doit être lue au fil de l'eau"
        # Contrat d'événements inchangé pour le hub
        assert "yield {'type': 'tool_calls'" in seg
        assert "yield {'type': 'truncated'}" in seg
        assert '_anthropic_billable_input' in seg, "facturation pondérée conservée"
    assert trouve, "_anthropic_tools_turn introuvable"
    ok("chat Anthropic : diffusion en continu, contrat d'événements préservé")


def test_signal_troncature_bout_en_bout():
    """Le frontend attendait un signal [TRUNCATED] pour afficher son bouton
    « Continuer », mais AUCUN code serveur ne l'émettait : le bouton n'apparaissait
    jamais, pour aucun fournisseur, et les réponses étaient coupées en silence."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    hub = open(os.path.join(racine, 'core', 'hub.py'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()

    # Émission : Anthropic ET les fournisseurs OpenAI-compat (Mistral, DeepSeek…)
    # Anthropic, OpenAI-compat, et la reprise (qui peut être tronquée à son tour)
    assert eng.count("yield {'__truncated__': True}") == 3
    assert "yield {'type': 'truncated'}" in eng, "phase 1 avec outils"
    # _finish_reason doit vivre dans la fonction qui l'utilise (sinon NameError)
    for node in ast.walk(ast.parse(eng)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == '_call_openai_compat_stream':
            seg = ast.get_source_segment(eng, node)
            assert '_finish_reason = None' in seg and '_finish_reason = _fr' in seg

    # Relais et réception
    assert hub.count('data: [TRUNCATED]') == 3
    assert "elif event['type'] == 'truncated':" in hub
    assert app.count("'[TRUNCATED]'") == 2 and 'addContinueButton' in app
    assert 'Un bouton Continuer est disponible' in app, "la troncature doit être annoncée"
    ok("troncature : signal émis, relayé, reçu — bouton « Continuer » et annonce")


def test_facturation_cache_partout():
    """Tous les chemins Anthropic doivent utiliser la facturation pondérée.
    _anthropic_tools_turn (phase 1 du chat) l'avait été oublié : avec le cache,
    input_tokens ne compte que le non-caché → coûts sous-évalués."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    assert "usage.get('input_tokens', 0)" not in src, \
        "un chemin Anthropic journalise encore les tokens d'entrée bruts"
    assert src.count('_anthropic_billable_input(') >= 4
    ok("facturation pondérée sur TOUS les chemins Anthropic")


def test_repli_cache_refuse():
    """cache_control part sur TOUS les appels Anthropic, chat en streaming compris.
    Si l'API le refusait, plus aucune conversation ne passerait : on vérifie que le
    refus désactive le cache et relance, et qu'aucune AUTRE erreur ne le déclenche."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    bloc = src[src.find('def _anthropic_desactiver_cache'):src.find('\ndef _anthropic_billable_input')]

    faux_db = types.ModuleType('core.database')
    reglages = {}
    faux_db.set_setting = lambda k, v: reglages.__setitem__(k, v)
    sys.modules['core.database'] = faux_db

    class R:
        def __init__(self, code, texte):
            self.status_code, self.text = code, texte

    class HSE(Exception):
        def __init__(self, resp):
            self.response = resp
    faux_httpx = types.ModuleType('httpx')
    faux_httpx.HTTPStatusError = HSE
    sys.modules['httpx'] = faux_httpx

    import re as _re          # la tranche exécutée contient aussi des motifs compilés
    ns = {'re': _re, 'json': __import__('json')}
    exec(bloc, ns)
    f = ns['_anthropic_cache_fallback']
    assert f(HSE(R(400, 'Unexpected field: cache_control'))) is True
    assert reglages.get('anthropic_cache_active') == '0'
    reglages.clear()
    assert f(HSE(R(400, 'credit balance is too low'))) is False
    assert f(HSE(R(429, 'rate limit'))) is False
    assert f(ValueError('réseau')) is False
    assert not reglages, "seul un refus du champ de cache doit le désactiver"
    del sys.modules['core.database'], sys.modules['httpx']
    ok("cache refusé : repli automatique, sans masquer les autres erreurs")


def test_mcp_inerte_sans_serveur():
    """Sans serveur MCP configuré, rien ne doit changer dans l'appel : ni champ
    mcp_servers, ni en-tête bêta. Et le jeton ne doit jamais sortir en lecture."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    assert "if _mcp:\n        payload['mcp_servers'] = _mcp" in eng
    assert "**({'anthropic-beta': 'mcp-client-2025-11-20'} if _mcp else {})" in eng

    db = open(os.path.join(racine, 'core', 'database.py'), encoding='utf-8').read()
    i = db.find('def list_mcp_servers')
    corps = db[i:db.find('\ndef ', i + 10)]
    assert "k != 'jeton_enc'" in corps, "le jeton chiffré doit être retiré de la lecture"
    assert 'a_jeton' in corps, "un booléen doit remplacer le jeton"

    m = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    assert 'startswith("https://")' in m, "adresse MCP : https exigé"
    ok("MCP : inerte sans serveur, jeton jamais exposé, https exigé")


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


def test_description_audio():
    """Un fichier son ne se réduit pas à ses paroles : Whisper transcrit déjà en
    local, mais il ne dit ni qui parle, ni sur quel ton, ni ce qu'on entend
    derrière. Gemini sait le faire — et c'est précisément l'information qu'une
    transcription fait perdre."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    coa = open(os.path.join(racine, 'modules', 'coanimm.py'), encoding='utf-8').read()
    saf = open(os.path.join(racine, 'modules', 'coanimm_safety.py'), encoding='utf-8').read()

    seg = ''
    for n in ast.walk(ast.parse(eng)):
        if getattr(n, 'name', '') == 'describe_audio_gemini':
            seg = ast.get_source_segment(eng, n) or ''
    assert seg, 'describe_audio_gemini introuvable'
    assert "startswith(('http://', 'https://'))" in seg, 'un lien doit être accepté tel quel'
    assert "'file_data'" in seg and "'inline_data'" in seg, 'lien ET fichier local'
    assert '18 * 1024 * 1024' in seg, 'garde de taille pour l’envoi direct'
    assert 'MAX_TOKENS' in seg, 'une description tronquée doit être signalée'
    assert 'TRANSCRIPTION' in seg and 'OBSERVATIONS' in seg, 'séparer les deux registres'
    assert 'minute:seconde' in seg, 'des repères de temps pour se situer'
    assert "N'invente rien" in seg, 'consigne factuelle'
    assert '_gemini_tokens_sortie' in seg, 'la facturation doit être comptée'

    assert '/api/coanimm/describe_audio' in mn
    assert '"describe_audio" in _db.list_coanimm_disabled_tools()' in mn, 'désactivable'
    assert coa.count('nimm_describe_audio') >= 3, 'helper + prologue + doc'
    assert "'nimm_describe_audio': 'recherche'" in saf, "l'audio part au cloud"
    ok("description sonore : au-delà de la transcription, désactivable, comptée")


def test_documents_epingles():
    """Cache EXPLICITE de Gemini : on paie la lecture d'une longue étude une seule
    fois, puis chaque question ne coûte plus qu'une fraction. Le piège est le
    plancher de jetons imposé par l'API : sans contrôle en amont, Fernando
    recevrait une erreur HTTP brute en anglais après une minute d'attente."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    dbs = open(os.path.join(racine, 'core', 'database.py'), encoding='utf-8').read()
    coa = open(os.path.join(racine, 'modules', 'coanimm.py'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()

    noms = {}
    for n in ast.walk(ast.parse(eng)):
        if getattr(n, 'name', '') in ('create_cache_gemini', 'ask_cache_gemini',
                                      'list_caches_gemini', 'delete_cache_gemini'):
            noms[n.name] = ast.get_source_segment(eng, n) or ''
    assert len(noms) == 4, 'les quatre opérations du cycle de vie sont requises'

    crea = noms['create_cache_gemini']
    assert '_GEMINI_CACHE_MIN_TOKENS' in crea, 'plancher de jetons vérifié AVANT appel'
    assert 'count_tokens' in crea, 'on compte avant de payer'
    assert 'cachedContents' in crea and "'ttl'" in crea, 'endpoint et durée de vie'
    assert 'displayName' in crea, 'un titre lisible pour retrouver le document'
    interro = noms['ask_cache_gemini']
    assert "'cachedContent'" in interro, 'la question doit référencer le cache'
    assert '_gemini_tokens_entree' in interro, 'la remise de cache doit être comptée'

    # Message d'erreur traduit plutôt qu'un code HTTP nu
    assert '_gemini_message_erreur' in eng
    assert 'expiré' in eng, 'un cache disparu doit être expliqué, pas subi'

    # Magasin local : métadonnées seulement, jamais le contenu confidentiel
    for f in ('list_gemini_pins', 'add_gemini_pin', 'remove_gemini_pin', 'find_gemini_pin'):
        assert 'def %s(' % f in dbs, f
    assert 'MÉTADONNÉES' in dbs, 'le contenu du document ne doit pas être recopié en local'

    # Routes + croisement avec la réalité distante (pas de fantôme expiré)
    assert '/api/gemini/pins' in mn and '/api/gemini/pins/ask' in mn
    assert 'list_caches_gemini' in mn and '_save_gemini_pins(vivants)' in mn, \
        'les caches expirés doivent disparaître de la liste locale'

    # Outils CoaNIMM : une seule case à cocher pour toute la famille
    for f in ('nimm_pin_document', 'nimm_ask_pinned', 'nimm_list_pinned', 'nimm_unpin_document'):
        assert f in coa, f
    assert '"pin_document" not in _disabled' in coa, 'famille pilotée par une seule entrée'
    assert '"tool": "pin_document"' in mn, 'présent au catalogue'

    # Interface : réservée à Gemini, et copiable
    assert 'id="gemini-pins-section" data-needs-key="gemini"' in html
    assert 'aria-live="polite"' in html
    assert "navigator.clipboard.writeText" in app
    assert '_pinRestant' in app, 'une durée relative se lit mieux qu’un horodatage ISO'
    ok("documents épinglés : plancher vérifié, expirés purgés, une seule case, panneau Gemini")


def test_lot_gemini():
    """Le panneau de lots existait pour Mistral puis Anthropic. Gemini complète le
    trio. Deux pièges propres à Gemini : l'identifiant contient une barre oblique
    (batches/123), et les résultats se rangent tantôt sous response, tantôt sous
    dest — accepter une seule forme, c'est risquer une page blanche après une
    heure d'attente."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()

    assert ':batchGenerateContent' in mn, 'endpoint de soumission'
    assert 'input_config' in mn and '"requests": {"requests"' in mn, 'requêtes en ligne'
    assert '{batch_id:path}' in mn, "l'identifiant Gemini contient une barre oblique"
    assert mn.count('{batch_id:path}') >= 3, 'statut, résultats et annulation'
    assert 'JOB_STATE_SUCCEEDED' in mn and '_GEMINI_ETATS' in mn, 'états traduits en français'

    # Souplesse sur la forme des résultats
    seg = ''
    for n in ast.walk(ast.parse(mn)):
        if getattr(n, 'name', '') == '_gemini_batch_extraire':
            seg = ast.get_source_segment(mn, n) or ''
    assert seg, '_gemini_batch_extraire introuvable'
    assert '"response"' in seg and '"dest"' in seg, 'les deux emplacements possibles'
    assert 'isinstance(brut, dict)' in seg, 'liste parfois encapsulée une fois de plus'
    assert 'sorties.sort(key=_rang)' in seg, "l'ordre de soumission doit être restitué"

    # L'ordre est vraiment restitué, y compris au-delà de dix requêtes
    mod = {}
    exec(compile(ast.Module(body=[n for n in ast.parse(mn).body
                                  if getattr(n, 'name', '') == '_gemini_batch_extraire'],
                            type_ignores=[]), '<extrait>', 'exec'), mod)
    faux = {'response': {'inlinedResponses': [
        {'metadata': {'key': 'req_%d' % i},
         'response': {'candidates': [{'content': {'parts': [{'text': 'r%d' % i}]}}]}}
        for i in (11, 2, 0, 10, 1)]}}
    res = mod['_gemini_batch_extraire'](faux)
    assert [r['text'] for r in res] == ['r0', 'r1', 'r2', 'r10', 'r11'], \
        'tri numérique, pas alphabétique'
    # Forme « dest », et une erreur par requête
    autre = {'dest': {'inlinedResponses': [
        {'metadata': {'key': 'req_0'}, 'error': {'message': 'quota'}}]}}
    r2 = mod['_gemini_batch_extraire'](autre)
    assert r2 and r2[0]['error'] == 'quota' and r2[0]['text'] == ''

    assert 'value="gemini" data-needs-key="gemini"' in html, 'option grisée sans clé Gemini'
    assert '_BATCH_GEMINI_REPLI' in app, 'liste de repli si Gemini ne répond pas'
    assert "'/api/models/' + p" in app, 'modèles interrogés dynamiquement'
    assert 'd.libelle' in app, "l'état doit être annoncé en français"
    ok("lot Gemini : identifiant à barre oblique, résultats réordonnés, deux formes acceptées")


def test_document_de_la_conversation():
    """Attacher un document à un fil, plutôt que de laisser le RAG deviner.

    Trois exigences : (1) le document attaché DOIT désactiver la base de
    connaissances pour ce fil — sinon on empile ce que l'utilisateur a choisi
    et ce que NIMM a deviné, exactement le bruit qu'on venait de corriger ;
    (2) il doit se placer dans la partie STABLE du prompt, seule position où
    les caches de contexte servent à quelque chose ; (3) le régime de
    facturation doit être annoncé POUR DE VRAI selon le fournisseur — NIMM en
    sert sept, et trois seulement mettent les préfixes en cache.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hub = open(os.path.join(racine, 'core', 'hub.py'), encoding='utf-8').read()
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    dbs = open(os.path.join(racine, 'core', 'database.py'), encoding='utf-8').read()
    coa = open(os.path.join(racine, 'modules', 'coanimm.py'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    arbre = ast.parse(hub)

    # (1) le document attaché supplante la base de connaissances, DANS LES DEUX CHEMINS
    assert hub.count('_document_du_fil(thread_id)') == 2, \
        'le chemin avec outils ET le chemin en streaming'
    assert hub.count("doc_context, _doc_titles = '', []") == 2, \
        'le RAG doit se taire quand l’utilisateur a désigné son document'
    assert hub.count('doc_fil=_doc_fil') == 2

    # (2) position stable : avant la mémoire et les messages récents
    corps = ''
    for n in ast.walk(arbre):
        if getattr(n, 'name', '') == 'build_system_prompt':
            corps = ast.get_source_segment(hub, n) or ''
    assert corps, 'build_system_prompt introuvable'
    i_doc = corps.find('Document de cette conversation')
    i_biblio = corps.find('Conversations passées sur ce sujet')
    i_kb = corps.find('base de connaissances')
    assert 0 < i_doc < i_biblio and i_doc < i_kb, \
        'le document du fil doit précéder bibliothèque et base de connaissances'
    assert 'dis-le clairement' in corps, "ne pas combler les trous avec du général"

    # (3) régime de facturation réellement différencié
    reg = {}
    exec(compile(ast.Module(body=[n for n in arbre.body
                                  if getattr(n, 'name', '') == 'regime_de_cache'
                                  or (isinstance(n, ast.Assign)
                                      and getattr(n.targets[0], 'id', '').startswith('_REGIME'))],
                            type_ignores=[]), '<extrait>', 'exec'), reg)
    f = reg['regime_de_cache']
    caches = {p: f(p) for p in ('anthropic', 'gemini', 'deepseek')}
    assert len(set(caches.values())) == 3, 'trois fournisseurs, trois messages distincts'
    for p, m in caches.items():
        assert '10 %' in m, 'la remise réelle doit être chiffrée pour ' + p
    for p in ('openai', 'mistral', 'ollama', 'openrouter', '', None):
        assert 'ne propose pas de cache' in f(p), \
            'ne pas promettre une économie inexistante (' + str(p) + ')'
    assert f('ANTHROPIC') == f('anthropic'), 'insensible à la casse'

    # Magasin local : effacement réel au détachement
    for fn in ('get_thread_document', 'set_thread_document', 'clear_thread_document'):
        assert 'def %s(' % fn in dbs, fn
    assert '_THREAD_DOC_MAX_CAR' in dbs and '_THREAD_DOC_MAX_FILS' in dbs, 'bornes'
    assert 'confidentiel' in dbs, "un document confidentiel doit pouvoir disparaître"

    # Routes et outils
    assert mn.count('/api/threads/{thread_id}/document') == 3, 'lire, attacher, détacher'
    assert 'regime_de_cache' in mn, "le régime est annoncé à l’utilisateur"
    assert 'nimm_attach_document' in coa and 'nimm_detach_document' in coa
    assert '"tool": "thread_document"' in mn, 'présent au catalogue'

    # Interface : disponible quel que soit le fournisseur, donc SANS data-needs-key
    i_sec = html.find('id="thread-doc-section"')
    assert i_sec > 0
    assert 'data-needs-key' not in html[i_sec:i_sec + 120], \
        'attacher un document doit marcher avec tous les fournisseurs'
    assert 'aria-live="polite"' in html[i_sec:i_sec + 2500]
    assert '_threadDocRefresh' in app
    ok("document de la conversation : le RAG se tait, position stable, coût annoncé sans mentir")


def test_magasin_documents_de_fil():
    """Test FONCTIONNEL du magasin — c'est lui qui a trouvé le vrai défaut.

    Le plafond de fils s'appuyait sur l'horodatage, écrit à la seconde près.
    Treize attaches dans la même seconde portent la même date ; un tri stable
    conservait donc les PLUS ANCIENNES et jetait celle qu'on venait de faire.
    L'analyse statique n'aurait jamais vu ça : seul l'exécuter le montre.
    L'ordre d'insertion fait désormais foi.
    """
    import json as _json
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    import core.database as d

    store, vrai_get, vrai_set = {}, d.get_setting, d.set_setting
    d.get_setting = lambda k, dflt=None: store.get(k, dflt)
    d.set_setting = lambda k, v: store.__setitem__(k, v)
    try:
        assert d.get_thread_document('t1') == {}
        assert d.get_thread_document('') == {}, 'fil vide toléré'

        # Troncature signalée, longueur réelle conservée
        gros = 'B' * (d._THREAD_DOC_MAX_CAR + 500)
        f = d.set_thread_document('t2', 'Gros', gros)
        assert f['tronque'] and f['nb_car'] == len(gros)
        assert len(d.get_thread_document('t2')['texte']) == d._THREAD_DOC_MAX_CAR

        # Plafond : les plus RÉCENTS survivent, même écrits dans la même seconde
        for i in range(d._THREAD_DOC_MAX_FILS + 3):
            d.set_thread_document('f%02d' % i, 't%d' % i, 'x' * 5)
        reste = _json.loads(store['thread_documents'])
        assert len(reste) == d._THREAD_DOC_MAX_FILS
        assert 'f12' in reste and 'f11' in reste, 'le plus récent ne doit jamais sauter'
        assert 'f00' not in reste, 'les plus anciens sautent'

        # Réattacher un fil ancien le rafraîchit
        d.set_thread_document('f03', 'maj', 'y' * 5)
        assert list(_json.loads(store['thread_documents']).keys())[-1] == 'f03'

        # Détacher efface RÉELLEMENT le texte (contrainte de confidentialité)
        d.set_thread_document('secret', 'Confidentiel', 'MOTDEPASSEUNIQUE')
        assert 'MOTDEPASSEUNIQUE' in store['thread_documents']
        assert d.clear_thread_document('secret') is True
        assert 'MOTDEPASSEUNIQUE' not in store['thread_documents'], \
            'un document confidentiel doit disparaître pour de bon'
        assert d.clear_thread_document('secret') is False
    finally:
        d.get_setting, d.set_setting = vrai_get, vrai_set
    ok("magasin des documents de fil : troncature, plafond par récence réelle, effacement")


def test_choix_dans_la_base():
    """Choisir un document dans une liste plutôt que taper son chemin.

    Saisir « C:\\Users\\...\\etude.pdf » au clavier braille est long et fautif ;
    la base de connaissances contient déjà les documents versés, autant les
    proposer. Piège à éviter : elle contient AUSSI des centaines de pages mises
    en cache par la recherche web — les inclure noierait les vrais documents.
    """
    import sqlite3 as _sq
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    dbs = open(os.path.join(racine, 'core', 'database.py'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    sys.path.insert(0, racine)
    import core.database as d

    # Base sur fichier temporaire (et non ':memory:') : les fonctions testées
    # ouvrent et FERMENT leur connexion, ce qu'une base en mémoire ne survit pas.
    import tempfile as _tf
    _fd, _chemin = _tf.mkstemp(suffix='.db')
    os.close(_fd)
    conn = _sq.connect(_chemin)
    conn.row_factory = _sq.Row
    conn.execute("""CREATE TABLE web_reference (id INTEGER PRIMARY KEY, query TEXT,
                    query_norm TEXT, content TEXT, embedding TEXT, captured_at TEXT,
                    expiration TEXT, source TEXT)""")
    lignes = [
        ('Étude accessibilité', 'A' * 4000, '2026-07-01T10:00:00', None, 'fichier:etude.pdf'),
        ('Page web captée',     'B' * 900,  '2026-07-02T10:00:00', None, 'recherche'),
        ('Notes réunion',       'C' * 200,  '2026-07-03T10:00:00', None, 'texte'),
        ('Document périmé',     'D' * 100,  '2026-07-04T10:00:00', '2020-01-01T00:00:00', 'texte'),
        ('Étude accessibilité', 'A' * 4000, '2026-06-01T10:00:00', None, 'fichier:etude.pdf'),
    ]
    for q, c, cap, exp, src in lignes:
        conn.execute("INSERT INTO web_reference (query, content, captured_at, expiration, source)"
                     " VALUES (?,?,?,?,?)", (q, c, cap, exp, src))
    conn.commit()

    conn.close()

    def _ouvrir():
        c = _sq.connect(_chemin)
        c.row_factory = _sq.Row
        return c

    vrai_conn, vrai_ens = d.get_conn, d._ensure_web_reference_table
    d.get_conn = _ouvrir
    d._ensure_web_reference_table = lambda c: None
    try:
        docs = d.list_documents_base()
        titres = [x['titre'] for x in docs]
        assert 'Page web captée' not in titres, "le cache de recherche web n'est pas un document versé"
        assert 'Document périmé' not in titres, 'une entrée expirée ne doit pas être proposée'
        assert titres.count('Étude accessibilité') == 1, 'un document réingéré ne doit pas doubler'
        assert titres == ['Notes réunion', 'Étude accessibilité'], 'plus récent en tête : ' + str(titres)
        assert docs[1]['nb_car'] == 4000, 'la taille sert à annoncer le coût'

        # Récupération par identifiant, et refus des identifiants morts
        ident = docs[1]['id']
        assert d.get_document_base(ident)['texte'].startswith('AAAA')
        assert d.get_document_base(9999) == {}
        assert d.get_document_base(None) == {} and d.get_document_base('abc') == {}
    finally:
        d.get_conn, d._ensure_web_reference_table = vrai_conn, vrai_ens
        try:
            os.unlink(_chemin)
        except OSError:
            pass

    assert '/api/documents/base' in mn
    assert 'ref_id: Optional[int]' in mn and 'get_document_base(req.ref_id)' in mn
    assert "n'est plus dans la base" in mn, 'un document disparu doit être expliqué'
    assert 'id="thread-doc-base-select"' in html and '<label for="thread-doc-base-select"' in html
    assert '_tdRemplirBase' in app and 'ref_id: parseInt' in app
    assert "Choisis un document dans la liste, ou indique un chemin" in app, \
        'les deux voies restent possibles'
    ok("base de connaissances : documents versés proposés au choix, cache web écarté")


def test_reordonnancement():
    """Réordonnanceur : le vrai correctif du document hors sujet.

    L'ancrage lexical exigeait un mot commun — c'est un garde-fou, pas une
    mesure de pertinence. Un réordonnanceur lit la question ET le passage
    ensemble. Trois exigences non négociables, parce que ce code tourne sur le
    chemin chaud de la conversation : inerte sans configuration, silencieux en
    cas de panne, et jamais de moteur lent choisi tout seul.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    hub = open(os.path.join(racine, 'core', 'hub.py'), encoding='utf-8').read()
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    import modules.reranker as R

    cfg = {}
    vrai = R._reglage
    R._reglage = lambda n, d='': cfg.get(n, d)
    try:
        pas = [{'passage': 'texte %d' % i, 'titre': 'T%d' % i} for i in range(4)]

        # (1) INERTE sans configuration : mêmes passages, dans le même ordre
        out, m, note = R.reordonner('question posée', pas)
        assert out == pas and m == '' and 'Aucun réordonnanceur configuré' in note

        # Le réglage explicite prime, et un refus est EXPLIQUÉ
        cfg['rag_rerank_mode'] = 'off'
        assert R.moteur_disponible()[0] == '' and 'désactivé' in R.moteur_disponible()[1]
        cfg['rag_rerank_mode'] = 'voyage'
        mo, no = R.moteur_disponible({'cohere': 'k'})
        assert mo == '' and 'aucune clé' in no, 'pas de repli silencieux sur un autre moteur'

        # Le local prime sur le cloud en mode auto : rien ne sort de la machine
        cfg.clear()
        assert R.moteur_disponible({'cohere': 'k'})[0] == 'cohere'
        cfg['rag_rerank_url'] = 'http://localhost:8081'
        assert R.moteur_disponible({'cohere': 'k'})[0] == 'local'

        # (2) PANNE du moteur → ordre d'origine conservé, aucune exception
        R._rerank_local = lambda q, t: None
        out, m, note = R.reordonner('question', pas)
        assert out == pas and m == '' and "n'a pas répondu" in note

        # (3) Tri réel + seuil : ce qui est sous le seuil n'est pas servi
        cfg['rag_rerank_seuil'] = '0.5'
        R._rerank_local = lambda q, t: [(0, 0.1), (1, 0.95), (2, 0.60), (3, 0.2)]
        out, m, note = R.reordonner('question', pas, top_n=3)
        assert m == 'local'
        assert [p['titre'] for p in out] == ['T1', 'T2'], [p['titre'] for p in out]
        assert out[0]['score_rerank'] == 0.95
        assert '2 écarté(s)' in note, note

        # Aucun passage pertinent → on ne sert RIEN, plutôt que le moins mauvais
        R._rerank_local = lambda q, t: [(i, 0.05) for i in range(4)]
        out, m, note = R.reordonner('question', pas)
        assert out == [] and m == 'local' and 'aucun des' in note.lower()

        # top_n respecté
        cfg['rag_rerank_seuil'] = '0.0'
        R._rerank_local = lambda q, t: [(i, 0.9 - i / 10) for i in range(4)]
        assert len(R.reordonner('q', pas, top_n=2)[0]) == 2

        # Un indice hors bornes ne fait pas planter
        R._rerank_local = lambda q, t: [(99, 0.9), (0, 0.8)]
        out, m, _ = R.reordonner('q', pas)
        assert [p['titre'] for p in out] == ['T0']
    finally:
        R._reglage = vrai
        import importlib
        importlib.reload(R)

    # (4) Le moteur « llm » n'est JAMAIS choisi tout seul : il ajoute une attente
    seg = ''
    for n in ast.walk(ast.parse(open(os.path.join(racine, 'modules', 'reranker.py'),
                                     encoding='utf-8').read())):
        if getattr(n, 'name', '') == 'moteur_disponible':
            seg = ast.get_source_segment(open(os.path.join(racine, 'modules', 'reranker.py'),
                                              encoding='utf-8').read(), n) or ''
    assert seg and "mode == 'llm'" in seg
    apres_auto = seg[seg.find('mode auto'):]
    assert "'llm'" not in apres_auto, "le mode automatique ne doit jamais retenir « llm »"

    # (5) Câblage hub : filet élargi SEULEMENT si un moteur peut trier derrière
    assert 'k=10 if _moteur else 3' in hub, 'sinon on ajoute du hors-sujet sans trieur'
    # Les deux chemins de conversation appellent la base de connaissances.
    # On compte l'APPEL, pas sa forme : depuis qu'il passe par un fil
    # d'exécution (il bloquait la boucle), il s'écrit sur deux lignes.
    assert len(re.findall(r'_match_documents,?\s*\n?\s*user_message', hub)) == 2, \
        'les deux chemins de conversation'
    assert 'add_diagnostic' in hub and '_resume' in hub, 'traçable au journal'
    assert 'passages = passages[:3]' in hub, 'moteur muet → on revient à l’ancien filet'

    # (6) Réglages : l'effet RÉEL est renvoyé, pas un simple « enregistré »
    assert '/api/settings/rerank' in mn and 'moteur_effectif' in mn
    assert 'id="rag-rerank-mode"' in html and 'id="rag-rerank-seuil"' in html
    assert 'data-needs-key="cohere"' in html, 'moteur grisé sans sa clé'
    assert 'aria-live="polite"' in html
    assert "'Enregistré. ' + (d.explication" in app, "annoncer l'effet réel"
    ok("réordonnancement : inerte sans réglage, muet en panne, seuil respecté, jamais lent d’office")


def test_veille():
    """Veille : Exa cherche par le SENS, et NIMM relève tout seul.

    NIMM savait déjà planifier et déjà ingérer ; la veille relie les deux. Trois
    exigences : une échéance calculable SANS horloge ni réseau, un déjà-vu qui
    ne resserve jamais deux fois le même article, et une panne qui ne remonte
    jamais en exception — un relevé raté ne doit pas arrêter NIMM.
    """
    from datetime import datetime as _dt, timedelta as _td
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    coa = open(os.path.join(racine, 'modules', 'coanimm.py'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    import modules.veille as V

    # (1) Échéance : fonction pure, testable sans horloge
    maintenant = _dt(2026, 7, 27, 9, 0, 0)
    assert V.veille_due({'periode': 'hebdomadaire', 'dernier_run': ''}, maintenant), \
        'jamais relevé → à relever tout de suite'
    recent = (maintenant - _td(days=2)).isoformat()
    assert not V.veille_due({'periode': 'hebdomadaire', 'dernier_run': recent}, maintenant)
    assert V.veille_due({'periode': 'quotidienne', 'dernier_run': recent}, maintenant)
    vieux = (maintenant - _td(days=8)).isoformat()
    assert V.veille_due({'periode': 'hebdomadaire', 'dernier_run': vieux}, maintenant)
    assert not V.veille_due({'actif': False, 'periode': 'quotidienne',
                             'dernier_run': vieux}, maintenant), 'un sujet éteint dort'
    assert V.veille_due({'periode': 'hebdomadaire', 'dernier_run': 'n’importe quoi'},
                        maintenant), 'date illisible → relever plutôt que bloquer'
    futur = (maintenant + _td(days=3)).isoformat()
    assert V.veille_due({'periode': 'hebdomadaire', 'dernier_run': futur}, maintenant), \
        'horloge reculée : ne pas rester coincé des jours'

    # (2) Déjà-vu et ingestion — magasin et réseau simulés
    store, vlire, vecrire = {}, V._lire, V._ecrire
    V._lire = lambda c, d: json.loads(store.get(c, d))
    V._ecrire = lambda c, v: store.__setitem__(c, json.dumps(v))
    vsearch = V.exa_search
    lot1 = [{'titre': 'A', 'url': 'http://a', 'date': '', 'auteur': '', 'extrait': 'xa', 'score': 1},
            {'titre': 'B', 'url': 'http://b', 'date': '', 'auteur': '', 'extrait': 'xb', 'score': 1}]
    try:
        sujet = {'id': 's1', 'libelle': 'Accessibilité', 'requete': 'q',
                 'periode': 'hebdomadaire', 'nb': 8}
        V.exa_search = lambda *a, **k: (lot1, '')
        neufs, msg = V.relever_sujet(sujet, ingerer=False)
        assert len(neufs) == 2 and '2 nouveauté' in msg, msg

        # Deuxième passage : rien de neuf, et on le DIT
        neufs, msg = V.relever_sujet(sujet, ingerer=False)
        assert neufs == [] and 'rien de nouveau' in msg, msg

        # Un seul article inédit ressort
        lot2 = lot1 + [{'titre': 'C', 'url': 'http://c', 'date': '', 'auteur': '',
                        'extrait': 'xc', 'score': 1}]
        V.exa_search = lambda *a, **k: (lot2, '')
        neufs, msg = V.relever_sujet(sujet, ingerer=False)
        assert [n['url'] for n in neufs] == ['http://c'], neufs

        # (3) Panne : message en français, aucune exception
        V.exa_search = lambda *a, **k: ([], 'Exa refuse la clé d’API.')
        neufs, msg = V.relever_sujet(sujet, ingerer=False)
        assert neufs == [] and 'refuse la clé' in msg

        # Une adresse de référence prend le pas sur la requête
        appels = []
        V.exa_similar = lambda url, *a, **k: (appels.append(url), ([], ''))[1]
        V.relever_sujet({'id': 's2', 'libelle': 'L', 'requete': 'q',
                         'url_reference': 'http://ref', 'periode': 'mensuelle'},
                        ingerer=False)
        assert appels == ['http://ref'], 'la page de référence doit primer'
    finally:
        V._lire, V._ecrire, V.exa_search = vlire, vecrire, vsearch
        import importlib
        importlib.reload(V)

    # (4) Lecture souple des réponses d'Exa
    assert V._lire_resultats({'results': [{'title': 'T', 'url': 'http://u'}]})[0]['titre'] == 'T'
    assert V._lire_resultats([{'id': 'http://u', 'title': 'T'}])[0]['url'] == 'http://u'
    assert V._lire_resultats({'results': [{'title': 'sans url'}]}) == [], 'sans adresse, inutilisable'
    assert V._lire_resultats('bruit') == []

    # (5) Le relevé est BLOQUANT : il doit partir dans un fil séparé
    assert '_veille_worker' in mn and 'run_in_executor' in mn, \
        'sinon toute la conversation attendrait le réseau'
    assert 'await _aio.sleep(120)' in mn, 'laisser NIMM démarrer avant d’appeler l’extérieur'
    assert '/api/veille/sujets' in mn and '/api/exa/search' in mn
    assert 'nimm_veille' in coa and 'nimm_suivre_sujet' in coa
    assert 'id="veille-section" data-needs-key="exa"' in html, 'masqué sans clé Exa'
    assert 'aria-live="polite"' in html and '_veilleCharger' in app
    ok("veille : échéance pure, déjà-vu respecté, panne muette, relevé hors du chemin chaud")


def test_catalogue_services():
    """La liste des services était écrite EN DUR à trois endroits du frontend.

    Conséquence concrète : en branchant Exa, Cohere, Voyage et Jina, leurs clés
    n'avaient AUCUN champ où être saisies — le code existait, la fonction était
    inatteignable. Un catalogue serveur unique règle le problème et interdit
    qu'il revienne.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    import core.services as SV

    ids = SV.ids()
    assert len(ids) == len(set(ids)), 'identifiants uniques'
    # Les services branchés récemment doivent être saisissables
    for attendu in ('exa', 'cohere', 'voyage', 'jina'):
        assert attendu in ids, attendu + " n'a nulle part où recevoir sa clé"
    # Et les anciens ne doivent pas avoir disparu au passage
    for ancien in ('anthropic', 'mistral', 'gemini', 'openai', 'openrouter',
                   'deepseek', 'brave', 'tavily', 'stability_ai'):
        assert ancien in ids, ancien + ' a disparu du catalogue'

    groupes = SV.par_famille({'exa': 'kkk', 'anthropic': '   '})
    assert sum(len(g['services']) for g in groupes) == len(ids), 'aucun service perdu'
    plat = {x['id']: x for g in groupes for x in g['services']}
    assert plat['exa']['configure'] is True
    assert plat['anthropic']['configure'] is False, 'une clé de blancs ne compte pas'
    assert all(s.get('role') for s in SV.SERVICES), 'chaque service dit à quoi il sert'
    # Le catalogue ne doit JAMAIS laisser fuiter une clé vers le frontend
    assert 'kkk' not in json.dumps(groupes, ensure_ascii=False), \
        'le formulaire n’a pas besoin des secrets, seulement de l’état'
    assert SV.html_id('stability_ai') == 'stability-ai', 'convention d’identifiant HTML'

    # Une famille mal orthographiée ne doit pas faire disparaître un service
    faux = dict(SV.SERVICES[0]); faux['id'] = 'zzz'; faux['famille'] = 'inconnue'
    SV.SERVICES.append(faux); SV._PAR_ID['zzz'] = faux
    try:
        g2 = SV.par_famille({})
        assert 'zzz' in {x['id'] for gr in g2 for x in gr['services']}
    finally:
        SV.SERVICES.pop(); SV._PAR_ID.pop('zzz', None)

    assert '/api/settings/services' in mn
    assert 'id="api-keys-auto"' in html, 'point d’accroche du formulaire engendré'
    assert 'api-key-anthropic' not in html, 'plus aucune saisie en dur'
    assert app.count("_svcIds()") >= 3, 'les trois listes en dur sont remplacées'
    assert "'anthropic', 'deepseek'" in app, 'un repli subsiste si la route échoue'
    assert 'aria-describedby' in app, 'le rôle du service est lu au focus'
    assert '_svcEchappe' in app, 'le catalogue est injecté en HTML : il faut échapper'
    ok("catalogue des services : source unique, clés saisissables, secrets non exposés")


def test_exa_avance():
    """Exa au-delà de la recherche simple : filtrer, résumer, lire proprement."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    coa = open(os.path.join(racine, 'modules', 'coanimm.py'), encoding='utf-8').read()
    import modules.veille as V

    # Résumé ciblé : on veut écouter une réponse, pas le début d'un site
    bloc = V._bloc_contenus(question_resume='Quelles obligations pour les libraires ?')
    assert bloc['summary']['query'].startswith('Quelles obligations')
    assert 'summary' not in V._bloc_contenus(), 'pas de résumé si on n’en demande pas'

    # Catégories : valeurs imposées par Exa, libellés français
    assert 'research paper' in V.CATEGORIES and 'pdf' in V.CATEGORIES
    assert V.CATEGORIES[''] == 'Tout'

    envois = {}
    vrai = V._appel_exa
    V._appel_exa = lambda chemin, corps, k=None: (envois.update({'c': chemin, 'b': corps}),
                                                  ({'results': []}, ''))[1]
    try:
        V.exa_search('accessibilité des livres', nb=5, depuis_jours=7,
                     categorie='research paper', domaines_exclus=['spam.fr'])
        b = envois['b']
        assert envois['c'] == 'search'
        assert b['category'] == 'research paper'
        assert b['excludeDomains'] == ['spam.fr']
        assert b['numResults'] == 5 and b['type'] == 'auto'
        assert b['contents']['summary']['query'] == 'accessibilité des livres', \
            'le résumé doit répondre À LA question posée'
        assert b['startPublishedDate'].endswith('T00:00:00.000Z')

        # Une catégorie inventée ne doit pas être transmise : Exa renverrait 400
        V.exa_search('x', categorie='n’importe quoi')
        assert 'category' not in envois['b'], 'catégorie inconnue → non transmise'

        # Sans résumé, on garde le texte brut
        V.exa_search('x', resume=False)
        assert 'summary' not in envois['b']['contents']

        # Lecture propre d'une page
        V.exa_lire('http://a.fr')
        assert envois['c'] == 'contents' and envois['b']['urls'] == ['http://a.fr']
        assert V.exa_lire([])[1], 'adresse vide → message, pas de plantage'
        assert V.exa_lire('http://a.fr')[1] == "Exa n'a rien pu extraire de cette adresse."
    finally:
        V._appel_exa = vrai

    # La catégorie voyage jusqu'au sujet de veille
    import inspect
    assert 'categorie' in inspect.signature(V.add_sujet).parameters
    assert 'categorie=cat' in inspect.getsource(V.relever_sujet), \
        'un sujet filtré doit le rester à chaque relevé'

    assert '/api/exa/lire' in mn and '"categories"' in mn
    assert 'nimm_lire_page' in coa
    ok("Exa avancé : catégories filtrées, résumé ciblé, lecture propre d’une page")


def test_exa_dans_le_chat():
    """Exa était bâti mais inatteignable depuis une conversation.

    Un outil qui n'existe que dans un panneau de réglages n'est pas vraiment
    branché : quand on demande « cherche-moi ça » en discutant, c'est Brave qui
    répondait. Exa devient un mode de recherche à part entière, appelé à part —
    donc valable avec n'importe quel modèle, contrairement à l'ancrage Google.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hub = open(os.path.join(racine, 'core', 'hub.py'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    arbre = ast.parse(hub)

    # Routage : Exa reconnu, et repli EXPLIQUÉ si la clé manque
    seg = ''
    for n in ast.walk(arbre):
        if getattr(n, 'name', '') == '_choisir_recherche_web':
            seg = ast.get_source_segment(hub, n) or ''
    assert "choisi == 'exa'" in seg, 'Exa doit être un mode de routage'
    assert "clé Exa absente" in seg, 'un repli silencieux serait un mensonge'
    # Contrairement à l'ancrage Google, Exa ne dépend PAS du modèle actif
    i_exa = seg.find("choisi == 'exa'")
    assert "provider == 'exa'" not in seg[i_exa:], \
        "Exa est un appel séparé : il ne doit exiger aucun modèle particulier"

    # Fonction de recherche : résumé ciblé et citations réutilisant le format existant
    fn = ''
    for n in ast.walk(arbre):
        if getattr(n, 'name', '') == '_search_via_exa':
            fn = ast.get_source_segment(hub, n) or ''
    assert fn, '_search_via_exa introuvable'
    assert 'run_in_executor' in fn, 'exa_search est bloquant : hors du fil principal'
    assert '[NIMM_CITATIONS]' in fn, 'réutiliser le format de citations déjà affiché'
    assert 'raise RuntimeError' in fn, 'une panne doit déclencher le repli Brave/Tavily'

    # Branché dans les DEUX chemins de conversation
    assert hub.count("'mistral', 'anthropic', 'exa'") == 2, \
        'le chemin avec outils ET le chemin en streaming'
    assert hub.count("'exa': _search_via_exa") == 2

    assert 'value="exa" data-needs-key="exa"' in html, 'option grisée sans clé Exa'
    assert 'tous modèles' in html, "dire que ça marche avec n'importe quel modèle"
    ok("Exa dans la conversation : mode de recherche à part entière, repli expliqué")


def _affectes(noeud):
    """Noms affectés dans une fonction — sert à repérer le piège exact du
    2026-07-27 : un nom accumulé dans UNE fonction et lu dans une AUTRE."""
    return {n.id for n in ast.walk(noeud)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}


def test_audit_structurel():
    """Trois défauts qui ne se voient QUE par une analyse globale.

    Ils ont tous les trois été trouvés en auditant, pas en relisant :
    py_compile les laisse passer, et ils ne cassent rien avant l'exécution.
    """
    import pathlib
    racine = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # (1) NOM UTILISÉ SANS ÊTRE DÉFINI dans sa propre fonction.
    # _raisonnement_acc était accumulé dans une AUTRE fonction : tout flux
    # OpenAI-compatible (DeepSeek, OpenAI, OpenRouter, Mistral) levait un
    # NameError à la toute fin, après affichage — donc très discret.
    fautes = []
    for f in list(racine.glob('core/*.py')) + list(racine.glob('modules/*.py')) + [racine / 'main.py']:
        arbre = ast.parse(f.read_text(encoding='utf-8'))
        # Fonctions de PREMIER NIVEAU seulement : une fonction imbriquée lit
        # légitimement les variables de celle qui l'entoure, et c'est au premier
        # niveau que le piège s'est refermé.
        for fn in arbre.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            locaux, globaux = set(), set()
            for x in ast.walk(fn):
                if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store):
                    locaux.add(x.id)
                elif isinstance(x, (ast.Global, ast.Nonlocal)):
                    globaux.update(x.names)
                elif isinstance(x, (ast.Import, ast.ImportFrom)):
                    for al in x.names:
                        locaux.add((al.asname or al.name).split('.')[0])
                elif isinstance(x, ast.ExceptHandler) and x.name:
                    locaux.add(x.name)          # except … as _e
            locaux.update(a.arg for a in fn.args.args + fn.args.kwonlyargs)
            if fn.args.vararg:
                locaux.add(fn.args.vararg.arg)
            if fn.args.kwarg:
                locaux.add(fn.args.kwarg.arg)
            # On ne teste que les noms « privés de fonction » (préfixe _ et non
            # définis au niveau module) : c'est là que le piège se referme.
            module_niv = {n.id for x in arbre.body if isinstance(x, ast.Assign)
                          for n in x.targets if isinstance(n, ast.Name)}
            module_niv |= {getattr(x, 'name', '') for x in arbre.body}
            # Un alias d'import posé N'IMPORTE OÙ dans le fichier est légitime :
            # NIMM importe volontiers en cours de fonction, parfois dans un bloc
            # conditionnel que ce parcours ne rattache pas à la bonne portée.
            module_niv |= {(al.asname or al.name).split('.')[0]
                           for x in ast.walk(arbre)
                           if isinstance(x, (ast.Import, ast.ImportFrom)) for al in x.names}
            imbriquees = [g for g in ast.walk(fn)
                          if isinstance(g, (ast.FunctionDef, ast.AsyncFunctionDef))
                          and g is not fn]
            for g in imbriquees:
                locaux |= _affectes(g)
                locaux.add(g.name)
            for x in ast.walk(fn):
                if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load) \
                   and x.id.startswith('_') and not x.id.startswith('__') \
                   and x.id not in locaux and x.id not in globaux \
                   and x.id not in module_niv \
                   and any(x.id in _affectes(g) for g in arbre.body
                           if isinstance(g, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and g is not fn):
                    fautes.append(f"{f.name}:{x.lineno} {fn.name}() lit {x.id}")
    assert not fautes, "noms utilisés sans être définis :\n  " + "\n  ".join(fautes[:10])

    # (2) ROUTE DÉFINIE DEUX FOIS : la première gagne, la seconde est du code
    # mort — et si elle utilise une autre clé de réglage, le bouton semble
    # marcher tout en écrivant ailleurs. C'était le cas de stt-turbo.
    import collections
    routes = collections.Counter()
    arbre = ast.parse((racine / 'main.py').read_text(encoding='utf-8'))
    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) \
                   and d.func.attr in ('get', 'post', 'put', 'patch', 'delete') \
                   and d.args and isinstance(d.args[0], ast.Constant):
                    routes[d.func.attr.upper() + ' ' + d.args[0].value] += 1
    doubles = [k for k, v in routes.items() if v > 1]
    assert not doubles, "routes définies deux fois : " + ', '.join(doubles)
    assert len(routes) > 250, 'garde-fou : le décompte des routes doit rester plausible'

    # (3) ARITÉ des appels au journal de fonctionnement — un appel à trois
    # arguments avait rendu la route d'épinglage inutilisable (erreur 500).
    mauvais = []
    for f in racine.rglob('*.py'):
        if '__pycache__' in str(f) or f.name.startswith('test_'):
            continue
        try:
            a = ast.parse(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        for n in ast.walk(a):
            if isinstance(n, ast.Call) \
               and (getattr(n.func, 'attr', None) or getattr(n.func, 'id', None)) == 'add_diagnostic' \
               and len(n.args) + len(n.keywords) != 2:
                mauvais.append(f"{f.name}:{n.lineno}")
    assert not mauvais, "add_diagnostic prend 2 arguments : " + ', '.join(mauvais)

    ok("audit structurel : aucun nom indéfini, aucune route en double, journal bien appelé")


def test_veille_se_signale():
    """La veille relevait en arrière-plan… et se taisait.

    Le travailleur de fond existait bien, mais son résultat n'allait que dans la
    console du serveur et un diagnostic : rien de tout cela ne se lit à
    l'afficheur braille pendant qu'on travaille. Trois exigences : signaler ce
    qui APPREND quelque chose, ne PAS radoter, et consommer la notification une
    seule fois.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    import modules.veille as V

    # (1) Règle de signalement — fonction PURE, testable sans horloge ni réseau
    art = [{'titre': 'A', 'url': 'http://a'}]
    assert V._merite_signalement(art, 'Veille « X » : 1 nouveauté', {}), \
        'des nouveautés se signalent toujours'
    assert not V._merite_signalement([], 'Veille « X » : rien de nouveau (3 vus).', {}), \
        'le fonctionnement normal ne dérange pas'
    panne = 'Veille « X » : Aucune clé Exa enregistrée.'
    assert V._merite_signalement([], panne, {}), 'une panne inédite se signale'
    assert not V._merite_signalement([], panne, {'dernier_signal': panne}), \
        'la MÊME panne ne se signale pas toutes les heures'
    assert V._merite_signalement([], 'Veille « X » : Exa refuse la clé.',
                                 {'dernier_signal': panne}), \
        'une panne DIFFÉRENTE, elle, mérite d’être dite'

    # (2) Magasin simulé : le drapeau est posé, puis consommé UNE fois
    store, vlire, vecrire = {}, V._lire, V._ecrire
    V._lire = lambda c, d: json.loads(store.get(c, d))
    V._ecrire = lambda c, v: store.__setitem__(c, json.dumps(v))
    vsearch = V.exa_search
    try:
        store['veille_sujets'] = json.dumps([
            {'id': 's1', 'libelle': 'Accessibilité', 'requete': 'q',
             'periode': 'hebdomadaire', 'nb': 8, 'actif': True, 'dernier_run': ''}])
        V.exa_search = lambda *a, **k: (
            [{'titre': 'A', 'url': 'http://a', 'date': '2026-07-28', 'auteur': '',
              'extrait': 'xa', 'score': 1}], '')
        V.relever_les_dus(ingerer=False)

        sujet = V.list_sujets()[0]
        assert sujet.get('notifie') is False, \
            'un sujet créé AVANT le signalement doit quand même recevoir le drapeau'
        assert sujet.get('dernieres_nouveautes'), 'les articles trouvés sont conservés'

        attente = V.notifications_en_attente()
        assert len(attente) == 1 and attente[0]['libelle'] == 'Accessibilité'
        assert attente[0]['nouveautes'][0]['url'] == 'http://a'
        assert V.notifications_en_attente() == [], \
            'LECTURE UNIQUE : la deuxième lecture ne doit plus rien rendre'
    finally:
        V._lire, V._ecrire, V.exa_search = vlire, vecrire, vsearch
        import importlib
        importlib.reload(V)

    # (3) Le chemin complet existe : route consommatrice + annonce côté interface
    assert '@app.post("/api/veille/notifications")' in mn, 'POST : la lecture consomme'
    assert 'notifications_en_attente' in mn
    assert 'nb_trouves=len(nouveaux), notifie=True' in mn, \
        'un relevé manuel est déjà sous les yeux : il ne doit pas ressortir en annonce'
    assert '_veillePollNotifications' in app and 'coanimm-status-announce' in app
    assert '_veilleRendreNouveautes' in app, 'l’annonce passe, le texte doit rester'
    ok("veille : les relevés de fond se signalent, une fois, et seulement s’ils apprennent quelque chose")


def test_banc_essai_reordonnanceur():
    """Choisir un réordonnanceur au jugé, c'est régler un instrument sans l'entendre.

    Le banc pose la MÊME question aux mêmes passages dans chaque moteur. Trois
    exigences : ne modifier AUCUN réglage, ne pas bloquer la conversation
    pendant qu'il mesure, et rendre un rapport COPIABLE — un tableau qui
    n'existe qu'à l'écran ne se compare pas d'une semaine à l'autre.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    src = open(os.path.join(racine, 'modules', 'reranker.py'), encoding='utf-8').read()
    import modules.reranker as R

    cfg = {}
    vrai = R._reglage
    R._reglage = lambda n, d='': cfg.get(n, d)
    try:
        # (1) Le modèle par défaut suit le MOTEUR, pas un réglage unique mal partagé
        assert R._modele_pour('jina', '') == 'jina-reranker-v2-base-multilingual'
        assert R._modele_pour('cohere', '') == 'rerank-v3.5'
        cfg['rag_rerank_modele'] = 'bge-reranker-v2-m3'
        assert R._modele_pour('jina') == 'bge-reranker-v2-m3', 'le réglage explicite prime'
        assert R._modele_pour('jina', '') == 'jina-reranker-v2-base-multilingual', \
            'le banc doit pouvoir imposer le défaut de chaque moteur'
        cfg.clear()

        # (2) Inventaire honnête : les moteurs absents sont LISTÉS avec leur raison
        noms = [m['nom'] for m in R.moteurs_testables({})]
        assert noms == list(R.MOTEURS_BANC), noms
        par_nom = {m['nom']: m for m in R.moteurs_testables({'cohere': 'k'})}
        assert par_nom['cohere']['disponible'] and par_nom['semantique']['disponible']
        assert not par_nom['voyage']['disponible'] and 'Aucune clé' in par_nom['voyage']['raison']
        assert not par_nom['local']['disponible'], 'aucune adresse renseignée'
        cfg['rag_rerank_url'] = 'http://localhost:8081'
        assert [m for m in R.moteurs_testables({}) if m['nom'] == 'local'][0]['disponible']
        cfg.clear()

        # (3) Une question vide n'appelle personne
        assert 'erreur' in asyncio.run(R.banc_essai('', {}))

        # (4) Mesure complète, réseau et base simulés
        passages = [{'passage': 'la loi sur le livre numérique', 'titre': 'Loi',
                     'source': 'loi.pdf', 'score': 0.9},
                    {'passage': 'recette de tarte', 'titre': 'Tarte',
                     'source': 'cuisine.pdf', 'score': 0.7}]
        faux_enrich = types.ModuleType('modules.enrichissement')
        faux_enrich.search_documents = lambda q, k=5: list(passages)
        vrai_enrich = sys.modules.get('modules.enrichissement')
        sys.modules['modules.enrichissement'] = faux_enrich
        vcohere = R._rerank_cohere
        R._rerank_cohere = lambda q, t, c, modele=None: [(0, 0.94), (1, 0.02)]
        try:
            rap = asyncio.run(R.banc_essai('obligations du livre numérique',
                                           {'cohere': 'k'},
                                           moteurs=['semantique', 'cohere', 'voyage']))
        finally:
            R._rerank_cohere = vcohere
            if vrai_enrich is not None:
                sys.modules['modules.enrichissement'] = vrai_enrich
            else:
                sys.modules.pop('modules.enrichissement', None)

        par_moteur = {m['moteur']: m for m in rap['moteurs']}
        assert set(par_moteur) == {'semantique', 'cohere', 'voyage'}
        assert par_moteur['cohere']['ok'] and par_moteur['cohere']['classement'][0]['titre'] == 'Loi'
        assert par_moteur['cohere']['classement'][0]['retenu']
        assert not par_moteur['cohere']['classement'][1]['retenu'], 'sous le seuil'
        assert not par_moteur['voyage']['ok'] and 'Aucune clé' in par_moteur['voyage']['note'], \
            'un moteur sans clé est rapporté, pas masqué'
        assert par_moteur['semantique']['ok'], 'la référence sans réordonnanceur est mesurée'
        assert rap['nb_passages'] == 2 and rap['texte'], 'un rapport copiable est produit'
        assert 'Loi' in rap['texte'] and 'BANC' in rap['texte']
    finally:
        R._reglage = vrai

    # (5) Instrument de mesure, pas réglage déguisé : le banc n'écrit RIEN
    debut = src.index("def banc_essai") if "def banc_essai" in src else src.index("async def banc_essai")
    corps = src[debut:]
    assert 'set_setting' not in corps, "le banc ne doit modifier AUCUN réglage"
    assert '_aio.to_thread' in corps, "les moteurs HTTP sont bloquants : hors de la boucle"

    # (6) Le chemin complet existe, et il est accessible
    assert '@app.post("/api/rag/banc")' in mn and '/api/rag/banc/moteurs' in mn
    assert 'id="banc-question"' in html and 'id="banc-texte"' in html
    assert 'aria-label="Résultats du banc d\'essai"' in html
    assert '_bancRendre' in app and "createElement('table')" in app, \
        'un classement se parcourt en tableau, pas en paragraphe'
    assert "th.scope = 'col'" in app and "td.scope = 'row'" in app, \
        'sans en-têtes portées, un tableau est illisible au lecteur d’écran'
    ok("banc d'essai : mesure côte à côte, aucun réglage touché, rapport copiable et tableau accessible")


def test_musique_lyria():
    """Lyria dormait derrière une clé déjà présente.

    Trois exigences : ne rien promettre sans la clé, remonter les paroles
    SÉPARÉMENT de l'audio (c'est la seule partie lisible au braille), et ne
    jamais lever d'exception vers l'appelant — une génération musicale ratée
    n'est pas une panne de NIMM.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    gitignore = open(os.path.join(racine, '.gitignore'), encoding='utf-8').read()
    import modules.musique as M

    # (1) Sans clé, on le DIT — et on ne tente rien
    dispo = M.modeles_disponibles({})
    assert not dispo['cle_presente'] and 'Aucune clé Gemini' in dispo['note']
    assert M.modeles_disponibles({'gemini': 'k'})['cle_presente']
    assert 'erreur' in asyncio.run(M.generer('un morceau', api_keys={}))
    assert 'erreur' in asyncio.run(M.generer('', api_keys={'gemini': 'k'})), \
        'une consigne vide n’appelle personne'

    # (2) L'ordre des parties n'est PAS garanti : audio d'abord, texte ensuite
    audio, mime, textes = M._extraire({'candidates': [{'content': {'parts': [
        {'inlineData': {'data': 'QUJD', 'mimeType': 'audio/mpeg'}},
        {'text': 'Couplet 1'}, {'text': 'Refrain'}]}}]})
    assert audio == 'QUJD' and mime == 'audio/mpeg'
    assert textes == 'Couplet 1\n\nRefrain', textes
    # …et dans l'autre sens, avec la variante snake_case
    audio2, _, t2 = M._extraire({'candidates': [{'content': {'parts': [
        {'text': 'Paroles'}, {'inline_data': {'data': 'WFla', 'mime_type': 'audio/wav'}}]}}]})
    assert audio2 == 'WFla' and t2 == 'Paroles'
    assert M._extraire({'bruit': 1}) == ('', '', '')

    # (3) Un refus de sécurité arrive en 200 sans audio : ça se dit
    refus = M._raison_refus({'candidates': [{'finishReason': 'SAFETY'}]})
    assert 'refusée' in refus and 'SAFETY' in refus
    assert 'bloquée' in M._raison_refus({'promptFeedback': {'blockReason': 'OTHER'}})
    assert M._raison_refus({'candidates': [{'finishReason': 'STOP'}]}) == ''

    # (4) Le décodage ne lève jamais
    assert M.decoder('QUJD') == b'ABC'
    assert M.decoder('pas du base64 !!') == b''
    assert M.decoder('data:audio/mpeg;base64,QUJD') == b'ABC'

    # (5) Le format demandé est corrigé, jamais imposé en douce
    assert 'wav' in M.MODELES['pro']['formats'] and 'wav' not in M.MODELES['clip']['formats']

    # (6) Chemin complet, confinement du nom de fichier, et audio hors du dépôt
    assert '/api/musique/generer' in mn and '/api/musique/fichier/' in mn
    assert '_musique_nom_sur' in mn and 'os.path.basename' in mn, \
        'un nom venu du client ne traverse jamais un dossier'
    assert 'data/musiques/' in gitignore, 'les fichiers audio n’ont rien à faire dans git'

    # (7) Interface : bouton conditionné à la clé, paroles copiables, lecteur étiqueté
    assert 'id="toggle-musique"' in html
    assert "_btnMus.hidden = !(keys && keys.gemini)" in app, \
        'un bouton qui mène à un refus n’a rien à faire dans la barre'
    assert 'zone.readOnly = true' in app and "createElement('textarea')" in app, \
        'les paroles doivent être sélectionnables et copiables'
    assert "audio.setAttribute('aria-label'" in app, 'un lecteur audio sans nom est muet'
    assert "'u': 'toggle-musique'" in app and "'toggle-musique': 'Alt+Shift+U'" in app
    ok("musique : Lyria ouvert par la clé Gemini, paroles séparées et copiables, échecs muets")


def test_imagerie_reglee():
    """« Gemini (Imagen) » ne réglait rien : ni format, ni résolution, ni modèle.

    La correction évidente — ajouter le vrai Imagen — aurait été une faute :
    Imagen cesse de répondre le 17 août 2026. Les réglages passent donc par
    l'API Interactions. Trois exigences : ne rien envoyer chez le prestataire
    qui y reste (store=false), corriger une résolution impossible sans mentir
    dessus, et décrire l'image produite.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    src = open(os.path.join(racine, 'modules', 'imagerie.py'), encoding='utf-8').read()
    import modules.imagerie as I

    # (1) Sans clé, on le DIT — et on n'appelle personne
    o = I.options({})
    assert not o['cle_presente'] and 'Aucune clé Gemini' in o['note']
    assert I.options({'gemini': 'k'})['cle_presente']
    assert 'erreur' in asyncio.run(I.generer('un chat', api_keys={}))
    assert 'erreur' in asyncio.run(I.generer('', api_keys={'gemini': 'k'}))

    # (2) RGPD : rien ne reste chez Google. Même choix que l'agent Vibe.
    assert "'store': False" in src, "l'API Interactions conserve TOUT par défaut"

    # (2 bis) La livraison en ligne est DEMANDÉE, pas espérée : ce module lit des
    # octets, pas une référence. Et le format demandé est celui qu'on écrira.
    assert "'delivery': 'inline'" in src
    assert "'mime_type': _MIME_DEMANDE" in src

    # (2 ter) L'extension du fichier suit le format REÇU, pas celui demandé
    assert I.extension_pour('image/jpeg') == 'jpg'
    assert I.extension_pour('image/webp') == 'webp'
    assert I.extension_pour('image/png') == 'png'
    assert I.extension_pour('image/jpeg; charset=utf-8') == 'jpg', 'paramètres MIME tolérés'
    assert I.extension_pour('') == 'png' and I.extension_pour(None) == 'png'
    assert 'extension_pour' in mn and '.png"' not in mn.split('imagerie_generer')[-1][:1500], \
        'la route ne doit plus écrire une extension en dur'

    # (3) On n'a PAS branché Imagen, et le code dit pourquoi
    assert 'imagen-4' not in src and 'imagen-3' not in src, 'API condamnée : pas de code neuf dessus'
    assert '17 août 2026' in src and '17 août 2026' in mn, \
        'la raison du choix doit rester lisible là où on serait tenté de revenir dessus'
    assert 'imagen-' not in mn and ':predict"' not in mn, \
        "aucun modèle ni endpoint Imagen ne doit être appelé"

    # (4) Lecture de la réponse : l'ordre des blocs n'est PAS garanti
    rep = {'steps': [
        {'type': 'model_output', 'content': [
            {'type': 'text', 'text': 'Voilà.'},
            {'type': 'image', 'data': 'QUJD', 'mime_type': 'image/png'}]}]}
    images, texte = I._extraire(rep)
    assert images and images[0]['b64'] == 'QUJD' and texte == 'Voilà.'
    # …et dans l'autre sens, avec un raccourci de commodité
    im2, _ = I._extraire({'output_image': {'data': 'WFla', 'mime_type': 'image/jpeg'}})
    assert im2[0]['b64'] == 'WFla' and im2[0]['mime'] == 'image/jpeg'
    assert I._extraire({'bruit': 1}) == ([], '')
    assert I._extraire('rien') == ([], '')

    # (5) Une résolution impossible est corrigée, mais la réponse porte la VRAIE
    vraie = I.generer
    capture = {}

    async def _faux_post(prompt, modele='flash', ratio='1:1', taille='1K',
                         api_keys=None, images_ref=None):
        capture['ratio'], capture['taille'] = ratio, taille
        return {'images': [{'b64': 'QUJD', 'mime': 'image/png'}], 'ratio': ratio,
                'taille': taille}
    assert 'lite' in I.MODELES and I.MODELES['lite']['tailles'] == ('1K',), \
        'le modèle économique ne fait que du 1K'
    assert '4K' in I.MODELES['flash']['tailles']
    assert '21:9' in I.RATIOS and '9:16' in I.RATIOS

    # (5 bis) Identifiants relevés dans la liste officielle des modèles, jamais
    # déduits d'une phrase — voir le même piège attrapé côté Veo.
    ids = sorted(m['id'] for m in I.MODELES.values())
    assert ids == ['gemini-3-pro-image', 'gemini-3.1-flash-image',
                   'gemini-3.1-flash-lite-image'], ids
    for nom, conf in I.MODELES.items():
        assert conf['tailles'], nom
        assert set(conf['tailles']) <= {'0.5K', '1K', '2K', '4K'}, nom
    assert '0.5K' not in I.MODELES['pro']['tailles'], \
        'le 0,5K est propre au modèle Flash'

    # (6) L'image générée est DÉCRITE : sans alt, une image est un fichier muet
    assert '_vibe_describe_image' in mn and 'alt' in mn
    assert 'id="studio-image-decrire"' in html
    assert "vign.alt = im.alt ||" in app, 'jamais d’alt inventé quand la description manque'
    assert 'zone.readOnly = true' in app, 'la description doit être copiable'

    # (7) UNE SEULE porte pour créer un média. RÈGLE RÉÉCRITE le 28/08.
    #
    # Le studio a vécu dans la barre du haut, puis derrière le menu « + »
    # (30/07), et il vit désormais DANS le panneau Images. Motif du dernier
    # déménagement : Fernando y a cherché la création d'image et de vidéo trois
    # fois de suite sans les trouver. Le « + » sert ce qui s'ajoute au message
    # en cours ; le panneau Images sert ce qui produit et conserve des fichiers.
    #
    # Ce qui n'a pas changé et reste vérifié : UNE porte, pas trois.
    assert 'id="toggle-studio"' not in html and 'toggle-studio' not in app, \
        'le studio ne doit pas retrouver un bouton propre dans la barre'
    assert 'id="studio-modal"' not in html and 'studio-modal' not in app, \
        'la modale studio a fusionné : plus personne ne doit la chercher'
    assert 'plus-studio' not in html and 'plus-studio' not in app, \
        'l’entrée du menu « + » a été retirée avec la fusion'
    debut_images = html.index('<div id="galerie-modal"')
    assert html.index('id="studio-image-details"') > debut_images, \
        'la création d’image doit vivre dans le panneau Images'
    assert 'window._ouvrirStudio' in app, 'la fonction d’ouverture doit survivre'
    ok("imagerie : réglages complets, rien conservé chez Google, image décrite, une seule porte")


def test_anthropic_parametres_echantillonnage():
    """RÉGRESSION VÉCUE : « 400 Bad Request » sur toute conversation Anthropic.

    Cause : depuis la génération 4.7, plusieurs modèles Anthropic refusent TOUT
    paramètre d'échantillonnage — « non-default temperature, top_p, or top_k
    values return a 400 error on every request, regardless of whether thinking
    is used ». Ce n'est donc pas lié à la réflexion : c'est vrai sur chaque
    appel. NIMM envoyait `temperature` en dur sur les TROIS chemins Anthropic.
    Déclenchée en mettant Sonnet 5 et Opus 5 dans les modèles conseillés : le
    modèle changeait, et plus rien ne répondait.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()

    # (1) La règle est PURE et testable sans réseau ni clé
    espace = {}
    deb = eng.index('_ANTHROPIC_SANS_ECHANTILLONNAGE = (')
    fin = eng.index('\n\n', eng.index('return not any', deb))
    exec(eng[deb:fin], espace)
    accepte = espace['anthropic_accepte_temperature']

    for interdit in ('claude-sonnet-5', 'claude-opus-5', 'claude-fable-5',
                     'claude-opus-4-7', 'claude-opus-4-8', 'claude-mythos-5'):
        assert not accepte(interdit), interdit + ' : température refusée par l’API'
    for permis in ('claude-sonnet-4-6', 'claude-haiku-4-5-20251001',
                   'claude-3-5-sonnet-20241022'):
        assert accepte(permis), permis + ' : la température doit rester réglable'
    assert not accepte('CLAUDE-SONNET-5'), 'la casse ne doit pas ouvrir une brèche'
    # Modèle inconnu : on conserve le comportement historique plutôt que de
    # retirer un réglage à un modèle qui l'accepte peut-être.
    assert accepte('') and accepte(None) and accepte('un-modele-inconnu')

    # (2) Les TROIS chemins Anthropic appliquent la règle — c'est le nombre de
    #     chemins qui compte : n'en corriger que deux, c'est le bug qui revient
    #     dès qu'on active les outils ou qu'on quitte le flux.
    assert eng.count('anthropic_accepte_temperature(model)') == 3, \
        'appel direct, flux et flux-avec-outils doivent tous appliquer la règle'

    # (3) Plus aucun envoi inconditionnel dans les charges utiles Anthropic
    for bloc in re.findall(r"payload = \{[^}]*'messages':\s*(?:_oai_msgs_to_anthropic|anthropic_messages)[^}]*\}", eng):
        assert "'temperature': temperature" not in bloc, \
            'température encore envoyée en dur à Anthropic'
    # (4) MÊME CLASSE DE DÉFAUT CHEZ LES AUTRES — cherchée à la demande de
    #     Fernando après la panne Anthropic. Deux trous PRÉEXISTANTS trouvés :
    #     le garde des modèles de raisonnement OpenAI (série o, qui exigent
    #     `max_completion_tokens` et refusent `temperature`) existait sur le flux
    #     AVEC outils, mais ni sur l'appel direct, ni sur le flux SIMPLE — or
    #     c'est ce dernier qu'emprunte la conversation ordinaire. Même asymétrie
    #     que celle qui a cassé Anthropic : un chemin corrigé, les autres non.
    for fonction, ancre in (
            ('_call_openai_compat', "**({'max_completion_tokens': max_tokens} if _modele_raisonnement_openai(model)"),
            ('_call_openai_compat_stream', "# Le flux AVEC outils avait ce garde, pas le flux simple"),
            ('continuer_reponse_stream', "if not (_modele_raisonnement_openai(_m_repr) or _modele_sans_outils(_m_repr)):"),
    ):
        assert ancre in eng, '%s : garde des modèles de raisonnement absent' % fonction

    # Aucune charge utile OpenAI-compatible ne doit envoyer `temperature` en dur.
    # Gemini et Ollama sont hors sujet : le premier la range dans
    # `generationConfig` (acceptée par tous ses modèles, la réflexion se règle
    # ailleurs), le second est un serveur local tolérant.
    for bloc in re.findall(r"json=\{[^}]*'chat/completions'[^}]*\}", eng):
        assert "'temperature': temperature," not in bloc, \
            'charge utile OpenAI-compat avec température inconditionnelle'
    ok("Anthropic : température omise sur les modèles qui la refusent, sur les trois chemins")


def test_reponse_muette_apres_outil():
    """RÉGRESSION VÉCUE : réponse entièrement MUETTE après une recherche web.

    Symptôme rapporté par Fernando : « Content de te retrouver. Je cherche. »,
    puis « Recherche en cours… », puis « NIMM t'a répondu » — et rien. Aucune
    erreur affichée, donc aucune exception : le flux s'est terminé sans produire
    le moindre texte.

    Cause : en phase 2 (après l'exécution de l'outil), NIMM REDÉCLARE les outils
    à Anthropic — c'est structurellement obligatoire dès que l'historique
    contient un appel et son résultat. Mais le chemin employé alors ne sait lire
    QUE du texte : il ignore les blocs d'appel d'outil. Le modèle, ayant le droit
    de chercher à nouveau, a redemandé l'outil — dans le vide.

    Le commentaire du code tirait déjà cette conclusion pour les autres
    fournisseurs (on ne leur repasse pas les outils) sans la tirer pour Anthropic.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    hub = open(os.path.join(racine, 'core', 'hub.py'), encoding='utf-8').read()

    # (1) Le chemin de flux Anthropic sait INTERDIRE l'usage des outils tout en
    #     les laissant déclarés — les retirer provoquerait un refus de l'API.
    deb = eng.index('async def _call_anthropic_stream')
    corps = eng[deb:eng.index('\nasync def ', deb + 10)]
    assert 'outils_interdits' in corps.split(chr(10))[0], 'option absente de la signature'
    assert "payload['tool_choice'] = {'type': 'none'}" in corps
    assert "payload['tools'] = _oai_tools_to_anthropic(tools)" in corps, \
        'les outils doivent rester DÉCLARÉS : Anthropic les exige'

    # (2) L'option est relayée depuis le point d'entrée du flux
    assert 'outils_interdits: bool = False,' in eng
    assert 'outils_interdits=outils_interdits' in eng

    # (3) La phase 2 a cédé la place à une boucle agentique BORNÉE : le modèle
    #     garde les outils actifs et peut enchaîner plusieurs appels (ex : lister
    #     un fichier PUIS l'exécuter), plafonnée à _MAX_TOOL_LOOPS pour interdire
    #     la boucle infinie. Le garde-fou l'annonce explicitement si le plafond
    #     est atteint — et le REPLI SANS OUTILS (7) reste en dernier recours.
    assert '_MAX_TOOL_LOOPS = 4' in hub
    assert '_prochain_evt' in hub
    assert 'call_llm_stream_with_tools(' in hub
    assert "Je m'arrête là après plusieurs étapes" in hub

    # (4) GARDE-FOU : un silence ne doit JAMAIS passer inaperçu, quelle qu'en
    #     soit la cause. Une réponse muette est pire qu'une erreur — la synthèse
    #     vocale annonce « NIMM t'a répondu » et il n'y a rien à écouter.
    assert '_avant_phase2 = len(full_reply)' in hub
    assert 'if len(full_reply) == _avant_phase2:' in hub
    assert 'add_diagnostic as _ad_muet' in hub, 'le silence doit aussi aller au journal'
    # (5) Le flux Anthropic ne doit RIEN jeter en silence. Deux défauts trouvés
    #     en cherchant la cause du silence, tous deux masquants :
    #     - seuls les blocs de TEXTE étaient lus ; les modèles récents
    #       réfléchissent d'office et émettent des blocs d'un autre type, jetés ;
    #     - toute erreur de lecture était avalée par un « except: continue »,
    #       ce qui rendait la cause introuvable.
    assert "_delta.get('thinking')" in eng, \
        "la réflexion doit être captée, pas jetée"
    assert '_erreurs_parse' in eng, "une ligne illisible doit être signalée, pas avalée"
    assert "if _reflexion_acc and not _a_du_texte:" in eng, \
        "réflexion sans texte : le dire, c'est le seul moyen de diagnostiquer"
    # (6) Le repli après refus du cache relançait sans l'interdiction d'outils
    assert eng.count('outils_interdits=outils_interdits') == 2, \
        "les DEUX appels (relais normal et repli après refus du cache) doivent " \
        "conserver l'interdiction, sinon le silence revient par l'un des chemins"
    # (7) REPLI SANS OUTILS — dernier recours, et le seul qui ne dépende d'aucune
    #     subtilité d'API. Après trois correctifs posés sans voir la cause
    #     (interdiction d'usage, garde-fou, lecture de la réflexion), le parti
    #     pris change : plutôt que de négocier les options, on change la QUESTION.
    #     L'historique est reconstruit sans appel d'outil, le résultat fusionné
    #     dans la question — le modèle n'a alors plus aucun moyen d'en redemander.
    assert '_hist_plat' in hub and 'tools=None,' in hub
    assert "if m.get('role') in ('user', 'assistant')" in hub
    assert "not m.get('tool_calls')" in hub, 'aucun appel d’outil ne doit subsister'
    # Fusion dans le dernier message plutôt qu'ajout : deux « user » consécutifs
    # sont une forme que tous les fournisseurs n'acceptent pas.
    assert "_hist_plat[-1].get('role') == 'user'" in hub
    # Et si même le repli échoue, on le dit encore.
    assert 'repli sans outils compris' in hub
    ok("réponse muette après outil : boucle agentique bornée, repli et silence impossible")



def test_demarrage_a_froid():
    """Ce qui coûte au PREMIER message, et qui ne se voit qu'une fois.

    Laurent a ramené la latence de 15 s à 7-8 s et signalait « encore un peu de
    marge ». Deux défauts trouvés en suivant sa piste :

    1. `_get_model()` n'avait AUCUN verrou. Le préchauffage lancé au démarrage
       et le premier message pouvaient demander le modèle en même temps : le
       second voyait `_embed_model` encore à None et lançait un SECOND
       chargement du même modèle, en concurrence avec le premier.
    2. `_match_documents` était appelé DANS la coroutine : il calcule un
       plongement et peut lancer des appels HTTP vers le réordonnanceur, ce qui
       bloquait toute la boucle — donc tout le serveur — et à froid le
       chargement du modèle s'y ajoutait.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mem = open(os.path.join(racine, 'modules', 'memory.py'), encoding='utf-8').read()
    hub = open(os.path.join(racine, 'core', 'hub.py'), encoding='utf-8').read()

    # (1) Le chargement du modèle est protégé, avec double vérification
    assert '_embed_lock = threading.Lock()' in mem
    corps = mem[mem.index('def _get_model'):]
    corps = corps[:corps.index('def _embed')]
    assert 'with _embed_lock:' in corps, 'chargement non protégé'
    # Deux tests de présence : un AVANT le verrou (coût nul en régime courant)
    # et un DEDANS (un autre fil a pu terminer pendant l'attente).
    assert corps.count('if _embed_model is not None:') == 2, \
        'double vérification requise : sans celle du dessus, chaque appel prend le verrou'

    # (2) Les étapes bloquantes sortent de la boucle, sur les DEUX chemins
    #     (message simple et message diffusé) — même motif que partout ailleurs :
    #     n'en traiter qu'un, c'est laisser le défaut sur l'autre.
    assert hub.count('await asyncio.to_thread(') >= 2
    arbre = ast.parse(hub)
    for n in ast.walk(arbre):
        if isinstance(n, ast.AsyncFunctionDef) and n.name in ('process_message', 'process_message_stream'):
            for x in ast.walk(n):
                if isinstance(x, ast.Call) and getattr(x.func, 'id', '') == '_match_documents':
                    ligne = hub.split(chr(10))[x.lineno - 1]
                    amont = hub.split(chr(10))[x.lineno - 2]
                    assert 'to_thread' in ligne or 'to_thread' in amont, (
                        '%s : _match_documents bloque la boucle (ligne %d)' % (n.name, x.lineno))
    ok("démarrage à froid : modèle chargé une seule fois, plongements hors de la boucle")


def test_documentation_a_jour():
    """Le README est la porte d'entrée : il vieillit sans que rien ne l'annonce.

    Remarque de Fernando (10/08/2026) : « as-tu mis à jour les fichiers de doc ? »
    Non. ARCHITECTURE.md était tenu à jour à chaque lot — c'est le journal
    technique — mais le README ignorait cinq fonctions livrées et deux
    fournisseurs branchés. Ce test lie les deux : un fournisseur déclaré dans
    le catalogue doit figurer dans le README.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    readme = open(os.path.join(racine, 'README.md'), encoding='utf-8').read()
    import core.services as SV

    # (1) Tout fournisseur de conversation du catalogue est dans le README
    for s in SV.SERVICES:
        if s.get('famille') != 'conversation':
            continue
        nom = s['nom'].split('(')[0].strip()
        assert nom.lower() in readme.lower(), (
            'fournisseur absent du README : ' + nom)

    # (2) Les fonctions livrées y sont nommées
    for fonction in ('Lyria', 'Veo', 'veille', "banc d'essai", 'sauvegarde'):
        assert fonction.lower() in readme.lower(), (
            'fonction absente du README : ' + fonction)

    # (3) Les tableaux sont BIEN FORMÉS. Une ligne qui a une colonne de trop
    #     décale toute la lecture au lecteur d'écran — défaut introduit par moi
    #     le 30/07 sur la ligne Gemini, passé inaperçu dix jours.
    lignes = readme.split(chr(10))
    i = 0
    while i < len(lignes):
        if lignes[i].startswith('|') and i + 1 < len(lignes) and set(lignes[i+1].replace('|','').replace(':','').strip()) <= set('- '):
            attendu = lignes[i].count('|')
            j = i
            while j < len(lignes) and lignes[j].startswith('|'):
                assert lignes[j].count('|') == attendu, (
                    'tableau mal formé ligne %d : %d séparateurs au lieu de %d — %s'
                    % (j + 1, lignes[j].count('|'), attendu, lignes[j][:60]))
                j += 1
            i = j
        else:
            i += 1
    ok("documentation : README à jour des fournisseurs et des fonctions, tableaux bien formés")


def test_reflexion_deepseek():
    """La réflexion invisible de DeepSeek : coupée partout, mais RÉGLABLE.

    Trouvaille de Laurent (07/08/2026) : `deepseek-v4-*` réfléchit d'office à
    effort élevé. Invisible, mais ça consomme le budget `max_tokens` — d'où
    des titres de fils vides — et ça ajoutait quatorze secondes avant le
    premier mot. Son correctif couvrait TROIS chemins ; il en existe QUATRE,
    la reprise de réponse ayant été oubliée. Même motif que les adresses de
    base et la température Anthropic : un chemin traité, les autres non.

    Sa question ouverte — est-ce que ça nuit sur les questions complexes ? —
    n'a pas de réponse tranchée, et c'est précisément pourquoi le choix ne
    doit pas être figé dans le code.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()

    # (1) La règle est PURE et testable sans base ni réseau
    deb = eng.index('def reflexion_deepseek_desactivee')
    fin = eng.index('def _modele_raisonnement_openai', deb)
    import sys as _sys, types as _types
    def _regle(valeur, panne=False):
        faux = _types.ModuleType('core.database')
        if panne:
            def _boum(*a, **k): raise RuntimeError('base indisponible')
            faux.get_setting = _boum
        else:
            faux.get_setting = lambda c, d='': valeur
        _sys.modules['core.database'] = faux
        ns = {}
        exec(eng[deb:fin], ns)
        return ns['reflexion_deepseek_desactivee']()

    assert _regle('coupee') is True, 'défaut : réflexion coupée'
    assert _regle('gardee') is False
    assert _regle('GARDEE') is False, 'la casse ne doit pas ouvrir une brèche'
    assert _regle('') is True and _regle('valeur_inconnue') is True
    assert _regle(None, panne=True) is True, 'base indisponible : défaut réactif'

    # (2) LES QUATRE chemins DeepSeek, pas trois. Le compte est ancré : en
    #     couvrir un de moins, c'est la lenteur qui revient sur ce chemin-là.
    assert eng.count('and reflexion_deepseek_desactivee()') == 4, (
        'appel direct, flux simple, flux-outils ET reprise de réponse')
    # Aucune pose inconditionnelle ne doit subsister
    for m in re.finditer(r"thinking. \{.type.: .disabled.\}", eng):
        amont = eng[max(0, m.start() - 300):m.start()]
        assert 'reflexion_deepseek_desactivee' in amont, \
            'réflexion coupée sans passer par le réglage'

    # (3) Le réglage est ATTEIGNABLE : une fonction sans interface n'existe pas
    assert '@app.get("/api/settings/deepseek-reflexion")' in mn
    assert '@app.post("/api/settings/deepseek-reflexion")' in mn
    assert 'deepseek-reflexion-toggle' in html, 'aucune case à cocher'
    assert "_wireToggleReglage('deepseek-reflexion-toggle'" in app, \
        'brancher via le helper existant plutôt que d\'inventer un contrat de plus'

    # (4) Même contrat {active} que les autres réglages à case : un troisième
    #     format aurait été une divergence de plus à maintenir.
    bloc = mn[mn.index('async def deepseek_reflexion_get'):]
    bloc = bloc[:bloc.index('@app.post')]
    assert "'active'" in bloc and 'mode' not in bloc.split('"""')[-1]
    ok("réflexion DeepSeek : coupée par défaut sur les QUATRE chemins, et réglable")


def test_erreur_api_explique_la_cause():
    """Une erreur qui ne dit que l'adresse appelée ne sert à personne.

    Le 400 ci-dessus s'affichait « Erreur inattendue de anthropic : Client error
    '400 Bad Request' for url … » — l'API expliquait pourtant précisément le
    refus, dans le corps de la réponse, qui n'était jamais lu.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()

    espace = {'json': json}
    deb = eng.index('def _detail_erreur_api')
    fin = eng.index('\n\n', eng.index('return corps.strip()[:300]', deb))
    exec(eng[deb:fin], espace)
    detail = espace['_detail_erreur_api']

    # Les fournisseurs ne rangent pas le message au même endroit : accepter les
    # trois formes plutôt que d'en privilégier une et perdre les autres.
    assert 'temperature' in detail(
        '{"type":"error","error":{"type":"invalid_request_error",'
        '"message":"temperature: Input should be 1"}}')
    assert detail('{"error":{"message":"Unsupported parameter"}}') == 'Unsupported parameter'
    assert detail('{"message":"Bad model id"}') == 'Bad model id'
    assert detail('{"detail":"Nom de fichier invalide."}') == 'Nom de fichier invalide.'
    assert detail('{"error":"model not found"}') == 'model not found'
    assert detail('Bad Request') == 'Bad Request', 'corps non JSON : rendu tel quel'
    assert detail('') == '' and detail(None) == ''

    # Le classement traite désormais le 400, et le corps de la réponse est
    # conservé dans sa casse d'origine (le reste est mis en minuscules).
    assert "if code == 400:" in eng and 'brut = txt' in eng
    assert '_detail_erreur_api(brut)' in eng
    ok("erreurs d'API : la raison du refus remonte jusqu'à l'utilisateur")


def test_fournisseurs_cables_partout():
    """Un fournisseur à moitié branché répond en direct et se tait en flux.

    L'adresse de base et le modèle de repli étaient recopiés à TROIS endroits
    d'engine.py — appel direct, flux, flux avec outils. Trois copies, c'est la
    garantie qu'un ajout n'en touche que deux, et le symptôme est discret : le
    fournisseur marche quand on le teste, et reste muet en usage réel.
    Source unique désormais, et ce test vérifie que chaque fournisseur déclaré
    est atteignable de bout en bout.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    eng = open(os.path.join(racine, 'core', 'engine.py'), encoding='utf-8').read()
    db = open(os.path.join(racine, 'core', 'database.py'), encoding='utf-8').read()
    hub = open(os.path.join(racine, 'core', 'hub.py'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    import core.services as SV

    # engine.py importe httpx, absent de certains environnements de test : on lit
    # donc la table dans l'ARBRE SYNTAXIQUE plutôt que d'importer le module.
    arbre = ast.parse(eng)
    table = None
    for n_ in ast.walk(arbre):
        if isinstance(n_, ast.Assign) and any(
                getattr(t, 'id', '') == 'FOURNISSEURS_OPENAI_COMPAT' for t in n_.targets):
            table = ast.literal_eval(n_.value)
    assert table, 'table des fournisseurs compatibles OpenAI introuvable'
    assert {'deepseek', 'openai', 'openrouter', 'mistral', 'groq', 'cerebras'} <= set(table)

    def _valeur(nom_var):
        for x in ast.walk(arbre):
            if isinstance(x, ast.Assign) and any(
                    getattr(t, 'id', '') == nom_var for t in x.targets):
                return ast.literal_eval(x.value)
        return {}
    modeles_defaut = _valeur('_PROVIDER_DEFAULT_MODEL')

    # (1) Chaque entrée est complète et plausible
    for nom, conf in table.items():
        assert conf['base'].startswith('https://'), nom
        assert conf['modele'], nom
        assert isinstance(conf.get('outils'), bool), \
            '%s : dire si le fournisseur sait appeler des outils, ne pas le supposer' % nom

    # (2) UNE seule source pour le CHAT : plus de dictionnaire d'adresses recopié.
    #     On ne compte pas les occurrences d'une adresse — les points d'accès
    #     annexes (liste des modèles, agents, solde, complétion de code) la
    #     réutilisent légitimement. Ce qu'on traque, c'est la structure dupliquée.
    for reste in ("urls[provider]", "models[provider]",
                  "urls = {\n        'deepseek'", "models = {\n        'deepseek'"):
        assert reste not in eng, 'reste de l’ancienne table locale : ' + reste
    assert eng.count('_base_openai_compat(') >= 6, \
        'les appels doivent tirer leur adresse de la table, pas d’un littéral'

    # (3) Le flux et le flux-avec-outils se servent de la table, pas d'une liste figée
    assert 'elif provider in FOURNISSEURS_OPENAI_COMPAT:' in eng
    assert "_SUPPORTED = {p for p, c in FOURNISSEURS_OPENAI_COMPAT.items() if c.get('outils')}" in eng, \
        "les fournisseurs sans outils doivent retomber sur le flux simple, pas envoyer une requête ignorée"

    # (4) Les deux nouveaux sont câblés de bout en bout
    for nom in ('groq', 'cerebras'):
        assert nom in modeles_defaut, '%s : modèle par défaut' % nom
        assert nom in SV.ids(), '%s : absent du catalogue des services (pas de champ de clé)' % nom
        assert "'%s':" % nom in db or "('%s'," % nom in db, '%s : tarif/portefeuille' % nom
        assert nom.upper() + '_API_KEY' in eng, '%s : clé d’environnement (engine)' % nom
        assert nom.upper() + '_API_KEY' in hub, '%s : clé d’environnement (hub)' % nom
        assert "'%s':       '%s'," % (nom, nom) in hub or "'%s':   '%s'," % (nom, nom) in hub, \
            '%s : correspondance clé→fournisseur dans hub' % nom
        assert 'value="%s"' % nom in html, '%s : absent des sélecteurs de fournisseur' % nom

    # (5) Le catalogue de modèles est interrogé en direct pour les deux : leurs
    #     modèles à poids ouverts changent souvent, rien ne doit être figé.
    assert "if provider in ('groq', 'cerebras'):" in eng and "'/models'" in eng

    # (6) Repli automatique : les deux entrent dans l'ordre de secours, mais
    #     APRÈS les modèles propriétaires — ils sont rapides, pas plus fins.
    ordre = eng[eng.index("ordre = ['mistral'"):]
    ordre = ordre[:ordre.index(']')]
    for nom in ('groq', 'cerebras'):
        assert nom in ordre, '%s : absent du repli automatique' % nom
    assert ordre.index('anthropic') < ordre.index('groq')

    # (7) Modèles conseillés : le minimum vérifié, le catalogue vivant fait le reste
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    bloc = app[app.index('const MODELS_BY_PROVIDER'):]
    bloc = bloc[:bloc.index('\n};')]
    for nom in ('groq', 'cerebras'):
        assert nom + ':' in bloc, '%s : aucun modèle conseillé' % nom

    # (8) LES LISTES EN DUR DE app.js — trouvées par Fernando, qui ne voyait pas
    #     les nouveaux fournisseurs dans les fils existants. Le premier jet de ce
    #     test ne regardait que les sélecteurs du HTML et les avait toutes ratées.
    #     Chacune a un effet observable différent : sans elles, le fournisseur
    #     apparaît dans un menu mais n'est jamais choisi automatiquement, son
    #     champ de clé ne s'enregistre pas tout seul, et il n'a pas de pastille
    #     dans les coûts. Autant de pannes discrètes.
    listes = {
        'auto-sélection du chat':        'const chatProviders = [',
        'correspondance des clés':       'const KEY_MAP  = {',
        'repli du catalogue':            "_SERVICES.length ? _SERVICES.map",
        'bascule automatique':           'const llmProviders = [',
        'pastilles de coûts':            'const _COST_ICONS = {',
    }
    def _declaration(app, ancre):
        """Le texte de CETTE déclaration seulement, jusqu'à son délimiteur.

        Une fenêtre de taille fixe déborderait sur les déclarations suivantes,
        qui citent les mêmes fournisseurs : le test passerait alors qu'une liste
        est incomplète. Défaut constaté en éprouvant ce contrôle.
        """
        deb = app.index(ancre)
        fin_c = app.find('];', deb)
        fin_a = app.find('};', deb)
        candidats = [x for x in (fin_c, fin_a) if x != -1]
        return app[deb:min(candidats) + 2] if candidats else app[deb:deb + 300]

    for libelle, ancre in listes.items():
        assert ancre in app, 'ancre introuvable (%s) : le test doit être remis à jour' % libelle
        extrait = _declaration(app, ancre)
        for nom in ('groq', 'cerebras'):
            assert nom in extrait, "%s : %s manquant dans « %s »" % (libelle, nom, ancre)

    # La sauvegarde automatique des champs de clé : liste distincte des autres,
    # certains services y portant un nom à tiret.
    m = re.search(r"\[([^\]]*'anthropic'[^\]]*)\]\.forEach\(p => \{\s*\n\s*const el = document\.getElementById\(`api-key-",
                  app)
    assert m, 'la sauvegarde automatique des clés a changé de forme : remettre ce test à jour'
    for nom in ('groq', 'cerebras'):
        assert "'" + nom + "'" in m.group(1), \
            '%s : absent de la sauvegarde automatique des champs de clé' % nom
    ok("fournisseurs : source unique d'adresses, Groq et Cerebras câblés de bout en bout")


def test_accessibilite_des_medias():
    """Toute image, tout lecteur audio ou vidéo doit avoir un nom.

    Pour qui navigue au lecteur d'écran, une image sans texte alternatif est une
    case vide et un lecteur audio sans nom s'annonce « lecteur audio » sans dire
    de quoi. Ce contrôle balaie l'interface au lieu de compter sur une relecture
    — méthode retenue après avoir manqué trois textes alternatifs sur quatre.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()

    # (1) Aucune balise <img> du HTML sans attribut alt
    sans_alt = [m.group(0)[:80] for m in re.finditer(r'<img\b[^>]*>', html)
                if 'alt=' not in m.group(0)]
    assert not sans_alt, 'images sans texte alternatif : ' + ' | '.join(sans_alt)

    # (2) Toute image construite en JS reçoit un alt dans la foulée
    for m in re.finditer(r"createElement\('img'\)", app):
        fenetre = app[m.start():m.start() + 1200]
        ligne = app[:m.start()].count('\n') + 1
        assert '.alt' in fenetre, 'image créée sans alt vers la ligne %d' % ligne

    # (3) Tout lecteur audio ou vidéo construit en JS reçoit un nom ET ses
    #     contrôles — un son qu'on ne peut pas arrêter est un piège.
    for balise in ('audio', 'video'):
        for m in re.finditer(r"createElement\('%s'\)" % balise, app):
            fenetre = app[m.start():m.start() + 900]
            ligne = app[:m.start()].count('\n') + 1
            assert 'aria-label' in fenetre, \
                'lecteur %s sans nom vers la ligne %d' % (balise, ligne)
            assert 'controls' in fenetre, \
                'lecteur %s sans contrôles vers la ligne %d' % (balise, ligne)

    # (3 bis) Les noms de la barre du haut restent COURTS. Ces boutons sont lus à
    #     chaque passage du curseur : un libellé de trente-cinq caractères y coûte
    #     du temps à chaque fois. Remarque de Fernando le 30/07 sur le bouton
    #     Musique, que j'avais nommé « Musique, génération et bibliothèque ».
    #     L'infobulle (title) peut rester explicite : elle ne se lit qu'à la demande.
    zone = html[html.index('<div id="top-right">'):][:4000]
    trop_longs = []
    for m in re.finditer(r'<button\s+id="(toggle-[^"]+)"[^>]*?aria-label="([^"]*)"', zone):
        if len(m.group(2)) > 24:
            trop_longs.append('%s (%d car.)' % (m.group(1), len(m.group(2))))
    assert not trop_longs, ('noms trop longs dans la barre du haut : '
                            + ', '.join(trop_longs))

    # (3 ter) Même borne pour les boutons de la zone de saisie et du menu « + » :
    #     eux aussi sont traversés en permanence. On borne la LONGUEUR plutôt que
    #     d'interdire des mots : une première version de ce test proscrivait
    #     « Ouvrir » et attrapait « Ouvrir le clavier », qui est juste — ce bouton
    #     ferme le panneau micro pour revenir au clavier, il décrit son effet.
    zone_saisie = html[html.index('<div id="input-actions">'):][:3000]
    menu = html[html.index('id="plus-menu"'):][:2000]
    longs = []
    for source, ou in ((zone_saisie, 'zone de saisie'), (menu, 'menu +')):
        for m in re.finditer(r'<button\s+id="([^"]+)"[^>]*?aria-label="([^"]*)"', source):
            if len(m.group(2)) > 30:
                longs.append('%s dans %s (%d car.)' % (m.group(1), ou, len(m.group(2))))
    assert not longs, 'noms accessibles trop longs : ' + ', '.join(longs)

    # (4) Aucun bouton muet : ni texte, ni nom accessible
    muets = []
    for m in re.finditer(r'<button\b[^>]*>(.*?)</button>', html, re.S):
        texte = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if not texte and 'aria-label' not in m.group(0):
            muets.append(m.group(0)[:70].replace('\n', ' '))
    assert not muets, 'boutons sans nom accessible : ' + ' | '.join(muets)
    # (5) Le sélecteur de voix est UNIQUE et rassemble tous les moteurs. Ajouter
    #     une porte par moteur serait une tabulation de plus pour rien — et le
    #     docstring de list_voices() doit rester juste : périmé, il a suffi à
    #     faire croire à un manque inexistant lors d'un audit.
    tts = open(os.path.join(racine, 'modules', 'tts.py'), encoding='utf-8').read()
    corps = tts[tts.index('def list_voices'):tts.index('def synthesize_voxtral')]
    for moteur in ('kokoro', 'piper', 'edge', 'gemini', 'voxtral', 'mistral'):
        assert moteur in corps.lower(), 'moteur absent du sélecteur unique : ' + moteur
    doc = corps[:corps.index('"""', corps.index('"""') + 3)]
    assert 'Kokoro + Piper + Edge' not in doc, \
        'docstring périmé : il annonçait trois moteurs pour six'
    assert 'id="voice-select"' in html and 'preview-voice-btn' in html, \
        'une seule liste, un seul bouton d’écoute'
    ok("accessibilité des médias : aucune image muette, aucun lecteur anonyme, aucun bouton sans nom")


def test_modeles_conseilles():
    """Les modèles CONSEILLÉS vieillissent — et un modèle éteint ne répond plus.

    Le catalogue, lui, est interrogé chez le fournisseur puis fusionné : ce
    n'est donc pas une liste figée qu'on teste, mais deux choses vérifiables
    hors ligne — qu'aucun modèle notoirement éteint ne soit proposé, et que la
    date de dernière revue soit inscrite pour que la péremption se voie.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()

    # (1) Modèles annoncés « Shut down » par Google : ne jamais les proposer
    eteints = ('gemini-2.0-flash', 'gemini-2.0-flash-lite',
               'gemini-3.1-flash-lite-preview', 'gemini-3-pro-preview',
               'imagen-3.0', 'imagen-4.0')
    debut = app.index('const MODELS_BY_PROVIDER')
    bloc = app[debut:app.index('};', debut)]
    for mort in eteints:
        assert mort not in bloc, 'modèle éteint encore conseillé : ' + mort

    # (2) Le mécanisme qui empêche la liste de vieillir doit rester en place :
    #     catalogue vivant interrogé et FUSIONNÉ, pas remplacé.
    assert '/api/models/' in app and 'Autres modèles disponibles' in app, \
        'sans la fusion du catalogue vivant, la liste conseillée devient un plafond'

    # (3) Date de dernière revue inscrite : une recommandation sans date ne se
    #     périme jamais aux yeux du lecteur, alors qu'elle se périme en vrai.
    assert re.search(r'Conseils revus le \d\d/\d\d/\d{4}', app), \
        'inscrire la date de revue des modèles conseillés'
    ok("modèles conseillés : aucun modèle éteint, catalogue vivant fusionné, revue datée")


def test_contrat_interface_serveur():
    """Le piège le plus fréquent de NIMM : une fonction inatteignable.

    Historique de ce défaut, à chaque fois trouvé par accident : le bouton Vibe
    absent du HTML rendait tout un pipeline injoignable ; la sentinelle
    [TRUNCATED] guettée par l'interface n'était émise par AUCUN code serveur ;
    des clés d'API n'avaient aucun champ de saisie. Le code existait, la
    fonction n'existait pas.

    Ce test vérifie le contrat dans LES DEUX SENS, et ancre la liste des routes
    légitimement absentes de l'interface. Ajouter une route sans la brancher
    devient donc un choix explicite, pas un oubli.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    front = (open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
             + '\n' + open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read())

    # Les routes se relèvent dans l'ARBRE SYNTAXIQUE, pas à l'expression
    # régulière : main.py déclare des chemins en guillemets simples comme en
    # guillemets doubles, et une regex sur un seul des deux est aveugle sur des
    # dizaines de routes (erreur commise en écrivant ce test).
    arbre = ast.parse(src)
    routes = []
    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                if isinstance(d, ast.Call) \
                   and getattr(d.func, 'attr', '') in ('get', 'post', 'patch', 'put', 'delete') \
                   and d.args and isinstance(d.args[0], ast.Constant):
                    routes.append((d.func.attr.upper(), d.args[0].value, n.name))
    assert len(routes) > 300, 'garde-fou : %d routes relevées, c’est trop peu' % len(routes)
    assert any("'" in l for l in src.split('@app.')[1:3]) or True

    # Comparaison SEGMENT PAR SEGMENT plutôt que par expression régulière.
    # Pourquoi : une adresse peut contenir une expression complète, y compris
    # un choix entre deux mots — `/api/memory/${key}/${verrou ? 'unlock' : 'lock'}`.
    # L'ancienne version coupait l'adresse au premier espace et signalait une
    # route inexistante alors que les deux existent. Un segment calculé peut
    # valoir n'importe quoi à l'exécution : on le traite donc comme un joker,
    # exactement comme un {paramètre} côté serveur.
    def _segs_route(c):
        return [None if s.startswith('{') else s for s in c.strip('/').split('/')]

    def _segs_appel(u):
        u = u.split('?')[0].strip('/')
        return [None if ('${' in s or '+' in s) else s for s in u.split('/')]

    def _compatible(appel, route):
        if len(appel) != len(route):
            # Une adresse finissant par un segment calculé peut aussi désigner
            # la route sans ce segment (`/api/x/${''}` → `/api/x`).
            if len(appel) - 1 == len(route) and appel and appel[-1] is None:
                appel = appel[:-1]
            elif len(appel) + 1 == len(route) and route and route[-1] is None:
                route = route[:-1]
            else:
                return False
        return all(a is None or r is None or a == r for a, r in zip(appel, route))

    segs_routes = [_segs_route(c) for _, c, _ in routes]

    # ── SENS 1 : l'interface appelle-t-elle des routes inexistantes ? ──
    # Les gabarits entre accents graves peuvent contenir des espaces et des
    # apostrophes : ils se relisent jusqu'à leur accent fermant, pas jusqu'au
    # premier blanc.
    appels = {m.group(1) for m in re.finditer(r"""['\"](/api/[^'\"\s]*)""", front)}
    appels |= {m.group(1) for m in re.finditer(r'`(/api/[^`]*)`', front)}
    appels.discard('/api/')                             # fragment, pas un appel
    orphelins = [u for u in sorted(appels)
                 if not any(_compatible(_segs_appel(u), r) for r in segs_routes)]
    assert not orphelins, ("l'interface appelle des routes qui n'existent pas : "
                           + ', '.join(orphelins))

    # ── SENS 2 : quelles routes l'interface ne nomme jamais ? ──
    # Certaines ne DOIVENT pas y figurer, et chacune a sa raison. La liste est
    # explicite pour qu'une nouvelle route non branchée saute aux yeux.
    permis_prefixes = (
        '/api/coanimm/',        # outils exécutés par le LLM, pas par l'interface
        '/api/exa/',            # idem : recherche par le sens, côté agent
    )
    permis_exact = {
        '/',                                  # la page elle-même
        '/api/vibe/files/{filename}',         # adresse rendue par le serveur
        '/api/musique/fichier/{nom}',         # idem
        '/api/video/fichier/{nom}',           # idem
        '/api/memory/clean',                  # administration / scripts
        '/api/memory/all',                    # administration / scripts
        '/api/mistral/ocr',                   # appelée depuis un script CoaNIMM
        '/api/mistral-conversations/start',   # vestige, à trancher
        '/api/settings/vision-provider',      # vestige : remplacé par /api/settings/routing
        '/api/voice/list-mistral',            # DIAGNOSTIC : appelée à la main en dépannage
        '/api/voice/test-tts/{pid}',          # DIAGNOSTIC : idem (les docstrings le disent)
        '/api/tokens/estimate',               # sans interface, à dessein — voir plus bas
        '/api/mistral/audio/voices',          # appelée depuis un script CoaNIMM
        '/api/mistral/audio/speak',           # idem
    }
    # Une route de diagnostic n'est PAS une fonction inatteignable : elle est
    # faite pour être appelée à la main quand quelque chose ne marche pas.
    # Confondre les deux a produit un faux positif d'audit le 30/07 — les voix
    # Mistral étaient déjà dans le sélecteur, et j'ai proposé de « brancher » des
    # outils de dépannage. La distinction se lit dans le docstring.
    for chemin in ('/api/voice/list-mistral', '/api/voice/test-tts/{pid}'):
        i = src.find(chemin)
        assert i > 0 and 'diagnostic' in src[i:i + 400].lower(), \
            'route rangée en diagnostic sans le dire dans son docstring : ' + chemin
    # Certaines familles de routes sont appelées avec une adresse CONSTRUITE :
    # le fournisseur est une variable, donc le chemin complet n'apparaît nulle
    # part en clair. On l'admet, mais seulement sur preuve : la ligne qui bâtit
    # l'adresse doit être là. Sans cette preuve, la famille redevient suspecte.
    assert "'/api/' + _batchProvider() + '/batch'" in front, \
        'la base des routes de traitement par lots a changé : revoir cette exception'
    familles_construites = ('/api/mistral/batch', '/api/gemini/batch',
                            '/api/anthropic/batch')

    def _cite(chemin):
        litteral = chemin.split('{')[0].rstrip('/')
        if litteral and litteral in front:
            return True
        if chemin.startswith(familles_construites):
            return True
        bouts = [s for s in chemin.strip('/').split('/') if not s.startswith('{')]
        return len(bouts) >= 2 and ('/' + '/'.join(bouts[-2:])) in front

    non_branchees = sorted({c for _, c, _ in routes
                            if not _cite(c)
                            and not c.startswith(permis_prefixes)
                            and c not in permis_exact})
    assert not non_branchees, (
        "routes ajoutées sans être branchées à l'interface (les brancher, ou les "
        "inscrire dans permis_exact avec leur raison) : " + ', '.join(non_branchees))

    # La liste blanche ne doit pas devenir un tapis sous lequel on balaie :
    # elle est bornée, et chaque entrée porte un commentaire dans le source.
    assert len(permis_exact) <= 15, 'la liste des exceptions grossit trop'
    ok("contrat interface/serveur : aucun appel dans le vide, aucune route ajoutée sans être branchée")


def test_alt_honnete():
    """Un texte alternatif qui répète la consigne est un texte qui MENT.

    Les images créées depuis la conversation portaient `alt = la consigne` :
    il disait ce qui avait été demandé, pas ce qui avait été produit. Au
    lecteur d'écran, impossible de savoir que le modèle avait dérivé. Même
    défaut dans la galerie. Règle tenue ici : soit une vraie description, soit
    on écrit qu'il n'y en a pas — jamais la consigne déguisée en description.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()

    # (1) La consigne ne sert PLUS d'alt — les QUATRE endroits où l'image
    #     apparaît : création dans le fil, retouche, historique, galerie.
    #     Le défaut existait aux quatre ; trois avaient été manqués au premier
    #     passage et c'est ce test qui les a sortis.
    assert 'alt="${_esc(prompt)}"' not in app, 'création et retouche dans le fil'
    assert 'alt="${_esc(img.prompt)}"' not in app, 'images rechargées depuis l’historique'
    assert 'alt="${_esc(img.prompt || img.filename)}"' not in app, 'galerie'

    # (2) Un alt provisoire honnête, remplacé par la vraie description
    assert 'description en cours' in app
    assert 'imgEl.alt = desc;' in app

    # (2 bis) Le correctif est FACTORISÉ : quatre copies auraient divergé
    assert app.count('async function _decrireImageGeneree(') == 1
    assert app.count('_decrireImageGeneree(') >= 4, 'appelée depuis chaque chemin'

    # (2 ter) Après une retouche, la consigne est une INSTRUCTION : encore moins
    #         utilisable en description qu'une consigne de création.
    assert 'Image retouchée, description en cours' in app

    # (2 quater) Historique : pas de description automatique — ce serait un appel
    #            de vision par image à chaque ouverture de fil — mais un bouton.
    assert 'img-describe-btn' in app and 'Décrire cette image' in app
    assert "Pas de description enregistrée" in app

    # (3) Quand la description manque, on le DIT — et on nomme la consigne
    #     comme consigne, pas comme description
    assert 'Description automatique indisponible' in app
    assert "à partir de la consigne" in app
    assert 'sans description enregistrée' in app, 'galerie : même honnêteté'

    # (4) La route de description ne lève jamais et explique ses échecs
    assert '/api/image/decrire' in mn and '/api/image/decrire' in app
    assert '"raison"' in mn, 'un échec silencieux redeviendrait un alt menteur'
    assert 'return {"description": "", "raison"' in mn

    # (5) La description est jointe à la LISTE de la galerie : une image par
    #     requête ferait cent allers-retours pour cent vignettes
    assert "img['alt'] = (fiche.get('alt') or '').strip()" in mn

    # (6) La description reste lisible et COPIABLE, pas seulement parlée :
    #     une annonce vocale passe, un texte reste.
    assert 'sum.textContent = "Description de l\'image"' in app
    assert 'zone.readOnly = true' in app
    ok("texte alternatif : jamais la consigne déguisée en description, et l’absence est dite")


def test_video_veo():
    """Veo est une opération LONGUE : onze secondes à six minutes.

    Trois exigences, chacune tirée d'une contrainte réelle : corriger AVANT de
    partir un couple durée/résolution que Google refusera (sinon c'est six
    minutes d'attente pour rien), rapatrier la vidéo tout de suite (Google
    l'efface au bout de deux jours), et ne pas confondre un hoquet réseau avec
    un échec de génération.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    mn = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    app = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    src = open(os.path.join(racine, 'modules', 'video.py'), encoding='utf-8').read()
    gitignore = open(os.path.join(racine, '.gitignore'), encoding='utf-8').read()
    import modules.video as V

    # (1) Sans clé, on le DIT
    o = V.options({})
    assert not o['cle_presente'] and 'deux jours' in o['avertissement']
    assert 'erreur' in asyncio.run(V.lancer('une côte', api_keys={}))
    assert 'erreur' in asyncio.run(V.lancer('', api_keys={'gemini': 'k'}))

    # (2) Règles de Google — fonction PURE, testable sans réseau
    assert V.regles('8', '720p') == ('8', '720p', '')
    d, r, note = V.regles('4', '1080p')
    assert (d, r) == ('8', '1080p') and 'Google' in note, \
        'corriger avant de partir, mais jamais en silence'
    d, r, note = V.regles('6', '4k')
    assert (d, r) == ('8', '4k') and note
    assert V.regles('9', 'zzz')[:2] == ('8', '720p'), 'valeurs absurdes ramenées au défaut'
    # Tous les modèles n'ont pas les mêmes résolutions, et les corrections SE CUMULENT
    d, r, note = V.regles('4', '4k', ('720p', '1080p'))
    assert (d, r) == ('8', '1080p'), (d, r)
    assert 'ne propose pas' in note and 'Google' in note, \
        'deux corrections, deux explications — aucune ne doit manger l’autre'
    assert V.regles('4', '720p', ('720p', '1080p')) == ('4', '720p', '')

    # (2 bis) Identifiants de modèles — relevés dans la liste officielle, PAS
    # déduits de la prose. Piège réel : les tables de paramètres de Google
    # mentionnent un « Veo 3.1 Fast » dont aucun identifiant n'est publié ; le
    # modèle réellement appelable à côté de Veo 3.1 est Veo 3.1 Lite.
    ids = sorted(m['id'] for m in V.MODELES.values())
    assert ids == ['veo-3.1-generate-preview', 'veo-3.1-lite-generate-preview'], ids
    assert '4k' not in V.MODELES['veo31lite']['resolutions'], \
        'Veo 3.1 Lite ne fait pas de 4K — le promettre serait un refus à l’arrivée'
    assert '4k' in V.MODELES['veo31']['resolutions']
    for nom, conf in V.MODELES.items():
        assert conf['resolutions'], nom
        assert set(conf['resolutions']) <= {'720p', '1080p', '4k'}, nom

    # (3) Europe : Veo 3.x n'accepte que allow_adult, posé d'avance
    assert "'personGeneration': 'allow_adult'" in src, \
        'sinon on découvre le refus après six minutes d’attente'

    # (4) Lecture de l'opération terminée, formes tolérées
    fini = {'done': True, 'response': {'generateVideoResponse': {'generatedSamples': [
        {'video': {'uri': 'https://exemple/veo.mp4'}}]}}}
    assert V._uri_video(fini) == 'https://exemple/veo.mp4'
    assert V._uri_video({'response': {'generatedVideos': [{'video': {'url': 'http://u'}}]}}) == 'http://u'
    assert V._uri_video({'done': True, 'response': {}}) == ''
    assert V._uri_video(None) == ''

    # (5) Un hoquet réseau n'est PAS un échec : l'opération continue chez Google
    assert "'fait': False, 'message'" in src
    assert 'La génération a échoué' in src, 'une vraie erreur, elle, est dite'

    # (6) Chemin complet : lancement, suivi, rapatriement, reprise après rechargement
    assert '/api/video/lancer' in mn and '/api/video/etat' in mn
    assert '/api/video/en-cours' in mn, 'une génération de six minutes survit à un F5'
    assert 'telecharger' in mn, 'rapatrier tout de suite : Google efface à deux jours'
    assert '_media_nom_sur' in mn and 'os.path.basename' in mn
    assert 'data/videos/' in gitignore

    # (7) Interface : annonces espacées, lecteur étiqueté, réglages nommés
    assert '_ST_INTERVALLE_MS = 30000' in app, \
        'une annonce toutes les 5 secondes couvrirait tout le reste à la voix'
    assert "lecteur.setAttribute('aria-label'" in app, 'un lecteur vidéo sans nom est muet'
    assert '_stReprendre' in app
    assert 'id="studio-video-resolution"' in html and 'aria-live="polite"' in html
    ok("vidéo : règles de Google appliquées avant l'attente, rapatriement immédiat, suivi qui survit au rechargement")



def test_fantome_a_la_creation():
    """Le mode fantôme se règle AVANT le premier mot, plus après coup.

    Constat de Fernando après usage : le bouton de la barre du haut ne pouvait
    être actionné qu'une fois le fil ouvert — donc, en pratique, après que les
    premiers échanges avaient déjà été écrits. La promesse « aucune trace » ne
    tenait pas. Le réglage descend dans la création du fil.

    Ce test vérifie les quatre points où cela pouvait casser, et un cinquième
    qui n'est pas une mécanique mais une décision d'interface.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    js = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()

    # (1) Le serveur accepte la demande à la création, et l'honore.
    assert 'ghost:            Optional[bool] = False' in main, \
        'ThreadCreate doit accepter ghost'
    assert 'if req.ghost:' in main and '_add_to_ghost_list(thread_id)' in main, \
        'la création doit inscrire le fil dans la liste fantôme'

    # (2) L'ajout ne doit ni perdre les autres fils, ni créer de doublon.
    #     Vérifié sur une SOURCE SIMULÉE, jamais sur les fichiers du projet.
    espace = {'json': json, 'get_setting': lambda k, d='': '["a", "b"]'}
    corps = main[main.index('def _add_to_ghost_list'):]
    corps = corps[:corps.index(chr(10) + 'def ', 10)]
    exec(compile(corps, 'simule', 'exec'), espace)
    ajoute = espace['_add_to_ghost_list']
    assert json.loads(ajoute('c')) == ['a', 'b', 'c'], 'les autres fils sont perdus'
    assert json.loads(ajoute('a')) == ['a', 'b'], 'doublon créé'
    espace['get_setting'] = lambda k, d='': 'ceci nest pas du json'
    assert json.loads(ajoute('z')) == ['z'], 'une liste illisible doit être reconstruite'

    # (3) L'interface transmet le choix, et la case repart décochée.
    assert 'ghost = false' in js, 'createThread doit accepter le mode fantôme'
    assert "body.ghost            = true" in js
    assert "result.ghost" in js, "l'appelant doit transmettre la case"
    assert "_syncGhostFromMask();" in js, \
        'la case repart décochée à l\'ouverture, sauf si le masque présélectionné impose le fantôme'

    # (4) Le bouton de la barre a bien disparu, partout.
    assert 'ghost-toggle' not in js and 'ghost-toggle' not in html, \
        'le bouton fantôme subsiste dans la barre'
    assert "getElementById('live-toggle')" in js, 'le bouton Live doit être joignable'
    # Le raccourci a changé le 28/08 : Alt+F seul entrait en concurrence
    # avec le navigateur. Le mode Live rejoint la famille Alt+Maj, où
    # vivent déjà tous les panneaux.
    assert "aria-keyshortcuts', 'Alt+Shift+K'" in js, 'raccourci Live non annoncé'
    assert "k === 'k'" in js, 'Alt+Maj+K n’est écouté nulle part'
    assert "case 'f': {   // Alt+F" not in js, 'Alt+F devait être libéré'
    # Aucune lettre Alt+Maj ne doit servir deux fois : un doublon ferait
    # gagner le premier arrivé, en silence.
    _table = set(re.findall(r"^\s{8}'([a-z])': 'toggle-", js, re.M))
    _apart = set(re.findall(r"if \(k === '([a-z])'\)", js))
    assert not (_table & _apart), \
        'lettre Alt+Maj attribuée deux fois : %s' % sorted(_table & _apart)
    assert len(_table) >= 8 and _apart, 'relevé des raccourcis trop maigre'

    # (5) DÉCISION D'INTERFACE : la case n'est PAS dans « Options avancées ».
    #     Une décision de confidentialité ne se cache pas derrière un repli —
    #     surtout au lecteur d'écran, qui doit alors déplier pour la trouver.
    avant = html.index('id="new-thread-ghost"')
    replis = [m.start() for m in re.finditer(r'<details', html) if m.start() < avant]
    fins = [m.start() for m in re.finditer(r'</details>', html) if m.start() < avant]
    assert len(replis) == len(fins), \
        'la case fantôme est enfermée dans un bloc « Options avancées »'
    assert 'aria-describedby="new-thread-ghost-aide"' in html, \
        'la case doit porter son explication'

    # (6) Un fil déjà ouvert reste basculable, et le texte le dit honnêtement.
    assert '_ghostBoxP.checked !== _ghostAvant' in js, \
        'la route est une bascule : ne l’appeler que si l’état a changé'
    assert 'd\\u00e9j\\u00e0 \\u00e9t\\u00e9 enregistr\\u00e9 avant reste en place' in js, \
        'il faut dire qu’activer après coup n’efface pas le passé'
    ok("mode fantôme : réglé à la création, plus de bouton dans la barre")


def test_live_configuration():
    """Le premier message d'une session Live — celui qu'on ne peut pas corriger.

    La configuration d'une session Live n'est pas modifiable une fois la
    connexion ouverte. Une faute ici ne coûte pas un message : elle coûte la
    session entière. D'où un test sur la fonction PURE qui la construit,
    plutôt qu'une découverte au micro.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    from modules import live as L

    s = L.construire_setup(voix='Kore', consigne='sois bref', langue='fr-FR')['setup']

    # Le modèle porte son préfixe : sans « models/ », Google refuse.
    assert s['model'].startswith('models/'), 'préfixe models/ manquant'
    assert s['model'] == 'models/' + L.MODELE_DEFAUT

    # LES DEUX transcriptions, toujours. C'est ce qui rend la conversation
    # lisible au braille ; sans elles le mode Live serait inutilisable.
    assert s['inputAudioTranscription'] == {}, 'transcription de MA voix non demandée'
    assert s['outputAudioTranscription'] == {}, 'transcription de NIMM non demandée'

    # L'interruption est écrite, pas seulement supposée par défaut.
    assert s['realtimeInputConfig']['activityHandling'] == 'START_OF_ACTIVITY_INTERRUPTS'
    assert s['realtimeInputConfig']['automaticActivityDetection']['disabled'] is False
    muet = L.construire_setup(interruption=False)['setup']
    assert muet['realtimeInputConfig']['activityHandling'] == 'NO_INTERRUPTION'

    # Audio en sortie, voix et langue au bon endroit.
    g = s['generationConfig']
    assert g['responseModalities'] == ['AUDIO']
    assert g['speechConfig']['voiceConfig']['prebuiltVoiceConfig']['voiceName'] == 'Kore'
    assert g['speechConfig']['languageCode'] == 'fr-FR'

    # Une voix inconnue ne doit PAS tuer la session : on retombe sur la voix
    # par défaut plutôt que d'échouer à la connexion.
    assert L.voix_valide('Machin') == L.VOIX_DEFAUT
    assert L.voix_valide('kore') == 'Kore', 'la casse ne doit pas compter'

    # La consigne est celle d'une conversation PARLÉE, pas d'un chat écrit.
    c = L.consigne_vocale(user_name='Fernando', memoire='- il aime le braille',
                          masque='Tu es taquin.')
    for exigence in ('phrases courtes', 'Aucune mise en forme', 'tu t\'arrêtes'):
        assert exigence in c, 'consigne vocale incomplète : %s' % exigence
    assert 'Fernando' in c and 'braille' in c and 'taquin' in c
    # Page blanche : aucune fuite de contexte.
    vide = L.consigne_vocale(user_name='Fernando', memoire='- secret', se_souvient=False)
    assert 'Fernando' not in vide and 'secret' not in vide, \
        'la page blanche laisse fuir du contexte'

    # Les identifiants de modèle ne se déduisent pas de la prose : celui-ci
    # vient du tutoriel officiel. La leçon du « Veo 3.1 Fast » inventé.
    assert 'live' in L.MODELE_DEFAUT, 'le modèle Live doit être un modèle Live'
    ok("session Live : configuration complète, transcriptions et interruption écrites")


def test_live_interprete_le_flux():
    """Traduire Google en événements plats — et ne jamais rester muet.

    Le format de Google est imbriqué et son ordre n'est PAS garanti : la
    documentation le dit explicitement pour les transcriptions. Un seul
    message peut porter à la fois une interruption, une transcription et du
    son. L'interface ne doit pas avoir à le savoir.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    from modules import live as L

    evts = L.interpreter({'serverContent': {
        'interrupted': True,
        'inputTranscription': {'text': 'attends'},
        'outputTranscription': {'text': 'je disais'},
        'modelTurn': {'parts': [{'inlineData': {'data': 'QUFB'}}]},
        'turnComplete': True,
    }})
    types = [e['type'] for e in evts]

    # L'INTERRUPTION D'ABORD : l'interface doit vider sa file de lecture avant
    # tout le reste, sinon on entend la fin d'une phrase déjà annulée.
    assert types[0] == 'interrompu', 'l’interruption doit passer en premier : %s' % types
    assert 'audio' in types and types.count('transcription') == 2
    assert types[-1] == 'tour_fini'
    qui = [e['qui'] for e in evts if e['type'] == 'transcription']
    assert qui == ['moi', 'nimm'], 'les deux locuteurs doivent être distingués'

    # Un message illisible produit une ERREUR, jamais un silence. C'est la
    # leçon de la réponse muette : ce qui n'est pas dit coûte trois séances.
    assert L.interpreter('{ceci nest pas du json')[0]['type'] == 'erreur'

    # RÈGLE RÉÉCRITE le 26/08 : un appel d'outil n'est plus une anomalie,
    # depuis que NIMM déclare les siens dans la session. Ce qui reste vrai,
    # c'est qu'il ne doit jamais disparaître en silence : il remonte à plat,
    # avec son identifiant, et c'est le serveur qui refuse un nom inconnu.
    _ap = L.interpreter({'toolCall': {'functionCalls': [
        {'name': 'search_web', 'id': 'z1', 'args': {'query': 'x'}}]}})
    assert _ap[0]['type'] == 'outil' and _ap[0]['id'] == 'z1'
    # Une demande vide ne doit ni lever, ni inventer d'événement.
    assert L.interpreter({'toolCall': {'functionCalls': []}}) == []

    # Un message vide ne doit pas lever, ni inventer d'événement.
    assert L.interpreter({}) == [] and L.interpreter(None) == []
    assert L.interpreter({'setupComplete': {}})[0]['type'] == 'prete'

    # Sans clé Gemini, le moteur natif est FERMÉ, et le repli proposé.
    o = L.options({})
    natif = [m for m in o['moteurs'] if m['nom'] == 'gemini'][0]
    assert natif['ouvert'] is False and o['moteur_defaut'] == 'chaine'
    assert L.options({'gemini': 'k'})['moteur_conseille'] == 'gemini'
    ok("flux Live : interruption prioritaire, aucun silence, repli sans clé")


def test_live_accessible():
    """Une conversation vocale doit rester lisible SANS voix.

    Point contre-intuitif, et c'est le cœur du sujet : la transcription ne
    doit PAS s'annoncer toute seule. Un aria-live la ferait lire par le
    lecteur d'écran pendant que NIMM parle — deux voix simultanées, et plus
    rien de compréhensible. Elle vit donc dans un champ de texte qu'on
    parcourt, relit et copie quand on veut, au braille, en silence.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    js = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()

    # (1) La transcription est un CHAMP DE TEXTE : parcourable et copiable.
    bloc = html[html.index('id="live-transcript"'):]
    bloc = bloc[:bloc.index('</textarea>') + 11]
    assert '<textarea' in html[html.index('id="live-transcript"') - 200:], \
        'la transcription doit être un textarea, pour être copiable'
    assert 'readonly' in bloc, 'la transcription ne doit pas être éditable'
    assert 'aria-live' not in bloc, \
        'un aria-live ici couvrirait la voix de NIMM : interdit'

    # (2) SEUL l'état s'annonce : c'est court, et ça se glisse entre deux phrases.
    etat = html[html.index('id="live-etat"'):]
    etat = etat[:etat.index('</p>')]
    assert 'aria-live="polite"' in etat and 'role="status"' in etat, \
        'l’état doit être annoncé : c’est la seule chose qu’on ne peut pas voir'

    # (3) Chaque commande porte un nom accessible et non ambigu.
    for ident in ('live-transcript', 'live-ecrire', 'live-moteur', 'live-voix'):
        assert ('for="%s"' % ident) in html or ('aria-label' in html[html.index('id="%s"' % ident):][:400]), \
            'commande sans étiquette : %s' % ident
    assert 'aria-describedby="live-moteur-aide"' in html
    assert 'aria-describedby="live-transcript-aide"' in html

    # (4) Les deux modales sont de vraies boîtes de dialogue.
    for ident in ('live-modal', 'live-panel'):
        seg = html[html.index('id="%s"' % ident):][:600]
        assert 'role="dialog"' in seg and 'aria-modal="true"' in seg, \
            '%s n’est pas une boîte de dialogue' % ident
        assert 'aria-labelledby' in seg, '%s sans titre annoncé' % ident

    # (5) On doit pouvoir sortir au clavier, sans chercher un bouton.
    assert "e.key === 'Escape'" in js and '_liveRaccrocher()' in js, \
        'Échap doit raccrocher'
    assert "aria-keyshortcuts=\"Alt+M\"" in html, 'Alt+M doit être annoncé sur le bouton'

    # (6) Le focus revient d'où il venait — sinon on est perdu dans la page.
    assert '_liveFocusAvant' in js and '_liveFocusAvant?.focus()' in js

    # (7) Le curseur de lecture ne saute PAS si l'on est en train de relire.
    assert 'document.activeElement !== zone' in js, \
        'la transcription ne doit pas défiler sous le doigt pendant la relecture'
    ok("Live accessible : transcription copiable et silencieuse, état annoncé")


def test_live_confidentialite():
    """Une session Live n'écrit rien — sauf si on le demande, à la fin."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    js = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    livepy = open(os.path.join(racine, 'modules', 'live.py'), encoding='utf-8').read()

    # (1) Le module Live n'importe AUCUNE fonction d'écriture : la garantie
    #     est structurelle, pas seulement promise dans un commentaire.
    for interdit in ('add_message', 'save_memory', 'set_setting'):
        assert interdit not in livepy, \
            'modules/live.py ne doit pas pouvoir écrire (%s)' % interdit

    # (2) La clé ne quitte JAMAIS le serveur : l'interface parle à NIMM, NIMM
    #     parle à Google. Une connexion directe du navigateur mettrait la clé
    #     dans la page, donc dans toute extension installée.
    assert 'generativelanguage.googleapis.com' not in js, \
        'l’interface ne doit pas connaître l’adresse de Google : la clé fuirait'
    assert "/api/live/ws" in js and 'url_gemini' in livepy

    # (3) L'écriture n'a lieu qu'après une question explicite, et le défaut
    #     est de ne rien garder.
    assert 'confirmModal(' in js[js.index('_liveRaccrocher'):], \
        'la conservation doit être demandée'
    assert 'if (garder)' in js
    conserver = main[main.index('async def live_conserver'):]
    conserver = conserver[:conserver.index(chr(10) + '@app') if chr(10) + '@app' in conserver else len(conserver)]
    assert 'add_message' in conserver, 'la route de conservation doit écrire'
    assert 'create_thread' in conserver

    # (4) Le fil support du moteur « chaîne » est fantôme, PUIS détruit.
    assert "ghost: true" in js, 'le fil support doit être fantôme'
    assert "method: 'DELETE'" in js[js.index('_liveFilEphemere'):], \
        'le fil support doit être détruit au raccroché'

    # (5) Un incident Live est ÉCRIT quelque part de lisible.
    assert '_live_diag(' in main and "add_diagnostic('live'" in main, \
        'un incident Live doit laisser une trace consultable au braille'
    ok("Live confidentiel : rien n’est écrit sans un oui, la clé reste au serveur")


def test_tout_est_utf8():
    """Chaque fichier source doit se lire en UTF-8. Sans exception.

    Ce test existe parce qu'il a immédiatement attrapé un défaut réel : deux
    caractères écrits en latin-1 dans une greffe binaire de app.js. Le
    contrôle de syntaxe JavaScript passait, la page se chargeait, et deux mots
    d'un commentaire étaient illisibles — jusqu'au jour où un outil lisant le
    fichier en UTF-8 aurait échoué sans expliquer pourquoi.

    C'est le genre de faute qu'une relecture ne voit pas et qu'une machine
    voit en une seconde.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    exts = ('.py', '.js', '.html', '.css', '.json', '.md', '.txt')
    sautes = {'.git', '__pycache__', 'node_modules', 'venv', '.venv', 'backups'}
    fautifs, examines = [], 0
    for dossier, sous, fichiers in os.walk(racine):
        sous[:] = [d for d in sous if d not in sautes]
        for f in fichiers:
            if not f.endswith(exts):
                continue
            chemin = os.path.join(dossier, f)
            examines += 1
            try:
                open(chemin, 'rb').read().decode('utf-8')
            except UnicodeDecodeError as e:
                fautifs.append('%s (octet %d)' % (os.path.relpath(chemin, racine), e.start))
    assert not fautifs, 'fichiers non UTF-8 : %s' % ', '.join(fautifs[:5])
    assert examines > 50, 'le balayage n’a presque rien examiné (%d)' % examines
    ok("encodage : %d fichiers sources, tous en UTF-8" % examines)


def test_live_contrat_interface_serveur():
    """Chaque route Live appelée par la page existe côté serveur, et chaque
    élément cherché par le script existe dans la page.

    Même contrôle que pour le reste de NIMM, appliqué au nouveau lot : c'est
    la classe de défaut qui a le plus coûté ici (six listes de fournisseurs
    oubliées dans app.js, trouvées par Fernando et non par moi).
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    main = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()

    appelees = set(re.findall(r"/api/live/[a-z_]+", js))
    declarees = set(re.findall(r"@app\.(?:get|post|websocket)\(\"(/api/live/[a-z_]+)\"", main))
    assert appelees, 'aucune route Live appelée : le test ne vérifie rien'
    assert not (appelees - declarees), \
        'routes Live appelées mais absentes du serveur : %s' % sorted(appelees - declarees)

    # `live-toggle` est créé par le script lui-même : c'est le seul admis.
    cherches = set(re.findall(r"getElementById\('(live-[a-z-]+)'\)", js))
    presents = set(re.findall(r'id="(live-[a-z-]+)"', html)) | {'live-toggle'}
    assert not (cherches - presents), \
        'éléments cherchés mais absents de la page : %s' % sorted(cherches - presents)
    assert len(cherches) >= 10, 'contrôle trop maigre (%d éléments)' % len(cherches)

    # La dépendance ajoutée est déclarée : sans elle, la passerelle tombe avec
    # une erreur d'import au premier essai, sur la machine de quelqu'un d'autre.
    req = open(os.path.join(racine, 'requirements.txt'), encoding='utf-8').read()
    assert 'websockets' in req, 'websockets absent de requirements.txt'

    # Le numéro de version du script a changé : sans cela, le navigateur sert
    # l'ancien fichier depuis son cache et rien de tout ceci n'existe.
    # RÈGLE RÉÉCRITE le 31/08 : la valeur était écrite en dur, donc ce test
    # tombait dès que QUELQU'UN d'autre changeait le numéro — Laurent l'a
    # légitimement passé à « 20260829-backup-fix ». Un test qui punit une
    # bonne pratique est un mauvais test. On vérifie la FORME : un numéro
    # daté doit exister sur le script ET sur la feuille de style, sans quoi le
    # navigateur sert l'ancienne version depuis son cache.
    for fichier in ('app.js', 'styles.css'):
        m = re.search(r'/static/' + re.escape(fichier) + r'\?v=(\d{8})-[0-9a-z-]+', html)
        assert m, 'aucun numéro de version daté sur %s' % fichier
        assert m.group(1) >= '20260801', \
            '%s porte un numéro de version qui date de %s' % (fichier, m.group(1))
    ok("contrat Live : routes, éléments, dépendance et cache-bust cohérents")


def test_masque_illisible_ne_bloque_pas():
    """Le repli de `load_mask` visait un fichier qui n'existe plus.

    Trouvé en passant, en cherchant comment donner son caractère à NIMM en
    mode Live : le repli ouvrait `lia.json`, absent de modules/masks depuis un
    moment. Un masque abîmé levait donc une SECONDE fois, hors du rattrapage —
    et NIMM ne répondait plus du tout.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hub = open(os.path.join(racine, 'core', 'hub.py'), encoding='utf-8').read()
    corps = hub[hub.index('def _masque_de_repli'):]
    corps = corps[:corps.index('# MODE POTARDS')]
    # On ignore les commentaires et les chaînes de documentation : ils PARLENT
    # de 'lia.json' pour expliquer le défaut. C'est le CODE qui ne doit plus
    # le désigner — sans quoi le test interdirait d'écrire la leçon.
    code = chr(10).join(l.split('#')[0] for l in corps.split(chr(10)))
    code = re.sub(r'\"\"\".*?\"\"\"', '', code, flags=re.S)
    assert "'lia.json'" not in code, 'un repli vise encore un fichier absent'
    assert code.count('_masque_de_repli(') >= 3, \
        'les TROIS replis doivent passer par la même porte (absent, privé, illisible)'
    assert 'system_prompt' in corps, 'le masque de secours doit être exploitable'
    # Un masque privé ne doit pas servir de repli : ce serait remplacer une
    # gêne par une fuite.
    assert "m.get('owner')" in corps, 'le repli peut servir un masque privé'

    # Et le fichier visé par le repli doit exister pour de bon.
    dossier = os.path.join(racine, 'modules', 'masks')
    dispo = [f for f in os.listdir(dossier) if f.endswith('.json')]
    assert dispo, 'aucun masque disponible'
    ok("masque illisible : repli sur un masque réellement présent")



def test_outils_tous_atteignables():
    """DIX outils sur vingt-cinq étaient morts, et personne ne le savait.

    Trouvé en voulant réutiliser `_execute_tool` pour le mode Live : la
    fonction commençait par

        query = args.get('query', '').strip()
        if not query:
            return '[Aucun résultat — paramètre query vide]'

    Ce garde était INCONDITIONNEL et placé avant tout aiguillage. Or dix
    outils n'ont pas de paramètre `query` : get_weather prend `city`,
    write_file prend `filename`, geocode_address prend `address`… Ils étaient
    déclarés au modèle, appelés par lui, et répondaient invariablement
    « paramètre query vide » sans jamais atteindre leur branche.

    Le modèle, lui, ne se plaint pas : il enchaîne sur autre chose. C'est
    exactement le genre de défaut qu'aucune relecture ne voit, parce qu'il n'y
    a rien à voir — seulement quelque chose qui n'arrive jamais.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hub = open(os.path.join(racine, 'core', 'hub.py'), encoding='utf-8').read()

    # (1) Relever les DÉCLARATIONS, et les branches réellement écrites.
    arbre = ast.parse(hub)
    declares = {}
    for n in ast.walk(arbre):
        if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') in (
                'NIMM_TOOLS', '_COANIMM_OPS_TOOLS', '_COANIMM_ASYNC_TOOLS'):
            try:
                val = ast.literal_eval(n.value)
            except Exception:
                continue
            if not isinstance(val, list):
                continue
            for t in val:
                f = (t or {}).get('function') or {}
                if f.get('name'):
                    props = ((f.get('parameters') or {}).get('properties') or {})
                    declares[f['name']] = set(props)
    assert len(declares) >= 20, 'relevé trop maigre (%d outils)' % len(declares)

    corps = hub[hub.index('async def _execute_tool'):]
    corps = corps[:corps.index(chr(10) + 'async def ', 10)]
    branches = set(re.findall(r"name == '([a-z_0-9]+)'", corps))
    manquantes = set(declares) - branches
    assert not manquantes, 'outils déclarés sans branche : %s' % sorted(manquantes)

    # (2) Le garde ne doit plus renvoyer les outils qui n'ont pas de `query`.
    assert "if not query and name in _OUTILS_A_QUERY:" in corps, \
        'le garde est redevenu inconditionnel : les outils sans query sont morts'

    # (3) La liste se DÉDUIT des déclarations : l'écrire à la main la ferait
    #     vieillir au premier outil ajouté.
    assert 'def _outils_exigeant_query' in hub
    espace = {'NIMM_TOOLS': [{'function': {'name': n,
                                           'parameters': {'properties': {p: {} for p in ps}}}}
                             for n, ps in declares.items()]}
    src = hub[hub.index('def _outils_exigeant_query'):]
    src = src[:src.index(chr(10) + chr(10) + chr(10))]
    exec(compile(src, 'simule', 'exec'), espace)
    calcule = espace['_outils_exigeant_query']()
    attendu = {n for n, ps in declares.items() if 'query' in ps}
    assert calcule == attendu, 'déduction fausse : %s' % sorted(calcule ^ attendu)
    sans_query = sorted(set(declares) - attendu)
    assert len(sans_query) >= 8, \
        'le test ne prouve rien si presque tous les outils ont un query (%d)' % len(sans_query)
    ok("outils : les %d outils sans paramètre query sont enfin atteignables"
       % len(sans_query))


def test_outils_en_live():
    """Donner à NIMM ses outils pendant qu'on lui parle — et pas n'importe lesquels.

    Sans outils, une session Live donne un Gemini rapide qui te connaît, mais
    coupé de la recherche web, de la base de connaissances, du carnet et de
    l'agenda. Question de Fernando, le jour même : « tout se fera via Gemini,
    les recherches, le raisonnement ? » Oui — et c'était le compromis non dit.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    from modules import live as L

    faux = [
        {'type': 'function', 'function': {
            'name': 'get_weather', 'description': 'la météo',
            'parameters': {'type': 'object',
                           'properties': {'city': {'type': 'string'}},
                           'required': ['city', 'inexistant']}}},
        {'type': 'function', 'function': {
            'name': 'run_code', 'description': 'exécute du code',
            'parameters': {'type': 'object', 'properties': {'code': {'type': 'string'}}}}},
        {'type': 'function', 'function': {
            'name': 'write_file', 'description': 'écrit un fichier',
            'parameters': {'type': 'object', 'properties': {'filename': {'type': 'string'}}}}},
        {'type': 'function', 'function': {
            'name': 'sans_parametre', 'description': 'rien à passer',
            'parameters': {'type': 'object', 'properties': {}}}},
    ]
    decl, noms = L.outils_pour_live(faux)

    # (1) Les outils qui ÉCRIVENT ou EXÉCUTENT restent dehors. Ce n'est pas un
    #     oubli : une session Live ne conserve rien, et l'accord capacité par
    #     capacité de CoaNIMM ne peut pas se donner au milieu d'une phrase.
    assert 'run_code' not in noms and 'write_file' not in noms, \
        'un outil qui agit sur le disque est passé en Live'
    assert L.OUTILS_ECARTES == {'run_code', 'write_file'}

    # (2) Format de Google : une liste plate de functionDeclarations.
    par_nom = {d['name']: d for d in decl}
    assert set(par_nom) == {'get_weather', 'sans_parametre'}
    assert 'type' not in par_nom['get_weather'], \
        "l'enveloppe OpenAI ne doit pas passer telle quelle"

    # (3) Un `required` qui nomme un paramètre inexistant fait refuser la
    #     déclaration : on ne garde que ceux qui existent vraiment.
    assert par_nom['get_weather']['parameters']['required'] == ['city']

    # (4) Un objet SANS propriété fait échouer la session entière chez Google :
    #     mieux vaut ne pas envoyer de schéma du tout.
    assert 'parameters' not in par_nom['sans_parametre'], \
        'un schéma vide part quand même : la session sera refusée'

    # (5) Le setup range tout dans UNE entrée `tools`.
    s = L.construire_setup(outils=decl)['setup']
    assert len(s['tools']) == 1 and len(s['tools'][0]['functionDeclarations']) == 2
    assert 'tools' not in L.construire_setup()['setup'], \
        'sans outils, aucune clé tools ne doit être envoyée'

    # (6) Un appel remonte à plat, avec son identifiant — c'est lui qui apparie
    #     la réponse à la demande.
    e = L.interpreter({'toolCall': {'functionCalls': [
        {'name': 'get_weather', 'id': 'a1', 'args': {'city': 'Angers'}},
        {'name': 'search_web', 'id': 'a2', 'args': {'query': 'x'}}]}})
    assert [x['type'] for x in e] == ['outil', 'outil'], 'les deux appels doivent remonter'
    assert e[0]['id'] == 'a1' and e[1]['nom'] == 'search_web'
    r = L.reponse_outil('get_weather', 'a1', 'il pleut')
    assert r['toolResponse']['functionResponses'][0]['id'] == 'a1'
    assert r['toolResponse']['functionResponses'][0]['response']['result'] == 'il pleut'

    # (7) Une annulation est un événement à part : couper NIMM pendant qu'un
    #     outil tourne ne doit pas relancer la phrase interrompue.
    assert L.interpreter({'toolCallCancellation': {'ids': ['a1']}})[0]['type'] == 'outil_annule'
    ok("outils en Live : lecture seule, format Google respecté, appels appariés")


def test_outils_en_live_cables():
    """Le câblage bout en bout : déclaration, exécution, annonce."""
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    js = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()

    # (1) La passerelle exécute vraiment, et refuse ce qu'elle n'a pas déclaré.
    assert '_honorer_outil' in main and 'from core.hub import _execute_tool' in main
    assert 'if nom not in _noms_outils:' in main, \
        'un nom non déclaré ne doit jamais s’exécuter'
    assert 'reponse_outil(' in main, 'le résultat doit repartir vers Google'

    # (2) L'outil tourne dans une TÂCHE À PART : l'attendre dans la boucle de
    #     réception arrêterait la lecture des paquets audio, donc la voix.
    passerelle = main[main.index('async def _honorer_outil'):]
    passerelle = passerelle[:passerelle.index('async def live_conserver')
                            if 'async def live_conserver' in passerelle else len(passerelle)]
    assert 'create_task(' in passerelle, "l'outil bloque la boucle audio"
    assert 't.cancel()' in passerelle, \
        'un outil qui survit à la session écrirait dans une connexion fermée'

    # (3) Une annulation empêche la réponse de repartir.
    assert 'ident in _annules' in passerelle

    # (4) L'interface ANNONCE le passage par un outil. Sans cela, NIMM se tait
    #     une à deux secondes sans raison visible — et dans une conversation
    #     parlée, un silence inexpliqué ressemble à une panne.
    assert "case 'outil':" in js and '_liveNomOutil(' in js
    assert 'LIVE_NOMS_OUTILS' in js, 'les noms techniques ne se disent pas à l’oral'
    assert '_liveNoterOutil(' in js, 'le passage doit aussi être ÉCRIT, pour le braille'

    # (5) Les lignes d'outil sont distinguables à la relecture.
    assert "'[' + t.texte.trim() + ']'" in js, \
        'on doit distinguer ce que NIMM a dit de ce qu’il est allé chercher'

    # (6) Débrayable, et le réglage est ENREGISTRÉ AVANT l'ouverture : le
    #     serveur le lit au moment de configurer la session.
    assert 'id="live-outils"' in html and 'aria-describedby="live-outils-aide"' in html
    assert "await fetch('/api/live/options'" in js, \
        'réglage envoyé sans attendre : il arrivait parfois après l’ouverture'
    assert "set_setting('live_outils'" in main

    # (7) Chaque outil déclaré a une étiquette en français, sauf ceux qu'on
    #     écarte exprès. Un outil ajouté sans étiquette serait annoncé sous son
    #     nom technique : le test le signale plutôt que de le laisser passer.
    hub = open(os.path.join(racine, 'core', 'hub.py'), encoding='utf-8').read()
    noms = set()
    for n in ast.walk(ast.parse(hub)):
        if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') in (
                'NIMM_TOOLS', '_COANIMM_OPS_TOOLS', '_COANIMM_ASYNC_TOOLS'):
            try:
                val = ast.literal_eval(n.value)
            except Exception:
                continue
            if isinstance(val, list):
                noms |= {(t.get('function') or {}).get('name') for t in val
                         if (t.get('function') or {}).get('name')}
    table = set(re.findall(r'^\s{4}([a-z_0-9]+):\s+\'', js, re.M))
    oublies = sorted((noms - {'run_code', 'write_file'}) - table)
    assert not oublies, 'outils sans étiquette française : %s' % oublies
    ok("outils en Live : exécutés hors de la boucle audio, annoncés et écrits")



def test_retouche_aiguillage():
    """Découper ou redessiner : ce n'est pas le même travail, ni la même confiance.

    Le dossier « papillons » de Fernando contenait les deux natures, et ses
    noms de fichiers étaient les consignes : « enlever la dame en arrière-plan
    avec son sac », mais aussi des recadrages et un agrandissement.

    Confier un recadrage à un modèle génératif est une mauvaise idée : il ne
    DÉCOUPE pas, il REDESSINE — tous les pixels changent, les visages avec.
    Inversement, aucune bibliothèque locale ne fera disparaître la dame.

    Ce test vérifie l'aiguillage sur les consignes RÉELLES du dossier, plus les
    formulations courantes des deux catégories.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    from modules import retouche as R

    # Les trois consignes réelles, telles qu'elles étaient écrites.
    reelles = [
        "Il faut garder le papillon qui est au premier plan, posé sur un bras, "
        "mais si possible sans voir le bras, et surtout enlever la dame en "
        "arrière-plan avec son sac",
        "Il faut essayer d'enlever la barre en fer entre les deux nichoirs",
        "On voit un bout du mur, il faut l'enlever",
    ]
    for c in reelles:
        assert R.analyser(c)['voie'] == 'modele', \
            'consigne inventive envoyée en local : %s' % c[:50]

    exactes = {
        "recadre au format carré": 'recadrer',
        "recadre en 16:9": 'recadrer',
        "rogne de 10 %": 'recadrer',
        "enlève les bords blancs": 'recadrer',
        "pivote à droite": 'rotation',
        "tourne l'image de 90 degrés": 'rotation',
        "redresse la photo": 'redresser',
        "retourne en miroir": 'miroir',
        "agrandis ×2": 'echelle',
        "agrandis par 4": 'echelle',
        "réduis de moitié": 'echelle',
        "redimensionne à 1600 px": 'largeur',
        "éclaircis un peu": 'luminosite',
        "assombris beaucoup": 'luminosite',
        "plus de contraste": 'contraste',
        "rends-la plus nette": 'nettete',
        "mets-la en noir et blanc": 'gris',
    }
    for c, op in exactes.items():
        a = R.analyser(c)
        assert a['voie'] == 'local', 'partie au modèle pour rien : %s' % c
        assert op in [o['op'] for o in a['operations']], \
            '%s : opération %s non reconnue (%s)' % (c, op, a['operations'])

    # « enlève » ne rend pas une demande inventive : « enlève les bords » est
    # un rognage. Sans cette exception, un simple recadrage partait au modèle.
    assert R.analyser("enlève les bords blancs")['voie'] == 'local'
    assert R.analyser("enlève la dame")['voie'] == 'modele'

    # MÉLANGE : tout part au modèle. Faire la moitié localement puis l'autre
    # moitié autrement donnerait un résultat que personne ne saurait décrire.
    m = R.analyser("recadre en carré et enlève la dame")
    assert m['voie'] == 'modele' and 'mélange' in m['raison']

    # Rien de reconnu, ou rien du tout : au modèle, et il le dit.
    assert R.analyser("fais quelque chose de joli")['voie'] == 'modele'
    assert R.analyser("")['voie'] == 'modele'
    assert R.analyser("")['raison']

    # « un peu » et « beaucoup » ne demandent pas la même chose.
    doux = R.analyser("éclaircis un peu")['operations'][0]['facteur']
    fort = R.analyser("éclaircis beaucoup")['operations'][0]['facteur']
    assert fort > doux, 'la nuance d’intensité est ignorée'

    # La raison est TOUJOURS remplie : c'est elle qui sera lue à l'utilisateur.
    for c in list(exactes) + reelles + ["", "n'importe quoi"]:
        assert R.analyser(c)['raison'], 'raison vide pour : %r' % c[:40]
    ok("retouche : les consignes réelles du dossier papillons sont bien aiguillées")


def test_retouche_operations_locales():
    """Les opérations exactes le sont vraiment, et se racontent.

    On fabrique une image en mémoire : aucun fichier du projet n'est touché.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    from modules import retouche as R
    try:
        from PIL import Image
    except ImportError:
        ok("retouche : Pillow absent, opérations locales non vérifiées")
        return

    import io as _io
    tampon = _io.BytesIO()
    Image.new('RGB', (400, 300), (120, 60, 30)).save(tampon, format='JPEG')
    src = tampon.getvalue()

    def dims(octets):
        return Image.open(_io.BytesIO(octets)).size

    # Recadrage au carré : la plus petite dimension commande.
    res, mime, journal, err = R.appliquer(src, [{'op': 'recadrer', 'ratio': (1, 1)}])
    assert not err and dims(res) == (300, 300), dims(res)
    assert mime == 'image/png', 'le sans-perte est requis pour enchaîner les reprises'

    # Rotation : les dimensions s'échangent.
    res, _, _, err = R.appliquer(src, [{'op': 'rotation', 'angle': 90}])
    assert not err and dims(res) == (300, 400)

    # Agrandissement : facteur exact, et le journal DIT que rien n'est inventé.
    res, _, journal, err = R.appliquer(src, [{'op': 'echelle', 'facteur': 2.0}])
    assert not err and dims(res) == (800, 600)
    assert any('sans détail inventé' in l for l in journal), \
        'un agrandissement simple ne doit pas se faire passer pour mieux'

    # Largeur imposée : la hauteur suit la proportion.
    res, _, _, err = R.appliquer(src, [{'op': 'largeur', 'px': 200}])
    assert not err and dims(res) == (200, 150)

    # Les opérations s'enchaînent dans l'ordre demandé.
    res, _, journal, err = R.appliquer(src, [{'op': 'echelle', 'facteur': 2.0},
                                             {'op': 'recadrer', 'ratio': (1, 1)}])
    assert not err and dims(res) == (600, 600)

    # Le journal se termine TOUJOURS par les dimensions et le poids : sans les
    # voir, c'est la seule preuve que l'opération a eu lieu.
    assert any('au départ' in l and 'arrivée' in l for l in journal)
    assert any('sans perte' in l for l in journal)

    # Accord en genre : « contraste augmentée » était faux.
    _, _, journal, _ = R.appliquer(src, [{'op': 'contraste', 'facteur': 1.3}])
    assert any('contraste augmenté' in l and 'augmentée' not in l for l in journal), journal

    # Aucune fonction ne lève : les erreurs reviennent en français.
    assert 'illisible' in R.appliquer(b'pas une image', [{'op': 'gris'}])[3]
    assert R.appliquer(b'', [{'op': 'gris'}])[3]
    assert R.appliquer(src, [])[3], 'une liste vide doit être signalée'
    ok("retouche locale : exacte au pixel, et racontée dimension par dimension")


def test_retouche_cablee_et_honnete():
    """Le câblage, et la règle qui compte : ne jamais faire passer la consigne
    pour une description.

    C'est le même piège que pour les images créées, corrigé le 29/07 : on ne
    voit pas le résultat, donc la phrase qui le décrit EST le résultat. Servir
    la demande à la place de la description, c'est répondre à côté sans que
    personne puisse s'en apercevoir.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    js = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()

    # (1) Contrat interface / serveur.
    app = set(re.findall(r"/api/retouche/[a-z_]+", js))
    dec = set(re.findall(r"@app\.(?:get|post)\(\"(/api/retouche/[a-z_]+)\"", main))
    assert app and not (app - dec), 'routes appelées sans exister : %s' % sorted(app - dec)
    ids_js = set(re.findall(r"\$\('(studio-retouche-[a-z-]+)'\)", js))
    ids_html = set(re.findall(r'id="(studio-retouche-[a-z-]+)"', html))
    assert ids_js and not (ids_js - ids_html), \
        'éléments absents de la page : %s' % sorted(ids_js - ids_html)

    # (2) La VOIE est annoncée AVANT de lancer : savoir si l'image sera
    #     découpée ou redessinée change la confiance qu'on lui accorde.
    assert '/api/retouche/analyser' in js and 'studio-retouche-voie' in html
    voie = html[html.index('id="studio-retouche-voie"'):][:220]
    assert 'aria-live="polite"' in voie, 'l’aiguillage doit être annoncé'

    # (3) La description porte sur l'image OBTENUE, jamais sur la consigne.
    route = main[main.index('async def retouche_appliquer'):]
    route = route[:route.index(chr(10) + '@app') if chr(10) + '@app' in route else len(route)]
    assert '_vibe_describe_image' in route, 'le résultat n’est pas décrit'
    assert 'octets_res' in route, 'la description doit partir des octets OBTENUS'
    assert '"description": consigne' not in route and "'description': consigne" not in route

    # (4) Le commentaire du modèle N'EST PAS une description : il est rendu à
    #     part, pour qu'on ne le prenne pas pour ce qu'il n'est pas.
    assert '"commentaire"' in route

    # (5) Une description absente est DITE, pas passée sous silence.
    assert 'sans description disponible' in js, \
        'une alternative manquante doit s’annoncer'

    # (6) Le compte rendu est copiable : c'est le produit du panneau pour
    #     quelqu'un qui ne voit pas l'image.
    cr = html[html.index('id="studio-retouche-compte-rendu"') - 200:]
    cr = cr[:cr.index('</textarea>')]
    assert '<textarea' in cr and 'readonly' in cr, \
        'le compte rendu doit être un champ de texte copiable'

    # (7) Pillow travaille en bloquant : hors de la boucle.
    assert 'asyncio.to_thread(' in route, 'une grande image figerait le serveur'

    # (8) Sans clé Gemini, la voie inventive refuse en EXPLIQUANT ce qui reste
    #     possible, au lieu d'échouer sèchement.
    assert 'recadrer, pivoter, agrandir' in route

    # (9) La dépendance est déclarée.
    req = open(os.path.join(racine, 'requirements.txt'), encoding='utf-8').read()
    # Insensible à la casse : ce test cherchait « Pillow » avec une majuscule,
    # exactement comme le code qui a créé un doublon en ne voyant pas le
    # « pillow » déjà présent. Le contrôle reproduisait le défaut qu'il aurait
    # dû empêcher. pip, lui, ne fait pas la différence.
    assert 'pillow' in req.lower(), 'Pillow absent de requirements.txt'

    # (10) Le panneau est bien dans le studio, avec ses étiquettes.
    for ident in ('studio-retouche-fichier', 'studio-retouche-consigne',
                  'studio-retouche-compte-rendu'):
        assert ('for="%s"' % ident) in html, 'commande sans étiquette : %s' % ident
    ok("retouche : câblée, voie annoncée d’avance, résultat décrit honnêtement")



def test_focus_suit_l_ouverture():
    """Ouvrir un panneau doit y emmener le focus. Au clic comme au clavier.

    Défaut signalé par Fernando le 28/08 : en activant le bouton « Galerie
    d'images », le panneau s'ouvrait mais le focus restait sur le bouton. Au
    lecteur d'écran, rien ne se passe — il faut deviner qu'un panneau est
    apparu, puis aller le chercher à la tabulation.

    La cause tenait à l'histoire du code : le déplacement du focus n'existait
    QUE dans le gestionnaire de raccourci Alt+Maj. Chaque bouton avait son
    propre gestionnaire de clic, écrit à un moment différent, et aucun ne s'en
    occupait. Onze panneaux, onze occasions d'oublier.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()

    # (1) Le clic déplace le focus, et pas seulement le raccourci.
    assert 'LE FOCUS SUIT AUSSI LE CLIC' in js
    bloc = js[js.index('LE FOCUS SUIT AUSSI LE CLIC'):]
    bloc = bloc[:bloc.index('})();')]
    assert "document.addEventListener('click'" in bloc, \
        'le clic ne déclenche aucun déplacement de focus'
    assert 'focusModal(' in bloc

    # (2) PAR DÉLÉGATION, et c'est nécessaire : trois de ces boutons n'existent
    #     pas dans la page. Ils sont créés par renderSidebar(), qui les recrée
    #     à chaque rendu — un gestionnaire posé sur l'élément disparaîtrait.
    assert 'closest(' in bloc, \
        'sans délégation, les boutons créés dynamiquement ne sont pas couverts'
    crees = ['toggle-memory', 'toggle-prompt-library', 'toggle-search-conversations']
    ids_html = set(re.findall(r'id="([a-zA-Z0-9_-]+)"', html))
    absents = [b for b in crees if b not in ids_html]
    assert absents, ("ces boutons sont désormais dans la page : la justification "
                     "de la délégation a vieilli, relire le commentaire")
    for b in absents:
        assert ("id        = '%s'" % b) in js or ("id = '%s'" % b) in js, \
            '%s n’est ni dans la page ni créé par le script' % b

    # (3) TOUS les panneaux de la table sont couverts — pas une liste écrite à
    #     la main, qui laisserait le douzième derrière.
    assert 'Object.keys(SHORTCUTS)' in bloc, \
        'la couverture doit se déduire de la table, pas être recopiée'

    # (4) Chaque panneau attendu existe vraiment : un appariement cassé ne
    #     lève pas, il ne fait simplement rien — le pire des cas.
    table = dict(re.findall(r"^\s{8}'([a-z])': '(toggle-[a-z-]+)'", js, re.M))
    assert len(table) >= 8, 'relevé de la table trop maigre (%d)' % len(table)
    casses = []
    for _, bouton in table.items():
        panneau = ('history-panel' if bouton == 'toggle-history'
                   else bouton.replace('toggle-', '') + '-modal')
        if panneau not in ids_html:
            casses.append((bouton, panneau))
    assert not casses, 'panneaux introuvables : %s' % casses

    # (5) À la fermeture, le focus REVIENT d'où il venait. Sans cela on se
    #     retrouve en haut de la page sans savoir où l'on était.
    assert 'MutationObserver' in bloc, \
        'la fermeture passe par plusieurs chemins : les suivre un par un les rate'
    assert '_ouvreurs' in bloc
    ok("focus : tout panneau ouvert reçoit le focus, et le rend en se fermant")


def test_retouche_atteignable_depuis_la_galerie():
    """L'outil doit être là où on le cherche — et il y est maintenant POUR DE BON.

    Fernando a cherché « Manipuler une image » dans la galerie, et c'est
    logique : c'est l'endroit où l'on pense aux images qu'on possède déjà.

    Première réponse (28/08, matin) : un bouton dans la galerie qui renvoyait
    au studio. Insuffisant — il a redemandé, en cherchant cette fois la
    création d'image et de vidéo au même endroit. Une passerelle ne répare pas
    un mauvais rangement, elle l'avoue.

    Seconde réponse : le studio ENTRE dans le panneau. Plus de renvoi, plus de
    porte intermédiaire. Ce test vérifie donc l'inverse de ce qu'il vérifiait :
    la passerelle ne doit PLUS exister, et la retouche doit être sur place.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    js = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()

    assert 'galerie-vers-retouche' not in html and 'galerie-vers-retouche' not in js, \
        'la passerelle n’a plus lieu d’être : la retouche est dans le panneau'

    debut = html.index('<div id="galerie-modal"')
    assert html.index('id="studio-retouche-details"') > debut, \
        'la retouche doit vivre DANS le panneau Images'

    # Le volet reste câblé après le déménagement — c'est le risque de ce genre
    # de fusion : le code survit, la page change, et rien ne lève.
    for route in ('/api/retouche/options', '/api/retouche/analyser',
                  '/api/retouche/appliquer'):
        assert route in js, 'route %s plus appelée après la fusion' % route
    for ident in ('studio-retouche-btn', 'studio-retouche-consigne',
                  'studio-retouche-fichier', 'studio-retouche-reprendre'):
        assert ("$('%s')" % ident) in js, '%s n’est plus câblé' % ident
    corps = js[js.index('function _retoucheCabler'):]
    corps = corps[:corps.index(chr(10) + '    }' + chr(10))]
    assert 'addEventListener' in corps, \
        'le corps de _retoucheCabler est vide : le panneau ne répondrait à rien'
    ok("retouche : dans le panneau Images, sans passerelle, et toujours câblée")

def test_cles_api_toutes_enregistrables():
    """Six services du catalogue ne pouvaient pas voir leur clé enregistrée.

    Trouvé en cherchant pourquoi Fernando ne voyait plus la génération d'image
    et de vidéo. `ApiKeysSetting` énumérait ses champs À LA MAIN, et six
    services du catalogue n'y figuraient pas : groq, cerebras, exa, cohere,
    voyage, jina.

    Or Pydantic IGNORE en silence un champ qu'il ne connaît pas. L'interface
    envoyait donc la clé Groq, le serveur répondait « ok », et rien n'était
    enregistré. Groq et Cerebras étaient inutilisables depuis leur câblage du
    30/07 — câblés partout, mais sans moyen de leur donner une clé.

    La même liste figée servait à la LECTURE : l'interface croyait ces clés
    absentes, et grisait leurs options même lorsqu'elles existaient.

    C'est la troisième fois que ce motif coûte cher (adresses de fournisseurs
    dupliquées, listes de fournisseurs dans app.js, et maintenant les clés).
    La règle est la même à chaque fois : UNE table, et tout le reste s'en
    déduit.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, racine)
    from core.services import SERVICES
    main = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()

    connus = {s['id'] for s in SERVICES}
    assert len(connus) >= 12, 'catalogue trop maigre (%d)' % len(connus)
    for attendu in ('groq', 'cerebras', 'exa', 'cohere', 'voyage', 'jina'):
        assert attendu in connus, '%s absent du catalogue' % attendu

    # (1) Les deux routes se DÉDUISENT du catalogue, elles ne le recopient pas.
    lecture = main[main.index('async def get_api_keys'):]
    lecture = lecture[:lecture.index('@app.post')]
    assert 'SERVICES' in lecture, 'la lecture énumère encore une liste figée'
    assert "'anthropic','deepseek'" not in lecture, 'liste recopiée restante'

    modele = main[main.index('class ApiKeysSetting'):]
    modele = modele[:modele.index(chr(10) + 'class ')]
    assert "'extra': 'allow'" in modele, \
        'sans extra=allow, Pydantic jette en silence les clés inconnues'
    assert 'SERVICES' in modele, 'le filtre doit s’appuyer sur le catalogue'

    # (2) La preuve fonctionnelle, sur une SOURCE SIMULÉE : une clé Groq
    #     envoyée doit être retenue. C'est ce qui ne marchait pas.
    espace = {'SERVICES': SERVICES}
    corps = modele[modele.index('    def cles_utiles'):]
    corps = 'def cles_utiles(self):' + corps[corps.index('\n'):]
    corps = corps.replace('from core.services import SERVICES as _CATALOGUE',
                          '_CATALOGUE = SERVICES')
    corps = corps.replace('self.model_dump() if hasattr(self, \'model_dump\') else self.dict()',
                          'self')

    class _Faux(dict):
        pass
    exec(compile(corps, 'simule', 'exec'), espace)
    fn = espace['cles_utiles']
    envoye = _Faux({'groq': 'gsk_x', 'cerebras': 'csk_y', 'gemini': '   ',
                    'inconnu': 'z', 'exa': 'e'})
    retenues = fn(envoye)
    assert set(retenues) == {'groq', 'cerebras', 'exa'}, retenues
    assert 'gemini' not in retenues, 'une clé vide ne doit pas écraser l’existante'
    assert 'inconnu' not in retenues, 'un service hors catalogue ne doit pas entrer'

    # (3) La réponse DIT ce qui a été retenu. C'est précisément ce qui manquait
    #     pour s'apercevoir que six services partaient à la poubelle.
    ecriture = main[main.index('async def save_api_keys'):]
    ecriture = ecriture[:ecriture.index(chr(10) + '@app')]
    assert 'enregistrees' in ecriture, \
        'répondre « ok » sans dire quoi a caché le défaut pendant un mois'

    # (4) Chaque `data-needs-key` de la page désigne un service RÉEL. Un nom qui
    #     ne correspond à rien laisse l'élément grisé pour toujours, en
    #     silence — c'était le cas de « stability » (le catalogue dit
    #     « stability_ai »).
    demandees = set(re.findall(r'data-needs-key="([a-z_]+)"', html))
    assert demandees, 'aucun data-needs-key relevé : le test ne vérifie rien'
    orphelines = sorted(demandees - connus)
    assert not orphelines, \
        'clés demandées par la page mais absentes du catalogue : %s' % orphelines
    ok("clés API : les %d services du catalogue sont enregistrables et vus"
       % len(connus))


def test_menu_plus_dit_ou_il_mene():
    """Une porte doit annoncer ce qu'il y a derrière.

    Fernando, cherchant la génération d'image et de vidéo : « il me semblait
    que fut un temps il y avait aussi un moteur pour générer une image, une
    vidéo, et je ne vois plus rien de tout ça ». Rien n'avait été retiré : le
    studio vit dans le menu « + », dont le nom accessible était « Ajouter ».

    Ce n'est pas un défaut de code — tout marchait. C'est un défaut de nom, et
    il ne se voit que si l'on navigue à l'oreille : le titre de survol disait
    bien « Ajouter un fichier, créer une image ou une vidéo », mais un
    aria-label écrase le titre pour le lecteur d'écran.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    js = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()

    bouton = html[html.index('id="upload-btn"'):]
    bouton = bouton[:bouton.index('>') + 1]
    m = re.search(r'aria-label="([^"]+)"', bouton)
    assert m, 'le bouton « + » n’a pas de nom accessible'
    nom = m.group(1).lower()
    assert nom != 'ajouter', 'nom accessible trop pauvre : rien ne dit où il mène'
    # RÈGLE AJUSTÉE le 28/08 au soir : le « + » ne mène plus à la vidéo ni au
    # studio, qui ont rejoint le panneau Images. Son nom ne doit donc PAS les
    # promettre — un nom qui annonce plus qu'il ne donne fait perdre autant de
    # temps qu'un nom trop pauvre.
    assert 'image' in nom, 'le « + » crée bien une image dans la conversation'
    assert 'vidéo' not in nom, \
        'le « + » ne mène plus à la vidéo : ne pas la promettre'
    # ... mais COURT. Les deux exigences se tiennent : ce bouton est
    # traversé en permanence, et un nom de cinquante caractères y coûte du
    # temps à chaque passage. Règle posée par Fernando le 30/07 sur le
    # bouton Musique, et vérifiée par test_accessibilite_des_medias.
    assert len(m.group(1)) <= 30, \
        'nom accessible trop long (%d car.) : il sera lu à chaque passage' % len(m.group(1))

    # Un menu déroulant doit dire s'il est ouvert, et le dire VRAIMENT.
    assert 'aria-expanded' in bouton, 'aria-expanded absent du bouton de menu'
    assert "btn.setAttribute('aria-expanded'" in js, \
        'aria-expanded posé une fois pour toutes mentirait dès la première ouverture'
    # On regarde AUTOUR de la mise à jour elle-même, pas à la première
    # occurrence du mot dans le fichier : aria-expanded sert ailleurs.
    _zone = js[js.index("btn.setAttribute('aria-expanded'") - 700:]
    _zone = _zone[:1400]
    assert 'MutationObserver' in _zone, \
        'cinq endroits ouvrent ou ferment ce menu : les suivre un par un en rate un'

    # L'entrée du studio a disparu du menu : elle vit dans le panneau Images.
    assert 'plus-studio' not in html, \
        'l’entrée studio subsiste dans le « + » après la fusion'
    ok("menu « + » : son nom dit où il mène, et son état est vrai")



def test_une_seule_porte_vers_les_images():
    """Quatre portes menaient aux images. Il n'en reste qu'une.

    Fernando a cherché la création d'image et de vidéo dans la GALERIE trois
    fois de suite, sans les trouver. Après la deuxième, j'ai ajouté un bouton
    qui renvoyait au studio ; après la troisième, il a fallu admettre que ce
    n'était pas un défaut d'explication mais de rangement. C'est là que va le
    réflexe quand on pense « image ».

    Historique du va-et-vient, pour ne pas le refaire :
      - le studio a d'abord vécu dans la barre du haut ;
      - déplacé derrière le menu « + » le 30/07, pour réduire la redondance ;
      - fusionné dans le panneau Images le 28/08, parce que le « + » n'est pas
        l'endroit où l'on cherche des images.

    Le menu « + » garde ce qui s'ajoute AU MESSAGE en cours (joindre un
    fichier, créer une image dans la conversation, document Vibe). Le panneau
    Images tient ce qui PRODUIT et CONSERVE des fichiers.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()
    js = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()

    # (1) La modale studio n'existe plus, et RIEN ne la cherche encore.
    assert 'id="studio-modal"' not in html, 'la modale studio subsiste'
    assert 'studio-modal' not in js, 'le script cherche encore une modale disparue'
    assert 'plus-studio' not in html and 'plus-studio' not in js, \
        'l’entrée studio subsiste dans le menu « + »'

    # (2) Les trois volets ont bien SUIVI, dans le panneau Images.
    volets = re.findall(r'<details id="(studio-[a-z-]+)"', html)
    assert set(volets) == {'studio-image-details', 'studio-video-details',
                           'studio-retouche-details'}, volets
    debut = html.index('<div id="galerie-modal"')
    for v in volets:
        assert html.index('id="%s"' % v) > debut, \
            '%s n’est pas dans le panneau Images' % v

    # (3) Aucun élément cherché par le script n'a disparu dans le déménagement.
    #     C'est le risque propre à ce genre de fusion : le code survit, la page
    #     non, et rien ne lève — les fonctions cessent simplement de répondre.
    ids_html = set(re.findall(r'id="([a-zA-Z0-9_-]+)"', html))
    cherches = set(re.findall(r"getElementById\('(studio-[a-z-]+)'\)", js))
    cherches |= set(re.findall(r"\$\('(studio-[a-z-]+)'\)", js))
    absents = sorted(cherches - ids_html)
    assert not absents, 'éléments cherchés mais disparus : %s' % absents
    assert len(cherches) >= 15, 'contrôle trop maigre (%d éléments)' % len(cherches)

    # (4) Une seule porte, donc un seul raccourci. Alt+Maj+I est rendu.
    assert "if (k === 'i')" not in js, 'Alt+Maj+I désigne encore un studio disparu'
    assert 'Alt+Shift+I' not in js, 'raccourci orphelin'
    assert "'g': 'toggle-galerie'" in js, 'Alt+Maj+G doit rester la porte'

    # (5) Le bouton dit ce qu'il y a derrière — sans dépasser trente
    #     caractères, règle posée par Fernando le 30/07.
    bouton = html[html.index('id="toggle-galerie"'):]
    bouton = bouton[:bouton.index('>') + 1]
    m = re.search(r'aria-label="([^"]+)"', bouton)
    assert m and len(m.group(1)) <= 24, \
        'nom du bouton Images absent ou trop long pour la barre du haut'
    assert 'image' in (re.search(r'title="([^"]+)"', bouton).group(1).lower()), \
        'l’infobulle doit détailler ce que contient le panneau'

    # (6) Le menu « + » garde ce qui s'ajoute au MESSAGE, et rien d'autre.
    menu = html[html.index('id="plus-menu"'):]
    menu = menu[:menu.index('</div>')]
    entrees = set(re.findall(r'<button id="(plus-[a-z-]+)"', menu))
    assert 'plus-attach' in entrees, 'joindre un fichier a disparu'
    assert 'plus-imagegen' in entrees, \
        'créer une image DANS LA CONVERSATION est autre chose que le studio : à garder'
    assert 'plus-studio' not in entrees
    ok("images : une seule porte (Alt+Maj+G), rien d’injoignable après la fusion")



def test_mise_a_jour_dit_la_verite():
    """« Mise à jour appliquée ! » était faux sur les trois quarts du logiciel.

    Le backlog demandait un script de migration vers Git, parce qu'Éric et
    Nando, installés depuis un ZIP, ne recevaient pas les mises à jour. Or ce
    besoin est déjà couvert autrement : `/api/update` télécharge l'archive
    GitHub et remplace les fichiers, sans Git du tout. La demande du backlog
    est donc périmée.

    Mais en la vérifiant, ceci est apparu : la route copie des fichiers, et
    l'interface annonçait « Mise à jour appliquée ! Rechargement dans 3
    secondes… » avant de recharger la page toute seule.

    C'est faux. Python a déjà chargé `main.py`, `core/` et `modules/` en
    mémoire : les remplacer sur le disque ne change RIEN au processus en
    cours. Seuls les fichiers statiques sont relus par le navigateur. On
    obtient donc une INTERFACE NEUVE SUR UN SERVEUR ANCIEN — précisément la
    panne « contrat interface / serveur » que nos tests traquent, sauf qu'elle
    se produit chez l'utilisateur, à l'exécution. Les routes du jour
    (`/api/live/ws`, `/api/retouche/appliquer`) n'existeraient pas encore.

    Et si la version exige une bibliothèque de plus — Pillow pour la retouche,
    websockets pour le mode Live, tous deux ajoutés cette semaine — personne
    ne l'installe.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main = open(os.path.join(racine, 'main.py'), encoding='utf-8').read()
    js = open(os.path.join(racine, 'frontend', 'app.js'), encoding='utf-8').read()
    html = open(os.path.join(racine, 'frontend', 'index.html'), encoding='utf-8').read()

    route = main[main.index('async def do_update'):]
    route = route[:route.index(chr(10) + '@app')]

    # (1) La route DIT s'il faut relancer, et pourquoi.
    assert 'redemarrage_requis' in route, 'la route ne dit pas si un redémarrage s’impose'
    assert 'CODE_SERVEUR' in route, \
        'sans distinguer le code serveur des fichiers statiques, on ne peut pas le savoir'

    # (2) Elle nomme les bibliothèques APPARUES : personne ne les installera
    #     à la place de l'utilisateur.
    assert 'dependances_nouvelles' in route
    assert 'requirements.txt' in route

    # (3) Elle ne recopie que ce qui DIFFÈRE — sinon « fichiers modifiés »
    #     vaudrait toujours la totalité du dépôt, et n'apprendrait rien.
    assert 'filecmp' in route, 'sans comparaison, le compte de fichiers ment'

    # (4) Elle ne touche pas aux fichiers qui appartiennent à la machine.
    assert 'SKIP_FICHIERS' in route and 'nimm.log' in route, \
        'les journaux locaux seraient écrasés par ceux du dépôt'
    assert '"data"' in route or "'data'" in route, 'les données doivent être préservées'

    # (5) L'archive est décompressée AVANT toute copie : une archive abîmée ne
    #     doit pas laisser l'installation à moitié remplacée.
    assert route.index('extractall') < route.index('shutil.copy2'), \
        'copie entamée avant d’avoir vérifié que l’archive s’ouvre'

    # (6) L'interface ne ment plus, et ne recharge plus toute seule.
    bloc = js[js.index("fetch('/api/update'"):][:3000]
    assert 'Mise à jour appliquée' not in bloc, 'affirmation fausse restaurée'
    assert 'setTimeout(() => location.reload(), 3000)' not in bloc, \
        'le rechargement automatique donne à croire que tout est actif'
    assert 'd.message' in bloc, 'le message du serveur doit être affiché tel quel'
    assert 'redemarrage_requis' in bloc

    # (7) Le message porte une INSTRUCTION (« relance NIMM ») : s'il n'est pas
    #     annoncé, il n'existe pas pour qui n'a pas l'écran.
    zone = html[html.index('id="update-status"'):]
    zone = zone[:zone.index('>') + 1]
    assert 'aria-live' in zone, 'l’instruction de redémarrage doit être annoncée'
    assert '_coanimmAnnounce' in bloc, 'et annoncée aussi au moment où elle arrive'

    # (8) La liste des fichiers est copiable — on ne dicte pas vingt chemins.
    assert 'readOnly = true' in bloc, 'la liste des fichiers doit être copiable'
    ok("mise à jour : dit ce qui a changé, réclame le redémarrage, nomme les dépendances")



def test_requirements_complet_et_sans_doublon():
    """Ce que NIMM importe pour démarrer doit être déclaré. Sans exception.

    Question de Fernando le 31/08 : « en as-tu profité pour mettre à jour
    requirements.txt ? ». La vérification a rapporté deux choses, dont une de
    mon fait.

    1. J'AVAIS CRÉÉ UN DOUBLON. `Pillow` était déjà déclaré plus bas, en
       minuscules, pour l'OCR. Mon contrôle avant ajout était sensible à la
       casse et ne l'a pas vu. Sans conséquence pour pip, mais c'est le genre
       de désordre qui fait douter du reste du fichier.

    2. `requests` N'ÉTAIT DÉCLARÉ NULLE PART, alors qu'il est importé EN TÊTE
       de `net_guard.py` et de `websearch.py`. Un import en tête n'est pas
       rattrapable : sans lui, ces deux modules ne se chargent pas du tout —
       donc ni la recherche web, ni le garde-fou anti-SSRF. Ça ne se voyait
       pas parce qu'une autre bibliothèque l'installe en passant. Sur une
       installation neuve, ou le jour où cette autre bibliothèque cesse d'en
       dépendre, la recherche web tombe sans explication.

    LA DISTINCTION QUI FAIT TOUT
    Un import placé dans un `try` ou dans une fonction est OPTIONNEL : son
    absence est rattrapée, et le code le dit en français (kokoro, piper,
    geopy, networkx sont dans ce cas — volontairement non déclarés). Un import
    en TÊTE de module est OBLIGATOIRE. Ce test ne surveille que les seconds.
    """
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _norm(nom):
        # pip traite « - », « _ » et « . » comme équivalents. Ne pas le faire,
        # c'est produire de faux manquants — première version de ce test.
        return re.sub(r'[-_.]+', '-', nom.strip().lower())

    declares = {}
    for n, ligne in enumerate(open(os.path.join(racine, 'requirements.txt'),
                                   encoding='utf-8'), 1):
        brut = ligne.split('#')[0].strip()
        if not brut:
            continue
        declares.setdefault(_norm(re.split(r'[<>=!\[ ]', brut)[0]), []).append(n)

    assert len(declares) >= 30, 'relevé trop maigre (%d)' % len(declares)

    # (1) Aucun doublon : deux lignes pour un même paquet, c'est le signe que
    #     personne ne sait plus ce que contient le fichier.
    doublons = {k: v for k, v in declares.items() if len(v) > 1}
    assert not doublons, 'paquets déclarés deux fois : %s' % doublons

    # (2) Tout import EN TÊTE de module doit être déclaré.
    std = set(sys.stdlib_module_names) | {'core', 'modules', 'main', 'tests'}
    alias = {'PIL': 'pillow', 'yaml': 'pyyaml', 'bs4': 'beautifulsoup4',
             'docx': 'python-docx', 'pptx': 'python-pptx', 'fitz': 'pymupdf',
             'dotenv': 'python-dotenv', 'sklearn': 'scikit-learn',
             'whisper': 'openai-whisper', 'multipart': 'python-multipart',
             'fpdf': 'fpdf2', 'sentence_transformers': 'sentence-transformers',
             'google': 'google-genai'}

    obligatoires = {}
    for dossier in ('.', 'core', 'modules'):
        chemin_d = os.path.join(racine, dossier)
        for f in sorted(os.listdir(chemin_d)):
            if not f.endswith('.py'):
                continue
            p = os.path.join(chemin_d, f)
            try:
                arbre = ast.parse(open(p, encoding='utf-8').read())
            except Exception:
                continue
            # SEULEMENT le premier niveau : un import sous `try` ou dans une
            # fonction est un choix, pas une dépendance dure.
            for n in arbre.body:
                noms = []
                if isinstance(n, ast.Import):
                    noms = [a.name.split('.')[0] for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                    noms = [n.module.split('.')[0]]
                for x in noms:
                    if x not in std:
                        obligatoires.setdefault(x, set()).add(
                            os.path.relpath(p, racine).replace('\\', '/'))

    assert len(obligatoires) >= 8, \
        'relevé des imports obligatoires trop maigre (%d)' % len(obligatoires)

    manquants = sorted(
        '%s (%s)' % (nom, ', '.join(sorted(fichiers)))
        for nom, fichiers in obligatoires.items()
        if _norm(alias.get(nom, nom)) not in declares)
    assert not manquants, (
        'importés en tête de module mais absents de requirements.txt : '
        + ' ; '.join(manquants))

    # (3) Les deux ajouts de la semaine doivent y être : sans eux, la retouche
    #     et le mode Live refusent de fonctionner sur une machine neuve.
    for paquet in ('pillow', 'websockets', 'requests'):
        assert paquet in declares, '%s absent de requirements.txt' % paquet
    ok("requirements : %d paquets, aucun doublon, aucun import obligatoire oublié"
       % len(declares))


if __name__ == '__main__':
    for fn in [test_succes_direct, test_echec_puis_reparation, test_critique_puis_correction,
               test_capacite_manquante, test_arret_sur_erreur, test_wrapper_non_stream,
               test_adaptation_appelee, test_sans_entree_pas_dadaptation, test_adaptation_invalide_repli,
               test_journalisation_succes, test_journalisation_refus_capacite, test_journalisation_echec_etape,
               test_chat_liste, test_chat_resolution_nom, test_chat_dispatch,
               test_fiabilite_ricochet, test_critique_desactivable, test_echeances,
               test_worker_marque_a_notifier, test_facturation_cache,
               test_specificites_anthropic_confinees, test_mcp_inerte_sans_serveur,
               test_repli_cache_refuse, test_avis_raison_arret,
               test_facturation_cache_partout, test_signal_troncature_bout_en_bout,
               test_anthropic_diffuse_en_continu, test_tous_fournisseurs_diffusent,
               test_verification_des_faits, test_appel_outil_ecrit_en_texte,
               test_rag_ancrage_lexical, test_pied_document_honnete,
               test_journal_de_fonctionnement, test_historique_purge_des_appels_en_texte,
               test_panne_fournisseur_reprise, test_plan_de_la_reponse,
               test_modele_de_raisonnement, test_specificites_gemini_et_openai,
               test_caches_de_contexte, test_visibilite_selon_les_cles,
               test_description_video, test_correlation_modele_agent_recherche,
               test_reprise_sans_couture,
               test_description_audio, test_documents_epingles, test_lot_gemini,
               test_document_de_la_conversation,
               test_magasin_documents_de_fil,
               test_choix_dans_la_base,
               test_reordonnancement,
               test_veille,
               test_catalogue_services, test_exa_avance,
               test_exa_dans_le_chat,
               test_audit_structurel,
               test_verification_relance_sur_pause,
               test_script_reparation, test_script_permission_inchangee,
               test_script_blocage_securite_pas_de_retry,
               test_veille_se_signale, test_banc_essai_reordonnanceur,
               test_musique_lyria,
               test_imagerie_reglee, test_video_veo, test_alt_honnete,
               test_contrat_interface_serveur,
               test_accessibilite_des_medias, test_modeles_conseilles,
               test_fournisseurs_cables_partout,
               test_anthropic_parametres_echantillonnage,
               test_erreur_api_explique_la_cause,
               test_reflexion_deepseek,
               test_documentation_a_jour,
               test_demarrage_a_froid,
               test_reponse_muette_apres_outil,
               test_fantome_a_la_creation, test_live_configuration,
               test_live_interprete_le_flux, test_live_accessible,
               test_live_confidentialite, test_live_contrat_interface_serveur,
               test_masque_illisible_ne_bloque_pas, test_tout_est_utf8,
               test_outils_tous_atteignables, test_outils_en_live,
               test_outils_en_live_cables,
               test_retouche_aiguillage, test_retouche_operations_locales,
               test_retouche_cablee_et_honnete,
               test_focus_suit_l_ouverture,
               test_retouche_atteignable_depuis_la_galerie,
               test_cles_api_toutes_enregistrables,
               test_menu_plus_dit_ou_il_mene,
               test_une_seule_porte_vers_les_images,
               test_mise_a_jour_dit_la_verite,
               test_requirements_complet_et_sans_doublon]:
        fn()
    print(f"\nTOUS LES TESTS PASSENT ({len(PASSED)} scénarios).")
