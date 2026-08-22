"""Pydantic schemas for retry policy endpoints."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CreateRetryPolicyRequest(BaseModel):
    """Request body for creating a retry policy."""

    name: str = Field(min_length=1)
    strategy: Literal["fixed", "linear", "exponential"] = "exponential"
    base_delay_seconds: int = Field(default=5, ge=0)
    max_delay_seconds: int | None = Field(default=None, ge=0)
    multiplier: Decimal | None = Field(default=Decimal("2.0"), gt=0)
    max_attempts: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def check_max_delay(self) -> "CreateRetryPolicyRequest":
        """Ensure max_delay_seconds >= base_delay_seconds when provided."""
        if (
            self.max_delay_seconds is not None
            and self.max_delay_seconds < self.base_delay_seconds
        ):
            raise ValueError("max_delay_seconds must be >= base_delay_seconds")
        return self


class UpdateRetryPolicyRequest(BaseModel):
    """Request body for patching a retry policy. All fields optional."""

    name: str | None = Field(default=None, min_length=1)
    strategy: Literal["fixed", "linear", "exponential"] | None = None
    base_delay_seconds: int | None = Field(default=None, ge=0)
    max_delay_seconds: int | None = Field(default=None, ge=0)
    multiplier: Decimal | None = Field(default=None, gt=0)
    max_attempts: int | None = Field(default=None, ge=1)


class RetryPolicyResponse(BaseModel):
    """Retry policy representation."""

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    strategy: str
    base_delay_seconds: int
    max_delay_seconds: int | None
    multiplier: Decimal | None
    max_attempts: int
    created_at: datetime
