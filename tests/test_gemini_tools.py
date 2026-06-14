# -*- coding: utf-8 -*-
"""
Test hors-ligne du tool-calling Gemini (httpx simulé, aucune vraie clé).

Vérifie :
  1. Phase 1 — réponse functionCall → événement 'tool_calls' au bon format.
  2. Phase 1 — réponse texte → événement 'token'.
  3. Phase 2 — _call_gemini avec messages d'outils (assistant tool_calls + tool)
     convertit bien en functionCall / functionResponse dans le payload envoyé.
"""
import asyncio
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import engine

# Clé bidon : get_api_key la trouvera via api_keys passé explicitement.
API_KEYS = {'gemini': 'FAKE'}

TOOLS = [{
    "type": "function",
    "function": {
        "name": "search_memory",
        "description": "Cherche dans la mémoire.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "terme"}},
            "required": ["query"],
        },
    },
}]


class FakeResponse:
    def __init__(self, data):
        self._data = data
    def raise_for_status(self):
        pass
    def json(self):
        return self._data


class FakeClient:
    """Remplace engine.httpx.AsyncClient. Capture le payload, renvoie une réponse fixe."""
    captured = {}
    next_response = None

    def __init__(self, *a, **k):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def post(self, url, json=None, headers=None, **k):
        FakeClient.captured['url'] = url
        FakeClient.captured['payload'] = json
        return FakeResponse(FakeClient.next_response)


class FakeHttpx:
    AsyncClient = FakeClient


def _install():
    engine.httpx = FakeHttpx()


async def collect(gen):
    return [ev async for ev in gen]


async def test_phase1_functioncall():
    FakeClient.next_response = {
        'candidates': [{'content': {'parts': [
            {'functionCall': {'name': 'search_memory', 'args': {'query': 'domicile'}}}
        ]}}],
        'usageMetadata': {'promptTokenCount': 10, 'candidatesTokenCount': 5},
    }
    messages = [{'role': 'user', 'content': 'j\'habite où ?'}]
    evs = await collect(engine._gemini_tools_turn(
        messages, TOOLS, 'gemini-2.0-flash', 'Tu es NIMM.', 512, 0.7, API_KEYS))

    assert len(evs) == 1, evs
    ev = evs[0]
    assert ev['type'] == 'tool_calls', ev
    assert ev['calls'][0]['name'] == 'search_memory'
    assert ev['calls'][0]['args'] == {'query': 'domicile'}
    # assistant_msg au format OpenAI (arguments = chaîne JSON)
    tc = ev['assistant_msg']['tool_calls'][0]
    assert tc['function']['name'] == 'search_memory'
    assert json.loads(tc['function']['arguments']) == {'query': 'domicile'}
    # Le payload phase 1 doit contenir les functionDeclarations.
    decls = FakeClient.captured['payload']['tools'][0]['functionDeclarations']
    assert decls[0]['name'] == 'search_memory'
    assert decls[0]['parameters']['required'] == ['query']
    print("OK  phase 1 functionCall → tool_calls")


async def test_phase1_text():
    FakeClient.next_response = {
        'candidates': [{'content': {'parts': [{'text': 'La capitale est Paris.'}]}}],
        'usageMetadata': {},
    }
    messages = [{'role': 'user', 'content': 'capitale de la France ?'}]
    evs = await collect(engine._gemini_tools_turn(
        messages, TOOLS, 'gemini-2.0-flash', None, 512, 0.7, API_KEYS))

    assert len(evs) == 1
    assert evs[0]['type'] == 'token'
    assert evs[0]['text'] == 'La capitale est Paris.'
    print("OK  phase 1 texte → token")


async def test_phase2_tool_messages():
    """Phase 2 : le hub rejoue assistant(tool_calls) + message tool, sans outils."""
    FakeClient.next_response = {
        'candidates': [{'content': {'parts': [{'text': 'Tu habites à Lyon.'}]}}],
        'usageMetadata': {},
    }
    messages = [
        {'role': 'user', 'content': 'j\'habite où ?'},
        {'role': 'assistant', 'content': '',
         'tool_calls': [{'id': 'gemini_0_search_memory', 'type': 'function',
                         'function': {'name': 'search_memory',
                                      'arguments': '{"query": "domicile"}'}}]},
        {'role': 'tool', 'tool_call_id': 'gemini_0_search_memory',
         'content': 'Fernando habite à Lyon.'},
    ]
    out = await engine._call_gemini(
        messages, 'gemini-2.0-flash', 'Tu es NIMM.', 512, 0.7, API_KEYS)

    assert out == 'Tu habites à Lyon.', out
    contents = FakeClient.captured['payload']['contents']
    # user / model(functionCall) / user(functionResponse)
    assert contents[0]['role'] == 'user'
    assert contents[1]['role'] == 'model'
    fc = contents[1]['parts'][0]['functionCall']
    assert fc['name'] == 'search_memory'
    assert fc['args'] == {'query': 'domicile'}
    assert contents[2]['role'] == 'user'
    fr = contents[2]['parts'][0]['functionResponse']
    assert fr['name'] == 'search_memory'
    assert fr['response'] == {'result': 'Fernando habite à Lyon.'}
    print("OK  phase 2 tool_calls/tool → functionCall/functionResponse")


async def main():
    _install()
    print("\n=== TEST GEMINI TOOL-CALLING (hors-ligne) ===\n")
    await test_phase1_functioncall()
    await test_phase1_text()
    await test_phase2_tool_messages()
    print("\nTous les tests passent.\n")


asyncio.run(main())
