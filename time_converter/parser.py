from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from math import floor
from typing import Callable

from .utils import month_delta, year_delta

__all__ = ("AboveMaxDuration", "BelowMinDuration", "NoDuration", "TimeRepresentation", "TimePeriod")
TIME_REGEX = re.compile(r"(?P<AMOUNT>\d+(?:\.\d+)?)\s?(?P<PERIOD>[a-z]+)?", re.IGNORECASE)


class BelowMinDuration(ValueError):
    """Raised if an input resolves to be below a converter's minimum required duration"""


class AboveMaxDuration(ValueError):
    """Raised if an input resolves to be above the converter's max allowed duration"""


class NoDuration(ValueError):
    """Raised if an input fails to resolve to any meaningful timedelta"""


def _wrap(wrap: Callable[[datetime, int], float]) -> Callable[[datetime, int | float], float]:
    """Internal handler for float time periods with use in int-based handlers"""

    @wraps(wrap)
    def wrapper(now: datetime, quantity: int | float):
        rounded, decimal = floor(quantity), quantity % 1
        delta = wrap(now, rounded)
        if decimal:
            # This can lose a bit of precision depending on when the last month of the
            # above call lands on, but that's an acceptable trade off in my opinion,
            # as floats are already fairly fuzzy for months and years.
            delta += wrap(now + timedelta(seconds=delta), 1) * decimal
        return delta

    return wrapper


class TimePeriod(Enum):
    SECONDS = 1.0
    MINUTES = 60.0
    HOURS = MINUTES * 60.0  # noqa
    DAYS = HOURS * 24.0  # noqa
    WEEKS = DAYS * 7.0  # noqa
    # Callables for handling more complex forms of timedeltas; Enum doesn't like these being
    # bare function values, and as such these must be wrapped in a tuple and unwrapped later on
    # in __init__ before usage
    MONTHS = (_wrap(month_delta),)
    YEARS = (_wrap(year_delta),)

    def __init__(self, val: float | tuple[Callable]):
        self.suffix = self.name.lower()
        self.multiplier = val[0] if isinstance(val, tuple) else val

    def __call__(self, now: datetime, quantity: int | float) -> float:
        if callable(self.multiplier):
            return self.multiplier(now, quantity)
        else:
            return self.multiplier * quantity

    @classmethod
    def find(cls, period: str) -> TimePeriod | None:
        try:
            return next(x for x in cls if x.suffix.startswith(period.lower()))
        except StopIteration:
            return None


@dataclass(frozen=True, slots=True)
class TimeRepresentation:
    amount: int | float
    period: TimePeriod

    def to_seconds(self, now: datetime = ...) -> float:
        now = now or datetime.utcnow()
        return self.period(now, self.amount)

    @classmethod
    def str_to_reps(
        cls,
        duration: str,
        *,
        default: TimePeriod = None,
    ) -> list[TimeRepresentation]:
        reps = []
        for match in TIME_REGEX.finditer(duration):
            try:
                amount = float(match.group("AMOUNT"))
            except ValueError:
                continue
            period = match.group("PERIOD")
            try:
                period = next(x for x in TimePeriod if x.suffix.startswith(period.lower()))
            except (StopIteration, AttributeError):
                if default is None:
                    continue
                period = default
            reps.append(cls(amount=amount, period=period))
        return reps

    @classmethod
    def str_to_delta(
        cls,
        duration: str,
        *,
        max_duration: timedelta | list[TimeRepresentation] = None,
        default: TimePeriod = None,
    ) -> timedelta:
        """Convert a :class:`str` to a :class:`datetime.timedelta`"""
        if isinstance(max_duration, list):
            max_duration = cls.reps_to_delta(max_duration)
        reps = cls.str_to_reps(duration, default=default)
        return cls.reps_to_delta(reps, max_duration=max_duration)

    @classmethod
    def reps_to_delta(
        cls, reps: list[TimeRepresentation], now: datetime = None, max_duration: timedelta = None
    ) -> timedelta:
        """Convert a list of :class:`TimeRepresentation` objects to a :class:`datetime.timedelta`"""
        if now is None:
            now = datetime.utcnow()

        delta = timedelta()
        for rep in reps:
            delta += timedelta(seconds=rep.to_seconds(now + delta))
            if max_duration and delta > max_duration:
                raise AboveMaxDuration()

        return delta
