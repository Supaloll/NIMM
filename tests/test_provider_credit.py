# -*- coding: utf-8 -*-
"""
Test hors-ligne de get_provider_credit() (httpx simulé, aucune vraie clé).

Vérifie :
  1. OpenRouter — total_credits - total_usage.
  2. DeepSeek — balance_infos[0].total_balance.
  3. Stability AI — credits.
  4. Pas de clé configurée → {'available': False, 'reason': 'no_key'}.
  5. Provider non supporté → {'available': False, 'reason': 'unsupported_provider'}.
  6. Erreur réseau/API → {'available': False, 'reason': '...'} (pas d'exception).
"""
import asyncio
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import engine


class FakeResponse:
    def __init__(self, data, status_ok=True):
        self._data = data
        self._status_ok = status_ok
    def raise_for_status(self):
        if not self._status_ok:
            raise RuntimeError("HTTP error")
    def json(self):
        return self._data


class FakeClient:
    """Remplace engine.httpx.AsyncClient. Renvoie une réponse fixe sur GET."""
    next_response = None
    next_ok = True
    captured = {}

    def __init__(self, *a, **k):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def get(self, url, headers=None, **k):
        FakeClient.captured['url'] = url
        FakeClient.captured['headers'] = headers
        return FakeResponse(FakeClient.next_response, FakeClient.next_ok)


class FakeHttpx:
    AsyncClient = FakeClient


def _install():
    engine.httpx = FakeHttpx()


async def test_openrouter():
    FakeClient.next_response = {'data': {'total_credits': 20.0, 'total_usage': 3.5}}
    FakeClient.next_ok = True
    res = await engine.get_provider_credit('openrouter', {'openrouter': 'sk-or-fake'})
    assert res == {'available': True, 'balance': 16.5, 'currency': 'USD'}, res
    assert 'openrouter.ai' in FakeClient.captured['url']
    print("OK  openrouter → solde calculé")


async def test_deepseek():
    FakeClient.next_response = {
        'is_available': True,
        'balance_infos': [{'currency': 'USD', 'total_balance': '12.34'}],
    }
    FakeClient.next_ok = True
    res = await engine.get_provider_credit('deepseek', {'deepseek': 'sk-fake'})
    assert res == {'available': True, 'balance': 12.34, 'currency': 'USD'}, res
    print("OK  deepseek → solde lu")


async def test_stability():
    FakeClient.next_response = {'credits': 87.5}
    FakeClient.next_ok = True
    res = await engine.get_provider_credit('stability-ai', {'stability-ai': 'sk-fake'})
    assert res == {'available': True, 'balance': 87.5, 'currency': 'crédits'}, res
    print("OK  stability-ai → solde lu")


async def test_no_key():
    res = await engine.get_provider_credit('openrouter', {})
    assert res == {'available': False, 'reason': 'no_key'}, res
    print("OK  pas de clé → no_key")


async def test_unsupported_provider():
    res = await engine.get_provider_credit('mistral', {'mistral': 'fake'})
    assert res == {'available': False, 'reason': 'unsupported_provider'}, res
    print("OK  provider non supporté → unsupported_provider")


async def test_api_error():
    FakeClient.next_response = {}
    FakeClient.next_ok = False
    res = await engine.get_provider_credit('deepseek', {'deepseek': 'sk-fake'})
    assert res['available'] is False and 'reason' in res, res
    print("OK  erreur API → reason sans exception")


async def main():
    _install()
    print("\n=== TEST CRÉDIT PROVIDER (hors-ligne) ===\n")
    await test_openrouter()
    await test_deepseek()
    await test_stability()
    await test_no_key()
    await test_unsupported_provider()
    await test_api_error()
    print("\nTous les tests passent.\n")


if __name__ == '__main__':
    asyncio.run(main())
