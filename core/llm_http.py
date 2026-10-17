"""HTTP transport for fixed-provider adapters: never forward keys via redirects."""
from urllib.request import HTTPRedirectHandler, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def urlopen(request, *, timeout):
    return build_opener(_NoRedirect()).open(request, timeout=timeout)
