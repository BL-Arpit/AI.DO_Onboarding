from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str = Field(default="default", pattern=r"^[a-zA-Z0-9_-]{1,64}$")


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "reply",
        "create",
        "read",
        "list",
        "update",
        "delete",
        "upload",
        "audit",
        "export",
        "cancel",
        "status",
        "next",
        "missing",
        "documents",
        "history",
    ] = "reply"
    reply: str = Field(default="", max_length=2000)
    target: str = Field(default="", max_length=254)
    fields: dict[str, str] = Field(default_factory=dict, max_length=5)
    document_fields: dict[str, dict] = Field(default_factory=dict, max_length=8)

    @field_validator("fields")
    @classmethod
    def allowed_fields(cls, value):
        if set(value) - {"name", "email", "phone", "client", "track"}:
            raise ValueError("Unknown employee field.")
        if any(len(v) > 254 for v in value.values()):
            raise ValueError("Field too long.")
        return value


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "reply",
                "create",
                "read",
                "list",
                "update",
                "delete",
                "upload",
                "audit",
                "export",
                "cancel",
                "status",
                "next",
                "missing",
                "documents",
                "history",
            ],
        },
        "reply": {"type": "string"},
        "target": {
            "type": "string",
            "description": "Employee email, ID, or exact name; empty for selected employee.",
        },
        "fields": {
            "type": "object",
            "properties": {
                k: {"type": "string"} for k in ["name", "email", "phone", "client", "track"]
            },
            "additionalProperties": False,
        },
        "document_fields": {
            "type": "object",
            "description": "Optional patch for existing uploaded document fields only.",
        },
    },
    "required": ["action"],
    "additionalProperties": False,
}
