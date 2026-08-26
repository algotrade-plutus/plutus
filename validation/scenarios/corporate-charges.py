"""Corporate actions and the charge model, put to the assembled simulator.

Two questions, one module, because they meet in one place: an ex-date changes
both the quantity a charge is levied on and the reference a band is drawn from,
and a run that gets either wrong reports a P&L that never happened.

The questions
=============

**1. Does an ex-date land correctly?** Nine HOSE ex-dates from the daily
corpus, 2021-05-31 .. 2021-07-12, each with its published ceiling and floor.
The corpus does not carry the adjusted reference -- ``quote_reference`` repeats
the *previous close* on an ex-date, 98.93% of HOSE rows -- so the published
band is the only oracle, and the test is: does
:func:`~plutus.market.session.corporate.adjusted_reference` produce a reference
whose band, drawn by ``adapters/datahub.reconstruct_bands``, is the one the
exchange published, to the tick, on all nine?

The answer is yes -- and **only when the reference is left unrounded**. See
:data:`FINDINGS` F-1: rounding it to the quotation unit gets 5 of 9 half-up,
4 of 9 rounding down and 4 of 9 rounding up, and HPG's 2021-05-31 band cannot
be reproduced from any price on the quotation grid at all. That is the first
empirical evidence in this repository on a rule
:data:`~plutus.market.session.corporate.REFERENCE_ROUNDED_TO_TICK` itself calls
"untested", and it says the module's own default is wrong for the only case
the rule applies to.

**2. Is every charge levied per venue, per date, per side, and itemised?**
The 0.1% securities-transfer PIT is sell-side only and withheld at source; the
exchange trading-service row is per venue; the derivatives PIT is levied on the
*margined* value and is therefore linear in the dated VSD initial-margin ratio,
which must be the same series the margin requirement reads. The corpus carries
a session where that ratio changes -- **2022-12-15**, 0.13 -> 0.17 -- so the
coupling is asserted across the change and not at a single date.

What the data cannot decide, stated once
========================================

* **There is no corporate-action feed on this machine.** Neither the Parquet
  corpus nor the production database has a dividend, split or rights table:
  no amount, no ratio, no record date, no payment date. Every leg in
  :data:`EX_DATES` is *inferred* from the ex-date price adjustment and is
  labelled with how. The cash/stock split of a compound event is an inference
  that reproduces the measured factor to ~1e-4 and is not a sourced record.
* **A rights issue cannot be validated against reality here at all**, because
  a subscription price appears nowhere in either source.
  :func:`rights_conservation` therefore drives a *declared synthetic* event
  and tests the one thing that does not need a source: that the event
  conserves value, i.e. the shares cannot arrive without the money leaving.
* **Fills are ``soft``.** The daily corpus has no high, no low and no volume,
  so a marketable order that was never touched and one that was fully filled
  are the same bar (``validation.corpus``). ``hard`` is 100% INDETERMINATE on
  it and would levy no charge at all. ``soft`` is the arm that produces fills
  to charge; the charge model is what is under test here, not the fill model,
  and every run records ``fill_policy`` in its provenance.
* **The settlement calendar is the unsourced weekday one.** No window here
  crosses Tet, so no settlement date in this module depends on it, but every
  settlement-log row says ``weekday-only-UNSOURCED`` and a reader should not
  read a T+2 date off this module as sourced.

Findings are :data:`FINDINGS`, as data rather than prose, so a report can print
them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from plutus.core.order import Side
from plutus.market.adapters.datahub import reconstruct_bands
from plutus.market.protocol import InstrumentKind
from plutus.market.session.charges import (
    DERIVATIVES_PIT_RATE, margined_value,
)
from plutus.market.session.corporate import (
    CorporateAction, CorporateActionApplied, CorporateActionAudit,
    CorporateActionEngine, CorporateActionSchedule, RestingOrderPolicy,
    RightsSubscriptionUnfunded, adjusted_reference,
)
from plutus.market.session.types import ChargeClass, Venue

from validation import (BaseStrategy, Scenario, ScenarioResult, Window,
                        build_session, closes, datahub_source, run_scenario)
from validation.logs import TradeAction

__all__ = [
    'BROKER_PROFILE', 'CA_WINDOW', 'DERIVATIVES_WINDOW',
    'EQUITY_CHARGE_WINDOW', 'EX_DATES', 'FINDINGS', 'MULTIPLIER',
    'PRE_BAND_WINDOW', 'TIERED_PROFILE', 'VIB_WINDOW', 'VSDC_FEE_WINDOW',
    'ExDateCase', 'ExDateRun', 'ReferenceRow', 'RestingRun', 'RightsOutcome',
    'band_from_reference', 'expected_maturity_pit', 'main', 'prior_close',
    'reference_evidence', 'rights_conservation', 'run_derivatives_charges',
    'run_equity_charges', 'run_ex_date', 'run_expiry_pit',
    'run_pre_band_equity', 'run_resting_order', 'run_vsdc_fee_shape_change',
]

_ZERO = Decimal('0')

#: VN30F index-futures contract multiplier, VND per index point. Not read off
#: the venue: government-bond futures on the same venue carry a different one.
MULTIPLIER = Decimal('100000')


# --------------------------------------------------------------------------
# What this module found. Data, not prose, so a report can print it.
# --------------------------------------------------------------------------

FINDINGS: Mapping[str, str] = {
    'F-1 reference rounding': (
        'REFUTED BY THE CORPUS. corporate.REFERENCE_ROUNDED_TO_TICK defaults '
        'the adjusted reference to ROUND_HALF_UP on the quotation unit and '
        'says in terms that the case "only bites after a corporate-action '
        'adjustment -- and that case is untested". It is now tested, on 9 '
        'HOSE ex-dates judged against the exchange\'s own published ceiling '
        'and floor. The UNROUNDED reference reproduces the band 9/9. '
        'Tick-rounding it reproduces 5/9 half-up (fails HPG, FPT, VIB, MSN), '
        '4/9 round-down (adds CTG) and 4/9 round-up (adds ACB). HPG '
        '2021-05-31 is decisive on its own: the published 52.70 ceiling '
        'requires 49.2523 <= P\' < 49.3458 and the published 45.90 floor '
        'requires 49.3011 < P\' <= 49.3548, and that intersection contains no '
        'multiple of the 0.05 quotation unit -- so the exchange cannot have '
        'rounded the reference to the tick before drawing the band, in any '
        'direction. The true value is the unrounded 49.3333. Pass tick=None '
        '(or a 1-dong grid) for a HOSE ex-date; the module\'s default is '
        'wrong for the only case it applies to.'),
    'F-2 ex-date not wired': (
        'ExchangeSession has no corporate-action hook, by design '
        '(corporate.py: "driven by the caller, not by advance_to"). The '
        'consequence is measured here rather than assumed. The same algorithm, '
        'the same window, the same data: WITHOUT the engine it books '
        '-32,517,777 VND, a 19% loss; WITH it, +15,867,055 VND, a 9% gain. '
        'The two runs differ by 48,384,832 VND on a 168m position over 12 '
        'sessions, and every one of those dong is the corporate action -- the '
        '1.35x stock dividend and the 500 VND/share cash leg. Eight of the '
        'harness\'s nine identities hold in BOTH runs. The only one that '
        'separates them, holdings_conservation, fails on the CORRECT run, '
        'because shares that no fill produced are exactly what a bonus issue '
        'creates. CorporateActionAudit is the one thing that names the wrong '
        'run as wrong, and nothing in the session calls it either.'),
    'F-2b a stock dividend strands an odd lot': (
        'The exchange gets this right and it is worth pinning. 2,500 shares '
        'x 1.35 = 3,375, and 3,375 is not a multiple of the 100-share HOSE '
        'board lot, so selling the whole holding is refused ROUND_LOT with '
        'binding_constraint 100. 3,300 fill; 75 shares are stranded as a lo '
        'le, which in the real market is sold to the broker off-board and '
        'which this simulator has no way to trade. Any backtest that applies '
        'a stock dividend and then sells the whole position is trading a '
        'quantity the board would never have matched. types.py already names '
        'the hazard for a different cause -- "a max_participation cap that is '
        'not floored leaves the ledger holding an odd lot that ROUND_LOT will '
        'later refuse to sell" -- and a corporate action reaches it by a route '
        'no flooring can close, because the entitlement really is 3,375.'),
    'F-3 resting-order policy unreachable': (
        'CONFIRMS the module, twice over. RestingOrderPolicy exists for an '
        'order live across an adjustment, and no order in this simulator can '
        'be: an LO submitted at 09:30 is EXPIRED by the 14:45 sweep, so it '
        'can never be live at the next session open where apply_due runs. '
        'Both branches are reachable only by driving the engine inside a '
        'session, which is what run_resting_order does. And even then the '
        'SCALE branch cannot be exercised END TO END: the order it is meant '
        'for was priced at CUM levels, and a cum-priced order cannot be '
        'entered on the ex-date at all -- VIB\'s pre-adjustment 69.90 is '
        'above its ex-date ceiling of 53.40, so admission refuses it '
        'BAND_LIMIT before the policy is reached. Only the arithmetic of the '
        'branch -- the quantity, the price ratio, the re-taken reservation -- '
        'can be checked, and that is what the tests check.'),
    'F-4 derivatives PIT at maturity was never levied': (
        'FOUND HERE, FIXED CONCURRENTLY BY THE EXPIRY SCENARIO, PINNED HERE. '
        'Rulebook 8.1/12.3: taxable income on a futures contract is determined '
        'when the order is matched OR AT CONTRACT MATURITY. '
        'charges.assess_at_maturity implemented it and had no call site. '
        'Measured on this branch before the fix landed: VN30F2212 held into '
        'its 2022-12-15 expiry settled for +550,000 VND, with '
        'exchange_service 2,700 + clearing 2,550 + PIT 6,887 charged on the '
        'OPENING leg and NOTHING on the closing one -- so a contract held to '
        'expiry paid one leg of tax where a contract closed the day before '
        'paid two. exchange.py::_maturity_charges is now the call site (added '
        'by another agent while this scenario was being written; it is the '
        'same fix, so it is not duplicated). This module asserts the number '
        'against the STATUTE rather than against the module that implements '
        'it: 0.1% x [1065.1 x 100,000 x 1 x 0.17 / 2] = 9,053 VND.'),
    'F-5 the PIT drift detector was dead on the session path': (
        'exchange.py::_derivative_charges re-implements the charge '
        'arithmetic instead of calling charges.levy, so charges._pit_rate_check '
        '-- which exists to catch a second margin ratio entering the run -- '
        'never ran on any fill. The two agree numerically today (0.0005 x IM '
        'x notional == 0.001 x notional x IM / 2 identically), and this module '
        'asserts they still do; but the guard the rulebook asked for is not '
        'guarding the fill path. The maturity charge added by F-4 goes '
        'through levy(), so the detector is now live on that one path.'),
    'F-6 no corporate-action data exists': (
        'Neither corpus carries a dividend/split/rights table: no amount, no '
        'ratio, no record date, no payment date. Only the ex-date reference '
        'drop is recoverable, and quote_reference does not carry it -- it '
        'repeats the previous close on 98.93% of HOSE ex-date rows, so the '
        'band midpoint is the only oracle. Every leg in EX_DATES is an '
        'inference and says so. A dividend RECEIVABLE and its payment date '
        'cannot be tested on this machine at all.'),
    'F-7 the dividend cash leg is credited at the ex-date': (
        'A DECLARED SIMPLIFICATION of corporate.py, restated here because it '
        'is a settlement fact and this module owns the settlement log: the '
        'cash leg is credited settled and immediately at the ex-date, while '
        'the real payment lands weeks later on a payment date no source here '
        'carries. It produces no settlement-log row, so a dividend is the one '
        'money movement in the securities pool with no tranche behind it.'),
    'F-8 a tiered commission config killed the run at the first fill': (
        'FIXED (one guard). That tiered commission is not modelled is '
        'DECLARED -- types.py::_commission_rule says Tier 1 does not do it and '
        'charges.assess_daily, the daily-close pass a tier on "Tong gia tri '
        'giao dich/ngay/tai khoan" requires, has no session call site. What '
        'was not declared is what happened to a config that asked for one. '
        'charges.CommissionSchedule.from_config understands {"tiers": [...]}; '
        'BrokerProfile.from_config -- the one the session actually calls -- '
        'does not, and silently produced a ChargeRule with neither rate nor '
        'amount. The session BUILT, ran, and died at the FIRST FILL with '
        'ValueError("charge rule \'broker.commission.hsx\' sets neither rate '
        'nor amount") -- an error naming a charge rule, from a config the '
        'caller wrote. _commission_rule now refuses the row at parse time and '
        'says tiers are not modelled.'),
    'F-11 the exchange and clearing fees do not fire at maturity': (
        'CORRECT AND WORTH PINNING, because it is an asymmetry a reader will '
        'take for a bug. A contract closed by MATCHING pays three rows -- '
        'exchange trading service 2,700, VSDC clearing 2,550, transfer tax -- '
        'on each leg. A contract carried into final cash settlement pays all '
        'three on the opening leg and ONLY THE TAX on the closing one, '
        'because the exchange fee is per MATCHED contract and the clearing '
        'fee per NOVATED one, and no source read says either is charged on a '
        'final cash settlement. Measured: closing VN30F2301 by trade on '
        '2022-12-16 costs 2,700 + 2,550 + 9,010; letting VN30F2212 expire on '
        '2022-12-15 costs 9,053 and nothing else. Omitting an unsourced '
        'charge is right; a run that needs them must source them first.'),
    'F-12 VAT is zero on every row in this window': (
        'DECLARED CONFLICT, carried not resolved. Every charge levied in '
        'every run here has vat=0, because vat_applies is off on every '
        'rulebook row for 2021-2022. The rulebook records the opposite '
        'evidence in the same breath: brokers demonstrably billed VSDC '
        'derivatives charges grossed up exactly 10% during the state-price '
        'VAT exemption (2,805 = 2,550 x 1.1). A run in this window is '
        'therefore reporting the gazetted arm of a conflict, not a settled '
        'fact, and a result sensitive to 10% on the VSDC rows must say which '
        'arm it took.'),
    'F-10 one tick parameter, two incompatible roundings': (
        'A CONSEQUENCE OF F-1, and a real one. '
        'CorporateActionEngine.apply(tick=...) is passed to TWO different '
        'roundings: adjusted_reference rounds the ex-date REFERENCE onto it, '
        'and RestingOrderPolicy.SCALE rounds a scaled LIMIT PRICE onto it. '
        'F-1 says the reference must not be tick-rounded on HOSE; a limit '
        'price must be, or it can never match. One parameter cannot satisfy '
        'both, so a caller running SCALE with tick=None gets a limit price of '
        '33.82016890213611525086934923 -- 26 significant digits and off the '
        'grid -- while a caller passing the tick gets the wrong band. The two '
        'roundings want separate parameters.'),
    'F-9 custody and position-management fees never fire': (
        'MEASURED, and it is a real hole on the derivatives side. '
        'vsdc_custody_equity (0.27 VND per unit per month) and, before '
        '2022-01-01, vsdc_derivatives_position_management (2,550 VND per open '
        'contract per account per day) are dated rows with a MONTHLY / '
        'per-open-contract-per-day base and no accrual pass anywhere in the '
        'session. Measured: a VN30F2203 fill on 2021-12-30 pays exchange '
        '2,700 + tax 9,924 and NOTHING to the depository; the same trade on '
        '2022-01-04 pays 2,550 more, because the charge changed shape into a '
        'per-matched-contract clearing fee that a per-fill model can price. '
        'So every pre-2022 derivatives run in this repository under-charges '
        'the depository fee entirely, and every equity run under-charges '
        'custody. A holding that never trades costs nothing here.'),
    'F-14 the headline "undecided" rate misses an undecided admission': (
        'A REPORTING GAP IN THE HARNESS, not in the session. '
        'IndeterminateReport carries two populations over two denominators and '
        'says so: by_field counts FILL evaluations the policy could not '
        'decide, by_rule counts SUBMISSIONS the exchange could not judge. '
        'ScenarioResult.summary() prints only the first. Measured on the '
        '2020-03 window: both orders are refused band_limit/INDETERMINATE, '
        'by_rule is {"band_limit": 2}, and the summary line reads "undecided '
        '0/0 evaluations" with rate None. A run in which the data decided '
        'nothing reports as a run with nothing undecided. The session is '
        'right; a reader of summary() alone is not.'),
    'F-13 the 2020 HSX rate change is unreachable through a fill': (
        'A DATA LIMIT, correctly reported. The HOSE trading-service rate '
        'steps 0.0300% -> 0.0270% on 2020-03-19 and the corpus covers the '
        'date -- but it publishes no reference and no band for any HOSE stock '
        'before 2021-02-17, so an order on either side of the change is '
        'refused BAND_LIMIT with verdict INDETERMINATE and never reaches a '
        'charge. The refusal is the right behaviour: the data could not '
        'decide, which is not a rule saying no, and the trade log carries '
        'verdict alongside rule for exactly this. The equity per-date axis is '
        'therefore asserted on the derivatives side (F-9, 2022-01-01) where '
        'the corpus can reach it.'),
}


# --------------------------------------------------------------------------
# The windows
# --------------------------------------------------------------------------

#: HPG's 2021-05-31 ex-date, with room either side for a T+2 buy before it and
#: a sale after it. HPG is the most liquid name in the corpus and the ex-date
#: is **ceiling-locked**, which is what makes it the sharp case: the band that
#: day is drawn entirely from the adjusted reference, so a simulator that
#: rebases off the stale ``quote_reference`` prices every order against a band
#: that never existed.
CA_WINDOW = Window(
    name='hpg-ex-date-2021-05-31', start=date(2021, 5, 24),
    end=date(2021, 6, 8), tickers=('HPG',), reference_ticker='HPG',
    note='HOSE ex-rights code 03 (cash + stock) on the most liquid name in '
         'the corpus, ceiling-locked on the ex-date')

#: One HSX name and one HNX name traded in the same run, so the per-venue axis
#: of the charge table is exercised by two rows that differ only in venue.
#: Runs to 2022-03-18 and not to the sale, deliberately: the 2022-03-14 sell
#: settles at the **open of 2022-03-17** under the pre-2022-08-29 regime, so a
#: window that stopped at the sale would leave the cash leg promised and never
#: observed settling and could not tell that from a settlement that failed.
EQUITY_CHARGE_WINDOW = Window(
    name='equity-charges-hsx-hnx', start=date(2022, 3, 7),
    end=date(2022, 3, 18), tickers=('HPG', 'PVS'), reference_ticker='HPG',
    note='HPG on HSX and PVS on HNX; the 0.1% transfer tax is sell-side only '
         'at both, the exchange service row is not')

#: The VSD initial-margin ratio steps 0.13 -> 0.17 on 2022-12-15, and
#: VN30F2212 expires on that same session. One window therefore carries the
#: dated-rate change, the margin-model coupling and a held-to-expiry contract.
DERIVATIVES_WINDOW = Window(
    name='derivatives-pit-2022-12-15', start=date(2022, 12, 13),
    end=date(2022, 12, 19), tickers=('VN30F2301', 'VN30F2212'),
    reference_ticker='VN30F2301',
    note='the VSD initial margin ratio steps 0.13 -> 0.17 on 2022-12-15 and '
         'VN30F2212 expires the same day')


# --------------------------------------------------------------------------
# The ex-dates, and how each leg was inferred
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ExDateCase:
    """One HOSE ex-date, its inferred legs, and its **published** band.

    ``published_ceiling`` and ``published_floor`` are read straight off
    ``quote_ceil`` / ``quote_floor`` for the ex-date and are the only oracle
    in the corpus: ``quote_reference`` on the same row is the *unadjusted*
    previous close, so the adjusted reference itself is not published anywhere
    the harness can see it.

    ``inference`` says how the legs were obtained and is never "sourced":
    there is no corporate-action table in either corpus (:data:`FINDINGS`
    F-6).
    """

    ticker: str
    ex_date: date
    prev_close: Decimal
    cash_per_share: Decimal
    stock_ratio: Decimal
    published_ceiling: Decimal
    published_floor: Decimal
    inference: str

    @property
    def action(self) -> CorporateAction:
        """The event as one :class:`CorporateAction` with its legs."""
        if self.cash_per_share and self.stock_ratio:
            return CorporateAction.combined(
                self.ticker, self.ex_date,
                cash_per_share=self.cash_per_share,
                stock_ratio=self.stock_ratio)
        if self.stock_ratio:
            return CorporateAction.stock_dividend(
                self.ticker, self.ex_date, self.stock_ratio)
        return CorporateAction.cash_dividend(
            self.ticker, self.ex_date, self.cash_per_share)


#: Nine HOSE ex-dates inside 2021-05-28 .. 2021-07-12, every one of them on a
#: VN30 constituent. Three event shapes -- pure cash, pure stock, compound --
#: and three of them ceiling-locked on the ex-date.
#:
#: **How the legs were obtained, and why the check is not circular.** Each
#: ratio is *seeded* from the corpus -- ``prev_close / mid(ceiling, floor)``
#: for a stock leg, ``prev_close - mid`` for a cash one -- and the band
#: midpoint is only an approximation of the reference, because both endpoints
#: have already been rounded onto (possibly different) tick tiers. Two things
#: then make the leg an assertion rather than a restatement of the seed:
#:
#: * every stock seed lands on a **round percentage** -- 40%, 25%, 100%, 29%,
#:   35% -- which the midpoint had no reason to do if the leg were wrong;
#: * the leg is checked by **reconstructing both band endpoints** from the
#:   exact reference the formula produces, through the adapter's own
#:   ``reconstruct_bands``, with the tick keyed per endpoint. That is a
#:   two-sided, two-tier constraint, and it is satisfied only by a reference
#:   inside a window narrower than one tick -- see
#:   ``test_the_hpg_ceiling_and_floor_pin_the_reference_between_two_ticks``.
#:
#: A **compound** event is the one place a leg is genuinely under-determined:
#: the split between the cash and the stock leg is not recoverable from one
#: price, so the round decomposition that reproduces the measured adjustment
#: factor is used and is labelled INFERRED.
EX_DATES: Tuple[ExDateCase, ...] = (
    ExDateCase('HPG', date(2021, 5, 31), Decimal('67.10'), Decimal('500'),
               Decimal('0.35'), Decimal('52.70'), Decimal('45.90'),
               'compound: the 500 VND cash + 35% stock decomposition '
               'reproduces the measured adjclose factor 1.360279 to 1.4e-4; '
               'the split itself is INFERRED, not sourced'),
    ExDateCase('FPT', date(2021, 6, 1), Decimal('97.90'), Decimal('1000'),
               Decimal('0.15'), Decimal('90.10'), Decimal('78.40'),
               'compound: 1,000 VND cash + 15% stock, INFERRED as above '
               '(measured factor 1.161807)'),
    ExDateCase('VIB', date(2021, 6, 9), Decimal('69.90'), _ZERO,
               Decimal('0.40'), Decimal('53.40'), Decimal('46.45'),
               'pure stock, seeded at 40%: the exact reference 49.928571 reproduces '
               'the published 53.40/46.45 band; the band midpoint 49.925 is a '
               'rounding artefact'),
    ExDateCase('ACB', date(2021, 6, 10), Decimal('42.45'), _ZERO,
               Decimal('0.25'), Decimal('36.30'), Decimal('31.60'),
               'pure stock, seeded at 25%: exact reference 33.96, published band '
               '36.30/31.60'),
    ExDateCase('VCI', date(2021, 6, 18), Decimal('98.30'), _ZERO,
               Decimal('1.00'), Decimal('52.50'), Decimal('45.75'),
               'pure bonus 1:1: exact reference 49.15, published band 52.50/45.75. '
               'CEILING-LOCKED on the ex-date, so the whole session traded at '
               'a price drawn entirely from the adjusted reference'),
    ExDateCase('PLX', date(2021, 6, 23), Decimal('58.60'), Decimal('1200'),
               _ZERO, Decimal('61.40'), Decimal('53.40'),
               'pure cash: 58.60 - 57.40 = 1.20 quote units = 1,200 VND per share, '
               'published band 61.40/53.40'),
    ExDateCase('MSN', date(2021, 7, 1), Decimal('111.40'), Decimal('950'),
               _ZERO, Decimal('118.10'), Decimal('102.80'),
               'pure cash: 111.40 - 110.45 = 0.95 quote units = 950 VND per share, '
               'published band 118.10/102.80'),
    ExDateCase('CTG', date(2021, 7, 7), Decimal('48.50'), _ZERO,
               Decimal('0.29'), Decimal('40.20'), Decimal('35.00'),
               'pure stock, seeded at 29%: exact reference 37.596899, published '
               'band 40.20/35.00'),
    ExDateCase('MBB', date(2021, 7, 12), Decimal('41.85'), _ZERO,
               Decimal('0.35'), Decimal('33.15'), Decimal('28.85'),
               'pure stock at 35%: the exact reference 31.00 is on the grid, so '
               'this is the one case where the midpoint IS the reference'),
)

#: The one this module actually trades through. Everything else in
#: :data:`EX_DATES` is evidence for the reference formula.
HPG_CASE = EX_DATES[0]


# --------------------------------------------------------------------------
# The reference, against the published band
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ReferenceRow:
    """One ex-date judged against the exchange's own published band.

    ``band_unrounded`` and ``band_rounded`` are ``(ceiling, floor)`` drawn
    from the adjusted reference with the *same* function the market-data
    adapter uses, so a match is a match against the adapter's own arithmetic
    and not against a restatement of it.
    """

    case: ExDateCase
    raw_reference: Decimal
    rounded_reference: Decimal
    tick: Optional[Decimal]
    band_unrounded: Tuple[Optional[Decimal], Optional[Decimal]]
    band_rounded: Tuple[Optional[Decimal], Optional[Decimal]]
    quantity_factor: Decimal
    hose_code: Optional[str]

    @property
    def published(self) -> Tuple[Decimal, Decimal]:
        return (self.case.published_ceiling, self.case.published_floor)

    @property
    def unrounded_matches(self) -> bool:
        return self.band_unrounded == self.published

    @property
    def rounded_matches(self) -> bool:
        return self.band_rounded == self.published


def band_from_reference(reference: Decimal, ticker: str, ts: datetime,
                        session: Any) -> Tuple[Optional[Decimal],
                                               Optional[Decimal]]:
    """``(ceiling, floor)`` the exchange would publish from ``reference``.

    Uses ``adapters/datahub.reconstruct_bands`` -- the adapter's own function,
    which truncates the ceiling down and rounds the floor up so the band never
    widens by rounding -- with the tick resolved per *resulting band price*
    from the dated rulebook. That per-price keying is load-bearing at these
    ex-dates: HPG's adjusted reference is 49.33, on the 0.05 grid, while its
    ceiling 52.70 is above 50 and therefore on the 0.10 grid.
    """
    rules = session._rulebook.at(ts)
    spec = session._router.instrument(ticker, ts)

    def tick_fn(_ticker: str, price: Decimal) -> Optional[Decimal]:
        return rules.tick_size(session._router.venue(_ticker, ts),
                               InstrumentKind.STOCK, price, ticker=_ticker)

    return reconstruct_bands(reference, spec.daily_trading_limit, tick_fn,
                             ticker)


def reference_evidence(session: Any = None,
                       cases: Sequence[ExDateCase] = EX_DATES,
                       rounding: str = ROUND_HALF_UP,
                       ) -> Tuple[ReferenceRow, ...]:
    """Every ex-date in ``cases``, judged against its published band.

    Builds its own session when not given one, because this is evidence about
    the rulebook and the adapter and does not need a run.
    """
    if session is None:
        session = build_session(
            start=date(2021, 5, 1), end=date(2021, 7, 31), venues=['HSX'],
            source=datahub_source(), initial_cash='0', fill_policy='soft')

    rows: List[ReferenceRow] = []
    for case in cases:
        ts = datetime.combine(case.ex_date, time(9, 30))
        action = case.action
        rules = session._rulebook.at(ts)
        raw = adjusted_reference(action, case.prev_close, venue=Venue.HSX,
                                 tick=None)
        # The tick the reference itself would be rounded onto, keyed on the
        # reference's own price band -- which is what "rounded to the
        # quotation unit" can only mean.
        tick = rules.tick_size(Venue.HSX, InstrumentKind.STOCK,
                               raw.reference_price, ticker=case.ticker)
        rounded = adjusted_reference(action, case.prev_close, venue=Venue.HSX,
                                     tick=tick, rounding=rounding)
        rows.append(ReferenceRow(
            case=case,
            raw_reference=raw.reference_price,
            rounded_reference=rounded.reference_price,
            tick=tick,
            band_unrounded=band_from_reference(raw.reference_price,
                                               case.ticker, ts, session),
            band_rounded=band_from_reference(rounded.reference_price,
                                             case.ticker, ts, session),
            quantity_factor=raw.quantity_factor,
            hose_code=action.hose_code))
    return tuple(rows)


# --------------------------------------------------------------------------
# Driving the engine from inside a run
# --------------------------------------------------------------------------

def prior_close(source: Any, ticker: str, ex_date: date,
                lookback: int = 14) -> Optional[Decimal]:
    """The last close strictly before ``ex_date``: the formula's ``P``.

    Read from the same source the session reads, so the two cannot disagree
    about what the market did. ``lookback`` spans a long weekend and a public
    holiday; it is not a calendar and does not pretend to be one.
    """
    window = closes(source, ticker,
                    date.fromordinal(ex_date.toordinal() - lookback),
                    date.fromordinal(ex_date.toordinal() - 1))
    if not window:
        return None
    return window[max(window)]


def _apply_due(ctx: Any, engine: CorporateActionEngine, source: Any,
               *, take_up: Optional[bool] = None,
               tick_from_reference: bool = False,
               ) -> Tuple[CorporateActionApplied, ...]:
    """Drive ``engine.apply_due`` at the context's instant.

    **This reaches past the strategy facade, because there is no hook.**
    ``ExchangeSession`` never touches ``corporate.py`` -- deliberately, since a
    corporate-action feed is exogenous data on the same footing as the market
    adapter -- so the engine needs the securities account and the order book,
    and neither is on the session's public API. Recorded here rather than
    worked around silently, exactly as ``StrategyContext.advanceable`` does for
    the sale advance (:data:`FINDINGS` F-2).

    ``tick_from_reference`` is off by default and that is
    :data:`FINDINGS` F-1: passing a tick makes the engine round the adjusted
    reference onto the quotation grid, and the corpus says the exchange did
    not. It is a parameter so the refuted arm can still be run.
    """
    session = ctx._session
    ts = ctx.now
    rules = session._rulebook.at(ts)
    due = engine.due(ts)
    prices: Dict[str, Decimal] = {}
    venues: Dict[str, Venue] = {}
    ticks: Dict[str, Decimal] = {}
    lots: Dict[str, int] = {}
    for action in due:
        ticker = action.ticker
        base = prior_close(source, ticker, action.ex_date)
        if base is not None:
            prices[ticker] = base
        venue = session._router.venue(ticker, ts)
        venues[ticker] = venue
        spec = session._router.instrument(ticker, ts)
        lots[ticker] = spec.trading_unit
        if tick_from_reference and base is not None:
            reference = adjusted_reference(action, base, venue=venue,
                                           tick=None).reference_price
            tick = rules.tick_size(venue, InstrumentKind.STOCK, reference,
                                   ticker=ticker)
            if tick is not None:
                ticks[ticker] = tick
    return engine.apply_due(
        ts, account=session._securities, book=session._book,
        phase=session.phase(Venue.HSX), prices=prices, venues=venues,
        ticks=ticks, lots=lots, take_up=take_up)


# --------------------------------------------------------------------------
# Scenario 1 -- an algorithm that holds through a real ex-date
# --------------------------------------------------------------------------

class HoldThroughExDate(BaseStrategy):
    """Buy cum, hold across the ex-date, sell after it.

    Two parcels on purpose. The first is bought early enough to be **settled**
    by the ex-date; the second is bought on the last cum session, so on the
    ex-date it is still in ``Holding.unsettled``. Under T+2 the record date is
    struck one settlement cycle after the ex-date precisely so that the second
    buyer is on the register, so both parcels must draw the entitlement -- and
    a model that priced it off settlement state would silently short exactly
    the buyer the cycle was designed to include.

    ``apply`` decides whether the engine is driven at all. With it off the
    strategy is an ordinary buy-and-hold that happens to cross an ex-date,
    which is what almost every backtest is.

    **The exit is deliberately attempted twice.** A 35% stock dividend on a
    2,500-share holding leaves 3,375 shares, and 3,375 is not a multiple of
    the 100-share HOSE board lot. The first sell asks for the whole holding
    and is refused ``round_lot``; the second asks for the largest whole lot
    and fills. The 75-share remainder is a **lo le** -- an odd lot -- which in
    the real market is sold to the broker off-board and which this simulator
    correctly refuses to match. It is left stranded and reported rather than
    quietly rounded away, because it is the ordinary consequence of a
    Vietnamese stock dividend and any model that lets it trade on the matching
    board is wrong.
    """

    name = 'hold-through-ex-date'

    def __init__(self, case: ExDateCase, source: Any, *, apply: bool = True,
                 settled_parcel: int = 1000, unsettled_parcel: int = 1500,
                 buy_settled_on: date = date(2021, 5, 25),
                 buy_unsettled_on: date = date(2021, 5, 28),
                 sell_on: date = date(2021, 6, 3)) -> None:
        self.case = case
        self.source = source
        self.apply = apply
        self.settled_parcel = settled_parcel
        self.unsettled_parcel = unsettled_parcel
        self.buy_settled_on = buy_settled_on
        self.buy_unsettled_on = buy_unsettled_on
        self.sell_on = sell_on
        self.engine = CorporateActionEngine(
            CorporateActionSchedule([case.action]))
        self.audit = CorporateActionAudit(self.engine.schedule, self.engine)
        self.applied: Tuple[CorporateActionApplied, ...] = ()
        self.holding_at_ex_open: Optional[Any] = None
        self.tranches_at_ex_open: Tuple[Any, ...] = ()
        self.odd_lot_refusal: Optional[Any] = None
        self.stranded_shares: int = 0

    def on_session(self, ctx: Any) -> None:
        today = ctx.today
        ticker = self.case.ticker
        if today == self.buy_settled_on:
            price = ctx.price(ticker)
            ctx.buy(ticker, self.settled_parcel, limit_price=price)
            ctx.note('bought the parcel that will be SETTLED on the ex-date',
                     ticker=ticker, quantity=self.settled_parcel)
        elif today == self.buy_unsettled_on:
            price = ctx.price(ticker)
            ctx.buy(ticker, self.unsettled_parcel, limit_price=price)
            ctx.note('bought on the last cum session: this parcel is still '
                     'UNSETTLED on the ex-date and is entitled anyway, '
                     'because the record date is struck T+2 after it',
                     ticker=ticker, quantity=self.unsettled_parcel)
        elif today == self.case.ex_date:
            holding = ctx.holdings(ticker)
            self.holding_at_ex_open = holding
            self.tranches_at_ex_open = tuple(holding.unsettled)
            if self.apply:
                self.applied = _apply_due(ctx, self.engine, self.source)
                for record in self.applied:
                    ctx.note(
                        'corporate action applied',
                        ticker=record.ticker,
                        factor=str(record.quantity_factor),
                        cash_leg=str(record.cash_leg),
                        residue=str(record.fractional_residue),
                        before=record.holding_before.total,
                        after=record.holding_after.total,
                        reference=(None if record.reference is None else
                                   str(record.reference.reference_price)))
            else:
                ctx.note('ex-date crossed and NOTHING applied: every number '
                         'for this instrument is wrong from here',
                         ticker=ticker, held=holding.total)
        elif today == self.sell_on:
            holding = ctx.holdings(ticker)
            if not holding.settled:
                return
            price = ctx.price(ticker)
            lot = ctx.instrument(ticker).trading_unit
            whole = (holding.settled // lot) * lot
            if whole != holding.settled:
                refusal = ctx.sell(ticker, holding.settled, limit_price=price)
                self.odd_lot_refusal = refusal
                ctx.note('the whole holding is off the board lot after the '
                         'stock dividend and cannot be matched',
                         ticker=ticker, held=holding.settled, lot=lot,
                         rule=getattr(getattr(refusal, 'rule', None), 'value',
                                      None))
            if whole:
                ctx.sell(ticker, whole, limit_price=price)
            self.stranded_shares = holding.settled - whole


@dataclass(frozen=True)
class ExDateRun:
    """One ex-date run and everything a reader has to see to judge it."""

    result: ScenarioResult
    strategy: HoldThroughExDate
    audit_report: Any
    opening_cash: Decimal
    closing_cash: Decimal
    closing_holding: int
    closing_mark: Optional[Decimal]
    gross_proceeds: Decimal
    total_charges: Decimal

    @property
    def applied(self) -> Tuple[CorporateActionApplied, ...]:
        return self.strategy.applied

    @property
    def stranded_value(self) -> Decimal:
        """The odd lot the stock dividend left behind, marked at the close.

        Zero in the naive run, because a run that never applied the action
        never had the shares. It is carried separately from cash so the two
        runs can be compared on total value rather than on a cash figure one
        of them cannot realise.
        """
        if not self.closing_holding or self.closing_mark is None:
            return _ZERO
        return (Decimal(self.closing_holding) * self.closing_mark
                * Decimal('1000'))

    @property
    def terminal_value(self) -> Decimal:
        """Closing settled cash plus whatever could not be sold."""
        return self.closing_cash + self.stranded_value

    @property
    def net_pnl(self) -> Decimal:
        """Terminal value less the opening cash. The whole run, in dong."""
        return self.terminal_value - self.opening_cash


def run_ex_date(*, apply: bool = True, source: Any = None,
                case: ExDateCase = HPG_CASE) -> ExDateRun:
    """Hold ``case.ticker`` across its ex-date, with or without the engine."""
    source = source or datahub_source()
    session = build_session(
        start=CA_WINDOW.start, end=CA_WINDOW.end, venues=['HSX'],
        source=source, initial_cash='1000000000', fill_policy='soft')
    strategy = HoldThroughExDate(case, source, apply=apply)
    result = run_scenario(Scenario(
        name=f'{CA_WINDOW.name}-{"applied" if apply else "naive"}',
        window=CA_WINDOW, session=session, strategy=strategy, source=source,
        note=case.inference))
    charges = sum((c.total for c in session.charges()), _ZERO)
    gross = sum((Decimal(e.fill_quantity or 0) * (e.fill_price or _ZERO)
                 * Decimal('1000')
                 for e in result.logs.trades.of(TradeAction.FILLED)
                 if e.side == Side.SELL.value), _ZERO)
    marks = closes(source, case.ticker, CA_WINDOW.start, CA_WINDOW.end)
    return ExDateRun(
        result=result, strategy=strategy,
        audit_report=strategy.audit.report(
            session, through=CA_WINDOW.end, tickers=(case.ticker,)),
        opening_cash=result.logs.cash.entries[0].amount,
        closing_cash=session.cash().settled_balance,
        closing_holding=session.holdings(case.ticker).total,
        closing_mark=marks[max(marks)] if marks else None,
        gross_proceeds=gross, total_charges=charges)


# --------------------------------------------------------------------------
# Scenario 2 -- an order live when the adjustment lands
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RestingRun:
    """What the configured policy did to one live order."""

    policy: RestingOrderPolicy
    side: Side
    outcome: Any
    order_after: Any
    encumbrance_before: Tuple[Any, ...]
    encumbrance_at_adjustment: Tuple[Any, ...]
    encumbrance_after: Tuple[Any, ...]
    result: ScenarioResult
    applied: CorporateActionApplied


class RestOverAdjustment(BaseStrategy):
    """Rest a limit buy, then drive the adjustment while it is still live.

    The order is submitted on the ex-date's own OPEN step and the engine is
    driven immediately afterwards, in the same step. That is not the shape
    ``apply_due``'s docstring prescribes -- it wants the ex-date's open,
    *before* the session's fills -- and it is the only shape that reaches the
    policy at all: no Vietnamese order type outlives a session and this
    simulator enforces it, so an order submitted on the previous session is
    ``EXPIRED`` by the 14:45 sweep and cannot be live when the next open comes
    round (:data:`FINDINGS` F-3).
    """

    name = 'rest-over-adjustment'

    def __init__(self, case: ExDateCase, source: Any,
                 policy: RestingOrderPolicy, *, quantity: int = 1000,
                 limit_price: Decimal = Decimal('46.00'),
                 side: Side = Side.BUY) -> None:
        self.case = case
        self.source = source
        self.quantity = quantity
        self.limit_price = limit_price
        self.side = side
        self.engine = CorporateActionEngine(
            CorporateActionSchedule([case.action]), resting_orders=policy)
        self.applied: Optional[CorporateActionApplied] = None
        self.order_id: Optional[str] = None
        self.encumbrance_before: Tuple[Any, ...] = ()
        self.encumbrance_at_adjustment: Tuple[Any, ...] = ()

    def on_session(self, ctx: Any) -> None:
        if ctx.today != self.case.ex_date:
            return
        place = ctx.buy if self.side is Side.BUY else ctx.sell
        accepted = place(self.case.ticker, self.quantity,
                         limit_price=self.limit_price)
        self.order_id = accepted.order_id
        self.encumbrance_before = tuple(
            ctx._session._securities.encumbrances.of(self.order_id))
        applied = _apply_due(ctx, self.engine, self.source)
        self.applied = applied[0] if applied else None
        self.encumbrance_at_adjustment = tuple(
            ctx._session._securities.encumbrances.of(self.order_id))


#: The **sell** arm of the resting-order test, on its own ex-date.
#:
#: A buy reserves cash and a sell reserves shares, and ``SCALE`` re-takes the
#: two by different arithmetic -- value for cash, quantity for shares -- so a
#: buy-only test leaves half the branch unexercised. HPG cannot host it: its
#: ex-date is ceiling-locked, so under a ``soft`` policy every sell price
#: inside the band is marketable and nothing rests. VIB's 2021-06-09 ex-date
#: closes at 52.50 against a 53.40 ceiling, so a sell at the ceiling rests.
VIB_CASE = EX_DATES[2]

VIB_WINDOW = Window(
    name='vib-ex-date-2021-06-09', start=date(2021, 6, 2),
    end=date(2021, 6, 15), tickers=('VIB',), reference_ticker='VIB',
    note='a 40% bonus issue with a resting SELL across it, so the SHARES '
         'reservation is the one that has to be re-taken')


def run_resting_order(policy: RestingOrderPolicy = RestingOrderPolicy.CANCEL,
                      *, source: Any = None, side: Side = Side.BUY,
                      case: Optional[ExDateCase] = None) -> RestingRun:
    """Rest an order across the adjustment under one policy.

    ``side`` picks which reservation is under test. A buy rests on HPG's
    ceiling-locked ex-date; a sell rests on VIB's, where the close sits below
    the ceiling.
    """
    source = source or datahub_source()
    buy_side = side is Side.BUY
    case = case or (HPG_CASE if buy_side else VIB_CASE)
    window = CA_WINDOW if buy_side else VIB_WINDOW
    session = build_session(
        start=window.start, end=window.end, venues=['HSX'],
        source=source, initial_cash='1000000000', fill_policy='soft',
        initial_holdings=None if buy_side else {case.ticker: 1000})
    strategy = RestOverAdjustment(
        case, source, policy, side=side,
        limit_price=Decimal('46.00') if buy_side else case.published_ceiling)
    result = run_scenario(Scenario(
        name=f'{window.name}-resting-{side.value.lower()}-{policy.value}',
        window=window, session=session, strategy=strategy, source=source,
        opening_holdings={} if buy_side else {case.ticker: 1000}))
    records = {r.order_id: r for r in session.orders()}
    assert strategy.applied is not None, 'the engine applied nothing'
    return RestingRun(
        policy=policy, side=side,
        outcome=strategy.applied.resting_orders[0]
        if strategy.applied.resting_orders else None,
        order_after=records.get(strategy.order_id),
        encumbrance_before=strategy.encumbrance_before,
        encumbrance_at_adjustment=strategy.encumbrance_at_adjustment,
        encumbrance_after=tuple(
            session._securities.encumbrances.of(strategy.order_id)),
        result=result, applied=strategy.applied)


# --------------------------------------------------------------------------
# Scenario 3 -- a rights issue must not create money
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RightsOutcome:
    """One rights take-up, with both money legs and the value identity."""

    action: CorporateAction
    applied: Optional[CorporateActionApplied]
    cash_before: Decimal
    cash_after: Decimal
    shares_before: int
    shares_after: int
    reference_before: Decimal
    reference_after: Decimal
    refusal: Optional[BaseException] = None

    @property
    def value_before(self) -> Decimal:
        """Cash plus shares at the cum reference, in VND."""
        return (self.cash_before
                + Decimal(self.shares_before) * self.reference_before
                * Decimal('1000'))

    @property
    def value_after(self) -> Decimal:
        """Cash plus shares at the ex reference, in VND."""
        return (self.cash_after
                + Decimal(self.shares_after) * self.reference_after
                * Decimal('1000'))


#: **DECLARED SYNTHETIC.** No rights issue anywhere in either corpus carries a
#: subscription price, a ratio or a record date (:data:`FINDINGS` F-6), so the
#: legs here are chosen, not measured. The ticker and the ex-date are real so
#: the session can price the instrument; the event is not.
SYNTHETIC_RIGHTS = CorporateAction.combined(
    'HPG', date(2021, 6, 2),
    rights_ratio=Decimal('0.5'), subscription_price=Decimal('10000'),
    note='SYNTHETIC. 1 new share per 2 held at 10,000 VND, the ordinary '
         'Vietnamese deep-discount shape. Nothing in either corpus carries a '
         'rights subscription price, so this leg cannot be validated against '
         'reality on this machine -- only its arithmetic can.')


def rights_conservation(*, take_up: Optional[bool] = True,
                        initial_cash: str = '1000000000',
                        holding: int = 1000,
                        source: Any = None) -> RightsOutcome:
    """Apply the synthetic rights issue and measure both money legs.

    The property under test needs no source: **rights shares are bought, not
    given**. Crediting them without debiting ``shares x subscription_price``
    creates money out of the event, and it is the one arithmetic error here
    that no downstream number would reveal -- the holding is larger, the cash
    is untouched, and every invariant in the package still holds.

    ``take_up=None`` asks the engine to guess and it must refuse.
    """
    source = source or datahub_source()
    session = build_session(
        start=CA_WINDOW.start, end=CA_WINDOW.end, venues=['HSX'],
        source=source, initial_cash=initial_cash, fill_policy='soft',
        initial_holdings={'HPG': holding})
    ts = datetime.combine(SYNTHETIC_RIGHTS.ex_date, time(9, 30))
    session.advance_to(ts)

    base = prior_close(source, 'HPG', SYNTHETIC_RIGHTS.ex_date)
    engine = CorporateActionEngine(CorporateActionSchedule([SYNTHETIC_RIGHTS]))
    reference = adjusted_reference(SYNTHETIC_RIGHTS, base, venue=Venue.HSX,
                                   tick=None, take_up=bool(take_up))
    cash_before = session.cash().settled_balance
    shares_before = session.holdings('HPG').total

    applied: Optional[CorporateActionApplied] = None
    refusal: Optional[BaseException] = None
    try:
        applied = engine.apply(
            SYNTHETIC_RIGHTS, account=session._securities, ts=ts,
            book=session._book, base_price=base, venue=Venue.HSX,
            take_up=take_up)
    except (ValueError, RightsSubscriptionUnfunded) as exc:
        refusal = exc

    return RightsOutcome(
        action=SYNTHETIC_RIGHTS, applied=applied,
        cash_before=cash_before, cash_after=session.cash().settled_balance,
        shares_before=shares_before, shares_after=session.holdings('HPG').total,
        reference_before=base, reference_after=reference.reference_price,
        refusal=refusal)


# --------------------------------------------------------------------------
# Scenario 4 -- the equity charge model, per venue and per side
# --------------------------------------------------------------------------

#: **UNSOURCED, and the module it is passed to says so.** Every broker number
#: is commercial and none of it is gazetted -- ``CommissionSchedule.PROVENANCE``
#: and ``BrokerTerms.PROVENANCE`` both say it in terms. 0.15% sits inside the
#: 0.10%-0.35% retail band and the 30,000 VND per-order minimum is the only
#: shape the sources describe at all ("some firms impose a minimum charge per
#: order"; no value was ever traced to a schedule).
#:
#: It is here because **without a broker profile the largest charge on a
#: retail equity trade is simply absent**: ``RuleSet.charges`` refuses to
#: return a ``BROKER`` row by design, so a session built with no profile levies
#: the exchange fee and the tax and nothing else. A charge scenario that did
#: not configure one would be testing two thirds of the bill.
BROKER_PROFILE: Mapping[str, Any] = {
    'name': 'illustrative-retail-UNSOURCED',
    'commission': [
        {'venue': 'HSX', 'base': 'trade_value', 'rate': '0.0015',
         'min': '30000'},
        {'venue': 'HNX', 'base': 'trade_value', 'rate': '0.0015',
         'min': '30000'},
    ],
}

#: The same profile asking for tiers. ``charges.CommissionSchedule`` parses
#: this shape; ``BrokerProfile.from_config`` -- the one the session calls --
#: does not. See :data:`FINDINGS` F-8.
TIERED_PROFILE: Mapping[str, Any] = {
    'name': 'illustrative-tiered-UNSOURCED',
    'commission': [
        {'venue': 'HSX', 'base': 'trade_value',
         'tier_variable': 'daily_value_per_account',
         'tiers': [{'from': 0, 'rate': '0.0025'},
                   {'from': 100000000, 'rate': '0.0030'}],
         'min_per_order': '30000'},
    ],
}


class RoundTripBothVenues(BaseStrategy):
    """A round trip on HSX, one on HNX, and one order small enough to clamp.

    Five fills, two venues, both sides. The 0.1% transfer tax must fire on the
    sells and on no buy; the exchange trading-service row must fire on all five
    and must name the venue it was levied at; the broker's per-order minimum
    must bite on the small order and on no other.
    """

    name = 'round-trip-both-venues'

    def __init__(self, legs: Mapping[str, Tuple[date, date, int]], *,
                 small_leg: Optional[Tuple[str, date, int]] = None) -> None:
        self.legs = dict(legs)
        self.small_leg = small_leg
        self.small_order_id: Optional[str] = None

    def on_session(self, ctx: Any) -> None:
        for ticker, (buy_on, sell_on, quantity) in self.legs.items():
            if ctx.today == buy_on:
                ctx.buy(ticker, quantity, limit_price=ctx.price(ticker))
            elif ctx.today == sell_on:
                holding = ctx.holdings(ticker)
                if holding.settled >= quantity:
                    ctx.sell(ticker, quantity, limit_price=ctx.price(ticker))
        if self.small_leg is not None:
            ticker, day, quantity = self.small_leg
            if ctx.today == day:
                accepted = ctx.buy(ticker, quantity,
                                   limit_price=ctx.price(ticker))
                self.small_order_id = getattr(accepted, 'order_id', None)
                ctx.note('a top-up small enough that the per-order minimum '
                         'commission binds', ticker=ticker, quantity=quantity)


def run_equity_charges(source: Any = None,
                       broker_profile: Optional[Mapping[str, Any]] = None,
                       ) -> ScenarioResult:
    """A round trip on HSX and one on HNX in the same account."""
    source = source or datahub_source()
    session = build_session(
        start=EQUITY_CHARGE_WINDOW.start, end=EQUITY_CHARGE_WINDOW.end,
        venues=['HSX', 'HNX'], source=source, initial_cash='1000000000',
        fill_policy='soft',
        broker_profile=dict(BROKER_PROFILE if broker_profile is None
                            else broker_profile))
    strategy = RoundTripBothVenues(
        {'HPG': (date(2022, 3, 8), date(2022, 3, 14), 1000),
         'PVS': (date(2022, 3, 8), date(2022, 3, 14), 1000)},
        small_leg=('HPG', date(2022, 3, 9), 100))
    return run_scenario(Scenario(
        name=EQUITY_CHARGE_WINDOW.name, window=EQUITY_CHARGE_WINDOW,
        session=session, strategy=strategy, source=source))


# --------------------------------------------------------------------------
# Scenario 5 -- the derivatives PIT across the VSD ratio change
# --------------------------------------------------------------------------

class FuturesAcrossRatioChange(BaseStrategy):
    """One contract bought under IM 0.13, one under IM 0.17, one held to expiry.

    The three legs answer three different questions with one account: whether
    the PIT base is the *margined* value, whether the ratio that scales it is
    the dated one, and whether the same ratio is the one the margin
    requirement is computed from at the same instant.
    """

    name = 'futures-across-ratio-change'

    def __init__(self, *, front: str = 'VN30F2212',
                 next_month: str = 'VN30F2301',
                 before: date = date(2022, 12, 14),
                 after: date = date(2022, 12, 15),
                 close_on: date = date(2022, 12, 16)) -> None:
        self.front = front
        self.next_month = next_month
        self.before = before
        self.after = after
        self.close_on = close_on
        self.margin_by_day: Dict[Tuple[date, str], Any] = {}

    def on_session(self, ctx: Any) -> None:
        if ctx.today == self.before:
            ctx.buy(self.next_month, 1, limit_price=ctx.price(self.next_month))
            ctx.buy(self.front, 1, limit_price=ctx.price(self.front))
            ctx.note('bought under the 0.13 VSD initial-margin ratio',
                     ratio='0.13')
        elif ctx.today == self.after:
            ctx.buy(self.next_month, 1, limit_price=ctx.price(self.next_month))
            ctx.note('bought under the 0.17 VSD initial-margin ratio; '
                     f'{self.front} expires this session', ratio='0.17')
        elif ctx.today == self.close_on:
            ctx.sell(self.next_month, 1,
                     limit_price=ctx.price(self.next_month))
            ctx.note('closed one leg by MATCHING it out, so the tax fires on '
                     'the closing fill. The contract that expired instead is '
                     'never matched out, which is why the maturity leg has to '
                     'exist', ratio='0.17')

    def on_events(self, ctx: Any, events: Sequence[Any]) -> None:
        self.margin_by_day[(ctx.today, ctx.phase.value)] = ctx.margin()


def run_derivatives_charges(source: Any = None
                            ) -> Tuple[ScenarioResult,
                                       FuturesAcrossRatioChange, Any]:
    """Trade across 2022-12-15, where the VSD ratio steps 0.13 -> 0.17."""
    source = source or datahub_source()
    session = build_session(
        start=DERIVATIVES_WINDOW.start, end=DERIVATIVES_WINDOW.end,
        venues=['HNXDS'], source=source, initial_cash='0',
        initial_deposit='500000000', fill_policy='soft')
    strategy = FuturesAcrossRatioChange()
    result = run_scenario(Scenario(
        name=DERIVATIVES_WINDOW.name, window=DERIVATIVES_WINDOW,
        session=session, strategy=strategy, source=source))
    return result, strategy, session


#: The VSDC derivatives charge changes **shape**, not just value, on
#: 2022-01-01: an accrual per open contract per account per day becomes a fee
#: per matched contract. One window either side of it, on a contract that
#: trades through both.
VSDC_FEE_WINDOW = Window(
    name='vsdc-derivatives-fee-shape-2022-01-01',
    start=date(2021, 12, 28), end=date(2022, 1, 6),
    tickers=('VN30F2203',), reference_ticker='VN30F2203',
    note='per open contract per day (monthly, never levied) becomes per '
         'matched contract at the fill')

#: HOSE's exchange trading-service rate steps 0.0300% -> 0.0270% on
#: 2020-03-19, and the corpus covers the date -- but it carries **no band for
#: any HOSE stock before 2021-02-17**, so no order can be admitted there. The
#: window is here to record that the change is *untestable through a fill* on
#: this corpus and that the simulator says INDETERMINATE rather than guessing.
PRE_BAND_WINDOW = Window(
    name='hsx-service-rate-2020-03-19', start=date(2020, 3, 16),
    end=date(2020, 3, 23), tickers=('HPG',), reference_ticker='HPG',
    note='the rate change is real and the corpus cannot reach it: no HOSE '
         'band exists before 2021-02-17')


class BuyOnDays(BaseStrategy):
    """Buy a fixed size on each named session. Nothing else."""

    name = 'buy-on-days'

    def __init__(self, ticker: str, days: Sequence[date],
                 quantity: int) -> None:
        self.ticker = ticker
        self.days = frozenset(days)
        self.quantity = quantity

    def on_session(self, ctx: Any) -> None:
        if ctx.today not in self.days:
            return
        price = ctx.price(self.ticker)
        if price is not None:
            ctx.buy(self.ticker, self.quantity, limit_price=price)


def run_vsdc_fee_shape_change(source: Any = None
                              ) -> Tuple[ScenarioResult, Any]:
    """One futures fill either side of 2022-01-01.

    The **per date** axis of the charge table on the derivatives side, and the
    sharpest form of it available: before the change the VSDC row has a
    per-open-contract-per-day base that no per-fill function can price, so a
    fill pays the exchange fee and the tax and nothing to the depository at
    all. After it, the same trade pays 2,550 VND per matched contract.
    """
    source = source or datahub_source()
    session = build_session(
        start=VSDC_FEE_WINDOW.start, end=VSDC_FEE_WINDOW.end,
        venues=['HNXDS'], source=source, initial_cash='0',
        initial_deposit='500000000', fill_policy='soft')
    strategy = BuyOnDays('VN30F2203',
                         (date(2021, 12, 30), date(2022, 1, 4)), 1)
    result = run_scenario(Scenario(
        name=VSDC_FEE_WINDOW.name, window=VSDC_FEE_WINDOW, session=session,
        strategy=strategy, source=source))
    return result, session


def run_pre_band_equity(source: Any = None) -> Tuple[ScenarioResult, Any]:
    """An HSX order in 2020, where the corpus publishes no band.

    The honest outcome is a refusal, and specifically an **INDETERMINATE**
    one: the data could not decide, which is not the same as a rule saying no.
    Conflating the two would report a data gap as a market rule, and it is why
    the trade log carries ``verdict`` alongside ``rule``.
    """
    source = source or datahub_source()
    session = build_session(
        start=PRE_BAND_WINDOW.start, end=PRE_BAND_WINDOW.end, venues=['HSX'],
        source=source, initial_cash='1000000000', fill_policy='soft')
    strategy = BuyOnDays('HPG', (date(2020, 3, 18), date(2020, 3, 19)), 100)
    result = run_scenario(Scenario(
        name=PRE_BAND_WINDOW.name, window=PRE_BAND_WINDOW, session=session,
        strategy=strategy, source=source))
    return result, session


def run_expiry_pit(source: Any = None) -> Tuple[ScenarioResult, Any]:
    """Hold VN30F2212 into its 2022-12-15 expiry and read the charge table.

    The whole point is the *closing* leg. A contract carried into final cash
    settlement is never matched out, so a model that levies the derivatives
    transfer tax only on fills under-charges every held-to-expiry contract by
    one leg -- which is what ``charges.assess_at_maturity`` exists for and what
    nothing called (:data:`FINDINGS` F-4).
    """
    result, _strategy, session = run_derivatives_charges(source)
    return result, session


def expected_maturity_pit(settlement: Decimal, contracts: int,
                          initial_margin_rate: Decimal) -> Decimal:
    """``0.1% x [settlement x multiplier x contracts x IM / 2]``, whole dong.

    The published formula verbatim (Cong van 11133/BTC-CST; TT 87/2026 Dieu
    5.1), written out here so the test asserts against the statute rather than
    against the module that implements it.
    """
    base = margined_value(contracts, settlement, MULTIPLIER,
                          initial_margin_rate)
    return (DERIVATIVES_PIT_RATE * base).quantize(Decimal('1'),
                                                  rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------

def main() -> None:  # pragma: no cover - a human-facing report
    """Run every scenario and print what the logs say."""
    source = datahub_source()

    print('=' * 78)
    print('THE ADJUSTED REFERENCE AGAINST THE EXCHANGE\'S PUBLISHED BAND')
    print('=' * 78)
    rows = reference_evidence()
    print(f'{"ticker":6} {"ex-date":11} {"P":>8} {"P\'raw":>10} '
          f'{"P\'tick":>8} {"band(raw)":>16} {"band(tick)":>16} '
          f'{"published":>16}')
    for row in rows:
        print(f'{row.case.ticker:6} {row.case.ex_date.isoformat():11} '
              f'{row.case.prev_close:>8} {row.raw_reference:>10} '
              f'{row.rounded_reference:>8} '
              f'{str(row.band_unrounded):>16} {str(row.band_rounded):>16} '
              f'{str(row.published):>16}  '
              f'{"raw OK" if row.unrounded_matches else "raw FAIL":9}'
              f'{"tick OK" if row.rounded_matches else "tick FAIL"}')
    print(f'\nunrounded reproduces the published band on '
          f'{sum(r.unrounded_matches for r in rows)}/{len(rows)}; '
          f'tick-rounded on {sum(r.rounded_matches for r in rows)}/{len(rows)}')

    print()
    print('=' * 78)
    print('HPG ACROSS 2021-05-31, WITH AND WITHOUT THE ENGINE')
    print('=' * 78)
    naive = run_ex_date(apply=False, source=source)
    applied = run_ex_date(apply=True, source=source)
    for label, run in (('naive', naive), ('applied', applied)):
        print(f'\n-- {label} --')
        print(run.result.summary())
        print(f'  closing cash {run.closing_cash}')
        print(f'  net P&L      {run.net_pnl}')
        print(f'  audit        {run.audit_report}')
        for identity in run.result.failed_identities:
            print(f'  IDENTITY BROKEN {identity.name}: {identity.breaches}')
    print(f'\nsame algorithm, same window, same data. The two runs differ by '
          f'{applied.net_pnl - naive.net_pnl} VND,')
    print(f'all of it the corporate action. '
          f'{applied.strategy.stranded_shares} shares were left stranded off '
          f'the board lot.')

    print()
    print('=' * 78)
    print('AN ORDER LIVE WHEN THE ADJUSTMENT LANDS')
    print('=' * 78)
    for policy in (RestingOrderPolicy.CANCEL, RestingOrderPolicy.SCALE):
        run = run_resting_order(policy, source=source)
        print(f'{policy.value:7} {run.outcome}')
        print(f'        order state {run.order_after.state.value}, '
              f'encumbrances after {len(run.encumbrance_after)}')

    print()
    print('=' * 78)
    print('A RIGHTS ISSUE MUST NOT CREATE MONEY (SYNTHETIC EVENT)')
    print('=' * 78)
    for label, kwargs in (('taken up', {'take_up': True}),
                          ('lapsed', {'take_up': False}),
                          ('not stated', {'take_up': None}),
                          ('unfunded', {'take_up': True,
                                        'initial_cash': '1000000'})):
        outcome = rights_conservation(source=source, **kwargs)
        print(f'{label:11} shares {outcome.shares_before} -> '
              f'{outcome.shares_after}, cash {outcome.cash_before} -> '
              f'{outcome.cash_after}, refusal={type(outcome.refusal).__name__ if outcome.refusal else None}')

    print()
    print('=' * 78)
    print('EQUITY CHARGES, PER VENUE AND PER SIDE')
    print('=' * 78)
    equity = run_equity_charges(source)
    print(equity.summary())
    print(f'  broker profile {equity.provenance.broker_profile_name}')
    for row in equity.logs.cash:
        if row.charge_kind:
            print(f'  {row.ts.date()} {row.ticker:5} {row.charge_kind:32} '
                  f'{row.charge_base:12} base={row.charge_base_value:>14} '
                  f'amount={-row.amount:>10} affects_balance='
                  f'{row.affects_balance}')
    try:
        run_equity_charges(source, broker_profile=TIERED_PROFILE)
    except ValueError as exc:
        print(f'  a TIERED commission config is refused: {exc}')

    print()
    print('=' * 78)
    print('DERIVATIVES PIT ACROSS THE 2022-12-15 VSD RATIO CHANGE')
    print('=' * 78)
    result, strategy, session = run_derivatives_charges(source)
    print(result.summary())
    for charge in session.charges():
        print(f'  {charge.ts.date()} {charge.ticker:10} {charge.kind:34} '
              f'base={charge.base_value:>14} amount={charge.amount:>8}')
    for key, view in sorted(strategy.margin_by_day.items()):
        if view.initial_margin:
            print(f'  margin {key} IM={view.initial_margin} '
                  f'required={view.required} util={view.utilisation}')

    print()
    print('=' * 78)
    print('THE VSDC DERIVATIVES FEE CHANGES SHAPE ON 2022-01-01')
    print('=' * 78)
    vsdc_result, vsdc_session = run_vsdc_fee_shape_change(source)
    print(vsdc_result.summary())
    for charge in vsdc_session.charges():
        print(f'  {charge.ts.date()} {charge.kind:38} '
              f'base={charge.base_value:>14} amount={charge.amount:>8}')

    print()
    print('=' * 78)
    print('THE 2020 HSX RATE CHANGE, WHICH THIS CORPUS CANNOT REACH')
    print('=' * 78)
    pre_result, pre_session = run_pre_band_equity(source)
    print(pre_result.summary())
    for row in pre_result.logs.trades:
        if row.action is TradeAction.REJECTED:
            print(f'  {row.ts.date()} {row.ticker} refused {row.rule} '
                  f'verdict={row.verdict}')
    print(f'  by_rule {pre_result.indeterminate.by_rule}, '
          f'by_field {pre_result.indeterminate.by_field}, '
          f'rate {pre_result.indeterminate.rate}')

    print()
    print('=' * 78)
    print('FINDINGS')
    print('=' * 78)
    for key, text in sorted(FINDINGS.items()):
        print(f'\n{key}\n  {text}')


if __name__ == '__main__':  # pragma: no cover
    main()
