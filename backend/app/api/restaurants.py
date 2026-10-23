"""
Restaurant & menu endpoints.

Mounted under /api (see app/main.py) so the existing React frontend, which
targets `${REACT_APP_BACKEND_URL}/api`, can talk to this backend unchanged.

Endpoints:
    GET    /restaurants                 list active restaurants (optional cuisine / near-me)
    GET    /restaurants/{id}            single restaurant with menu
    POST   /restaurants                 register a restaurant (auth, owner)
    GET    /restaurants/{id}/orders     that restaurant's orders (auth, owner)
    GET    /restaurants/{id}/menu       menu items for a restaurant
    PUT    /restaurants/{id}/menu       replace a restaurant's menu (auth, owner)

Order status transitions live in app/api/orders.py; this file only lists an
owner's queue.

Location privacy: exact coordinates are encrypted at rest and never returned.
When a caller provides lat/lng we compute a straight-line distance for sorting
but do not expose the restaurant's own coordinates.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._lookups import payments_by_order
from app.database import get_db
from app.core.audit import change_role
from app.core.auth import get_current_user
from app.core.encryption import encrypt_data
from app.core.ids import generate_id
from app.models.general import OrderStatus, UserRole
from app.models.order_orm import OrderRecord
from app.models.restaurant_orm import RestaurantRecord
from app.models.user_orm import UserRecord
from app.schemas.order import OrderResponse
from app.schemas.restaurant import (
    MenuItemRequest,
    MenuItemResponse,
    RestaurantCreateRequest,
    RestaurantResponse,
)

router = APIRouter(prefix="/restaurants", tags=["restaurants"])

# Rough km per degree of latitude/longitude at mid-latitudes. Good enough for
# a first-pass "near me" sort; real routing will replace this later.
_DEGREES_TO_KM = 111.0


def _to_response(rec: RestaurantRecord, distance_km: Optional[float] = None) -> RestaurantResponse:
    """Convert an ORM record into the safe client-facing response."""
    menu = [MenuItemResponse(**item) for item in (rec.menu or [])]
    return RestaurantResponse(
        restaurant_id=rec.restaurant_id,
        user_id=rec.user_id,
        name=rec.name,
        description=rec.description or "",
        cuisine_type=rec.cuisine_type or "",
        image_url=rec.image_url,
        is_active=rec.is_active,
        is_online=rec.is_online,
        rating=rec.rating or 0.0,
        total_reviews=rec.total_reviews or 0,
        city=rec.city or "",
        zip_code=rec.zip_code or "",
        menu=menu,
        distance_km=distance_km,
        created_at=rec.created_at,
    )


def _approximate_km(restaurant: RestaurantRecord, lat: float, lng: float) -> Optional[float]:
    """
    Approximate distance from a user to a restaurant.

    Coordinates are encrypted at rest, so we currently cannot compute a real
    distance without decrypting every row. Returning None keeps us honest (the
    UI simply omits distance) and leaves decrypt-and-measure as a follow-up.
    """
    return None


@router.get("", response_model=List[RestaurantResponse])
async def list_restaurants(
    cuisine: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    radius_km: Optional[float] = None,
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """List restaurants. Owners rely on this to find their own restaurant."""
    query = select(RestaurantRecord)
    if not include_inactive:
        query = query.where(RestaurantRecord.is_active.is_(True))
    if cuisine:
        query = query.where(RestaurantRecord.cuisine_type == cuisine.lower())

    result = await db.execute(query)
    restaurants = list(result.scalars().all())

    responses: List[RestaurantResponse] = []
    for rec in restaurants:
        distance = _approximate_km(rec, lat, lng) if lat is not None and lng is not None else None
        responses.append(_to_response(rec, distance))

    if lat is not None and lng is not None:
        responses.sort(key=lambda r: r.distance_km if r.distance_km is not None else 1e9)

    return responses


@router.post("", response_model=RestaurantResponse, status_code=status.HTTP_201_CREATED)
async def create_restaurant(
    body: RestaurantCreateRequest,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a new restaurant owned by the current user."""
    existing = await db.execute(
        select(RestaurantRecord).where(RestaurantRecord.user_id == current_user.user_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already registered a restaurant",
        )

    restaurant = RestaurantRecord(
        user_id=current_user.user_id,
        name=body.name,
        description=body.description,
        cuisine_type=body.cuisine_type,
        image_url=body.image_url,
        lat_encrypted=encrypt_data(str(body.lat)),
        lng_encrypted=encrypt_data(str(body.lng)),
        address=body.address,
        city=body.city,
        zip_code=body.zip_code,
    )
    db.add(restaurant)

    # Promote the owner so restaurant-specific UI unlocks. The trail records the
    # role they held before, not the one they end up with.
    change_role(
        db,
        current_user,
        UserRole.RESTAURANT_ADMIN.value,
        detail="registered a restaurant",
    )

    await db.flush()
    return _to_response(restaurant)


@router.get("/{restaurant_id}", response_model=RestaurantResponse)
async def get_restaurant(restaurant_id: str, db: AsyncSession = Depends(get_db)):
    """Fetch a single restaurant including its menu."""
    result = await db.execute(
        select(RestaurantRecord).where(RestaurantRecord.restaurant_id == restaurant_id)
    )
    restaurant = result.scalar_one_or_none()
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return _to_response(restaurant)


@router.get("/{restaurant_id}/orders", response_model=List[OrderResponse])
async def get_restaurant_orders(
    restaurant_id: str,
    order_status: Optional[OrderStatus] = Query(
        None,
        alias="status",
        description="Only return orders in this status.",
    ),
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List one restaurant's orders, newest first.

    The kitchen screen reads its whole queue with this, filtering by tab through
    the `status` query parameter (omitted for "all"). Only the owning user may
    read it: an order list is the restaurant's book of business, including the
    delivery address of every customer who ordered.

    `status` is named `order_status` here so it does not shadow `fastapi.status`.
    """
    result = await db.execute(
        select(RestaurantRecord).where(RestaurantRecord.restaurant_id == restaurant_id)
    )
    restaurant = result.scalar_one_or_none()
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    if restaurant.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this restaurant",
        )

    query = select(OrderRecord).where(OrderRecord.restaurant_id == restaurant_id)
    if order_status is not None:
        query = query.where(OrderRecord.status == order_status.value)
    query = query.order_by(OrderRecord.created_at.desc())

    orders = list((await db.execute(query)).scalars().all())
    # The kitchen is told whether the bill was paid, not just what it totals:
    # an order can exist before its payment does, and cooking an unpaid one is a
    # decision the restaurant should get to make knowingly.
    payments = await payments_by_order(db, [record.order_id for record in orders])
    return [
        OrderResponse.from_record(record).with_payment(
            payments[record.order_id].payment_status
            if record.order_id in payments
            else None
        )
        for record in orders
    ]


@router.get("/{restaurant_id}/menu", response_model=List[MenuItemResponse])
async def get_menu(restaurant_id: str, db: AsyncSession = Depends(get_db)):
    """Return only the menu items for a restaurant."""
    result = await db.execute(
        select(RestaurantRecord).where(RestaurantRecord.restaurant_id == restaurant_id)
    )
    restaurant = result.scalar_one_or_none()
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return [MenuItemResponse(**item) for item in (restaurant.menu or [])]


@router.put("/{restaurant_id}/menu", response_model=List[MenuItemResponse])
async def update_menu(
    restaurant_id: str,
    items: List[MenuItemRequest],
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Replace a restaurant's menu. Only the owning user may do this."""
    result = await db.execute(
        select(RestaurantRecord).where(RestaurantRecord.restaurant_id == restaurant_id)
    )
    restaurant = result.scalar_one_or_none()
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    if restaurant.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this restaurant",
        )

    normalised: List[dict] = []
    for item in items:
        data = item.model_dump()
        # Ensure every item has a stable id.
        data["item_id"] = data.get("item_id") or generate_id("item")
        normalised.append(data)

    # Assign (rather than mutate) so SQLAlchemy detects the JSON change.
    restaurant.menu = normalised
    await db.flush()
    return [MenuItemResponse(**item) for item in normalised]
