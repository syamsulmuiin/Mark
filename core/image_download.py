"""Bounded public image retrieval with DNS pinning and redirect revalidation."""
from __future__ import annotations
import hashlib
import http.client
import io
import ipaddress
from pathlib import Path
import socket
import ssl
import uuid
import time
from urllib.parse import urlsplit, urljoin

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000


def public_target(url):
    parsed = urlsplit(url)
    if (parsed.scheme not in {'https', 'http'} or not parsed.hostname
            or parsed.username or parsed.password
            or parsed.port not in (None, 80 if parsed.scheme == 'http' else 443)):
        raise ValueError('unsupported_image_url')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    ips = list(dict.fromkeys(row[4][0] for row in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError('non_public_image_host')
    return parsed, ips[0], port


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, hostname, address, port):
        super().__init__(hostname, port=port, timeout=8)
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def fetch_image_bytes(url):
    deadline = time.monotonic() + 20
    for _ in range(4):
        if time.monotonic() >= deadline:
            raise TimeoutError('image_download_deadline')
        parsed, address, port = public_target(url)
        connection = (_PinnedHTTPS(parsed.hostname, address, port) if parsed.scheme == 'https'
                      else http.client.HTTPConnection(address, port, timeout=8))
        try:
            path = parsed.path or '/'
            if parsed.query:
                path += '?' + parsed.query
            connection.request('GET', path, headers={'Host': parsed.netloc, 'User-Agent':'MarkImageFetcher/1.0',
                                                      'Accept':'image/png,image/jpeg,image/webp,image/gif',
                                                      'Accept-Encoding':'identity'})
            response = connection.getresponse()
            if response.status in {301,302,303,307,308}:
                location = response.getheader('Location')
                if not location:
                    raise ValueError('image_redirect_missing')
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError('image_http_error')
            length = response.getheader('Content-Length')
            if length and int(length) > MAX_BYTES:
                raise ValueError('image_too_large')
            data = bytearray()
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError('image_download_deadline')
                chunk = response.read1(min(65536, MAX_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise ValueError('image_too_large')
            return bytes(data)
        finally:
            connection.close()
    raise ValueError('image_redirect_limit')


def save_verified_image(url, base_dir):
    return save_image_bytes(fetch_image_bytes(url), base_dir)


def save_image_bytes(data, base_dir):
    from PIL import Image
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
        raise ValueError('image_too_large_or_empty')
    with Image.open(io.BytesIO(data)) as image:
        formats = {'JPEG':'.jpg', 'PNG':'.png', 'WEBP':'.webp', 'GIF':'.gif'}
        if image.format not in formats or image.width * image.height > MAX_PIXELS:
            raise ValueError('unsupported_or_oversized_image')
        suffix = formats[image.format]
        image.verify()
    root = Path(base_dir).resolve() / 'storage/artifacts/images'
    if root.resolve() != root:
        raise ValueError('unsafe_image_directory')
    root.mkdir(parents=True, exist_ok=True)
    target = root / ('image-' + uuid.uuid4().hex + suffix)
    with target.open('xb') as output:
        output.write(data)
    return {'file_path':str(target), 'sha256':hashlib.sha256(data).hexdigest(),
            'size':len(data), 'image_verified':True}
