"""Native ChatGPT/Codex account login and text HTTP adapter; no CLI process."""
import base64
import json
import math
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request
from core import provider_credentials as credentials
from core.provider_oauth import post, AuthHTTPError
from core.llm_http import urlopen

# Public OAuth client from openai/codex, codex-rs/login/src/auth/manager.rs.
CLIENT_ID = 'app_EMoamEEZ73f0CkXaXp7hrann'
ISSUER = 'https://auth.openai.com'
ENDPOINT = 'https://chatgpt.com/backend-api/codex/responses'


def _claims(token):
    # Used only for routing/expiry hints. OpenAI validates the bearer token.
    try:
        encoded = token.split('.')[1]
        value = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        return value if isinstance(value, dict) else {}
    except (ValueError, IndexError, TypeError):
        return {}


def _record(tokens, previous=None):
    previous = previous or {}
    access = tokens.get('access_token')
    refresh = tokens.get('refresh_token') or previous.get('refresh_token')
    if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
        raise RuntimeError('OpenAI did not return valid account credentials')
    claims = _claims(tokens.get('id_token') or access)
    details = claims.get('https://api.openai.com/auth') or {}
    account = details.get('chatgpt_account_id') if isinstance(details, dict) else None
    account = account or previous.get('account_id')
    if not isinstance(account, str) or not account or '\n' in account or '\r' in account:
        raise RuntimeError('OpenAI account identifier is missing')
    try:
        lifetime = float(tokens.get('expires_in', 3600))
        if not math.isfinite(lifetime) or not 60 <= lifetime <= 604800:
            raise ValueError()
        expiry = time.time() + lifetime
    except (ValueError, TypeError):
        raise RuntimeError('OpenAI returned an invalid credential expiry') from None
    return {'access_token': access, 'refresh_token': refresh, 'account_id': account,
            'expires_at': expiry, 'invalid': False}


def login(display=print, *, timeout=900):
    code = post(ISSUER + '/api/accounts/deviceauth/usercode', {'client_id': CLIENT_ID})
    device, user = code.get('device_auth_id'), code.get('user_code') or code.get('usercode')
    if not isinstance(device, str) or not device or not isinstance(user, str) or not user:
        raise RuntimeError('OpenAI returned an invalid device code')
    display('Sign in to OpenAI for Mark at https://auth.openai.com/codex/device')
    display('Enter this one-time code: ' + user)
    deadline = time.monotonic() + min(900, max(1, timeout))
    try:
        interval = min(30, max(1, float(code.get('interval', 5))))
    except (ValueError, TypeError):
        interval = 5
    while time.monotonic() < deadline:
        try:
            granted = post(ISSUER + '/api/accounts/deviceauth/token', {'device_auth_id': device, 'user_code': user})
        except AuthHTTPError as exc:
            if exc.status not in {403, 404}:
                raise
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
            continue
        if not all(isinstance(granted.get(key), str) and granted[key] for key in ('authorization_code', 'code_verifier')):
            raise RuntimeError('OpenAI returned an invalid device grant')
        tokens = post(ISSUER + '/oauth/token', {'grant_type': 'authorization_code', 'client_id': CLIENT_ID,
            'code': granted['authorization_code'], 'code_verifier': granted['code_verifier'],
            'redirect_uri': ISSUER + '/deviceauth/callback'}, form=True)
        record = _record(tokens)
        credentials.save('openai_codex', record)
        return
    raise RuntimeError('OpenAI device login expired; run setup again')


def check_login():
    with credentials.LOCK:
        record = credentials.load('openai_codex')
        if not record.get('access_token') or record.get('invalid'):
            raise RuntimeError('OpenAI account login required; choose Codex account login in Mark setup')
        try:
            expires_at = float(record.get('expires_at', 0))
            if not math.isfinite(expires_at):
                raise ValueError()
        except (ValueError, TypeError):
            raise RuntimeError('OpenAI account expiry is invalid; sign in again in Mark setup') from None
        if expires_at <= time.time() + 60:
            try:
                tokens = post(ISSUER + '/oauth/token', {'grant_type': 'refresh_token', 'client_id': CLIENT_ID,
                    'refresh_token': record.get('refresh_token', '')}, form=True)
            except AuthHTTPError as exc:
                if exc.status in {400, 401, 403}:
                    credentials.invalidate('openai_codex')
                    raise RuntimeError('OpenAI account login expired or revoked; sign in again in Mark setup') from None
                raise
            record = _record(tokens, record)
            credentials.save('openai_codex', record)
        return record


def generate_text(model, prompt, *, timeout=120.0):
    if not model.strip() or not prompt.strip():
        raise ValueError('Model and prompt are required')
    record = check_login()
    request = Request(ENDPOINT, data=json.dumps({'model': model, 'instructions': 'Answer the user request. Return text only; do not execute tools.',
        'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': prompt}]}],
        'store': False, 'stream': True, 'tools': []}).encode(), headers={
            'Authorization': 'Bearer ' + record['access_token'], 'ChatGPT-Account-ID': record['account_id'],
            'Content-Type': 'application/json', 'Accept': 'text/event-stream', 'OpenAI-Beta': 'responses=experimental', 'originator': 'mark'}, method='POST')
    started, total = time.monotonic(), 0
    try:
        with urlopen(request, timeout=timeout) as response:
            for line in response:
                total += len(line)
                if total > 8 * 1024 * 1024 or time.monotonic() - started > timeout:
                    raise RuntimeError('OpenAI account response exceeded its limit')
                if not line.startswith(b'data:'):
                    continue
                raw = line[5:].strip()
                if raw == b'[DONE]':
                    break
                event = json.loads(raw)
                kind = event.get('type')
                if kind in {'error', 'response.failed', 'response.incomplete'}:
                    raise RuntimeError('OpenAI account text response failed or was incomplete')
                if kind == 'response.completed':
                    result = event.get('response') or {}
                    if result.get('status') != 'completed':
                        raise RuntimeError('OpenAI account response was not completed')
                    blocks = [part.get('text', '') for item in result.get('output', [])
                        if item.get('type') == 'message' for part in item.get('content', []) if part.get('type') == 'output_text']
                    answer = '\n'.join(blocks).strip()
                    if not answer:
                        raise RuntimeError('OpenAI account returned no text')
                    return answer
    except HTTPError as exc:
        if exc.code == 401:
            credentials.invalidate('openai_codex')
        raise RuntimeError(f'OpenAI account HTTP {exc.code}; no provider fallback') from None
    except (URLError, OSError, ValueError, TypeError, AttributeError):
        raise RuntimeError('OpenAI account response connection or format failed') from None
    raise RuntimeError('OpenAI account stream ended without a completed response')
