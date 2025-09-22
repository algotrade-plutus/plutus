import datetime
import os
from decimal import Decimal
from functools import wraps
from pathlib import Path
from typing import Any, Callable, List, TypeVar, Union, Optional

import pytz


def add_mins(tm, mins):
    full_date = datetime.datetime(100, 1, 1, tm.hour, tm.minute, tm.second)
    full_date = full_date + datetime.timedelta(minutes=mins)
    return full_date.time()


def add_secs(tm, secs):
    full_date = datetime.datetime(100, 1, 1, tm.hour, tm.minute, tm.second)
    full_date = full_date + datetime.timedelta(seconds=secs)
    return full_date.time()


def get_delivery_date(symbol: str, timestamp: float, special_dates: List[str] = []):
    """Get delivery date T + 2.5 if instrument is underlying else today

    FIXME: calculate T + 2.5
    """
    delivery_date = datetime.datetime.fromtimestamp(
        timestamp, tz=pytz.timezone("Asia/Ho_Chi_Minh")
    )

    if "VN30F" in symbol:
        return delivery_date

    delivery_date = delivery_date.replace(hour=0, minute=0, second=0, microsecond=0)

    i = 1
    normal_addition = 2
    while i <= normal_addition:
        delivery_date = delivery_date + datetime.timedelta(days=1)
        if delivery_date.weekday() == 5 or delivery_date.weekday() == 6:
            continue
        if str(delivery_date.date()) in special_dates:
            continue
        i += 1

    return delivery_date + datetime.timedelta(days=0.5)


def get_latest_price_redis_key(instrument_name: str) -> str:
    return f"{instrument_name}-L"


def percentage_bar(percentage: float) -> str:
    """Visualize percentage.

    Returns:
        A string representation of percentage e.g. [|||||     55.50%]
    """
    bar = "|" * int(percentage / 10)
    return f"[{bar:10}{percentage:5}%]"


def profit_bar(profits: List[Decimal]) -> str:
    """Visualize profit bar.

    Returns:
        A string representation of profits. For example,
            [4.2, -1.2, -0.3, -0,4, 0.9, 1.3] ~ :...::
    """
    return "".join(map(lambda p: (".", ":")[p > 0], profits))


def round_decimal(value: Union[float, Decimal], precision: int = 2) -> Decimal:
    value = round(value, precision)
    return Decimal(str(value))


def round_lot(quantity: int, trading_unit: int) -> int:
    """return a round-lot (a multiple of trading unit)"""
    return int(quantity // trading_unit) * trading_unit


def round_price(price: Decimal, ticksize: Decimal):
    """Round down price to a multiple of tick size"""
    return (price // ticksize) * ticksize


ACallable = TypeVar("ACallable", bound=Callable)


def run_once(func: ACallable) -> ACallable:
    """Make a wrapper function that only run once

    Args:
        func: a function to wrap

    Returns:
        The wrapper function
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not wrapper.has_run:
            wrapper.has_run = True
            return func(*args, **kwargs)

    wrapper.has_run = False
    return wrapper


def str_float_to_decimal(value: Optional[Union[float, str]], precision: int = 2) -> Any:
    """Returns a Decimal if input type is float or string.

    Otherwise, leave the value as is. The return value is not necessary a Decimal.
    """
    if isinstance(value, str):
        if value == "None":
            return None
        else:
            value = float(value)

    return round_decimal(value, precision) if isinstance(value, float) else value


def generate_tradable_quantity_key(common_key: str, symbol: str) -> str:
    return f"{common_key}:{symbol}:TRADABLE-QUANTITY"


def generate_additional_tradable_quantity_key(
    common_key: str, symbol: str, date
) -> str:
    return (
        f'{common_key}:{symbol}:ADDITIONAL-TRADABLE-QUANTITY:{date.strftime("%Y%m%d")}'
    )


def get_file_path(root_dir, relative_file_path):
    return os.path.join(root_dir, relative_file_path)


def get_full_path_file(file_descriptor, relative_file_path):
    return os.path.join(Path(file_descriptor).parent, relative_file_path)
