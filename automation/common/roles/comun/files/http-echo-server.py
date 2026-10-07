from http.server import BaseHTTPRequestHandler, HTTPServer
import json, os
VERSION = os.environ.get("API_VERSION", "v1")
SERVICE = os.environ.get("SERVICE_NAME", "gobierno-api")
class H(BaseHTTPRequestHandler):
    def _reply(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode() if n else ""
        data = {"service": SERVICE, "version": VERSION, "method": self.command,
                "path": self.path, "body": body,
                "x_forwarded_for": self.headers.get("X-Forwarded-For"),
                "x_envoy_external_address": self.headers.get("X-Envoy-External-Address"),
                "x_client_common_name": self.headers.get("X-Client-Common-Name"),
                "authorization_recibida": "Authorization" in self.headers,
                "cabeceras_x": {k: v for k, v in self.headers.items()
                                if k.lower().startswith("x-") and not k.lower().startswith(("x-envoy-peer", "x-forwarded-client-cert"))}}
        if VERSION == "v2":
            data["saldo"] = {"cuenta": "ACC-DEMO-001", "moneda": "EUR", "disponible": 1250.40}
        else:
            data["balance"] = "1250.40 EUR"
        payload = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)
    do_GET = _reply
    do_POST = _reply
HTTPServer(("0.0.0.0", 8080), H).serve_forever()
