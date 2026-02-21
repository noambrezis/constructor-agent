from pydantic import BaseModel


class OriginalMessage(BaseModel):
    text: str | None = None


class MessageBody(BaseModel):
    messageId: str
    groupId: str                              # WhatsApp JID e.g. "120363XXXXX@g.us"
    sender: str                               # WhatsApp JID of sender
    reactor: str | None = None               # JID of person who reacted (reactions only)
    messageText: str | None = None
    type: str                                 # "message" | "reaction"
    emoji: str | None = None                 # e.g. "👍"
    mediaUrl: str | None = None
    mediaType: str | None = None             # "image" | "video" | "audio"
    mediaPlaybackUrl: str | None = None
    sonioxFileId: str | None = None          # Pre-uploaded Soniox file ID
    originalMessage: OriginalMessage | None = None


class WebhookPayload(BaseModel):
    body: MessageBody
