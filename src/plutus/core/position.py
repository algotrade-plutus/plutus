"""This module specifies the Position class and the related classes such as Pair.

The classes in this module are:
- Position
- Pair

## Position
- Instance variables:
    - id
    - is_liquidized
    - volume

- Methods:
    - to_dict
    - unrealized_value
    - update_from_transaction
    - value

## Pair
- Instance variables:
    - value

- Methods:
    - to_dict

"""

import datetime
from copy import copy, deepcopy
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

import utils
from plutus.core.instrument import Instrument
from plutus.core.order import Side, OrderSide
from plutus.core.transaction import Transaction


class PositionType(Enum):
    """Type of Position"""

    LONG = True
    SHORT = False

    @property
    def side(self):
        """get side of open position"""
        return (OrderSide.SELL, OrderSide.BUY)[self.value]

    @classmethod
    def from_order_side(cls, side: OrderSide):
        """get position side from order side"""
        return cls(side == OrderSide.BUY)

    @staticmethod
    def side_to_position_type(side: OrderSide):
        """get the position type (LONG/SHORT) from order side (BUY/SELL)."""
        return PositionType.LONG if side == OrderSide.BUY else PositionType.SHORT

    def __str__(self):
        """Returns the string representation of Position Type"""
        return ("short", "long")[self.value]

    def __repr__(self):
        return self.__str__()


class Position:
    """This class defines the Position concept and the methods of an Position object.

    Some signature descriptions of an Position:

    - A Position belong to a specific Portfolio.
    - Position can be updated by Transactions.
    - A Position is liquidized if its quantity is zero.

    Attributes:
        position_id (int): The ID of the Position in integer.
        portfolio_id (int): The ID of Portfolio the Position belongs.
        exchange_id (str): The exchange id of the ticker symbol of the Position.
        ticker_symbol (str): The ticker symbol of the Position.
        capital (Decimal): The money amount that is used to open position since the beginning date
        opening_amount (int): The number of stock / position that is not closed
        closing_amount (int): The number of stock / position that is closed
        realized_pnl (Decimal): The realized PnL after closing "closing_amount" stock / position
        fee (Decimal): The total fee
        last_update_time (float): Timestamp of the last transaction that affects the Position.

    Raises:
        AssertionError: If quantity is negative.
    """

    def __init__(
        self,
        position_id: Optional[str],
        portfolio_id: Optional[int],
        exchange_id: str,
        ticker_symbol: str,
        capital: Decimal,
        opening_amount: int,
        closing_amount: int = 0,
        realized_pnl: Decimal = Decimal("0"),
        fee: Optional[Decimal] = Decimal("0"),
        last_update_time: float = None,
    ):
        """Initializes the Position object.

        NOTE: in case keep lossless information from position history, we may keep history
        of opening_amount, acquisition_value, realized_pnl as a dictionary by timestamp.
            dict {timestamp: opening_amount}
            dict {timestamp: closing_amount}
            dict {timestamp: acquisition_value}
            dict {timestamp: realized_pnl}
        """
        # assert opening_amount != 0, 'Position size must not be 0'

        # self.position_id = position_id if position_id is not None else uuid4().hex
        self.position_id = position_id
        self.portfolio_id = portfolio_id
        self.exchange_id = exchange_id
        self.ticker_symbol = ticker_symbol

        # only increase if position is opened by more than two transactions
        self.opening_amount = opening_amount
        self.closing_amount = closing_amount

        # no longer use acquire_price to init position as loss information when rounded
        self.capital = capital

        # realized profit and loss when close position
        self.realized_pnl = realized_pnl

        self.fee = fee
        self.last_update_time = last_update_time

    # --------------------------------------------------------------------------
    # Overwritten-class built-in methods
    def __int__(self):
        """Returns the int representation of the Position as quantity."""
        return self.quantity

    def __len__(self):
        """Returns the len of position as opening amount."""
        return self.quantity

    def __str__(self):
        """Returns the string representation of the Position.

        Returns:
            A string represents the Position.
        """
        return (
            f"Position ID: {self.position_id}, pid: {str(self.portfolio_id)}, "
            f"{str(self.instrument)}, {self.side}, quantity: {self.quantity:6}, "
            f"acquired price: {self.average_entry_price}, "
            f"{datetime.datetime.fromtimestamp(self.last_update_time, tz=Environment.TIMEZONE)}"
        )

    def __repr__(self):
        # TODO: refactor the __repr__ method to adhere to the convention of Python.
        #  There is a difference between __repr__ and _str__ in Python's specification.
        """Return the official string representation of the Position object.

        Returns:
             An official string represents the Position object.
        """
        return "%r" % self.__dict__

    def __eq__(self, other) -> bool:
        return (
            self.position_id == other.position_id
            and self.portfolio_id == other.portfolio_id
            and self.exchange_id == other.exchange_id
            and self.ticker_symbol == other.ticker_symbol
            and self.opening_amount == other.opening_amount
            and self.closing_amount == other.closing_amount
            and self.capital == other.capital
            and self.realized_pnl == other.realized_pnl
            and self.fee == other.fee
        )

    # --------------------------------------------------------------------------
    # Property methods

    @property
    def id(self) -> str:
        """An integer represents Position ID."""
        return self.position_id

    @property
    def pid(self) -> int:
        """An integer represents Position's Portfolio ID"""
        return self.portfolio_id

    @property
    def instrument(self) -> Instrument:
        """Return Position's Instrument"""
        return Instrument.from_id(f"{self.exchange_id}:{self.ticker_symbol}")

    @property
    def is_liquidized(self) -> bool:
        """A boolean indicates if the Position is liquidized or not."""
        return self.opening_amount == 0

    @property
    def is_closed(self) -> bool:
        """A boolean indicates if the Position is closed or not."""
        return self.opening_amount == 0

    # alias
    is_close = is_closed

    @property
    def size(self) -> int:
        """Size of position is the total opening & closing amount."""
        return self.opening_amount + self.closing_amount

    @property
    def type(self) -> PositionType:
        """The string represents the position of this position."""
        return PositionType.LONG if self.size > 0 else PositionType.SHORT

    @property
    def side(self) -> Side:
        """Return Position's Side based on Position's size"""
        return Side.BUY if self.size > 0 else Side.SELL

    @property
    def sign(self) -> int:
        """A sign of the Position side in integer."""
        return self.side.sign

    @property
    def remainder(self) -> int:
        """Size of open position. alias of opening_amount."""
        return self.opening_amount

    @property
    def quantity(self) -> int:
        """Size of open position."""
        return abs(self.opening_amount)

    @property
    def realized_quantity(self) -> int:
        """The closing quantity of the Position in integer"""
        return abs(self.closing_amount)

    @property
    def volume(self) -> int:
        """The quantity of the Position in integer. An alias of quantity."""
        return abs(self.opening_amount)

    @property
    def average_entry_price(self) -> Decimal:
        """The average entry price of the Position in Decimal."""
        return utils.round_decimal(self.capital / abs(self.size))

    @property
    def acquisition_value(self) -> Decimal:
        """Returns the acquisition value of the opening amount."""
        return utils.round_decimal((self.capital / self.size) * self.opening_amount)

    # --------------------------------------------------------------------------
    # IO methods

    @classmethod
    def from_transaction(cls, transaction: Transaction, size: int = None):
        """Construct an object from dictionary of basic data types."""
        return cls(
            position_id=None,
            portfolio_id=transaction.portfolio_id,
            exchange_id=transaction.exchange_id,
            ticker_symbol=transaction.ticker_symbol,
            capital=transaction.acquisition_value(size),
            opening_amount=size if size else transaction.size,
            fee=transaction.acquisition_cost(size),
            last_update_time=transaction.matched_timestamp,
        )

    @classmethod
    def from_basic_dict(cls, position_basic_dict: dict):
        """Construct an object from dictionary of basic data types."""
        return cls(
            position_id=position_basic_dict["position_id"],
            portfolio_id=position_basic_dict["portfolio_id"],
            exchange_id=position_basic_dict["exchange_id"],
            ticker_symbol=position_basic_dict["ticker_symbol"],
            capital=utils.str_float_to_decimal(position_basic_dict["capital"]),
            opening_amount=position_basic_dict["opening_amount"],
            closing_amount=position_basic_dict.get("closing_amount", 0),
            realized_pnl=utils.str_float_to_decimal(
                position_basic_dict.get("realized_pnl", "0")
            ),
            fee=utils.str_float_to_decimal(position_basic_dict.get("fee", "0")),
            last_update_time=(
                datetime.datetime.now().timestamp()
                if "last_update_time" not in position_basic_dict
                else position_basic_dict["last_update_time"]
            ),
        )

    def to_basic_dict(self):
        """Returns an object in dictionary of basic data types format."""
        basic_dict = deepcopy(vars(self))
        basic_dict["capital"] = str(basic_dict["capital"])
        basic_dict["realized_pnl"] = str(basic_dict["realized_pnl"])
        basic_dict["fee"] = str(basic_dict["fee"])
        return basic_dict

    @classmethod
    def from_dict(cls, **kwargs):
        """Initializes a Position object from a data dictionary."""
        return cls(
            position_id=kwargs["position_id"],
            portfolio_id=kwargs["portfolio_id"],
            exchange_id=kwargs["exchange_id"],
            ticker_symbol=kwargs["ticker_symbol"],
            capital=kwargs["capital"],
            opening_amount=kwargs["opening_amount"],
            closing_amount=kwargs["closing_amount"],
            realized_pnl=kwargs["realized_pnl"],
            fee=kwargs["fee"],
            last_update_time=kwargs["last_update_time"],
        )

    def to_dict(self):
        """Converts the object into dictionary.

        Returns:
             The dictionary represents the object.
        """
        return deepcopy(vars(self))

    def set_id(self, position_id: str):
        """Set the id into the object"""
        self.position_id = position_id

    # --------------------------------------------------------------------------
    # private methods

    def _resize(self, size: int):
        """Update remainder when realize. Example:

        (open, close) = (10, 0); size = 5  #same side
        close -= min(0, 5 * 1) = 0
        open += 5 = 15

        (open, close) = (10, 0); size = -5  #opposite side
        close -= min(0, -5 * 1) = 5
        open += -5 = 5

        (open, close) = (-10, 0); size = 5  #opposite side
        close += min(0, 5 * -1) = -5
        open += 5 = -5

        (open, close) = (-10, 0); size = -5  #same side
        close += min(0, -5 * -1) = 0
        open += -5 = -15

        (open, close) = (10,  0) size = -15  #over side
        open = max(0, (10 - 15) * 1) = 0

        (open, close) = (-10, 0) size = 15  #over side
        open = max(0, (-10 + 15) * -1) = 0
        """
        if self._is_oversize(size):
            # switch opposite-side is not allowed.
            self.closing_amount = self.size
            self.opening_amount = 0
        else:
            self.closing_amount -= self.sign * min(0, size * self.sign)
            self.opening_amount += size

    def _get_realized_quantity(self, size: int) -> int:
        """Get realized quantity when close position.

        Args:
            size (int): new opening/closing size

        Returns:
            int
        """
        # check sign of size and position are the same
        if size * self.sign >= 0:
            return 0

        return abs(self._get_executed_size(size))

    def _get_executed_size(self, size: int) -> int:
        """Get executed size.

        Args:
            size (int): new opening/closing size

        Returns:
            int
        """
        if self._is_oversize(size):
            # in case all the old Position is closed,
            # the quantity of (old) the position is now the realized quantity
            return -self.opening_amount
        else:
            # in case the old Position is not closed
            # the transaction quantity is the realized quantity
            return size

    def _is_oversize(self, size) -> bool:
        """Check if transaction size is over the remainder by compute position size
        when transaction is executed
        Args:
            size (int): new opening/closing size

        Returns:
            boolean
        """
        return (self.opening_amount + size) * self.sign < 0

    # --------------------------------------------------------------------------
    # APIs

    def get_pnl(self, settlement_price: Decimal, size: int) -> Decimal:
        """Compute profit and loss of Position from a transaction.
        Args:
            settlement_price (Decimal): closing price
            size (int): closing size

        Returns:
            The profit/loss and the quantity of resulting in the profit/loss.
        """
        realized_quantity = self._get_realized_quantity(size)

        return (
            self.sign
            * realized_quantity
            * (settlement_price - self.average_entry_price)
        )

    def update_from_transaction(self, transaction: Transaction, size: int = None):
        """Updates the Position from a Transaction.

        The update happens inplace. This function computes the profit/loss
        after updating the information from the transaction and the quantity
        resulting in the profit/loss then update the Position attributes.

        Args:
            transaction (Transaction): The Transaction contains the information to update the Position.
            size (int): The transaction size

        Returns:
            updated position

        NOTE: switch opposite-side is not allowed. raise error if size of transaction
        to close position is over the position size.
        """
        if self.instrument != transaction.instrument:
            raise ValueError(
                "Transaction instrument must be the same with the updating Position."
            )
        self.last_update_time = Environment.get_current_time().now().timestamp()

        if size is None:
            size = transaction.size

        # recalculate profit and loss when realized position
        self.realized_pnl += self.get_pnl(transaction.matched_price, size)

        # recalculate fee when update position
        executed_size = self._get_executed_size(size)
        self.fee += transaction.acquisition_cost(executed_size)

        # recalculate capital when expand position size.
        self.capital += max(0, self.sign * executed_size * transaction.matched_price)

        # update opening & closing amount when realized position
        self._resize(size)

        return executed_size

    def get_unrealized_pnl_ratio(self, current_price: Decimal):
        """Returns the unrealized profit and loss ratio of the Position based
        on the current price.

        Args:
            current_price: The current price of the Position.

        Returns:
            The unrealized profit and loss ratio of the Position.
        """
        return self.sign * (current_price / self.average_entry_price - 1)

    def get_unrealized_pnl(self, current_price: Decimal) -> Decimal:
        """Calculates the difference between the current value of the Position
        compares to when it's acquired.

        Args:
            current_price: The current price of the underlying Instrument.

        Returns:
            The difference between the current value of the Position compares
            to when it's acquired.
        """
        return Decimal((current_price - self.average_entry_price) * self.opening_amount)

    def get_value(self, current_price: Decimal) -> Decimal:
        # TODO: change name to begin with verb
        """Returns the value of the Position.

        Args:
            current_price: The current price of the Instrument.

        Returns:
            The value of the Position which is current price times quantity.
        """
        return abs(current_price * self.opening_amount)

    def clone(self):
        """Clone position."""
        return copy(self)


@dataclass(init=True, eq=True, repr=True)
class PositionHistory:
    """Defines the updated history of a position from a transaction."""

    position_history_id: Optional[str]
    position_id: str
    transaction_id: str
    size: int

    def to_basic_dict(self):
        """Returns an object in dictionary of basic data types format."""
        basic_dict = deepcopy(vars(self))
        return basic_dict

    @classmethod
    def from_basic_dict(cls, position_history_basic_dict: dict):
        return cls(
            position_history_id=position_history_basic_dict["position_history_id"],
            position_id=position_history_basic_dict["position_id"],
            transaction_id=position_history_basic_dict["transaction_id"],
            size=position_history_basic_dict["size"],
        )

    @property
    def id(self):
        """Returns the id"""
        return self.position_history_id

    def set_id(self, position_history_id: str):
        """Sets the id into the object"""
        self.position_history_id = position_history_id
