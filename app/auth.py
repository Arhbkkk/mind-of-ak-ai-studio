"""Small, fail-closed owner gate for the single-owner hosted studio.

Uses HTTP Basic over HTTPS and stores no credentials in the repository.
Set OWNER_PASSWORD in the hosting environment before exposing the app.
"""
from __future__ import annotations

import base64
import binascii
import hmac
import os

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
        # Keep health checks available to the hosting platform; protect the UI,
        # static assets, uploads, analysis, validation, exports and downloads.
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
        return await call_next(request)
