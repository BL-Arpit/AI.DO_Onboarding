from pydantic import BaseModel


class ValidationItem(BaseModel):
    field: str
    message: str


class ErrorResponse(BaseModel):
    detail: str
    request_id: str = ""
    errors: list[ValidationItem] | None = None
