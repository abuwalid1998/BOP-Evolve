# Generative AI assistant (Groq)

BOP Evolve uses a large language model to **write and explain** in English and Arabic. The default is `openai/gpt-oss-20b` on Groq's OpenAI-compatible API.

The assistant never decides anything and never changes data. Every answer is a draft labelled with the model and time, for a qualified person to review.

## Where it appears

| Screen | Feature switch | What it does |
|---|---|---|
| Policies & Control Rules › policy editor | `policy_writing` | Drafts the policy title and statement (English and Arabic), key requirements and rationale from your notes. **Use this draft** fills the form. |
| Policies & Control Rules › rule editor | `policy_writing` | Turns a plain-language description into a control rule. It proposes the name, risk, expected and observed wording, severity, kind and **conditions**. The conditions are validated by the rules engine like any other rule, and rejected if they use facts that do not exist for the service type. The live backtest then shows the impact. |
| Policies & Control Rules › rule detail | `policy_writing` | Explains the 90-day backtest: volume, accuracy indicator, lift, comparison with the version in force, and a recommendation. |
| Case file | `case_assistant` | Prepares the review conversation: summary, likely root cause, coaching points, open questions and a caution. |
| Employee Development Report | `employee_summary` | Strengths, focus areas, a development plan and a conversation opener. It is built from the report's figures and the employee's workplace KPIs. |
| Workplace policies | `workplace_insights` | Patterns, likely causes (habits vs scheduling, transport, staffing) and recommendations for a unit, from aggregates only. |
| Getting started / Staff onboarding | `onboarding` | Role-specific welcome, the 3-question policy quiz, and wave reminder drafts. |

## Privacy: pseudonymised payloads only

Each endpoint builds a purpose-made input (`backend/app/api/ai.py`, `backend/app/api/onboarding.py`).

**What is sent:**

- employee reference codes (for example `E-1001`, or an HMAC-derived code for imported staff)
- roles and dates
- rule facts and statistics
- policy texts
- unit names (for unit-level insights)

**What is never sent:**

- names
- HR employee numbers
- national IDs
- customer data
- free text written by staff (explanations, objections, reviewer rationale, observation notes)

Tests cover this. In `backend/tests/test_ai.py`, an employee's typed explanation is checked to be absent from every request sent to the provider.

## Configuration

The key **must never be committed**. It can come from either of two places:

1. **`.env`:** `GROQ_API_KEY=...`. `.env` is git-ignored, and `docker-compose.yml` passes the variable to the backend and worker.
2. **System Configuration › AI assistant:** a System Administrator pastes the key and it is stored **encrypted** (Fernet, `CONFIG_SECRET_KEY`). A stored key overrides the environment.

The key is never returned to the browser, written to logs or put in the audit trail. The screen only shows where it comes from and a masked hint.

The same tab also provides:

- **Test connection**, which makes one small live request
- the model and reasoning effort
- an on/off switch for the whole assistant and one per feature
- usage for the last 30 days (answers, failures, tokens)

| Variable | Default |
|---|---|
| `GROQ_API_KEY` | empty |
| `GROQ_MODEL` | `openai/gpt-oss-20b` (overridable at runtime as `ai.model`) |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` |
| `AI_TIMEOUT_SECONDS` | `45` |

**Network:** the backend container must reach `api.groq.com` over HTTPS. Behind a corporate proxy, set `HTTPS_PROXY` for the backend.

**Rotate keys:** any key that has been pasted into chat, email or a ticket should be rotated in the Groq console.

## How a request is made

`backend/app/services/ai.py` handles every request the same way:

1. Checks the master switch and the feature switch, and that a key exists.
2. Returns a cached answer when the identical input (task, prompt version, model, language, payload) was answered in the last 30 days. This is why all 3,400 people in a wave share one quiz per language.
3. Applies a per-user limit of 30 provider calls per 10 minutes.
4. Calls `POST /chat/completions` with:
   - `response_format: json_object`
   - for gpt-oss models, `reasoning_effort` (low, medium or high) and `include_reasoning: false`
5. Validates the required JSON keys. On invalid JSON it retries once.
6. Records the call in `ai_generations` (no key; the input only as a hash) and adds an `ai.<task>` audit event.

Errors map to clear messages in the UI: not configured, switched off, invalid key, rate limited, timeout, unreadable answer, provider unreachable.

## Verification status

The automated tests run the real HTTP client against a local stand-in for the Groq API. They check:

- the request shape
- caching and the retry
- switches, privacy and audit

From the development sandbox, `api.groq.com` was not reachable, so **live calls to Groq were not exercised here**. After adding your key, use **Test connection** to confirm.
