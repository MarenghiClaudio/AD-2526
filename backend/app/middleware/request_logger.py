"""
Middleware di logging strutturato per ogni richiesta HTTP.

Per ogni request scrive una riga JSON con:
  ts, method, path, status, total_ms, db_ms, [user_id], [client]

Si aggancia a `request.state.timing` (popolato dagli endpoint via
`start_timing()`) per avere la breakdown DB vs Python. Se l'endpoint
non popola `timing` (es. errore precoce), il `db_ms` è 0.

Output destination:
  - se `REQUEST_LOG_PATH == "-"`, scrive su stderr
  - altrimenti append-only su file (line-buffered, una request per riga)

L'analisi offline si fa con pandas:
    df = pd.read_json("requests.log", lines=True)
    df.groupby("path")["total_ms"].describe(percentiles=[.5, .95, .99])
"""

import json
import logging
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable, TextIO

from fastapi import Request, Response

from ..config import get_settings
from ..core.timing import RequestTiming

logger = logging.getLogger(__name__)

_LOG_SINK: TextIO | None = None


def _open_sink() -> TextIO:
    """Apre lazily la destinazione del log strutturato."""
    global _LOG_SINK
    if _LOG_SINK is not None:
        return _LOG_SINK

    path = get_settings().request_log_path
    if path == "-":
        _LOG_SINK = sys.stderr
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # buffering=1 → line-buffered, ogni riga viene flushata subito.
        _LOG_SINK = open(path, "a", buffering=1, encoding="utf-8")
        logger.info("Request log file: %s", path)
    return _LOG_SINK


def close_sink() -> None:
    """Chiude il file di log allo shutdown (no-op se è stderr)."""
    global _LOG_SINK
    if _LOG_SINK is not None and _LOG_SINK is not sys.stderr:
        _LOG_SINK.close()
    _LOG_SINK = None


async def request_logging_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """
    Wrappa ogni request, misura il total_ms server-side e scrive la riga
    di log strutturato. Tutta la logica di body-timing rimane negli
    endpoint via `start_timing()` / `build_response()`.
    """
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        total_ms = round((time.perf_counter() - start) * 1000.0, 3)
        rt: RequestTiming | None = getattr(request.state, "timing", None)
        db_ms = rt.db.elapsed_ms if rt is not None else 0.0

        entry: dict[str, object] = {
            "ts": time.time(),
            "method": request.method,
            "path": request.url.path,
            "status": status_code,
            "total_ms": total_ms,
            "db_ms": db_ms,
        }
        # Path params utili per analizzare hot users in Fase 2
        if request.path_params:
            for key in ("user_id", "post_id"):
                if key in request.path_params:
                    entry[key] = request.path_params[key]
        if request.client is not None:
            entry["client"] = request.client.host

        sink = _open_sink()
        sink.write(json.dumps(entry) + "\n")
