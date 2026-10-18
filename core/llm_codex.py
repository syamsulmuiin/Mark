"""Native ChatGPT/Codex account login and text HTTP adapter; no CLI process."""
import base64
import json
import math
import secrets
from urllib.parse import urlencode
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request
from core import provider_credentials as credentials
from core.provider_oauth import post, AuthHTTPError, pkce, callback_code
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


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _token_expiry(tokens, access, now):
    """Use access-token expiry metadata without inventing a token lifetime."""
    lifetime = _number(tokens.get('expires_in'))
    jwt_expiry = _number(_claims(access).get('exp'))
    if jwt_expiry is not None and jwt_expiry <= now:
        raise RuntimeError('OpenAI returned an already expired access token; start a new login')
    candidates = []
    if lifetime is not None and lifetime > 0:
        candidates.append(now + lifetime)
    if jwt_expiry is not None:
        candidates.append(jwt_expiry)
    # Year 9999 is the timestamp representation limit, not a token-duration policy.
    candidates = [value for value in candidates if math.isfinite(value) and now < value <= 253402300799]
    if not candidates:
        raise RuntimeError('OpenAI credential expiry is unavailable: no usable expires_in or access-token exp')
    return min(candidates)


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
    expiry = _token_expiry(tokens, access, time.time())
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


def login_browser(read_secret, display=print):
    """Explicit alternative to device auth; browser may run on a different device."""
    verifier, challenge = pkce()
    state = secrets.token_urlsafe(32)
    redirect = 'http://localhost:1455/auth/callback'
    url = ISSUER + '/oauth/authorize?' + urlencode({
        'client_id': CLIENT_ID, 'response_type': 'code', 'redirect_uri': redirect,
        'scope': 'openid profile email offline_access', 'state': state,
        'code_challenge': challenge, 'code_challenge_method': 'S256',
        'id_token_add_organizations': 'true', 'codex_cli_simplified_flow': 'true', 'originator': 'mark'})
    display('Open this OpenAI login link in your browser. After approval, copy the full localhost redirect URL. The localhost page may not load when Mark runs on another machine:')
    display(url)
    deadline = time.monotonic() + 600
    response = read_secret('Full OpenAI redirected URL: ').strip()
    if time.monotonic() > deadline:
        raise RuntimeError('OpenAI browser login expired; start a fresh login')
    code = callback_code(response, redirect, state)
    tokens = post(ISSUER + '/oauth/token', {'grant_type': 'authorization_code', 'client_id': CLIENT_ID,
        'redirect_uri': redirect, 'code': code, 'code_verifier': verifier}, form=True)
    credentials.save('openai_codex', _record(tokens))


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


def list_models(*, timeout=20.0):
    """Fetch native account models, without API-key or CLI dependencies."""
    record = check_login()
    request = Request(ENDPOINT.rsplit('/', 1)[0] + '/models?client_version=1.0.0', headers={
        'Authorization': 'Bearer ' + record['access_token'],
        'ChatGPT-Account-ID': record['account_id'], 'Accept': 'application/json',
        'User-Agent': 'Mark/1.0.0', 'originator': 'mark'}, method='GET')
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise RuntimeError('OpenAI account model catalog exceeded its limit')
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not isinstance(payload.get('models'), list):
            raise ValueError('invalid catalog')
        models, seen = [], set()
        for item in payload['models']:
            if not isinstance(item, dict) or item.get('visibility') != 'list':
                continue
            slug = item.get('slug')
            if (not isinstance(slug, str) or not slug or len(slug) > 256
                    or any(not (c.isascii() and (c.isalnum() or c in '-_./:')) for c in slug)
                    or slug in seen):
                continue
            modalities = item.get('input_modalities', ['text'])
            if not isinstance(modalities, list) or 'text' not in modalities:
                continue
            name = item.get('display_name')
            name = ''.join(c for c in name if c.isprintable())[:160] if isinstance(name, str) else slug
            models.append({'id': slug, 'name': name or slug})
            seen.add(slug)
        return models
    except HTTPError as exc:
        if exc.code == 401:
            credentials.invalidate('openai_codex')
        raise RuntimeError(f'OpenAI account model catalog HTTP {exc.code}') from None
    except (URLError, OSError, ValueError, TypeError, AttributeError):
        raise RuntimeError('OpenAI account model catalog connection or format failed') from None


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
