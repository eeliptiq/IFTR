"""
Organization endpoints: sign up a food bank, shelter or community kitchen.

Mounted under /api (see app/main.py).

Registration is the organization half of what restaurant registration does for a
kitchen: it creates the record and promotes the account's role, so the
organization screens unlock. Nothing here verifies an organization; that is an
admin decision, and an unverified organization can browse surplus food but not
reserve it (see app/api/surplus.py).

Read rules are deliberately narrower than "list everything":

  * verified organizations are public to signed-in accounts, which is what the
    browsing screens need;
  * an unverified record is visible only to the account that registered it,
    because otherwise `verified_only=false` - a parameter the registration page
    passes just to find itself - would publish every pending application.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import change_role
from app.core.auth import get_current_user
from app.core.encryption import encrypt_data
from app.database import get_db
from app.models.general import UserRole
from app.models.organization_orm import OrganizationRecord
from app.models.user_orm import UserRecord
from app.schemas.organization import (
    OrganizationCreateRequest,
    OrganizationResponse,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])

ORGANIZATION_NOT_FOUND = "Organization not found"


async def current_organization(
    db: AsyncSession, user: UserRecord
) -> Optional[OrganizationRecord]:
    """The organization belonging to this account, or None."""
    result = await db.execute(
        select(OrganizationRecord).where(OrganizationRecord.user_id == user.user_id)
    )
    return result.scalar_one_or_none()


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization(
    body: OrganizationCreateRequest,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register an organization for the current account."""
    if await current_organization(db, current_user) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already registered an organization",
        )

    organization = OrganizationRecord(
        user_id=current_user.user_id,
        name=body.name.strip(),
        description=body.description,
        org_type=body.org_type.strip(),
        lat_encrypted=encrypt_data(str(body.lat)),
        lng_encrypted=encrypt_data(str(body.lng)),
        address=body.address.strip(),
        city=body.city.strip(),
        contact_email=body.contact_email.strip(),
        contact_phone=body.contact_phone.strip(),
        delivery_address=body.delivery_address,
    )
    db.add(organization)

    # Promote the account so the organization-specific navigation unlocks, as
    # registering a restaurant does for its owner. Recorded with the role they
    # held before, so the trail says what onboarding actually replaced.
    change_role(
        db,
        current_user,
        UserRole.ORGANIZATION_ADMIN.value,
        detail="registered an organization",
    )

    await db.flush()
    return OrganizationResponse.from_record(organization)


@router.get("", response_model=List[OrganizationResponse])
async def list_organizations(
    verified_only: bool = True,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List organizations, verified ones only by default.

    `verified_only=false` adds the caller's own record if it is still pending -
    the registration page's way of asking "did my application go through?" - but
    does not expose anybody else's unverified application.
    """
    query = select(OrganizationRecord)
    if verified_only:
        query = query.where(OrganizationRecord.is_verified.is_(True))
    else:
        query = query.where(
            or_(
                OrganizationRecord.is_verified.is_(True),
                OrganizationRecord.user_id == current_user.user_id,
            )
        )

    result = await db.execute(query.order_by(OrganizationRecord.name.asc()))
    return [
        OrganizationResponse.from_record(record)
        for record in result.scalars().all()
    ]


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: str,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """One organization: any verified one, or the caller's own pending record."""
    result = await db.execute(
        select(OrganizationRecord).where(OrganizationRecord.org_id == org_id)
    )
    organization = result.scalar_one_or_none()

    # A pending application belonging to somebody else is reported as missing
    # rather than forbidden: whether a given food bank has applied yet is not
    # the caller's business.
    if organization is None or (
        not organization.is_verified
        and organization.user_id != current_user.user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ORGANIZATION_NOT_FOUND,
        )
    return OrganizationResponse.from_record(organization)
