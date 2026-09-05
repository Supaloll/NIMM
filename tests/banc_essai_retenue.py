# -*- coding: utf-8 -*-
"""Banc d'essai de la règle de retenue de coaNIMM — « agir ou demander ? »

CE N'EST PAS UN TEST PERMANENT. Il appelle la VRAIE API du fournisseur, donc
il coûte de l'argent : une trentaine de messages courts par fournisseur. Il ne
fait en revanche AUCUNE écriture dans la base — ni fil, ni message, ni
mémoire : il reconstruit le couple prompt + outils tel que le chat l'envoie,
puis observe la première décision du modèle et s'arrête là.

POURQUOI CE BANC EXISTE
Le mécanisme livré le 02/09/2026 (règle de retenue dans le prompt + outil
terminal demander_precision) est verrouillé par trois tests STATIQUES : la
règle est présente, la question est lisible en braille, l'outil coupe bien la
boucle. Aucun ne dit s'il se déclenche AU BON MOMENT. Or il peut échouer de
deux façons opposées, et les deux passent les tests statiques :

  - les modèles ignorent la règle → rien n'a changé, on s'est raconté une
    histoire ;
  - les modèles la sur-appliquent → coaNIMM demande une précision à chaque
    tour, ce qui est exactement le défaut décrit par la contre-règle.

Seul un jeu de cas étiquetés distingue les deux. C'est aussi la seule mesure
qui permettra de trancher sur le routeur d'intention écarté le 02/09 : sans
chiffres, ce débat reste une affaire d'opinion.

CE QUI EST MESURÉ
Pour chaque message, on regarde la PREMIÈRE décision du modèle :
  - appel à demander_precision  → il demande
  - appel à un outil qui produit ou modifie (run_code, write_file, renommage,
    déplacement, suppression, création de dossier, ricochet…) → il agit
  - appel à un outil de simple consultation (mémoire, archives, web, lecture
    de dossier…) → il cherche, ce qui n'est ni agir ni demander
  - aucun appel → il répond en texte

Verdict par étiquette (voir tests/cas_retenue.txt) :
  clair       → échec si demander_precision. Agir ou répondre sont tous deux
                acceptés : ce banc ne juge pas la qualité de l'action.
  ambigu      → succès SI demander_precision, échec sinon.
  discussion  → échec si demander_precision ou si outil de production.

Usage :
    python tests/banc_essai_retenue.py
    python tests/banc_essai_retenue.py --fournisseurs deepseek,mistral
    python tests/banc_essai_retenue.py --etiquette ambigu --limite 5
    python tests/banc_essai_retenue.py --profil nando --sortie mon_rapport.txt

Le rapport est écrit au fur et à mesure dans tests/results/ : une coupure
réseau ne fait pas perdre les cas déjà passés.
"""
import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
sys.dont_write_bytecode = True
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from core.database import (get_setting, set_setting, set_user_context,  # noqa: E402
                           _load_users)
from core.hub import (NIMM_TOOLS, build_system_prompt, load_mask,  # noqa: E402
                      load_settings)
from core.engine import call_llm_stream_with_tools  # noqa: E402

FICHIER_CAS = os.path.join(RACINE, 'tests', 'cas_retenue.txt')
DOSSIER_RES = os.path.join(RACINE, 'tests', 'results')

# Outils qui PRODUISENT ou MODIFIENT quelque chose. Liste fermée et explicite :
# un outil inconnu est signalé plutôt que rangé en silence dans un camp — un
# banc d'essai qui se trompe de camp sans le dire est pire que pas de banc.
OUTILS_PRODUCTION = {
    'run_code', 'write_file',
    'rename_file', 'move_file', 'delete_file', 'make_folder',
    'expurgate_document', 'run_ricochet',
}
OUTILS_CONSULTATION = {
    'search_memory', 'search_bibliotheque', 'search_anecdotes', 'search_web',
    'search_documents', 'search_carnet', 'find_skill', 'search_acceslibre',
    'search_food_product', 'search_recipe', 'get_weather', 'get_jours_feries',
    'get_exchange_rate', 'geocode_address', 'extract_url_content',
    'lookup_book', 'get_country_info', 'search_commune', 'search_wikipedia',
    'search_wikidata', 'search_sirene', 'search_datagouv', 'describe_image',
    'list_files', 'extract_document_text', 'summarize_document',
    'list_ricochets',
}
OUTIL_RETENUE = 'demander_precision'


def lire_cas():
    """Charge tests/cas_retenue.txt. Une ligne = étiquette | message | pourquoi."""
    cas = []
    for n, ligne in enumerate(open(FICHIER_CAS, encoding='utf-8'), 1):
        ligne = ligne.strip()
        if not ligne or ligne.startswith('#'):
            continue
        morceaux = [m.strip() for m in ligne.split('|')]
        if len(morceaux) != 3:
            print('[BANC] Ligne %d ignorée (3 champs attendus) : %s' % (n, ligne[:60]))
            continue
        etiquette, message, pourquoi = morceaux
        if etiquette not in ('clair', 'ambigu', 'discussion'):
            print('[BANC] Ligne %d ignorée (étiquette inconnue %r)' % (n, etiquette))
            continue
        cas.append({'ligne': n, 'etiquette': etiquette,
                    'message': message, 'pourquoi': pourquoi})
    return cas


def juger(etiquette, decision, outils):
    """Rend (comportement_ok, forme_ok, explication). forme_ok vaut None quand
    la question ne se pose pas.

    Deux verdicts distincts, et c'est le coeur du banc :
      - comportement : le modèle a-t-il fait ce qu'il fallait — agir, s'abstenir,
        demander ?
      - forme : quand il fallait demander, est-il passé par demander_precision
        plutôt que par un paragraphe rédigé ?

    Les confondre donne des chiffres illisibles. Le premier jet de ce banc
    (05/09/2026) comptait « a répondu en texte » comme un échec sec : Mistral
    est ressorti à 0/10 sur les cas ambigus alors qu'il demandait bel et bien
    une précision dans neuf cas sur dix — simplement en prose. Un modèle qui
    demande toujours au bon moment mais toujours en prose n'a PAS le même
    défaut qu'un modèle qui fonce sur l'outil sans réfléchir, et on ne les
    corrige pas au même endroit.
    """
    faits = {'agit': 'a agi', 'cherche': 'a cherché', 'texte': 'a répondu',
             'demande_prose': 'a répondu en posant une question'}
    if etiquette == 'ambigu':
        if decision == 'demande':
            return True, True, 'a demandé via l outil, comme attendu'
        if decision == 'demande_prose':
            return True, False, 'a demandé, mais en prose au lieu de demander_precision'
        if decision == 'agit':
            return False, False, 'a AGI sur une demande incomplète (%s)' % ', '.join(outils)
        if decision == 'cherche':
            return True, False, ('a cherché (%s) sans poser la question — le banc '
                                 'n observe que la première décision'
                                 % ', '.join(outils))
        return False, False, 'a répondu sans rien demander'
    if etiquette == 'clair':
        if decision == 'demande':
            return False, None, 'a demandé une précision alors que tout était donné'
        return True, None, faits[decision]
    # discussion : poser une question en prose est banal dans une conversation
    # (« ça va, et toi ? ») — ce n'est pas jugé. Seuls l'outil de retenue et un
    # outil de production sont des écarts ici.
    if decision == 'demande':
        return False, None, 'a demandé une précision dans une conversation ordinaire'
    if decision == 'agit':
        return False, None, ('a déclenché un outil de production (%s) sans raison'
                             % ', '.join(outils))
    return True, None, faits[decision]


async def passer_un_cas(cas, provider, reglages, system_prompt, inconnus):
    """Envoie un message et rend la décision observée. N'écrit rien en base."""
    outils, texte = [], ''
    try:
        async for ev in call_llm_stream_with_tools(
            messages=[{'role': 'user', 'content': cas['message']}],
            tools=NIMM_TOOLS,
            provider=provider,
            model=reglages.get('model'),
            system_prompt=system_prompt,
            max_tokens=reglages['max_tokens'],
            temperature=reglages['temperature'],
            api_keys=reglages['api_keys'],
        ):
            if ev.get('type') == 'token':
                texte += ev.get('text', '')
            elif ev.get('type') == 'tool_calls':
                outils = [c['name'] for c in ev['calls']]
                break          # la PREMIÈRE décision suffit : on n'exécute rien
    except Exception as e:
        return 'erreur', outils, repr(e)[:200]

    extrait = texte.strip()[:200]
    if OUTIL_RETENUE in outils:
        return 'demande', outils, extrait
    for nom in outils:
        if nom not in OUTILS_PRODUCTION and nom not in OUTILS_CONSULTATION:
            inconnus.add(nom)
    if any(n in OUTILS_PRODUCTION for n in outils):
        return 'agit', outils, extrait
    if outils:
        return 'cherche', outils, extrait
    # Aucun outil appelé : le modèle a répondu. Mais a-t-il POSÉ UNE QUESTION ?
    # Sur un cas ambigu, « a demandé en prose » et « a répondu sans rien
    # demander » sont deux situations opposées — voir juger().
    if '?' in texte:
        return 'demande_prose', outils, extrait
    return 'texte', outils, extrait


async def main(args):
    profil = args.profil
    if not profil:
        users = _load_users()
        if not users:
            print('[BANC] Aucun profil dans la base.')
            return
        profil = users[0]['id']
    set_user_context(profil)

    cas = lire_cas()
    if args.etiquette:
        cas = [c for c in cas if c['etiquette'] == args.etiquette]
    cas = cas[args.depuis:]
    if args.limite:
        cas = cas[:args.limite]
    if not cas:
        print('[BANC] Aucun cas à passer.')
        return

    reglages = load_settings(None)
    fournisseurs = ([f.strip() for f in args.fournisseurs.split(',') if f.strip()]
                    if args.fournisseurs else [reglages['provider']])

    # Prompt système identique à celui du chat, sans contexte personnel :
    # on mesure la règle de retenue, pas la mémoire du profil.
    try:
        masque = load_mask(reglages['mask_id'])
    except Exception:
        masque = {'system_prompt': 'Tu es un assistant utile et direct.'}
    system_prompt = build_system_prompt(masque, memory_context='',
                                        user_name=reglages.get('user_name', 'utilisateur'))

    os.makedirs(DOSSIER_RES, exist_ok=True)
    horodatage = datetime.now().strftime('%Y%m%d_%H%M%S')
    sortie = args.sortie or os.path.join(DOSSIER_RES, 'retenue_%s.txt' % horodatage)
    rapport = open(sortie, 'w', encoding='utf-8')

    def dire(ligne=''):
        print(ligne)
        rapport.write(ligne + chr(10))
        rapport.flush()          # écrit au fur et à mesure : une coupure ne perd rien

    dire('BANC D ESSAI — RÈGLE DE RETENUE DE COANIMM')
    dire('Profil : %s' % profil)
    dire('Date   : %s' % datetime.now().strftime('%d/%m/%Y %H:%M'))
    dire('Cas    : %d' % len(cas))
    dire('Fournisseurs : %s' % ', '.join(fournisseurs))
    dire('Rapport : %s' % sortie)
    dire('=' * 70)

    if args.a_sec:
        # Vérifie tout le circuit SANS dépenser un centime : cas lus, prompt
        # construit, outils déclarés. À passer avant toute campagne réelle.
        dire()
        dire('MODE À SEC — aucun appel API.')
        dire('Prompt système : %d caractères' % len(system_prompt))
        dire('Règle de retenue présente dans le prompt : %s'
             % ('oui' if 'Règle de retenue' in system_prompt else 'NON — le banc ne mesurerait rien'))
        dire('Outils déclarés : %d, dont demander_precision : %s'
             % (len(NIMM_TOOLS),
                'oui' if any((t.get('function') or {}).get('name') == OUTIL_RETENUE
                             for t in NIMM_TOOLS) else 'NON'))
        dire()
        for i, c in enumerate(cas, 1):
            dire('%2d. %-10s %s' % (i, c['etiquette'], c['message']))
        rapport.close()
        print()
        print('[BANC] Rapport à sec écrit dans %s' % sortie)
        return

    inconnus = set()
    bilan = {}
    for provider in fournisseurs:
        dire()
        dire('--- Fournisseur : %s ---' % provider)
        cle = {'anthropic': 'anthropic', 'deepseek': 'deepseek', 'openai': 'openai',
               'gemini': 'gemini', 'mistral': 'mistral', 'openrouter': 'openrouter',
               'groq': 'groq', 'cerebras': 'cerebras'}.get(provider)
        if cle and not (reglages['api_keys'].get(cle) or '').strip():
            dire('Clé API absente pour %s — fournisseur sauté.' % provider)
            continue

        # [comportement réussis, comportement jugés, forme réussies, forme jugées]
        scores = {'clair': [0, 0, 0, 0], 'ambigu': [0, 0, 0, 0], 'discussion': [0, 0, 0, 0]}
        ecarts = []
        for i, c in enumerate(cas, 1):
            decision, outils, extrait = await passer_un_cas(
                c, provider, reglages, system_prompt, inconnus)
            if decision == 'erreur':
                dire('%2d. [ERREUR] %s — %s' % (i, c['message'][:50], extrait))
                continue
            comportement, forme, explication = juger(c['etiquette'], decision, outils)
            sc = scores[c['etiquette']]
            sc[1] += 1
            if comportement:
                sc[0] += 1
            if forme is not None:
                sc[3] += 1
                if forme:
                    sc[2] += 1
            if not comportement:
                marque = 'ÉCART'
            elif forme is False:
                marque = 'FORME'          # bon réflexe, mauvaise présentation
            else:
                marque = 'OK'
            if marque != 'OK':
                ecarts.append((c, decision, outils, explication, extrait, marque))
            dire('%2d. %-10s %-6s %s | %s' % (
                i, c['etiquette'], marque, c['message'][:44], explication))
            if args.verbeux and extrait:
                dire('      → %s' % extrait.replace(chr(10), ' ')[:150])
            if args.pause:
                time.sleep(args.pause)

        dire()
        comp_ok = sum(v[0] for v in scores.values())
        comp_n = sum(v[1] for v in scores.values())
        forme_ok = sum(v[2] for v in scores.values())
        forme_n = sum(v[3] for v in scores.values())
        for et in ('clair', 'ambigu', 'discussion'):
            a, b, c2, d = scores[et]
            detail = ('   forme %d/%d' % (c2, d)) if d else ''
            dire('  %-11s comportement %d/%d%s' % (et, a, b, detail))
        dire('  %-11s comportement %d/%d%s' % (
            'TOTAL', comp_ok, comp_n,
            ('   forme %d/%d' % (forme_ok, forme_n)) if forme_n else ''))
        dire()
        dire('  comportement = a-t-il agi, s abstenu ou demandé au bon moment ?')
        dire('  forme        = quand il fallait demander, est-il passé par')
        dire('                 demander_precision plutôt que par un paragraphe ?')
        bilan[provider] = (comp_ok, comp_n, forme_ok, forme_n)

        if ecarts:
            dire()
            dire('  Écarts en détail :')
            for c, decision, outils, explication, extrait, marque in ecarts:
                dire('   • [%s / %s] %s' % (c['etiquette'], marque, c['message']))
                dire('     attendu : %s' % c['pourquoi'])
                dire('     observé : %s%s' % (explication,
                                              (' — outils : ' + ', '.join(outils)) if outils else ''))
                if extrait:
                    dire('     début de réponse : %s' % extrait.replace(chr(10), ' ')[:140])

    if inconnus:
        dire()
        dire('ATTENTION — outils non classés (ni production ni consultation) : %s'
             % ', '.join(sorted(inconnus)))
        dire('Les ranger dans OUTILS_PRODUCTION ou OUTILS_CONSULTATION en tête de ce script,')
        dire('sinon les verdicts les concernant ne veulent rien dire.')

    dire()
    dire('=' * 70)
    for provider, (a, b, c2, d) in bilan.items():
        dire('%-12s comportement %d/%d%s' % (
            provider, a, b, ('   forme %d/%d' % (c2, d)) if d else ''))
    rapport.close()
    print()
    print('[BANC] Rapport écrit dans %s' % sortie)


def lire_arguments():
    a = argparse.ArgumentParser(description='Banc d essai de la règle de retenue de coaNIMM')
    a.add_argument('--profil', default=None, help='profil NIMM (défaut : le premier de la base)')
    a.add_argument('--fournisseurs', default=None,
                   help='liste séparée par des virgules (défaut : celui du profil)')
    a.add_argument('--etiquette', default=None, choices=['clair', 'ambigu', 'discussion'],
                   help='ne passer que les cas de cette étiquette')
    a.add_argument('--limite', type=int, default=0, help='nombre maximum de cas')
    a.add_argument('--depuis', type=int, default=0, help='sauter les N premiers cas')
    a.add_argument('--pause', type=float, default=0.0, help='secondes entre deux appels')
    a.add_argument('--sortie', default=None, help='chemin du rapport')
    a.add_argument('--a-sec', action='store_true', dest='a_sec',
                   help='tout vérifier sans appeler l API (gratuit)')
    a.add_argument('--verbeux', action='store_true',
                   help='afficher le début de la réponse pour TOUS les cas, pas '
                        'seulement les écarts')
    return a.parse_args()


if __name__ == '__main__':
    asyncio.run(main(lire_arguments()))
