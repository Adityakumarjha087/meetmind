"""Shared outbound HTTP client (httpx2). Tests swap the transport via ``set_transport``."""

from __future__ import annotations

import httpx2

_transport: httpx2.BaseTransport | None = None


def set_transport(transport: httpx2.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def client(timeout: float = 15.0) -> httpx2.Client:
    if _transport is not None:
        return httpx2.Client(transport=_transport, timeout=timeout)
    return httpx2.Client(timeout=timeout)
