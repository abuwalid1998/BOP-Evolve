"""Generative assistant on Groq's OpenAI-compatible API (default model ``openai/gpt-oss-20b``).

Every feature goes through :func:`generate`, which

* checks that the assistant and the feature are switched on in System Configuration;
* sends only pseudonymised, purpose-built payloads (employee reference codes, roles, dates,
  facts and statistics - never names, national IDs or customer data);
* asks for a JSON object and validates the keys each task promises;
* caches identical requests and records every call (cached or not) in ``ai_generations``
  and the audit trail;
* never logs, stores in plain text or returns the API key.

Outputs are drafts and explanations for a person to review. Nothing here changes data.
"""

import hashlib
import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.models import AIGeneration, AppSetting
from app.services import audit, secrets, settings_store

log = logging.getLogger("bop_evolve.ai")

KEY_SETTING = "secret.groq_api_key"
REGISTRY_NAME = "Generative assistant (Groq)"
REGISTRY_PURPOSE = (
    "Drafts policy statements and control rules, explains backtests, prepares review conversations, summarises "
    "employee development, analyses workplace KPIs and personalises onboarding, in English and Arabic."
)
REGISTRY_LIMITATIONS = (
    "Large language model (default openai/gpt-oss-20b on Groq). Receives pseudonymised, purpose-built inputs only; "
    "outputs are drafts for a person to review and never change data or decide anything. Can be switched off as a "
    "whole or per feature; every call is logged and audited."
)
CACHE_DAYS = 30
RATE_LIMIT = 30  # calls to the provider per user ...
RATE_WINDOW = 600  # ... per ten minutes (cache hits are free)
_calls: dict[str, deque] = defaultdict(deque)


class AIError(Exception):
    """``code`` is one of: not_configured, disabled, feature_disabled, invalid_key, rate_limited,
    provider_error, timeout, invalid_output."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


# ------------------------------------------------------------------ settings
def _stored_key(db: Session) -> str | None:
    row = db.get(AppSetting, KEY_SETTING)
    if row is None or not row.value.get("value"):
        return None
    try:
        return secrets.decrypt(row.value["value"])
    except ValueError:
        log.warning("Stored Groq key cannot be decrypted with the current key; ignoring it")
        return None


def api_key(db: Session) -> tuple[str | None, str]:
    """(key, source) where source is stored | environment | none. Stored overrides the environment."""
    stored = _stored_key(db)
    if stored:
        return stored, "stored"
    env = get_settings().groq_api_key.strip()
    if env:
        return env, "environment"
    return None, "none"


def set_key(db: Session, key: str, actor_id: str) -> None:
    row = db.get(AppSetting, KEY_SETTING)
    value = {"value": secrets.encrypt(key.strip())}
    if row is None:
        db.add(AppSetting(key=KEY_SETTING, value=value, updated_by=actor_id))
    else:
        row.value, row.updated_by, row.updated_at = value, actor_id, utcnow()


def clear_key(db: Session) -> bool:
    row = db.get(AppSetting, KEY_SETTING)
    if row is None:
        return False
    db.delete(row)
    return True


def mask(key: str | None) -> str | None:
    return f"{key[:4]}…{key[-4:]}" if key and len(key) > 12 else ("set" if key else None)


def status(db: Session) -> dict:
    values = settings_store.effective(db)
    key, source = api_key(db)
    return {
        "enabled": values["ai.enabled"] == "on",
        "configured": bool(key),
        "key_source": source,
        "key_hint": mask(key),
        "model": values["ai.model"],
        "reasoning_effort": values["ai.reasoning_effort"],
        "provider": "Groq",
        "base_url": get_settings().groq_base_url,
        "features": {name: values[f"ai.feature.{name}"] == "on" for name in settings_store.AI_FEATURES},
    }


# -------------------------------------------------------------------- client
@dataclass
class Completion:
    content: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int


def _call(key: str, model: str, effort: str, messages: list[dict], max_tokens: int) -> Completion:
    settings = get_settings()
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_completion_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if "gpt-oss" in model:
        # gpt-oss reasons before answering; keep the reasoning internal and return only the JSON answer.
        body["reasoning_effort"] = effort
        body["include_reasoning"] = False
    started = time.monotonic()
    try:
        with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
            response = client.post(
                f"{settings.groq_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=body,
            )
    except httpx.TimeoutException as exc:
        raise AIError("timeout", "The AI provider did not answer in time.") from exc
    except httpx.HTTPError as exc:
        raise AIError("provider_error", f"Could not reach the AI provider ({exc.__class__.__name__}).") from exc
    latency = int((time.monotonic() - started) * 1000)
    if response.status_code == 401:
        raise AIError("invalid_key", "The AI provider rejected the API key.")
    if response.status_code == 429:
        raise AIError("rate_limited", "The AI provider's rate limit was reached; try again shortly.")
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message", "")
        except ValueError:
            detail = ""
        raise AIError("provider_error", f"AI provider error {response.status_code}. {detail[:200]}".strip())
    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise AIError("invalid_output", "The AI provider returned an unexpected response.") from exc
    usage = data.get("usage") or {}
    return Completion(content, usage.get("prompt_tokens"), usage.get("completion_tokens"), latency)


def _parse(content: str, required: tuple[str, ...]) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{") :]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise AIError("invalid_output", "The AI answer was not JSON.")
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AIError("invalid_output", "The AI answer was not valid JSON.") from exc
    if not isinstance(value, dict):
        raise AIError("invalid_output", "The AI answer was not a JSON object.")
    missing = [k for k in required if k not in value]
    if missing:
        raise AIError("invalid_output", f"The AI answer is missing: {', '.join(missing)}.")
    return value


def _rate_check(user_id: str | None) -> None:
    if not user_id:
        return
    now = time.monotonic()
    calls = _calls[user_id]
    while calls and now - calls[0] > RATE_WINDOW:
        calls.popleft()
    if len(calls) >= RATE_LIMIT:
        raise AIError("rate_limited", "Too many AI requests in the last ten minutes; try again shortly.")
    calls.append(now)


# --------------------------------------------------------------------- tasks
LANGUAGES = {"en": "English", "ar": "Arabic (Modern Standard Arabic, formal banking register)"}

SYSTEM = (
    "You are the writing and analysis assistant inside BOP Evolve, the service-quality and staff-development "
    "platform of the Bank of Palestine. Write like a senior banker and HR business partner: precise, formal, "
    "fair and constructive. Findings describe procedures, never a person's character or intent. Never invent "
    "facts, numbers, names or policies that are not in the input. Inputs identify employees only by reference "
    "codes; do not guess identities. All data in this demonstration is synthetic. Your output is a draft for a "
    "qualified person to review; never present it as a decision. Answer with one JSON object only, no prose "
    "outside it."
)


@dataclass(frozen=True)
class Task:
    feature: str
    version: str
    instructions: str
    required: tuple[str, ...]
    max_tokens: int = 1800


TASKS: dict[str, Task] = {
    "policy_draft": Task(
        "policy_writing",
        "1",
        "Draft a bank policy statement from the notes. Return JSON with: title_en, title_ar (short titles); "
        "statement_en, statement_ar (the requirement staff must follow, 2-4 sentences, imperative, measurable); "
        "key_requirements_en, key_requirements_ar (arrays of 3-5 short bullet strings); rationale_en, "
        "rationale_ar (why the bank needs this policy: risk, regulation, customer outcome; 2-3 sentences). The "
        "Arabic must be natural formal Arabic, not a word-for-word translation.",
        ("title_en", "title_ar", "statement_en", "statement_ar", "rationale_en", "rationale_ar"),
    ),
    "rule_draft": Task(
        "policy_writing",
        "1",
        "Turn the description into a control rule for the given service type. Use ONLY the facts listed in "
        "'available_facts', with their exact keys, allowed operators and option values. Return JSON with: "
        "name_en, name_ar; risk_en, risk_ar (what goes wrong if the procedure is skipped); expected_en, "
        "expected_ar (the behaviour the policy expects); observed_en, observed_ar (neutral, factual wording of "
        "the deviation as it would appear on a finding); severity (low|medium|high|critical); kind "
        "(breach for a policy breach, early_warning for circumstances that only precede breaches); conditions "
        "({match: all|any, conditions: [{field, op, value}]}, value null for is_true/is_false); rationale_en, "
        "rationale_ar (why these conditions and this severity).",
        ("name_en", "name_ar", "expected_en", "expected_ar", "severity", "kind", "conditions", "rationale_en"),
    ),
    "backtest_explain": Task(
        "policy_writing",
        "1",
        "Explain the backtest of a control rule to a policy owner in the requested language. Return JSON with: "
        "headline (one sentence); explanation (3-5 sentences on volume, accuracy indicator, risk lift, trend "
        "and, if present, the comparison with the version in force); recommendation (approve, adjust or "
        "reconsider, with the reason); caveats (array of short strings, include that data is synthetic).",
        ("headline", "explanation", "recommendation", "caveats"),
        1200,
    ),
    "case_assistant": Task(
        "case_assistant",
        "1",
        "Help a reviewer prepare the review conversation for this finding, in the requested language. Return "
        "JSON with: summary (2-3 sentences: what happened and why the rule flagged it); likely_root_cause (one "
        "of individual_action, policy_ambiguity, process_design, system_issue, workload, undetermined, with a "
        "one-sentence reason in root_cause_reason); coaching_points (3-5 strings); questions_for_employee (2-4 "
        "open, non-judgemental questions); caution (one sentence on what the reviewer must verify themselves).",
        ("summary", "likely_root_cause", "coaching_points", "questions_for_employee", "caution"),
        1400,
    ),
    "employee_summary": Task(
        "employee_summary",
        "1",
        "Write a development summary of this employee for the Chief HR Officer, in the requested language. "
        "Base it only on the figures given. Return JSON with: headline (one sentence); strengths (2-4 strings); "
        "focus_areas (2-4 strings, each naming the service type or workplace policy concerned); "
        "development_plan (array of 2-4 objects {action, owner_role, timeframe}); conversation_opener (one "
        "supportive sentence the manager can open the conversation with); caution (one sentence: indicative, "
        "for development planning only, not for disciplinary or pay decisions).",
        ("headline", "strengths", "focus_areas", "development_plan", "conversation_opener", "caution"),
        1600,
    ),
    "workplace_insights": Task(
        "workplace_insights",
        "1",
        "Analyse the workplace-policy and time KPIs of this organisational unit for HR, in the requested "
        "language. Return JSON with: headline (one sentence); patterns (3-5 strings citing the figures); "
        "likely_causes (2-4 strings, distinguishing individual habits from scheduling, staffing, transport or "
        "process causes); recommendations (3-5 concrete actions with an owner role); caution (one sentence).",
        ("headline", "patterns", "likely_causes", "recommendations", "caution"),
        1400,
    ),
    "onboarding_welcome": Task(
        "onboarding",
        "1",
        "Write a short, warm and professional welcome to BOP Evolve for a new user with this role and unit, in "
        "the requested language. Do not use a name. Return JSON with: title (max 8 words); message (2-3 "
        "sentences on what BOP Evolve does for someone in this role); first_week_tips (array of 3 short, "
        "role-specific tips).",
        ("title", "message", "first_week_tips"),
        700,
    ),
    "onboarding_reminder": Task(
        "onboarding",
        "1",
        "Draft a short, encouraging reminder from HR to staff in this onboarding wave who have not finished "
        "the BOP Evolve welcome journey. Use the aggregate counts to mention the step most people still have "
        "to do. No names, no pressure or sanctions. Return JSON with: subject (max 10 words, in the requested "
        "language); message_en and message_ar (3-4 sentences each, the Arabic natural and formal).",
        ("subject", "message_en", "message_ar"),
        900,
    ),
    "policy_quiz": Task(
        "onboarding",
        "1",
        "Write a 3-question multiple-choice quiz that checks understanding of these workplace policies, in the "
        "requested language. Return JSON with: questions (array of exactly 3 objects {question, options (array "
        "of exactly 4 strings), answer_index (0-3), explanation (one sentence)}). Test the actual requirements "
        "(times, limits, procedures), not trivia.",
        ("questions",),
        1600,
    ),
}


def _input_hash(task: str, version: str, model: str, language: str, payload: dict) -> str:
    raw = json.dumps([task, version, model, language, payload], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def generate(
    db: Session,
    task_name: str,
    payload: dict,
    *,
    language: str = "en",
    actor_id: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    refresh: bool = False,
    request_id: str | None = None,
) -> dict:
    """Run one task and return ``{"output": {...}, "meta": {...}}``. Raises :class:`AIError`."""
    task = TASKS[task_name]
    values = settings_store.effective(db)
    if values["ai.enabled"] != "on":
        raise AIError("disabled", "The AI assistant is switched off in System Configuration.")
    if values[f"ai.feature.{task.feature}"] != "on":
        raise AIError("feature_disabled", "This AI feature is switched off in System Configuration.")
    key, _ = api_key(db)
    if not key:
        raise AIError("not_configured", "No Groq API key is configured (System Configuration > AI assistant).")
    language = language if language in LANGUAGES else "en"
    model = values["ai.model"]
    digest = _input_hash(task_name, task.version, model, language, payload)

    if not refresh:
        cached = db.scalar(
            select(AIGeneration)
            .where(
                AIGeneration.input_hash == digest,
                AIGeneration.status == "ok",
                AIGeneration.created_at >= utcnow() - timedelta(days=CACHE_DAYS),
            )
            .order_by(AIGeneration.created_at.desc())
            .limit(1)
        )
        if cached is not None:
            return {"output": cached.output, "meta": _meta(cached, cached_hit=True)}

    _rate_check(actor_id)
    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": (
                f"Task: {task.instructions}\nWrite user-facing text in {LANGUAGES[language]} unless a key name "
                f"ends in _en or _ar.\nInput (JSON):\n{json.dumps(payload, ensure_ascii=False, default=str)}"
            ),
        },
    ]
    record = AIGeneration(
        feature=task.feature,
        task=task_name,
        prompt_version=task.version,
        model=model,
        language=language,
        input_hash=digest,
        subject_type=subject_type,
        subject_id=subject_id,
        status="error",
        created_by=actor_id,
    )
    try:
        completion = _call(key, model, values["ai.reasoning_effort"], messages, task.max_tokens)
        record.latency_ms = completion.latency_ms
        record.prompt_tokens, record.completion_tokens = completion.prompt_tokens, completion.completion_tokens
        try:
            output = _parse(completion.content, task.required)
        except AIError:
            # One retry with a reminder; models occasionally wrap or truncate JSON.
            messages.append({"role": "assistant", "content": completion.content[:4000]})
            messages.append({"role": "user", "content": "Return only the JSON object with all required keys."})
            completion = _call(key, model, values["ai.reasoning_effort"], messages, task.max_tokens)
            record.latency_ms = (record.latency_ms or 0) + completion.latency_ms
            output = _parse(completion.content, task.required)
        record.status, record.output = "ok", output
    except AIError as exc:
        record.error_code = exc.code
        db.add(record)
        _audit(db, record, actor_id, request_id, outcome="failure")
        db.commit()
        raise
    db.add(record)
    _audit(db, record, actor_id, request_id)
    db.commit()
    return {"output": output, "meta": _meta(record, cached_hit=False)}


def _audit(db: Session, record: AIGeneration, actor_id, request_id, outcome: str = "success") -> None:
    audit.record(
        db,
        actor_user_id=actor_id,
        action=f"ai.{record.task}",
        resource_type=record.subject_type or "ai",
        resource_id=record.subject_id,
        request_id=request_id,
        outcome=outcome,
        metadata={
            "model": record.model,
            "language": record.language,
            "error": record.error_code,
            "tokens": (record.prompt_tokens or 0) + (record.completion_tokens or 0),
        },
    )


def _meta(record: AIGeneration, *, cached_hit: bool) -> dict:
    return {
        "id": record.id,
        "model": record.model,
        "provider": "Groq",
        "generated_at": record.created_at.isoformat() if record.created_at else utcnow().isoformat(),
        "cached": cached_hit,
        "latency_ms": record.latency_ms,
        "language": record.language,
    }


def test_connection(db: Session) -> dict:
    """Small live call used by System Configuration. Does not use the cache."""
    key, source = api_key(db)
    if not key:
        raise AIError("not_configured", "No Groq API key is configured.")
    values = settings_store.effective(db)
    completion = _call(
        key,
        values["ai.model"],
        "low",
        [
            {"role": "system", "content": "Answer with a JSON object only."},
            {"role": "user", "content": 'Reply with {"status": "ok", "greeting": "<a five-word greeting>"}.'},
        ],
        200,
    )
    output = _parse(completion.content, ("status",))
    return {
        "ok": True,
        "model": values["ai.model"],
        "latency_ms": completion.latency_ms,
        "reply": output,
        "key_source": source,
    }
