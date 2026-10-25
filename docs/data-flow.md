# How data flows: from raw records to answers

BOP Evolve turns raw, messy records from approved source systems into trusted data, then information, then reviewed knowledge, and finally answers that lead to action. The same story is shown, animated and with live numbers, on the **How Data Flows** page of the app and as the animation on the sign-in screen.

```mermaid
flowchart TB
  subgraph S1["1 · Raw data"]
    A1["Approved source systems<br/>CRM · QA reviews · Complaints<br/>Call-centre metadata · LMS · Policy catalogue"]
  end

  subgraph S2["2 · Trusted data"]
    B1["Check schema and required fields"]
    B2["De-duplicate and map to opaque<br/>employee, branch and policy IDs"]
    Q[("Quarantine and alert")]
  end

  subgraph S3["3 · Information"]
    C1["Versioned policy rules"]
    C2["Approved models (advisory)"]
    C3["Potential finding<br/>reasons · confidence · evidence pointers"]
  end

  subgraph S4["4 · Knowledge"]
    D1["Reviewer decision<br/>and rationale"]
    D2["Employee response<br/>and dispute"]
    D3["Context: person, policy,<br/>process, system or workload"]
    PO["Policy and process owners"]
  end

  subgraph S5["5 · Answers"]
    E1["Actions: coaching, training, job aids"]
    E2["Follow-up on comparable later cases"]
    E3["Learning profile G0 to Gx, approved by a person<br/>Dashboards, reports and scenarios"]
  end

  F(["Answers: what happened · did they know · are they improving<br/>people or process · what helps · can I trust it"])

  A1 --> B1
  B1 --> B2
  B1 -. "invalid records" .-> Q
  B2 --> C1
  B2 --> C2
  C1 --> C3
  C2 --> C3
  C3 --> D1
  C3 --> D2
  D1 --> D3
  D2 --> D3
  D3 --> E1
  E1 --> E2
  E2 --> E3
  E3 --> F
  D3 -. "systemic issue" .-> PO
  PO -. "fix the cause" .-> C1
```

## What changes at each step

| Stage | State of the data | What is added | Guardrail |
|---|---|---|---|
| 1 · Collect | **Raw**: messy, incomplete, mixed formats | Source system, extraction time, batch ID | Only approved sources are enabled; no customer content is copied |
| 2 · Validate | **Trusted**: schema-valid, unique, mapped | Opaque IDs, policy version in force on the event date | Invalid records are quarantined and alerted, never silently dropped |
| 3 · Detect | **Information**: a potential finding | Rule and policy version, expected vs observed action, confidence, limitations | Outputs are advisory; a finding stays *potential* until a person reviews it |
| 4 · Review | **Knowledge**: a decided finding in context | Reviewer rationale, employee awareness and dispute, contributing factor | Self-reported awareness, reviewer assessment and demonstrated learning stay separate |
| 5 · Learn | **Answers and action**: outcomes over time | Actions with evidence, follow-up results, learning-profile versions, aggregates | Privacy thresholds on aggregates; no single score decides anything about a person |

## Follow one record

This is the example shown in the app (synthetic data).

| Stage | The record |
|---|---|
| Raw | `{"src":"QA","key":"E-1001-00141","type":"account_opening","ts":"2026-10-24T12:27Z","id_check":"after_activation"}` |
| Trusted | Schema valid, not a duplicate. Mapped to employee E-1001, North Branch 01 · Tellers. Policy KYC-01 v1.1 was in force on that date. |
| Information | Potential finding, rule `KYC_DOC_CHECK` v2. Expected: verify the ID document before activating the account. Observed: verification recorded after activation. Confidence 80 %. |
| Knowledge | Employee: "I was unsure." Reviewer: confirmed; policy clear, evidence supports, factor is process design. |
| Answers | Coaching and a job aid agreed and completed. 0 recurrences in 6 comparable cases. Learning profile proposed to advance to G4 Practice; a manager approves it. |

## Questions each part answers

| Question | Where in the app |
|---|---|
| What happened, and why was it flagged? | Mistake Explorer → case detail |
| Did the employee know it was a mistake? | Case detail: the three separate states |
| Is the person improving over time? | Employee Learning |
| Is it a people, policy or process problem? | Team & Branch Insights (systemic share) |
| Which intervention is likely to help most? | Future Scenarios (illustrative) |
| Can I trust these numbers? | Pipeline & Model Health |

Implementation pointers: ingestion and rules in `backend/app/pipeline/`, review and response workflow in `backend/app/api/cases.py`, learning generations in `backend/app/services/learning.py`, the animation in `frontend/src/components/FlowCanvas.tsx`, and the page in `frontend/src/pages/DataFlow.tsx`.
