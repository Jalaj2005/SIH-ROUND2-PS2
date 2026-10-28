from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Meta(BaseModel):
    request_id: str


class PageMeta(Meta):
    page: int
    page_size: int
    total: int


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: Meta


class ListEnvelope(BaseModel, Generic[T]):
    data: list[T]
    meta: PageMeta


class ErrorDetail(BaseModel):
    field: str | None = None
    issue: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = []
    request_id: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


def single(data: Any, request_id: str) -> dict:
    return {"data": data, "meta": {"request_id": request_id}}


def paged(items: list, *, request_id: str, page: int, page_size: int, total: int) -> dict:
    return {
        "data": items,
        "meta": {"request_id": request_id, "page": page, "page_size": page_size, "total": total},
    }
