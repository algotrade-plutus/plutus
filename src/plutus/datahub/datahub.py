"""This is the interface to the PriceHub concept.

PriceHub is a unified place to get price information in the system.

This module defines the price hub data constants in PriceHubDataStructure
and the general logic of price hub in PriceHub.

The classes which represent concepts in this module are:

- PriceHub

Classes which are conceptual namespace for constants are:

- PriceHubDataStructure

## PriceHub
- Methods:
    - get_ceiling_price
    - get_floor_price
    - get_latest_quote
    - get_reference_price
    - set_callback_function
"""

# Block 1: standard library of python, sorted by package name, "import" first, "from" second
import time

from decimal import Decimal
from enum import Enum
from typing import Callable, Optional, Tuple, Union

# Block 2: third-parties packages, if it does not clear whether the package
# is a standard lib or third-parties just put on the second block

# Block 3: import from internal code, still use the rule "import" first, "from" second
from plutus.core.instrument import Instrument
from plutus.core.market import CachedQuote, InternalDataHubQuote
from plutus.core.order import OrderSide


# Block 4: something need to be run immediately from all those packages, by the import order


class PriceSource(Enum):
    FPTS_PRICE_HUB = 'FPTS_PRICE_HUB'
    FPTS_REST_API = 'FPTS_REST_API'
    FPTS_BSC_API = 'FPTS_BSC_API'
    MOON_TRADING = 'MOON_TRADING'


class PriceHubDataStructure:
    """Defines the data constants of FPTS PriceHub.

    Mostly based on the data of trading electric board.
    The constants represent by numbers. INFO_MAPPING maps numbers into strings.
    """
    TICKER_SYMBOL = 0
    REF_PRICE = 1
    CEILING_PRICE = 2
    FLOOR_PRICE = 3
    BID_PRICE_3 = 4
    BID_QUANTITY_3 = 5
    BID_PRICE_2 = 6
    BID_QUANTITY_2 = 7
    BID_PRICE_1 = 8
    BID_QUANTITY_1 = 9
    LATEST_MATCHED_PRICE = 10
    LATEST_MATCHED_QUANTITY = 11
    REF_DIFF_ABS = 12
    REF_DIFF_PCT = 13
    ASK_PRICE_1 = 14
    ASK_QUANTITY_1 = 15
    ASK_PRICE_2 = 16
    ASK_QUANTITY_2 = 17
    ASK_PRICE_3 = 18
    ASK_QUANTITY_3 = 19
    TOTAL_MATCHED_QUANTITY = 20
    OPEN_PRICE = 21
    HIGHEST_PRICE = 22
    LOWEST_PRICE = 23
    AVERAGE_PRICE = 24
    OPEN_INTEREST = 25
    FOREIGN_BUY_QUANTITY = 26
    FOREIGN_SELL_QUANTITY = 27
    FOREIGN_ROOM = 28
    CLOSE_PRICE = 29
    BID_QUANTITY_4 = 30
    ASK_QUANTITY_4 = 31
    MATURITY_DATE = 32
    HIDDEN_SYSTEM_STATUS = 33
    TIMESTAMP = 34

    INFO_MAPPING = {
        0: 'ticker_symbol',
        1: 'ref_price',
        2: 'ceiling_price',
        3: 'floor_price',
        4: 'bid_price_3',
        5: 'bid_quantity_3',
        6: 'bid_price_2',
        7: 'bid_quantity_2',
        8: 'bid_price_1',
        9: 'bid_quantity_1',
        10: 'latest_matched_price',
        11: 'latest_matched_quantity',
        12: 'ref_diff_abs',
        13: 'ref_diff_pct',
        14: 'ask_price_1',
        15: 'ask_quantity_1',
        16: 'ask_price_2',
        17: 'ask_quantity_2',
        18: 'ask_price_3',
        19: 'ask_quantity_3',
        20: 'total_matched_quantity',
        21: 'open_price',
        22: 'highest_price',
        23: 'lowest_price',
        24: 'average_price',
        25: 'open_interest',
        26: 'foreign_buy_quantity',
        27: 'foreign_sell_quantity',
        28: 'foreign_room',
        29: 'close_price',
        30: 'bid_quantity_4',
        31: 'ask_quantity_4',
        32: 'maturity_date',
        33: 'hidden_system_status',
        34: 'timestamp'
    }


class DataHub:
    """Defines the interface and general logic of PriceHub.

    Subclasses need to implement get_latest_quote and set_callback_function methods.

    Attributes:
        ceiling_price (dict): A dictionary contains the ceiling prices of the instruments.
        floor_price (dict): A dictionary contains the floor prices of the instruments.
        reference_price (dict): A dictionary contains the reference prices of the instruments.
    """

    # --------------------------------------------------------------------------
    # Operation functions:
    # - start
    # --------------------------------------------------------------------------
    def start_pubsub(self):
        """Starts the pricehub.

        Returns:
            None.

        Raises:
            NotImplementedError: If subclass does not implement this method.
        """
        raise NotImplementedError

    # --------------------------------------------------------------------------
    # APIs:
    # - get_latest_quote
    # - set_data_handler
    # --------------------------------------------------------------------------
    def _get_latest_quote(
        self,
        instrument: Instrument
    ) -> Optional[CachedQuote]:
        """Returns the latest quotes of the Instrument.

        This is the private method which subclasses need to implement.
        The logic of checking the validity of the latest quote contains
        in the public version of this one.

        Args:
            instrument (Instrument): The Instrument to get the quotes.

        Returns:
            A CachedQuote object contains the quote.

        Raises:
            NotImplementedError: If subclass does not implement this method.
        """
        raise NotImplementedError

    def get_latest_quote(
        self,
        instrument: Instrument,
        quote_valid_duration: Optional[Union[float, int]] = None,
    ) -> Optional[CachedQuote]:
        """Returns the latest quotes of the Instrument.
        Contains the logic of checking None and checking expiration of data
        to support other get individual CachedQuoteElement method.

        Args:
            instrument (Instrument): The Instrument to get the quotes.
            quote_valid_duration (float, or int. Optional.): The valid duration
                of the quote in seconds from the quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            A CachedQuote object contains the quote.
        """
        cached_quote = self._get_latest_quote(instrument)

        if not cached_quote:
            return None

        # Check if the quote is valid or not. The valid duration is set in
        # the quote_valid_duration parameters. If the quote_valid_duration is
        # None, it means that the API just check the existence of the quote.
        if quote_valid_duration:
            time_delta = time.time() - cached_quote.timestamp
            # The quote is older than the valid duration.
            if time_delta > quote_valid_duration:
                return None

        return cached_quote

    def _get_latest_cached_quote_element_value(
        self,
        instrument: Instrument,
        cache_quote_element_type: str,
        quote_valid_duration: Optional[Union[float, int]] = None,
        cached_quote_element_valid_duration: Optional[Union[float, int]] = None
    ) -> Optional[Union[Decimal, int, str]]:
        """Returns the value of the CachedQuoteElement based on some criteria.

        The current criterion is that the CachedQuoteElement must not exceed
        the expiration time.

        Args:
            instrument (Instrument): The instrument of the CachedQuoteElement.
            cache_quote_element_type (str): The type of the CachedQuoteElement in string.
            cached_quote_element_valid_duration (float, or int. Optional.): The valid duration
                of the cached quote element in seconds from the cached quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.
            quote_valid_duration (float, or int. Optional.): The valid duration
                of the quote in seconds, from the quote's latest timestamp.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            The value of the CachedQuoteElement.

        """
        cached_quote = self.get_latest_quote(instrument, quote_valid_duration)
        if not cached_quote:
            return None

        # Change into dictionary mode, the reason is to easily traverse the attribute name
        quote_info_dict = vars(cached_quote)
        cached_quote_element = quote_info_dict[cache_quote_element_type]

        if not cached_quote_element:
            return None

        # Check if the cached quote element is valid or not. The valid duration
        # is set in the cached_quote_element_valid_duration parameters. If the
        # cached_quote_element_valid_duration is None, it means that the API
        # just check the existence of the element.
        if cached_quote_element_valid_duration:
            time_delta = time.time() - cached_quote_element.last_updated
            # The quote is older than the valid duration.
            if time_delta > cached_quote_element_valid_duration:
                return None

        if isinstance(cached_quote_element.value, float):
            cached_quote_element.value = Decimal(str(
                cached_quote_element.value / instrument.currency_unit
            ))

        return cached_quote_element.value

    def get_timestamp(self, instrument: Instrument) -> Optional[Decimal]:
        """Returns the latest timestamp."""
        cached_quote = self.get_latest_quote(instrument)
        return cached_quote.timestamp if cached_quote else None

    def get_latest_matched_price(
        self,
        instrument: Instrument,
        quote_valid_duration: Optional[Union[float, int]] = None,
        cached_quote_element_valid_duration: Optional[Union[float, int]] = None,
    ) -> Optional[Decimal]:
        """Returns the latest matched price of the Instrument before the expiration time.

        Args:
            instrument (Instrument): The Instrument to get the latest matched price.
            quote_valid_duration (float, or int. Optional): The valid duration
                of the quote in seconds from the quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.
            cached_quote_element_valid_duration (float, or int. Optional): The
                valid duration of the cached quote element in seconds from
                the quote's latest timestamp.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            A Decimal if there is a valid latest matched price.
            None if there is no latest matched price or the latest matched price
            is expired.

        """
        return self._get_latest_cached_quote_element_value(
            instrument,
            'latest_matched_price',
            quote_valid_duration,
            cached_quote_element_valid_duration
        )

    def get_latest_estimated_matched_price(
        self,
        instrument: Instrument,
        quote_valid_duration: Optional[Union[float, int]] = None,
        cached_quote_element_valid_duration: Optional[Union[float, int]] = None,
    ) -> Optional[Decimal]:
        """Returns the latest estimated matched price of the Instrument before the expiration time.

        Args:
            instrument (Instrument): The Instrument to get the latest matched price.
            quote_valid_duration (float, or int. Optional): The valid duration
                of the quote in seconds from the quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.
            cached_quote_element_valid_duration (float, or int. Optional): The
                valid duration of the cached quote element in seconds from
                the quote's latest timestamp.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            A Decimal if there is a valid latest estimated matched price.
            None if there is no latest estimated matched price or the latest estimated
            matched price is expired.

        """
        return self._get_latest_cached_quote_element_value(
            instrument,
            'latest_estimated_matched_price',
            quote_valid_duration,
            cached_quote_element_valid_duration
        )

    def get_latest_matched_quantity(
        self,
        instrument: Instrument,
        quote_valid_duration: Optional[Union[float, int]] = None,
        cached_quote_element_valid_duration: Optional[Union[float, int]] = None,
    ) -> Optional[int]:
        """Returns the latest matched quantity of the Instrument
        before the expiration time.

        Args:
            instrument (Instrument): The Instrument to get the latest matched quantity.
            quote_valid_duration (float, or int. Optional): The valid duration
                of the quote in seconds from the quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.
            cached_quote_element_valid_duration (float, or int. Optional): The
                valid duration of the cached quote element in seconds from
                the quote's latest timestamp.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            A Decimal if there is a valid latest matched quantity.
            None if there is no latest matched quantity or the cached is expired.

        """
        return self._get_latest_cached_quote_element_value(
            instrument,
            'latest_matched_quantity',
            quote_valid_duration,
            cached_quote_element_valid_duration
        )

    def get_total_matched_quantity(
        self,
        instrument: Instrument,
        quote_valid_duration: Optional[Union[float, int]] = None,
        cached_quote_element_valid_duration: Optional[Union[float, int]] = None,
    ) -> Optional[int]:
        """Returns the total matched quantity of the Instrument
        before the expiration time.

        Args:
            instrument (Instrument): The Instrument to get the latest matched quantity.
            quote_valid_duration (float, or int. Optional): The valid duration
                of the quote in seconds from the quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.
            cached_quote_element_valid_duration (float, or int. Optional): The
                valid duration of the cached quote element in seconds from
                the quote's latest timestamp.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            A Decimal if there is a valid latest matched quantity.
            None if there is no latest matched quantity or the cached is expired.

        """
        return self._get_latest_cached_quote_element_value(
            instrument,
            'total_matched_quantity',
            quote_valid_duration,
            cached_quote_element_valid_duration
        )

    def get_open_price(
        self,
        instrument: Instrument,
        quote_valid_duration: Optional[Union[float, int]] = None,
        cached_quote_element_valid_duration: Optional[Union[float, int]] = None,
    ) -> Optional[Decimal]:
        """Returns the opep price of the Instrument before the expiration time.

        Args:
            instrument (Instrument): The Instrument to get the open price.
            quote_valid_duration (float, or int. Optional): The valid duration
                of the quote in seconds from the quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.
            cached_quote_element_valid_duration (float, or int. Optional): The
                valid duration of the cached quote element in seconds from
                the quote's latest timestamp.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            A Decimal if there is a valid open price.
            None if there is no open price or the cached is expired.

        """
        return self._get_latest_cached_quote_element_value(
            instrument,
            'open_price',
            quote_valid_duration,
            cached_quote_element_valid_duration
        )

    def get_close_price(
        self,
        instrument: Instrument,
        quote_valid_duration: Optional[Union[float, int]] = None,
        cached_quote_element_valid_duration: Optional[Union[float, int]] = None,
    ) -> Optional[Decimal]:
        """Returns the close price of the Instrument before the expiration time.

        Args:
            instrument (Instrument): The Instrument to get the close price.
            quote_valid_duration (float, or int. Optional): The valid duration
                of the quote in seconds from the quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.
            cached_quote_element_valid_duration (float, or int. Optional): The
                valid duration of the cached quote element in seconds from
                the quote's latest timestamp.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            A Decimal if there is a valid close price.
            None if there is no close price or the cached is expired.

        """
        return self._get_latest_cached_quote_element_value(
            instrument,
            'close_price',
            quote_valid_duration,
            cached_quote_element_valid_duration
        )

    def get_reference_price(
        self,
        instrument: Instrument,
        quote_valid_duration: Optional[Union[float, int]] = None,
        cached_quote_element_valid_duration: Optional[Union[float, int]] = None,
    ) -> Optional[Decimal]:
        """Returns the reference price of the Instrument before the expiration time.

        Args:
            instrument (Instrument): The Instrument to get the reference price.
            quote_valid_duration (float, or int. Optional): The valid duration
                of the quote in seconds from the quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.
            cached_quote_element_valid_duration (float, or int. Optional): The
                valid duration of the cached quote element in seconds from
                the quote's latest timestamp.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            A Decimal if there is a valid reference price.
            None if there is no reference price or the cached is expired.

        """
        return self._get_latest_cached_quote_element_value(
            instrument,
            'ref_price',
            quote_valid_duration,
            cached_quote_element_valid_duration
        )

    def get_ceiling_price(
        self,
        instrument: Instrument,
        quote_valid_duration: Optional[Union[float, int]] = None,
        cached_quote_element_valid_duration: Optional[Union[float, int]] = None,
    ) -> Optional[Decimal]:
        """Returns the ceiling price of the Instrument before the expiration time.

        Args:
            instrument (Instrument): The Instrument to get the ceiling price.
            quote_valid_duration (float, or int. Optional): The valid duration
                of the quote in seconds from the quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.
            cached_quote_element_valid_duration (float, or int. Optional): The
                valid duration of the cached quote element in seconds from
                the quote's latest timestamp.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            A Decimal if there is a valid ceiling price.
            None if there is no ceiling price or the cached is expired.

        """
        return self._get_latest_cached_quote_element_value(
            instrument,
            'ceiling_price',
            quote_valid_duration,
            cached_quote_element_valid_duration
        )

    def get_floor_price(
        self,
        instrument: Instrument,
        quote_valid_duration: Optional[Union[float, int]] = None,
        cached_quote_element_valid_duration: Optional[Union[float, int]] = None,
    ) -> Optional[Decimal]:
        """Returns the floor price of the Instrument before the expiration time.

        Args:
            instrument (Instrument): The Instrument to get the floor price.
            quote_valid_duration (float, or int. Optional): The valid duration
                of the quote in seconds from the quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.
            cached_quote_element_valid_duration (float, or int. Optional): The
                valid duration of the cached quote element in seconds from
                the quote's latest timestamp.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            A Decimal if there is a valid floor price.
            None if there is no floor price or the cached is expired.

        """
        return self._get_latest_cached_quote_element_value(
            instrument,
            'floor_price',
            quote_valid_duration,
            cached_quote_element_valid_duration
        )

    def get_ask_price_1(
        self,
        instrument: Instrument,
        quote_valid_duration: Optional[Union[float, int]] = None,
        cached_quote_element_valid_duration: Optional[Union[float, int]] = None,
    ) -> Optional[Decimal]:
        """Returns the ask price 1 of the Instrument before the expiration time.

        Args:
            instrument (Instrument): The Instrument to get the ask price 1.
            quote_valid_duration (float, or int. Optional): The valid duration
                of the quote in seconds from the quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.
            cached_quote_element_valid_duration (float, or int. Optional): The
                valid duration of the cached quote element in seconds from
                the quote's latest timestamp.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            A Decimal if there is a valid ask price 1.
            None if there is no ask price 1 or the cached is expired.
        """
        return self._get_latest_cached_quote_element_value(
            instrument,
            'ask_price_1',
            quote_valid_duration,
            cached_quote_element_valid_duration
        )

    def get_ask_quantity_1(
        self,
        instrument: Instrument,
        quote_valid_duration: Optional[Union[float, int]] = None,
        cached_quote_element_valid_duration: Optional[Union[float, int]] = None,
    ) -> Optional[Decimal]:
        """Returns the ask quantity 1 of the Instrument before the expiration time.

        Args:
            instrument (Instrument): The Instrument to get the ask quantity 1.
            quote_valid_duration (float, or int. Optional): The valid duration
                of the quote in seconds from the quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.
            cached_quote_element_valid_duration (float, or int. Optional): The
                valid duration of the cached quote element in seconds from
                the quote's latest timestamp.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            A Decimal if there is a valid ask quantity 1.
            None if there is no ask quantity 1 or the cached is expired.
        """
        return self._get_latest_cached_quote_element_value(
            instrument,
            'ask_quantity_1',
            quote_valid_duration,
            cached_quote_element_valid_duration
        )

    def get_bid_price_1(
        self,
        instrument: Instrument,
        quote_valid_duration: Optional[Union[float, int]] = None,
        cached_quote_element_valid_duration: Optional[Union[float, int]] = None,
    ) -> Optional[Decimal]:
        """Returns the bid price 1 of the Instrument before the expiration time.

        Args:
            instrument (Instrument): The Instrument to get the bid price 1.
            quote_valid_duration (float, or int. Optional): The valid duration
                of the quote in seconds from the quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.
            cached_quote_element_valid_duration (float, or int. Optional): The
                valid duration of the cached quote element in seconds from
                the quote's latest timestamp.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            A Decimal if there is a valid bid price 1.
            None if there is no bid price 1 or the cached is expired.
        """
        return self._get_latest_cached_quote_element_value(
            instrument,
            'bid_price_1',
            quote_valid_duration,
            cached_quote_element_valid_duration
        )

    def get_ask_price_3(
        self,
        instrument: Instrument,
        quote_valid_duration: Optional[Union[float, int]] = None,
        cached_quote_element_valid_duration: Optional[Union[float, int]] = None,
    ) -> Optional[Decimal]:
        """Returns the bid price 1 of the Instrument before the expiration time.

        Args:
            instrument (Instrument): The Instrument to get the bid price 1.
            quote_valid_duration (float, or int. Optional): The valid duration
                of the quote in seconds from the quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.
            cached_quote_element_valid_duration (float, or int. Optional): The
                valid duration of the cached quote element in seconds from
                the quote's latest timestamp.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            A Decimal if there is a valid bid price 1.
            None if there is no bid price 1 or the cached is expired.
        """
        return self._get_latest_cached_quote_element_value(
            instrument,
            'ask_price_3',
            quote_valid_duration,
            cached_quote_element_valid_duration
        )

    def get_bid_price_3(
        self,
        instrument: Instrument,
        quote_valid_duration: Optional[Union[float, int]] = None,
        cached_quote_element_valid_duration: Optional[Union[float, int]] = None,
    ) -> Optional[Decimal]:
        """Returns the bid price 1 of the Instrument before the expiration time.

        Args:
            instrument (Instrument): The Instrument to get the bid price 1.
            quote_valid_duration (float, or int. Optional): The valid duration
                of the quote in seconds from the quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.
            cached_quote_element_valid_duration (float, or int. Optional): The
                valid duration of the cached quote element in seconds from
                the quote's latest timestamp.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            A Decimal if there is a valid bid price 1.
            None if there is no bid price 1 or the cached is expired.
        """
        return self._get_latest_cached_quote_element_value(
            instrument,
            'bid_price_3',
            quote_valid_duration,
            cached_quote_element_valid_duration
        )

    def get_bid_quantity_1(
        self,
        instrument: Instrument,
        quote_valid_duration: Optional[Union[float, int]] = None,
        cached_quote_element_valid_duration: Optional[Union[float, int]] = None,
    ) -> Optional[Decimal]:
        """Returns the bid price 1 of the Instrument before the expiration time.

        Args:
            instrument (Instrument): The Instrument to get the bid price 1.
            quote_valid_duration (float, or int. Optional): The valid duration
                of the quote in seconds from the quote's latest timestamp.
                This can be seen as price hub heartbeat.
                Set to None to ignore the valid duration. Default is None.
            cached_quote_element_valid_duration (float, or int. Optional): The
                valid duration of the cached quote element in seconds from
                the quote's latest timestamp.
                Set to None to ignore the valid duration. Default is None.

        Returns:
            A Decimal if there is a valid bid price 1.
            None if there is no bid price 1 or the cached is expired.
        """
        return self._get_latest_cached_quote_element_value(
            instrument,
            'bid_quantity_1',
            quote_valid_duration,
            cached_quote_element_valid_duration
        )

    def get_market_order_limit_price(
        self, instrument: Instrument, side: OrderSide
    ) -> Optional[Decimal]:
        """Return ceil price if orderside is BUY, otherwise floor price.

        NOTE: Since HNX does not support MARKET order yet. Replace MARKET order by
        LIMIT order with ceil/floor price.
        """
        if side is OrderSide.BUY:
            return self.get_ceiling_price(instrument)
        else:
            return self.get_floor_price(instrument)

    def is_supply_shortage(
        self, instrument: Instrument, side: OrderSide
    ) -> bool:
        """Check supply shortage of an instrument (one-sided market).

        TODO: to be revised
        """
        price = self.get_latest_matched_price(instrument)
        if price is None:
            return True

        floor = self.get_floor_price(instrument)
        ceil = self.get_ceiling_price(instrument)

        # bid supply shortage. ask-sided market
        if side == OrderSide.SELL and price == floor:
            return True

        # ask supply shortage. bid-sided market
        if side == OrderSide.BUY and price == ceil:
            return True

        return False

    def is_dead(self, instrument: Instrument, quote_valid_duration: int = 15) -> bool:
        """Check if price hub is working (last updated 15 seconds ago)

        TODO: move to price hub logic
        """
        cached_quote = self.get_latest_quote(
            instrument,
            quote_valid_duration=quote_valid_duration
        )
        if cached_quote is None:
            return True

        if cached_quote.timestamp is None:
            return True

        return False

    def is_price_valid(self, price: Decimal, instrument: Instrument) -> bool:
        """Check if a price in ceiling-floor price bound"""
        return self.get_floor_price(instrument) <= price <= self.get_ceiling_price(instrument)

    def set_data_handler(
        self,
        data_handler: Callable[[Instrument, InternalDataHubQuote], None],
        instrument_id_pattern: str,
        run_in_thread: bool,
        sleep_time: float = 0.001,
        daemon: bool = False,
    ) -> Tuple[bool, str]:
        """Sets a callback function to the price hub.

        The callback function will run when appropriate data arrive.
        Subclasses need to implement this method.

        Args:
            data_handler (Callable): A data handler associate with the instrument ID pattern.
            instrument_id_pattern (str): A topic that data handle subscribe to.
            run_in_thread (bool): A flag to indicate that each message should be
                handled by a data handler in separate thread. This should be not
                confused with the run_in_thread of the pubsub of Redis.
                run_in_thread of the pubsub of Redis run each pattern subscriber
                in thread, but the data_handler in each subscriber handles each message sequentially.
            sleep_time (float): The sleep time of the data handler if needed.
            daemon (bool): Run thread as a Daemon or not.

        We normally want to run the handler in separated thread in a non-daemon
        fashion to prevent any surprises may have when the main program ends suddenly.

        Returns:
            A tuple of a boolean and a string.
            A tuple of (True, empty string) if set successfully.
            A tuple of (False, error message) if set failed.

        Raises:
            NotImplementedError: If subclass does not implement this method.
        """
        raise NotImplementedError
