from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Optional

import requests
from jose import JWTError, jwk, jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

_BEARER = HTTPBearer(auto_error=False)

COGNITO_REGION = "ap-southeast-2"
COGNITO_POOL_ID = "ap-southeast-2_2T8FIQjdI"
COGNITO_CLIENT_ID = "5k854jhjc38pfao09p4rhghp5h"
COGNITO_ISSUER = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_POOL_ID}"
JWKS_URL = f"{COGNITO_ISSUER}/.well-known/jwks.json"


@lru_cache(maxsize=1)
def _get_jwks() -> dict:
    try:
        resp = requests.get(JWKS_URL, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("Failed to fetch JWKS: %s", exc)
        return {"keys": []}


def _find_key(kid: str) -> Optional[dict]:
    jwks = _get_jwks()
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    # Refresh once and retry
    _get_jwks.cache_clear()
    jwks = _get_jwks()
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


def verify_cognito_token(token: str) -> dict[str, Any]:
    try:
        headers = jwt.get_unverified_headers(token)
        kid = headers.get("kid")
        if not kid:
            raise HTTPException(status_code=401, detail="Malformed token")

        key_data = _find_key(kid)
        if key_data is None:
            raise HTTPException(status_code=401, detail="Token key not found")

        public_key = jwk.construct(key_data)
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=COGNITO_CLIENT_ID,
            issuer=COGNITO_ISSUER,
        )
        return claims
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_BEARER),
) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return verify_cognito_token(credentials.credentials)
