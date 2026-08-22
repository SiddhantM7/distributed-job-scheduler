"""Pydantic schemas for organization and member endpoints."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CreateOrgRequest(BaseModel):
    name: str = Field(min_length=1)
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9-]+$")


class OrgResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime


class AddMemberRequest(BaseModel):
    user_id: uuid.UUID
    role: Literal["owner", "admin", "member"] = "member"


class MemberResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    created_at: datetime
