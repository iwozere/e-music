"""
Pydantic request/response schemas (API contracts).
"""
from datetime import datetime
from typing import Optional

from typing import List

from pydantic import BaseModel, ConfigDict, Field, EmailStr


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: str
    role: str
    created_at: datetime


class RegisterBody(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class GoogleAuthBody(BaseModel):
    id_token: str = Field(min_length=10)


class RefreshBody(BaseModel):
    refresh_token: str = Field(min_length=10)


class StreamGrantBody(BaseModel):
    track_id: str = Field(min_length=1, max_length=128)


class LogoutBody(BaseModel):
    refresh_token: Optional[str] = None


class PairBody(BaseModel):
    pin: str = Field(min_length=4, max_length=32)


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AiShuffleBody(BaseModel):
    track_ids: List[str] = Field(default_factory=list, description="Ordered list of recently played track IDs (internal UUIDs or remote_ids)")
