"""
User profile endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.auth import get_current_user
from app.models.user_orm import UserRecord
from app.schemas.auth import UserResponse, UserUpdateRequest

router = APIRouter(prefix="/users", tags=["users"])


def _user_record_to_response(user: UserRecord) -> UserResponse:
    """Convert ORM record to safe response model."""
    return UserResponse(
        user_id=user.user_id,
        email=user.email,
        name=user.name,
        role=user.role,
        phone=user.phone,
        picture=user.picture,
        calendar_preference=user.calendar_preference,
        credits=user.credits,
        is_approved=user.is_approved,
        created_at=user.created_at,
    )


@router.get("/me", response_model=UserResponse)
async def get_my_profile(current_user: UserRecord = Depends(get_current_user)):
    """Get the current user's full profile."""
    return _user_record_to_response(current_user)


@router.put("/me", response_model=UserResponse)
async def update_my_profile(
    body: UserUpdateRequest,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's profile."""
    update_data = body.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(current_user, field, value)

    await db.flush()
    return _user_record_to_response(current_user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_profile(
    user_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a public user profile by ID."""
    result = await db.execute(
        select(UserRecord).where(UserRecord.user_id == user_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return _user_record_to_response(user)
