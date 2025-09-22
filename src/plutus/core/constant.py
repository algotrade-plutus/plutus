""""Defines the class Exchange and other related methods."""

import math
import datetime

import pytz

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, List, Optional


class VietnamMarketConstant:
    """Defines Vietnamese exchanges' constants."""
    UNIT_PRICE = 1000
    """Price unit of the Vietnam Dong"""

    TIMEZONE = pytz.timezone('Asia/Ho_Chi_Minh')
    """Timezone of the Vietnam Market"""

    HSX = 'HSX'
    """Hochiminh Stock Exchange"""

    HNX = 'HNX'
    """Hanoi Stock Exchange"""

    UPCOM = 'UPCOM'
    """Unlisted Public Company Market"""

    DS = 'HNXDS'
    """Derivatives Market"""

    CURRENCY_UNIT = {'HSX': 1000, 'HNX': 1000, 'UPCOM': 1000, 'HNXDS': 1}
    """Currency unit in each exchange. Note: Review the meaning in HNXDS"""

    TRADING_UNIT = {HSX: 100, HNX: 100, UPCOM: 100, DS: 1}
    """A multiple of trading unit is called a round-lot"""

    DAILY_TRADING_LIMIT = {HSX: 0.07, HNX: 0.1, UPCOM: 0.15, DS: 0.07}
    """A daily trading limit is the maximum price range limit that a security is
    allowed to fluctuate in one trading session"""

    TICK_SIZE = {
        DS: Decimal('0.1'),
        HNX: Decimal('0.1'),
        UPCOM: Decimal('0.1'),
        HSX: {
            (0, 10): Decimal('0.01'),
            (10, 50): Decimal('0.05'),
            (50, math.inf): Decimal('0.1')
        }
    }
    """Tick size may vary by exchange and price.
    NOTE: tick size is 0.01 for warrants & exchange-traded funds (ETF)"""


class AbstractTradingSession:
    """Trading session may vary by exchange"""

    def __init__(
        self,
        start_time: datetime.time,
        end_time: datetime.time,
        effective_day: datetime.datetime.weekday = (0, 1, 2, 3, 4),  # only workday
        timezone: datetime.timezone = None  # timezone info
    ):
        self.start = start_time
        self.end = end_time
        self.effective_day = effective_day
        self.timezone = timezone

    def is_current(self, given_datetime: datetime.datetime):
        """Return True if the trading session is at the given datetime."""
        if given_datetime.weekday() not in self.effective_day:
            return False

        return self.start <= given_datetime.time() <= self.end

    # TODO: considering how to compare from the previous day ATC session (T and T+1 day)
    def get_total_seconds_from(
        self,
        time_point: datetime.time,
        given_datetime: datetime.datetime
    ) -> float:
        """Returns the total seconds from the given_datetime to the time_point.

        Args:
            time_point (datetime.time): A point in time in datetime.time.
            given_datetime (datetime.datetime): A given datetime to compare with the time_point.

        Returns:
            A total seconds from the given_datetime to the time_point.
            A positive number if the time_point has passed (given_datetime.time() > time_point),
            a negative number otherwise.
        """
        return (
            given_datetime
            - datetime.datetime.combine(given_datetime.date(), time_point, tzinfo=self.timezone)
        ).total_seconds()

    def get_total_seconds_from_start(
        self,
        given_datetime: datetime.datetime
    ) -> float:
        """Returns the total seconds from the given_datetime to the start of the session.

        Args:
            given_datetime (datetime.datetime): A given datetime.

        Returns:
            A total seconds from the given_datetime to the start of the session.
            A positive number if the session has started (given_datetime > start),
            a negative number otherwise.
        """
        return self.get_total_seconds_from(self.start, given_datetime)

    def get_total_seconds_from_end(
        self,
        given_datetime: datetime.datetime
    ) -> float:
        """Returns the total seconds from the given_datetime to the end of the session.

        Args:
            given_datetime (datetime.datetime): A given datetime.

        Returns:
            A total seconds from the given_datetime to the end of the session.
            A positive number if the session has ended (given_datetime > end),
            a negative number otherwise.
        """
        return self.get_total_seconds_from(self.end, given_datetime)


class VietNamTradingSession:
    """NOTE: There is only one trading session per day. Sub-sessions are determined
    by trading methods, Call Auction (vi-en. Periodic Order Matching) Method or
    Continuous Auction (vi-en. Continuous Order Matching) Method, and named according
    to the default order type of the trading period.

    e.g. ATO/ATC order type is commonly used as opening/closing session
    in viet-english convention
    """

    ATO_HSX = AbstractTradingSession(
        start_time=datetime.time(9, 0, 0),
        end_time=datetime.time(9, 15, 0)
    )
    ATO_DS = AbstractTradingSession(
        start_time=datetime.time(8, 45, 0),
        end_time=datetime.time(9, 0, 0)
    )
    """
    Opening (Auction) Session:
    Call Auction (vi-en. Periodic Order Matching) Method At The Open
    """

    LO_HSX = AbstractTradingSession(
        start_time=datetime.time(9, 15, 0),
        end_time=datetime.time(14, 30, 0)
    )
    LO_HNX = AbstractTradingSession(
        start_time=datetime.time(9, 0, 0),
        end_time=datetime.time(14, 30, 0)
    )
    LO_UPCOM = AbstractTradingSession(
        start_time=datetime.time(9, 0, 0),
        end_time=datetime.time(15, 0, 0)
    )
    LO_DS = AbstractTradingSession(
        start_time=datetime.time(9, 0, 0),
        end_time=datetime.time(14, 30, 0)
    )
    """
    Continuous/Core Trading Session:
    Continuous Auction (vi-en. Continuous Order Matching) Method
    """


    ATC = AbstractTradingSession(
        start_time=datetime.time(14, 30, 0),
        end_time=datetime.time(14, 45, 0)
    )
    """
    Closing (Auction) Session:
    Call Auction (vi-en. Periodic Order Matching) Method At The Close
    """

    PLO = AbstractTradingSession(
        start_time=datetime.time(14, 45, 0),
        end_time=datetime.time(15, 0, 0)
    )
    """Late Trading Session"""

    NOON_BREAK = AbstractTradingSession(
        start_time=datetime.time(11, 30, 0),
        end_time=datetime.time(13, 0, 0)
    )
    """Noon Break"""


@dataclass(init=True, repr=True, eq=True, frozen=True)
class Exchange:
    """The class Exchange contains information of a specific exchange.

    The information can be:
        - Trading sessions (ATO, LO, ATC, etc.)
        - Trading unit
        - Daily trading limit
        - Tick size
    """

    name: str
    code: str
    working_day = (List[int],)
    before_trading_session: Optional[AbstractTradingSession]
    ato_session: Optional[AbstractTradingSession]
    lo_session: AbstractTradingSession
    noon_break: Optional[AbstractTradingSession]
    atc_session: Optional[AbstractTradingSession]
    plo_session: Optional[AbstractTradingSession]
    after_trading_session: Optional[AbstractTradingSession]
    trading_unit: int
    daily_trading_limit: float
    tick_size_function: Optional[Callable[[str, Decimal], Decimal]]

    # TODO: consider changing to a more abstract way to determine the start of
    #  the particular exchange
    @property
    def trading_time_start(self):
        """Returns the start of the trading time of the exchange."""
        return self.ato_session.start if self.ato_session else self.lo_session.start

    # TODO: consider changing to a more abstract way to determine the end of
    #  the particular exchange
    @property
    def trading_time_end(self):
        """Returns the end of the trading time of the exchange."""
        return self.plo_session.end if self.plo_session else self.atc_session.end

    def get_tick_size(
        self,
        ticker_symbol: str,
        price_point: Decimal,
    ) -> Decimal:
        """Returns the tick size of the exchange.

        Calls a function to calculate the tick size function if needed.

        Args:
            ticker_symbol (str): The symbol of the instrument.
            price_point (Decimal): Some exchanges (right now HSX) need
                price point to identify the tick_size since tick size is varied
                by price point.
        Returns:
            The tick size defined by the exchange.

        """
        return self.tick_size_function(ticker_symbol, price_point)


def get_hsx_tick_size(
    ticker_symbol: str,
    price_point: Decimal,
) -> Decimal:
    """Gets the tick size of HSX.

    Args:
        ticker_symbol (str): The ticker symbol of the instrument
        price_point (Decimal): The price point to get the appropriate tick size

    Returns:
        A tick size in Decimal.
    """
    # tick size is 0.01 for warrants & exchange-traded funds (ETF)
    if len(ticker_symbol) == 8 and ticker_symbol[0] in ["C", "E", "F"]:
        return Decimal(".01")

    hsx_tick_size_info = {
        (0, 10): Decimal("0.01"),
        (10, 50): Decimal("0.05"),
        (50, math.inf): Decimal("0.1"),
    }
    # tick sizes of stocks in HSX vary by price
    for (lower_bound, upper_bound), tick_size in hsx_tick_size_info.items():
        if lower_bound <= price_point < upper_bound:
            return tick_size


HSX = Exchange(
    name="HoChiMinh Stock Exchange",
    code=VietnamMarketConstant.HSX,
    before_trading_session=AbstractTradingSession(
        start_time=datetime.time(0, 0, 0),
        end_time=datetime.time(8, 59, 59),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    ato_session=AbstractTradingSession(
        start_time=datetime.time(9, 0, 0),
        end_time=datetime.time(9, 15, 0),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    lo_session=AbstractTradingSession(
        start_time=datetime.time(9, 15, 0),
        end_time=datetime.time(14, 30, 0),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    noon_break=AbstractTradingSession(
        start_time=datetime.time(11, 30, 0),
        end_time=datetime.time(13, 0, 0),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    atc_session=AbstractTradingSession(
        start_time=datetime.time(14, 30, 0),
        end_time=datetime.time(14, 45, 0),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    plo_session=None,
    after_trading_session=AbstractTradingSession(
        start_time=datetime.time(14, 45, 1),
        end_time=datetime.time(23, 59, 59),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    trading_unit=100,
    daily_trading_limit=0.07,
    tick_size_function=get_hsx_tick_size,
)

HNX = Exchange(
    name="Hanoi Stock Exchange",
    code=VietnamMarketConstant.HNX,
    before_trading_session=AbstractTradingSession(
        start_time=datetime.time(0, 0, 0),
        end_time=datetime.time(8, 59, 59),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    ato_session=None,
    lo_session=AbstractTradingSession(
        start_time=datetime.time(9, 0, 0),
        end_time=datetime.time(14, 30, 0),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    noon_break=AbstractTradingSession(
        start_time=datetime.time(11, 30, 0),
        end_time=datetime.time(13, 0, 0),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    atc_session=AbstractTradingSession(
        start_time=datetime.time(14, 30, 0),
        end_time=datetime.time(14, 45, 0),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    plo_session=AbstractTradingSession(
        start_time=datetime.time(14, 45, 0),
        end_time=datetime.time(15, 0, 0),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    after_trading_session=AbstractTradingSession(
        start_time=datetime.time(15, 0, 1),
        end_time=datetime.time(23, 59, 59),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    trading_unit=100,
    daily_trading_limit=0.1,
    tick_size_function=lambda _, __: Decimal("0.1"),
)

UPCOM = Exchange(
    name="Unlisted Public Company Market",
    code=VietnamMarketConstant.UPCOM,
    before_trading_session=AbstractTradingSession(
        start_time=datetime.time(0, 0, 0),
        end_time=datetime.time(8, 59, 59),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    ato_session=None,
    lo_session=AbstractTradingSession(
        start_time=datetime.time(9, 0, 0),
        end_time=datetime.time(15, 0, 0),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    noon_break=AbstractTradingSession(
        start_time=datetime.time(11, 30, 0),
        end_time=datetime.time(13, 0, 0),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    atc_session=None,
    plo_session=None,
    after_trading_session=AbstractTradingSession(
        start_time=datetime.time(15, 0, 1),
        end_time=datetime.time(23, 59, 59),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    trading_unit=100,
    daily_trading_limit=0.15,
    tick_size_function=lambda _, __: Decimal("0.1"),
)

DS = Exchange(
    name="Derivatives Market",
    code=VietnamMarketConstant.DS,
    before_trading_session=AbstractTradingSession(
        start_time=datetime.time(0, 0, 0),
        end_time=datetime.time(8, 44, 59),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    ato_session=AbstractTradingSession(
        start_time=datetime.time(8, 45, 0),
        end_time=datetime.time(9, 0, 0),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    lo_session=AbstractTradingSession(
        start_time=datetime.time(9, 0, 0),
        end_time=datetime.time(14, 30, 0),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    noon_break=AbstractTradingSession(
        start_time=datetime.time(11, 30, 0),
        end_time=datetime.time(13, 0, 0),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    atc_session=AbstractTradingSession(
        start_time=datetime.time(14, 30, 0),
        end_time=datetime.time(14, 45, 0),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    plo_session=None,
    after_trading_session=AbstractTradingSession(
        start_time=datetime.time(14, 45, 1),
        end_time=datetime.time(23, 59, 59),
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    trading_unit=1,
    daily_trading_limit=0.07,
    tick_size_function=lambda _, __: Decimal("0.1"),
)
