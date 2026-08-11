"""Webhook signature verification for HoodGrow corporate-action webhooks."""

from __future__ import annotations

import hashlib
import hmac
import re

_HEX_64 = re.compile(r"\A[0-9a-fA-F]{64}\Z")


def verify_webhook_signature(
    raw_body: str | bytes,
    signature_header: str | None,
    secret: str,
) -> bool:
    """Verify the ``x-hoodgrow-signature`` header on an incoming webhook
    against the raw request body and your ``webhookSecret`` — HMAC-SHA256,
    constant-time compared.

    **Always call this before trusting a webhook body**, and always against
    the RAW bytes exactly as received (do not re-serialize the parsed JSON
    first — key order/whitespace changes break the digest).

    The header value is ``sha256=<hex>``; the leading ``sha256=`` is optional
    here. Returns ``False`` (never raises) for a missing header, a malformed
    hex signature, or any mismatch.

    Example (Flask)::

        from hoodgrow import verify_webhook_signature, WebhookEvent

        @app.post("/hooks")
        def hooks():
            if not verify_webhook_signature(
                request.get_data(), request.headers.get("x-hoodgrow-signature"), SECRET
            ):
                return "", 401
            event = WebhookEvent.model_validate_json(request.get_data())
            return "", 200
    """
    if not signature_header or not secret:
        return False

    provided = (
        signature_header[len("sha256=") :]
        if signature_header.startswith("sha256=")
        else signature_header
    )
    # Reject anything that isn't a clean 64-char hex digest up front.
    if not _HEX_64.match(provided):
        return False

    body_bytes = raw_body.encode("utf-8") if isinstance(raw_body, str) else bytes(raw_body)
    expected = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided.lower(), expected)
