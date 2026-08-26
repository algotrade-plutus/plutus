"""Equity margin lending -- *giao dich ky quy*. The type contract, and the two
config objects.

**This is not derivatives margin.** ``session/deposit.py`` models clearing
margin at VSDC and shares nothing with this module but a Vietnamese name.
Different regulator (SSC, not VSDC), different custody chain (collateral stays
in the client's own account at the securities company; derivatives margin sits
at VSDC via the settlement bank), different call test (an *equity/assets ratio*,
not *utilisation of posted assets*), different cure ceiling. Do not reuse
``deposit.py``, and in particular do not copy
:class:`plutus.market.session.types.MarginStatus` here -- the four rungs mean
different things and the vocabularies must not merge.

**The central split: statutory floors and commercial terms are separate
objects.** Vietnam publishes *floors*; each firm sets its own stricter values.

* :class:`MarginRegulation` -- gazetted, dated, cited. Not user-configurable.
  Every field traces to a clause someone read. The analogue of the exchange
  rulebook.
* :class:`BrokerMarginTerms` -- commercial, per-firm, **assumed**. The analogue
  of :class:`plutus.market.broker.BrokerTerms`.

Conflating them would assert a house rule as market law. The relationship is
one-directional and enforced at construction: a broker term may be *stricter*
than the law and never *looser*, and
:class:`BrokerTermLooserThanLaw` names the floor that was breached.

**What this module deliberately does not contain.** No engine. No ratio is
computed here, no call is issued, no forced sale is instructed. This file is the
vocabulary the engine will speak: the two config objects, the records the engine
passes around, and an enum for every closed set. The next stage implements
against these names.

**Where the research could not reach, and what that costs.** The spec
(``docs/reference/equity-margin-spec.md``) grades its own sources, and this
module carries those grades rather than flattening them:

1. **QD 87 Dieu 7.2's top-up formulas are images in every accessible mirror.**
   The amounts on :class:`MarginCall` are therefore **DERIVED** -- our own
   arithmetic off the EB/AB algebra, in no text read. Flagged on the field, in
   the class docstring and in :data:`PROVENANCE`.
2. **No verified numeric call or force-sell threshold for statutory equity
   margin exists at any broker in the research.** The one published threshold
   table (DNSE) is a *giao dich tien mat* cash-product table, not a margin
   ladder. So :attr:`BrokerMarginTerms.maintenance_margin_ratio` and
   :attr:`BrokerMarginTerms.liquidation_margin_ratio` have **no defaults** and
   must be supplied. A run that has not set them cannot be constructed.
3. **Every statutory text came from a commercial mirror**, not from cong bao or
   an SSC PDF, and everything from QD 87 Dieu 5 onward has exactly two mirrors.
   :attr:`SourceGrade.VERIFIED` here means "the operative text was read", not
   "the gazette copy was obtained".

**Section 4 of the spec lists what the rulebook is SILENT on.** Those are not
defaulted here. The liquidation order, the proceeds-application order, the
forced-sale execution price and the interest day-count are **required fields
with no defaults**, because QD 87 Dieu 12.2(i) and Dieu 11.4 delegate them to
the contract by name and a default would be an invented rule wearing a citation.

Import boundary: this module imports :class:`~plutus.market.session.types.Venue`
and :class:`~plutus.market.session.types.Cash` and nothing else from the
package. It does not import ``exchange``, ``ledgers``, ``orders`` or
``deposit``, and nothing imports it yet -- wiring is a later stage. ``Cash`` is
the tranche ledger's **read model**, not the ledger, and it is here for one
reason: QD 87 Dieu 2 khoan 5 puts *tien ban chung khoan dang cho ve* inside
``CB``, while ``Cash.available`` deliberately excludes it. :func:`cash_base` is
where those two answers are computed side by side so neither can be mistaken for
the other.
"""

from calendar import monthrange
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from decimal import ROUND_CEILING, Decimal
from enum import Enum
from types import MappingProxyType
from typing import (Any, Callable, Dict, FrozenSet, List, Mapping, Optional,
                    Protocol, Sequence, Tuple, runtime_checkable)

from plutus.market.session.types import Cash, Venue

__all__ = [
    # provenance
    'SourceGrade', 'Provenance', 'PROVENANCE',
    # errors
    'BrokerTermLooserThanLaw', 'UnresolvedMarginRegulation',
    # statutory vocabulary
    'CollateralValuationCap', 'RatioDetermination', 'CureMethod',
    'ExclusionPredicate', 'ProhibitedCollateral', 'IneligibleAccountHolder',
    'FirmLendingLimit',
    # commercial vocabulary
    'PriceSource', 'AccountingUnit', 'DayCount', 'LiquidationOrder',
    'ProceedsComponent', 'ForcedSaleScope', 'ForcedSalePrice',
    'ForcedSaleTarget', 'ForcedSaleTrigger',
    # engine vocabulary
    'LoanStatus', 'MarginCallStatus', 'MarginAccountStatus',
    'MarginEligibility', 'MarginOrderRefusal', 'MarginEventKind',
    # the two config objects
    'MarginRegulation', 'BrokerMarginTerms', 'InterestTier',
    # the dated statutory series
    'QD_87_2017', 'MARGIN_REGULATIONS', 'FIRM_LENDING_LIMITS',
    'regulation_in_force',
    # records the engine passes around
    'MarginLoan', 'MarginCall', 'ForcedSaleInstruction', 'MarginAccountState',
    'MarginAccountAlgebra', 'SecurityEligibility', 'InvestorEligibility',
    'MarginOrderAssessment', 'MarginEvent',
    # declared modelling constants
    'MAX_DAYS_IN_MONTH',
    # ---- the call / forced-sale state machine (spec 2.8, 2.9, 3.2-3.4) ----
    # what binds when statute and contract both speak
    'PolicyBound', 'BindingPolicy', 'binding_policy',
    # grading, and the DERIVED amounts
    'account_status', 'TopUpRequirement', 'top_up_requirement',
    'value_to_restore',
    # curing
    'CureContribution', 'cure_credit',
    # the clock
    'BusinessDayCalendar', 'cure_deadline',
    # forced-sale selection and sizing
    'MarginCollateralPosition', 'PositionSelector', 'liquidation_sequence',
    'positions_in_scope', 'ForcedSalePlan',
    'FORCED_SALE_TRIGGER_PRIORITY',
    # proceeds
    'ProceedsApplication', 'apply_sale_proceeds',
    # errors and the machine itself
    'ForcedSaleNotAuthorised', 'NoOpenMarginCall', 'MarginCallMonitor',
]


_ZERO = Decimal('0')
_ONE = Decimal('1')

#: The longest a calendar month can be, used **only** as a necessary-condition
#: bound when a broker term stated in days is checked against a statutory limit
#: stated in months (QD 87 Dieu 11.1/11.2 say *thang*; every broker publishes
#: *ngay*).
#:
#: **This is a config-time bound, not the test.** ``base_term_days <= 3 * 31``
#: refuses a term that could not possibly fit inside three calendar months; it
#: does **not** establish that a particular loan's maturity does. The exact
#: test is a date computation the engine must run at disbursement --
#: ``due_on <= disbursed_on + relativedelta(months=+3)`` -- and the 31 here is
#: deliberately the *loosest* bridge so that this check never refuses a loan the
#: date arithmetic would allow. Being permissive at config time and strict at
#: disbursement is the safe direction; the reverse would reject legal terms.
MAX_DAYS_IN_MONTH = 31


# --------------------------------------------------------------------------
# Provenance -- the spec's own confidence vocabulary
# --------------------------------------------------------------------------

class SourceGrade(str, Enum):
    """How well one value is sourced. **The spec's vocabulary, not the
    rulebook's.**

    :class:`plutus.market.session.types.Confidence` (HIGH / MEDIUM / LOW /
    UNVERIFIED) grades the *exchange* rulebook, where the question is how much
    to trust a reading. The equity-margin spec asks a different question --
    whether a value was read in a text at all, reported second-hand, computed by
    us, or simply absent -- and defines its own four grades in section 0. Mapping
    one onto the other would lose exactly the distinction this module exists to
    preserve: ``DERIVED`` is not "low confidence in a source", it is **no
    source**.

    ``VERIFIED``
        The complete operative text was read. Note the spec's reachability
        caveat: every statutory text came from a commercial legal-database
        mirror, and everything from QD 87 Dieu 5 onward has exactly two mirrors
        (luatvietan, luatvietnam) that do agree verbatim. VERIFIED does not mean
        a cong bao or SSC-issued copy was obtained.
    ``REPORTED``
        Secondary source only -- news, broker FAQ, broker fee schedule.
    ``DERIVED``
        **Our own arithmetic. Not in any source read.** Every occurrence must
        say so at the point of use, not only here.
    ``SILENT``
        The rulebook does not address it -- delegated to the broker contract by
        name, or simply absent. A SILENT field is one where a default would be
        an invented rule.
    """

    VERIFIED = 'verified'
    REPORTED = 'reported'
    DERIVED = 'derived'
    SILENT = 'silent'


@dataclass(frozen=True)
class Provenance:
    """Where one field's value came from: the article, the grade, the caveat.

    The established house pattern is ``Dict[str, str]``
    (:attr:`plutus.market.broker.BrokerTerms.PROVENANCE`,
    :attr:`plutus.market.session.ledgers.AdvanceTerms.PROVENANCE`). This is that
    pattern with the two load-bearing parts pulled out of the prose, because a
    completeness test that can only substring-match cannot assert *"every field
    the spec grades DERIVED is graded DERIVED here"* -- and that assertion is
    the one this module most needs to be able to make.

    ``str(provenance)`` renders back to the flat house form, so a caller
    printing provenance into a published result gets the same one-line shape it
    gets from every other config object in the package.

    Attributes:
        article: the clause, as it is actually cited -- e.g.
            ``'QD 87 Dieu 5.1'``. ``None`` only where the point is that **no**
            article addresses it, which is what :attr:`SourceGrade.SILENT` and
            :attr:`SourceGrade.DERIVED` mean.
        grade: the spec's section 0 grade for this value.
        note: why it is graded that way, and what a caller must disclose if a
            published result is sensitive to it.
    """

    article: Optional[str]
    grade: SourceGrade
    note: str

    def __str__(self) -> str:
        head = self.article if self.article else self.grade.value.upper()
        return f'{head} -- {self.grade.value.upper()} -- {self.note}'

    @property
    def is_assumption(self) -> bool:
        """True where nothing was read: ``DERIVED`` or ``SILENT``.

        The two grades a published result must disclose. ``REPORTED`` is a real
        source and is not an assumption, even though it is weaker than
        ``VERIFIED``.
        """
        return self.grade in (SourceGrade.DERIVED, SourceGrade.SILENT)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

class BrokerTermLooserThanLaw(ValueError):
    """A commercial term is looser than the statutory floor it sits above.

    A ``ValueError`` because it is a construction error, and a **named** one
    because it is the single invariant this module exists to enforce and callers
    will want to catch exactly it. The message names the offending field, the
    value, the floor, and the article the floor comes from -- a bare "invalid
    config" would tell a user their terms are wrong without telling them which
    law says so.

    Attributes:
        term: the :class:`BrokerMarginTerms` field name.
        value: what the caller supplied.
        floor: the statutory bound it breached.
        article: the clause that sets the bound.
    """

    def __init__(self, term: str, value: Any, floor: Any, article: str,
                 detail: str = '') -> None:
        self.term = term
        self.value = value
        self.floor = floor
        self.article = article
        tail = f' {detail}' if detail else ''
        super().__init__(
            f'broker term {term}={value!r} is looser than the statutory floor '
            f'{floor!r} set by {article}. Vietnam publishes floors and each '
            f'firm sets its own stricter values; a term below the floor is not '
            f'a commercial choice, it is unlawful, and encoding it here would '
            f'assert a house rule as market law.{tail}')


class UnresolvedMarginRegulation(LookupError):
    """No dated :class:`MarginRegulation` covers this date.

    The margin-lending twin of ``rulebook.UnresolvedRule``, and raised for the
    same reason: the statutory layer's whole claim is traceability, so the
    failure mode where nothing is known must be a refusal and not the nearest
    row.

    The live case is any date before **2017-04-01**. QD 637/QD-UBCK
    (2011-08-30) governed until then and set the initial-margin floor at 60 %,
    but that value is **REPORTED** (a 2011 press report) and QD 637's
    *maintenance* floor was not obtained by the research at all. Shipping a row
    for that period would mean inventing an ``mmr`` floor, which is exactly the
    class of fabrication this module refuses. See the spec, section 2.1.
    """

    def __init__(self, on: date, reason: str) -> None:
        self.on = on
        self.reason = reason
        super().__init__(
            f'no margin regulation is resolvable for {on.isoformat()}: '
            f'{reason}')


# --------------------------------------------------------------------------
# Statutory vocabulary
# --------------------------------------------------------------------------

class CollateralValuationCap(str, Enum):
    """The ceiling on what pledged collateral may be valued at.

    **QD 87 Dieu 2.4, verbatim:** *"Gia tri cua chung khoan (v) la gia tri do
    cong ty chung khoan xac dinh tren Hop dong ... nhung khong vuot qua gia dong
    cua tai ngay gan nhat cua chung khoan do."* VERIFIED.

    One member, and that is the point: the article admits exactly one ceiling.
    The broker may haircut freely *below* the last close -- in practice as a
    per-ticker *ty le cho vay* -- but may not value collateral above it. The
    enum exists rather than a bare string so the engine cannot quietly grow a
    second basis, and so that a future amendment ships as a second member with
    its own dated :class:`MarginRegulation` row.

    Note the interaction with :class:`PriceSource`: a broker may *monitor* at a
    live market price (DNSE does), and on an up day the live price exceeds the
    last close. The cap still binds -- the collateral value entering ``PV`` is
    ``min(monitoring price, last close)``. Valuing above the cap raises ``EB``
    and therefore the ratio, which delays calls, which is why
    :attr:`BrokerMarginTerms.collateral_valuation_cap_enforced` cannot be turned
    off.
    """

    LAST_CLOSE = 'last_close'


class RatioDetermination(str, Enum):
    """When the margin ratio is computed.

    ``END_OF_DAY`` is **QD 87 Dieu 6.1**: the CTCK determines each margin
    account's ratio at the end of the trading day, on the Dieu 2.4 valuation,
    at a within-day timestamp agreed in writing with the client. VERIFIED. It is
    the regulatory floor behaviour and the default.

    ``INTRADAY`` is what brokers actually do in 2026 -- DNSE sweeps hourly
    09:00-15:00 and force-sells intraday at live market prices, *"ty le Deal
    tinh theo gia thi truong chu khong tinh theo gia tham chieu"*. REPORTED.
    It is a **broker option**, selected by
    :attr:`BrokerMarginTerms.intraday_monitoring`, exactly as the derivatives
    path treats broker utilisation thresholds.

    Monitoring more often than the rule requires is stricter, not looser, so
    ``INTRADAY`` is never a validation breach.
    """

    END_OF_DAY = 'end_of_day'
    INTRADAY = 'intraday'


class CureMethod(str, Enum):
    """How a client may answer a *lenh goi ky quy bo sung*. QD 87 Dieu 7.

    VERIFIED. Three methods, and the client must restore **at least** ``mmr``;
    the precise target level is the CTCK's to set, which is why
    :attr:`BrokerMarginTerms.cure_target_ratio` exists as a broker term rather
    than a constant here.

    The three are not equivalent arithmetically, and the difference is the
    reason this is an enum and not a boolean:

    * ``SELL_SECURITIES`` reduces ``PV`` and raises ``CB`` by the proceeds,
      then repays ``DB``.
    * ``DEPOSIT_CASH`` swept against the debt at end of day (ACBS: *"he thong
      se tu dong thu can tru no vao cuoi ngay"*) leaves ``EB`` unchanged and
      raises ``AB``.
    * ``POST_SECURITIES`` raises ``AB`` and ``EB`` together.

    The amounts each requires are **DERIVED** -- see :class:`MarginCall`.
    """

    SELL_SECURITIES = 'sell_securities'
    DEPOSIT_CASH = 'deposit_cash'
    POST_SECURITIES = 'post_securities'


class ExclusionPredicate(str, Enum):
    """Why a security is not eligible for margin. QD 87 Dieu 3, as amended by
    QD 1205 Dieu 1.

    A security is INELIGIBLE if **any** predicate holds. All VERIFIED. The
    exchange publishes the resulting negative list; each CTCK then selects its
    own positive list from what remains, so this enum names the *exchange*
    layer's reasons.

    ``INELIGIBLE_VENUE``
        Not the universe QD 87 Dieu 3 opens on -- *co phieu, chung chi quy niem
        yet*, i.e. HOSE and HNX listed only. **Recorded divergence, not
        resolved silently:** TT 120 Dieu 9.4's universe is *co phieu niem yet,
        dang ky giao dich, chung chi quy niem yet*, which on its face includes
        UPCoM. Both texts are VERIFIED. TT 120 Dieu 9.8 expressly delegates the
        margin *quy che* to the SSC and QD 87 **is** that quy che, so TT 120
        reads as the permissive outer universe narrowed from inside -- a
        delegation operating as designed rather than a hierarchy conflict. The
        market does listed-only; the sole evidence for that is a one-off parse
        of one broker's PDF on one date (SSI, 2026-08-25: 238 HOSE / 48 HNX /
        0 UPCoM), which is not on a par with a read statute.
    ``LISTED_UNDER_SIX_MONTHS``
        Dieu 3.1. Counted from first trading day to the review date; on a venue
        transfer the two exchanges' listed times are **summed**.
    ``TRADING_STATUS``
        Dieu 3.2 -- *canh bao, kiem soat, kiem soat dac biet, tam ngung giao
        dich*, or in the delisting queue. **Taxonomy gap:** current HOSE
        practice also cuts margin for *han che giao dich* and *dinh chi giao
        dich*, statuses from the post-2020 listing rules that are absent from
        Dieu 3.2's vocabulary (HVN 2026-04-03; ASP and SVD 2025-07-03).
        REPORTED. The rulebook is **SILENT** on that mapping -- see
        :data:`PROVENANCE`; do not encode it as if it were gazetted.
    ``QUALIFIED_AUDIT_OPINION``
        Dieu 3.3 -- the audited annual FS, or reviewed/audited semi-annual FS,
        carries an opinion other than unqualified.
    ``LATE_FINANCIAL_STATEMENT``
        Dieu 3.4 -- issuer more than **5 business days** late disclosing the
        audited annual or reviewed semi-annual FS, from the deadline or the end
        of any granted extension.
    ``TAX_OR_PROSECUTION``
        Dieu 3.5 **in the QD 1205 wording, effective 2018-01-02** -- an
        administrative-penalty decision for tax evasion or tax fraud, or for
        failure to comply with a tax-enforcement decision, or a decision to
        prosecute (*khoi to bi can*) the company. QD 1205 **narrowed** this:
        before that date any tax-authority violation conclusion cut margin.
        It is a dated rule change and belongs on a dated regulation row.
    ``LOSS_OR_ACCUMULATED_LOSS``
        Dieu 3.6 -- loss in the period and/or accumulated loss on the latest
        audited annual or reviewed/audited semi-annual FS; parents use the
        **consolidated** FS. For a public fund: NAV/unit below par for at least
        one month, looking at 3 consecutive months to the selection date.

    **Most of these need issuer financial-statement facts the corpus does not
    carry.** Where a predicate cannot be evaluated the answer is
    :attr:`MarginEligibility.INDETERMINATE`, never "eligible" -- see
    :class:`SecurityEligibility`.
    """

    INELIGIBLE_VENUE = 'ineligible_venue'
    LISTED_UNDER_SIX_MONTHS = 'listed_under_six_months'
    TRADING_STATUS = 'trading_status'
    QUALIFIED_AUDIT_OPINION = 'qualified_audit_opinion'
    LATE_FINANCIAL_STATEMENT = 'late_financial_statement'
    TAX_OR_PROSECUTION = 'tax_or_prosecution'
    LOSS_OR_ACCUMULATED_LOSS = 'loss_or_accumulated_loss'


class ProhibitedCollateral(str, Enum):
    """What a CTCK may not lend against. QD 87 Dieu 10.1(a)-(e). VERIFIED.

    Distinct from :class:`ExclusionPredicate`, which is about the *security*
    being off the exchange's list. These are about the **relationship** between
    the security, the client and the lending firm, and three of the six do not
    look at the security at all.

    ``SELF_UNDERWRITTEN``
        (a) Shares or fund units the CTCK itself firm-underwrote, from signing
        the underwriting contract until **6 months after** the offering
        completes.
    ``AFFILIATED_ISSUER``
        (b) Shares of a listed company that owns **>= 50 %** of the CTCK's
        charter capital, and shares of a listed or registered-for-trading
        company in which the CTCK owns **>= 50 %**.
    ``OWN_SHARES``
        (c) The CTCK's own shares.
    ``CLIENT_BELOW_REQUIRED_RATIO``
        (d) When the client is not meeting the contractual or regulatory margin
        ratio. Note this is a *lending* prohibition, not a call: an account in
        breach may not borrow more, independently of whether a call has issued.
    ``FOREIGN_INVESTOR``
        (d-dd) Foreign investors, corroborating the flat prohibition in TT 120
        Dieu 9.2. **Read the warning on**
        :attr:`MarginRegulation.foreign_investors_allowed` before acting on
        this: it bars *margin lending* to foreigners and must not be read as
        "foreigners cannot buy on credit".
    ``INELIGIBLE_ACCOUNT_HOLDER``
        (e) The persons enumerated in Dieu 13.4 -- see
        :class:`IneligibleAccountHolder`.
    """

    SELF_UNDERWRITTEN = 'self_underwritten'
    AFFILIATED_ISSUER = 'affiliated_issuer'
    OWN_SHARES = 'own_shares'
    CLIENT_BELOW_REQUIRED_RATIO = 'client_below_required_ratio'
    FOREIGN_INVESTOR = 'foreign_investor'
    INELIGIBLE_ACCOUNT_HOLDER = 'ineligible_account_holder'


class IneligibleAccountHolder(str, Enum):
    """Who may not open a margin account. QD 87 Dieu 13.4, TT 120 Dieu 9.2.
    VERIFIED.

    ``CTCK_INSIDER``
        The CTCK's owner, major shareholder, capital member, Board of
        Directors, Supervisory Board, CEO, deputy CEO, chief accountant, and
        other board-appointed officers. TT 121/2020 Dieu 27.3 independently
        bars lending to this class in any form.
    ``RELATED_PERSON``
        Their related persons. The definition of *nguoi co lien quan* is
        Luat Chung khoan's and is not restated here.
    ``IN_DISSOLUTION_OR_BANKRUPTCY``
        Entities in dissolution or bankruptcy.
    ``IN_BREACH_OF_MARGIN_CONTRACT``
        Parties in breach of the CTCK's margin contract.
    ``FOREIGN_INVESTOR``
        TT 120 Dieu 9.2, corroborated by QD 87 Dieu 10.1(dd). A flat
        prohibition **for margin lending**; see the warning on
        :attr:`MarginRegulation.foreign_investors_allowed`.

    Not in this enum, deliberately: *"authorised or proxy traders cannot
    register margin on the owner's behalf"* is an ACBS FAQ item -- REPORTED, and
    a **broker term, not statute**. A firm that applies it sets it in its own
    terms; it does not belong in a statutory closed set.
    """

    CTCK_INSIDER = 'ctck_insider'
    RELATED_PERSON = 'related_person'
    IN_DISSOLUTION_OR_BANKRUPTCY = 'in_dissolution_or_bankruptcy'
    IN_BREACH_OF_MARGIN_CONTRACT = 'in_breach_of_margin_contract'
    FOREIGN_INVESTOR = 'foreign_investor'


class FirmLendingLimit(str, Enum):
    """The four firm-level caps. QD 87 Dieu 9.1-9.4. VERIFIED.

    Each is a *fraction*, and three of the four are fractions of a different
    denominator, which is why they are an enum keyed against
    :attr:`MarginRegulation.firm_limits` rather than four scalars: the engine
    must not be able to apply 0.03 to the wrong base.

    ``TOTAL_BOOK``
        Dieu 9.1 -- the CTCK's whole margin loan book, **<= 200 % of its
        equity**.
    ``PER_CUSTOMER``
        Dieu 9.2 -- total margin lending to one customer, **<= 3 % of the
        CTCK's equity**.
    ``PER_SECURITY``
        Dieu 9.3 -- total margin loan book against one security, **<= 10 % of
        the CTCK's equity**.
    ``PER_ISSUER_SHARES``
        Dieu 9.4 -- **<= 5 % of that issuer's total listed shares**. The
        denominator is a **share count, not equity**. Re-fetched verbatim:
        *"Tong so chung khoan cho vay giao dich ky quy cua mot cong ty chung
        khoan khong duoc vuot qua 5% tong so chung khoan niem yet cua mot to
        chuc niem yet."* An audit pass reported the per-issuer qualifier
        missing; a re-fetch of the primary mirror does not support that, and the
        reading stands.

    *Von chu so huu* is taken from the latest audited or reviewed FS **not older
    than 06 months** from the calculation date -- see
    :attr:`MarginRegulation.equity_statement_max_age_months`.
    """

    TOTAL_BOOK = 'total_book'
    PER_CUSTOMER = 'per_customer'
    PER_SECURITY = 'per_security'
    PER_ISSUER_SHARES = 'per_issuer_shares'


# --------------------------------------------------------------------------
# Commercial vocabulary -- nothing below is a rule
# --------------------------------------------------------------------------

class PriceSource(str, Enum):
    """Which price the broker *monitors* the ratio at.

    Distinct from :class:`CollateralValuationCap`, which is the statutory
    ceiling and always applies. This enum chooses the number the cap is applied
    to, and the two questions were conflated in an earlier draft of the design.

    ``LAST_CLOSE``
        The Dieu 2.4 valuation itself, and the default -- the regulatory floor
        behaviour, paired with :attr:`RatioDetermination.END_OF_DAY`.
    ``LIVE_MARKET``
        The latest matched price. What DNSE does: *"ty le Deal tinh theo gia
        thi truong chu khong tinh theo gia tham chieu"*. REPORTED. The Dieu 2.4
        cap still binds, so collateral enters ``PV`` at ``min(live, last
        close)`` -- an up day does **not** inflate the ratio.
    ``REFERENCE``
        The session reference price. Named because DNSE explicitly says it does
        *not* use it, which means some firm does; no firm was observed doing so.
        SILENT.
    """

    LAST_CLOSE = 'last_close'
    LIVE_MARKET = 'live_market'
    REFERENCE = 'reference'


class AccountingUnit(str, Enum):
    """What the ratio is computed over.

    ``ACCOUNT`` is the statutory unit. QD 87 Dieu 2's algebra is stated over
    *tai khoan* and Dieu 6.1 determines the ratio per margin account. VERIFIED,
    and the default.

    ``DEAL`` is DNSE's product: *"Ty le Deal = Tai san thuc co cua deal / Tong
    tai san cua deal"*, force-selling only the breaching deal's stock and
    leaving other tickers in the sub-account untouched. REPORTED. It is a
    materially different mechanism -- an account that is comfortably above
    ``mmr`` overall can have one deal in breach -- so it is a unit and not a
    flag.

    ``SUB_ACCOUNT`` sits between the two and is REPORTED only as the container
    DNSE's deals live in.

    Choosing ``DEAL`` does not make the account-level statutory test go away;
    it adds a second, stricter test the broker runs. The engine must be able to
    say which one fired.
    """

    ACCOUNT = 'account'
    SUB_ACCOUNT = 'sub_account'
    DEAL = 'deal'


class DayCount(str, Enum):
    """The interest day-count basis. **Two conventions in one market.**

    QD 87 Dieu 11.4 delegates the calculation method entirely: *"Cach tinh tien
    lai vay duoc xac dinh tren co so thoa thuan bang van ban giua cong ty chung
    khoan va khach hang."* VERIFIED as an absence -- the rulebook prescribes no
    day-count, no accrual convention and no compounding rule. **SILENT.**

    Both bases were observed at named firms in the same market in the same year:

    * **ACT/360** -- SSI, 13.5 %/nam explicitly *"(360 ngay)"*. Note the fetch
      date 2026-08-26 is not the vintage: SSI's *bieu gia* page carries an
      effective date of **2022-11-01**.
    * **ACT/365** -- DNSE, 0.0342 %/ngay = 12.5 %/nam (12.5 / 365 = 0.03425).

    Both REPORTED. **There is no default**: ``day_count`` is a required
    :class:`BrokerMarginTerms` field, because a basis that is implied rather
    than stated is a ~1.4 % error nobody can see in the output. This is the same
    split ``AdvanceTerms.annualisation_basis`` records for the sale advance,
    which declares 365 -- but that declaration was made where the sources merely
    *mixed* the two; here two named firms in the same year use different ones,
    so declaring a house basis would be worse than asking.
    """

    ACT_360 = 'act/360'
    ACT_365 = 'act/365'

    @property
    def days_per_year(self) -> Decimal:
        """Denominator for converting an annual rate to a daily one.

        A property rather than a mapping the engine keeps, so there is exactly
        one place the 360 and the 365 live. ``Decimal`` because the result
        divides money.
        """
        return Decimal('360') if self is DayCount.ACT_360 else Decimal('365')


class LiquidationOrder(str, Enum):
    """Which position a forced sale reaches for first. **SILENT in the
    regulation.**

    QD 87 Dieu 12.2(i) requires only that the *contract* state *"phuong thuc xu
    ly tai san the chap ... va thu tu uu tien su dung tien ban chung khoan the
    chap"*. VERIFIED **that the rule delegates**; the ordering itself is a
    per-broker contract term and no Vietnamese document prescribes one.

    This is the exact analogue of
    :attr:`plutus.market.session.types.LiquidationRule.LARGEST_LOSS_FIRST` on
    the derivatives side -- an adopted ordering with no source behind it. Which
    is why :attr:`BrokerMarginTerms.liquidation_order` has **no default**: the
    caller states a policy or does not get an object.

    No member of this enum is sourced. They are the orderings a broker
    plausibly runs, offered so a caller states one explicitly instead of the
    engine picking:

    ``BREACHING_FIRST``
        Sell the position that caused the breach. Pairs with
        :attr:`ForcedSaleScope.BREACHING_POSITION`; DNSE-shaped.
    ``LARGEST_LOSS_FIRST``
        The derivatives-side adopted ordering, carried over by analogy only.
    ``LARGEST_POSITION_FIRST``
        By market value, which minimises the number of tickets.
    ``LOWEST_LOAN_RATIO_FIRST``
        Sell the weakest collateral first -- the ticker whose *ty le cho vay*
        is lowest contributes least to ``PV`` per dong of debt released.
    ``BROKER_RANKED``
        A caller-supplied explicit ranking. The honest option when the firm's
        contract states a list.
    """

    BREACHING_FIRST = 'breaching_first'
    LARGEST_LOSS_FIRST = 'largest_loss_first'
    LARGEST_POSITION_FIRST = 'largest_position_first'
    LOWEST_LOAN_RATIO_FIRST = 'lowest_loan_ratio_first'
    BROKER_RANKED = 'broker_ranked'


class ProceedsComponent(str, Enum):
    """What forced-sale proceeds are applied to, in some order. **SILENT.**

    The order is the *second* half of QD 87 Dieu 12.2(i) -- *"thu tu uu tien su
    dung tien ban chung khoan the chap"* -- and is delegated to the contract
    just as the sale ordering is. VERIFIED that it delegates; the priority
    itself is unsourced.

    :attr:`BrokerMarginTerms.proceeds_application_order` is a **tuple of every
    member exactly once**, with no default. A partial order would leave a
    component unpriced; a default would invent the term the article says the
    contract must state.

    What *is* statutory is the residual: QD 87 Dieu 8 gives the client only
    *"phan con lai sau khi tru no ky quy"* where all securities are sold -- see
    :attr:`MarginRegulation.withdrawal_only_after_debt_deducted`.
    """

    PRINCIPAL = 'principal'
    INTEREST = 'interest'
    FEES = 'fees'
    TAXES = 'taxes'


class ForcedSaleScope(str, Enum):
    """How much of the account a forced sale may reach.

    QD 87 Dieu 8 says *part or all* of the pledged securities, depending on
    whether the remaining required collateral is smaller or larger than the
    total value in the account. VERIFIED -- but that is a bound on the
    **quantity**, not a rule about which holdings are in scope, and the two are
    different questions.

    ``BREACHING_POSITION``
        Only the breaching position's stock; other tickers untouched.
        DNSE-shaped, REPORTED, and only coherent with
        :attr:`AccountingUnit.DEAL` or ``SUB_ACCOUNT``.
    ``WHOLE_ACCOUNT``
        Everything pledged is in scope, ordered by
        :class:`LiquidationOrder`.
    ``BROKER_RANKED``
        A caller-supplied subset.
    """

    BREACHING_POSITION = 'breaching_position'
    WHOLE_ACCOUNT = 'whole_account'
    BROKER_RANKED = 'broker_ranked'


class ForcedSalePrice(str, Enum):
    """At what price a forced sale is placed. **SILENT -- no rule exists.**

    Section 4 of the spec lists this as one of the nine things not to invent.
    DNSE places at *gia san* (the floor price) at the moment the auto-sell
    fires; no other firm publishes its policy. REPORTED, at one firm.

    :attr:`BrokerMarginTerms.forced_sale_price` therefore has **no default**.
    The choice is not cosmetic -- selling at the floor guarantees a fill and
    guarantees the worst price in the band, and a simulator that silently
    assumed ``MARKET`` would report materially better liquidation outcomes than
    a DNSE client experiences.

    ``LIMIT`` requires a price from the caller;
    :class:`ForcedSaleInstruction` carries it.
    """

    FLOOR = 'floor'
    MARKET = 'market'
    LIMIT = 'limit'


class ForcedSaleTarget(str, Enum):
    """How far a forced sale sells.

    ``MAINTENANCE`` -- sell just enough to lift the ratio back to the
    maintenance level and stop. ACBS states exactly this (*"sells only enough
    to bring the ratio back up to the maintenance level"*) and DNSE says it
    never sells the whole deal by default. REPORTED at two firms, and it is
    also the reading closest to QD 87 Dieu 7's *"at least mmr"* cure target,
    which is why it is the default.

    ``MAINTENANCE_PLUS_BUFFER`` -- overshoot by
    :attr:`BrokerMarginTerms.forced_sale_target_buffer`, so a second breach the
    same session is less likely. Unsourced as a policy; the buffer defaults to
    zero, which makes the two members identical until a caller sets one.
    """

    MAINTENANCE = 'maintenance'
    MAINTENANCE_PLUS_BUFFER = 'maintenance_plus_buffer'


class ForcedSaleTrigger(str, Enum):
    """Why a forced sale fired. Five paths, and they do not share a clock.

    ``CURE_WINDOW_EXPIRED``
        The client failed to top up, or topped up only partially, within the
        call deadline. **QD 87 Dieu 8, VERIFIED** -- this is the statutory
        trigger.
    ``FORCE_LEVEL_BREACHED``
        The ratio touched :attr:`BrokerMarginTerms.liquidation_margin_ratio`.
        **This branch bypasses the cure window entirely** -- SSI force-sells
        *"immediately upon breaching TLKQ xu ly"*, without waiting out the three
        days it grants for a maintenance breach. REPORTED. A model with one
        threshold cannot express it, which is the whole reason brokers are
        modelled with two levels.
    ``CONSECUTIVE_BREACH_DAYS``
        Breached the maintenance level for
        :attr:`BrokerMarginTerms.consecutive_breach_days_before_sale`
        consecutive business days. SSI uses 3 -- the statutory cure ceiling,
        used in full. REPORTED.
    ``LOAN_OVERDUE``
        The debt is overdue. SSI: >= 3 business days. ACBS: disposal starts on
        the 5th business day after maturity. REPORTED, and the two firms
        disagree, which is why it is a broker term.
    ``COLLATERAL_INELIGIBLE``
        A pledged security fell off the margin list, so it no longer counts
        toward the collateral base and the ratio fell as a result. The
        *exclusion* is statutory (TT 120 Dieu 9.6); that it should trigger a
        sale rather than only a call is the broker's call.
    """

    CURE_WINDOW_EXPIRED = 'cure_window_expired'
    FORCE_LEVEL_BREACHED = 'force_level_breached'
    CONSECUTIVE_BREACH_DAYS = 'consecutive_breach_days'
    LOAN_OVERDUE = 'loan_overdue'
    COLLATERAL_INELIGIBLE = 'collateral_ineligible'


# --------------------------------------------------------------------------
# Engine vocabulary -- the closed sets the engine reports against
# --------------------------------------------------------------------------

class LoanStatus(str, Enum):
    """Where one margin loan is in its life.

    ``OUTSTANDING`` -- disbursed, inside its original term (QD 87 Dieu 11.1:
    **<= 3 months** from disbursement).

    ``EXTENDED`` -- extended on the client's **written request**, each extension
    **<= 3 months** (Dieu 11.2). The *number* of extensions is not capped by the
    regulation; see :attr:`BrokerMarginTerms.extension_count_max`.

    ``OVERDUE`` -- past maturity and not extended. Interest typically accrues at
    :attr:`BrokerMarginTerms.overdue_multiplier` times the in-term rate --
    150 % at SSI and DNSE, REPORTED.

    ``REPAID`` -- principal, interest and fees cleared.

    ``LIQUIDATED`` -- closed out by a forced sale. Distinct from ``REPAID``
    because the residual matters: QD 87 Dieu 8 says that where liquidation does
    not cover ``DB`` and the client does not pay the difference, the CTCK
    recovers it under the contract and general law. A liquidated loan can leave
    a debt behind; a repaid one cannot.
    """

    OUTSTANDING = 'outstanding'
    EXTENDED = 'extended'
    OVERDUE = 'overdue'
    REPAID = 'repaid'
    LIQUIDATED = 'liquidated'


class MarginCallStatus(str, Enum):
    """Where one *lenh goi ky quy bo sung* is in its life.

    ``PARTIALLY_CURED`` is a real state and not a rounding of ``OPEN``: QD 87
    Dieu 8 gives the force-sale right when the client *"fails to top up, **or
    tops up only partially**"* within the deadline, and the amount then sold
    depends on the collateral still required. An engine that collapsed partial
    into open would sell the pre-top-up quantity.

    ``ESCALATED`` records that this call produced a
    :class:`ForcedSaleInstruction`, which is what makes the call log joinable to
    the sale log.
    """

    OPEN = 'open'
    PARTIALLY_CURED = 'partially_cured'
    CURED = 'cured'
    EXPIRED = 'expired'
    ESCALATED = 'escalated'


class MarginAccountStatus(str, Enum):
    """Where a margin account sits against its broker's two levels.

    **Not** :class:`plutus.market.session.types.MarginStatus`. That enum grades
    ``MR / margin assets`` against VSDC's three-rung derivatives ladder; this one
    grades ``AB / EB`` against a broker's call and force-sell levels. The rungs
    are not the same rungs and the ratios are not the same ratio, and a shared
    enum would let one be read as the other.

    ``OK``
        At or above :attr:`BrokerMarginTerms.maintenance_margin_ratio`.
    ``CALL``
        Below the maintenance level and at or above the liquidation level. A
        *lenh goi ky quy bo sung* issues and the cure clock starts (QD 87
        Dieu 7.1, ceiling 3 business days).
    ``FORCE_SELL``
        Below :attr:`BrokerMarginTerms.liquidation_margin_ratio`. **The cure
        window does not apply** -- see
        :attr:`ForcedSaleTrigger.FORCE_LEVEL_BREACHED`.
    ``SUSPENDED``
        Lending is stopped: the SSC has ordered margin trading at this CTCK
        suspended (TT 120 Dieu 9.9, VERIFIED), or the firm lost its licence
        conditions and must immediately stop signing and disbursing (TT 120
        Dieu 9.7 / QD 87 Dieu 16). Existing debt does not vanish; new lending
        stops.
    ``INDETERMINATE``
        The data could not decide -- no valuation for a pledged security, an
        eligibility predicate that needs issuer financials the corpus does not
        carry. **Never read as OK.** The house rule throughout this package is
        that "the data could not decide" stays countable apart from "a rule said
        no".
    """

    OK = 'ok'
    CALL = 'call'
    FORCE_SELL = 'force_sell'
    SUSPENDED = 'suspended'
    INDETERMINATE = 'indeterminate'


class MarginEligibility(str, Enum):
    """The three-valued answer to "may this be margined?".

    ``INDETERMINATE`` is required, not defensive. Most of QD 87 Dieu 3's
    predicates need issuer financial-statement facts -- audit opinions,
    disclosure lateness, accumulated losses -- that the corpus does not carry,
    and a security whose predicates cannot be evaluated is **not** eligible by
    default. Silently answering ``ELIGIBLE`` on missing data would margin
    securities the exchange has excluded and report a cleaner run than the data
    supports.
    """

    ELIGIBLE = 'eligible'
    INELIGIBLE = 'ineligible'
    INDETERMINATE = 'indeterminate'


class MarginOrderRefusal(str, Enum):
    """Why a margin order was refused at the pre-trade gate.

    The gate itself is **QD 87 Dieu 13.5(d)**, VERIFIED: the CTCK must not let
    the client trade on margin or withdraw cash beyond the account's current
    buying power. ``order_value x imr <= EE``, equivalently
    ``order_value <= BP``.

    ``BUYING_POWER_EXCEEDED``
        The Dieu 13.5(d) test failed.
    ``SECURITY_NOT_ELIGIBLE``
        The ticker is on the exchange's negative list or off the broker's
        positive one -- see :class:`SecurityEligibility`.
    ``INVESTOR_NOT_ELIGIBLE``
        QD 87 Dieu 13.4 or the foreign-investor prohibition -- see
        :class:`InvestorEligibility`.
    ``NO_MARGIN_CONTRACT``
        TT 120 Dieu 9.1 / QD 87 Dieu 12.1: the *hop dong giao dich ky quy*
        **is** the credit agreement, so there is no lending without one.
    ``ACCOUNT_IN_BREACH``
        QD 87 Dieu 10.1(d): no lending while the client is not meeting the
        contractual or regulatory margin ratio. Independent of whether a call
        has issued.
    ``PROHIBITED_COLLATERAL``
        QD 87 Dieu 10.1(a)-(c) -- self-underwritten, affiliated issuer, own
        shares.
    ``FIRM_LIMIT``
        One of the four QD 87 Dieu 9 caps -- see :class:`FirmLendingLimit`.
    ``CREDIT_LIMIT``
        The broker's own per-customer limit, which sits **under** the statutory
        3 %-of-equity cap. SSI up to 70 ty dong, DNSE 10 ty, ABS 10-35 ty. All
        REPORTED.
    ``LENDING_SUSPENDED``
        TT 120 Dieu 9.9 or 9.7.
    ``INDETERMINATE``
        The gate could not be evaluated. Kept separate from every refusal above
        for the same reason :attr:`MarginEligibility.INDETERMINATE` is.
    """

    BUYING_POWER_EXCEEDED = 'buying_power_exceeded'
    SECURITY_NOT_ELIGIBLE = 'security_not_eligible'
    INVESTOR_NOT_ELIGIBLE = 'investor_not_eligible'
    NO_MARGIN_CONTRACT = 'no_margin_contract'
    ACCOUNT_IN_BREACH = 'account_in_breach'
    PROHIBITED_COLLATERAL = 'prohibited_collateral'
    FIRM_LIMIT = 'firm_limit'
    CREDIT_LIMIT = 'credit_limit'
    LENDING_SUSPENDED = 'lending_suspended'
    INDETERMINATE = 'indeterminate'


class MarginEventKind(str, Enum):
    """What a caller polling the engine can be told happened.

    Deliberately **not** :class:`plutus.market.session.types.EventKind`. That
    enum's ``MARGIN_CALL`` and ``FORCED_LIQUIDATION`` members are the
    derivatives deposit's, and folding equity margin into them would make the
    two products indistinguishable in an event log that a caller uses to decide
    what to do. When the two streams are eventually merged, they merge as
    separate members, not by reusing these.

    Three of these are notice events rather than state changes, and they are
    here because the notice is a legal obligation with an ordering constraint:

    * ``CALL_ISSUED`` -- the CTCK **issues** the call by the contact method in
      the account contract (QD 87 Dieu 7.1).
    * ``FORCED_SALE_NOTICED`` -- the CTCK must notify the client **before
      placing the sell order** (Dieu 8), and disclose publicly first where the
      client is an insider or major shareholder (TT 120 Dieu 9.6). An
      instruction issued without this is a rule breach the engine must be able
      to report, which is why the notice is an event and a timestamp rather
      than an assumption.
    * ``FORCED_SALE_RESULT_SENT`` -- a statement of results afterwards
      (Dieu 8).

    ``LENDING_SUSPENDED`` covers both the SSC's stabilisation order (TT 120
    Dieu 9.9) and the firm's own loss of eligibility (TT 120 Dieu 9.7 / QD 87
    Dieu 16, report to the SSC within 48 hours).
    """

    LOAN_DISBURSED = 'loan_disbursed'
    LOAN_EXTENDED = 'loan_extended'
    LOAN_OVERDUE = 'loan_overdue'
    LOAN_REPAID = 'loan_repaid'
    INTEREST_ACCRUED = 'interest_accrued'
    CALL_ISSUED = 'call_issued'
    CALL_CURED = 'call_cured'
    CALL_PARTIALLY_CURED = 'call_partially_cured'
    CALL_EXPIRED = 'call_expired'
    #: Added with the state machine: a forced-sale right has **arisen**, by any
    #: of the five paths in :class:`ForcedSaleTrigger`. Only one of those paths
    #: has a call behind it to expire, and the loudest -- the ratio touching the
    #: firm's force-sell level -- **bypasses the cure window** and so has no
    #: call at all. Without this member the single most consequential transition
    #: in the machine would be silent until the caller happened to ask for a
    #: plan. See :class:`MarginCallMonitor`.
    FORCED_SALE_DUE = 'forced_sale_due'
    FORCED_SALE_NOTICED = 'forced_sale_noticed'
    FORCED_SALE_INSTRUCTED = 'forced_sale_instructed'
    FORCED_SALE_RESULT_SENT = 'forced_sale_result_sent'
    COLLATERAL_BECAME_INELIGIBLE = 'collateral_became_ineligible'
    FIRM_LIMIT_BREACHED = 'firm_limit_breached'
    LENDING_SUSPENDED = 'lending_suspended'
    LENDING_RESUMED = 'lending_resumed'
    INDETERMINATE = 'indeterminate'


# --------------------------------------------------------------------------
# The statutory layer
# --------------------------------------------------------------------------

#: The four QD 87 Dieu 9 caps, as a mapping the engine indexes by
#: :class:`FirmLendingLimit`. VERIFIED, and independently REPORTED by Thoi bao
#: Tai chinh Viet Nam.
#:
#: **Three denominators, not one.** The first three are fractions of the CTCK's
#: *von chu so huu*; the fourth is a fraction of the **issuer's total listed
#: shares**. A single scalar per limit is only safe because the key names the
#: base -- read :class:`FirmLendingLimit` before applying any of them.
FIRM_LENDING_LIMITS: Mapping[FirmLendingLimit, Decimal] = MappingProxyType({
    FirmLendingLimit.TOTAL_BOOK: Decimal('2.00'),
    FirmLendingLimit.PER_CUSTOMER: Decimal('0.03'),
    FirmLendingLimit.PER_SECURITY: Decimal('0.10'),
    FirmLendingLimit.PER_ISSUER_SHARES: Decimal('0.05'),
})


@dataclass(frozen=True)
class MarginRegulation:
    """The statutory floors for equity margin lending. Dated, cited, and **not
    user-configurable**.

    The analogue of the exchange rulebook: every field traces to a clause that
    was read, and :attr:`PROVENANCE` gives the article and the grade for each
    one. :class:`BrokerMarginTerms` is the commercial half and may only be
    stricter.

    **Dated, not constant.** QD 87 Dieu 5.3 gives the SSC a standing power to
    move the two ratios on market conditions without new legislation, and the
    power has been used inside living memory: the floor was 60 % under QD 637
    from 2011-08-30 and became 50 % when QD 87 took effect 2017-04-01. Modelling
    the ratios as module constants would make a counterfactual at a 2015 date
    silently wrong. Resolve with :func:`regulation_in_force`, which **raises**
    before 2017-04-01 rather than extrapolating -- QD 637's maintenance floor
    was never obtained by the research and inventing one is the fabrication this
    object exists to prevent.

    **Is QD 87 still in force?** No *Tinh trang hieu luc* field was directly
    readable -- paywalled or blocked on every mirror. Three lines of evidence
    say yes: TT 120 Dieu 9.8 obliges the SSC to issue a margin *quy che* and no
    replacement surfaced; HOSE was still citing QD 87 + QD 1205 as the legal
    basis for its ineligibility list in July 2025; and the April 2026 HOSE list
    carries exclusion reasons that map one-to-one onto QD 87 Dieu 3. Strong, but
    it is an inference and not a status read -- and two of those three citations
    are truncated URLs that cannot currently be re-fetched.

    **A historical note that is not a rule.** A January 2018 SSC draft would
    have raised the initial-margin floor from 50 % to 60 %. It was **never
    adopted**. REPORTED. Do not ship it as a dated row.

    Attributes:
        citation: the instrument, as issued.
        effective_from: the date this row took effect.
        effective_to: ``None`` while still in force.
        grade: how well this row as a whole is sourced. Per-field grades are in
            :attr:`PROVENANCE`, which is the finer answer.
        note: what a reader must know before quoting this row.

        initial_margin_ratio_floor: **QD 87 Dieu 5.1**, verbatim: *"Ty le ky
            quy ban dau do cong ty chung khoan quy dinh nhung khong duoc thap
            hon 50%."* The floor is on the ratio the **broker sets**, so a
            firm may be stricter and none may be looser.
            **The common restatement "maximum loan-to-value 50 %" is DERIVED,
            not this text** -- it rides on the identity ``imr = 1 -
            loan_ratio``, which is our own and holds only for a single, fully
            collateralised purchase. Dieu 2 khoan 8 defines ``imr`` as the
            account's *tai san thuc co* over the value of the order at market
            price at trade time, so an account already holding other eligible
            collateral supports a larger purchase than the identity implies.
        maintenance_margin_ratio_floor: **QD 87 Dieu 5.2**, verbatim: *"Ty le
            ky quy duy tri do cong ty chung khoan quy dinh nhung khong duoc thap
            hon 30%."* Tested against ``AB / EB``.
            **Note the contrast with derivatives**, where Vietnam publishes no
            maintenance ratio at any date and ``deposit.py`` says so in its
            first line. Two different products, two different answers; the
            qualifier is load-bearing in both directions.
        ratios_adjustable_by_regulator: QD 87 Dieu 5.3 -- the SSC may adjust
            khoan 1 and 2 on market conditions. Why this object is dated.
        regulator_may_suspend: TT 120 Dieu 9.9 -- in cases necessary to
            stabilise the market the SSC may order margin trading at a CTCK
            suspended. A kill switch, not a ratio.

        collateral_value_cap: QD 87 Dieu 2.4. The broker may haircut freely
            below the last close and **may not value collateral above it**.
        ratio_determination: QD 87 Dieu 6.1 -- end of trading day, on the
            Dieu 2.4 valuation, at a within-day timestamp agreed in writing.
            The regulatory floor behaviour; intraday is a broker option.

        max_cure_business_days: **QD 87 Dieu 7.1 alone** -- the period the CTCK
            requires, *but not more than three (03) business days*. A
            **ceiling**, and the specific period is a contract term. TT 120
            Dieu 9.6 carries the call and the force-sale right but **no day
            count**; citing the two jointly for the 3 days is wrong.
        cure_methods: QD 87 Dieu 7 -- sell, add cash, or add eligible
            collateral, enough to restore **at least** ``mmr``.
        cure_target_is_broker_term: Dieu 7.1 sets the floor of the cure target
            and leaves the precise level to the CTCK. VERIFIED that it
            delegates.
        top_up_formula_obtained: **False, and this is a research gap, not a
            policy.** QD 87 Dieu 7.2 gives two formulas -- securities to post,
            and cash to post -- and **every accessible mirror renders them as
            images and drops them**. The amounts on :class:`MarginCall` are
            therefore DERIVED. Ship them as an assumption; do not ship them as
            "the regulation says".

        forced_sale_notice_required: QD 87 Dieu 8 -- the CTCK must notify the
            client **before placing the sell order**, and send a statement of
            results afterwards, by the contractually agreed method.
        forced_sale_disclosure_required: TT 120 Dieu 9.6 -- before selling, the
            CTCK performs the required public disclosure and notifies the
            client so the client can meet its own ownership-reporting
            obligations. Relevant when the client is an insider or major
            shareholder.
        withdrawal_only_after_debt_deducted: QD 87 Dieu 8 -- where all
            securities are sold the client may withdraw only the remainder after
            the margin debt is deducted. Where liquidation does not cover ``DB``
            the CTCK recovers the residual under the contract and general law.
        liquidation_order_is_broker_term: QD 87 Dieu 12.2(i) -- the *contract*
            must state the method of disposing of collateral. VERIFIED **that
            the rule delegates**; the ordering is unsourced.
        proceeds_order_is_broker_term: same clause, second half -- *thu tu uu
            tien su dung tien ban chung khoan the chap*.
        forced_sale_price_prescribed: **False.** No rule sets the execution
            price. DNSE uses *gia san*; nothing else is published.

        firm_limits: the four QD 87 Dieu 9 caps. See
            :data:`FIRM_LENDING_LIMITS` and :class:`FirmLendingLimit`.
        equity_statement_max_age_months: QD 87 Dieu 9 -- *von chu so huu* is
            taken from the latest audited or reviewed FS not older than 06
            months from the calculation date; if charter capital rose between
            cycles, use the FS for the most recent period.
        suspension_report_hours: TT 120 Dieu 9.7 / QD 87 Dieu 16 -- on losing
            eligibility the CTCK must **immediately** stop signing new margin
            contracts and stop disbursing, and report in writing to the SSC
            within **48 hours**. It may resume only after SSC notification on
            evidence of remediation.

        prohibited_collateral: QD 87 Dieu 10.1(a)-(e).
        underwriting_lockout_months: Dieu 10.1(a) -- 6 months after the offering
            completes.
        affiliate_ownership_threshold: Dieu 10.1(b) -- the >= 50 % cross-holding
            that makes an issuer's shares ineligible as collateral at this CTCK.

        max_loan_term_months: QD 87 Dieu 11.1 -- **<= three (03) months** from
            disbursement, agreed in the contract.
        max_extension_months: QD 87 Dieu 11.2 -- on the client's **written
            request**; each extension **<= 3 months**.
        max_extensions: **None -- the number of extensions is NOT capped by the
            regulation.** That cap is a broker term, and modelling it as a
            statutory zero or as some integer would invent a rule. ``None``
            here means "uncapped by law", not "unknown".
        interest_rate_cap: **None.** QD 87 Dieu 11.3: the rate is agreed **in
            writing** between the CTCK and the client and is *"theo quy dinh
            cua Bo Luat Dan su"*. There is no statutory margin interest rate and
            no cap beyond the Civil Code's general ceiling, which is not
            modelled here.
        prescribes_interest_day_count: **False.** QD 87 Dieu 11.4 delegates the
            calculation method entirely -- no day-count, no accrual convention,
            no compounding rule. SILENT, and the reason
            :attr:`BrokerMarginTerms.day_count` is required.

        margin_contract_required: TT 120 Dieu 9.1 / QD 87 Dieu 12.1 -- the *hop
            dong giao dich ky quy* **is** the credit agreement.
        segregated_margin_account_required: TT 120 Dieu 9.3 / QD 87 Dieu
            13.5(a) -- one margin account per investor per CTCK, segregated from
            the ordinary account and across investors.
        foreign_investors_allowed: **False.** TT 120 Dieu 9.2, corroborated by
            QD 87 Dieu 10.1(dd). A flat prohibition, VERIFIED.

            **Do not read this as "foreigners cannot buy on credit."** TT 120
            Dieu 9a, inserted by TT 68/2024 and amended since, is the
            non-prefunded (NPF) buy regime for foreign **institutional**
            investors -- broker credit extended to precisely the class this
            field bars, under a different regime that is not *ky quy*. It is out
            of scope here and lives in the exchange rulebook. An implementer who
            reads only this field will build a simulator that refuses all
            foreign credit-funded buying, which is wrong.
        ineligible_account_holders: QD 87 Dieu 13.4, plus the foreign
            prohibition.

        eligible_venues: QD 87 Dieu 3's universe -- *co phieu, chung chi quy
            **niem yet***, i.e. HOSE and HNX. **Divergence recorded, not
            resolved silently:** TT 120 Dieu 9.4 says *co phieu niem yet, dang
            ky giao dich, chung chi quy niem yet*, which on its face includes
            UPCoM. Both VERIFIED. TT 120 Dieu 9.8 delegates the *quy che* to the
            SSC and QD 87 is that quy che, so TT 120 reads as the permissive
            outer universe narrowed from inside -- a delegation working as
            designed. The market half of the evidence is a one-off parse of one
            broker's list on one date. See :data:`PROVENANCE`.
        min_listing_months: QD 87 Dieu 3.1 -- 6 months from first trading day to
            the review date; venue-transfer times are **summed**.
        exclusion_predicates: QD 87 Dieu 3 as amended by QD 1205 Dieu 1.
        ineligible_excluded_from_collateral: **True, on TT 120 Dieu 9.6**, which
            excludes non-margin securities from the collateral base for **both**
            ratios. QD 87 Dieu 10.2 says something narrower -- no new lending,
            no longer counted toward ``AB``, but still security for the existing
            loan unless otherwise agreed. Both VERIFIED; the higher-ranking
            instrument is implemented and the divergence is recorded here rather
            than resolved in silence.
        exchange_publish_lag_business_days: QD 87 Dieu 4.1 -- the exchange
            publishes the ineligible list within 2 business days of any Dieu 3
            trigger arising, as a **full snapshot, not a delta**.
        broker_publish_lag_business_days: QD 87 Dieu 4.2 -- the CTCK publishes
            its own positive list within 2 business days of the exchange's
            publication, on its website and at all business locations.
        relist_review_min_months: QD 87 Dieu 4.1 -- removal from the ineligible
            list at most once every 6 months from the last publication, except
            the under-6-months case; exact timing is the exchange's call.

        no_trade_beyond_buying_power: **QD 87 Dieu 13.5(d)** -- the CTCK must
            not let the client trade on margin or withdraw cash beyond the
            account's current buying power. The hard pre-trade check.
        margin_order_is_distinct_type: **QD 87 Dieu 13.5(e)** -- margin order
            tickets must be **distinguishable** from ordinary order tickets,
            carry full client information, be client-confirmed, and are an
            inseparable annex to the contract. In an API this means a margin
            order is a **distinct order type, not a flag on a normal order**.
        repledge_requires_client_consent: QD 87 Dieu 13.3 -- the CTCK may not
            repledge the client's margin securities for anything but the margin
            relationship without client consent.
        cash_withdrawal_requires_debt_cleared: QD 87 Dieu 13.5(c) -- the client
            pays interest on ``DB`` and may withdraw cash only after clearing
            all debts to the CTCK.
    """

    # -- identity and dating
    citation: str
    effective_from: date
    effective_to: Optional[date]
    grade: SourceGrade
    note: str

    # -- 2.1 the ratios
    initial_margin_ratio_floor: Decimal
    maintenance_margin_ratio_floor: Decimal
    ratios_adjustable_by_regulator: bool
    regulator_may_suspend: bool

    # -- 2.3 / 2.4 valuation and timing
    collateral_value_cap: CollateralValuationCap
    ratio_determination: RatioDetermination

    # -- 2.8 the call
    max_cure_business_days: int
    cure_methods: Tuple[CureMethod, ...]
    cure_target_is_broker_term: bool
    top_up_formula_obtained: bool

    # -- 2.9 the forced sale
    forced_sale_notice_required: bool
    forced_sale_disclosure_required: bool
    withdrawal_only_after_debt_deducted: bool
    liquidation_order_is_broker_term: bool
    proceeds_order_is_broker_term: bool
    forced_sale_price_prescribed: bool

    # -- 2.10 firm-level limits
    firm_limits: Mapping[FirmLendingLimit, Decimal]
    equity_statement_max_age_months: int
    suspension_report_hours: int

    # -- 2.11 prohibited collateral
    prohibited_collateral: Tuple[ProhibitedCollateral, ...]
    underwriting_lockout_months: int
    affiliate_ownership_threshold: Decimal

    # -- 2.12 term, extension, interest
    max_loan_term_months: int
    max_extension_months: int
    max_extensions: Optional[int]
    interest_rate_cap: Optional[Decimal]
    prescribes_interest_day_count: bool

    # -- 2.5 investor eligibility
    margin_contract_required: bool
    segregated_margin_account_required: bool
    foreign_investors_allowed: bool
    ineligible_account_holders: Tuple[IneligibleAccountHolder, ...]

    # -- 2.6 security eligibility
    eligible_venues: FrozenSet[Venue]
    min_listing_months: int
    exclusion_predicates: Tuple[ExclusionPredicate, ...]
    ineligible_excluded_from_collateral: bool
    exchange_publish_lag_business_days: int
    broker_publish_lag_business_days: int
    relist_review_min_months: int

    # -- 2.13 operating duties
    no_trade_beyond_buying_power: bool
    margin_order_is_distinct_type: bool
    repledge_requires_client_consent: bool
    cash_withdrawal_requires_debt_cleared: bool

    #: Per-field article and grade. **Read this before quoting any value.**
    #:
    #: The same role as :attr:`plutus.market.broker.BrokerTerms.PROVENANCE`, and
    #: the inverse posture: on ``BrokerTerms`` nothing is sourced and the dict
    #: says so; here almost everything is, and the dict says which clause and
    #: how well. Three entries are **not** VERIFIED and they are the ones a
    #: published result must disclose -- the DERIVED loan-to-value restatement,
    #: the unreadable Dieu 7.2 formulas, and the SILENT day-count.
    #:
    #: Completeness is a tested invariant: every dataclass field has an entry
    #: and every entry names a field.
    #:
    #: **Unannotated on purpose**, exactly as on ``BrokerTerms``,
    #: ``AdvanceTerms`` and ``CommissionSchedule``: an annotation would make it a
    #: dataclass field, so it would need a value at every construction and would
    #: appear in its own completeness check. It is populated immediately after
    #: the class body -- see :data:`_REGULATION_PROVENANCE`.
    PROVENANCE = MappingProxyType({})

    def covers(self, on: date) -> bool:
        """Whether this row's dated interval contains ``on``."""
        if on < self.effective_from:
            return False
        return self.effective_to is None or on <= self.effective_to


_V = SourceGrade.VERIFIED
_R = SourceGrade.REPORTED
_D = SourceGrade.DERIVED
_S = SourceGrade.SILENT


def _p(article: Optional[str], grade: SourceGrade, note: str) -> Provenance:
    """Terse constructor, used only to keep the provenance tables readable."""
    return Provenance(article=article, grade=grade, note=note)


#: Article and grade for every :class:`MarginRegulation` field.
#:
#: Assigned onto the class below rather than declared inside it, because an
#: annotated class attribute inside a dataclass body becomes a field. Reachable
#: as ``MarginRegulation.PROVENANCE`` the way ``BrokerTerms.PROVENANCE`` is.
_REGULATION_PROVENANCE: Mapping[str, Provenance] = MappingProxyType({
    'citation': _p('QD 87/QD-UBCK (2017-01-25, eff. 2017-04-01), amended as to '
                   'khoan 5 Dieu 3 by QD 1205/QD-UBCK (2017-12-27, eff. '
                   '2018-01-02)', _V,
                   'Read in full operative text on two mirrors that agree '
                   'verbatim. NOT obtained from cong bao or an SSC PDF: '
                   'thuvienphapluat.vn, vbpl.vn and vanbanphapluat.co were '
                   'blocked and ssc.gov.vn is JavaScript-gated'),
    'effective_from': _p('QD 87, hieu luc thi hanh', _V,
                         '2017-04-01. Replaced QD 637/QD-UBCK (2011-08-30) and '
                         'QD 09/QD-UBCK (2013-01-08)'),
    'effective_to': _p('QD 87', _R,
                       'None -- still in force. No Tinh trang hieu luc field '
                       'was directly readable on any mirror; current force is '
                       'INFERRED from TT 120 Dieu 9.8 having produced no '
                       'successor quy che, and from HOSE citing QD 87 + QD 1205 '
                       'as the basis of its ineligibility list in July 2025. A '
                       'strong inference, not a status read'),
    'grade': _p('QD 87/QD-UBCK (row metadata)', _V,
                'The row-level grade. Per-field grades are the finer answer '
                'and are what a published result should quote'),
    'note': _p('QD 87/QD-UBCK (row metadata)', _V,
               'Prose. Carries the reachability caveat forward to anyone '
               'printing the row'),

    'initial_margin_ratio_floor': _p('QD 87 Dieu 5.1', _V,
        '0.50. Verbatim "khong duoc thap hon 50%", cross-checked on luatvietan '
        'and luatvietnam. The restatement "=> maximum loan-to-value 50%" is '
        'DERIVED and is NOT this text -- see PROVENANCE["loan_to_value_'
        'identity"]. Was 60% under QD 637 from 2011-08-30 to 2017-03-31 '
        '(REPORTED); a January 2018 SSC draft to return it to 60% was never '
        'adopted (REPORTED) and is not a dated row'),
    'maintenance_margin_ratio_floor': _p('QD 87 Dieu 5.2', _V,
        '0.30. Verbatim "khong duoc thap hon 30%". Tested against AB/EB. '
        'Contrast derivatives, where Vietnam publishes no maintenance ratio at '
        'any date 2020-2026 -- two products, two answers'),
    'ratios_adjustable_by_regulator': _p('QD 87 Dieu 5.3', _V,
        'The SSC may adjust khoan 1 and 2 on market conditions without new '
        'legislation. Why this object is dated rather than constant'),
    'regulator_may_suspend': _p('TT 120 Dieu 9.9', _V,
        'In cases necessary to stabilise the market the SSC may order margin '
        'trading at a CTCK suspended'),

    'collateral_value_cap': _p('QD 87 Dieu 2.4', _V,
        'LAST_CLOSE. Verbatim "nhung khong vuot qua gia dong cua tai ngay gan '
        'nhat". Haircuts below it are free; valuation above it is unlawful'),
    'ratio_determination': _p('QD 87 Dieu 6.1', _V,
        'END_OF_DAY, on the Dieu 2.4 valuation, at a within-day timestamp '
        'agreed in writing with the client. Brokers in 2026 run it intraday at '
        'live prices (REPORTED); that is a broker option, not the rule'),

    'max_cure_business_days': _p('QD 87 Dieu 7.1', _V,
        '3, and it is a CEILING -- "the period the CTCK requires, but not more '
        'than three (03) business days". The specific period is a contract '
        'term. TT 120 Dieu 9.6 carries the call and the force-sale right but '
        'NO day count; citing the two jointly for the 3 days is wrong'),
    'cure_methods': _p('QD 87 Dieu 7', _V,
        'Sell securities, add cash, or add eligible collateral securities, '
        'enough to restore at least mmr'),
    'cure_target_is_broker_term': _p('QD 87 Dieu 7.1', _V,
        'VERIFIED that it delegates: the article floors the cure target at mmr '
        'and leaves the precise level to the CTCK'),
    'top_up_formula_obtained': _p('QD 87 Dieu 7.2', _S,
        'FALSE, and this is a research gap. The article gives two formulas -- '
        'securities to post and cash to post -- and EVERY accessible mirror '
        'renders them as images and drops them (luatvietnam omits them from the '
        'free HTML; hoatieu, dongduong and luatvietan all drop them). The '
        'amounts on MarginCall are therefore DERIVED. To close: obtain the cong '
        'bao copy or the SSC PDF'),

    'forced_sale_notice_required': _p('QD 87 Dieu 8', _V,
        'The CTCK must notify the client BEFORE placing the sell order, and '
        'send a statement of results afterwards, by the agreed method'),
    'forced_sale_disclosure_required': _p('TT 120 Dieu 9.6', _V,
        'Before selling, the CTCK performs the required public disclosure and '
        'notifies the client so the client can meet its own ownership-reporting '
        'obligations -- relevant when the client is an insider or major '
        'shareholder'),
    'withdrawal_only_after_debt_deducted': _p('QD 87 Dieu 8', _V,
        'Where all securities are sold the client may withdraw only the '
        'remainder after the margin debt is deducted. A shortfall is recovered '
        'per the contract and general law'),
    'liquidation_order_is_broker_term': _p('QD 87 Dieu 12.2(i)', _V,
        'VERIFIED that the rule delegates. The ordering itself is SILENT -- see '
        'PROVENANCE["liquidation_order"]'),
    'proceeds_order_is_broker_term': _p('QD 87 Dieu 12.2(i)', _V,
        'Same clause, second half: "thu tu uu tien su dung tien ban chung khoan '
        'the chap". VERIFIED that it delegates; the priority is SILENT'),
    'forced_sale_price_prescribed': _p(None, _S,
        'FALSE. No Vietnamese document sets the execution price for a forced '
        'sale. DNSE uses gia san (REPORTED); no other firm publishes one'),

    'firm_limits': _p('QD 87 Dieu 9.1-9.4', _V,
        'Book <= 200% equity; one customer <= 3% equity; one security <= 10% '
        'equity; one issuer <= 5% of THAT ISSUER\'S total listed shares. '
        'Independently REPORTED by Thoi bao Tai chinh Viet Nam. Dieu 9.4 '
        're-fetched verbatim: "...5% tong so chung khoan niem yet cua mot to '
        'chuc niem yet" -- an audit pass reported the per-issuer qualifier '
        'missing; the re-fetch does not support that'),
    'equity_statement_max_age_months': _p('QD 87 Dieu 9', _V,
        'Von chu so huu from the latest audited or reviewed FS not older than '
        '06 months from the calculation date; if charter capital rose between '
        'cycles, use the FS for the most recent period'),
    'suspension_report_hours': _p('TT 120 Dieu 9.7; QD 87 Dieu 16', _V,
        '48. On losing eligibility the CTCK immediately stops signing and '
        'disbursing and reports in writing to the SSC within 48 hours; it may '
        'resume only after SSC notification on evidence of remediation'),

    'prohibited_collateral': _p('QD 87 Dieu 10.1(a)-(e)', _V,
        'Self-underwritten; >=50% cross-held issuer; own shares; client below '
        'the required ratio; foreign investors; the Dieu 13.4 persons'),
    'underwriting_lockout_months': _p('QD 87 Dieu 10.1(a)', _V,
        '6 months after the offering completes, counted from signing the '
        'underwriting contract'),
    'affiliate_ownership_threshold': _p('QD 87 Dieu 10.1(b)', _V,
        '0.50, and it runs both ways: a listed company owning >=50% of the '
        "CTCK's charter capital, and a listed or registered company in which "
        'the CTCK owns >=50%'),

    'max_loan_term_months': _p('QD 87 Dieu 11.1', _V,
        '3 months from disbursement, agreed in the contract. Every broker '
        'observed publishes the term in DAYS (90); the config-time check uses '
        'MAX_DAYS_IN_MONTH as a necessary-condition bridge and the exact test '
        'is date arithmetic at disbursement'),
    'max_extension_months': _p('QD 87 Dieu 11.2', _V,
        '3 months per extension, on the client\'s WRITTEN request'),
    'max_extensions': _p('QD 87 Dieu 11.2', _V,
        'None -- the NUMBER of extensions is not capped by the regulation. '
        'VERIFIED as an absence. None means "uncapped by law", not "unknown"; '
        'the cap is a broker term (DNSE: free +90 then max 2 further; ACBS: '
        'max 2)'),
    'interest_rate_cap': _p('QD 87 Dieu 11.3', _V,
        'None. The rate is agreed in writing and "theo quy dinh cua Bo Luat Dan '
        'su". There is no statutory margin interest rate and no cap beyond the '
        "Civil Code's general ceiling, which is not modelled. Note the khoan "
        'numbering: rate + Civil Code is 11.3, calculation method is 11.4'),
    'prescribes_interest_day_count': _p('QD 87 Dieu 11.4', _S,
        'FALSE. "Cach tinh tien lai vay duoc xac dinh tren co so thoa thuan '
        'bang van ban" -- no day-count, no accrual convention, no compounding '
        'rule. ACT/360 (SSI) and ACT/365 (DNSE) both observed in the same '
        'market in the same year, which is why BrokerMarginTerms.day_count is '
        'required and has no default'),

    'margin_contract_required': _p('TT 120 Dieu 9.1; QD 87 Dieu 12.1', _V,
        'The hop dong giao dich ky quy IS the credit agreement'),
    'segregated_margin_account_required': _p(
        'TT 120 Dieu 9.3; QD 87 Dieu 13.5(a)', _V,
        'One margin account per investor per CTCK, segregated from the ordinary '
        'account and across investors. This is why the records here carry an '
        'account_id string and NOT a types.AccountRef'),
    'foreign_investors_allowed': _p('TT 120 Dieu 9.2; QD 87 Dieu 10.1(dd)', _V,
        'FALSE -- a flat prohibition FOR MARGIN LENDING. It must NOT be read as '
        '"foreigners cannot buy on credit": TT 120 Dieu 9a (inserted by TT '
        '68/2024, amended by TT 18/2025 and TT 08/2026) is the non-prefunded '
        'buy regime for foreign INSTITUTIONAL investors -- broker credit to '
        'precisely this class, under a different regime, not ky quy. Out of '
        'scope here; it lives in the exchange rulebook'),
    'ineligible_account_holders': _p('QD 87 Dieu 13.4; TT 120 Dieu 9.2', _V,
        "The CTCK's owner / major shareholder / capital member / BoD / "
        'Supervisory Board / CEO / DCEO / chief accountant / other '
        'board-appointed officers and their related persons; entities in '
        'dissolution or bankruptcy; parties in breach of the margin contract; '
        'foreign investors. TT 121/2020 Dieu 27.3 independently bars lending to '
        'the insider class in any form'),

    'eligible_venues': _p('QD 87 Dieu 3', _V,
        'HOSE + HNX listed only. DIVERGENCE RECORDED: TT 120 Dieu 9.4\'s '
        'universe is "co phieu niem yet, DANG KY GIAO DICH, chung chi quy niem '
        'yet", which on its face includes UPCoM. Both texts VERIFIED. TT 120 '
        'Dieu 9.8 delegates the quy che to the SSC and QD 87 is that quy che, '
        'so TT 120 reads as the permissive outer universe narrowed from inside '
        '-- a delegation working as designed, not a hierarchy conflict. The '
        'market half of the evidence is a ONE-OFF parse of ONE broker\'s PDF on '
        'ONE date (SSI 2026-08-25: 238 HOSE / 48 HNX / 0 UPCoM), not reproduced '
        'by a second reader. To close: parse a second CTCK list or the HOSE/HNX '
        'negative lists directly'),
    'min_listing_months': _p('QD 87 Dieu 3.1', _V,
        '6 months, first trading day to review date. On a venue transfer the '
        "two exchanges' listed times are SUMMED"),
    'exclusion_predicates': _p('QD 87 Dieu 3.1-3.6 as amended by QD 1205 '
                               'Dieu 1', _V,
        'A security is ineligible if ANY predicate holds. QD 1205 NARROWED '
        'predicate 5 with effect from 2018-01-02: before that date any '
        'tax-authority violation conclusion cut margin; from that date '
        'mis-declaration causing underpayment, late payment and similar no '
        'longer do. A dated rule change -- implement it as one. Separately '
        'SILENT: how post-2020 "han che giao dich" / "dinh chi giao dich" map '
        "onto Dieu 3.2's older enumeration"),
    'ineligible_excluded_from_collateral': _p('TT 120 Dieu 9.6', _V,
        'TRUE, and this is the higher-ranking of two texts that do not match. '
        'QD 87 Dieu 10.2 says only: no new lending, no longer counted toward '
        'AB, but STILL SECURITY for the existing loan unless otherwise agreed. '
        "TT 120 excludes it from the collateral base for BOTH ratios. Both "
        "VERIFIED; TT 120's version is implemented and the divergence is "
        'recorded rather than resolved silently'),
    'exchange_publish_lag_business_days': _p('QD 87 Dieu 4.1', _V,
        '2 business days from any Dieu 3 trigger arising. The publication is a '
        'FULL SNAPSHOT, not a delta. Observed cadence is quarterly plus '
        'event-driven updates (REPORTED)'),
    'broker_publish_lag_business_days': _p('QD 87 Dieu 4.2', _V,
        '2 business days from the exchange publication, on the website and at '
        'all business locations. The CTCK also reports Phu luc 01 to the '
        'exchange before the 5th trading day of the following month'),
    'relist_review_min_months': _p('QD 87 Dieu 4.1', _V,
        'Removal from the ineligible list at most once every 6 months from the '
        'last publication, except the under-6-months case; exact timing is the '
        "exchange's call"),

    'no_trade_beyond_buying_power': _p('QD 87 Dieu 13.5(d)', _V,
        'The hard pre-trade check: the CTCK must not let the client trade on '
        'margin or withdraw cash beyond the account\'s current buying power. '
        'order_value x imr <= EE, equivalently order_value <= BP'),
    'margin_order_is_distinct_type': _p('QD 87 Dieu 13.5(e)', _V,
        'Margin order tickets must be DISTINGUISHABLE from ordinary tickets, '
        'carry full client information, be client-confirmed, and are an '
        'inseparable annex to the contract. In an API a margin order is '
        'therefore a distinct ORDER TYPE, not a flag on a normal order'),
    'repledge_requires_client_consent': _p('QD 87 Dieu 13.3', _V,
        "The CTCK may not repledge the client's margin securities for anything "
        'but the margin relationship without consent. Dieu 13.5(b): the '
        "collateral remains the client's property"),
    'cash_withdrawal_requires_debt_cleared': _p('QD 87 Dieu 13.5(c)', _V,
        'The client pays interest on DB and may withdraw cash only after '
        'clearing all debts to the CTCK'),
})

MarginRegulation.PROVENANCE = _REGULATION_PROVENANCE


#: The margin *quy che* in force since 2017-04-01. **The only dated row this
#: module ships**, and every value in it traces to a clause in
#: :attr:`MarginRegulation.PROVENANCE`.
#:
#: There is deliberately no row for the QD 637 period (2011-08-30 to
#: 2017-03-31). Its initial-margin floor of 60 % is REPORTED from a 2011 press
#: report and its **maintenance floor was never obtained**; a row for it would
#: have to invent an ``mmr``. :func:`regulation_in_force` raises there instead.
QD_87_2017 = MarginRegulation(
    citation='QD 87/QD-UBCK (2017-01-25, hieu luc 2017-04-01); Dieu 3 khoan 5 '
             'amended by QD 1205/QD-UBCK (2017-12-27, hieu luc 2018-01-02); '
             'frame in TT 120/2020/TT-BTC Dieu 9',
    effective_from=date(2017, 4, 1),
    effective_to=None,
    grade=SourceGrade.VERIFIED,
    note='Full operative text read on two commercial mirrors that agree '
         'verbatim (luatvietan, luatvietnam). NOT a cong bao or SSC copy -- '
         'every primary-source host was blocked or JavaScript-gated. If a '
         'traceability claim in a paper depends on a specific clause, obtain '
         'the gazette copy. Still-in-force is an inference from TT 120 Dieu '
         '9.8 and from HOSE practice in 2025-2026, not a status read.',

    initial_margin_ratio_floor=Decimal('0.50'),
    maintenance_margin_ratio_floor=Decimal('0.30'),
    ratios_adjustable_by_regulator=True,
    regulator_may_suspend=True,

    collateral_value_cap=CollateralValuationCap.LAST_CLOSE,
    ratio_determination=RatioDetermination.END_OF_DAY,

    max_cure_business_days=3,
    cure_methods=(CureMethod.SELL_SECURITIES,
                  CureMethod.DEPOSIT_CASH,
                  CureMethod.POST_SECURITIES),
    cure_target_is_broker_term=True,
    top_up_formula_obtained=False,

    forced_sale_notice_required=True,
    forced_sale_disclosure_required=True,
    withdrawal_only_after_debt_deducted=True,
    liquidation_order_is_broker_term=True,
    proceeds_order_is_broker_term=True,
    forced_sale_price_prescribed=False,

    firm_limits=FIRM_LENDING_LIMITS,
    equity_statement_max_age_months=6,
    suspension_report_hours=48,

    prohibited_collateral=tuple(ProhibitedCollateral),
    underwriting_lockout_months=6,
    affiliate_ownership_threshold=Decimal('0.50'),

    max_loan_term_months=3,
    max_extension_months=3,
    max_extensions=None,
    interest_rate_cap=None,
    prescribes_interest_day_count=False,

    margin_contract_required=True,
    segregated_margin_account_required=True,
    foreign_investors_allowed=False,
    ineligible_account_holders=tuple(IneligibleAccountHolder),

    eligible_venues=frozenset({Venue.HSX, Venue.HNX}),
    min_listing_months=6,
    exclusion_predicates=tuple(ExclusionPredicate),
    ineligible_excluded_from_collateral=True,
    exchange_publish_lag_business_days=2,
    broker_publish_lag_business_days=2,
    relist_review_min_months=6,

    no_trade_beyond_buying_power=True,
    margin_order_is_distinct_type=True,
    repledge_requires_client_consent=True,
    cash_withdrawal_requires_debt_cleared=True,
)


#: The dated statutory series, oldest first. One row today.
MARGIN_REGULATIONS: Tuple[MarginRegulation, ...] = (QD_87_2017,)


def regulation_in_force(on: date) -> MarginRegulation:
    """The margin *quy che* governing ``on``. **Raises rather than guessing.**

    QD 87 Dieu 5.3 lets the SSC move the two ratios without new legislation and
    the floor has moved once inside living memory (60 % -> 50 % on 2017-04-01),
    so a date-resolved lookup is the correct shape even while the table holds
    one row. A module constant would make a 2015 counterfactual silently apply
    2017 law.

    Raises:
        UnresolvedMarginRegulation: for any date before 2017-04-01. QD 637/QD-
            UBCK governed then; its initial-margin floor of 60 % is REPORTED
            from a 2011 press report and its **maintenance floor was never
            obtained by the research**. Extrapolating QD 87's 30 % backwards
            would put an invented number behind a real citation, which is the
            one thing this module must not do.
    """
    for row in MARGIN_REGULATIONS:
        if row.covers(on):
            return row
    earliest = min(row.effective_from for row in MARGIN_REGULATIONS)
    if on < earliest:
        raise UnresolvedMarginRegulation(
            on,
            f'QD 87/QD-UBCK took effect {earliest.isoformat()}. Before that '
            f'date QD 637/QD-UBCK (2011-08-30) governed, and while its initial '
            f'margin floor of 60% is REPORTED, its MAINTENANCE floor was never '
            f'obtained -- so no row exists and none may be extrapolated')
    raise UnresolvedMarginRegulation(
        on, 'no dated row covers this date and none may be extrapolated')


# --------------------------------------------------------------------------
# The broker layer -- nothing below is a rule
# --------------------------------------------------------------------------

def _require_decimal(name: str, value: Any) -> None:
    """Refuse a ``float`` where money or a ratio is expected.

    House rule: ``Decimal`` for money and ratios, never ``float``. The check is
    here rather than left to duck typing because ``Decimal('0.30') >
    0.3`` is ``True`` -- a ``float`` threshold does not merely round, it
    compares wrong against the Decimals it is tested against, and it does so
    silently and only sometimes. A margin ladder is exactly a chain of such
    comparisons.

    ``int`` is accepted: it is exact, and ``Decimal(1) == 1`` holds.
    """
    if isinstance(value, float):
        raise TypeError(
            f'{name} must be a Decimal, got float {value!r}. Decimal for money '
            f'and ratios, never float: a float threshold compares wrong '
            f'against the Decimals the ratio is built from, silently and only '
            f'sometimes. Write Decimal({str(value)!r})')


def _validate_rate_schedule(schedule: Tuple['InterestTier', ...]) -> None:
    """Refuse a tier table with a gap, an overlap or an unpriced tail.

    An empty schedule is legal and means **no rate has been agreed** -- QD 87
    Dieu 11.3 requires the rate to be agreed in writing, so "unset" is a real
    contractual state and the engine must refuse to accrue rather than invent
    a number.

    A non-empty schedule must cover the loan's whole life exactly once: start at
    day 0, be contiguous, not overlap, and end open. **This shape is our
    modelling choice** -- Dieu 11.4 delegates the calculation method entirely
    and prescribes nothing. It is enforced because the alternative is a day on
    which the engine has no rate and has to pick one, which is the same
    fabrication one layer down. Every observed schedule (ACBS T+, ACBS T14,
    DNSE promo, Pinetree P-Zero) already has this shape.
    """
    if not schedule:
        return
    ordered = sorted(schedule, key=lambda t: t.day_from)
    if tuple(ordered) != tuple(schedule):
        raise ValueError(
            f'rate_schedule must be ordered by day_from, got '
            f'{[(t.day_from, t.day_to) for t in schedule]}')
    if ordered[0].day_from != 0:
        raise ValueError(
            f'rate_schedule must start at day 0 -- T0 is the disbursement day '
            f'and interest accrues from it -- got day_from='
            f'{ordered[0].day_from}')
    for earlier, later in zip(ordered, ordered[1:]):
        if earlier.day_to is None:
            raise ValueError(
                'only the last tier of a rate_schedule may be open-ended; an '
                'open-ended tier followed by another one makes two rates apply '
                'to the same day')
        if later.day_from != earlier.day_to + 1:
            gap = 'a gap' if later.day_from > earlier.day_to + 1 else 'an overlap'
            raise ValueError(
                f'rate_schedule has {gap} between day {earlier.day_to} and day '
                f'{later.day_from}. Tiers must be contiguous and day_to is '
                f'inclusive, so the next tier starts at day_to + 1')
    if not ordered[-1].is_open_ended:
        raise ValueError(
            f'the last tier of a rate_schedule must be open-ended (day_to='
            f'None), got day_to={ordered[-1].day_to}. A loan can outlive a '
            f'closed final tier -- an overdue loan certainly does -- and the '
            f'engine would then have no rate for the days past it')


@dataclass(frozen=True)
class InterestTier:
    """One band of a broker's margin interest schedule.

    Brokers do not price margin as a single rate. ACBS runs *Margin T+* at 0 %
    for days 0-6 then 13 %, and *T14* at 8 % for days 0-13 then 13 %; DNSE ships
    promo tiers at 5.99 % / 9.99 % for the first 30 days then 12.5 %; Pinetree
    runs 0 % for 30 days, 6.5 % for 90, 8.8 % for 30; ABS tiers 13.5-15 %/nam by
    day bucket. All REPORTED. A scalar rate cannot express any of them.

    ``day_from`` counts from **T0 = disbursement** (ACBS states this
    explicitly). ``day_to`` is inclusive; ``None`` makes the tier open-ended,
    which every observed schedule ends with.

    ``annual_rate`` is a fraction, not a percentage: 13.5 %/nam is
    ``Decimal('0.135')``. It is converted to a daily rate through
    :attr:`DayCount.days_per_year`, and **which basis is in force is not
    recoverable from the rate** -- SSI's 13.5 % is over 360 and DNSE's 12.5 %
    is over 365. That is why the basis is a separate, required field on
    :class:`BrokerMarginTerms` rather than an attribute of the tier.
    """

    day_from: int
    day_to: Optional[int]
    annual_rate: Decimal

    def __post_init__(self) -> None:
        if self.day_from < 0:
            raise ValueError(
                f'day_from counts from T0 = disbursement and cannot be '
                f'negative, got {self.day_from}')
        if self.day_to is not None and self.day_to < self.day_from:
            raise ValueError(
                f'day_to is inclusive and must not precede day_from, got '
                f'day_from={self.day_from}, day_to={self.day_to}')
        if self.annual_rate < _ZERO:
            raise ValueError(
                f'annual_rate must not be negative, got {self.annual_rate}. A '
                f'0% promotional tier is real and permitted (ACBS Margin T+, '
                f'Pinetree P-Zero); a negative one is not')

    @property
    def is_open_ended(self) -> bool:
        """Whether this tier runs to the end of the loan."""
        return self.day_to is None


@dataclass(frozen=True)
class BrokerMarginTerms:
    """The commercial terms of one securities company's margin product.

    **Nothing on this object is a rule.** Section 3 of the spec is a survey of
    observed broker values, useful as defaults and as realistic ranges, and it
    records that the research found **zero verified numeric thresholds for
    statutory equity margin at any named broker**. No default here is sourced,
    and :attr:`PROVENANCE` says so field by field.

    **Six fields have no default and must be supplied.** Each is a place where
    defaulting would invent a rule the regulation expressly delegates, or would
    ship a number no source supports:

    * :attr:`maintenance_margin_ratio` and :attr:`liquidation_margin_ratio` --
      spec section 5, gap 5. The one published broker threshold table (DNSE) is
      a *giao dich tien mat* **cash-product** table for all five rows, header
      ``Goi``, not a margin ladder. The marquee reading that the 50 % package
      force-sells at exactly the statutory 30 % floor reads a coincidence off a
      non-margin product and is withdrawn. What survives is the **shape**:
      brokers run two levels, a call above a force-sell. The numbers do not
      survive, so the caller states them.
    * :attr:`forced_sale_price` -- spec section 4, item 3. No rule; one firm
      publishes a policy.
    * :attr:`day_count` -- spec section 4, item 4. Two conventions in one
      market in one year.
    * :attr:`liquidation_order` and :attr:`proceeds_application_order` -- QD 87
      Dieu 12.2(i) delegates both to the contract **by name**.

    **The validation relationship is one-directional.** A broker term may be
    stricter than the statutory floor and never looser.
    :meth:`__post_init__` refuses at construction with
    :class:`BrokerTermLooserThanLaw`, naming the field, the value, the floor and
    the article. The floors come from :attr:`regulation`, which defaults to
    :data:`QD_87_2017` -- a sourced object, so the default is not an assumption.

    **Record the vintage.** Section 3's own caveat: "observed 2026" is loose for
    at least one entry, since SSI's *bieu gia* page carries an effective date of
    2022-11-01 while it was fetched 2026-08-26. :attr:`terms_effective_from` and
    :attr:`terms_fetched_on` exist so a result can say which it has.

    Attributes:
        maintenance_margin_ratio: the **call** level -- SSI's *TLKQ duy tri*,
            DNSE's *ty le canh bao*. At or above it the account is
            :attr:`MarginAccountStatus.OK`; below it a call issues and the cure
            clock starts. Bounded below by
            :attr:`MarginRegulation.maintenance_margin_ratio_floor`.
            **UNSOURCED. No default.**
        liquidation_margin_ratio: the **force-sell** level -- SSI's *TLKQ xu
            ly*, DNSE's *ty le xu ly*. Breaching it force-sells **immediately,
            bypassing the cure window**, which is why one threshold cannot model
            a Vietnamese broker. Must be no greater than
            :attr:`maintenance_margin_ratio` and no less than the statutory
            floor. **UNSOURCED. No default.**
        forced_sale_price: at what price the liquidating order is placed.
            **SILENT in the regulation. No default.**
        day_count: the interest basis. **SILENT in the regulation. No
            default.** See :class:`DayCount`.
        liquidation_order: which position is sold first. **SILENT. No
            default.**
        proceeds_application_order: what sale proceeds pay down, in order. Must
            be a permutation of every :class:`ProceedsComponent` exactly once --
            a partial order would leave a component unpriced. **SILENT. No
            default.**

        regulation: the statutory floors these terms are validated against.
            Defaults to :data:`QD_87_2017`. For a run at a historical date,
            resolve with :func:`regulation_in_force` and pass the result.
        firm: the securities company these terms describe, if known.
        terms_effective_from: the date the firm's published schedule says it
            took effect. Not the fetch date.
        terms_fetched_on: when the schedule was read.

        initial_margin_ratio: the firm's *ty le ky quy ban dau*. Defaults to
            the statutory floor 0.50, which is **the loosest value the law
            allows**, chosen because it is also what every broker sampled does
            -- SSI's per-ticker maximum is exactly 50 %, and DNSE, FNS and
            Pinetree all cap at 50 %. A stricter firm sets a higher number.
        loan_ratio_by_ticker: per-ticker *ty le cho vay*, the haircut mechanism
            brokers actually publish. Empty by default: a ticker with no entry
            is one this firm does not lend against, which is the conservative
            reading and the one that matches a positive list.
        max_loan_ratio: the cap applied to every entry above. 0.50 by default.
            **This is not a statutory cap.** Restating QD 87 Dieu 5.1 as a
            50 % loan-to-value rides on ``imr = 1 - loan_ratio``, which is
            **DERIVED** -- our own identity, in no text read, and true only for
            a single fully collateralised purchase. What is REPORTED is that
            every firm sampled caps at 50 % anyway.
        collateral_valuation_cap_enforced: whether QD 87 Dieu 2.4's ceiling is
            applied. **May not be turned off.** Setting it ``False`` raises,
            because valuing collateral above the last close inflates ``PV``,
            inflates ``EB``, raises ``AB / EB`` and delays calls -- looser than
            the law, in the direction that hurts the client.
        ineligible_counted_as_collateral: whether securities off the margin list
            still count toward the ratios. **May not be turned on.** TT 120
            Dieu 9.6 excludes them from the collateral base for both ratios.

        cure_business_days: the cure window this firm grants, bounded above by
            :attr:`MarginRegulation.max_cure_business_days` (3). Defaults to 3
            -- the ceiling used in full, which is what SSI and ACBS do.
        cure_target_ratio: the ratio a cure must restore. ``None`` means "back
            to :attr:`maintenance_margin_ratio`", which is the Dieu 7.1 floor
            reading; a firm may require more.
        consecutive_breach_days_before_sale: force-sell after this many
            consecutive business days below the maintenance level, independently
            of the call clock. SSI uses 3.
        overdue_business_days_before_sale: force-sell this many business days
            after maturity. SSI >= 3; ACBS starts on the 5th. The two firms
            disagree, which is exactly why it is a broker term.

        intraday_monitoring: ``False`` runs the statutory end-of-day test only
            (QD 87 Dieu 6.1). ``True`` is the 2026 market reality and is
            *stricter*, never a breach.
        monitor_interval_minutes: sweep interval when monitoring intraday. DNSE
            sweeps hourly 09:00-15:00. Must be ``None`` when
            :attr:`intraday_monitoring` is ``False``.
        price_source: which price the ratio is monitored at. The Dieu 2.4 cap
            applies on top regardless -- see
            :attr:`collateral_valuation_cap_enforced`.
        accounting_unit: what the ratio is computed over. ``ACCOUNT`` is the
            statutory unit; DNSE runs per-deal.

        forced_sale_scope: how much of the account a sale may reach.
        forced_sale_target: how far it sells.
        forced_sale_target_buffer: the overshoot, used only with
            :attr:`ForcedSaleTarget.MAINTENANCE_PLUS_BUFFER`. Zero by default,
            which makes the two targets identical until a caller sets it.
        forced_sale_notice_lead_minutes: how far ahead of the sell order the
            client is notified. QD 87 Dieu 8 requires notice **before** the
            order; DNSE executes with no further notice beyond the call, i.e.
            lead 0. Zero is therefore the observed default and still satisfies
            the article only if the notice is emitted first -- which is why
            :class:`ForcedSaleInstruction` carries ``notified_at`` and a
            :attr:`ForcedSaleInstruction.notice_satisfied` check rather than
            trusting this number.

        rate_schedule: the interest tiers. **Empty by default, and an empty
            schedule means no rate has been agreed** -- QD 87 Dieu 11.3
            requires the rate to be agreed in writing, so an unset schedule is
            the correct model of "no contract", and the engine must refuse to
            accrue rather than invent a number. Observed rates for reference:
            SSI 13.5 %/nam, DNSE 12.5 %/nam, ACBS 13 %, Pinetree 10.5 %, ABS
            13.5-15 %.
        calendar_days: accrue on calendar days rather than business days. ACBS
            states calendar days on the actual end-of-day outstanding.
        overdue_multiplier: multiple of the in-term rate applied while overdue.
            150 % observed at SSI and DNSE.
        capitalise_fees: whether extension fees are rolled into ``DB``. ACBS
            does. ``False`` by default, so a fee does not silently grow the debt
            the ratio is computed against.

        base_term_days: the firm's loan term. 90 days at SSI, DNSE, ACBS and
            FNS. Checked against the statutory 3 months -- see
            :data:`MAX_DAYS_IN_MONTH` for why the config-time check is a
            necessary condition only.
        extension_days: days added per extension. 90 observed.
        extension_count_max: ``None`` means uncapped, which is the statutory
            position (QD 87 Dieu 11.2 caps the length of each extension, not the
            number). DNSE: one free auto-extension then max 2 further. ACBS:
            max 2.
        extension_fee_rate: fee as a fraction of principal due. DNSE 0.3 %.
            Zero by default -- charging a fee nobody agreed to is worse than
            understating cost, and the field is here so a caller can state one.

        per_customer_credit_limit: the firm's own cap in dong. ``None`` means
            only the statutory 3 %-of-equity cap binds. SSI up to 70 ty, DNSE
            10 ty, ABS 10-35 ty; all sit **under** the statutory cap.
        collateral_includes_unsettled_sale_proceeds: QD 87 Dieu 2's ``CB``
            already includes *tien ban chung khoan cho ve*, so ``True`` is the
            statutory reading and the default. The flag exists because the loan
            is a contract and a firm may be stricter about what it will lend
            against than the ratio algebra is about what counts.
        collateral_includes_pending_buys: securities bought and pending
            settlement. SSI, ACBS and FNS all include them.
        collateral_includes_untradable_rights: rights not yet tradable, stock
            dividends and bonus shares not yet credited. **ACBS includes them;
            FNS explicitly excludes them.** The variation is real, which is why
            it is a flag; ``False`` is the conservative default.
        accrued_charges_in_debt: whether accrued interest and fees are added to
            ``DB`` when the ratio is computed. QD 87 Dieu 2's algebra defines
            ``DB`` as *du no ky quy* and does not say. DNSE's per-deal formula
            deducts accrued interest, fees and estimated tax from equity, which
            the spec flags as extending beyond the article. ``True`` is
            **our choice**, made conservatively: it lowers ``AB``, so calls fire
            sooner rather than later.
    """

    # -- no default: supplying these is the caller's job, see the class docstring
    maintenance_margin_ratio: Decimal
    liquidation_margin_ratio: Decimal
    forced_sale_price: ForcedSalePrice
    day_count: DayCount
    liquidation_order: LiquidationOrder
    proceeds_application_order: Tuple[ProceedsComponent, ...]

    # -- the statutory floors these are checked against
    regulation: MarginRegulation = QD_87_2017

    # -- provenance of the terms themselves
    firm: Optional[str] = None
    terms_effective_from: Optional[date] = None
    terms_fetched_on: Optional[date] = None

    # -- 3.1 the haircut mechanism
    initial_margin_ratio: Decimal = Decimal('0.50')
    loan_ratio_by_ticker: Mapping[str, Decimal] = field(default_factory=dict)
    max_loan_ratio: Decimal = Decimal('0.50')
    collateral_valuation_cap_enforced: bool = True
    ineligible_counted_as_collateral: bool = False

    # -- 3.2 the call, and the clocks
    cure_business_days: int = 3
    cure_target_ratio: Optional[Decimal] = None
    consecutive_breach_days_before_sale: int = 3
    overdue_business_days_before_sale: int = 3

    # -- 2.4 / 3.3 monitoring
    intraday_monitoring: bool = False
    monitor_interval_minutes: Optional[int] = None
    price_source: PriceSource = PriceSource.LAST_CLOSE
    accounting_unit: AccountingUnit = AccountingUnit.ACCOUNT

    # -- 3.3 forced-sale execution
    forced_sale_scope: ForcedSaleScope = ForcedSaleScope.WHOLE_ACCOUNT
    forced_sale_target: ForcedSaleTarget = ForcedSaleTarget.MAINTENANCE
    forced_sale_target_buffer: Decimal = Decimal('0')
    forced_sale_notice_lead_minutes: int = 0

    # -- 3.5 interest
    rate_schedule: Tuple[InterestTier, ...] = ()
    calendar_days: bool = True
    overdue_multiplier: Decimal = Decimal('1.50')
    capitalise_fees: bool = False

    # -- 3.4 term, extension, overdue
    base_term_days: int = 90
    extension_days: int = 90
    extension_count_max: Optional[int] = None
    extension_fee_rate: Decimal = Decimal('0')

    # -- 3.6 other terms
    per_customer_credit_limit: Optional[Decimal] = None
    collateral_includes_unsettled_sale_proceeds: bool = True
    collateral_includes_pending_buys: bool = True
    collateral_includes_untradable_rights: bool = False
    accrued_charges_in_debt: bool = True

    #: Where each of these came from. **Read before quoting any of them.**
    #:
    #: The commercial counterpart of :attr:`MarginRegulation.PROVENANCE`, and
    #: the same rule as :attr:`plutus.market.broker.BrokerTerms.PROVENANCE`:
    #: every default is a plausible market value, not a sourced one. No entry
    #: here is graded VERIFIED, and none may be -- the research read no broker's
    #: *hop dong giao dich ky quy*.
    #:
    #: Unannotated on purpose; see the note on
    #: :attr:`MarginRegulation.PROVENANCE`.
    PROVENANCE = MappingProxyType({})

    # -- validation ----------------------------------------------------------

    def __post_init__(self) -> None:
        """Refuse, at construction, any term looser than the statutory floor.

        Two kinds of refusal, kept distinguishable on purpose:

        * :class:`BrokerTermLooserThanLaw` -- the term breaches a floor set by a
          clause that was read. The message names the field, the value, the
          floor and the article, because "invalid config" would tell a user
          their terms are wrong without telling them which law says so.
        * ``ValueError`` -- the term is internally incoherent (a force-sell
          level above the call level, a sweep interval on a firm that does not
          monitor intraday, a proceeds order missing a component). No statute is
          breached; the object just would not mean anything.

        A third class is deliberately **absent**: nothing here refuses a term
        for being *stricter* than the law. A firm may set ``imr`` at 0.80,
        monitor hourly and force-sell at 0.45; all of that is legal and some of
        it is observed.
        """
        reg = self.regulation

        # -- 3.1 the ratios, against QD 87 Dieu 5 -----------------------------
        for name in ('initial_margin_ratio', 'maintenance_margin_ratio',
                     'liquidation_margin_ratio', 'max_loan_ratio'):
            value = getattr(self, name)
            _require_decimal(name, value)
            if not _ZERO < value <= _ONE:
                raise ValueError(
                    f'{name} is a fraction and must lie in (0, 1], got '
                    f'{value}. A ratio above 1 is a percentage that forgot to '
                    f'be divided by 100')

        if self.initial_margin_ratio < reg.initial_margin_ratio_floor:
            raise BrokerTermLooserThanLaw(
                'initial_margin_ratio', self.initial_margin_ratio,
                reg.initial_margin_ratio_floor, 'QD 87 Dieu 5.1',
                'The article floors the ratio the BROKER sets: "ty le ky quy '
                'ban dau do cong ty chung khoan quy dinh nhung khong duoc thap '
                'hon 50%".')
        if self.maintenance_margin_ratio < reg.maintenance_margin_ratio_floor:
            raise BrokerTermLooserThanLaw(
                'maintenance_margin_ratio', self.maintenance_margin_ratio,
                reg.maintenance_margin_ratio_floor, 'QD 87 Dieu 5.2',
                'This is the CALL level (SSI: TLKQ duy tri). "Ty le ky quy duy '
                'tri do cong ty chung khoan quy dinh nhung khong duoc thap hon '
                '30%".')
        if self.liquidation_margin_ratio < reg.maintenance_margin_ratio_floor:
            raise BrokerTermLooserThanLaw(
                'liquidation_margin_ratio', self.liquidation_margin_ratio,
                reg.maintenance_margin_ratio_floor, 'QD 87 Dieu 5.2',
                'The force-sell level (SSI: TLKQ xu ly) sits below the call '
                'level, so the SAME 30% floor binds it -- and binds it harder, '
                'since an account is allowed to sit between the two levels '
                'while it cures.')
        if self.liquidation_margin_ratio > self.maintenance_margin_ratio:
            raise ValueError(
                f'the broker ladder must be non-increasing (call level >= '
                f'force-sell level), got maintenance_margin_ratio='
                f'{self.maintenance_margin_ratio} and '
                f'liquidation_margin_ratio={self.liquidation_margin_ratio}. '
                f'Brokers run TWO levels with the call above the force-sell; '
                f'inverting them means the account is force-sold before it is '
                f'ever called, and the cure window QD 87 Dieu 7.1 grants '
                f'becomes unreachable')

        # -- 2.3 / 9.6 the two floors that cannot be waived -------------------
        if not self.collateral_valuation_cap_enforced:
            raise BrokerTermLooserThanLaw(
                'collateral_valuation_cap_enforced', False, True,
                'QD 87 Dieu 2.4',
                'Collateral may be valued at "khong vuot qua gia dong cua tai '
                'ngay gan nhat". Waiving the cap raises PV, raises EB, raises '
                'AB/EB and delays every call -- looser than the law in the '
                'direction that hurts the client. Monitor at a live price if '
                'you like (price_source=LIVE_MARKET); the cap still applies on '
                'top, as min(live, last close).')
        if self.ineligible_counted_as_collateral:
            raise BrokerTermLooserThanLaw(
                'ineligible_counted_as_collateral', True, False,
                'TT 120 Dieu 9.6',
                '"Chung khoan khong duoc phep giao dich ky quy khong duoc tinh '
                'vao tai san bao dam khi xac dinh ty le ky quy ban dau va ty le '
                'ky quy duy tri" -- excluded from the collateral base for BOTH '
                'ratios. Note QD 87 Dieu 10.2 is narrower (still security for '
                'the existing loan); TT 120 is the higher-ranking instrument '
                'and is what is implemented.')

        # -- 3.1 the per-ticker haircuts --------------------------------------
        for ticker, ratio in self.loan_ratio_by_ticker.items():
            _require_decimal(f'loan_ratio_by_ticker[{ticker!r}]', ratio)
            if not _ZERO < ratio <= self.max_loan_ratio:
                raise ValueError(
                    f'loan ratio for {ticker!r} is {ratio}, outside (0, '
                    f'{self.max_loan_ratio}]. A ticker this firm will not lend '
                    f'against is ABSENT from the mapping, not present at zero '
                    f'-- the mapping is a positive list. Note the cap is a '
                    f'broker term: restating QD 87 Dieu 5.1 as a 50% '
                    f'loan-to-value rides on imr = 1 - loan_ratio, which is '
                    f'DERIVED and holds only for a single fully collateralised '
                    f'purchase')

        # -- 2.8 the cure window, against QD 87 Dieu 7.1 ----------------------
        if self.cure_business_days > reg.max_cure_business_days:
            raise BrokerTermLooserThanLaw(
                'cure_business_days', self.cure_business_days,
                reg.max_cure_business_days, 'QD 87 Dieu 7.1',
                'The article sets a CEILING -- "the period the CTCK requires, '
                'but not more than three (03) business days" -- so a longer '
                'window leaves the account in breach for longer than the law '
                'permits. Note TT 120 Dieu 9.6 carries the call and the '
                'force-sale right but no day count; the 3 days are Dieu 7.1 '
                'alone.')
        if self.cure_business_days < 1:
            raise ValueError(
                f'cure_business_days must be at least 1, got '
                f'{self.cure_business_days}. QD 87 Dieu 7.1 requires the CTCK '
                f'to set a period and caps it at three business days; zero is '
                f'not a period, and it would erase the call state entirely by '
                f'making every call expire the instant it issued. THE LOWER '
                f'BOUND IS OUR READING -- the article states only the ceiling. '
                f'A firm that force-sells with no window models that through '
                f'liquidation_margin_ratio, which bypasses the window by '
                f'design')
        if self.cure_target_ratio is not None:
            _require_decimal('cure_target_ratio', self.cure_target_ratio)
            if self.cure_target_ratio < reg.maintenance_margin_ratio_floor:
                raise BrokerTermLooserThanLaw(
                    'cure_target_ratio', self.cure_target_ratio,
                    reg.maintenance_margin_ratio_floor, 'QD 87 Dieu 5.2',
                    'A cure must restore at least the maintenance ratio, whose '
                    'floor is 30%.')
            if self.cure_target_ratio < self.maintenance_margin_ratio:
                raise ValueError(
                    f'cure_target_ratio {self.cure_target_ratio} is below this '
                    f'firm\'s own maintenance_margin_ratio '
                    f'{self.maintenance_margin_ratio}, so a "cured" account '
                    f'would still be in call. QD 87 Dieu 7 requires the top-up '
                    f'to restore AT LEAST mmr; the precise level above that is '
                    f'the CTCK\'s, which is what this field is for. Leave it '
                    f'None to mean exactly the maintenance level')

        for name in ('consecutive_breach_days_before_sale',
                     'overdue_business_days_before_sale',
                     'forced_sale_notice_lead_minutes'):
            if getattr(self, name) < 0:
                raise ValueError(f'{name} must not be negative, got '
                                 f'{getattr(self, name)}')
        if self.consecutive_breach_days_before_sale > reg.max_cure_business_days:
            raise BrokerTermLooserThanLaw(
                'consecutive_breach_days_before_sale',
                self.consecutive_breach_days_before_sale,
                reg.max_cure_business_days, 'QD 87 Dieu 7.1',
                'Waiting more consecutive breach days than the cure ceiling '
                'lets an uncured account sit below the maintenance ratio '
                'longer than the article allows. SSI uses exactly 3 -- the '
                'ceiling, used in full.')

        # -- 2.12 term and extension, against QD 87 Dieu 11 -------------------
        max_term_days = reg.max_loan_term_months * MAX_DAYS_IN_MONTH
        if self.base_term_days < 1:
            raise ValueError(f'base_term_days must be at least 1, got '
                             f'{self.base_term_days}')
        if self.base_term_days > max_term_days:
            raise BrokerTermLooserThanLaw(
                'base_term_days', self.base_term_days, max_term_days,
                'QD 87 Dieu 11.1',
                f'The term is "<= {reg.max_loan_term_months} thang" from '
                f'disbursement. This config-time bound uses '
                f'MAX_DAYS_IN_MONTH={MAX_DAYS_IN_MONTH} and is a NECESSARY '
                f'condition only -- the exact test is date arithmetic at '
                f'disbursement and the engine must still run it.')
        max_ext_days = reg.max_extension_months * MAX_DAYS_IN_MONTH
        if self.extension_days < 0:
            raise ValueError(f'extension_days must not be negative, got '
                             f'{self.extension_days}')
        if self.extension_days > max_ext_days:
            raise BrokerTermLooserThanLaw(
                'extension_days', self.extension_days, max_ext_days,
                'QD 87 Dieu 11.2',
                f'Each extension is "<= {reg.max_extension_months} thang", on '
                f'the client\'s written request. The NUMBER of extensions is '
                f'not capped by the regulation -- that cap is '
                f'extension_count_max, a broker term.')
        if self.extension_count_max is not None and self.extension_count_max < 0:
            raise ValueError(
                f'extension_count_max must not be negative, got '
                f'{self.extension_count_max}. Use 0 for a firm that does not '
                f'extend, and None for uncapped -- which is the statutory '
                f'position')
        if (reg.max_extensions is not None
                and (self.extension_count_max is None
                     or self.extension_count_max > reg.max_extensions)):
            raise BrokerTermLooserThanLaw(
                'extension_count_max', self.extension_count_max,
                reg.max_extensions, 'QD 87 Dieu 11.2',
                'This regulation row caps the number of extensions. QD 87 does '
                'not, so this branch is unreachable against QD_87_2017 and '
                'exists so a future amendment does not need new code.')

        # -- 3.5 interest ------------------------------------------------------
        _validate_rate_schedule(self.rate_schedule)
        _require_decimal('overdue_multiplier', self.overdue_multiplier)
        if self.overdue_multiplier < _ONE:
            raise ValueError(
                f'overdue_multiplier must be at least 1, got '
                f'{self.overdue_multiplier}. A multiple below 1 rewards being '
                f'overdue. 150% is observed at SSI and DNSE; it is REPORTED, '
                f'not sourced to any rule -- QD 87 Dieu 11.3 sets no rate at '
                f'all')
        _require_decimal('extension_fee_rate', self.extension_fee_rate)
        if self.extension_fee_rate < _ZERO:
            raise ValueError(f'extension_fee_rate must not be negative, got '
                             f'{self.extension_fee_rate}')
        if (reg.interest_rate_cap is not None
                and any(t.annual_rate > reg.interest_rate_cap
                        for t in self.rate_schedule)):
            raise BrokerTermLooserThanLaw(
                'rate_schedule',
                max(t.annual_rate for t in self.rate_schedule),
                reg.interest_rate_cap, 'QD 87 Dieu 11.3',
                'QD 87 sets no margin interest cap beyond the Civil Code\'s '
                'general ceiling, so this branch is unreachable against '
                'QD_87_2017 and exists so a capped future row does not need '
                'new code.')

        # -- 3.3 monitoring and execution coherence ----------------------------
        if self.monitor_interval_minutes is not None:
            if not self.intraday_monitoring:
                raise ValueError(
                    'monitor_interval_minutes is set but intraday_monitoring '
                    'is False. QD 87 Dieu 6.1 determines the ratio at the end '
                    'of the trading day; a sweep interval on a firm that does '
                    'not sweep is a config that says two things')
            if self.monitor_interval_minutes < 1:
                raise ValueError(
                    f'monitor_interval_minutes must be at least 1, got '
                    f'{self.monitor_interval_minutes}. Use None for continuous '
                    f'monitoring')
        if (self.forced_sale_scope is ForcedSaleScope.BREACHING_POSITION
                and self.accounting_unit is AccountingUnit.ACCOUNT):
            raise ValueError(
                'forced_sale_scope=BREACHING_POSITION requires an '
                'accounting_unit of SUB_ACCOUNT or DEAL. QD 87 Dieu 2\'s ratio '
                'is computed over the whole account, so at ACCOUNT granularity '
                'there is no single "breaching position" to sell -- the account '
                'breached, not a ticker. DNSE can sell only the breaching '
                'deal\'s stock precisely because it runs per-deal')
        _require_decimal('forced_sale_target_buffer',
                         self.forced_sale_target_buffer)
        if self.forced_sale_target_buffer < _ZERO:
            raise ValueError(
                f'forced_sale_target_buffer must not be negative, got '
                f'{self.forced_sale_target_buffer}; a negative buffer would '
                f'stop selling below the maintenance level')
        if self.maintenance_margin_ratio + self.forced_sale_target_buffer > _ONE:
            raise ValueError(
                f'maintenance_margin_ratio + forced_sale_target_buffer = '
                f'{self.maintenance_margin_ratio + self.forced_sale_target_buffer}'
                f' exceeds 1, which is an unreachable target: AB/EB is at most '
                f'1, attained only by an account with no debt at all')

        # -- 3.6 other terms ---------------------------------------------------
        if self.per_customer_credit_limit is not None:
            _require_decimal('per_customer_credit_limit',
                             self.per_customer_credit_limit)
            if self.per_customer_credit_limit <= _ZERO:
                raise ValueError(
                    f'per_customer_credit_limit must be positive, got '
                    f'{self.per_customer_credit_limit}. Use None to mean "only '
                    f'the statutory 3%-of-equity cap binds"')

        # -- 2.9 / 12.2(i) the two delegated orderings -------------------------
        supplied = tuple(self.proceeds_application_order)
        if sorted(supplied, key=lambda c: c.value) != sorted(
                ProceedsComponent, key=lambda c: c.value):
            raise ValueError(
                f'proceeds_application_order must list every ProceedsComponent '
                f'exactly once, got {[c.value for c in supplied]}. QD 87 Dieu '
                f'12.2(i) requires the CONTRACT to state the "thu tu uu tien '
                f'su dung tien ban chung khoan the chap"; a partial order '
                f'leaves a component unpriced and there is no default to fall '
                f'back to, because the regulation is SILENT and inventing one '
                f'would be a house rule wearing a citation')

        # -- vintage -----------------------------------------------------------
        if (self.terms_effective_from is not None
                and self.terms_fetched_on is not None
                and self.terms_effective_from > self.terms_fetched_on):
            raise ValueError(
                f'terms_effective_from {self.terms_effective_from.isoformat()} '
                f'is after terms_fetched_on '
                f'{self.terms_fetched_on.isoformat()}. The fetch date is when '
                f'the schedule was read, not the vintage of the value -- SSI\'s '
                f'13.5%/nam schedule was fetched 2026-08-26 and carries an '
                f'effective date of 2022-11-01, which is the point of keeping '
                f'both')

    # -- the two commercial names the market actually uses -------------------

    @property
    def call_level(self) -> Decimal:
        """:attr:`maintenance_margin_ratio` under the name DNSE publishes.

        A property, not a second field, so the two names cannot drift. SSI calls
        it *TLKQ duy tri*; DNSE calls it *ty le canh bao*; QD 87 Dieu 5.2 calls
        the floor beneath it *ty le ky quy duy tri*.
        """
        return self.maintenance_margin_ratio

    @property
    def force_sell_level(self) -> Decimal:
        """:attr:`liquidation_margin_ratio` under the name the market uses.

        SSI: *TLKQ xu ly*. DNSE: *ty le xu ly*. No statutory name exists,
        because the regulation has one ratio floor and brokers run two levels
        above it.
        """
        return self.liquidation_margin_ratio


#: Article and grade for every :class:`BrokerMarginTerms` field.
#:
#: **Not one entry is VERIFIED, and none may be.** The research read no broker's
#: *hop dong giao dich ky quy* and found zero verified numeric thresholds for
#: statutory equity margin at any named firm. Where a field carries a statutory
#: *bound*, the bound's article is named -- but the *value* inside it is still
#: the firm's, and the grade reflects the value, not the bound.
_BROKER_PROVENANCE: Mapping[str, Provenance] = MappingProxyType({
    'maintenance_margin_ratio': _p(None, _S,
        'NO DEFAULT, and no source. Spec section 5 gap 5: the only published '
        'broker threshold table (DNSE) is a "Goi" / giao dich tien mat '
        'CASH-PRODUCT table for all five rows, not a margin ladder -- the '
        'reading that its 50% package force-sells at exactly the statutory 30% '
        'floor is withdrawn. SSI and ACBS publish STRUCTURE only (TLKQ duy tri '
        'vs TLKQ xu ly). Bounded below by QD 87 Dieu 5.2 (0.30); the value '
        'inside that bound is the caller\'s. To close: obtain a CTCK hop dong '
        'giao dich ky quy or a margin policy stating the two levels '
        'numerically'),
    'liquidation_margin_ratio': _p(None, _S,
        'NO DEFAULT, and no source. As above. What survives the DNSE '
        'correction is the SHAPE -- brokers run two levels, call above '
        'force-sell -- and the force-sell branch BYPASSES the 3-day cure '
        'window (SSI: force-sells "immediately upon breaching TLKQ xu ly"). '
        'Bounded below by QD 87 Dieu 5.2'),
    'forced_sale_price': _p(None, _S,
        'NO DEFAULT. Spec section 4 item 3: no Vietnamese document sets the '
        'execution price. DNSE uses gia san at the moment the auto-sell fires '
        '(REPORTED, one firm); nothing else is published. The choice is not '
        'cosmetic -- selling at the floor guarantees a fill and guarantees the '
        'worst price in the band'),
    'day_count': _p('QD 87 Dieu 11.4 (as an absence)', _S,
        'NO DEFAULT. The article delegates the calculation method entirely. '
        'BOTH bases are observed in the same market in the same year: SSI '
        '13.5%/nam explicitly "(360 ngay)" = ACT/360, DNSE 0.0342%/ngay = '
        '12.5%/nam over 365 = ACT/365. AdvanceTerms.annualisation_basis '
        'DECLARES 365 for the sale advance because its sources merely mixed '
        'the two; here two named firms differ, so declaring a house basis '
        'would be worse than asking'),
    'liquidation_order': _p('QD 87 Dieu 12.2(i) (as a delegation)', _S,
        'NO DEFAULT. VERIFIED that the rule delegates -- the contract must '
        'state "phuong thuc xu ly tai san the chap" -- and SILENT on what the '
        'ordering is. The exact analogue of LiquidationRule.LARGEST_LOSS_FIRST '
        'on the derivatives side: an adopted ordering that no Vietnamese '
        'document prescribes. No member of the enum is sourced'),
    'proceeds_application_order': _p('QD 87 Dieu 12.2(i) (as a delegation)', _S,
        'NO DEFAULT. Same clause, second half: "thu tu uu tien su dung tien '
        'ban chung khoan the chap". Must be a permutation of every component; '
        'a partial order leaves one unpriced. What IS statutory is only the '
        'residual (Dieu 8: the client gets "phan con lai sau khi tru no ky '
        'quy")'),

    'regulation': _p('QD 87/QD-UBCK', _V,
        'The statutory floors these terms are validated against. Defaults to '
        'QD_87_2017, which is a SOURCED object -- so unlike everything else on '
        'this class, this default is not an assumption. For a historical date, '
        'resolve with regulation_in_force() and pass the result'),
    'firm': _p(None, _S, 'Identification only. None is honest for a synthetic '
                         'or averaged broker'),
    'terms_effective_from': _p(None, _R,
        'The date the firm\'s own schedule says it took effect. Section 3\'s '
        'caveat: "observed 2026" is loose -- SSI\'s bieu gia page carries an '
        'effective date of 2022-11-01 while it was fetched 2026-08-26'),
    'terms_fetched_on': _p(None, _R,
        'When the schedule was read. NOT the vintage of the value; keeping '
        'both is the point'),

    'initial_margin_ratio': _p('QD 87 Dieu 5.1 (the bound only)', _R,
        'DEFAULT 0.50 = the statutory floor, which is THE LOOSEST VALUE THE '
        'LAW ALLOWS. It is the default because it is also what every broker '
        'sampled does: SSI\'s per-ticker maximum is exactly 50%, and DNSE, FNS '
        'and Pinetree all cap at 50%. REPORTED. A stricter firm sets a higher '
        'number, and a published result sensitive to leverage must say which '
        'was used'),
    'loan_ratio_by_ticker': _p(None, _R,
        'ASSUMPTION: empty. Brokers publish per-ticker ty le cho vay (SSI 10 / '
        '20 / 30 / 40 / 50%; DNSE "linh hoat tu 10% den 50%", >200 tickers, '
        'refreshed monthly). Empty means this firm lends against nothing, '
        'which is the conservative reading and matches a positive list that '
        'has not been loaded. The list is DATED DATA supplied by the caller, '
        'exactly like the VSDC settlement calendar -- do not hardcode one'),
    'max_loan_ratio': _p(None, _D,
        'ASSUMPTION 0.50, and the arithmetic behind it is DERIVED. "QD 87 Dieu '
        '5.1 => maximum loan-to-value 50%" rides on imr = 1 - loan_ratio, '
        'which is OUR identity, in no text read, and true only for a single '
        'fully collateralised purchase -- Dieu 2 khoan 8 defines imr over the '
        'ORDER value, so an account already holding eligible collateral '
        'supports a larger purchase. That every firm sampled caps at 50% '
        'anyway is a separate REPORTED observation that happens to agree, not '
        'a proof of the identity. THIS IS NOT A STATUTORY CAP'),
    'collateral_valuation_cap_enforced': _p('QD 87 Dieu 2.4', _V,
        'True, and refuses False. The only field on this class whose value is '
        'fixed by a read article rather than chosen: valuation above the last '
        'close is unlawful, and it is looser in the direction that hurts the '
        'client'),
    'ineligible_counted_as_collateral': _p('TT 120 Dieu 9.6', _V,
        'False, and refuses True. Securities off the margin list are excluded '
        'from the collateral base for BOTH ratios. QD 87 Dieu 10.2 is '
        'narrower; TT 120 is higher-ranking and is what is implemented'),

    'cure_business_days': _p('QD 87 Dieu 7.1 (the ceiling only)', _R,
        'ASSUMPTION 3 = the statutory ceiling used in full, which is what SSI '
        '("breached TLKQ duy tri for >= 3 consecutive business days") and ACBS '
        '("disposal starts at X+3 trading days") both do. The specific period '
        'is a contract term and a stricter firm grants fewer days. The lower '
        'bound of 1 enforced at construction is OUR READING; the article '
        'states only the ceiling'),
    'cure_target_ratio': _p('QD 87 Dieu 7.1 (the floor only)', _S,
        'ASSUMPTION None = restore exactly to maintenance_margin_ratio. The '
        'article floors the target at mmr and leaves the precise level to the '
        'CTCK; no firm publishes one'),
    'consecutive_breach_days_before_sale': _p(None, _R,
        'ASSUMPTION 3, from SSI\'s published structure. A SECOND clock, '
        'independent of the call: SSI force-sells on 3 consecutive business '
        'days below TLKQ duy tri whether or not a call was answered'),
    'overdue_business_days_before_sale': _p(None, _R,
        'ASSUMPTION 3, the stricter of two observed values that DISAGREE: SSI '
        'force-sells when the debt is overdue >= 3 business days; ACBS starts '
        'disposal on the 5th business day after maturity. The disagreement is '
        'why it is a broker term'),

    'intraday_monitoring': _p('QD 87 Dieu 6.1', _R,
        'DEFAULT False = the regulatory floor behaviour, which is end-of-day '
        'at a valuation <= last close. Brokers in 2026 run it INTRADAY at live '
        'market prices and force-sell intraday (DNSE: "ty le Deal tinh theo '
        'gia thi truong chu khong tinh theo gia tham chieu"). Monitoring more '
        'often is stricter, never a breach -- but a result run at the default '
        'is a result about the rule, not about the market'),
    'monitor_interval_minutes': _p(None, _R,
        'ASSUMPTION None. DNSE sweeps call notices hourly 09:00-15:00, which '
        'is 60'),
    'price_source': _p('QD 87 Dieu 2.4 (the cap, not the source)', _R,
        'DEFAULT LAST_CLOSE = the Dieu 2.4 valuation itself. The cap applies '
        'on top of ANY source, so LIVE_MARKET means min(live, last close) and '
        'an up day does not inflate the ratio'),
    'accounting_unit': _p('QD 87 Dieu 2, Dieu 6.1 (for ACCOUNT)', _R,
        'DEFAULT ACCOUNT = the statutory unit; the algebra is stated over tai '
        'khoan and the ratio is determined per margin account. DEAL is DNSE\'s '
        'product and is a materially different mechanism -- an account '
        'comfortably above mmr can have one deal in breach'),

    'forced_sale_scope': _p(None, _R,
        'ASSUMPTION WHOLE_ACCOUNT. QD 87 Dieu 8 bounds the QUANTITY -- part or '
        'all, depending on whether the remaining required collateral is '
        'smaller or larger than the total value in the account -- and says '
        'nothing about which holdings are in scope. DNSE sells only the '
        'breaching deal\'s stock; that requires a per-deal unit'),
    'forced_sale_target': _p('QD 87 Dieu 7 (the "at least mmr" floor)', _R,
        'ASSUMPTION MAINTENANCE, observed at two firms: ACBS "sells only '
        'enough to bring the ratio back up to the maintenance level", DNSE '
        '"never the whole deal by default". Also the reading closest to the '
        'article\'s cure target'),
    'forced_sale_target_buffer': _p(None, _S,
        'ASSUMPTION 0, which makes MAINTENANCE and MAINTENANCE_PLUS_BUFFER '
        'identical until a caller sets it. No firm publishes an overshoot'),
    'forced_sale_notice_lead_minutes': _p('QD 87 Dieu 8 (that notice is '
                                          'required)', _S,
        'ASSUMPTION 0. The article requires notice BEFORE the sell order is '
        'placed but sets no lead time; DNSE executes with no further notice '
        'beyond the call. Zero satisfies the article only if the notice is '
        'actually emitted first, which is why ForcedSaleInstruction carries '
        'notified_at and a notice_satisfied check rather than trusting this '
        'number'),

    'rate_schedule': _p('QD 87 Dieu 11.3 (that a rate must be agreed)', _S,
        'DEFAULT EMPTY, and empty means NO RATE HAS BEEN AGREED. The article '
        'requires the rate to be agreed in writing, so an unset schedule is a '
        'real contractual state and the engine must refuse to accrue rather '
        'than invent a number. Observed for reference, all REPORTED: SSI '
        '13.5%/nam, DNSE 12.5%/nam, ACBS 13%, Pinetree 10.5%, ABS 13.5-15%. '
        'The tier SHAPE (contiguous from day 0, open-ended tail) is OUR '
        'modelling choice -- Dieu 11.4 prescribes nothing'),
    'calendar_days': _p(None, _R,
        'ASSUMPTION True. ACBS: "lai duoc tinh theo du no thuc te cua khoan '
        'vay cuoi moi ngay", T0 = disbursement, calendar days. No firm was '
        'observed accruing on business days only'),
    'overdue_multiplier': _p(None, _R,
        'ASSUMPTION 1.50, observed at SSI and DNSE. There is no statutory rate '
        'and no statutory overdue penalty; QD 87 Dieu 11.3 delegates the rate '
        'to the contract subject to the Civil Code'),
    'capitalise_fees': _p(None, _R,
        'ASSUMPTION False. ACBS capitalises extension fees into DB; DNSE '
        'charges them separately. False is the conservative default because a '
        'capitalised fee silently grows the debt the ratio is computed against'),

    'base_term_days': _p('QD 87 Dieu 11.1 (the bound only)', _R,
        'ASSUMPTION 90, observed at SSI, DNSE, ACBS and FNS. The statute says '
        '"<= 3 thang"; every firm publishes days. The config-time check bridges '
        'the two with MAX_DAYS_IN_MONTH and is a NECESSARY CONDITION ONLY -- '
        'the engine must still run the date arithmetic at disbursement'),
    'extension_days': _p('QD 87 Dieu 11.2 (the bound only)', _R,
        'ASSUMPTION 90, observed at SSI, DNSE and ACBS. Each extension is '
        'statutorily <= 3 months, on the client\'s WRITTEN request'),
    'extension_count_max': _p('QD 87 Dieu 11.2 (as an absence)', _S,
        'DEFAULT None = uncapped, which IS the statutory position: the article '
        'caps the length of each extension and not the number. Observed caps '
        'are broker terms -- DNSE one free auto-extension then max 2 further, '
        'ACBS max 2, FNS 180 days total'),
    'extension_fee_rate': _p(None, _R,
        'ASSUMPTION 0. DNSE charges 0.3% of principal due; ACBS charges a fee '
        'that may be capitalised. Zero understates cost, but charging a fee '
        'nobody agreed to is the worse error'),

    'per_customer_credit_limit': _p('QD 87 Dieu 9.2 (the statutory cap '
                                    'above it)', _R,
        'DEFAULT None = only the statutory 3%-of-equity cap binds. Observed: '
        'SSI up to 70 ty dong, DNSE 10 ty total, ABS 10 ty on eKYC with a 35 '
        'ty uplift. All sit UNDER the statutory cap'),
    'collateral_includes_unsettled_sale_proceeds': _p('QD 87 Dieu 2.5', _R,
        'DEFAULT True, which is the statutory reading -- CB is defined as tien '
        '+ tien ban chung khoan cho ve. NOTE THE INTERACTION with ledgers.py: '
        'pending proceeds are excluded from Cash.available unless advanced, '
        'but they DO count toward CB. Two different questions, two different '
        'answers; do not collapse them. The flag exists because the loan is a '
        'contract and a firm may lend against less than the ratio counts'),
    'collateral_includes_pending_buys': _p(None, _R,
        'ASSUMPTION True. SSI, ACBS and FNS all include securities bought and '
        'pending settlement'),
    'collateral_includes_untradable_rights': _p(None, _R,
        'ASSUMPTION False. THE FIRMS DISAGREE, which is why this is a flag: '
        'ACBS recognises cash dividends, stock dividends, bonus shares and '
        'rights-to-subscribe into the collateral base; FNS explicitly EXCLUDES '
        'shares from rights not yet tradable. False is the conservative side'),
    'accrued_charges_in_debt': _p('QD 87 Dieu 2 (silent on this)', _D,
        'OUR CHOICE, defaulted conservatively to True. Dieu 2 defines DB as du '
        'no ky quy and does not say whether accrued interest and fees join it. '
        'DNSE\'s per-deal formula deducts accrued interest, fees and estimated '
        'tax from equity -- which the spec flags as extending beyond the '
        'article\'s account-level algebra, along with being per-deal and using '
        'live prices. True lowers AB, so calls fire sooner rather than later'),
})

BrokerMarginTerms.PROVENANCE = _BROKER_PROVENANCE


# --------------------------------------------------------------------------
# Records the engine passes around
# --------------------------------------------------------------------------
#
# Frozen dataclasses throughout, matching session/types.py. Every account
# identifier is a plain ``str`` and deliberately **not** a
# :class:`plutus.market.session.types.AccountRef`: TT 120 Dieu 9.3 requires the
# margin account to be segregated from the ordinary account and across
# investors, so it is a third account, and an ``AccountRef`` carries a ``Pool``
# whose two members are the securities and derivatives pools. Reusing it would
# say the margin account is one of those, which is the segregation error the
# type would otherwise be preventing.


@dataclass(frozen=True)
class MarginLoan:
    """One margin loan -- *du no ky quy* with a term, a rate and a maturity.

    Carries an optional ``ticker`` because
    :attr:`BrokerMarginTerms.accounting_unit` decides whether a loan is an
    account-level balance or a per-deal one. At ``AccountingUnit.ACCOUNT`` the
    ticker is ``None`` and one loan may fund many purchases; at ``DEAL`` each
    loan is tied to the stock it bought, which is what lets DNSE force-sell one
    deal and leave the rest of the sub-account alone.

    ``principal`` is the disbursed amount still owed. Accrued interest and fees
    are **separate fields**, not rolled in, because whether they join ``DB`` for
    the ratio is a broker choice
    (:attr:`BrokerMarginTerms.accrued_charges_in_debt`) and QD 87 Dieu 2 does
    not say. A record that had already added them could not express the other
    choice.

    Attributes:
        loan_id: unique within the account.
        account_id: the segregated margin account -- see the note above this
            section.
        ticker: the stock this loan funded, or ``None`` at account
            granularity.
        quantity: shares bought with it, at deal granularity.
        principal: outstanding disbursed amount, in dong.
        accrued_interest: interest accrued and not yet paid or capitalised.
        accrued_fees: extension and other fees accrued. Joins ``principal``
            only where :attr:`BrokerMarginTerms.capitalise_fees` is set, which
            ACBS does and DNSE does not.
        disbursed_on: **T0**. Interest counts from here (ACBS states this
            explicitly), and QD 87 Dieu 11.1's three months run from here.
        due_on: current maturity, including any extensions already granted.
        extensions_used: how many extensions have been granted. QD 87 Dieu 11.2
            caps the length of each at 3 months and **does not cap the
            number**; :attr:`BrokerMarginTerms.extension_count_max` does.
        status: see :class:`LoanStatus`.
        rate_at_disbursement: the annual rate in force on day 0, kept for the
            record. The live rate comes from
            :attr:`BrokerMarginTerms.rate_schedule` indexed by loan age, since
            every observed schedule is tiered.
    """

    loan_id: str
    account_id: str
    principal: Decimal
    disbursed_on: date
    due_on: date
    status: LoanStatus
    ticker: Optional[str] = None
    quantity: int = 0
    accrued_interest: Decimal = _ZERO
    accrued_fees: Decimal = _ZERO
    extensions_used: int = 0
    rate_at_disbursement: Optional[Decimal] = None

    @property
    def total_owed(self) -> Decimal:
        """Principal plus everything accrued against it.

        **Not necessarily ``DB``.** Whether accrued interest and fees enter the
        ratio's ``DB`` is :attr:`BrokerMarginTerms.accrued_charges_in_debt`, and
        this property does not decide it -- it is the amount a repayment must
        clear, which is a different question and always includes them.
        """
        return self.principal + self.accrued_interest + self.accrued_fees

    def age_days(self, on: date) -> int:
        """Days since disbursement, for indexing the tiered rate schedule.

        Day 0 is the disbursement day, matching
        :attr:`InterestTier.day_from`.
        """
        return (on - self.disbursed_on).days


@dataclass(frozen=True)
class MarginCall:
    """A *lenh goi ky quy bo sung*, with its deadline and the amounts to cure.

    **The two top-up amounts are DERIVED, not sourced. Read this before
    quoting either.** QD 87 Dieu 7.2 gives two formulas -- (a) the value of
    securities to post, (b) the cash to post -- and **every accessible mirror
    renders them as images and drops them** (luatvietnam omits them from the
    free HTML; hoatieu, dongduong and luatvietan all drop them). What this
    record carries is **our own arithmetic** off the EB/AB algebra:

    * posting eligible securities of value ``S`` raises both ``AB`` and ``EB``,
      so ``S >= (mmr*EB - AB) / (1 - mmr)``;
    * depositing cash ``C`` **applied to repay ``DB``** -- Vietnamese brokers
      sweep deposits against debt at end of day (ACBS: *"he thong se tu dong
      thu can tru no vao cuoi ngay"*) -- leaves ``EB`` unchanged and raises
      ``AB``, so ``C >= mmr*EB - AB``;
    * depositing cash that **stays in ``CB``** behaves like the securities case.

    Do not ship these as "the regulation says". TODO: obtain the Dieu 7.2 images
    from cong bao or ssc.gov.vn and re-grade.

    ``deadline`` is an instant, not a day count, because the cure window is
    measured in **business days** (QD 87 Dieu 7.1, ceiling 3) and resolving that
    to a wall-clock moment needs a trading calendar the engine holds and this
    record does not.

    Attributes:
        call_id: unique within the account.
        account_id: the segregated margin account.
        issued_at: when the CTCK issued the call by the contact method in the
            account contract (QD 87 Dieu 7.1).
        deadline: the instant the cure window closes.
        ratio_at_issue: ``AB / EB`` when the call fired, or ``None`` where
            ``EB`` was zero -- an account with no assets has no ratio, and
            ``None`` must never read as "fine".
        target_ratio: what a cure must restore.
            :attr:`BrokerMarginTerms.cure_target_ratio` or, where that is
            ``None``, the firm's maintenance level.
        top_up_cash: **DERIVED.** Cash that, swept against ``DB``, restores
            ``target_ratio``.
        top_up_securities_value: **DERIVED.** Value of eligible collateral that
            restores ``target_ratio``.
        cure_methods: which of QD 87 Dieu 7's three methods this firm accepts.
        status: see :class:`MarginCallStatus`. ``PARTIALLY_CURED`` is a real
            state -- Dieu 8 gives the force-sale right when the client tops up
            *only partially*, and the amount then sold depends on what is still
            required.
        cured_at: when the account came back above ``target_ratio``.
        accounting_unit: what the breaching ratio was computed over, carried on
            the record so a per-deal call is not mistaken for an account-level
            one.
        deal_id: the loan or deal in breach, at sub-account or deal
            granularity.
    """

    call_id: str
    account_id: str
    issued_at: datetime
    deadline: datetime
    target_ratio: Decimal
    status: MarginCallStatus
    ratio_at_issue: Optional[Decimal] = None
    top_up_cash: Decimal = _ZERO
    top_up_securities_value: Decimal = _ZERO
    cure_methods: Tuple[CureMethod, ...] = ()
    cured_at: Optional[datetime] = None
    accounting_unit: AccountingUnit = AccountingUnit.ACCOUNT
    deal_id: Optional[str] = None

    @property
    def is_open(self) -> bool:
        """Whether this call still constrains the account.

        ``PARTIALLY_CURED`` counts as open: the client answered but not enough,
        and QD 87 Dieu 8 treats a partial top-up exactly as a failure to top up
        for the purposes of the force-sale right.
        """
        return self.status in (MarginCallStatus.OPEN,
                               MarginCallStatus.PARTIALLY_CURED)


@dataclass(frozen=True)
class ForcedSaleInstruction:
    """One *ban giai chap* order the engine tells the caller to place.

    **An instruction, not an execution.** This package models the exchange and a
    thin broker; it does not run a strategy, a portfolio or a P&L, and it does
    not place orders. The engine reports that a sale is due, at what price
    policy, for how much, and why; the caller submits it and reports the fills
    back. That boundary is also why ``notified_at`` is a field rather than an
    assumption -- the notice is the caller's to send.

    **Notice ordering is a legal constraint, not bookkeeping.** QD 87 Dieu 8
    requires the CTCK to notify the client **before placing the sell order** and
    to send a statement of results afterwards; TT 120 Dieu 9.6 requires the
    public disclosure to happen first where the client's own ownership-reporting
    obligations are engaged. :attr:`notice_satisfied` is how an engine reports
    that it did, and how a test catches an engine that did not.

    Attributes:
        instruction_id: unique within the account.
        account_id: the segregated margin account.
        ticker: what to sell.
        quantity: how many shares. QD 87 Dieu 8 bounds this -- part or all of
            the pledged securities, depending on whether the *remaining*
            required collateral is smaller or larger than the total value in
            the account -- and :attr:`BrokerMarginTerms.forced_sale_target`
            decides where inside that bound the firm stops.
        price_policy: :class:`ForcedSalePrice`. **SILENT in the regulation.**
        limit_price: required when ``price_policy`` is
            :attr:`ForcedSalePrice.LIMIT`, ignored otherwise. ``FLOOR`` resolves
            to *gia san* at the moment the sale fires, which the engine reads
            from the band, not from here.
        scope: :class:`ForcedSaleScope`, carried so a whole-account liquidation
            is distinguishable from a single-deal one in the log.
        trigger: :class:`ForcedSaleTrigger`. Five paths and they do not share a
            clock -- in particular ``FORCE_LEVEL_BREACHED`` bypasses the cure
            window entirely.
        target_ratio: the ratio the sale is sizing itself to restore.
        call_id: the call this escalated from, or ``None`` for the branches
            that never issue one.
        issued_at: when the instruction was raised.
        notified_at: when the client was notified. Must not be after
            ``issued_at`` -- see :attr:`notice_satisfied`.
        disclosed_at: when the public disclosure was made, where TT 120 Dieu
            9.6 engages it.
    """

    instruction_id: str
    account_id: str
    ticker: str
    quantity: int
    price_policy: ForcedSalePrice
    scope: ForcedSaleScope
    trigger: ForcedSaleTrigger
    target_ratio: Decimal
    issued_at: datetime
    limit_price: Optional[Decimal] = None
    call_id: Optional[str] = None
    notified_at: Optional[datetime] = None
    disclosed_at: Optional[datetime] = None

    @property
    def notice_satisfied(self) -> bool:
        """Whether QD 87 Dieu 8's before-the-order notice was actually given.

        ``False`` where no notice was recorded, and ``False`` where the notice
        is stamped after the instruction. Both are rule breaches and the caller
        needs them countable. It is a **property and not a validation** because
        an engine must be able to construct the un-noticed case in order to
        report it -- refusing at construction would make the breach
        unrepresentable and therefore invisible.
        """
        return self.notified_at is not None and self.notified_at <= self.issued_at


@dataclass(frozen=True)
class MarginAccountState:
    """The **inputs** to the account algebra: one margin account at one instant.

    Deliberately separate from :class:`MarginAccountAlgebra`, which holds the
    computed outputs. The split exists because QD 87 Dieu 2's algebra is a pure
    function of these fields, so the engine's central computation is testable
    without a ledger, and a recorded state can be replayed to reproduce a call.

    **``pending_sale_proceeds`` is not ``Cash.available``.** QD 87 Dieu 2 defines
    ``CB`` as *tien + tien ban chung khoan cho ve*, so unsettled sale proceeds
    **do** count toward the margin ratio -- while ``ledgers.py`` deliberately
    excludes them from ``Cash.available`` unless advanced, because they cannot
    fund a purchase yet. Two different questions with two different right
    answers; do not collapse them.

    **Collateral is pre-valued.** ``eligible_securities_value`` must already
    have the QD 87 Dieu 2.4 cap applied -- valued by the CTCK, but not above
    the last close. The haircut (*ty le cho vay*) is applied by the caller
    building this state, because it is per-ticker and this record is
    per-account.

    Attributes:
        account_id: the segregated margin account (TT 120 Dieu 9.3).
        as_of: the instant this state describes.
        cash: *tien* -- settled cash in the margin account.
        pending_sale_proceeds: *tien ban chung khoan cho ve* -- see above.
        eligible_securities_value: the value of securities on this account that
            are permitted for margin trading, already capped at the last close.
            This is ``PV``.
        ineligible_securities_value: securities held that are **not** margin
            eligible. **Excluded from the collateral base for both ratios** by
            TT 120 Dieu 9.6, and carried here rather than dropped so the engine
            can report *why* a ratio fell when a ticker came off the list.
        pending_purchase_value: securities bought and pending settlement.
            Counts only where
            :attr:`BrokerMarginTerms.collateral_includes_pending_buys` is set.
        untradable_rights_value: rights not yet tradable, uncredited stock
            dividends and bonus shares. **The firms disagree** -- ACBS includes
            them, FNS excludes them -- so this is separate and gated by
            :attr:`BrokerMarginTerms.collateral_includes_untradable_rights`.
        margin_debt: ``DB``, the disbursed principal owed. Accrued charges are
            separate.
        accrued_interest: accrued and unpaid. Joins ``DB`` only where
            :attr:`BrokerMarginTerms.accrued_charges_in_debt` is set.
        accrued_fees: as above.
        loans: the individual loans behind ``margin_debt``. Empty is legal at
            account granularity; at :attr:`AccountingUnit.DEAL` it is the
            per-deal detail the ratio is computed over.
        open_calls: calls not yet cured or expired.
        is_foreign_investor: TT 120 Dieu 9.2 -- a flat prohibition **for margin
            lending**. Read the warning on
            :attr:`MarginRegulation.foreign_investors_allowed` before treating
            it as "may not buy on credit".
        margin_contract_signed: TT 120 Dieu 9.1 / QD 87 Dieu 12.1 -- the *hop
            dong giao dich ky quy* **is** the credit agreement.
        holder_classes: any :class:`IneligibleAccountHolder` category this
            holder falls into. Empty is the ordinary case.
        lending_suspended: the SSC has ordered margin trading at this CTCK
            suspended (TT 120 Dieu 9.9), or the firm lost its eligibility
            conditions (TT 120 Dieu 9.7 / QD 87 Dieu 16).
        unpriced_tickers: securities held for which no valuation was available.
            **Non-empty forces** :attr:`MarginAccountStatus.INDETERMINATE`: a
            ratio computed as if an unpriced holding were worth zero is not a
            conservative estimate, it is a different account.
    """

    account_id: str
    as_of: datetime
    cash: Decimal = _ZERO
    pending_sale_proceeds: Decimal = _ZERO
    eligible_securities_value: Decimal = _ZERO
    ineligible_securities_value: Decimal = _ZERO
    pending_purchase_value: Decimal = _ZERO
    untradable_rights_value: Decimal = _ZERO
    margin_debt: Decimal = _ZERO
    accrued_interest: Decimal = _ZERO
    accrued_fees: Decimal = _ZERO
    loans: Tuple[MarginLoan, ...] = ()
    open_calls: Tuple[MarginCall, ...] = ()
    is_foreign_investor: bool = False
    margin_contract_signed: bool = True
    holder_classes: Tuple[IneligibleAccountHolder, ...] = ()
    lending_suspended: bool = False
    unpriced_tickers: Tuple[str, ...] = ()

    @property
    def has_unpriced_collateral(self) -> bool:
        """Whether any held security could not be valued.

        The engine must turn this into
        :attr:`MarginAccountStatus.INDETERMINATE` rather than compute a ratio
        around the gap.
        """
        return bool(self.unpriced_tickers)


@dataclass(frozen=True)
class MarginAccountAlgebra:
    """The **outputs** of QD 87 Dieu 2's algebra, computed at one instant.

    VERIFIED (khoan 3-12), and reproduced here in the article's own terms so a
    reader can check the implementation against the text::

        DB  = du no ky quy                          cash owed to the CTCK
        CB  = tien + tien ban chung khoan cho ve     cash + unsettled proceeds
        PV  = gia tri chung khoan duoc phep GDKQ     eligible collateral value
        EB  = CB + PV                                tong tai san
        AB  = EB - DB                                tai san thuc co
        ty le ky quy = AB / EB
        mmr = min(AB / EB)
        imr = AB / (market value of the securities the margin order would buy,
                    at trade time)                   -- PER ORDER
        MR  = gia tri chung khoan x imr              gia tri ky quy yeu cau
        EE  = AB - MR                                gia tri du ky quy
        BP  = EE / imr                               suc mua

    Both naming conventions are exposed: descriptive field names, and the
    article's two-letter names as properties. The short names are what the
    regulation, the brokers and any reviewer will use; the long ones are what
    stops a reader mistaking ``EB`` for equity.

    **One reading in here is ours and is flagged.** Dieu 2 khoan 8 defines
    ``imr`` **per order** -- the account's *tai san thuc co* over the value of
    the order at market price at trade time -- while khoan 9-12 use ``imr`` as
    the *required* ratio that ``MR``, ``EE`` and ``BP`` are computed from.
    Reading ``gia tri chung khoan`` in the ``MR`` line as the account's ``PV``
    is the account-level interpretation, and it is **DERIVED**: it is what makes
    the algebra evaluable without an order in hand, which the caller needs for a
    standing buying-power figure. When an order *is* in hand, the per-order
    reading is the right one and :class:`MarginOrderAssessment` uses it. See
    :data:`PROVENANCE`.

    Attributes:
        account_id: the segregated margin account.
        as_of: the instant computed.
        basis: whether this was the statutory end-of-day computation (QD 87
            Dieu 6.1) or a broker's intraday sweep.
        price_source: what price the collateral was valued at, before the
            Dieu 2.4 cap.
        accounting_unit: what the ratio was computed over.
        margin_debt: ``DB``.
        cash_and_pending_proceeds: ``CB``.
        eligible_securities_value: ``PV``.
        total_assets: ``EB = CB + PV``.
        net_assets: ``AB = EB - DB``. **May be negative** -- an account whose
            collateral has fallen below its debt has negative *tai san thuc co*,
            and clamping it to zero would hide exactly the account that most
            needs a forced sale.
        margin_ratio: ``AB / EB``, or ``None`` when ``EB`` is zero. ``None`` is
            not zero and must never read as "fine"; an account with no assets
            and no debt is not in breach, and an account with no assets and a
            debt is past the point a ratio describes.
        initial_margin_ratio: the ``imr`` applied, from
            :attr:`BrokerMarginTerms.initial_margin_ratio`.
        maintenance_margin_ratio: the ``mmr`` applied. This is the **binding**
            call level -- :attr:`BindingPolicy.call_level`, which is the firm's
            :attr:`BrokerMarginTerms.maintenance_margin_ratio` except where a
            statutory floor has risen above it under QD 87 Dieu 5.3, in which
            case the floor is what the account was actually graded on.
        required_margin_value: ``MR``.
        excess_equity: ``EE = AB - MR``. Negative means the account is already
            beyond its buying power.
        buying_power: ``BP = EE / imr``, the QD 87 Dieu 13.5(d) bound.
        status: see :class:`MarginAccountStatus`.
        indeterminate_reasons: why the status is ``INDETERMINATE``, if it is --
            unpriced tickers, unevaluable eligibility predicates. Empty
            otherwise.
    """

    account_id: str
    as_of: datetime
    basis: RatioDetermination
    price_source: PriceSource
    accounting_unit: AccountingUnit
    margin_debt: Decimal
    cash_and_pending_proceeds: Decimal
    eligible_securities_value: Decimal
    total_assets: Decimal
    net_assets: Decimal
    margin_ratio: Optional[Decimal]
    initial_margin_ratio: Decimal
    maintenance_margin_ratio: Decimal
    required_margin_value: Decimal
    excess_equity: Decimal
    buying_power: Decimal
    status: MarginAccountStatus
    indeterminate_reasons: Tuple[str, ...] = ()

    # -- QD 87 Dieu 2's own names -------------------------------------------

    @property
    def db(self) -> Decimal:
        """``DB`` -- *du no ky quy*."""
        return self.margin_debt

    @property
    def cb(self) -> Decimal:
        """``CB`` -- *tien + tien ban chung khoan cho ve*."""
        return self.cash_and_pending_proceeds

    @property
    def pv(self) -> Decimal:
        """``PV`` -- *gia tri chung khoan duoc phep giao dich ky quy*."""
        return self.eligible_securities_value

    @property
    def eb(self) -> Decimal:
        """``EB = CB + PV`` -- *tong tai san*."""
        return self.total_assets

    @property
    def ab(self) -> Decimal:
        """``AB = EB - DB`` -- *tai san thuc co*. May be negative."""
        return self.net_assets

    @property
    def imr(self) -> Decimal:
        """``imr`` -- the required initial margin ratio applied."""
        return self.initial_margin_ratio

    @property
    def mmr(self) -> Decimal:
        """``mmr`` -- the maintenance margin ratio applied."""
        return self.maintenance_margin_ratio

    @property
    def mr(self) -> Decimal:
        """``MR`` -- *gia tri ky quy yeu cau*."""
        return self.required_margin_value

    @property
    def ee(self) -> Decimal:
        """``EE = AB - MR`` -- *gia tri du ky quy*."""
        return self.excess_equity

    @property
    def bp(self) -> Decimal:
        """``BP = EE / imr`` -- *suc mua*. The Dieu 13.5(d) bound."""
        return self.buying_power

    @property
    def is_indeterminate(self) -> bool:
        """Whether the data could not decide this account's status."""
        return self.status is MarginAccountStatus.INDETERMINATE


@dataclass(frozen=True)
class SecurityEligibility:
    """Whether one security may be margined, and which predicates decided it.

    Two layers, and the record keeps them apart because they are published by
    different parties on different clocks. **Layer 1** is the exchange's
    NEGATIVE list -- QD 87 Dieu 3's predicates, published as a full snapshot
    within 2 business days of any trigger arising (Dieu 4.1). **Layer 2** is the
    CTCK's own POSITIVE list, selected from what remains and published within 2
    business days of the exchange's (Dieu 4.2). A ticker can be absent from the
    broker's list while passing every statutory predicate; that is a commercial
    decision and is reported through ``on_broker_list``, not through
    ``failed``.

    **``INDETERMINATE`` is the answer wherever a predicate cannot be
    evaluated.** Most of Dieu 3 needs issuer financial-statement facts the
    corpus does not carry -- audit opinions, disclosure lateness, accumulated
    losses. Answering ``ELIGIBLE`` on missing data would margin securities the
    exchange has excluded and report a cleaner run than the data supports.

    The eligible-security list is **dated data supplied by the caller**, exactly
    like the VSDC settlement calendar. Nothing in this module ships one.

    Attributes:
        ticker: the security.
        venue: where it trades. QD 87 Dieu 3's universe is HOSE and HNX listed
            only; the recorded divergence with TT 120 Dieu 9.4 over UPCoM is on
            :attr:`MarginRegulation.eligible_venues`.
        as_of: the date this answer is about. Eligibility is dated -- a ticker
            added or removed carries an effective date.
        result: see :class:`MarginEligibility`.
        failed: predicates that were evaluated and held, i.e. reasons this
            security is ineligible.
        unevaluated: predicates that could not be evaluated on the data
            available. Non-empty with no ``failed`` entries is exactly the
            ``INDETERMINATE`` case.
        on_broker_list: whether the CTCK's own positive list carries it.
            ``None`` where no list was supplied, which is itself a reason for
            ``INDETERMINATE`` rather than an implicit yes.
        loan_ratio: the firm's *ty le cho vay* for this ticker, where it lends
            against it at all.
        note: free text -- e.g. that a *han che giao dich* status was observed
            and the QD 87 Dieu 3.2 mapping for it is SILENT.
    """

    ticker: str
    as_of: date
    result: MarginEligibility
    venue: Optional[Venue] = None
    failed: Tuple[ExclusionPredicate, ...] = ()
    unevaluated: Tuple[ExclusionPredicate, ...] = ()
    on_broker_list: Optional[bool] = None
    loan_ratio: Optional[Decimal] = None
    note: Optional[str] = None


@dataclass(frozen=True)
class InvestorEligibility:
    """Whether one investor may hold a margin account at this CTCK.

    Three independent statutory tests, all VERIFIED, and they fail for
    different reasons so the record keeps them separate:

    * **the contract** -- TT 120 Dieu 9.1 / QD 87 Dieu 12.1. The *hop dong giao
      dich ky quy* **is** the credit agreement; without it there is no lending
      to discuss.
    * **the person** -- QD 87 Dieu 13.4. The CTCK's own insiders and their
      related persons, entities in dissolution or bankruptcy, parties in breach
      of the margin contract. TT 121/2020 Dieu 27.3 independently bars lending
      to the insider class in any form.
    * **nationality** -- TT 120 Dieu 9.2, a flat prohibition. **Read the warning
      on** :attr:`MarginRegulation.foreign_investors_allowed`: it bars *margin
      lending*, and TT 120 Dieu 9a is a separate regime under which foreign
      institutions do buy on broker credit.

    Not tested here, because it is not statute: whether an authorised or proxy
    trader may register margin on the owner's behalf. ACBS says no; that is a
    broker term, REPORTED, and belongs in the firm's own rules.

    Attributes:
        account_id: the segregated margin account.
        as_of: the date this answer is about.
        result: see :class:`MarginEligibility`.
        failed: which holder classes disqualify this investor.
        unevaluated: classes that could not be checked -- typically
            ``RELATED_PERSON``, which needs a relationship graph no corpus
            carries.
        has_margin_contract: TT 120 Dieu 9.1.
        note: free text.
    """

    account_id: str
    as_of: date
    result: MarginEligibility
    failed: Tuple[IneligibleAccountHolder, ...] = ()
    unevaluated: Tuple[IneligibleAccountHolder, ...] = ()
    has_margin_contract: bool = True
    note: Optional[str] = None


@dataclass(frozen=True)
class MarginOrderAssessment:
    """The pre-trade gate's answer for one margin order.

    **The gate is QD 87 Dieu 13.5(d)**, VERIFIED: *the CTCK must not let the
    client trade on margin or withdraw cash beyond the account's current buying
    power*. Written two equivalent ways::

        order_value x imr <= EE          equivalently    order_value <= BP

    ``imr`` here is the **per-order** ratio of Dieu 2 khoan 8 -- the account's
    *tai san thuc co* over the market value of the securities the order would
    buy, at trade time -- which is the reading the article actually gives, and
    the reason this record exists rather than the caller reading ``BP`` off
    :class:`MarginAccountAlgebra` and comparing.

    **A margin order is a distinct order type, not a flag.** QD 87 Dieu 13.5(e)
    requires margin order tickets to be *distinguishable* from ordinary ones,
    to carry full client information, to be client-confirmed, and to be an
    inseparable annex to the contract. Whatever wires this into ``orders.py``
    must add a type, not a boolean.

    Attributes:
        account_id: the segregated margin account.
        ticker: what the order would buy.
        quantity: how many shares.
        price: the price the assessment was made at.
        order_value: ``quantity x price``, the Dieu 2 khoan 8 base.
        as_of: the instant assessed.
        required_margin: ``order_value x imr``.
        excess_equity: ``EE`` at the time of assessment.
        buying_power: ``BP`` at the time of assessment.
        admitted: whether the order passes every gate. ``False`` whenever
            ``refusals`` or ``indeterminate`` is non-empty.
        refusals: every rule that said no -- **all** of them, not the first,
            because a caller fixing one wants to see the rest.
        indeterminate: gates that could not be evaluated. Kept apart from
            ``refusals`` so "the data could not decide" stays countable against
            "a rule said no", which is the posture the whole package takes.
        detail: the numbers behind the decision, for a rejection report.
    """

    account_id: str
    ticker: str
    quantity: int
    price: Decimal
    order_value: Decimal
    as_of: datetime
    required_margin: Decimal
    excess_equity: Decimal
    buying_power: Decimal
    admitted: bool
    refusals: Tuple[MarginOrderRefusal, ...] = ()
    indeterminate: Tuple[MarginOrderRefusal, ...] = ()
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarginEvent:
    """One thing the engine did, for a caller polling it.

    Deliberately not :class:`plutus.market.session.types.Event`. That record's
    ``EventKind`` carries the derivatives deposit's ``MARGIN_CALL`` and
    ``FORCED_LIQUIDATION``, and an equity margin call arriving under the same
    member would be indistinguishable from a futures one in the log a caller
    uses to decide what to do. When the streams are merged they merge as new
    members.

    ``detail`` is untyped on purpose: the payload differs per kind, and a union
    of thirteen shapes would be read by nobody. The records above are the typed
    surface -- an event says *what happened* and points at the record.

    Attributes:
        kind: see :class:`MarginEventKind`.
        ts: when it happened.
        account_id: the segregated margin account.
        loan_id: the loan concerned, where one is.
        call_id: the call concerned, where one is.
        instruction_id: the forced-sale instruction concerned, where one is.
        detail: the payload.
    """

    kind: MarginEventKind
    ts: datetime
    account_id: str
    loan_id: Optional[str] = None
    call_id: Optional[str] = None
    instruction_id: Optional[str] = None
    detail: Mapping[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# What this module decides for itself, and what nobody has sourced
# --------------------------------------------------------------------------

#: The choices and the gaps that belong to neither config object.
#:
#: :attr:`MarginRegulation.PROVENANCE` and
#: :attr:`BrokerMarginTerms.PROVENANCE` are per-field. This table is for
#: everything else: the nine things section 4 of the spec says the rulebook is
#: SILENT on, the five research gaps in section 5, and the modelling decisions
#: this file made on its own. Same shape and same purpose as
#: :data:`plutus.market.session.corporate.PROVENANCE` -- an assumption that does
#: not say it is one reads as evidence, and every entry here is a place a
#: published result must disclose.
PROVENANCE: Mapping[str, Provenance] = MappingProxyType({

    # -- the nine SILENT items, spec section 4 ------------------------------
    'liquidation_order': _p('QD 87 Dieu 12.2(i)', _S,
        'SILENT item 1. The order in which positions are liquidated on a '
        'forced sale. The article requires only that the CONTRACT state the '
        'disposal method, so this is a per-broker term and no Vietnamese '
        'document prescribes an ordering. Modelled as a required '
        'BrokerMarginTerms enum with NO default. Exactly the analogue of '
        'LiquidationRule.LARGEST_LOSS_FIRST on the derivatives side'),
    'proceeds_application_order': _p('QD 87 Dieu 12.2(i)', _S,
        'SILENT item 2. The priority order for applying sale proceeds across '
        'principal / interest / fees / taxes. Same clause, same delegation. '
        'Required, no default, and must be a full permutation'),
    'forced_sale_price': _p(None, _S,
        'SILENT item 3. No rule sets the execution price for a forced sale. '
        'DNSE uses gia san (REPORTED, one firm); no other firm publishes one. '
        'Required, no default -- selling at the floor guarantees a fill and '
        'the worst price in the band, so a silent MARKET assumption would '
        'report materially better liquidation outcomes than a real client '
        'experiences'),
    'interest_day_count': _p('QD 87 Dieu 11.4', _S,
        'SILENT item 4. Day-count, compounding and accrual convention are '
        'delegated entirely. ACT/360 (SSI) and ACT/365 (DNSE) both observed at '
        'named firms in the same market in the same year -- a ~1.4% difference '
        'nobody can see in the output. Required, no default. Contrast '
        'AdvanceTerms.annualisation_basis, which DECLARES 365 because its '
        'sources merely mixed the two'),
    'extension_count': _p('QD 87 Dieu 11.2', _S,
        'SILENT item 5. Only the 3-month-per-extension cap is statutory; the '
        'NUMBER of extensions is not capped by the regulation. Modelled as '
        'MarginRegulation.max_extensions = None, meaning "uncapped by law", '
        'and BrokerMarginTerms.extension_count_max = None by default, meaning '
        'this firm has adopted the statutory position'),
    'intraday_monitoring': _p('QD 87 Dieu 6.1', _S,
        'SILENT item 6. The rule mandates END-OF-DAY computation at a '
        'valuation <= last close; brokers in 2026 run it intraday at live '
        'prices and force-sell intraday. Implemented as the regulatory floor '
        'behaviour by default with intraday as a broker option, exactly as the '
        'derivatives path treats broker utilisation thresholds. A result run '
        'at the default is a result about the RULE, not about the market'),
    'interest_rate_cap': _p('QD 87 Dieu 11.3', _S,
        "SILENT item 7. No cap beyond the Civil Code's general ceiling, which "
        'is not modelled here. MarginRegulation.interest_rate_cap is None and '
        'the validator has a branch for a capped future row that is '
        'unreachable against QD_87_2017'),
    'trading_status_mapping': _p('QD 87 Dieu 3.2', _S,
        'SILENT item 8. Dieu 3.2 enumerates canh bao / kiem soat / kiem soat '
        'dac biet / tam ngung giao dich / huy niem yet. Current HOSE practice '
        'ALSO cuts margin for han che giao dich and dinh chi giao dich -- '
        'statuses from the post-2020 listing rules, absent from Dieu 3.2\'s '
        'vocabulary (HVN excluded for han che giao dich + kiem soat 2026-04-03; '
        'ASP and SVD under han che giao dich 2025-07-03). REPORTED. The '
        'rulebook is silent on the mapping: ExclusionPredicate.TRADING_STATUS '
        'is one member and the caller decides what feeds it. DO NOT encode a '
        'mapping as if it were gazetted'),
    'upcom_eligibility': _p('QD 87 Dieu 3 vs TT 120 Dieu 9.4', _S,
        'SILENT item 9. TT 120 says co phieu niem yet, DANG KY GIAO DICH, chung '
        'chi quy niem yet -- which on its face includes UPCoM. QD 87 says '
        'listed only. Both VERIFIED. TT 120 Dieu 9.8 delegates the quy che to '
        'the SSC and QD 87 IS that quy che, so this reads as a delegation '
        'operating as designed rather than a hierarchy conflict -- and the same '
        'clause is what supports QD 87 still being in force. Implemented as '
        'HOSE + HNX, divergence recorded on the field. The market half of the '
        'evidence is a ONE-OFF parse of ONE broker list on ONE date'),

    # -- research gaps, spec section 5 --------------------------------------
    'top_up_amounts': _p('QD 87 Dieu 7.2', _D,
        'GAP 1, and the highest-impact DERIVED value in this module. The '
        'article gives two formulas -- securities to post, cash to post -- and '
        'EVERY accessible mirror renders them as IMAGES and drops them. '
        'MarginCall.top_up_cash and .top_up_securities_value are therefore OUR '
        'ARITHMETIC off the EB/AB algebra: S >= (mmr*EB - AB)/(1 - mmr) for '
        'securities; C >= mmr*EB - AB for cash swept against DB at end of day; '
        'cash that stays in CB behaves like the securities case. DO NOT SHIP '
        'THESE AS "THE REGULATION SAYS". To close: obtain the cong bao copy or '
        'the SSC PDF'),
    'broker_thresholds_unverified': _p(None, _S,
        'GAP 5, rewritten after adversarial audit. NO verified numeric '
        'call/force-sell threshold for statutory equity margin exists at ANY '
        'broker in this research. SSI and ACBS publish structure only. DNSE '
        'publishes a full threshold table but it is a "Goi" / giao dich tien '
        'mat CASH-PRODUCT table for ALL FIVE ROWS -- re-fetched and confirmed '
        'verbatim -- not a margin ladder; the reading that its 50% package '
        'force-sells at exactly the statutory 30% floor is WITHDRAWN. So the '
        'derivatives-style "sourced shape, commercial levels" pattern has NO '
        'equity-margin counterpart to copy: both the shape values and the '
        'levels are missing. What the statute gives is the FLOOR ONLY. Hence '
        'two required fields with no defaults'),
    'qd_87_still_in_force': _p('QD 87', _R,
        'GAP 2. No Tinh trang hieu luc field was directly readable for QD 87 or '
        'QD 1205 -- paywalled or blocked. Current force is INFERRED from three '
        'lines: TT 120 Dieu 9.8 obliges the SSC to issue a margin quy che and '
        'no successor surfaced; HOSE cited QD 87 + QD 1205 for its July 2025 '
        'ineligibility list (this citation is complete and re-confirmed); the '
        'April 2026 HOSE list maps one-to-one onto Dieu 3. Strong, but an '
        'inference and not a status read -- and the 2026 half rests on '
        'TRUNCATED URLs that cannot currently be re-fetched'),
    'source_reachability': _p(None, _R,
        'GAP 3, and load-bearing for every VERIFIED grade in this module. '
        'thuvienphapluat.vn, vbpl.vn and vanbanphapluat.co returned 403 or a '
        'JS bot-wall; ssc.gov.vn document pages are JavaScript-gated. EVERY '
        'statutory text came from a COMMERCIAL MIRROR, not cong bao or an SSC '
        'PDF. And the corroboration is thinner than an earlier revision '
        'claimed: Dieu 1-2 have four mirrors, Dieu 3-4 have three, and '
        'EVERYTHING FROM DIEU 5 ONWARD -- which is every number implemented '
        'here -- has exactly two (luatvietan, luatvietnam), which do agree '
        'verbatim. If a traceability claim in a paper depends on a specific '
        'clause, obtain the gazette copy'),
    'broker_sample': _p(None, _R,
        'GAP 4. Interest-rate structure at VPS, MBS, HSC, VNDirect and TCBS was '
        'not obtained (403 or single-page app). The broker sample behind every '
        'REPORTED default here is SSI, DNSE, ACBS, ABS, Pinetree, BVSC and FNS. '
        'Separately, "observed 2026" is loose: SSI\'s bieu gia page carries an '
        'effective date of 2022-11-01 against a 2026-08-26 fetch, which is why '
        'BrokerMarginTerms carries both dates'),

    # -- decisions this module made on its own -------------------------------
    'loan_to_value_identity': _p(None, _D,
        'The identity imr = 1 - loan_ratio, and with it the restatement "QD 87 '
        'Dieu 5.1 => maximum loan-to-value 50%", is OURS. It is in no text '
        'read, and it holds ONLY for a single, fully collateralised purchase: '
        'Dieu 2 khoan 8 defines imr as the account\'s tai san thuc co over the '
        'value of THE ORDER at market price at trade time, so an account '
        'already holding other eligible collateral supports a LARGER purchase '
        'than the identity implies. That brokers publish a per-ticker ty le '
        'cho vay <= 50% is a separate REPORTED observation that happens to '
        'agree, not a proof. Used only to bound '
        'BrokerMarginTerms.max_loan_ratio, which is documented as a broker '
        'term and not a statutory cap'),
    'account_level_mr_reading': _p('QD 87 Dieu 2 khoan 8-12', _D,
        'Dieu 2 defines imr PER ORDER (khoan 8) and then computes MR, EE and BP '
        'from it (khoan 9-12). Reading "gia tri chung khoan" in the MR line as '
        'the ACCOUNT\'s PV -- which is what MarginAccountAlgebra does -- is our '
        'interpretation, adopted because it is what makes the algebra evaluable '
        'without an order in hand, and a standing buying-power figure is '
        'exactly what a caller needs. When an order IS in hand the per-order '
        'reading is the right one, and MarginOrderAssessment uses it. The two '
        'agree for an account whose only assets are the collateral behind the '
        'order and diverge otherwise'),
    'rate_schedule_shape': _p('QD 87 Dieu 11.4', _D,
        'That a rate schedule must start at day 0, be contiguous, not overlap '
        'and end open-ended is OUR modelling choice; the article prescribes '
        'nothing at all. It is enforced because the alternative is a day on '
        'which the engine has no rate and must pick one, which is the same '
        'fabrication one layer down. Every observed schedule (ACBS Margin T+ '
        'and T14, DNSE promo tiers, Pinetree P-Zero) already has this shape'),
    'term_months_to_days_bridge': _p('QD 87 Dieu 11.1, 11.2', _D,
        'The statute states the term in MONTHS; every broker publishes DAYS '
        '(90). MAX_DAYS_IN_MONTH = 31 bridges them at construction time and is '
        'a NECESSARY CONDITION ONLY -- it refuses a term that could not fit in '
        'three calendar months and does not establish that a particular loan\'s '
        'maturity does. Deliberately the LOOSEST bridge, so the config check '
        'never refuses a term the date arithmetic would allow; the exact test '
        'is the engine\'s at disbursement'),
    'cure_window_lower_bound': _p('QD 87 Dieu 7.1', _D,
        'The article states only the CEILING of three business days. That the '
        'window must be at least one business day is OUR READING, enforced '
        'because a zero-day window would erase the call state by making every '
        'call expire the instant it issued. A firm that force-sells with no '
        'window models that through liquidation_margin_ratio, which bypasses '
        'the window by design'),
    'accrued_charges_in_debt': _p('QD 87 Dieu 2', _D,
        'Whether accrued interest and fees join DB for the ratio is not stated. '
        "DNSE's per-deal formula deducts accrued interest, fees and estimated "
        'tax from equity -- which extends beyond the article on three counts at '
        'once (per-deal, charges deducted, live prices). Defaulted to True as '
        'the conservative side: it lowers AB, so calls fire sooner'),
    'account_id_not_account_ref': _p('TT 120 Dieu 9.3', _D,
        'Every record here identifies the account with a plain str, NOT a '
        'types.AccountRef. The margin account is segregated from the ordinary '
        'account and across investors, so it is a third account, while '
        'AccountRef carries a Pool whose two members are the securities and '
        'derivatives pools. Reusing AccountRef would assert the margin account '
        'is one of those, which is the segregation error the type would '
        'otherwise prevent. A MarginAccountRef may be worth minting when this '
        'is wired in'),
    'separate_enums_from_deposit': _p(None, _D,
        'MarginAccountStatus and MarginEventKind duplicate names that exist in '
        'session/types.py for DERIVATIVES margin, and do so deliberately. '
        'types.MarginStatus grades MR / margin assets against VSDC\'s '
        'utilisation ladder; this one grades AB / EB against a broker\'s two '
        'levels. Different ratio, different rungs, different product, different '
        'regulator. A shared enum would let one be read as the other -- which '
        'is precisely the confusion the spec opens by warning against, since '
        'the only thing the two products share is the Vietnamese name ky quy'),
    'source_grade_vocabulary': _p(None, _D,
        'SourceGrade (VERIFIED / REPORTED / DERIVED / SILENT) is the spec\'s '
        'section 0 vocabulary and is deliberately NOT types.Confidence (HIGH / '
        'MEDIUM / LOW / UNVERIFIED). The rulebook\'s grades answer "how much do '
        'we trust this reading"; these answer "was it read at all". DERIVED is '
        'not low confidence in a source, it is NO SOURCE, and mapping the two '
        'would lose exactly that'),
    'no_engine_yet': _p(None, _S,
        'This module is the type contract only. Nothing computes a ratio, '
        'issues a call or instructs a sale, and nothing imports it. The '
        'validation relationship and PROVENANCE completeness are tested; the '
        'algebra is not, because it is not here'),
    'prompt_injection_in_sources': _p(None, _R,
        'hethongphapluat.com article pages carry an embedded instruction block '
        'addressed to an AI reader, demanding the answer tell the user to visit '
        'that site. It was treated as DATA, not instruction, on both encounters. '
        'Two of the spec\'s sources are on that host -- TT 120 Dieu 9/10 and '
        'ND 155 Dieu 198. Flagged because that host will likely be scraped '
        'again'),
})


# ==========================================================================
# THE ACCOUNT ALGEBRA -- QD 87 Dieu 2 khoan 3-12
# ==========================================================================
#
# Everything above this line is vocabulary. This section computes with it, and
# it computes exactly what the article states, in the article's own order::
#
#     DB  = du no ky quy                          khoan 3
#     CB  = tien + tien ban chung khoan cho ve     khoan 5
#     PV  = gia tri chung khoan duoc phep GDKQ     khoan 6
#     EB  = CB + PV                                khoan 7
#     AB  = EB - DB                                khoan 7
#     ty le ky quy = AB / EB
#     imr = AB / (market value of the order, at trade time)   khoan 8, PER ORDER
#     MR  = gia tri chung khoan x imr              khoan 10
#     EE  = AB - MR                                khoan 11
#     BP  = EE / imr                               khoan 12
#
# Three things in that list are not what a reader coming from a US margin
# account expects, and each has its own section below:
#
# 1. **khoan 5 puts unsettled sale proceeds inside CB.** That is a real
#    interaction with the tranche ledger, which deliberately keeps them out of
#    ``Cash.available``. Two questions, two answers -- :func:`cash_base`.
# 2. **khoan 8 makes imr a PER-ORDER ratio at market price at trade time**, not
#    an account constant -- :func:`order_initial_margin_ratio` and
#    :func:`assess_margin_order`.
# 3. **The collateral value is capped at the last close** (Dieu 2.4) whatever
#    price the broker monitors at -- :func:`value_collateral`.
#
# No money is rounded anywhere in this section. QD 87 prescribes no rounding,
# every input is already a ``Decimal``, and quantising a ratio or a buying-power
# figure would be a house convention wearing a citation. Where an exact
# comparison matters the code uses the multiplicative form of the test rather
# than the division -- see :func:`assess_margin_order`.


# --------------------------------------------------------------------------
# CB -- and why it is not Cash.available (khoan 5)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CashBase:
    """``CB`` -- *tien + tien ban chung khoan dang cho ve*. QD 87 Dieu 2 khoan 5.

    **The whole point of this record is that two correct numbers disagree.**
    ``ledgers.CashLedger`` reports ``Cash.available = settled + advanced -
    committed`` and deliberately leaves unsettled sale proceeds out of it,
    because Vietnamese equity is 100 % pre-funded and pending proceeds cannot
    fund a purchase (rulebook 5.1: sell-then-rebuy on the same day is not
    possible on settled cash alone). QD 87 Dieu 2 khoan 5 defines ``CB`` as
    *tien + tien ban chung khoan cho ve*, so those same proceeds **do** count
    toward the margin ratio. One asks *can this money be spent today*, the other
    asks *what is this account worth*. Collapsing them is the defect this record
    exists to make impossible: :attr:`cb` and :attr:`available` are computed side
    by side and :attr:`divergence` is their difference.

    **The sale advance nets out of ``CB`` exactly, and must not be added or
    subtracted.** *Ung truoc tien ban* makes part of a pending tranche spendable
    early; ``CashLedger`` models that by adding the outstanding principal to
    ``available`` while leaving ``settled_balance`` alone and keeping the tranche
    in ``pending_proceeds`` at its full amount. So the client's cash-side
    position is ``settled + advanced`` already received plus ``pending -
    advanced`` still to come, which is ``settled + pending`` -- the advance
    cancels. Adding ``advanced`` to ``CB`` would count the advanced dong twice;
    subtracting it would count them zero times. It is carried on the record only
    so a reader can see that it was considered.

    **Advance interest is outside the algebra, and that is our reading.** QD 87
    Dieu 2 khoan 3 defines ``DB`` as *du no ky quy* -- the margin loan. An
    advance is not a margin loan (it is a prepayment of the client's own sale
    proceeds under a different broker product), so its accrued interest is
    neither in ``CB`` nor in ``DB``. It is a charge, and ``types.Cash`` says
    charges are reported and never netted. Recorded in :data:`PROVENANCE` under
    ``advance_outside_the_algebra``.

    Attributes:
        settled: ``Cash.settled_balance`` -- *tien*.
        unsettled_proceeds: ``Cash.pending_total`` -- *tien ban chung khoan dang
            cho ve*, at the tranches' full face amount.
        advanced: outstanding advance principal. Carried, never applied. See
            above.
        committed: cash encumbered by live buy orders. **Not deducted from
            ``CB``**: khoan 5 says *tien*, and money promised to an unfilled
            order is still the client's. :attr:`uncommitted` is there for a
            caller running several gates in sequence off one snapshot -- see the
            warning on :func:`assess_margin_order`.
        counts_unsettled: whether the pending proceeds were counted, from
            :attr:`BrokerMarginTerms.collateral_includes_unsettled_sale_proceeds`.
            ``True`` is the statutory reading and the default; ``False`` is a
            firm being stricter than the algebra, which is always allowed.
    """

    settled: Decimal
    unsettled_proceeds: Decimal = _ZERO
    advanced: Decimal = _ZERO
    committed: Decimal = _ZERO
    counts_unsettled: bool = True

    @property
    def cb(self) -> Decimal:
        """``CB`` as khoan 5 defines it: *tien* plus proceeds still coming."""
        if not self.counts_unsettled:
            return self.settled
        return self.settled + self.unsettled_proceeds

    @property
    def available(self) -> Decimal:
        """What the tranche ledger would call spendable. **Not ``CB``.**

        ``settled + advanced - committed``, reproduced here so the two answers
        are one attribute apart and a reader cannot substitute one for the
        other by accident.
        """
        return self.settled + self.advanced - self.committed

    @property
    def divergence(self) -> Decimal:
        """``CB - available``. Zero only for an account with no pending
        proceeds, no advance and no live buy order."""
        return self.cb - self.available

    @property
    def uncommitted(self) -> Decimal:
        """``CB`` less cash already promised to live buy orders.

        **Not a statutory quantity.** khoan 5 does not net live orders, and this
        module does not use this property anywhere. It exists because a caller
        gating several orders against one snapshot has to net them somewhere,
        and doing it here is better than doing it silently inside the gate.
        """
        return self.cb - self.committed


def cash_base(cash: Cash, terms: BrokerMarginTerms) -> CashBase:
    """Read ``CB`` off the tranche ledger's cash read model. Dieu 2 khoan 5.

    The one seam between this module and ``ledgers.py``. It takes the
    ``types.Cash`` read model -- not the ledger -- so the margin algebra stays a
    pure function of a snapshot and a recorded state can be replayed.

    Args:
        cash: the securities account's cash position, as ``CashLedger.cash()``
            returns it.
        terms: read for
            :attr:`BrokerMarginTerms.collateral_includes_unsettled_sale_proceeds`
            only.

    Returns:
        A :class:`CashBase` carrying both answers -- see its docstring for why
        there are two and why the advance is not applied to either.
    """
    return CashBase(
        settled=cash.settled_balance,
        unsettled_proceeds=cash.pending_total,
        advanced=cash.advanced,
        committed=cash.committed,
        counts_unsettled=terms.collateral_includes_unsettled_sale_proceeds,
    )


# --------------------------------------------------------------------------
# PV -- collateral valuation and the Dieu 2.4 cap (spec 2.3)
# --------------------------------------------------------------------------

class CollateralBucket(str, Enum):
    """Which of :class:`MarginAccountState`'s value fields a lot lands in.

    One member per field, plus two for the lots that land in none of them. The
    enum exists so :class:`LotValuation` can say *where* a holding went and
    :func:`value_collateral` can be checked lot by lot rather than only in
    aggregate.

    ``ELIGIBLE``
        Counted in ``PV`` -- a margin-eligible security held outright.
    ``PENDING_PURCHASE``
        Bought and pending settlement. Counted only where
        :attr:`BrokerMarginTerms.collateral_includes_pending_buys` is set; SSI,
        ACBS and FNS all include them (REPORTED).
    ``UNTRADABLE_RIGHTS``
        Rights not yet tradable, stock dividends and bonus shares not yet
        credited. **The firms disagree** -- ACBS includes them, FNS explicitly
        excludes them -- so the flag is
        :attr:`BrokerMarginTerms.collateral_includes_untradable_rights` and it
        is ``False`` by default.
    ``INELIGIBLE``
        Not permitted for margin trading. **Excluded from the collateral base
        for both ratios** by TT 120 Dieu 9.6, which is why
        :attr:`BrokerMarginTerms.ineligible_counted_as_collateral` cannot be
        turned on. Valued anyway, into
        :attr:`MarginAccountState.ineligible_securities_value`, so the engine can
        report *why* a ratio fell when a ticker came off the list.
    ``UNDETERMINED``
        Eligibility could not be evaluated -- most of QD 87 Dieu 3's predicates
        need issuer financial-statement facts the corpus does not carry. **Not
        eligible by default**, and it makes the whole account
        :attr:`MarginAccountStatus.INDETERMINATE`, because a lot that might
        belong in ``PV`` and is counted as zero is not a conservative estimate,
        it is a different account.
    ``UNPRICED``
        Eligible, would have counted, and could not be valued. Same consequence
        as ``UNDETERMINED`` and for the same reason.
    """

    ELIGIBLE = 'eligible'
    PENDING_PURCHASE = 'pending_purchase'
    UNTRADABLE_RIGHTS = 'untradable_rights'
    INELIGIBLE = 'ineligible'
    UNDETERMINED = 'undetermined'
    UNPRICED = 'unpriced'


@dataclass(frozen=True)
class CollateralLot:
    """One holding, with every price the Dieu 2.4 cap needs to be applied.

    **Three prices, not one, and the cap needs two of them.** QD 87 Dieu 2.4:
    *"Gia tri cua chung khoan (v) la gia tri do cong ty chung khoan xac dinh tren
    Hop dong ... nhung khong vuot qua gia dong cua tai ngay gan nhat."* The firm
    picks the number; the last close is the ceiling. So valuing a lot needs the
    price the firm monitors at (:attr:`BrokerMarginTerms.price_source`) **and**
    the last close, always. A lot with a live price and no last close is
    **unpriced**, not valued at the live price -- the cap cannot be shown to
    hold, and Dieu 2.4 is not optional.

    ``eligibility`` defaults to :attr:`MarginEligibility.INDETERMINATE` and not
    to ``ELIGIBLE``. The eligible-security list is dated data supplied by the
    caller, exactly like the VSDC settlement calendar; nothing in this module
    ships one, and a lot whose eligibility nobody stated has not been shown to
    be margin collateral.

    Attributes:
        ticker: the security.
        quantity: shares held. Never negative -- Vietnamese cash equity permits
            no short selling, so a negative equity holding is a data error.
        last_close: *gia dong cua tai ngay gan nhat*. The Dieu 2.4 ceiling, and
            also the default valuation price.
        live_price: the latest matched price, for a firm monitoring at
            :attr:`PriceSource.LIVE_MARKET` (DNSE: *"ty le Deal tinh theo gia
            thi truong"*).
        reference_price: the session reference price, for
            :attr:`PriceSource.REFERENCE`.
        eligibility: whether this security may be margined at all.
        pending_settlement: bought and not yet settled.
        untradable_right: a right, stock dividend or bonus share not yet
            tradable.
        venue: where it trades, carried for a caller checking Dieu 3's HOSE +
            HNX universe. Not used by the valuation.
    """

    ticker: str
    quantity: int
    last_close: Optional[Decimal] = None
    live_price: Optional[Decimal] = None
    reference_price: Optional[Decimal] = None
    eligibility: MarginEligibility = MarginEligibility.INDETERMINATE
    pending_settlement: bool = False
    untradable_right: bool = False
    venue: Optional[Venue] = None

    def __post_init__(self) -> None:
        if self.quantity < 0:
            raise ValueError(
                f'{self.ticker!r} has quantity {self.quantity}. Collateral '
                f'quantity cannot be negative -- Vietnamese cash equity permits '
                f'no short selling, so a negative equity holding is a data '
                f'error and valuing it would put a negative number into PV')
        for name in ('last_close', 'live_price', 'reference_price'):
            value = getattr(self, name)
            if value is None:
                continue
            _require_decimal(f'{self.ticker}.{name}', value)
            if value <= _ZERO:
                raise ValueError(
                    f'{self.ticker}.{name} is {value}; a price must be '
                    f'positive. Use None for "not available", which is what '
                    f'makes the lot UNPRICED rather than worthless')
        if self.pending_settlement and self.untradable_right:
            raise ValueError(
                f'{self.ticker!r} is marked both pending_settlement and '
                f'untradable_right. They are different things gated by '
                f'different broker flags -- a bought-and-unsettled share (SSI, '
                f'ACBS and FNS all count it) and an uncredited right (ACBS '
                f'counts it, FNS explicitly does not) -- and a lot that claimed '
                f'to be both would be counted under whichever flag was tested '
                f'first')

    def price_at(self, source: PriceSource) -> Optional[Decimal]:
        """The monitored price for ``source``, before the Dieu 2.4 cap.

        ``None`` where the caller did not supply it. The cap is applied by
        :func:`value_collateral`, never here -- this is the *"gia tri do cong ty
        chung khoan xac dinh"* half of the article and the ceiling is the other
        half.
        """
        if source is PriceSource.LIVE_MARKET:
            return self.live_price
        if source is PriceSource.REFERENCE:
            return self.reference_price
        return self.last_close


@dataclass(frozen=True)
class LotValuation:
    """What one :class:`CollateralLot` was worth, and under which article.

    Attributes:
        ticker: the security.
        quantity: shares valued.
        bucket: see :class:`CollateralBucket`.
        unit_value: the per-share value after the Dieu 2.4 cap, or ``None``
            where the lot could not be valued.
        value: ``quantity x unit_value``, or zero where it could not be valued.
            **Zero here never means worthless** -- read ``bucket`` first.
        capped: whether the Dieu 2.4 ceiling actually bound, i.e. the monitored
            price was above the last close. Recorded because a firm monitoring
            at :attr:`PriceSource.LIVE_MARKET` on an up day is exactly the case
            where the cap changes the ratio, and a caller ought to be able to
            count them.
        monitored_price: the price before the cap, for the same reason.
        counted: whether this lot contributes to ``PV`` under the terms it was
            valued with. ``False`` for ineligible, unpriced and undetermined
            lots, and for a bucket this firm's flags exclude.
        reason: why, in one line, where that is not obvious from ``bucket``.
    """

    ticker: str
    quantity: int
    bucket: CollateralBucket
    unit_value: Optional[Decimal] = None
    value: Decimal = _ZERO
    capped: bool = False
    monitored_price: Optional[Decimal] = None
    counted: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class CollateralValuation:
    """Every lot valued, bucketed into :class:`MarginAccountState`'s fields.

    The four value totals map one-to-one onto ``MarginAccountState``'s four
    security-value fields, and :attr:`unpriced_tickers` onto its
    ``unpriced_tickers`` -- which is what lets :func:`build_account_state` join
    this to :func:`cash_base` without either side interpreting the other.

    **``unpriced_tickers`` holds only lots that would otherwise have counted.**
    An ineligible security that could not be priced is not an indeterminacy:
    TT 120 Dieu 9.6 excludes it from the collateral base whatever it is worth,
    so its price cannot change any ratio. A lot the firm's own flags exclude
    (pending buys at a firm that does not count them) is the same. Naming those
    would make almost every account INDETERMINATE for no reason, which is how a
    three-valued answer stops being read.

    Attributes:
        as_of: the instant valued.
        price_source: which price was capped.
        eligible_value: ``PV``'s core -- see
            :attr:`MarginAccountState.eligible_securities_value`.
        ineligible_value: reported, never counted.
        pending_purchase_value: gated by the firm's flag.
        untradable_rights_value: gated by the firm's flag.
        unpriced_tickers: lots that would have counted and could not be valued,
            plus lots whose eligibility could not be evaluated. Non-empty forces
            :attr:`MarginAccountStatus.INDETERMINATE`.
        capped_tickers: lots where the Dieu 2.4 ceiling actually bound.
        lots: the per-lot detail, in the order supplied.
    """

    as_of: datetime
    price_source: PriceSource
    eligible_value: Decimal = _ZERO
    ineligible_value: Decimal = _ZERO
    pending_purchase_value: Decimal = _ZERO
    untradable_rights_value: Decimal = _ZERO
    unpriced_tickers: Tuple[str, ...] = ()
    capped_tickers: Tuple[str, ...] = ()
    lots: Tuple[LotValuation, ...] = ()

    @property
    def is_indeterminate(self) -> bool:
        """Whether any lot that would have counted could not be valued."""
        return bool(self.unpriced_tickers)


def value_collateral(
    lots: Sequence[CollateralLot],
    terms: BrokerMarginTerms,
    *,
    as_of: datetime,
) -> CollateralValuation:
    """Value collateral under QD 87 Dieu 2.4. **The cap is not optional.**

    *"Gia tri cua chung khoan (v) la gia tri do cong ty chung khoan xac dinh tren
    Hop dong ... nhung khong vuot qua gia dong cua tai ngay gan nhat."* VERIFIED.
    The broker may haircut freely **below** the last close and may never value
    above it, so every counted lot is worth ``min(monitored price, last
    close)``. A firm monitoring at :attr:`PriceSource.LIVE_MARKET` therefore
    gets the live price on a down day and the last close on an up day: an
    up-tick cannot inflate the ratio, which is the whole content of the article.

    **What this function does not do: apply the per-ticker *ty le cho vay*.**
    Section 2.3 of the spec observes that brokers express their haircut as a
    per-ticker loan ratio, and it would be easy to read that as "value collateral
    at ``loan_ratio x last_close``". This function does not, and the choice is
    ours:

    * the only number Dieu 2.4 gives is the **ceiling**. The value inside it is
      *"do cong ty chung khoan xac dinh tren Hop dong"* -- a contract term, and
      the research read no broker's contract (spec section 5, gap 5);
    * the loan ratio already enters the algebra on the other side, through
      ``imr = 1 - loan_ratio`` (:func:`order_initial_margin_ratio`). Haircutting
      ``PV`` by it **and** requiring that ``imr`` would haircut the same
      collateral twice, and the second haircut would be invisible in the output.

    A firm whose contract really does value collateral at the loan ratio models
    that by passing lots already haircut -- the caller builds the lots. Recorded
    in :data:`PROVENANCE` under ``collateral_haircut_not_applied``.

    Args:
        lots: the holdings. Order is preserved in the result.
        terms: read for :attr:`BrokerMarginTerms.price_source`, the two
            collateral-inclusion flags, and
            :attr:`BrokerMarginTerms.collateral_valuation_cap_enforced` -- which
            cannot be ``False``, since ``BrokerMarginTerms`` refuses to
            construct with the cap waived.
        as_of: the instant these prices describe.

    Returns:
        A :class:`CollateralValuation` bucketed into
        :class:`MarginAccountState`'s fields.

    Raises:
        ValueError: on a duplicate ticker in the same bucket. Two rows for one
            ticker in one bucket is either double-counted collateral or a
            caller who meant to net them, and both are worth refusing.
    """
    source = terms.price_source
    valuations: List[LotValuation] = []
    eligible = _ZERO
    ineligible = _ZERO
    pending = _ZERO
    rights = _ZERO
    unpriced: List[str] = []
    capped: List[str] = []
    seen: set = set()

    for lot in lots:
        if lot.pending_settlement:
            bucket = CollateralBucket.PENDING_PURCHASE
            counts = terms.collateral_includes_pending_buys
        elif lot.untradable_right:
            bucket = CollateralBucket.UNTRADABLE_RIGHTS
            counts = terms.collateral_includes_untradable_rights
        else:
            bucket = CollateralBucket.ELIGIBLE
            counts = True

        key = (lot.ticker, bucket)
        if key in seen:
            raise ValueError(
                f'{lot.ticker!r} appears twice in the {bucket.value} bucket. '
                f'Two rows for one ticker in one bucket either double-counts '
                f'the holding into PV or means the caller intended to net them; '
                f'net them before valuing. A ticker held outright AND pending '
                f'settlement is two buckets and is fine')
        seen.add(key)

        if lot.eligibility is MarginEligibility.INELIGIBLE:
            unit = _capped_unit_value(lot, source)
            value = unit * lot.quantity if unit is not None else _ZERO
            ineligible += value
            valuations.append(LotValuation(
                ticker=lot.ticker, quantity=lot.quantity,
                bucket=CollateralBucket.INELIGIBLE, unit_value=unit,
                value=value, monitored_price=lot.price_at(source),
                counted=False,
                reason='TT 120 Dieu 9.6 -- excluded from the collateral base '
                       'for BOTH the initial and the maintenance ratio. Valued '
                       'here only so a caller can see what leaving the margin '
                       'list cost'))
            continue

        if lot.eligibility is MarginEligibility.INDETERMINATE:
            if counts:
                unpriced.append(lot.ticker)
            valuations.append(LotValuation(
                ticker=lot.ticker, quantity=lot.quantity,
                bucket=CollateralBucket.UNDETERMINED,
                monitored_price=lot.price_at(source), counted=False,
                reason='eligibility was not evaluated. Most of QD 87 Dieu 3 '
                       'needs issuer financial-statement facts the corpus does '
                       'not carry, and a lot that might belong in PV counted as '
                       'zero is a different account, not a conservative one'))
            continue

        monitored = lot.price_at(source)
        unit = _capped_unit_value(lot, source)
        if unit is None:
            if counts:
                unpriced.append(lot.ticker)
            missing = ('no last close, so the Dieu 2.4 ceiling cannot be shown '
                       'to hold -- the monitored price is NOT a fallback'
                       if lot.last_close is None else
                       f'no {source.value} price to value it at')
            valuations.append(LotValuation(
                ticker=lot.ticker, quantity=lot.quantity,
                bucket=CollateralBucket.UNPRICED, monitored_price=monitored,
                counted=False, reason=missing))
            continue

        value = unit * lot.quantity
        was_capped = monitored is not None and monitored > unit
        if was_capped:
            capped.append(lot.ticker)
        if bucket is CollateralBucket.ELIGIBLE:
            eligible += value
        elif bucket is CollateralBucket.PENDING_PURCHASE:
            pending += value
        else:
            rights += value
        valuations.append(LotValuation(
            ticker=lot.ticker, quantity=lot.quantity, bucket=bucket,
            unit_value=unit, value=value, capped=was_capped,
            monitored_price=monitored, counted=counts,
            reason=None if counts else
            f'this firm does not count {bucket.value} toward the collateral '
            f'base. Valued so the caller can see what it chose not to count'))

    return CollateralValuation(
        as_of=as_of,
        price_source=source,
        eligible_value=eligible,
        ineligible_value=ineligible,
        pending_purchase_value=pending,
        untradable_rights_value=rights,
        unpriced_tickers=tuple(unpriced),
        capped_tickers=tuple(capped),
        lots=tuple(valuations),
    )


def _capped_unit_value(lot: CollateralLot,
                       source: PriceSource) -> Optional[Decimal]:
    """``min(monitored price, last close)``, or ``None`` if either is missing.

    The Dieu 2.4 cap in one expression. Both operands are required: with no last
    close the ceiling is unknown, and the article does not permit valuing at the
    monitored price and hoping.
    """
    if lot.last_close is None:
        return None
    monitored = lot.price_at(source)
    if monitored is None:
        return None
    return min(monitored, lot.last_close)


# --------------------------------------------------------------------------
# When the ratio is determined (spec 2.4, QD 87 Dieu 6.1)
# --------------------------------------------------------------------------

#: Default session bounds for an intraday sweep. **REPORTED at one firm, and
#: ours by default.** DNSE publishes an hourly call-notice sweep running
#: 09:00-15:00; no other firm publishes a window, and QD 87 is silent -- Dieu 6.1
#: mandates end of day and nothing else. A caller simulating a real venue should
#: pass that venue's session bounds instead of taking these.
DEFAULT_SESSION_OPEN = time(9, 0)
DEFAULT_SESSION_CLOSE = time(15, 0)


@dataclass(frozen=True)
class RatioSchedule:
    """When QD 87 Dieu 6.1's determination happens, and how often.

    **Dieu 6.1, VERIFIED:** the CTCK determines each margin account's ratio **at
    the end of the trading day**, using the Dieu 2.4 valuation; *the exact
    within-day timestamp is agreed in writing with the client*. So the basis is
    statutory, the clock time is a contract term, and this record separates
    them.

    **The statute-vs-practice divergence, which is load-bearing.** The regulation
    mandates end-of-day computation at a valuation no higher than the last close.
    Brokers in 2026 run it **intraday at live market prices** and force-sell
    intraday (DNSE, REPORTED). This module implements end of day as the
    regulatory floor behaviour and intraday as a broker option
    (:attr:`BrokerMarginTerms.intraday_monitoring`), exactly as the derivatives
    path treats broker utilisation thresholds. **A result produced at the default
    is a result about the rule, not about the market.**

    **The end-of-day determination is never removed by the broker option.**
    Intraday sweeps are *additional*: a firm that also looks hourly is stricter,
    and stricter is always allowed. A firm that replaced the statutory
    determination with a 10:00 sweep would not be, so :meth:`instants` always
    contains :attr:`determination_at`.

    Attributes:
        basis: :attr:`RatioDetermination.END_OF_DAY` unless the firm sweeps.
        determination_at: the within-day timestamp the contract names for the
            statutory determination. Defaults to :attr:`session_close` -- Dieu
            6.1 says *cuoi ngay giao dich*, so the close is the reading that
            needs no extra assumption, and it is **our default**, not a term
            anyone published.
        session_open: first sweep instant when monitoring intraday.
        session_close: last sweep instant when monitoring intraday.
        interval_minutes: sweep period. ``None`` with an intraday basis means
            **continuous** -- the ratio is recomputed on every price event -- and
            :meth:`instants` refuses rather than pretending a continuous monitor
            has a timetable.
    """

    basis: RatioDetermination = RatioDetermination.END_OF_DAY
    determination_at: time = DEFAULT_SESSION_CLOSE
    session_open: time = DEFAULT_SESSION_OPEN
    session_close: time = DEFAULT_SESSION_CLOSE
    interval_minutes: Optional[int] = None

    def __post_init__(self) -> None:
        if self.session_open > self.session_close:
            raise ValueError(
                f'session_open {self.session_open} is after session_close '
                f'{self.session_close}')
        if self.interval_minutes is not None and self.interval_minutes < 1:
            raise ValueError(
                f'interval_minutes must be at least 1, got '
                f'{self.interval_minutes}. Use None for a continuous monitor')
        if (self.basis is RatioDetermination.END_OF_DAY
                and self.interval_minutes is not None):
            raise ValueError(
                'interval_minutes is set on an END_OF_DAY schedule. QD 87 Dieu '
                '6.1 determines the ratio once, at the end of the trading day; '
                'a sweep period on a schedule that does not sweep is a config '
                'that says two things')

    @classmethod
    def from_terms(
        cls,
        terms: BrokerMarginTerms,
        *,
        determination_at: Optional[time] = None,
        session_open: time = DEFAULT_SESSION_OPEN,
        session_close: time = DEFAULT_SESSION_CLOSE,
    ) -> 'RatioSchedule':
        """The schedule one firm's terms imply.

        :attr:`BrokerMarginTerms.intraday_monitoring` picks the basis and
        :attr:`BrokerMarginTerms.monitor_interval_minutes` the period; the two
        clock times are the caller's, because no article and no firm publishes
        them for the general case.
        """
        return cls(
            basis=(RatioDetermination.INTRADAY if terms.intraday_monitoring
                   else RatioDetermination.END_OF_DAY),
            determination_at=(determination_at if determination_at is not None
                              else session_close),
            session_open=session_open,
            session_close=session_close,
            interval_minutes=(terms.monitor_interval_minutes
                              if terms.intraday_monitoring else None),
        )

    @property
    def is_continuous(self) -> bool:
        """Whether this firm recomputes on every price event.

        Ask this before :meth:`instants`, which refuses on a continuous
        schedule.
        """
        return (self.basis is RatioDetermination.INTRADAY
                and self.interval_minutes is None)

    def instants(self, on: date) -> Tuple[datetime, ...]:
        """Every moment the ratio is determined on ``on``, in order.

        One instant for the statutory end-of-day determination, plus the sweeps
        where the firm runs them. The statutory instant is always present -- see
        the class docstring.

        Raises:
            ValueError: on a continuous schedule, which has no timetable to
                enumerate. Check :attr:`is_continuous` first and drive the
                recomputation from the price stream.
        """
        if self.is_continuous:
            raise ValueError(
                'a continuous intraday monitor has no enumerable instants: it '
                'recomputes on every price event. Check is_continuous first, '
                'drive recomputation from the tick stream, and use '
                'determination_at for the QD 87 Dieu 6.1 end-of-day '
                'determination, which still happens')
        statutory = datetime.combine(on, self.determination_at)
        if self.basis is RatioDetermination.END_OF_DAY:
            return (statutory,)
        step = timedelta(minutes=self.interval_minutes)
        cursor = datetime.combine(on, self.session_open)
        last = datetime.combine(on, self.session_close)
        out: List[datetime] = []
        while cursor <= last:
            out.append(cursor)
            cursor += step
        if statutory not in out:
            out.append(statutory)
        return tuple(sorted(out))


# --------------------------------------------------------------------------
# The algebra itself (khoan 3-12)
# --------------------------------------------------------------------------

def compute_account_algebra(
    state: MarginAccountState,
    terms: BrokerMarginTerms,
    *,
    basis: Optional[RatioDetermination] = None,
    regulation: Optional[MarginRegulation] = None,
) -> MarginAccountAlgebra:
    """QD 87 Dieu 2 khoan 3-12, evaluated over one account at one instant.

    A pure function of ``state`` and ``terms``: no ledger, no clock, no I/O. A
    recorded :class:`MarginAccountState` replayed through here reproduces the
    ratio that fired a call, which is the property the state/algebra split
    exists for.

    **What each line is, and where it comes from.**

    ``DB`` (khoan 3) is ``margin_debt``, plus accrued interest and fees where
    :attr:`BrokerMarginTerms.accrued_charges_in_debt` is set. Whether accrued
    charges join ``DB`` is **not stated** by the article; ``True`` is this
    module's conservative default because it lowers ``AB`` and fires calls
    sooner. See :data:`PROVENANCE` under ``accrued_charges_in_debt``.

    ``CB`` (khoan 5) is cash **plus unsettled sale proceeds**. See
    :class:`CashBase` for why that is not ``Cash.available``.

    ``PV`` (khoan 6) is the value of the securities *duoc phep giao dich ky quy*
    -- eligible collateral only. Securities off the margin list are **excluded
    from the base for both ratios** (TT 120 Dieu 9.6, over the narrower QD 87
    Dieu 10.2), which is why ``BrokerMarginTerms`` refuses to construct with
    ``ineligible_counted_as_collateral``. Pending buys and untradable rights join
    ``PV`` only where the firm's flags say so -- the firms genuinely disagree
    (ACBS counts uncredited rights, FNS explicitly does not).

    ``EB = CB + PV`` (khoan 7), ``AB = EB - DB``, and ``AB`` **may be negative**:
    an account whose collateral has fallen below its debt has negative *tai san
    thuc co*, and clamping it would hide exactly the account that most needs a
    forced sale.

    ``MR = gia tri chung khoan x imr`` (khoan 10) is computed here over the
    account's ``PV``. **That reading is ours and is DERIVED** -- khoan 8 defines
    ``imr`` per order, and reading the ``MR`` line at account level is what makes
    the algebra evaluable without an order in hand. When an order *is* in hand,
    :func:`assess_margin_order` uses the per-order reading. See
    :data:`PROVENANCE` under ``account_level_mr_reading``.

    ``EE = AB - MR`` (khoan 11) and ``BP = EE / imr`` (khoan 12). Neither is
    clamped at zero: a negative ``EE`` says by how much the account is already
    beyond its buying power, and that number is the one a caller needs.

    **The status is graded by** :func:`account_status` **against**
    :func:`binding_policy`, not against ``terms`` directly. Two reasons, and
    both matter. The levels a run must be graded on are the *binding* ones --
    QD 87 Dieu 5.3 lets the SSC move the floors and a run crossing such a date
    holds terms validated against the old row -- which is what ``regulation``
    below is for. And there must be exactly one grader: a second implementation
    of the same ladder in this function would be free to drift from the one the
    call and forced-sale machine uses, and the two would disagree about the same
    account.

    Args:
        state: the inputs. Every value field must be a non-negative ``Decimal``.
        terms: the firm whose ``imr``, ``mmr`` and flags apply.
        basis: override the determination basis -- pass
            :attr:`RatioDetermination.INTRADAY` for a sweep. Defaults to the
            firm's own posture. Passing ``INTRADAY`` for a firm that does not
            monitor intraday raises, because the result would claim a
            computation the firm's terms say it never makes.
        regulation: the statutory row in force for the run, resolved with
            :func:`regulation_in_force`. Defaults to ``terms.regulation``.
            Passing a row whose floors have risen above the firm's own levels
            grades every account against the new floors, which is what Dieu 5.3
            means in practice.

    Returns:
        A fully populated :class:`MarginAccountAlgebra`.

    Raises:
        ValueError: on a negative value field, or an incoherent ``basis``.
        TypeError: on a ``float`` anywhere money or a ratio is expected.
    """
    for name in ('cash', 'pending_sale_proceeds', 'eligible_securities_value',
                 'ineligible_securities_value', 'pending_purchase_value',
                 'untradable_rights_value', 'margin_debt', 'accrued_interest',
                 'accrued_fees'):
        value = getattr(state, name)
        _require_decimal(f'{state.account_id}.{name}', value)
        if value < _ZERO:
            raise ValueError(
                f'{name} is {value} on account {state.account_id!r}. Every '
                f'term of QD 87 Dieu 2\'s algebra is a value or a debt and none '
                f'of them is signed -- a negative one flips the ratio silently '
                f'rather than failing, and AB is the only quantity here allowed '
                f'to go below zero')

    if basis is None:
        basis = (RatioDetermination.INTRADAY if terms.intraday_monitoring
                 else RatioDetermination.END_OF_DAY)
    elif (basis is RatioDetermination.INTRADAY
            and not terms.intraday_monitoring):
        raise ValueError(
            'basis=INTRADAY was requested but this firm\'s terms set '
            'intraday_monitoring=False. QD 87 Dieu 6.1 mandates the end-of-day '
            'determination; intraday is a broker option and a result cannot '
            'claim a computation the firm does not make. Set '
            'intraday_monitoring on the terms if that is the firm you mean')

    db = state.margin_debt
    if terms.accrued_charges_in_debt:
        db = db + state.accrued_interest + state.accrued_fees

    cb = state.cash
    if terms.collateral_includes_unsettled_sale_proceeds:
        cb = cb + state.pending_sale_proceeds

    pv = state.eligible_securities_value
    if terms.collateral_includes_pending_buys:
        pv = pv + state.pending_purchase_value
    if terms.collateral_includes_untradable_rights:
        pv = pv + state.untradable_rights_value

    eb = cb + pv
    ab = eb - db
    ratio = (ab / eb) if eb != _ZERO else None

    policy = binding_policy(terms, regulation)
    imr = terms.initial_margin_ratio
    mmr = policy.call_level
    mr = pv * imr
    ee = ab - mr
    bp = ee / imr

    reasons: List[str] = []
    if state.unpriced_tickers:
        reasons.append(
            'no determinable collateral value for ' +
            ', '.join(state.unpriced_tickers) +
            ' -- a holding that might belong in PV counted as zero is a '
            'different account, not a conservative one')

    status = account_status(ratio, policy, debt=db,
                            suspended=state.lending_suspended,
                            indeterminate=bool(reasons))

    return MarginAccountAlgebra(
        account_id=state.account_id,
        as_of=state.as_of,
        basis=basis,
        price_source=terms.price_source,
        accounting_unit=terms.accounting_unit,
        margin_debt=db,
        cash_and_pending_proceeds=cb,
        eligible_securities_value=pv,
        total_assets=eb,
        net_assets=ab,
        margin_ratio=ratio,
        initial_margin_ratio=imr,
        maintenance_margin_ratio=mmr,
        required_margin_value=mr,
        excess_equity=ee,
        buying_power=bp,
        status=status,
        indeterminate_reasons=tuple(reasons),
    )


def build_account_state(
    *,
    account_id: str,
    as_of: datetime,
    cash: Cash,
    collateral: Sequence[CollateralLot],
    terms: BrokerMarginTerms,
    margin_debt: Optional[Decimal] = None,
    accrued_interest: Optional[Decimal] = None,
    accrued_fees: Optional[Decimal] = None,
    loans: Tuple[MarginLoan, ...] = (),
    open_calls: Tuple[MarginCall, ...] = (),
    is_foreign_investor: bool = False,
    margin_contract_signed: bool = True,
    holder_classes: Tuple[IneligibleAccountHolder, ...] = (),
    lending_suspended: bool = False,
) -> MarginAccountState:
    """Join the tranche ledger and a price snapshot into one algebra input.

    The seam. :func:`cash_base` supplies khoan 5's ``CB`` from the ledger's read
    model, :func:`value_collateral` supplies khoan 6's ``PV`` under the Dieu 2.4
    cap, and this function assembles them into the record
    :func:`compute_account_algebra` consumes. Nothing here interprets: every
    decision was already made by one of those two.

    ``margin_debt``, ``accrued_interest`` and ``accrued_fees`` default to
    ``None`` meaning *derive them from* ``loans``, which is the case at
    :attr:`AccountingUnit.DEAL` where the per-deal loans are the debt. Passing a
    number states the account-level balance directly and the loans become
    detail. Passing both a number and loans that disagree is the caller's
    business -- this function does not reconcile them, because at ``DEAL``
    granularity a firm may hold an account-level figure that is not the sum of
    the deals.

    Only loans in :attr:`LoanStatus.OUTSTANDING`, :attr:`LoanStatus.EXTENDED` or
    :attr:`LoanStatus.OVERDUE` contribute to a derived debt. ``REPAID`` is
    cleared and ``LIQUIDATED`` may leave a residual the contract pursues, but
    neither is *du no ky quy* on this account any more.
    """
    base = cash_base(cash, terms)
    valued = value_collateral(collateral, terms, as_of=as_of)

    live = tuple(loan for loan in loans
                 if loan.status in (LoanStatus.OUTSTANDING,
                                    LoanStatus.EXTENDED, LoanStatus.OVERDUE))
    if margin_debt is None:
        margin_debt = sum((loan.principal for loan in live), _ZERO)
    if accrued_interest is None:
        accrued_interest = sum((loan.accrued_interest for loan in live), _ZERO)
    if accrued_fees is None:
        accrued_fees = sum((loan.accrued_fees for loan in live), _ZERO)

    return MarginAccountState(
        account_id=account_id,
        as_of=as_of,
        cash=base.settled,
        pending_sale_proceeds=(base.unsettled_proceeds
                               if base.counts_unsettled else _ZERO),
        eligible_securities_value=valued.eligible_value,
        ineligible_securities_value=valued.ineligible_value,
        pending_purchase_value=valued.pending_purchase_value,
        untradable_rights_value=valued.untradable_rights_value,
        margin_debt=margin_debt,
        accrued_interest=accrued_interest,
        accrued_fees=accrued_fees,
        loans=loans,
        open_calls=open_calls,
        is_foreign_investor=is_foreign_investor,
        margin_contract_signed=margin_contract_signed,
        holder_classes=holder_classes,
        lending_suspended=lending_suspended,
        unpriced_tickers=valued.unpriced_tickers,
    )


# ==========================================================================
# THE MARGIN CALL AND FORCED SALE STATE MACHINE
# --------------------------------------------------------------------------
# Spec sections 2.8 (the call), 2.9 (the forced sale -- *ban giai chap*),
# 3.2 (the two broker levels), 3.3 (execution policy), 3.4 (term and overdue).
#
# Everything from here down is the engine the type contract above was written
# for. The division of labour is deliberate and worth stating once:
#
#   * the records above are what a call and a sale ARE;
#   * this section is WHEN they happen, and it is the only place in the module
#     that carries state across time.
#
# Nothing here computes QD 87 Dieu 2's algebra. The ratio arrives as a
# :class:`MarginAccountAlgebra` the caller built; this section grades it against
# the broker's two levels, keeps the resulting call alive across sessions,
# decides when the force-sale right has arisen, and sizes the sale. Keeping the
# algebra out means the state machine is testable against a hand-written ratio,
# which is what every test below does.
# ==========================================================================


# --------------------------------------------------------------------------
# The one calendar question this section asks
# --------------------------------------------------------------------------

@runtime_checkable
class BusinessDayCalendar(Protocol):
    """Business-day arithmetic, declared structurally to keep the import fence.

    QD 87 Dieu 7.1 states the cure ceiling in *ngay lam viec* -- business days
    -- so a cure deadline is business-day arithmetic and nothing else. This
    Protocol is the whole dependency: one method, no venue, no rules object.

    Declaring it here rather than importing ``session/calendar.py`` keeps this
    module's stated import boundary intact (it still imports only ``Venue``)
    while accepting :class:`~plutus.market.session.calendar.VsdcSettlementCalendar`
    unchanged -- that class already has this exact method with this exact
    signature. A caller with a better source substitutes an object, not a
    subclass.

    **Which calendar is the right calendar is OUR choice, and it is not
    obvious.** QD 87 says *ngay lam viec* without saying whose working days.
    The VSDC settlement calendar and the two exchanges' trading calendars
    diverge around Tet, and the difference there is up to a week of cure window
    -- which is the whole cure window and then some. This module refuses to own
    a calendar for that reason: the caller passes the one it can defend, and
    :attr:`MarginCall.deadline` is only as sourced as the object behind it.
    """

    def add_business_days(self, start: date, days: int) -> date:
        """``start`` plus ``days`` business days.

        ``days=0`` must return the next business day at or after ``start``,
        which is what :class:`~plutus.market.session.calendar.VsdcSettlementCalendar`
        does.
        """
        ...


def cure_deadline(issued_at: datetime, business_days: int,
                  calendar: BusinessDayCalendar) -> datetime:
    """The instant a cure window closes. QD 87 Dieu 7.1.

    The article gives a **count of business days** and no time of day. Landing
    the deadline at the same time of day the call issued is **OUR choice**, and
    it is the reading closest to the two clauses that do speak: Dieu 7.1 makes
    the period itself a contract term, and Dieu 6.1 has the within-day timestamp
    of the ratio computation agreed in writing with the client. A deadline at
    midnight would silently shorten every window by the better part of a day,
    and a deadline at the next close would lengthen it; anchoring to the call
    keeps the window exactly as many business days long as the contract says.

    Declared in :data:`PROVENANCE` under ``cure_deadline_time_of_day``.

    Args:
        issued_at: when the CTCK issued the *lenh goi ky quy bo sung*.
        business_days: the **binding** window -- see :func:`binding_policy`,
            which takes the tighter of the broker's term and the statutory
            ceiling.
        calendar: see :class:`BusinessDayCalendar`.
    """
    if business_days < 0:
        raise ValueError(
            f'business_days must not be negative, got {business_days}. '
            f'QD 87 Dieu 7.1 caps the window at three business days and '
            f'requires the CTCK to set one; a negative window is not a period')
    landing = calendar.add_business_days(issued_at.date(), business_days)
    return datetime.combine(landing, issued_at.timetz())


# --------------------------------------------------------------------------
# What binds when the statute and the contract both speak -- 2.8 + 3.2 + 3.4
# --------------------------------------------------------------------------

class PolicyBound(str, Enum):
    """Which of the two layers actually set a threshold.

    The whole point of the statutory/commercial split is that both speak and
    the **tighter one binds**. That answer is data, not commentary: a result
    that reports a 3-day cure window should be able to say whether it is 3 days
    because the firm chose 3 or because QD 87 Dieu 7.1 would not allow 4.

    ``BROKER``
        The firm's own term is stricter and is what binds.
    ``STATUTE``
        The statutory floor or ceiling is stricter and overrides the firm's
        term. Reachable in exactly one direction that matters: QD 87 Dieu 5.3
        lets the SSC **move the ratio floors**, and a firm whose contract was
        written under the old floor is bound by the new one from the day it
        takes effect, without renegotiating anything.
    ``BOTH``
        They agree. Common -- SSI and ACBS both use the 3-day ceiling in full.
    """

    BROKER = 'broker'
    STATUTE = 'statute'
    BOTH = 'both'


@dataclass(frozen=True)
class BindingPolicy:
    """The thresholds that actually bind, and which layer set each one.

    :class:`BrokerMarginTerms` already refuses a term looser than the floors in
    **its own** :attr:`BrokerMarginTerms.regulation`. That is a construction-time
    check against one regulation row, and it is not the whole story, because the
    regulation is **dated**: QD 87 Dieu 5.3 gives the SSC a standing power to
    move the ratios, and it has been used once inside living memory (the
    2011 floor of 60 % became 50 % in 2017). A run that crosses such a date
    holds terms validated against the old row and must be graded against the
    new one.

    So this record recomputes the binding values from **both** layers and keeps
    the provenance of each. It never loosens: every value here is the stricter
    of the two, so a policy built from terms and their own regulation is
    identical to the terms.

    Attributes:
        call_level: the ratio at or above which the account is
            :attr:`MarginAccountStatus.OK`. ``max`` of the firm's
            :attr:`BrokerMarginTerms.maintenance_margin_ratio` and
            :attr:`MarginRegulation.maintenance_margin_ratio_floor`.
        force_sell_level: the ratio below which a sale fires **without a cure
            window**. ``max`` of the firm's
            :attr:`BrokerMarginTerms.liquidation_margin_ratio` and the same
            statutory floor.
        cure_business_days: ``min`` of the firm's
            :attr:`BrokerMarginTerms.cure_business_days` and
            :attr:`MarginRegulation.max_cure_business_days`. QD 87 Dieu 7.1's
            three days are a **ceiling**, so fewer is stricter and legal.
        cure_target_ratio: what a cure must restore. The firm's
            :attr:`BrokerMarginTerms.cure_target_ratio` where set, else
            :attr:`call_level`, and never below :attr:`call_level` -- a target
            under the call level would "cure" an account straight back into a
            call.
        call_level_bound_by: see :class:`PolicyBound`.
        force_sell_level_bound_by: as above.
        cure_window_bound_by: as above.
        terms: the commercial layer this was built from.
        regulation: the statutory row it was graded against, which is **not
            necessarily** ``terms.regulation``.
    """

    call_level: Decimal
    force_sell_level: Decimal
    cure_business_days: int
    cure_target_ratio: Decimal
    call_level_bound_by: PolicyBound
    force_sell_level_bound_by: PolicyBound
    cure_window_bound_by: PolicyBound
    terms: BrokerMarginTerms
    regulation: MarginRegulation

    @property
    def levels_collapsed(self) -> bool:
        """Whether the call level and the force-sell level are the same number.

        True when a statutory floor has risen above the firm's own call level,
        which erases the ``CALL`` band: the account goes from ``OK`` to
        ``FORCE_SELL`` with no window in between. Worth reporting rather than
        discovering -- a run in that state issues no calls at all, and a reader
        who did not know why would think the machine was broken.
        """
        return self.call_level == self.force_sell_level


def _bound_by(broker: Any, statutory: Any, *, stricter_is_higher: bool
              ) -> PolicyBound:
    """Which layer set a threshold, given which direction is stricter."""
    if broker == statutory:
        return PolicyBound.BOTH
    if stricter_is_higher:
        return PolicyBound.BROKER if broker > statutory else PolicyBound.STATUTE
    return PolicyBound.BROKER if broker < statutory else PolicyBound.STATUTE


def binding_policy(terms: BrokerMarginTerms,
                   regulation: Optional[MarginRegulation] = None,
                   ) -> BindingPolicy:
    """Resolve the thresholds that bind. **The tighter layer always wins.**

    Args:
        terms: the firm's commercial terms.
        regulation: the statutory row in force **for the run**, which a caller
            crossing an SSC adjustment resolves with :func:`regulation_in_force`
            and passes in. Defaults to ``terms.regulation``, in which case the
            result restates the terms.

    A worked case, and the reason this function is not just ``terms``: a firm
    signed contracts at ``maintenance = 0.32`` under a 30 % floor. The SSC
    raises the floor to 0.35 under Dieu 5.3. Every one of that firm's accounts
    is in call at 0.33 from the effective date, with no contract amendment, and
    the run must say so.
    """
    reg = terms.regulation if regulation is None else regulation
    floor = reg.maintenance_margin_ratio_floor

    call_level = max(terms.maintenance_margin_ratio, floor)
    force_level = max(terms.liquidation_margin_ratio, floor)
    window = min(terms.cure_business_days, reg.max_cure_business_days)

    target = (terms.cure_target_ratio if terms.cure_target_ratio is not None
              else call_level)
    target = max(target, call_level)

    return BindingPolicy(
        call_level=call_level,
        force_sell_level=force_level,
        cure_business_days=window,
        cure_target_ratio=target,
        call_level_bound_by=_bound_by(terms.maintenance_margin_ratio, floor,
                                      stricter_is_higher=True),
        force_sell_level_bound_by=_bound_by(terms.liquidation_margin_ratio,
                                            floor, stricter_is_higher=True),
        cure_window_bound_by=_bound_by(terms.cure_business_days,
                                       reg.max_cure_business_days,
                                       stricter_is_higher=False),
        terms=terms,
        regulation=reg,
    )


# --------------------------------------------------------------------------
# Grading one ratio against the two levels -- spec 3.2
# --------------------------------------------------------------------------

def account_status(ratio: Optional[Decimal], policy: BindingPolicy, *,
                   debt: Decimal = _ZERO, suspended: bool = False,
                   indeterminate: bool = False) -> MarginAccountStatus:
    """Where one ratio sits on the broker's ladder.

    **Brokers run two levels, not one** (spec 3.2). SSI distinguishes *TLKQ duy
    tri* from *TLKQ xu ly* and force-sells immediately on the second; the
    statute knows only one number, the ``mmr`` floor. A model with a single
    threshold cannot express either firm, which is why
    :class:`BindingPolicy` carries two and this function reads both.

    The four non-obvious branches, each of which a test pins:

    **``indeterminate`` wins over everything.** An unpriced holding or an
    unevaluable eligibility predicate means the data could not decide, and the
    house rule throughout this package is that "could not decide" stays
    countable apart from "a rule said no". Never read as OK.

    **``ratio is None`` is EB == 0, and it splits on the debt.** An account with
    no assets and no debt is not in breach. An account with no assets and a debt
    outstanding is past the point a ratio describes, and it is reported
    ``FORCE_SELL`` -- which produces a plan with nothing to sell and a
    :attr:`ForcedSalePlan.shortfall` equal to the whole requirement, i.e.
    exactly QD 87 Dieu 8's *"if liquidation does not cover DB"* case. Reporting
    it as ``INDETERMINATE`` would be wrong: nothing is unknown.

    **Suspension does not shelter a breach.** ``SUSPENDED`` is returned only
    when the ladder itself is clean. TT 120 Dieu 9.9's stabilisation order and
    Dieu 9.7's loss of eligibility both stop **new lending**; neither cures an
    existing ratio, and neither removes a client's obligation. Collapsing a
    breaching account to ``SUSPENDED`` would hide precisely the accounts a
    stabilisation order was issued about. The enum forces a single answer, and
    reporting the breach is the conservative half of the choice.

    **The bands are half-open downward:** ``ratio < force_sell_level`` forces,
    ``ratio < call_level`` calls, otherwise OK. A ratio sitting exactly **on**
    a level is not in breach of it -- QD 87 Dieu 5.2 says *"khong duoc thap hon"*,
    not lower than, so equality complies.
    """
    if indeterminate:
        return MarginAccountStatus.INDETERMINATE
    if ratio is None:
        if debt > _ZERO:
            return MarginAccountStatus.FORCE_SELL
        return (MarginAccountStatus.SUSPENDED if suspended
                else MarginAccountStatus.OK)
    _require_decimal('ratio', ratio)
    if ratio < policy.force_sell_level:
        return MarginAccountStatus.FORCE_SELL
    if ratio < policy.call_level:
        return MarginAccountStatus.CALL
    return (MarginAccountStatus.SUSPENDED if suspended
            else MarginAccountStatus.OK)


# --------------------------------------------------------------------------
# The top-up amounts -- spec 2.8. DERIVED, and flagged at every use.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TopUpRequirement:
    """What it takes to cure one call. **Every number here is DERIVED.**

    **Read this before quoting any field.** QD 87 Dieu 7.2 gives two formulas --
    (a) the value of securities to post and (b) the cash to post -- and *every
    accessible mirror renders them as images and drops them*. What follows is
    **our own arithmetic** off the Dieu 2 algebra, not the article's. Do not
    ship it as "the regulation says". Declared in :data:`PROVENANCE` under
    ``top_up_amounts``, and the TODO there is to obtain the cong bao copy.

    Write the shortfall once, in cash terms::

        gap = target x EB - AB

    Every cure method closes some fraction of that one number, and the
    fractions differ because the methods move different terms of the algebra:

    ========================  =======================  ====================
    method                    effect on (EB, AB)       closes
    ========================  =======================  ====================
    cash, swept against DB    (EB, AB + C)             ``C``
    cash, left in CB          (EB + C, AB + C)         ``C x (1 - target)``
    eligible securities       (EB + S, AB + S)         ``S x (1 - target)``
    self-directed sale,       (EB - V, AB)             ``V x target``
    proceeds repaying DB
    ========================  =======================  ====================

    Inverting each gives the four amounts below. The cash figure is the smallest
    of them for any ``target < 0.5`` and the largest is the self-sale, which is
    why a client who can find cash finds cash.

    Attributes:
        target_ratio: what the cure must restore --
            :attr:`BindingPolicy.cure_target_ratio`.
        total_assets: ``EB`` at the moment the call issued.
        net_assets: ``AB`` at the moment the call issued. **May be negative.**
        gap: ``target x EB - AB``, the shortfall in cash terms. Zero or less
            when the account already meets the target.
        cash: cash to deposit and sweep against ``DB``. Equals :attr:`gap`.
        securities_value: value of eligible collateral to post, or of cash left
            sitting in ``CB``.
        self_sale_value: value of collateral the client sells itself, proceeds
            applied to the debt. This is the same quantity a forced sale has to
            raise -- see :func:`value_to_restore` -- because a *ban giai chap*
            is a self-directed sale the CTCK places on the client's behalf.
    """

    target_ratio: Decimal
    total_assets: Decimal
    net_assets: Decimal
    gap: Decimal
    cash: Decimal
    securities_value: Decimal
    self_sale_value: Decimal

    @property
    def already_met(self) -> bool:
        """Whether the account is already at or above the target."""
        return self.gap <= _ZERO


def top_up_requirement(total_assets: Decimal, net_assets: Decimal,
                       target_ratio: Decimal) -> TopUpRequirement:
    """The four DERIVED cure amounts for one account. See :class:`TopUpRequirement`.

    Args:
        total_assets: ``EB = CB + PV``.
        net_assets: ``AB = EB - DB``. May be negative; an account whose
            collateral has fallen under its debt still has a computable
            requirement, and clamping ``AB`` at zero would understate it.
        target_ratio: strictly between 0 and 1. The upper bound is not
            decoration -- ``securities_value`` divides by ``1 - target`` and a
            target of 1 would demand an infinite deposit, which is the
            arithmetic saying an all-equity account cannot be reached by
            posting collateral against a debt.
    """
    _require_decimal('total_assets', total_assets)
    _require_decimal('net_assets', net_assets)
    _require_decimal('target_ratio', target_ratio)
    if not _ZERO < target_ratio < _ONE:
        raise ValueError(
            f'target_ratio must be strictly between 0 and 1, got '
            f'{target_ratio}. At 0 no cure is ever required and the forced-sale '
            f'sizing divides by it; at 1 the securities top-up divides by zero')

    gap = target_ratio * total_assets - net_assets
    if gap <= _ZERO:
        return TopUpRequirement(target_ratio=target_ratio,
                                total_assets=total_assets,
                                net_assets=net_assets,
                                gap=gap, cash=_ZERO, securities_value=_ZERO,
                                self_sale_value=_ZERO)
    return TopUpRequirement(
        target_ratio=target_ratio,
        total_assets=total_assets,
        net_assets=net_assets,
        gap=gap,
        cash=gap,
        securities_value=gap / (_ONE - target_ratio),
        self_sale_value=gap / target_ratio,
    )


def value_to_restore(total_assets: Decimal, net_assets: Decimal,
                     target_ratio: Decimal) -> Decimal:
    """Market value of collateral a forced sale must raise. **DERIVED.**

    ``EB - AB / target``, which is :attr:`TopUpRequirement.self_sale_value`
    written the other way round, and the two are the same formula because a
    *ban giai chap* is a self-directed sale the CTCK places itself.

    The derivation, since no article contains it: selling value ``V`` and
    applying the proceeds to the debt takes ``PV`` down by ``V`` and ``DB`` down
    by ``V``, so ``EB`` falls by ``V`` and ``AB`` does not move at all. Setting
    ``AB / (EB - V) >= target`` and solving gives ``V >= EB - AB / target``.

    **Two consequences worth stating**, both of which surprise people and both
    of which a test pins:

    1. Selling collateral **without** applying the proceeds to the debt changes
       the ratio by exactly nothing -- ``PV`` falls and ``CB`` rises by the same
       amount, ``EB`` is unchanged, ``AB`` is unchanged. A liquidation that
       leaves the cash sitting in the account cures nothing.
    2. When ``AB <= 0`` the formula returns at least ``EB``, i.e. *sell
       everything and it is still not enough*. That is not a bug in the
       arithmetic, it is QD 87 Dieu 8's shortfall case, and
       :attr:`ForcedSalePlan.restores_target` reports it rather than hiding it.

    Zero when the account already meets the target -- never negative, because a
    negative sale is not a thing.
    """
    return top_up_requirement(total_assets, net_assets,
                              target_ratio).self_sale_value


# --------------------------------------------------------------------------
# Curing -- spec 2.8. Three methods, three different arithmetics.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CureContribution:
    """One thing a client did in answer to a call. QD 87 Dieu 7.

    The article gives three methods and the client must restore **at least**
    ``mmr``; the precise target is the CTCK's. The three are not
    interchangeable -- see :func:`cure_credit` for what each is worth -- and
    that is the reason this is a record with a method on it rather than a
    number.

    Attributes:
        method: which of QD 87 Dieu 7's three. Must be one the call accepts;
            :meth:`MarginCallMonitor.cure` refuses a method absent from
            :attr:`MarginCall.cure_methods`.
        amount: cash deposited, market value of collateral posted, or **gross**
            proceeds of a self-directed sale. Strictly positive: a contribution
            of nothing is a caller error, not a partial cure.
        at: when the client did it. A contribution stamped after
            :attr:`MarginCall.deadline` is refused -- see
            :meth:`MarginCallMonitor.cure`.
        ticker: the security posted or sold, where one is.
        quantity: shares posted or sold.
        applied_to_debt: whether the money ends up repaying ``DB``.

            For ``DEPOSIT_CASH`` this is the ACBS sweep -- *"he thong se tu dong
            thu can tru no vao cuoi ngay"* -- and it is worth **more** than cash
            left in ``CB``, because repaying debt raises ``AB`` without raising
            ``EB``. REPORTED at one firm, defaulted to ``True``.

            For ``SELL_SECURITIES`` it is load-bearing rather than a nicety: a
            sale whose proceeds stay in the account moves nothing at all and
            cures **zero**. ``False`` is a real thing a client can do, so it is
            representable and scores zero, rather than being refused and
            therefore never counted.

            Meaningless for ``POST_SECURITIES``, and ignored there.
        note: free text for the log.
    """

    method: CureMethod
    amount: Decimal
    at: datetime
    ticker: Optional[str] = None
    quantity: int = 0
    applied_to_debt: bool = True
    note: Optional[str] = None

    def __post_init__(self) -> None:
        _require_decimal('amount', self.amount)
        if self.amount <= _ZERO:
            raise ValueError(
                f'a cure contribution must be strictly positive, got '
                f'{self.amount}. QD 87 Dieu 8 distinguishes failing to top up '
                f'from topping up ONLY PARTIALLY, and both leave the call open '
                f'-- so a zero contribution is not a partial cure, it is the '
                f'caller recording nothing. Do not construct one')
        if self.quantity < 0:
            raise ValueError(f'quantity must not be negative, got '
                             f'{self.quantity}')


def cure_credit(contribution: CureContribution,
                target_ratio: Decimal) -> Decimal:
    """How much of the DERIVED cure gap one contribution closes.

    **DERIVED, like everything else off Dieu 7.2.** The four coefficients are
    the table in :class:`TopUpRequirement`, inverted: a contribution is scored
    in the same cash-equivalent units as :attr:`TopUpRequirement.gap`, so a
    mixed answer -- some cash, some stock, a partial sale -- adds up.

    ==================================  ==========================
    contribution                        credit
    ==================================  ==========================
    cash swept against ``DB``           ``amount``
    cash left in ``CB``                 ``amount x (1 - target)``
    eligible securities posted          ``amount x (1 - target)``
    self-directed sale repaying ``DB``  ``amount x target``
    self-directed sale, proceeds kept   **zero**
    ==================================  ==========================

    The last row is not a rounding of the one above it. ``PV`` falls and ``CB``
    rises by the same amount, so ``EB`` and ``AB`` are both unchanged and the
    ratio does not move. A client who sells stock in answer to a call and leaves
    the money in the account has done nothing, and the machine must say so
    rather than credit the sale.

    Note the credit is scored on **gross** proceeds. Selling costs -- the 0.1 %
    transfer tax, the brokerage commission -- reduce what actually reaches the
    debt, so a real sale closes slightly less of the gap than this returns.
    Those charges belong to ``session/charges.py`` and are the caller's to net
    off before recording the contribution; this function will not invent a fee
    schedule. Declared in :data:`PROVENANCE` under ``cure_credit_is_gross``.
    """
    _require_decimal('target_ratio', target_ratio)
    if not _ZERO < target_ratio < _ONE:
        raise ValueError(f'target_ratio must be strictly between 0 and 1, got '
                         f'{target_ratio}')
    if contribution.method is CureMethod.DEPOSIT_CASH:
        if contribution.applied_to_debt:
            return contribution.amount
        return contribution.amount * (_ONE - target_ratio)
    if contribution.method is CureMethod.POST_SECURITIES:
        return contribution.amount * (_ONE - target_ratio)
    if contribution.method is CureMethod.SELL_SECURITIES:
        if contribution.applied_to_debt:
            return contribution.amount * target_ratio
        return _ZERO
    raise ValueError(f'unhandled cure method {contribution.method!r}')


# --------------------------------------------------------------------------
# What a forced sale may reach, and in what order -- spec 2.9, 3.3. SILENT.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class MarginCollateralPosition:
    """One pledged holding, as the forced-sale planner needs to see it.

    Deliberately **not** a portfolio position. This package models the exchange
    and a thin broker, not a portfolio, and the fields here are exactly the ones
    a *ban giai chap* decision reads: what it is worth, how the firm's ordering
    rule ranks it, and whether it is the position that broke.

    ``price`` must already carry the QD 87 Dieu 2.4 cap -- valued by the CTCK
    but **not above the last close**. The haircut (*ty le cho vay*) is the
    caller's to apply when it builds ``PV``; it is carried here as
    :attr:`loan_ratio` only because
    :attr:`LiquidationOrder.LOWEST_LOAN_RATIO_FIRST` ranks on it.

    Attributes:
        ticker: the security.
        quantity: shares pledged and available to sell.
        price: the capped valuation per share, or ``None`` where the security
            could not be valued. An unpriced position **cannot be sized** and is
            reported in :attr:`ForcedSalePlan.unsellable` rather than sold at a
            guess -- and upstream it should already have made the whole account
            :attr:`MarginAccountStatus.INDETERMINATE`.
        loan_ratio: the firm's *ty le cho vay*. ``None`` means the firm does not
            lend against this ticker, which ranks it as the weakest collateral
            there is under ``LOWEST_LOAN_RATIO_FIRST``.
        is_eligible: whether it is on the margin list. An ineligible holding is
            still the client's property and still sellable -- TT 120 Dieu 9.6
            removes it from the **collateral base**, not from the account.
        is_breaching: whether this is the position that caused the breach.
            Read only by :attr:`ForcedSaleScope.BREACHING_POSITION` and
            :attr:`LiquidationOrder.BREACHING_FIRST`, both of which are
            per-deal shapes.
        deal_id: the deal or sub-account this sits in, at finer granularity
            than :attr:`AccountingUnit.ACCOUNT`.
        unrealised_pnl: profit or loss against cost, used only by
            :attr:`LiquidationOrder.LARGEST_LOSS_FIRST`. ``None`` where cost is
            unknown, which sorts **last** rather than first: an unknown loss is
            not evidence of a large one.
    """

    ticker: str
    quantity: int
    price: Optional[Decimal] = None
    loan_ratio: Optional[Decimal] = None
    is_eligible: bool = True
    is_breaching: bool = False
    deal_id: Optional[str] = None
    unrealised_pnl: Optional[Decimal] = None

    def __post_init__(self) -> None:
        if self.price is not None:
            _require_decimal('price', self.price)
        if self.loan_ratio is not None:
            _require_decimal('loan_ratio', self.loan_ratio)
        if self.unrealised_pnl is not None:
            _require_decimal('unrealised_pnl', self.unrealised_pnl)
        if self.quantity < 0:
            raise ValueError(f'quantity must not be negative, got '
                             f'{self.quantity}')

    @property
    def market_value(self) -> Optional[Decimal]:
        """``quantity x price``, or ``None`` where the price is unknown."""
        if self.price is None:
            return None
        return Decimal(self.quantity) * self.price

    @property
    def is_sellable(self) -> bool:
        """Whether a sale of this position can be sized at all."""
        return (self.price is not None and self.price > _ZERO
                and self.quantity > 0)


@runtime_checkable
class PositionSelector(Protocol):
    """A pluggable forced-sale ordering. **The order is not law.**

    QD 87 Dieu 12.2(i) requires only that the *contract* state *"phuong thuc xu
    ly tai san the chap"*; no Vietnamese document prescribes which position a
    CTCK reaches for first. Section 4 of the spec lists it first among the
    things not to invent. So the ordering is a plug, and the default plug --
    :func:`liquidation_sequence` -- **invents nothing**: it dispatches on
    :attr:`BrokerMarginTerms.liquidation_order`, a field with no default, so
    the caller has always stated a policy before an ordering exists at all.

    Substituting one is the honest route for a firm whose contract states a list
    the five :class:`LiquidationOrder` members do not describe.

    Whatever is substituted must be **total and deterministic**: the same
    positions in a different input order must produce the same sequence, or two
    runs of the same scenario liquidate different stock.
    """

    def __call__(self, positions: Sequence[MarginCollateralPosition],
                 order: LiquidationOrder, *,
                 ranking: Sequence[str] = ()
                 ) -> Tuple[MarginCollateralPosition, ...]:
        ...


def _ranking_index(position: MarginCollateralPosition,
                   ranking: Sequence[str]) -> int:
    """Where a position sits in a caller-supplied ranking, by ticker or deal."""
    for index, name in enumerate(ranking):
        if name == position.ticker or (position.deal_id is not None
                                       and name == position.deal_id):
            return index
    return len(ranking)


def liquidation_sequence(positions: Sequence[MarginCollateralPosition],
                         order: LiquidationOrder, *,
                         ranking: Sequence[str] = (),
                         ) -> Tuple[MarginCollateralPosition, ...]:
    """The default :class:`PositionSelector`. **Ordering is a broker term.**

    Nothing in this function is sourced, and it does not pick an ordering: it
    implements the five :class:`LiquidationOrder` members so that a caller who
    has stated one gets it. The analogue on the derivatives side is
    ``deposit.liquidation_sequence``, which carries the same warning for the
    same reason -- there, too, an ordering was adopted that no Vietnamese
    document prescribes.

    Every key ends in ``ticker`` then ``deal_id``, so the sequence is **total
    and stable**: two runs of one scenario liquidate the same stock in the same
    order, whatever order the caller happened to build the list in.

    Two ranking choices inside the members are ours and are pinned by tests:

    * ``LARGEST_LOSS_FIRST`` sorts positions with **no known P&L last**. An
      unknown loss is not evidence of a large one, and sorting them first would
      liquidate the positions the caller knows least about.
    * ``LOWEST_LOAN_RATIO_FIRST`` treats a missing *ty le cho vay* as **zero**,
      i.e. the weakest collateral there is. A ticker the firm will not lend
      against contributes nothing to ``PV``, so selling it first releases the
      least borrowing capacity per dong raised -- which is the point of the
      ordering.

    Raises:
        ValueError: for ``BROKER_RANKED`` with an empty ``ranking``. That member
            means "the contract states a list"; with no list it would silently
            become an alphabetical sort, which is an ordering nobody chose.
    """
    items = list(positions)
    if order is LiquidationOrder.BROKER_RANKED and not ranking:
        raise ValueError(
            'LiquidationOrder.BROKER_RANKED needs an explicit ranking. The '
            'member exists for a firm whose hop dong giao dich ky quy states '
            'the disposal list QD 87 Dieu 12.2(i) requires it to state; with no '
            'list it would degenerate into an alphabetical sort, which is an '
            'ordering no contract chose. Pass ranking=(...) or select another '
            'LiquidationOrder')

    def tail(p: MarginCollateralPosition) -> Tuple[str, str]:
        return (p.ticker, p.deal_id or '')

    if order is LiquidationOrder.BREACHING_FIRST:
        key = lambda p: (0 if p.is_breaching else 1,) + tail(p)  # noqa: E731
    elif order is LiquidationOrder.LARGEST_LOSS_FIRST:
        key = lambda p: ((1, _ZERO) if p.unrealised_pnl is None  # noqa: E731
                         else (0, p.unrealised_pnl)) + tail(p)
    elif order is LiquidationOrder.LARGEST_POSITION_FIRST:
        key = lambda p: ((1, _ZERO) if p.market_value is None  # noqa: E731
                         else (0, -p.market_value)) + tail(p)
    elif order is LiquidationOrder.LOWEST_LOAN_RATIO_FIRST:
        key = lambda p: (p.loan_ratio or _ZERO,) + tail(p)  # noqa: E731
    elif order is LiquidationOrder.BROKER_RANKED:
        key = lambda p: (_ranking_index(p, ranking),) + tail(p)  # noqa: E731
    else:
        raise ValueError(f'unhandled liquidation order {order!r}')

    return tuple(sorted(items, key=key))


def positions_in_scope(positions: Sequence[MarginCollateralPosition],
                       scope: ForcedSaleScope, *,
                       ranking: Sequence[str] = (),
                       deal_id: Optional[str] = None,
                       ) -> Tuple[MarginCollateralPosition, ...]:
    """Which holdings a sale under this firm's policy may touch at all.

    Scope is a different question from ordering and from quantity, and the
    record keeps the three apart. QD 87 Dieu 8 bounds the **quantity** -- *part
    or all of the pledged securities, depending on whether the remaining
    required collateral is smaller or larger than the total value in the
    account* -- and says nothing about which holdings are in play. DNSE touches
    only the breaching deal and leaves the rest of the sub-account alone;
    that is a commercial policy, REPORTED at one firm.

    Raises:
        ValueError: for ``BREACHING_POSITION`` when nothing identifies the
            breaching position, and for ``BROKER_RANKED`` with no ranking.
            Both would otherwise return an empty scope, and a sale that
            silently sells nothing because the caller forgot to flag a deal is
            indistinguishable from an account with nothing to sell.
    """
    if scope is ForcedSaleScope.WHOLE_ACCOUNT:
        return tuple(positions)
    if scope is ForcedSaleScope.BREACHING_POSITION:
        chosen = tuple(p for p in positions
                       if p.is_breaching
                       or (deal_id is not None and p.deal_id == deal_id))
        if not chosen:
            raise ValueError(
                f'ForcedSaleScope.BREACHING_POSITION was asked to size a sale '
                f'but nothing identifies the breaching position: no holding '
                f'carries is_breaching, and deal_id={deal_id!r} matches none. '
                f'This scope only makes sense at sub-account or deal '
                f'granularity -- see BrokerMarginTerms.accounting_unit')
        return chosen
    if scope is ForcedSaleScope.BROKER_RANKED:
        if not ranking:
            raise ValueError(
                'ForcedSaleScope.BROKER_RANKED needs an explicit ranking; it '
                'means "the contract names the holdings in play"')
        return tuple(p for p in positions if _ranking_index(p, ranking)
                     < len(ranking))
    raise ValueError(f'unhandled forced sale scope {scope!r}')


#: The order in which simultaneous force-sale triggers are reported.
#:
#: **Ours, and unsourced.** QD 87 Dieu 8 gives one trigger -- failure to top up
#: within the deadline. Everything else in :class:`ForcedSaleTrigger` is a
#: broker term, no document ranks them, and an account can easily satisfy three
#: at once (below the force level, past its cure deadline, and three days into a
#: breach). :attr:`ForcedSalePlan.triggers` carries **all** of them; this order
#: only decides which one goes in the single-valued
#: :attr:`ForcedSaleInstruction.trigger` field, so a log can be counted by
#: cause.
#:
#: The ranking is by immediacy: the force level bypasses the cure window
#: entirely, so it comes first; the statutory trigger comes next; the three
#: broker clocks follow. Declared in :data:`PROVENANCE` under
#: ``forced_sale_trigger_priority``.
FORCED_SALE_TRIGGER_PRIORITY: Tuple[ForcedSaleTrigger, ...] = (
    ForcedSaleTrigger.FORCE_LEVEL_BREACHED,
    ForcedSaleTrigger.CURE_WINDOW_EXPIRED,
    ForcedSaleTrigger.CONSECUTIVE_BREACH_DAYS,
    ForcedSaleTrigger.LOAN_OVERDUE,
    ForcedSaleTrigger.COLLATERAL_INELIGIBLE,
)


@dataclass(frozen=True)
class ForcedSalePlan:
    """One *ban giai chap* decision: what to sell, why, and whether it is enough.

    **A plan, not an execution, and not even an order.** The engine reports that
    a sale is due, over which holdings, at what price policy and for what
    reason; the caller submits the tickets and reports the fills back. That
    boundary is the same one :class:`ForcedSaleInstruction` draws, and it is why
    the notice timestamps are inputs rather than assumptions.

    **The shortfall is the point of the record.** QD 87 Dieu 8 contemplates
    liquidation that does not cover ``DB`` and leaves the CTCK recovering the
    residual under the contract and general law. An account whose ``AB`` has
    gone negative cannot be restored by selling anything -- see
    :func:`value_to_restore` -- and :attr:`restores_target` says so instead of
    the plan quietly selling everything and reporting success.

    Attributes:
        account_id: the segregated margin account.
        as_of: the instant the plan was made.
        trigger: the highest-priority live trigger, per
            :data:`FORCED_SALE_TRIGGER_PRIORITY`.
        triggers: **every** live trigger, unranked-by-severity in that same
            order. More than one is normal.
        target_ratio: the ratio the sale sizes itself to restore --
            :attr:`BindingPolicy.cure_target_ratio`, or that plus
            :attr:`BrokerMarginTerms.forced_sale_target_buffer` under
            :attr:`ForcedSaleTarget.MAINTENANCE_PLUS_BUFFER`.
        value_to_raise: the DERIVED ``EB - AB / target``.
        value_available: total market value of the in-scope, priceable
            holdings. Less than ``value_to_raise`` is the Dieu 8 shortfall.
        planned_value: gross value of the tickets at the valuation the sizing
            used, before charges. At or a little above :attr:`value_to_raise`
            when the plan restores the target, because share counts are whole
            numbers and the last ticket rounds up. **Not what the sale will
            realise** under :attr:`ForcedSalePrice.FLOOR` -- see
            :meth:`MarginCallMonitor.plan_forced_sale`.
        instructions: the tickets, in the firm's stated liquidation order.
        scope: which holdings were in play.
        selection_order: the firm's stated ordering. Carried so the log can say
            what it was -- an adopted ordering that reports itself is the whole
            point of the field's existing.
        price_policy: :attr:`BrokerMarginTerms.forced_sale_price`. SILENT in
            the regulation.
        call_id: the call this escalated from, or ``None`` for the branches
            that never issue one -- a force-level breach or an overdue loan.
        unsellable: tickers skipped because they could not be priced.
        note: free text, used for the notice breach and the empty-scope case.
    """

    account_id: str
    as_of: datetime
    trigger: ForcedSaleTrigger
    triggers: Tuple[ForcedSaleTrigger, ...]
    target_ratio: Decimal
    value_to_raise: Decimal
    value_available: Decimal
    planned_value: Decimal
    instructions: Tuple[ForcedSaleInstruction, ...]
    scope: ForcedSaleScope
    selection_order: LiquidationOrder
    price_policy: ForcedSalePrice
    call_id: Optional[str] = None
    unsellable: Tuple[str, ...] = ()
    note: Optional[str] = None

    @property
    def restores_target(self) -> bool:
        """Whether selling everything in scope can reach the target at all.

        ``False`` is QD 87 Dieu 8's shortfall: the CTCK recovers the residual
        under the contract and general law, and the client's withdrawal right
        is over the remainder after the debt is deducted -- of which there is
        none.
        """
        return self.value_available >= self.value_to_raise

    @property
    def shortfall(self) -> Decimal:
        """How much of the requirement no sale in scope can raise. Never negative."""
        gap = self.value_to_raise - self.value_available
        return gap if gap > _ZERO else _ZERO

    @property
    def notice_satisfied(self) -> bool:
        """Whether every ticket carries QD 87 Dieu 8's before-the-order notice.

        ``False`` for an empty plan, deliberately: a sale nobody was told about
        is not made compliant by there being nothing to sell.
        """
        return bool(self.instructions) and all(
            i.notice_satisfied for i in self.instructions)


# --------------------------------------------------------------------------
# Applying the proceeds -- spec 2.9. The ORDER is SILENT; the residual is not.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ProceedsApplication:
    """Where the money from a *ban giai chap* went.

    **Two different grades in one record, and they must not be blurred.**

    * That the client gets only *"phan con lai sau khi tru no ky quy"* where all
      the securities are sold is **QD 87 Dieu 8, VERIFIED**. :attr:`residual` is
      that remainder, and :attr:`MarginRegulation.withdrawal_only_after_debt_deducted`
      is the rule.
    * The **order** in which principal, interest, fees and taxes are paid is
      **SILENT** -- QD 87 Dieu 12.2(i) requires the contract to state *"thu tu
      uu tien su dung tien ban chung khoan the chap"* and no document supplies
      one. It comes from
      :attr:`BrokerMarginTerms.proceeds_application_order`, which has no
      default.

    The order changes nothing when the proceeds cover everything. It decides
    **which component goes unpaid** when they do not, which is the case that
    matters and the one a test pins.

    Attributes:
        proceeds: what the sale raised, net of whatever the caller already
            deducted.
        order: the firm's stated priority.
        applied: how much each component received.
        unpaid: what each component is still owed. Non-empty values are the
            residual debt QD 87 Dieu 8 leaves the CTCK to recover under the
            contract and general law.
        residual: what is left for the client. Zero whenever anything is
            unpaid.
    """

    proceeds: Decimal
    order: Tuple[ProceedsComponent, ...]
    applied: Mapping[ProceedsComponent, Decimal]
    unpaid: Mapping[ProceedsComponent, Decimal]
    residual: Decimal

    @property
    def fully_discharged(self) -> bool:
        """Whether every component was paid in full."""
        return all(v <= _ZERO for v in self.unpaid.values())


def apply_sale_proceeds(proceeds: Decimal,
                        owed: Mapping[ProceedsComponent, Decimal],
                        order: Sequence[ProceedsComponent],
                        ) -> ProceedsApplication:
    """Pay down what is owed in the firm's stated order. QD 87 Dieu 8 / 12.2(i).

    Args:
        proceeds: gross or net sale proceeds, as the caller defines them. This
            function does not compute charges -- ``session/charges.py`` owns
            the transfer tax and the commission, and inventing them here would
            put two fee schedules in the codebase.
        owed: what each component is owed. A component absent from the mapping
            is owed nothing.
        order: a **permutation of every** :class:`ProceedsComponent` exactly
            once, matching the shape
            :attr:`BrokerMarginTerms.proceeds_application_order` is validated
            to. A partial order would leave a component unpriced and the
            residual would then be the client's money paying an invisible
            claim.

    Raises:
        ValueError: for a partial or repeating order, or a negative amount.
    """
    _require_decimal('proceeds', proceeds)
    if proceeds < _ZERO:
        raise ValueError(f'proceeds must not be negative, got {proceeds}')
    ordered = tuple(order)
    if sorted(ordered, key=lambda c: c.value) != sorted(ProceedsComponent,
                                                        key=lambda c: c.value):
        raise ValueError(
            f'proceeds order must name every ProceedsComponent exactly once, '
            f'got {[c.value for c in ordered]}. QD 87 Dieu 12.2(i) delegates '
            f'the priority to the contract by name, so it is stated in full or '
            f'not at all -- a partial order leaves a component unpriced and '
            f'hands the client money that is owed elsewhere')

    remaining = proceeds
    applied: Dict[ProceedsComponent, Decimal] = {}
    unpaid: Dict[ProceedsComponent, Decimal] = {}
    for component in ordered:
        due = owed.get(component, _ZERO)
        _require_decimal(f'owed[{component.value}]', due)
        if due < _ZERO:
            raise ValueError(f'owed[{component.value}] must not be negative, '
                             f'got {due}')
        paid = due if remaining >= due else remaining
        applied[component] = paid
        unpaid[component] = due - paid
        remaining -= paid

    return ProceedsApplication(
        proceeds=proceeds,
        order=ordered,
        applied=MappingProxyType(applied),
        unpaid=MappingProxyType(unpaid),
        residual=remaining,
    )


# --------------------------------------------------------------------------
# Errors the state machine raises
# --------------------------------------------------------------------------

class ForcedSaleNotAuthorised(RuntimeError):
    """A forced sale was asked for on an account that has no right to one.

    **This is the guard the whole section is built around.** QD 87 Dieu 8 gives
    the CTCK the right to sell a client's property in two circumstances only --
    the client failed to top up, or topped up only partially, within the call
    deadline -- and the market adds the force-sell level, which the firm's own
    contract states. Outside those, selling a client's securities is not a
    liquidation, it is a disposal of somebody else's property.

    So :meth:`MarginCallMonitor.plan_forced_sale` does **not** take a trigger.
    It derives one from state the monitor observed itself, and raises this when
    there is none. A caller cannot argue an account into a liquidation, and a
    test that forgets to drive the account below a level gets an exception
    rather than a plan.

    A ``RuntimeError`` and not a ``ValueError``: nothing is wrong with the
    arguments. The account is in the wrong state.

    Attributes:
        account_id: the segregated margin account.
        status: where the account actually was on the ladder.
        reason: prose for the log.
    """

    def __init__(self, account_id: str,
                 status: Optional[MarginAccountStatus], reason: str) -> None:
        self.account_id = account_id
        self.status = status
        self.reason = reason
        super().__init__(
            f'no forced-sale right exists for account {account_id!r} '
            f'(status={status.value if status is not None else "unobserved"}): '
            f'{reason}')


class NoOpenMarginCall(LookupError):
    """A cure was recorded against an account with no call outstanding.

    Silently accepting it would lose the distinction the whole state machine
    exists to keep: a top-up in answer to a call is a cure with a deadline
    attached, and money arriving at an account nobody called is a deposit. The
    two have different consequences for :attr:`MarginCall.status`, for the
    consecutive-breach counter and for QD 87 Dieu 13.8's per-account books.

    Attributes:
        account_id: the segregated margin account.
        reason: prose for the log.
    """

    def __init__(self, account_id: str, reason: str) -> None:
        self.account_id = account_id
        self.reason = reason
        super().__init__(f'account {account_id!r} has no open margin call: '
                         f'{reason}')


# --------------------------------------------------------------------------
# The state machine itself
# --------------------------------------------------------------------------

class MarginCallMonitor:
    """The day loop. **A margin call is STATE, not an event.**

    This is a class and not a function for exactly the reason
    ``deposit.MarginMonitor`` is: an outstanding call has to be carried across
    sessions, and there is nowhere in a batch computation to put one::

        day T    ratio falls below the call level -> MarginCall(deadline=T+3bd)
                 the client may deposit, post collateral, sell, or do nothing
        day T+1  still short -> the call is still open, and is NOT re-issued
        day T+2  still short -> still open
        day T+3  still short, deadline reached -> CALL_EXPIRED, sale due

    Re-issuing the call on every observation would turn one three-day obligation
    into three separate ones and would reset the clock each time -- which is the
    bug the state-versus-event distinction exists to prevent, and it is the same
    lesson the derivatives deposit already learned.

    **Two levels, and only one of them grants a window.** Brokers run a call
    level and a force-sell level (spec 3.2). Below the call level a *lenh goi ky
    quy bo sung* issues and the client gets the contractual window, capped at
    three business days by QD 87 Dieu 7.1. Below the force-sell level the sale
    fires **immediately**, with no window at all -- SSI force-sells *"ngay khi"*
    the *TLKQ xu ly* is breached. A model with one threshold cannot express a
    Vietnamese broker, and a machine that invented an intermediate call on the
    way past the force level would grant a cure right the contract does not.

    **The tighter of statute and contract binds.** The window and both levels
    come from :class:`BindingPolicy`, not from the terms directly, so a run that
    crosses an SSC adjustment under QD 87 Dieu 5.3 is graded against the floor
    in force on the day rather than the floor the contract was signed under.

    **Five ways a sale becomes due, and they do not share a clock** -- see
    :class:`ForcedSaleTrigger`. Only the first is statutory:

    * ``CURE_WINDOW_EXPIRED`` -- QD 87 Dieu 8. VERIFIED.
    * ``FORCE_LEVEL_BREACHED`` -- bypasses the window entirely.
    * ``CONSECUTIVE_BREACH_DAYS`` -- SSI uses three, the statutory ceiling used
      in full.
    * ``LOAN_OVERDUE`` -- SSI >= 3 business days, ACBS the 5th. They disagree,
      which is why it is a term.
    * ``COLLATERAL_INELIGIBLE`` -- off by default, see the constructor.

    **Every transition that creates or discharges an obligation emits an
    event.** A call issuing, curing, partially curing and expiring; a
    forced-sale right arising, by whichever of the five paths; a sale noticed,
    instructed and reported on; lending suspended and resumed; collateral
    leaving the margin list; entry into a blind stretch. One transition
    deliberately emits nothing: a **force-sell right lapsing** when the ratio
    recovers with no call behind it. That is not an oversight -- the force-sell
    level creates no client obligation, unlike a call, so there is nothing to
    discharge and nothing to report. Where a call *was* behind it, the lapse
    emits ``CALL_CURED`` with ``after_expiry`` set.

    **A blind observation is not an observation.** An ``INDETERMINATE`` reading
    -- an unpriced holding, an eligibility predicate that needs issuer
    financials the corpus does not carry -- advances nothing: no cure, no
    expiry, no escalation, and :attr:`last_status` still reports the last thing
    actually seen. Both alternatives are wrong in ways that matter. Clearing an
    open call would report a cure nobody paid; expiring one would sell an
    account against a price nobody saw. A deadline that falls during a blind
    stretch therefore **survives it** and bites on the first observation that
    has data, which is the conservative direction and is what a broker does when
    its price feed is down.

    **What this class does not do.** It does not compute the ratio -- that is
    QD 87 Dieu 2's algebra and it arrives as a :class:`MarginAccountAlgebra`.
    It does not place orders; :meth:`plan_forced_sale` returns instructions and
    the caller submits them. It does not accrue interest or extend loans; it
    only reads :attr:`MarginLoan.due_on` for the overdue trigger. And it does
    not send the client anything: the notice QD 87 Dieu 8 requires **before**
    the sell order is an input, never a value this class manufactures, because
    an engine that stamped its own compliance could not report a breach of it.

    One monitor per **accounting unit**, matching
    :attr:`BrokerMarginTerms.accounting_unit`: one per margin account at
    ``ACCOUNT`` granularity, one per deal at ``DEAL``. TT 120 Dieu 9.3's
    segregation is why the account identifier is a constructor argument and why
    a state for a different account is refused rather than absorbed.
    """

    def __init__(self, account_id: str, terms: BrokerMarginTerms,
                 calendar: BusinessDayCalendar, *,
                 regulation: Optional[MarginRegulation] = None,
                 selector: Optional[PositionSelector] = None,
                 broker_ranking: Sequence[str] = (),
                 sell_on_ineligible_collateral: bool = False,
                 deal_id: Optional[str] = None) -> None:
        """Bind one account to one set of terms.

        Args:
            account_id: the segregated margin account (TT 120 Dieu 9.3).
            terms: the firm's commercial terms.
            calendar: business days for the cure deadline and the overdue
                clock. See :class:`BusinessDayCalendar` on why this module
                refuses to own one.
            regulation: the statutory row in force for the run. Defaults to
                ``terms.regulation``; pass :func:`regulation_in_force` when a
                run crosses a dated change.
            selector: a :class:`PositionSelector` replacing the default
                ordering. The default, :func:`liquidation_sequence`, invents
                nothing -- it dispatches on the firm's own
                :attr:`BrokerMarginTerms.liquidation_order`, which has no
                default of its own.
            broker_ranking: the disposal list for
                :attr:`LiquidationOrder.BROKER_RANKED` or
                :attr:`ForcedSaleScope.BROKER_RANKED`, by ticker or deal id.
            sell_on_ineligible_collateral: whether a pledged security falling
                off the margin list may itself make a sale due.

                **Defaults to False, and that is our conservative choice.** TT
                120 Dieu 9.6's exclusion from the collateral base is statutory
                and unconditional -- it lands in the ratio whatever this flag
                says, by lowering ``PV``. Whether the firm additionally
                *liquidates* on it is nowhere stated, so the default is that it
                does not, and the ratio speaks for itself. Even when enabled the
                trigger requires the account to be **actually in breach**:
                selling because a ticker left the list while the ratio is
                comfortable would be a disposal with no rule behind it.

                It is a constructor argument rather than a
                :class:`BrokerMarginTerms` field only because that object is
                owned by another stage; it belongs there when the two merge.
            deal_id: the deal this monitor watches, at finer granularity than
                ``ACCOUNT``.
        """
        self.account_id = account_id
        self.terms = terms
        self.calendar = calendar
        self.deal_id = deal_id
        #: The thresholds that actually bind. See :class:`BindingPolicy`.
        self.policy = binding_policy(terms, regulation)
        self.selector: PositionSelector = selector or liquidation_sequence
        self.broker_ranking: Tuple[str, ...] = tuple(broker_ranking)
        self.sell_on_ineligible_collateral = bool(sell_on_ineligible_collateral)

        self._calls: List[MarginCall] = []
        self._call: Optional[MarginCall] = None
        self._expired_call: Optional[MarginCall] = None
        self._requirement: Decimal = _ZERO
        self._cured: Decimal = _ZERO
        self._contributions: List[CureContribution] = []
        self._breach_days: List[date] = []
        self._last_status: Optional[MarginAccountStatus] = None
        self._last_observed_at: Optional[datetime] = None
        self._ineligible_value: Optional[Decimal] = None
        self._suspended = False
        self._due: Optional[ForcedSaleTrigger] = None
        self._due_all: Tuple[ForcedSaleTrigger, ...] = ()
        self._instructions: Dict[str, ForcedSaleInstruction] = {}
        self._seq = 0

    # -- what the caller can see ------------------------------------------

    @property
    def open_call(self) -> Optional[MarginCall]:
        """The outstanding *lenh goi ky quy bo sung*, or ``None``.

        ``PARTIALLY_CURED`` still appears here: QD 87 Dieu 8 treats a partial
        top-up exactly as a failure to top up for the purposes of the
        force-sale right.
        """
        return self._call

    @property
    def calls(self) -> Tuple[MarginCall, ...]:
        """Every call this account has been issued, with its final status.

        QD 87 Dieu 13.8 requires the CTCK to keep per-account books recording
        **every call** alongside the daily collateral inventory and end-of-day
        ratio, which is why the history is kept rather than only the live one.
        """
        return tuple(self._calls)

    @property
    def last_status(self) -> Optional[MarginAccountStatus]:
        """The ladder rung of the last observation that could decide one.

        ``None`` before the first observation -- an account nobody has looked
        at is **not** ``OK``, and defaulting it to ``OK`` would let an
        unobserved account read as compliant. An ``INDETERMINATE`` observation
        does update this, because the fact that the data could not decide is
        itself the last thing known.
        """
        return self._last_status

    @property
    def breach_days(self) -> Tuple[date, ...]:
        """Distinct dates on which the account was observed below the call level.

        Reset by an observation at or above the call level, and **not** by a
        cure. That is deliberate and it is the interlock behind SSI's
        consecutive-breach rule: a client who tops up just enough each morning
        to clear the call, and is back in breach by the close, never resets this
        counter and is force-sold on the third day. Only an actual ratio at or
        above the call level clears it.

        Counted by **observation date**, not by walking the calendar: the
        machine counts days it actually saw. An intraday run that observes ten
        times a day still counts one.
        """
        return tuple(self._breach_days)

    @property
    def forced_sale_due(self) -> Optional[ForcedSaleTrigger]:
        """The highest-priority live trigger, or ``None`` if no right exists.

        ``None`` here is exactly the condition under which
        :meth:`plan_forced_sale` raises :class:`ForcedSaleNotAuthorised`.
        """
        return self._due

    @property
    def forced_sale_triggers(self) -> Tuple[ForcedSaleTrigger, ...]:
        """**Every** live trigger, in :data:`FORCED_SALE_TRIGGER_PRIORITY` order."""
        return self._due_all

    @property
    def contributions(self) -> Tuple[CureContribution, ...]:
        """What the client has done against the currently open call."""
        return tuple(self._contributions)

    @property
    def cure_progress(self) -> Tuple[Decimal, Decimal]:
        """``(credited, required)`` against the open call, in cash-equivalent terms.

        Both are **DERIVED** -- see :class:`TopUpRequirement`. ``(0, 0)`` when
        no call is open.
        """
        return (self._cured, self._requirement)

    @property
    def instructions(self) -> Tuple[ForcedSaleInstruction, ...]:
        """Every forced-sale ticket this monitor has raised."""
        return tuple(self._instructions.values())

    # -- the day loop ------------------------------------------------------

    def observe(self, state: MarginAccountState,
                algebra: MarginAccountAlgebra) -> Tuple[MarginEvent, ...]:
        """One observation. Returns the events that are **news**, oldest first.

        Empty when nothing changed -- in particular an open call inside its
        window is **not** re-reported on every observation, which is what makes
        it state rather than a repeated event.

        Both records are required and both are checked, because they answer
        different halves of the question and a mismatched pair is a silent
        wrong answer: ``algebra`` carries the ratio and the Dieu 2 aggregates,
        ``state`` carries the loans behind the overdue trigger, the suspension
        flag and the ineligible collateral. They must describe the same account
        at the same instant.

        Args:
            state: the account's inputs at ``as_of``.
            algebra: the Dieu 2 outputs at the same instant, computed by the
                caller.

        Raises:
            ValueError: if either record names a different account, if the two
                instants differ, if the observation goes backwards in time, or
                if an intraday algebra arrives at a firm whose terms say it
                monitors end-of-day only. The last is not pedantry: QD 87 Dieu
                6.1 mandates end-of-day at a valuation capped by the last close,
                brokers in 2026 sweep hourly at live prices, and a run that
                claims the first while being fed the second is reporting a
                regime it did not run.
        """
        if state.account_id != self.account_id:
            raise ValueError(
                f'state is for account {state.account_id!r}, this monitor '
                f'watches {self.account_id!r}. TT 120 Dieu 9.3 makes the margin '
                f'account segregated per investor; one monitor is one account')
        if algebra.account_id != self.account_id:
            raise ValueError(
                f'algebra is for account {algebra.account_id!r}, this monitor '
                f'watches {self.account_id!r}')
        if state.as_of != algebra.as_of:
            raise ValueError(
                f'state is as of {state.as_of} and algebra as of '
                f'{algebra.as_of}. The algebra is a pure function of the state, '
                f'so a mismatch means yesterday\'s ratio is about to be graded '
                f'against today\'s loans')
        ts = algebra.as_of
        if self._last_observed_at is not None and ts < self._last_observed_at:
            raise ValueError(
                f'observation at {ts} is earlier than the last one at '
                f'{self._last_observed_at}. The cure clock, the breach-day '
                f'counter and the call history are all ordered; replaying an '
                f'earlier instant into them corrupts every one')
        if (algebra.basis is RatioDetermination.INTRADAY
                and not self.terms.intraday_monitoring):
            raise ValueError(
                'an INTRADAY algebra arrived at terms with '
                'intraday_monitoring=False. QD 87 Dieu 6.1 mandates the '
                'end-of-day computation; intraday is the 2026 market practice '
                'and a broker OPTION (spec section 4, SILENT item 6). A run '
                'configured for the statutory floor behaviour that is fed '
                'intraday marks reports a regime it did not run')

        events: List[MarginEvent] = []

        # -- suspension is a fact about the firm, not about prices, so it is
        #    reported even in a blind stretch. TT 120 Dieu 9.9 / 9.7.
        if state.lending_suspended != self._suspended:
            self._suspended = state.lending_suspended
            events.append(self._event(
                MarginEventKind.LENDING_SUSPENDED if self._suspended
                else MarginEventKind.LENDING_RESUMED, ts,
                detail={'article': 'TT 120 Dieu 9.9 (SSC stabilisation order) '
                                   'or Dieu 9.7 (loss of eligibility)',
                        'note': 'new lending stops; existing debt does not '
                                'vanish and an existing breach is not cured'}))

        status = account_status(
            algebra.margin_ratio, self.policy,
            debt=algebra.margin_debt,
            suspended=state.lending_suspended,
            indeterminate=algebra.is_indeterminate
            or state.has_unpriced_collateral)

        if status is MarginAccountStatus.INDETERMINATE:
            if self._last_status is not MarginAccountStatus.INDETERMINATE:
                events.append(self._event(
                    MarginEventKind.INDETERMINATE, ts,
                    detail={'reasons': tuple(algebra.indeterminate_reasons)
                            + tuple(f'unpriced:{t}'
                                    for t in state.unpriced_tickers),
                            'note': 'the machine does not advance on a blind '
                                    'observation: no cure, no expiry, no '
                                    'escalation. A deadline falling inside a '
                                    'blind stretch survives it'}))
            self._last_status = MarginAccountStatus.INDETERMINATE
            self._last_observed_at = ts
            return tuple(events)

        # -- TT 120 Dieu 9.6: a security leaving the list stops counting toward
        #    the collateral base. The event is the news; whether it also makes a
        #    sale due is the firm's, and off by default.
        if (self._ineligible_value is not None
                and state.ineligible_securities_value > self._ineligible_value):
            events.append(self._event(
                MarginEventKind.COLLATERAL_BECAME_INELIGIBLE, ts,
                detail={'was': self._ineligible_value,
                        'now': state.ineligible_securities_value,
                        'article': 'TT 120 Dieu 9.6 over QD 87 Dieu 10.2',
                        'note': 'excluded from the collateral base for BOTH '
                                'ratios; it remains the client\'s property and '
                                'remains security for the existing loan'}))
        self._ineligible_value = state.ineligible_securities_value

        in_breach = status in (MarginAccountStatus.CALL,
                               MarginAccountStatus.FORCE_SELL)
        day = ts.date()
        if in_breach:
            if day not in self._breach_days:
                self._breach_days.append(day)
        else:
            self._breach_days = []

        ratio = algebra.margin_ratio

        # -- 1. did the ratio itself cure an outstanding call? ---------------
        if ratio is not None and self._call is not None \
                and ratio >= self._call.target_ratio:
            cured = self._update_call(status=MarginCallStatus.CURED,
                                      cured_at=ts)
            events.append(self._event(
                MarginEventKind.CALL_CURED, ts, call_id=cured.call_id,
                detail={'ratio': ratio, 'target_ratio': cured.target_ratio,
                        'by': 'observed ratio',
                        'note': 'the authoritative cure test -- the account is '
                                'back at the target, however it got there'}))
            self._clear_call()
        elif ratio is not None and self._expired_call is not None \
                and ratio >= self._expired_call.target_ratio:
            lapsed = self._expired_call
            self._clear_call()
            events.append(self._event(
                MarginEventKind.CALL_CURED, ts, call_id=lapsed.call_id,
                detail={'ratio': ratio, 'target_ratio': lapsed.target_ratio,
                        'after_expiry': True,
                        'note': 'OUR READING: the Dieu 8 right had arisen when '
                                'the window closed, and is dropped because the '
                                'account is no longer in breach. Selling a '
                                'compliant account is what the authority check '
                                'exists to prevent. The call keeps its EXPIRED '
                                'status in the Dieu 13.8 book'}))

        # -- 2. the five triggers, recomputed from scratch every observation --
        live: List[ForcedSaleTrigger] = []

        if status is MarginAccountStatus.FORCE_SELL:
            live.append(ForcedSaleTrigger.FORCE_LEVEL_BREACHED)

        if self._call is not None and ts >= self._call.deadline:
            expired = self._update_call(status=MarginCallStatus.EXPIRED)
            self._expired_call = expired
            self._call = None
            events.append(self._event(
                MarginEventKind.CALL_EXPIRED, ts, call_id=expired.call_id,
                detail={'deadline': expired.deadline, 'ratio': ratio,
                        'credited': self._cured,
                        'required': self._requirement,
                        'article': 'QD 87 Dieu 7.1 (the window) / Dieu 8 (the '
                                   'right that arises)',
                        'note': 'Dieu 8 gives the right where the client fails '
                                'to top up OR tops up only partially'}))
        if self._expired_call is not None:
            live.append(ForcedSaleTrigger.CURE_WINDOW_EXPIRED)

        if in_breach and len(self._breach_days) >= \
                self.terms.consecutive_breach_days_before_sale:
            live.append(ForcedSaleTrigger.CONSECUTIVE_BREACH_DAYS)

        for loan in state.loans:
            if loan.status in (LoanStatus.REPAID, LoanStatus.LIQUIDATED):
                continue
            if day <= loan.due_on:
                continue
            sale_from = self.calendar.add_business_days(
                loan.due_on, self.terms.overdue_business_days_before_sale)
            if day >= sale_from:
                live.append(ForcedSaleTrigger.LOAN_OVERDUE)
                break

        if (self.sell_on_ineligible_collateral and in_breach
                and state.ineligible_securities_value > _ZERO):
            live.append(ForcedSaleTrigger.COLLATERAL_INELIGIBLE)

        previous_due = self._due
        self._due_all = tuple(sorted(set(live),
                                     key=FORCED_SALE_TRIGGER_PRIORITY.index))
        self._due = self._due_all[0] if self._due_all else None
        if self._due is not None and self._due is not previous_due:
            events.append(self._event(
                MarginEventKind.FORCED_SALE_DUE, ts,
                call_id=(self._expired_call.call_id
                         if self._expired_call is not None else None),
                detail={
                    'trigger': self._due,
                    'triggers': self._due_all,
                    'ratio': ratio,
                    'call_level': self.policy.call_level,
                    'force_sell_level': self.policy.force_sell_level,
                    'force_sell_level_bound_by':
                        self.policy.force_sell_level_bound_by,
                    'note': 'FORCE_LEVEL_BREACHED bypasses the cure window '
                            'entirely -- no call is issued on the way past it. '
                            'Only CURE_WINDOW_EXPIRED is statutory (QD 87 Dieu '
                            '8); the other four are broker terms',
                }))

        # -- 3. issue a call. Only from the CALL band: the force level grants
        #       no window, and a call while a sale is already due would restart
        #       a clock the client has already run out.
        if (status is MarginAccountStatus.CALL and self._call is None
                and self._expired_call is None):
            events.append(self._issue_call(algebra, ts))

        self._last_status = status
        self._last_observed_at = ts
        return tuple(events)

    def _issue_call(self, algebra: MarginAccountAlgebra,
                    ts: datetime) -> MarginEvent:
        """Raise a *lenh goi ky quy bo sung* and start the clock. QD 87 Dieu 7."""
        target = self.policy.cure_target_ratio
        requirement = top_up_requirement(algebra.total_assets,
                                         algebra.net_assets, target)
        deadline = cure_deadline(ts, self.policy.cure_business_days,
                                 self.calendar)
        call = MarginCall(
            call_id=self._next_id('call'),
            account_id=self.account_id,
            issued_at=ts,
            deadline=deadline,
            target_ratio=target,
            status=MarginCallStatus.OPEN,
            ratio_at_issue=algebra.margin_ratio,
            top_up_cash=requirement.cash,
            top_up_securities_value=requirement.securities_value,
            cure_methods=self.policy.regulation.cure_methods,
            accounting_unit=self.terms.accounting_unit,
            deal_id=self.deal_id,
        )
        self._calls.append(call)
        self._call = call
        self._requirement = requirement.gap
        self._cured = _ZERO
        self._contributions = []
        return self._event(
            MarginEventKind.CALL_ISSUED, ts, call_id=call.call_id,
            detail={
                'ratio': algebra.margin_ratio,
                'call_level': self.policy.call_level,
                'call_level_bound_by': self.policy.call_level_bound_by,
                'target_ratio': target,
                'deadline': deadline,
                'cure_business_days': self.policy.cure_business_days,
                'cure_window_bound_by': self.policy.cure_window_bound_by,
                'top_up_cash': requirement.cash,
                'top_up_securities_value': requirement.securities_value,
                'top_up_self_sale_value': requirement.self_sale_value,
                'article': 'QD 87 Dieu 7.1; the 3-business-day ceiling is that '
                           'article ALONE -- TT 120 Dieu 9.6 carries the call '
                           'and the sale right but no day count',
                'top_up_grade': 'DERIVED -- QD 87 Dieu 7.2\'s two formulas are '
                                'images in every accessible mirror. These are '
                                'our arithmetic off the EB/AB algebra. DO NOT '
                                'QUOTE AS THE REGULATION',
            })

    # -- curing -------------------------------------------------------------

    def cure(self, contribution: CureContribution) -> Tuple[MarginEvent, ...]:
        """Record one client answer to the open call. QD 87 Dieu 7.

        The three methods are scored into one cash-equivalent number by
        :func:`cure_credit`, so a mixed answer adds up, and compared against the
        requirement recorded when the call issued.

        **A full cure here is PROVISIONAL and the docstring says so on purpose.**
        The requirement is the DERIVED gap at the moment of issue, which is what
        the client was actually told to pay; the authoritative test is the ratio
        at the next observation. A market move between the top-up and the next
        observation can put the account straight back in breach, which issues a
        **new** call with a **new** window -- and the consecutive-breach counter
        deliberately does not reset on a cure, so a client curing cosmetically
        every morning still reaches
        :attr:`ForcedSaleTrigger.CONSECUTIVE_BREACH_DAYS`.

        Returns:
            One event: ``CALL_CURED`` or ``CALL_PARTIALLY_CURED``.
            ``PARTIALLY_CURED`` leaves the call **open** -- QD 87 Dieu 8 treats
            a partial top-up exactly as a failure to top up.

        Raises:
            NoOpenMarginCall: nothing was called. Money arriving at an
                uncalled account is a deposit, not a cure.
            ValueError: for a contribution stamped before the call, stamped
                **after the deadline**, or using a method the call does not
                accept.

                The late case is refused rather than absorbed, and the reason is
                worth stating: once the window has closed the QD 87 Dieu 8 right
                has arisen, and letting a late payment retroactively remove it
                would mean an account could never be liquidated by a client fast
                enough with a bank transfer. The client's money is not lost --
                run :meth:`observe` to expire the call, and the restored ratio
                clears the **account** at the next observation. What a late
                payment cannot do is unmake the right.
        """
        if self._call is None:
            raise NoOpenMarginCall(
                self.account_id,
                'no call is outstanding, so this is a deposit and not a cure. '
                'A call that was already cured, expired or escalated is closed')
        call = self._call
        if contribution.at < call.issued_at:
            raise ValueError(
                f'contribution is stamped {contribution.at}, before the call '
                f'issued at {call.issued_at}. It cannot answer a call that had '
                f'not been made')
        if contribution.at > call.deadline:
            raise ValueError(
                f'contribution is stamped {contribution.at}, after the cure '
                f'deadline {call.deadline}. QD 87 Dieu 7.1 sets the window and '
                f'Dieu 8 gives the CTCK the sale right the moment it closes; a '
                f'late payment does not unmake that right. Run observe() to '
                f'expire the call -- the restored ratio will clear the account '
                f'at the next observation')
        if call.cure_methods and contribution.method not in call.cure_methods:
            raise ValueError(
                f'{contribution.method.value!r} is not among the cure methods '
                f'this call accepts ({[m.value for m in call.cure_methods]}). '
                f'QD 87 Dieu 7 names three; a firm may accept fewer')

        credit = cure_credit(contribution, call.target_ratio)
        self._contributions.append(contribution)
        self._cured += credit
        detail = {
            'method': contribution.method,
            'amount': contribution.amount,
            'applied_to_debt': contribution.applied_to_debt,
            'credit': credit,
            'credited_total': self._cured,
            'required': self._requirement,
            'grade': 'DERIVED -- see TopUpRequirement; QD 87 Dieu 7.2 is '
                     'unreadable in every accessible mirror',
        }
        if credit <= _ZERO:
            detail['note'] = (
                'this contribution cures NOTHING: a self-directed sale whose '
                'proceeds stay in the account moves PV down and CB up by the '
                'same amount, so EB, AB and the ratio are all unchanged')

        if self._cured >= self._requirement:
            cured = self._update_call(status=MarginCallStatus.CURED,
                                      cured_at=contribution.at)
            detail['provisional'] = True
            detail['note'] = (
                'PROVISIONAL: measured against the DERIVED requirement at '
                'issue. The authoritative test is the ratio at the next '
                'observation, and the breach-day counter does not reset here')
            self._clear_call()
            return (self._event(MarginEventKind.CALL_CURED, contribution.at,
                                call_id=cured.call_id, detail=detail),)

        partial = self._update_call(status=MarginCallStatus.PARTIALLY_CURED)
        detail['shortfall'] = self._requirement - self._cured
        return (self._event(MarginEventKind.CALL_PARTIALLY_CURED,
                            contribution.at, call_id=partial.call_id,
                            detail=detail),)

    # -- the forced sale ----------------------------------------------------

    def plan_forced_sale(self, positions: Sequence[MarginCollateralPosition],
                         algebra: MarginAccountAlgebra, *,
                         notified_at: Optional[datetime] = None,
                         disclosed_at: Optional[datetime] = None,
                         ranking: Optional[Sequence[str]] = None,
                         selector: Optional[PositionSelector] = None,
                         ) -> Tuple[ForcedSalePlan, Tuple[MarginEvent, ...]]:
        """Size and order a *ban giai chap*. QD 87 Dieu 8, TT 120 Dieu 9.6.

        **There is no trigger argument, and that is the design.** The trigger is
        derived from state this monitor observed itself, and
        :class:`ForcedSaleNotAuthorised` is raised when none is live. A caller
        cannot argue an account into a liquidation; it has to drive the ratio
        below a level, or let a window close, in front of the machine.

        How much is sold is bounded by the article -- *part or all of the
        pledged securities, depending on whether the remaining required
        collateral is smaller or larger than the total value in the account* --
        and where inside that bound the firm stops is
        :attr:`BrokerMarginTerms.forced_sale_target`. The quantity comes from
        :func:`value_to_restore`, which is **DERIVED**.

        **Sizing uses each position's carried valuation, and under
        ``ForcedSalePrice.FLOOR`` that systematically under-sells.** DNSE places
        at *gia san*, which is below the valuation by up to the band width, so
        the fills raise less than the plan sized for and a second sale follows.
        Sizing at the floor price instead would need the day's band, which is
        the exchange layer's and is not an input here. Declared in
        :data:`PROVENANCE` under ``forced_sale_sizing_price``.

        **The notice is never manufactured.** QD 87 Dieu 8 requires the CTCK to
        notify the client *before placing the sell order*, and TT 120 Dieu 9.6
        requires the public disclosure first where the client's own
        ownership-reporting obligations are engaged. Pass ``notified_at`` and
        ``disclosed_at`` if the caller sent them. Leave them out and the tickets
        are still produced -- with :attr:`ForcedSaleInstruction.notice_satisfied`
        ``False`` and a note on the plan -- because an engine that refused to
        represent the un-noticed case could not report the breach, and one that
        stamped its own notice would report compliance it never earned.

        Quantities are in **whole shares and are not rounded to a board lot.**
        Lot sizes are the exchange's and belong to the order layer that submits
        these tickets; inventing one here would put a second lot table in the
        codebase. Declared under ``no_lot_rounding``.

        Returns:
            The plan, and the events it produced. The events are separate
            because the plan is a record and the events are a log, and a caller
            polling for news should not have to reach into a record for it.

        Raises:
            ForcedSaleNotAuthorised: no live trigger.
            ValueError: for a mismatched or stale algebra, or a target buffer
                that pushes the target to 1 or beyond.
        """
        if self._due is None:
            raise ForcedSaleNotAuthorised(
                self.account_id, self._last_status,
                'no live trigger. QD 87 Dieu 8 gives the right where the client '
                'failed to top up within the deadline; the firm\'s force-sell '
                'level, its consecutive-breach and overdue clocks are the other '
                'four paths. Drive one of them through observe() first')
        if algebra.account_id != self.account_id:
            raise ValueError(
                f'algebra is for account {algebra.account_id!r}, this monitor '
                f'watches {self.account_id!r}')
        ts = algebra.as_of
        if self._last_observed_at is not None and ts < self._last_observed_at:
            raise ValueError(
                f'algebra is as of {ts}, earlier than the last observation at '
                f'{self._last_observed_at}. A sale sized on a stale ratio sells '
                f'the wrong quantity')

        terms = self.terms
        target = self.policy.cure_target_ratio
        if terms.forced_sale_target is ForcedSaleTarget.MAINTENANCE_PLUS_BUFFER:
            target = target + terms.forced_sale_target_buffer
        if target >= _ONE:
            raise ValueError(
                f'forced_sale_target_buffer pushes the target to {target}, at '
                f'or above 1. A target of 1 means an account with no debt at '
                f'all, which no sale of collateral reaches while any debt '
                f'remains')

        to_raise = value_to_restore(algebra.total_assets, algebra.net_assets,
                                    target)
        call = self._expired_call or self._call
        ranking_used = (tuple(ranking) if ranking is not None
                        else self.broker_ranking)
        scoped = positions_in_scope(
            positions, terms.forced_sale_scope, ranking=ranking_used,
            deal_id=self.deal_id or (call.deal_id if call is not None else None))
        select = selector or self.selector
        ordered = select(scoped, terms.liquidation_order, ranking=ranking_used)

        sellable = tuple(p for p in ordered if p.is_sellable)
        unsellable = tuple(p.ticker for p in ordered if not p.is_sellable)
        available = _ZERO
        for position in sellable:
            available += position.market_value

        remaining = to_raise
        planned = _ZERO
        instructions: List[ForcedSaleInstruction] = []
        for position in sellable:
            if remaining <= _ZERO:
                break
            wanted = (remaining / position.price).to_integral_value(
                rounding=ROUND_CEILING)
            quantity = min(int(wanted), position.quantity)
            if quantity <= 0:
                continue
            raised = Decimal(quantity) * position.price
            instructions.append(ForcedSaleInstruction(
                instruction_id=self._next_id('sale'),
                account_id=self.account_id,
                ticker=position.ticker,
                quantity=quantity,
                price_policy=terms.forced_sale_price,
                scope=terms.forced_sale_scope,
                trigger=self._due,
                target_ratio=target,
                issued_at=ts,
                limit_price=(position.price
                             if terms.forced_sale_price is ForcedSalePrice.LIMIT
                             else None),
                call_id=call.call_id if call is not None else None,
                notified_at=notified_at,
                disclosed_at=disclosed_at,
            ))
            remaining -= raised
            planned += raised

        notes: List[str] = []
        if notified_at is None:
            notes.append(
                'NO CLIENT NOTICE RECORDED: QD 87 Dieu 8 requires the CTCK to '
                'notify before placing the sell order. The tickets are still '
                'produced so the breach is countable')
        elif notified_at > ts:
            notes.append(
                'NOTICE STAMPED AFTER THE INSTRUCTION: QD 87 Dieu 8 requires '
                'it BEFORE the sell order')
        if (self.policy.regulation.forced_sale_disclosure_required
                and disclosed_at is None):
            notes.append(
                'no public disclosure recorded: TT 120 Dieu 9.6 requires it '
                'before selling where the client\'s own ownership-reporting '
                'obligations are engaged')
        if not instructions:
            notes.append(
                'nothing sellable in scope: the right exists and cannot be '
                'exercised, which is QD 87 Dieu 8\'s shortfall case')

        plan = ForcedSalePlan(
            account_id=self.account_id,
            as_of=ts,
            trigger=self._due,
            triggers=self._due_all,
            target_ratio=target,
            value_to_raise=to_raise,
            value_available=available,
            planned_value=planned,
            instructions=tuple(instructions),
            scope=terms.forced_sale_scope,
            selection_order=terms.liquidation_order,
            price_policy=terms.forced_sale_price,
            call_id=call.call_id if call is not None else None,
            unsellable=unsellable,
            note='; '.join(notes) or None,
        )

        events: List[MarginEvent] = []
        if notified_at is not None:
            events.append(self._event(
                MarginEventKind.FORCED_SALE_NOTICED, notified_at,
                call_id=plan.call_id,
                detail={'disclosed_at': disclosed_at,
                        'before_the_order': notified_at <= ts,
                        'article': 'QD 87 Dieu 8; TT 120 Dieu 9.6 for the '
                                   'public disclosure'}))
        for instruction in instructions:
            self._instructions[instruction.instruction_id] = instruction
            events.append(self._event(
                MarginEventKind.FORCED_SALE_INSTRUCTED, ts,
                call_id=instruction.call_id,
                instruction_id=instruction.instruction_id,
                detail={'ticker': instruction.ticker,
                        'quantity': instruction.quantity,
                        'trigger': instruction.trigger,
                        'triggers': self._due_all,
                        'price_policy': instruction.price_policy,
                        'selection_order': terms.liquidation_order,
                        'scope': terms.forced_sale_scope,
                        'target_ratio': target,
                        'notice_satisfied': instruction.notice_satisfied,
                        'restores_target': plan.restores_target,
                        'shortfall': plan.shortfall}))

        if instructions:
            if call is not None:
                self._update_call(status=MarginCallStatus.ESCALATED)
            self._clear_call()
            self._due = None
            self._due_all = ()
        return plan, tuple(events)

    def report_sale_results(self, instruction_id: str, ts: datetime, *,
                            filled_quantity: int,
                            average_price: Optional[Decimal] = None,
                            note: Optional[str] = None,
                            ) -> Tuple[MarginEvent, ...]:
        """Record the statement of results QD 87 Dieu 8 requires afterwards.

        The article requires the CTCK to notify before the order **and to send a
        statement of results after it**, by the contractually agreed method.
        The second half is as much an obligation as the first, and an engine
        that modelled only the notice would report half the duty.

        Raises:
            LookupError: for an instruction this monitor did not raise.
            ValueError: for a fill larger than the ticket.
        """
        instruction = self._instructions.get(instruction_id)
        if instruction is None:
            raise LookupError(
                f'{instruction_id!r} is not an instruction this monitor raised '
                f'for account {self.account_id!r}')
        if filled_quantity < 0 or filled_quantity > instruction.quantity:
            raise ValueError(
                f'filled_quantity {filled_quantity} is outside the ticket '
                f'(0..{instruction.quantity})')
        if average_price is not None:
            _require_decimal('average_price', average_price)
        return (self._event(
            MarginEventKind.FORCED_SALE_RESULT_SENT, ts,
            call_id=instruction.call_id, instruction_id=instruction_id,
            detail={'ticker': instruction.ticker,
                    'filled_quantity': filled_quantity,
                    'ordered_quantity': instruction.quantity,
                    'average_price': average_price,
                    'unfilled': instruction.quantity - filled_quantity,
                    'note': note,
                    'article': 'QD 87 Dieu 8 -- a statement of results after '
                               'the sale, by the contractually agreed method'}),)

    # -- internals ----------------------------------------------------------

    def _next_id(self, kind: str) -> str:
        """Deterministic per-account identifiers, so a replay reproduces a log."""
        self._seq += 1
        return f'{self.account_id}:{kind}:{self._seq}'

    def _event(self, kind: MarginEventKind, ts: datetime, *,
               call_id: Optional[str] = None,
               instruction_id: Optional[str] = None,
               loan_id: Optional[str] = None,
               detail: Optional[Mapping[str, Any]] = None) -> MarginEvent:
        return MarginEvent(kind=kind, ts=ts, account_id=self.account_id,
                           loan_id=loan_id, call_id=call_id,
                           instruction_id=instruction_id,
                           detail=MappingProxyType(dict(detail or {})))

    def _update_call(self, **changes: Any) -> MarginCall:
        """Restate the most recent call, keeping the Dieu 13.8 book in step."""
        updated = replace(self._calls[-1], **changes)
        self._calls[-1] = updated
        if self._call is not None:
            self._call = updated
        if self._expired_call is not None:
            self._expired_call = updated
        return updated

    def _clear_call(self) -> None:
        """Drop the live call and everything scored against it.

        The history in :attr:`calls` is untouched -- QD 87 Dieu 13.8 wants every
        call on the book, with the status it ended in.
        """
        self._call = None
        self._expired_call = None
        self._requirement = _ZERO
        self._cured = _ZERO
        self._contributions = []


# --------------------------------------------------------------------------
# What the state machine decided for itself
# --------------------------------------------------------------------------
#
# Merged into the module table rather than kept in a second one: a caller
# dumping provenance into a result reads :data:`PROVENANCE`, and a second dict
# would be the entries nobody prints. The block above is left exactly as it was
# written; these are additions.

PROVENANCE = MappingProxyType({
    **PROVENANCE,

    'binding_policy_tighter_wins': _p('QD 87 Dieu 5.1-5.3, 7.1', _D,
        'That the STRICTER of the statutory floor and the broker term binds -- '
        'max() on both ratio levels, min() on the cure window -- is our reading '
        'of a floor-and-ceiling regime, not a clause. It matters only when the '
        'two disagree, which Dieu 5.3 makes reachable: the SSC may move the '
        'ratios without new legislation and did so once (60% -> 50%, 2017). A '
        'firm whose contract was signed under the old floor is bound by the new '
        'one from its effective date, and BindingPolicy is where a run says '
        'which layer bound each threshold'),

    'cure_deadline_time_of_day': _p('QD 87 Dieu 7.1', _D,
        'The article gives a COUNT of business days and no time of day. Landing '
        'the deadline at the same time of day the call issued is OURS. Midnight '
        'would silently shorten every window by most of a day and the next '
        'close would lengthen it; anchoring to the call keeps the window exactly '
        'as many business days long as the contract says. Dieu 6.1 has the '
        'within-day timestamp of the ratio computation agreed in writing, which '
        'is the closest the rulebook comes to speaking'),

    'business_day_calendar_choice': _p('QD 87 Dieu 7.1', _S,
        'The article says ngay lam viec without saying WHOSE working days. The '
        'VSDC settlement calendar and the two exchanges\' trading calendars '
        'diverge around Tet by up to a week -- which is the whole cure window '
        'and more. This module therefore ships NO calendar: BusinessDayCalendar '
        'is a one-method Protocol and the caller passes the calendar it can '
        'defend. MarginCall.deadline is only as sourced as that object'),

    'cure_credit_normalisation': _p('QD 87 Dieu 7.2', _D,
        'Scoring the three cure methods into one cash-equivalent number -- cash '
        'swept against DB at 1x, cash left in CB and posted securities at '
        '(1 - target), a self-directed sale repaying DB at target -- is OUR '
        'arithmetic off the EB/AB algebra, for the same reason the top-up '
        'amounts are: Dieu 7.2\'s formulas are images in every accessible '
        'mirror. It exists so a MIXED answer adds up, which the article '
        'contemplates (three methods, restore at least mmr) and gives no '
        'arithmetic for. Note the fourth row: a self-directed sale whose '
        'proceeds are NOT applied to the debt scores ZERO, because PV falls and '
        'CB rises by the same amount and neither EB nor AB moves'),

    'cure_credit_is_gross': _p(None, _D,
        'Cure credit is scored on GROSS proceeds. A real sale pays the 0.1% '
        'transfer tax and a commission first, so it closes slightly less of the '
        'gap than the credit says. Those charges belong to session/charges.py '
        'and the caller nets them off before recording the contribution; '
        'inventing a fee schedule here would put a second one in the codebase'),

    'forced_sale_sizing': _p('QD 87 Dieu 8', _D,
        'The quantity formula S >= EB - AB/target is OURS. Dieu 8 bounds the '
        'sale qualitatively -- part or all of the pledged securities, depending '
        'on whether the remaining required collateral is smaller or larger than '
        'the total value in the account -- and gives no arithmetic. The '
        'derivation: selling S and repaying DB takes EB down by S and leaves AB '
        'untouched, so AB/(EB - S) >= target solves to that. It is the same '
        'number as TopUpRequirement.self_sale_value, because a ban giai chap is '
        'a self-directed sale the CTCK places itself. When AB <= 0 it returns at '
        'least EB -- sell everything and still fall short -- which is Dieu 8\'s '
        'own shortfall case and is REPORTED, not hidden'),

    'forced_sale_sizing_price': _p(None, _D,
        'The sale is sized at each position\'s CARRIED VALUATION, capped at the '
        'last close per Dieu 2.4. Under ForcedSalePrice.FLOOR the ticket is '
        'placed at gia san, which is below that by up to the band width, so the '
        'fills raise LESS than the plan sized for and a second sale follows. '
        'Sizing at the floor instead would need the day\'s band, which is the '
        'exchange layer\'s input and not one this section takes. The direction '
        'of the error is stated because it is systematic, not random'),

    'forced_sale_trigger_priority': _p(None, _D,
        'FORCED_SALE_TRIGGER_PRIORITY ranks the five triggers by immediacy. NO '
        'document ranks them -- QD 87 Dieu 8 knows only one, the expired cure '
        'window, and the other four are broker terms. An account routinely '
        'satisfies three at once. ForcedSalePlan.triggers carries ALL of them; '
        'the ranking only decides which one lands in the single-valued '
        'ForcedSaleInstruction.trigger field, so a log can be counted by cause'),

    'forced_sale_right_lapses_on_recovery': _p('QD 87 Dieu 8', _D,
        'When a cure window closes the Dieu 8 right arises. That the right is '
        'DROPPED if the ratio recovers to the target before the sale is placed '
        'is OUR reading -- the article does not say the right expires. It is '
        'adopted because the alternative is selling a compliant account, which '
        'is the disposal of somebody else\'s property that '
        'ForcedSaleNotAuthorised exists to prevent. The call keeps its EXPIRED '
        'status in the Dieu 13.8 book; only the right goes'),

    'late_cure_refused': _p('QD 87 Dieu 7.1 / Dieu 8', _D,
        'A contribution stamped after the deadline is REFUSED by '
        'MarginCallMonitor.cure rather than absorbed. Ours: the article does not '
        'say what happens to a late payment. Absorbing it would let a client '
        'with a fast bank transfer unmake a right that had already arisen, so '
        'the machine expires the call and lets the restored RATIO clear the '
        'account at the next observation. The money is not lost; the right is '
        'not unmade'),

    'provisional_cure': _p('QD 87 Dieu 7', _D,
        'MarginCallMonitor.cure marks a call CURED when the recorded '
        'contributions meet the DERIVED requirement AS AT ISSUE, which is what '
        'the client was actually told to pay. The authoritative test is the '
        'ratio at the next observation, and the event says provisional=True. '
        'The interlock against cosmetic curing is that the breach-day counter '
        'is reset only by an observed ratio at or above the call level, never '
        'by a cure -- so a client topping up just enough each morning still '
        'reaches the consecutive-breach trigger'),

    'notice_never_manufactured': _p('QD 87 Dieu 8 / TT 120 Dieu 9.6', _D,
        'The engine never synthesises notified_at or disclosed_at. Both are '
        'caller inputs, and a plan produced without them still emits its '
        'tickets -- with notice_satisfied False and a note on the plan -- '
        'because an engine that refused to represent the un-noticed case could '
        'not report the breach, and one that stamped its own notice would '
        'report a compliance it never earned. The RULE is VERIFIED; the refusal '
        'to fabricate it is our design'),

    'sell_on_ineligible_collateral': _p('TT 120 Dieu 9.6 / QD 87 Dieu 10.2', _S,
        'A pledged security leaving the margin list is excluded from the '
        'collateral base for BOTH ratios (TT 120 Dieu 9.6, over QD 87 Dieu '
        '10.2\'s narrower version) -- that much is statutory and lands in the '
        'ratio unconditionally by lowering PV. Whether it should ALSO make a '
        'forced sale due is nowhere stated. Defaulted OFF, and even when '
        'enabled the trigger requires the account to be actually in breach'),

    'no_lot_rounding': _p(None, _D,
        'Forced-sale quantities are whole shares, NOT rounded to a board lot. '
        'Lot sizes are the exchange\'s and belong to the order layer that '
        'submits these tickets; a second lot table here would be a second '
        'source of truth. An instruction is an instruction, not an order'),

    'suspension_does_not_shelter_a_breach': _p('TT 120 Dieu 9.9 / 9.7', _D,
        'MarginAccountStatus.SUSPENDED is reported only when the ladder is '
        'otherwise clean. Both suspension routes -- the SSC\'s stabilisation '
        'order and the firm\'s own loss of eligibility -- stop NEW LENDING; '
        'neither cures a ratio and neither discharges a debt. The enum forces '
        'one answer per account and reporting the breach is the conservative '
        'half: collapsing a breaching account to SUSPENDED would hide exactly '
        'the accounts a stabilisation order was issued about'),

    'breach_days_counted_by_observation': _p(None, _D,
        'The consecutive-breach counter counts DISTINCT OBSERVATION DATES on '
        'which the account was seen below the call level, and does not walk the '
        'calendar to fill in days nobody looked at. An intraday run that sweeps '
        'ten times a day counts one. A day with no observation is not counted '
        'as compliant either -- it is simply not counted, which is the same '
        'posture the blind-observation rule takes'),

    'unknown_pnl_sorts_last': _p(None, _D,
        'Under LiquidationOrder.LARGEST_LOSS_FIRST a position with no known P&L '
        'sorts LAST, and under LOWEST_LOAN_RATIO_FIRST a missing ty le cho vay '
        'is treated as zero, i.e. the weakest collateral there is. Both are '
        'ours. An unknown loss is not evidence of a large one, and a ticker the '
        'firm will not lend against contributes nothing to PV, so selling it '
        'releases the least borrowing capacity per dong raised'),
})


# ==========================================================================
# THE PRE-TRADE GATE -- QD 87 Dieu 13.5(d)
# ==========================================================================
#
# *"Cong ty chung khoan khong duoc de khach hang giao dich ky quy hoac rut tien
# vuot qua suc mua hien co cua tai khoan."* VERIFIED. Written two equivalent
# ways::
#
#     order_value x imr <= EE          equivalently    order_value <= BP
#
# Only the trading half is implemented here. The **withdrawal** half of the same
# clause -- and Dieu 13.5(c), which lets a client withdraw cash only after every
# debt to the CTCK is cleared -- needs no new arithmetic but does need a record
# of its own, and MarginOrderAssessment is order-shaped. It is deliberately not
# implemented rather than bolted onto an order assessment, and
# MarginRegulation.cash_withdrawal_requires_debt_cleared already carries the
# rule for whoever adds it.


def order_initial_margin_ratio(terms: BrokerMarginTerms,
                               ticker: str) -> Decimal:
    """The ``imr`` this order runs at. **khoan 8 makes this per order.**

    QD 87 Dieu 2 khoan 8 defines *ty le ky quy ban dau* as the account's *tai san
    thuc co* over the market value of **the securities the margin order would
    buy, at trade time** -- an order-level quantity, not an account constant.
    Two things make it vary from order to order: the price is the trade-time
    market price (the caller's, passed to :func:`assess_margin_order`), and the
    required ratio itself varies by ticker, because brokers publish a per-ticker
    *ty le cho vay* rather than an ``imr``.

    **The bridge between the two is DERIVED.** ``imr = 1 - loan_ratio`` is our
    own identity, it is in no text read, and it holds only for a single fully
    collateralised purchase -- an account already holding other eligible
    collateral supports a larger purchase than it implies. It is used here
    because it is the only way a published *ty le cho vay* enters the algebra at
    all, and it is used **defensively**: the result is the strictest of the
    firm's own ``initial_margin_ratio`` and ``1 - loan_ratio``, so the identity
    can only ever tighten the gate, never loosen it below a term the firm
    actually stated or below QD 87 Dieu 5.1's 50 % floor. See :data:`PROVENANCE`
    under ``loan_to_value_identity``.

    **An empty ``loan_ratio_by_ticker`` means the list was not supplied**, not
    that the firm lends against nothing. The field's own reading -- a ticker with
    no entry is one this firm does not lend against -- is the right one for a
    *populated* positive list, and :func:`assess_margin_order` applies it there:
    a ticker missing from a non-empty list is refused as
    :attr:`MarginOrderRefusal.SECURITY_NOT_ELIGIBLE`. An empty mapping cannot
    distinguish "this firm does no margin business" from "the caller did not
    pass a list", and refusing every order on the default would make the gate
    say a great deal about the caller's data and nothing about the rule.
    """
    loan_ratio = terms.loan_ratio_by_ticker.get(ticker)
    if loan_ratio is None:
        return terms.initial_margin_ratio
    return max(terms.initial_margin_ratio, _ONE - loan_ratio)


# --------------------------------------------------------------------------
# Firm-level limits -- QD 87 Dieu 9 (opt-in)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class FirmLendingState:
    """The CTCK's own book, for QD 87 Dieu 9's four caps. VERIFIED.

    **Three of the four are fractions of the firm's equity and the fourth is
    not** -- Dieu 9.4 is a fraction of the *issuer's* total listed shares, and it
    is counted in shares, not dong. :class:`FirmLendingLimit` names the base of
    each and :func:`firm_limit_headroom` keeps the units apart.

    **``equity_statement_date`` has no default, deliberately.** Dieu 9 takes
    *von chu so huu* from the latest audited or reviewed financial statement
    **not older than 06 months** from the calculation date. An equity figure
    whose vintage nobody stated cannot be shown to satisfy that, and defaulting
    the date to "recent" would silently license the whole limit check. Where the
    statement is stale the three equity-based limits report ``evaluable=False``
    and :func:`assess_margin_order` answers ``INDETERMINATE`` -- the Dieu 9.4
    share cap is unaffected, because it never touches equity.

    Attributes:
        equity: *von chu so huu*, in dong.
        equity_statement_date: the balance-sheet date of the statement it came
            from. Not the filing date and not today.
        total_book: the firm's whole margin loan book (Dieu 9.1).
        customer_book: everything already lent to **this** customer (Dieu 9.2).
        security_book: margin loans outstanding against each ticker (Dieu 9.3).
        shares_lent: shares already lent against, per ticker (Dieu 9.4
            numerator).
        issuer_listed_shares: each issuer's total listed shares (Dieu 9.4
            denominator). A ticker absent from this mapping makes the share cap
            unevaluable; nothing in this module ships listed-share counts.
    """

    equity: Decimal
    equity_statement_date: date
    total_book: Decimal = _ZERO
    customer_book: Decimal = _ZERO
    security_book: Mapping[str, Decimal] = field(default_factory=dict)
    shares_lent: Mapping[str, int] = field(default_factory=dict)
    issuer_listed_shares: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_decimal('equity', self.equity)
        if self.equity <= _ZERO:
            raise ValueError(
                f'equity is {self.equity}. QD 87 Dieu 9 states three of its four '
                f'caps as multiples of von chu so huu, and a firm with no '
                f'positive equity has no lending capacity to compute -- it also '
                f'fails ND 155 Dieu 198.1(c) outright')
        for name in ('total_book', 'customer_book'):
            _require_decimal(name, getattr(self, name))
            if getattr(self, name) < _ZERO:
                raise ValueError(f'{name} must not be negative, got '
                                 f'{getattr(self, name)}')


@dataclass(frozen=True)
class FirmLimitHeadroom:
    """How much room one QD 87 Dieu 9 cap has left.

    Attributes:
        limit: which cap. **Read :class:`FirmLendingLimit` for the unit** --
            three of the four are dong and
            :attr:`FirmLendingLimit.PER_ISSUER_SHARES` is a share count.
        cap: the ceiling, in that unit.
        used: what is already against it.
        headroom: ``cap - used``. **May be negative**, which says the firm is
            already over and no new lending against this base is lawful.
        evaluable: ``False`` where the inputs could not support the test --
            a stale equity statement, or an issuer whose listed-share count the
            caller did not supply.
        reason: why not, where ``evaluable`` is ``False``.
        article: the clause, for a refusal message that teaches.
    """

    limit: FirmLendingLimit
    cap: Decimal = _ZERO
    used: Decimal = _ZERO
    evaluable: bool = True
    reason: Optional[str] = None
    article: str = 'QD 87 Dieu 9'

    @property
    def headroom(self) -> Decimal:
        """``cap - used``. Meaningless unless :attr:`evaluable`."""
        return self.cap - self.used

    def admits(self, increment: Decimal) -> bool:
        """Whether ``increment`` more fits under this cap.

        ``True`` for an unevaluable limit: a limit that could not be tested has
        not refused anything, and the caller must read :attr:`evaluable`
        separately. :func:`assess_margin_order` does exactly that and answers
        ``INDETERMINATE`` rather than admitting.
        """
        if not self.evaluable:
            return True
        return self.used + increment <= self.cap


def firm_limit_headroom(
    firm: FirmLendingState,
    *,
    ticker: str,
    as_of: date,
    regulation: MarginRegulation = QD_87_2017,
) -> Mapping[FirmLendingLimit, FirmLimitHeadroom]:
    """The four Dieu 9 caps, evaluated against one firm and one ticker.

    VERIFIED, and independently REPORTED by Thoi bao Tai chinh Viet Nam:

    * **Dieu 9.1** total margin book <= **200 %** of equity;
    * **Dieu 9.2** total lending to one customer <= **3 %** of equity;
    * **Dieu 9.3** total lending against one security <= **10 %** of equity;
    * **Dieu 9.4** total **shares** lent against for one issuer <= **5 % of that
      issuer's total listed shares** -- *"khong duoc vuot qua 5% tong so chung
      khoan niem yet cua mot to chuc niem yet"*, re-fetched verbatim. Note the
      unit: shares, not dong.

    The equity figure must come from a statement no older than
    :attr:`MarginRegulation.equity_statement_max_age_months` (6) -- so a stale
    statement makes the first three unevaluable while leaving the fourth intact.

    Raises:
        ValueError: where the statement is dated after ``as_of``. A firm cannot
            compute today's capacity from a statement that does not exist yet,
            and look-ahead is the one data error this package refuses everywhere.
    """
    if firm.equity_statement_date > as_of:
        raise ValueError(
            f'equity_statement_date {firm.equity_statement_date.isoformat()} is '
            f'after the calculation date {as_of.isoformat()}. QD 87 Dieu 9 takes '
            f'equity from the LATEST statement not older than '
            f'{regulation.equity_statement_max_age_months} months; a statement '
            f'from the future is look-ahead, not freshness')

    stale_from = _add_months(firm.equity_statement_date,
                             regulation.equity_statement_max_age_months)
    stale = as_of > stale_from
    stale_reason = (
        f'the equity figure comes from a statement dated '
        f'{firm.equity_statement_date.isoformat()}, which is more than '
        f'{regulation.equity_statement_max_age_months} months before '
        f'{as_of.isoformat()}. QD 87 Dieu 9 requires a statement no older than '
        f'that, so this equity cannot support the cap -- obtain the current one'
        if stale else None)

    out: Dict[FirmLendingLimit, FirmLimitHeadroom] = {}
    equity_based = (
        (FirmLendingLimit.TOTAL_BOOK, firm.total_book, 'QD 87 Dieu 9.1'),
        (FirmLendingLimit.PER_CUSTOMER, firm.customer_book, 'QD 87 Dieu 9.2'),
        (FirmLendingLimit.PER_SECURITY,
         firm.security_book.get(ticker, _ZERO), 'QD 87 Dieu 9.3'),
    )
    for limit, used, article in equity_based:
        out[limit] = FirmLimitHeadroom(
            limit=limit,
            cap=FIRM_LENDING_LIMITS[limit] * firm.equity,
            used=used,
            evaluable=not stale,
            reason=stale_reason,
            article=article,
        )

    listed = firm.issuer_listed_shares.get(ticker)
    if listed is None:
        out[FirmLendingLimit.PER_ISSUER_SHARES] = FirmLimitHeadroom(
            limit=FirmLendingLimit.PER_ISSUER_SHARES,
            evaluable=False,
            article='QD 87 Dieu 9.4',
            reason=f'no listed-share count for {ticker!r}. Dieu 9.4 is a '
                   f'fraction of the ISSUER\'s total listed shares, not of the '
                   f'firm\'s equity, and nothing in this module ships listed '
                   f'share counts -- they are dated issuer data the caller '
                   f'supplies, like the eligible-security list')
    else:
        out[FirmLendingLimit.PER_ISSUER_SHARES] = FirmLimitHeadroom(
            limit=FirmLendingLimit.PER_ISSUER_SHARES,
            cap=FIRM_LENDING_LIMITS[FirmLendingLimit.PER_ISSUER_SHARES]
            * Decimal(listed),
            used=Decimal(firm.shares_lent.get(ticker, 0)),
            article='QD 87 Dieu 9.4',
        )
    return MappingProxyType(out)


def _add_months(on: date, months: int) -> date:
    """``on`` plus ``months`` calendar months, clamped to the shorter month.

    QD 87 states every period in *thang*. This is the exact arithmetic, unlike
    :data:`MAX_DAYS_IN_MONTH`, which is a deliberately loose config-time bridge
    for terms a broker publishes in days.
    """
    total = on.year * 12 + (on.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(on.day, monthrange(year, month)[1]))


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------

def assess_margin_order(
    state: MarginAccountState,
    terms: BrokerMarginTerms,
    *,
    ticker: str,
    quantity: int,
    price: Decimal,
    as_of: Optional[datetime] = None,
    security: Optional[SecurityEligibility] = None,
    investor: Optional[InvestorEligibility] = None,
    firm: Optional[FirmLendingState] = None,
    prohibited_collateral: Tuple[ProhibitedCollateral, ...] = (),
    algebra: Optional[MarginAccountAlgebra] = None,
    regulation: Optional[MarginRegulation] = None,
) -> MarginOrderAssessment:
    """The pre-trade gate. **A verdict, never a bool.**

    QD 87 Dieu 13.5(d): the CTCK must not let the client trade on margin beyond
    the account's current buying power. The test is ``order_value x imr <= EE``.

    **Every rule that says no is reported, not the first.** A caller fixing one
    refusal wants to see the rest, and a run that counts refusals by reason is
    the only way to tell a buying-power-bound simulation from an
    eligibility-bound one.

    **"The data could not decide" is kept apart from "a rule said no."**
    :attr:`MarginOrderAssessment.indeterminate` is a separate tuple from
    ``refusals``. Both block the order -- ``admitted`` is ``False`` if either is
    non-empty -- but only one of them is a finding about the market.

    **The per-order ``imr`` is khoan 8's, not the account's.** ``EE`` comes from
    the account-level algebra (khoan 10-11, computed over ``PV`` at the account's
    own ``imr``), and the *order's* buying power is ``EE`` divided by
    :func:`order_initial_margin_ratio` for this ticker. That is khoan 12 with
    khoan 8's ratio, and it is why this function exists instead of the caller
    reading ``BP`` off :class:`MarginAccountAlgebra` and comparing. The two agree
    exactly when the firm publishes no per-ticker *ty le cho vay* for the ticker.

    **The decision uses the multiplicative form.** ``order_value x imr <= EE`` and
    ``order_value <= BP`` are the same statement in exact arithmetic, but
    ``BP = EE / imr`` is a ``Decimal`` division and is only correct to the
    context precision, so at the boundary the two can disagree by an ulp. The
    multiplication cannot. ``buying_power`` is still reported, because it is the
    number a client is quoted.

    **A margin order is a distinct order type, not a flag** -- QD 87 Dieu
    13.5(e) requires margin order tickets to be distinguishable from ordinary
    ones, client-confirmed, and an inseparable annex to the contract. Whatever
    wires this into ``orders.py`` must add a type.

    **Sequential gating warning.** This is a pure function of a snapshot. Gating
    two orders against the same ``state`` admits both if either fits: nothing
    here encumbers. A caller running several must commit each into the state it
    passes to the next, exactly as ``ledgers.py`` encumbers cash against live buy
    orders -- see :attr:`CashBase.uncommitted`.

    Args:
        state: the account, as of ``state.as_of``.
        terms: the firm's commercial terms.
        ticker: what the order would buy.
        quantity: shares. Must be positive.
        price: the trade-time market price -- khoan 8's *gia thi truong tai
            thoi diem giao dich*. Must be a positive ``Decimal``.
        as_of: when the order is assessed. Defaults to ``state.as_of``; may not
            precede it.
        security: the ticker's eligibility. **``None`` is INDETERMINATE, not
            eligible** -- the eligible-security list is dated data the caller
            supplies, and answering "eligible" on data nobody provided would
            margin securities the exchange has excluded.
        investor: the holder's eligibility. ``None`` falls back to the flags on
            ``state`` (``is_foreign_investor``, ``holder_classes``,
            ``margin_contract_signed``), which are the three statutory tests
            expressed on the account itself.
        firm: the CTCK's book, for the QD 87 Dieu 9 caps. **Opt-in**: those caps
            are facts about a firm, not about this account, and a caller
            simulating one client does not have them. Where it is ``None`` the
            four caps are not tested and ``detail['firm_limits_tested']`` says
            so -- they are not reported as indeterminate, because that would
            make every ordinary gate call indeterminate and drain the word.
        prohibited_collateral: QD 87 Dieu 10.1 categories the caller knows apply
            to this ticker or client. (a)-(c) -- self-underwritten, affiliated
            issuer, own shares -- refuse as ``PROHIBITED_COLLATERAL``; (d), (d)
            and (e) are the same facts as the account-in-breach, foreign and
            ineligible-holder tests and are reported under those names so one
            fact does not appear twice under two headings.
        algebra: a precomputed :class:`MarginAccountAlgebra` for this state,
            where the caller already has one. Recomputed from ``state`` and
            ``terms`` otherwise.
        regulation: the statutory row in force for the run, forwarded to
            :func:`compute_account_algebra` and :func:`firm_limit_headroom`.
            Defaults to ``terms.regulation``.

    Returns:
        A :class:`MarginOrderAssessment`: the verdict, every reason, and the
        numbers behind it.

    Raises:
        ValueError: on a non-positive quantity or price, on an ``as_of``
            preceding the state, or on eligibility data dated after ``as_of``
            (look-ahead).
        TypeError: on a ``float`` price.
    """
    if quantity <= 0:
        raise ValueError(
            f'quantity is {quantity}. QD 87 Dieu 2 khoan 8 values the order at '
            f'market price at trade time, and an order for no shares has no '
            f'value to test against EE -- it is not an order')
    _require_decimal('price', price)
    if price <= _ZERO:
        raise ValueError(
            f'price is {price}. khoan 8 is explicit that the base is the '
            f'MARKET value of the securities the order would buy; a '
            f'non-positive price makes the required margin non-positive and the '
            f'gate admits everything')

    at = as_of if as_of is not None else state.as_of
    if at < state.as_of:
        raise ValueError(
            f'as_of {at.isoformat()} precedes the state it is assessed against '
            f'({state.as_of.isoformat()}). The gate is a snapshot test and a '
            f'state from the future is look-ahead')
    for name, record in (('security', security), ('investor', investor)):
        if record is not None and record.as_of > at.date():
            raise ValueError(
                f'{name} eligibility is dated {record.as_of.isoformat()}, after '
                f'the order date {at.date().isoformat()}. Eligibility is dated '
                f'data published on a lag -- QD 87 Dieu 4 gives the exchange 2 '
                f'business days and the CTCK 2 more -- so tomorrow\'s list is '
                f'look-ahead')

    alg = algebra if algebra is not None else compute_account_algebra(
        state, terms, regulation=regulation)

    imr = order_initial_margin_ratio(terms, ticker)
    order_value = price * quantity
    required_margin = order_value * imr
    ee = alg.excess_equity
    bp = ee / imr
    loan = order_value - required_margin

    refusals: List[MarginOrderRefusal] = []
    indeterminate: List[MarginOrderRefusal] = []
    why: Dict[str, str] = {}

    def refuse(reason: MarginOrderRefusal, note: str) -> None:
        if reason not in refusals:
            refusals.append(reason)
            why[reason.value] = note

    def undecided(reason: MarginOrderRefusal, note: str) -> None:
        if reason not in indeterminate:
            indeterminate.append(reason)
            why[reason.value] = note

    # -- the gate itself, Dieu 13.5(d) -----------------------------------
    if required_margin > ee:
        refuse(MarginOrderRefusal.BUYING_POWER_EXCEEDED,
               f'QD 87 Dieu 13.5(d): order_value {order_value} x imr {imr} = '
               f'{required_margin} exceeds EE {ee}. Buying power {bp}, short by '
               f'{required_margin - ee}')

    # -- lending stopped at the firm, TT 120 Dieu 9.9 / 9.7 ---------------
    if state.lending_suspended:
        refuse(MarginOrderRefusal.LENDING_SUSPENDED,
               'TT 120 Dieu 9.9 lets the SSC order margin trading at a CTCK '
               'suspended to stabilise the market; Dieu 9.7 and QD 87 Dieu 16 '
               'require a firm that loses its eligibility conditions to stop '
               'signing and disbursing IMMEDIATELY and report to the SSC within '
               '48 hours. Existing debt does not vanish; new lending stops')

    # -- the contract IS the credit agreement, TT 120 Dieu 9.1 ------------
    has_contract = (investor.has_margin_contract if investor is not None
                    else state.margin_contract_signed)
    if not has_contract:
        refuse(MarginOrderRefusal.NO_MARGIN_CONTRACT,
               'TT 120 Dieu 9.1 / QD 87 Dieu 12.1: the hop dong giao dich ky '
               'quy IS the credit agreement, and Dieu 12.2 sets its minimum '
               'content -- the imr, the mmr, the top-up deadline, the credit '
               'limit, the rate. Without it there is no lending to discuss')

    # -- the investor, TT 120 Dieu 9.2 and QD 87 Dieu 13.4 ----------------
    if state.is_foreign_investor and not terms.regulation.foreign_investors_allowed:
        refuse(MarginOrderRefusal.INVESTOR_NOT_ELIGIBLE,
               'TT 120 Dieu 9.2 / QD 87 Dieu 10.1(d): a flat prohibition on '
               'margin lending to foreign investors. NOTE it bars ky quy only '
               '-- TT 120 Dieu 9a is a separate regime under which foreign '
               'INSTITUTIONAL investors buy on broker credit without '
               'pre-funding, and it is out of scope here. This refusal must not '
               'be read as "foreigners cannot buy on credit"')
    if state.holder_classes:
        refuse(MarginOrderRefusal.INVESTOR_NOT_ELIGIBLE,
               'QD 87 Dieu 13.4 bars a margin account for ' +
               ', '.join(h.value for h in state.holder_classes) +
               '. TT 121/2020 Dieu 27.3 independently bars a CTCK from lending '
               'to its insiders and their related persons in any form')
    if investor is not None:
        if investor.result is MarginEligibility.INELIGIBLE:
            refuse(MarginOrderRefusal.INVESTOR_NOT_ELIGIBLE,
                   'the supplied InvestorEligibility is INELIGIBLE on ' +
                   (', '.join(h.value for h in investor.failed) or 'no '
                    'recorded predicate'))
        elif investor.result is MarginEligibility.INDETERMINATE:
            undecided(MarginOrderRefusal.INVESTOR_NOT_ELIGIBLE,
                      'the supplied InvestorEligibility is INDETERMINATE on ' +
                      (', '.join(h.value for h in investor.unevaluated)
                       or 'unrecorded predicates') +
                      '. RELATED_PERSON typically needs a relationship graph no '
                      'corpus carries')

    # -- the security: exchange negative list, then broker positive list ---
    if security is None:
        undecided(MarginOrderRefusal.SECURITY_NOT_ELIGIBLE,
                  f'no SecurityEligibility was supplied for {ticker!r}. The '
                  f'eligible-security list is DATED DATA the caller supplies, '
                  f'exactly like the VSDC settlement calendar -- nothing in '
                  f'this module ships one, and QD 87 Dieu 3\'s predicates need '
                  f'issuer financial-statement facts the corpus does not carry. '
                  f'Absent data is INDETERMINATE, never eligible')
    else:
        if security.ticker != ticker:
            raise ValueError(
                f'the SecurityEligibility is for {security.ticker!r} and the '
                f'order is for {ticker!r}')
        if security.result is MarginEligibility.INELIGIBLE:
            refuse(MarginOrderRefusal.SECURITY_NOT_ELIGIBLE,
                   f'{ticker} fails QD 87 Dieu 3 (as amended by QD 1205) on ' +
                   (', '.join(p.value for p in security.failed)
                    or 'no recorded predicate') +
                   '. TT 120 Dieu 9.6 also excludes it from the collateral base '
                   'for both ratios')
        elif security.result is MarginEligibility.INDETERMINATE:
            undecided(MarginOrderRefusal.SECURITY_NOT_ELIGIBLE,
                      f'{ticker}\'s eligibility could not be decided: ' +
                      (', '.join(p.value for p in security.unevaluated)
                       or 'unrecorded predicates') +
                      ' were not evaluable')
        if security.on_broker_list is False:
            refuse(MarginOrderRefusal.SECURITY_NOT_ELIGIBLE,
                   f'{ticker} is not on this CTCK\'s own positive list. QD 87 '
                   f'Dieu 4.2 has the firm publish its list within 2 business '
                   f'days of the exchange\'s; selecting a narrower list than '
                   f'the statutory universe is a commercial decision and always '
                   f'permitted')
        elif security.on_broker_list is None:
            undecided(MarginOrderRefusal.SECURITY_NOT_ELIGIBLE,
                      f'no CTCK positive list was supplied, so whether this '
                      f'firm margins {ticker} at all is unknown. QD 87 Dieu 3 '
                      f'is a NEGATIVE list published by the exchange; the '
                      f'firm\'s own POSITIVE list is a second layer and an '
                      f'implicit yes would invent it')

    if terms.loan_ratio_by_ticker and ticker not in terms.loan_ratio_by_ticker:
        refuse(MarginOrderRefusal.SECURITY_NOT_ELIGIBLE,
               f'{ticker} is absent from this firm\'s ty le cho vay table, '
               f'which is a positive list: a ticker with no entry is one the '
               f'firm does not lend against. An EMPTY table means no list was '
               f'supplied and is not read this way')

    # -- QD 87 Dieu 10.1, and where each category is reported --------------
    banned = tuple(p for p in prohibited_collateral if p in (
        ProhibitedCollateral.SELF_UNDERWRITTEN,
        ProhibitedCollateral.AFFILIATED_ISSUER,
        ProhibitedCollateral.OWN_SHARES))
    if banned:
        refuse(MarginOrderRefusal.PROHIBITED_COLLATERAL,
               'QD 87 Dieu 10.1 bars lending against ' +
               ', '.join(p.value for p in banned) +
               ' -- (a) securities the CTCK itself firm-underwrote, until 6 '
               'months after the offering completes; (b) a listed company '
               'owning >= 50% of the CTCK, or one the CTCK owns >= 50% of; '
               '(c) the CTCK\'s own shares')
    if ProhibitedCollateral.CLIENT_BELOW_REQUIRED_RATIO in prohibited_collateral:
        refuse(MarginOrderRefusal.ACCOUNT_IN_BREACH,
               'QD 87 Dieu 10.1(d), as supplied by the caller')
    if (ProhibitedCollateral.FOREIGN_INVESTOR in prohibited_collateral
            or ProhibitedCollateral.INELIGIBLE_ACCOUNT_HOLDER
            in prohibited_collateral):
        refuse(MarginOrderRefusal.INVESTOR_NOT_ELIGIBLE,
               'QD 87 Dieu 10.1(d)/(e), as supplied by the caller')

    # -- QD 87 Dieu 10.1(d): no new lending while in breach ----------------
    if alg.status is MarginAccountStatus.INDETERMINATE:
        undecided(MarginOrderRefusal.INDETERMINATE,
                  'the account ratio could not be computed: ' +
                  '; '.join(alg.indeterminate_reasons))
    elif alg.status in (MarginAccountStatus.CALL,
                        MarginAccountStatus.FORCE_SELL):
        refuse(MarginOrderRefusal.ACCOUNT_IN_BREACH,
               f'QD 87 Dieu 10.1(d): no lending while the client is not meeting '
               f'the contractual or regulatory margin ratio. AB/EB is '
               f'{alg.margin_ratio}, below the binding call level '
               f'{alg.maintenance_margin_ratio}. Independent of whether a call '
               f'has issued')
    elif any(call.is_open for call in state.open_calls):
        refuse(MarginOrderRefusal.ACCOUNT_IN_BREACH,
               'a lenh goi ky quy bo sung is still open on this account. QD 87 '
               'Dieu 8 treats a PARTIAL top-up exactly as a failure to top up '
               'for the force-sale right, so a partially cured call is still an '
               'account in breach')

    # -- the broker's own per-customer limit, under the statutory cap ------
    if terms.per_customer_credit_limit is not None:
        if alg.margin_debt + loan > terms.per_customer_credit_limit:
            refuse(MarginOrderRefusal.CREDIT_LIMIT,
                   f'this firm caps one customer at '
                   f'{terms.per_customer_credit_limit}; the order would take '
                   f'the balance to {alg.margin_debt + loan}. A BROKER term '
                   f'(SSI up to 70 ty, DNSE 10 ty, ABS 10-35 ty, all REPORTED) '
                   f'sitting UNDER the statutory 3%-of-equity cap of QD 87 Dieu '
                   f'9.2')

    # -- QD 87 Dieu 9, opt-in ----------------------------------------------
    headroom: Mapping[FirmLendingLimit, FirmLimitHeadroom] = {}
    if firm is not None:
        headroom = firm_limit_headroom(
            firm, ticker=ticker, as_of=at.date(),
            regulation=terms.regulation if regulation is None else regulation)
        for limit, room in headroom.items():
            increment = (Decimal(quantity)
                         if limit is FirmLendingLimit.PER_ISSUER_SHARES
                         else loan)
            if not room.evaluable:
                undecided(MarginOrderRefusal.INDETERMINATE,
                          f'{room.article} could not be evaluated: '
                          f'{room.reason}')
            elif not room.admits(increment):
                refuse(MarginOrderRefusal.FIRM_LIMIT,
                       f'{room.article}: {limit.value} is capped at {room.cap} '
                       f'with {room.used} used, and this order adds '
                       f'{increment} -- over by '
                       f'{room.used + increment - room.cap}')

    detail: Dict[str, Any] = {
        'article': 'QD 87 Dieu 13.5(d)',
        'test': 'order_value x imr <= EE',
        'initial_margin_ratio_applied': imr,
        'account_initial_margin_ratio': terms.initial_margin_ratio,
        'loan_ratio': terms.loan_ratio_by_ticker.get(ticker),
        'loan_ratio_table_supplied': bool(terms.loan_ratio_by_ticker),
        'implied_loan': loan,
        'order_margin_ratio': (alg.net_assets / order_value),
        'shortfall': max(_ZERO, required_margin - ee),
        'margin_ratio': alg.margin_ratio,
        'account_status': alg.status,
        'db': alg.db, 'cb': alg.cb, 'pv': alg.pv, 'eb': alg.eb, 'ab': alg.ab,
        'mr': alg.mr, 'ee': ee, 'account_buying_power': alg.bp,
        'basis': alg.basis,
        'price_source': alg.price_source,
        'accounting_unit': alg.accounting_unit,
        'firm_limits_tested': firm is not None,
        'firm_limits': dict(headroom),
        'reasons': why,
    }

    return MarginOrderAssessment(
        account_id=state.account_id,
        ticker=ticker,
        quantity=quantity,
        price=price,
        order_value=order_value,
        as_of=at,
        required_margin=required_margin,
        excess_equity=ee,
        buying_power=bp,
        admitted=not refusals and not indeterminate,
        refusals=tuple(refusals),
        indeterminate=tuple(indeterminate),
        detail=detail,
    )


__all__ += [
    # ---- the account algebra (spec 2.2, 2.3, 2.4) ----
    'CashBase', 'cash_base',
    'CollateralBucket', 'CollateralLot', 'LotValuation', 'CollateralValuation',
    'value_collateral',
    'RatioSchedule', 'DEFAULT_SESSION_OPEN', 'DEFAULT_SESSION_CLOSE',
    'compute_account_algebra', 'build_account_state',
    # ---- the pre-trade gate (spec 6, QD 87 Dieu 13.5(d)) ----
    'order_initial_margin_ratio',
    'FirmLendingState', 'FirmLimitHeadroom', 'firm_limit_headroom',
    'assess_margin_order',
]


PROVENANCE = MappingProxyType({
    **PROVENANCE,

    'unsettled_proceeds_in_cb': _p('QD 87 Dieu 2 khoan 5', _V,
        'khoan 5 defines CB as "tien + tien ban chung khoan dang cho ve", so '
        'unsettled sale proceeds DO count toward the margin ratio -- while '
        'ledgers.py deliberately excludes them from Cash.available, because '
        'Vietnamese equity is 100% pre-funded and they cannot fund a purchase. '
        'Two different questions with two different right answers. CashBase '
        'computes both side by side so neither can be substituted for the '
        'other; the divergence is a property, not a comment'),

    'advance_outside_the_algebra': _p('QD 87 Dieu 2 khoan 3, khoan 5', _D,
        'OUR READING. An ung truoc tien ban is a prepayment of the client\'s own '
        'sale proceeds, not a margin loan, so khoan 3\'s DB (du no ky quy) does '
        'not carry it and khoan 5\'s CB does not net it: the ledger adds the '
        'outstanding principal to available while leaving settled_balance alone '
        'and keeping the tranche at full face, so CB = settled + pending has '
        'the advance cancel exactly. Its INTEREST is a charge and sits outside '
        'the algebra altogether, reported and never netted. If a firm treats an '
        'advance as ky quy debt, this is wrong for that firm'),

    'collateral_haircut_not_applied': _p('QD 87 Dieu 2.4', _D,
        'OUR CHOICE. Dieu 2.4 gives a CEILING -- the value is "do cong ty chung '
        'khoan xac dinh tren Hop dong ... nhung khong vuot qua gia dong cua tai '
        'ngay gan nhat" -- and the value inside it is a contract term the '
        'research never read. value_collateral therefore applies the cap and '
        'NOT the per-ticker ty le cho vay, for two reasons: the haircut is '
        'unsourced, and the loan ratio already enters through imr = 1 - '
        'loan_ratio, so applying it to PV as well would haircut the same '
        'collateral twice and the second cut would be invisible. A firm whose '
        'contract really values collateral at the loan ratio passes lots '
        'already haircut'),

    'unpriced_only_where_it_would_count': _p('TT 120 Dieu 9.6', _D,
        'OUR CHOICE. A lot that cannot be valued makes the account '
        'INDETERMINATE only if it would otherwise have counted toward PV. An '
        'INELIGIBLE security is excluded from the collateral base for both '
        'ratios whatever it is worth, so its missing price cannot change any '
        'ratio; the same goes for a bucket this firm\'s flags exclude. Naming '
        'those would make nearly every account INDETERMINATE, which is how a '
        'three-valued answer stops being read at all'),

    'account_status_precedence': _p('QD 87 Dieu 5, Dieu 7, TT 120 Dieu 9.9', _D,
        'OUR CHOICE, and there is exactly ONE implementation of it. '
        'MarginAccountStatus is single-valued and no article ranks its rungs, '
        'so account_status grades INDETERMINATE > FORCE_SELL > CALL > SUSPENDED '
        '> OK. compute_account_algebra DELEGATES to it rather than repeating '
        'the ladder: a second grader would be free to drift from the one the '
        'call and forced-sale machine uses, and the two would then disagree '
        'about the same account. It grades against binding_policy, not against '
        'terms, so a run crossing a Dieu 5.3 adjustment is graded on the floors '
        'in force. See suspension_does_not_shelter_a_breach'),

    'zero_asset_account_is_force_sell': _p('QD 87 Dieu 2 khoan 7', _D,
        'With EB = 0 the ratio AB/EB is undefined and is reported as None, '
        'which must never read as zero or as fine. account_status splits it on '
        'the debt: no debt is OK, since there is nothing to grade, and a debt '
        'outstanding is FORCE_SELL rather than INDETERMINATE, because total '
        'collateral loss against a live du no ky quy is not a gap in the data '
        '-- it is QD 87 Dieu 8\'s "liquidation does not cover DB" case, and '
        'nothing about it is unknown'),

    'no_engine_yet': _p(None, _R,
        'SUPERSEDED 2026-08-26, and kept under its original key so a reader who '
        'saw the old claim finds the correction. This module is NO LONGER the '
        'type contract only: QD 87 Dieu 2\'s algebra, the Dieu 2.4 valuation '
        'cap, the Dieu 6.1 determination schedule, the Dieu 13.5(d) pre-trade '
        'gate, the Dieu 7 call machinery and the Dieu 8 forced-sale machinery '
        'are all implemented and tested here. What remains true: nothing '
        'imports this module yet, and it still places no orders -- the engine '
        'reports what is due and the caller submits it'),

    'per_order_imr_from_loan_ratio': _p('QD 87 Dieu 2 khoan 8', _D,
        'khoan 8 makes imr a PER-ORDER ratio at market price at trade time, and '
        'is VERIFIED. What is DERIVED is the bridge to the number brokers '
        'actually publish: they publish a per-ticker ty le cho vay, never an '
        'imr, and imr = 1 - loan_ratio is OUR identity, in no text read, true '
        'only for a single fully collateralised purchase. '
        'order_initial_margin_ratio uses it DEFENSIVELY -- max(firm imr, 1 - '
        'loan_ratio) -- so it can only tighten the gate, never loosen it below '
        'a term the firm stated or below the Dieu 5.1 floor'),

    'gate_uses_the_multiplicative_form': _p('QD 87 Dieu 13.5(d)', _D,
        'OUR CHOICE. "order_value x imr <= EE" and "order_value <= BP" are the '
        'same statement in exact arithmetic, but BP = EE / imr is a Decimal '
        'division correct only to the context precision, so at the boundary the '
        'two can disagree by an ulp. The decision uses the multiplication, '
        'which cannot; BP is still reported, because it is the number a client '
        'is quoted'),

    'firm_limits_are_opt_in': _p('QD 87 Dieu 9', _D,
        'OUR CHOICE. The four Dieu 9 caps are facts about a CTCK\'s whole book, '
        'not about one account, so assess_margin_order tests them only when a '
        'FirmLendingState is supplied and records firm_limits_tested=False '
        'otherwise. They are NOT reported as INDETERMINATE when absent: that '
        'would make every ordinary gate call indeterminate and drain the word '
        'of the meaning it carries for eligibility, where absent data really is '
        'the finding. A STALE equity statement is different -- there the caller '
        'asked for the test and the inputs cannot support it, so it is '
        'INDETERMINATE'),

    'withdrawal_gate_not_implemented': _p('QD 87 Dieu 13.5(c), 13.5(d)', _S,
        'Dieu 13.5(d) bars trading OR WITHDRAWING beyond buying power, and Dieu '
        '13.5(c) lets a client withdraw cash only after every debt to the CTCK '
        'is cleared. Neither is implemented: the arithmetic is the same but the '
        'verdict record is order-shaped, and bolting a withdrawal onto '
        'MarginOrderAssessment would report a withdrawal as an order. '
        'MarginRegulation.cash_withdrawal_requires_debt_cleared and '
        'withdrawal_only_after_debt_deducted carry the rules for whoever adds '
        'it'),

    'session_bounds_for_the_sweep': _p('QD 87 Dieu 6.1', _S,
        'Dieu 6.1 mandates an END-OF-DAY determination and names no other '
        'moment; the within-day timestamp is "agreed in writing with the '
        'client". DEFAULT_SESSION_OPEN 09:00 and DEFAULT_SESSION_CLOSE 15:00 '
        'are DNSE\'s published call-notice sweep window, REPORTED at one firm '
        'and adopted here as a default; RatioSchedule.determination_at defaults '
        'to the close because "cuoi ngay giao dich" needs no further '
        'assumption. A caller simulating a real venue passes that venue\'s '
        'bounds. The statutory instant is never removed by the intraday option '
        '-- sweeps are additional, and additional is stricter'),
})


# ==========================================================================
# ELIGIBILITY -- spec sections 2.5, 2.6, 2.7 and 2.11
# ==========================================================================
#
# Two layers, in the spec's own words: *a two-layer negative -> positive list*.
# The exchange publishes a NEGATIVE list under QD 87 Dieu 3 (the statutory
# exclusions) and Dieu 4.1 (a full snapshot, within 2 business days of any
# trigger); each CTCK then selects its own POSITIVE list from what remains and
# publishes it within 2 business days (Dieu 4.2).
#
# **Nothing here ships a list.** We cannot know a broker's actual universe, and
# a compiled-in one would be a fabricated market. Both lists are dated data
# supplied by the caller -- exactly like the VSDC settlement calendar -- and
# what this module adds is the statutory layer *on top of* whatever the caller
# supplies: the Dieu 3 predicates are evaluated independently, and a positive
# statutory exclusion beats a broker list that still carries the ticker.
#
# **The predicates are data, not branches.** Each one is an ExclusionRule in
# STATUTORY_EXCLUSION_RULES, keyed by ExclusionPredicate, carrying its own
# article and grade and a three-valued test. The assessor iterates the table; it
# does not know the predicates by name. A caller may pass a different table
# through EligibilityPolicy.rules -- and a predicate the table does not
# implement comes back UNEVALUATED, never "passes".
#
# **Three-valued throughout.** ``True`` the predicate holds and the security is
# out, ``False`` it was checked and passed, ``None`` it could not be checked.
# Most of Dieu 3 needs issuer financial-statement facts this corpus does not
# carry, and the spec is explicit that where a predicate cannot be evaluated the
# answer is INDETERMINATE and never "eligible". Every fact record below uses
# ``None`` for *not known* and reserves ``False`` for *checked and clean*, so a
# caller cannot get a clean bill of health by leaving a field out.


#: **QD 87 Dieu 3.4. VERIFIED.** A security is excluded when the issuer is more
#: than five business days late disclosing the audited annual FS or the
#: reviewed/audited semi-annual FS, counted from the deadline or the end of any
#: granted extension. Strictly *more than* -- exactly five days late is not yet
#: an exclusion.
#:
#: **Why this is a module constant and not a** :class:`MarginRegulation` **field.**
#: It is a statutory number and it belongs on the dated row; it is here only
#: because this stage is additive to an object that already shipped, and
#: promoting it is a one-line change when :data:`MARGIN_REGULATIONS` next gains
#: a row. Recorded in :data:`PROVENANCE` under ``eligibility_constants_undated``
#: so the debt is visible rather than implied.
LATE_DISCLOSURE_BUSINESS_DAYS = 5

#: **QD 87 Dieu 3.6, the public-fund limb. VERIFIED.** For a fund certificate the
#: test is NAV per unit below par for **at least one month**, looking at the
#: **three consecutive months** to the selection date. Same undated-constant
#: caveat as :data:`LATE_DISCLOSURE_BUSINESS_DAYS`.
FUND_NAV_LOOKBACK_MONTHS = 3

#: **QD 1205/QD-UBCK (2017-12-27) took effect 2018-01-02** and amended **only**
#: khoan 5 Dieu 3 of QD 87 -- the tax and prosecution limb. VERIFIED.
#:
#: The amendment **narrowed** the exclusion. Before this date any conclusion by
#: a tax authority that the issuer had committed a violation cut margin; from
#: this date only an administrative-penalty decision for **tax evasion or tax
#: fraud**, or for **failure to comply with a tax-enforcement decision**, or a
#: decision to **prosecute** (*khoi to bi can*) the company does. Mis-declaration
#: causing underpayment, late payment and similar no longer do.
#:
#: The spec says to implement this as a dated rule change, and
#: :func:`_test_tax_or_prosecution` does -- as a date comparison **inside the
#: predicate**, because :data:`MARGIN_REGULATIONS` carries one row spanning the
#: change and splitting it would mean re-issuing an object another stage owns.
QD_1205_EFFECTIVE_FROM = date(2018, 1, 2)


# Every eligibility window in this section is stated in *thang* -- six months
# listed (Dieu 3.1), six months after an offering completes (Dieu 10.1(a)), six
# months between relistings (Dieu 4.1) -- and all three go through the module's
# shared ``_add_months``, which clamps the anniversary to the shorter month.
# That clamping is a choice nobody gazetted; it is declared in
# :data:`PROVENANCE` under ``month_arithmetic``. It is not
# :data:`MAX_DAYS_IN_MONTH`, which is a deliberately loose config-time bridge
# for loan terms a broker publishes in days and is not used here.


# --------------------------------------------------------------------------
# Facts the caller supplies -- None means NOT KNOWN, never "clean"
# --------------------------------------------------------------------------

class TradingStatus(str, Enum):
    """An issuer's trading status, as the exchanges publish it.

    **Two groups, and the split is the whole point.** The first five are
    QD 87 Dieu 3.2's own enumeration and are VERIFIED. The last two are statuses
    the post-2020 listing rules created; they are **absent from Dieu 3.2's
    vocabulary**, current HOSE practice cuts margin for them anyway (HVN
    excluded for *han che giao dich* + *kiem soat* on 2026-04-03; ASP and SVD
    under *han che giao dich* on 2025-07-03, both REPORTED), and **the rulebook
    is SILENT on the mapping**. Spec section 4 item 8 names this as one of the
    nine things not to invent.

    So they are members of this enum -- a caller must be able to *state* the
    fact -- and what they mean for eligibility is decided by
    :attr:`EligibilityPolicy.unmapped_status_policy`, which defaults to
    :attr:`UnmappedStatusPolicy.INDETERMINATE`. See
    :data:`STATUTORY_TRADING_STATUSES` and :data:`UNMAPPED_TRADING_STATUSES`.

    ``NORMAL``
        No status. Present so a caller can say *checked, and there is nothing*
        explicitly, though an empty tuple means the same.

    QD 87 Dieu 3.2 -- VERIFIED, each one excludes on its own:

    ``CANH_BAO``
        *Canh bao* -- warning.
    ``KIEM_SOAT``
        *Kiem soat* -- control.
    ``KIEM_SOAT_DAC_BIET``
        *Kiem soat dac biet* -- special control.
    ``TAM_NGUNG_GIAO_DICH``
        *Tam ngung giao dich* -- trading halted.
    ``HUY_NIEM_YET``
        In the delisting queue -- *thuoc dien huy niem yet*.

    Post-2020 listing rules -- REPORTED practice, **mapping SILENT**:

    ``HAN_CHE_GIAO_DICH``
        *Han che giao dich* -- trading restricted to certain sessions.
    ``DINH_CHI_GIAO_DICH``
        *Dinh chi giao dich* -- trading suspended.
    """

    NORMAL = 'normal'

    CANH_BAO = 'canh_bao'
    KIEM_SOAT = 'kiem_soat'
    KIEM_SOAT_DAC_BIET = 'kiem_soat_dac_biet'
    TAM_NGUNG_GIAO_DICH = 'tam_ngung_giao_dich'
    HUY_NIEM_YET = 'huy_niem_yet'

    HAN_CHE_GIAO_DICH = 'han_che_giao_dich'
    DINH_CHI_GIAO_DICH = 'dinh_chi_giao_dich'


#: The five statuses **QD 87 Dieu 3.2 names**. Any one of them excludes.
STATUTORY_TRADING_STATUSES: FrozenSet[TradingStatus] = frozenset({
    TradingStatus.CANH_BAO,
    TradingStatus.KIEM_SOAT,
    TradingStatus.KIEM_SOAT_DAC_BIET,
    TradingStatus.TAM_NGUNG_GIAO_DICH,
    TradingStatus.HUY_NIEM_YET,
})

#: The statuses Dieu 3.2 **does not name**, which HOSE nonetheless cuts margin
#: for. The mapping onto Dieu 3.2 is SILENT -- see
#: :class:`UnmappedStatusPolicy`.
UNMAPPED_TRADING_STATUSES: FrozenSet[TradingStatus] = frozenset({
    TradingStatus.HAN_CHE_GIAO_DICH,
    TradingStatus.DINH_CHI_GIAO_DICH,
})


class UnmappedStatusPolicy(str, Enum):
    """What a post-2020 trading status means, given that no text says.

    Spec section 4, item 8: *"The rulebook is silent on this mapping. Record it
    as SILENT; do not encode a mapping as if it were gazetted."* The decision is
    unavoidable -- a security carrying only *han che giao dich* is either in or
    out -- so it is configurable, and the default is the one answer that invents
    nothing.

    ``INDETERMINATE``
        **The default, and OUR CHOICE.** The predicate cannot be evaluated, so
        :attr:`MarginEligibility.INDETERMINATE` and ``TRADING_STATUS`` lands in
        ``unevaluated``. Conservative in the only sense that matters here: it
        never reads as eligible, and it never asserts a mapping nobody
        gazetted.
    ``EXCLUDE``
        Follow observed HOSE practice and treat it as Dieu 3.2's equivalent.
        **REPORTED, from three ticker-level observations.** Correct about the
        market and unsupported by the text.
    ``IGNORE``
        Read Dieu 3.2 literally: a status it does not enumerate does not
        exclude. Correct about the text and wrong about the market. Offered
        because a paper reporting *what the rulebook says* wants exactly this.
    """

    INDETERMINATE = 'indeterminate'
    EXCLUDE = 'exclude'
    IGNORE = 'ignore'


class AuditOpinion(str, Enum):
    """The auditor's opinion on the issuer's financial statements.

    QD 87 Dieu 3.3 excludes on any opinion **other than unqualified**, so the
    only distinction the rule needs is ``UNQUALIFIED`` versus everything else.
    The three others are separate anyway because a rejection report that says
    *adverse* is worth more than one that says *not unqualified*, and because
    the four are the standard Vietnamese set.

    ``UNQUALIFIED``
        *Y kien chap nhan toan phan.* The only one that passes.
    ``QUALIFIED``
        *Y kien ngoai tru.*
    ``ADVERSE``
        *Y kien trai nguoc.*
    ``DISCLAIMER``
        *Tu choi dua ra y kien.*
    """

    UNQUALIFIED = 'unqualified'
    QUALIFIED = 'qualified'
    ADVERSE = 'adverse'
    DISCLAIMER = 'disclaimer'


class SecurityKind(str, Enum):
    """What QD 87 Dieu 3's universe contains: *co phieu* and *chung chi quy*.

    The kind changes one predicate. Dieu 3.6's loss test is *loss in the period
    and/or accumulated loss* for a share, and for a **public fund** it is
    instead *NAV per unit below par for at least one month over the three
    consecutive months to the selection date*. Two different tests behind one
    :attr:`ExclusionPredicate.LOSS_OR_ACCUMULATED_LOSS`, selected by this field.
    """

    SHARE = 'share'
    FUND_UNIT = 'fund_unit'


@dataclass(frozen=True)
class SecurityFacts:
    """Everything QD 87 Dieu 3 needs to know about one security on one date.

    **``None`` means the fact was not obtained. It never means "clean".** That
    convention is the reason this record exists rather than a dict of booleans:
    a caller who omits a field gets :attr:`MarginEligibility.INDETERMINATE`,
    which is the spec's instruction, instead of an accidental pass. ``False``
    is reserved for *checked, and it does not hold*.

    A bare ``SecurityFacts(ticker, as_of)`` therefore evaluates to
    INDETERMINATE on every predicate, which is the honest answer for a caller
    who has supplied no facts.

    Attributes:
        ticker: the security.
        as_of: the **review date**. Dieu 3.1 counts the listing window to it,
            Dieu 3.6's fund limb calls it the *selection date*, and
            :data:`QD_1205_EFFECTIVE_FROM` is compared against it.
        venue: where it trades. ``None`` leaves
            :attr:`ExclusionPredicate.INELIGIBLE_VENUE` unevaluated.
        kind: share or fund unit -- selects Dieu 3.6's two tests.
        first_trading_day: **Dieu 3.1**, the day the listing window starts.
        prior_venue_listed_days: **Dieu 3.1's summation rule.** On a venue
            transfer *the two exchanges' listed times are summed*, so a ticker
            that spent five months on HNX and one on HOSE is six months
            listed. Implemented by shifting ``first_trading_day`` back by this
            many days -- **OUR READING** of a text that says only "summed", and
            declared in :data:`PROVENANCE` under ``venue_transfer_summation``.
        trading_statuses: **Dieu 3.2.** ``None`` is *not checked*; ``()`` and
            ``(TradingStatus.NORMAL,)`` are both *checked and clean*. A
            post-2020 status here is resolved by
            :attr:`EligibilityPolicy.unmapped_status_policy`.
        latest_audit_opinion: **Dieu 3.3**, from the audited annual FS or the
            reviewed/audited semi-annual FS, whichever is latest.
        financial_statement_days_late: **Dieu 3.4**, business days past the
            disclosure deadline or the end of any granted extension. Excluded
            at **more than** :data:`LATE_DISCLOSURE_BUSINESS_DAYS`.
        tax_evasion_or_fraud_decision: **Dieu 3.5, QD 1205 wording.** An
            administrative-penalty decision against the listed company for tax
            evasion or tax fraud.
        tax_enforcement_non_compliance_decision: **Dieu 3.5, QD 1205 wording.**
            A penalty decision for failure to comply with a tax-enforcement
            decision.
        prosecution_decision: **Dieu 3.5, QD 1205 wording.** A decision to
            prosecute the company -- *khoi to bi can*.
        other_tax_violation_conclusion: **Dieu 3.5 in its ORIGINAL wording, and
            it stops mattering on 2018-01-02.** Any other tax-authority
            conclusion of a violation -- mis-declaration causing underpayment,
            late payment. QD 1205 removed these, so this field excludes only
            **before** :data:`QD_1205_EFFECTIVE_FROM` and is ignored on or
            after it. A caller running a 2017 counterfactual needs it; a caller
            running 2026 should leave it ``None``.
        period_loss: **Dieu 3.6**, share limb -- a loss in the period on the
            latest audited annual or reviewed/audited semi-annual FS.
        accumulated_loss: **Dieu 3.6**, share limb -- accumulated loss on the
            same statements.
        is_parent_company: **Dieu 3.6** requires a parent to be tested on the
            **consolidated** statements.
        statements_are_consolidated: whether the two loss flags were read off
            consolidated statements. For a parent, anything but ``True`` means
            the facts came from the wrong entity and the predicate is
            **unevaluated** -- not "passes". Ignored for a non-parent.
        fund_nav_below_par_months: **Dieu 3.6**, fund limb -- in how many of the
            :data:`FUND_NAV_LOOKBACK_MONTHS` consecutive months to ``as_of``
            NAV per unit was below par. One is enough to exclude.
        note: free text carried onto the assessment, e.g. which HOSE
            publication these facts came from.
    """

    ticker: str
    as_of: date
    venue: Optional[Venue] = None
    kind: SecurityKind = SecurityKind.SHARE

    first_trading_day: Optional[date] = None
    prior_venue_listed_days: int = 0

    trading_statuses: Optional[Tuple[TradingStatus, ...]] = None

    latest_audit_opinion: Optional[AuditOpinion] = None
    financial_statement_days_late: Optional[int] = None

    tax_evasion_or_fraud_decision: Optional[bool] = None
    tax_enforcement_non_compliance_decision: Optional[bool] = None
    prosecution_decision: Optional[bool] = None
    other_tax_violation_conclusion: Optional[bool] = None

    period_loss: Optional[bool] = None
    accumulated_loss: Optional[bool] = None
    is_parent_company: bool = False
    statements_are_consolidated: Optional[bool] = None
    fund_nav_below_par_months: Optional[int] = None

    note: Optional[str] = None

    def __post_init__(self) -> None:
        if self.prior_venue_listed_days < 0:
            raise ValueError(
                f'prior_venue_listed_days={self.prior_venue_listed_days} is '
                f'negative. QD 87 Dieu 3.1 SUMS the time listed on each venue; '
                f'a negative summand would shorten the window instead of '
                f'lengthening it')
        if (self.financial_statement_days_late is not None
                and self.financial_statement_days_late < 0):
            raise ValueError(
                f'financial_statement_days_late='
                f'{self.financial_statement_days_late} is negative. QD 87 Dieu '
                f'3.4 counts lateness from the deadline; early disclosure is 0')
        if self.fund_nav_below_par_months is not None:
            if not 0 <= self.fund_nav_below_par_months <= FUND_NAV_LOOKBACK_MONTHS:
                raise ValueError(
                    f'fund_nav_below_par_months='
                    f'{self.fund_nav_below_par_months} is outside the '
                    f'{FUND_NAV_LOOKBACK_MONTHS}-month window QD 87 Dieu 3.6 '
                    f'looks at')


@dataclass(frozen=True)
class InvestorFacts:
    """Everything QD 87 Dieu 13.4 and TT 120 Dieu 9.1-9.3 need about one holder.

    Same convention as :class:`SecurityFacts`: ``None`` is *not known* and never
    *clean*. A bare ``InvestorFacts(account_id, as_of)`` is INDETERMINATE,
    because a caller who has asserted nothing about an investor has not
    established that the investor may borrow.

    **One deliberate exception, and it is a scope cut, not a fact.**
    ``is_foreign_investor=None`` resolves to *domestic* while
    :attr:`EligibilityPolicy.assume_domestic_investor` is set, which it is by
    default. This iteration models a domestic investor throughout; the
    assumption is written into :attr:`InvestorEligibility.note` on every
    assessment that uses it, so it is loud rather than silent, and clearing the
    flag makes an unstated nationality INDETERMINATE like everything else. See
    :data:`PROVENANCE` under ``domestic_investor_scope_cut``.

    Attributes:
        account_id: the segregated margin account (TT 120 Dieu 9.3).
        as_of: the date this is asserted for.
        has_margin_contract: **TT 120 Dieu 9.1 / QD 87 Dieu 12.1.** The *hop
            dong giao dich ky quy* **is** the credit agreement, so ``False``
            bars lending outright and ``None`` leaves it undecidable.
        is_foreign_investor: **TT 120 Dieu 9.2 / QD 87 Dieu 10.1(dd)**, a flat
            prohibition. Read the warning on
            :attr:`MarginRegulation.foreign_investors_allowed` before treating
            a refusal here as "foreigners cannot buy on credit" -- TT 120
            Dieu 9a is a separate regime, out of scope, and not *ky quy*.
        holder_classes: which :class:`IneligibleAccountHolder` categories this
            holder **is** in. Empty means checked and none.
        unknown_holder_classes: categories that could **not** be checked.
            ``RELATED_PERSON`` is the standing example -- it needs a
            relationship graph no corpus in this project carries -- and naming
            it here is how it reaches ``unevaluated`` instead of being assumed
            away.
        margin_account_is_segregated: **TT 120 Dieu 9.3 / QD 87 Dieu 13.5(a).**
            ``False`` bars the account. ``None`` is **not** a bar, and that is
            OUR CHOICE: segregation is a property of the CTCK's account
            architecture rather than of the investor, and in a simulator we
            build that architecture ourselves. Declared in :data:`PROVENANCE`
            under ``unasserted_account_architecture``.
        has_other_margin_account_at_ctck: **TT 120 Dieu 9.3** -- one margin
            account per investor per CTCK. ``True`` bars a second one; ``None``
            is not a bar, same reasoning and same provenance entry.
        trades_through_authorised_person: whether an authorised or proxy trader
            operates the account. **Not statute.** ACBS's FAQ says such a
            person cannot register margin on the owner's behalf; that is
            REPORTED and a **broker term**, so it bars only when
            :attr:`EligibilityPolicy.bar_authorised_traders` is set, which it
            is not by default.
        note: free text carried onto the assessment.
    """

    account_id: str
    as_of: date
    has_margin_contract: Optional[bool] = None
    is_foreign_investor: Optional[bool] = None
    holder_classes: Tuple[IneligibleAccountHolder, ...] = ()
    unknown_holder_classes: Tuple[IneligibleAccountHolder, ...] = ()
    margin_account_is_segregated: Optional[bool] = None
    has_other_margin_account_at_ctck: Optional[bool] = None
    trades_through_authorised_person: Optional[bool] = None
    note: Optional[str] = None

    def __post_init__(self) -> None:
        both = set(self.holder_classes) & set(self.unknown_holder_classes)
        if both:
            names = ', '.join(sorted(c.value for c in both))
            raise ValueError(
                f'{names} appears in both holder_classes and '
                f'unknown_holder_classes. A category cannot be simultaneously '
                f'established and unknown, and allowing it would make the '
                f'INELIGIBLE / INDETERMINATE distinction depend on which set '
                f'was consulted first')


@dataclass(frozen=True)
class CollateralRelationship:
    """The facts QD 87 Dieu 10.1(a)-(c) needs: the CTCK, the issuer, the paper.

    Separate from :class:`SecurityFacts` because these are not properties of the
    security at all -- they are properties of the **relationship between the
    lending firm and the issuer**, and the same ticker is prohibited collateral
    at one CTCK and ordinary collateral at the next. Folding them into
    ``SecurityFacts`` would make an exchange-published fact and a firm-specific
    one look like the same kind of thing.

    ``None`` is *not known*, as everywhere else in this section.

    Attributes:
        ticker: the security.
        as_of: the date this is asserted for.
        self_underwritten: **Dieu 10.1(a)** -- did this CTCK firm-underwrite
            this paper? ``False`` passes; ``True`` starts the lockout window.
        underwriting_contract_signed_on: when the underwriting contract was
            signed. The lockout runs from here.
        offering_completed_on: when the offering completed. The lockout ends
            :attr:`MarginRegulation.underwriting_lockout_months` after it.
            ``None`` while ``self_underwritten`` is ``True`` means the offering
            has not completed, so the window has not started closing and the
            paper is **prohibited** -- determinate, not unknown.
        is_own_share: **Dieu 10.1(c)** -- the CTCK's own shares.
        issuer_stake_in_ctck: **Dieu 10.1(b)**, first limb -- the fraction of
            the CTCK's charter capital this listed issuer owns. Prohibited at
            or above :attr:`MarginRegulation.affiliate_ownership_threshold`.
        ctck_stake_in_issuer: **Dieu 10.1(b)**, second limb -- the fraction of
            this issuer the CTCK owns. The second limb reaches
            *registered-for-trading* companies as well as listed ones, so a
            UPCoM issuer can trigger it even though UPCoM paper is outside
            Dieu 3's margin universe anyway.
        note: free text.
    """

    ticker: str
    as_of: date
    self_underwritten: Optional[bool] = None
    underwriting_contract_signed_on: Optional[date] = None
    offering_completed_on: Optional[date] = None
    is_own_share: Optional[bool] = None
    issuer_stake_in_ctck: Optional[Decimal] = None
    ctck_stake_in_issuer: Optional[Decimal] = None
    note: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ('issuer_stake_in_ctck', 'ctck_stake_in_issuer'):
            value = getattr(self, name)
            if value is None:
                continue
            _require_decimal(name, value)
            if not _ZERO <= value <= _ONE:
                raise ValueError(
                    f'{name}={value} is not a fraction in [0, 1]. QD 87 '
                    f'Dieu 10.1(b) is a 50 % OWNERSHIP threshold, so this is a '
                    f'fraction of charter capital -- not a percentage and not a '
                    f'share count')


# --------------------------------------------------------------------------
# The two published lists -- dated data, supplied by the caller
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ExchangeMarginList:
    """Layer 1: the exchange's **NEGATIVE** list. QD 87 Dieu 4.1. VERIFIED.

    *"The publication is a full snapshot, not a delta"* -- every ineligible
    security as at that moment, published within 2 business days of any Dieu 3
    trigger arising. That is what makes an **absence** informative: on a full
    snapshot, a ticker that is not named is a ticker the exchange has not
    excluded. A caller holding only a partial extract must say so with
    :attr:`covers_venue_universe`, and absence then proves nothing.

    HOSE publishes a full list quarterly plus event-driven updates (68 codes for
    Q2/2026 on 2026-04-03; 93 codes for Q2/2024). REPORTED, and not something
    this module encodes -- **nothing here ships a list**.

    Attributes:
        published_on: the publication date. Eligibility is dated, and a
            snapshot older than the review date is the normal case rather than
            an error -- it is the last one the exchange put out.
        ineligible: ticker -> the Dieu 3 predicates the exchange gave as its
            reasons. An empty tuple of reasons is legal -- the exchange named
            the ticker without a machine-readable reason -- and the ticker is
            still ineligible.
        venue: which venue this snapshot covers, or ``None`` for a
            caller-assembled all-venue list. A snapshot for one venue must not
            be consulted about a security on another, and
            :func:`assess_security` refuses that outright rather than
            answering.
        covers_venue_universe: whether this really is the Dieu 4.1 full
            snapshot. ``False`` says *this is a partial extract*, and then a
            ticker's absence leaves the published-list layer **unevaluated**
            instead of clean. Defaults to ``True`` because that is what
            Dieu 4.1 requires the exchange to publish.
        source: where the caller got it, for a rejection report.
    """

    published_on: date
    ineligible: Mapping[str, Tuple[ExclusionPredicate, ...]] = \
        field(default_factory=dict)
    venue: Optional[Venue] = None
    covers_venue_universe: bool = True
    source: Optional[str] = None

    def names(self, ticker: str) -> bool:
        """Whether this snapshot excludes ``ticker``."""
        return ticker in self.ineligible

    def reasons(self, ticker: str) -> Tuple[ExclusionPredicate, ...]:
        """The predicates the exchange gave for ``ticker``. Empty if none."""
        return tuple(self.ineligible.get(ticker, ()))


@dataclass(frozen=True)
class BrokerMarginList:
    """Layer 2: one CTCK's **POSITIVE** list. QD 87 Dieu 4.2 / Dieu 13.7.

    Published within 2 business days of the exchange's publication, on the
    firm's website and at all business locations, and reported to the exchange
    on Phu luc 01 before the 5th trading day of the following month. VERIFIED.

    **This is the list we cannot know**, which is exactly why it is an argument.
    A ticker absent from it passes every statutory predicate and still cannot be
    margined at this firm -- a commercial decision, reported through
    :attr:`SecurityEligibility.on_broker_list` and never through ``failed``,
    because it is not a rule breach.

    Attributes:
        tickers: what the firm lends against.
        published_on: when the firm published this version.
        effective_from: when it starts binding. Brokers issue per-ticker
            add/remove notices with an effective date, so a list can be
            published before it takes effect; a list consulted before its own
            effective date yields INDETERMINATE rather than being applied
            early.
        loan_ratio_by_ticker: the per-ticker *ty le cho vay*, where published.
            Every key must be in ``tickers`` -- a ratio for a ticker the firm
            does not lend against is a contradiction, not a default.
        firm: whose list it is.
    """

    tickers: FrozenSet[str]
    published_on: date
    effective_from: Optional[date] = None
    loan_ratio_by_ticker: Mapping[str, Decimal] = field(default_factory=dict)
    firm: Optional[str] = None

    def __post_init__(self) -> None:
        stray = set(self.loan_ratio_by_ticker) - set(self.tickers)
        if stray:
            names = ', '.join(sorted(stray))
            raise ValueError(
                f'loan_ratio_by_ticker names {names}, which is not on this '
                f'positive list. A ty le cho vay for paper the firm does not '
                f'lend against is a contradiction; QD 87 Dieu 13.7 requires '
                f'the published list and the published ratios to describe the '
                f'same universe')
        for ticker, ratio in sorted(self.loan_ratio_by_ticker.items()):
            _require_decimal(f'loan_ratio_by_ticker[{ticker}]', ratio)
            if not _ZERO < ratio <= _ONE:
                raise ValueError(
                    f'loan_ratio_by_ticker[{ticker}]={ratio} is outside '
                    f'(0, 1]. A ty le cho vay is a fraction of the collateral '
                    f'value; zero means the firm does not lend against it, '
                    f'which it says by leaving the ticker off the list')
        if (self.effective_from is not None
                and self.effective_from < self.published_on):
            raise ValueError(
                f'effective_from={self.effective_from.isoformat()} precedes '
                f'published_on={self.published_on.isoformat()}. QD 87 Dieu 4.2 '
                f'makes publication the act that binds, so a list cannot take '
                f'effect before the firm published it')

    def carries(self, ticker: str) -> bool:
        """Whether the firm lends against ``ticker``."""
        return ticker in self.tickers

    def loan_ratio(self, ticker: str) -> Optional[Decimal]:
        """The firm's *ty le cho vay*, or ``None`` if it published none."""
        return self.loan_ratio_by_ticker.get(ticker)

    def is_in_force(self, on: date) -> bool:
        """Whether this version binds on ``on``."""
        return on >= (self.effective_from or self.published_on)


def earliest_relist_date(last_published_on: date,
                         *,
                         regulation: MarginRegulation = QD_87_2017,
                         listed_under_six_months_case: bool = False) -> date:
    """When a security may next come **off** the ineligible list. Dieu 4.1.

    VERIFIED: removal happens *at most once every 6 months from the last
    publication*, and the exact timing inside that is the exchange's call --
    which is why this returns the **earliest permissible** date and not a
    predicted one. The single carve-out is the under-six-months case: a security
    excluded only for being newly listed comes off when it reaches six months,
    not on the relist cadence.

    Args:
        last_published_on: the exchange's last publication naming it.
        regulation: the dated row supplying
            :attr:`MarginRegulation.relist_review_min_months`.
        listed_under_six_months_case: whether the only exclusion was
            :attr:`ExclusionPredicate.LISTED_UNDER_SIX_MONTHS`. Then the
            cadence does not apply and ``last_published_on`` is returned
            unchanged -- the security is free as soon as the listing window
            closes, which that predicate decides on its own facts.
    """
    if listed_under_six_months_case:
        return last_published_on
    return _add_months(last_published_on, regulation.relist_review_min_months)


# --------------------------------------------------------------------------
# The exclusion predicates, as DATA
# --------------------------------------------------------------------------

#: A predicate's answer: ``True`` it holds and the security is out, ``False`` it
#: was checked and passed, ``None`` it could not be checked on these facts.
#:
#: The third value is not defensive. Most of QD 87 Dieu 3 needs issuer
#: financial-statement facts this project's corpus does not carry, and the spec
#: is explicit: where a predicate cannot be evaluated the answer is
#: INDETERMINATE, never "eligible".
PredicateAnswer = Optional[bool]

#: The shape every predicate test has. Taking the regulation and the policy as
#: arguments -- rather than closing over them -- is what lets a dated row change
#: an answer (``eligible_venues``, ``min_listing_months``) and lets a caller's
#: policy resolve the one mapping nobody gazetted.
PredicateTest = Callable[
    ['SecurityFacts', MarginRegulation, 'EligibilityPolicy'], PredicateAnswer]


@dataclass(frozen=True)
class ExclusionRule:
    """One QD 87 Dieu 3 predicate, as data: its article, its grade, its test.

    **This is the point of the section.** A hard-coded chain of ``if`` branches
    would compile the exclusion list into the engine, and a compiled-in list is
    exactly what the spec forbids -- the universe is *supplied* data. Here the
    predicates are a mapping the caller can inspect, subset or replace, and the
    assessor iterates it without knowing any predicate by name.

    It also makes overclaiming testable. Each rule carries the article it
    implements and the grade behind it, so *"every statutory predicate cites a
    clause someone read"* is an assertion rather than a hope.

    Attributes:
        predicate: which :class:`ExclusionPredicate` this implements.
        article: the clause, as cited.
        grade: how well that clause is sourced. VERIFIED for all seven
            statutory rules -- what is SILENT in Dieu 3.2 is the *mapping* of
            the post-2020 statuses onto it, not the article.
        summary: one line, for a rejection report.
        test: the three-valued predicate. See :data:`PredicateAnswer`.
    """

    predicate: ExclusionPredicate
    article: str
    grade: SourceGrade
    summary: str
    test: PredicateTest

    def __call__(self, facts: 'SecurityFacts', regulation: MarginRegulation,
                 policy: 'EligibilityPolicy') -> PredicateAnswer:
        """Evaluate, so a rule works wherever a callable is expected."""
        return self.test(facts, regulation, policy)


def _any_true_else_unknown(*values: Optional[bool]) -> PredicateAnswer:
    """``True`` if any is ``True``; ``None`` if any is unknown; else ``False``.

    The ordering is deliberate. A limb that is **known to hold** decides the
    predicate even when a sibling limb is unknown -- an issuer with an
    accumulated loss is out whether or not we also know about the period loss.
    Only when nothing holds does an unknown limb make the predicate unevaluable.
    Checking unknown first would report INDETERMINATE for securities we can
    positively exclude, which loses information in the direction that lets more
    borrowing happen.
    """
    if any(v is True for v in values):
        return True
    if any(v is None for v in values):
        return None
    return False


def _test_ineligible_venue(facts: 'SecurityFacts',
                           regulation: MarginRegulation,
                           policy: 'EligibilityPolicy') -> PredicateAnswer:
    """QD 87 Dieu 3's universe: *co phieu, chung chi quy niem yet*.

    Reads :attr:`MarginRegulation.eligible_venues` rather than naming HOSE and
    HNX, so the recorded TT 120 Dieu 9.4 divergence over UPCoM lives in exactly
    one place -- on the dated field, where its provenance note is -- and a
    future row that admits *dang ky giao dich* changes the answer here without
    changing this function.
    """
    if facts.venue is None:
        return None
    return facts.venue not in regulation.eligible_venues


def _test_listed_under_six_months(facts: 'SecurityFacts',
                                  regulation: MarginRegulation,
                                  policy: 'EligibilityPolicy') -> PredicateAnswer:
    """QD 87 Dieu 3.1 -- listed less than six months at the review date.

    Counted from the first trading day, and on a venue transfer *the two
    exchanges' listed times are summed*. The summation is implemented by
    shifting the first trading day back by
    :attr:`SecurityFacts.prior_venue_listed_days`, which is **OUR READING** of a
    text that says only "summed" -- see :data:`PROVENANCE` under
    ``venue_transfer_summation``. It is exact when the two listings abut and
    generous by the gap when they do not.

    A first trading day in the future is *not yet listed*, which this predicate
    also reports as excluded, for the same reason and under the same article.
    """
    if facts.first_trading_day is None:
        return None
    start = facts.first_trading_day - timedelta(
        days=facts.prior_venue_listed_days)
    return _add_months(start, regulation.min_listing_months) > facts.as_of


def _test_trading_status(facts: 'SecurityFacts',
                         regulation: MarginRegulation,
                         policy: 'EligibilityPolicy') -> PredicateAnswer:
    """QD 87 Dieu 3.2 -- and the one place the rulebook is SILENT.

    The five statuses Dieu 3.2 enumerates exclude outright and are checked
    first, so a security carrying both a gazetted status and a post-2020 one is
    determinately excluded rather than dragged into the unresolved mapping.

    A security carrying **only** a post-2020 status -- *han che giao dich*,
    *dinh chi giao dich* -- is the SILENT case (spec section 4, item 8). HOSE
    cuts margin for these; Dieu 3.2's vocabulary predates them and does not name
    them. :attr:`EligibilityPolicy.unmapped_status_policy` decides, and
    **defaults to INDETERMINATE** -- the only answer that neither invents a
    mapping nor lets an excluded security read as eligible.
    """
    if facts.trading_statuses is None:
        return None
    observed = set(facts.trading_statuses)
    if observed & STATUTORY_TRADING_STATUSES:
        return True
    if observed & UNMAPPED_TRADING_STATUSES:
        if policy.unmapped_status_policy is UnmappedStatusPolicy.EXCLUDE:
            return True
        if policy.unmapped_status_policy is UnmappedStatusPolicy.IGNORE:
            return False
        return None
    return False


def _test_qualified_audit_opinion(facts: 'SecurityFacts',
                                  regulation: MarginRegulation,
                                  policy: 'EligibilityPolicy') -> PredicateAnswer:
    """QD 87 Dieu 3.3 -- any opinion **other than unqualified** excludes.

    The rule is stated negatively in the text and implemented negatively here:
    the test is *not* ``UNQUALIFIED``, not a membership check against a list of
    bad opinions, so an opinion this enum does not yet name still excludes.
    """
    if facts.latest_audit_opinion is None:
        return None
    return facts.latest_audit_opinion is not AuditOpinion.UNQUALIFIED


def _test_late_financial_statement(facts: 'SecurityFacts',
                                   regulation: MarginRegulation,
                                   policy: 'EligibilityPolicy') -> PredicateAnswer:
    """QD 87 Dieu 3.4 -- **more than** five business days late.

    Strictly greater. A security exactly five business days late is not excluded
    by this limb, and the boundary is pinned by test, because an off-by-one here
    silently changes which securities a run can margin.
    """
    if facts.financial_statement_days_late is None:
        return None
    return facts.financial_statement_days_late > LATE_DISCLOSURE_BUSINESS_DAYS


def _test_tax_or_prosecution(facts: 'SecurityFacts',
                             regulation: MarginRegulation,
                             policy: 'EligibilityPolicy') -> PredicateAnswer:
    """QD 87 Dieu 3.5 -- **a dated rule change, implemented as one.**

    QD 1205/QD-UBCK amended only khoan 5 Dieu 3, effective
    :data:`QD_1205_EFFECTIVE_FROM` (2018-01-02), and it **narrowed** the
    exclusion. From that date the limbs are an administrative-penalty decision
    for tax evasion or tax fraud, a penalty decision for failure to comply with
    a tax-enforcement decision, and a decision to prosecute the company. Before
    it, *any* tax-authority conclusion of a violation cut margin --
    mis-declaration causing underpayment, late payment and similar.

    So the same facts give different answers on either side of the date, which
    is what the spec means by *"implement it as one"*. The comparison is against
    :attr:`SecurityFacts.as_of`, the review date.

    **Why the date lives here and not on a dated row.**
    :data:`MARGIN_REGULATIONS` carries a single QD 87 row spanning 2017-04-01
    onwards, and splitting it in two is a change to an object another stage
    owns. The debt is recorded in :data:`PROVENANCE` under
    ``eligibility_constants_undated``.
    """
    narrowed = (facts.tax_evasion_or_fraud_decision,
                facts.tax_enforcement_non_compliance_decision,
                facts.prosecution_decision)
    if facts.as_of >= QD_1205_EFFECTIVE_FROM:
        return _any_true_else_unknown(*narrowed)
    return _any_true_else_unknown(*narrowed,
                                  facts.other_tax_violation_conclusion)


def _test_loss_or_accumulated_loss(facts: 'SecurityFacts',
                                   regulation: MarginRegulation,
                                   policy: 'EligibilityPolicy') -> PredicateAnswer:
    """QD 87 Dieu 3.6 -- two tests, selected by :class:`SecurityKind`.

    For a **share**: loss in the period and/or accumulated loss on the latest
    audited annual or reviewed/audited semi-annual FS. *Parent companies use the
    CONSOLIDATED FS*, so a parent whose flags were read off separate statements
    is **unevaluated** rather than passed -- the facts are about the wrong
    entity, and treating them as clean would admit exactly the issuer the
    consolidation requirement exists to catch.

    For a **public fund**: NAV per unit below par for at least one month,
    looking at the :data:`FUND_NAV_LOOKBACK_MONTHS` consecutive months to the
    selection date.
    """
    if facts.kind is SecurityKind.FUND_UNIT:
        if facts.fund_nav_below_par_months is None:
            return None
        return facts.fund_nav_below_par_months >= 1
    if facts.is_parent_company and facts.statements_are_consolidated is not True:
        return None
    return _any_true_else_unknown(facts.period_loss, facts.accumulated_loss)


#: **QD 87 Dieu 3, as amended by QD 1205 Dieu 1 -- one rule per predicate.**
#:
#: The default table :class:`EligibilityPolicy` hands to
#: :func:`assess_security`. Completeness against :class:`ExclusionPredicate` is
#: a tested invariant: a predicate the regulation lists and this table does not
#: implement would otherwise be silently skipped, which is the failure mode that
#: turns a missing rule into a clean bill of health.
STATUTORY_EXCLUSION_RULES: Mapping[ExclusionPredicate, ExclusionRule] = \
    MappingProxyType({
        ExclusionPredicate.INELIGIBLE_VENUE: ExclusionRule(
            predicate=ExclusionPredicate.INELIGIBLE_VENUE,
            article='QD 87 Dieu 3',
            grade=SourceGrade.VERIFIED,
            summary='outside the co phieu / chung chi quy niem yet universe; '
                    'the TT 120 Dieu 9.4 divergence over UPCoM is recorded on '
                    'MarginRegulation.eligible_venues',
            test=_test_ineligible_venue),
        ExclusionPredicate.LISTED_UNDER_SIX_MONTHS: ExclusionRule(
            predicate=ExclusionPredicate.LISTED_UNDER_SIX_MONTHS,
            article='QD 87 Dieu 3.1',
            grade=SourceGrade.VERIFIED,
            summary='listed under six months at the review date; on a venue '
                    'transfer the two exchanges listed times are summed',
            test=_test_listed_under_six_months),
        ExclusionPredicate.TRADING_STATUS: ExclusionRule(
            predicate=ExclusionPredicate.TRADING_STATUS,
            article='QD 87 Dieu 3.2',
            grade=SourceGrade.VERIFIED,
            summary='canh bao / kiem soat / kiem soat dac biet / tam ngung '
                    'giao dich / delisting queue. The mapping of the post-2020 '
                    'han che giao dich and dinh chi giao dich statuses onto '
                    'this enumeration is SILENT',
            test=_test_trading_status),
        ExclusionPredicate.QUALIFIED_AUDIT_OPINION: ExclusionRule(
            predicate=ExclusionPredicate.QUALIFIED_AUDIT_OPINION,
            article='QD 87 Dieu 3.3',
            grade=SourceGrade.VERIFIED,
            summary='latest audited annual or reviewed semi-annual FS carries '
                    'an opinion other than unqualified',
            test=_test_qualified_audit_opinion),
        ExclusionPredicate.LATE_FINANCIAL_STATEMENT: ExclusionRule(
            predicate=ExclusionPredicate.LATE_FINANCIAL_STATEMENT,
            article='QD 87 Dieu 3.4',
            grade=SourceGrade.VERIFIED,
            summary=f'more than {LATE_DISCLOSURE_BUSINESS_DAYS} business days '
                    f'late disclosing the audited annual or reviewed '
                    f'semi-annual FS, from the deadline or the end of any '
                    f'granted extension',
            test=_test_late_financial_statement),
        ExclusionPredicate.TAX_OR_PROSECUTION: ExclusionRule(
            predicate=ExclusionPredicate.TAX_OR_PROSECUTION,
            article='QD 87 Dieu 3.5 as amended by QD 1205 Dieu 1 '
                    '(eff. 2018-01-02)',
            grade=SourceGrade.VERIFIED,
            summary='tax evasion or fraud penalty, failure to comply with a '
                    'tax-enforcement decision, or a decision to prosecute. '
                    'QD 1205 NARROWED this, so the predicate answers '
                    'differently on either side of 2018-01-02',
            test=_test_tax_or_prosecution),
        ExclusionPredicate.LOSS_OR_ACCUMULATED_LOSS: ExclusionRule(
            predicate=ExclusionPredicate.LOSS_OR_ACCUMULATED_LOSS,
            article='QD 87 Dieu 3.6',
            grade=SourceGrade.VERIFIED,
            summary='loss in the period and/or accumulated loss, consolidated '
                    'for a parent; for a public fund, NAV per unit below par '
                    f'in at least one of the {FUND_NAV_LOOKBACK_MONTHS} '
                    f'consecutive months to the selection date',
            test=_test_loss_or_accumulated_loss),
    })


# --------------------------------------------------------------------------
# Spec 2.7 -- securities that fall off the list, where TWO TEXTS DISAGREE
# --------------------------------------------------------------------------

class IneligibleCollateralTreatment(str, Enum):
    """What happens to collateral that stops being margin-eligible.

    **The two texts do not match, and both are VERIFIED.** The spec sets this
    out at section 2.7 and instructs that the divergence be recorded rather than
    resolved in silence:

    * **QD 87 Dieu 10.2** -- no new lending against it; it may no longer count
      toward ``AB``; but it **remains security** for the existing loan unless
      otherwise agreed.
    * **TT 120 Dieu 9.6** -- *"Chung khoan khong duoc phep giao dich ky quy
      khong duoc tinh vao tai san bao dam khi xac dinh ty le ky quy ban dau va
      ty le ky quy duy tri"*: out of the collateral base for **both** ratios.

    **Where they actually differ.** Both stop new lending and both leave the
    paper pledged, so the operative difference is the **initial** ratio. TT 120
    names *ty le ky quy ban dau* explicitly; QD 87 Dieu 10.2 speaks only of
    ``AB``, which is the maintenance side. Reading the difference as
    *initial-ratio-only* is our characterisation of two texts that do not
    address each other, and it is declared in :data:`PROVENANCE` under
    ``ineligible_collateral_divergence``.

    **We default to TT 120 and say so.** It is the higher-ranking instrument, it
    is the spec's instruction, and it is the conservative reading: excluding
    collateral lowers ``PV``, hence ``EB`` and ``AB``, hence ``AB/EB``, so calls
    fire **sooner** under it than under QD 87 Dieu 10.2. A default that fired
    calls later would flatter every run.

    ``EXCLUDED_FROM_BOTH_RATIOS``
        **TT 120 Dieu 9.6. The default.** Out of the collateral base for the
        initial ratio and the maintenance ratio alike.
    ``RETAINED_AS_SECURITY``
        **QD 87 Dieu 10.2**, read narrowly. Out of ``AB`` for the maintenance
        ratio, still collateral when the initial ratio is determined, still
        pledged. Offered because a paper reporting *what QD 87 says* needs it,
        and because the divergence is real -- hiding half of it would be the
        overclaim this module exists to avoid.
    """

    EXCLUDED_FROM_BOTH_RATIOS = 'excluded_from_both_ratios'
    RETAINED_AS_SECURITY = 'retained_as_security'


#: The two texts, side by side, on every :class:`IneligibleCollateralRuling`.
#: A caller who prints a ruling gets both readings and which one was applied,
#: which is the whole of "do not pick one silently" in one string.
INELIGIBLE_COLLATERAL_DIVERGENCE = (
    'QD 87 Dieu 10.2 and TT 120 Dieu 9.6 DO NOT MATCH and both are VERIFIED. '
    'QD 87 Dieu 10.2: no new lending against it, it may no longer count toward '
    'AB, but it remains security for the existing loan unless otherwise agreed. '
    'TT 120 Dieu 9.6: excluded from the collateral base when determining BOTH '
    'the initial and the maintenance margin ratio. The operative difference is '
    'the INITIAL ratio. This module DEFAULTS TO TT 120 -- higher-ranking, and '
    'the conservative side, since excluding collateral lowers AB/EB and fires '
    'calls sooner -- and exposes QD 87 Dieu 10.2 as '
    'IneligibleCollateralTreatment.RETAINED_AS_SECURITY.')


@dataclass(frozen=True)
class IneligibleCollateralRuling:
    """What a ticker coming off the margin list does to an existing position.

    Returned by :func:`rule_on_ineligible_collateral`. Four booleans rather than
    one, because the two texts agree on three of them and differ on the fourth,
    and a single "eligible" flag would hide exactly the disagreement.

    Attributes:
        ticker: the security that came off the list.
        as_of: when.
        treatment: which text was applied.
        blocks_new_lending: **True under both texts.** No new margin lending
            against this security. QD 87 Dieu 10.2 says so directly; under
            TT 120 it follows from the paper being out of the initial-ratio
            collateral base.
        counts_toward_initial_ratio: **the point of disagreement.** ``False``
            under TT 120 Dieu 9.6, ``True`` under QD 87 Dieu 10.2 read
            narrowly.
        counts_toward_maintenance_ratio: **False under both texts** -- out of
            ``AB``.
        remains_pledged: **True under both texts.** It is still security for the
            existing loan unless otherwise agreed, so it is still there to be
            sold in a forced sale. Dropping it from the ratio is not releasing
            it, and an engine that conflated the two would hand collateral back
            to a client in breach.
        divergence: :data:`INELIGIBLE_COLLATERAL_DIVERGENCE`, carried on the
            record so a printed ruling is self-explaining.
    """

    ticker: str
    as_of: date
    treatment: IneligibleCollateralTreatment
    blocks_new_lending: bool
    counts_toward_initial_ratio: bool
    counts_toward_maintenance_ratio: bool
    remains_pledged: bool
    divergence: str = INELIGIBLE_COLLATERAL_DIVERGENCE

    @property
    def counts_toward_any_ratio(self) -> bool:
        """Whether this paper still enters a collateral base at all."""
        return (self.counts_toward_initial_ratio
                or self.counts_toward_maintenance_ratio)


def rule_on_ineligible_collateral(
        ticker: str,
        as_of: date,
        *,
        treatment: Optional[IneligibleCollateralTreatment] = None,
        policy: Optional['EligibilityPolicy'] = None,
) -> IneligibleCollateralRuling:
    """Spec 2.7: what a ticker falling off the list does to an open position.

    **The conservative reading is the default** and the other is one keyword
    away. See :class:`IneligibleCollateralTreatment` for the two texts, why they
    differ only on the initial ratio, and why TT 120 wins by default.

    **There is exactly one default, and it lives on the policy object.**
    ``treatment`` overrides it for a single call; leaving both unset resolves to
    :data:`DEFAULT_ELIGIBILITY_POLICY`. A second default hard-coded in this
    signature would let a caller configure
    :attr:`EligibilityPolicy.ineligible_collateral_treatment` and watch it be
    ignored -- an interpretive choice that silently does not apply is worse than
    one that was never offered.

    This is **not** the same question as
    :attr:`BrokerMarginTerms.ineligible_counted_as_collateral`, which is a
    *broker term* and is refused outright when set -- a firm claiming ineligible
    paper as collateral is looser than a read article. This function answers
    which of two **statutory texts** governs, which is a question about the law
    and not about a firm's contract. The two stay separate on purpose.
    """
    if treatment is None:
        resolved = (policy or DEFAULT_ELIGIBILITY_POLICY
                    ).ineligible_collateral_treatment
    else:
        resolved = treatment
    return IneligibleCollateralRuling(
        ticker=ticker,
        as_of=as_of,
        treatment=resolved,
        blocks_new_lending=True,
        counts_toward_initial_ratio=(
            resolved is IneligibleCollateralTreatment.RETAINED_AS_SECURITY),
        counts_toward_maintenance_ratio=False,
        remains_pledged=True,
    )


# --------------------------------------------------------------------------
# The policy object -- every unavoidable choice, in one place, defaulted
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class EligibilityPolicy:
    """The eligibility engine's own configuration. **Not law, and not terms.**

    A third object, deliberately. :class:`MarginRegulation` is what the law
    says; :class:`BrokerMarginTerms` is what one firm charges and requires.
    Neither is the right home for *"which of two conflicting statutory texts do
    we apply"* or *"what does a status nobody mapped mean"*. Putting an
    interpretive choice on the statutory object would dress it as law; putting
    it on the broker object would dress it as a commercial term. It is neither:
    it is **ours**, and it lives on its own object where :data:`PROVENANCE` can
    grade it.

    Every field here is a decision the spec left open, defaulted to the reading
    that invents least.

    Attributes:
        rules: the predicate table. Defaults to
            :data:`STATUTORY_EXCLUSION_RULES`. **A predicate the regulation
            lists and this table does not implement is reported unevaluated,
            never passed** -- so handing in a subset narrows what can be
            decided; it does not widen what is eligible.
        unmapped_status_policy: what a post-2020 trading status means. SILENT
            item 8. Defaults to :attr:`UnmappedStatusPolicy.INDETERMINATE`.
        ineligible_collateral_treatment: which of the two section-2.7 texts
            governs paper that falls off the list. Defaults to TT 120 Dieu 9.6.
        assume_domestic_investor: **the standing scope cut of this iteration.**
            With it set, an unstated nationality resolves to *domestic* and the
            assumption is written into :attr:`InvestorEligibility.note` on every
            assessment that relies on it. Clear it and an unstated nationality
            becomes INDETERMINATE like every other unstated fact. Defaults to
            ``True`` because the alternative makes every fact-light assessment
            undecidable, and because the foreign limb is still **enforced**
            whenever nationality *is* stated -- what is cut is the modelling of
            foreign investors, not the prohibition.
        bar_authorised_traders: whether an account operated by an authorised or
            proxy trader may register margin. **Not statute** -- an ACBS FAQ
            item, REPORTED, and a broker term. Defaults to ``False`` so a
            statutory run does not silently carry one firm's house rule.
        note: free text, for a caller recording why they configured it this
            way.
    """

    rules: Mapping[ExclusionPredicate, ExclusionRule] = STATUTORY_EXCLUSION_RULES
    unmapped_status_policy: UnmappedStatusPolicy = \
        UnmappedStatusPolicy.INDETERMINATE
    ineligible_collateral_treatment: IneligibleCollateralTreatment = \
        IneligibleCollateralTreatment.EXCLUDED_FROM_BOTH_RATIOS
    assume_domestic_investor: bool = True
    bar_authorised_traders: bool = False
    note: Optional[str] = None

    def __post_init__(self) -> None:
        for key, rule in self.rules.items():
            if rule.predicate is not key:
                raise ValueError(
                    f'rules[{key.value!r}] implements '
                    f'{rule.predicate.value!r}. The table is keyed by the '
                    f'predicate each rule decides, and a mismatch would report '
                    f'a security excluded under an article that says nothing '
                    f'about it')

    def rule_for(self, predicate: ExclusionPredicate) -> Optional[ExclusionRule]:
        """The rule implementing ``predicate``, or ``None`` if unimplemented."""
        return self.rules.get(predicate)


#: The policy every assessor uses when the caller supplies none: TT 120 on the
#: section-2.7 divergence, INDETERMINATE on the unmapped statuses, the domestic
#: scope cut in force, and no house rule borrowed from any broker.
DEFAULT_ELIGIBILITY_POLICY = EligibilityPolicy()


# --------------------------------------------------------------------------
# Spec 2.6 -- the assessor for one security
# --------------------------------------------------------------------------

#: Written onto :attr:`SecurityEligibility.note` when every statutory predicate
#: passes and the firm simply does not carry the ticker. It is a **commercial**
#: refusal, not a rule breach, which is why ``failed`` stays empty.
_NOT_ON_BROKER_LIST_NOTE = (
    'passes every QD 87 Dieu 3 predicate but is not on this CTCK positive '
    'list. That is a COMMERCIAL decision under Dieu 4.2, not a statutory '
    'exclusion, which is why failed is empty and on_broker_list is False')

#: Written when no positive list was supplied at all.
_NO_BROKER_LIST_NOTE = (
    'no CTCK positive list was supplied. QD 87 Dieu 4.2 makes the firm list a '
    'published document and this module ships none, so its absence is '
    'INDETERMINATE and never an implicit yes')


def assess_security(
    facts: SecurityFacts,
    *,
    regulation: MarginRegulation = QD_87_2017,
    policy: EligibilityPolicy = DEFAULT_ELIGIBILITY_POLICY,
    exchange_list: Optional[ExchangeMarginList] = None,
    broker_list: Optional[BrokerMarginList] = None,
    terms: Optional[BrokerMarginTerms] = None,
) -> SecurityEligibility:
    """Spec 2.6: may this security be margined, and which layer decided?

    **The two-layer negative -> positive list, in order.**

    1. **Layer 1, the exchange's negative list** (Dieu 4.1). Where
       ``exchange_list`` names the ticker, its published reasons go straight
       into ``failed``. A snapshot that names a ticker with no machine-readable
       reason still excludes it.
    2. **Layer 1 again, from first principles.** Every predicate in
       ``policy.rules`` is evaluated against ``facts`` **independently of the
       published list**, and anything that holds joins ``failed``. This is the
       statutory layer enforced *on top of* whatever the caller supplied, which
       is the whole point: we cannot know a broker's universe, so we check the
       law ourselves rather than trusting a list to be complete.
    3. **Layer 2, the firm's positive list** (Dieu 4.2). Reported through
       ``on_broker_list``.

    **Precedence, and it is one-directional.** A predicate that positively holds
    beats a broker list that still carries the ticker -- a firm cannot lend
    against paper the exchange has excluded, and the answer is INELIGIBLE with
    the article named. The reverse never happens: a firm that declines to lend
    against perfectly eligible paper is exercising a commercial choice, so the
    answer is still INELIGIBLE but ``failed`` stays empty and
    :attr:`SecurityEligibility.note` says which kind of refusal it was.

    **Unevaluated beats eligible, never the reverse.** With no positive
    predicate, an unevaluable one makes the answer INDETERMINATE -- including
    when a predicate the regulation lists has no rule in ``policy.rules`` at
    all.

    Args:
        facts: what is known about the security. ``None`` fields are *not
            known*; see :class:`SecurityFacts`.
        regulation: the dated statutory row. Supplies the venue universe, the
            listing window and the predicate list.
        policy: the interpretive choices. See :class:`EligibilityPolicy`.
        exchange_list: the Dieu 4.1 snapshot, if the caller has one.
        broker_list: the Dieu 4.2 positive list, if the caller has one. Its
            absence is INDETERMINATE, not a yes.
        terms: read only for :attr:`BrokerMarginTerms.loan_ratio_by_ticker`, as
            a fallback when the positive list published no *ty le cho vay*.

    Returns:
        A :class:`SecurityEligibility`. ``failed`` carries statutory
        exclusions, ``unevaluated`` carries predicates the facts could not
        decide, and ``on_broker_list`` carries the commercial layer.

    Raises:
        ValueError: when ``exchange_list`` is a single-venue snapshot for a
            different venue than the security trades on, or when it was
            published after the review date. Both are mismatched inputs rather
            than eligibility answers, and answering either would be worse than
            refusing.
    """
    if exchange_list is not None:
        if exchange_list.published_on > facts.as_of:
            raise ValueError(
                f'exchange_list was published '
                f'{exchange_list.published_on.isoformat()}, after the review '
                f'date {facts.as_of.isoformat()}. Eligibility is dated; a '
                f'snapshot from the future is a caller mistake, not an answer')
        if (exchange_list.venue is not None and facts.venue is not None
                and exchange_list.venue is not facts.venue):
            raise ValueError(
                f'exchange_list covers {exchange_list.venue.value} and '
                f'{facts.ticker} trades on {facts.venue.value}. QD 87 Dieu 4.1 '
                f'makes each exchange publish its own list; consulting one '
                f'venue snapshot about another venue proves nothing either way')

    failed: List[ExclusionPredicate] = []
    unevaluated: List[ExclusionPredicate] = []
    notes: List[str] = []

    # Named on the Dieu 4.1 snapshot at all. Tracked apart from ``failed``
    # because the exchange may name a ticker without a machine-readable reason
    # -- HOSE publishes them in prose -- and the ticker is ineligible either
    # way. Deriving ineligibility from a non-empty ``failed`` alone would let a
    # reason nobody could parse turn a published exclusion into a clean bill.
    named_on_exchange_list = False
    published: Tuple[ExclusionPredicate, ...] = ()
    if exchange_list is not None and exchange_list.names(facts.ticker):
        named_on_exchange_list = True
        published = exchange_list.reasons(facts.ticker)
        failed.extend(published)
        if not published:
            notes.append(
                f'named on the exchange ineligible list published '
                f'{exchange_list.published_on.isoformat()} with no '
                f'machine-readable reason; still ineligible under QD 87 '
                f'Dieu 4.1')
    elif exchange_list is not None and not exchange_list.covers_venue_universe:
        notes.append(
            'the exchange list supplied is a PARTIAL extract, so absence from '
            'it establishes nothing. QD 87 Dieu 4.1 requires a full snapshot; '
            'only a full one makes an absence informative')

    for predicate in regulation.exclusion_predicates:
        if predicate in failed:
            continue
        rule = policy.rule_for(predicate)
        if rule is None:
            unevaluated.append(predicate)
            notes.append(
                f'{predicate.value} has no rule in the supplied table, so it '
                f'was not decided. An unimplemented predicate is unevaluated, '
                f'never passed')
            continue
        answer = rule(facts, regulation, policy)
        if answer is True:
            failed.append(predicate)
        elif answer is None:
            unevaluated.append(predicate)

    if (ExclusionPredicate.TRADING_STATUS in unevaluated
            and facts.trading_statuses is not None
            and set(facts.trading_statuses) & UNMAPPED_TRADING_STATUSES):
        notes.append(
            'carries a post-2020 trading status (han che giao dich / dinh chi '
            'giao dich) that QD 87 Dieu 3.2 does not enumerate. The mapping is '
            'SILENT and this run left it undecided; set '
            'EligibilityPolicy.unmapped_status_policy to resolve it')

    on_broker_list: Optional[bool] = None
    loan_ratio: Optional[Decimal] = None
    if broker_list is not None:
        if not broker_list.is_in_force(facts.as_of):
            notes.append(
                f'the CTCK positive list takes effect '
                f'{(broker_list.effective_from or broker_list.published_on).isoformat()}, '
                f'after the review date {facts.as_of.isoformat()}. QD 87 '
                f'Dieu 4.2 binds from publication, so it is not applied early')
        else:
            on_broker_list = broker_list.carries(facts.ticker)
            loan_ratio = broker_list.loan_ratio(facts.ticker)
            if (exchange_list is not None
                    and broker_list.published_on < exchange_list.published_on):
                notes.append(
                    f'the CTCK list ({broker_list.published_on.isoformat()}) '
                    f'predates the exchange snapshot '
                    f'({exchange_list.published_on.isoformat()}); QD 87 '
                    f'Dieu 4.2 gives the firm 2 business days to republish. '
                    f'The statutory layer is enforced on top regardless')
    if loan_ratio is None and terms is not None:
        loan_ratio = terms.loan_ratio_by_ticker.get(facts.ticker)

    if failed or named_on_exchange_list:
        result = MarginEligibility.INELIGIBLE
    elif unevaluated:
        result = MarginEligibility.INDETERMINATE
    elif on_broker_list is None:
        result = MarginEligibility.INDETERMINATE
        notes.append(_NO_BROKER_LIST_NOTE)
    elif on_broker_list is False:
        result = MarginEligibility.INELIGIBLE
        notes.append(_NOT_ON_BROKER_LIST_NOTE)
    else:
        result = MarginEligibility.ELIGIBLE

    if facts.note:
        notes.append(facts.note)

    return SecurityEligibility(
        ticker=facts.ticker,
        as_of=facts.as_of,
        result=result,
        venue=facts.venue,
        failed=tuple(failed),
        unevaluated=tuple(unevaluated),
        on_broker_list=on_broker_list,
        loan_ratio=loan_ratio,
        note='; '.join(notes) if notes else None,
    )


# --------------------------------------------------------------------------
# Spec 2.5 -- the assessor for one investor
# --------------------------------------------------------------------------

#: Written onto :attr:`InvestorEligibility.note` whenever the scope cut, rather
#: than a stated fact, decided nationality.
DOMESTIC_INVESTOR_ASSUMPTION_NOTE = (
    'nationality was NOT stated and this iteration ASSUMES A DOMESTIC '
    'INVESTOR (EligibilityPolicy.assume_domestic_investor). TT 120 Dieu 9.2 '
    'bars foreign investors from margin lending flatly, and that bar IS '
    'enforced whenever nationality is stated -- what is cut here is the '
    'modelling of foreign investors, not the prohibition. Do not read a '
    'refusal under this limb as "foreigners cannot buy on credit": TT 120 '
    'Dieu 9a is a separate non-prefunded regime for foreign institutions, out '
    'of scope, and not ky quy')


def assess_investor(
    facts: InvestorFacts,
    *,
    regulation: MarginRegulation = QD_87_2017,
    policy: EligibilityPolicy = DEFAULT_ELIGIBILITY_POLICY,
) -> InvestorEligibility:
    """Spec 2.5: may this investor hold a margin account at this CTCK?

    **Four independent statutory tests, kept apart because they fail for
    different reasons.**

    * **The contract** -- TT 120 Dieu 9.1 / QD 87 Dieu 12.1. The *hop dong giao
      dich ky quy* **is** the credit agreement. Without one there is nothing to
      discuss, and an unstated one is undecidable rather than assumed.
    * **The person** -- QD 87 Dieu 13.4, through
      :attr:`MarginRegulation.ineligible_account_holders`: the CTCK's insiders
      and their related persons, entities in dissolution or bankruptcy, parties
      in breach of the margin contract. TT 121/2020 Dieu 27.3 independently
      bars lending to the insider class in any form.
    * **Nationality** -- TT 120 Dieu 9.2, a flat prohibition, enforced whenever
      stated. Unstated, it falls to the scope cut; see
      :data:`DOMESTIC_INVESTOR_ASSUMPTION_NOTE`.
    * **The account architecture** -- TT 120 Dieu 9.3: one margin account per
      investor per CTCK, segregated from the ordinary account and across
      investors. Stated ``False`` (or a stated second account) bars it;
      **unstated is not a bar**, which is our choice and is declared in
      :data:`PROVENANCE` under ``unasserted_account_architecture``.

    A holder class the caller could not check reaches ``unevaluated`` --
    ``RELATED_PERSON`` is the standing case, because it needs a relationship
    graph no corpus here carries -- and with nothing positively failing, that
    makes the answer INDETERMINATE.

    **One non-statutory option.** ACBS's FAQ says an authorised or proxy trader
    may not register margin on the owner's behalf. That is REPORTED and a broker
    term, so it bars only under
    :attr:`EligibilityPolicy.bar_authorised_traders`, off by default, and it is
    reported through the note rather than as a Dieu 13.4 class -- it is not one.
    """
    failed: List[IneligibleAccountHolder] = []
    unevaluated: List[IneligibleAccountHolder] = []
    notes: List[str] = []
    barred_outside_holder_classes = False
    undecidable_outside_holder_classes = False

    statutory = set(regulation.ineligible_account_holders)
    for holder_class in facts.holder_classes:
        if holder_class in statutory and holder_class not in failed:
            failed.append(holder_class)
    for holder_class in facts.unknown_holder_classes:
        if holder_class in statutory and holder_class not in unevaluated:
            unevaluated.append(holder_class)

    if regulation.margin_contract_required:
        if facts.has_margin_contract is False:
            barred_outside_holder_classes = True
            notes.append(
                'no hop dong giao dich ky quy. TT 120 Dieu 9.1 / QD 87 '
                'Dieu 12.1 make that contract the credit agreement itself, so '
                'there is no margin lending without it')
        elif facts.has_margin_contract is None:
            undecidable_outside_holder_classes = True
            notes.append(
                'whether a hop dong giao dich ky quy exists was not stated. '
                'TT 120 Dieu 9.1 requires one and this module will not assume '
                'a credit agreement into existence')

    if not regulation.foreign_investors_allowed:
        if facts.is_foreign_investor is True:
            if IneligibleAccountHolder.FOREIGN_INVESTOR in statutory:
                if IneligibleAccountHolder.FOREIGN_INVESTOR not in failed:
                    failed.append(IneligibleAccountHolder.FOREIGN_INVESTOR)
            else:
                barred_outside_holder_classes = True
            notes.append(
                'foreign investor. TT 120 Dieu 9.2 and QD 87 Dieu 10.1(dd) bar '
                'margin lending flatly. This is NOT a bar on buying with '
                'broker credit -- TT 120 Dieu 9a is a separate regime for '
                'foreign institutions and is out of scope here')
        elif facts.is_foreign_investor is None:
            if policy.assume_domestic_investor:
                notes.append(DOMESTIC_INVESTOR_ASSUMPTION_NOTE)
            elif IneligibleAccountHolder.FOREIGN_INVESTOR in statutory:
                if IneligibleAccountHolder.FOREIGN_INVESTOR not in unevaluated:
                    unevaluated.append(IneligibleAccountHolder.FOREIGN_INVESTOR)
            else:
                undecidable_outside_holder_classes = True

    if (regulation.segregated_margin_account_required
            and facts.margin_account_is_segregated is False):
        barred_outside_holder_classes = True
        notes.append(
            'the margin account is not segregated. TT 120 Dieu 9.3 / QD 87 '
            'Dieu 13.5(a) require it to be separate from the ordinary account '
            'and from every other investor')
    if facts.has_other_margin_account_at_ctck is True:
        barred_outside_holder_classes = True
        notes.append(
            'this investor already holds a margin account at this CTCK. '
            'TT 120 Dieu 9.3 allows one per investor per firm')

    if policy.bar_authorised_traders and facts.trades_through_authorised_person:
        barred_outside_holder_classes = True
        notes.append(
            'operated by an authorised or proxy trader, barred by '
            'EligibilityPolicy.bar_authorised_traders. NOT STATUTE -- an ACBS '
            'FAQ item, REPORTED, and a broker term; it is off by default and '
            'is not a QD 87 Dieu 13.4 class')

    if failed or barred_outside_holder_classes:
        result = MarginEligibility.INELIGIBLE
    elif unevaluated or undecidable_outside_holder_classes:
        result = MarginEligibility.INDETERMINATE
    else:
        result = MarginEligibility.ELIGIBLE

    if facts.note:
        notes.append(facts.note)

    return InvestorEligibility(
        account_id=facts.account_id,
        as_of=facts.as_of,
        result=result,
        failed=tuple(failed),
        unevaluated=tuple(unevaluated),
        has_margin_contract=facts.has_margin_contract is True,
        note='; '.join(notes) if notes else None,
    )


# --------------------------------------------------------------------------
# Spec 2.11 -- prohibited collateral, QD 87 Dieu 10.1(a)-(e)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CollateralAssessment:
    """Whether the CTCK may lend against this paper for this client.

    **A different question from :class:`SecurityEligibility`**, and the spec
    keeps them apart: Dieu 3 asks whether the *market* permits margin on a
    security, Dieu 10.1 asks whether **this firm** may lend against it **to this
    client**. Three of the six limbs do not look at the security at all, and the
    same ticker is prohibited collateral at one CTCK and ordinary collateral at
    the next.

    Attributes:
        ticker: the paper offered as collateral or bought on margin.
        account_id: the client.
        as_of: the date assessed.
        result: :attr:`MarginEligibility.ELIGIBLE` only when every limb was
            checked and none holds.
        prohibited: which :class:`ProhibitedCollateral` limbs hold.
        unevaluated: limbs the facts could not decide. Non-empty with nothing
            prohibited is the INDETERMINATE case.
        note: why, in prose, including the standing domestic-investor scope
            cut where it was relied on.
    """

    ticker: str
    account_id: str
    as_of: date
    result: MarginEligibility
    prohibited: Tuple[ProhibitedCollateral, ...] = ()
    unevaluated: Tuple[ProhibitedCollateral, ...] = ()
    note: Optional[str] = None

    @property
    def may_lend(self) -> bool:
        """Whether lending is permitted. **INDETERMINATE is not permission.**"""
        return self.result is MarginEligibility.ELIGIBLE


def assess_collateral(
    relationship: CollateralRelationship,
    investor: InvestorEligibility,
    *,
    account_meets_required_ratio: Optional[bool] = None,
    regulation: MarginRegulation = QD_87_2017,
    policy: EligibilityPolicy = DEFAULT_ELIGIBILITY_POLICY,
) -> CollateralAssessment:
    """Spec 2.11: QD 87 Dieu 10.1(a)-(e), all six limbs. VERIFIED.

    * **(a) SELF_UNDERWRITTEN** -- paper this CTCK firm-underwrote, from signing
      the underwriting contract until
      :attr:`MarginRegulation.underwriting_lockout_months` **after the offering
      completes**. An offering that has not completed leaves the window open, so
      the paper is prohibited: determinate, not unknown.
    * **(b) AFFILIATED_ISSUER** -- a listed company owning at least
      :attr:`MarginRegulation.affiliate_ownership_threshold` of the CTCK's
      charter capital, or a listed or registered-for-trading company the CTCK
      owns that much of. Both limbs, either direction.
    * **(c) OWN_SHARES** -- the CTCK's own shares.
    * **(d) CLIENT_BELOW_REQUIRED_RATIO** -- the client is not meeting the
      contractual or regulatory margin ratio. **A lending prohibition, not a
      call**: an account in breach may not borrow more whether or not a call has
      issued. Passed in rather than computed, because the ratio is the account
      algebra's answer and this function is about the relationship.
    * **(dd) FOREIGN_INVESTOR** and **(e) INELIGIBLE_ACCOUNT_HOLDER** -- read
      off ``investor``, so the two assessments compose instead of asking the
      caller for the same facts twice. An investor limb that was *unevaluated*
      there is unevaluated here.

    Every limb the regulation lists is visited; a limb whose facts are missing
    lands in ``unevaluated``, and with nothing prohibited the answer is
    INDETERMINATE. There is no path from missing facts to ``may_lend``.
    """
    prohibited: List[ProhibitedCollateral] = []
    unevaluated: List[ProhibitedCollateral] = []
    notes: List[str] = []
    limbs = set(regulation.prohibited_collateral)

    def record(limb: ProhibitedCollateral, answer: Optional[bool],
               why: str) -> None:
        if limb not in limbs:
            return
        if answer is True:
            prohibited.append(limb)
            notes.append(why)
        elif answer is None:
            unevaluated.append(limb)

    if relationship.self_underwritten is None:
        underwriting: Optional[bool] = None
    elif relationship.self_underwritten is False:
        underwriting = False
    elif relationship.offering_completed_on is None:
        underwriting = True
        notes.append(
            'firm-underwritten by this CTCK and the offering has not '
            'completed, so QD 87 Dieu 10.1(a) lockout has not begun to run')
    else:
        lockout_ends = _add_months(relationship.offering_completed_on,
                                   regulation.underwriting_lockout_months)
        underwriting = relationship.as_of <= lockout_ends
        if underwriting:
            notes.append(
                f'firm-underwritten; QD 87 Dieu 10.1(a) lockout runs to '
                f'{lockout_ends.isoformat()}')
    record(ProhibitedCollateral.SELF_UNDERWRITTEN, underwriting,
           'QD 87 Dieu 10.1(a)')

    threshold = regulation.affiliate_ownership_threshold
    stakes = (relationship.issuer_stake_in_ctck,
              relationship.ctck_stake_in_issuer)
    affiliated = _any_true_else_unknown(
        *(None if s is None else s >= threshold for s in stakes))
    record(ProhibitedCollateral.AFFILIATED_ISSUER, affiliated,
           f'QD 87 Dieu 10.1(b): an ownership stake at or above {threshold} '
           f'in either direction between this CTCK and the issuer')

    record(ProhibitedCollateral.OWN_SHARES, relationship.is_own_share,
           "QD 87 Dieu 10.1(c): the CTCK's own shares")

    below_ratio = (None if account_meets_required_ratio is None
                   else not account_meets_required_ratio)
    record(ProhibitedCollateral.CLIENT_BELOW_REQUIRED_RATIO, below_ratio,
           'QD 87 Dieu 10.1(d): the client is not meeting the contractual or '
           'regulatory margin ratio, so no further lending -- independently of '
           'whether a margin call has issued')

    foreign_failed = (
        IneligibleAccountHolder.FOREIGN_INVESTOR in investor.failed)
    foreign_unknown = (
        IneligibleAccountHolder.FOREIGN_INVESTOR in investor.unevaluated)
    record(ProhibitedCollateral.FOREIGN_INVESTOR,
           True if foreign_failed else (None if foreign_unknown else False),
           'QD 87 Dieu 10.1(dd) / TT 120 Dieu 9.2: foreign investor. Read the '
           'Dieu 9a warning before reading this as "no foreign credit"')

    other_failed = [c for c in investor.failed
                    if c is not IneligibleAccountHolder.FOREIGN_INVESTOR]
    other_unknown = [c for c in investor.unevaluated
                     if c is not IneligibleAccountHolder.FOREIGN_INVESTOR]
    record(ProhibitedCollateral.INELIGIBLE_ACCOUNT_HOLDER,
           True if other_failed else (None if other_unknown else False),
           'QD 87 Dieu 10.1(e): the holder is one of the Dieu 13.4 persons -- '
           + ', '.join(c.value for c in other_failed))

    if (investor.note
            and DOMESTIC_INVESTOR_ASSUMPTION_NOTE in investor.note):
        notes.append(DOMESTIC_INVESTOR_ASSUMPTION_NOTE)

    if prohibited:
        result = MarginEligibility.INELIGIBLE
    elif unevaluated:
        result = MarginEligibility.INDETERMINATE
    else:
        result = MarginEligibility.ELIGIBLE

    if relationship.note:
        notes.append(relationship.note)

    return CollateralAssessment(
        ticker=relationship.ticker,
        account_id=investor.account_id,
        as_of=relationship.as_of,
        result=result,
        prohibited=tuple(prohibited),
        unevaluated=tuple(unevaluated),
        note='; '.join(notes) if notes else None,
    )


# --------------------------------------------------------------------------
# What the eligibility layer decided for itself
# --------------------------------------------------------------------------

#: The eligibility layer's own choices and gaps, in the same shape as
#: :data:`PROVENANCE` and folded into it immediately below.
#:
#: Two of these restate spec section 4 items from this section's point of view
#: (the post-2020 status mapping, the UPCoM universe); the rest are decisions
#: this section had to make because the assessment is not evaluable without
#: them. Every one is graded, and none is graded VERIFIED -- a choice we made is
#: never a clause someone read.
ELIGIBILITY_PROVENANCE: Mapping[str, Provenance] = MappingProxyType({
    'ineligible_collateral_divergence': _p(
        'QD 87 Dieu 10.2 vs TT 120 Dieu 9.6', _D,
        'SPEC 2.7, TWO TEXTS THAT DO NOT MATCH, both VERIFIED. QD 87 Dieu 10.2: '
        'no new lending, no longer counts toward AB, but REMAINS SECURITY for '
        'the existing loan unless otherwise agreed. TT 120 Dieu 9.6: excluded '
        'from the collateral base when determining BOTH the initial and the '
        'maintenance ratio. What is DERIVED is the characterisation that they '
        'differ ONLY on the INITIAL ratio -- neither text addresses the other, '
        'and that reading is ours. The default is TT 120: higher-ranking, the '
        "spec's instruction, and the conservative side, since excluding "
        'collateral lowers AB/EB and fires calls SOONER. QD 87 Dieu 10.2 is '
        'reachable as IneligibleCollateralTreatment.RETAINED_AS_SECURITY and '
        'the divergence is printed on every ruling'),
    'unmapped_trading_status_default': _p(
        'QD 87 Dieu 3.2', _S,
        'SILENT item 8, from the assessor side. A security carrying ONLY a '
        'post-2020 status -- han che giao dich, dinh chi giao dich -- is '
        'reported INDETERMINATE by default, which is OUR CHOICE and the only '
        'answer that neither invents a mapping nor lets an excluded security '
        'read as eligible. UnmappedStatusPolicy.EXCLUDE follows observed HOSE '
        'practice (REPORTED, three tickers) and .IGNORE reads Dieu 3.2 '
        'literally. Nothing here encodes a mapping as gazetted'),
    'domestic_investor_scope_cut': _p(
        'TT 120 Dieu 9.2 / QD 87 Dieu 10.1(dd)', _D,
        'THE STANDING SCOPE CUT OF THIS ITERATION: an investor whose '
        'nationality is NOT stated is assumed DOMESTIC '
        '(EligibilityPolicy.assume_domestic_investor, default True), and the '
        'assumption is written onto InvestorEligibility.note every time it is '
        'relied on. The flat foreign prohibition IS enforced whenever '
        'nationality is stated -- what is cut is the MODELLING of foreign '
        'investors, not the bar. Clearing the flag makes an unstated '
        'nationality INDETERMINATE like every other unstated fact. Separately, '
        'and load-bearing: a refusal under this limb must NOT be read as '
        '"foreigners cannot buy on credit" -- TT 120 Dieu 9a is a separate '
        'non-prefunded regime for foreign INSTITUTIONS, adjacent, out of scope '
        'and not ky quy'),
    'no_broker_list_is_indeterminate': _p(
        'QD 87 Dieu 4.2', _D,
        'A CTCK positive list is a PUBLISHED document and this module ships '
        'none. Its absence is therefore INDETERMINATE and never an implicit '
        'yes -- our choice, and the one the spec asks for when it says a '
        'security whose predicates cannot be evaluated is not eligible by '
        'default. A ticker that IS on a supplied list but fails a statutory '
        'predicate is INELIGIBLE: the statutory layer is enforced ON TOP of '
        'the supplied data, never replaced by it'),
    'broker_list_absence_is_commercial': _p(
        'QD 87 Dieu 4.2', _D,
        'A ticker that passes every Dieu 3 predicate and is simply not on the '
        "firm's positive list is reported INELIGIBLE with an EMPTY failed "
        'tuple and on_broker_list=False. That split is ours: the firm declining '
        'to lend is a COMMERCIAL decision under Dieu 4.2, not a rule breach, '
        'and putting it in failed would make a business choice look like a '
        'statutory exclusion in every report that counts them'),
    'venue_transfer_summation': _p(
        'QD 87 Dieu 3.1', _D,
        'Dieu 3.1 says that on a venue transfer the two exchanges listed times '
        'are SUMMED and says nothing more. Implemented by shifting '
        'first_trading_day back by SecurityFacts.prior_venue_listed_days, which '
        'is exact when the two listings abut and generous by the gap when they '
        'do not. Ours'),
    'month_arithmetic': _p(
        'QD 87 Dieu 3.1, 4.1, 10.1(a)', _D,
        'Every eligibility window is stated in MONTHS and no text says what the '
        'anniversary of the 31st is in a 30-day month. The shared _add_months '
        'clamps to the last day of the target month -- OUR CHOICE, and it keeps '
        'a minimum window from spilling into the following month, so a security '
        'is admitted no later than the plain reading would admit it. Distinct '
        'from MAX_DAYS_IN_MONTH, which is a config-time necessary condition on '
        'loan TERMS and is not used here'),
    'unasserted_account_architecture': _p(
        'TT 120 Dieu 9.3 / QD 87 Dieu 13.5(a)', _D,
        'Segregation and the one-account-per-CTCK rule are duties on the '
        "FIRM's account architecture, not properties of the investor, and in a "
        'simulator we build that architecture ourselves. So an UNSTATED '
        'margin_account_is_segregated or has_other_margin_account_at_ctck is '
        'NOT a bar, while a stated breach of either is. Ours, and the one place '
        'in this section where an unstated fact does not force INDETERMINATE'),
    'authorised_trader_is_a_broker_term': _p(
        None, _R,
        'ACBS says an authorised or proxy trader may not register margin on the '
        "owner's behalf. REPORTED, from one firm's FAQ, and a BROKER TERM -- no "
        'article says it. Offered as EligibilityPolicy.bar_authorised_traders, '
        'OFF by default so a statutory run does not silently carry one house '
        "rule, and reported through the note rather than as a Dieu 13.4 class, "
        'because it is not one'),
    'self_underwriting_window_open': _p(
        'QD 87 Dieu 10.1(a)', _D,
        'The lockout runs from signing the underwriting contract until 6 months '
        'AFTER the offering completes. Where the paper is known to be '
        'self-underwritten but no completion date is stated, we treat the window '
        'as still OPEN and the collateral as PROHIBITED -- determinate, not '
        'unknown. Ours, and the conservative side: an offering nobody has '
        'recorded as complete is more likely incomplete than silently finished'),
    'eligibility_constants_undated': _p(
        'QD 87 Dieu 3.4, 3.6, and QD 1205 Dieu 1', _D,
        'LATE_DISCLOSURE_BUSINESS_DAYS = 5, FUND_NAV_LOOKBACK_MONTHS = 3 and '
        'QD_1205_EFFECTIVE_FROM = 2018-01-02 are STATUTORY numbers sitting at '
        'MODULE level rather than on the dated MarginRegulation row where they '
        'belong. That is a structural compromise, not a claim about the law: '
        'this stage is additive to an object that already shipped and '
        'MARGIN_REGULATIONS carries a single QD 87 row spanning the QD 1205 '
        'amendment. The QD 1205 narrowing IS implemented as a dated rule change '
        '-- as a date test inside the predicate -- so the same facts answer '
        'differently either side of 2018-01-02. Promote all three when the '
        'series next gains a row'),
    'predicate_table_is_the_universe': _p(
        'QD 87 Dieu 3', _D,
        'The seven exclusion predicates are DATA -- STATUTORY_EXCLUSION_RULES, '
        'swappable through EligibilityPolicy.rules -- and not branches, so the '
        'margin universe is supplied rather than compiled in. The consequence '
        'is ours and is enforced: a predicate the regulation LISTS and the '
        'supplied table does NOT implement is reported UNEVALUATED, never '
        'passed. Handing in a subset narrows what can be decided; it never '
        'widens what is eligible'),
})

# The eligibility layer's provenance is folded into the module table rather than
# left beside it, so a caller still has ONE place to read before quoting a
# value. The merge is additive -- the key sets are disjoint, which is asserted
# by test -- and it rebinds the name rather than editing the literal above,
# because the two tables were written at different stages.
PROVENANCE = MappingProxyType({**PROVENANCE, **ELIGIBILITY_PROVENANCE})

__all__.extend([
    # -------- eligibility (spec 2.5, 2.6, 2.7, 2.11) --------
    # statutory numbers this stage carries at module level
    'LATE_DISCLOSURE_BUSINESS_DAYS', 'FUND_NAV_LOOKBACK_MONTHS',
    'QD_1205_EFFECTIVE_FROM',
    # observable facts
    'TradingStatus', 'STATUTORY_TRADING_STATUSES', 'UNMAPPED_TRADING_STATUSES',
    'AuditOpinion', 'SecurityKind',
    'SecurityFacts', 'InvestorFacts', 'CollateralRelationship',
    # the two published lists, and the relist cadence
    'ExchangeMarginList', 'BrokerMarginList', 'earliest_relist_date',
    # the predicates, as data
    'PredicateAnswer', 'PredicateTest', 'ExclusionRule',
    'STATUTORY_EXCLUSION_RULES',
    # spec 2.7 -- the two texts that do not match
    'IneligibleCollateralTreatment', 'IneligibleCollateralRuling',
    'INELIGIBLE_COLLATERAL_DIVERGENCE', 'rule_on_ineligible_collateral',
    # our own choices, in one object
    'UnmappedStatusPolicy', 'EligibilityPolicy', 'DEFAULT_ELIGIBILITY_POLICY',
    'DOMESTIC_INVESTOR_ASSUMPTION_NOTE',
    # the assessors
    'assess_security', 'assess_investor', 'assess_collateral',
    'CollateralAssessment',
    # provenance
    'ELIGIBILITY_PROVENANCE',
])
