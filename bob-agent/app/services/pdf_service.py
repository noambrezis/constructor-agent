"""PDFMonkey PDF generation service.

Submits a document generation job to PDFMonkey, polls until the PDF is
ready, and returns the download URL so the caller can send it via Bridge.
"""

import asyncio
import json

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger()

PDFMONKEY_BASE = "https://api.pdfmonkey.io/api/v1"
POLL_INTERVAL = 1.0
MAX_POLL_SECONDS = 120


async def generate(template_data: dict) -> str:
    """Submit a PDFMonkey document generation job and return the download URL.

    Returns:
        HTTPS download URL for the generated PDF.

    Raises:
        RuntimeError: PDFMonkey reported an error status or HTTP error.
        TimeoutError: PDF was not ready within MAX_POLL_SECONDS.
    """
    auth = {"Authorization": f"Bearer {settings.PDFMONKEY_API_KEY}"}

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Create document generation job
        try:
            resp = await client.post(
                f"{PDFMONKEY_BASE}/document_generations",
                headers=auth,
                json={
                    "document_generation": {
                        "document_template_id": settings.PDFMONKEY_TEMPLATE_ID,
                        "payload": json.dumps(template_data),
                    }
                },
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("pdfmonkey_create_failed", status=exc.response.status_code, body=exc.response.text[:500])
            raise RuntimeError(f"PDFMonkey create failed ({exc.response.status_code}): {exc.response.text[:200]}") from exc

        doc_id = resp.json()["document_generation"]["id"]
        logger.info("pdfmonkey_job_submitted", doc_id=doc_id, template_id=settings.PDFMONKEY_TEMPLATE_ID)

        # 2. Poll until success or error
        elapsed = 0.0
        while elapsed < MAX_POLL_SECONDS:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

            try:
                status_resp = await client.get(
                    f"{PDFMONKEY_BASE}/document_generations/{doc_id}",
                    headers=auth,
                )
                status_resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error("pdfmonkey_poll_failed", doc_id=doc_id, status=exc.response.status_code, body=exc.response.text[:300])
                raise RuntimeError(f"PDFMonkey poll failed ({exc.response.status_code})") from exc

            data = status_resp.json()["document_generation"]
            status = data.get("status")
            logger.info("pdfmonkey_poll", doc_id=doc_id, status=status, elapsed=elapsed)

            if status == "success":
                url = data["download_url"]
                logger.info("pdfmonkey_pdf_ready", doc_id=doc_id, url=url[:80])
                return url

            if status == "error":
                errors = data.get("errors", "unknown")
                logger.error("pdfmonkey_generation_error", doc_id=doc_id, errors=errors)
                raise RuntimeError(f"PDFMonkey generation failed: {errors}")

        raise TimeoutError(
            f"PDFMonkey generation timed out after {MAX_POLL_SECONDS}s (doc {doc_id})"
        )
