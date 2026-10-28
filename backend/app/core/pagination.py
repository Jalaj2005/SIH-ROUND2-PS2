from dataclasses import dataclass

from fastapi import Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def pagination_params(
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page (max 100)"),
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


def paginate(db: Session, stmt: Select, params: PageParams):
    """Return (items, total) for an ordered SELECT of ORM entities."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = db.scalars(stmt.limit(params.page_size).offset(params.offset)).all()
    return items, total
