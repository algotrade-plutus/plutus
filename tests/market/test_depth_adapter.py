"""The depth adapter: a reconstructed book that reports its own staleness.

Two tiers, deliberately.

The **synthetic** tier builds three-row Parquet tables in ``tmp_path`` and runs
unconditionally. Every reconstruction invariant that could be got wrong -- the
per-level as-of join, the refusal to equality-join the two sides, ABSENT vs
empty, the day boundary, ladder gaps, the age arithmetic -- is pinned there,
so the contract is defended on a machine with no corpus. Each synthetic table
is a hand-written change stream shaped like the real one, including the
``{2,3}``-with-no-level-1 update that the extract actually contains.

The **measured** tier runs against ``hermes-dev-extract`` and pins the numbers
this adapter's docstring claims. It skips where the extract is absent. These
are the tests that would catch the extract changing under us, which the
synthetic tier cannot.

``tests/market/conftest.py`` resolves the daily corpus and the raw tick
archive; the dev extract is a third root and is resolved here rather than
there, because this module is the only thing that reads it.
"""

import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from plutus.core.order import Side
from plutus.market.adapters.depth import (
    MAX_DEPTH, DepthBook, DepthLevel, DepthSide, DepthSource, SideAvailability,
    Truncation,
)
from plutus.market.protocol import OrderBook, Resolution
from plutus.market.session.types import DataField

# --------------------------------------------------------------------------
# Roots
# --------------------------------------------------------------------------

_EXTRACT_DEFAULT = Path('/Users/nadan/algotrade-research/dataset/hermes-dev-extract')


def _extract_root():
    env = os.environ.get('PLUTUS_DEPTH_ROOT')
    for root in ([Path(env)] if env else []) + [_EXTRACT_DEFAULT]:
        if (root / 'local_quote_bidprice.parquet').exists():
            return root
    return None


EXTRACT = _extract_root()

requires_extract = pytest.mark.skipif(
    EXTRACT is None,
    reason='No depth extract found; set PLUTUS_DEPTH_ROOT.',
)

DAY = date(2022, 11, 9)


@pytest.fixture(scope='module')
def local():
    if EXTRACT is None:
        pytest.skip('needs the dev extract')
    return DepthSource(str(EXTRACT), table_prefix='local_quote')


@pytest.fixture(scope='module')
def remote():
    if EXTRACT is None:
        pytest.skip('needs the dev extract')
    return DepthSource(str(EXTRACT), table_prefix='quote')


# --------------------------------------------------------------------------
# A synthetic extract, so the invariants hold with no corpus present
# --------------------------------------------------------------------------

def _write(conn, path, rows, column):
    """One change-stream table: ``(datetime, tickersymbol, <column>, depth)``."""
    if rows:
        values = ',\n'.join(
            f"(TIMESTAMP '{ts}', '{tk}', {value}, {depth})"
            for ts, tk, value, depth in rows)
        select = (f"SELECT * FROM (VALUES {values}) "
                  f"AS t(datetime, tickersymbol, {column}, depth)")
    else:
        select = (f"SELECT NULL::TIMESTAMP AS datetime, "
                  f"NULL::VARCHAR AS tickersymbol, "
                  f"NULL::{'DECIMAL(20,6)' if column == 'price' else 'BIGINT'} "
                  f"AS {column}, NULL::BIGINT AS depth WHERE FALSE")
    conn.execute(f"COPY ({select}) TO '{path}' (FORMAT PARQUET)")


@pytest.fixture
def toy(tmp_path):
    """A hand-built extract with the awkward shapes the real one has.

    ``TOY`` on 2022-11-09, prefix ``local_quote``:

    * bid prices: level 1 at 09:00:00, levels 1-3 at 09:00:10, then **level 1
      alone** at 09:05:00 -- the shape that breaks a per-instant snapshot read.
    * bid sizes: on their own clock, including a level-2-only tick at
      09:07:00, which is what makes one side's levels differ in age.
    * ask prices: first update at 09:02:00 is ``{2,3}`` with no level 1 -- a
      real ladder gap, copied from HPG's 09:00:08 open. Level 1 arrives at
      09:03:00.
    * ask sizes: none at all -- the HTV-in-``quote`` shape, prices without
      depth.
    * No bid or ask instant coincides with any instant on the other side, so
      an equality join would return nothing.
    """
    conn = duckdb.connect()
    tk = 'TOY'
    _write(conn, tmp_path / 'local_quote_bidprice.parquet', [
        ('2022-11-09 09:00:00', tk, '20.00', 1),
        ('2022-11-09 09:00:10', tk, '20.10', 1),
        ('2022-11-09 09:00:10', tk, '20.00', 2),
        ('2022-11-09 09:00:10', tk, '19.90', 3),
        ('2022-11-09 09:05:00', tk, '20.20', 1),
        ('2022-11-10 09:00:00', tk, '25.00', 1),
    ], 'price')
    _write(conn, tmp_path / 'local_quote_bidsize.parquet', [
        ('2022-11-09 09:00:00', tk, 100, 1),
        ('2022-11-09 09:00:10', tk, 200, 1),
        ('2022-11-09 09:00:10', tk, 300, 2),
        ('2022-11-09 09:00:10', tk, 400, 3),
        ('2022-11-09 09:07:00', tk, 500, 2),
    ], 'quantity')
    _write(conn, tmp_path / 'local_quote_askprice.parquet', [
        ('2022-11-09 09:02:00', tk, '20.40', 2),
        ('2022-11-09 09:02:00', tk, '20.50', 3),
        ('2022-11-09 09:03:00', tk, '20.30', 1),
    ], 'price')
    _write(conn, tmp_path / 'local_quote_asksize.parquet', [], 'quantity')
    conn.close()
    return DepthSource(tmp_path, table_prefix='local_quote')


AT_0901 = datetime(2022, 11, 9, 9, 1)
AT_0910 = datetime(2022, 11, 9, 9, 10)


# -- requirement 1: reconstruct a book as of an instant ---------------------

def test_a_level_only_update_does_not_delete_the_levels_behind_it(toy):
    """The core of the design, and what a per-instant read gets wrong.

    At 09:05:00 only level 1 changed. Read the *latest instant's rows* and the
    ladder is one level deep; read the latest row **per level** and it is three
    deep with a new touch. The extract has 15,719 such bid-size instants for
    FPT alone, so this is the common case, not the corner.
    """
    book = toy.book_at('TOY', AT_0910)
    assert [level.price for level in book.bid.levels] == [
        Decimal('20.20'), Decimal('20.00'), Decimal('19.90')]
    assert book.bid.levels[0].price_as_of == datetime(2022, 11, 9, 9, 5)
    assert book.bid.levels[1].price_as_of == datetime(2022, 11, 9, 9, 0, 10)


def test_the_two_sides_are_not_equality_joined(toy):
    """No instant in the toy bid stream appears in the ask stream, and no
    instant in the real one is guaranteed to: measured, 53 of 203 coincide on
    FPT 2022-11-09. An equality join returns an empty book here."""
    book = toy.book_at('TOY', AT_0910)
    assert book.is_two_sided
    assert book.bid.as_of == datetime(2022, 11, 9, 9, 7)    # a size tick
    assert book.ask.as_of == datetime(2022, 11, 9, 9, 3)    # a price tick
    assert book.cross_side_skew == timedelta(minutes=4)


def test_forward_fill_stops_at_the_day_boundary(toy):
    """HSX cancels unfilled orders at the close, so yesterday's ladder is not
    evidence about today's 09:00 book. The toy has a bid at 2022-11-10
    09:00:00 and nothing before it that day."""
    before = toy.book_at('TOY', datetime(2022, 11, 10, 8, 59, 59))
    assert before.bid.availability is SideAvailability.ABSENT
    after = toy.book_at('TOY', datetime(2022, 11, 10, 9, 0, 0))
    assert after.bid.best.price == Decimal('25.00')


def test_a_ladder_is_never_deeper_than_the_corpus(toy, local):
    assert MAX_DEPTH == 3
    for source, ticker, ts in ((toy, 'TOY', AT_0910),
                               (local, 'FPT', datetime(2022, 11, 9, 10, 30))):
        book = source.book_at(ticker, ts)
        assert len(book.bid.levels) <= MAX_DEPTH
        assert len(book.ask.levels) <= MAX_DEPTH
        assert [l.depth for l in book.bid.levels] == list(
            range(1, len(book.bid.levels) + 1))


def test_max_depth_beyond_the_corpus_is_refused():
    with pytest.raises(ValueError, match='max_depth'):
        DepthSource('/nowhere', max_depth=4)


# -- requirement 2: report the staleness of what is returned ----------------

def test_every_level_carries_the_age_of_both_of_its_numbers(toy):
    """A level is two observations from two tables, and one ``as_of`` for the
    pair would be a lie about one of them."""
    book = toy.book_at('TOY', AT_0910)
    level = book.bid.levels[1]
    assert level.price_as_of == datetime(2022, 11, 9, 9, 0, 10)
    assert level.size_as_of == datetime(2022, 11, 9, 9, 7)
    assert level.price_age == timedelta(minutes=9, seconds=50)
    assert level.size_age == timedelta(minutes=3)


def test_a_levels_age_is_the_older_of_its_two_observations(toy):
    """Restrictive by construction: a fresh price on a stale size is a stale
    level, because a sweep consumes the size."""
    book = toy.book_at('TOY', AT_0910)
    touch = book.bid.levels[0]
    assert touch.price_age == timedelta(minutes=5)
    assert touch.size_age == timedelta(minutes=9, seconds=50)
    assert touch.age == timedelta(minutes=9, seconds=50)


def test_a_side_is_as_old_as_its_oldest_ingredient(toy):
    """``as_of`` is the freshest and ``age`` the oldest, and the gap between
    them is the point: a 5-minute touch in front of a 9m50s level 3 is a
    normal shape in this corpus and a caller has to see both."""
    side = toy.book_at('TOY', AT_0910).bid
    assert side.as_of == datetime(2022, 11, 9, 9, 7)
    assert side.oldest_as_of == datetime(2022, 11, 9, 9, 0, 10)
    assert side.freshest_age == timedelta(minutes=3)
    assert side.age == timedelta(minutes=9, seconds=50)
    assert side.age >= side.freshest_age


def test_cross_side_skew_is_reported_on_every_two_sided_book(toy):
    """The brief's "a bid quoted 4 seconds ago and an ask quoted 40 seconds
    ago is a weaker object" -- made a number."""
    book = toy.book_at('TOY', AT_0910)
    assert book.cross_side_skew == abs(book.bid.as_of - book.ask.as_of)
    assert book.cross_side_skew >= timedelta(0)


def test_skew_is_none_when_a_side_was_never_observed(toy):
    """Not zero. Zero would read as "both sides current"."""
    book = toy.book_at('TOY', AT_0901)
    assert book.ask.availability is SideAvailability.ABSENT
    assert book.cross_side_skew is None
    assert book.spread is None


def test_a_stale_price_paired_with_a_newer_size_is_flagged(toy):
    """Measured property 4: 2.28 % of FPT bid-price rows and 18.97 % of HTV's
    have no size row at the same instant, so the previous price's size stays
    attached. Undetectable row by row; flagged by the age ordering."""
    book = toy.book_at('TOY', AT_0910)
    assert book.bid.levels[1].sizes_lag_price is False
    assert book.bid.levels[2].sizes_lag_price is False
    # level 1's price moved at 09:05 with no size row: the 09:00:10 size rides.
    assert book.bid.levels[0].size_as_of < book.bid.levels[0].price_as_of
    assert book.bid.levels[0].sizes_lag_price is True


def test_max_age_drops_stale_levels_outward_and_says_why(toy):
    """Dropping depth is the restrictive direction -- a sweep runs out sooner
    and returns INDETERMINATE, which costs an opportunity, not money."""
    book = toy.book_at('TOY', AT_0910, max_age=timedelta(minutes=5))
    assert book.bid.levels == ()
    assert book.bid.availability is SideAvailability.ABSENT
    assert book.bid.truncation is Truncation.MAX_AGE
    assert book.bid.truncated_at_depth == 1
    assert book.bid.observed_depths == (1, 2, 3)


def test_max_age_generous_enough_keeps_the_whole_ladder(toy):
    book = toy.book_at('TOY', AT_0910, max_age=timedelta(minutes=30))
    assert len(book.bid.levels) == 3
    assert book.bid.truncation is Truncation.NONE


def test_a_negative_max_age_is_refused(toy):
    with pytest.raises(ValueError, match='non-negative'):
        toy.book_at('TOY', AT_0910, max_age=timedelta(seconds=-1))


# -- requirement 3: serve depth honestly ------------------------------------

def test_an_absent_side_is_not_an_empty_one(toy):
    """The requirement in one assertion. Both states have no levels; only one
    of them is a claim about the market, and the type must keep them apart."""
    absent = toy.book_at('TOY', AT_0901).ask
    assert absent.availability is SideAvailability.ABSENT
    assert absent.levels == ()
    assert absent.total_size is None
    assert absent.availability is not SideAvailability.EMPTY


def test_this_source_never_claims_a_book_is_empty(toy, local):
    """EMPTY is declared and unreachable: the corpus carries no deletion
    record, so "nobody is resting" is a fact it cannot express. Returning it
    would be an overclaim."""
    books = [toy.book_at('TOY', AT_0901), toy.book_at('TOY', AT_0910)]
    if EXTRACT is not None:
        books += list(local.books('HTV', datetime(2022, 11, 9),
                                  datetime(2022, 11, 10)))
    for book in books:
        assert book.bid.availability is not SideAvailability.EMPTY
        assert book.ask.availability is not SideAvailability.EMPTY


def test_observed_is_exactly_the_state_with_a_touch(toy):
    """The invariant a caller may rely on, enforced in ``__post_init__`` so it
    cannot be constructed away."""
    with pytest.raises(ValueError, match='invariant'):
        DepthSide(side=Side.BUY, availability=SideAvailability.OBSERVED)
    with pytest.raises(ValueError, match='invariant'):
        DepthSide(
            side=Side.BUY, availability=SideAvailability.ABSENT,
            levels=(DepthLevel(depth=1, price=Decimal('1'), size=1,
                               price_as_of=AT_0901, size_as_of=AT_0901,
                               ts=AT_0901),))


def test_a_ladder_gap_refuses_the_side_rather_than_promoting_level_two(toy):
    """The toy's ask opens ``{2,3}`` with no level 1, exactly as HPG's does at
    09:00:08. Serving 20.40 as the touch would report a book nobody quoted."""
    book = toy.book_at('TOY', datetime(2022, 11, 9, 9, 2, 30))
    assert book.ask.availability is SideAvailability.ABSENT
    assert book.ask.truncation is Truncation.LADDER_GAP
    assert book.ask.observed_depths == (2, 3)
    assert book.ask.truncated_at_depth == 1
    assert book.ask.levels == ()


def test_a_shallow_ladder_is_not_called_a_gap(toy):
    """Two levels quoted and nothing deeper is the corpus being quiet, not a
    hole. The two need separate counts."""
    book = toy.book_at('TOY', datetime(2022, 11, 9, 9, 0, 5))
    assert book.bid.availability is SideAvailability.OBSERVED
    assert len(book.bid.levels) == 1
    assert book.bid.truncation is Truncation.NO_OBSERVATION
    assert book.bid.observed_depths == (1,)


def test_an_unsized_level_is_none_and_never_zero(toy):
    """A zero would be a definite no-fill. The extract holds no zero-quantity
    row at all -- minimum 100 in ``local_quote``, 1 in ``quote``."""
    book = toy.book_at('TOY', AT_0910)
    assert book.ask.levels
    assert all(level.size is None for level in book.ask.levels)
    assert book.ask.has_sizes is False
    assert book.ask.total_size is None


def test_total_size_refuses_a_partial_sum(toy):
    """A ladder sized at the touch and unsized behind it cannot be swept past
    the touch, so a partial sum is a number nobody measured."""
    book = toy.book_at('TOY', AT_0910)
    assert book.bid.total_size == 200 + 500 + 400
    assert book.ask.total_size is None


def test_a_book_is_returned_even_where_nothing_can_be_answered(toy):
    """``None`` would collapse "no ask yet", "no sizes here" and "wrong
    ticker" into one silence."""
    book = toy.book_at('NOSUCH', AT_0910)
    assert isinstance(book, DepthBook)
    assert book.bid.availability is SideAvailability.UNSERVED
    assert book.ask.availability is SideAvailability.UNSERVED
    assert DataField.BOOK in book.withheld


def test_out_of_window_is_not_the_same_as_absent(toy):
    """A coverage error must not hide behind a plausible market state."""
    assert (toy.book_at('TOY', datetime(2023, 6, 1, 10, 0)).bid.availability
            is SideAvailability.OUT_OF_WINDOW)
    assert (toy.book_at('TOY', AT_0901).ask.availability
            is SideAvailability.ABSENT)


# -- requirement 4: declare the contract, stamp it on every book -------------

def test_the_contract_is_declared_like_datahubs(toy):
    assert DepthSource.SERVES == frozenset({DataField.BOOK,
                                            DataField.BOOK_SIZE})
    assert DataField.BOOK_SIZE not in DepthSource.WITHHELD
    for field_ in (DataField.LAST, DataField.CEILING, DataField.FLOOR,
                   DataField.VOLUME, DataField.SESSION_PHASE,
                   DataField.SETTLEMENT_PRICE):
        assert field_ in DepthSource.WITHHELD
    assert not (DepthSource.SERVES & DepthSource.WITHHELD)


def test_withheld_is_stamped_on_every_book(toy):
    for ts in (AT_0901, AT_0910, datetime(2022, 11, 9, 9, 2, 30)):
        book = toy.book_at('TOY', ts)
        assert DepthSource.WITHHELD <= book.withheld


def test_book_size_is_named_per_book_not_per_source(toy, local):
    """The ``VOLUME`` pattern from ``DataHubSource``: served where the rows
    exist, named where they do not. A class-level WITHHELD could not tell "this
    source never has sizes" from "this window does not"."""
    assert DataField.BOOK_SIZE in toy.book_at('TOY', AT_0910).withheld
    if EXTRACT is not None:
        sized = local.book_at('FPT', datetime(2022, 11, 9, 10, 30))
        assert DataField.BOOK_SIZE not in sized.withheld


def test_missing_for_names_only_the_side_an_aggressor_needs(toy):
    """A BUY sweeps the asks. A book with an ABSENT bid is a perfectly good
    book to buy into, and naming BOOK missing for it would manufacture an
    INDETERMINATE the data does not require."""
    book = toy.book_at('TOY', AT_0901)   # ask ABSENT, bid OBSERVED and sized
    assert DataField.BOOK in book.missing_for(Side.BUY)
    assert DataField.BOOK not in book.missing_for(Side.SELL)
    assert DataField.BOOK_SIZE not in book.missing_for(Side.SELL)


def test_missing_for_names_book_size_when_the_resting_side_is_unsized(toy):
    book = toy.book_at('TOY', AT_0910)   # asks have prices, no sizes
    assert DataField.BOOK_SIZE in book.missing_for(Side.BUY)
    assert DataField.BOOK not in book.missing_for(Side.BUY)
    assert DataField.BOOK_SIZE not in book.missing_for(Side.SELL)


def test_a_cross_aggressor_has_no_resting_side(toy):
    with pytest.raises(ValueError, match='one-sided'):
        toy.book_at('TOY', AT_0910).resting_side_for(Side.CROSS)


def test_coverage_answers_before_a_run_starts(toy):
    cov = toy.coverage('TOY', DAY)
    assert cov.serves_prices and cov.serves_depth
    assert cov.bid_size_rows == 5 and cov.ask_size_rows == 0
    assert cov.ticker_in_source
    assert DataField.BOOK not in cov.withheld
    absent = toy.coverage('TOY', date(2023, 6, 1))
    assert not absent.serves_prices and not absent.serves_depth
    assert DataField.BOOK in absent.withheld
    assert DataField.BOOK_SIZE in absent.withheld


def test_the_source_records_which_observer_it_read(toy):
    """``local_quote_*`` and ``quote_*`` both hold HTV Nov 2022 with different
    lineage and different size coverage. A book that did not say which one it
    came from could not be reproduced."""
    assert toy.book_at('TOY', AT_0910).table_prefix == 'local_quote'


# -- requirement 5: declared resolutions -------------------------------------

def test_resolutions_are_declared_and_enforced(toy):
    assert DepthSource.SERVES_RESOLUTIONS == frozenset({Resolution.TICK})
    assert Resolution.DAILY not in DepthSource.SERVES_RESOLUTIONS
    assert toy.book_at('TOY', AT_0910).resolution is Resolution.TICK
    with pytest.raises(ValueError, match='instant'):
        toy.book_at('TOY', AT_0910, resolution=Resolution.DAILY)


# -- the bridge to protocol.OrderBook ---------------------------------------

def test_to_order_book_collapses_to_the_oldest_observation(toy):
    """``OrderBook`` has one ``as_of`` and this book has up to twelve
    observations behind it. Stamping ``ts`` would assert a currency nothing
    supports; the oldest ingredient is the true, restrictive collapse."""
    book = toy.book_at('TOY', AT_0910)
    order_book = book.to_order_book()
    assert isinstance(order_book, OrderBook)
    assert order_book.as_of == min(book.bid.oldest_as_of, book.ask.oldest_as_of)
    assert order_book.as_of < book.ts
    assert [l.price for l in order_book.bids] == [
        l.price for l in book.bid.levels]


def test_to_order_book_is_lossy_in_the_way_the_docstring_says(toy):
    """An ABSENT side and an empty one both become ``()`` here, which is the
    whole reason DepthBook exists as a separate type."""
    absent = toy.book_at('TOY', AT_0901).to_order_book()
    assert absent.asks == ()
    assert not hasattr(absent, 'availability')


# -- iteration ---------------------------------------------------------------

def test_instants_are_the_union_of_every_change_on_either_side(toy):
    got = toy.instants('TOY', datetime(2022, 11, 9), datetime(2022, 11, 10))
    assert got == [
        datetime(2022, 11, 9, 9, 0, 0),
        datetime(2022, 11, 9, 9, 0, 10),
        datetime(2022, 11, 9, 9, 2, 0),
        datetime(2022, 11, 9, 9, 3, 0),
        datetime(2022, 11, 9, 9, 5, 0),
        datetime(2022, 11, 9, 9, 7, 0),
    ]
    assert datetime(2022, 11, 10, 9, 0) not in got   # end is exclusive


def test_books_walks_the_event_clock(toy):
    books = list(toy.books('TOY', datetime(2022, 11, 9), datetime(2022, 11, 10)))
    assert [b.ts for b in books] == toy.instants(
        'TOY', datetime(2022, 11, 9), datetime(2022, 11, 10))
    assert all(b.ticker == 'TOY' for b in books)


def test_an_inverted_window_is_refused(toy):
    with pytest.raises(ValueError, match='empty or inverted'):
        toy.instants('TOY', datetime(2022, 11, 10), datetime(2022, 11, 9))


# --------------------------------------------------------------------------
# Measured against the extract
# --------------------------------------------------------------------------

@requires_extract
def test_the_two_sides_of_fpt_do_not_share_timestamps(local):
    """The brief's structural fact, re-measured through this adapter: 53 of
    203 bid-price instants have an ask-price instant at the same microsecond,
    so a full two-sided book is never observed."""
    conn = duckdb.connect()

    def instants(table):
        return {row[0] for row in conn.execute(
            f"SELECT DISTINCT datetime FROM "
            f"read_parquet('{EXTRACT}/{table}.parquet') "
            f"WHERE tickersymbol = 'FPT' AND datetime::DATE = '2022-11-09'"
        ).fetchall()}

    bids = instants('local_quote_bidprice')
    asks = instants('local_quote_askprice')
    assert len(bids) == 203
    assert len(bids & asks) == 53


@requires_extract
def test_size_updates_outnumber_price_updates(local):
    """Size moves without price moving -- 848 bid-size instants against 203
    bid-price instants -- which is why a level's two numbers need two ages."""
    cov = local.coverage('FPT', DAY)
    assert cov.bid_price_rows == 578
    assert cov.bid_size_rows == 1244
    assert cov.ask_size_rows == 2497


@requires_extract
def test_one_fpt_book_has_three_ages_on_one_side(local):
    """The worked instance from the module docstring. Three bid prices from a
    single instant 182 s back, three sizes from two later instants -- a single
    ``as_of`` per side could not have said this."""
    book = local.book_at('FPT', datetime(2022, 11, 9, 10, 30))
    assert len(book.bid.levels) == 3
    assert len({l.price_as_of for l in book.bid.levels}) == 1
    assert len({l.size_as_of for l in book.bid.levels}) == 2
    assert book.bid.age > book.bid.freshest_age
    assert [l.size for l in book.bid.levels] == [1200, 1300, 6400]


@requires_extract
def test_htv_has_41_bid_size_rows_on_the_ninth(local):
    """The brief's coverage warning, checkable rather than remembered. HTV is
    servable that day -- but 31 books for a whole session, not 2,795."""
    cov = local.coverage('HTV', DAY)
    assert cov.bid_size_rows == 41
    assert cov.ask_size_rows == 20
    assert cov.serves_depth
    books = list(local.books('HTV', datetime(2022, 11, 9),
                             datetime(2022, 11, 10)))
    assert len(books) == 31


@requires_extract
def test_htv_in_the_remote_root_has_prices_and_no_depth_at_all(remote):
    """The requirement's other half: a source that cannot serve depth says so
    rather than serving an empty ladder that reads as "no liquidity".
    ``quote_bidsize`` holds no HTV row, at any date."""
    cov = remote.coverage('HTV', DAY)
    assert cov.serves_prices
    assert not cov.serves_depth
    assert cov.bid_size_rows == 0 and cov.ask_size_rows == 0
    assert DataField.BOOK_SIZE in cov.withheld
    assert DataField.BOOK not in cov.withheld

    book = remote.book_at('HTV', datetime(2022, 11, 9, 10, 0))
    assert book.bid.availability is SideAvailability.OBSERVED
    assert book.bid.levels
    assert all(level.size is None for level in book.bid.levels)
    assert DataField.BOOK_SIZE in book.withheld
    assert DataField.BOOK_SIZE in book.missing_for(Side.SELL)


@requires_extract
def test_the_same_ticker_day_differs_between_the_two_observers(local, remote):
    """Why one source reads one prefix. Same 40 bid-price rows, sizes in one
    root and not the other, timestamps microseconds apart. Merging them would
    invent a lineage no row carries."""
    mine, theirs = local.coverage('HTV', DAY), remote.coverage('HTV', DAY)
    assert mine.bid_price_rows == theirs.bid_price_rows == 40
    assert mine.serves_depth and not theirs.serves_depth
    assert mine.first_ts != theirs.first_ts


@requires_extract
def test_a_ticker_outside_the_prefix_is_unserved_not_absent(local):
    """VN30F2504 is in ``quote_*`` and not in ``local_quote_*``. Reporting it
    as "the market had not quoted yet" would hide a misconfigured run."""
    assert 'VN30F2504' not in local.tickers()
    book = local.book_at('VN30F2504', datetime(2025, 4, 2, 10, 0))
    assert book.bid.availability is SideAvailability.UNSERVED
    assert book.ask.availability is SideAvailability.UNSERVED
    assert DataField.BOOK in book.withheld


@requires_extract
def test_hpg_opens_with_a_real_ladder_gap(local):
    """Measured: 149 of HPG's 11,988 books on 2022-11-09 have ask levels 2 and
    3 known with no touch, all in the first seconds of the session. The first
    ask price update of the day is ``{2,3}``."""
    gaps = [b for b in local.books('HPG', datetime(2022, 11, 9),
                                   datetime(2022, 11, 9, 9, 5))
            if b.ask.truncation is Truncation.LADDER_GAP]
    assert gaps
    first = gaps[0]
    assert first.ask.availability is SideAvailability.ABSENT
    assert first.ask.observed_depths == (2, 3)
    assert first.ask.levels == ()


@requires_extract
def test_the_reconstruction_almost_never_crosses_in_the_continuous_session(local):
    """The quality claim, measured. An as-of join per side can produce a bid
    above an ask -- an arbitrage that never existed -- and the rate is the
    honest measure of how much the skew costs. FPT 2022-11-09: zero crossed
    books out of 2,795."""
    books = list(local.books('FPT', datetime(2022, 11, 9),
                             datetime(2022, 11, 10)))
    assert len(books) == 2795
    assert sum(b.is_crossed for b in books) == 0
    assert sum(b.is_touching for b in books) == 2
    assert all(b.is_two_sided for b in books)


@requires_extract
def test_crossed_books_are_flagged_rather_than_swept(remote):
    """VN30F2504 2025-04-02 produces one crossed book in 6,790 two-sided ones.
    It is not filtered out -- suppressing it would hide the reconstruction's
    error rate -- it is flagged, so a sweep can refuse it."""
    crossed = [b for b in remote.books('VN30F2504', datetime(2025, 4, 2),
                                       datetime(2025, 4, 3))
               if b.is_crossed]
    assert len(crossed) == 1
    book = crossed[0]
    assert book.bid.best.price > book.ask.best.price
    assert not book.is_reconstructable
    assert book.spread < 0


@requires_extract
def test_where_sizes_exist_they_exist_at_every_served_level(local):
    """All-or-nothing, measured: across every two-sided book FPT served that
    day, none has a level with a price and no size."""
    for book in local.books('FPT', datetime(2022, 11, 9), datetime(2022, 11, 10)):
        for side in (book.bid, book.ask):
            if side.availability is SideAvailability.OBSERVED:
                assert side.has_sizes
                assert side.total_size is not None


@requires_extract
def test_the_lunch_break_shows_up_as_the_largest_staleness(local):
    """11:30:01 to 13:00:13 is 5,412 s and it is the biggest per-level gap in
    the extract. A caller sizing ``max_age`` against the 35 s median would
    discard the whole book on the first tick after lunch, which is why the age
    is reported raw and not silently netted of closed time."""
    after_lunch = local.book_at('FPT', datetime(2022, 11, 9, 13, 0, 5))
    assert after_lunch.stalest_age > timedelta(minutes=80)
    assert after_lunch.bid.availability is SideAvailability.OBSERVED
    budgeted = local.book_at('FPT', datetime(2022, 11, 9, 13, 0, 5),
                             max_age=timedelta(minutes=5))
    assert budgeted.bid.availability is SideAvailability.ABSENT
    assert budgeted.bid.truncation is Truncation.MAX_AGE


@requires_extract
def test_prices_are_decimal_and_sizes_are_int(local):
    """House rule. DuckDB hands back ``DECIMAL(20,6)`` and it stays Decimal --
    never re-parsed through ``str()``, which would be a second rounding this
    module has no authority to perform."""
    book = local.book_at('FPT', datetime(2022, 11, 9, 10, 30))
    for level in book.bid.levels + book.ask.levels:
        assert isinstance(level.price, Decimal)
        assert isinstance(level.size, int) and not isinstance(level.size, bool)


@requires_extract
def test_the_extract_carries_no_level_beyond_three(local, remote):
    """Checked against the tables, not assumed from ``MAX_DEPTH``."""
    conn = duckdb.connect()
    for table in ('local_quote_bidprice', 'local_quote_asksize',
                  'quote_askprice', 'quote_bidsize'):
        row = conn.execute(
            f"SELECT min(depth), max(depth) FROM "
            f"read_parquet('{EXTRACT}/{table}.parquet')").fetchone()
        assert row == (1, MAX_DEPTH)
