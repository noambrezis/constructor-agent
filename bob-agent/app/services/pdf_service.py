"""PDFMonkey PDF generation service.

Submits a document generation job to PDFMonkey, polls until the PDF is
ready, and returns the download URL so the caller can send it via Bridge.
"""

import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

PDFMONKEY_BASE = "https://api.pdfmonkey.io/api/v1"
POLL_INTERVAL = 1.0
MAX_POLL_SECONDS = 120


async def generate(template_data: dict) -> str:
    """Submit a PDFMonkey document generation job and return the download URL.

    Args:
        template_data: Arbitrary dict that will be serialised to JSON and
            passed as the document payload to the PDFMonkey template.

    Returns:
        HTTPS download URL for the generated PDF.

    Raises:
        RuntimeError: PDFMonkey reported an error status.
        TimeoutError: PDF was not ready within MAX_POLL_SECONDS.
        httpx.HTTPStatusError: Non-2xx HTTP response from PDFMonkey.
    """
    import json

    auth = {"Authorization": f"Bearer {settings.PDFMONKEY_API_KEY}"}

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Create document generation job
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
        doc_id = resp.json()["document_generation"]["id"]
        logger.info("pdfmonkey_job_submitted", extra={"doc_id": doc_id})

        # 2. Poll until success or error
        elapsed = 0.0
        while elapsed < MAX_POLL_SECONDS:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

            status_resp = await client.get(
                f"{PDFMONKEY_BASE}/document_generations/{doc_id}",
                headers=auth,
            )
            status_resp.raise_for_status()
            data = status_resp.json()["document_generation"]
            status = data.get("status")

            if status == "success":
                url = data["download_url"]
                logger.info("pdfmonkey_pdf_ready", extra={"doc_id": doc_id})
                return url

            if status == "error":
                errors = data.get("errors", "unknown")
                raise RuntimeError(f"PDFMonkey generation failed (doc {doc_id}): {errors}")

        raise TimeoutError(
            f"PDFMonkey generation timed out after {MAX_POLL_SECONDS}s (doc {doc_id})"
        )
