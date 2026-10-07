"""Git smart HTTP de lectura; la publicación usa exec autorizado por Kubernetes."""
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


class GitReadOnly(BaseHTTPRequestHandler):
    def handle_git(self):
        url = urlsplit(self.path)
        # upload-pack usa POST para lectura; receive-pack nunca se expone.
        allowed = (self.command == 'GET' and url.path == '/platform.git/info/refs'
                   and parse_qs(url.query).get('service') == ['git-upload-pack']) or (
                       self.command == 'POST' and url.path == '/platform.git/git-upload-pack'
                       and not url.query)
        if not allowed:
            self.send_error(403, 'Repositorio de solo lectura')
            return
        length = int(self.headers.get('Content-Length', '0'))
        if length > 4 * 1024 * 1024 or length < 0:
            self.send_error(413)
            return
        env = dict(os.environ, GIT_PROJECT_ROOT=os.environ.get('GIT_RAIZ', '/srv/git'),
                   GIT_HTTP_EXPORT_ALL='1', REQUEST_METHOD=self.command, PATH_INFO=url.path,
                   QUERY_STRING=url.query, CONTENT_TYPE=self.headers.get('Content-Type', ''),
                   CONTENT_LENGTH=str(length), REMOTE_ADDR=self.client_address[0],
                   GIT_PROTOCOL=self.headers.get('Git-Protocol', ''))
        result = subprocess.run(['git', 'http-backend'], input=self.rfile.read(length),
                                env=env, capture_output=True, timeout=60, check=False)
        if result.returncode:
            self.send_error(502)
            return
        headers, sep, body = result.stdout.partition(b'\r\n\r\n')
        if not sep:
            self.send_error(502)
            return
        status, pairs = 200, []
        for line in headers.decode().split('\r\n'):
            key, _, value = line.partition(':')
            if key.lower() == 'status':
                status = int(value.strip().split()[0])
            elif key:
                pairs.append((key, value.strip()))
        self.send_response(status)
        for key, value in pairs:
            self.send_header(key, value)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = handle_git
    do_POST = handle_git
    do_PUT = handle_git
    do_DELETE = handle_git

    def log_message(self, *_):
        pass  # No registrar URLs, contenidos ni datos del entorno privado.


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8080), GitReadOnly).serve_forever()
