"""The live chat channels (see app/core/realtime.py): a business's team channel and the public market channel."""

from pydantic import Field

from app.schemas.base import CamelModel


class ChatMessageIn(CamelModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatMessage(CamelModel):
    """One message in the team or market channel, as saved in the Realtime Database."""

    id: str = ""
    sender_uid: str
    sender_name: str
    business_id: str  # the business it was sent from
    business_name: str
    business_logo: str = ""
    message: str
    created_at: int


class ChatAccess(CamelModel):
    """What the browser needs to listen to the chats live. Asking for it also lets this user read them."""

    uid: str
    business_id: str
    team_path: str  # this business's team channel
    market_path: str  # the public market channel
