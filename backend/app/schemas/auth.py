from pydantic import BaseModel, ConfigDict, Field


class DemoLoginRequest(BaseModel):
    # Plain str on purpose: ".test" demo addresses fail strict email validators.
    email: str = Field(min_length=3, max_length=320, examples=["scrutiny.officer@example.test"])


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: str
    role: str
    institution_id: str | None = None
    region_id: str | None = None
    is_active: bool


class ScopeOut(BaseModel):
    scope_type: str
    institution_id: str | None = None
    region_id: str | None = None


class MeOut(BaseModel):
    user: UserOut
    scope: ScopeOut


class LoginOut(MeOut):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    prototype_auth: bool = True
    notice: str = "Prototype authentication for seeded synthetic users only. Not production identity."
