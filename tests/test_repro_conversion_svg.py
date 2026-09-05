# -*- coding: utf-8 -*-
"""Outil de DIAGNOSTIC : rejoue une demande dans le vrai chemin du chat.

CE N'EST PAS UN TEST PERMANENT. Il n'est pas lance par
tests/test_coanimm_agentique.py et ne doit pas l'etre : il appelle la VRAIE
API du fournisseur (donc il coute de l'argent) et ecrit dans la VRAIE base du
profil vise, sur un fil neuf. A garder dans le meme esprit que
tests/test_perf_message.py : un instrument qu'on ressort quand un
comportement resiste au raisonnement.

Origine : Laurent, 02/09/2026. coaNIMM annoncait convertir un .svg en .png,
puis s'arretait net -- parfois sur un simple "<" orphelin. Ce script appelle
core.hub.process_message_stream(), la fonction exacte servie par la route
/api/chat/stream, et se contente d'afficher les evenements SSE recus. A chaque
appel API, engine.py emet [DEBUG-MESSAGES] (index, role, contenu vide ou non,
tool_calls presents ou non, tool_call_id) ; en cas d'echec, [DEBUG-ERROR]
affiche le corps brut de la requete et de la reponse. C'est ce qui a permis de
voir que le modele n'avait droit qu'a UN outil par tour (voir la section
"coaNIMM s'arretait au milieu du travail" dans ARCHITECTURE.md).

Le profil, le fournisseur et le message etaient ecrits en dur dans la premiere
version -- un chemin de bureau personnel et un nom d'utilisateur partaient
ainsi dans le depot public, et personne d'autre ne pouvait relancer le script
sans l'editer. Tout est desormais en parametres.

Usage :
    python tests/test_repro_conversion_svg.py --profil laurent \
        --message "Peux-tu convertir ce .svg en .png ? Le chemin est C:\\...\\x.svg"

    python tests/test_repro_conversion_svg.py --profil nando \
        --fournisseur deepseek --message "..."

Sans --profil, le premier profil de la base est utilise. Sans --message, une
demande de conversion generique est envoyee (elle ne devrait rien produire de
concret : c'est le COMPORTEMENT de la boucle qu'on observe, pas le resultat).
"""
import argparse
import asyncio
import json
import os
import sys
import uuid

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import (get_setting, set_setting, set_user_context,  # noqa: E402
                           _load_users)
from core.hub import process_message_stream  # noqa: E402

MESSAGE_PAR_DEFAUT = ("Peux-tu convertir ce fichier .svg en .png ? "
                      "Le chemin est /chemin/vers/mon_fichier.svg")


def lire_arguments():
    a = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    a.add_argument('--profil', default=None,
                   help='id du profil NIMM a utiliser (defaut : le premier de la base)')
    a.add_argument('--fournisseur', default='mistral',
                   help="fournisseur force pour le chat (defaut : mistral, celui qui plantait)")
    a.add_argument('--message', default=MESSAGE_PAR_DEFAUT,
                   help='le message a envoyer, entre guillemets')
    return a.parse_args()


async def main(args):
    profil = args.profil
    if not profil:
        users = _load_users()
        if not users:
            print('[REPRO] Aucun profil dans la base — rien a rejouer.')
            return
        profil = users[0]['id']
        print('[REPRO] Aucun --profil donne : utilisation de %r.' % profil)

    thread_id = 'repro-' + uuid.uuid4().hex[:12]
    print('=' * 72)
    print('[REPRO] Profil       : ' + profil)
    print('[REPRO] Thread neuf  : ' + thread_id)
    print('[REPRO] Fournisseur  : %s (force via routing)' % args.fournisseur)
    print('[REPRO] Message      : ' + args.message)
    print('[REPRO] ATTENTION : appel API reel et ecriture dans la base de ce profil.')
    print('=' * 72)

    set_user_context(profil)
    ancien_provider = get_setting('provider', '')
    ancien_routing = get_setting('provider_routing', '{}')

    # Forcer le chat sur le fournisseur vise (source unique de load_settings)
    routing = json.loads(ancien_routing or '{}')
    routing['chat'] = args.fournisseur
    set_setting('provider_routing', json.dumps(routing))

    try:
        n = 0
        async for chunk in process_message_stream(
            thread_id=thread_id,
            user_message=args.message,
            web_search=False,
        ):
            n += 1
            print('[SSE #%d] %r' % (n, chunk))
        print('[REPRO] Flux termine normalement (%d evenements).' % n)
    except Exception as e:
        print('[REPRO] EXCEPTION remontee : ' + repr(e))
    finally:
        # Restauration du routing du profil, meme apres une exception
        set_setting('provider', ancien_provider)
        set_setting('provider_routing', ancien_routing)
        print('[REPRO] Settings restaures (provider=%r).' % ancien_provider)


if __name__ == '__main__':
    asyncio.run(main(lire_arguments()))
