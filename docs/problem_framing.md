# Problem Framing

> All data in this project is synthetic and contains IDs only (no names).
> Every number reported is "on synthetic data". Nothing here is a claim
> about real clinical or operational impact.

## Business questions
1. Where do patients drop out of the intake -> eligibility -> prior auth -> visit -> claim -> payment flow?
2. Did an AI reminder reduce no-shows (randomized experiment)?
3. Which patients should receive outreach when capacity is limited?

## Stakeholders
| Stakeholder | What they need |
|---|---|
| Clinic operations manager | Fewer no-shows, higher fill rate, shorter wait from intake to first visit |
| Clinical director | Access to care for high-acuity patients, no equity harm from targeting |
| Revenue cycle lead | Fewer denials, lower days in A/R, less revenue leakage |
| Product / AI team | Evidence on whether the reminder works and for whom |
| Data/analytics lead | Trustworthy, tested, documented metrics |

## KPI definitions (draft; finalized in Phase 3)
| KPI | Definition |
|---|---|
| No-show rate | no_show / (completed + no_show + late_cancel), scheduled appointments whose date has passed |
| Late-cancel rate | late_cancel / same denominator |
| Fill rate | booked appointment slots / available provider slots (slot capacity is an assumption) |
| Days intake -> first visit | first completed appointment date - intake date, per patient |
| Prior-auth turnaround | decided_ts - submitted_ts, in hours |
| PA SLA-breach rate | share of decisions slower than 72h (urgent) or 7 calendar days (standard). Reference thresholds are an ASSUMPTION borrowed from the CMS-0057-F public rule, not a claim about behavioral-health payers |
| Clean-claim rate | claims paid on first submission without denial / claims submitted |
| Denial rate by reason | denied claims / claims submitted, split by denial code |
| Days in A/R | mean(paid_date - submit_date) for paid claims |
| Revenue leakage | allowed amount on denied or unpaid claims past 90 days / total allowed |

## Decisions this data supports
- Whether to roll out the AI voice-call reminder (ship / iterate / stop).
- Which appointments to target when outreach capacity is 20% of volume.
- Where to fix the front-end flow (eligibility, prior auth) to cut drop-off.
- Which denial reasons to attack first in revenue cycle.

## Success criteria
- Pipeline runs end to end from a clean state with one command (make all).
- All dbt/SQL tests and pytest tests pass; every KPI is verified against an independent pandas calculation.
- Experiment analysis follows a pre-specified plan (power, validity checks, Holm correction).
- Model choice follows a promotion rule stated before running.
- Dashboard built with 5 pages; every README number traceable to a script.

## Hard rules
- Synthetic data only; effect sizes and noise rates are assumptions (see docs/assumptions.md).
- No tool is claimed unless it was actually run.
