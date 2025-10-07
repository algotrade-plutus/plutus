import datetime

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from src.plutus.core.instrument import Instrument


class QuoteInterval(Enum):
    REALTIME = 'REALTIME'
    ONE_MIN = '1_MIN'
    FIVE_MIN = '5_MIN'
    FIFTEEN_MIN = '15_MIN'
    THIRTY_MIN = '30_MIN'
    ONE_HOUR = '1_HOUR'
    ONE_DAY = '1_DAY'


@dataclass(init=True, repr=True, eq=True)
class DataFilter:
    instrument: Instrument
    quote_type: List[str]
    interval: List[str]
    time_spot: Optional[List[datetime.datetime]] = None
