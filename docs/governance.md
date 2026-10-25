# Governance notes for the prototype

This repository is a **mock-data prototype**. Before any real data is used, the bank must approve data access, monitoring purposes, employee notice, retention, security controls, model validation, and the use of analytics in employment decisions.

## What the prototype enforces

* **Synthetic data only.** A persistent "Demo data — simulated" banner, an `X-Demo-Data: synthetic` header, and CSV exports prefixed with a synthetic-data line.
* **Safe-by-default configuration.** The API refuses to start with `APP_ENV=production` while `AUTH_MODE=mock` or `DEMO_MODE=true`, or with the default JWT secret.
* **Server-side authorisation.** Every endpoint checks permissions and filters rows by the caller's organisational scope. Out-of-scope records return 404 so their existence is not disclosed.
* **Least privilege.** Data/AI operations see pipeline and model health but no case content; analysts see aggregates only; employees see only their own records; restricted evidence is hidden from roles without that permission.
* **Human oversight.** Rules/models only create *potential* findings. A reviewer records the decision with rationale; reviewers cannot review findings about themselves; employees cannot approve their own learning profile.
* **Employee voice.** Self-reported awareness, reviewer assessment and demonstrated learning are stored and shown separately. Employees can dispute and request review (status becomes `DISPUTED`).
* **Immutable history.** Review decisions, model runs and learning generations are append-only; new evaluations create proposed versions that must be approved.
* **Privacy thresholds.** Team/branch insights suppress groups below 3 employees or 10 cases (configurable).
* **No false certainty.** Scenario simulation is aggregate, labelled illustrative, shows 90 % intervals, sample sizes and limitations; employee-level estimates are disabled behind a configuration gate and attempts are audited.
* **Audit.** Logins (including failures), case and learning-profile views, reviews, responses, actions, approvals, simulations, report views, pipeline controls and admin changes are recorded with request IDs; sensitive metadata keys are redacted.

## Decisions still required (from the specification §22)

1. First pilot process.
2. Policy owner approval of each mistake definition and severity.
3. Approved read-only source system.
4. Evidence visibility for employees and managers.
5. Formal response, dispute and appeal workflow.
6. Owner and approval of the learning-generation method and weights.
7. Retention periods for cases, evidence references and audit logs.
8. Standard authentication, database, deployment and monitoring platforms.
9. Which model outputs are allowed in the pilot.
10. Exit criteria for moving from mock to real data.
