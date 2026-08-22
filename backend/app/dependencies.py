"""FastAPI dependency injection: DB connection and JWT auth."""
import uuid
from typing import AsyncGenerator

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.database import engine
from app.models.tables import users

security = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncConnection, None]:
    """FastAPI dependency: yields an async DB connection with auto-commit on success."""
    async with engine.connect() as conn:
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncConnection = Depends(get_db),
) -> dict:
    """Validate a Bearer JWT and return the current user row as a dict.

    Raises 401 if the token is missing, invalid, expired, or the user no
    longer exists in the database.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "NOT_AUTHENTICATED", "message": "Not authenticated", "details": {}},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Import here to avoid circular import (auth service → config ← dependencies)
    from app.services.auth import decode_token  # noqa: PLC0415

    try:
        user_id: uuid.UUID = decode_token(credentials.credentials, "access")
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Invalid or expired token", "details": {}},
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(
        select(
            users.c.id,
            users.c.email,
            users.c.name,
            users.c.created_at,
        ).where(users.c.id == user_id)
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "USER_NOT_FOUND", "message": "User no longer exists", "details": {}},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return dict(row)
