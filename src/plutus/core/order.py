"""Defines order object to work in the client APIs"""

import datetime
import logging
from copy import deepcopy
from decimal import Decimal
from enum import Enum
from typing import Optional

from plutus import utils
from plutus.utils import Environment
from plutus.core.instrument import Instrument


class Side(Enum):
    """Defines the Order Side or an order."""

    BUY = "BUY"
    SELL = "SELL"
    CROSS = "CROSS"

    def __str__(self):
        """Returns the string representation of Side"""
        return self.value

    def reverse(self):
        """Returns the reverse Side"""
        if self is self.BUY:
            return self.SELL

        if self is self.SELL:
            return self.BUY

    @property
    def sign(self):
        """Returns the sign of Side"""
        if self is self.BUY:
            return 1

        if self is self.SELL:
            return -1


OrderSide = Side


class OrderType(Enum):
    """Defines the order type in the system."""

    AT_THE_OPENING = "ATO"
    AT_THE_CLOSE = "ATC"
    MARKET_WITH_LEFTOVER_AS_LIMIT = "MTL"
    LIMIT = "LO"
    MARKET_FILL_OR_KILL = "MOK"
    MARKET_IMMEDIATE_OR_CANCEL = "MAK"
    # sell at floor or buy at ceiling for guaranteed match
    MARKET = "MKT"

    def __str__(self):
        return self.value


# TODO: have a mapping between Algotrade client Order Status and FIX
class OrderStatus(Enum):
    """Defines the order statuses of the Algotrade client.

    Most of these order statuses map the FIX OrdStatus(39) field
    with some added states to cover specific cases from the client.
    """

    # Mapping with FIX OrdStatus(39) field
    NEW = "NEW"  # OrdStatus(39): 0
    PARTIALLY_FILLED = "PARTIALLY_FILLED"  # OrdStatus(39): 1
    FILLED = "FILLED"  # OrdStatus(39): 2
    DONE_FOR_DAY = "DONE_FOR_DAY"  # OrdStatus(39): 3
    CANCELLED = "CANCELLED"  # OrdStatus(39): 4
    REPLACED = "REPLACED"  # OrdStatus(39): 5
    PENDING_CANCEL = "PENDING_CANCEL"  # OrdStatus(39): 6
    STOPPED = "STOPPED"  # OrdStatus(39): 7
    REJECTED = "REJECTED"  # OrdStatus(39): 8
    SUSPENDED = "SUSPENDED"  # OrdStatus(39): 9
    PENDING_NEW = "PENDING_NEW"  # OrdStatus(39): A
    CALCULATED = "CALCULATED"  # OrdStatus(39): B
    EXPIRED = "EXPIRED"  # OrdStatus(39): C
    ACCEPTED_FOR_BIDDING = "ACCEPTED_FOR_BIDDING"  # OrdStatus(39): D
    PENDING_REPLACE = "PENDING_REPLACE"  # OrdStatus(39): E

    # Other states of the Order defined by the client
    # Order just created by the client
    CREATED = "CREATED"
    # Order being sent to the broker
    SENT_TO_BROKER = "SENT_TO_BROKER"
    # Order received at the broker (internal broker, or stock broker (FPTS, SSI, BSC, etc.))
    RECEIVED_BROKER = "RECEIVED_BROKER"
    # Order being sent to the exchange (HNX, HSX, etc.) from broker
    SENT_TO_EXCHANGE = "SENT_TO_EXCHANGE"
    # Order received at the stock exchange (HNX, HSX, etc.)
    RECEIVED_EXCHANGE = "RECEIVED_EXCHANGE"

    # Paired or Tuple order is being filled
    PARTIAL_FILLED_PAIR = "PARTIAL_FILLED_PAIR"

    def __str__(self):
        return self.value


class OrderCancelStatus(Enum):
    """Defines the order cancel status of the system."""

    PENDING = "PENDING"
    REJECTED = "REJECTED"
    CONFIRMED = "CONFIRMED"

    def __str__(self):
        return self.value


class Order:
    """Represents the order.

    This class is a unified Order interface for different types broker in the system.

    Args:
        ticker_symbol (str): The ticker symbol to place the order.
        exchange_id (str): The exchange id to place the order.
            order_type (OrderType): The type of the order.
        quantity (int): The quantity of the financial instrument.
        order_side (Side): The side of the order (buy or sell).
        broker_id (str): The broker ID to execute the order.
            Usually the locale (optional) and abbreviation of the broker, e.g. VN:FPTS, or FPTS
        order_status (OrderStatus): The status of this order from the broker.
        limit_price (Decimal or None): The price to order if this is a limit price order.
        client_order_id (str or None): The order id from the client side.
        server_order_id (str or None): The order id from the server side.
        avg_price (Decimal or None): The average price this order have been matched.
        matched_quantity (int): The quantity of this order have been matched.
        last_modified (float): The last modified timestamp.
        last_checked (float): The last checked timestamp.
        kwargs: Other key-value parameters if needed.

    Raises:
        AssertionError: If the side is neither buy side or sell side.
    """

    def __init__(
        self,
        ticker_symbol: str,
        exchange_id: str,
        order_type: OrderType,
        quantity: int,
        order_side: Side,
        broker_id: str,
        order_status: OrderStatus = OrderStatus.CREATED,
        limit_price: Optional[Decimal] = None,
        client_order_id: Optional[str] = None,
        server_order_id: Optional[str] = None,
        avg_price: Optional[Decimal] = None,
        matched_quantity: int = 0,
        last_modified: float = None,
        last_checked: float = None,
        order_cancel_status: Optional[OrderCancelStatus] = None,
        accum_fee: Decimal = Decimal("0.0"),
        portfolio_id: Optional[int] = None,
        **kwargs,
    ):
        self.ticker_symbol = ticker_symbol
        self.exchange_id = exchange_id
        self.order_type = order_type
        self.quantity = quantity
        self.order_side = order_side
        self.broker_id = broker_id
        self.order_status = order_status
        self.limit_price = limit_price
        self.client_order_id = client_order_id
        self.server_order_id = server_order_id
        self.avg_price = avg_price
        self.matched_quantity = matched_quantity
        self.last_modified = last_modified
        self.last_checked = last_checked
        self.order_cancel_status = order_cancel_status
        self.accum_fee = accum_fee
        # TODO: Development note.
        #  Consider remove the portfolio_id in the order object to streamline the object?
        #  Related to the question about bot and portfolio.
        self.portfolio_id = portfolio_id
        self.other_info = kwargs

    @classmethod
    def from_dict(cls, **kwargs):
        """Creates an Order object from the dictionary.

        NOTE: only use this method for the dictionary created by to_dict
        """
        # TODO: Find an elegant way to add the other_info into the class
        return cls(
            ticker_symbol=kwargs["ticker_symbol"],
            exchange_id=kwargs["exchange_id"],
            order_type=OrderType(kwargs["order_type"]),
            quantity=kwargs["quantity"],
            order_side=OrderSide(kwargs["order_side"]),
            broker_id=kwargs["broker_id"],
            order_status=OrderStatus(kwargs["order_status"]),
            limit_price=(
                Decimal(kwargs["limit_price"])
                if kwargs["limit_price"] is not None
                else None
            ),
            client_order_id=kwargs["client_order_id"],
            server_order_id=kwargs["server_order_id"],
            avg_price=(
                Decimal(kwargs["avg_price"])
                if kwargs["avg_price"] is not None
                else None
            ),
            matched_quantity=kwargs["matched_quantity"],
            last_modified=kwargs["last_modified"],
            last_checked=kwargs["last_checked"],
            order_cancel_status=kwargs["order_cancel_status"],
            portfolio_id=kwargs["portfolio_id"],
        )

    def to_basic_dict(self):
        basic_dict = deepcopy(vars(self))
        # Convert all the non-basic type into basic type
        basic_dict["order_type"] = str(self.order_type)
        basic_dict["order_side"] = str(self.order_side)
        basic_dict["order_status"] = str(self.order_status)
        if self.limit_price:
            basic_dict["limit_price"] = str(self.limit_price)
        if self.avg_price:
            basic_dict["avg_price"] = str(self.avg_price)
        if self.order_cancel_status:
            basic_dict["order_cancel_status"] = str(self.order_cancel_status)
        basic_dict["accum_fee"] = str(self.accum_fee)
        return basic_dict

    @classmethod
    def from_basic_dict(cls, basic_dict: dict):
        return cls(
            ticker_symbol=basic_dict["ticker_symbol"],
            exchange_id=basic_dict["exchange_id"],
            order_type=OrderType(basic_dict["order_type"]),
            quantity=basic_dict["quantity"],
            order_side=OrderSide(basic_dict["order_side"]),
            broker_id=basic_dict["broker_id"],
            order_status=OrderStatus(basic_dict["order_status"]),
            limit_price=utils.str_float_to_decimal(basic_dict["limit_price"]),
            client_order_id=basic_dict["client_order_id"],
            server_order_id=basic_dict["server_order_id"],
            avg_price=utils.str_float_to_decimal(basic_dict["avg_price"]),
            matched_quantity=basic_dict["matched_quantity"],
            last_modified=basic_dict["last_modified"],
            last_checked=basic_dict["last_checked"],
            order_cancel_status=basic_dict["order_cancel_status"],
            accum_fee=utils.str_float_to_decimal(basic_dict["accum_fee"]),
            portfolio_id=basic_dict["portfolio_id"],
        )

    @property
    def id(self) -> str:
        """The (internal) id of this order in integer."""
        return self.client_order_id

    @property
    def is_filled(self):
        """A boolean to indicate if the order have been fully matched or not."""
        if self.matched_quantity == self.quantity:
            if self.order_status is not OrderStatus.FILLED:
                logging.warning(
                    f"{self.id}|{self.server_order_id} "
                    f"order status {self.order_status} "
                    f"but order is filled {self.quantity}({self.matched_quantity})",
                )
            return True

        # incase self.matched_quantity != self.quantity
        if self.order_status is OrderStatus.FILLED:
            raise ValueError(
                f"{self.id}|{self.server_order_id} "
                f"order status should not be FILLED, "
                f"matched quantity: {self.matched_quantity}({self.quantity})"
            )
        return False

    @property
    def is_partial_filled(self):
        """A boolean to indicate if the order is partial filled or not."""
        return self.matched_quantity != 0 and self.matched_quantity < self.quantity

    @property
    def is_partial_filled_and_cancelled(self):
        """A boolean to indicate if the order is partial filled and is cancelled."""
        return self.is_partial_filled and self.order_status is OrderStatus.CANCELLED

    @property
    def is_partial_filled_and_expired(self):
        """A boolean to indicate if the order is partial filled and is expired."""
        return self.is_partial_filled and self.order_status is OrderStatus.EXPIRED

    @property
    def is_no_filled_and_cancelled(self):
        """A boolean to indicate if the order have no matched quantity and is cancelled."""
        return self.matched_quantity == 0 and self.order_status is OrderStatus.CANCELLED

    @property
    def is_no_filled_and_expired(self):
        """A boolean to indicate if the order have no matched quantity and is expired."""
        return self.matched_quantity == 0 and self.order_status is OrderStatus.EXPIRED

    @property
    def is_pending_cancel(self):
        """A boolean to indicate if the order is in pending cancel or not"""
        return self.order_status == OrderStatus.PENDING_CANCEL

    @property
    def is_completed(self):
        """A boolean to indicate if the order was filled, cancelled or expired."""
        return self.is_filled or self.order_status in [
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
            OrderStatus.REJECTED,
            OrderStatus.SUSPENDED,
            OrderStatus.STOPPED,
        ]

    @property
    def is_under_submitted(self):
        """A boolean to indicate if order is submitted but not yet received by broker."""
        return self.order_status in [
            OrderStatus.CREATED,
            OrderStatus.SENT_TO_BROKER,
            OrderStatus.RECEIVED_BROKER,
        ]

    @property
    def is_cancelable(self):
        """A boolean to indicate if it is ok to sent cancel request.

        Return False if order is completed, under-submitted or cancel request
        has been sent.
        """
        if self.order_cancel_status:
            return False

        return not self.is_completed and not self.is_under_submitted

    @property
    def is_at_least_partial_filled(self):
        """A boolean to indicate that at least the order is partially filled."""
        return self.matched_quantity != 0

    @property
    def is_instructed_execution(self):
        return (
            "order_execution_instruction" in self.other_info
            and self.other_info["order_execution_instruction"]
        )

    @property
    def pending_quantity(self):
        """Return quantity not filled yet"""
        return self.quantity - self.matched_quantity

    @property
    def value(self) -> Decimal:
        """Current value of order"""
        return (
            self.matched_quantity * self.avg_price if self.avg_price is not None else 0
        )

    # TODO: refactor this later
    @property
    def instrument(self) -> Instrument:
        """Return Order's instrument"""
        return Instrument.from_id(f"{self.exchange_id}:{self.ticker_symbol}")

    def update_from(self, updated_order):
        """Update order info"""
        self.order_status = updated_order.order_status
        self.order_cancel_status = updated_order.order_cancel_status
        self.avg_price = updated_order.avg_price
        self.matched_quantity = updated_order.matched_quantity
        self.last_modified = updated_order.last_modified
        self.last_checked = updated_order.last_checked
        self.accum_fee = updated_order.accum_fee
        self.other_info = updated_order.other_info

    def __str__(self):
        """Returns the string representation of the SubmittedOrder."""
        s = f"Order ID: {self.id}, oid: {self.server_order_id}, {self.order_side}, "
        s += f"{self.exchange_id}:{self.ticker_symbol}, "

        s += f"matched: {self.matched_quantity:5}, " f"avg price: {self.avg_price}, "

        if self.last_modified is not None:
            s += (
                f"last modified: "
                f"{datetime.datetime.fromtimestamp(self.last_modified, tz=Environment.TIMEZONE)}, "
            )

        s += f"{self.order_status}, "

        if self.last_checked is not None:
            s += (
                f"last checked: "
                f"{datetime.datetime.fromtimestamp(self.last_checked, tz=Environment.TIMEZONE)}, "
            )

        if self.order_cancel_status is not None:
            s += f"order cancel status: {self.order_cancel_status}"

        return s

    def __eq__(self, other):
        return vars(self) == vars(other)

    def __repr__(self):
        """Returns the official string representation of the Order"""
        return "%r" % self.__dict__

    def set_id(self, order_id: str):
        """Set the id into the object"""
        self.client_order_id = order_id
