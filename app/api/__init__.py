from fastapi import APIRouter

from app.api import campaigns, offers, references, streams

router = APIRouter(prefix="/api")
router.include_router(campaigns.router)
router.include_router(streams.router)
router.include_router(offers.router)
router.include_router(references.router)
