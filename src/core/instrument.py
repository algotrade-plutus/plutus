"""This module defines the concept of (financial) Instrument(s).
Other financial Instrument specifications can be defined here.

The classes in this module are:
- Instrument

## Instrument
- Instance variables:
    - trading_unit

- Methods:
    - get_id

"""

from typing import Type, TypeVar

from core.environment import Exchange

T = TypeVar("T")


# TODO: Development Note 1
#  The property trading_unit and the method tick_size is a little bit troublesome
#  because they reference to another class which somehow serves as a data container
#  (the class Exchange where different exchanges are defined as some kind of data).
#  Problems arise when more exchanges are available (later) and somehow the class
#  Instrument need to know about that to function properly.
#  The exchange property of the Instrument class should only provide logic to
#  access those data not the data directly. The problem still retain with the
#  newly defined Exchange class because it is somehow still a data container.


class Instrument:
    """This class defines the (financial) Instrument concept which mainly contains
    the name of the instrument and the exchange where it's listed.

    Attributes:
        ticker_symbol (str): The name of the instrument.
        exchange_code_str (str or None): The exchange where it's listed.

    NOTE: [Convention] instrument-type is defined by the length and prefix of ticker symbol
        STOCK: 3-char symbol
        WARRANT: 8-char symbol. C_
        FUND: 8-char symbol. E_ or F_
    """

    def __init__(
        self,
        ticker_symbol: str,
        exchange_code_str: str = None,
    ):
        """Initialize the Instrument object"""

        self.ticker_symbol = ticker_symbol
        self.exchange_code_str = exchange_code_str
        self.trading_unit = Exchange.TRADING_UNIT.get(exchange_code_str, None)

    @classmethod
    def from_id(cls: Type[T], instrument_id: str) -> T:
        """Convert instrument_id to Instrument
        Args:
            instrument_id (str): string of instrument as instrument_id

        Returns:
            Instrument
        """
        exchange_code_str, ticker_symbol = instrument_id.split(":")
        return cls(ticker_symbol, exchange_code_str)

    @property
    def id(self) -> str:
        """Returns the id of the instrument which is the exchange name and the instrument name."""
        return f"{self.exchange_code_str}:{self.ticker_symbol}"

    @property
    def eid(self) -> str:
        """Return instrument exchange code"""
        return self.exchange_code_str

    @property
    def symbol(self) -> str:
        """Return instrument name"""
        return self.ticker_symbol

    @property
    def is_stock(self) -> bool:
        """Check instrument is stock or not"""
        return len(self.symbol) == 3

    @property
    def currency_unit(self):
        """Return Instrument currency unit based on its exchange code"""
        return Exchange.CURRENCY_UNIT.get(self.exchange_code_str, None)

    def __hash__(self):
        """Return the hash of the object."""
        return hash((self.exchange_code_str, self.ticker_symbol))

    def __eq__(self, other) -> bool:
        """Compares self with other Instrument object.

        Two objects are equal if the instrument_name and exchange are equal.

        Args:
            other (Instrument): other Instrument object

        Returns:
             A boolean indicate equality.
        """
        return (self.ticker_symbol, self.exchange_code_str) == (
            other.ticker_symbol,
            other.exchange_code_str,
        )

    def __str__(self):
        """Returns the string representation of the Instrument object."""
        return self.id

    def __repr__(self):
        """Returns the official string representation of the Instrument object."""
        return self.__str__()
