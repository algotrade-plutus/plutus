"""RedisPriceHub is one of the basic implementation and widely used of PriceHub
concept in the system.

This module defines and provides methods to access to price data stored in Redis.
"""

import logging
import ujson
from typing import Tuple, Callable, Optional, List

import redis

from plutus.core.instrument import Instrument
from plutus.core.market import CachedQuote
from plutus.datahub.datahub import DataHub, InternalDataHubQuote
from plutus.datahub.data_handler import RedisDataHandler


class RedisDataHub(DataHub):
    """Implementation of PriceHub concept using Redis.

    Market information such as prices, volumes, bids, asks of instruments are
    stored in Redis in key-value manner. Processes can access market information
    in a consistence manner.

    Attributes:
        redis_host (str): A string specifies the Redis server address.
        redis_port (int): A integer specifies the Redis server port.
    """

    def __init__(
        self,
        redis_host: str,
        redis_port: int,
        redis_password: str,
    ):
        """Initializes the RedisPriceHub object"""
        super().__init__()
        self.redis_data_hub = redis.StrictRedis(
            host=redis_host,
            port=redis_port,
            password=redis_password
        )
        self.data_handler_list: List[RedisDataHandler] = []

    # --------------------------------------------------------------------------
    # Operation functions:
    # - start_pubsub
    # --------------------------------------------------------------------------
    def start_pubsub(self):
        """Starts the Pricehub Pubsub function.

        Returns:
            None
        """
        for redis_data_handler in self.data_handler_list:
            pub_sub = self.redis_data_hub.pubsub()

            # Remember to use redis_data_handler NOT data_handler_function
            pub_sub.psubscribe(**{
                redis_data_handler.subscribed_pattern: redis_data_handler.redis_data_handler
            })
            pub_sub.run_in_thread(
                sleep_time=redis_data_handler.sleep_time,
                daemon=redis_data_handler.daemon
            )

    # --------------------------------------------------------------------------
    # APIs:
    # - get_latest_quote
    # - set_data_handler
    # --------------------------------------------------------------------------
    def _get_latest_quote(
        self,
        instrument: Instrument
    ) -> Optional[CachedQuote]:
        """Returns the latest market information of the instrument.

        Args:
            instrument (Instrument): An Instrument of interest.

        Returns:
            The CachedQuote object if available. Otherwise, None.
        """
        message = self.redis_data_hub.get(instrument.id)

        if message is None:
            return None

        try:
            data = ujson.loads(message)

            # TODO: check data structure of redis message
            if type(data) is not dict:
                logging.warning('InvalidCachedQuoteDataStructure: %s', data)
                return None

            return CachedQuote.from_basic_dict(data)

        except ujson.JSONDecodeError:
            logging.error('JSONDecodeError: %s', message)

    def set_data_handler(
        self,
        data_handler: Callable[[Instrument, InternalDataHubQuote], None],
        instrument_id_pattern: str,
        run_in_thread: bool,
        sleep_time: float = 0.001,
        daemon: bool = False
    ) -> Tuple[bool, str]:
        """Sets the data handler to handle the message from redis.

        Data handler holds the logic that process the market information from Redis.

        Args:
            data_handler (Callable): The callback function that need to process that message.
            instrument_id_pattern (str): A Redis topic that produces the messages.
            run_in_thread (bool): A flag to indicate that each message should be
                handled by a data handler in separate thread. This should be not
                confused with the run_in_thread of the pubsub of Redis.
                run_in_thread of the pubsub of Redis run each pattern subscriber
                in thread, but the data_handler in each subscriber handles each message sequentially.
            sleep_time (float): The sleep time of the data handler if needed.
            daemon (bool): Run thread as a Daemon or not.

        Returns:
            A tuple consists of a boolean and a message:
            A tuple of (True, empty string) if set successfully.
            A tuple of (False, error message) if set failed.
        """
        # TODO: Are there any cases that this function fails?
        self.data_handler_list.append(
            RedisDataHandler(
                data_handler_function=data_handler,
                subscribed_pattern=instrument_id_pattern,
                run_in_thread=run_in_thread,
                sleep_time=sleep_time,
                daemon=daemon
            )
        )

        return True, ''
