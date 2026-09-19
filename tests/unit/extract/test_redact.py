from app.extract.redact import redact


def test_aadhaar_redacted():
    text, tags = redact("Aadhaar: 234512341234 on file")
    assert "234512341234" not in text
    assert "AADHAAR" in tags


def test_pan_redacted():
    text, tags = redact("PAN ABCDE1234F provided")
    assert "ABCDE1234F" not in text
    assert "PAN" in tags


def test_account_redacted():
    text, tags = redact("Account number 123456789012 debited")
    assert "123456789012" not in text
    assert "ACCOUNT" in tags


def test_ifsc_redacted():
    text, tags = redact("IFSC HDFC0001234 used for transfer")
    assert "HDFC0001234" not in text
    assert "IFSC" in tags


def test_email_redacted():
    text, tags = redact("contact borrower@example.com for details")
    assert "borrower@example.com" not in text
    assert "EMAIL" in tags


def test_gst_redacted():
    text, tags = redact("GSTIN 27ABCDE1234F1Z5 registered")
    assert "27ABCDE1234F1Z5" not in text
    assert "GST" in tags


def test_ordering_account_before_phone_does_not_swallow_phone():
    """A ten-digit phone number must be tagged PHONE, not swallowed whole by the ACCOUNT
    pattern (9-18 digits) matching first."""
    text, tags = redact("call 9876543210 now")
    assert "PHONE" in tags
    assert "9876543210" not in text


def test_exempt_field_passes_through_unchanged():
    original = "Grievance officer: 9876543210, officer@lender.com"
    text, tags = redact(original, exempt=True)
    assert text == original
    assert tags == []


def test_gold_loan_agreement_not_redacted_as_a_name():
    text, tags = redact("Gold Loan Agreement executed on this date")
    assert text == "Gold Loan Agreement executed on this date"
    assert tags == []


def test_multiple_pii_types_all_redacted():
    text, tags = redact("Aadhaar 234512341234, phone 9876543210, email x@y.com")
    assert set(tags) == {"AADHAAR", "PHONE", "EMAIL"}
    assert "234512341234" not in text
    assert "9876543210" not in text
    assert "x@y.com" not in text
