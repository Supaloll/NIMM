# -*- coding: utf-8 -*-
"""
Diagnostic tool calling — verifie que DeepSeek appelle bien les outils.
Necessite NIMM demarre. Affiche les logs tool en temps reel.
"""
import asyncio
import httpx
import sys
sys.stdout.reconfigure(encoding='utf-8')

BASE = "http://localhost:8080"

async def main():
    async with httpx.AsyncClient(base_url=BASE) as client:

        # Creer un fil de test
        r = await client.post(f"{BASE}/api/threads", json={"name": "_diag_tool"})
        thread_id = r.json()["thread_id"]
        print(f"Fil cree : {thread_id}\n")

        tests = [
            "j'habite ou ?",
            "quel est mon metier ?",
            "qui est Nadia ?",
        ]

        for msg in tests:
            print(f"> Envoi : {msg!r}")
            chunks = []
            async with client.stream(
                "POST", f"{BASE}/api/chat/stream",
                json={"thread_id": thread_id, "message": msg},
                timeout=30
            ) as r:
                async for line in r.aiter_lines():
                    if line.startswith("data:") and "[DONE]" not in line and "[META]" not in line and "[ERREUR" not in line:
                        text = line[5:].replace("\\n", "\n").strip()
                        if text:
                            chunks.append(text)
            print(f"  Reponse : {''.join(chunks)[:150]}")
            print()

        # Nettoyage
        await client.delete(f"{BASE}/api/threads/{thread_id}")
        print("OK Fin du test - verifie les lignes [HUB] Tool dans le terminal NIMM")

asyncio.run(main())
