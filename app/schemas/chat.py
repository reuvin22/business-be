"""The live chat channels (see app/core/realtime.py): a business's team channel and the public market channel."""

from pydantic import Field, model_validator

from app.schemas.base import CamelModel, UrlText

MAX_PHOTOS = 4  # photos in one message


class ChatMessageIn(CamelModel):
    message: str = Field(default="", max_length=2000)
    attachments: list[UrlText] = Field(default=[], max_length=MAX_PHOTOS)  # photos (uploaded with kind=chat)

    @model_validator(mode="after")
    def text_or_photos(self):
        if not self.message.strip() and not self.attachments:
            raise ValueError("write a message or add a photo")
        return self


class ChatMessage(CamelModel):
    """One message in the team or market channel, as saved in the Realtime Database."""

    id: str = ""
    sender_uid: str
    sender_name: str
    business_id: str  # the business it was sent from
    business_name: str
    business_logo: str = ""
    message: str
    attachments: list[str] = []  # photos
    edited_at: int | None = None  # set when the sender changed the text
    created_at: int


class ChatAccess(CamelModel):
    """What the browser needs to listen to the chats live. Asking for it also lets this user read them."""

    uid: str
    business_id: str
    team_path: str  # this business's team channel
    market_path: str  # the public market channel


class MessageEditIn(CamelModel):
    """The new text of a message (its photos and order card stay as they are)."""

    message: str = Field(default="", max_length=2000)
