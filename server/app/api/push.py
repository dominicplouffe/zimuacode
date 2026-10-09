from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel import select

from app.deps import DbDep, UserDep
from app.models import PushSubscription
from app.notify import Notifier

router = APIRouter(prefix="/api/push", tags=["notifications"])


class PushKey(BaseModel):
    public_key: str


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class NewSubscription(BaseModel):
    endpoint: str
    keys: SubscriptionKeys


def _notifier(request: Request) -> Notifier:
    notifier: Notifier = request.app.state.notifier
    return notifier


@router.get("/key")
def push_key(request: Request, _user: UserDep) -> PushKey:
    return PushKey(public_key=_notifier(request).public_key)


@router.post("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def subscribe(body: NewSubscription, user: UserDep, db: DbDep) -> None:
    if not body.endpoint.startswith("https://"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Push endpoints must be https")
    sub = db.exec(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    ).first()
    sub = sub or PushSubscription(user_id=user.id or 0, endpoint=body.endpoint, p256dh="", auth="")
    sub.user_id = user.id or 0
    sub.p256dh = body.keys.p256dh
    sub.auth = body.keys.auth
    db.add(sub)
    db.commit()


@router.delete("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(endpoint: str, user: UserDep, db: DbDep) -> None:
    sub = db.exec(
        select(PushSubscription).where(
            PushSubscription.endpoint == endpoint, PushSubscription.user_id == user.id
        )
    ).first()
    if sub:
        db.delete(sub)
        db.commit()


@router.post("/test", status_code=status.HTTP_202_ACCEPTED)
async def test_notification(request: Request, user: UserDep) -> None:
    notifier = _notifier(request)
    notifier.notify(
        user.id or 0, "Zimua Code", "Notifications are working.", notifier.settings.public_url
    )
