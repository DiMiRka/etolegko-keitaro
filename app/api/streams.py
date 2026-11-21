from fastapi import APIRouter

from app.api.deps import CatalogDep, KeitaroDep, SessionDep
from app.core.errors import AppError
from app.schemas import OfferAdd, PinIn, StateIn, StreamOut
from app.services import streams as stream_svc

router = APIRouter(prefix="/streams", tags=["streams"])


@router.post("/{stream_id}/offers", response_model=StreamOut)
async def add_offer(stream_id: int, body: OfferAdd, session: SessionDep, catalog: CatalogDep):
    stream = await stream_svc.load_stream(session, stream_id)
    offer = await catalog.get(body.offer_id)
    if offer is None:
        raise AppError(f"Оффер {body.offer_id} не найден в Keitaro")
    await stream_svc.add_offer(session, stream, body.offer_id, offer["name"])
    return StreamOut.of(stream)


@router.post("/{stream_id}/offers/{offer_id}/remove", response_model=StreamOut)
async def remove_offer(stream_id: int, offer_id: int, session: SessionDep):
    stream = await stream_svc.load_stream(session, stream_id)
    await stream_svc.remove_offer(session, stream, stream_svc.find_offer(stream, offer_id))
    return StreamOut.of(stream)


@router.post("/{stream_id}/offers/{offer_id}/bring-back", response_model=StreamOut)
async def bring_back(stream_id: int, offer_id: int, session: SessionDep):
    stream = await stream_svc.load_stream(session, stream_id)
    await stream_svc.bring_back(session, stream, stream_svc.find_offer(stream, offer_id))
    return StreamOut.of(stream)


@router.post("/{stream_id}/offers/{offer_id}/pin", response_model=StreamOut)
async def pin_offer(stream_id: int, offer_id: int, body: PinIn, session: SessionDep):
    stream = await stream_svc.load_stream(session, stream_id)
    await stream_svc.set_pin(session, stream, stream_svc.find_offer(stream, offer_id), body.pinned, body.share)
    return StreamOut.of(stream)


@router.post("/{stream_id}/cancel", response_model=StreamOut)
async def cancel(stream_id: int, session: SessionDep):
    stream = await stream_svc.load_stream(session, stream_id)
    await stream_svc.cancel(session, stream)
    return StreamOut.of(stream)


@router.post("/{stream_id}/state", response_model=StreamOut)
async def set_stream_state(stream_id: int, body: StateIn, session: SessionDep, kt: KeitaroDep):
    stream = await stream_svc.load_stream(session, stream_id)
    await stream_svc.set_stream_state(session, kt, stream, body.active)
    return StreamOut.of(stream)


@router.post("/{stream_id}/push", response_model=StreamOut)
async def push(stream_id: int, session: SessionDep, kt: KeitaroDep, force: bool = False):
    stream = await stream_svc.load_stream(session, stream_id)
    await stream_svc.push(session, kt, stream, force=force)
    return StreamOut.of(stream)
