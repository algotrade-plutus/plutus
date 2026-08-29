# T3 -- Dated rule editions across the simulated window

Each row is a **sourced** change to an exchange or depository rule inside the simulation window, with the edition on each side of the change, the effective date it turns on, and the source confidence. This is the structured evidence behind the paper's lead claim: an exchange rulebook has to be represented as *effective-dated editions resolved per simulated instant*, because a simulator that resolves rules once at load time judges most of its own sample under rules that were not in force.

> **Quote the per-rule figure, never an aggregate.** Exposure (the share of the sample sitting under a superseded edition) is a *ceiling* on the distortion a date-blind resolution can cause, not an estimate of it; it is tight for the round lot and loose for the UPCoM band. See the notes.

*Source: `measurements/dated_rules.py::DATED_CHANGES` (rendered verbatim). `corpus-measurable` marks whether corpus rows can be counted on each side of the change; margin ratios and settlement instants are real but leave no trace in a daily close series. The corpus window ends 2022-12-30.*

| Rule | Venue | Edition before | Edition after | Effective | Confidence | Corpus-measurable |
|---|---|---|---|---|---|---|
| `round_lot` | HSX | 10 shares | 100 shares | 2021-01-04 | high | yes |
| `price_band_wide_regime` | UPCOM | +/-15% ordinary | +/-40% after >25 sessions untraded | 2022-11-16 | high | yes |
| `settlement_delivery_time` | ALL | T+2 at next session open | T+2 at 13:00 | 2022-08-29 | high | no |
| `vsd_initial_margin` | HNXDS | 13% | 17% | 2022-12-15 | high | no |
| `krx_cutover` | HSX | pre-KRX order types, matching priority, closing price | post-KRX equivalents | 2025-05-05 | high | no |

## Notes and citations

- **`round_lot` (HSX, eff. 2021-01-04, confidence high; citation: HOSE minimum trading unit raised; rulebook s4.2).** The cleanest case. A date-blind lot of 100 rejects every legal 10-to-90 share HOSE order placed before this date.
- **`price_band_wide_regime` (UPCOM, eff. 2022-11-16, confidence high; citation: rulebook s3, corpus-measured, high).** READ THE EXPOSURE FIGURE FOR THIS ROW WITH CARE. The +/-15% ordinary band existed before this date; what 2022-11-16 added was the wide regime for names untraded >25 sessions. So the ~98% exposure below says only that most rows predate the addition, not that most rows are misjudged. The tighter and more honest figure is the rulebook's own corpus measurement: 70,578 of 412,041 UPCoM name-days (17.1%) actually carry the wide band, and separation from the ordinary band was total in an 8,000-row sample. Cite 17.1%, not the exposure.
- **`settlement_delivery_time` (ALL, eff. 2022-08-29, confidence high; citation: VSD decision; rulebook s5.1).** Changes the first sellable INSTANT, not the cycle length. Invisible in a daily close series but decisive for an intraday sell.
- **`vsd_initial_margin` (HNXDS, eff. 2022-12-15, confidence high; citation: VSD notice 2022-12-12; rulebook s6.3).** A 31% relative increase in the requirement. The derivatives PIT base is LINEAR in this ratio, so a date-blind value corrupts the tax model and the margin model together.
- **`krx_cutover` (HSX, eff. 2025-05-05, confidence high; citation: rulebook, THE KRX DELTA).** Outside the corpus window (which ends 2022-12-30), so exposure is zero HERE and total for anyone simulating 2025 onward. The reason the mechanism must exist before the data does.
