# Publish checklist

What must be true before this ships as something a researcher can point an algorithm at
and trust. Kept short on purpose: the full inventory is `FEATURES.md`, and this is only
the subset that blocks a release.

Status as of 2026-08-27. Suite: **2319 passing**.

---

## MUST — blocks publication

| # | Item | Why it blocks | State |
|---|---|---|---|
| 1 | **Order-book walk** | Without it, fills happen at a single price with no depth. The fidelity audit's verdict on that state: *"an excellent accounting engine attached to an execution model that is not a simulation of a market."* A user would be validating their strategy's accounting, not its executability. | In progress |
| 2 | **Amendment re-runs encumbrance and admission** | `ExchangeSession.amend` exists and implements the dated Vietnamese amendment rules (phase locks, priority preservation per QĐ 352 Điều 21.3). What it does not do is re-reserve funding or re-check admission, so an amend-up escapes both. Its own docstring records this as a deliberate Tier 1 scope cut. Two additions to an existing function, not a new feature. | Not started |

**That is the entire must-list.** Two items.

---

## RESOLVED — items that were on this list and are not any more

**A shipped VSDC settlement calendar.** Removed 2026-08-27. A settlement calendar does not
have to ship: VSDC works exactly the days the exchange trades, so T+N counted over
days-the-data-carries lands on the published answer. Verified at three Tết closures, and a
2026-02-12 trade gives **2026-02-23**, matching Announcement 4228/TB-VSDC.

This was on the list because of an imprecise claim in our own docs — `calendar.py` and the
design spec both said settlement days *"diverge from trading days"*, when what diverges is
**weekdays** versus trading days. Both corrected. See
`memory/settlement-calendar-from-data.md`.

Deriving it is also the better engineering: a shipped calendar goes stale the moment VSDC
publishes a new year, whereas a derived one is correct for whatever window the user has and
fails loudly (no data) rather than silently (wrong holiday).

Futures expiry needs no calendar either — `quote.ticker.expdate` is populated for all 73
contracts.

---

## SHOULD — ship better with these, but declarable without

- **Close the remaining permissive paths.** Several were found and fixed; the last audit
  found five more, of which `BAND_LOCK` having no fill-time counterpart is the important
  one — and the book walk closes it as a side effect, since a locked book simply has no
  levels to sweep.
- **Ship `SMrate` and `MF` values** for the post-KRX scenario margin. SSI and TCBS publish
  theirs (0.87% basis rate; 5,000đ minimum margin per VN30 contract). Without them the
  model is wired but cannot compute.
- **Exercise the post-KRX scenario margin further** — wired and running, but only ~55% of
  its lines have executed under any test. Untested is not wrong, but it is unproven.

---

## DECLARABLE — absent, and honest to say so

These do not block a release provided the limitation is stated. Roughly eight are things a
Vietnamese trader would actually notice; the rest are config variants and charge
line-items. See `FEATURES.md` §16 for the full list with reasons.

Short selling (not permitted for Vietnamese equities anyway) · VAT · dividend withholding
tax · interest accrual pass · position-limit warning ladder (80/90/100, primary-sourced,
just not applied) · intraday margin checkpoints (09h30/14h00/16h30) · VSDC
collateral-management fee · government bond futures (deferred by author decision) ·
foreign-ownership room (tradeoff T1) · event-driven callbacks.

---

## How to keep this file honest

Update it in the same commit as any change to its items. A checklist that drifts is worse
than none, because it will be trusted. If an item moves off the MUST list, say **why** in
the RESOLVED section rather than deleting the row — the reasoning is what a later reader
needs, and in the calendar case the reasoning was itself a correction to a mistake we had
made.
