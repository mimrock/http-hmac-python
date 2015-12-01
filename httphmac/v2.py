from .base_signer import BaseSigner, BaseResponseSigner

import base64
import hashlib
import hmac
import re
import time


class V2Signer(BaseSigner):
    def __init__(self, digest):
        super(V2Signer, self).__init__(digest)
        self.preset_time = None

    def signable(self, request, authheaders, bodyhash=None):
        method = request.method.upper()
        host = request.get_header("host")
        path = request.url.canonical_path()
        query = request.url.query
        timestamp = request.get_header("x-authorization-timestamp")
        auth_headers = 'id={0}&nonce={1}&realm={2}&version=2.0'.format(authheaders['id'], authheaders['nonce'], authheaders['realm'])
        base = '{0}\n{1}\n{2}\n{3}\n{4}'.format(method, host, path, query, auth_headers, timestamp)

        cheaders = []
        cheaders_sign = '\n'
        if "headers" in authheaders:
            cheaders = authheaders["headers"].split(";")
        cheaders.sort()
        for cheader in cheaders:
            cheaders_sign += '{0}: {1}\n'.format(cheader.lower(), request.get_header(cheader))
        base += cheaders_sign
        base += '{0}'.format(request.get_header('x-authorization-timestamp'))

        if bodyhash is not None:
            base += '\n{0}\n{1}'.format(request.get_header('content-type'), bodyhash)

        return base

    def parse_auth_headers(self, authorization):
        matches = re.findall(r'(\w+)="(.*?)"', authorization)
        return dict(matches)

    def sign(self, request, authheaders, secret):
        if "id" not in authheaders or authheaders["id"] == '':
            raise KeyError("id required in authorization headers.")
        if "nonce" not in authheaders or authheaders["nonce"] == '':
            raise KeyError("nonce required in authorization headers.")
        if "realm" not in authheaders or authheaders["realm"] == '':
            raise KeyError("realm required in authorization headers.")
        if request.get_header('x-authorization-timestamp') == '':
            raise KeyError("X-Authorization-Timestamp is required.")
        timestamp = int(float(request.get_header('x-authorization-timestamp')))
        if timestamp == 0:
            raise ValueError("X-Authorization-Timestamp must be a valid, non-zero timestamp.")
        if self.preset_time is None:
            curr_time = time.gmtime()
        else:
            curr_time = self.preset_time
        if timestamp > curr_time + 900:
            raise ValueError("X-Authorization-Timestamp is too far in the future.")
        if timestamp < curr_time - 900:
            raise ValueError("X-Authorization-Timestamp is too far in the past.")
        bodyhash = None
        if request.body is not None and request.body != b'':
            content_hash = request.get_header("x-authorization-content-sha256")
            if content_hash == '':
                raise KeyError("X-Authorization-Content-SHA256 is required for requests with a request body.")
            sha256 = hashlib.sha256()
            sha256.update(request.body)
            bodyhash = base64.b64encode(sha256.digest()).decode('utf-8')
            if content_hash != bodyhash:
                raise ValueError("X-Authorization-Content-SHA256 must match the SHA-256 hash of the request body.")

        mac = hmac.HMAC(base64.b64decode(secret.encode('utf-8'), validate=True), digestmod=self.digest)
        mac.update(self.signable(request, authheaders, bodyhash).encode('utf-8'))
        digest = mac.digest()
        return base64.b64encode(digest).decode('utf-8')

    def get_response_signer(self):
        if not hasattr(self, "response_signer"):
            self.response_signer = V2ResponseSigner(self.digest)
        return self.response_signer

    def matches(self, header):
        print(header)
        if re.match(r'(?i)^\s*acquia-http-hmac.*?version=\"2\.0\".*?$', header) is not None:
            return True
        return False


class V2ResponseSigner(BaseResponseSigner):
    def __init__(self, digest):
        super(V2ResponseSigner, self).__init__(digest)

    def signable(self, request, authheaders, response_body):
        nonce = authheaders["nonce"]
        timestamp = request.get_header("x-authorization-timestamp")
        body_str = response_body
        if isinstance(response_body, bytes):
            body_str = response_body.decode('utf-8')
        return '{0}\n{1}\n{2}'.format(nonce, timestamp, body_str)

    def sign(self, request, authheaders, response_body, secret):
        if "nonce" not in authheaders or authheaders["nonce"] == '':
            raise KeyError("nonce required in authorization headers.")
        if request.get_header('x-authorization-timestamp') == '':
            raise KeyError("X-Authorization-Timestamp is required.")

        mac = hmac.HMAC(base64.b64decode(secret.encode('utf-8'), validate=True), digestmod=self.digest)
        mac.update(self.signable(request, authheaders, response_body).encode('utf-8'))
        digest = mac.digest()
        return base64.b64encode(digest).decode('utf-8')