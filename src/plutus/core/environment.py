"""This module defines some of the market practicality constant
such as market start, end, and break time.

The class in this module are:
- Environment

## Environment
This class do not have any methods.
The class contains  class property served as program constants.
"""
import datetime
import math
import time
from decimal import Decimal
from threading import RLock, Thread
from typing import Optional

import pytz


# TODO: should the name change into VietnameseMarketEnvironment or VietnameseTradingEnvironment?


class Environment:
    """Defines the constants of the Vietnamese market"""
    current_time: Optional[datetime.datetime] = None
    lock_current_time = RLock()
    simulation_thread = None

    UNIT_PRICE = 1000
    TIMEZONE = pytz.timezone('Asia/Ho_Chi_Minh')

    @staticmethod
    def _increase_when_time_pass():
        while True:
            time.sleep(0.1)
            if Environment.current_time is not None:
                with Environment.lock_current_time:
                    Environment.current_time += datetime.timedelta(seconds=0.1)

    @staticmethod
    def set_time(date_time: datetime.datetime):
        with Environment.lock_current_time:
            Environment.current_time = date_time.astimezone(Environment.TIMEZONE)

    @staticmethod
    def start_simulation():
        if Environment.simulation_thread is None:
            Environment.simulation_thread = Thread(target=Environment._increase_when_time_pass)
            Environment.simulation_thread.daemon = True
            Environment.simulation_thread.start()

    @staticmethod
    def get_current_time() -> datetime.datetime:
        if Environment.current_time is not None:
            return Environment.current_time
        return datetime.datetime.now(tz=Environment.TIMEZONE)

    @staticmethod
    def sleep_until(until_time: datetime.time):
        until_date_time = datetime.datetime.combine(Environment.get_current_time().date(),
                                                    until_time).astimezone(Environment.TIMEZONE)
        while until_date_time > Environment.get_current_time():
            time.sleep(1)


class Exchange:
    """Defines Vietnamese exchanges' constants."""
    HSX = 'HSX'
    """Hochiminh Stock Exchange"""

    HNX = 'HNX'
    """Hanoi Stock Exchange"""

    UPCOM = 'UPCOM'
    """Unlisted Public Company Market"""

    DS = 'HNXDS'
    """Derivatives Market"""

    CURRENCY_UNIT = {'HSX': 1000, 'HNX': 1000, 'UPCOM': 1000, 'HNXDS': 1}
    """FIXME: x1000 VND currency unit from pricehub"""

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


class TradingSessions:
    """NOTE: There is only one trading session per day. Sub-sessions are determined
    by trading methods, Call Auction (vi-en. Periodic Order Matching) Method or
    Continuous Auction (vi-en. Continuous Order Matching) Method, and named according
    to the default order type of the trading period.

    e.g. ATO/ATC order type is commonly used as opening/closing session
    in viet-english convention
    """

    ATO = {
        Exchange.HSX: AbstractTradingSession(
            start_time=datetime.time(9, 0, 0),
            end_time=datetime.time(9, 15, 0)),
        Exchange.DS: AbstractTradingSession(
            start_time=datetime.time(8, 45, 0),
            end_time=datetime.time(9, 0, 0))
    }
    """
        Opening (Auction) Session:
        Call Auction (vi-en. Periodic Order Matching) Method At The Open
    """
    ATO_HSX = ATO[Exchange.HSX]
    ATO_DS = ATO[Exchange.DS]

    LO = {
        Exchange.HSX: AbstractTradingSession(
            start_time=datetime.time(9, 15, 0),
            end_time=datetime.time(14, 30, 0)),
        Exchange.HNX: AbstractTradingSession(
            start_time=datetime.time(9, 0, 0),
            end_time=datetime.time(14, 30, 0)),
        Exchange.UPCOM: AbstractTradingSession(
            start_time=datetime.time(9, 0, 0),
            end_time=datetime.time(15, 0, 0)),
        Exchange.DS: AbstractTradingSession(
            start_time=datetime.time(9, 0, 0),
            end_time=datetime.time(14, 30, 0))
    }
    """
    Continuous/Core Trading Session:
    Continuous Auction (vi-en. Continuous Order Matching) Method
    """
    LO_HSX = LO[Exchange.HSX]
    LO_HNX = LO[Exchange.HNX]
    LO_UPCOM = LO[Exchange.UPCOM]
    LO_DS = LO[Exchange.DS]

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
