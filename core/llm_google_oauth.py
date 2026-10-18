"""Gemini Developer API Text OAuth using the user's own desktop OAuth client."""
import json
import re
from pathlib import Path
from urllib.request import Request
from urllib.error import HTTPError, URLError
from core import provider_credentials as store
from core.provider_oauth import callback_code
from core.llm_http import urlopen

SCOPES = ['https://www.googleapis.com/auth/cloud-platform', 'https://www.googleapis.com/auth/generative-language.retriever']
REDIRECT = 'http://localhost:8765/mark/google'


def login(read_input, read_secret, display=print):
    from google_auth_oauthlib.flow import InstalledAppFlow
    path = Path(read_input('Google Desktop OAuth client JSON path: ').strip()).expanduser()
    try:
        original = json.loads(path.read_text())
        client = original['installed']
        if (client['auth_uri'] != 'https://accounts.google.com/o/oauth2/auth'
                or client['token_uri'] != 'https://oauth2.googleapis.com/token'):
            raise ValueError()
        config = {'installed': {key: client[key] for key in ('client_id', 'client_secret', 'auth_uri', 'token_uri')}}
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeError('Use your own Google Desktop OAuth client JSON with official Google endpoints') from None
    project = read_input('Google Cloud project ID (Generative Language API enabled): ').strip()
    if not re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]', project):
        raise ValueError('Invalid Google Cloud project ID')
    flow = InstalledAppFlow.from_client_config(config, SCOPES, autogenerate_code_verifier=True)
    flow.redirect_uri = REDIRECT
    url, state = flow.authorization_url(access_type='offline', prompt='consent')
    display('Open this Google login link for Mark. After consent, copy the full localhost redirect URL; the localhost page may not load on a remote server:')
    display(url)
    redirected = read_secret('Full Google redirected URL: ').strip()
    code = callback_code(redirected, REDIRECT, state)
    try:
        flow.fetch_token(code=code)
        credentials = flow.credentials.with_quota_project(project)
        if not credentials.refresh_token:
            raise ValueError()
        record = {'credentials': json.loads(credentials.to_json()), 'project': project, 'invalid': False}
    except Exception:
        raise RuntimeError('Google authorization exchange failed; no credentials were saved') from None
    store.save('google_oauth', record)


def credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as RefreshRequest
    from google.auth.exceptions import RefreshError
    with store.LOCK:
        record = store.load('google_oauth')
        if not record.get('credentials') or record.get('invalid'):
            raise RuntimeError('Google OAuth login required in Mark setup')
        try:
            creds = Credentials.from_authorized_user_info(record['credentials'], scopes=SCOPES)
            if not creds.valid:
                creds.refresh(RefreshRequest())
                record['credentials'] = json.loads(creds.to_json())
                store.save('google_oauth', record)
        except RefreshError as exc:
            if not getattr(exc, 'retryable', False):
                store.invalidate('google_oauth')
            raise RuntimeError('Google OAuth refresh failed; verify connection or sign in again in Mark setup') from None
        except Exception:
            raise RuntimeError('Google OAuth credentials could not be used; sign in again in Mark setup') from None
        return creds, record['project']


def generate_text(model, prompt, *, timeout=30):
    name = model.removeprefix('models/')
    if not re.fullmatch(r'[A-Za-z0-9._-]+', name) or not prompt.strip():
        raise ValueError('Valid Google model and prompt are required')
    creds, project = credentials()
    request = Request('https://generativelanguage.googleapis.com/v1beta/models/' + name + ':generateContent',
        data=json.dumps({'contents': [{'role': 'user', 'parts': [{'text': prompt}]}]}).encode(),
        headers={'Authorization': 'Bearer ' + creds.token, 'x-goog-user-project': project,
                 'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError()
        result = json.loads(raw)['candidates'][0]
        if result.get('finishReason') != 'STOP':
            raise ValueError()
        answer = '\n'.join(part['text'] for part in result['content']['parts'] if 'text' in part).strip()
        if not answer:
            raise ValueError()
        return answer
    except HTTPError as exc:
        if exc.code == 401:
            store.invalidate('google_oauth')
        raise RuntimeError(f'Google OAuth HTTP {exc.code}; no provider fallback') from None
    except (URLError, OSError, ValueError, KeyError, IndexError, TypeError):
        raise RuntimeError('Google OAuth text request failed or returned incomplete content') from None
