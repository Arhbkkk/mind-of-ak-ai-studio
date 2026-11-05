"""Fail-closed owner gate for the single-owner hosted studio.

HTTP Basic is acceptable here only because the app is owner-only and served over HTTPS.
Set OWNER_PASSWORD in the hosting environment; never commit credentials.
"""
from __future__ import annotations

import base64
import binascii
import hmac
import os
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response


def credentials_match(authorization: str | None, username: str, password: str) -> bool:
    if not authorization or not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(authorization[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    supplied_user, separator, supplied_password = decoded.partition(":")
    if not separator:
        return False
    return hmac.compare_digest(supplied_user, username) and hmac.compare_digest(supplied_password, password)


def install_owner_gate(app: FastAPI) -> None:
    @app.middleware("http")
    async def owner_only(request: Request, call_next):
        # The hosting platform needs an unauthenticated liveness endpoint.
        if request.url.path == "/api/health":
            return await call_next(request)

        expected_password = os.getenv("OWNER_PASSWORD", "")
        expected_username = os.getenv("OWNER_USERNAME", "owner")
        if not expected_password:
            return JSONResponse(
                status_code=503,
                content={"detail": "Owner access is not configured. Set OWNER_PASSWORD in the hosting environment."},
            )

        if not credentials_match(request.headers.get("authorization"), expected_username, expected_password):
            return Response(
                content="Owner sign-in required. Enter the studio credentials.",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Mind of AK AI Studio", charset="UTF-8"'},
                media_type="text/plain",
            )

        # Basic authentication is browser-managed; require a same-origin Origin
        # header on state-changing requests to reduce cross-site request forgery.
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            host = request.headers.get("host", "").lower()
            parsed = urlsplit(origin or "")
            same_backend_origin = bool(origin) and parsed.netloc.lower() == host and parsed.scheme in {"http", "https"}
            configured_origins = {
                value.strip().rstrip("/")
                for value in os.getenv("ALLOWED_ORIGINS", "").split(",")
                if value.strip()
            }
            allowed_frontend_origin = bool(origin) and origin.rstrip("/") in configured_origins
            if not (same_backend_origin or allowed_frontend_origin):
                return JSONResponse(status_code=403, content={"detail": "Cross-origin state changes are not allowed."})

        return await call_next(request)
