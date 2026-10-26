"""Generative assistant, exercised end to end against a local stand-in for Groq's OpenAI-compatible API.

No request leaves the machine: the stub records what the backend would send so the tests can
check the pseudonymisation rules (no names, no free text written by staff, no key in responses).
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import AIGeneration, AppSetting, AuditEvent, EmployeeProfile, Finding, MistakeRule, WorkplaceException
from app.services import ai

KEY = "gsk_test_" + "x" * 40

OUTPUTS = {
    "Draft a bank policy statement": {
        "title_en": "Cash counting",
        "title_ar": "عدّ النقد",
        "statement_en": "Count cash twice.",
        "statement_ar": "عدّ النقد مرتين.",
        "key_requirements_en": ["a"],
        "key_requirements_ar": ["أ"],
        "rationale_en": "Reduces errors.",
        "rationale_ar": "يقلل الأخطاء.",
    },
    "Turn the description into a control rule": {
        "name_en": "Very late",
        "name_ar": "تأخر كبير",
        "risk_en": "r",
        "risk_ar": "r",
        "expected_en": "On time",
        "expected_ar": "في الموعد",
        "observed_en": "Late",
        "observed_ar": "متأخر",
        "severity": "medium",
        "kind": "breach",
        "rationale_en": "why",
        "rationale_ar": "لماذا",
        "conditions": {"match": "all", "conditions": [{"field": "minutes_late", "op": "gt", "value": 30}]},
    },
    "Explain the backtest": {
        "headline": "h",
        "explanation": "e",
        "recommendation": "approve",
        "caveats": ["synthetic"],
    },
    "Help a reviewer": {
        "summary": "s",
        "likely_root_cause": "workload",
        "root_cause_reason": "r",
        "coaching_points": ["c"],
        "questions_for_employee": ["q"],
        "caution": "c",
    },
    "development summary": {
        "headline": "h",
        "strengths": ["s"],
        "focus_areas": ["f"],
        "development_plan": [{"action": "a", "owner_role": "o", "timeframe": "t"}],
        "conversation_opener": "o",
        "caution": "c",
    },
    "Analyse the workplace-policy": {
        "headline": "h",
        "patterns": ["p"],
        "likely_causes": ["l"],
        "recommendations": ["r"],
        "caution": "c",
    },
    "short, warm": {"title": "Welcome", "message": "m", "first_week_tips": ["a", "b", "c"]},
    "3-question multiple-choice quiz": {
        "questions": [
            {"question": f"Q{i}", "options": ["a", "b", "c", "d"], "answer_index": i, "explanation": "e"}
            for i in range(3)
        ]
    },
    "reminder from HR": {"subject": "Reminder", "message_en": "Please finish.", "message_ar": "يرجى الإكمال."},
    'Reply with {"status"': {"status": "ok", "greeting": "hello from the stub"},
}


class Stub:
    def __init__(self):
        self.requests: list[dict] = []
        self.garble_next = False

    def answer(self, body: dict) -> str:
        prompt = body["messages"][-1]["content"] if body["messages"][-1]["role"] == "user" else ""
        text = " ".join(m["content"] for m in body["messages"])
        if self.garble_next:
            self.garble_next = False
            return "Sure! Here is a draft without JSON."
        if "Return only the JSON object" in prompt:
            text = body["messages"][1]["content"]
        for marker, output in OUTPUTS.items():
            if marker in text:
                return json.dumps(output, ensure_ascii=False)
        return "{}"


@pytest.fixture(scope="module")
def stub():
    state = Stub()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            if self.headers.get("Authorization") != f"Bearer {KEY}":
                payload, code = {"error": {"message": "Invalid API Key"}}, 401
            else:
                payload = {
                    "choices": [{"message": {"role": "assistant", "content": state.answer(body)}}],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 80},
                }
                code = 200
            raw = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings = get_settings()
    original = settings.groq_base_url
    settings.groq_base_url = f"http://127.0.0.1:{server.server_port}/openai/v1"
    yield state
    settings.groq_base_url = original
    server.shutdown()


def _admin(login):
    return login("superadmin")


def test_unconfigured_assistant_is_reported_not_called(client, login, stub):
    status = client.get("/api/ai/status", headers=login("ops.policy")).json()
    assert status["configured"] is False and status["model"] == "openai/gpt-oss-20b"
    r = client.post(
        "/api/ai/policy-draft", json={"notes": "Tellers must count cash twice"}, headers=login("ops.policy")
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_configured"
    assert stub.requests == []


def test_key_is_stored_encrypted_and_never_returned(client, login, db, stub):
    bad = client.put("/api/config/ai/key", json={"api_key": "gsk_wrong_" + "y" * 30}, headers=_admin(login))
    assert bad.status_code == 200
    failed = client.post("/api/config/ai/test", headers=_admin(login)).json()
    assert failed == {"ok": False, "code": "invalid_key", "message": "The AI provider rejected the API key."}
    saved = client.put("/api/config/ai/key", json={"api_key": KEY}, headers=_admin(login))
    body = saved.text
    assert saved.status_code == 200 and KEY not in body and saved.json()["key_source"] == "stored"
    assert saved.json()["key_hint"] == f"{KEY[:4]}…{KEY[-4:]}"
    row = db.get(AppSetting, ai.KEY_SETTING)
    assert KEY not in json.dumps(row.value)
    ok = client.post("/api/config/ai/test", headers=_admin(login)).json()
    assert ok["ok"] and ok["reply"]["status"] == "ok"
    sent = stub.requests[-1]
    assert sent["path"] == "/openai/v1/chat/completions" and sent["body"]["model"] == "openai/gpt-oss-20b"
    assert sent["body"]["response_format"] == {"type": "json_object"} and sent["body"]["include_reasoning"] is False
    # Only System Administrators manage the key.
    assert client.put("/api/config/ai/key", json={"api_key": KEY}, headers=login("hr.ld")).status_code == 403
    events = db.scalars(select(AuditEvent.metadata_redacted).where(AuditEvent.action.like("config.ai%"))).all()
    assert all(KEY not in json.dumps(e) for e in events)


def test_policy_and_rule_drafting_with_validation_and_cache(client, login, db, stub):
    headers = login("ops.policy")
    first = client.post(
        "/api/ai/policy-draft", json={"notes": "Tellers must count cash twice before handing over"}, headers=headers
    )
    assert first.status_code == 200, first.text
    assert first.json()["output"]["title_ar"] == "عدّ النقد" and first.json()["meta"]["cached"] is False
    calls = len(stub.requests)
    second = client.post(
        "/api/ai/policy-draft", json={"notes": "Tellers must count cash twice before handing over"}, headers=headers
    ).json()
    assert second["meta"]["cached"] is True and len(stub.requests) == calls

    rule = client.post(
        "/api/ai/rule-draft",
        json={"description": "Flag staff who arrive very late", "category": "attendance"},
        headers=headers,
    ).json()
    assert (
        rule["output"]["conditions"]
        == {"match": "all", "conditions": [{"field": "minutes_late", "op": "gt", "value": 30}]}
        and rule["output"]["condition_errors"] is None
    )
    # The same AI answer is rejected for a service type whose facts it does not use.
    other = client.post(
        "/api/ai/rule-draft",
        json={"description": "Flag staff who arrive very late", "category": "cash_transaction"},
        headers=headers,
    ).json()
    assert other["output"]["conditions"] is None and other["output"]["condition_errors"]
    facts = stub.requests[-1]["body"]["messages"][1]["content"]
    assert "minutes_late" not in facts  # only the service type's own facts are offered

    stub.garble_next = True
    retried = client.post(
        "/api/ai/policy-draft",
        json={"notes": "A different policy on ID badges at counters", "refresh": True},
        headers=headers,
    )
    assert retried.status_code == 200 and retried.json()["meta"]["cached"] is False
    assert (
        db.scalar(
            select(AIGeneration)
            .where(AIGeneration.task == "policy_draft", AIGeneration.status == "ok")
            .order_by(AIGeneration.created_at.desc())
        ).prompt_tokens
        == 120
    )

    rule_row = db.scalar(select(MistakeRule).where(MistakeRule.rule_code == "HR_LATE_ARRIVAL"))
    explained = client.post(f"/api/ai/rules/{rule_row.id}/explain-backtest", json={"days": 60}, headers=headers)
    assert explained.status_code == 200 and explained.json()["output"]["recommendation"] == "approve"


def test_payloads_are_pseudonymised(client, login, db, stub):
    # Free text written by the employee must not reach the provider.
    me = client.get("/api/workplace/me", headers=login("employee.demo")).json()
    target = next(x for x in me["exceptions"] if x["can_respond"])
    secret_text = "My neighbour Khalil drove me because of the checkpoint"
    client.post(
        f"/api/workplace/exceptions/{target['id']}/respond",
        json={"reason_code": "transport", "reason_text": secret_text},
        headers=login("employee.demo"),
    )

    chief = client.post("/api/auth/login", json={"username": "hr.chief", "password": "123"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {chief}"}
    employee = db.scalar(
        select(EmployeeProfile).where(EmployeeProfile.user_id.is_not(None), EmployeeProfile.external_ref.is_(None))
    )
    summary = client.post(f"/api/ai/employees/{employee.id}/summary", json={"language": "ar"}, headers=headers)
    assert summary.status_code == 200, summary.text
    sent = stub.requests[-1]["body"]["messages"][1]["content"]
    assert employee.pseudonym in sent and "workplace_kpis_90_days" in sent
    assert "Demo Employee" not in sent and "Arabic" in sent

    insights = client.post("/api/ai/workplace/insights", json={"days": 30}, headers=headers)
    assert insights.status_code == 200, insights.text
    sent_insights = stub.requests[-1]["body"]["messages"][1]["content"]
    assert "punctuality_rate" in sent_insights and "E-1" not in sent_insights  # aggregates only

    finding = db.scalar(select(Finding).limit(1))
    assisted = client.post(f"/api/ai/findings/{finding.id}/assist", json={}, headers=login("risk.compliance"))
    assert assisted.status_code == 200

    everything = json.dumps([r["body"] for r in stub.requests], ensure_ascii=False)
    assert secret_text not in everything and "Khalil" not in everything
    assert not any(r["auth"] and KEY in json.dumps(r["body"]) for r in stub.requests)
    # Each call is audited.
    actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.action.like("ai.%"))))
    assert {"ai.policy_draft", "ai.employee_summary", "ai.workplace_insights", "ai.case_assistant"} <= actions
    excused = db.get(WorkplaceException, target["id"])
    assert excused.reason_text == secret_text  # kept in BOP Evolve, just never sent


def test_feature_switches_and_onboarding_ai(client, login, stub):
    admin = _admin(login)
    client.put("/api/config/settings", json={"values": {"ai.feature.policy_writing": "off"}}, headers=admin)
    off = client.post(
        "/api/ai/policy-draft", json={"notes": "Switched off feature test notes"}, headers=login("ops.policy")
    )
    assert off.status_code == 409 and off.json()["detail"]["code"] == "feature_disabled"
    client.delete("/api/config/settings/ai.feature.policy_writing", headers=admin)

    welcome = client.post("/api/onboarding/me/welcome", json={"language": "en"}, headers=login("employee.demo"))
    assert welcome.status_code == 200 and len(welcome.json()["output"]["first_week_tips"]) == 3
    quiz = client.get("/api/onboarding/me/quiz?language=en", headers=login("employee.demo")).json()
    assert quiz["source"] == "ai" and quiz["quiz_id"].startswith("AIG")
    graded = client.post(
        "/api/onboarding/me/quiz",
        json={"quiz_id": quiz["quiz_id"], "answers": [0, 1, 2]},
        headers=login("employee.demo"),
    ).json()
    assert graded["score"] == 3 and graded["passed"]

    client.put("/api/config/settings", json={"values": {"ai.enabled": "off"}}, headers=admin)
    fallback = client.get("/api/onboarding/me/quiz?language=en", headers=login("employee.demo")).json()
    assert fallback["source"] == "built_in"
    client.delete("/api/config/settings/ai.enabled", headers=admin)
    usage = client.get("/api/config/ai/usage", headers=admin).json()
    assert any(f["feature"] == "onboarding" and f["ok"] >= 2 for f in usage["features"])
    client.delete("/api/config/ai/key", headers=admin)
    assert client.get("/api/ai/status", headers=admin).json()["configured"] is False
