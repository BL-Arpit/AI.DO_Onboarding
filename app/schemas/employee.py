import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EmployeeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    phone: str = Field(min_length=8, max_length=30)
    client: str = Field(default="", max_length=120)
    track: Literal["client", "onboard", "validate"] = "onboard"

    @field_validator("name")
    @classmethod
    def name_clean(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("Name is required.")
        return value

    @field_validator("email")
    @classmethod
    def email_clean(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", value):
            raise ValueError("Enter a valid email address.")
        return value

    @field_validator("phone")
    @classmethod
    def phone_clean(cls, value):
        value = re.sub(r"[\s()\-]", "", value)
        if not re.fullmatch(r"\+?\d{8,15}", value):
            raise ValueError("Phone must contain 8 to 15 digits.")
        return value


class UpdateEmployee(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    fields: dict[str, str] = Field(min_length=1, max_length=5)


class VersionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


class FieldsInput(VersionInput):
    fields: dict[str, dict] = Field(max_length=8)


# Excel parser compatibility, using the same authoritative validation as chat/API.
def clean_person(data):
    try:
        return (
            EmployeeInput.model_validate(
                {
                    k: data.get(k, "") or ("onboard" if k == "track" else "")
                    for k in ("name", "email", "phone", "client", "track")
                }
            ).model_dump(),
            [],
        )
    except Exception as exc:
        errors = exc.errors() if hasattr(exc, "errors") else []
        return {
            k: str(data.get(k, "") or "").strip()
            for k in ("name", "email", "phone", "client", "track")
        }, [str(e["msg"]) for e in errors] or ["Invalid employee data."]
