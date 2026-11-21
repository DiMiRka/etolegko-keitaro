from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.models import ChangeLog, Stream


def shares(stream: Stream) -> dict[str, int]:
    return {str(o.offer_id): o.share for o in stream.offers if o.is_active}


def offer_label(stream: Stream, offer_id: int) -> str:
    name = next((o.offer_name for o in stream.offers if o.offer_id == offer_id), "")
    if not name:
        return str(offer_id)
    return name if name.startswith(str(offer_id)) else f"{offer_id} {name}"


def record(
    session: AsyncSession,
    campaign_id: int,
    action: str,
    message: str,
    stream: Stream | None = None,
    details: dict | None = None,
) -> None:
    user = current_user.get()
    session.add(ChangeLog(
        campaign_id=campaign_id,
        created_at=datetime.now(UTC).replace(tzinfo=None),
        username=user.username if user else None,
        stream_id=stream.id if stream is not None else None,
        action=action,
        message=message,
        details=details,
    ))


def record_stream(
    session: AsyncSession, stream: Stream, action: str, message: str, before: dict | None = None, **extra
) -> None:
    details = {"stream": stream.name, **extra}
    if before is not None:
        details["before"] = before
        details["after"] = shares(stream)
    record(session, stream.campaign_id, action, f"Поток «{stream.name}»: {message}", stream, details)


async def history(session: AsyncSession, campaign_id: int, limit: int = 100) -> list[dict]:
    rows = await session.scalars(
        select(ChangeLog)
        .where(ChangeLog.campaign_id == campaign_id)
        .order_by(ChangeLog.id.desc())
        .limit(limit)
    )
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat(sep=" ", timespec="seconds") + "Z",
            "action": r.action,
            "message": r.message,
            "username": r.username,
            "stream_id": r.stream_id,
            "details": r.details,
        }
        for r in rows
    ]
