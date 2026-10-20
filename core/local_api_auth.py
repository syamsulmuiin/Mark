"""Owner-readable authentication for local operator endpoints behind proxies."""
from __future__ import annotations
import hmac
import os
from pathlib import Path
import secrets

HEADER = 'X-Mark-Local-Token'


def local_token(base_dir, *, create=False):
    path=Path(base_dir)/'devices'/'local_api.token'
    if create:
        path.parent.mkdir(parents=True,exist_ok=True)
        try:
            descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor,'w',encoding='ascii') as stream:
                stream.write(secrets.token_hex(32))
    try:
        token=path.read_text(encoding='ascii').strip()
    except (OSError,ValueError):
        raise RuntimeError('Local API credential unavailable; start or repair the server first') from None
    if len(token)!=64 or any(c not in '0123456789abcdef' for c in token):
        raise RuntimeError('Local API credential is invalid; restore devices/local_api.token')
    return token


def local_headers(base_dir):
    return {'X-Jarvis-Local':'1',HEADER:local_token(base_dir)}


def authorized_local_request(request, token):
    host=request.client.host if request.client else ''
    supplied=request.headers.get(HEADER.lower(),'')
    return (host in {'127.0.0.1','::1'} and request.headers.get('x-jarvis-local')=='1'
            and isinstance(supplied,str) and hmac.compare_digest(supplied.encode(),token.encode()))
