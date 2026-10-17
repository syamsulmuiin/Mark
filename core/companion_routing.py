"""Resolve browser aliases against capabilities actually advertised by a device."""
from urllib.parse import urlencode, urlsplit


def normalize_companion_call(capability, args, available):
    capability = str(capability or '').strip()
    payload = dict(args or {})
    if capability in available or 'open_url' not in available:
        return capability, payload
    if capability == 'browser.open':
        url = str(payload.get('url') or '').strip()
        if urlsplit(url).scheme not in {'http', 'https'} or not urlsplit(url).hostname:
            raise ValueError('browser.open requires an HTTP(S) URL')
        return 'open_url', {'url': url}
    if capability == 'browser.search':
        query = str(payload.get('query') or payload.get('text') or '').strip()
        if not query:
            raise ValueError('browser.search requires a query')
        return 'open_url', {'url': 'https://www.google.com/search?' + urlencode({'q': query})}
    return capability, payload
