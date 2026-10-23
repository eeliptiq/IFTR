"""
Authentication endpoints: register, login, get current user.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.auth import create_access_token, get_current_user
from app.core.security import hash_password, verify_password
from app.models.general import UserRole
from app.models.user_orm import UserRecord
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_record_to_response(user: UserRecord) -> UserResponse:
    """Convert ORM record to safe response model."""
    return UserResponse.from_record(user)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user account."""
    # Check duplicate email
    existing = await db.execute(
        select(UserRecord).where(UserRecord.email == body.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create user
    user = UserRecord(
        email=body.email,
        name=body.name,
        password_hash=hash_password(body.password.get_secret_value()),
        role=body.role.value,
        phone=body.phone,
        # Auto-approve customers; drivers/restaurant admins need admin approval
        is_approved=(body.role == UserRole.CUSTOMER),
    )
    db.add(user)
    await db.flush()  # assign user_id

    token = create_access_token(user.user_id, UserRole(user.role))

    return TokenResponse(
        access_token=token,
        user=_user_record_to_response(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate and return a JWT token."""
    result = await db.execute(
        select(UserRecord).where(UserRecord.email == body.email)
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(user.password_hash, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    token = create_access_token(user.user_id, UserRole(user.role))

    return TokenResponse(
        access_token=token,
        user=_user_record_to_response(user),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: UserRecord = Depends(get_current_user)):
    """Get the currently authenticated user's profile."""
    return _user_record_to_response(current_user)


@router.post("/logout")
async def logout():
    """
    Acknowledge a logout.

    There is no server-side session to end: authentication is a signed JWT the
    browser holds and discards. The endpoint exists because the ported sidebar
    posts to it, and answering `404` there made a working button look broken.

    The honest limitation is that a token cannot be revoked this way - it stays
    valid until it expires. Revocation needs a denylist or short-lived tokens
    with refresh, neither of which exists yet; the client clearing its copy is
    what logs this browser out.
    """
    return {"message": "Logged out"}
