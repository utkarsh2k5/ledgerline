"""Tiny cache for dashboard analytics, invalidated by data state, not by time.

The key includes the latest dataset version ids and the reconciliation state,
so any new upload or break resolution produces a new key automatically.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..data_access import latest_version_ids
from ..models import ReconBreak, Scheme
from .engine import Analysis, build_analysis

_LOCK = threading.Lock()
_CACHE: OrderedDict[tuple, Analysis] = OrderedDict()
_MAX = 8


def _state_key(db: Session, scheme_id: int) -> tuple:
    versions = tuple(sorted((k, v or 0) for k, v in latest_version_ids(db, scheme_id).items()))
    recon = db.execute(
        select(func.count(ReconBreak.id), func.max(ReconBreak.id), func.max(ReconBreak.resolved_at))
        .where(ReconBreak.scheme_id == scheme_id, ReconBreak.status.in_(["open", "resolved"]))
    ).one()
    return versions + (tuple(str(x) for x in recon),)


def get_analysis(db: Session, scheme: Scheme, period_end: date) -> Analysis:
    key = (scheme.id, period_end, _state_key(db, scheme.id))
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    analysis = build_analysis(db, scheme, period_end)
    with _LOCK:
        _CACHE[key] = analysis
        while len(_CACHE) > _MAX:
            _CACHE.popitem(last=False)
    return analysis


def clear() -> None:
    with _LOCK:
        _CACHE.clear()
