#!/usr/bin/env python3
"""End-to-end check of demo scenarios S1-S5 against a running stack (docker compose up).

Only the public HTTP API is used, as the web interface would use it: the client and the bank
employees log in with the test accounts, fill and submit applications, take decisions, sign.
Every expected outcome comes from docs/product/demo-scenarios.md and analytics artifacts; any
mismatch stops the script with a non-zero exit code.

Usage:
    python3 scripts/e2e_demo.py                    # all scenarios, API at http://localhost:8000/api
    E2E_BASE_URL=http://localhost:8080/api python3 scripts/e2e_demo.py S1 S3
Standard library only (Python 3.9+).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable, Dict, List, Optional

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000/api").rstrip("/")
TIMEOUT = float(os.environ.get("E2E_WAIT_SECONDS", "180"))
PASSWORDS = {"client": "Demo-Client-2026", "uw": "Demo-Uw-2026", "risk": "Demo-Risk-2026"}
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"
if not sys.stdout.isatty():
    GREEN = RED = DIM = BOLD = RESET = ""


class Failure(Exception):
    pass


def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"  {GREEN}OK{RESET} {msg}", flush=True)


def check(condition: bool, msg: str, detail: Any = None) -> None:
    if not condition:
        extra = f"\n      {json.dumps(detail, ensure_ascii=False)[:1500]}" if detail is not None else ""
        raise Failure(msg + extra)
    ok(msg)


class Http:
    def __init__(self, login: str, password: str):
        self.login = login
        self.token = ""
        status, body, _ = self.call("POST", "/v1/auth/login", {"login": login, "password": password}, auth=False)
        if status != 200:
            raise Failure(f"login {login} failed: {status} {body}")
        self.token = body["access_token"]
        self.user = body["user"]

    def call(self, method: str, path: str, body: Any = None, *, auth: bool = True, key: Optional[str] = None, raw: Optional[bytes] = None, content_type: Optional[str] = None):
        url = BASE + path
        data = None
        headers = {"Accept": "application/json", "X-Request-Id": "e2e-" + uuid.uuid4().hex[:16]}
        if raw is not None:
            data = raw
            headers["Content-Type"] = content_type or "application/octet-stream"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = "Bearer " + self.token
        if key:
            headers["Idempotency-Key"] = key
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = resp.read()
                return resp.status, (json.loads(payload) if payload and resp.headers.get_content_type() == "application/json" else payload.decode("utf-8", "replace")), {k.lower(): v for k, v in resp.headers.items()}
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            try:
                parsed = json.loads(payload)
            except ValueError:
                parsed = payload.decode("utf-8", "replace")
            return exc.code, parsed, {k.lower(): v for k, v in exc.headers.items()}

    def ok(self, method: str, path: str, body: Any = None, expect: int = 200, **kw) -> Any:
        status, data, _ = self.call(method, path, body, **kw)
        if status != expect:
            raise Failure(f"{self.login}: {method} {path} -> {status}, expected {expect}: {json.dumps(data, ensure_ascii=False)[:800]}")
        return data

    def upload(self, app_id: str, document_type: str, file_name: str, item_id: Optional[str] = None) -> Dict[str, Any]:
        boundary = "----e2e" + uuid.uuid4().hex
        parts = []
        fields = {"document_type": document_type}
        if item_id:
            fields["info_request_item_id"] = item_id
        for name, value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_name}"\r\nContent-Type: application/pdf\r\n\r\n'.encode() + PDF + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        return self.ok("POST", f"/v1/applications/{app_id}/documents", raw=b"".join(parts), content_type=f"multipart/form-data; boundary={boundary}", expect=201)


def key() -> str:
    return uuid.uuid4().hex


def wait_for(fetch: Callable[[], Dict[str, Any]], predicate: Callable[[Dict[str, Any]], bool], what: str, on_tick: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    deadline = time.time() + TIMEOUT
    last = None
    while time.time() < deadline:
        last = fetch()
        if on_tick:
            on_tick(last)
        if predicate(last):
            return last
        time.sleep(1.0)
    raise Failure(f"timeout waiting for {what}; last state: {json.dumps({k: last.get(k) for k in ('client_status', 'status', 'available_actions')} if last else None, ensure_ascii=False)}")


def assert_no_internal_fields(view: Dict[str, Any]) -> None:
    text = json.dumps(view)
    forbidden = ['"score"', '"grade"', '"pd"', '"factor_contributions"', '"rules_path"', '"recommendation"', '"status": "OFFER_PENDING"', '"assignee"', '"comments"']
    leaked = [f for f in forbidden if f in text]
    check(not leaked, "client view has no score, grade, rules or internal status", leaked)


def cleanup(client: Http) -> None:
    """Close active applications of a previous run so that duplicates do not block the scenario."""
    page = client.ok("GET", "/v1/applications?page_size=100")
    for item in page["items"]:
        view = client.ok("GET", f"/v1/applications/{item['id']}")
        actions = view["available_actions"]
        if "WITHDRAW" in actions:
            client.ok("POST", f"/v1/applications/{item['id']}/withdraw", {"expected_version": view["version"]}, key=key())
            log(f"{DIM}closed previous application {item['application_number']}{RESET}")
        elif "DECLINE_OFFER" in actions:
            client.ok("POST", f"/v1/applications/{item['id']}/offer/decline", {"expected_version": view["version"]}, key=key())
            log(f"{DIM}declined previous offer {item['application_number']}{RESET}")


def new_application(client: Http, product: str, purpose: str, amount: int, term: int) -> Dict[str, Any]:
    wizard = uuid.uuid4().hex
    client.ok("POST", "/v1/analytics/events", {"event_type": "PRODUCT_WIZARD_STARTED", "wizard_session_id": wizard}, expect=202)
    client.ok("POST", "/v1/analytics/events", {"event_type": "PRODUCT_SELECTED", "wizard_session_id": wizard, "product_code": product, "purpose": purpose, "amount": str(amount), "term_months": term, "rank": 1, "was_recommended": True}, expect=202)
    app = client.ok("POST", "/v1/applications", {"product_code": product, "purpose": purpose, "amount": str(amount), "term_months": term, "wizard_session_id": wizard}, key=key(), expect=201)
    check(app["client_status"] == "FILLING" and app["progress_step"] == 1, f"draft {app['application_number']} created (T-01), client status FILLING")
    return app


def fill_and_submit(client: Http, app: Dict[str, Any], inn: str, fields: Dict[str, Any], expect_warning: Optional[str] = None, documents: Optional[List[str]] = None) -> Dict[str, Any]:
    pre = client.ok("POST", f"/v1/applications/{app['id']}/prefill", {"expected_version": app["version"], "inn": inn})
    check(pre["prefill"]["status"] == "FOUND", f"prefill by INN: {pre['application']['company']['company_short_name']}, {pre['application']['company']['okved_main_code']}")
    view = pre["application"]
    warnings = [w["reason_code"] for w in view["early_warnings"]]
    if expect_warning:
        check(expect_warning in warnings, f"early check warning {expect_warning}: {view['early_warnings'][0]['text'][:90]}...")
    else:
        check(not warnings, "no early check warnings")
    patched = client.ok("PATCH", f"/v1/applications/{app['id']}", {"expected_version": view["version"], **fields})
    check(not patched["field_errors"], "draft autosave without field errors")
    view = patched["application"]
    for doc in documents or []:
        view = client.upload(app["id"], doc, f"{doc.lower()}.pdf")
    if documents:
        check(all(d["uploaded"] for d in view["required_documents"]), f"documents uploaded: {', '.join(documents)}")
    for consent in ("CONSENT_PERSONAL_DATA", "CONSENT_CREDIT_BUREAU", "AUTHORITY_CONFIRMATION"):
        view = client.ok("PUT", f"/v1/applications/{app['id']}/consents/{consent}", {"expected_version": view["version"]})
    check(all(c["given"] for c in view["consents"]), "three consents given with server time")
    submit_key = key()
    submitted = client.ok("POST", f"/v1/applications/{app['id']}/submit", {"expected_version": view["version"]}, key=submit_key)
    check(submitted["client_status"] in ("SENT", "CHECKING"), f"submitted (T-03), client status {submitted['client_status']}")
    status, replay, headers = client.call("POST", f"/v1/applications/{app['id']}/submit", {"expected_version": view["version"]}, key=submit_key)
    check(status == 200 and headers.get("idempotent-replayed") == "true" and replay["version"] == submitted["version"], "repeated submit with the same Idempotency-Key returns the stored result")
    return submitted


def poll_client(client: Http, app_id: str, statuses: List[str], seen: Optional[set] = None) -> Dict[str, Any]:
    def tick(v):
        if seen is not None:
            seen.add(v["client_status"])

    return wait_for(lambda: client.ok("GET", f"/v1/applications/{app_id}"), lambda v: v["client_status"] in statuses, f"client status in {statuses}", tick)


def sign_and_issue(client: Http, app_id: str, option_id: str, view: Dict[str, Any], expect_docs: List[str]) -> Dict[str, Any]:
    accepted = client.ok("POST", f"/v1/applications/{app_id}/offer/accept", {"expected_version": view["version"], "option_id": option_id}, key=key())
    check(accepted["client_status"] == "DOCUMENTS" and accepted["final_terms"]["option_id"] == option_id, "offer accepted (T-33), final terms fixed")
    ready = wait_for(lambda: client.ok("GET", f"/v1/applications/{app_id}"), lambda v: v["signing"] is not None and "REQUEST_SIGNING_CODE" in v["available_actions"], "documents ready (T-36)")
    types = sorted(d["document_type"] for d in ready["signing"]["documents"])
    check(types == sorted(expect_docs), f"documents prepared by EDO mock: {', '.join(types)}", types)
    text = client.ok("GET", f"/v1/applications/{app_id}/signing-documents/{ready['signing']['documents'][0]['id']}")
    check(isinstance(text, str) and "договор" in text.lower(), "document text is readable before signing")
    code = client.ok("POST", f"/v1/applications/{app_id}/signing-code", key=key())
    check(len(code.get("code") or "") == 6, "signing code shown in the product (no SMS), TTL 5 min")
    wrong = "000000" if code["code"] != "000000" else "111111"
    status, err, _ = client.call("POST", f"/v1/applications/{app_id}/sign", {"expected_version": ready["version"], "code": wrong}, key=key())
    check(status == 422 and err["error"]["code"] == "SIGNING_CODE_INVALID" and err["error"]["details"]["attempts_left"] == 2, "wrong code rejected, attempts left: 2")
    sign_key = key()
    signed = client.ok("POST", f"/v1/applications/{app_id}/sign", {"expected_version": ready["version"], "code": code["code"]}, key=sign_key)
    check(signed["client_status"] in ("PAYOUT", "COMPLETED"), "documents signed (T-39)")
    status, replay, headers = client.call("POST", f"/v1/applications/{app_id}/sign", {"expected_version": ready["version"], "code": code["code"]}, key=sign_key)
    check(status == 200 and headers.get("idempotent-replayed") == "true", "repeated SIGN with the same key is replayed (no second signature)")
    done = poll_client(client, app_id, ["COMPLETED"])
    check(done["loan"] is not None and done["progress"][7]["state"] == "DONE", f"issued (T-42): {done['client_status_text']['title']}, contract {done['loan']['contract_number']}, account {done['loan']['account_number_masked']}")
    return done


def staff_card(staff: Http, app_id: str) -> Dict[str, Any]:
    return staff.ok("GET", f"/v1/bank/applications/{app_id}?view_context=SEARCH")


def common_card_checks(card: Dict[str, Any]) -> None:
    transitions = [h for h in card["history"] if h["event_type"] == "STATUS_CHANGED"]
    finals = [d for d in card["decisions"] if d["status"] == "FINAL"]
    check(all(d["policy_version"] and (d["scorecard_version"] or d["outcome"] == "NEEDS_INFO") for d in finals), "every decision stores scorecard and policy versions")
    check(len(transitions) >= 5, f"journal has STATUS_CHANGED for each of {len(transitions)} transitions")


# ---------------------------------------------------------------------------- scenarios


def s1(risk: Http) -> None:
    client = Http("client.irina", PASSWORDS["client"])
    cleanup(client)
    match = client.ok("POST", "/v1/catalog/match", {"purpose": "EQUIPMENT", "amount": "1200000", "term_months": 24})
    card = match["cards"][0]
    check(card["product_code"] == "EXPRESS" and card["recommended"] and card["monthly_payment_from"] == "62253.79", "selection: EXPRESS recommended, payment from 62 253,79")
    app = new_application(client, "EXPRESS", "EQUIPMENT", 1200000, 24)
    fill_and_submit(client, app, "002000010193", {"representative_role": "OWNER", "monthly_revenue_declared": "1500000", "existing_monthly_payments_declared": "0"})
    seen: set = set()
    view = poll_client(client, app["id"], ["DECISION_READY"], seen)
    assert_no_internal_fields(view)
    offer = view["offer"]
    option = offer["options"][0]
    check(offer["outcome"] == "APPROVED" and option["option_type"] == "REQUESTED" and option["amount"] == "1200000.00" and option["rate_percent"] == "22.00" and option["monthly_payment"] == "62253.79", "auto approval (T-19): 1 200 000 on 24 months at 22%, payment 62 253,79", offer)
    check(view["progress"][3]["state"] == "SKIPPED", "progress step 4 'specialist' marked as not needed")
    sign_and_issue(client, app["id"], option["id"], view, ["CREDIT_AGREEMENT", "PAYMENT_SCHEDULE"])
    card = staff_card(risk, app["id"])
    auto = [d for d in card["decisions"] if d["mode"] == "AUTO"][-1]
    check(card["scoring"]["score"] == 605 and card["scoring"]["grade"] == "A" and auto["outcome"] == "APPROVED", "bank card: score 605, grade A, decision AUTO APPROVED")
    common_card_checks(card)


def s2(risk: Http) -> None:
    client = Http("client.andrey", PASSWORDS["client"])
    cleanup(client)
    match = client.ok("POST", "/v1/catalog/match", {"purpose": "CASH_GAP", "amount": "15000000", "term_months": 12})
    check(match["cards"][0]["product_code"] == "WORKING_CAPITAL" and any("кредитную линию" in h for h in match["hints"]), "selection: WORKING_CAPITAL with a credit line hint")
    app = new_application(client, "WORKING_CAPITAL", "CASH_GAP", 15000000, 12)
    fill_and_submit(client, app, "0010002014", {"representative_role": "CEO", "monthly_revenue_declared": "7500000", "existing_monthly_payments_declared": "950000", "owner_guarantee_agreed": True})
    view = poll_client(client, app["id"], ["DECISION_READY"])
    assert_no_internal_fields(view)
    offer = view["offer"]
    by_type = {o["option_type"]: o for o in offer["options"]}
    check(offer["outcome"] == "COUNTER_OFFER" and view["client_status_text"]["title"] == "Банк предлагает другие условия", "counter offer (T-19, POL-07)")
    check(by_type["AMOUNT_REDUCED"]["amount"] == "13950000.00" and by_type["AMOUNT_REDUCED"]["monthly_payment"] == "1285584.27", "option AMOUNT_REDUCED: 13 950 000 on 12 months")
    check(by_type["TERM_EXTENDED"]["term_months"] == 13 and by_type["TERM_EXTENDED"]["recommended"], "option TERM_EXTENDED: 15 000 000 on 13 months, recommended")
    line = by_type["PRODUCT_CHANGED"]
    check(line["product_code"] == "CREDIT_LINE" and line["amount"] == "13880000.00" and line["credit_line"] is not None, "option PRODUCT_CHANGED: credit line 13 880 000 at 20%")
    check(offer["requested"]["monthly_payment"] == "1382348.67" and offer["reasons"][0]["text"].startswith("Ежемесячный платеж"), "client sees the request and the CO_DEBT_LOAD reason text")
    done = sign_and_issue(client, app["id"], line["id"], view, ["CREDIT_AGREEMENT", "PAYMENT_SCHEDULE", "GUARANTEE_AGREEMENT"])
    check(done["loan"]["operation_type"] == "CREDIT_LINE_LIMIT" and done["client_status_text"]["title"] == "Лимит кредитной линии открыт", "ABS mock opened the credit line limit")
    card = staff_card(risk, app["id"])
    auto = [d for d in card["decisions"] if d["mode"] == "AUTO"][-1]
    path = {r["rule"]: r["result"] for r in auto["rules_path"]}
    check(card["scoring"]["grade"] == "A" and path.get("POL-06") == "PASS" and path.get("POL-07") == "FIRE", "bank card: good grade A, decision by debt load POL-07 (scoring and policy separated)")
    check(auto["values"]["allowed_payment"] == "1285900.00", "policy values: allowed payment 1 285 900,00")
    common_card_checks(card)


def s3(risk: Http) -> None:
    client = Http("client.marina", PASSWORDS["client"])
    uw = Http("uw.dmitry", PASSWORDS["uw"])
    uw2 = Http("uw.anna", PASSWORDS["uw"])
    cleanup(client)
    match = client.ok("POST", "/v1/catalog/match", {"purpose": "EQUIPMENT", "amount": "40000000", "term_months": 60})
    check([c["product_code"] for c in match["cards"]] == ["INVESTMENT"] and any("специалист" in h for h in match["hints"]), "selection: only INVESTMENT, reviewed by a specialist")
    app = new_application(client, "INVESTMENT", "EQUIPMENT", 40000000, 60)
    fill_and_submit(
        client, app, "0010003018",
        {
            "representative_role": "CFO", "monthly_revenue_declared": "6750000", "existing_monthly_payments_declared": "600000", "owner_guarantee_agreed": True,
            "collateral_type": "PURCHASED_ASSET", "collateral_description": "Линия упаковки пищевой продукции, приобретаемая по договору поставки",
            "collateral_value": "48000000", "collateral_owner": "APPLICANT",
            "investment_project_description": "Покупка второй линии упаковки: рост выпуска на 40% под контракт с торговой сетью, окупаемость 4 года",
        },
        documents=["COLLATERAL_DOCUMENTS", "SUPPLIER_QUOTE"],
    )
    view = poll_client(client, app["id"], ["SPECIALIST_REVIEW"])
    check("Инвестиционные кредиты всегда рассматривает специалист." in view["client_status_text"]["notes"] and view["client_status_text"]["deadline_at"], "client: SPECIALIST_REVIEW with a reason note and a decision deadline")
    queue = uw.ok("GET", "/v1/bank/applications?tab=queue&page_size=100")
    row = next((i for i in queue["items"] if i["id"] == app["id"]), None)
    check(row is not None and [r["code"] for r in row["manual_review_reasons"]] == ["MR_PRODUCT_MANUAL_ONLY", "MR_DATA_MISMATCH"], "underwriter queue: reasons MR_PRODUCT_MANUAL_ONLY, MR_DATA_MISMATCH and SLA", row)
    card = uw.ok("GET", f"/v1/bank/applications/{app['id']}?view_context=QUEUE")
    rec = [d for d in card["decisions"] if d["mode"] == "AUTO"][-1]["recommendation"]
    check(any("на 35.00% выше данных ГИР БО" in d["text"] for d in card["discrepancies"]), "card: discrepancy 'revenue 35% above GIR BO'")
    check(rec["outcome"] == "COUNTER_OFFER" and rec["max_amount_requested_term"] == "36210000.00", "policy recommendation: counter offer, maximum 36 210 000 on 60 months")
    card = uw.ok("POST", f"/v1/bank/applications/{app['id']}/take", {"expected_version": card["version"]}, key=key())
    status, err, _ = uw2.call("POST", f"/v1/bank/applications/{app['id']}/take", {"expected_version": card["version"] - 1}, key=key())
    check(status == 409 and err["error"]["code"] == "ALREADY_TAKEN", f"second underwriter taking the same version gets 409: {err['error']['message']}")
    check(card["status"] == "IN_REVIEW" and card["assignee"]["full_name"], "IN_REVIEW (T-25), assigned to the underwriter")
    status, err, _ = uw2.call("POST", f"/v1/bank/applications/{app['id']}/approve", {"expected_version": card["version"], "comment": "x"}, key=key())
    check(status in (403, 404), "another underwriter cannot decide on an application in someone else's work")
    card = uw.ok("POST", f"/v1/bank/applications/{app['id']}/request-info", {
        "expected_version": card["version"], "comment": "Нужно пояснение роста выручки и оценка залога",
        "items": [
            {"reason_code": "NI_DATA_MISMATCH_EXPLANATION", "answer_type": "TEXT"},
            {"reason_code": "NI_DATA_MISMATCH_EXPLANATION", "answer_type": "FIELD", "field_name": "monthly_revenue_declared"},
            {"reason_code": "NI_COLLATERAL_DOCUMENTS", "answer_type": "DOCUMENT", "document_type": "COLLATERAL_VALUATION"},
        ],
    }, key=key())
    check(card["status"] == "INFO_REQUESTED", "structured info request (T-29), 3 items")
    view = poll_client(client, app["id"], ["ACTION_REQUIRED"])
    items = view["info_request"]["items"]
    check(len(items) == 3 and view["action_required"] and "Ответить до" in view["client_status_text"]["deadline_text"], "client: ACTION_REQUIRED with 3 items and a deadline")
    doc_item = next(i for i in items if i["answer_type"] == "DOCUMENT")
    view = client.upload(app["id"], "COLLATERAL_VALUATION", "valuation.pdf", doc_item["id"])
    doc_id = next(d["id"] for d in view["documents"] if d["document_type"] == "COLLATERAL_VALUATION")
    answers = []
    for it in items:
        if it["answer_type"] == "TEXT":
            answers.append({"item_id": it["id"], "answer_text": "Рост выручки в 2026 году: новый контракт с федеральной торговой сетью, отчетность ГИР БО за прошлый год"})
        elif it["answer_type"] == "FIELD":
            answers.append({"item_id": it["id"], "answer_value": "6750000"})
        else:
            answers.append({"item_id": it["id"], "document_ids": [doc_id]})
    view = client.ok("POST", f"/v1/applications/{app['id']}/info-response", {"expected_version": view["version"], "answers": answers}, key=key())
    check(view["client_status"] == "CHECKING", "answer sent (T-10): client sees CHECKING")
    view = poll_client(client, app["id"], ["SPECIALIST_REVIEW"])
    card = wait_for(lambda: uw.ok("GET", f"/v1/bank/applications/{app['id']}"), lambda c: c["status"] == "IN_REVIEW", "return to the pinned underwriter (T-23)")
    reasons = [r["code"] for r in card["manual_review_reasons"]]
    sources = {s["source"]: s for s in card["sources"]}
    check("MR_RETURNED_AFTER_INFO" in reasons and card["assignee"]["full_name"], "returned to the same underwriter with MR_RETURNED_AFTER_INFO")
    cached = [h for h in card["history"] if h["event_type"] == "SOURCE_REQUEST_SUCCEEDED" and h["payload"].get("from_cache")]
    check(len(cached) >= len(sources) and all(len([a for a in s["attempts"] if a["stage"] == "ENRICH"]) <= 1 for s in sources.values()), "second pass used cached source answers (24 h), no repeated requests")
    card = uw.ok("POST", f"/v1/bank/applications/{app['id']}/approve", {"expected_version": card["version"], "comment": "Пояснение принято: контракт с сетью подтверждает рост выручки, залог покрывает сумму"}, key=key())
    proposal = [d for d in card["decisions"] if d["status"] == "PROPOSED"][-1]
    check(card["status"] == "PENDING_RISK_APPROVAL" and proposal["override"] and proposal["four_eyes_trigger"] == "OVERRIDE", "approval above the policy maximum is an override: four eyes (T-28)")
    status, err, _ = uw.call("POST", f"/v1/bank/applications/{app['id']}/confirm", {"expected_version": card["version"]}, key=key())
    check(status == 403, "underwriter cannot confirm (risk manager only)")
    pending = risk.ok("GET", "/v1/bank/applications?tab=approval&page_size=100")
    check(any(i["id"] == app["id"] for i in pending["items"]), "risk manager sees it in the 'approval' tab")
    card = risk.ok("POST", f"/v1/bank/applications/{app['id']}/confirm", {"expected_version": card["version"], "comment": "Подтверждаю"}, key=key())
    check(card["status"] == "OFFER_PENDING", "risk manager confirmed (T-31)")
    view = poll_client(client, app["id"], ["DECISION_READY"])
    option = view["offer"]["options"][0]
    check(view["offer"]["outcome"] == "APPROVED" and option["amount"] == "40000000.00" and option["term_months"] == 60 and option["rate_percent"] == "17.00", "client: approved 40 000 000 on 60 months at 17%")
    sign_and_issue(client, app["id"], option["id"], view, ["CREDIT_AGREEMENT", "PAYMENT_SCHEDULE", "GUARANTEE_AGREEMENT", "PLEDGE_AGREEMENT"])
    card = staff_card(risk, app["id"])
    types = {h["event_type"] for h in card["history"]}
    check({"APPLICATION_VIEWED", "INFO_REQUESTED", "INFO_PROVIDED", "FOUR_EYES_REQUESTED", "FOUR_EYES_APPROVED", "CONSENT_GIVEN", "LOAN_ISSUED"} <= types, "history: views, info request and answer, four eyes, consents, issue")
    check(any(a["action"] == "VIEW_APPLICATION" for a in card["audit"]) and card["field_changes"] is not None, "audit journal shows who opened the card and when")
    common_card_checks(card)


def s4(risk: Http) -> None:
    client = Http("client.sergey", PASSWORDS["client"])
    cleanup(client)
    match = client.ok("POST", "/v1/catalog/match", {"purpose": "INVENTORY", "amount": "2000000", "term_months": 12, "inn": "002000040102"})
    express = next(c for c in match["cards"] if c["product_code"] == "EXPRESS")
    check(not express["available"] and "6 месяцев" in express["unavailable_reason"], f"early check in selection: {express['unavailable_reason']}")
    app = new_application(client, "EXPRESS", "INVENTORY", 2000000, 12)
    fill_and_submit(client, app, "002000040102", {"representative_role": "OWNER", "monthly_revenue_declared": "600000", "existing_monthly_payments_declared": "0"}, expect_warning="SF_BUSINESS_AGE")
    view = poll_client(client, app["id"], ["REJECTED"])
    assert_no_internal_fields(view)
    reasons = view["decision"]["reasons"]
    check(len(reasons) == 2 and "6 месяцев" in reasons[0]["text"] and "бюро кредитных историй" in reasons[1]["text"], "client: two understandable reasons with next steps (business age, current delinquency)")
    check("30" not in reasons[1]["text"], "texts do not disclose policy thresholds")
    card = staff_card(risk, app["id"])
    final = [d for d in card["decisions"] if d["status"] == "FINAL"][-1]
    stops = [h["payload"]["reason_code"] for h in card["history"] if h["event_type"] == "STOP_FACTOR_TRIGGERED"]
    check(final["reason_codes"] == ["SF_BUSINESS_AGE", "SF_CURRENT_DELINQUENCY"] and stops == final["reason_codes"], "bank card: stop factors SF_BUSINESS_AGE, SF_CURRENT_DELINQUENCY and STOP_FACTOR_TRIGGERED events")
    check(card["scoring"]["grade"] == "E" and card["scoring"]["score"] == 507, "score is still calculated for analytics: 507, grade E")
    common_card_checks(card)


def s5(risk: Http) -> None:
    client = Http("client.oleg", PASSWORDS["client"])
    cleanup(client)
    risk.ok("POST", "/v1/demo/integrations/reset")
    log("integrations mock reset: the bureau times out on the first 4 requests for this INN")
    app = new_application(client, "EXPRESS", "INVENTORY", 3000000, 24)
    fill_and_submit(client, app, "0010005015", {"representative_role": "FINANCE_MANAGER", "monthly_revenue_declared": "6000000", "existing_monthly_payments_declared": "300000", "owner_guarantee_agreed": True})
    card = wait_for(lambda: risk.ok("GET", f"/v1/bank/applications/{app['id']}?view_context=SEARCH"), lambda c: c["status"] == "EXTERNAL_SERVICE_UNAVAILABLE", "EXTERNAL_SERVICE_UNAVAILABLE (T-14)")
    check(card["processing"]["next_retry_at"] is not None and card["processing"]["last_error_code"] == "SOURCE_TIMEOUT", f"bank: source unavailable, retry planned at {card['processing']['next_retry_at']}")
    view = client.ok("GET", f"/v1/applications/{app['id']}")
    check(view["client_status"] == "CHECKING" and "отвечает с задержкой" in view["client_status_text"]["what_is_happening"] and any(n["code"] == "NTF_CHECK_DELAYED" for n in view["notifications"]), "client: CHECKING with the delay text and a notification, no error shown")
    view = poll_client(client, app["id"], ["DECISION_READY"])
    check(view["offer"]["outcome"] == "APPROVED" and view["offer"]["options"][0]["monthly_payment"] == "155634.46", "after the retry: auto approval 3 000 000 on 24 months, payment 155 634,46")
    card = risk.ok("GET", f"/v1/bank/applications/{app['id']}")
    bki = next(s for s in card["sources"] if s["source"] == "CREDIT_BUREAU")["attempts"]
    other = [s for s in card["sources"] if s["source"] != "CREDIT_BUREAU"]
    check([a["outcome"] for a in bki] == ["FAILED"] * 4 + ["SUCCESS"], "bureau attempts: 4 failed, the 5th succeeded", bki)
    check(all(len([a for a in s["attempts"] if a["stage"] == "ENRICH"]) <= 1 for s in other), "other sources were not requested again (answers kept, registry data reused from prefill)")
    sign_and_issue(client, app["id"], view["offer"]["options"][0]["id"], view, ["CREDIT_AGREEMENT", "PAYMENT_SCHEDULE", "GUARANTEE_AGREEMENT"])


def authz(risk: Http) -> None:
    irina = Http("client.irina", PASSWORDS["client"])
    andrey = Http("client.andrey", PASSWORDS["client"])
    own = irina.ok("GET", "/v1/applications?page_size=1")["items"]
    if own:
        status, _, _ = andrey.call("GET", f"/v1/applications/{own[0]['id']}")
        check(status == 404, "a client cannot see another client's application (404)")
    status, _, _ = andrey.call("GET", "/v1/bank/applications")
    check(status == 403, "a client cannot use the employee API (403)")
    metrics = risk.ok("GET", "/v1/risk/metrics?period_days=90")
    check(metrics["applications_created"] >= 419 and metrics["north_star"] is not None, f"metrics on events with synthetic history: {metrics['applications_created']} applications, North Star {metrics['north_star']}")
    configs = risk.ok("GET", "/v1/risk/configs")
    check({c["version"] for c in configs["active"]} == {"scorecard-2026.10-v1", "policy-2026.10-v1"}, "active versions: scorecard-2026.10-v1, policy-2026.10-v1 with sha256")


SCENARIOS = {"S1": ("Автоодобрение экспресс-кредита", s1), "S2": ("Контрпредложение и кредитная линия", s2), "S3": ("Дозапрос, ручное рассмотрение, 4 глаза", s3), "S4": ("Отказ по стоп-факторам", s4), "S5": ("Сбой БКИ, повтор и одобрение", s5), "AUTHZ": ("Права доступа, метрики, версии", authz)}


def main(argv: List[str]) -> int:
    selected = [a.upper() for a in argv[1:]] or list(SCENARIOS)
    print(f"{BOLD}E2E demo against {BASE}{RESET}")
    try:
        status, body, _ = Http.__new__(Http).call("GET", "/health/ready", auth=False)
    except Exception as exc:  # noqa: BLE001
        print(f"{RED}API is not reachable at {BASE}: {exc}{RESET}")
        return 2
    if status != 200:
        print(f"{RED}API is not ready: {body}{RESET}")
        return 2
    risk = Http("risk.elena", PASSWORDS["risk"])
    failed = []
    started = time.time()
    for code in selected:
        title, fn = SCENARIOS[code]
        print(f"\n{BOLD}{code}. {title}{RESET}")
        t0 = time.time()
        try:
            fn(risk)
            print(f"  {GREEN}{code} passed{RESET} {DIM}({time.time() - t0:.1f} s){RESET}")
        except Failure as exc:
            failed.append(code)
            print(f"  {RED}FAILED: {exc}{RESET}")
    print()
    if failed:
        print(f"{RED}{BOLD}E2E FAILED: {', '.join(failed)}{RESET} ({time.time() - started:.0f} s)")
        return 1
    print(f"{GREEN}{BOLD}E2E PASSED: {', '.join(selected)}{RESET} ({time.time() - started:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
