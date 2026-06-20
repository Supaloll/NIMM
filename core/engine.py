# ============================================
# NIMM — core/engine.py
# Moteur LLM multi-providers
# Providers : Anthropic / DeepSeek / Gemini / OpenAI / Ollama / OpenRouter
# ============================================

import os
import json
import httpx
from typing import Optional

def _log(provider: str, model: str, tokens_in: int, tokens_out: int, pipeline: str = 'chat'):
    """Log silencieux — ne bloque jamais le pipeline si DB indisponible."""
    try:
        from core.database import log_cost
        log_cost(provider, model or '', tokens_in, tokens_out, pipeline)
    except Exception:
        pass

# ── Clés API (priorité : base de données > .env) ──
def get_api_key(provider: str, db_keys: dict = None) -> Optional[str]:
    if db_keys and db_keys.get(provider):
        return db_keys[provider]
    env_map = {
        'anthropic':  'ANTHROPIC_API_KEY',
        'deepseek':   'DEEPSEEK_API_KEY',
        'gemini':     'GEMINI_API_KEY',
        'openai':     'OPENAI_API_KEY',
        'openrouter': 'OPENROUTER_API_KEY',
        'mistral':    'MISTRAL_API_KEY',
        'tavily':     'TAVILY_API_KEY',
    }
    return os.getenv(env_map.get(provider, ''))


# ══════════════════════════════════════════
# APPEL LLM PRINCIPAL
# ══════════════════════════════════════════

_PROVIDER_DEFAULT_MODEL = {
    'anthropic':  'claude-opus-4-5',
    'deepseek':   'deepseek-chat',
    'openai':     'gpt-4o-mini',
    'openrouter': 'openai/gpt-4o-mini',
    'mistral':    'mistral-small-latest',
    'gemini':     'gemini-1.5-flash',
    'ollama':     'llama3.1:8b',
}

# Préfixe de nom de modèle → fournisseur propriétaire (détection d'incohérence)
_MODEL_OWNER = {
    'claude': 'anthropic', 'deepseek': 'deepseek', 'gpt': 'openai',
    'o1': 'openai', 'o3': 'openai', 'o4': 'openai',
    'mistral': 'mistral', 'ministral': 'mistral', 'pixtral': 'mistral', 'codestral': 'mistral',
    'gemini': 'gemini',
}


def _resolve_model(provider, model):
    """Évite les 400 « modèle invalide » au changement de fournisseur : si le modèle
    sélectionné appartient visiblement à un autre fournisseur, on retombe sur le
    modèle par défaut du fournisseur courant. Les modèles inconnus (tags Ollama,
    modèles OpenRouter en vendor/x) sont laissés intacts."""
    provider = (provider or '').lower()
    if not model:
        return _PROVIDER_DEFAULT_MODEL.get(provider)
    if provider == 'openrouter':
        return model
    ml = model.lower()
    for prefix, owner in _MODEL_OWNER.items():
        if ml.startswith(prefix):
            return model if owner == provider else _PROVIDER_DEFAULT_MODEL.get(provider, model)
    return model


async def call_llm(
    messages: list,
    provider: str = 'anthropic',
    model: str = None,
    system_prompt: str = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    api_keys: dict = None,
    images: list = None,        # [{"data": base64, "media_type": "image/jpeg"}]
    tools: list = None,
) -> str:
    """
    Point d'entrée unique pour tous les providers.
    Retourne le texte de la réponse.
    """
    provider = provider.lower()
    model = _resolve_model(provider, model)

    if provider == 'anthropic':
        return await _call_anthropic(messages, model, system_prompt, max_tokens, temperature, api_keys, images, tools=tools)
    elif provider == 'deepseek':
        return await _call_openai_compat(messages, model or 'deepseek-chat', system_prompt, max_tokens, temperature, api_keys, 'deepseek', 'https://api.deepseek.com/v1', images=images)
    elif provider == 'gemini':
        return await _call_gemini(messages, model, system_prompt, max_tokens, temperature, api_keys, tools=tools)
    elif provider == 'openai':
        return await _call_openai_compat(messages, model or 'gpt-4o', system_prompt, max_tokens, temperature, api_keys, 'openai', 'https://api.openai.com/v1', images=images)
    elif provider == 'openrouter':
        return await _call_openai_compat(messages, model or 'mistralai/mistral-7b-instruct', system_prompt, max_tokens, temperature, api_keys, 'openrouter', 'https://openrouter.ai/api/v1', images=images)
    elif provider == 'mistral':
        return await _call_openai_compat(messages, model or 'mistral-small-latest', system_prompt, max_tokens, temperature, api_keys, 'mistral', 'https://api.mistral.ai/v1', images=images)
    elif provider == 'ollama':
        return await _call_ollama(messages, model or 'llama3', system_prompt, max_tokens, temperature)
    else:
        raise ValueError(f"Provider inconnu : {provider}")


# ══════════════════════════════════════════
# ANTHROPIC
# ══════════════════════════════════════════

def _oai_tools_to_anthropic(tools):
    """Schéma d'outils OpenAI → Anthropic (input_schema = parameters)."""
    out = []
    for t in tools or []:
        fn = t.get('function', t)
        out.append({
            'name':         fn.get('name', ''),
            'description':  fn.get('description', ''),
            'input_schema': fn.get('parameters', {'type': 'object', 'properties': {}}),
        })
    return out


def _oai_msgs_to_anthropic(messages):
    """Messages OpenAI (tool_calls d'assistant, messages 'tool') → format Anthropic :
    blocs tool_use dans l'assistant, tool_result regroupés dans un message user."""
    out = []
    for m in messages:
        role = m.get('role')
        if role == 'system':
            continue
        if role == 'assistant' and m.get('tool_calls'):
            blocks = []
            if m.get('content'):
                blocks.append({'type': 'text', 'text': m['content']})
            for tc in m['tool_calls']:
                fn = tc.get('function', {})
                args = fn.get('arguments', {})
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except Exception: args = {}
                blocks.append({'type': 'tool_use', 'id': tc.get('id', ''),
                               'name': fn.get('name', ''), 'input': args})
            out.append({'role': 'assistant', 'content': blocks})
        elif role == 'tool':
            block = {'type': 'tool_result', 'tool_use_id': m.get('tool_call_id', ''),
                     'content': m.get('content', '')}
            if (out and out[-1]['role'] == 'user' and isinstance(out[-1]['content'], list)
                    and out[-1]['content'] and out[-1]['content'][0].get('type') == 'tool_result'):
                out[-1]['content'].append(block)
            else:
                out.append({'role': 'user', 'content': [block]})
        else:
            out.append({'role': role, 'content': m.get('content', '')})
    return out


async def _call_anthropic(messages, model, system_prompt, max_tokens, temperature, api_keys, images, tools=None):
    api_key = get_api_key('anthropic', api_keys)
    if not api_key:
        raise ValueError("Clé API Anthropic manquante.")

    model = model or 'claude-opus-4-5'

    # Construire les messages au format Anthropic (gère tool_use / tool_result)
    anthropic_messages = _oai_msgs_to_anthropic(messages)

    # Injecter les images dans le dernier message user si présentes
    if images and anthropic_messages:
        last = anthropic_messages[-1]
        if last['role'] == 'user' and isinstance(last['content'], str):
            content_blocks = []
            for img in images:
                content_blocks.append({
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': img['media_type'],
                        'data': img['data']
                    }
                })
            content_blocks.append({'type': 'text', 'text': last['content']})
            last['content'] = content_blocks

    payload = {
        'model':      model,
        'max_tokens': max_tokens,
        'temperature': temperature,
        'messages':   anthropic_messages,
    }
    if system_prompt:
        payload['system'] = system_prompt
    if tools:
        payload['tools'] = _oai_tools_to_anthropic(tools)

    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key':         api_key,
                'anthropic-version': '2023-06-01',
                'content-type':      'application/json',
            },
            json=payload
        )
        r.raise_for_status()
        data = r.json()
        usage = data.get('usage', {})
        _log('anthropic', model, usage.get('input_tokens', 0), usage.get('output_tokens', 0))
        return ''.join(b.get('text', '') for b in data.get('content', []) if b.get('type') == 'text')


async def _anthropic_tools_turn(messages, tools, model, system_prompt, max_tokens, temperature, api_keys):
    """Phase 1 Anthropic : un appel avec outils. Émet soit un événement tool_calls,
    soit le texte en tokens."""
    api_key = get_api_key('anthropic', api_keys)
    if not api_key:
        raise ValueError("Clé API Anthropic manquante.")
    model = model or 'claude-opus-4-5'

    payload = {
        'model':       model,
        'max_tokens':  max_tokens,
        'temperature': temperature,
        'messages':    _oai_msgs_to_anthropic(messages),
        'tools':       _oai_tools_to_anthropic(tools),
    }
    if system_prompt:
        payload['system'] = system_prompt

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            'https://api.anthropic.com/v1/messages',
            headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
            json=payload
        )
        r.raise_for_status()
        data = r.json()

    usage = data.get('usage', {})
    _log('anthropic', model, usage.get('input_tokens', 0), usage.get('output_tokens', 0))
    content = data.get('content', []) or []
    tool_uses = [b for b in content if b.get('type') == 'tool_use']
    if tool_uses:
        calls, oai_tcs = [], []
        for b in tool_uses:
            calls.append({'name': b.get('name', ''), 'args': b.get('input', {}) or {}, 'id': b.get('id', '')})
            oai_tcs.append({
                'id': b.get('id', ''), 'type': 'function',
                'function': {'name': b.get('name', ''),
                             'arguments': json.dumps(b.get('input', {}) or {}, ensure_ascii=False)}
            })
        text = ''.join(b.get('text', '') for b in content if b.get('type') == 'text')
        assistant_msg = {'role': 'assistant', 'content': text, 'tool_calls': oai_tcs}
        yield {'type': 'tool_calls', 'calls': calls, 'assistant_msg': assistant_msg}
    else:
        text = ''.join(b.get('text', '') for b in content if b.get('type') == 'text')
        yield {'type': 'token', 'text': text}


# ══════════════════════════════════════════
# OPENAI-COMPATIBLE (DeepSeek / OpenAI / OpenRouter)
# ══════════════════════════════════════════

async def _call_openai_compat(messages, model, system_prompt, max_tokens, temperature, api_keys, provider_name, base_url, images=None, tools=None):
    api_key = get_api_key(provider_name, api_keys)
    if not api_key:
        raise ValueError(f"Clé API {provider_name} manquante.")

    oai_messages = []
    if system_prompt:
        oai_messages.append({'role': 'system', 'content': system_prompt})
    for m in messages:
        if m.get('role') != 'system':
            # Passer le message complet — préserve tool_calls et tool_call_id
            oai_messages.append(m)

    # Vision : injecter les images dans le dernier message utilisateur (format OpenAI image_url).
    if images:
        for msg in reversed(oai_messages):
            if msg.get('role') == 'user':
                txt = msg.get('content') if isinstance(msg.get('content'), str) else ''
                content = [{'type': 'text', 'text': txt}] if txt else []
                for img in images:
                    content.append({
                        'type': 'image_url',
                        'image_url': {'url': f"data:{img['media_type']};base64,{img['data']}"}
                    })
                msg['content'] = content
                break

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type':  'application/json',
    }
    if provider_name == 'openrouter':
        headers['HTTP-Referer'] = 'https://nimm.local'
        headers['X-Title']      = 'NIMM'

    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            f'{base_url}/chat/completions',
            headers=headers,
            json={
                'model':       model,
                'messages':    oai_messages,
                'max_tokens':  max_tokens,
                'temperature': temperature,
                **({'tools': tools} if tools else {}),
            }
        )
        r.raise_for_status()
        data = r.json()
        usage = data.get('usage', {})
        _log(provider_name, model, usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0))
        return data['choices'][0]['message']['content']


# ══════════════════════════════════════════
# GEMINI
# ══════════════════════════════════════════

def _oai_tools_to_gemini(tools):
    """Schéma d'outils OpenAI → Gemini (functionDeclarations).
    Les schémas de paramètres NIMM (type/properties/required/description) sont
    acceptés tels quels par Gemini."""
    decls = []
    for t in tools or []:
        fn   = t.get('function', t)
        decl = {'name': fn.get('name', ''), 'description': fn.get('description', '')}
        params = fn.get('parameters')
        if params and params.get('properties'):
            decl['parameters'] = params
        decls.append(decl)
    return [{'functionDeclarations': decls}]


def _oai_msgs_to_gemini(messages):
    """Messages OpenAI (tool_calls d'assistant, messages 'tool') → contents Gemini.
    Un tool_call devient un part functionCall dans un content 'model' ; un message
    'tool' devient un part functionResponse dans un content 'user'. Gemini exige le
    nom de la fonction dans functionResponse : on le retrouve via la carte id→nom
    bâtie à partir des tool_calls de l'assistant."""
    out = []
    id_to_name = {}
    for m in messages:
        role = m.get('role')
        if role == 'system':
            continue
        if role == 'assistant' and m.get('tool_calls'):
            parts = []
            if m.get('content'):
                parts.append({'text': m['content']})
            for tc in m['tool_calls']:
                fn   = tc.get('function', {})
                name = fn.get('name', '')
                args = fn.get('arguments', {})
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except Exception: args = {}
                id_to_name[tc.get('id', '')] = name
                parts.append({'functionCall': {'name': name, 'args': args or {}}})
            out.append({'role': 'model', 'parts': parts})
        elif role == 'tool':
            name = id_to_name.get(m.get('tool_call_id', ''), '')
            out.append({'role': 'user', 'parts': [{
                'functionResponse': {
                    'name':     name,
                    'response': {'result': m.get('content', '')},
                }
            }]})
        else:
            gem_role = 'user' if role == 'user' else 'model'
            out.append({'role': gem_role, 'parts': [{'text': m.get('content', '') or ''}]})
    return out


async def _call_gemini(messages, model, system_prompt, max_tokens, temperature, api_keys, tools=None):
    api_key = get_api_key('gemini', api_keys)
    if not api_key:
        raise ValueError("Clé API Gemini manquante.")

    model = model or 'gemini-2.0-flash'

    payload = {
        'contents': _oai_msgs_to_gemini(messages),
        'generationConfig': {
            'maxOutputTokens': max_tokens,
            'temperature':     temperature,
        }
    }
    if tools:
        payload['tools'] = _oai_tools_to_gemini(tools)
    if system_prompt:
        payload['systemInstruction'] = {'parts': [{'text': system_prompt}]}

    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}',
            json=payload
        )
        r.raise_for_status()
        data = r.json()
        meta = data.get('usageMetadata', {})
        _log('gemini', model, meta.get('promptTokenCount', 0), meta.get('candidatesTokenCount', 0))
        parts = (data.get('candidates') or [{}])[0].get('content', {}).get('parts', []) or []
        return ''.join(p.get('text', '') for p in parts if 'text' in p)


async def _gemini_tools_turn(messages, tools, model, system_prompt, max_tokens, temperature, api_keys):
    """Phase 1 Gemini : un appel avec outils. Émet soit un événement tool_calls,
    soit le texte en tokens."""
    api_key = get_api_key('gemini', api_keys)
    if not api_key:
        raise ValueError("Clé API Gemini manquante.")
    model = model or 'gemini-2.0-flash'

    payload = {
        'contents': _oai_msgs_to_gemini(messages),
        'tools':    _oai_tools_to_gemini(tools),
        'generationConfig': {
            'maxOutputTokens': max_tokens,
            'temperature':     temperature,
        }
    }
    if system_prompt:
        payload['systemInstruction'] = {'parts': [{'text': system_prompt}]}

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}',
            json=payload
        )
        r.raise_for_status()
        data = r.json()

    meta = data.get('usageMetadata', {})
    _log('gemini', model, meta.get('promptTokenCount', 0), meta.get('candidatesTokenCount', 0))
    parts  = (data.get('candidates') or [{}])[0].get('content', {}).get('parts', []) or []
    fcalls = [p['functionCall'] for p in parts if 'functionCall' in p]
    if fcalls:
        calls, oai_tcs = [], []
        for i, fc in enumerate(fcalls):
            name = fc.get('name', '')
            args = fc.get('args', {}) or {}
            cid  = f"gemini_{i}_{name}"
            calls.append({'name': name, 'args': args, 'id': cid})
            oai_tcs.append({
                'id': cid, 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}
            })
        text = ''.join(p.get('text', '') for p in parts if 'text' in p)
        assistant_msg = {'role': 'assistant', 'content': text, 'tool_calls': oai_tcs}
        yield {'type': 'tool_calls', 'calls': calls, 'assistant_msg': assistant_msg}
    else:
        text = ''.join(p.get('text', '') for p in parts if 'text' in p)
        yield {'type': 'token', 'text': text}


# ══════════════════════════════════════════
# OLLAMA (local)
# ══════════════════════════════════════════

def _oai_msgs_to_ollama(messages):
    """Convertit des messages au format OpenAI (y compris tool_calls d'assistant et
    messages 'tool') vers le format Ollama (arguments en objet, pas d'id)."""
    out = []
    for m in messages:
        role = m.get('role')
        if role == 'system':
            continue
        if role == 'assistant' and m.get('tool_calls'):
            tcs = []
            for tc in m['tool_calls']:
                fn = tc.get('function', {})
                args = fn.get('arguments', {})
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except Exception: args = {}
                tcs.append({'function': {'name': fn.get('name', ''), 'arguments': args}})
            out.append({'role': 'assistant', 'content': m.get('content') or '', 'tool_calls': tcs})
        elif role == 'tool':
            out.append({'role': 'tool', 'content': m.get('content', '')})
        else:
            out.append({'role': role, 'content': m.get('content', '')})
    return out


async def _call_ollama(messages, model, system_prompt, max_tokens, temperature):
    ollama_messages = []
    if system_prompt:
        ollama_messages.append({'role': 'system', 'content': system_prompt})
    ollama_messages.extend(_oai_msgs_to_ollama(messages))

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            'http://localhost:11434/api/chat',
            json={
                'model':    model,
                'messages': ollama_messages,
                'stream':   False,
                'options':  {
                    'num_predict': max_tokens,
                    'temperature': temperature,
                }
            }
        )
        r.raise_for_status()
        data = r.json()
        _log('ollama', model or 'llama3', data.get('prompt_eval_count', 0), data.get('eval_count', 0))
        return data['message']['content']


async def _ollama_tools_turn(messages, tools, model, system_prompt, max_tokens, temperature):
    """Phase 1 Ollama : un appel avec outils. Émet soit un événement tool_calls,
    soit le texte en tokens. Ollama accepte le format d'outils OpenAI tel quel."""
    ollama_messages = []
    if system_prompt:
        ollama_messages.append({'role': 'system', 'content': system_prompt})
    ollama_messages.extend(_oai_msgs_to_ollama(messages))

    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(
            'http://localhost:11434/api/chat',
            json={
                'model':    model or 'llama3.1',
                'messages': ollama_messages,
                'tools':    tools,
                'stream':   False,
                'options':  {'num_predict': max_tokens, 'temperature': temperature},
            }
        )
        r.raise_for_status()
        data = r.json()

    msg = data.get('message', {}) or {}
    _log('ollama', model or 'llama3.1', data.get('prompt_eval_count', 0), data.get('eval_count', 0))
    tcs = msg.get('tool_calls') or []
    if tcs:
        calls, oai_tcs = [], []
        for i, tc in enumerate(tcs):
            fn   = tc.get('function', {})
            name = fn.get('name', '')
            args = fn.get('arguments', {})
            if isinstance(args, str):
                try: args = json.loads(args)
                except Exception: args = {}
            cid = f"ollama_{i}_{name}"
            calls.append({'name': name, 'args': args, 'id': cid})
            oai_tcs.append({
                'id': cid, 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}
            })
        assistant_msg = {'role': 'assistant', 'content': msg.get('content') or '', 'tool_calls': oai_tcs}
        yield {'type': 'tool_calls', 'calls': calls, 'assistant_msg': assistant_msg}
    else:
        yield {'type': 'token', 'text': msg.get('content', '')}


# ══════════════════════════════════════════
# EXTRACTION JSON (utilitaire partagé)
# ══════════════════════════════════════════

def extract_json(text: str) -> Optional[dict]:
    """
    Extrait le premier bloc JSON valide d'une réponse LLM.
    Utilisé par le module mémoire et d'autres modules.
    """
    import re
    # Chercher un bloc ```json ... ```
    match = re.search(r'```json\s*([\s\S]*?)```', text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Chercher accolades directes
    match = re.search(r'(\{[\s\S]*\})', text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return None


# ══════════════════════════════════════════
# GEMINI VISION
# ══════════════════════════════════════════

async def call_gemini_vision(image_b64: str, media_type: str, prompt: str, api_keys: dict) -> str:
    """Analyse une image via Gemini Vision."""
    api_key = get_api_key('gemini', api_keys)
    if not api_key:
        raise ValueError("Clé API Gemini manquante.")
    payload = {
        'contents': [{
            'role': 'user',
            'parts': [
                {'inline_data': {'mime_type': media_type, 'data': image_b64}},
                {'text': prompt}
            ]
        }],
        'generationConfig': {'maxOutputTokens': 1024, 'temperature': 0.2}
    }
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}',
            json=payload
        )
        r.raise_for_status()
        data = r.json()
        return data['candidates'][0]['content']['parts'][0]['text']


async def call_vision(image_b64: str, media_type: str, prompt: str,
                      vision_provider: str, api_keys: dict) -> str:
    """
    Analyse d'image — routage selon vision_provider.
    Gemini : API dédiée. Anthropic/OpenAI/Ollama : call_llm avec images.
    """
    provider = vision_provider.lower() if vision_provider else 'gemini'

    if provider in ('gemini', 'auto', ''):
        return await call_gemini_vision(image_b64, media_type, prompt, api_keys)

    elif provider in ('anthropic', 'openai', 'ollama', 'mistral'):
        images = [{'data': image_b64, 'media_type': media_type}]
        return await call_llm(
            messages=[{'role': 'user', 'content': prompt}],
            provider=provider,
            model=None,
            system_prompt='Tu es un assistant qui décrit précisément des images en français.',
            max_tokens=1024,
            temperature=0.2,
            api_keys=api_keys,
            images=images,
        )

    else:
        # Fallback Gemini si provider inconnu
        return await call_gemini_vision(image_b64, media_type, prompt, api_keys)


# ══════════════════════════════════════════
# STREAMING
# ══════════════════════════════════════════

async def _call_openai_compat_stream(messages, model, system_prompt, max_tokens, temperature, api_keys, provider_name, base_url, tools=None):
    """Stream tokens via API OpenAI-compatible (DeepSeek, OpenAI, OpenRouter)."""
    api_key = get_api_key(provider_name, api_keys)
    if not api_key:
        raise ValueError(f"Clé API {provider_name} manquante.")
    oai_messages = []
    if system_prompt:
        oai_messages.append({'role': 'system', 'content': system_prompt})
    for m in messages:
        if m.get('role') != 'system':
            # Passer le message complet — préserve tool_calls (assistant) et tool_call_id (tool)
            oai_messages.append(m)
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type':  'application/json',
    }
    if provider_name == 'openrouter':
        headers['HTTP-Referer'] = 'https://nimm.local'
        headers['X-Title']      = 'NIMM'
    _stream_acc  = ''
    _dsml_stream = False

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            'POST',
            f'{base_url}/chat/completions',
            headers=headers,
            json={
                'model':       model,
                'messages':    oai_messages,
                'max_tokens':  max_tokens,
                'temperature': temperature,
                'stream':      True,
                **({'tools': tools} if tools else {}),
            }
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith('data:'):
                    continue
                chunk = line[5:].strip()
                if chunk == '[DONE]':
                    break
                try:
                    import json as _json
                    data = _json.loads(chunk)
                    token = data['choices'][0]['delta'].get('content', '')
                    if token:
                        _stream_acc += token
                        if not _dsml_stream and '\uff5c\uff5cDSML\uff5c\uff5c' in _stream_acc:
                            _dsml_stream = True
                        if not _dsml_stream:
                            yield token
                except Exception:
                    continue

async def _call_anthropic_stream(messages, model, system_prompt, max_tokens, temperature, api_keys, images, tools=None):
    """Stream tokens via API Anthropic."""
    api_key = get_api_key('anthropic', api_keys)
    if not api_key:
        raise ValueError("Clé API Anthropic manquante.")
    model = model or 'claude-opus-4-5'
    # Conversion OpenAI -> Anthropic : gère les messages 'tool' (rôle inexistant
    # côté Anthropic) et les tool_calls de l'assistant, sinon 400 Bad Request
    # dès qu'un outil (search_web, search_memory…) a été utilisé en phase 1.
    anthropic_messages = _oai_msgs_to_anthropic(messages)
    if images and anthropic_messages:
        last = anthropic_messages[-1]
        if last['role'] == 'user' and isinstance(last['content'], str):
            content_blocks = []
            for img in images:
                content_blocks.append({
                    'type': 'image',
                    'source': {'type': 'base64', 'media_type': img['media_type'], 'data': img['data']}
                })
            content_blocks.append({'type': 'text', 'text': last['content']})
            last['content'] = content_blocks
    payload = {
        'model':      model,
        'max_tokens': max_tokens,
        'temperature': temperature,
        'messages':   anthropic_messages,
        'stream':     True,
    }
    if system_prompt:
        payload['system'] = system_prompt
    if tools:
        payload['tools'] = _oai_tools_to_anthropic(tools)
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            'POST',
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key':         api_key,
                'anthropic-version': '2023-06-01',
                'content-type':      'application/json',
            },
            json=payload
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith('data:'):
                    continue
                chunk = line[5:].strip()
                try:
                    import json as _json
                    data = _json.loads(chunk)
                    if data.get('type') == 'content_block_delta':
                        token = data.get('delta', {}).get('text', '')
                        if token:
                            yield token
                except Exception:
                    continue

async def call_llm_stream(
    messages: list,
    provider: str = 'anthropic',
    model: str = None,
    system_prompt: str = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    api_keys: dict = None,
    images: list = None,
    tools: list = None,
    pipeline: str = 'chat',
):
    """Stream de tokens — génère les tokens un par un."""
    provider = provider.lower()
    model = _resolve_model(provider, model)
    _accumulated = []

    try:
        if provider == 'anthropic':
            async for token in _call_anthropic_stream(messages, model, system_prompt, max_tokens, temperature, api_keys, images, tools=tools):
                _accumulated.append(token)
                yield token
        elif provider in ('deepseek', 'openai', 'openrouter', 'mistral'):
            urls = {
                'deepseek':   'https://api.deepseek.com/v1',
                'openai':     'https://api.openai.com/v1',
                'openrouter': 'https://openrouter.ai/api/v1',
                'mistral':    'https://api.mistral.ai/v1',
            }
            models = {
                'deepseek':   'deepseek-chat',
                'openai':     'gpt-4o-mini',
                'openrouter': 'openai/gpt-4o-mini',
                'mistral':    'mistral-small-latest',
            }
            async for token in _call_openai_compat_stream(
                messages, model or models[provider], system_prompt,
                max_tokens, temperature, api_keys, provider, urls[provider], tools=tools
            ):
                _accumulated.append(token)
                yield token
        else:
            # Fallback : appel normal (déjà loggé dans call_llm)
            result = await call_llm(messages, provider, model, system_prompt, max_tokens, temperature, api_keys, images, tools=tools)
            _accumulated.append(result)
            yield result
            return  # call_llm a déjà loggé — on sort avant le _log stream
    finally:
        # Estimation tokens pour les streams (pas de comptage exact disponible côté API)
        if _accumulated and provider in ('anthropic', 'deepseek', 'openai', 'openrouter', 'mistral', 'gemini'):
            in_text  = (system_prompt or '') + ' '.join(str(m.get('content', '')) for m in messages)
            out_text = ''.join(_accumulated)
            est_in   = max(1, len(in_text) // 4)
            est_out  = max(1, len(out_text) // 4)
            _log(provider, model or '', est_in, est_out, pipeline)


# ══════════════════════════════════════════
# STREAM AVEC TOOL CALLING (DeepSeek / OpenAI-compat)
# ══════════════════════════════════════════

async def call_llm_stream_with_tools(
    messages: list,
    tools: list,
    provider: str = 'deepseek',
    model: str = None,
    system_prompt: str = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    api_keys: dict = None,
):
    """
    Stream avec détection de tool calls (DeepSeek / OpenAI-compat uniquement).

    Yield des événements typés :
      {"type": "token", "text": "..."}         → token normal, à envoyer au frontend
      {"type": "tool_calls", "calls": [...],
       "assistant_msg": {...}}                  → outil demandé, arrêter le stream

    Pour le provider encore non supporté (Gemini) :
    → fallback silencieux : yield uniquement des tokens normaux (pas de tool calling).
    """
    provider = provider.lower()
    model = _resolve_model(provider, model)

    if provider == 'ollama':
        async for ev in _ollama_tools_turn(messages, tools, model, system_prompt, max_tokens, temperature):
            yield ev
        return

    if provider == 'anthropic':
        async for ev in _anthropic_tools_turn(messages, tools, model, system_prompt, max_tokens, temperature, api_keys):
            yield ev
        return

    if provider == 'gemini':
        async for ev in _gemini_tools_turn(messages, tools, model, system_prompt, max_tokens, temperature, api_keys):
            yield ev
        return

    _SUPPORTED = {'deepseek', 'openai', 'openrouter', 'mistral'}
    if provider not in _SUPPORTED:
        # Fallback : stream normal sans tools (providers sans tool-calling)
        async for token in call_llm_stream(
            messages=messages,
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            api_keys=api_keys,
        ):
            yield {"type": "token", "text": token}
        return

    # ── Providers OpenAI-compat ──
    urls = {
        'deepseek':   'https://api.deepseek.com/v1',
        'openai':     'https://api.openai.com/v1',
        'openrouter': 'https://openrouter.ai/api/v1',
        'mistral':    'https://api.mistral.ai/v1',
    }
    models = {
        'deepseek':   'deepseek-chat',
        'openai':     'gpt-4o-mini',
        'openrouter': 'openai/gpt-4o-mini',
        'mistral':    'mistral-small-latest',
    }

    api_key  = get_api_key(provider, api_keys)
    if not api_key:
        raise ValueError(f"Clé API {provider} manquante.")

    base_url = urls[provider]
    _model   = model or models[provider]

    oai_messages = []
    if system_prompt:
        oai_messages.append({'role': 'system', 'content': system_prompt})
    for m in messages:
        if m['role'] != 'system':
            oai_messages.append({'role': m['role'], 'content': m['content']})

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type':  'application/json',
    }
    if provider == 'openrouter':
        headers['HTTP-Referer'] = 'https://nimm.local'
        headers['X-Title']      = 'NIMM'

    payload = {
        'model':       _model,
        'messages':    oai_messages,
        'max_tokens':  max_tokens,
        'temperature': temperature,
        'tools':       tools,
        'tool_choice': 'auto',
        'stream':      True,
    }

    # Accumulateurs pour reconstruire les tool_calls fragmentés
    _tool_calls_acc = {}   # index → {"id": str, "name": str, "arguments": str}
    _finish_reason  = None
    _raw_acc        = ''   # accumule le content brut pour détecter le DSML
    _dsml_detected  = False

    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            'POST',
            f'{base_url}/chat/completions',
            headers=headers,
            json=payload,
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith('data:'):
                    continue
                chunk = line[5:].strip()
                if chunk == '[DONE]':
                    break

                try:
                    import json as _json
                    data    = _json.loads(chunk)
                    choice  = data['choices'][0]
                    delta   = choice.get('delta', {})
                    _finish_reason = choice.get('finish_reason') or _finish_reason

                    # ── Token normal ──
                    # DeepSeek peut écrire ses tool_calls en DSML dans le content
                    # au lieu du champ structuré tool_calls. On accumule tout le
                    # content brut ; dès qu'un bloc DSML est détecté on coupe le
                    # flux visible et on laisse le post-traitement gérer.
                    text = delta.get('content', '')
                    if text:
                        _raw_acc += text
                        if not _dsml_detected and '\uff5c\uff5cDSML\uff5c\uff5c' in _raw_acc:
                            _dsml_detected = True
                        if not _dsml_detected:
                            import re as _re
                            clean = _re.sub(r'<｜[^｜>]*(?:｜[^>]*)?>?', '', text)
                            if clean:
                                yield {"type": "token", "text": clean}

                    # ── Accumulation des tool_calls fragmentés ──
                    for tc in delta.get('tool_calls', []):
                        idx = tc.get('index', 0)
                        if idx not in _tool_calls_acc:
                            _tool_calls_acc[idx] = {
                                'id':        tc.get('id', ''),
                                'name':      tc.get('function', {}).get('name', ''),
                                'arguments': '',
                            }
                        else:
                            if tc.get('id'):
                                _tool_calls_acc[idx]['id'] = tc['id']
                            if tc.get('function', {}).get('name'):
                                _tool_calls_acc[idx]['name'] = tc['function']['name']
                        _tool_calls_acc[idx]['arguments'] += tc.get('function', {}).get('arguments', '')

                except Exception:
                    continue

    # ── Fallback DSML : DeepSeek a mis le tool_call dans le content ──
    if not _tool_calls_acc and _dsml_detected:
        import re as _re
        import json as _json
        calls = []
        for m in _re.finditer(
            r'<tool_call>\s*<tool_name>\s*([^<]+?)\s*</tool_name>\s*<parameters>(.*?)</parameters>\s*</tool_call>',
            _raw_acc, _re.DOTALL
        ):
            tool_name = m.group(1).strip()
            params_text = m.group(2).strip()
            args = {}
            for p in _re.finditer(
                r'<parameter name="([^"]+)"[^>]*>(.*?)</parameter>',
                params_text, _re.DOTALL
            ):
                args[p.group(1)] = p.group(2).strip()
            calls.append({'id': f'dsml_{tool_name}', 'name': tool_name, 'args': args})
        if calls:
            assistant_msg = {
                'role': 'assistant',
                'content': None,
                'tool_calls': [
                    {
                        'id': c['id'],
                        'type': 'function',
                        'function': {
                            'name': c['name'],
                            'arguments': json.dumps(c['args'], ensure_ascii=False),
                        }
                    }
                    for c in calls
                ]
            }
            yield {"type": "tool_calls", "calls": calls, "assistant_msg": assistant_msg}

    # ── Si des tool_calls ont été accumulés ──
    # Note : DeepSeek retourne finish_reason='length' ou 'stop' même avec tool_calls,
    # on ne peut donc pas se fier uniquement à finish_reason.
    if _tool_calls_acc:
        calls = []
        for idx in sorted(_tool_calls_acc.keys()):
            tc = _tool_calls_acc[idx]
            try:
                import json as _json
                args = _json.loads(tc['arguments']) if tc['arguments'] else {}
            except Exception:
                args = {}
            calls.append({
                'id':   tc['id'],
                'name': tc['name'],
                'args': args,
            })

        # Message assistant reconstitué (nécessaire pour l'historique OpenAI)
        assistant_msg = {
            'role':       'assistant',
            'content':    None,
            'tool_calls': [
                {
                    'id':   c['id'],
                    'type': 'function',
                    'function': {
                        'name':      c['name'],
                        'arguments': json.dumps(c['args'], ensure_ascii=False),
                    }
                }
                for c in calls
            ]
        }

        yield {"type": "tool_calls", "calls": calls, "assistant_msg": assistant_msg}


# ══════════════════════════════════════════
# GÉNÉRATION IMAGE
# ══════════════════════════════════════════

async def generate_image(prompt: str, provider: str, api_keys: dict) -> dict:
    """
    Génère une image à partir d'un prompt texte.
    Retourne { 'url': str, 'b64': str, 'provider': str }
    'url' est prioritaire si présent, sinon 'b64' (base64 PNG).
    Provider principal : gemini. Fallback automatique : dall-e-3 si gemini échoue.
    """
    provider = (provider or 'gemini').lower()

    if provider == 'dall-e':
        return await _generate_dalle(prompt, api_keys)
    elif provider == 'stability-ai':
        return await _generate_stability(prompt, api_keys)
    elif provider == 'local':
        return await _generate_local(prompt)
    else:
        # Gemini en principal, dall-e-3 en fallback automatique
        try:
            return await _generate_gemini_image(prompt, api_keys)
        except Exception as _gemini_err:
            print(f"[ENGINE] ⚠️ Gemini image échoué ({_gemini_err}) — fallback dall-e-3")
            if api_keys.get('openai'):
                return await _generate_dalle(prompt, api_keys)
            raise _gemini_err


async def _generate_dalle(prompt: str, api_keys: dict) -> dict:
    """dall-e-3 via OpenAI API."""
    api_key = get_api_key('openai', api_keys)
    if not api_key:
        raise ValueError("Clé API OpenAI manquante (nécessaire pour la génération d'image).")

    payload = {
        'model':           'dall-e-3',
        'prompt':          prompt,
        'n':               1,
        'size':            '1024x1024',
        'response_format': 'url',
    }
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            'https://api.openai.com/v1/images/generations',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type':  'application/json',
            },
            json=payload,
        )
        if not r.is_success:
            detail = r.text[:500]
            raise ValueError(f"OpenAI dall-e-3 {r.status_code} : {detail}")
        data = r.json()
        url            = data['data'][0].get('url', '')
        revised_prompt = data['data'][0].get('revised_prompt', prompt)
        return {'url': url, 'b64': '', 'provider': 'dall-e', 'revised_prompt': revised_prompt}


async def _generate_stability(prompt: str, api_keys: dict) -> dict:
    """Stability AI — SDXL."""
    api_key = get_api_key('stability_ai', api_keys)
    if not api_key:
        raise ValueError("Clé API Stability AI manquante.")

    import base64
    payload = {
        'text_prompts': [{'text': prompt, 'weight': 1.0}],
        'cfg_scale':    7,
        'height':       1024,
        'width':        1024,
        'steps':        30,
        'samples':      1,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            'https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type':  'application/json',
                'Accept':        'application/json',
            },
            json=payload,
        )
        r.raise_for_status()
        data   = r.json()
        b64    = data['artifacts'][0]['base64']
        return {'url': '', 'b64': b64, 'provider': 'stability-ai'}


async def _generate_gemini_image(prompt: str, api_keys: dict) -> dict:
    """Generation d'image via Gemini 2.5 Flash Image (Nano Banana)."""
    api_key = get_api_key('gemini', api_keys)
    if not api_key:
        raise ValueError("Cle API Gemini manquante (necessaire pour la generation d'image).")

    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key={api_key}',
            headers={'Content-Type': 'application/json'},
            json={
                'contents': [{'parts': [{'text': prompt}]}],
                'generationConfig': {'responseModalities': ['IMAGE']},
            },
        )
        if not r.is_success:
            detail = r.text[:500]
            raise ValueError(f"Gemini image {r.status_code} : {detail}")
        data = r.json()
        b64  = data['candidates'][0]['content']['parts'][0]['inlineData']['data']
        return {'url': '', 'b64': b64, 'provider': 'gemini', 'revised_prompt': prompt}


async def edit_gemini_image(prompt: str, image_b64: str, api_keys: dict) -> dict:
    """Retouche d'une image existante via Gemini 2.5 Flash Image."""
    api_key = get_api_key('gemini', api_keys)
    if not api_key:
        raise ValueError("Clé API Gemini manquante pour la retouche d'image.")

    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key={api_key}',
            headers={'Content-Type': 'application/json'},
            json={
                'contents': [{
                    'parts': [
                        {'text': prompt},
                        {'inlineData': {'mimeType': 'image/png', 'data': image_b64}},
                    ]
                }],
                'generationConfig': {'responseModalities': ['IMAGE']},
            },
        )
        if not r.is_success:
            detail = r.text[:500]
            raise ValueError(f"Gemini image edit {r.status_code} : {detail}")
        data = r.json()
        b64  = data['candidates'][0]['content']['parts'][0]['inlineData']['data']
        return {'url': '', 'b64': b64, 'provider': 'gemini', 'revised_prompt': prompt}


async def _generate_local(prompt: str) -> dict:
    """Stub ComfyUI/A1111 local — endpoint configurable."""
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            'http://127.0.0.1:7860/sdapi/v1/txt2img',
            json={'prompt': prompt, 'steps': 20, 'width': 512, 'height': 512},
        )
        r.raise_for_status()
        data = r.json()
        b64  = data['images'][0]
        return {'url': '', 'b64': b64, 'provider': 'local'}


# ══════════════════════════════════════════
# CRÉDIT RESTANT — providers exposant un solde
# ══════════════════════════════════════════

# Providers pour lesquels l'API expose un solde/crédit restant interrogeable.
PROVIDERS_WITH_CREDIT = ('openrouter', 'deepseek', 'stability-ai')


async def get_provider_credit(provider: str, api_keys: dict) -> dict:
    """
    Interroge l'API du provider pour son solde/crédit restant, si l'API
    l'expose. Retourne :
      - {'available': True, 'balance': float, 'currency': str}
      - {'available': False, 'reason': str}  (pas de clé, provider non
        supporté, ou erreur réseau/API — `reason` reste court et sûr à
        afficher)
    """
    # La clé Stability AI est stockée sous 'stability_ai' (underscore) côté
    # api_keys, alors que le provider de crédit est 'stability-ai' (tiret).
    key_name = 'stability_ai' if provider == 'stability-ai' else provider
    key = (api_keys or {}).get(key_name)
    if not key:
        return {'available': False, 'reason': 'no_key'}

    if provider not in PROVIDERS_WITH_CREDIT:
        return {'available': False, 'reason': 'unsupported_provider'}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if provider == 'openrouter':
                r = await client.get(
                    'https://openrouter.ai/api/v1/credits',
                    headers={'Authorization': f'Bearer {key}'},
                )
                r.raise_for_status()
                data  = r.json().get('data', {})
                total = data.get('total_credits', 0) or 0
                used  = data.get('total_usage', 0) or 0
                return {'available': True, 'balance': round(total - used, 4), 'currency': 'USD'}

            if provider == 'deepseek':
                r = await client.get(
                    'https://api.deepseek.com/user/balance',
                    headers={'Authorization': f'Bearer {key}'},
                )
                r.raise_for_status()
                infos = r.json().get('balance_infos') or []
                if not infos:
                    return {'available': False, 'reason': 'empty_response'}
                info = infos[0]
                return {
                    'available': True,
                    'balance':   float(info.get('total_balance', 0)),
                    'currency':  info.get('currency', 'USD'),
                }

            if provider == 'stability-ai':
                r = await client.get(
                    'https://api.stability.ai/v1/user/balance',
                    headers={'Authorization': f'Bearer {key}'},
                )
                r.raise_for_status()
                data = r.json()
                return {'available': True, 'balance': float(data.get('credits', 0)), 'currency': 'crédits'}
    except Exception as e:
        return {'available': False, 'reason': str(e)[:120]}

    return {'available': False, 'reason': 'unsupported_provider'}
