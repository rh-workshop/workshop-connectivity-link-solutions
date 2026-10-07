# Servidor Git smart HTTP mínimo para el Lab 6: delega en git http-backend.
# Lo lee Argo CD dentro del clúster; los commits se hacen en el propio pod.
# Sin autenticación: repo efímero y de demostración, solo accesible por Service.
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RAIZ = os.environ.get("GIT_RAIZ", "/srv/git")


class Git(BaseHTTPRequestHandler):
    def _backend(self):
        ruta, _, consulta = self.path.partition("?")
        largo = int(self.headers.get("Content-Length") or 0)
        cuerpo = self.rfile.read(largo) if largo else b""
        entorno = dict(
            os.environ,
            GIT_PROJECT_ROOT=RAIZ,
            GIT_HTTP_EXPORT_ALL="1",
            REQUEST_METHOD=self.command,
            PATH_INFO=ruta,
            QUERY_STRING=consulta,
            CONTENT_TYPE=self.headers.get("Content-Type", ""),
            CONTENT_LENGTH=str(len(cuerpo)),
            REMOTE_ADDR=self.client_address[0],
            GIT_PROTOCOL=self.headers.get("Git-Protocol", ""),
            HTTP_CONTENT_ENCODING=self.headers.get("Content-Encoding", ""),
        )
        salida = subprocess.run(["git", "http-backend"], input=cuerpo, env=entorno,
                                capture_output=True, check=False).stdout
        cabecera, _, datos = salida.partition(b"\r\n\r\n")
        estado, cabeceras = 200, []
        for linea in cabecera.decode(errors="replace").split("\r\n"):
            clave, _, valor = linea.partition(":")
            if clave.lower() == "status":
                estado = int(valor.strip().split()[0])
            elif clave:
                cabeceras.append((clave, valor.strip()))
        self.send_response(estado)
        for clave, valor in cabeceras:
            self.send_header(clave, valor)
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    do_GET = _backend
    do_POST = _backend


ThreadingHTTPServer(("0.0.0.0", 8080), Git).serve_forever()
