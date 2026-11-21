from pydantic import BaseModel, Field


class StateIn(BaseModel):
    active: bool


class OfferOut(BaseModel):
    id: int
    name: str


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
