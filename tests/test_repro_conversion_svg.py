# -*- coding: utf-8 -*-
"""Reproduction autonome : conversion SVG -> PNG via le VRAI chemin du chat.

Appelle core.hub.process_message_stream() -- la fonction exacte servie par la
route /api/chat/stream -- sur un thread neuf, avec le fournisseur force sur
'mistral' (celui qui plante). Le flux suit son cours normal (boucle d'outils
du Bloc #01 incluse). A chaque appel API, engine.py emet [DEBUG-MESSAGES]
(index, role, content rempli/vide, tool_calls present/absent, tool_call_id) ;
en cas d'echec, [DEBUG-ERROR] affiche le corps brut de la requete et de la
reponse. Ce script ne fait que consommer le flux et afficher les evenements.
"""
import asyncio
import json
import os
import sys
import uuid

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import get_setting, set_setting, set_user_context  # noqa: E402
from core.hub import process_message_stream  # noqa: E402

UTILISATEUR = 'laurent'
THREAD_ID = 'repro-svg-' + uuid.uuid4().hex[:12]
USER_MESSAGE = (r"Peux-tu convertir ce fichier .svg en .png ? "
                r"Le chemin est C:\Users\Supalol\Desktop\Inkscaperies\Greiner Schleret Prestation.svg")


async def main():
    print('=' * 72)
    print('[REPRO] Utilisateur : ' + UTILISATEUR)
    print('[REPRO] Thread neuf  : ' + THREAD_ID)
    print('[REPRO] Message      : ' + USER_MESSAGE)
    print('[REPRO] Fournisseur  : mistral (force via routing)')
    print('=' * 72)

    set_user_context(UTILISATEUR)
    ancien_provider = get_setting('provider', '')
    ancien_routing = get_setting('provider_routing', '{}')

    # Forcer le chat sur mistral (source unique de load_settings)
    routing = json.loads(ancien_routing or '{}')
    routing['chat'] = 'mistral'
    set_setting('provider_routing', json.dumps(routing))

    try:
        n = 0
        async for chunk in process_message_stream(
            thread_id=THREAD_ID,
            user_message=USER_MESSAGE,
            web_search=False,
        ):
            n += 1
            print(f'[SSE #{n}] {chunk!r}')
        print('[REPRO] Flux termine normalement (' + str(n) + ' evenements).')
    except Exception as e:
        print('[REPRO] EXCEPTION remontee : ' + repr(e))
    finally:
        # Restauration du routing du profil
        set_setting('provider', ancien_provider)
        set_setting('provider_routing', ancien_routing)
        print('[REPRO] Settings restaures (provider=%r).' % ancien_provider)


if __name__ == '__main__':
    asyncio.run(main())
