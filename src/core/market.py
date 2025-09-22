"""This module defines useful class related to the trading market.

The classes in this module are:
- Quote
- Asset

This module currently is not in used and incomplete

## Quote
## Depth
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Union

from core.instrument import Instrument

import utils

VN30FUTURE_QUOTE_CODE_MAPPING = {
    0: "instrument",
    1: "ref_price",
    2: "ceiling_price",
    3: "floor_price",
    4: "bid_price_3",
    5: "bid_quantity_3",
    6: "bid_price_2",
    7: "bid_quantity_2",
    8: "bid_price_1",
    9: "bid_quantity_1",
    10: "latest_matched_price",
    11: "latest_matched_quantity",
    12: "ref_diff_abs",
    13: "ref_diff_pct",
    14: "ask_price_1",
    15: "ask_quantity_1",
    16: "ask_price_2",
    17: "ask_quantity_2",
    18: "ask_price_3",
    19: "ask_quantity_3",
    20: "total_matched_quantity",
    21: "open_price",
    22: "highest_price",
    23: "lowest_price",
    24: "open_interest",
    25: "maturity_date",
    26: "foreign_buy_quantity",
    27: "foreign_sell_quantity",
    28: "hidden_system_status",
    29: "latest_estimated_matched_price",
}

# Codes which are float (prices, diff, etc.)
VN30FUTURE_DECIMAL_CONVERSION_CODE = [
    1,
    2,
    3,
    4,
    6,
    8,
    10,
    12,
    13,
    14,
    16,
    18,
    21,
    22,
    23,
    29,
]

STOCK_QUOTE_CODE_MAPPING = {
    0: "instrument",
    1: "ref_price",
    2: "ceiling_price",
    3: "floor_price",
    4: "bid_quantity_4",
    5: "bid_price_3",
    6: "bid_quantity_3",
    7: "bid_price_2",
    8: "bid_quantity_2",
    9: "bid_price_1",
    10: "bid_quantity_1",
    11: "latest_matched_price",
    12: "latest_matched_quantity",
    13: "ref_diff_abs",
    14: "ask_price_1",
    15: "ask_quantity_1",
    16: "ask_price_2",
    17: "ask_quantity_2",
    18: "ask_price_3",
    19: "ask_quantity_3",
    20: "ask_quantity_4",
    21: "total_matched_quantity",
    22: "open_price",
    23: "highest_price",
    24: "lowest_price",
    25: "average_price",
    26: "foreign_buy_quantity",
    27: "foreign_sell_quantity",
    28: "foreign_room",
    29: "close_price",
    30: "hidden_system_status",
    31: "latest_estimated_matched_price",
}

# Codes which are float (prices, diff, etc.)
STOCK_DECIMAL_CONVERSION_CODE = [
    1,
    2,
    3,
    5,
    7,
    9,
    11,
    13,
    14,
    16,
    18,
    22,
    23,
    24,
    25,
    29,
    31,
]

QUOTE_DECIMAL_ATTRIB = [
    "ref_price",
    "ceiling_price",
    "floor_price",
    "bid_price_3",
    "bid_price_2",
    "bid_price_1",
    "latest_matched_price",
    "ref_diff_abs",
    "ref_diff_pct",
    "ask_price_1",
    "ask_price_2",
    "ask_price_3",
    "open_price",
    "close_price",
    "highest_price",
    "lowest_price",
    "average_price",
    "latest_estimated_matched_price",
]


# Codes which are float (prices, diff, etc.)
@dataclass(init=True, repr=True, eq=True, frozen=True)
class InternalDataHubQuote:
    """Defined the quote dataclass from the Internal Price Hub.

    Attributes:
        instrument (Instrument):
        ref_price (Decimal):
        ceiling_price (Decimal):
        floor_price (Decimal):
        bid_price_10 (Decimal):
        bid_quantity_10 (int):
        bid_price_9 (Decimal):
        bid_quantity_9 (int):
        bid_price_8 (Decimal):
        bid_quantity_8 (int):
        bid_price_7 (Decimal):
        bid_quantity_7 (int):
        bid_price_6 (Decimal):
        bid_quantity_6 (int):
        bid_price_5 (Decimal):
        bid_quantity_5 (int):
        bid_price_4 (Decimal):
        bid_quantity_4 (int):
        bid_price_3 (Decimal):
        bid_quantity_3 (int):
        bid_price_2 (Decimal):
        bid_quantity_2 (int):
        bid_price_1 (Decimal):
        bid_quantity_1 (int):
        latest_matched_price (Decimal):
        latest_matched_quantity (int):
        ref_diff_abs (Decimal):
        ref_diff_pct (Decimal):
        ask_price_1 (Decimal):
        ask_quantity_1 (int):
        ask_price_2 (Decimal):
        ask_quantity_2 (int):
        ask_price_3 (Decimal):
        ask_quantity_3 (int):
        ask_price_4 (Decimal):
        ask_quantity_4 (int):
        ask_price_5 (Decimal):
        ask_quantity_5 (int):
        ask_price_6 (Decimal):
        ask_quantity_6 (int):
        ask_price_7 (Decimal):
        ask_quantity_7 (int):
        ask_price_8 (Decimal):
        ask_quantity_8 (int):
        ask_price_9 (Decimal):
        ask_quantity_9 (int):
        ask_price_10 (Decimal):
        ask_quantity_10 (int):
        total_matched_quantity (int):
        open_price (Decimal):
        highest_price (Decimal):
        lowest_price (Decimal):
        average_price (Decimal):
        open_interest (int):
        foreign_buy_quantity (int):
        foreign_sell_quantity (int):
        foreign_room (int):
        close_price (Decimal):
        bid_quantity_4 (int):
        ask_quantity_4 (int):
        maturity_date (str):
        hidden_system_status (str):
        datetime_str (str):
        timestamp (float):
        latest_estimated_matched_price (Decimal):
    """

    instrument: Instrument = None
    ref_price: Decimal = None
    ceiling_price: Decimal = None
    floor_price: Decimal = None
    bid_price_10: Decimal = None
    bid_quantity_10: int = None
    bid_price_9: Decimal = None
    bid_quantity_9: int = None
    bid_price_8: Decimal = None
    bid_quantity_8: int = None
    bid_price_7: Decimal = None
    bid_quantity_7: int = None
    bid_price_6: Decimal = None
    bid_quantity_6: int = None
    bid_price_5: Decimal = None
    bid_quantity_5: int = None
    bid_price_4: Decimal = None
    bid_quantity_4: int = None
    bid_price_3: Decimal = None
    bid_quantity_3: int = None
    bid_price_2: Decimal = None
    bid_quantity_2: int = None
    bid_price_1: Decimal = None
    bid_quantity_1: int = None
    latest_matched_price: Decimal = None
    latest_matched_quantity: int = None
    ref_diff_abs: Decimal = None
    ref_diff_pct: Decimal = None
    ask_price_1: Decimal = None
    ask_quantity_1: int = None
    ask_price_2: Decimal = None
    ask_quantity_2: int = None
    ask_price_3: Decimal = None
    ask_quantity_3: int = None
    ask_price_4: Decimal = None
    ask_quantity_4: int = None
    ask_price_5: Decimal = None
    ask_quantity_5: int = None
    ask_price_6: Decimal = None
    ask_quantity_6: int = None
    ask_price_7: Decimal = None
    ask_quantity_7: int = None
    ask_price_8: Decimal = None
    ask_quantity_8: int = None
    ask_price_9: Decimal = None
    ask_quantity_9: int = None
    ask_price_10: Decimal = None
    ask_quantity_10: int = None
    total_matched_quantity: int = None
    open_price: Decimal = None
    highest_price: Decimal = None
    lowest_price: Decimal = None
    average_price: Decimal = None
    open_interest: int = None
    foreign_buy_quantity: int = None
    foreign_sell_quantity: int = None
    foreign_room: int = None
    close_price: Decimal = None
    maturity_date: str = None
    hidden_system_status: str = None
    datetime_str: str = None
    timestamp: float = None
    latest_estimated_matched_price: Decimal = None

    def to_basic_dict(self):
        """Converts data of the object into dictionary.

        Decimal, float will be converted to string.

        Returns:
            A dictionary contains the information of the object
        """
        object_basic_dict = vars(self).copy()

        for attrib in QUOTE_DECIMAL_ATTRIB:
            value = object_basic_dict[attrib]

            if value and type(value) in [float, Decimal]:
                value = str(value)

            object_basic_dict[attrib] = value

        object_basic_dict["instrument"] = object_basic_dict["instrument"].id

        return object_basic_dict

    @classmethod
    def from_basic_dict(cls, info_dict: dict):
        """Makes an object from a dictionary.

        Args:
            info_dict (dict): An info_dict contains information to create the object.

        Returns:
            A PriceHubQuote object.
        """
        instrument_id = info_dict["instrument"]
        info_dict["instrument"] = Instrument.from_id(instrument_id)

        for attrib in QUOTE_DECIMAL_ATTRIB:
            value = info_dict.get(attrib)
            info_dict[attrib] = utils.str_float_to_decimal(value)

        info_dict = {
            key: info_dict[key] for key in info_dict if key in cls.__annotations__
        }

        return cls(**info_dict)

    @classmethod
    def from_cached_quote(cls, cached_quote):
        """Make InternalPriceHubQuote object from cached quote

        Args:
            cached_quote (CachedQuote): A CachedQuote object contains the quote

        Returns:
            A PriceHubQuote object.

        NOTE: CacheQuote & PriceHubQuote must have the same attributes' name
        """
        cached_quote_dict = vars(cached_quote).copy()

        for key, cached_quote_element in cached_quote_dict.items():
            if isinstance(cached_quote_element, CachedQuoteElement):
                cached_quote_dict[key] = cached_quote_element.value

            if key in QUOTE_DECIMAL_ATTRIB:
                value = cached_quote_element.value

                if value is None:
                    continue

                # format to currency of intrument
                if key != "ref_diff_abs" and "ref_diff_pct":
                    value = value / cached_quote.instrument.currency_unit

                cached_quote_dict[key] = utils.str_float_to_decimal(value)

        return cls(**cached_quote_dict)


@dataclass(init=True, repr=True, eq=True)
class CachedQuoteElement:
    """Defines the cached quote element.

    Attributes:
        instrument (Instrument):
        quote_type (str):
        value (int, Decimal or str):
        source (str):
        last_updated_str (str):
        last_updated (float):
    """

    instrument: Instrument = None
    quote_type: str = None
    value: Union[int, Decimal, str] = None
    source: str = None
    last_updated_str: str = None
    last_updated: float = None

    def to_basic_dict(self):
        """Converts into dictionary contains information in
        Python built-in datatype."""
        ret_dict = vars(self).copy()

        ret_dict["instrument"] = ret_dict["instrument"].id

        if isinstance(ret_dict["value"], Decimal):
            ret_dict["value"] = str(ret_dict["value"])

        return ret_dict

    @classmethod
    def from_basic_dict(cls, info_dict: dict):
        """Initiates object through dictionary contains information in
        Python built-in datatype.

        Args:
            info_dict (dict): information data as dict

        Returns:
            CachedQuoteElement
        """
        instrument_id = info_dict["instrument"]
        info_dict["instrument"] = Instrument.from_id(instrument_id)

        if info_dict["quote_type"] in QUOTE_DECIMAL_ATTRIB:
            value = info_dict["value"]
            value = utils.str_float_to_decimal(value)
            info_dict["value"] = value

        # filter out keys that are not attributes of CachedQuoteElement
        info_dict = {
            key: info_dict[key] for key in info_dict if key in cls.__annotations__
        }

        return cls(**info_dict)


@dataclass(init=True, repr=True, eq=True)
class CachedQuote:
    """Defines the cached quote in Algotrade system.

    Attributes:
    """

    instrument: Instrument = None
    ref_price: CachedQuoteElement = None
    ceiling_price: CachedQuoteElement = None
    floor_price: CachedQuoteElement = None
    bid_price_10: CachedQuoteElement = None
    bid_quantity_10: CachedQuoteElement = None
    bid_price_9: CachedQuoteElement = None
    bid_quantity_9: CachedQuoteElement = None
    bid_price_8: CachedQuoteElement = None
    bid_quantity_8: CachedQuoteElement = None
    bid_price_7: CachedQuoteElement = None
    bid_quantity_7: CachedQuoteElement = None
    bid_price_6: CachedQuoteElement = None
    bid_quantity_6: CachedQuoteElement = None
    bid_price_5: CachedQuoteElement = None
    bid_quantity_5: CachedQuoteElement = None
    bid_price_4: CachedQuoteElement = None
    bid_quantity_4: CachedQuoteElement = None
    bid_price_3: CachedQuoteElement = None
    bid_quantity_3: CachedQuoteElement = None
    bid_price_2: CachedQuoteElement = None
    bid_quantity_2: CachedQuoteElement = None
    bid_price_1: CachedQuoteElement = None
    bid_quantity_1: CachedQuoteElement = None
    latest_matched_price: CachedQuoteElement = None
    latest_matched_quantity: CachedQuoteElement = None
    ref_diff_abs: CachedQuoteElement = None
    ref_diff_pct: CachedQuoteElement = None
    ask_price_1: CachedQuoteElement = None
    ask_quantity_1: CachedQuoteElement = None
    ask_price_2: CachedQuoteElement = None
    ask_quantity_2: CachedQuoteElement = None
    ask_price_3: CachedQuoteElement = None
    ask_quantity_3: CachedQuoteElement = None
    ask_price_4: CachedQuoteElement = None
    ask_quantity_4: CachedQuoteElement = None
    ask_price_5: CachedQuoteElement = None
    ask_quantity_5: CachedQuoteElement = None
    ask_price_6: CachedQuoteElement = None
    ask_quantity_6: CachedQuoteElement = None
    ask_price_7: CachedQuoteElement = None
    ask_quantity_7: CachedQuoteElement = None
    ask_price_8: CachedQuoteElement = None
    ask_quantity_8: CachedQuoteElement = None
    ask_price_9: CachedQuoteElement = None
    ask_quantity_9: CachedQuoteElement = None
    ask_price_10: CachedQuoteElement = None
    ask_quantity_10: CachedQuoteElement = None
    total_matched_quantity: CachedQuoteElement = None
    open_price: CachedQuoteElement = None
    highest_price: CachedQuoteElement = None
    lowest_price: CachedQuoteElement = None
    average_price: CachedQuoteElement = None
    open_interest: CachedQuoteElement = None
    foreign_buy_quantity: CachedQuoteElement = None
    foreign_sell_quantity: CachedQuoteElement = None
    foreign_room: CachedQuoteElement = None
    close_price: CachedQuoteElement = None
    maturity_date: CachedQuoteElement = None
    hidden_system_status: str = None
    datetime_str: str = None
    timestamp: float = None
    latest_estimated_matched_price: CachedQuoteElement = None

    # -------------------@ RedisQuotePublisher support methods @--------------------------------!

    # TODO: poor code structure, refactor this later
    def update_from_pricehub_quote(
        self, quote: InternalDataHubQuote, source_name: str
    ):
        """Updates the cache by a pricehub quote.

        Args:
            quote (InternalDataHubQuote): new quote data.
            source_name (str): The source name to log from which the new quote is obtained.

        Returns:
            None

        Raises:
            ValueError:
                - When updated_info_dict does not have instrument_name,
                    exchange_code_str and timestamp.
                - When the instrument_name and exchange_code_str of cached quote
                    and updated_info_dict do not match (except when the value of
                    these attribute of cached quote is None).

        NOTE: (RedisQuotePublisher support methods) publish data to redis directly
        from FPTS pricehub. Already replaced by pricehub server.
        To be moved out of this repos.
        """
        # Change into dictionary mode, the reason is to easily traverse the attribute name
        updated_info_dict = vars(quote)

        input_instrument = updated_info_dict["instrument"]
        input_datetime_str = updated_info_dict["datetime_str"]
        input_timestamp = updated_info_dict["timestamp"]

        if (
            input_instrument is None
            or input_datetime_str is None
            or input_timestamp is None
        ):
            raise ValueError(
                "updated info dictionary need to have at least info of instrument, "
                "datetime in string and timestamp"
            )

        if self.instrument and self.instrument != input_instrument:
            raise ValueError(
                "The updated info instrument and the cached quote instrument do not match."
            )

        for attrib, value in updated_info_dict.items():
            if value is None:
                continue

            if attrib in [
                "instrument",
                "datetime_str",
                "timestamp",
                "hidden_system_status",
            ]:
                setattr(self, attrib, value)

            else:
                cached_quote_element = getattr(self, attrib)
                if cached_quote_element is None:
                    cached_quote_element = CachedQuoteElement(
                        instrument=input_instrument,
                        quote_type=attrib,
                        value=value,
                        source=source_name,
                        last_updated_str=input_datetime_str,
                        last_updated=input_timestamp,
                    )
                    setattr(self, attrib, cached_quote_element)
                else:
                    cached_quote_element.value = value
                    cached_quote_element.source = source_name
                    cached_quote_element.last_updated_str = input_datetime_str
                    cached_quote_element.last_updated = input_timestamp

    # ------------------------------------------------------------------------------------------!

    def to_basic_dict(self):
        """Converts into dictionary contains information in
        Python built-in datatype."""
        ret_dict = vars(self).copy()

        ret_dict["instrument"] = ret_dict["instrument"].id

        for key, value in ret_dict.items():
            if isinstance(value, CachedQuoteElement):
                ret_dict[key] = value.to_basic_dict()

        return ret_dict

    @classmethod
    def from_basic_dict(cls, info_dict: dict):
        """Initiates object through dictionary contains information in
        Python built-in datatype.

        Args:
            info_dict (dict): information data as dict

        Returns:
            CachedQuote
        """
        instrument_id = info_dict["instrument"]
        info_dict["instrument"] = Instrument.from_id(instrument_id)

        for attrib, value in info_dict.items():
            if attrib in [
                "instrument",
                "datetime_str",
                "timestamp",
                "hidden_system_status",
            ]:
                continue

            if not value:
                continue

            info_dict[attrib] = CachedQuoteElement.from_basic_dict(value)

        # filter out keys that are not attributes of CachedQuote
        info_dict = {
            key: info_dict[key] for key in info_dict if key in cls.__annotations__
        }

        return cls(**info_dict)


@dataclass(init=True, repr=True, eq=True, frozen=True)
class Depth:
    """Incomplete class. To be defined later.

    Possibly represent the bid and ask prices of an instrument.
    Potential attributes are listed below.

    Attributes:
        instrument_name (Instrument): The instrument
        exchange (str): The exchange code
        latest_matched_price (Decimal): The latest matched price
        latest_matched_quantity (int): The latest matched quantity
        asks (List of Decimal): The list of Decimal represents the ask prices
        bids (List of Decimal): The list of Decimal represents the bid prices
    """

    instrument_name: str = None
    exchange: str = None
    latest_matched_price: Decimal = None
    latest_matched_quantity: int = None
    asks: List[Decimal] = None
    bids: List[Decimal] = None
