"""`/agent/*` and webhooks need `Authorization: Bearer $INTERNAL_TOKEN` (CONTRACT §2)."""

import hmac

from fastapi import Header, HTTPException, status

from api.core.config import get_settings


async def require_internal_token(authorization: str = Header(default="")) -> None:
    expected = f"Bearer {get_settings().internal_token}"
    if not hmac.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad or missing internal token")
