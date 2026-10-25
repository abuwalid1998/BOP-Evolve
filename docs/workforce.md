# Workforce development and the employee outlook

The **Workforce Development** page is the Chief HR Officer's view of every employee's development, and the **Employee Development Report** is its printable, per-employee version. Both need the `workforce.view` permission (role `hr_chief`, scope bank-wide; `super_admin` also has it). The demo account is `hr.chief` with password `123` (`HR_CHIEF_PASSWORD`).

## What is measured

All figures cover the last 12 months.

| Measure | Definition |
|---|---|
| Confirmed findings | Findings reviewed as *Confirmed* or *Confirmed (amended)*, by date of service. |
| Repeat occurrences | Confirmed findings within 90 days of an earlier confirmed finding of the same service type. |
| Learning from findings | Of the confirmed findings whose follow-up window has closed, the share with no repeat on comparable later cases. |
| Corrective actions | Agreed actions, completed, completed on or before the due date, open and overdue. |
| Development stage | The latest approved stage (G0–G5) and any stage awaiting approval. |
| Knowledge gaps | Per service type: the employee was not aware of or unsure about the requirement; understanding was not confirmed after feedback (14+ days after review); the finding repeated after coaching or training; assigned training is not complete; the policy was updated after the last coaching or training. |

The report also lists every finding with its date, the employee's account, the review decision (who, when, root cause), each corrective action with its owner, who agreed it, its status and dates, coaching sessions, and the follow-up result.

## Repeat-risk outlook

The outlook comes from the registered model **Employee repeat-risk estimator** (`backend/app/services/workforce.py`). It is fitted on the bank's own history every ten minutes (synthetic in the demo):

1. **Peer rate.** For each service type, confirmed findings per case across the bank.
2. **Employee propensity.** Observed vs expected confirmed findings for the employee across all the service types they handle, shrunk towards 1. The shrinkage strength is fitted by the method of moments from how much employees differ beyond Poisson noise (Poisson-gamma empirical Bayes).
3. **Service-type deviation.** The employee's record in that service type, shrunk towards their overall propensity (prior strength 3 expected findings).
4. **Learning effects.** From follow-up results: how much less often repeats happened when the latest corrective actions were completed, or when understanding was confirmed after feedback. The multipliers are constrained so that learning evidence can only lower the estimate and its absence can only raise it.

For the next 90 days, expected repeats = the employee's recent volume × the adjusted rate. The chance of at least one repeat is `1 − e^(−λ)`, shown next to the chance for a peer with the same caseload.

| Level | Rule |
|---|---|
| Low | Chance below 10 %, or below 0.85 × the peer chance |
| Elevated | At least 1.5 × the peer chance, and at least 15 % |
| Moderate | Everything else |

Each service type shows the drivers behind its estimate and a suggested development action: refresher training, completing open actions, supervised practice, a policy briefing, a referral to the process owner when causes are mainly systemic, or routine monitoring.

The outlook is an indicative estimate for planning development support. It is printed with its model card, it does not infer intent, and it must not be used for disciplinary or pay decisions. On synthetic data it demonstrates the method, not accuracy.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/hr/workforce?unit_id=` | Totals for the selected unit (the bank by default), its child units with aggregates, the employees inside it with their summary and outlook, and the model card. |
| `GET /api/hr/employees/{id}/report` | Everything the printed report shows. Audited as `hr.report_viewed`. |
| `POST /api/hr/employees/{id}/report/printed` | Records `hr.report_printed` in the audit trail; the page calls it before opening the print dialog. |
