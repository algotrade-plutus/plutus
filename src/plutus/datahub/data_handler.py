"""Defines the DataHandler (and other variants) to handle data from PriceHubs."""

from dataclasses import dataclass
from threading import Thread
from typing import Callable

import ujson

from plutus.core.instrument import Instrument
from plutus.core.market import InternalDataHubQuote


@dataclass(init=True, repr=True, eq=True)
class DataHandler:
    """A Data handler class to define the data handler function of PriceHub.

    The core is the data_handler_function. Other attributes provide the context
    of how the data_handler_function should be run.

    Attributes:
        # TODO: add more documentation to the function (Callable).
        function (Callable): The function to handle data.
            Input: instrument, price_hub_quote. Return: None.
        subscribed_pattern (str): The pattern which the data handler subscribed to.
        run_in_thread (bool): A flag to indicate that each message should be
            handled by a data handler in separate thread. This should be not
            confused with the run_in_thread of the pubsub of Redis.
            run_in_thread of the pubsub of Redis run each pattern subscriber
            in thread, but the data_handler in each subscriber handles each message sequentially.
        sleep_time (float): The sleep time of the function if needed.
        daemon (bool): Flag to indicate if the thread is a daemon when run in thread.
    """
    data_handler_function: Callable[[Instrument, InternalDataHubQuote], None]
    subscribed_pattern: str
    run_in_thread: bool
    sleep_time: float = 0.001
    daemon: bool = False


@dataclass(init=True, repr=True, eq=True)
class RedisDataHandler(DataHandler):
    """A version of Data Handler class which have a wrapper to handle message from Redis.

    Inherits the attributes from DataHandler class.
    """

    def redis_data_handler(self, redis_sub_msg: dict):
        """A wrappers to preprocess the Redis subscribed message before passing
        into data handler function.

        Args:
            redis_sub_msg (dict): A message sent from the subscribed topic.

        Redis subscribed message is a dictionary which structure is:

        {
            'type' (str): Type of the message (often 'pmessage').
            'pattern' (byte): The pattern which the subscriber subscribe to.
            'channel' (byte): The channel which the message come from.
            'data' (byte): The data sent by the publisher.
        }

        Returns:
            None
        """
        # Parse the message from Redis publisher
        # Get the instrument
        instrument_id = redis_sub_msg['channel'].decode('utf-8')
        instrument = Instrument.from_id(instrument_id)

        # Get the pricehub quote
        price_hub_quote_dict = ujson.loads(redis_sub_msg['data'])
        price_hub_quote = InternalDataHubQuote.from_basic_dict(price_hub_quote_dict)

        # Pass into the data handler function
        if self.run_in_thread:
            thread = Thread(
                target=self.data_handler_function, args=(instrument, price_hub_quote),
                daemon=False
            )
            thread.start()
        else:
            self.data_handler_function(instrument, price_hub_quote)
