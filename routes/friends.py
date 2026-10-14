from datetime import datetime, timezone
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from core.dependencies import get_current_user_id
from db.connection import get_db
from db.models import (
    Friendship,
    User,
    UserAchievement,
    UserGestureStat,
    UserStreak,
)
from schemas import (
    FriendRequestsResponse,
    FriendshipOut,
    FriendUser,
    PublicProfileResponse,
    UserSearchResult,
)

router = APIRouter(tags=["Friends"])

SEARCH_LIMIT = 20
MAX_PENDING_OUTGOING = 50


# ---------------- HELPERS ----------------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _pair_filter(a: int, b: int):
    return or_(
        and_(Friendship.requester_id == a, Friendship.addressee_id == b),
        and_(Friendship.requester_id == b, Friendship.addressee_id == a),
    )


def _find_friendship(db: Session, a: int, b: int) -> Any:
    return db.query(Friendship).filter(_pair_filter(a, b)).first()


def _status_for(me: int, f) -> str:
    if f is None:
        return "none"
    if f.status == "accepted":
        return "friends"
    return "pending_outgoing" if f.requester_id == me else "pending_incoming"


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _streaks_map(db: Session, user_ids: List[int]) -> dict:
    """{user_id: поточний streak} одним запитом."""
    if not user_ids:
        return {}
    rows = (
        db.query(UserStreak.user_id, UserStreak.streak_length)
        .filter(UserStreak.user_id.in_(user_ids), UserStreak.is_current == True)
        .all()
    )
    return {uid: (length or 0) for uid, length in rows}


def _friend_user(user: User, streaks: dict) -> FriendUser:
    return FriendUser(
        id=user.id,  # type: ignore
        username=user.username,  # type: ignore
        avatar_url=user.avatar_url,  # type: ignore
        total_xp=user.total_xp or 0,  # type: ignore
        current_streak=streaks.get(user.id, 0),
    )


def _build_list(db: Session, me: int, friendships: List[Any]) -> List[FriendshipOut]:
    others = [f.addressee if f.requester_id == me else f.requester for f in friendships]
    streaks = _streaks_map(db, [u.id for u in others])  # type: ignore
    return [
        FriendshipOut(
            friendship_id=f.id,  # type: ignore
            user=_friend_user(u, streaks),
            created_at=f.created_at,  # type: ignore
        )
        for f, u in zip(friendships, others)
    ]


def _friendship_query(db: Session):
    return db.query(Friendship).options(
        joinedload(Friendship.requester),
        joinedload(Friendship.addressee),
    )


# ---------------- LIST FRIENDS ----------------

@router.get("", response_model=List[FriendshipOut])
def list_friends(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    rows = (
        _friendship_query(db)
        .filter(
            Friendship.status == "accepted",
            or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id),
        )
        .order_by(Friendship.created_at.desc())
        .all()
    )
    return _build_list(db, user_id, rows)


# ---------------- REQUESTS (incoming / outgoing) ----------------

@router.get("/requests", response_model=FriendRequestsResponse)
def list_requests(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    incoming = (
        _friendship_query(db)
        .filter(Friendship.status == "pending", Friendship.addressee_id == user_id)
        .order_by(Friendship.created_at.desc())
        .all()
    )
    outgoing = (
        _friendship_query(db)
        .filter(Friendship.status == "pending", Friendship.requester_id == user_id)
        .order_by(Friendship.created_at.desc())
        .all()
    )
    return FriendRequestsResponse(
        incoming=_build_list(db, user_id, incoming),
        outgoing=_build_list(db, user_id, outgoing),
    )


# ---------------- SEARCH BY USERNAME ----------------

@router.get("/search", response_model=List[UserSearchResult])
def search_users(
    q: str = Query(..., min_length=2, max_length=30),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    term = q.strip()
    if len(term) < 2:
        raise HTTPException(status_code=400, detail="Query is too short")

    # username не унікальний, тому повертаємо всіх збігів (до SEARCH_LIMIT)
    users = (
        db.query(User)
        .filter(
            User.id != user_id,
            User.is_active == True,
            User.username.ilike(f"%{_escape_like(term)}%", escape="\\"),
        )
        .order_by(func.lower(User.username), User.id)
        .limit(SEARCH_LIMIT)
        .all()
    )
    if not users:
        return []

    ids = [u.id for u in users]
    friendships: List[Any] = (
        db.query(Friendship)
        .filter(
            or_(
                and_(Friendship.requester_id == user_id, Friendship.addressee_id.in_(ids)),
                and_(Friendship.addressee_id == user_id, Friendship.requester_id.in_(ids)),
            )
        )
        .all()
    )
    by_other = {
        (f.addressee_id if f.requester_id == user_id else f.requester_id): f
        for f in friendships
    }

    result = []
    for u in users:
        f = by_other.get(u.id)
        result.append(
            UserSearchResult(
                id=u.id,  # type: ignore
                username=u.username,  # type: ignore
                avatar_url=u.avatar_url,  # type: ignore
                total_xp=u.total_xp or 0,  # type: ignore
                friendship_status=_status_for(user_id, f),
                friendship_id=f.id if f else None,  # type: ignore
            )
        )
    return result


# ---------------- PUBLIC PROFILE ----------------

@router.get("/profile/{target_id}", response_model=PublicProfileResponse)
def get_public_profile(
    target_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    user: Any = db.get(User, target_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="User not found")

    mastered = (
        db.query(func.count(UserGestureStat.id))
        .filter(
            UserGestureStat.user_id == target_id,
            UserGestureStat.mastery_level >= 3,
        )
        .scalar()
        or 0
    )
    achievements_count = (
        db.query(func.count(UserAchievement.id))
        .filter(UserAchievement.user_id == target_id)
        .scalar()
        or 0
    )
    streak_row = (
        db.query(UserStreak.streak_length)
        .filter(UserStreak.user_id == target_id, UserStreak.is_current == True)
        .first()
    )
    current_streak = (streak_row[0] or 0) if streak_row else 0

    if target_id == user_id:
        status, friendship_id = "self", None
    else:
        f = _find_friendship(db, user_id, target_id)
        status, friendship_id = _status_for(user_id, f), (f.id if f else None)  # type: ignore

    # email, role, google_id та інші приватні поля навмисно не повертаються
    return PublicProfileResponse(
        id=user.id,  # type: ignore
        username=user.username,  # type: ignore
        avatar_url=user.avatar_url,  # type: ignore
        total_xp=user.total_xp or 0,  # type: ignore
        current_streak=current_streak,
        gestures_mastered=int(mastered),
        achievements_count=int(achievements_count),
        member_since=user.created_at,  # type: ignore
        friendship_status=status,
        friendship_id=friendship_id,
    )


# ---------------- SEND REQUEST ----------------

@router.post("/request/{target_id}")
def send_request(
    target_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    if target_id == user_id:
        raise HTTPException(status_code=400, detail="You cannot add yourself")

    target: Any = db.get(User, target_id)
    if not target or not target.is_active:
        raise HTTPException(status_code=404, detail="User not found")

    existing = _find_friendship(db, user_id, target_id)
    if existing:
        if existing.status == "accepted":
            raise HTTPException(status_code=400, detail="Already friends")
        if existing.requester_id == user_id:
            raise HTTPException(status_code=400, detail="Request already sent")
        # зустрічний запит: людина вже запросила нас, тож просто приймаємо
        existing.status = "accepted"  # type: ignore
        existing.responded_at = _now()  # type: ignore
        db.commit()
        return {"friendship_id": existing.id, "status": "accepted"}

    pending_count = (
        db.query(func.count(Friendship.id))
        .filter(Friendship.requester_id == user_id, Friendship.status == "pending")
        .scalar()
        or 0
    )
    if pending_count >= MAX_PENDING_OUTGOING:
        raise HTTPException(status_code=400, detail="Too many pending requests")

    friendship = Friendship(
        requester_id=user_id,
        addressee_id=target_id,
        status="pending",
    )
    db.add(friendship)
    try:
        db.commit()
    except IntegrityError:
        # гонка запитів: унікальний індекс friendships_pair_idx у БД
        db.rollback()
        raise HTTPException(status_code=400, detail="Request already exists")

    return {"friendship_id": friendship.id, "status": "pending"}


# ---------------- ACCEPT ----------------

@router.post("/{friendship_id}/accept")
def accept_request(
    friendship_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    f: Any = db.get(Friendship, friendship_id)
    if not f or user_id not in (f.requester_id, f.addressee_id):
        raise HTTPException(status_code=404, detail="Request not found")
    if f.addressee_id != user_id:
        raise HTTPException(status_code=403, detail="Only the recipient can accept a request")
    if f.status == "accepted":
        raise HTTPException(status_code=400, detail="Already friends")

    f.status = "accepted"  # type: ignore
    f.responded_at = _now()  # type: ignore
    db.commit()
    return {"friendship_id": f.id, "status": "accepted"}


# ---------------- DECLINE / CANCEL / REMOVE FRIEND ----------------

@router.delete("/{friendship_id}")
def delete_friendship(
    friendship_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    f: Any = db.get(Friendship, friendship_id)
    if not f or user_id not in (f.requester_id, f.addressee_id):
        raise HTTPException(status_code=404, detail="Friendship not found")

    db.delete(f)
    db.commit()
    return {"success": True}