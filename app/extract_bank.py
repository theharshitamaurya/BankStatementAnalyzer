import argparse
import csv
import datetime as dt
import json
import pathlib
import re
from collections import Counter
from decimal import Decimal
import concurrent.futures

import pdfplumber


AMOUNT_RE = re.compile(r"-?\d{1,3}(?:,\d{2,3})*(?:\.\d{2})-?|-?\d+\.\d{2}-?")
DATE_TOKEN_RE = re.compile(
    r"\b(?:\d{2}[-/.]\d{2}[-/.]\d{4}|\d{2}[-/.]\d{2}[-/.]\d{2}|\d{2}[-/][A-Za-z]{3}[-/]\d{4}|\d{2}\s+[A-Za-z]{3}\s+\d{4})\b",
    re.I,
)
DATE_START_RE = re.compile(
    r"^\s*(?:\d+\s+)?'?(?:\d{2}[-/.]\d{2}[-/.]\d{4}|\d{2}[-/.]\d{2}[-/.]\d{2}|\d{2}[-/][A-Za-z]{3}[-/]\d{4}|\d{2}\s+[A-Za-z]{3}\s+\d{4})\b",
    re.I,
)
BOILER_RE = re.compile(
    r"(Page\s+\d+|PageNo|Registered Office|This is a computer generated|"
    r"Generated On|STATEMENT OF ACCOUNT$|Transaction Value Date Particulars|"
    r"Date Narration|TRANS DATE VALUE DATE|Sr\.?No\.?|Opening Balance Total Debit|"
    r"Legends for transactions|Never share your OTP|For clarification kindly)",
    re.I,
)
HDFC_DATE_START_RE = re.compile(r"^(\d{2}/\d{2}/\d{2})\s+(.*)$")
HDFC_VALUE_DATE_RE = re.compile(r"\b\d{2}/\d{2}/\d{2}\b")
HDFC_AMOUNT_RE = re.compile(r"(?<!\w)-?\d{1,3}(?:,\d{3})*\.\d{2}-?")
HDFC_REF_RE = re.compile(r"^(?P<narration>.+?)\s+(?P<reference>(?:[A-Z]{2,}\d[A-Z0-9]*|\d{10,}|[A-Z0-9]{12,}|CDT\d{8,}))$")
HDFC_NOISE_RE = re.compile(
    r"(HDFC BANK LIMITED|\*Closing balance includes|Contents of this statement|"
    r"Page\s*No\s*\.?:|Account Branch\s*:|Registered Office Address|"
    r"State account branch GSTN|HDFC Bank GSTIN|https://www\.hdfcbank\.com|Generated On:|"
    r"Cust\s*ID\s*:|A/C\s*Open\s*Date\s*:|Nomination\s*:|Account\s*No\s*:|"
    r"Address\s*:|Email\s*:|Phone\s*:|Phone\s+no\.?\s*:|JOINT HOLDERS|OD Limit|Currency\s*:|"
    r"From\s*:|To\s*:|Date\s+Narration|Chq\./Ref\.No\.|Value\s+Dt|"
    r"Withdrawal\s+Amt\.|Deposit\s+Amt\.|Closing\s+Balance|STATEMENT\s+SUMMARY|"
    r"\bCity\s*:|\bBranch\s+Code\s*:|\bM/S\.|\bC/O\b|\bthe address on this statement\b|"
    r"\bthis statement\b|\bnot require signature\b|GURU\s+NANAK|AMBADI\s+ROAD|"
    r"MAHAVIR\s+DHAM|NALLASOPARA|VASAI\s*\(WEST\))",
    re.I,
)


def extract_account_details(text):
    name_match = re.search(r"(?:A/C\s*Name|A/c\s*Name|Account\s*Name)\s*:?\s*([^\n]+)", text, re.I)
    name = ""
    if name_match:
        name = name_match.group(1).strip()
    else:
        city_match = re.search(r"City\s*:\s*[^\n]+\n([^\n]+)", text, re.I)
        if city_match:
            candidate = city_match.group(1).strip()
            if not any(k in candidate.upper() for k in ["STATE", "PHONE", "EMAIL", "ZIP", "PIN CODE", "NOMIN", "CUSTID"]):
                name = candidate
        if not name:
            ms_match = re.search(r"\bM/[Ss]\.\s*([A-Za-z0-9\s&.,'-]+)", text[:2000])
            if ms_match:
                name = "M/S. " + ms_match.group(1).strip()
            else:
                ms_match2 = re.search(r"\bM/S\s+([A-Za-z0-9\s&.,'-]+)", text[:2000])
                if ms_match2:
                    name = "M/S " + ms_match2.group(1).strip()
        if not name and "Statement of Account No" in text[:2000]:
            first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
            if first_line and not re.search(r"statement|account|customer|ifsc|micr", first_line, re.I):
                name = first_line
        if not name:
            kotak_match = re.search(r"(?:\d{2}\s+[A-Za-z]{3}\s+\d{4}\s*-\s*\d{2}\s+[A-Za-z]{3}\s+\d{4})\n([^\n]+)", text, re.I)
            if kotak_match:
                candidate = kotak_match.group(1).strip()
                if not re.search(r"account|statement|page", candidate, re.I):
                    name = candidate

    if name:
        name = name.split("Address :")[0].strip()
        name = name.split("Joint Holders :")[0].strip()
        name = name.split("JOINTHOLDERS:")[0].strip()
        name = re.sub(r"\s+", " ", name).strip()
    
    acc_match = re.search(
        r"(?:Statement\s+of\s+Account\s+No|Account\s*No\.?|AccountNo|A/C\s*Number|A/C\s*No\.?|A/c\s*No\.?|A/c\s*Number)\s*:?\s*(\d+)",
        text,
        re.I
    )
    account_no = ""
    if acc_match:
        account_no = acc_match.group(1).strip()
    else:
        digits = re.findall(r"\b\d{9,18}\b", text[:2000])
        if digits:
            for d in digits:
                if d in text[:2000]:
                    account_no = d
                    break
                
    return name, account_no


def slugify_name(name):
    name = name.upper()
    for prefix in ["M/S.", "M/S", "MR.", "MRS.", "MR", "MRS", "DR.", "DR", "MISS", "MS.", "MS"]:
        if name.startswith(prefix):
            name = name[len(prefix):].strip()
    name = re.sub(r"[^A-Z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "ACCOUNT_HOLDER"


def format_period_slug(date_str):
    if date_str and len(date_str) >= 7:
        return date_str[:7].replace("-", "_")
    return "UNKNOWN"


def parse_amount(raw):
    raw = raw.replace(",", "").strip()
    if raw in ("", "-"):
        return Decimal("0.00")
    negative = raw.startswith("-") or raw.endswith("-")
    raw = raw.strip("-")
    value = Decimal(raw)
    return -value if negative else value


def parse_balance_from_match(match, text):
    value = parse_amount(match.group(0))
    suffix = text[match.end() : match.end() + 2].lower()
    if suffix == "dr" and value > 0:
        return -value
    return value


def to_float(value):
    return float(value)


def parse_any_date(raw):
    raw = raw.strip("' ")
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%y", "%d/%m/%y", "%d.%m.%y", "%d-%b-%Y", "%d/%b/%Y", "%d %b %Y"):
        try:
            return dt.datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def money_close(a, b, tolerance=Decimal("0.05")):
    return abs(a - b) <= tolerance


def parse_hdfc_date(raw):
    try:
        return dt.datetime.strptime(raw, "%d/%m/%y").date().isoformat()
    except ValueError:
        return parse_any_date(raw)


def is_hdfc_noise(line):
    if HDFC_NOISE_RE.search(line) or BOILER_RE.search(line):
        return True
    upper = line.upper()
    profile_tokens = [
        "PALGHAR",
        "MAHARASHTRA",
        "CUST ID",
        "NOMINATION",
        "REGISTERED",
        "A/C OPEN DATE",
        "IFSC",
        "MICR",
    ]
    return any(token in upper for token in profile_tokens) and not HDFC_DATE_START_RE.match(line)


def clean_hdfc_continuation(lines):
    kept = []
    for line in lines:
        line = HDFC_NOISE_RE.split(line, maxsplit=1)[0].strip()
        if not line:
            continue
        if is_hdfc_noise(line):
            continue
        kept.append(line)
    return " ".join(kept).strip()


def split_hdfc_narration_reference(rest):
    rest = re.sub(r"\s+", " ", rest).strip()
    rest = re.sub(r"[\s.-]+$", "", rest)
    match = HDFC_REF_RE.match(rest)
    if match:
        return match.group("narration").strip(), match.group("reference").strip()

    parts = rest.rsplit(" ", 1)
    if len(parts) == 2 and re.fullmatch(r"[A-Z0-9]{10,}", parts[1]):
        return parts[0].strip(), parts[1].strip()
    return rest, ""


def build_hdfc_transactions(text, pdf_name, bank, st_from, st_to, opening_balance, seq_start, issues):
    start = text.find("Date Narration")
    end_match = re.search(r"STATEMENT\s*SUMMARY\s*:-", text, re.I)
    end = end_match.start() if end_match else len(text)
    block = text[start:end] if start != -1 else text[:end]

    txs = []
    current = None
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("Date Narration") or is_hdfc_noise(line):
            continue
        match = HDFC_DATE_START_RE.match(line)
        if match:
            if current:
                txs.append(current)
            current = {"start_line": line, "date": match.group(1), "cont": []}
        elif current:
            current["cont"].append(line)
    if current:
        txs.append(current)

    records = []
    balance = opening_balance
    seq = seq_start
    for tx in txs:
        line = tx["start_line"]
        all_dates = list(HDFC_VALUE_DATE_RE.finditer(line))
        if len(all_dates) < 2:
            issues.append({"file": pdf_name, "issue": "could not find HDFC value date", "line": line})
            continue

        value_date = all_dates[-1].group(0)
        amount_matches = list(HDFC_AMOUNT_RE.finditer(line[all_dates[-1].end() :]))
        if len(amount_matches) < 2:
            issues.append({"file": pdf_name, "issue": "could not find HDFC amounts", "line": line})
            continue

        printed_amount = parse_amount(amount_matches[-2].group(0))
        closing = parse_amount(amount_matches[-1].group(0))
        if balance is None:
            balance = closing

        rest = line[len(tx["date"]) : all_dates[-1].start()].strip()
        narration, reference = split_hdfc_narration_reference(rest)
        continuation = clean_hdfc_continuation(tx["cont"])
        full_narration = re.sub(r"\s+", " ", f"{narration} {continuation}".strip()).strip(" .-")

        delta = closing - balance
        if printed_amount < 0:
            withdrawal = abs(printed_amount)
            deposit = Decimal("0.00")
        elif money_close(delta, printed_amount):
            deposit = printed_amount
            withdrawal = Decimal("0.00")
        elif money_close(delta, -printed_amount):
            withdrawal = printed_amount
            deposit = Decimal("0.00")
        elif delta >= 0:
            deposit = printed_amount
            withdrawal = Decimal("0.00")
        else:
            withdrawal = printed_amount
            deposit = Decimal("0.00")

        seq += 1
        records.append(
            {
                "seq": seq,
                "source_file": pdf_name,
                "statement_from": st_from,
                "statement_to": st_to,
                "date": parse_hdfc_date(tx["date"]),
                "value_date": parse_hdfc_date(value_date),
                "narration": full_narration[:500],
                "reference": reference,
                "direction": "Receipt" if deposit > 0 else "Payment",
                "withdrawal": to_float(withdrawal),
                "deposit": to_float(deposit),
                "amount": to_float(deposit if deposit > 0 else withdrawal),
                "closing_balance": to_float(closing),
                "bank": bank,
            }
        )
        balance = closing
    return records


def password_candidates(path, manual_passwords=None):
    stem = pathlib.Path(path).stem
    candidates = [""]
    for password in manual_passwords or []:
        password = str(password).strip()
        if password:
            candidates.append(password)
    for pattern in [
        r"PW[-\s]*([A-Za-z0-9]+)",
        r"PSW[-\s]*([A-Za-z0-9]+)",
        r"PWS[-\s]*([A-Za-z0-9]+)",
        r"-\s*([A-Z]{4}\d{4})$",
    ]:
        match = re.search(pattern, stem, re.I)
        if match:
            candidates.append(match.group(1))
    return list(dict.fromkeys(candidates))


def read_pdf_text(path, manual_passwords=None):
    last_error = None
    for password in password_candidates(path, manual_passwords):
        try:
            kwargs = {"password": password} if password else {}
            with pdfplumber.open(path, **kwargs) as pdf:
                text = "\n".join(page.extract_text(x_tolerance=1, y_tolerance=3) or "" for page in pdf.pages)
                return text, len(pdf.pages), password
        except Exception as exc:
            last_error = exc
    raise last_error


def detect_bank(text, filename):
    filename_upper = pathlib.Path(filename).name.upper()
    header_upper = text[:5000].upper()
    upper = f"{filename_upper}\n{header_upper}"
    if "KOTAK" in upper:
        return "Kotak Mahindra Bank"
    if "AXIS" in filename_upper or "AXIS BANK" in header_upper:
        return "Axis Bank"
    if "HDFC" in filename_upper or "HDFC BANK" in header_upper:
        return "HDFC Bank"
    if "ICICI" in filename_upper or re.search(r"\bICICI\s+BANK\b", header_upper):
        return "ICICI Bank"
    if "BANK OF BARODA" in filename_upper or "BANK OF BARODA" in header_upper:
        return "Bank of Baroda"
    if "IDFC FIRST" in upper:
        return "IDFC First Bank"
    if "IDFB" in upper:
        return "IDFC First Bank"
    if "AXIS BANK" in upper or "UTIB" in upper:
        return "Axis Bank"
    if "ICICI" in upper:
        return "ICICI Bank"
    if "DCB BANK" in upper:
        return "DCB Bank"
    if "IDBI BANK" in upper:
        return "IDBI Bank"
    if "FEDERAL BANK" in upper or "FDRL" in upper:
        return "Federal Bank"
    if "UNION BANK" in upper or "UBIN" in upper:
        return "Union Bank"
    if "SARASWAT" in upper or "SRCB" in upper:
        return "Saraswat Bank"
    if "BANK OF MAHARASHTRA" in upper or "MAHB" in upper:
        return "Bank of Maharashtra"
    if "BANK OF BARODA" in upper or "BARB0" in upper:
        return "Bank of Baroda"
    if "VASAI VIKAS" in upper or "VVSB" in upper:
        return "Vasai Vikas Bank"
    if "BASSEIN CATHOLIC" in upper or "BACB" in upper:
        return "Bassein Catholic Co-op Bank"
    return "Unknown Bank"


def find_period(text):
    patterns = [
        r"From\s*:?\s*(\d{2}/\d{2}/\d{4})\s+To\s*:?\s*(\d{2}/\d{2}/\d{4})",
        r"PERIOD\s*:?\s*(\d{2}[-/]\d{2}[-/]\d{4})\s+(?:to|To|-)\s+(\d{2}[-/]\d{2}[-/]\d{4})",
        r"STATEMENT PERIOD\s*:?\s*(\d{4}-\d{2}-\d{2})\s+TO\s+(\d{4}-\d{2}-\d{2})",
        r"from\s+(\d{2}[-/][A-Za-z]{3}[-/]\d{4})\s+to\s+(\d{2}[-/][A-Za-z]{3}[-/]\d{4})",
        r"period\s+of\s+(\d{2}[-/]\d{2}[-/]\d{4})\s+to\s+(\d{2}[-/]\d{2}[-/]\d{4})",
        r"FOR THE PERIOD FROM\s+(\d{4}-\d{2}-\d{2})\s+TO\s+(\d{4}-\d{2}-\d{2})",
        r"(\d{2}\s+[A-Za-z]{3}\s+\d{4})\s*-\s*(\d{2}\s+[A-Za-z]{3}\s+\d{4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return normalize_period_date(match.group(1)), normalize_period_date(match.group(2))
    dates = [parse_any_date(m.group(0)) for m in DATE_TOKEN_RE.finditer(text)]
    dates = [d for d in dates if d]
    return (min(dates), max(dates)) if dates else ("", "")


def normalize_period_date(raw):
    raw = raw.strip().replace(" ", "-")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    return parse_any_date(raw)


def extract_opening_balance(text):
    match = re.search(r"Opening Balance\s*:?\s*(-?[\d,]+\.\d{2})(Cr|Dr)?", text, re.I)
    if match:
        value = parse_amount(match.group(1))
        if (match.group(2) or "").lower() == "dr":
            value = -value
        return value
    match = re.search(r"Opening Balance[^\d]+(-?[\d,]+\.\d{2})(Cr|Dr)?", text, re.I)
    if match:
        value = parse_amount(match.group(1))
        if (match.group(2) or "").lower() == "dr":
            value = -value
        return value
    match = re.search(r"Opening Balance\s+(-?[\d,]+\.\d{2})", text, re.I)
    if match:
        return parse_amount(match.group(1))
    match = re.search(r"\bB/F\s+(-?[\d,]+\.\d{2})(Cr|Dr)?", text, re.I)
    if match:
        value = parse_amount(match.group(1))
        if (match.group(2) or "").lower() == "dr":
            value = -value
        return value
    return None


def extract_grand_totals(text):
    match = re.search(
        r"Grand\s+Total\s*:?\s*([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+(-?[\d,]+\.\d{2})(Cr|Dr)?",
        text,
        re.I,
    )
    if not match:
        return None
    closing = parse_amount(match.group(3))
    if (match.group(4) or "").lower() == "dr" and closing > 0:
        closing = -closing
    return {
        "debits": parse_amount(match.group(1)),
        "credits": parse_amount(match.group(2)),
        "closing_balance": closing,
    }


def build_kotak_transactions(text, pdf_name, bank, st_from, st_to, opening_balance, seq_start):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    txs = []
    current = None
    kotak_date_re = re.compile(r"^\d+\s+(\d{2}\s+[A-Za-z]{3}\s+\d{4})")
    for line in lines:
        if BOILER_RE.search(line):
            continue
        match = kotak_date_re.match(line)
        if match:
            if current:
                txs.append(current)
            current = {"line": line, "date": match.group(1), "continuation": []}
        elif current:
            current["continuation"].append(line)
    if current:
        txs.append(current)

    records = []
    balance = opening_balance
    seq = seq_start
    for tx in txs:
        line = tx["line"]
        amount_matches = list(AMOUNT_RE.finditer(line))
        if len(amount_matches) < 2:
            continue
        closing = parse_amount(amount_matches[-1].group(0))
        printed_amount = parse_amount(amount_matches[-2].group(0))
        if balance is None:
            balance = closing
        delta = closing - balance
        withdrawal = Decimal("0.00")
        deposit = Decimal("0.00")
        if money_close(delta, printed_amount):
            deposit = printed_amount
        elif money_close(delta, -printed_amount):
            withdrawal = printed_amount
        elif printed_amount < 0:
            withdrawal = abs(printed_amount)
        elif delta >= 0:
            deposit = printed_amount
        else:
            withdrawal = printed_amount

        raw_text = " ".join([line] + tx["continuation"])
        date_match = re.search(r"\d{2}\s+[A-Za-z]{3}\s+\d{4}", raw_text)
        cut = date_match.end() if date_match else 0
        narration = raw_text[cut:]
        for m in reversed(amount_matches):
            narration = narration.replace(m.group(0), " ", 1)
        narration = re.sub(r"\s+", " ", narration).strip(" -")
        narration = re.sub(r"^\d+\s+", "", narration)

        seq += 1
        records.append({
            "seq": seq,
            "source_file": pdf_name,
            "statement_from": st_from,
            "statement_to": st_to,
            "date": parse_any_date(tx["date"]),
            "value_date": parse_any_date(tx["date"]),
            "narration": narration[:500],
            "reference": "",
            "direction": "Receipt" if deposit > 0 else "Payment",
            "withdrawal": to_float(withdrawal),
            "deposit": to_float(deposit),
            "amount": to_float(deposit if deposit > 0 else withdrawal),
            "closing_balance": to_float(closing),
            "bank": bank,
        })
        balance = closing
    return records


def build_transactions(text, pdf_name, bank, st_from, st_to, opening_balance, seq_start):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    txs = []
    current = None
    pending = []

    for line in lines:
        if BOILER_RE.search(line):
            continue
        if DATE_START_RE.match(line):
            if current:
                txs.append(current)
            current = {"line": line, "continuation": list(pending)}
            pending = []
        elif current:
            current["continuation"].append(line)
        else:
            # Some statements print narration immediately before the dated numeric row.
            if not any(word in line.upper() for word in ["STATEMENT", "ACCOUNT", "ADDRESS", "BRANCH", "IFSC"]):
                pending = (pending + [line])[-3:]
    if current:
        txs.append(current)

    records = []
    balance = opening_balance
    seq = seq_start
    for tx in txs:
        line = tx["line"]
        date_matches = list(DATE_TOKEN_RE.finditer(line))
        if not date_matches:
            continue
        tx_date = parse_any_date(date_matches[0].group(0))
        value_date = parse_any_date(date_matches[1].group(0)) if len(date_matches) > 1 else tx_date
        amount_matches = list(AMOUNT_RE.finditer(line))
        if len(amount_matches) < 2:
            continue

        closing = parse_balance_from_match(amount_matches[-1], line)
        nums = [parse_amount(m.group(0)) for m in amount_matches]
        debit = Decimal("0.00")
        credit = Decimal("0.00")

        if len(nums) >= 3:
            maybe_debit, maybe_credit = nums[-3], nums[-2]
            if maybe_debit != 0 or maybe_credit != 0:
                debit, credit = maybe_debit, maybe_credit

        if debit == 0 and credit == 0:
            amount = nums[-2]
            delta = None if balance is None else closing - balance
            if delta is not None and money_close(delta, amount):
                credit = amount
            elif delta is not None and money_close(delta, -amount):
                debit = amount
            else:
                upper = " ".join([line] + tx["continuation"]).upper()
                credit_words = ["CR", "REC", "RECEIPT", "DEPOSIT", "BY CASH", "CASH RECEIPT", "NEFT/", "UPI/CR"]
                debit_words = ["DR", "PAY", "WDL", "WITHDRAW", "CHARG", "GST", "POS", "DEBIT", "FT - DR"]
                if any(w in upper for w in credit_words) and not any(w in upper for w in [" DR", "/DR/", "FT - DR"]):
                    credit = amount
                elif any(w in upper for w in debit_words):
                    debit = amount
                else:
                    credit = amount

        raw_text = " ".join([line] + tx["continuation"])
        cut = date_matches[-1].end() if date_matches else 0
        narration = raw_text[cut:]
        for m in reversed(amount_matches):
            narration = narration.replace(m.group(0), " ", 1)
        narration = re.sub(r"\b(?:Dr|Cr)\b", " ", narration, flags=re.I)
        narration = re.sub(r"\s+", " ", narration).strip(" -")
        if not narration:
            narration = re.sub(r"\s+", " ", raw_text).strip()

        seq += 1
        records.append(
            {
                "seq": seq,
                "source_file": pdf_name,
                "statement_from": st_from,
                "statement_to": st_to,
                "date": tx_date,
                "value_date": value_date,
                "narration": narration[:500],
                "reference": "",
                "direction": "Receipt" if credit > 0 else "Payment",
                "withdrawal": to_float(debit),
                "deposit": to_float(credit),
                "amount": to_float(credit if credit > 0 else debit),
                "closing_balance": to_float(closing),
                "bank": bank,
            }
        )
        balance = closing
    return records


FD_INTEREST_RE = re.compile(r"\b(?:INT|INTEREST)\b", re.I)
FD_RE = re.compile(
    r"\b(?:"
    r"F\.?\s*D\.?|FDR|FIXED\s*DEPOSIT|TERM\s*DEPOSIT|TDR|"
    r"FD\s*(?:NO|A/C|AC|ACCOUNT|OPEN|CLOS(?:E|URE|ING)?|MATUR(?:ITY|ED)?|"
    r"RENEW(?:AL|ED)?|BOOK(?:ING|ED)?|DEP(?:OSIT)?|INT(?:EREST)?|RECEIPT|LIEN)"
    r")\b",
    re.I,
)
MUTUAL_FUND_RE = re.compile(r"\b(?:MUTUAL\s+FUND|MF|SIP|REDEMPTION|CAP\s+FUND)\b", re.I)
LIC_RE = re.compile(r"\b(?:LIC|LIFE\s+INSURANCE)\b", re.I)
PF_RE = re.compile(
    r"\b(?:"
    r"PUBLIC\s+PROVIDENT\s+FUND|PROVIDENT\s+FUND|EPF|"
    r"PPF\s*(?:A/C|AC|ACCOUNT|CONTRIBUTION|DEPOSIT|INTEREST|INT|SUBSCRIPTION|"
    r"TRANSFER|MATURITY|WITHDRAWAL|LOAN)|"
    r"PF\s*(?:CONTRIBUTION|INTEREST|TRANSFER|CLAIM|WITHDRAWAL|SETTLEMENT|"
    r"EMPLOYEE|EMPLOYER)"
    r")\b",
    re.I,
)
SALARY_RE = re.compile(r"\b(?:SALARY|PAYROLL)\b", re.I)


def classify(records):
    def has_salary_marker(record):
        return bool(SALARY_RE.search(record["narration"]))

    def has_split_salary_context(index):
        record = records[index]
        if record["direction"] != "Receipt" or record["amount"] < 10000:
            return False
        for neighbor_index in (index - 1, index + 1):
            if neighbor_index < 0 or neighbor_index >= len(records):
                continue
            neighbor = records[neighbor_index]
            if (
                neighbor.get("date") == record.get("date")
                and neighbor.get("direction") == "Payment"
                and neighbor.get("amount", 0) <= 1000
                and has_salary_marker(neighbor)
            ):
                return True
        return False

    for index, record in enumerate(records):
        narration = record["narration"]
        compact = re.sub(r"\s+", "", narration.upper())
        amount_abs = abs(record["amount"])
        categories = []
        if any(k in compact for k in ["CASHDEPOSIT", "CASHRECEIPT", "BYCASH", "CASHDEP", "CASH"]):
            categories.append("Cash")
        if "UPI" in compact:
            categories.append("UPI")
        if "IMPS" in compact:
            categories.append("IMPS")
        if LIC_RE.search(narration):
            categories.append("LIC")
        if record["direction"] == "Payment" and any(k in compact for k in ["EMI", "ECS", "ACHDR", "NACH", "LOAN", "INSTALMENT", "INSTALLMENT"]):
            categories.append("EMI")
        if record["direction"] == "Receipt" and (has_salary_marker(record) or has_split_salary_context(index)):
            categories.append("Salary")
        is_mutual_fund = bool(MUTUAL_FUND_RE.search(narration))
        is_fd = bool(FD_RE.search(narration)) and not is_mutual_fund
        if is_fd and FD_INTEREST_RE.search(narration):
            categories.append("FD interest")
        elif is_fd:
            categories.append("FD Deposit/Withdrawal")
        if is_mutual_fund:
            categories.append("Mutual Fund / Investment")
        if PF_RE.search(narration):
            categories.append("PPF/PF interest/contribution")
        if amount_abs >= 100000:
            categories.append("High Transaction")
        record["categories"] = "; ".join(dict.fromkeys(categories)) if categories else "Other"

    def recurring_key(narration):
        upper = narration.upper()
        for token in re.split(r"[/|-]", upper):
            token = re.sub(r"[^A-Z ]", "", token).strip()
            if len(token) >= 8 and token not in {"PAYMENT", "TRANSFER", "CHARGES"}:
                return token[:40]
        upper = re.sub(r"\d+", "#", upper)
        upper = re.sub(r"\s+", " ", upper).strip()
        return upper[:50]

    counts = Counter(f"{recurring_key(r['narration'])}|{r['direction']}" for r in records)
    for record in records:
        key = f"{recurring_key(record['narration'])}|{record['direction']}"
        record["recurring_key"] = key.split("|", 1)[0]
        record["is_recurring"] = "Yes" if counts[key] >= 2 else "No"
        if record["is_recurring"] == "Yes" and "Recurring Transaction" not in record["categories"]:
            record["categories"] = (
                f"{record['categories']}; Recurring Transaction"
                if record["categories"] != "Other"
                else "Recurring Transaction"
            )


def process_single_pdf(pdf_path, manual_passwords):
    try:
        text, pages, password = read_pdf_text(pdf_path, manual_passwords)
        bank = detect_bank(text, pdf_path.name)
        st_from, st_to = find_period(text)
        opening = extract_opening_balance(text)
        grand_totals = extract_grand_totals(text)
        
        issues = []
        if bank == "HDFC Bank":
            file_records = build_hdfc_transactions(text, pdf_path.name, bank, st_from, st_to, opening, 0, issues)
        elif bank == "Kotak Mahindra Bank":
            file_records = build_kotak_transactions(text, pdf_path.name, bank, st_from, st_to, opening, 0)
        else:
            file_records = build_transactions(text, pdf_path.name, bank, st_from, st_to, opening, 0)
            
        if not file_records:
            return {"success": False, "file": pdf_path.name, "issue": "no transactions parsed", "bank": bank}
            
        parsed_debits = round(sum(r["withdrawal"] for r in file_records), 2)
        parsed_credits = round(sum(r["deposit"] for r in file_records), 2)
        acc_name, acc_no = extract_account_details(text)
        
        statement = {
            "file": pdf_path.name,
            "pages": pages,
            "from": st_from or min(r["date"] for r in file_records),
            "to": st_to or max(r["date"] for r in file_records),
            "opening_balance": to_float(opening) if opening is not None else 0,
            "dr_count": sum(1 for r in file_records if r["withdrawal"] != 0),
            "cr_count": sum(1 for r in file_records if r["deposit"] != 0),
            "debits": to_float(grand_totals["debits"]) if grand_totals else parsed_debits,
            "credits": to_float(grand_totals["credits"]) if grand_totals else parsed_credits,
            "closing_balance": to_float(grand_totals["closing_balance"]) if grand_totals else file_records[-1]["closing_balance"],
            "bank": bank,
            "password_used": bool(password),
            "account_name": acc_name,
            "account_no": acc_no,
        }
        return {"success": True, "file": pdf_path.name, "records": file_records, "statement": statement, "issues": issues}
    except Exception as exc:
        return {"success": False, "file": pdf_path.name, "issue": f"could not read/parse PDF: {type(exc).__name__}"}

def extract(input_dir, work_dir, manual_passwords=None):
    pdfs = sorted(pathlib.Path(input_dir).glob("*.pdf"))
    if not pdfs:
        raise ValueError("No PDF files were uploaded.")

    records = []
    statements = []
    issues = []

    # Process PDFs in parallel to massively speed up multi-file extraction
    with concurrent.futures.ProcessPoolExecutor() as executor:
        futures = {executor.submit(process_single_pdf, pdf_path, manual_passwords): pdf_path for pdf_path in pdfs}
        
        # We need to maintain sequential order based on filenames for predictable sequence IDs later
        results_by_file = {}
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            pdf_path = futures[future]
            results_by_file[pdf_path.name] = future.result()
            print(json.dumps({"type": "progress", "message": f"Extracting data from PDFs...", "pdf_progress": {"current": i, "total": len(pdfs)}}), flush=True)
            
    seq = 0
    for pdf_path in pdfs:
        res = results_by_file[pdf_path.name]
        if not res["success"]:
            issues.append({"file": res["file"], "issue": res["issue"], "bank": res.get("bank", "Unknown")})
            continue
            
        file_records = res["records"]
        # Update sequence numbers sequentially to maintain order
        for r in file_records:
            seq += 1
            r["seq"] = seq
            
        statements.append(res["statement"])
        records.extend(file_records)
        issues.extend(res.get("issues", []))

    classify(records)
    records.sort(key=lambda row: (row["date"], row["seq"]))

    work_path = pathlib.Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "seq",
        "source_file",
        "statement_from",
        "statement_to",
        "date",
        "value_date",
        "narration",
        "reference",
        "direction",
        "withdrawal",
        "deposit",
        "amount",
        "closing_balance",
        "categories",
        "is_recurring",
        "recurring_key",
    ]
    with (work_path / "transactions.csv").open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    (work_path / "statements.json").write_text(json.dumps(statements, indent=2), encoding="utf-8")
    (work_path / "issues.json").write_text(json.dumps(issues, indent=2), encoding="utf-8")

    job_acc_name = ""
    job_acc_no = ""
    for s in statements:
        if s.get("account_name"):
            job_acc_name = slugify_name(s["account_name"])
            break
    for s in statements:
        if s.get("account_no"):
            job_acc_no = s["account_no"]
            break
    
    if not job_acc_name:
        job_acc_name = "UNKNOWN_HOLDER"
    if not job_acc_no:
        job_acc_no = "0000"
        
    job_last4 = job_acc_no[-4:] if len(job_acc_no) >= 4 else job_acc_no
    
    valid_froms = [s["from"] for s in statements if s["from"]]
    valid_tos = [s["to"] for s in statements if s["to"]]
    
    min_from = min(valid_froms) if valid_froms else "YYYY_MM"
    max_to = max(valid_tos) if valid_tos else "YYYY_MM"
    
    start_period = format_period_slug(min_from)
    end_period = format_period_slug(max_to)
    
    dynamic_filename = f"Analysis_{job_acc_name}_{job_last4}_{start_period}_to_{end_period}.xlsx"

    return {
        "pdfs": len(pdfs),
        "statements": len(statements),
        "transactions": len(records),
        "issues": issues,
        "banks": sorted(set(s["bank"] for s in statements)),
        "password_protected_statements": sum(1 for s in statements if s.get("password_used")),
        "total_payments": round(sum(r["withdrawal"] for r in records), 2),
        "total_receipts": round(sum(r["deposit"] for r in records), 2),
        "account_name": job_acc_name,
        "account_no_last4": job_last4,
        "start_period": start_period,
        "end_period": end_period,
        "dynamic_filename": dynamic_filename,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument(
        "--password",
        action="append",
        default=[],
        help="Optional statement password. Can be supplied more than once.",
    )
    args = parser.parse_args()
    summary = extract(args.input_dir, args.work_dir, args.password)
    pathlib.Path(args.summary_json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if summary["issues"]:
        print(json.dumps(summary, indent=2))
    else:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
