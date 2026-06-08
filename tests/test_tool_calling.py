# -*- coding: utf-8 -*-
"""
Test rapide du pipeline tool calling.
Lance NIMM en arriere-plan et envoie 3 messages via HTTP.
Verifie que les logs terminal montrent le tool calling en action.
"""
import asyncio
import httpx
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

BASE = "http://localhost:8080"

TESTS = [
    ("j'habite ou ?",           "search_memory attendu"),
    ("quelle est la capitale de la France ?", "aucun tool attendu"),
    ("tu te souviens de nos conversations sur la couture ?", "search_bibliotheque attendu"),
]

async def send_message(client, msg):
    """Envoie un message et collecte la reponse complete."""
    # Creer un fil temporaire
    r = await client.post(f"{BASE}/api/threads", json={"name": "test_tool"})
    thread_id = r.json()["thread_id"]

    chunks = []
    async with client.stream(
        "POST", f"{BASE}/api/chat/stream",
        json={"thread_id": thread_id, "message": msg},
        timeout=30
    ) as r:
        async for line in r.aiter_lines():
            if line.startswith("data:") and "[DONE]" not in line and "[META]" not in line:
                chunks.append(line[5:].strip())

    # Nettoyer le fil
    await client.delete(f"{BASE}/api/threads/{thread_id}")
    return " ".join(chunks)

async def main():
    print("\n=== TEST TOOL CALLING ===\n")
    print("[INFO] Surveille les logs NIMM pour les lignes [HUB] Tool ...\n")
    async with httpx.AsyncClient(base_url=BASE) as client:
        for msg, attendu in TESTS:
            print(f"> Message : {msg!r}")
            print(f"  Attendu  : {attendu}")
            try:
                reply = await send_message(client, msg)
                # Nettoyer les caracteres non-ASCII pour l'affichage
                safe_reply = reply.encode('ascii', 'replace').decode('ascii')
                print(f"  Reponse  : {safe_reply[:120]}...")
            except Exception as e:
                safe_err = str(e).encode('ascii', 'replace').decode('ascii')
                print(f"  ERR Erreur : {safe_err}")
            print()

asyncio.run(main())
