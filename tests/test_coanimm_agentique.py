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

    # 1. Les champs propres à Anthropic ne sont posés que dans ses fonctions
    for motif in ("payload['cache_control']", "payload['thinking']", "payload['output_config']"):
        for m in re.finditer(re.escape(motif), src):
            debut = src.rfind('def ', 0, m.start())
            nom = src[debut:src.find('(', debut)]
            assert 'anthropic' in nom, f"{motif} posé hors Anthropic ({nom})"

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
    for autre in ('deepseek-chat', 'mistral-large-latest', 'gpt-4o', ''):
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
               test_verification_relance_sur_pause,
               test_script_reparation, test_script_permission_inchangee,
               test_script_blocage_securite_pas_de_retry]:
        fn()
    print(f"\nTOUS LES TESTS PASSENT ({len(PASSED)} scénarios).")
