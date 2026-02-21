import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings


class BridgeClient:
    def __init__(self) -> None:
        # Populated by startup(); None until then
        self._client: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.BRIDGE_URL,
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def shutdown(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("BridgeClient not initialized — call startup() first")
        return self._client

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
    async def send_message(self, group_id: str, message: str) -> None:
        resp = await self.client.post(
            "/send-message", json={"groupId": group_id, "message": message}
        )
        resp.raise_for_status()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
    async def send_messages(self, group_id: str, messages: list[str]) -> None:
        # Bridge /send-messages expects objects with a consolidated_info field
        resp = await self.client.post(
            "/send-messages",
            json={"groupId": group_id, "messages": [{"consolidated_info": m} for m in messages]},
        )
        resp.raise_for_status()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
    async def send_document(
        self, group_id: str, document_url: str, filename: str, caption: str = ""
    ) -> None:
        resp = await self.client.post(
            "/send-document",
            json={
                "groupId": group_id,
                "documentUrl": document_url,
                "filename": filename,
                "caption": caption,
            },
        )
        resp.raise_for_status()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
    async def confirm_processing(self, message_id: str) -> None:
        """Always call this — even on error — so the Bridge releases its queue slot."""
        resp = await self.client.post(
            "/confirm-processing", json={"messageId": message_id}
        )
        resp.raise_for_status()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
    async def schedule_message(
        self, group_id: str, name: str, start_date: str
    ) -> None:
        resp = await self.client.post(
            "/schedule-message",
            json={"groupId": group_id, "name": name, "startDate": start_date},
        )
        resp.raise_for_status()


# Module-level singleton — initialized in FastAPI lifespan
bridge = BridgeClient()
