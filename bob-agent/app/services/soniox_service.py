"""Soniox speech-to-text service.

The WhatsApp Bridge pre-uploads audio files to Soniox and passes the resulting
file_id in the webhook payload (MessageBody.sonioxFileId). This service:
  1. Submits a transcription job using that file_id
  2. Polls until the job completes (up to STT_TIMEOUT_SECONDS)
  3. Fetches and returns the transcript text

Hebrew construction vocabulary is injected via the context hints so the model
recognises domain-specific terms (supplier names, locations, defect terminology).
"""

import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SONIOX_BASE = "https://api.soniox.com/v1"
POLL_INTERVAL = 1.0

CONSTRUCTION_TERMS = [
    "ליקוי", "ליקויים", "רטיבות", "סדק", "סדקים", "קילוף", "התנפחות",
    "טיח", "ריצוף", "אריחים", "איטום", "נזילה", "עובש", "בטון", "שלד",
    "תשתית", "ביסוס", "פיגום", "אינסטלציה", "חשמל", "גבס", "פרקט",
    "חלון", "דלת", "מסגרת", "קבלן", "קבלן משנה", "מפקח", "דירה",
    "קומה", "יחידה", "תיקון", "טיפול", "אחריות", "בדיקה", "פרוטוקול",
]


async def transcribe(file_id: str, site_context: dict) -> str:
    """Submit *file_id* for transcription, poll until done, return transcript.

    Args:
        file_id: Soniox file ID pre-uploaded by the WhatsApp Bridge.
        site_context: Site context dict with optional ``locations`` and
            ``suppliers`` lists to improve recognition accuracy.

    Returns:
        Transcript text (may be empty string if Soniox returns no text).

    Raises:
        TimeoutError: Transcription did not complete within STT_TIMEOUT_SECONDS.
        httpx.HTTPStatusError: Non-2xx response from the Soniox API.
    """
    auth = {"Authorization": f"Bearer {settings.SONIOX_API_KEY}"}
    max_poll = settings.STT_TIMEOUT_SECONDS

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Submit transcription job
        resp = await client.post(
            f"{SONIOX_BASE}/transcriptions",
            headers=auth,
            json={
                "model": "stt-async-preview",
                "file_id": file_id,
                "language_hints": ["he", "en"],
                "context": {
                    "general": [
                        {"key": "domain", "value": "ניהול ליקויי בנייה"},
                        {"key": "topic", "value": "דיווח ליקויים באתר בנייה"},
                    ],
                    "terms": [
                        *CONSTRUCTION_TERMS,
                        *site_context.get("locations", []),
                        *site_context.get("suppliers", []),
                    ],
                },
            },
        )
        resp.raise_for_status()
        job_id = resp.json()["id"]
        logger.info("soniox_job_submitted", extra={"job_id": job_id})

        # 2. Poll for completion
        elapsed = 0.0
        while elapsed < max_poll:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

            status_resp = await client.get(
                f"{SONIOX_BASE}/transcriptions/{job_id}",
                headers=auth,
            )
            status_resp.raise_for_status()
            status = status_resp.json().get("status")

            if status == "completed":
                break
            if status == "failed":
                raise RuntimeError(f"Soniox transcription failed for job {job_id}")
        else:
            raise TimeoutError(
                f"Soniox transcription timed out after {max_poll}s (job {job_id})"
            )

        # 3. Fetch transcript text
        transcript_resp = await client.get(
            f"{SONIOX_BASE}/transcriptions/{job_id}/transcript",
            headers=auth,
        )
        transcript_resp.raise_for_status()
        text = transcript_resp.json().get("text", "")
        logger.info("soniox_transcript_ready", extra={"job_id": job_id, "length": len(text)})
        return text
