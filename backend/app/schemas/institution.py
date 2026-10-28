from pydantic import BaseModel, ConfigDict


class InstitutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    institution_code: str
    region_id: str
    status: str
