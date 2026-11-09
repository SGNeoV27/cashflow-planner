"""Save and load plans as JSON (for client records and the audit trail)."""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from enum import Enum
from typing import Any, get_args, get_origin, get_type_hints

from . import models


def _encode(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return {f.name: _encode(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_encode(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _encode(v) for k, v in obj.items()}
    return obj


def _decode(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = get_origin(tp)
    if origin is list:
        (inner,) = get_args(tp)
        return [_decode(inner, v) for v in value]
    if origin is dict:
        return dict(value)
    args = [a for a in get_args(tp) if a is not type(None)]
    if args and origin is not None:  # Optional[X] / X | None
        return _decode(args[0], value)
    if isinstance(tp, type):
        if dataclasses.is_dataclass(tp):
            hints = get_type_hints(tp, vars(models))
            return tp(**{k: _decode(hints[k], v) for k, v in value.items() if k in hints})
        if issubclass(tp, Enum):
            return tp(value)
        if tp is date:
            return date.fromisoformat(value)
    return value


def plan_to_dict(plan: models.Plan) -> dict:
    return _encode(plan)


def plan_from_dict(data: dict) -> models.Plan:
    return _decode(models.Plan, data)


def dumps(plan: models.Plan) -> str:
    return json.dumps(plan_to_dict(plan), indent=2)


def loads(text: str) -> models.Plan:
    return plan_from_dict(json.loads(text))
