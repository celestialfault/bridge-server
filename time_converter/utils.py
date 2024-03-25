from datetime import datetime

__all__ = ("is_leap_year", "get_max_days", "month_delta", "year_delta")


def is_leap_year(year: int) -> bool:
    """Check if a given year is a leap year"""
    # This function is structured this way for the sake of readability
    # sourcery skip: assign-if-exp, reintroduce-else

    # if the year is evenly divisible by 4
    if year % 4 == 0:
        # except if it's divisible by 100
        if year % 100 == 0:
            # unless it's also divisible by 400
            return year % 400 == 0
        return True
    return False


def get_max_days(year: int) -> list[int]:
    """Get the max days for each month of the year, accounting for leap years in the process"""
    return [31, 29 if is_leap_year(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def month_delta(now: datetime = None, months: int = 1) -> float:
    """Get the amount of seconds between ``now`` and the given amount of ``months``"""
    if now is None:
        now = datetime.utcnow()

    skip_years = months // 12
    year = now.year + skip_years
    months -= skip_years * 12
    day = now.day
    month = now.month

    if now.month + months > 12:
        # handle inputs such as '2 months' which would result in dec -> feb
        # >=12 month inputs are already handled above, as such this is the only such case
        # where this would apply
        month = (now.month + months) - 12
        year += 1
    else:
        month += months

    # This catches any situations where we go from dates like May 31 -> June 30, or similarly
    # with leap days, such as Jan 31 -> Feb 29 or Feb 29 -> 28
    day = min(day, get_max_days(year)[month - 1])
    return (now.replace(day=day, month=month, year=year) - now).total_seconds()


def year_delta(now: datetime = None, years: int = 1) -> float:
    """Alias to ``month_delta(now, years * 12)``"""
    if now is None:
        now = datetime.utcnow()
    return month_delta(now, months=years * 12)
