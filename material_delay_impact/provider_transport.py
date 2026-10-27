"""Native Gemini and Claude adapters for the internal Responses-shaped contract.

Only fixed official endpoints are used. Native assistant blocks (including
Gemini thought signatures) are retained verbatim between read-only tool turns.
"""
import json
import re
from urllib.parse import quote


def wire_schema(schema):
    # Provider grammar subsets differ; the complete schema is still enforced
    # locally by ai_engine.shape before any result is accepted.
    if isinstance(schema, list):
        return [wire_schema(v) for v in schema]
    if not isinstance(schema, dict):
        return schema
    return {k: wire_schema(v) for k, v in schema.items()
            if k not in ('minLength', 'maxLength', 'minimum', 'maximum', 'maxItems')}


def request(provider, payload, key):
    model = payload.get('model', '')
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', model):
        raise ValueError('configuration')
    history = payload.get('input', [])
    if isinstance(history, str):
        history = [{'role': 'user', 'content': history}]
    system, messages, names = [], [], {}
    def add(role, content):
        field = 'parts' if provider == 'gemini' else 'content'
        if messages and messages[-1]['role'] == role:
            messages[-1][field].extend(content)
        else:
            messages.append({'role': role, field: content})
    for item in history:
        kind = item.get('type')
        if kind == 'provider_message':
            # These blocks were returned by this provider, not generated locally.
            if provider == 'gemini':
                messages.append(item['native'])
            else:
                add('assistant', item['native'])
        elif kind == 'function_call':
            names[item['call_id']] = item['name']
        elif kind == 'function_call_output':
            if provider == 'gemini':
                add('user', [{'functionResponse': {'name': names[item['call_id']],
                    'response': json.loads(item['output'])}}])
            else:
                add('user', [{'type': 'tool_result', 'tool_use_id': item['call_id'], 'content': item['output']}])
        elif item.get('role') == 'system':
            system.append(item['content'])
        elif item.get('role') in ('user', 'assistant'):
            role = 'model' if provider == 'gemini' and item['role'] == 'assistant' else item['role']
            add(role, [{'text': item['content']}] if provider == 'gemini' else [{'type': 'text', 'text': item['content']}])
    tools = payload.get('tools', []) if payload.get('tool_choice') != 'none' else []
    schema = payload.get('text', {}).get('format', {}).get('schema') if not tools else None
    limit = payload.get('max_output_tokens', 3000)
    if provider == 'gemini':
        body = {'contents': messages, 'generationConfig': {'maxOutputTokens': limit}}
        if system:
            body['systemInstruction'] = {'parts': [{'text': '\n'.join(system)}]}
        if tools:
            body['tools'] = [{'functionDeclarations': [
                {'name': t['name'], 'description': t.get('description', ''),
                 'parametersJsonSchema': wire_schema(t['parameters'])} for t in tools]}]
            body['toolConfig'] = {'functionCallingConfig': {'mode': 'ANY'}}
        if schema:
            body['generationConfig'].update(responseMimeType='application/json', responseJsonSchema=wire_schema(schema))
        return ('https://generativelanguage.googleapis.com/v1beta/models/' + quote(model, safe='') + ':generateContent',
                {'x-goog-api-key': key, 'Content-Type': 'application/json'}, body)
    body = {'model': model, 'messages': messages, 'max_tokens': limit}
    if system:
        body['system'] = '\n'.join(system)
    if tools:
        body['tools'] = [{'name': t['name'], 'description': t.get('description', ''),
                          'input_schema': wire_schema(t['parameters'])} for t in tools]
        body['tool_choice'] = {'type': 'any'}
    if schema:
        body['output_config'] = {'format': {'type': 'json_schema', 'schema': wire_schema(schema)}}
    return ('https://api.anthropic.com/v1/messages',
            {'x-api-key': key, 'anthropic-version': '2023-06-01', 'Content-Type': 'application/json'}, body)


def response(provider, value):
    # Usage belongs to the received response even if its content is malformed.
    # Return a rejected envelope so the shared meter records it before validation.
    usage = gemini_usage(value) if provider == 'gemini' else claude_usage(value)
    try:
        result = _response(provider, value)
    except (ValueError, TypeError, KeyError, AttributeError):
        result = {'status': 'incomplete', 'output': []}
    return {**result, 'usage': usage}


def _response(provider, value):
    output, texts, calls = [], [], []
    if provider == 'gemini':
        candidates = value.get('candidates', [])
        if len(candidates) != 1:
            return {'status': 'incomplete', 'output': [], 'usage': gemini_usage(value)}
        candidate = candidates[0]
        native = candidate.get('content', {})
        for index, part in enumerate(native.get('parts', [])):
            if 'functionCall' in part:
                call = part['functionCall']
                calls.append({'type': 'function_call', 'call_id': 'gemini_' + str(index),
                              'name': call.get('name'), 'arguments': json.dumps(call.get('args', {}))})
            elif 'text' in part and not part.get('thought'):
                texts.append({'type': 'output_text', 'text': part['text']})
        complete = candidate.get('finishReason') == 'STOP'
        usage = gemini_usage(value)
    else:
        native = value.get('content', [])
        for part in native:
            if part.get('type') == 'tool_use':
                calls.append({'type': 'function_call', 'call_id': part.get('id'),
                              'name': part.get('name'), 'arguments': json.dumps(part.get('input', {}))})
            elif part.get('type') == 'text':
                texts.append({'type': 'output_text', 'text': part['text']})
        complete = value.get('stop_reason') in ('end_turn', 'tool_use')
        usage = claude_usage(value)
    if calls:
        output.append({'type': 'provider_message', 'native': native})
        output.extend(calls)
    if texts:
        output.append({'type': 'message', 'content': texts})
    return {'status': 'completed' if complete else 'incomplete', 'output': output, 'usage': usage}


def claude_usage(value):
    raw = value.get('usage')
    if not isinstance(raw, dict):
        return {}
    usage = {}
    # Input excludes cache creation/read. Invalid cache metadata must not produce
    # a plausible but understated total from the non-cache input alone.
    counts = [raw.get('input_tokens'), raw.get('cache_creation_input_tokens', 0), raw.get('cache_read_input_tokens', 0)]
    if all(type(n) is int and n >= 0 for n in counts):
        usage['input_tokens'] = sum(counts)
    if type(raw.get('output_tokens')) is int and raw['output_tokens'] >= 0:
        usage['output_tokens'] = raw['output_tokens']
    if 'input_tokens' in usage and 'output_tokens' in usage:
        usage['total_tokens'] = usage['input_tokens'] + usage['output_tokens']
    return usage


def gemini_usage(value):
    raw = value.get('usageMetadata')
    if not isinstance(raw, dict):
        return {}
    usage = {}
    for src, dest in [('promptTokenCount', 'input_tokens'), ('totalTokenCount', 'total_tokens')]:
        if type(raw.get(src)) is int and raw[src] >= 0:
            usage[dest] = raw[src]
    # Candidates excludes thinking tokens. Billing and totals include both.
    output = [raw.get('candidatesTokenCount'), raw.get('thoughtsTokenCount', 0)]
    if all(type(n) is int and n >= 0 for n in output):
        usage['output_tokens'] = sum(output)
    return usage
