"""Cloudflare Access JWT gate for the single-owner hosted studio.

The Worker forwards Cloudflare's signed Cf-Access-Jwt-Assertion header.
The API independently validates signature, issuer, and application audience,
so direct calls to the Render origin cannot bypass the edge login.
"""
from __future__ import annotations

import base64
import binascii
import hmac
import os
from functools import lru_cache
from urllib.parse import urlsplit

import jwt
from jwt import InvalidTokenError, PyJWKClient
from jwt.exceptions import PyJWKClientError
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ACCESS_JWT_HEADER = "cf-access-jwt-assertion"


def credentials_match(authorization: str | None, username: str, password: str) -> bool:
    """Legacy comparison helper retained for existing unit tests; not an auth path."""
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


@lru_cache(maxsize=4)
def _jwks_client(team_domain: str) -> PyJWKClient:
    return PyJWKClient(
        f"{team_domain}/cdn-cgi/access/certs",
        cache_keys=True,
        lifespan=3600,
    )


def _validated_identity(token: str, team_domain: str, audience: str) -> dict:
    signing_key = _jwks_client(team_domain).get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=audience,
        issuer=team_domain,
        options={"require": ["exp", "iat", "iss", "aud"]},
    )


def install_owner_gate(app: FastAPI) -> None:
    @app.middleware("http")
    async def cloudflare_access_only(request: Request, call_next):
        # Keep the platform liveness endpoint public for Render health checks.
        if request.url.path == "/api/health":
            return await call_next(request)

        team_domain = os.getenv("ACCESS_TEAM_DOMAIN", "").strip().rstrip("/")
        audience = os.getenv("ACCESS_AUD", "").strip()
        if not team_domain or not audience:
            return JSONResponse(
                status_code=503,
                content={"detail": "Cloudflare Access is not fully configured on the API."},
            )

        parsed_team = urlsplit(team_domain)
        if parsed_team.scheme != "https" or not parsed_team.netloc or parsed_team.path:
            return JSONResponse(status_code=503, content={"detail": "Invalid ACCESS_TEAM_DOMAIN configuration."})

        token = request.headers.get(ACCESS_JWT_HEADER)
        if not token:
            return JSONResponse(status_code=401, content={"detail": "Cloudflare Access sign-in required."})

        try:
            _validated_identity(token, team_domain, audience)
        except (InvalidTokenError, PyJWKClientError, ValueError):
            return JSONResponse(status_code=401, content={"detail": "Cloudflare Access token is invalid or expired."})
        except Exception:
            # Fail closed if the signing-key service is temporarily unavailable.
            return JSONResponse(status_code=503, content={"detail": "Could not verify Cloudflare Access identity. Retry shortly."})

        # Protect state-changing endpoints against cross-origin browser requests.
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
