"""An auction-aware daily source, so ATO/ATC orders reach an auction fill.

:class:`~plutus.market.adapters.datahub.DataHubSource` stamps every daily bar
``SessionPhase.CONTINUOUS`` on purpose: a daily bar's timestamp is midnight, so
inferring the phase from *it* would mark every bar pre-open. But the session
does not ask for the bar at midnight -- it asks for the interval at the instant
it has advanced to, and *that* instant is a real intraday time the dated
schedule can name. This subclass reads the phase off the interval's ``start``
(the advance instant), and wires the published **open** (``quote_open``, on disk
but deliberately unwired in the base source so it cannot move continuous-fill
decisions). Together they let an ATO cross at the published open and an ATC at
the published close, through the ordinary session path.

Everything the base source does is unchanged; this only overrides
:meth:`interval` to re-stamp the phase and attach the open. It is opt-in: a
strategy that wants auctions constructs this source and hands it to
``ExchangeSession.from_config(..., source=...)``. The rest of the suite keeps the
base source and is untouched.

The ``phase_for`` callable is injected rather than importing the rulebook here,
so the adapter stays decoupled from rule resolution; a caller supplies
``lambda ts: Rulebook().at(ts).phase(venue)``.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Callable, Optional, Union

from plutus.datahub.config import DataHubConfig
from plutus.market.adapters.datahub import DataHubSource
from plutus.market.protocol import Resolution, SessionPhase
from plutus.market.session.types import DataField, MarketInterval

PhaseFor = Callable[[datetime], SessionPhase]


class AuctionAwareDataHubSource(DataHubSource):
    """A :class:`DataHubSource` that names the intraday auction phase and serves
    the published open, so ATO/ATC orders cross through the session path.
    """

    def __init__(self, config: Union[DataHubConfig, str], *,
                 phase_for: PhaseFor) -> None:
        super().__init__(config)
        self._phase_for = phase_for

    @classmethod
    def for_root(cls, data_root: str, *, phase_for: PhaseFor
                 ) -> "AuctionAwareDataHubSource":
        return cls(DataHubConfig(data_root=data_root), phase_for=phase_for)

    def state_at(self, ticker: str, ts: datetime):
        """The base state, re-stamped with the phase at ``ts``.

        Admission reads the phase off the *state* at submit time
        (``exchange.py`` ``_phase(venue, observed=state.session)``), so the
        state has to carry the auction phase too, or an ATO/ATC would be
        refused as illegal-in-continuous before it ever reached a fill.
        """
        base = super().state_at(ticker, ts)
        if base is None:
            return None
        ts_dt = ts if isinstance(ts, datetime) else datetime(ts.year, ts.month, ts.day)
        return replace(base, session=self._phase_for(ts_dt))

    def interval(self, ticker: str, start: datetime, end: datetime, *,
                 resolution: Resolution = Resolution.DAILY
                 ) -> Optional[MarketInterval]:
        """The base daily bar, re-stamped with the phase at ``start`` and
        carrying the published open. ``None`` when the day is absent, exactly as
        the base source; a non-daily resolution still raises there.
        """
        base = super().interval(ticker, start, end, resolution=resolution)
        if base is None:
            return None
        start_dt = (start if isinstance(start, datetime)
                    else datetime(start.year, start.month, start.day))
        phase = self._phase_for(start_dt)
        open_px = self._open_at(ticker, start_dt)
        missing = set(base.missing)
        if open_px is not None:
            missing.discard(DataField.OPEN)
        return replace(
            base,
            state=replace(base.state, session=phase),
            open=open_px,
            missing=frozenset(missing),
        )

    def _open_at(self, ticker: str, ts: datetime) -> Optional[Decimal]:
        """The day's published open for ``ticker``, or ``None`` if absent.

        Read directly, not through the base source's ``_fetch`` -- wiring the
        open into that shared path would change limit-fill decisions for every
        strategy, which the base source's docstring defers on purpose. Here it
        rides only on the auction interval.
        """
        reader = self._reader('open_price')
        if reader is None:
            return None
        day = ts.date() if isinstance(ts, datetime) else ts
        rows = self._conn.execute(
            f"SELECT price FROM {reader} "
            f"WHERE tickersymbol = ? AND datetime >= ? AND datetime < ? "
            f"ORDER BY datetime LIMIT 1",
            [ticker, str(day)[:10], str(day + timedelta(days=1))[:10]],
        ).fetchall()
        return None if not rows else Decimal(str(rows[0][0]))
