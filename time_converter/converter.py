from __future__ import annotations

from datetime import timedelta

import discord.utils
from discord.ext.commands import BadArgument, Converter

from common import delta_to_str

from .parser import AboveMaxDuration, BelowMinDuration, NoDuration, TimePeriod, TimeRepresentation

__all__ = ("TimeDelta", "BelowMinDuration", "AboveMaxDuration", "NoDuration")


class TimeDelta(Converter):
    # noinspection PyShadowingBuiltins
    def __init__(self, min: str | None = None, max: str | None = None, default: str | None = None):
        self._min_time: list[TimeRepresentation] = []
        self._max_time: list[TimeRepresentation] = []
        self._default_period: TimePeriod | None = None
        if min:
            self.min_time(min)
        if max:
            self.max_time(max)
        if default:
            self.default_period(default)

    def __repr__(self):
        default_period = self._default_period
        max_time = TimeRepresentation.reps_to_delta(self._max_time) if self._max_time else None
        min_time = TimeRepresentation.reps_to_delta(self._min_time) if self._min_time else None
        return f"TimeDelta({default_period=}, {max_time=}, {min_time=})"

    def from_str(self, duration: str, *, bypass_restrictions: bool = False) -> timedelta:
        """Resolve an input duration with the converter's current configuration options

        All exceptions this method raises are subclasses of :class:`ValueError`.

        Raises
        -------
        BelowMinDuration
        AboveMaxDuration
        NoDuration
        """
        duration = TimeRepresentation.str_to_delta(
            duration, max_duration=self._max_time, default=self._default_period
        )
        if self._min_time and not bypass_restrictions:
            mint = TimeRepresentation.reps_to_delta(self._min_time)
            if duration < mint:
                raise BelowMinDuration()
        if duration.total_seconds() == 0.0:
            raise NoDuration()
        return duration

    def sync_convert(self, argument: str) -> timedelta:
        try:
            return self.from_str(argument)
        except NoDuration:
            raise BadArgument(
                f"`{discord.utils.escape_markdown(argument)}` is not a valid unit of time"
            ) from None
        except BelowMinDuration:
            raise BadArgument(
                "The given time is below the minimum duration of"
                f" {delta_to_str(TimeRepresentation.reps_to_delta(self._min_time))}"
            ) from None
        except AboveMaxDuration:
            raise BadArgument(
                "The given time is above the maximum duration of"
                f" {delta_to_str(TimeRepresentation.reps_to_delta(self._max_time))}"
            ) from None

    async def convert(self, ctx, argument: str) -> timedelta:
        """Internal method used for discord.py conversion support

        This is largely a different frontend to :meth:`from_str` that throws user input errors
        when applicable.

        A synchronous version of this method is available as :meth:`sync_convert`.
        """
        return self.sync_convert(argument)

    def default_period(self, default_period: str) -> TimeDelta:
        """Set the default time period of this parser

        By default, if no default period is set, any integers without an attached
        time period will be ignored.

        Example
        -------
        >>> TimeDelta().default_period("seconds")
        """
        self._default_period = TimePeriod.find(default_period)
        return self

    def min_time(self, time: str) -> TimeDelta:
        """Set the minimum duration of time that this parser will accept

        This accepts the same format that :meth:`from_str` will accept.

        Example
        --------
        >>> TimeDelta().min_time("1h30m")
        """
        self._min_time = TimeRepresentation.str_to_reps(time)
        return self

    def max_time(self, time: str) -> TimeDelta:
        """Set the maximum duration of time that this parser will accept

        This accepts the same format that :meth:`from_str` will accept.

        Example
        --------
        >>> TimeDelta().max_time("1h30m")
        """
        self._max_time = TimeRepresentation.str_to_reps(time)
        return self
