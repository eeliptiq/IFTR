"""
Admin controls: roles, account activity, organization verification, and the
trail of all three.

Every change here is a durable fact about an account or an organization, so
every change is written to `audit_events` in the same transaction with the actor
and the value before and after. Three guards are deliberate:

  * the last *active* administrator cannot be demoted or suspended, so the
    deployment cannot be left with nobody able to administer it or reactivate
    an account;
  * suspension blocks sign-in and every request made with an existing token,
    without touching the role or the records the account owns;
  * verification is a one-way door per request - unverifying blocks new
    reservations but does not rewrite reservations already accepted.

The console that drives all of this lives at `/admin/users` in the frontend;
the read models it needs (`GET /admin/users`, `/admin/organizations`,
`/admin/audit`) sit alongside the writes. `GET /admin/stats` is the
administrator dashboard's summary; it shares its aggregation with the
community impact feed (`GET /impact/stats`) rather than counting twice.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import (
    DELIVERY_REASSIGNED,
    ORGANIZATION_UNVERIFIED,
    ORGANIZATION_VERIFIED,
    USER_REACTIVATED,
    USER_SUSPENDED,
    change_role,
    record_event,
)
from app.api.impact import collect_stats
from app.core.auth import require_role
from app.database import get_db
from app.models.audit_orm import AuditEventRecord
from app.models.driver_orm import DriverRecord
from app.models.general import OrderStatus, UserRole
from app.models.organization_orm import OrganizationRecord
from app.models.order_orm import OrderRecord
from app.models.payment_orm import PAYMENT_PAID, OrderPaymentRecord
from app.models.surplus_food import SurplusDeliveryStatus
from app.models.surplus_food_orm import SurplusDeliveryRecord
from app.models.user_orm import UserRecord
from app.schemas.admin import (
    AccountStatusRequest,
    AccountStatusResponse,
    AdminOrganizationResponse,
    AdminStatsResponse,
    RoleChangeRequest,
)
from app.schemas.audit import AuditEventResponse
from app.schemas.auth import UserResponse
from app.schemas.organization import OrganizationResponse

router = APIRouter(prefix="/admin", tags=["admin"])

ORGANIZATION_NOT_FOUND = "Organization not found"
USER_NOT_FOUND = "User not found"

# What a suspended driver still has to be relieved of. An accepted order or
# volunteer run has not moved yet, so the platform can hand it to somebody else.
# Once it has been collected, only the person holding the food can finish it; a
# reassignment would send the next driver to a kitchen that no longer has it.
RELEASABLE_ORDER_STATUSES = (OrderStatus.ASSIGNED.value,)
RELEASABLE_RUN_STATUSES = (SurplusDeliveryStatus.ASSIGNED.value,)
HELD_STATUS_LABEL = "already collected a delivery"

ACTIVE_ORDER_STATUSES = (
    OrderStatus.ASSIGNED.value,
    OrderStatus.PICKED_UP.value,
    OrderStatus.IN_TRANSIT.value,
)
ACTIVE_RUN_STATUSES = (
    SurplusDeliveryStatus.ASSIGNED.value,
    SurplusDeliveryStatus.PICKED_UP.value,
    SurplusDeliveryStatus.IN_TRANSIT.value,
)


async def _active_driver_jobs(
    db: AsyncSession, driver_id: str
) -> tuple[List[OrderRecord], List[SurplusDeliveryRecord]]:
    """The work a driver has accepted or collected, orders and volunteer runs.

    A separate read so the release below has one place to ask "what is on this
    driver's plate", and so the concurrency test can put a transition in the
    window between the read and the write.
    """
    orders = list(
        (
            await db.execute(
                select(OrderRecord).where(
                    OrderRecord.driver_id == driver_id,
                    OrderRecord.status.in_(ACTIVE_ORDER_STATUSES),
                )
            )
        )
        .scalars()
        .all()
    )
    runs = list(
        (
            await db.execute(
                select(SurplusDeliveryRecord).where(
                    SurplusDeliveryRecord.driver_id == driver_id,
                    SurplusDeliveryRecord.status.in_(ACTIVE_RUN_STATUSES),
                )
            )
        )
        .scalars()
        .all()
    )
    return orders, runs


async def _release_driver_work(
    db: AsyncSession, target: UserRecord, actor: UserRecord
) -> int:
    """Return a suspended driver's uncollected work to the available pool.

    Reads the driver's active jobs, refuses the suspension when any of them has
    already been collected, and otherwise writes each accepted one back to the
    pool it came from: an order to `ready` so it appears on the driver board, a
    volunteer run to `pending` so it appears on the volunteer board. The row and
    the audit entry for it are written in the caller's transaction, so a refused
    suspension cannot leave a reassigned delivery behind.

    Each release is a conditional UPDATE that only matches while the row is
    still the job that was read. A transition landing in that window - the
    driver collecting the food, or a new job being accepted - leaves rows for
    the leftover check below to find, and the whole suspension is refused
    rather than overwriting a fact that arrived first.

    Returns how many deliveries were returned.
    """
    driver_result = await db.execute(
        select(DriverRecord).where(DriverRecord.user_id == target.user_id)
    )
    driver = driver_result.scalar_one_or_none()
    if driver is None:
        return 0

    orders, runs = await _active_driver_jobs(db, driver.driver_id)

    held = [row for row in orders if row.status not in RELEASABLE_ORDER_STATUSES]
    held += [row for row in runs if row.status not in RELEASABLE_RUN_STATUSES]
    if held:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot suspend a driver who has {HELD_STATUS_LABEL}; "
                "finish or resolve it first"
            ),
        )

    now = datetime.now(timezone.utc)
    released = 0
    for order in orders:
        # Only the exact row that was read is released. `synchronize_session` is
        # off because the loaded object is deliberately left stale: the next
        # read must come from the database, which is where a racing transition
        # would have landed.
        reclaimed = await db.execute(
            update(OrderRecord)
            .where(OrderRecord.order_id == order.order_id)
            .where(OrderRecord.driver_id == driver.driver_id)
            .where(OrderRecord.status == OrderStatus.ASSIGNED.value)
            .values(
                status=OrderStatus.READY.value,
                driver_id=None,
                driver_name="",
                assigned_at=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if reclaimed.rowcount != 1:
            continue
        record_event(
            db,
            action=DELIVERY_REASSIGNED,
            subject_type="order",
            subject_id=order.order_id,
            from_value=OrderStatus.ASSIGNED.value,
            to_value=OrderStatus.READY.value,
            actor=actor,
            detail="returned to the available pool when the driver was suspended",
        )
        released += 1

    for run in runs:
        reclaimed = await db.execute(
            update(SurplusDeliveryRecord)
            .where(SurplusDeliveryRecord.delivery_id == run.delivery_id)
            .where(SurplusDeliveryRecord.driver_id == driver.driver_id)
            .where(
                SurplusDeliveryRecord.status
                == SurplusDeliveryStatus.ASSIGNED.value
            )
            .values(
                status=SurplusDeliveryStatus.PENDING.value,
                driver_id=None,
                driver_name="",
                assigned_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        if reclaimed.rowcount != 1:
            continue
        record_event(
            db,
            action=DELIVERY_REASSIGNED,
            subject_type="surplus_delivery",
            subject_id=run.delivery_id,
            from_value=SurplusDeliveryStatus.ASSIGNED.value,
            to_value=SurplusDeliveryStatus.PENDING.value,
            actor=actor,
            detail="returned to the volunteer pool when the driver was suspended",
        )
        released += 1

    # The audit rows are pending in the session; flush them so the leftover
    # reads below see a consistent database rather than relying on autoflush.
    await db.flush()

    # A job can be claimed between the read above and this write. Suspending
    # with fresh work stranded on the account is the state this whole path
    # exists to avoid, so refuse instead: the session rolls back both the
    # suspension and the reassignments.
    leftover_orders = await db.scalar(
        select(func.count())
        .select_from(OrderRecord)
        .where(
            OrderRecord.driver_id == driver.driver_id,
            OrderRecord.status.in_(ACTIVE_ORDER_STATUSES),
        )
    )
    leftover_runs = await db.scalar(
        select(func.count())
        .select_from(SurplusDeliveryRecord)
        .where(
            SurplusDeliveryRecord.driver_id == driver.driver_id,
            SurplusDeliveryRecord.status.in_(ACTIVE_RUN_STATUSES),
        )
    )
    if (leftover_orders or 0) + (leftover_runs or 0):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The driver's work changed while suspending them; "
                "try again"
            ),
        )

    return released


async def _active_administrator_count(db: AsyncSession) -> int:
    total = await db.scalar(
        select(func.count())
        .select_from(UserRecord)
        .where(
            UserRecord.role == UserRole.ADMIN.value,
            UserRecord.is_active.is_(True),
        )
    )
    return int(total or 0)


@router.put(
    "/organizations/{org_id}/verify",
    response_model=OrganizationResponse,
)
async def verify_organization(
    org_id: str,
    current_user=Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark an organization verified, so it may reserve surplus food.

    Idempotent: verifying an already-verified organization is the same fact
    stated again, which keeps a retried tap from being an error the admin has to
    interpret. The counterpart is `DELETE /admin/organizations/{id}/verify`;
    both directions are recorded, so an organization's standing can be read as
    history rather than as a toggle with no memory.
    """
    result = await db.execute(
        select(OrganizationRecord).where(OrganizationRecord.org_id == org_id)
    )
    organization = result.scalar_one_or_none()
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ORGANIZATION_NOT_FOUND,
        )

    # Only the transition is history. A retried tap on an already-verified
    # organization states the same fact again and adds nothing to the trail.
    if not organization.is_verified:
        organization.is_verified = True
        record_event(
            db,
            action=ORGANIZATION_VERIFIED,
            subject_type="organization",
            subject_id=organization.org_id,
            from_value="unverified",
            to_value="verified",
            actor=current_user,
            detail="verified for surplus reservations",
        )

    await db.flush()
    return OrganizationResponse.from_record(organization)


@router.delete("/organizations/{org_id}/verify", response_model=OrganizationResponse)
async def unverify_organization(
    org_id: str,
    current_user=Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    Take an organization's verification away.

    New reservations are refused immediately, because the reserve path checks
    the flag. Reservations already accepted are left alone: a volunteer may be
    holding that food, and cancelling a run because paperwork changed would
    waste the rescue it was meant to make.

    Idempotent, like verification: unverifying an unverified organization states
    the same fact again and adds nothing to the trail.
    """
    result = await db.execute(
        select(OrganizationRecord).where(OrganizationRecord.org_id == org_id)
    )
    organization = result.scalar_one_or_none()
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ORGANIZATION_NOT_FOUND,
        )

    if organization.is_verified:
        organization.is_verified = False
        record_event(
            db,
            action=ORGANIZATION_UNVERIFIED,
            subject_type="organization",
            subject_id=organization.org_id,
            from_value="verified",
            to_value="unverified",
            actor=current_user,
            detail="unverified; new reservations are blocked",
        )

    await db.flush()
    return OrganizationResponse.from_record(organization)


@router.put("/users/{user_id}/role", response_model=UserResponse)
async def change_user_role(
    user_id: str,
    body: RoleChangeRequest,
    current_user=Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    Grant or revoke a role.

    This is the deliberate counterpart to registration's refusal to grant admin:
    once one administrator exists, administrators can hand roles out and take
    them back, and each transition is recorded.

    Demoting the last active administrator is refused. Everybody else may be
    demoted, including the caller (an administrator stepping down), because the
    guard is about whether the deployment still has an administrator who can
    sign in. A suspended administrator is not counted: reactivating them is the
    path back, not a role change.

    The role is a label and an onboarding flag, not the whole authorization
    story: restaurant, driver and organization endpoints decide by the records
    the account owns. Revoking one of those roles does not delete the record.
    """
    result = await db.execute(
        select(UserRecord).where(UserRecord.user_id == user_id)
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=USER_NOT_FOUND
        )

    new_role = body.role.value
    if (
        target.role == UserRole.ADMIN.value
        and target.is_active
        and new_role != UserRole.ADMIN.value
        and await _active_administrator_count(db) <= 1
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot remove the last administrator",
        )

    change_role(
        db,
        target,
        new_role,
        detail="changed by an administrator",
        actor=current_user,
    )
    await db.flush()
    return UserResponse.from_record(target)


@router.put("/users/{user_id}/active", response_model=AccountStatusResponse)
async def set_user_active(
    user_id: str,
    body: AccountStatusRequest,
    current_user=Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    Suspend or reactivate an account.

    Suspension is the stronger alternative to taking a role away: the role and
    every record the account owns stay put, but login and every request made
    with an already-issued token are refused until an administrator reactivates
    it. That makes it the tool for an account whose access must stop without
    rewriting the data it is responsible for.

    Suspending a driver also returns the work they have accepted but not yet
    collected to the pool, so a locked-out account cannot strand a delivery that
    is still waiting on the platform. A driver who has already collected the
    food is refused instead: the delivery cannot be handed to somebody else, and
    locking the carrier out would only make it less likely to arrive.

    Idempotent: setting the state an account already has writes nothing. The last
    active administrator cannot be suspended, because nobody would be left to
    reactivate them; everybody else can, including a caller who is not the only
    active administrator.
    """
    result = await db.execute(
        select(UserRecord).where(UserRecord.user_id == user_id)
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=USER_NOT_FOUND
        )

    if target.is_active == body.is_active:
        await db.flush()
        return AccountStatusResponse.from_record(target)

    if (
        not body.is_active
        and target.role == UserRole.ADMIN.value
        and await _active_administrator_count(db) <= 1
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot suspend the last administrator",
        )

    released = 0
    if not body.is_active:
        # Before the account is locked: whatever the driver has accepted and
        # not collected goes back to the pool, in the same transaction, or the
        # suspension is refused.
        released = await _release_driver_work(db, target, current_user)

    previous = "active" if target.is_active else "suspended"
    current = "active" if body.is_active else "suspended"
    target.is_active = body.is_active
    record_event(
        db,
        action=USER_REACTIVATED if body.is_active else USER_SUSPENDED,
        subject_type="user",
        subject_id=target.user_id,
        from_value=previous,
        to_value=current,
        actor=current_user,
        detail=(
            "reactivated by an administrator"
            if body.is_active
            else "suspended by an administrator"
        ),
    )
    await db.flush()
    return AccountStatusResponse.from_record(target, released_deliveries=released)


@router.get("/stats", response_model=AdminStatsResponse)
async def platform_stats(
    current_user=Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    The platform's totals, for the administrator dashboard.

    Same numbers as the community impact page, from the same function - a
    dashboard that counted separately would eventually disagree with a page
    that is supposed to be evidence. `total_revenue` is money actually
    collected: orders joined to a paid payment row, summed at their total. It is
    deliberately not `delivered_value`, which counts orders that were handed
    over whether or not anybody paid for them.
    """
    collected = await db.execute(
        select(func.coalesce(func.sum(OrderRecord.total_amount), 0))
        .select_from(OrderRecord)
        .join(OrderPaymentRecord, OrderPaymentRecord.order_id == OrderRecord.order_id)
        .where(OrderPaymentRecord.payment_status == PAYMENT_PAID)
    )
    return AdminStatsResponse(
        **(await collect_stats(db)).model_dump(),
        total_revenue=round(float(collected.scalar_one() or 0), 2),
    )


@router.get("/users", response_model=List[UserResponse])
async def list_users(
    role: Optional[UserRole] = Query(
        None, description="Only accounts holding this role."
    ),
    limit: int = Query(200, ge=1, le=500),
    current_user=Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    Accounts on the platform, newest first.

    The password hash never leaves the row; `UserResponse` is the same safe
    shape `/auth/me` returns, so the console cannot accidentally render a
    credential field that the API was not supposed to publish.
    """
    query = select(UserRecord)
    if role is not None:
        query = query.where(UserRecord.role == role.value)

    result = await db.execute(
        query.order_by(UserRecord.created_at.desc()).limit(limit)
    )
    return [
        UserResponse.from_record(user) for user in result.scalars().all()
    ]


@router.get("/organizations", response_model=List[AdminOrganizationResponse])
async def list_organizations(
    current_user=Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    Every organization, pending applications first.

    The public list shows verified records only (plus your own pending one), so
    an admin cannot verify anything from it. Unverified first is the queue: the
    work that needs a decision is at the top.
    """
    result = await db.execute(
        select(OrganizationRecord, UserRecord)
        .join(
            UserRecord,
            UserRecord.user_id == OrganizationRecord.user_id,
            isouter=True,
        )
        .order_by(
            OrganizationRecord.is_verified.asc(),
            OrganizationRecord.name.asc(),
        )
    )
    return [
        AdminOrganizationResponse.from_records(organization, owner)
        for organization, owner in result.all()
    ]


@router.get("/audit", response_model=List[AuditEventResponse])
async def list_audit_events(
    action: Optional[str] = Query(
        None, description="Only events with this action, e.g. user.role_changed."
    ),
    subject_id: Optional[str] = Query(
        None, description="Only events about this account or organization."
    ),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    The trail, newest first.

    An administrator can ask what happened to one account or organization
    (`subject_id`) or of one kind (`action`), which is how an investigation
    starts: the id comes from the row, the trail says who changed it and when.
    """
    query = select(AuditEventRecord)
    if action:
        query = query.where(AuditEventRecord.action == action)
    if subject_id:
        query = query.where(AuditEventRecord.subject_id == subject_id)

    result = await db.execute(
        query.order_by(
            AuditEventRecord.created_at.desc(),
            AuditEventRecord.event_id.desc(),
        ).limit(limit)
    )
    return [
        AuditEventResponse.from_record(record)
        for record in result.scalars().all()
    ]
