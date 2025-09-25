import aiofiles

from abc import ABC, abstractmethod
from typing import List, Optional

from plutus.data.model.quote import CachedQuote
from src.plutus.data.filter import DataFilter

class AsyncDataHubAbstract(ABC):

    @abstractmethod
    def _prepare(self):
        """Prepares the data source to adhere to the data template.
        - In case of the offline data (files, database, etc.), the data template is applied
        to the source to provide a sequence of correct data points. Data points are feed
        in event-based manner using async-like libraries.
        - In case of the online (streaming) data, the data template provide a set of rules
        to deliver the data points in a correct order and manner, i.e. the correct event
        order and rule specified by the template.
        """
        pass

    @abstractmethod
    def get(self) -> CachedQuote:
        """Returns the next Quote object"""
        pass

class AsyncFileHub(AsyncDataHubAbstract):

    def __init__(
        self,
        file_path: str,
        data_filter: DataFilter
    ):
        self.fp = file_path
        self.data_filter = data_filter
        self.data: Optional[List[CachedQuote]] = None

    def _prepare(self):
        async with aiofiles.open(self.fp, mode='r') as f:
            async for line in f:
                pass


        return self.data

    def get(self) -> CachedQuote:
        pass
