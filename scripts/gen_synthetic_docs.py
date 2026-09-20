#!/usr/bin/env python3
"""Synthetic document generator. M3-T07, LLD §17.3's `extraction_core` fixture source.

Generates plain-text fixtures for the six "deep treatment" document types (PRD §6.1): KFS,
loan agreement, sanction letter, MITC, collections-call transcript, closure statement. Each
document varies layout (one of several templates per type), currency format, date format,
and — for a minority of documents — OCR-style noise, so `extraction_core` eval cases built
from these fixtures actually exercise formatting robustness rather than one fixed shape.

Every document is synthetic by construction: names, amounts, dates and identifiers are drawn
from a fixed, clearly-fake pool (`_BORROWER_NAMES`, `_LENDER_NAMES`) — never a real person or
lender — and every fixture opens with a visible `SYNTHETIC DATA — TEST FIXTURE` banner
(CLAUDE.md §2.4). No generated value matches the AADHAAR, PAN, or ACCOUNT patterns in
`app/extract/redact.py` — proposal/reference numbers use letter-prefixed, dash-broken digit
runs (e.g. "LN-SYN-2026-00042"), and amounts are always comma-grouped, so no field ever
produces a bare 9-18 digit run or a 5-letter/4-digit/1-letter PAN shape.
"""

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

SYNTHETIC_BANNER = "*** SYNTHETIC DATA — TEST FIXTURE. No real borrower or lender. ***"

_BORROWER_NAMES = ["Asha Devi", "Ravi Kumar Singh", "Priya Nair", "Mohammed Iqbal", "Sunita Yadav"]
_LENDER_NAMES = ["Northbridge Finance Ltd.", "Sunrise Capital NBFC Ltd.", "Meridian Credit Ltd."]
_LOAN_TYPES = ["personal", "gold", "vehicle", "consumer_durable", "business"]
_AGENT_NAMES = ["Deepak Rao", "Farha Sheikh", "Vikram Chauhan"]
_AGENCIES = ["Apex Recovery Services", "Clearline Collections Pvt. Ltd."]

_CURRENCY_FORMATS = [
    lambda rupees: f"Rs. {rupees:,}",
    lambda rupees: f"INR {rupees:,}.00",
    lambda rupees: f"₹{rupees:,}/-",
]
_DATE_FORMATS = [
    lambda d: d.strftime("%d/%m/%Y"),
    lambda d: d.strftime("%d-%m-%Y"),
    lambda d: d.strftime("%d %B %Y"),
    lambda d: d.strftime("%Y-%m-%d"),
]

_OCR_SUBSTITUTIONS = {"O": "0", "l": "1", "S": "5", "e": "c"}
_OCR_NOISE_RATE = 0.15
_OCR_CHAR_HIT_RATE = 0.02


def _fmt_money(rupees: int, rng: random.Random) -> str:
    return rng.choice(_CURRENCY_FORMATS)(rupees)


def _fmt_date(d: date, rng: random.Random) -> str:
    return rng.choice(_DATE_FORMATS)(d)


def _proposal_ref(rng: random.Random, prefix: str) -> str:
    """Letter-prefixed, dash-broken so no digit run is 9+ chars long (avoids the ACCOUNT
    pattern in app/extract/redact.py) and no 5-letter/4-digit/1-letter run occurs (PAN)."""
    return f"{prefix}-SYN-{rng.randint(2025, 2026)}-{rng.randint(10000, 99999):05d}"


def _apply_ocr_noise(text: str, rng: random.Random) -> str:
    chars = list(text)
    for i, ch in enumerate(chars):
        if ch in _OCR_SUBSTITUTIONS and rng.random() < _OCR_CHAR_HIT_RATE:
            chars[i] = _OCR_SUBSTITUTIONS[ch]
    return "".join(chars)


def _gen_kfs(rng: random.Random) -> str:
    base = date(2026, rng.randint(1, 9), rng.randint(1, 28))
    principal = rng.choice([100000, 250000, 500000, 750000, 1200000])
    rate_bps = rng.choice([1200, 1450, 1650, 1850, 2100])
    fees = rng.choice([1000, 2500, 5000, 7500])
    ref = _proposal_ref(rng, "LN")
    templates = [
        (
            "KEY FACTS STATEMENT\n"
            "Loan proposal number: {ref}\n"
            "Type of loan: {loan_type}\n"
            "Sanctioned loan amount: {amount}\n"
            "Loan term: {term} days\n"
            "Interest rate: {rate:.2f}% p.a. ({rate_type})\n"
            "Total fees and charges: {fees}\n"
            "Annual Percentage Rate (APR): {apr:.2f}% p.a.\n"
            "Cooling-off / look-up period: {cooloff} days. No prepayment penalty applies "
            "if the borrower exits within this period.\n"
            "Grievance redressal officer: {gname}, phone {gphone}, email {gemail}\n"
            "This Key Facts Statement is valid for {validity} working days from the date "
            "of issue, {issued}.\n"
        ),
        (
            "-- KFS (Key Facts Statement) --\n"
            "Ref no.: {ref}\n"
            "Product: {loan_type} loan\n"
            "Amount sanctioned: {amount}\n"
            "Tenure: {term} days\n"
            "Rate of interest: {rate:.2f}% per annum, {rate_type} basis\n"
            "Fees payable: {fees}\n"
            "APR (all-inclusive): {apr:.2f}%\n"
            "Look-up / cooling-off period: {cooloff} days; no prepayment charge within this "
            "window.\n"
            "Grievance officer: {gname} | Tel: {gphone} | Email: {gemail}\n"
            "Validity of this statement: {validity} working days from {issued}.\n"
        ),
    ]
    body = rng.choice(templates).format(
        ref=ref,
        loan_type=rng.choice(_LOAN_TYPES),
        amount=_fmt_money(principal, rng),
        term=rng.choice([180, 365, 730, 1095]),
        rate=rate_bps / 100,
        rate_type=rng.choice(["fixed", "floating"]),
        fees=_fmt_money(fees, rng),
        apr=(rate_bps + rng.randint(50, 250)) / 100,
        cooloff=rng.choice([1, 3, 7]),
        gname=rng.choice(_AGENT_NAMES),
        gphone=f"1800-{rng.randint(100,999)}-{rng.randint(1000,9999)}",
        gemail="grievance@" + rng.choice(_LENDER_NAMES).split()[0].lower() + ".example",
        validity=rng.choice([3, 5, 7]),
        issued=_fmt_date(base, rng),
    )
    return body


def _gen_loan_agreement(rng: random.Random) -> str:
    principal = rng.choice([100000, 250000, 500000, 750000, 1200000])
    rate_bps = rng.choice([1200, 1450, 1650, 1850, 2100])
    borrower = rng.choice(_BORROWER_NAMES)
    lender = rng.choice(_LENDER_NAMES)
    ref = _proposal_ref(rng, "LA")
    body = (
        "LOAN AGREEMENT\n"
        f'This agreement is made between {lender} ("the Lender") and {borrower} '
        '("the Borrower").\n'
        f"Agreement reference: {ref}\n"
        f"Type of loan: {rng.choice(_LOAN_TYPES)}\n"
        f"Sanctioned amount: {_fmt_money(principal, rng)}\n"
        f"Rate of interest: {rate_bps/100:.2f}% p.a.\n"
        f"Disbursal shall be credited to the Borrower's own bank account.\n"
        f"Repayment shall be debited directly from the Borrower's own bank account; no "
        f"pass-through or pooling account is used.\n"
        f"Cooling-off period: {rng.choice([1, 3, 7])} days; no prepayment penalty within "
        "this period.\n"
        f"The particulars of the Key Facts Statement are reproduced as a summary box "
        "forming part of this Agreement.\n"
        f"Grievance escalation mechanism is described in clause {rng.randint(1, 9)}.{rng.randint(1,9)} "
        "of this Agreement.\n"
        f"This loan is not transferable without the Lender's prior written consent.\n"
    )
    if rng.random() < 0.4:
        body += (
            f"A lending service provider, {rng.choice(_AGENCIES)}, is engaged for sourcing "
            "and recovery under this Agreement; its fee is borne by the Lender, not the "
            "Borrower.\n"
        )
    return body


def _gen_sanction_letter(rng: random.Random) -> str:
    base = date(2026, rng.randint(1, 9), rng.randint(1, 28))
    principal = rng.choice([100000, 250000, 500000, 750000, 1200000])
    rate_bps = rng.choice([1200, 1450, 1650, 1850, 2100])
    ref = _proposal_ref(rng, "SL")
    return (
        "SANCTION LETTER\n"
        f"Reference: {ref}\n"
        f"Date: {_fmt_date(base, rng)}\n"
        f"We are pleased to sanction a {rng.choice(_LOAN_TYPES)} loan of "
        f"{_fmt_money(principal, rng)} at {rate_bps/100:.2f}% p.a.\n"
        f"Processing fee: {_fmt_money(rng.choice([1000, 2500, 5000]), rng)}\n"
        f"Loan term: {rng.choice([180, 365, 730])} days.\n"
        f"Annual Percentage Rate: {(rate_bps + rng.randint(50,250))/100:.2f}% p.a.\n"
    )


def _gen_mitc(rng: random.Random) -> str:
    base = date(2026, rng.randint(1, 9), rng.randint(1, 28))
    rate_bps = rng.choice([1200, 1450, 1650, 1850, 2100])
    return (
        "MOST IMPORTANT TERMS AND CONDITIONS (MITC)\n"
        f"Date: {_fmt_date(base, rng)}\n"
        f"Applicable interest rate: {rate_bps/100:.2f}% p.a.\n"
        "Default and penal charges are levied strictly as charges, not capitalised as "
        "additional interest.\n"
        "The borrower may access the full agreement and KFS on request at no charge.\n"
        f"Grievance officer contact is set out in the accompanying Key Facts Statement.\n"
    )


def _gen_call_transcript(rng: random.Random) -> str:
    base = date(2026, rng.randint(1, 9), rng.randint(1, 28))
    contact_hour = rng.choice([9, 11, 14, 19, 21])
    agent = rng.choice(_AGENT_NAMES)
    agency = rng.choice(_AGENCIES)
    dpd = rng.choice([15, 35, 65, 95])
    return (
        "COLLECTIONS CALL TRANSCRIPT\n"
        f"Date/time of call: {_fmt_date(base, rng)} {contact_hour:02d}:00 IST\n"
        f"Agent: {agent} ({agency})\n"
        f"Agent identified themself and the agency before proceeding with the call.\n"
        f"Days past due at time of contact: {dpd}\n"
        "Call was recorded; recording will be retained for {ret} days.\n"
        "No third party was contacted regarding this account.\n"
        "No abusive language or threats were used during this call.\n"
    ).format(ret=rng.choice([90, 180, 365]))


def _gen_closure_statement(rng: random.Random) -> str:
    base = date(2026, rng.randint(1, 9), rng.randint(1, 20))
    release_days = rng.choice([5, 15, 29, 30, 31, 45])
    return (
        "CLOSURE STATEMENT\n"
        f"Full repayment received on: {_fmt_date(base, rng)}\n"
        f"Closure statement issued on: {_fmt_date(base + timedelta(days=1), rng)}\n"
        f"Original title documents released on: "
        f"{_fmt_date(base + timedelta(days=release_days), rng)}\n"
    )


_GENERATORS = {
    "kfs": _gen_kfs,
    "loan_agreement": _gen_loan_agreement,
    "sanction_letter": _gen_sanction_letter,
    "mitc": _gen_mitc,
    "call_transcript": _gen_call_transcript,
    "closure_statement": _gen_closure_statement,
}


def generate_document(doc_type: str, rng: random.Random) -> str:
    body = _GENERATORS[doc_type](rng)
    if rng.random() < _OCR_NOISE_RATE:
        body = _apply_ocr_noise(body, rng)
    return f"{SYNTHETIC_BANNER}\n\n{body}"


def generate_all(out_dir: Path, count: int, *, seed: int = 42) -> list[Path]:
    rng = random.Random(seed)
    doc_types = list(_GENERATORS)
    per_type = max(1, count // len(doc_types))
    written: list[Path] = []
    for doc_type in doc_types:
        type_dir = out_dir / doc_type
        type_dir.mkdir(parents=True, exist_ok=True)
        for i in range(per_type):
            text = generate_document(doc_type, rng)
            path = type_dir / f"{doc_type}_{i:04d}.txt"
            path.write_text(text)
            written.append(path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--count", type=int, default=150)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    written = generate_all(Path(args.out), args.count, seed=args.seed)
    print(f"wrote {len(written)} synthetic documents to {args.out}")


if __name__ == "__main__":
    main()
