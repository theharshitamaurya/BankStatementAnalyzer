import argparse
import csv
import datetime as dt
import json
import pathlib
import re
from collections import Counter
from decimal import Decimal

import pdfplumber


NUM_RE = re.compile(r"(?<!\w)-?\d{1,3}(?:,\d{3})*\.\d{2}")
DATE_START_RE = re.compile(r"^(\d{2}/\d{2}/\d{2})\s+(.*)$")
VALUE_DATE_RE = re.compile(r"\b\d{2}/\d{2}/\d{2}\b")
BOILER_RE = re.compile(
    r"\b(HDFC BANK LIMITED|\*Closing balance includes|Contents of this statement|"
    r"Page No\s*\.?:|Account Branch\s*:|Registered Office Address:|"
    r"State account branch GSTN:|HDFC Bank GSTIN|https://www\.hdfcbank\.com|Generated On:)\b",
    re.I,
)


def amount(value):
    return Decimal(value.replace(",", ""))


def as_float(value):
    return float(value)


def parse_date(value):
    return dt.datetime.strptime(value, "%d/%m/%y").date().isoformat()


def parse_period_date(value):
    return dt.datetime.strptime(value, "%d/%m/%Y").date().isoformat()


def clean_continuation(lines):
    keep = []
    for line in lines:
        if BOILER_RE.search(line):
            break
        keep.append(line)
    return " ".join(keep).strip()


def normalize_key(narration):
    upper = narration.upper()
    for key in [
        "NAMDAR CORNER",
        "SHOAIB",
        "SHOIAB",
        "SHAOIB",
        "KVBL",
        "SBIN",
        "SURAJ TRADING",
        "HB TRADERS",
        "SHREE SAINATH",
        "CASH DEPOSIT",
    ]:
        if key in upper:
            return key.replace(" ", "")
    upper = re.sub(r"\d+", "#", upper)
    upper = re.sub(r"X+", "X", upper)
    upper = re.sub(r"\s+", " ", upper).strip()
    return upper[:60]


def classify(records):
    high_threshold = 100000.0
    for record in records:
        compact = re.sub(r"\s+", "", record["narration"].upper())
        amount_abs = abs(record["amount"])
        categories = []

        if "CASHDEPOSITBY" in compact:
            categories.append("Cash")
        if "UPI" in compact:
            categories.append("UPI")
        if "LIC" in compact:
            categories.append("LIC")
        if any(k in compact for k in ["EMI", "ECS", "ACHDR", "LOAN", "INSTALMENT", "INSTALLMENT"]):
            categories.append("EMI")
        if "SALARY" in compact:
            categories.append("Salary")
        if any(k in compact for k in ["FD", "FIXEDDEPOSIT", "TDR", "TERMDEPOSIT"]) and any(
            k in compact for k in ["INT", "INTEREST"]
        ):
            categories.append("FD interest")
        elif any(k in compact for k in ["FD", "FIXEDDEPOSIT", "TDR", "TERMDEPOSIT"]):
            categories.append("FD Deposit/Withdrawal")
        if any(k in compact for k in ["PPF", "EPF", "PROVIDENTFUND"]) or re.search(r"(?<!U)PF", compact):
            categories.append("PPF/PF interest/contribution")
        if amount_abs >= high_threshold:
            categories.append("High Transaction")

        record["categories"] = "; ".join(categories) if categories else "Other"

    counts = Counter(f"{normalize_key(r['narration'])}|{r['direction']}" for r in records)
    for record in records:
        key = f"{normalize_key(record['narration'])}|{record['direction']}"
        record["recurring_key"] = key.split("|", 1)[0]
        record["is_recurring"] = "Yes" if counts[key] >= 2 else "No"
        if record["is_recurring"] == "Yes" and "Recurring Transaction" not in record["categories"]:
            record["categories"] = (
                f"{record['categories']}; Recurring Transaction"
                if record["categories"] != "Other"
                else "Recurring Transaction"
            )


def extract(input_dir, work_dir):
    pdfs = sorted(pathlib.Path(input_dir).glob("*.pdf"))
    if not pdfs:
        raise ValueError("No PDF files were uploaded.")

    records = []
    statements = []
    issues = []
    seq = 0

    for pdf_path in pdfs:
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join(page.extract_text(x_tolerance=1, y_tolerance=3) or "" for page in pdf.pages)
            pages = len(pdf.pages)

        compact_text = re.sub(r"\s+", " ", text)
        period = re.search(r"From\s*:\s*(\d{2}/\d{2}/\d{4})\s+To\s*:\s*(\d{2}/\d{2}/\d{4})", text)
        summary = re.search(
            r"STATEMENT\s*SUMMARY\s*:-\s*\n\s*Opening\s*Balance\s+Dr\s*Count\s+Cr\s*Count\s+Debits\s+Credits\s+Closing\s*Bal\s*\n([^\n]+)",
            text,
            re.I | re.S,
        )
        if summary:
            parts = summary.group(1).split()
        else:
            summary_line = re.search(
                r"Opening\s*Balance\s+Dr\s*Count\s+Cr\s*Count\s+Debits\s+Credits\s+Closing\s*Bal\s+([\d,.]+\s+\d+\s+\d+\s+[\d,.]+\s+[\d,.]+\s+[\d,.]+)",
                compact_text,
                re.I,
            )
            if not summary_line:
                issues.append({"file": pdf_path.name, "issue": "summary not found"})
                continue
            parts = summary_line.group(1).split()

        open_bal = amount(parts[0])
        dr_count = int(parts[1])
        cr_count = int(parts[2])
        debits = amount(parts[3])
        credits = amount(parts[4])
        close_bal = amount(parts[5])
        st_from = parse_period_date(period.group(1)) if period else ""
        st_to = parse_period_date(period.group(2)) if period else ""

        statements.append(
            {
                "file": pdf_path.name,
                "pages": pages,
                "from": st_from,
                "to": st_to,
                "opening_balance": as_float(open_bal),
                "dr_count": dr_count,
                "cr_count": cr_count,
                "debits": as_float(debits),
                "credits": as_float(credits),
                "closing_balance": as_float(close_bal),
            }
        )

        start = text.find("Date Narration")
        end_match = re.search(r"STATEMENT\s*SUMMARY\s*:-", text, re.I)
        end = end_match.start() if end_match else len(text)
        block = text[start:end] if start != -1 else text[:end]

        txs = []
        current = None
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("Date Narration"):
                continue
            match = DATE_START_RE.match(line)
            if match:
                if current:
                    txs.append(current)
                current = {"start_line": line, "date": match.group(1), "cont": []}
            elif current:
                current["cont"].append(line)
        if current:
            txs.append(current)

        balance = open_bal
        file_records = []
        for tx in txs:
            seq += 1
            line = tx["start_line"]
            all_dates = list(VALUE_DATE_RE.finditer(line))
            if len(all_dates) < 2:
                issues.append({"file": pdf_path.name, "issue": "could not find value date", "line": line})
                continue

            value_date = all_dates[-1].group(0)
            amounts = NUM_RE.findall(line[all_dates[-1].end() :].strip())
            if len(amounts) < 2:
                issues.append({"file": pdf_path.name, "issue": "could not find amounts", "line": line})
                continue

            printed_amount = amount(amounts[-2])
            closing = amount(amounts[-1])
            delta = closing - balance
            if printed_amount < 0:
                withdrawal = printed_amount
                deposit = Decimal("0.00")
            elif delta >= 0:
                deposit = printed_amount
                withdrawal = Decimal("0.00")
            else:
                withdrawal = printed_amount
                deposit = Decimal("0.00")

            rest = line[len(tx["date"]) : all_dates[-1].start()].strip()
            narration = rest
            reference = ""
            ref_match = re.match(r"(.+?)\s+([A-Z0-9]{10,}|\d{12,}|CDT\d{10,})$", rest)
            if ref_match:
                narration = ref_match.group(1).strip()
                reference = ref_match.group(2).strip()

            full_narration = re.sub(
                r"\s+",
                " ",
                f"{narration} {clean_continuation(tx['cont'])}".strip(),
            )
            record = {
                "seq": seq,
                "source_file": pdf_path.name,
                "statement_from": st_from,
                "statement_to": st_to,
                "date": parse_date(tx["date"]),
                "value_date": parse_date(value_date),
                "narration": full_narration,
                "reference": reference,
                "direction": "Receipt" if deposit > 0 else "Payment",
                "withdrawal": as_float(withdrawal),
                "deposit": as_float(deposit),
                "amount": as_float(deposit if deposit > 0 else withdrawal),
                "closing_balance": as_float(closing),
            }
            file_records.append(record)
            balance = closing

        parsed_debits = sum(Decimal(str(r["withdrawal"])) for r in file_records)
        parsed_credits = sum(Decimal(str(r["deposit"])) for r in file_records)
        if (
            abs(parsed_debits - debits) > Decimal("0.02")
            or abs(parsed_credits - credits) > Decimal("0.02")
            or abs(balance - close_bal) > Decimal("0.02")
        ):
            issues.append(
                {
                    "file": pdf_path.name,
                    "issue": "reconcile mismatch",
                    "calc_debits": str(parsed_debits),
                    "summary_debits": str(debits),
                    "calc_credits": str(parsed_credits),
                    "summary_credits": str(credits),
                    "calc_close": str(balance),
                    "summary_close": str(close_bal),
                    "tx_count": len(file_records),
                }
            )
        records.extend(file_records)

    classify(records)
    records.sort(key=lambda row: row["seq"])
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
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    (work_path / "statements.json").write_text(json.dumps(statements, indent=2), encoding="utf-8")
    (work_path / "issues.json").write_text(json.dumps(issues, indent=2), encoding="utf-8")

    return {
        "pdfs": len(pdfs),
        "statements": len(statements),
        "transactions": len(records),
        "issues": issues,
        "total_payments": round(sum(r["withdrawal"] for r in records), 2),
        "total_receipts": round(sum(r["deposit"] for r in records), 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--summary-json", required=True)
    args = parser.parse_args()
    summary = extract(args.input_dir, args.work_dir)
    pathlib.Path(args.summary_json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if summary["issues"]:
        raise SystemExit(2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
