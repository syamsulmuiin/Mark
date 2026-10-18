"""Fixed-host OAuth helpers; authorization codes and tokens never enter logs."""
import base64
import hashlib
import json
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.request import Request
from core.llm_http import urlopen


class AuthHTTPError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f'Provider authentication HTTP {status}')


def post(url, data, *, form=False, timeout=30):
    if url not in {
        'https://auth.openai.com/api/accounts/deviceauth/usercode',
        'https://auth.openai.com/api/accounts/deviceauth/token',
        'https://auth.openai.com/oauth/token',
        'https://openrouter.ai/api/v1/auth/keys',
    }:
        raise ValueError('Untrusted authentication endpoint')
    body = urlencode(data).encode() if form else json.dumps(data).encode()
    request = Request(url, data=body, headers={'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json'}, method='POST')
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
    except HTTPError as exc:
        raise AuthHTTPError(exc.code) from None
    except (URLError, OSError):
        raise RuntimeError('Provider authentication connection failed') from None
    try:
        if len(raw) > 1024 * 1024:
            raise ValueError()
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise RuntimeError('Provider returned an invalid authentication response') from None


def pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    return verifier, challenge


def callback_code(url, redirect_uri, state):
    target, expected = urlsplit(url), urlsplit(redirect_uri)
    query = parse_qs(target.query)
    if (target.scheme, target.netloc, target.path) != (expected.scheme, expected.netloc, expected.path):
        raise ValueError('OAuth callback does not match this login')
    if target.fragment or query.get('state') != [state] or len(query.get('code', [])) != 1 or query.get('error'):
        raise ValueError('OAuth callback state/code is invalid or access was denied')
    return query['code'][0]


def openrouter_login(read_secret, display=print):
    verifier, challenge = pkce()
    display('Open this OpenRouter login link. Authorize Mark, then copy the one-time code shown on the page:')
    display('https://openrouter.ai/auth?' + urlencode({'code_challenge': challenge,
        'code_challenge_method': 'S256', 'key_label': 'Mark'}))
    code = read_secret('OpenRouter one-time authorization code: ').strip()
    if not code or len(code) > 8192:
        raise ValueError('Authorization code is missing or invalid')
    result = post('https://openrouter.ai/api/v1/auth/keys', {
        'code': code, 'code_verifier': verifier, 'code_challenge_method': 'S256'})
    key = result.get('key')
    if not isinstance(key, str) or not key.strip():
        raise RuntimeError('OpenRouter did not return an API key')
    return key
