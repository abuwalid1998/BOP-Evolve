# Data dictionary

All timestamps are stored in UTC (`timestamp with time zone`) and shown in `Asia/Hebron` local time in the UI. Identifiers are opaque prefixed strings (e.g. `CS-3F9A0B12C4D7`). Demo data is synthetic; employees are pseudonymous (`E-1001`).

## Organisation & access

| Table | Key fields | Notes |
|---|---|---|
| `users` | `username`, `display_name(_ar)`, `password_hash`, `status` | `password_hash` is PBKDF2 for the mock login only. |
| `roles` | `code`, `name`, `description` | Codes in `services/rbac.py`. |
| `user_roles` | `user_id`, `role_id`, `scope_type`, `scope_id` | Unique per (user, role, scope). |
| `auth_sessions` | `user_id`, `expires_at`, `revoked_at` | Server-side session so logout/expiry are enforced. |
| `org_units` | `parent_id`, `unit_type`, `code`, `name(_ar)` | bank → department → region → branch → section. |
| `employee_profiles` | `user_id?`, `pseudonym`, `org_unit_id`, `role_title` | Restricted mapping. |

## Cases & workflow

| Table | Key fields | Notes |
|---|---|---|
| `source_systems` | `code`, `enabled`, `approved_for_use` | Unapproved sources cannot be enabled or resumed. |
| `service_cases` | `source_system_id`, `source_case_key`, `employee_id`, `org_unit_id`, `case_type`, `occurred_at`, `policy_version_id`, `attributes` | Unique `(source_system_id, source_case_key)`. No customer content. `attributes` holds the procedural facts the rules evaluate ([rules-engine.md](rules-engine.md)). |
| `evidence_refs` | `evidence_type`, `secure_reference`, `content_hash`, `access_class` | Pointers only; `restricted` hidden from roles without `evidence.view_restricted`. |
| `policy_versions` | `policy_code`, `version`, `effective_from/to`, `status`, `created_by`, `submitted_by/at`, `approved_by/at`, `review_note` | Status: `draft`, `pending_approval`, `active`, `superseded`, `retired`. Rule applied is the version effective on the event date. |
| `mistake_rules` | `rule_code`, `version`, `category`, `kind`, `name(_ar)`, `conditions`, `severity`, `base_confidence`, `expected_action(_ar)`, `observed_action(_ar)`, `status`, `created_by`, `submitted_by/at`, `approved_by/at`, `retired_at`, `review_note` | Control rules (UI name). Versioned; `kind` is `breach` or `early_warning`; status `draft`, `pending_approval`, `active`, `retired`; one active version per `rule_code`. |
| `findings` | `status`, `severity`, `explanation(_ar)`, `confidence`, `detection_method`, `contributing_factor`, `matched_conditions` | Status: `POTENTIAL`, `CONFIRMED`, `AMENDED`, `DISPUTED`, `DISMISSED`. |
| `employee_responses` | `stage`, `awareness_state`, `understood_after_feedback`, `contextual_factors`, `requested_review` | Self-reported awareness; never inferred. |
| `review_decisions` | `decision`, `rationale`, `policy_clear`, `evidence_supports`, `system_issue_contributed` | Append-only. |
| `improvement_actions` | `action_type`, `owner_id`, `due_at`, `status`, `completion_evidence_ref` | Completion requires evidence; completed/cancelled are immutable. |
| `follow_up_evaluations` | `window_days`, `comparable_cases`, `recurrences`, `recurred` | Comparable later cases (same employee & case type). |

## Learning

| Table | Key fields | Notes |
|---|---|---|
| `training_records` | `course_code`, `score`, `completed_at` | Knowledge checks feed "understanding". |
| `coaching_sessions` | `outcome_code`, `reflection` | `practiced` / `demonstrated` satisfy the G4 gate. |
| `learning_generations` | `version`, `generation_code`, `status`, `effective_at`, `end_at`, `score`, `coverage`, `indicator_snapshot`, `method_version` | Append-only; `proposed` → `approved` / `rejected`. |

### Learning method `demo-1.0` (illustrative only)

The parameters below are the defaults. A System Administrator can tune them on the System Configuration screen; tuned parameters produce a method version such as `demo-1.0+3f9a0b12`, and each learning version stores the parameters it was evaluated with.

Indicators (weights are mock settings, not approved criteria): understanding 25 %, action completion 25 %, comparable follow-up performance 30 %, exposure-adjusted recurrence trend 20 %. Missing components are excluded and reported as reduced *coverage*.

Sequential gates (cannot be skipped), evaluated over confirmed findings in the last 365 days that were reviewed at least 30 days earlier:

| Gate | Requirement |
|---|---|
| G1 Awareness | Every finding has a before-feedback response. |
| G2 Understanding | Every finding confirmed understood after feedback and understanding ≥ 0.70. |
| G3 Action | Every finding has agreed actions and all are completed. |
| G4 Practice | A practised/demonstrated coaching session after the latest review. |
| G5 Validation | ≥ 5 comparable follow-up cases with ≥ 85 % handled correctly. |

## Configuration

| Table | Key fields | Notes |
|---|---|---|
| `app_settings` | `key`, `value` (JSON), `updated_at`, `updated_by` | Runtime overrides; a missing key means the built-in default. Definitions and validation live in `services/settings_store.py`. |
| `db_connections` | `name`, `engine`, `host`, `port`, `database`, `username`, `password_encrypted` or `password_env`, `sslmode`, `schema_name`, `last_test_*`, `last_check_*` | Saved connection profiles. Passwords are Fernet-encrypted with `CONFIG_SECRET_KEY` or read from a `BOP_DBPASS_*` environment variable; never returned by the API. |

## Operations

| Table | Notes |
|---|---|
| `pipelines` | State (`HEALTHY`, `RUNNING`, `DEGRADED`, `FAILED`, `PAUSED`, `STALE`), schedule, SLA, lag, last error, request ID, owner, runbook. |
| `ingestion_runs` | Read / written / rejected / duplicated counts, duration, request ID. |
| `quarantined_records` | Rejected records with reason (redacted payload). |
| `model_registry` | Status (`DEVELOPMENT` … `RETIRED`), validation date, latency, missing-input rate, drift, override rate, limitations. Status is simulated in the demo. |
| `model_runs` | Versioned inference records; `review_status` becomes `accepted` / `overridden` after human review. |
| `simulation_runs` | Inputs, outputs and limitations of each scenario run. |
| `audit_events` | Actor, action, resource, outcome, request ID, redacted metadata. |
| `service_heartbeats` | Worker liveness. |
