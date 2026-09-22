import json

import structlog

from app.obs.logging import (
    DENYLIST_KEYS,
    bind_request_context,
    clear_request_context,
    configure_logging,
    drop_denylisted_keys,
    get_logger,
)


def test_denylist_processor_redacts_every_listed_key():
    event_dict = {key: "sensitive content" for key in DENYLIST_KEYS}
    event_dict["field_key"] = "apr_bps"  # not denylisted — must survive untouched

    out = drop_denylisted_keys(None, "info", dict(event_dict))

    for key in DENYLIST_KEYS:
        assert out[key] == "[REDACTED-BY-DENYLIST]"
    assert out["field_key"] == "apr_bps"


def test_denylist_processor_redacts_nested_dict_and_list():
    event_dict = {
        "field_key": "apr_bps",
        "extra": {"prompt": "the full prompt text", "ok": "fine"},
        "facts": [
            {"field_key": "apr_bps", "value_raw": "18.5%"},
            {"field_key": "sanctioned_amount", "value_raw": "Rs 5,00,000"},
        ],
    }
    out = drop_denylisted_keys(None, "info", event_dict)
    assert out["extra"]["prompt"] == "[REDACTED-BY-DENYLIST]"
    assert out["extra"]["ok"] == "fine"
    assert all(f["value_raw"] == "[REDACTED-BY-DENYLIST]" for f in out["facts"])
    assert out["facts"][0]["field_key"] == "apr_bps"


def test_denylist_processor_is_a_no_op_when_keys_absent():
    event_dict = {"verdict": "compliant", "clause_path": "RBC2025/p35"}
    out = drop_denylisted_keys(None, "info", dict(event_dict))
    assert out == event_dict


def test_configured_logger_emits_json_with_denylist_applied(capsys):
    configure_logging(json_output=True)
    log = get_logger()
    log.info(
        "extraction complete",
        field_key="apr_bps",
        value_raw="18.5%",
        quoted_span="18.5% p.a.",
        rationale="the model's reasoning goes here",
    )
    captured = capsys.readouterr()
    line = json.loads(captured.out.strip().splitlines()[-1])

    assert line["event"] == "extraction complete"
    assert line["field_key"] == "apr_bps"
    assert line["value_raw"] == "[REDACTED-BY-DENYLIST]"
    assert line["quoted_span"] == "[REDACTED-BY-DENYLIST]"
    assert line["rationale"] == "[REDACTED-BY-DENYLIST]"
    # No verbatim leak anywhere in the raw line, even inside another field's value.
    assert "18.5% p.a." not in captured.out
    assert "the model's reasoning goes here" not in captured.out


def test_bound_context_appears_on_every_line_until_cleared(capsys):
    configure_logging(json_output=True)
    try:
        bind_request_context(
            request_id="req-123",
            tenant_id="tenant-abc",
            loan_account_id="loan-1",
            stage="verdict",
            check_key="R01_docs_release_30d",
        )
        log = get_logger()
        log.info("first line")
        log.info("second line")
    finally:
        clear_request_context()

    captured = capsys.readouterr()
    lines = [json.loads(line_) for line_ in captured.out.strip().splitlines()]
    assert len(lines) == 2
    for line in lines:
        assert line["request_id"] == "req-123"
        assert line["tenant_id"] == "tenant-abc"
        assert line["loan_account_id"] == "loan-1"
        assert line["stage"] == "verdict"
        assert line["check_key"] == "R01_docs_release_30d"


def test_context_cleared_does_not_leak_into_next_test(capsys):
    log = get_logger()
    log.info("unbound line")
    captured = capsys.readouterr()
    line = json.loads(captured.out.strip().splitlines()[-1])
    assert "request_id" not in line


def test_configure_logging_is_idempotent():
    configure_logging(json_output=True)
    configure_logging(json_output=True)
    # No exception, and structlog is still configured with our processors.
    assert structlog.is_configured()
