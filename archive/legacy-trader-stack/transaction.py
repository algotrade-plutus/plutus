"""This module defines transactional concepts which are Order, SubmittedOrder, and Transaction.
This module also contains some classes to gather constants which are conceptual related.
They are OrderSide, OrderType, and OrderStatus.

The classes which represent concepts in this module are:

- Order
- Side
- SubmittedOrder(Order)
- Transaction
- Position
- Pair

Classes which are conceptual namespace for constants are:

- OrderCancelStatus
- OrderSide
- OrderStatus
- OrderType

## Order:
- Methods: None

# Side
- Instance variables:
    - sign

## Pair:
- Static methods:
    - from_transactions

- Instance variables:
    - close_spread
    - id
    - is_close
    - open_spread
    - value

- Methods:
    - unrealized_value

## Position:
- Instance variables:
    - close_value
    - id
    - instrument
    - is_close
    - open_value
    - type
    - value

- Methods:
    - close
    - unrealized_value

## SubmittedOrder(Order)
- Instance variables:
    - id
    - is_completed

## Transaction:
- Instance variables:
    - id

- Methods: None
"""

import datetime
import logging
from copy import deepcopy
from decimal import Decimal
from typing import Optional, Union

import utils
from plutus.core.instrument import Instrument
from plutus.core.order import Order, OrderSide


class Transaction:
    """Represents the transaction concept.

    Transaction is the result of a matched order.

    Args:
        transaction_id (int or None): The transaction id.
        order_id (str): The order_id which resulted in this transaction.
        ticker_symbol (str): The ticker symbol of the transaction.
        exchange_id (str): The exchange id of the transaction.
        portfolio_id (int): The portfolio id of the transaction.
        matched_quantity (int): The matched quantity of this transaction.
        side (Side): the side (buy/sell) of this transaction.
        matched_price (Decimal): The matched price of this transaction.
        matched_timestamp (float): When the transaction happened.
        type (str): trading, expiry, dividend, internal
        fee (float): The fee of this transaction.
        delivery_date (datetime.date): The delivery date of this transaction (for stock only)

    TODO: add created time of transaction to database. Created time & matched
    datetime are different. The first one is created by the system while the
    other one is by broker.
    """

    def __init__(
        self,
        ticker_symbol: str,
        exchange_id: str,
        transaction_id: Optional[Union[int, str]],
        portfolio_id: int,
        order_id: Optional[str],
        side: OrderSide,
        matched_quantity: int,
        matched_price: Decimal,
        matched_timestamp: float,
        type: str = "trading",
        fee: Optional[Decimal] = Decimal(0),
        delivery_date: Optional[datetime.date] = None,
    ):
        """Initializes the object."""
        self.transaction_id = transaction_id
        self.ticker_symbol = ticker_symbol
        self.exchange_id = exchange_id
        self.portfolio_id = portfolio_id
        self.order_id = order_id
        self.side = side
        self.matched_quantity = matched_quantity
        self.matched_price = matched_price
        self.matched_timestamp = matched_timestamp
        self.type = type
        self.fee = fee
        self.delivery_date = delivery_date

    @classmethod
    def from_order(cls, order: Order):
        """Create a Transaction object from a fill (submitted order)

        Args:
            order (Order):

        Returns:
            Transaction
        """
        return cls(
            ticker_symbol=order.ticker_symbol,
            exchange_id=order.exchange_id,
            transaction_id=None,
            portfolio_id=order.portfolio_id,
            order_id=order.id,
            side=order.order_side,
            matched_quantity=order.matched_quantity,
            matched_price=order.avg_price,
            matched_timestamp=order.last_modified,
        )

    @staticmethod
    def from_orders(order: Order, updated_order: Order):
        """Create a Transaction object from a fill or partial fill (submitted order)
        FIXME: return a list of transactions

        Args:
            order (order): the original order
            updated_order (Order): the updated order

        Returns:
            [Transaction]
        """
        additional_matched_quantity = (
            updated_order.matched_quantity - order.matched_quantity
        )
        fee = updated_order.accum_fee - order.accum_fee

        if order.is_instructed_execution:
            transactions = []

            # FIXME: handle case partial-fill pair order
            if "list_order_info" not in updated_order.other_info:
                logging.error(
                    "UpdatedOrderError: missing list order info. order: %s, updated order: %s",
                    order.to_basic_dict(),
                    updated_order.to_basic_dict(),
                )
                return [None]

            n = len(updated_order.other_info["list_order_info"])

            for i, updated_sub_order in enumerate(
                updated_order.other_info["list_order_info"]
            ):
                updated_sub_order_value = (
                    updated_sub_order["price"] * updated_order.matched_quantity
                )
                sub_order_value = (
                    0
                    if order.matched_quantity == 0
                    else (
                        order.other_info["list_order_info"][i]["price"]
                        * order.matched_quantity
                    )
                )
                acquired_price = utils.round_decimal(
                    (updated_sub_order_value - sub_order_value)
                    / additional_matched_quantity
                )

                ticker_symbol = updated_sub_order["symbol"]
                transactions.append(
                    Transaction(
                        ticker_symbol=ticker_symbol,
                        exchange_id=order.exchange_id,
                        transaction_id=None,
                        portfolio_id=order.portfolio_id,
                        order_id=order.id,
                        side=OrderSide(updated_sub_order["side"]),
                        matched_quantity=additional_matched_quantity,
                        matched_price=acquired_price,
                        matched_timestamp=updated_order.last_modified,
                        fee=utils.round_decimal(fee / n, precision=6),
                        delivery_date=utils.get_delivery_date(
                            ticker_symbol, updated_order.last_modified
                        ),
                    )
                )
            return transactions

        acquired_price = utils.round_decimal(
            (updated_order.value - order.value) / additional_matched_quantity
        )

        return [
            Transaction(
                ticker_symbol=order.ticker_symbol,
                exchange_id=order.exchange_id,
                transaction_id=None,
                portfolio_id=order.portfolio_id,
                order_id=order.id,
                side=order.order_side,
                matched_quantity=additional_matched_quantity,
                matched_price=acquired_price,
                matched_timestamp=updated_order.last_modified,
                fee=fee,
                delivery_date=utils.get_delivery_date(
                    order.ticker_symbol, updated_order.last_modified
                ),
            )
        ]

    def to_basic_dict(self):
        """Return object in dictionary format of basic data types."""
        basic_dict = deepcopy(vars(self))
        basic_dict["side"] = str(basic_dict["side"])
        basic_dict["matched_price"] = str(basic_dict["matched_price"])
        basic_dict["fee"] = str(basic_dict["fee"])

        if self.delivery_date:
            basic_dict["delivery_date"] = self.delivery_date.isoformat()

        return basic_dict

    @classmethod
    def from_basic_dict(cls, basic_dict: dict):
        """Constructs object from dictionary of basic data types.

        Args:
            basic_dict: the dict that contains transaction information

        Returns:
            Transaction
        """
        return cls(
            ticker_symbol=basic_dict["ticker_symbol"],
            exchange_id=basic_dict["exchange_id"],
            transaction_id=basic_dict["transaction_id"],
            portfolio_id=basic_dict["portfolio_id"],
            order_id=basic_dict["order_id"],
            side=OrderSide(basic_dict["side"]),
            matched_quantity=basic_dict["matched_quantity"],
            matched_price=utils.str_float_to_decimal(basic_dict["matched_price"]),
            matched_timestamp=basic_dict["matched_timestamp"],
            type=basic_dict["type"],
            fee=utils.str_float_to_decimal(basic_dict["fee"]),
            delivery_date=(
                datetime.datetime.fromisoformat(basic_dict["delivery_date"])
                if basic_dict["delivery_date"]
                else None
            ),
        )

    @property
    def id(self) -> Optional[Union[int, str]]:
        """The id of the transaction in integer."""
        return self.transaction_id

    @property
    def value(self) -> Decimal:
        """value of transaction"""
        return self.matched_quantity * self.matched_price

    @property
    def sign(self) -> int:
        """A sign of the Transaction side in integer."""
        return self.side.sign

    @property
    def size(self) -> int:
        """A size of the Transaction in integer."""
        return self.matched_quantity * self.sign

    @property
    def instrument(self) -> Instrument:
        """Return Transaction's instrument"""
        return Instrument.from_id(f"{self.exchange_id}:{self.ticker_symbol}")

    def __eq__(self, other):
        return vars(self) == vars(other)

    def __int__(self):
        """Returns the int representation of the Transaction as matched quantity."""
        return self.matched_quantity

    def __str__(self):
        """Returns the string representation of the Transaction."""
        return (
            f"Transaction ID: {self.transaction_id} - {self.exchange_id}:{self.ticker_symbol}, "
            f"pid: {self.portfolio_id}, {self.side}, {self.matched_quantity}, "
            f"price: {self.matched_price}, {self.matched_timestamp}, "
            f"fee: {self.fee}, "
            f"delivery date: {self.delivery_date}"
        )

    def __repr__(self):
        """Returns the official string representation of the Transaction"""
        return "%r" % self.__dict__

    def set_id(self, transaction_id: int):
        """Set the id into the object"""
        self.transaction_id = transaction_id

    def set_portfolio_id(self, portfolio_id):
        """Set portfolio id for transaction -> for test only"""
        self.portfolio_id = portfolio_id

    def acquisition_value(self, size: Optional[int]) -> Decimal:
        """acquisition value."""
        if size is None:
            size = self.size
        return self.value / self.size * size

    def acquisition_cost(self, size: Optional[int]) -> Decimal:
        """acquisition cost/fee."""
        if size is None:
            size = self.size
        return self.fee / self.size * size
