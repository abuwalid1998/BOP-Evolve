# Policies & control rules

The **Policies & Control Rules** page lets a Policy Owner state what good practice looks like, test it on history and bring it into force under four-eyes approval. Active rules are what the ingestion worker uses to flag new cases.

## Procedural facts

Every case carries `service_cases.attributes`: structured, non-customer facts about how the service was delivered. Common facts apply to every service type; the others to one or two.

| Fact | Type | Service types |
|---|---|---|
| `interaction_type` (service channel), `complexity_band`, `hour_of_day`, `queue_wait_minutes` | enum / number | all |
| `id_verified_before_activation`, `customer_segment`, `customer_risk_rating` | bool / enum | account opening |
| `transaction_kind`, `amount_ils`, `second_approval_recorded` | enum / number / bool | cash transactions (`amount_ils` also transfers) |
| `ack_business_days`, `reference_shared` | number / bool | complaint handling |
| `card_product`, `fees_disclosed`, `customer_acknowledgement_recorded` | enum / bool | card services |
| `transfer_scope`, `new_beneficiary`, `beneficiary_readback` | enum / bool | transfers |
| `inquiry_topic`, `product_sheet_current` | enum / bool | product & service inquiries |
| `financing_discussed`, `affordability_checked` | bool | financing inquiries |

The catalogue (labels in English and Arabic, options, units and bounds) is `FIELDS` in `backend/app/pipeline/catalogue.py`. In the demo the facts are synthetic: the seed and the worker generate them so that they agree with the findings, and long queues late in the day are deliberately more common before breaches so that early-warning indicators have something to find.

## Rule definition

```json
{ "match": "all",
  "conditions": [
    { "field": "transaction_kind", "op": "eq", "value": "withdrawal" },
    { "field": "amount_ils", "op": "gt", "value": 20000 },
    { "field": "second_approval_recorded", "op": "is_false" } ] }
```

`match` is `all` or `any`. Operators: `eq`, `neq`, `in`, `not_in` (enums), `gt`, `gte`, `lt`, `lte` (numbers), `is_true`, `is_false` (booleans). Up to 12 conditions. A missing fact never satisfies a condition. Definitions are validated on the server against the fact catalogue for the rule's service type.

Each rule version also carries a name, the risk it addresses, the expected behaviour, the typical observed deviation (all bilingual), a severity, a base confidence and a link to a **policy version**.

| Kind | Effect |
|---|---|
| **Policy control** (`breach`) | When active, the worker raises a *potential* finding for every new case that matches, storing the matched conditions and the facts observed (`findings.matched_conditions`), shown on the case file. |
| **Early-warning indicator** (`early_warning`) | Never raises a finding against a person. It is monitored and forecast on the Rules page, with its *risk lift*: how much more often matched cases end in a confirmed breach than the average. |

## Workflow and four-eyes approval

```
draft ──submit──▶ pending approval ──approve──▶ in force ──retire──▶ retired
  ▲                      │
  └──── return (reason) ─┘
```

- Rules and policy versions are never edited after submission; a change is a **new version** (one open version per rule or policy at a time).
- Approval needs `rules.approve` and a different person from the author and the submitter. The page explains why the button is missing for the author.
- Approving a rule version retires the version previously in force. A rule can only be approved when its policy version is in force.
- Approving a policy version supersedes the previous version from its effective date; the response lists active rules still linked to the old version so they can be reviewed.
- Every step is written to the audit trail (`rule.*`, `policy.*`).

| Permission | Roles |
|---|---|
| `rules.view` | every role (staff can read the rules they are assessed against) |
| `rules.author` | Policy Owner, Risk & Compliance, System Administrator |
| `rules.approve` | Policy Owner, Risk & Compliance, System Administrator (never one's own version) |

## Backtest and forecast

`POST /api/rules/backtest` (and `GET /api/rules/{id}/backtest`) replays a definition over the last 14–365 days of cases of its service type and returns:

- cases flagged and match rate;
- how many flagged cases were reviewed and confirmed — an indicator of accuracy;
- the risk lift against the average confirmed-breach rate;
- weekly counts;
- a 30- and 90-day projection from the last 28 days' rate with a 95 % Poisson interval, and the expected number confirmed;
- how often each condition holds on its own;
- for a new version, the overlap with the version in force (flagged by both, newly flagged, no longer flagged);
- up to five recent example cases, only for users with `cases.view`, within their scope.

These are aggregate workload estimates on synthetic data. They are not predictions about any individual and must not be used as such.

## Upgrading an existing database

Migration `0003` adds the columns and fills names and default conditions for the seven demo rules. `python -m app.seed.upgrade`, run by the container entrypoint after every migration, is idempotent: it adds roles introduced since seeding (Policy Owner, granted to `ops.policy`), and back-fills facts on synthetic cases and matched conditions on their findings.
