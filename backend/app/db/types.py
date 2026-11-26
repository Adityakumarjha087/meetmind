"""Portable vector column: pgvector on PostgreSQL, JSON array elsewhere (SQLite tests)."""

from __future__ import annotations

from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine


class EmbeddingVector(TypeDecorator[list[float]]):
    impl = JSON
    cache_ok = True
    comparator_factory = Vector.comparator_factory  # enables .cosine_distance() on PostgreSQL

    def __init__(self, dim: int) -> None:
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: list[float] | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        if len(value) != self.dim:
            raise ValueError(f"expected embedding of dim {self.dim}, got {len(value)}")
        return [float(v) for v in value]

    def process_result_value(self, value: Any, dialect: Dialect) -> list[float] | None:
        if value is None:
            return None
        return [float(v) for v in value]
