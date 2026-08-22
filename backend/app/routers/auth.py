"""Auth router: register, login, refresh, me."""
import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.dependencies import get_db, get_current_user
from app.models.tables import users, organization_members, organizations
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    AccessTokenResponse,
    UserResponse,
    OrgMembershipResponse,
)
from app.services.auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(body: RegisterRequest, db: AsyncConnection = Depends(get_db)):
    """Create a new user account."""
    # Check for duplicate email
    existing = await db.execute(
        select(users.c.id).where(users.c.email == body.email)
    )
    if existing.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "EMAIL_TAKEN", "message": "Email already registered", "details": {}},
        )

    result = await db.execute(
        insert(users)
        .values(
            email=body.email,
            password_hash=hash_password(body.password),
            name=body.name,
        )
        .returning(
            users.c.id,
            users.c.email,
            users.c.name,
            users.c.created_at,
        )
    )
    row = result.mappings().one()
    return UserResponse(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        created_at=row["created_at"],
        memberships=[],
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncConnection = Depends(get_db)):
    """Exchange credentials for access + refresh tokens."""
    result = await db.execute(
        select(users.c.id, users.c.password_hash).where(users.c.email == body.email)
    )
    row = result.mappings().first()
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Invalid email or password", "details": {}},
        )
    user_id: uuid.UUID = row["id"]
    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(body: RefreshRequest, db: AsyncConnection = Depends(get_db)):
    """Exchange a refresh token for a new access token."""
    try:
        user_id = decode_token(body.refresh_token, "refresh")
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Invalid or expired refresh token", "details": {}},
        )
    # Verify user still exists
    result = await db.execute(select(users.c.id).where(users.c.id == user_id))
    if result.first() is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "USER_NOT_FOUND", "message": "User no longer exists", "details": {}},
        )
    return AccessTokenResponse(access_token=create_access_token(user_id))


@router.get("/me", response_model=UserResponse)
async def me(
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
):
    """Return current user profile and org memberships."""
    result = await db.execute(
        select(
            organization_members.c.organization_id,
            organization_members.c.role,
            organizations.c.name.label("organization_name"),
        )
        .join(organizations, organizations.c.id == organization_members.c.organization_id)
        .where(organization_members.c.user_id == current_user["id"])
    )
    memberships = [
        OrgMembershipResponse(
            organization_id=r["organization_id"],
            organization_name=r["organization_name"],
            role=r["role"],
        )
        for r in result.mappings()
    ]
    return UserResponse(
        id=current_user["id"],
        email=current_user["email"],
        name=current_user["name"],
        created_at=current_user["created_at"],
        memberships=memberships,
    )
