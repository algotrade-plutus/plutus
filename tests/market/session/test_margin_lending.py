"""The two things this stage can actually be wrong about.

``margin_lending.py`` is a type contract with no engine, so there is no ratio to
check and no call to fire. What it *does* assert, and can therefore get wrong,
is exactly two things:

1. **The validation relationship.** A :class:`BrokerMarginTerms` may be
   stricter than :class:`MarginRegulation` and never looser. Every test below
   that constructs a bad object also checks the *message* names the article, so
   a refusal that stops teaching which law was breached fails here.
2. **PROVENANCE completeness.** Every field of both config objects has an entry;
   every entry names a field; every value that the spec grades DERIVED or SILENT
   is graded that way here. Overclaiming is the defect this module is most
   exposed to, and the only way to catch it automatically is to make the grades
   data.

Nothing else is tested, because nothing else exists yet.
"""

from dataclasses import MISSING, fields
from datetime import date
from decimal import Decimal

import pytest

from plutus.market.session.margin_lending import (
    PROVENANCE, QD_87_2017, AccountingUnit, BrokerMarginTerms,
    BrokerTermLooserThanLaw, CollateralValuationCap, DayCount, ExclusionPredicate,
    FirmLendingLimit, ForcedSalePrice, ForcedSaleScope, InterestTier,
    LiquidationOrder, MarginRegulation, PriceSource, ProceedsComponent,
    Provenance, RatioDetermination, SourceGrade, UnresolvedMarginRegulation,
    regulation_in_force)
from plutus.market.session.types import Venue

D = Decimal

#: The six fields the spec refuses to let us default. Every construction below
#: has to supply them, so they live in one place.
REQUIRED = dict(
    maintenance_margin_ratio=D('0.35'),
    liquidation_margin_ratio=D('0.32'),
    forced_sale_price=ForcedSalePrice.FLOOR,
    day_count=DayCount.ACT_365,
    liquidation_order=LiquidationOrder.LARGEST_POSITION_FIRST,
    proceeds_application_order=tuple(ProceedsComponent),
)


def terms(**overrides) -> BrokerMarginTerms:
    """A minimally legal broker, with one field pushed out of range."""
    return BrokerMarginTerms(**{**REQUIRED, **overrides})


# ==========================================================================
# PROVENANCE completeness
# ==========================================================================

def test_regulation_provenance_covers_every_field_and_nothing_else():
    """A field with no entry is a value nobody can trace back to a clause.

    Set equality in both directions: a missing entry means an untraceable
    statutory value, and a stray entry means a field was renamed or deleted and
    the provenance table still claims to describe it.
    """
    named = {f.name for f in fields(MarginRegulation)}
    assert set(MarginRegulation.PROVENANCE) == named


def test_broker_provenance_covers_every_field_and_nothing_else():
    """The commercial counterpart, and the same rule as ``BrokerTerms``.

    Every default here is a plausible market value, not a sourced one, and the
    dict is where it says so.
    """
    named = {f.name for f in fields(BrokerMarginTerms)}
    assert set(BrokerMarginTerms.PROVENANCE) == named


def test_provenance_is_not_a_dataclass_field_on_either_object():
    """``PROVENANCE`` is unannotated on purpose, as on every other config object.

    An annotation would make it a dataclass field -- so it would need a value at
    every construction, and it would appear in its own completeness check above,
    which would then pass vacuously for the one entry it could never have.
    """
    assert 'PROVENANCE' not in {f.name for f in fields(MarginRegulation)}
    assert 'PROVENANCE' not in {f.name for f in fields(BrokerMarginTerms)}


def test_every_verified_statutory_entry_names_an_article():
    """VERIFIED means an operative text was read, so it must say which one.

    A ``VERIFIED`` grade with no article is the exact shape of an overclaim: it
    asserts a text exists and declines to identify it.
    """
    for name, prov in MarginRegulation.PROVENANCE.items():
        if prov.grade is SourceGrade.VERIFIED:
            assert prov.article, f'{name} is VERIFIED but names no article'


def test_no_statutory_field_is_graded_derived():
    """DERIVED values do not belong on the object that claims to be the law.

    ``MarginRegulation`` is the gazetted layer. Our own arithmetic lives in the
    module-level :data:`PROVENANCE` table and on the records it describes -- the
    top-up amounts, the loan-to-value identity, the account-level ``MR``
    reading. If one ever migrates onto a statutory field, this fails.
    """
    derived = [n for n, p in MarginRegulation.PROVENANCE.items()
               if p.grade is SourceGrade.DERIVED]
    assert derived == []


def test_the_statutory_fields_the_spec_grades_silent_say_so():
    """Three statutory fields record an absence, and must be graded as one.

    * ``top_up_formula_obtained`` -- QD 87 Dieu 7.2's two formulas are images in
      every accessible mirror and were never read.
    * ``prescribes_interest_day_count`` -- Dieu 11.4 delegates the calculation
      method entirely.
    * ``forced_sale_price_prescribed`` -- no document sets a forced-sale price.

    All three are ``False`` on the object, and a ``False`` that is graded
    VERIFIED would read as "the law says no" rather than "the law is silent".
    """
    for name in ('top_up_formula_obtained', 'prescribes_interest_day_count',
                 'forced_sale_price_prescribed'):
        assert MarginRegulation.PROVENANCE[name].grade is SourceGrade.SILENT
        assert getattr(QD_87_2017, name) is False


def test_still_in_force_is_reported_not_verified():
    """No *Tinh trang hieu luc* field was readable. That is an inference.

    ``effective_to=None`` is the strongest claim in the object -- it says this
    law governs today -- and it rests on HOSE practice and on the absence of a
    successor quy che, not on a status read. Grading it VERIFIED would put a
    read text behind an inference.
    """
    prov = MarginRegulation.PROVENANCE['effective_to']
    assert prov.grade is SourceGrade.REPORTED
    assert QD_87_2017.effective_to is None


def test_only_the_three_law_fixed_broker_fields_are_verified():
    """No commercial default is sourced. Exactly three broker fields are.

    The research read **no** broker's *hop dong giao dich ky quy* and found zero
    verified numeric thresholds at any named firm, so a VERIFIED grade on a
    commercial default would be a fabrication. The three exceptions are the
    fields whose value is fixed by a read article rather than chosen by the
    firm: the statutory floors object itself, the Dieu 2.4 valuation cap, and
    the TT 120 Dieu 9.6 exclusion. All three are refused when set the other way
    -- see the validation tests below.
    """
    verified = {n for n, p in BrokerMarginTerms.PROVENANCE.items()
                if p.grade is SourceGrade.VERIFIED}
    assert verified == {'regulation',
                        'collateral_valuation_cap_enforced',
                        'ineligible_counted_as_collateral'}


def test_the_six_unsourced_fields_have_no_default_and_say_so():
    """Spec sections 4 and 5: these six may not be defaulted, so they are not.

    Two halves, and both matter. The dataclass must genuinely refuse to
    construct without them -- no default, no default factory -- and the
    provenance note must tell a reader why, because a required field with a
    silent rationale gets a default added back by the next person who finds it
    inconvenient.
    """
    unsourced = {'maintenance_margin_ratio', 'liquidation_margin_ratio',
                 'forced_sale_price', 'day_count', 'liquidation_order',
                 'proceeds_application_order'}
    by_name = {f.name: f for f in fields(BrokerMarginTerms)}
    for name in unsourced:
        spec = by_name[name]
        assert spec.default is MISSING, f'{name} grew a default'
        assert spec.default_factory is MISSING, f'{name} grew a default factory'
        note = BrokerMarginTerms.PROVENANCE[name].note
        assert 'NO DEFAULT' in note, f'{name} does not say it has no default'


def test_no_default_survives_removal_of_the_field():
    """The feature is not done until a test fails without it.

    Constructing with any one of the six omitted must be a ``TypeError``. This
    is the mechanical guarantee behind "a run that has not set them cannot be
    constructed" -- the alternative, a default nobody noticed, is how the
    withdrawn DNSE cash-product numbers would get into a published result.
    """
    for name in REQUIRED:
        partial = {k: v for k, v in REQUIRED.items() if k != name}
        with pytest.raises(TypeError):
            BrokerMarginTerms(**partial)


def test_module_provenance_carries_every_silent_item_the_spec_lists():
    """Section 4's nine "do not invent these" items each have an entry.

    The spec enumerates them precisely so an implementer cannot quietly default
    one. Keying them here is what makes that enumeration survive contact with
    the code.
    """
    for key in ('liquidation_order', 'proceeds_application_order',
                'forced_sale_price', 'interest_day_count', 'extension_count',
                'intraday_monitoring', 'interest_rate_cap',
                'trading_status_mapping', 'upcom_eligibility'):
        assert key in PROVENANCE, f'section 4 item {key} is undeclared'
        assert PROVENANCE[key].grade is SourceGrade.SILENT


def test_the_top_up_amounts_are_declared_derived():
    """The highest-impact unsourced value in the module says so in capitals.

    QD 87 Dieu 7.2's formulas are images in every accessible mirror. What
    ``MarginCall`` carries is our own arithmetic off the EB/AB algebra, and a
    published result quoting a top-up amount has to disclose that.
    """
    prov = PROVENANCE['top_up_amounts']
    assert prov.grade is SourceGrade.DERIVED
    assert prov.is_assumption
    assert 'DO NOT SHIP THESE AS' in prov.note


def test_the_loan_to_value_identity_is_declared_derived():
    """``imr = 1 - loan_ratio`` is ours, and the 50 % LTV restatement rides on it.

    The identity is in no text read and holds only for a single fully
    collateralised purchase. It bounds one broker field and must never be quoted
    as QD 87 Dieu 5.1's content.
    """
    assert PROVENANCE['loan_to_value_identity'].grade is SourceGrade.DERIVED
    assert BrokerMarginTerms.PROVENANCE['max_loan_ratio'].grade \
        is SourceGrade.DERIVED
    assert 'NOT A STATUTORY CAP' in \
        BrokerMarginTerms.PROVENANCE['max_loan_ratio'].note


def test_provenance_renders_to_the_flat_house_form():
    """``str()`` gives back the one-line shape every other config object uses.

    The record exists so a completeness test can assert on the grade; it must
    still print like ``BrokerTerms.PROVENANCE`` for anyone dumping provenance
    into a result.
    """
    prov = Provenance(article='QD 87 Dieu 5.1', grade=SourceGrade.VERIFIED,
                      note='the floor')
    rendered = str(prov)
    assert 'QD 87 Dieu 5.1' in rendered
    assert 'VERIFIED' in rendered
    assert 'the floor' in rendered
    assert not prov.is_assumption
    assert Provenance(None, SourceGrade.SILENT, 'x').is_assumption
    assert Provenance(None, SourceGrade.DERIVED, 'x').is_assumption
    assert not Provenance(None, SourceGrade.REPORTED, 'x').is_assumption


# ==========================================================================
# The statutory values themselves
# ==========================================================================

def test_the_encoded_statutory_values_are_the_ones_the_articles_state():
    """One assertion per number, so a transcription slip cannot pass.

    The derivatives side already has a case study in this failure mode:
    ``0.175`` matched no source at any date and was a slip for ``0.17``. Two
    correctly-cited numbers still produce a wrong rule when one of them was
    typed wrong.
    """
    r = QD_87_2017
    assert r.initial_margin_ratio_floor == D('0.50')       # Dieu 5.1
    assert r.maintenance_margin_ratio_floor == D('0.30')   # Dieu 5.2
    assert r.ratios_adjustable_by_regulator is True        # Dieu 5.3
    assert r.collateral_value_cap is CollateralValuationCap.LAST_CLOSE  # 2.4
    assert r.ratio_determination is RatioDetermination.END_OF_DAY       # 6.1
    assert r.max_cure_business_days == 3                   # Dieu 7.1
    assert r.max_loan_term_months == 3                     # Dieu 11.1
    assert r.max_extension_months == 3                     # Dieu 11.2
    assert r.max_extensions is None                        # Dieu 11.2, absence
    assert r.interest_rate_cap is None                     # Dieu 11.3, absence
    assert r.min_listing_months == 6                       # Dieu 3.1
    assert r.exchange_publish_lag_business_days == 2        # Dieu 4.1
    assert r.broker_publish_lag_business_days == 2          # Dieu 4.2
    assert r.relist_review_min_months == 6                  # Dieu 4.1
    assert r.equity_statement_max_age_months == 6           # Dieu 9
    assert r.suspension_report_hours == 48                  # TT 120 Dieu 9.7
    assert r.underwriting_lockout_months == 6               # Dieu 10.1(a)
    assert r.affiliate_ownership_threshold == D('0.50')     # Dieu 10.1(b)
    assert r.effective_from == date(2017, 4, 1)


def test_the_four_firm_limits_carry_their_own_denominators():
    """QD 87 Dieu 9.1-9.4. Three are fractions of equity; the fourth is not.

    Keyed rather than four scalars precisely so ``0.05`` cannot be applied to
    equity: Dieu 9.4 is 5 % of *that issuer's total listed shares*, re-fetched
    verbatim as *"...5% tong so chung khoan niem yet cua mot to chuc niem yet"*.
    """
    limits = QD_87_2017.firm_limits
    assert limits[FirmLendingLimit.TOTAL_BOOK] == D('2.00')
    assert limits[FirmLendingLimit.PER_CUSTOMER] == D('0.03')
    assert limits[FirmLendingLimit.PER_SECURITY] == D('0.10')
    assert limits[FirmLendingLimit.PER_ISSUER_SHARES] == D('0.05')
    assert set(limits) == set(FirmLendingLimit)


def test_the_universe_is_listed_only_and_the_divergence_is_recorded():
    """HOSE + HNX, with the TT 120 conflict written into the field's own note.

    QD 87 Dieu 3 says *niem yet*; TT 120 Dieu 9.4 also says *dang ky giao dich*,
    which would admit UPCoM. Both texts are VERIFIED. The implementation follows
    QD 87 as the delegated quy che -- and the provenance entry has to carry the
    divergence, because resolving it silently is how a reader ends up believing
    the two texts agree.
    """
    assert QD_87_2017.eligible_venues == frozenset({Venue.HSX, Venue.HNX})
    assert Venue.UPCOM not in QD_87_2017.eligible_venues
    note = MarginRegulation.PROVENANCE['eligible_venues'].note
    assert 'DIVERGENCE' in note
    assert 'UPCoM' in note
    assert set(QD_87_2017.exclusion_predicates) == set(ExclusionPredicate)


def test_foreign_prohibition_carries_the_non_prefunded_warning():
    """The flat bar is real, and reading it as "no foreign credit" is wrong.

    TT 120 Dieu 9a is broker credit extended to precisely the class Dieu 9.2
    bars, under a different regime that is not *ky quy*. An implementer who
    reads only this field builds a simulator that refuses all foreign
    credit-funded buying.
    """
    assert QD_87_2017.foreign_investors_allowed is False
    note = MarginRegulation.PROVENANCE['foreign_investors_allowed'].note
    assert '9a' in note


def test_the_regulation_is_resolved_by_date_and_refuses_before_2017():
    """Dated, not constant, and it raises rather than extrapolating backwards.

    QD 637 governed until 2017-03-31 with a 60 % initial floor -- REPORTED --
    and its **maintenance** floor was never obtained. A row for that period
    would have to invent an ``mmr``, so there is no row, and a 2015
    counterfactual gets a refusal instead of 2017 law applied silently.
    """
    assert regulation_in_force(date(2017, 4, 1)) is QD_87_2017
    assert regulation_in_force(date(2026, 8, 26)) is QD_87_2017
    with pytest.raises(UnresolvedMarginRegulation) as excinfo:
        regulation_in_force(date(2017, 3, 31))
    assert 'QD 637' in str(excinfo.value)


# ==========================================================================
# The validation relationship: stricter is fine, looser is not
# ==========================================================================

def test_terms_at_exactly_the_floor_are_accepted():
    """The floors are inclusive. *"Khong duoc thap hon 50%"* admits 50 %."""
    at_floor = terms(initial_margin_ratio=D('0.50'),
                     maintenance_margin_ratio=D('0.30'),
                     liquidation_margin_ratio=D('0.30'))
    assert at_floor.initial_margin_ratio == D('0.50')
    assert at_floor.call_level == D('0.30')
    assert at_floor.force_sell_level == D('0.30')


def test_stricter_terms_are_accepted_in_every_direction():
    """Nothing here refuses a firm for being tougher than the law.

    A firm may demand 80 % initial margin, call at 60 %, force-sell at 45 %,
    monitor hourly at live prices and grant a one-day cure window. All of that
    is legal and some of it is observed.
    """
    strict = terms(initial_margin_ratio=D('0.80'),
                   maintenance_margin_ratio=D('0.60'),
                   liquidation_margin_ratio=D('0.45'),
                   cure_business_days=1,
                   intraday_monitoring=True,
                   monitor_interval_minutes=60,
                   price_source=PriceSource.LIVE_MARKET)
    assert strict.force_sell_level == D('0.45')
    assert strict.monitor_interval_minutes == 60


def test_initial_margin_below_the_floor_is_refused_naming_dieu_5_1():
    """QD 87 Dieu 5.1 floors the ratio the **broker** sets, at 50 %."""
    with pytest.raises(BrokerTermLooserThanLaw) as excinfo:
        terms(initial_margin_ratio=D('0.40'))
    err = excinfo.value
    assert err.term == 'initial_margin_ratio'
    assert err.value == D('0.40')
    assert err.floor == D('0.50')
    assert err.article == 'QD 87 Dieu 5.1'
    assert 'QD 87 Dieu 5.1' in str(err)


def test_maintenance_below_the_floor_is_refused_naming_dieu_5_2():
    """The call level is floored at 30 % -- QD 87 Dieu 5.2, VERIFIED."""
    with pytest.raises(BrokerTermLooserThanLaw) as excinfo:
        terms(maintenance_margin_ratio=D('0.29'),
              liquidation_margin_ratio=D('0.29'))
    assert excinfo.value.term == 'maintenance_margin_ratio'
    assert excinfo.value.article == 'QD 87 Dieu 5.2'


def test_force_sell_below_the_floor_is_refused_by_the_same_article():
    """The 30 % floor binds the lower rung too, and binds it harder.

    An account is allowed to sit between the two levels while it cures, so a
    force-sell level under 30 % means the account was already unlawfully
    under-margined for the whole cure window.
    """
    with pytest.raises(BrokerTermLooserThanLaw) as excinfo:
        terms(liquidation_margin_ratio=D('0.20'))
    assert excinfo.value.term == 'liquidation_margin_ratio'
    assert excinfo.value.floor == D('0.30')


def test_an_inverted_ladder_is_a_value_error_not_a_legal_breach():
    """Call above force-sell is the observed shape, but no article says so.

    The distinction is deliberate: :class:`BrokerTermLooserThanLaw` means a read
    clause was breached, and nothing in QD 87 orders the two broker levels --
    the regulation has one floor and does not know brokers run two rungs above
    it. Raising the statutory exception here would cite a law that is silent.
    """
    with pytest.raises(ValueError) as excinfo:
        terms(maintenance_margin_ratio=D('0.31'),
              liquidation_margin_ratio=D('0.40'))
    assert not isinstance(excinfo.value, BrokerTermLooserThanLaw)
    assert 'non-increasing' in str(excinfo.value)


def test_a_cure_window_longer_than_three_business_days_is_refused():
    """QD 87 Dieu 7.1 is a ceiling, and it is Dieu 7.1 **alone**.

    TT 120 Dieu 9.6 carries the call and the force-sale right but no day count,
    so the message must not cite the two jointly for the three days.
    """
    with pytest.raises(BrokerTermLooserThanLaw) as excinfo:
        terms(cure_business_days=4)
    assert excinfo.value.article == 'QD 87 Dieu 7.1'
    assert excinfo.value.floor == 3


def test_a_zero_day_cure_window_is_refused_as_our_reading():
    """Zero is not a period -- and the message says the bound is ours.

    The article states only the ceiling. A firm that force-sells with no window
    models that through ``liquidation_margin_ratio``, which bypasses the window
    by design.
    """
    with pytest.raises(ValueError) as excinfo:
        terms(cure_business_days=0)
    assert not isinstance(excinfo.value, BrokerTermLooserThanLaw)
    assert 'OUR READING' in str(excinfo.value)


def test_waiving_the_collateral_valuation_cap_is_refused():
    """QD 87 Dieu 2.4 is not a broker option.

    Valuing collateral above the last close raises ``PV``, raises ``EB``, raises
    ``AB / EB`` and delays every call -- looser than the law in the direction
    that hurts the client. Monitoring at a live price is still allowed; the cap
    applies on top.
    """
    with pytest.raises(BrokerTermLooserThanLaw) as excinfo:
        terms(collateral_valuation_cap_enforced=False)
    assert excinfo.value.article == 'QD 87 Dieu 2.4'


def test_counting_ineligible_securities_as_collateral_is_refused():
    """TT 120 Dieu 9.6 excludes them from the base for **both** ratios.

    QD 87 Dieu 10.2 is narrower -- still security for the existing loan -- and
    the higher-ranking instrument is the one implemented.
    """
    with pytest.raises(BrokerTermLooserThanLaw) as excinfo:
        terms(ineligible_counted_as_collateral=True)
    assert excinfo.value.article == 'TT 120 Dieu 9.6'


def test_a_term_longer_than_three_months_is_refused_naming_dieu_11_1():
    """The statute is in months, the firms publish days, and 200 fits neither."""
    with pytest.raises(BrokerTermLooserThanLaw) as excinfo:
        terms(base_term_days=200)
    assert excinfo.value.article == 'QD 87 Dieu 11.1'
    assert 'NECESSARY' in str(excinfo.value)


def test_an_extension_longer_than_three_months_is_refused():
    """Dieu 11.2 caps the length of each extension, not the number of them."""
    with pytest.raises(BrokerTermLooserThanLaw) as excinfo:
        terms(extension_days=120)
    assert excinfo.value.article == 'QD 87 Dieu 11.2'


def test_ninety_day_terms_pass_the_months_to_days_bridge():
    """90 days is what SSI, DNSE, ACBS and FNS all publish, and it must pass.

    The config-time bridge is deliberately the loosest one, so it never refuses
    a term the date arithmetic at disbursement would allow.
    """
    ninety = terms(base_term_days=90, extension_days=90)
    assert ninety.base_term_days == 90


def test_extensions_are_uncapped_by_the_regulation():
    """``extension_count_max=None`` is the statutory position, not a gap.

    QD 87 Dieu 11.2 caps each extension at 3 months and says nothing about how
    many. A firm may cap it -- DNSE and ACBS do -- and a firm that does not is
    not thereby unlawful.
    """
    assert terms().extension_count_max is None
    assert terms(extension_count_max=2).extension_count_max == 2
    assert terms(extension_count_max=0).extension_count_max == 0


def test_a_cure_target_below_the_firms_own_call_level_is_incoherent():
    """A "cured" account that is still in call has not been cured.

    Dieu 7 floors the target at ``mmr`` and leaves the precise level to the
    CTCK, which is what the field is for; below the firm's own level it means
    nothing.
    """
    with pytest.raises(ValueError) as excinfo:
        terms(cure_target_ratio=D('0.33'))
    assert not isinstance(excinfo.value, BrokerTermLooserThanLaw)
    with pytest.raises(BrokerTermLooserThanLaw):
        terms(maintenance_margin_ratio=D('0.30'),
              liquidation_margin_ratio=D('0.30'),
              cure_target_ratio=D('0.25'))


def test_waiting_more_consecutive_breach_days_than_the_cure_ceiling_is_refused():
    """A second clock, and it is bounded by the same three business days.

    SSI uses exactly 3 -- the statutory ceiling, used in full. Waiting longer
    lets an uncured account sit under the maintenance ratio beyond what Dieu 7.1
    allows.
    """
    with pytest.raises(BrokerTermLooserThanLaw) as excinfo:
        terms(consecutive_breach_days_before_sale=5)
    assert excinfo.value.article == 'QD 87 Dieu 7.1'


def test_a_loan_ratio_above_the_firms_cap_is_refused():
    """The per-ticker haircut mapping is a positive list bounded by its own cap.

    Note the message has to say the 50 % cap is a **broker** term: restating
    Dieu 5.1 as a loan-to-value rides on the DERIVED identity.
    """
    with pytest.raises(ValueError) as excinfo:
        terms(loan_ratio_by_ticker={'HPG': D('0.70')})
    assert 'DERIVED' in str(excinfo.value)
    with pytest.raises(ValueError):
        terms(loan_ratio_by_ticker={'HPG': D('0')})
    assert terms(loan_ratio_by_ticker={'HPG': D('0.50'),
                                       'VNM': D('0.30')})


def test_a_partial_proceeds_order_is_refused():
    """Every component exactly once, because there is no default to fall back on.

    QD 87 Dieu 12.2(i) requires the contract to state the priority. A partial
    order leaves a component unpriced and the regulation is SILENT, so inventing
    the remainder would be a house rule wearing a citation.
    """
    with pytest.raises(ValueError) as excinfo:
        terms(proceeds_application_order=(ProceedsComponent.PRINCIPAL,
                                          ProceedsComponent.INTEREST))
    assert 'exactly once' in str(excinfo.value)
    with pytest.raises(ValueError):
        terms(proceeds_application_order=(ProceedsComponent.PRINCIPAL,
                                          ProceedsComponent.PRINCIPAL,
                                          ProceedsComponent.INTEREST,
                                          ProceedsComponent.FEES))
    reordered = terms(proceeds_application_order=(
        ProceedsComponent.TAXES, ProceedsComponent.FEES,
        ProceedsComponent.INTEREST, ProceedsComponent.PRINCIPAL))
    assert reordered.proceeds_application_order[0] is ProceedsComponent.TAXES


def test_selling_only_the_breaching_position_needs_a_finer_accounting_unit():
    """At account granularity there is no single breaching position.

    QD 87 Dieu 2's ratio is computed over the whole account, so the account
    breached, not a ticker. DNSE can sell just the breaching deal's stock
    precisely because it runs per-deal.
    """
    with pytest.raises(ValueError) as excinfo:
        terms(forced_sale_scope=ForcedSaleScope.BREACHING_POSITION)
    assert 'accounting_unit' in str(excinfo.value)
    assert terms(forced_sale_scope=ForcedSaleScope.BREACHING_POSITION,
                 accounting_unit=AccountingUnit.DEAL)


def test_a_sweep_interval_without_intraday_monitoring_is_incoherent():
    """A config that says two things is refused rather than one half ignored."""
    with pytest.raises(ValueError) as excinfo:
        terms(monitor_interval_minutes=60)
    assert 'intraday_monitoring' in str(excinfo.value)


def test_a_float_ratio_is_refused_outright():
    """Decimal for money and ratios, never float, and enforced not merely stated.

    ``Decimal('0.30') > 0.3`` is ``True``. A float threshold does not round, it
    compares wrong against the Decimals the ratio is built from -- silently, and
    only sometimes. A margin ladder is exactly a chain of such comparisons.
    """
    with pytest.raises(TypeError) as excinfo:
        terms(maintenance_margin_ratio=0.35)
    # Matched on the guard's own wording, not merely on TypeError: without the
    # guard a float still eventually blows up on `float + Decimal` several
    # checks later, which would let this test pass while the guard was gone.
    assert 'never float' in str(excinfo.value)
    assert 'maintenance_margin_ratio' in str(excinfo.value)

    with pytest.raises(TypeError, match='never float'):
        terms(initial_margin_ratio=0.6)
    with pytest.raises(TypeError, match='never float'):
        terms(loan_ratio_by_ticker={'HPG': 0.5})


def test_an_overdue_multiplier_below_one_would_reward_being_overdue():
    """150 % is REPORTED at two firms; below 1 is incoherent at any firm."""
    with pytest.raises(ValueError):
        terms(overdue_multiplier=D('0.9'))
    assert terms(overdue_multiplier=D('1.50')).overdue_multiplier == D('1.50')


def test_an_empty_rate_schedule_means_no_rate_was_agreed():
    """QD 87 Dieu 11.3 requires the rate to be agreed in writing.

    So "unset" is a real contractual state, and the engine must refuse to accrue
    rather than invent a number. Defaulting a rate here would put an
    unnegotiated 13.5 % into every run that forgot to set one.
    """
    assert terms().rate_schedule == ()
    assert 'NO RATE HAS BEEN AGREED' in \
        BrokerMarginTerms.PROVENANCE['rate_schedule'].note


def test_a_rate_schedule_must_cover_the_whole_loan_exactly_once():
    """Gaps, overlaps, disorder and a closed tail are all refused.

    The shape is our modelling choice -- Dieu 11.4 prescribes nothing -- and it
    is enforced because the alternative is a day on which the engine has no rate
    and has to pick one.
    """
    acbs_t14 = (InterestTier(0, 13, D('0.08')),
                InterestTier(14, None, D('0.13')))
    assert terms(rate_schedule=acbs_t14).rate_schedule == acbs_t14

    with pytest.raises(ValueError, match='start at day 0'):
        terms(rate_schedule=(InterestTier(1, None, D('0.13')),))
    with pytest.raises(ValueError, match='gap'):
        terms(rate_schedule=(InterestTier(0, 10, D('0.08')),
                             InterestTier(20, None, D('0.13'))))
    with pytest.raises(ValueError, match='overlap'):
        terms(rate_schedule=(InterestTier(0, 10, D('0.08')),
                             InterestTier(5, None, D('0.13'))))
    with pytest.raises(ValueError, match='open-ended'):
        terms(rate_schedule=(InterestTier(0, 30, D('0.08')),))
    with pytest.raises(ValueError, match='ordered by day_from'):
        terms(rate_schedule=(InterestTier(14, None, D('0.13')),
                             InterestTier(0, 13, D('0.08'))))


def test_a_zero_rate_promotional_tier_is_legal():
    """ACBS Margin T+ and Pinetree P-Zero both run 0 % introductory tiers."""
    promo = (InterestTier(0, 6, D('0')), InterestTier(7, None, D('0.13')))
    assert terms(rate_schedule=promo).rate_schedule[0].annual_rate == D('0')
    with pytest.raises(ValueError):
        InterestTier(0, None, D('-0.01'))


def test_the_two_market_names_track_the_two_fields():
    """``call_level`` and ``force_sell_level`` are properties, not second fields.

    SSI says *TLKQ duy tri* / *TLKQ xu ly*; DNSE says *ty le canh bao* / *ty le
    xu ly*; QD 87 Dieu 5.2 names only the floor beneath the first. One value
    each, so the names cannot drift.
    """
    t = terms(maintenance_margin_ratio=D('0.42'),
              liquidation_margin_ratio=D('0.36'))
    assert t.call_level is t.maintenance_margin_ratio
    assert t.force_sell_level is t.liquidation_margin_ratio


def test_a_historical_regulation_row_would_bind_the_same_terms_differently():
    """The floors come from :attr:`regulation`, not from module constants.

    Passing a stricter regulation must refuse terms that
    :data:`QD_87_2017` accepts. This is what makes the object dated rather than
    a set of constants with a citation attached -- QD 87 Dieu 5.3 lets the SSC
    move the ratios, and the 2018 draft that would have taken the initial floor
    back to 60 % shows the direction it moves in.
    """
    import dataclasses
    stricter = dataclasses.replace(
        QD_87_2017,
        initial_margin_ratio_floor=D('0.60'),
        citation='counterfactual: the 2018 SSC draft, WHICH WAS NEVER ADOPTED',
        grade=SourceGrade.REPORTED)
    assert terms(initial_margin_ratio=D('0.50')).initial_margin_ratio == D('0.50')
    with pytest.raises(BrokerTermLooserThanLaw) as excinfo:
        terms(initial_margin_ratio=D('0.50'), regulation=stricter)
    assert excinfo.value.floor == D('0.60')


def test_the_terms_vintage_cannot_predate_its_own_fetch_inversely():
    """Effective date and fetch date are both kept, and must be ordered.

    SSI's 13.5 %/nam schedule was fetched 2026-08-26 and carries an effective
    date of 2022-11-01. Recording only the fetch date would date a 2022 value to
    2026.
    """
    ssi = terms(firm='SSI', terms_effective_from=date(2022, 11, 1),
                terms_fetched_on=date(2026, 8, 26))
    assert ssi.terms_effective_from < ssi.terms_fetched_on
    with pytest.raises(ValueError):
        terms(terms_effective_from=date(2026, 8, 26),
              terms_fetched_on=date(2022, 11, 1))


# ==========================================================================
# THE ACCOUNT ALGEBRA -- QD 87 Dieu 2 khoan 3-12
# ==========================================================================
#
# The tests above pin what the module *asserts*. These pin what it *computes*.
# Three things in Dieu 2 are counter-intuitive and each gets its own group:
# khoan 5 puts unsettled sale proceeds inside CB, khoan 8 makes imr a per-order
# ratio, and Dieu 2.4 caps every collateral value at the last close.

from dataclasses import replace
from datetime import datetime, time

from plutus.market.session.margin_lending import (
    DEFAULT_SESSION_CLOSE, CollateralBucket, CollateralLot, FirmLendingState,
    IneligibleAccountHolder, LoanStatus, MarginAccountState,
    MarginAccountStatus, MarginCall, MarginCallStatus, MarginEligibility,
    MarginLoan, MarginOrderRefusal, ProhibitedCollateral, RatioSchedule,
    SecurityEligibility, assess_margin_order, build_account_state, cash_base,
    compute_account_algebra, firm_limit_headroom, order_initial_margin_ratio,
    value_collateral)
from plutus.market.session.types import Cash, ProceedsTranche

NOW = datetime(2026, 8, 26, 15, 0)
TODAY = NOW.date()


def priced(ticker: str, quantity: int, close: str, **kw) -> CollateralLot:
    """An eligible, priced lot -- the ordinary case, in one line."""
    return CollateralLot(ticker=ticker, quantity=quantity, last_close=D(close),
                         eligibility=MarginEligibility.ELIGIBLE, **kw)


def account(**kw) -> MarginAccountState:
    """A margin account state with every value field defaulted to zero."""
    fields = dict(account_id='M1', as_of=NOW)
    fields.update(kw)
    return MarginAccountState(**fields)


def eligible(ticker: str = 'AAA') -> SecurityEligibility:
    """A ticker the exchange permits and this firm carries."""
    return SecurityEligibility(ticker=ticker, as_of=TODAY,
                               result=MarginEligibility.ELIGIBLE,
                               on_broker_list=True)


# ==========================================================================
# CB -- khoan 5, and the tranche ledger it disagrees with
# ==========================================================================

def cash_with(settled='0', pending='0', advanced='0', committed='0') -> Cash:
    tranches = ()
    if D(pending) != 0:
        tranches = (ProceedsTranche(amount=D(pending), settles_at=NOW,
                                    accrued_at=NOW),)
    return Cash(settled_balance=D(settled), committed=D(committed),
                advanced=D(advanced), pending_proceeds=tranches)


def test_cb_counts_unsettled_proceeds_and_available_does_not():
    """khoan 5 and ``Cash.available`` answer different questions.

    ``CB`` is *tien + tien ban chung khoan dang cho ve*; ``available`` is what
    can be spent today, and Vietnamese equity is 100 % pre-funded so pending
    proceeds cannot fund a purchase. Both are right. A single number would be
    wrong twice.
    """
    base = cash_base(cash_with(settled='1000', pending='500'), terms())
    assert base.cb == D('1500')
    assert base.available == D('1000')
    assert base.divergence == D('500')


def test_the_sale_advance_nets_out_of_cb_exactly():
    """Drawing an advance changes ``available`` and must not change ``CB``.

    The ledger adds the outstanding principal to ``available``, leaves
    ``settled_balance`` alone and keeps the tranche at full face -- so the
    already-received dong and the still-to-come dong are the same tranche
    counted once. Adding ``advanced`` to ``CB`` would count them twice;
    subtracting it would count them zero times.
    """
    without = cash_base(cash_with(settled='1000', pending='500'), terms())
    drawn = cash_base(
        cash_with(settled='1000', pending='500', advanced='300'), terms())
    assert drawn.cb == without.cb == D('1500')
    assert drawn.available == D('1300')
    assert drawn.advanced == D('300')


def test_committed_cash_is_still_tien_for_khoan_5():
    """Money promised to an unfilled buy order is still the client's.

    khoan 5 says *tien*, not *tien chua bi rang buoc*, so ``CB`` does not net
    live orders. ``uncommitted`` exists for a caller gating several orders off
    one snapshot, and it is not used by the algebra.
    """
    base = cash_base(cash_with(settled='1000', committed='400'), terms())
    assert base.cb == D('1000')
    assert base.available == D('600')
    assert base.uncommitted == D('600')


def test_a_firm_may_decline_to_count_unsettled_proceeds():
    """Stricter than the algebra is always allowed; looser never is."""
    strict = terms(collateral_includes_unsettled_sale_proceeds=False)
    base = cash_base(cash_with(settled='1000', pending='500'), strict)
    assert base.cb == D('1000')
    assert base.counts_unsettled is False


def test_unsettled_proceeds_move_the_margin_ratio():
    """The point of khoan 5, stated as a ratio rather than a balance.

    Two identical accounts, one holding its cash settled and the other waiting
    for T+2, have the **same** margin ratio. An implementation that reached for
    ``Cash.available`` would report the waiting account as poorer than it is and
    call it sooner.
    """
    settled = account(cash=D('1000'), eligible_securities_value=D('1000'),
                      margin_debt=D('500'))
    waiting = account(pending_sale_proceeds=D('1000'),
                      eligible_securities_value=D('1000'),
                      margin_debt=D('500'))
    assert (compute_account_algebra(settled, terms()).margin_ratio
            == compute_account_algebra(waiting, terms()).margin_ratio)
    excluded = compute_account_algebra(
        waiting, terms(collateral_includes_unsettled_sale_proceeds=False))
    assert excluded.cb == D('0')
    assert excluded.margin_ratio < D('0.75')


# ==========================================================================
# PV -- the Dieu 2.4 collateral cap
# ==========================================================================

def test_the_cap_binds_when_the_live_price_is_above_the_last_close():
    """*"khong vuot qua gia dong cua tai ngay gan nhat"* -- Dieu 2.4, VERIFIED.

    A firm monitoring at live market prices does not get to inflate ``PV`` on an
    up day. This is the case where the cap changes the ratio, so the ticker is
    named in ``capped_tickers`` and the lot records both prices.
    """
    live = terms(price_source=PriceSource.LIVE_MARKET)
    lot = priced('AAA', 100, '20', live_price=D('25'))
    valued = value_collateral([lot], live, as_of=NOW)
    assert valued.eligible_value == D('2000')
    assert valued.capped_tickers == ('AAA',)
    assert valued.lots[0].unit_value == D('20')
    assert valued.lots[0].monitored_price == D('25')
    assert valued.lots[0].capped is True


def test_the_cap_does_not_lift_a_price_that_is_below_the_close():
    """It is a ceiling, not a peg. A down day is valued at the live price."""
    live = terms(price_source=PriceSource.LIVE_MARKET)
    valued = value_collateral([priced('AAA', 100, '20', live_price=D('15'))],
                              live, as_of=NOW)
    assert valued.eligible_value == D('1500')
    assert valued.capped_tickers == ()


def test_no_last_close_makes_a_lot_unpriced_not_valued_at_the_live_price():
    """The ceiling cannot be shown to hold, so the article is not satisfied.

    Falling back to the monitored price would be the whole of Dieu 2.4 quietly
    not applying, and it would do so exactly on the securities whose data is
    worst.
    """
    live = terms(price_source=PriceSource.LIVE_MARKET)
    lot = CollateralLot('AAA', 100, live_price=D('25'),
                        eligibility=MarginEligibility.ELIGIBLE)
    valued = value_collateral([lot], live, as_of=NOW)
    assert valued.eligible_value == D('0')
    assert valued.unpriced_tickers == ('AAA',)
    assert valued.lots[0].bucket is CollateralBucket.UNPRICED
    assert 'NOT a fallback' in valued.lots[0].reason


def test_the_per_ticker_loan_ratio_is_not_applied_to_pv():
    """The haircut must not be taken twice, and the second one is invisible.

    The loan ratio enters through ``imr = 1 - loan_ratio`` on the order side.
    Applying it to ``PV`` as well would haircut the same collateral twice, and
    nothing in the output would show it happening. Dieu 2.4 gives only a
    ceiling; the value inside it is a contract term the research never read.
    """
    haircut = terms(loan_ratio_by_ticker={'AAA': D('0.30')})
    valued = value_collateral([priced('AAA', 100, '20')], haircut, as_of=NOW)
    assert valued.eligible_value == D('2000')


def test_an_ineligible_security_is_valued_and_never_counted():
    """TT 120 Dieu 9.6 excludes it from the base for **both** ratios.

    It is still valued, into its own field, so an engine can report *why* a
    ratio fell when a ticker came off the list -- which QD 87 Dieu 10.2's
    narrower reading (still security for the existing loan) makes worth seeing.
    """
    lot = CollateralLot('BBB', 100, last_close=D('20'),
                        eligibility=MarginEligibility.INELIGIBLE)
    valued = value_collateral([lot], terms(), as_of=NOW)
    assert valued.ineligible_value == D('2000')
    assert valued.eligible_value == D('0')
    assert valued.lots[0].counted is False
    assert 'TT 120 Dieu 9.6' in valued.lots[0].reason


def test_an_unpriced_ineligible_lot_is_not_an_indeterminacy():
    """Its price cannot change any ratio, so its absence decides nothing.

    Naming it would make almost every account INDETERMINATE, which is how a
    three-valued answer stops being read.
    """
    lot = CollateralLot('BBB', 100, eligibility=MarginEligibility.INELIGIBLE)
    assert value_collateral([lot], terms(), as_of=NOW).unpriced_tickers == ()


def test_an_unevaluable_eligibility_predicate_makes_the_account_undecided():
    """Most of QD 87 Dieu 3 needs issuer financials the corpus does not carry.

    Counting such a lot as zero is not conservative -- it is a different
    account. It has no determinable contribution to ``PV``, so it lands in
    ``unpriced_tickers`` and the status becomes INDETERMINATE.
    """
    lot = CollateralLot('CCC', 100, last_close=D('20'))  # default INDETERMINATE
    valued = value_collateral([lot], terms(), as_of=NOW)
    assert valued.lots[0].bucket is CollateralBucket.UNDETERMINED
    assert valued.unpriced_tickers == ('CCC',)
    assert valued.eligible_value == D('0')


def test_a_bucket_this_firm_excludes_is_valued_but_not_counted():
    """ACBS counts uncredited rights, FNS explicitly does not. Both are legal.

    And an unpriced lot in a bucket the firm excludes is not an indeterminacy,
    for the same reason an unpriced ineligible one is not.
    """
    lots = [priced('AAA', 100, '20', pending_settlement=True),
            priced('AAA', 50, '20', untradable_right=True),
            CollateralLot('DDD', 10, untradable_right=True,
                          eligibility=MarginEligibility.ELIGIBLE)]
    valued = value_collateral(lots, terms(), as_of=NOW)
    assert valued.pending_purchase_value == D('2000')
    assert valued.untradable_rights_value == D('1000')
    assert valued.lots[0].counted is True     # pending buys default to counted
    assert valued.lots[1].counted is False    # rights do not
    assert valued.unpriced_tickers == ()


def test_the_firm_flags_decide_what_reaches_pv():
    """The buckets are separate fields precisely so the flags can differ."""
    state = account(eligible_securities_value=D('1000'),
                    pending_purchase_value=D('500'),
                    untradable_rights_value=D('300'))
    assert compute_account_algebra(state, terms()).pv == D('1500')
    generous = terms(collateral_includes_untradable_rights=True)
    assert compute_account_algebra(state, generous).pv == D('1800')
    strict = terms(collateral_includes_pending_buys=False)
    assert compute_account_algebra(state, strict).pv == D('1000')


def test_one_ticker_twice_in_one_bucket_is_refused():
    """Two rows for one holding either double-counts PV or wants netting.

    A ticker held outright *and* pending settlement is two buckets and is fine
    -- that is the ordinary state of an account that bought this morning.
    """
    with pytest.raises(ValueError, match='appears twice'):
        value_collateral([priced('AAA', 100, '20'), priced('AAA', 50, '20')],
                         terms(), as_of=NOW)
    both = value_collateral(
        [priced('AAA', 100, '20'),
         priced('AAA', 50, '20', pending_settlement=True)], terms(), as_of=NOW)
    assert both.eligible_value == D('2000')
    assert both.pending_purchase_value == D('1000')


def test_a_negative_holding_is_refused_outright():
    """Vietnamese cash equity permits no short selling.

    A negative quantity would put a negative number into ``PV`` and raise the
    ratio of the account that has the least business having a high one.
    """
    with pytest.raises(ValueError, match='no short selling'):
        CollateralLot('AAA', -100, last_close=D('20'))


def test_a_float_price_on_a_lot_is_refused():
    """House rule, and ``Decimal('0.30') > 0.3`` is why."""
    with pytest.raises(TypeError, match='must be a Decimal'):
        CollateralLot('AAA', 100, last_close=20.0)


def test_a_lot_cannot_be_both_a_pending_buy_and_an_uncredited_right():
    """Different things, different flags, and the firms disagree about each."""
    with pytest.raises(ValueError, match='both pending_settlement'):
        CollateralLot('AAA', 100, last_close=D('20'),
                      pending_settlement=True, untradable_right=True)


# ==========================================================================
# Timing -- QD 87 Dieu 6.1 (spec 2.4)
# ==========================================================================

def test_the_statutory_schedule_determines_the_ratio_once_a_day():
    """Dieu 6.1: *cuoi ngay giao dich*. One instant, at the agreed time."""
    schedule = RatioSchedule.from_terms(terms())
    assert schedule.basis is RatioDetermination.END_OF_DAY
    assert schedule.instants(TODAY) == (datetime.combine(
        TODAY, DEFAULT_SESSION_CLOSE),)


def test_an_intraday_sweep_is_additional_and_never_replaces_the_close():
    """Stricter is always allowed; replacing the statutory instant is not.

    DNSE sweeps hourly 09:00-15:00 and force-sells intraday. A firm that swept
    at 10:00 *instead* of determining at the close would be looser than Dieu
    6.1, so the statutory instant is always in the list.
    """
    hourly = terms(intraday_monitoring=True, monitor_interval_minutes=60)
    schedule = RatioSchedule.from_terms(hourly)
    instants = schedule.instants(TODAY)
    assert schedule.basis is RatioDetermination.INTRADAY
    assert len(instants) == 7
    assert instants[0].time() == time(9, 0)
    assert datetime.combine(TODAY, DEFAULT_SESSION_CLOSE) in instants
    assert list(instants) == sorted(instants)

    early = RatioSchedule.from_terms(hourly, determination_at=time(14, 45))
    assert datetime.combine(TODAY, time(14, 45)) in early.instants(TODAY)


def test_a_continuous_monitor_has_no_timetable_and_says_so():
    """Refusing beats returning one instant and calling it the schedule."""
    live = terms(intraday_monitoring=True)
    schedule = RatioSchedule.from_terms(live)
    assert schedule.is_continuous is True
    with pytest.raises(ValueError, match='no enumerable instants'):
        schedule.instants(TODAY)


def test_a_sweep_period_on_an_end_of_day_schedule_is_incoherent():
    """A config that says two things is refused where it is written."""
    with pytest.raises(ValueError, match='does not sweep'):
        RatioSchedule(interval_minutes=60)


def test_an_intraday_basis_cannot_be_claimed_for_a_firm_that_does_not_sweep():
    """A result may not claim a computation the firm's terms say it never makes."""
    state = account(cash=D('1000'))
    with pytest.raises(ValueError, match='intraday_monitoring=False'):
        compute_account_algebra(state, terms(),
                                basis=RatioDetermination.INTRADAY)


# --------------------------------------------------------------------------
# Imports for the state-machine section. Kept as their own block rather than
# folded into the one at the top of the file: the two stages have separate
# surfaces, and a reader arriving at a forced-sale test should see what it
# depends on without scrolling past six hundred lines of config assertions.
# --------------------------------------------------------------------------

from dataclasses import replace  # noqa: E402
from datetime import datetime  # noqa: E402

from plutus.market.session.calendar import (  # noqa: E402
    weekday_settlement_calendar)
from plutus.market.session.margin_lending import (  # noqa: E402
    FORCED_SALE_TRIGGER_PRIORITY, BusinessDayCalendar, CureContribution,
    CureMethod, ForcedSaleNotAuthorised, ForcedSaleTarget, ForcedSaleTrigger,
    LoanStatus, MarginAccountAlgebra, MarginAccountState, MarginAccountStatus,
    MarginCallMonitor, MarginCallStatus, MarginCollateralPosition,
    MarginEventKind, MarginLoan, NoOpenMarginCall, PolicyBound, account_status,
    apply_sale_proceeds, binding_policy, cure_credit, cure_deadline,
    liquidation_sequence, positions_in_scope, top_up_requirement,
    value_to_restore)


# ==========================================================================
# THE MARGIN CALL AND FORCED SALE STATE MACHINE
# --------------------------------------------------------------------------
# Spec 2.8, 2.9, 3.2, 3.3, 3.4. The module docstring above says nothing else
# is tested "because nothing else exists yet"; an engine exists now, and the
# things it can be wrong about are different from the config object's:
#
# 1. **A call is state.** Re-issuing it on every observation, or letting it
#    evaporate when nobody looked, is the defect this whole section exists to
#    prevent. Several tests below drive four sessions to catch exactly that.
# 2. **The tighter of statute and contract binds.** Which means a run that
#    crosses an SSC adjustment must be graded against the floor of the day, not
#    the floor the contract was signed under.
# 3. **A forced sale needs a right.** The one test that matters most here is
#    the one that asks for a liquidation on a healthy account and gets an
#    exception.
# 4. **Nothing unsourced is presented as sourced.** The top-up amounts, the
#    sale sizing, the trigger ranking and the selection order are all ours, and
#    each has an entry in PROVENANCE that a test reads.
# ==========================================================================

MONDAY = date(2026, 3, 2)


def _at(day: int, hour: int = 14, minute: int = 45) -> datetime:
    """An instant in the first full week of March 2026. 2026-03-02 is a Monday."""
    return datetime(2026, 3, day, hour, minute)


def _cal():
    """A Mon-Fri settlement calendar. **Not Tet-correct, and it does not need
    to be** -- every date used below is in March.

    Using the real :class:`VsdcSettlementCalendar` rather than a stub is the
    point: it proves the module's one-method ``BusinessDayCalendar`` Protocol
    is satisfied by the class a caller would actually pass.
    """
    return weekday_settlement_calendar()


def _algebra(*, eb, ab, as_of, account='ACC',
             basis=RatioDetermination.END_OF_DAY, reasons=()):
    """A QD 87 Dieu 2 algebra built from EB and AB alone.

    Everything the state machine reads is derived from those two, so the tests
    can state the one number that matters -- the ratio -- and stay readable.
    """
    ratio = (ab / eb) if eb else None
    status = (MarginAccountStatus.INDETERMINATE if reasons
              else MarginAccountStatus.OK)
    return MarginAccountAlgebra(
        account_id=account, as_of=as_of, basis=basis,
        price_source=PriceSource.LAST_CLOSE,
        accounting_unit=AccountingUnit.ACCOUNT,
        margin_debt=eb - ab,
        cash_and_pending_proceeds=D('0'),
        eligible_securities_value=eb,
        total_assets=eb, net_assets=ab, margin_ratio=ratio,
        initial_margin_ratio=D('0.50'), maintenance_margin_ratio=D('0.35'),
        required_margin_value=D('0'), excess_equity=D('0'),
        buying_power=D('0'), status=status, indeterminate_reasons=reasons)


def _state(*, as_of, account='ACC', loans=(), suspended=False, unpriced=(),
           ineligible=D('0')):
    return MarginAccountState(account_id=account, as_of=as_of, loans=loans,
                              lending_suspended=suspended,
                              unpriced_tickers=unpriced,
                              ineligible_securities_value=ineligible)


def _monitor(broker=None, **kw):
    return MarginCallMonitor('ACC', broker or terms(), _cal(), **kw)


def _observe(monitor, *, eb, ab, day, hour=14, **state_kw):
    """Feed one matched (state, algebra) pair and return the events."""
    ts = _at(day, hour)
    return monitor.observe(_state(as_of=ts, **state_kw),
                           _algebra(eb=eb, ab=ab, as_of=ts))


def _kinds(events):
    return [e.kind for e in events]


# ==========================================================================
# What binds when the statute and the contract both speak -- 2.8, 3.2, 3.4
# ==========================================================================

def test_a_policy_built_from_a_firms_own_regulation_restates_its_terms():
    """The common case must be a no-op, or the split is doing damage.

    A firm whose terms were validated against QD 87 gets exactly its own
    numbers back, and the provenance says the broker chose them because they
    are stricter than the 30 % floor.
    """
    policy = binding_policy(terms())
    assert policy.call_level == D('0.35')
    assert policy.force_sell_level == D('0.32')
    assert policy.cure_business_days == 3
    assert policy.call_level_bound_by is PolicyBound.BROKER
    assert policy.force_sell_level_bound_by is PolicyBound.BROKER
    assert policy.cure_window_bound_by is PolicyBound.BOTH
    assert not policy.levels_collapsed


def test_a_raised_statutory_floor_overrides_a_contract_signed_under_the_old_one():
    """QD 87 Dieu 5.3 lets the SSC move the ratios, and it has moved once.

    The firm signed at 32 % under a 30 % floor. The floor goes to 36 %. Every
    one of that firm's accounts is graded at 36 % from the effective date, with
    no contract amendment -- and the policy says the statute is why.
    """
    stricter = replace(QD_87_2017, maintenance_margin_ratio_floor=D('0.36'))
    policy = binding_policy(terms(), stricter)
    assert policy.call_level == D('0.36')
    assert policy.force_sell_level == D('0.36')
    assert policy.call_level_bound_by is PolicyBound.STATUTE
    assert policy.force_sell_level_bound_by is PolicyBound.STATUTE


def test_a_raised_floor_can_collapse_the_two_levels_and_the_policy_says_so():
    """A run in that state issues no calls at all, and a reader must be told.

    With the floor above the firm's own call level the ``CALL`` band is empty:
    the account goes ``OK`` -> ``FORCE_SELL`` with no window in between.
    """
    policy = binding_policy(
        terms(), replace(QD_87_2017, maintenance_margin_ratio_floor=D('0.40')))
    assert policy.levels_collapsed
    assert account_status(D('0.39'), policy) is MarginAccountStatus.FORCE_SELL
    assert account_status(D('0.40'), policy) is MarginAccountStatus.OK


def test_a_tighter_statutory_cure_ceiling_shortens_a_window_already_agreed():
    """The ceiling is a ceiling. QD 87 Dieu 7.1.

    ``BrokerMarginTerms`` refuses a window longer than the ceiling **of its own
    regulation row**; this is the other half, where the row changes under a
    contract that was legal when written.
    """
    tightened = replace(QD_87_2017, max_cure_business_days=1)
    policy = binding_policy(terms(cure_business_days=3), tightened)
    assert policy.cure_business_days == 1
    assert policy.cure_window_bound_by is PolicyBound.STATUTE


def test_a_stricter_broker_window_binds_over_the_statutory_ceiling():
    """Fewer days is stricter, and stricter is always legal."""
    policy = binding_policy(terms(cure_business_days=1))
    assert policy.cure_business_days == 1
    assert policy.cure_window_bound_by is PolicyBound.BROKER


def test_the_cure_target_never_sits_below_the_call_level():
    """A target under the call level would "cure" an account back into a call.

    ``BrokerMarginTerms`` already refuses that combination directly; the policy
    has to hold the same line after a statutory floor moves underneath it,
    where the firm's stated target is suddenly the lower of the two.
    """
    policy = binding_policy(
        terms(cure_target_ratio=D('0.36')),
        replace(QD_87_2017, maintenance_margin_ratio_floor=D('0.38')))
    assert policy.call_level == D('0.38')
    assert policy.cure_target_ratio == D('0.38')


# ==========================================================================
# Grading one ratio against the two levels -- 3.2
# ==========================================================================

def test_the_ladder_has_two_levels_because_vietnamese_brokers_run_two():
    """Spec 3.2. A model with one threshold cannot express SSI or DNSE."""
    policy = binding_policy(terms())
    assert account_status(D('0.50'), policy) is MarginAccountStatus.OK
    assert account_status(D('0.34'), policy) is MarginAccountStatus.CALL
    assert account_status(D('0.31'), policy) is MarginAccountStatus.FORCE_SELL


def test_a_ratio_exactly_on_a_level_is_not_in_breach_of_it():
    """QD 87 Dieu 5.2 says *khong duoc thap hon* -- not lower than.

    Equality complies. An off-by-one here calls every account that is exactly at
    its maintenance ratio, which is the account a client has just cured.
    """
    policy = binding_policy(terms())
    assert account_status(D('0.35'), policy) is MarginAccountStatus.OK
    assert account_status(D('0.32'), policy) is MarginAccountStatus.CALL


def test_indeterminate_beats_every_other_reading():
    """"The data could not decide" is never "fine"."""
    policy = binding_policy(terms())
    assert account_status(D('0.90'), policy, indeterminate=True) \
        is MarginAccountStatus.INDETERMINATE
    assert account_status(D('0.01'), policy, indeterminate=True) \
        is MarginAccountStatus.INDETERMINATE


def test_suspension_does_not_shelter_an_account_below_the_force_level():
    """TT 120 Dieu 9.9 stops new lending; it does not cure a ratio.

    Collapsing a breaching account to ``SUSPENDED`` would hide exactly the
    accounts an SSC stabilisation order was issued about.
    """
    policy = binding_policy(terms())
    assert account_status(D('0.50'), policy, suspended=True) \
        is MarginAccountStatus.SUSPENDED
    assert account_status(D('0.31'), policy, suspended=True) \
        is MarginAccountStatus.FORCE_SELL
    assert account_status(D('0.34'), policy, suspended=True) \
        is MarginAccountStatus.CALL


def test_an_account_with_no_assets_and_a_debt_is_past_the_point_a_ratio_describes():
    """``EB == 0`` splits on the debt, and neither half is INDETERMINATE.

    Nothing is unknown in either case. No assets and no debt is not a breach;
    no assets and a debt outstanding is QD 87 Dieu 8's shortfall, and it has to
    reach the forced-sale branch so the shortfall gets reported.
    """
    policy = binding_policy(terms())
    assert account_status(None, policy, debt=D('0')) is MarginAccountStatus.OK
    assert account_status(None, policy, debt=D('100')) \
        is MarginAccountStatus.FORCE_SELL


def test_the_grader_refuses_a_float_ratio():
    """House rule, and here it is the whole ladder: ``Decimal('0.30') > 0.3``."""
    with pytest.raises(TypeError, match='never float'):
        account_status(0.34, binding_policy(terms()))


# ==========================================================================
# The DERIVED top-up amounts -- 2.8, and QD 87 Dieu 7.2 is unreadable
# ==========================================================================

def test_each_of_the_three_top_up_amounts_actually_restores_the_target():
    """The arithmetic is ours, so it is checked by re-deriving the ratio.

    QD 87 Dieu 7.2's two formulas are images in every accessible mirror. What
    the module ships is our own algebra, and the only honest test of it is to
    apply each amount to the account and confirm the ratio lands on the target.
    """
    eb, ab, target = D('1000'), D('340'), D('0.35')
    req = top_up_requirement(eb, ab, target)
    assert req.gap == D('10')
    assert req.cash == D('10')

    tiny = D('1e-20')  # Decimal division carries 28 significant digits
    # cash swept against DB: AB rises, EB unchanged
    assert (ab + req.cash) / eb == target
    # posted securities: both rise
    assert abs((ab + req.securities_value) / (eb + req.securities_value)
               - target) < tiny
    # self-directed sale repaying DB: EB falls, AB unchanged
    assert abs(ab / (eb - req.self_sale_value) - target) < tiny


def test_an_account_already_at_the_target_needs_nothing():
    """A negative gap is zero cure, not a negative one."""
    req = top_up_requirement(D('1000'), D('400'), D('0.35'))
    assert req.already_met
    assert (req.cash, req.securities_value, req.self_sale_value) \
        == (D('0'), D('0'), D('0'))


def test_a_target_of_one_is_refused_because_the_securities_top_up_divides_by_zero():
    """Not defensive: it is the arithmetic saying the account cannot be reached.

    A target of 1 is an account with no debt at all, and no amount of posted
    collateral reaches it while any debt remains.
    """
    with pytest.raises(ValueError, match='strictly between 0 and 1'):
        top_up_requirement(D('1000'), D('340'), D('1'))
    with pytest.raises(ValueError, match='strictly between 0 and 1'):
        top_up_requirement(D('1000'), D('340'), D('0'))


def test_the_forced_sale_size_and_the_self_directed_sale_are_the_same_number():
    """A *ban giai chap* is a self-directed sale the CTCK places itself.

    Two names for one formula, and if they ever diverge the machine is sizing a
    forced sale differently from the amount it told the client to raise.
    """
    assert value_to_restore(D('1000'), D('340'), D('0.35')) \
        == top_up_requirement(D('1000'), D('340'), D('0.35')).self_sale_value


def test_an_account_whose_equity_has_gone_negative_cannot_be_sold_back_to_health():
    """QD 87 Dieu 8's shortfall, in the arithmetic rather than in the prose.

    With ``AB <= 0`` the required sale exceeds the whole account, which is the
    formula saying *sell everything and it is still not enough*.
    """
    assert value_to_restore(D('1000'), D('-50'), D('0.35')) > D('1000')


# ==========================================================================
# Curing -- 2.8. Three methods, three different arithmetics.
# ==========================================================================

def test_cash_swept_against_the_debt_is_worth_more_than_cash_left_in_the_account():
    """ACBS sweeps deposits against debt at end of day; the difference is real.

    Repaying ``DB`` raises ``AB`` without raising ``EB``. Cash sitting in ``CB``
    raises both, so it moves the ratio less -- by a factor of ``1 - target``.
    """
    swept = CureContribution(CureMethod.DEPOSIT_CASH, D('100'), _at(2))
    parked = CureContribution(CureMethod.DEPOSIT_CASH, D('100'), _at(2),
                              applied_to_debt=False)
    assert cure_credit(swept, D('0.35')) == D('100')
    assert cure_credit(parked, D('0.35')) == D('65')


def test_a_self_directed_sale_that_does_not_repay_the_debt_cures_nothing():
    """``PV`` falls, ``CB`` rises by the same amount, and the ratio does not move.

    This is the least obvious fact in the section and the one an engine is most
    likely to get wrong by crediting the sale. A client who sells stock in
    answer to a call and leaves the money in the account has done nothing.
    """
    kept = CureContribution(CureMethod.SELL_SECURITIES, D('1000'), _at(2),
                            applied_to_debt=False)
    repaid = CureContribution(CureMethod.SELL_SECURITIES, D('1000'), _at(2))
    assert cure_credit(kept, D('0.35')) == D('0')
    assert cure_credit(repaid, D('0.35')) == D('350')


def test_a_mixed_cure_adds_up_because_every_method_is_scored_in_one_unit():
    """QD 87 Dieu 7 offers three methods and gives no arithmetic for combining
    them. Scoring each into the same cash-equivalent gap is what makes a
    part-cash part-collateral answer countable at all.
    """
    target = D('0.35')
    cash = CureContribution(CureMethod.DEPOSIT_CASH, D('4'), _at(2))
    stock = CureContribution(CureMethod.POST_SECURITIES, D('10'), _at(2))
    total = cure_credit(cash, target) + cure_credit(stock, target)
    assert total == D('4') + D('6.5')


def test_a_contribution_of_nothing_is_refused_at_construction():
    """Dieu 8 distinguishes failing to top up from topping up ONLY PARTIALLY.

    Zero is neither: it is the caller recording an event that did not happen.
    """
    with pytest.raises(ValueError, match='strictly positive'):
        CureContribution(CureMethod.DEPOSIT_CASH, D('0'), _at(2))


# ==========================================================================
# The cure clock -- 2.8, QD 87 Dieu 7.1
# ==========================================================================

def test_the_deadline_is_business_days_out_at_the_same_time_of_day():
    """The article gives a count of business days and no time of day.

    Anchoring to the call instant is ours and is declared. Midnight would
    silently shorten every window by most of a day.
    """
    issued = _at(2, 14, 45)
    assert cure_deadline(issued, 3, _cal()) == _at(5, 14, 45)


def test_the_window_steps_over_a_weekend():
    """*Ngay lam viec*, not calendar days. Three from a Friday lands on Wednesday."""
    assert cure_deadline(_at(6, 9), 3, _cal()) == _at(11, 9)


def test_a_real_settlement_calendar_satisfies_the_one_method_protocol():
    """The Protocol exists to keep the import fence, not to invent a type.

    If ``VsdcSettlementCalendar`` ever stops matching it, every deadline in the
    module needs a new source object -- which is worth failing loudly over.
    """
    assert isinstance(_cal(), BusinessDayCalendar)


# ==========================================================================
# Selection and scope -- 2.9, 3.3. SILENT in the regulation.
# ==========================================================================

def _positions():
    return (
        MarginCollateralPosition('AAA', 100, D('10'), loan_ratio=D('0.50'),
                                 unrealised_pnl=D('-50')),
        MarginCollateralPosition('BBB', 500, D('4'), loan_ratio=D('0.20'),
                                 unrealised_pnl=D('-500'), is_breaching=True),
        MarginCollateralPosition('CCC', 10, D('300'), loan_ratio=D('0.40'),
                                 unrealised_pnl=D('20')),
    )


def test_each_stated_liquidation_order_reaches_for_a_different_position_first():
    """No Vietnamese document prescribes an order -- QD 87 Dieu 12.2(i)
    delegates it to the contract by name. What the module owes is that a firm
    which states one gets it, and the four orderings really are four.
    """
    ps = _positions()
    first = lambda o: liquidation_sequence(ps, o)[0].ticker  # noqa: E731
    assert first(LiquidationOrder.BREACHING_FIRST) == 'BBB'
    assert first(LiquidationOrder.LARGEST_LOSS_FIRST) == 'BBB'
    assert first(LiquidationOrder.LARGEST_POSITION_FIRST) == 'CCC'
    assert first(LiquidationOrder.LOWEST_LOAN_RATIO_FIRST) == 'BBB'
    assert liquidation_sequence(ps, LiquidationOrder.BROKER_RANKED,
                                ranking=('CCC', 'AAA'))[0].ticker == 'CCC'


def test_broker_ranked_without_a_ranking_is_refused_rather_than_sorted():
    """The member means "the contract states a list". With no list it would
    degenerate into an alphabetical sort -- an ordering nobody chose, wearing a
    stated policy's name.
    """
    with pytest.raises(ValueError, match='needs an explicit ranking'):
        liquidation_sequence(_positions(), LiquidationOrder.BROKER_RANKED)


def test_a_position_with_no_known_loss_sorts_last_not_first():
    """An unknown loss is not evidence of a large one.

    Sorting unknowns first would liquidate the positions the caller knows least
    about, which is the opposite of conservative.
    """
    ps = (MarginCollateralPosition('AAA', 10, D('10'), unrealised_pnl=None),
          MarginCollateralPosition('BBB', 10, D('10'), unrealised_pnl=D('-1')))
    order = liquidation_sequence(ps, LiquidationOrder.LARGEST_LOSS_FIRST)
    assert [p.ticker for p in order] == ['BBB', 'AAA']


def test_the_sequence_does_not_depend_on_the_order_the_caller_built_the_list_in():
    """Two runs of one scenario must liquidate the same stock in the same order,
    or a reproduced result is not reproduced.
    """
    ps = _positions()
    for order in LiquidationOrder:
        if order is LiquidationOrder.BROKER_RANKED:
            continue
        forwards = liquidation_sequence(ps, order)
        backwards = liquidation_sequence(tuple(reversed(ps)), order)
        assert [p.ticker for p in forwards] == [p.ticker for p in backwards]


def test_a_breaching_position_scope_with_nothing_flagged_is_refused():
    """An empty scope and an empty account look identical downstream.

    A sale that silently sells nothing because the caller forgot to flag a deal
    is worse than an exception, because the run reports a liquidation that did
    not happen.
    """
    unflagged = (MarginCollateralPosition('AAA', 10, D('10')),)
    with pytest.raises(ValueError, match='nothing identifies the breaching'):
        positions_in_scope(unflagged, ForcedSaleScope.BREACHING_POSITION)


def test_the_breaching_scope_leaves_the_rest_of_the_sub_account_alone():
    """DNSE sells only the breaching deal's stock. REPORTED, at one firm."""
    scoped = positions_in_scope(_positions(),
                                ForcedSaleScope.BREACHING_POSITION)
    assert [p.ticker for p in scoped] == ['BBB']
    assert len(positions_in_scope(_positions(),
                                  ForcedSaleScope.WHOLE_ACCOUNT)) == 3


# ==========================================================================
# Applying the proceeds -- 2.9. The residual is VERIFIED; the order is SILENT.
# ==========================================================================

def test_the_stated_order_decides_which_component_goes_unpaid():
    """The whole reason QD 87 Dieu 12.2(i) makes it a contract term.

    Order is invisible when the proceeds cover everything. It decides who eats
    the loss when they do not, and two firms with different contracts leave
    different debts behind on identical facts.
    """
    owed = {ProceedsComponent.PRINCIPAL: D('100'),
            ProceedsComponent.INTEREST: D('30'),
            ProceedsComponent.FEES: D('10'),
            ProceedsComponent.TAXES: D('5')}
    principal_first = apply_sale_proceeds(
        D('100'), owed,
        (ProceedsComponent.PRINCIPAL, ProceedsComponent.INTEREST,
         ProceedsComponent.FEES, ProceedsComponent.TAXES))
    taxes_first = apply_sale_proceeds(
        D('100'), owed,
        (ProceedsComponent.TAXES, ProceedsComponent.FEES,
         ProceedsComponent.INTEREST, ProceedsComponent.PRINCIPAL))
    assert principal_first.unpaid[ProceedsComponent.PRINCIPAL] == D('0')
    assert taxes_first.unpaid[ProceedsComponent.PRINCIPAL] == D('45')
    assert not principal_first.fully_discharged
    assert not taxes_first.fully_discharged


def test_the_client_gets_only_what_is_left_after_the_debt():
    """QD 87 Dieu 8, VERIFIED -- *phan con lai sau khi tru no ky quy*."""
    application = apply_sale_proceeds(
        D('200'), {ProceedsComponent.PRINCIPAL: D('100'),
                   ProceedsComponent.INTEREST: D('20')},
        tuple(ProceedsComponent))
    assert application.residual == D('80')
    assert application.fully_discharged


def test_applying_proceeds_refuses_an_order_that_names_only_some_components():
    """A partial order leaves a component unpriced, so the residual hands the
    client money that is owed elsewhere. Dieu 12.2(i) delegates the priority by
    name: it is stated in full or not at all.
    """
    with pytest.raises(ValueError, match='exactly once'):
        apply_sale_proceeds(D('10'), {},
                            (ProceedsComponent.PRINCIPAL,
                             ProceedsComponent.INTEREST))


# ==========================================================================
# The state machine: a call is STATE
# ==========================================================================

def test_a_call_issues_once_and_survives_the_days_that_follow():
    """**The headline test of this section.**

    Four sessions, one unchanged breach. A machine that re-issued the call on
    every observation would turn one three-business-day obligation into three,
    and would reset the clock each time -- which is the bug the
    state-versus-event distinction exists to prevent, and the same lesson the
    derivatives deposit already learned.
    """
    m = _monitor()
    monday = _observe(m, eb=D('1000'), ab=D('340'), day=2)
    assert _kinds(monday) == [MarginEventKind.CALL_ISSUED]
    call_id = m.open_call.call_id

    assert _observe(m, eb=D('1000'), ab=D('340'), day=3) == ()
    # The third distinct breach day trips SSI's consecutive-breach clock, which
    # is a separate mechanism running alongside the call -- and note what it is
    # NOT: a second call.
    assert _kinds(_observe(m, eb=D('1000'), ab=D('340'), day=4)) \
        == [MarginEventKind.FORCED_SALE_DUE]
    assert m.forced_sale_due is ForcedSaleTrigger.CONSECUTIVE_BREACH_DAYS

    assert m.open_call is not None
    assert m.open_call.call_id == call_id
    assert len(m.calls) == 1
    assert m.open_call.status is MarginCallStatus.OPEN


def test_the_call_carries_the_derived_amounts_the_deadline_and_the_methods():
    """What the client is actually told, and where each number came from."""
    m = _monitor()
    (event,) = _observe(m, eb=D('1000'), ab=D('340'), day=2)
    call = m.open_call
    assert call.deadline == _at(5)
    assert call.target_ratio == D('0.35')
    assert call.ratio_at_issue == D('0.34')
    assert call.top_up_cash == D('10')
    assert call.cure_methods == QD_87_2017.cure_methods
    assert 'DERIVED' in event.detail['top_up_grade']
    assert event.detail['cure_window_bound_by'] is PolicyBound.BOTH


def test_no_call_is_invented_on_the_way_past_the_force_level():
    """SSI force-sells immediately on breaching *TLKQ xu ly*.

    Issuing a call there would grant a three-day cure right the contract does
    not give, and would delay a liquidation the firm performs at once.
    """
    m = _monitor()
    events = _observe(m, eb=D('1000'), ab=D('310'), day=2)
    assert _kinds(events) == [MarginEventKind.FORCED_SALE_DUE]
    assert m.open_call is None
    assert m.forced_sale_due is ForcedSaleTrigger.FORCE_LEVEL_BREACHED


def test_a_restored_ratio_cures_the_call_and_that_is_the_authoritative_test():
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('340'), day=2)
    events = _observe(m, eb=D('1000'), ab=D('400'), day=3)
    assert _kinds(events) == [MarginEventKind.CALL_CURED]
    assert events[0].detail['by'] == 'observed ratio'
    assert m.open_call is None
    assert m.calls[-1].status is MarginCallStatus.CURED
    assert m.calls[-1].cured_at == _at(3)


def test_a_partial_top_up_leaves_the_call_open():
    """QD 87 Dieu 8 gives the sale right where the client *tops up only
    partially*, so a partial cure is not a cure -- and the call has to stay open
    or the deadline it carries stops meaning anything.
    """
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('340'), day=2)
    (event,) = m.cure(CureContribution(CureMethod.DEPOSIT_CASH, D('4'), _at(3)))
    assert event.kind is MarginEventKind.CALL_PARTIALLY_CURED
    assert event.detail['shortfall'] == D('6')
    assert m.open_call.status is MarginCallStatus.PARTIALLY_CURED
    assert m.open_call.is_open


def test_a_full_top_up_closes_the_call_and_says_the_closure_is_provisional():
    """The requirement is the DERIVED gap at issue, which is what the client was
    told to pay. The ratio at the next observation is the real test, and the
    event says so rather than the docstring alone.
    """
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('340'), day=2)
    (event,) = m.cure(CureContribution(CureMethod.DEPOSIT_CASH, D('10'),
                                       _at(3)))
    assert event.kind is MarginEventKind.CALL_CURED
    assert event.detail['provisional'] is True
    assert m.open_call is None
    assert m.calls[-1].status is MarginCallStatus.CURED


def test_a_cure_on_an_account_nobody_called_is_refused():
    """Money arriving at an uncalled account is a deposit, not a cure, and the
    two have different consequences for the Dieu 13.8 book.
    """
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('400'), day=2)
    with pytest.raises(NoOpenMarginCall, match='no call is outstanding'):
        m.cure(CureContribution(CureMethod.DEPOSIT_CASH, D('10'), _at(2)))


def test_a_cure_stamped_after_the_deadline_is_refused():
    """Once the window closes the Dieu 8 right has arisen.

    Absorbing a late payment would let a client with a fast bank transfer unmake
    a right that already existed. The money is not lost -- the restored ratio
    clears the account at the next observation -- but the right is not unmade.
    """
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('340'), day=2)
    with pytest.raises(ValueError, match='after the cure deadline'):
        m.cure(CureContribution(CureMethod.DEPOSIT_CASH, D('10'), _at(6)))


def test_a_cure_method_the_call_does_not_accept_is_refused():
    """QD 87 Dieu 7 names three methods; a firm may accept fewer, and a call
    that accepted a method it does not offer would credit a cure that never
    reached the account.
    """
    only_cash = replace(QD_87_2017, cure_methods=(CureMethod.DEPOSIT_CASH,))
    m = _monitor(regulation=only_cash)
    _observe(m, eb=D('1000'), ab=D('340'), day=2)
    with pytest.raises(ValueError, match='not among the cure methods'):
        m.cure(CureContribution(CureMethod.POST_SECURITIES, D('20'), _at(3)))


def test_the_deadline_expires_the_call_and_makes_a_sale_due():
    """QD 87 Dieu 7.1 sets the window; Dieu 8 gives the right the moment it
    closes. Both events fire, in that order, so a log can join them.
    """
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('340'), day=2)
    events = _observe(m, eb=D('1000'), ab=D('340'), day=5)
    assert _kinds(events)[:2] == [MarginEventKind.CALL_EXPIRED,
                                  MarginEventKind.FORCED_SALE_DUE]
    assert m.calls[-1].status is MarginCallStatus.EXPIRED
    assert m.forced_sale_due is ForcedSaleTrigger.CURE_WINDOW_EXPIRED


def test_a_blind_observation_advances_nothing_and_a_deadline_survives_it():
    """Clearing a call on a blind mark would report a cure nobody paid; expiring
    one would sell an account against a price nobody saw.

    A deadline falling inside a blind stretch therefore survives it and bites on
    the first observation that has data -- the conservative direction, and what
    a broker does when its price feed is down.
    """
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('340'), day=2)
    ts = _at(5)
    blind = m.observe(_state(as_of=ts, unpriced=('AAA',)),
                      _algebra(eb=D('1000'), ab=D('340'), as_of=ts,
                               reasons=('no price for AAA',)))
    assert _kinds(blind) == [MarginEventKind.INDETERMINATE]
    assert m.open_call is not None
    assert m.open_call.status is MarginCallStatus.OPEN
    assert m.forced_sale_due is None
    assert m.last_status is MarginAccountStatus.INDETERMINATE

    with_data = _observe(m, eb=D('1000'), ab=D('340'), day=6)
    assert MarginEventKind.CALL_EXPIRED in _kinds(with_data)


def test_a_blind_stretch_is_reported_once_not_on_every_observation():
    """It is a state, like the call is."""
    m = _monitor()
    for day in (2, 3):
        ts = _at(day)
        events = m.observe(_state(as_of=ts, unpriced=('AAA',)),
                           _algebra(eb=D('1000'), ab=D('340'), as_of=ts,
                                    reasons=('no price',)))
        assert _kinds(events) == ([MarginEventKind.INDETERMINATE] if day == 2
                                 else [])


def test_the_breach_day_counter_is_not_reset_by_a_cure():
    """The interlock behind SSI's consecutive-breach rule.

    A client who tops up just enough each morning to clear the call, and is back
    in breach by the close, never resets this counter and is force-sold on the
    third day. Only an observed ratio at or above the call level clears it.
    """
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('340'), day=2)
    m.cure(CureContribution(CureMethod.DEPOSIT_CASH, D('10'), _at(2, 15)))
    _observe(m, eb=D('1000'), ab=D('340'), day=3)
    _observe(m, eb=D('1000'), ab=D('340'), day=4)
    assert len(m.breach_days) == 3
    assert ForcedSaleTrigger.CONSECUTIVE_BREACH_DAYS in m.forced_sale_triggers


def test_an_observation_back_at_the_call_level_clears_the_breach_counter():
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('340'), day=2)
    _observe(m, eb=D('1000'), ab=D('400'), day=3)
    assert m.breach_days == ()


def test_last_status_is_none_before_anyone_has_looked():
    """An unobserved account is not ``OK``. Defaulting it to ``OK`` would let a
    account nobody priced read as compliant.
    """
    assert _monitor().last_status is None


def test_an_observation_that_goes_backwards_in_time_is_refused():
    """The cure clock, the breach counter and the call history are all ordered."""
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('340'), day=4)
    with pytest.raises(ValueError, match='earlier than the last one'):
        _observe(m, eb=D('1000'), ab=D('340'), day=3)


def test_an_intraday_algebra_at_an_end_of_day_firm_is_refused():
    """QD 87 Dieu 6.1 mandates end-of-day; intraday is a broker option and the
    2026 market reality. A run configured for the statutory floor behaviour and
    fed intraday marks is reporting a regime it did not run.
    """
    m = _monitor()
    ts = _at(2)
    with pytest.raises(ValueError, match='INTRADAY algebra'):
        m.observe(_state(as_of=ts),
                  _algebra(eb=D('1000'), ab=D('340'), as_of=ts,
                           basis=RatioDetermination.INTRADAY))


def test_an_intraday_algebra_is_accepted_where_the_firm_says_it_sweeps():
    m = _monitor(terms(intraday_monitoring=True, monitor_interval_minutes=60,
                       price_source=PriceSource.LIVE_MARKET))
    ts = _at(2)
    events = m.observe(_state(as_of=ts),
                       _algebra(eb=D('1000'), ab=D('340'), as_of=ts,
                                basis=RatioDetermination.INTRADAY))
    assert _kinds(events) == [MarginEventKind.CALL_ISSUED]


def test_a_state_and_an_algebra_from_different_instants_are_refused():
    """The algebra is a pure function of the state. A mismatch grades
    yesterday's ratio against today's loans, and nothing downstream can tell.
    """
    m = _monitor()
    with pytest.raises(ValueError, match='as of'):
        m.observe(_state(as_of=_at(2)),
                  _algebra(eb=D('1000'), ab=D('340'), as_of=_at(3)))


def test_a_state_for_another_account_is_refused():
    """TT 120 Dieu 9.3 -- one monitor is one segregated account."""
    m = _monitor()
    ts = _at(2)
    with pytest.raises(ValueError, match='segregated'):
        m.observe(_state(as_of=ts, account='OTHER'),
                  _algebra(eb=D('1000'), ab=D('340'), as_of=ts))


def test_suspension_and_resumption_each_report_once():
    """TT 120 Dieu 9.9 and Dieu 9.7. New lending stops; the debt does not."""
    m = _monitor()
    first = _observe(m, eb=D('1000'), ab=D('400'), day=2, suspended=True)
    assert _kinds(first) == [MarginEventKind.LENDING_SUSPENDED]
    assert _observe(m, eb=D('1000'), ab=D('400'), day=3, suspended=True) == ()
    back = _observe(m, eb=D('1000'), ab=D('400'), day=4)
    assert _kinds(back) == [MarginEventKind.LENDING_RESUMED]
    assert m.last_status is MarginAccountStatus.OK


def test_collateral_leaving_the_list_is_reported_and_does_not_sell_by_default():
    """TT 120 Dieu 9.6 excludes it from the collateral base for both ratios --
    that part is statutory and lands in the ratio by lowering ``PV``. Whether
    the firm also liquidates on it is nowhere stated, so it does not.
    """
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('340'), day=2, ineligible=D('0'))
    events = _observe(m, eb=D('1000'), ab=D('340'), day=3,
                      ineligible=D('120'))
    assert _kinds(events) == [MarginEventKind.COLLATERAL_BECAME_INELIGIBLE]
    assert ForcedSaleTrigger.COLLATERAL_INELIGIBLE not in m.forced_sale_triggers


def test_a_firm_that_liquidates_on_ineligible_collateral_can_say_so():
    """And even then the account has to be in actual breach: selling because a
    ticker left the list while the ratio is comfortable is a disposal with no
    rule behind it.
    """
    m = _monitor(sell_on_ineligible_collateral=True)
    _observe(m, eb=D('1000'), ab=D('400'), day=2, ineligible=D('120'))
    assert ForcedSaleTrigger.COLLATERAL_INELIGIBLE not in m.forced_sale_triggers
    _observe(m, eb=D('1000'), ab=D('340'), day=3, ineligible=D('120'))
    assert ForcedSaleTrigger.COLLATERAL_INELIGIBLE in m.forced_sale_triggers


def test_an_overdue_loan_makes_a_sale_due_with_no_call_anywhere_in_sight():
    """SSI force-sells on debt overdue >= 3 business days; ACBS starts on the
    5th. The two firms disagree, which is exactly why it is a broker term -- and
    the ratio can be perfectly healthy throughout.
    """
    loan = MarginLoan(loan_id='L1', account_id='ACC', principal=D('100'),
                      disbursed_on=date(2026, 1, 5), due_on=MONDAY,
                      status=LoanStatus.OVERDUE)
    m = _monitor()
    assert _observe(m, eb=D('1000'), ab=D('900'), day=2, loans=(loan,)) == ()
    events = _observe(m, eb=D('1000'), ab=D('900'), day=5, loans=(loan,))
    assert _kinds(events) == [MarginEventKind.FORCED_SALE_DUE]
    assert m.forced_sale_due is ForcedSaleTrigger.LOAN_OVERDUE
    assert m.open_call is None


# ==========================================================================
# The forced sale -- 2.9, 3.3
# ==========================================================================

def test_forcing_a_sale_on_an_account_with_no_right_is_impossible():
    """**The other headline test.**

    QD 87 Dieu 8 gives the CTCK the right to sell a client's property in
    stated circumstances only. Outside them a liquidation is the disposal of
    somebody else's property, and no argument from the caller creates the right:
    ``plan_forced_sale`` takes no trigger, it derives one.
    """
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('900'), day=2)
    with pytest.raises(ForcedSaleNotAuthorised) as excinfo:
        m.plan_forced_sale(_positions(),
                           _algebra(eb=D('1000'), ab=D('900'), as_of=_at(2)))
    assert excinfo.value.status is MarginAccountStatus.OK
    assert 'Dieu 8' in str(excinfo.value)


def test_a_call_alone_does_not_authorise_a_sale_before_its_window_closes():
    """The cure window is the client's, and the whole point of it."""
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('340'), day=2)
    assert m.open_call is not None
    with pytest.raises(ForcedSaleNotAuthorised):
        m.plan_forced_sale(_positions(),
                           _algebra(eb=D('1000'), ab=D('340'), as_of=_at(2)))


def test_the_sale_sells_just_enough_to_restore_the_target():
    """ACBS sells only enough to bring the ratio back to the maintenance level;
    DNSE never sells the whole deal by default. REPORTED at two firms, and the
    reading closest to Dieu 7's *at least mmr*.

    The size is checked by re-deriving: one share fewer leaves the account still
    in breach.
    """
    m = _monitor(terms(liquidation_order=LiquidationOrder.LARGEST_POSITION_FIRST))
    _observe(m, eb=D('1000'), ab=D('310'), day=2)
    positions = (MarginCollateralPosition('AAA', 1000, D('10')),)
    plan, _ = m.plan_forced_sale(
        positions, _algebra(eb=D('1000'), ab=D('310'), as_of=_at(2)),
        notified_at=_at(2, 14, 40))

    assert len(plan.instructions) == 1
    sold = plan.instructions[0].quantity
    assert sold == 12
    assert D('310') / (D('1000') - sold * D('10')) >= D('0.35')
    assert D('310') / (D('1000') - (sold - 1) * D('10')) < D('0.35')
    assert plan.restores_target
    assert plan.shortfall == D('0')


def test_the_sale_follows_the_order_the_firm_stated_and_reports_it():
    """An adopted ordering that reports itself is the whole point of the field.

    Two firms, identical accounts, different contracts: different stock is sold.
    """
    positions = (
        MarginCollateralPosition('AAA', 100, D('10'), loan_ratio=D('0.50')),
        MarginCollateralPosition('BBB', 100, D('10'), loan_ratio=D('0.10')),
    )
    sold = {}
    for order in (LiquidationOrder.LOWEST_LOAN_RATIO_FIRST,
                  LiquidationOrder.BROKER_RANKED):
        m = _monitor(terms(liquidation_order=order),
                     broker_ranking=('AAA', 'BBB'))
        _observe(m, eb=D('1000'), ab=D('310'), day=2)
        plan, _ = m.plan_forced_sale(
            positions, _algebra(eb=D('1000'), ab=D('310'), as_of=_at(2)))
        sold[order] = plan.instructions[0].ticker
        assert plan.selection_order is order
    assert sold[LiquidationOrder.LOWEST_LOAN_RATIO_FIRST] == 'BBB'
    assert sold[LiquidationOrder.BROKER_RANKED] == 'AAA'


def test_a_caller_may_plug_in_an_ordering_the_five_members_do_not_describe():
    """The order is SILENT in the regulation, so the policy is a plug -- and the
    default plug invents nothing, it dispatches on a field with no default.
    """
    def reverse_alphabetical(positions, order, *, ranking=()):
        return tuple(sorted(positions, key=lambda p: p.ticker, reverse=True))

    m = _monitor(selector=reverse_alphabetical)
    _observe(m, eb=D('1000'), ab=D('310'), day=2)
    plan, _ = m.plan_forced_sale(
        _positions(), _algebra(eb=D('1000'), ab=D('310'), as_of=_at(2)))
    assert plan.instructions[0].ticker == 'CCC'


def test_a_shortfall_is_reported_and_not_papered_over():
    """QD 87 Dieu 8: where liquidation does not cover ``DB`` and the client does
    not pay the residual, the CTCK recovers it under the contract and general
    law. An engine that quietly sold everything and reported success would erase
    the only case the article bothers to legislate for.
    """
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('-50'), day=2)
    plan, _ = m.plan_forced_sale(
        (MarginCollateralPosition('AAA', 50, D('10')),),
        _algebra(eb=D('1000'), ab=D('-50'), as_of=_at(2)))
    assert not plan.restores_target
    assert plan.shortfall > D('0')
    assert plan.value_available == D('500')


def test_an_empty_scope_is_the_right_existing_and_not_being_exercisable():
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('310'), day=2)
    plan, events = m.plan_forced_sale(
        (), _algebra(eb=D('1000'), ab=D('310'), as_of=_at(2)))
    assert plan.instructions == ()
    assert 'nothing sellable in scope' in plan.note
    assert m.forced_sale_due is ForcedSaleTrigger.FORCE_LEVEL_BREACHED


def test_an_unpriced_holding_is_reported_rather_than_sold_at_a_guess():
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('310'), day=2)
    plan, _ = m.plan_forced_sale(
        (MarginCollateralPosition('AAA', 100, None),
         MarginCollateralPosition('BBB', 100, D('10'))),
        _algebra(eb=D('1000'), ab=D('310'), as_of=_at(2)))
    assert plan.unsellable == ('AAA',)
    assert [i.ticker for i in plan.instructions] == ['BBB']


def test_the_engine_never_manufactures_the_notice_it_is_required_to_send():
    """QD 87 Dieu 8 requires notice BEFORE the sell order.

    The tickets are still produced without one, because an engine that refused
    to represent the un-noticed case could not report the breach -- and one that
    stamped its own notice would report a compliance it never earned.
    """
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('310'), day=2)
    plan, events = m.plan_forced_sale(
        (MarginCollateralPosition('AAA', 1000, D('10')),),
        _algebra(eb=D('1000'), ab=D('310'), as_of=_at(2)))
    assert not plan.notice_satisfied
    assert 'NO CLIENT NOTICE RECORDED' in plan.note
    assert MarginEventKind.FORCED_SALE_NOTICED not in _kinds(events)
    assert events[0].detail['notice_satisfied'] is False


def test_a_notice_before_the_order_satisfies_the_article_and_is_logged():
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('310'), day=2)
    plan, events = m.plan_forced_sale(
        (MarginCollateralPosition('AAA', 1000, D('10')),),
        _algebra(eb=D('1000'), ab=D('310'), as_of=_at(2)),
        notified_at=_at(2, 14, 30), disclosed_at=_at(2, 14, 0))
    assert plan.notice_satisfied
    assert _kinds(events) == [MarginEventKind.FORCED_SALE_NOTICED,
                              MarginEventKind.FORCED_SALE_INSTRUCTED]
    assert events[0].detail['before_the_order'] is True


def test_planning_consumes_the_authority_so_one_right_is_one_sale():
    """A right that survived being exercised would let a caller loop and
    liquidate the account twice on one breach. The next observation decides
    afresh, from the ratio that the first sale produced.
    """
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('310'), day=2)
    m.plan_forced_sale((MarginCollateralPosition('AAA', 1000, D('10')),),
                       _algebra(eb=D('1000'), ab=D('310'), as_of=_at(2)))
    assert m.forced_sale_due is None
    with pytest.raises(ForcedSaleNotAuthorised):
        m.plan_forced_sale((MarginCollateralPosition('AAA', 1000, D('10')),),
                           _algebra(eb=D('1000'), ab=D('310'), as_of=_at(2)))


def test_the_escalated_call_joins_the_instruction_it_produced():
    """``MarginCallStatus.ESCALATED`` exists so the call log and the sale log are
    joinable, which is what QD 87 Dieu 13.8's per-account book needs.
    """
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('340'), day=2)
    call_id = m.open_call.call_id
    _observe(m, eb=D('1000'), ab=D('340'), day=5)
    plan, _ = m.plan_forced_sale(
        (MarginCollateralPosition('AAA', 1000, D('10')),),
        _algebra(eb=D('1000'), ab=D('340'), as_of=_at(5)))
    assert plan.call_id == call_id
    assert plan.instructions[0].call_id == call_id
    assert m.calls[-1].status is MarginCallStatus.ESCALATED


def test_the_expired_right_lapses_if_the_ratio_recovers_before_the_sale():
    """OUR READING, and declared. The Dieu 8 right had arisen; selling a
    compliant account is the disposal the authority check exists to prevent.
    The call keeps its EXPIRED status in the book -- only the right goes.
    """
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('340'), day=2)
    _observe(m, eb=D('1000'), ab=D('340'), day=5)
    assert m.forced_sale_due is ForcedSaleTrigger.CURE_WINDOW_EXPIRED
    events = _observe(m, eb=D('1000'), ab=D('500'), day=6)
    assert _kinds(events) == [MarginEventKind.CALL_CURED]
    assert events[0].detail['after_expiry'] is True
    assert m.forced_sale_due is None
    assert m.calls[-1].status is MarginCallStatus.EXPIRED


def test_more_than_one_trigger_at_once_is_normal_and_all_of_them_are_kept():
    """No document ranks the five, so the plan carries them all and the ranking
    only decides which one lands in the single-valued instruction field.
    """
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('340'), day=2)
    _observe(m, eb=D('1000'), ab=D('340'), day=3)
    events = _observe(m, eb=D('1000'), ab=D('310'), day=5)
    assert set(m.forced_sale_triggers) >= {
        ForcedSaleTrigger.FORCE_LEVEL_BREACHED,
        ForcedSaleTrigger.CURE_WINDOW_EXPIRED,
        ForcedSaleTrigger.CONSECUTIVE_BREACH_DAYS}
    assert m.forced_sale_due is ForcedSaleTrigger.FORCE_LEVEL_BREACHED
    assert list(m.forced_sale_triggers) == sorted(
        m.forced_sale_triggers, key=FORCED_SALE_TRIGGER_PRIORITY.index)


def test_the_target_buffer_oversells_on_purpose_and_only_when_asked():
    """``MAINTENANCE`` and ``MAINTENANCE_PLUS_BUFFER`` are identical until a
    caller sets a buffer -- the overshoot is unsourced as a policy.
    """
    plain = _monitor()
    buffered = _monitor(terms(
        forced_sale_target=ForcedSaleTarget.MAINTENANCE_PLUS_BUFFER,
        forced_sale_target_buffer=D('0.05')))
    quantities = []
    for m in (plain, buffered):
        _observe(m, eb=D('1000'), ab=D('310'), day=2)
        plan, _ = m.plan_forced_sale(
            (MarginCollateralPosition('AAA', 1000, D('10')),),
            _algebra(eb=D('1000'), ab=D('310'), as_of=_at(2)))
        quantities.append(plan.instructions[0].quantity)
    assert quantities[1] > quantities[0]


def test_results_are_reported_afterwards_because_the_article_requires_it():
    """QD 87 Dieu 8 requires notice before **and a statement of results after**.
    An engine that modelled only the notice would report half the duty.
    """
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('310'), day=2)
    plan, _ = m.plan_forced_sale(
        (MarginCollateralPosition('AAA', 1000, D('10')),),
        _algebra(eb=D('1000'), ab=D('310'), as_of=_at(2)))
    (event,) = m.report_sale_results(plan.instructions[0].instruction_id,
                                     _at(2, 15), filled_quantity=8,
                                     average_price=D('9.8'))
    assert event.kind is MarginEventKind.FORCED_SALE_RESULT_SENT
    assert event.detail['unfilled'] == 4
    assert event.instruction_id == plan.instructions[0].instruction_id


def test_results_cannot_be_reported_for_a_ticket_this_monitor_never_raised():
    m = _monitor()
    with pytest.raises(LookupError, match='not an instruction'):
        m.report_sale_results('made-up', _at(2), filled_quantity=1)


def test_a_fill_larger_than_the_ticket_is_refused():
    m = _monitor()
    _observe(m, eb=D('1000'), ab=D('310'), day=2)
    plan, _ = m.plan_forced_sale(
        (MarginCollateralPosition('AAA', 1000, D('10')),),
        _algebra(eb=D('1000'), ab=D('310'), as_of=_at(2)))
    with pytest.raises(ValueError, match='outside the ticket'):
        m.report_sale_results(plan.instructions[0].instruction_id, _at(2, 15),
                              filled_quantity=9999)


def test_one_breach_walks_the_whole_machine_and_every_step_is_an_event():
    """The end-to-end path, as a single readable sequence.

    Call issues, is partially answered, expires, becomes a sale, is noticed,
    instructed and reported on. Anything that stops emitting one of these makes
    a legal obligation invisible in the log a caller polls.
    """
    m = _monitor()
    log = []
    log += _observe(m, eb=D('1000'), ab=D('340'), day=2)
    log += m.cure(CureContribution(CureMethod.DEPOSIT_CASH, D('4'), _at(3)))
    log += _observe(m, eb=D('1000'), ab=D('340'), day=5)
    plan, events = m.plan_forced_sale(
        (MarginCollateralPosition('AAA', 1000, D('10')),),
        _algebra(eb=D('1000'), ab=D('340'), as_of=_at(5)),
        notified_at=_at(5, 14, 30))
    log += events
    log += m.report_sale_results(plan.instructions[0].instruction_id,
                                 _at(5, 15),
                                 filled_quantity=plan.instructions[0].quantity)
    assert _kinds(log) == [
        MarginEventKind.CALL_ISSUED,
        MarginEventKind.CALL_PARTIALLY_CURED,
        MarginEventKind.CALL_EXPIRED,
        MarginEventKind.FORCED_SALE_DUE,
        MarginEventKind.FORCED_SALE_NOTICED,
        MarginEventKind.FORCED_SALE_INSTRUCTED,
        MarginEventKind.FORCED_SALE_RESULT_SENT,
    ]
    assert all(e.account_id == 'ACC' for e in log)


# ==========================================================================
# Nothing unsourced is presented as sourced
# ==========================================================================

def test_every_choice_the_state_machine_made_for_itself_is_declared():
    """The defect this module is most exposed to is overclaiming, and the only
    way to catch it automatically is to make the declarations data.
    """
    for key in ('binding_policy_tighter_wins', 'cure_deadline_time_of_day',
                'cure_credit_normalisation', 'cure_credit_is_gross',
                'forced_sale_sizing', 'forced_sale_sizing_price',
                'forced_sale_trigger_priority',
                'forced_sale_right_lapses_on_recovery', 'late_cure_refused',
                'provisional_cure', 'notice_never_manufactured',
                'no_lot_rounding', 'suspension_does_not_shelter_a_breach',
                'breach_days_counted_by_observation', 'unknown_pnl_sorts_last'):
        assert key in PROVENANCE, f'{key} is undeclared'
        assert PROVENANCE[key].is_assumption, f'{key} claims to be sourced'


def test_the_two_things_the_state_machine_will_not_choose_are_marked_silent():
    """Which business-day calendar, and whether ineligible collateral sells.
    Both are absences in the rulebook, not weak sources.
    """
    assert PROVENANCE['business_day_calendar_choice'].grade is SourceGrade.SILENT
    assert PROVENANCE['sell_on_ineligible_collateral'].grade \
        is SourceGrade.SILENT


def test_the_sizing_formula_says_in_capitals_that_it_is_ours():
    """QD 87 Dieu 8 bounds the sale in prose and gives no arithmetic. A result
    quoting a liquidation quantity has to disclose where the number came from.
    """
    prov = PROVENANCE['forced_sale_sizing']
    assert prov.grade is SourceGrade.DERIVED
    assert 'OURS' in prov.note


# ==========================================================================
# The algebra itself -- khoan 3 to 12, worked through by hand
# ==========================================================================

def test_the_whole_chain_against_hand_computed_numbers():
    """Every line of Dieu 2, checked against arithmetic done on paper.

    ``CB`` 1000 + 500 = 1500. ``PV`` 2500. ``EB`` 4000. ``DB`` 1000.
    ``AB`` 3000. ratio 0.75. ``imr`` 0.50 so ``MR`` 1250, ``EE`` 1750 and
    ``BP`` 3500. If any one of these drifts, a call fires on the wrong day.
    """
    state = account(cash=D('1000'), pending_sale_proceeds=D('500'),
                    eligible_securities_value=D('2500'), margin_debt=D('1000'))
    alg = compute_account_algebra(state, terms())
    assert (alg.db, alg.cb, alg.pv, alg.eb, alg.ab) == (
        D('1000'), D('1500'), D('2500'), D('4000'), D('3000'))
    assert alg.margin_ratio == D('0.75')
    assert alg.imr == D('0.50')
    assert alg.mr == D('1250.00')
    assert alg.ee == D('1750.00')
    assert alg.bp == D('3500')
    assert alg.status is MarginAccountStatus.OK


def test_the_short_names_and_the_long_names_are_the_same_numbers():
    """Both conventions are exposed and neither may drift from the other.

    The article, the brokers and any reviewer will say ``EB``; a reader of this
    codebase needs to know it is not equity.
    """
    alg = compute_account_algebra(
        account(cash=D('1000'), eligible_securities_value=D('1000'),
                margin_debt=D('400')), terms())
    assert (alg.db, alg.cb, alg.pv, alg.eb, alg.ab, alg.mr, alg.ee, alg.bp) == (
        alg.margin_debt, alg.cash_and_pending_proceeds,
        alg.eligible_securities_value, alg.total_assets, alg.net_assets,
        alg.required_margin_value, alg.excess_equity, alg.buying_power)


def test_net_assets_may_go_negative_and_are_not_clamped():
    """*Tai san thuc co* below zero is the account that most needs selling.

    Clamping ``AB`` at zero would hide it, and the ratio would stop being a
    number that means anything at exactly the point it matters most.
    """
    alg = compute_account_algebra(
        account(eligible_securities_value=D('1000'), margin_debt=D('1500')),
        terms())
    assert alg.ab == D('-500')
    assert alg.margin_ratio == D('-0.5')
    assert alg.status is MarginAccountStatus.FORCE_SELL


def test_an_account_with_no_assets_has_no_ratio_and_None_is_not_zero():
    """``EB == 0``. With no debt there is nothing to grade; with a debt there is.

    A total collateral loss against a live *du no ky quy* is QD 87 Dieu 8's
    *"liquidation does not cover DB"* case. Nothing about it is unknown, so it
    is FORCE_SELL and not INDETERMINATE.
    """
    empty = compute_account_algebra(account(), terms())
    assert empty.margin_ratio is None
    assert empty.status is MarginAccountStatus.OK

    wiped = compute_account_algebra(account(margin_debt=D('1000')), terms())
    assert wiped.margin_ratio is None
    assert wiped.ab == D('-1000')
    assert wiped.status is MarginAccountStatus.FORCE_SELL


def test_an_unpriced_holding_makes_the_account_indeterminate_and_says_why():
    """And it wins over a breach: an uncomputed ratio is not a passed one."""
    state = account(eligible_securities_value=D('1000'),
                    margin_debt=D('900'), unpriced_tickers=('EEE',))
    alg = compute_account_algebra(state, terms())
    assert alg.status is MarginAccountStatus.INDETERMINATE
    assert alg.is_indeterminate is True
    assert 'EEE' in alg.indeterminate_reasons[0]


def test_accrued_charges_join_db_by_default_and_fire_calls_sooner():
    """Dieu 2 does not say, so the conservative side is the default.

    DNSE's per-deal formula deducts accrued interest, fees and estimated tax
    from equity. Adding them to ``DB`` lowers ``AB``, which lowers the ratio.
    """
    state = account(cash=D('1000'), eligible_securities_value=D('1000'),
                    margin_debt=D('1000'), accrued_interest=D('100'),
                    accrued_fees=D('50'))
    assert compute_account_algebra(state, terms()).db == D('1150')
    lenient = terms(accrued_charges_in_debt=False)
    assert compute_account_algebra(state, lenient).db == D('1000')
    assert (compute_account_algebra(state, terms()).margin_ratio
            < compute_account_algebra(state, lenient).margin_ratio)


def test_ineligible_collateral_never_reaches_pv():
    """TT 120 Dieu 9.6, and the terms object already refuses the other way."""
    alg = compute_account_algebra(
        account(eligible_securities_value=D('1000'),
                ineligible_securities_value=D('9000')), terms())
    assert alg.pv == D('1000')
    assert alg.eb == D('1000')


def test_a_negative_value_field_is_refused_rather_than_ratioed():
    """None of khoan 3-7's terms is signed; only ``AB`` may go below zero.

    A negative input flips the ratio silently instead of failing, which is the
    worst way for a number to be wrong.
    """
    with pytest.raises(ValueError, match='none of them is signed'):
        compute_account_algebra(account(cash=D('-1')), terms())
    with pytest.raises(TypeError, match='must be a Decimal'):
        compute_account_algebra(account(cash=1000.0), terms())


def test_a_raised_statutory_floor_calls_an_account_the_terms_call_fine():
    """QD 87 Dieu 5.3, which has been used once inside living memory.

    A firm's contracts say call at 0.35 and force-sell at 0.32. The SSC raises
    the maintenance floor to 0.40. An account at 0.38 was fine on Friday and on
    Monday is below **both** binding levels, with no contract amendment -- and
    the CALL band has vanished entirely, because a floor above the firm's own
    call level collapses the two rungs onto each other. The algebra must grade
    against the row in force, not the row the terms were validated with.
    """
    state = account(cash=D('1000'), eligible_securities_value=D('1000'),
                    margin_debt=D('1240'))
    assert compute_account_algebra(state, terms()).margin_ratio == D('0.38')
    assert compute_account_algebra(state, terms()).status \
        is MarginAccountStatus.OK
    raised = replace(QD_87_2017, maintenance_margin_ratio_floor=D('0.40'))
    graded = compute_account_algebra(state, terms(), regulation=raised)
    assert graded.mmr == D('0.40')
    assert binding_policy(terms(), raised).levels_collapsed is True
    assert graded.status is MarginAccountStatus.FORCE_SELL


def test_build_account_state_joins_the_ledger_to_the_price_snapshot():
    """The seam: ``cash_base`` for khoan 5 and ``value_collateral`` for Dieu 2.4.

    Nothing in it interprets -- both decisions were already made -- and the
    unpriced tickers arrive on the state, which is the only channel the algebra
    reads an indeterminacy through.
    """
    state = build_account_state(
        account_id='M1', as_of=NOW,
        cash=cash_with(settled='1000', pending='500', advanced='300'),
        collateral=[priced('AAA', 100, '20'),
                    CollateralLot('BBB', 10, last_close=D('5'),
                                  eligibility=MarginEligibility.INELIGIBLE),
                    CollateralLot('CCC', 10, last_close=D('5'))],
        terms=terms(), margin_debt=D('1000'))
    assert state.cash == D('1000')
    assert state.pending_sale_proceeds == D('500')
    assert state.eligible_securities_value == D('2000')
    assert state.ineligible_securities_value == D('50')
    assert state.unpriced_tickers == ('CCC',)
    assert compute_account_algebra(state, terms()).status \
        is MarginAccountStatus.INDETERMINATE


def test_a_derived_debt_counts_only_the_loans_that_are_still_owed():
    """``REPAID`` is cleared; ``LIQUIDATED`` may leave a residual the contract
    pursues, but neither is *du no ky quy* on this account any more."""
    def loan(loan_id, principal, status):
        return MarginLoan(loan_id=loan_id, account_id='M1',
                          principal=D(principal), disbursed_on=date(2026, 6, 1),
                          due_on=date(2026, 8, 30), status=status,
                          accrued_interest=D('10'))
    state = build_account_state(
        account_id='M1', as_of=NOW, cash=cash_with(settled='1000'),
        collateral=[], terms=terms(),
        loans=(loan('L1', '500', LoanStatus.OUTSTANDING),
               loan('L2', '300', LoanStatus.OVERDUE),
               loan('L3', '900', LoanStatus.REPAID)))
    assert state.margin_debt == D('800')
    assert state.accrued_interest == D('20')


# ==========================================================================
# The per-order imr -- khoan 8
# ==========================================================================

def test_without_a_loan_ratio_table_the_order_runs_at_the_account_imr():
    """An EMPTY table means no list was supplied, not "lends against nothing".

    Reading the default as a firm that does no margin business would refuse
    every order and say a great deal about the caller's data and nothing about
    the rule.
    """
    assert order_initial_margin_ratio(terms(), 'AAA') == D('0.50')


def test_a_low_loan_ratio_makes_the_order_imr_stricter():
    """``imr = 1 - loan_ratio``, DERIVED, and used only in the tightening
    direction.

    A ticker the firm lends 10 % against needs 90 % of the order in *tai san
    thuc co*. A ticker it lends the statutory maximum 50 % against needs 50 %.
    """
    firm = terms(loan_ratio_by_ticker={'AAA': D('0.50'), 'BBB': D('0.10')})
    assert order_initial_margin_ratio(firm, 'AAA') == D('0.50')
    assert order_initial_margin_ratio(firm, 'BBB') == D('0.90')


def test_the_derived_identity_can_never_loosen_a_stated_term():
    """A firm at ``imr`` 0.60 lending 50 % against a ticker still requires 0.60.

    The identity is ours, it is in no text read, and it holds only for a single
    fully collateralised purchase -- so it is applied as ``max``, never as an
    assignment.
    """
    strict = terms(initial_margin_ratio=D('0.60'),
                   loan_ratio_by_ticker={'AAA': D('0.50')})
    assert order_initial_margin_ratio(strict, 'AAA') == D('0.60')


# ==========================================================================
# The pre-trade gate -- QD 87 Dieu 13.5(d)
# ==========================================================================

def funded(**kw) -> MarginAccountState:
    """An account comfortably above every level, for gating one order."""
    fields = dict(cash=D('1000'), eligible_securities_value=D('2000'),
                  margin_debt=D('500'))
    fields.update(kw)
    return account(**fields)


def test_an_order_inside_the_buying_power_is_admitted_with_no_refusals():
    """``order_value x imr <= EE``, and the verdict carries the numbers.

    ``CB`` 1000, ``PV`` 2000, ``EB`` 3000, ``DB`` 500, ``AB`` 2500,
    ``MR`` 1000, ``EE`` 1500, so ``BP`` at ``imr`` 0.50 is 3000.
    """
    verdict = assess_margin_order(funded(), terms(), ticker='AAA',
                                  quantity=100, price=D('20'),
                                  security=eligible())
    assert verdict.admitted is True
    assert verdict.refusals == ()
    assert verdict.indeterminate == ()
    assert verdict.order_value == D('2000')
    assert verdict.required_margin == D('1000.00')
    assert verdict.excess_equity == D('1500.00')
    assert verdict.buying_power == D('3000')


def test_an_order_exactly_on_the_limit_is_admitted():
    """*"khong duoc de ... vuot qua suc mua"* -- beyond, not equal to."""
    exact = assess_margin_order(funded(), terms(), ticker='AAA', quantity=150,
                                price=D('20'), security=eligible())
    assert exact.order_value == D('3000')
    assert exact.required_margin == exact.excess_equity == D('1500.00')
    assert exact.admitted is True


def test_the_decision_is_the_multiplication_and_not_the_division():
    """``order_value x imr <= EE``, never ``order_value <= BP``.

    The two are the same statement in exact arithmetic, but ``BP = EE / imr``
    is a ``Decimal`` division correct only to the context precision, so at the
    boundary the division form can be off by an ulp in whichever direction the
    remainder falls. The multiplication cannot be. ``buying_power`` is still
    reported, because it is the number a client is quoted -- it is just not what
    the verdict is computed from.
    """
    firm = terms(initial_margin_ratio=D('0.55'))
    verdict = assess_margin_order(funded(), firm, ticker='AAA', quantity=137,
                                  price=D('20'), security=eligible())
    assert verdict.required_margin == verdict.order_value * D('0.55')
    assert verdict.admitted is (verdict.required_margin
                                <= verdict.excess_equity)
    assert verdict.buying_power == verdict.excess_equity / D('0.55')


def test_an_order_beyond_the_buying_power_is_refused_and_quantifies_the_gap():
    """A caller fixing a rejection needs to know by how much."""
    verdict = assess_margin_order(funded(), terms(), ticker='AAA',
                                  quantity=200, price=D('20'),
                                  security=eligible())
    assert verdict.admitted is False
    assert verdict.refusals == (MarginOrderRefusal.BUYING_POWER_EXCEEDED,)
    assert verdict.detail['shortfall'] == D('500.00')
    assert 'Dieu 13.5(d)' in verdict.detail['reasons']['buying_power_exceeded']


def test_the_per_order_imr_shrinks_the_order_the_ticker_supports():
    """khoan 8 is per order, and this is what per-order buys you.

    The same account may buy 3000 of a ticker the firm lends 50 % against and
    only 1666 of one it lends 10 % against, because the second needs 90 % of the
    order in *tai san thuc co*. An account-constant ``imr`` cannot express it.
    """
    firm = terms(loan_ratio_by_ticker={'AAA': D('0.50'), 'BBB': D('0.10')})
    generous = assess_margin_order(funded(), firm, ticker='AAA', quantity=150,
                                   price=D('20'), security=eligible())
    tight = assess_margin_order(funded(), firm, ticker='BBB', quantity=150,
                                price=D('20'), security=eligible('BBB'))
    assert generous.buying_power == D('3000')
    assert generous.admitted is True
    assert tight.detail['initial_margin_ratio_applied'] == D('0.90')
    assert tight.buying_power < D('1700')
    assert tight.admitted is False


def test_a_missing_eligibility_answer_is_indeterminate_and_not_a_refusal():
    """Absent data is never "eligible", and it is never a rule saying no either.

    The eligible-security list is dated data the caller supplies, exactly like
    the VSDC settlement calendar. Both tuples block the order; only one of them
    is a finding about the market.
    """
    verdict = assess_margin_order(funded(), terms(), ticker='AAA',
                                  quantity=10, price=D('20'))
    assert verdict.admitted is False
    assert verdict.refusals == ()
    assert verdict.indeterminate == (MarginOrderRefusal.SECURITY_NOT_ELIGIBLE,)


def test_the_two_eligibility_layers_are_reported_apart():
    """Layer 1 is the exchange's negative list; layer 2 is the CTCK's positive one.

    A ticker can pass every Dieu 3 predicate and still be absent from the firm's
    list -- a commercial decision, always permitted -- and ``on_broker_list=None``
    is not an implicit yes.
    """
    excluded = SecurityEligibility(
        ticker='AAA', as_of=TODAY, result=MarginEligibility.INELIGIBLE,
        failed=(ExclusionPredicate.LOSS_OR_ACCUMULATED_LOSS,),
        on_broker_list=False)
    verdict = assess_margin_order(funded(), terms(), ticker='AAA', quantity=10,
                                  price=D('20'), security=excluded)
    assert verdict.refusals == (MarginOrderRefusal.SECURITY_NOT_ELIGIBLE,)
    assert 'Dieu 3' in verdict.detail['reasons']['security_not_eligible']

    unlisted = SecurityEligibility(ticker='AAA', as_of=TODAY,
                                   result=MarginEligibility.ELIGIBLE)
    silent = assess_margin_order(funded(), terms(), ticker='AAA', quantity=10,
                                 price=D('20'), security=unlisted)
    assert silent.indeterminate == (MarginOrderRefusal.SECURITY_NOT_ELIGIBLE,)


def test_a_ticker_absent_from_a_populated_loan_ratio_table_is_refused():
    """A populated *ty le cho vay* table IS the firm's positive list."""
    firm = terms(loan_ratio_by_ticker={'AAA': D('0.50')})
    verdict = assess_margin_order(funded(), firm, ticker='ZZZ', quantity=10,
                                  price=D('20'), security=eligible('ZZZ'))
    assert MarginOrderRefusal.SECURITY_NOT_ELIGIBLE in verdict.refusals
    assert 'EMPTY table' in verdict.detail['reasons']['security_not_eligible']


def test_a_foreign_investor_is_refused_without_asserting_the_wider_claim():
    """TT 120 Dieu 9.2 is a flat prohibition **on margin lending**.

    TT 120 Dieu 9a is a separate regime under which foreign institutional
    investors buy on broker credit without pre-funding. An implementer reading
    only this refusal would build a simulator that refuses all foreign
    credit-funded buying, which is wrong, so the message says so.
    """
    verdict = assess_margin_order(funded(is_foreign_investor=True), terms(),
                                  ticker='AAA', quantity=10, price=D('20'),
                                  security=eligible())
    assert verdict.refusals == (MarginOrderRefusal.INVESTOR_NOT_ELIGIBLE,)
    assert 'Dieu 9a' in verdict.detail['reasons']['investor_not_eligible']


def test_an_insider_and_an_unsigned_contract_are_separate_refusals():
    """QD 87 Dieu 13.4 and TT 120 Dieu 9.1 fail for different reasons."""
    insider = assess_margin_order(
        funded(holder_classes=(IneligibleAccountHolder.CTCK_INSIDER,)),
        terms(), ticker='AAA', quantity=10, price=D('20'), security=eligible())
    assert insider.refusals == (MarginOrderRefusal.INVESTOR_NOT_ELIGIBLE,)

    unsigned = assess_margin_order(funded(margin_contract_signed=False),
                                   terms(), ticker='AAA', quantity=10,
                                   price=D('20'), security=eligible())
    assert unsigned.refusals == (MarginOrderRefusal.NO_MARGIN_CONTRACT,)


def test_a_suspended_firm_may_not_lend_even_to_a_healthy_account():
    """TT 120 Dieu 9.9 and Dieu 9.7: existing debt stays, new lending stops."""
    verdict = assess_margin_order(funded(lending_suspended=True), terms(),
                                  ticker='AAA', quantity=10, price=D('20'),
                                  security=eligible())
    assert MarginOrderRefusal.LENDING_SUSPENDED in verdict.refusals
    assert '48 hours' in verdict.detail['reasons']['lending_suspended']


def test_an_account_in_breach_may_not_borrow_more():
    """QD 87 Dieu 10.1(d), and it does not wait for a call to have issued."""
    breached = funded(eligible_securities_value=D('2000'),
                      cash=D('0'), margin_debt=D('1500'))
    verdict = assess_margin_order(breached, terms(), ticker='AAA', quantity=1,
                                  price=D('20'), security=eligible())
    assert MarginOrderRefusal.ACCOUNT_IN_BREACH in verdict.refusals
    assert 'Dieu 10.1(d)' in verdict.detail['reasons']['account_in_breach']


def test_a_partially_cured_call_still_blocks_new_borrowing():
    """QD 87 Dieu 8 treats a partial top-up as a failure to top up.

    The ratio here is healthy again, so only the open call stands between the
    account and a new margin order.
    """
    call = MarginCall(call_id='C1', account_id='M1', issued_at=NOW,
                      deadline=NOW, target_ratio=D('0.35'),
                      status=MarginCallStatus.PARTIALLY_CURED)
    verdict = assess_margin_order(funded(open_calls=(call,)), terms(),
                                  ticker='AAA', quantity=10, price=D('20'),
                                  security=eligible())
    assert MarginOrderRefusal.ACCOUNT_IN_BREACH in verdict.refusals
    assert 'PARTIAL' in verdict.detail['reasons']['account_in_breach']


def test_every_rule_that_says_no_is_reported_not_the_first_one():
    """A caller fixing one refusal wants to see the rest.

    And a run that counts refusals by reason is the only way to tell a
    buying-power-bound simulation from an eligibility-bound one.
    """
    verdict = assess_margin_order(
        funded(is_foreign_investor=True, margin_contract_signed=False,
               lending_suspended=True),
        terms(), ticker='AAA', quantity=10_000, price=D('20'),
        security=SecurityEligibility(ticker='AAA', as_of=TODAY,
                                     result=MarginEligibility.INELIGIBLE,
                                     on_broker_list=False))
    assert set(verdict.refusals) == {
        MarginOrderRefusal.BUYING_POWER_EXCEEDED,
        MarginOrderRefusal.LENDING_SUSPENDED,
        MarginOrderRefusal.NO_MARGIN_CONTRACT,
        MarginOrderRefusal.INVESTOR_NOT_ELIGIBLE,
        MarginOrderRefusal.SECURITY_NOT_ELIGIBLE,
    }


def test_prohibited_collateral_categories_land_under_one_heading_each():
    """Dieu 10.1(a)-(c) are collateral; (d), (d) and (e) are the same facts as
    the breach, foreign and insider tests and are reported under those names.

    One fact appearing twice under two headings would double-count in any
    tally of why orders were refused.
    """
    verdict = assess_margin_order(
        funded(), terms(), ticker='AAA', quantity=10, price=D('20'),
        security=eligible(),
        prohibited_collateral=(ProhibitedCollateral.OWN_SHARES,
                               ProhibitedCollateral.FOREIGN_INVESTOR))
    assert set(verdict.refusals) == {MarginOrderRefusal.PROHIBITED_COLLATERAL,
                                     MarginOrderRefusal.INVESTOR_NOT_ELIGIBLE}
    assert 'own shares' in verdict.detail['reasons']['prohibited_collateral']


def test_an_indeterminate_account_does_not_report_a_rule_saying_no():
    """The posture the whole package takes, at the gate."""
    verdict = assess_margin_order(funded(unpriced_tickers=('EEE',)), terms(),
                                  ticker='AAA', quantity=10, price=D('20'),
                                  security=eligible())
    assert verdict.refusals == ()
    assert MarginOrderRefusal.INDETERMINATE in verdict.indeterminate
    assert verdict.admitted is False


def test_the_broker_credit_limit_sits_under_the_statutory_one():
    """SSI up to 70 ty, DNSE 10 ty, ABS 10-35 ty -- all REPORTED broker terms."""
    capped = terms(per_customer_credit_limit=D('600'))
    verdict = assess_margin_order(funded(), capped, ticker='AAA', quantity=100,
                                  price=D('20'), security=eligible())
    assert MarginOrderRefusal.CREDIT_LIMIT in verdict.refusals
    assert verdict.detail['implied_loan'] == D('1000.00')


# -- QD 87 Dieu 9, opt-in --------------------------------------------------

def a_firm(**kw) -> FirmLendingState:
    fields = dict(equity=D('1000000'), equity_statement_date=date(2026, 6, 30),
                  issuer_listed_shares={'AAA': 1_000_000})
    fields.update(kw)
    return FirmLendingState(**fields)


def test_the_four_dieu_9_caps_keep_their_own_denominators():
    """Three are fractions of the firm's equity; Dieu 9.4 is not.

    *"khong duoc vuot qua 5% tong so chung khoan niem yet cua mot to chuc niem
    yet"* -- and it is counted in **shares**, not dong.
    """
    room = firm_limit_headroom(a_firm(), ticker='AAA', as_of=TODAY)
    assert room[FirmLendingLimit.TOTAL_BOOK].cap == D('2000000.00')
    assert room[FirmLendingLimit.PER_CUSTOMER].cap == D('30000.00')
    assert room[FirmLendingLimit.PER_SECURITY].cap == D('100000.0')
    assert room[FirmLendingLimit.PER_ISSUER_SHARES].cap == D('50000.00')


def test_firm_limits_are_not_tested_unless_the_caller_supplies_the_book():
    """They are facts about a CTCK, not about this account.

    Reporting them as INDETERMINATE when absent would make every ordinary gate
    call indeterminate and drain the word of the meaning it carries for
    eligibility, where absent data really is the finding.
    """
    verdict = assess_margin_order(funded(), terms(), ticker='AAA', quantity=10,
                                  price=D('20'), security=eligible())
    assert verdict.detail['firm_limits_tested'] is False
    assert verdict.indeterminate == ()
    assert verdict.admitted is True


def test_a_per_security_cap_breach_refuses_and_names_dieu_9_3():
    """10 % of equity against one security."""
    firm = a_firm(security_book={'AAA': D('99500')})
    verdict = assess_margin_order(funded(), terms(), ticker='AAA', quantity=100,
                                  price=D('20'), security=eligible(), firm=firm)
    assert MarginOrderRefusal.FIRM_LIMIT in verdict.refusals
    assert 'Dieu 9.3' in verdict.detail['reasons']['firm_limit']


def test_the_share_cap_counts_shares_and_not_dong():
    """Dieu 9.4's increment is the order quantity, whatever the price is."""
    firm = a_firm(shares_lent={'AAA': 49_950})
    verdict = assess_margin_order(funded(), terms(), ticker='AAA', quantity=100,
                                  price=D('20'), security=eligible(), firm=firm)
    assert MarginOrderRefusal.FIRM_LIMIT in verdict.refusals
    assert 'Dieu 9.4' in verdict.detail['reasons']['firm_limit']


def test_a_stale_equity_statement_makes_the_equity_caps_undecidable():
    """Dieu 9 takes equity from a statement **not older than 06 months**.

    The share cap never touches equity, so it survives -- which is why the four
    limits are graded one by one rather than together.
    """
    firm = a_firm(equity_statement_date=date(2025, 12, 31))
    room = firm_limit_headroom(firm, ticker='AAA', as_of=TODAY)
    assert room[FirmLendingLimit.TOTAL_BOOK].evaluable is False
    assert '06 months' not in room[FirmLendingLimit.TOTAL_BOOK].reason
    assert room[FirmLendingLimit.PER_ISSUER_SHARES].evaluable is True

    verdict = assess_margin_order(funded(), terms(), ticker='AAA', quantity=10,
                                  price=D('20'), security=eligible(), firm=firm)
    assert MarginOrderRefusal.INDETERMINATE in verdict.indeterminate
    assert verdict.refusals == ()


def test_an_issuer_with_no_listed_share_count_cannot_be_tested_against_dieu_9_4():
    """Listed-share counts are dated issuer data the caller supplies."""
    room = firm_limit_headroom(a_firm(issuer_listed_shares={}), ticker='AAA',
                               as_of=TODAY)
    limit = room[FirmLendingLimit.PER_ISSUER_SHARES]
    assert limit.evaluable is False
    assert 'listed-share count' in limit.reason
    assert limit.admits(D('1')) is True   # an untested cap refuses nothing


def test_an_equity_statement_from_the_future_is_look_ahead():
    """Freshness is not the same thing as not existing yet."""
    with pytest.raises(ValueError, match='look-ahead'):
        firm_limit_headroom(a_firm(equity_statement_date=date(2026, 12, 31)),
                            ticker='AAA', as_of=TODAY)


# -- input hygiene ---------------------------------------------------------

def test_an_order_for_nothing_is_not_an_order():
    """khoan 8 values the order at market price at trade time."""
    with pytest.raises(ValueError, match='not an order'):
        assess_margin_order(funded(), terms(), ticker='AAA', quantity=0,
                            price=D('20'))
    with pytest.raises(ValueError, match='MARKET value'):
        assess_margin_order(funded(), terms(), ticker='AAA', quantity=10,
                            price=D('0'))
    with pytest.raises(TypeError, match='must be a Decimal'):
        assess_margin_order(funded(), terms(), ticker='AAA', quantity=10,
                            price=20.0)


def test_eligibility_dated_after_the_order_is_refused_as_look_ahead():
    """QD 87 Dieu 4 publishes the lists on a lag -- 2 business days for the
    exchange and 2 more for the CTCK -- so tomorrow's list is look-ahead."""
    tomorrow = SecurityEligibility(ticker='AAA', as_of=date(2026, 8, 27),
                                   result=MarginEligibility.ELIGIBLE,
                                   on_broker_list=True)
    with pytest.raises(ValueError, match='look-ahead'):
        assess_margin_order(funded(), terms(), ticker='AAA', quantity=10,
                            price=D('20'), security=tomorrow)


def test_a_state_from_the_future_is_refused():
    """The gate is a snapshot test."""
    with pytest.raises(ValueError, match='precedes the state'):
        assess_margin_order(funded(), terms(), ticker='AAA', quantity=10,
                            price=D('20'), security=eligible(),
                            as_of=datetime(2026, 8, 25, 15, 0))


def test_the_eligibility_record_must_be_about_the_ticker_being_bought():
    """Silently gating one ticker on another's list is the worst kind of pass."""
    with pytest.raises(ValueError, match='is for'):
        assess_margin_order(funded(), terms(), ticker='AAA', quantity=10,
                            price=D('20'), security=eligible('BBB'))


def test_the_gate_is_a_pure_snapshot_and_encumbers_nothing():
    """Documented behaviour, pinned so it cannot become an accident.

    Two orders that each fit but together do not are both admitted against the
    same state. A caller running several must commit each into the state it
    passes to the next, exactly as ``ledgers.py`` encumbers cash against live
    buy orders.
    """
    state = funded()
    first = assess_margin_order(state, terms(), ticker='AAA', quantity=100,
                                price=D('20'), security=eligible())
    second = assess_margin_order(state, terms(), ticker='AAA', quantity=100,
                                 price=D('20'), security=eligible())
    assert first.admitted and second.admitted
    assert first.order_value + second.order_value > first.buying_power


# ==========================================================================
# PROVENANCE for everything this section decided
# ==========================================================================

def test_every_choice_this_section_made_is_declared():
    """An assumption that does not say it is one reads as evidence."""
    for key in ('advance_outside_the_algebra', 'collateral_haircut_not_applied',
                'unpriced_only_where_it_would_count', 'account_status_precedence',
                'zero_asset_account_is_force_sell', 'per_order_imr_from_loan_ratio',
                'gate_uses_the_multiplicative_form', 'firm_limits_are_opt_in'):
        assert PROVENANCE[key].grade is SourceGrade.DERIVED, key
        assert PROVENANCE[key].is_assumption


def test_khoan_5_is_verified_and_the_two_silent_items_say_so():
    """The one thing in this section that was actually read, and the two that
    were not."""
    assert PROVENANCE['unsettled_proceeds_in_cb'].grade is SourceGrade.VERIFIED
    assert PROVENANCE['unsettled_proceeds_in_cb'].article == 'QD 87 Dieu 2 khoan 5'
    assert PROVENANCE['withdrawal_gate_not_implemented'].grade is SourceGrade.SILENT
    assert PROVENANCE['session_bounds_for_the_sweep'].grade is SourceGrade.SILENT


def test_the_no_engine_claim_was_corrected_rather_than_deleted():
    """It was true when it was written and is not any more.

    Deleting it would leave a reader who saw the old claim with no correction;
    the key stays and the note supersedes.
    """
    entry = PROVENANCE['no_engine_yet']
    assert 'SUPERSEDED' in entry.note
    assert 'NO LONGER the' in entry.note


# ==========================================================================
# ELIGIBILITY -- spec 2.5, 2.6, 2.7, 2.11
# ==========================================================================
#
# Three things this layer can be wrong about, and every test below is one of
# them:
#
# 1. **It answers ELIGIBLE on facts it does not have.** The spec's instruction
#    is that an unevaluable predicate is INDETERMINATE and never "eligible", so
#    the fact records use None for *not known* and the assessors must never
#    turn a missing fact into a pass.
# 2. **It invents a rule.** The post-2020 trading-status mapping is SILENT and
#    the section-2.7 collateral question has TWO TEXTS that disagree. Picking
#    either silently is the defect; the tests pin the default AND that the
#    alternative is reachable AND that the divergence is stated.
# 3. **It compiles a market in.** The universe is supplied data. A test pins
#    that a predicate the supplied table does not implement comes back
#    unevaluated rather than passed, which is what makes a partial table safe.

from datetime import timedelta

from plutus.market.session.margin_lending import (
    DEFAULT_ELIGIBILITY_POLICY, DOMESTIC_INVESTOR_ASSUMPTION_NOTE,
    ELIGIBILITY_PROVENANCE, FUND_NAV_LOOKBACK_MONTHS,
    INELIGIBLE_COLLATERAL_DIVERGENCE, LATE_DISCLOSURE_BUSINESS_DAYS,
    QD_1205_EFFECTIVE_FROM, STATUTORY_EXCLUSION_RULES,
    STATUTORY_TRADING_STATUSES, UNMAPPED_TRADING_STATUSES, AuditOpinion,
    BrokerMarginList, CollateralRelationship, EligibilityPolicy,
    ExchangeMarginList, ExclusionRule, IneligibleAccountHolder,
    IneligibleCollateralTreatment, InvestorFacts, MarginEligibility,
    ProhibitedCollateral, SecurityFacts, SecurityKind, TradingStatus,
    UnmappedStatusPolicy, assess_collateral, assess_investor, assess_security,
    earliest_relist_date, rule_on_ineligible_collateral)

REVIEW = date(2026, 8, 26)


def sec(**overrides) -> SecurityFacts:
    """A security that passes every QD 87 Dieu 3 predicate on ``REVIEW``.

    Every field is stated, because the whole convention of this layer is that
    an unstated field is INDETERMINATE -- so a helper that leaves any of them
    out would make every test about missing data instead of about the rule
    under test.
    """
    base = dict(
        ticker='VNM',
        as_of=REVIEW,
        venue=Venue.HSX,
        kind=SecurityKind.SHARE,
        first_trading_day=date(2006, 1, 19),
        trading_statuses=(),
        latest_audit_opinion=AuditOpinion.UNQUALIFIED,
        financial_statement_days_late=0,
        tax_evasion_or_fraud_decision=False,
        tax_enforcement_non_compliance_decision=False,
        prosecution_decision=False,
        period_loss=False,
        accumulated_loss=False,
    )
    base.update(overrides)
    return SecurityFacts(**base)


def clean_investor(**overrides) -> InvestorFacts:
    """A domestic individual with a signed contract and no disqualification."""
    base = dict(
        account_id='068C123456',
        as_of=REVIEW,
        has_margin_contract=True,
        is_foreign_investor=False,
    )
    base.update(overrides)
    return InvestorFacts(**base)


def broker_list(*tickers, **overrides) -> BrokerMarginList:
    base = dict(tickers=frozenset(tickers), published_on=date(2026, 4, 6))
    base.update(overrides)
    return BrokerMarginList(**base)


# --------------------------------------------------------------------------
# The predicates are DATA, and the table is complete
# --------------------------------------------------------------------------

def test_every_statutory_predicate_has_a_rule_and_nothing_else_does():
    """A predicate with no rule is a predicate that silently never fires.

    The regulation lists seven exclusion predicates. If the table implemented
    six, the seventh would be skipped on every assessment and securities the
    exchange excludes would come back clean -- which is exactly the direction
    that lets more borrowing happen, so it fails closed here instead.
    """
    assert set(STATUTORY_EXCLUSION_RULES) == set(ExclusionPredicate)
    assert set(STATUTORY_EXCLUSION_RULES) == set(QD_87_2017.exclusion_predicates)


def test_every_rule_cites_a_read_article():
    """The point of rules-as-data is that overclaiming becomes checkable.

    Each rule carries the clause it implements and the grade behind it, so
    "every statutory predicate traces to a text someone read" is an assertion
    rather than a hope. The SILENT part of Dieu 3.2 is the *mapping* of the
    post-2020 statuses, not the article, so the article stays VERIFIED.
    """
    for predicate, rule in STATUTORY_EXCLUSION_RULES.items():
        assert rule.predicate is predicate
        assert rule.grade is SourceGrade.VERIFIED
        assert rule.article.startswith('QD 87 Dieu 3')
        assert rule.summary


def test_a_rule_table_keyed_against_the_wrong_predicate_is_refused():
    """A mis-keyed table would report an exclusion under an unrelated article.

    The rejection report names the clause, so a table that decides
    LOSS_OR_ACCUMULATED_LOSS under the key TRADING_STATUS would tell a user
    their security is under *kiem soat* because its issuer made a loss.
    """
    borrowed = STATUTORY_EXCLUSION_RULES[
        ExclusionPredicate.LOSS_OR_ACCUMULATED_LOSS]
    with pytest.raises(ValueError, match='implements'):
        EligibilityPolicy(rules={ExclusionPredicate.TRADING_STATUS: borrowed})


def test_a_predicate_the_table_does_not_implement_is_unevaluated_not_passed():
    """A partial table narrows what can be decided; it never widens eligibility.

    This is the safety property that makes a supplied rule table usable at all.
    A caller who hands in one rule is saying *I can check this much*, not
    *nothing else applies*, and the six unimplemented predicates come back
    unevaluated with the answer INDETERMINATE.
    """
    only_venue = EligibilityPolicy(rules={
        ExclusionPredicate.INELIGIBLE_VENUE:
            STATUTORY_EXCLUSION_RULES[ExclusionPredicate.INELIGIBLE_VENUE]})
    verdict = assess_security(sec(), policy=only_venue,
                              broker_list=broker_list('VNM'))
    assert verdict.result is MarginEligibility.INDETERMINATE
    assert verdict.failed == ()
    assert len(verdict.unevaluated) == 6
    assert ExclusionPredicate.INELIGIBLE_VENUE not in verdict.unevaluated


def test_a_rule_is_callable_so_a_caller_can_evaluate_one_predicate():
    """``ExclusionRule.__call__`` exists so the table is usable piecemeal."""
    rule = STATUTORY_EXCLUSION_RULES[ExclusionPredicate.QUALIFIED_AUDIT_OPINION]
    facts = sec(latest_audit_opinion=AuditOpinion.DISCLAIMER)
    assert rule(facts, QD_87_2017, DEFAULT_ELIGIBILITY_POLICY) is True
    assert rule(sec(), QD_87_2017, DEFAULT_ELIGIBILITY_POLICY) is False
    assert rule(sec(latest_audit_opinion=None), QD_87_2017,
                DEFAULT_ELIGIBILITY_POLICY) is None


# --------------------------------------------------------------------------
# The seven predicates, one at a time
# --------------------------------------------------------------------------

def test_upcom_is_outside_the_universe_and_the_venue_comes_off_the_dated_row():
    """Dieu 3's universe is *niem yet*, and the predicate reads the dated field.

    Hard-coding HOSE and HNX here would put the recorded TT 120 Dieu 9.4
    divergence in two places, and a future row admitting *dang ky giao dich*
    would then change one and not the other.
    """
    verdict = assess_security(sec(venue=Venue.UPCOM))
    assert verdict.result is MarginEligibility.INELIGIBLE
    assert verdict.failed == (ExclusionPredicate.INELIGIBLE_VENUE,)


def test_a_security_listed_five_months_is_out_and_six_months_is_in():
    """Dieu 3.1's boundary, both sides, on real calendar months.

    Six months from 2026-02-26 is 2026-08-26, and the article excludes a
    security listed *under* six months -- so the anniversary itself passes.
    """
    assert assess_security(sec(first_trading_day=date(2026, 3, 26))).failed == \
        (ExclusionPredicate.LISTED_UNDER_SIX_MONTHS,)
    on_the_day = assess_security(sec(first_trading_day=date(2026, 2, 26)),
                                 broker_list=broker_list('VNM'))
    assert on_the_day.failed == ()
    assert on_the_day.result is MarginEligibility.ELIGIBLE


def test_a_venue_transfer_sums_the_time_listed_on_both_exchanges():
    """Dieu 3.1: *on a venue transfer the two exchanges listed times are summed*.

    Five months on the new venue alone would exclude. With ninety days carried
    over from the old one the security is past six months and eligible, which
    is the whole content of the summation rule.
    """
    moved = dict(first_trading_day=date(2026, 4, 26))
    assert assess_security(sec(**moved)).result is MarginEligibility.INELIGIBLE
    summed = assess_security(sec(prior_venue_listed_days=90, **moved),
                             broker_list=broker_list('VNM'))
    assert summed.result is MarginEligibility.ELIGIBLE


def test_a_negative_carryover_would_shorten_the_window_and_is_refused():
    """The summation rule adds time; a negative summand would subtract it."""
    with pytest.raises(ValueError, match='SUMS'):
        sec(prior_venue_listed_days=-30)


def test_each_of_the_five_gazetted_trading_statuses_excludes_on_its_own():
    """Dieu 3.2 enumerates five and any one of them is enough."""
    for status in STATUTORY_TRADING_STATUSES:
        verdict = assess_security(sec(trading_statuses=(status,)))
        assert verdict.failed == (ExclusionPredicate.TRADING_STATUS,), status


def test_an_opinion_other_than_unqualified_excludes_whichever_it_is():
    """Dieu 3.3 is stated negatively, so the test is *not unqualified*.

    Implemented as the negation rather than as membership of a bad-opinion set,
    so an opinion this enum does not yet name still excludes.
    """
    for opinion in (AuditOpinion.QUALIFIED, AuditOpinion.ADVERSE,
                    AuditOpinion.DISCLAIMER):
        verdict = assess_security(sec(latest_audit_opinion=opinion))
        assert verdict.failed == (
            ExclusionPredicate.QUALIFIED_AUDIT_OPINION,), opinion


def test_lateness_excludes_at_more_than_five_business_days_not_at_five():
    """Dieu 3.4 says *more than* five, and the boundary is load-bearing.

    An off-by-one here changes which securities a whole run may margin, and it
    does so invisibly -- nothing downstream would look wrong.
    """
    edge = assess_security(
        sec(financial_statement_days_late=LATE_DISCLOSURE_BUSINESS_DAYS),
        broker_list=broker_list('VNM'))
    assert edge.result is MarginEligibility.ELIGIBLE
    over = assess_security(
        sec(financial_statement_days_late=LATE_DISCLOSURE_BUSINESS_DAYS + 1))
    assert over.failed == (ExclusionPredicate.LATE_FINANCIAL_STATEMENT,)


def test_qd_1205_narrowed_the_tax_limb_and_the_same_facts_answer_differently():
    """The one dated rule change in Dieu 3, implemented as a dated rule change.

    An ordinary tax-authority violation conclusion cut margin under QD 87's
    original khoan 5 and stopped doing so on 2018-01-02. Same facts, two review
    dates, two answers -- which is what "implement it as one" means.
    """
    facts = dict(other_tax_violation_conclusion=True,
                 first_trading_day=date(2006, 1, 19))
    before = assess_security(sec(as_of=QD_1205_EFFECTIVE_FROM - timedelta(days=1),
                                 **facts))
    assert before.failed == (ExclusionPredicate.TAX_OR_PROSECUTION,)
    after = assess_security(sec(as_of=QD_1205_EFFECTIVE_FROM, **facts),
                            broker_list=broker_list(
                                'VNM', published_on=date(2017, 12, 1)))
    assert after.failed == ()
    assert after.result is MarginEligibility.ELIGIBLE


def test_the_three_narrowed_tax_limbs_still_exclude_after_the_amendment():
    """QD 1205 narrowed the limb; it did not delete it."""
    for field_name in ('tax_evasion_or_fraud_decision',
                       'tax_enforcement_non_compliance_decision',
                       'prosecution_decision'):
        verdict = assess_security(sec(**{field_name: True}))
        assert verdict.failed == (
            ExclusionPredicate.TAX_OR_PROSECUTION,), field_name


def test_a_parent_tested_on_unconsolidated_statements_is_undecided():
    """Dieu 3.6 requires the CONSOLIDATED FS for a parent company.

    Loss flags read off the parent-only statements are facts about the wrong
    entity. Passing on them would admit exactly the issuer the consolidation
    requirement exists to catch, so the predicate is unevaluated instead.
    """
    parent = assess_security(sec(is_parent_company=True),
                             broker_list=broker_list('VNM'))
    assert parent.result is MarginEligibility.INDETERMINATE
    assert ExclusionPredicate.LOSS_OR_ACCUMULATED_LOSS in parent.unevaluated
    consolidated = assess_security(
        sec(is_parent_company=True, statements_are_consolidated=True),
        broker_list=broker_list('VNM'))
    assert consolidated.result is MarginEligibility.ELIGIBLE


def test_a_fund_is_tested_on_nav_below_par_not_on_losses():
    """Dieu 3.6's second limb: one month below par inside the three-month window.

    A fund carries no period loss or accumulated loss, so the share limb would
    pass it silently; the kind selects the right test.
    """
    clean = assess_security(
        sec(kind=SecurityKind.FUND_UNIT, fund_nav_below_par_months=0,
            period_loss=None, accumulated_loss=None),
        broker_list=broker_list('VNM'))
    assert clean.result is MarginEligibility.ELIGIBLE
    below = assess_security(sec(kind=SecurityKind.FUND_UNIT,
                                fund_nav_below_par_months=1))
    assert below.failed == (ExclusionPredicate.LOSS_OR_ACCUMULATED_LOSS,)


def test_a_fund_nav_count_outside_the_three_month_window_is_refused():
    """Dieu 3.6 looks at three consecutive months; four is a different rule."""
    with pytest.raises(ValueError, match=str(FUND_NAV_LOOKBACK_MONTHS)):
        sec(kind=SecurityKind.FUND_UNIT,
            fund_nav_below_par_months=FUND_NAV_LOOKBACK_MONTHS + 1)


def test_a_known_exclusion_beats_an_unknown_sibling_limb():
    """An issuer known to have an accumulated loss is out, period.

    Reporting INDETERMINATE because a *sibling* limb is unknown would lose a
    positive exclusion we can actually make, in the direction that lets more
    borrowing happen.
    """
    verdict = assess_security(sec(period_loss=None, accumulated_loss=True))
    assert verdict.failed == (ExclusionPredicate.LOSS_OR_ACCUMULATED_LOSS,)
    assert verdict.result is MarginEligibility.INELIGIBLE


# --------------------------------------------------------------------------
# The SILENT mapping, and the two texts that do not match
# --------------------------------------------------------------------------

def test_a_post_2020_status_alone_is_undecided_by_default():
    """SILENT item 8, and the default must not invent a mapping.

    *Han che giao dich* is a status the post-2020 listing rules created. HOSE
    cuts margin for it; QD 87 Dieu 3.2's vocabulary predates it and does not
    name it. Defaulting either way would encode an answer nobody gazetted, so
    the default is INDETERMINATE -- which never reads as eligible either.
    """
    verdict = assess_security(
        sec(trading_statuses=(TradingStatus.HAN_CHE_GIAO_DICH,)),
        broker_list=broker_list('VNM'))
    assert verdict.result is MarginEligibility.INDETERMINATE
    assert verdict.unevaluated == (ExclusionPredicate.TRADING_STATUS,)
    assert verdict.failed == ()
    assert 'SILENT' in verdict.note


def test_the_two_readings_of_an_unmapped_status_are_both_reachable():
    """EXCLUDE is HOSE practice; IGNORE is Dieu 3.2 read literally.

    Both are defensible and neither is sourced as the answer, which is why the
    module ships the third option as the default and these two as choices.
    """
    facts = sec(trading_statuses=(TradingStatus.DINH_CHI_GIAO_DICH,))
    excluded = assess_security(facts, policy=EligibilityPolicy(
        unmapped_status_policy=UnmappedStatusPolicy.EXCLUDE))
    assert excluded.failed == (ExclusionPredicate.TRADING_STATUS,)
    ignored = assess_security(facts, broker_list=broker_list('VNM'),
                              policy=EligibilityPolicy(
                                  unmapped_status_policy=UnmappedStatusPolicy.IGNORE))
    assert ignored.result is MarginEligibility.ELIGIBLE


def test_a_gazetted_status_decides_even_alongside_an_unmapped_one():
    """HVN was excluded for *han che giao dich* AND *kiem soat* on 2026-04-03.

    *Kiem soat* is in Dieu 3.2 and decides on its own, so the security is
    determinately out and never enters the unresolved mapping.
    """
    verdict = assess_security(sec(trading_statuses=(
        TradingStatus.HAN_CHE_GIAO_DICH, TradingStatus.KIEM_SOAT)))
    assert verdict.result is MarginEligibility.INELIGIBLE
    assert verdict.unevaluated == ()


def test_the_two_status_groups_are_disjoint_and_cover_the_enum():
    """The split between gazetted and post-2020 statuses is the whole point.

    A status that drifted into both sets, or into neither, would silently pass
    through ``_test_trading_status`` as clean.
    """
    assert not STATUTORY_TRADING_STATUSES & UNMAPPED_TRADING_STATUSES
    assert (STATUTORY_TRADING_STATUSES | UNMAPPED_TRADING_STATUSES
            | {TradingStatus.NORMAL}) == set(TradingStatus)


def test_collateral_falling_off_the_list_follows_tt_120_by_default():
    """Spec 2.7, and the default is the conservative, higher-ranking text.

    TT 120 Dieu 9.6 takes the paper out of the collateral base for BOTH ratios.
    That lowers PV, hence EB and AB, hence AB/EB -- so calls fire sooner under
    it. A default that fired them later would flatter every run.
    """
    ruling = rule_on_ineligible_collateral('HVN', REVIEW)
    assert ruling.treatment is \
        IneligibleCollateralTreatment.EXCLUDED_FROM_BOTH_RATIOS
    assert ruling.counts_toward_initial_ratio is False
    assert ruling.counts_toward_maintenance_ratio is False
    assert ruling.counts_toward_any_ratio is False


def test_the_qd_87_reading_is_configurable_and_differs_on_the_initial_ratio():
    """The other text is reachable, and the difference is exactly one boolean.

    QD 87 Dieu 10.2 speaks only of AB -- the maintenance side -- so under it the
    paper still counts when the initial ratio is determined. TT 120 names both
    ratios. Picking one silently is the defect the spec warns about; the module
    picks one loudly and ships the other.
    """
    ruling = rule_on_ineligible_collateral(
        'HVN', REVIEW,
        treatment=IneligibleCollateralTreatment.RETAINED_AS_SECURITY)
    assert ruling.counts_toward_initial_ratio is True
    assert ruling.counts_toward_maintenance_ratio is False


def test_both_texts_agree_the_paper_stays_pledged_and_blocks_new_lending():
    """The three points of agreement, pinned so a refactor cannot lose them.

    ``remains_pledged`` matters most: dropping collateral from the ratio is not
    releasing it, and an engine that conflated the two would hand collateral
    back to a client in breach precisely when it is needed for a forced sale.
    """
    for treatment in IneligibleCollateralTreatment:
        ruling = rule_on_ineligible_collateral('HVN', REVIEW,
                                               treatment=treatment)
        assert ruling.blocks_new_lending is True
        assert ruling.remains_pledged is True


def test_every_ruling_carries_both_texts_and_says_which_one_it_applied():
    """*Do not pick one silently* -- so a printed ruling states both readings."""
    note = rule_on_ineligible_collateral('HVN', REVIEW).divergence
    assert note is INELIGIBLE_COLLATERAL_DIVERGENCE
    assert 'QD 87 Dieu 10.2' in note
    assert 'TT 120 Dieu 9.6' in note
    assert 'DO NOT MATCH' in note
    assert 'DEFAULTS TO TT 120' in note


# --------------------------------------------------------------------------
# The two published lists -- supplied, never compiled in
# --------------------------------------------------------------------------

def test_the_exchange_negative_list_excludes_with_the_reasons_it_published():
    """Layer 1 as published, with the exchange's own Dieu 3 reasons carried."""
    published = ExchangeMarginList(
        published_on=date(2026, 4, 3),
        ineligible={'HVN': (ExclusionPredicate.TRADING_STATUS,)},
        venue=Venue.HSX)
    verdict = assess_security(sec(ticker='HVN'), exchange_list=published,
                              broker_list=broker_list('HVN'))
    assert verdict.result is MarginEligibility.INELIGIBLE
    assert verdict.failed == (ExclusionPredicate.TRADING_STATUS,)


def test_a_ticker_named_with_no_reason_is_still_ineligible():
    """A snapshot naming a ticker excludes it whether or not it says why.

    HOSE publishes reasons in prose; a caller who could not parse one still
    knows the exchange excluded the ticker, and that is the operative fact.
    """
    published = ExchangeMarginList(published_on=date(2026, 4, 3),
                                   ineligible={'ASP': ()})
    verdict = assess_security(sec(ticker='ASP'), exchange_list=published)
    assert verdict.result is MarginEligibility.INELIGIBLE
    assert 'no machine-readable reason' in verdict.note


def test_the_statutory_layer_is_enforced_on_top_of_a_stale_exchange_list():
    """A security the exchange has not yet named is still checked from facts.

    Dieu 4.1 gives the exchange 2 business days to publish, so a snapshot can
    lag the trigger. We cannot know a broker's universe and we do not trust a
    list to be complete: the predicates run independently, and one that holds
    excludes the security anyway.
    """
    published = ExchangeMarginList(published_on=date(2026, 4, 3), ineligible={})
    verdict = assess_security(
        sec(trading_statuses=(TradingStatus.KIEM_SOAT_DAC_BIET,)),
        exchange_list=published, broker_list=broker_list('VNM'))
    assert verdict.result is MarginEligibility.INELIGIBLE
    assert verdict.failed == (ExclusionPredicate.TRADING_STATUS,)


def test_a_partial_extract_says_so_and_absence_from_it_proves_nothing():
    """Only Dieu 4.1's FULL snapshot makes an absence informative."""
    partial = ExchangeMarginList(published_on=date(2026, 4, 3), ineligible={},
                                 covers_venue_universe=False)
    verdict = assess_security(sec(), exchange_list=partial,
                              broker_list=broker_list('VNM'))
    assert 'PARTIAL' in verdict.note


def test_a_snapshot_for_another_venue_is_refused_rather_than_answered():
    """Each exchange publishes its own list, so one says nothing about another.

    Answering from a mismatched snapshot would be worse than refusing: the
    caller would get a confident verdict built on a document that never covered
    the security.
    """
    hnx_only = ExchangeMarginList(published_on=date(2026, 4, 3), venue=Venue.HNX)
    with pytest.raises(ValueError, match='HNX'):
        assess_security(sec(venue=Venue.HSX), exchange_list=hnx_only)


def test_a_snapshot_published_after_the_review_date_is_refused():
    """Eligibility is dated; a list from the future is a caller mistake."""
    future = ExchangeMarginList(published_on=REVIEW + timedelta(days=1))
    with pytest.raises(ValueError, match='after the review date'):
        assess_security(sec(), exchange_list=future)


def test_no_broker_list_is_indeterminate_and_never_an_implicit_yes():
    """The firm's positive list is a published document and we ship none.

    Treating its absence as permission would margin every security that passes
    the statutory layer, at a firm that may lend against thirty of them.
    """
    verdict = assess_security(sec())
    assert verdict.result is MarginEligibility.INDETERMINATE
    assert verdict.on_broker_list is None
    assert 'never an implicit yes' in verdict.note


def test_absence_from_the_firms_list_is_commercial_and_leaves_failed_empty():
    """A firm declining to lend is not a rule breach, and the split is reported.

    ``failed`` counts statutory exclusions. Putting a commercial decision in it
    would make a business choice look like a Dieu 3 exclusion in every report
    that counts them.
    """
    verdict = assess_security(sec(), broker_list=broker_list('FPT'))
    assert verdict.result is MarginEligibility.INELIGIBLE
    assert verdict.failed == ()
    assert verdict.on_broker_list is False
    assert 'COMMERCIAL' in verdict.note


def test_a_statutory_exclusion_beats_a_firm_list_that_still_carries_it():
    """Precedence is one-directional: the law wins over the supplied list.

    A firm that has not yet republished still may not lend against paper the
    exchange excluded, and Dieu 4.2 gives it only 2 business days to catch up.
    """
    verdict = assess_security(
        sec(trading_statuses=(TradingStatus.CANH_BAO,)),
        broker_list=broker_list('VNM'))
    assert verdict.result is MarginEligibility.INELIGIBLE
    assert verdict.failed == (ExclusionPredicate.TRADING_STATUS,)
    assert verdict.on_broker_list is True


def test_a_firm_list_that_predates_the_exchange_snapshot_is_flagged():
    """Dieu 4.2's 2-business-day republication window, made visible.

    The statutory layer is enforced regardless; the note is what tells a reader
    the commercial layer may be out of date.
    """
    published = ExchangeMarginList(published_on=date(2026, 4, 3))
    stale = broker_list('VNM', published_on=date(2026, 1, 5))
    verdict = assess_security(sec(), exchange_list=published, broker_list=stale)
    assert 'predates the exchange snapshot' in verdict.note
    assert verdict.result is MarginEligibility.ELIGIBLE


def test_a_firm_list_is_not_applied_before_its_own_effective_date():
    """Brokers issue add/remove notices with an effective date.

    Applying one early would margin a ticker on the strength of a document that
    does not bind yet, so the commercial layer is simply undecided until then.
    """
    future = broker_list('VNM', published_on=date(2026, 8, 20),
                         effective_from=date(2026, 9, 1))
    verdict = assess_security(sec(), broker_list=future)
    assert verdict.result is MarginEligibility.INDETERMINATE
    assert verdict.on_broker_list is None
    assert 'not applied early' in verdict.note


def test_a_list_cannot_take_effect_before_it_was_published():
    """Dieu 4.2 makes publication the act that binds."""
    with pytest.raises(ValueError, match='precedes'):
        BrokerMarginList(tickers=frozenset({'VNM'}),
                         published_on=date(2026, 8, 20),
                         effective_from=date(2026, 8, 1))


def test_a_loan_ratio_for_paper_the_firm_does_not_list_is_a_contradiction():
    """Dieu 13.7 publishes the list and the ratios as one universe."""
    with pytest.raises(ValueError, match='not on this positive list'):
        BrokerMarginList(tickers=frozenset({'VNM'}),
                         published_on=REVIEW,
                         loan_ratio_by_ticker={'FPT': Decimal('0.5')})


def test_a_float_loan_ratio_is_refused_like_every_other_ratio_here():
    """House rule: Decimal for money and ratios, never float."""
    with pytest.raises(TypeError):
        BrokerMarginList(tickers=frozenset({'VNM'}), published_on=REVIEW,
                         loan_ratio_by_ticker={'VNM': 0.5})


def test_the_published_loan_ratio_reaches_the_verdict_and_terms_are_a_fallback():
    """The *ty le cho vay* is per-ticker, and either layer may carry it."""
    listed = broker_list('VNM',
                         loan_ratio_by_ticker={'VNM': Decimal('0.45')})
    assert assess_security(sec(), broker_list=listed).loan_ratio == \
        Decimal('0.45')
    fallback = assess_security(
        sec(), broker_list=broker_list('VNM'),
        terms=terms(loan_ratio_by_ticker={'VNM': Decimal('0.30')}))
    assert fallback.loan_ratio == Decimal('0.30')


def test_relisting_is_capped_at_once_every_six_months_except_the_new_listing():
    """Dieu 4.1's cadence, and its single carve-out.

    The function returns the EARLIEST permissible date, not a prediction: the
    exact timing inside the window is the exchange's call.
    """
    assert earliest_relist_date(date(2026, 4, 3)) == date(2026, 10, 3)
    assert earliest_relist_date(
        date(2026, 4, 3), listed_under_six_months_case=True) == date(2026, 4, 3)


# --------------------------------------------------------------------------
# Spec 2.5 -- the investor
# --------------------------------------------------------------------------

def test_an_investor_nobody_has_asserted_anything_about_is_undecided():
    """The default record establishes nothing, so it establishes no permission.

    A caller who has supplied no facts has not shown the investor may borrow,
    and the honest answer is INDETERMINATE rather than a pass.
    """
    verdict = assess_investor(InvestorFacts(account_id='068C1', as_of=REVIEW))
    assert verdict.result is MarginEligibility.INDETERMINATE
    assert verdict.has_margin_contract is False


def test_without_the_margin_contract_there_is_no_lending_to_discuss():
    """TT 120 Dieu 9.1 / QD 87 Dieu 12.1: that contract IS the credit agreement."""
    verdict = assess_investor(clean_investor(has_margin_contract=False))
    assert verdict.result is MarginEligibility.INELIGIBLE
    assert 'credit agreement' in verdict.note


def test_an_unstated_contract_is_not_assumed_into_existence():
    """Unstated is undecidable, not "probably signed"."""
    verdict = assess_investor(clean_investor(has_margin_contract=None))
    assert verdict.result is MarginEligibility.INDETERMINATE
    assert 'will not assume a credit agreement' in verdict.note


def test_every_dieu_13_4_holder_class_disqualifies():
    """QD 87 Dieu 13.4, read off the dated row rather than hard-coded here."""
    for holder_class in QD_87_2017.ineligible_account_holders:
        verdict = assess_investor(clean_investor(holder_classes=(holder_class,)))
        assert verdict.result is MarginEligibility.INELIGIBLE, holder_class
        assert verdict.failed == (holder_class,)


def test_a_holder_class_that_could_not_be_checked_is_unevaluated():
    """*Nguoi co lien quan* needs a relationship graph no corpus here carries.

    Naming it as unknown is how it reaches ``unevaluated`` instead of being
    assumed away, and with nothing positively failing that makes the whole
    answer INDETERMINATE.
    """
    verdict = assess_investor(clean_investor(
        unknown_holder_classes=(IneligibleAccountHolder.RELATED_PERSON,)))
    assert verdict.result is MarginEligibility.INDETERMINATE
    assert verdict.unevaluated == (IneligibleAccountHolder.RELATED_PERSON,)


def test_a_class_cannot_be_both_established_and_unknown():
    """Allowing it would make the verdict depend on which set was read first."""
    with pytest.raises(ValueError, match='both holder_classes'):
        InvestorFacts(account_id='068C1', as_of=REVIEW,
                      holder_classes=(IneligibleAccountHolder.CTCK_INSIDER,),
                      unknown_holder_classes=(
                          IneligibleAccountHolder.CTCK_INSIDER,))


def test_a_stated_foreign_investor_is_refused_and_the_note_names_dieu_9a():
    """The flat bar is enforced -- and reading it as "no foreign credit" is wrong.

    TT 120 Dieu 9a is broker credit extended to precisely the class Dieu 9.2
    bars, under a different regime. An implementer who reads only the refusal
    builds a simulator that refuses all foreign credit-funded buying.
    """
    verdict = assess_investor(clean_investor(is_foreign_investor=True))
    assert verdict.result is MarginEligibility.INELIGIBLE
    assert IneligibleAccountHolder.FOREIGN_INVESTOR in verdict.failed
    assert 'Dieu 9a' in verdict.note


def test_an_unstated_nationality_falls_to_the_domestic_scope_cut_out_loud():
    """The standing scope cut of this iteration, and it is never silent.

    The assumption is written onto the verdict every time it is relied on, so a
    published result carrying it discloses it. Everything else in this layer
    treats an unstated fact as undecidable; this one place does not, and that
    is exactly why it has to announce itself.
    """
    verdict = assess_investor(clean_investor(is_foreign_investor=None))
    assert verdict.result is MarginEligibility.ELIGIBLE
    assert DOMESTIC_INVESTOR_ASSUMPTION_NOTE in verdict.note
    assert 'ASSUMES A DOMESTIC INVESTOR' in verdict.note


def test_turning_the_scope_cut_off_makes_an_unstated_nationality_undecided():
    """It is configurable, and the strict setting behaves like every other fact."""
    verdict = assess_investor(
        clean_investor(is_foreign_investor=None),
        policy=EligibilityPolicy(assume_domestic_investor=False))
    assert verdict.result is MarginEligibility.INDETERMINATE
    assert IneligibleAccountHolder.FOREIGN_INVESTOR in verdict.unevaluated


def test_the_scope_cut_never_overrides_a_stated_nationality():
    """What is cut is the modelling of foreign investors, not the prohibition."""
    verdict = assess_investor(clean_investor(is_foreign_investor=True),
                              policy=EligibilityPolicy(
                                  assume_domestic_investor=True))
    assert verdict.result is MarginEligibility.INELIGIBLE


def test_an_unsegregated_account_and_a_second_account_are_both_barred():
    """TT 120 Dieu 9.3: one margin account per investor per CTCK, segregated."""
    unsegregated = assess_investor(
        clean_investor(margin_account_is_segregated=False))
    assert unsegregated.result is MarginEligibility.INELIGIBLE
    assert 'not segregated' in unsegregated.note
    second = assess_investor(
        clean_investor(has_other_margin_account_at_ctck=True))
    assert second.result is MarginEligibility.INELIGIBLE
    assert 'one per investor per firm' in second.note


def test_unstated_account_architecture_is_not_a_bar_and_says_why():
    """The one place an unstated fact does not force INDETERMINATE, on purpose.

    Segregation is a duty on the CTCK's account architecture rather than a
    property of the investor, and in a simulator we build that architecture
    ourselves. Declared as our choice in PROVENANCE.
    """
    verdict = assess_investor(clean_investor())
    assert verdict.result is MarginEligibility.ELIGIBLE
    entry = ELIGIBILITY_PROVENANCE['unasserted_account_architecture']
    assert entry.grade is SourceGrade.DERIVED
    assert entry.is_assumption


def test_the_authorised_trader_bar_is_off_by_default_and_is_not_statute():
    """One firm's FAQ item, REPORTED, and a broker term -- so it is opt-in.

    A statutory run must not silently carry a house rule, and when it is turned
    on the refusal says it is not a Dieu 13.4 class.
    """
    facts = clean_investor(trades_through_authorised_person=True)
    assert assess_investor(facts).result is MarginEligibility.ELIGIBLE
    barred = assess_investor(facts, policy=EligibilityPolicy(
        bar_authorised_traders=True))
    assert barred.result is MarginEligibility.INELIGIBLE
    assert 'NOT STATUTE' in barred.note
    assert barred.failed == ()


# --------------------------------------------------------------------------
# Spec 2.11 -- prohibited collateral, QD 87 Dieu 10.1(a)-(e)
# --------------------------------------------------------------------------

def rel(**overrides) -> CollateralRelationship:
    """A ticker with no prohibited relationship to the lending firm."""
    base = dict(
        ticker='VNM',
        as_of=REVIEW,
        self_underwritten=False,
        is_own_share=False,
        issuer_stake_in_ctck=Decimal('0'),
        ctck_stake_in_issuer=Decimal('0'),
    )
    base.update(overrides)
    return CollateralRelationship(**base)


def test_ordinary_collateral_for_an_ordinary_client_is_permitted():
    """All six limbs checked, none holds -- the only path to may_lend."""
    verdict = assess_collateral(rel(), assess_investor(clean_investor()),
                                account_meets_required_ratio=True)
    assert verdict.result is MarginEligibility.ELIGIBLE
    assert verdict.may_lend is True
    assert verdict.prohibited == ()


def test_a_relationship_nobody_asserted_is_undecided_and_may_lend_is_false():
    """INDETERMINATE is not permission, and the property says so."""
    verdict = assess_collateral(
        CollateralRelationship(ticker='VNM', as_of=REVIEW),
        assess_investor(clean_investor()))
    assert verdict.result is MarginEligibility.INDETERMINATE
    assert verdict.may_lend is False
    assert set(verdict.unevaluated) >= {
        ProhibitedCollateral.SELF_UNDERWRITTEN,
        ProhibitedCollateral.AFFILIATED_ISSUER,
        ProhibitedCollateral.OWN_SHARES,
        ProhibitedCollateral.CLIENT_BELOW_REQUIRED_RATIO}


def test_self_underwritten_paper_is_locked_out_for_six_months_after_the_offering():
    """Dieu 10.1(a), both sides of the anniversary."""
    inside = assess_collateral(
        rel(self_underwritten=True, offering_completed_on=date(2026, 3, 1)),
        assess_investor(clean_investor()), account_meets_required_ratio=True)
    assert inside.prohibited == (ProhibitedCollateral.SELF_UNDERWRITTEN,)
    assert '2026-09-01' in inside.note
    outside = assess_collateral(
        rel(self_underwritten=True, offering_completed_on=date(2026, 2, 1)),
        assess_investor(clean_investor()), account_meets_required_ratio=True)
    assert outside.result is MarginEligibility.ELIGIBLE


def test_an_offering_that_has_not_completed_leaves_the_lockout_open():
    """Determinate, not unknown, and it is the conservative side.

    The window runs to six months AFTER completion, so an offering nobody has
    recorded as complete has not started the clock at all.
    """
    verdict = assess_collateral(rel(self_underwritten=True),
                                assess_investor(clean_investor()),
                                account_meets_required_ratio=True)
    assert verdict.prohibited == (ProhibitedCollateral.SELF_UNDERWRITTEN,)
    assert 'has not completed' in verdict.note


def test_the_affiliation_threshold_bites_in_both_directions():
    """Dieu 10.1(b) reaches an issuer owning the CTCK and a CTCK owning it."""
    threshold = QD_87_2017.affiliate_ownership_threshold
    for field_name in ('issuer_stake_in_ctck', 'ctck_stake_in_issuer'):
        verdict = assess_collateral(rel(**{field_name: threshold}),
                                    assess_investor(clean_investor()),
                                    account_meets_required_ratio=True)
        assert verdict.prohibited == (
            ProhibitedCollateral.AFFILIATED_ISSUER,), field_name
    just_under = assess_collateral(
        rel(issuer_stake_in_ctck=threshold - Decimal('0.0001')),
        assess_investor(clean_investor()), account_meets_required_ratio=True)
    assert just_under.result is MarginEligibility.ELIGIBLE


def test_a_stake_outside_zero_to_one_is_refused_as_the_wrong_unit():
    """Dieu 10.1(b) is a 50 % ownership threshold, so this is a fraction."""
    with pytest.raises(ValueError, match='fraction'):
        rel(issuer_stake_in_ctck=Decimal('50'))
    with pytest.raises(TypeError):
        rel(ctck_stake_in_issuer=0.5)


def test_the_firms_own_shares_are_prohibited_collateral():
    """Dieu 10.1(c), and it does not care what the exchange list says."""
    verdict = assess_collateral(rel(is_own_share=True),
                                assess_investor(clean_investor()),
                                account_meets_required_ratio=True)
    assert verdict.prohibited == (ProhibitedCollateral.OWN_SHARES,)


def test_a_client_below_the_required_ratio_may_not_borrow_more():
    """Dieu 10.1(d) is a LENDING prohibition, not a margin call.

    An account in breach may not borrow more whether or not a call has issued,
    and an unstated ratio leaves the limb undecided rather than satisfied.
    """
    breach = assess_collateral(rel(), assess_investor(clean_investor()),
                               account_meets_required_ratio=False)
    assert breach.prohibited == (
        ProhibitedCollateral.CLIENT_BELOW_REQUIRED_RATIO,)
    assert 'independently of whether a margin call has issued' in breach.note
    unstated = assess_collateral(rel(), assess_investor(clean_investor()))
    assert unstated.unevaluated == (
        ProhibitedCollateral.CLIENT_BELOW_REQUIRED_RATIO,)


def test_the_investor_limbs_compose_rather_than_asking_for_the_facts_twice():
    """Dieu 10.1(dd) and (e) are read off the investor assessment.

    The nationality bar and the Dieu 13.4 classes are already decided there, and
    an *unevaluated* class there stays unevaluated here rather than resetting to
    clean.
    """
    foreign = assess_collateral(
        rel(), assess_investor(clean_investor(is_foreign_investor=True)),
        account_meets_required_ratio=True)
    assert ProhibitedCollateral.FOREIGN_INVESTOR in foreign.prohibited
    insider = assess_collateral(
        rel(),
        assess_investor(clean_investor(
            holder_classes=(IneligibleAccountHolder.CTCK_INSIDER,))),
        account_meets_required_ratio=True)
    assert ProhibitedCollateral.INELIGIBLE_ACCOUNT_HOLDER in insider.prohibited
    assert 'ctck_insider' in insider.note
    unknown = assess_collateral(
        rel(),
        assess_investor(clean_investor(
            unknown_holder_classes=(IneligibleAccountHolder.RELATED_PERSON,))),
        account_meets_required_ratio=True)
    assert unknown.result is MarginEligibility.INDETERMINATE
    assert ProhibitedCollateral.INELIGIBLE_ACCOUNT_HOLDER in unknown.unevaluated


def test_the_domestic_scope_cut_propagates_onto_the_collateral_assessment():
    """A lending decision that leaned on the assumption has to disclose it too.

    The assumption is made on the investor and used on the collateral, and a
    caller reading only the second record would otherwise never see it.
    """
    verdict = assess_collateral(
        rel(), assess_investor(clean_investor(is_foreign_investor=None)),
        account_meets_required_ratio=True)
    assert verdict.result is MarginEligibility.ELIGIBLE
    assert DOMESTIC_INVESTOR_ASSUMPTION_NOTE in verdict.note


def test_every_dieu_10_1_limb_is_visited():
    """Six limbs, and none may be quietly unreachable.

    A limb nobody evaluates is a prohibition that never fires, which is the
    same failure as a missing exclusion predicate one layer up.
    """
    verdict = assess_collateral(
        CollateralRelationship(ticker='VNM', as_of=REVIEW),
        assess_investor(InvestorFacts(
            account_id='068C1', as_of=REVIEW,
            unknown_holder_classes=tuple(IneligibleAccountHolder))))
    assert set(verdict.unevaluated) == set(QD_87_2017.prohibited_collateral)


# --------------------------------------------------------------------------
# Provenance for what this layer decided on its own
# --------------------------------------------------------------------------

def test_the_eligibility_choices_are_folded_into_one_provenance_table():
    """A caller still has ONE place to read before quoting a value.

    Disjointness matters: a colliding key would silently replace an earlier
    stage's disclosure with this one's.
    """
    assert not set(ELIGIBILITY_PROVENANCE) & (
        set(PROVENANCE) - set(ELIGIBILITY_PROVENANCE))
    for key, entry in ELIGIBILITY_PROVENANCE.items():
        assert PROVENANCE[key] is entry


def test_nothing_this_layer_chose_is_graded_verified():
    """A choice we made is never a clause someone read.

    Every entry here is DERIVED, SILENT or REPORTED. Grading one VERIFIED would
    be the overclaim this whole module is built to prevent.
    """
    for key, entry in ELIGIBILITY_PROVENANCE.items():
        assert entry.grade is not SourceGrade.VERIFIED, key


def test_the_two_places_the_spec_forbids_inventing_are_declared():
    """SILENT item 8 and the section 2.7 divergence, each with its own entry."""
    assert ELIGIBILITY_PROVENANCE['unmapped_trading_status_default'].grade \
        is SourceGrade.SILENT
    divergence = ELIGIBILITY_PROVENANCE['ineligible_collateral_divergence']
    assert divergence.grade is SourceGrade.DERIVED
    assert 'TWO TEXTS THAT DO NOT MATCH' in divergence.note
    assert 'RETAINED_AS_SECURITY' in divergence.note


def test_the_domestic_scope_cut_is_declared_with_the_non_prefunded_warning():
    """The scope cut is a modelling decision and carries the Dieu 9a caveat."""
    entry = ELIGIBILITY_PROVENANCE['domestic_investor_scope_cut']
    assert entry.is_assumption
    assert 'STANDING SCOPE CUT' in entry.note
    assert 'Dieu 9a' in entry.note


def test_the_undated_statutory_constants_declare_that_they_are_undated():
    """Three statutory numbers sit at module level rather than on a dated row.

    That is a structural compromise, not a claim about the law, and the entry
    says so plus how to discharge it.
    """
    entry = ELIGIBILITY_PROVENANCE['eligibility_constants_undated']
    assert 'MODULE level' in entry.note
    assert 'Promote all three' in entry.note
    assert (LATE_DISCLOSURE_BUSINESS_DAYS, FUND_NAV_LOOKBACK_MONTHS,
            QD_1205_EFFECTIVE_FROM) == (5, 3, date(2018, 1, 2))


def test_the_section_2_7_choice_lives_on_the_policy_and_is_actually_read():
    """One default, on the policy object, and the ruling function reads it.

    A configurable interpretive choice that silently does not apply is worse
    than one never offered: a caller who set
    ``ineligible_collateral_treatment`` and got TT 120 anyway would report the
    QD 87 Dieu 10.2 reading while running the other one. The explicit
    ``treatment`` keyword still overrides for a single call.
    """
    qd87 = EligibilityPolicy(
        ineligible_collateral_treatment=(
            IneligibleCollateralTreatment.RETAINED_AS_SECURITY))
    assert rule_on_ineligible_collateral(
        'HVN', REVIEW, policy=qd87).counts_toward_initial_ratio is True
    assert rule_on_ineligible_collateral('HVN', REVIEW) \
        .counts_toward_initial_ratio is False
    assert rule_on_ineligible_collateral(
        'HVN', REVIEW, policy=qd87,
        treatment=IneligibleCollateralTreatment.EXCLUDED_FROM_BOTH_RATIOS
    ).counts_toward_initial_ratio is False
