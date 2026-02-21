import hmac

from fastapi import HTTPException

from app.config import settings


def verify_webhook_secret(x_webhook_secret: str | None) -> None:
    """Validate the X-Webhook-Secret header. Uses hmac.compare_digest to prevent timing attacks."""
    if not x_webhook_secret:
        raise HTTPException(status_code=401, detail="Missing X-Webhook-Secret header")
    if not hmac.compare_digest(x_webhook_secret, settings.WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


def verify_admin_key(x_admin_key: str | None) -> None:
    """Validate the X-Admin-Key header for admin endpoints."""
    if not x_admin_key:
        raise HTTPException(status_code=401, detail="Missing X-Admin-Key header")
    if not hmac.compare_digest(x_admin_key, settings.ADMIN_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid admin key")
