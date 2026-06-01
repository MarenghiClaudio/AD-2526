"""
Helper per agganciare RequestTiming allo state di una request FastAPI.

Gli endpoint chiamano `start_timing(request)` come prima riga del body;
il middleware legge il timer da `request.state.timing` per emettere il
log strutturato a fine richiesta.
"""

from fastapi import Request

from .timing import RequestTiming


def start_timing(request: Request) -> RequestTiming:
    """Crea un RequestTiming e lo aggancia a request.state.timing."""
    rt = RequestTiming()
    request.state.timing = rt
    return rt
