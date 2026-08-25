"""Defines the class ExchangeSpec and other related methods."""

import math
import datetime
import re

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
    """A multiple of trading unit is called a round-lot.

    These are the values **in force today**. HOSE's round lot has not always
    been 100: it was 10 until 2021-01-03 and rose to 100 on 2021-01-04. Any
    lookup covering a date before that must go through
    :func:`get_trading_unit`, which takes the date; this dict cannot express
    the change and is kept for present-day callers and backwards
    compatibility.
    """

    HSX_ROUND_LOT_RAISED = datetime.date(2021, 1, 4)
    """The session HOSE's minimum round lot went from 10 shares to 100.

    Applying today's 100 to 2020 rejects orders the real HOSE accepted. The
    corpus holds 94,675 HSX stock closes in 2020, so this is not a corner
    case -- it is most of a year of the equity sample.
    """

    DAILY_TRADING_LIMIT = {HSX: 0.07, HNX: 0.1, UPCOM: 0.15, DS: 0.07}
    """A daily trading limit is the maximum price range limit that a security is
    allowed to fluctuate in one trading session"""

    TRADING_DAYS_PER_YEAR = 250
    """Trading sessions in a Vietnamese calendar year.

    Measured over 2010-2022 from the exchange calendar in this corpus: the
    median is 250 sessions, with a range of 247-252. The 252 figure carried by
    most libraries is the NYSE convention; applying it here overstates every
    annualized metric by roughly 0.40%, because annualization scales with
    sqrt(periods) or periods.

    Used as the default `annualization_factor` throughout
    :mod:`plutus.evaluation`. It remains overridable per call for non-daily
    data (12 for monthly, 1 for annual) or for comparison against results
    computed under the NYSE convention.
    """

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
        """Return True if the trading session is at the given datetime.

        The interval is **half-open**, ``[start, end)``. Vietnamese session
        boundaries abut exactly -- HSX's opening auction ends at 09:15:00 and
        continuous trading begins at 09:15:00 -- so an inclusive upper bound
        puts 09:15:00, 11:30:00, 13:00:00 and 14:30:00 in two sessions at once
        and makes the phase at those instants order-dependent. Closing the
        interval at the bottom and opening it at the top partitions the day.

        The session instances below were adjusted to abut under this
        convention; previously they left one-second holes (an
        ``after_trading_session`` starting at 14:45:01) that the inclusive
        upper bound happened to paper over.

        ``lo_session`` still spans ``noon_break`` by construction: the
        continuous window is one interval with a hole in it, not two. A caller
        resolving a phase must therefore test the noon break **before** the
        continuous session. That overlap is intentional; the boundary
        double-membership this method fixes was not.
        """
        if given_datetime.weekday() not in self.effective_day:
            return False

        return self.start <= given_datetime.time() < self.end

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
class ExchangeSpec:
    """The class ExchangeSpec contains the published rules of a specific exchange.

    The information can be:
        - Trading sessions (ATO, LO, ATC, etc.)
        - Trading unit
        - Daily trading limit
        - Tick size
    """

    name: str
    code: str
    # NOTE: not a dataclass field -- this is an assignment, not an annotation,
    # so dataclasses.fields() omits it. Left as-is deliberately: converting it
    # would change the positional signature of the four instantiations below.
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


def get_trading_unit(
    exchange_code: str,
    on: Optional[datetime.date] = None,
) -> Optional[int]:
    """The round lot in force on ``exchange_code`` at date ``on``.

    Resolving the lot by date rather than by exchange alone is the reason this
    is a function. HOSE raised its minimum from 10 to 100 shares on
    2021-01-04 (:attr:`VietnamMarketConstant.HSX_ROUND_LOT_RAISED`); a
    date-blind lookup rejects every legal 10-share HOSE order placed before
    then.

    Args:
        exchange_code: ``HSX``, ``HNX``, ``UPCOM`` or ``HNXDS``.
        on: the date to resolve at. ``None`` means today's rulebook.

    Returns:
        The round lot, or ``None`` for an exchange this rulebook does not
        carry -- the caller decides whether that is an error.
    """
    if (exchange_code == VietnamMarketConstant.HSX
            and on is not None
            and on < VietnamMarketConstant.HSX_ROUND_LOT_RAISED):
        return 10
    return VietnamMarketConstant.TRADING_UNIT.get(exchange_code)


#: A covered warrant's symbol is ``C`` + a three-letter underlying + four
#: digits (issuer and year), e.g. ``CFPT2314``. 1,816 of the 1,817 symbols the
#: ticker master types as ``warrant`` match this exactly.
_COVERED_WARRANT_RE = re.compile(r'^C[A-Z]{3}[0-9]{4}$')

#: ETF certificate symbols. ``E1VFVN30`` is the original; every later ETF is
#: ``FUE`` + four characters. Closed-end fund certificates are ALSO eight
#: characters and ALSO begin with ``F`` -- ``FUCTVGF1``, ``FUCVREIT`` -- but
#: they are not ETFs and do not get the flat tick. That collision is the whole
#: reason this is a prefix test and not a first-character test.
_ETF_PREFIXES = ('E1', 'FUE')


def is_covered_warrant(ticker_symbol: str) -> bool:
    """True for a HOSE covered-warrant symbol."""
    return bool(_COVERED_WARRANT_RE.match(ticker_symbol))


def is_etf(ticker_symbol: str) -> bool:
    """True for an ETF certificate symbol, false for a closed-end fund."""
    return (len(ticker_symbol) == 8
            and ticker_symbol.startswith(_ETF_PREFIXES))


def get_hsx_tick_size(
    ticker_symbol: str,
    price_point: Decimal,
) -> Decimal:
    """Gets the tick size of HSX.

    Covered warrants and ETF certificates trade on a flat 0.01 tick. Everything
    else on HOSE -- ordinary shares and **closed-end fund certificates** --
    uses the price-banded grid below.

    The previous predicate here was ``len(ticker) == 8 and ticker[0] in
    "CEF"``, which swept the closed-end funds in with the ETFs because they are
    also eight characters and also start with ``F``. Measured against the
    production quote tables, that was wrong: of 372 ``FUC*`` closes priced in
    the 10-50 band, **372 lie on the 0.05 tick** -- not one counterexample --
    which is the banded grid, not a flat 0.01. Genuine ETFs sit on 0.05 only
    42% of the time and warrants 62%, i.e. at the rate coincidence alone
    produces on a 0.01 grid.

    Args:
        ticker_symbol (str): The ticker symbol of the instrument
        price_point (Decimal): The price point to get the appropriate tick size

    Returns:
        A tick size in Decimal, or ``None`` when no band matches the price --
        callers treat that as indeterminate rather than guessing.
    """
    if is_covered_warrant(ticker_symbol) or is_etf(ticker_symbol):
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


HSX = ExchangeSpec(
    name="HoChiMinh Stock Exchange",
    code=VietnamMarketConstant.HSX,
    before_trading_session=AbstractTradingSession(
        start_time=datetime.time(0, 0, 0),
        end_time=datetime.time(9, 0, 0),
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
        start_time=datetime.time(14, 45, 0),
        end_time=datetime.time.max,
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    trading_unit=100,
    daily_trading_limit=0.07,
    tick_size_function=get_hsx_tick_size,
)

HNX = ExchangeSpec(
    name="Hanoi Stock Exchange",
    code=VietnamMarketConstant.HNX,
    before_trading_session=AbstractTradingSession(
        start_time=datetime.time(0, 0, 0),
        end_time=datetime.time(9, 0, 0),
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
        start_time=datetime.time(15, 0, 0),
        end_time=datetime.time.max,
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    trading_unit=100,
    daily_trading_limit=0.1,
    tick_size_function=lambda _, __: Decimal("0.1"),
)

UPCOM = ExchangeSpec(
    name="Unlisted Public Company Market",
    code=VietnamMarketConstant.UPCOM,
    before_trading_session=AbstractTradingSession(
        start_time=datetime.time(0, 0, 0),
        end_time=datetime.time(9, 0, 0),
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
        start_time=datetime.time(15, 0, 0),
        end_time=datetime.time.max,
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    trading_unit=100,
    daily_trading_limit=0.15,
    tick_size_function=lambda _, __: Decimal("0.1"),
)

DS = ExchangeSpec(
    name="Derivatives Market",
    code=VietnamMarketConstant.DS,
    before_trading_session=AbstractTradingSession(
        start_time=datetime.time(0, 0, 0),
        end_time=datetime.time(8, 45, 0),
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
        start_time=datetime.time(14, 45, 0),
        end_time=datetime.time.max,
        timezone=datetime.timezone(datetime.timedelta(hours=7)),
    ),
    trading_unit=1,
    daily_trading_limit=0.07,
    tick_size_function=lambda _, __: Decimal("0.1"),
)
