from fastapi import APIRouter

from app.api.deps import ReferencesDep, SettingsDep
from app.schemas import GroupCreate
from app.services.campaigns import Tracking, full_name

router = APIRouter(tags=["references"])


@router.get("/references")
async def get_references(references: ReferencesDep, settings: SettingsDep):
    defaults = Tracking.defaults(settings)
    return {
        **await references.all(),
        "defaults": {
            "domain_id": defaults.domain_id,
            "group_id": defaults.group_id,
            "traffic_source_id": defaults.traffic_source_id,
        },
    }


@router.post("/groups", status_code=201)
async def create_group(body: GroupCreate, references: ReferencesDep, settings: SettingsDep):
    return await references.create_group(full_name(body.name, settings.campaign_prefix))
