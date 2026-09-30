"""Tiny stdlib HTTP server for ``/healthz``, ``/readyz`` and ``/metrics`` (labs/CONTRACT.md §3).

Runs in a daemon thread next to the consumer loop. ``/healthz`` answers as long as the process is
alive; ``/readyz`` runs the supplied dependency checks (database ping) and returns 503 naming the
failing check, which tells the platform to keep the task out of rotation without restarting it.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Mapping
from urllib.parse import urlsplit

from worker import metrics

log = logging.getLogger(__name__)

ReadyCheck = Callable[[], Mapping[str, str]]


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], ready_check: ReadyCheck) -> None:
        super().__init__(address, _Handler)
        self.ready_check = ready_check


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    server_version = "shopfront-worker"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - name dictated by http.server
        route = urlsplit(self.path).path
        if route == "/healthz":
            self._json(200, {"status": "ok"}, route)
        elif route == "/readyz":
            checks = dict(self.server.ready_check())
            ready = all(value == "ok" for value in checks.values())
            self._json(200 if ready else 503, {"status": "ready" if ready else "unavailable", "checks": checks}, route)
        elif route == "/metrics":
            body, content_type = metrics.render()
            self._send(200, content_type, body, route)
        else:
            self._json(404, {"error": "not found"}, "unknown")

    def _json(self, status: int, payload: dict, route: str) -> None:
        self._send(status, "application/json", json.dumps(payload).encode("utf-8"), route)

    def _send(self, status: int, content_type: str, body: bytes, route: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        metrics.HTTP_REQUESTS.labels(method=self.command, route=route, status=str(status)).inc()

    def log_message(self, fmt: str, *args) -> None:  # health probes would flood the logs at INFO
        log.debug("http %s", fmt % args)


class HealthServer:
    def __init__(self, port: int, ready_check: ReadyCheck, host: str = "0.0.0.0") -> None:
        self._server = _Server((host, port), ready_check)
        self._thread = threading.Thread(target=self._server.serve_forever, name="health-http", daemon=True)
        self.port = self._server.server_address[1]

    def start(self) -> None:
        self._thread.start()
        log.info("health endpoint listening", extra={"port": self.port})

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
