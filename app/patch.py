import sys
content = open('extract_bank.py').read()

IDBI_FUNC_OLD = '''def build_idbi_transactions(text, pdf_name, bank, st_from, st_to, opening_balance, seq_start):
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
            if not any(word in line.upper() for word in ["STATEMENT", "ACCOUNT", "ADDRESS", "BRANCH", "IFSC"]):
                pending = (pending + [line])[-3:]
    if current:
        txs.append(current)

    records = []
    balance = opening_balance
    seq = seq_start

    for tx in txs:
        raw_text = " ".join([tx["line"]] + tx["continuation"])
        
        date_matches = list(DATE_TOKEN_RE.finditer(tx["line"]))
        if not date_matches:
            continue
        tx_date = parse_any_date(date_matches[0].group(0))
        value_date = parse_any_date(date_matches[1].group(0)) if len(date_matches) > 1 else tx_date
        
        amount_matches = list(AMOUNT_RE.finditer(raw_text))
        if len(amount_matches) < 2:
            continue
            
        closing = parse_amount(amount_matches[-1].group(0))
        amount = parse_amount(amount_matches[-2].group(0))
        
        debit = Decimal("0.00")
        credit = Decimal("0.00")
        
        upper = raw_text.upper()
        credit_words = ["CR", "REC", "RECEIPT", "DEPOSIT", "BY CASH", "CASH RECEIPT", "NEFT/", "UPI/CR"]
        debit_words = ["DR", "PAY", "WDL", "WITHDRAW", "CHARG", "GST", "POS", "DEBIT", "FT - DR"]
        
        if any(w in upper for w in credit_words) and not any(w in upper for w in [" DR", "/DR/", "FT - DR"]):
            credit = amount
        elif any(w in upper for w in debit_words):
            debit = amount
        else:
            credit = amount
            
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
                "withdrawal": to_float(debit),
                "deposit": to_float(credit),
                "amount": to_float(credit if credit > 0 else debit),
                "closing_balance": to_float(closing),
                "bank": bank,
            }
        )
        
    if len(records) > 1 and records[0]["date"] > records[-1]["date"]:
        records.reverse()
        
    for i in range(len(records)):
        r = records[i]
        prev_bal = balance if i == 0 else Decimal(str(records[i-1]["closing_balance"]))
        closing = Decimal(str(r["closing_balance"]))
        amount = Decimal(str(r["amount"]))
        if prev_bal is not None:
            delta = closing - prev_bal
            if money_close(delta, amount):
                r["deposit"] = float(amount)
                r["withdrawal"] = 0.0
            elif money_close(delta, -amount):
                r["withdrawal"] = float(amount)
                r["deposit"] = 0.0
            elif amount < 0:
                r["withdrawal"] = float(abs(amount))
                r["deposit"] = 0.0
                r["amount"] = float(abs(amount))
            elif delta >= 0:
                r["deposit"] = float(amount)
                r["withdrawal"] = 0.0
            else:
                r["withdrawal"] = float(amount)
                r["deposit"] = 0.0
        r["direction"] = "Receipt" if r["deposit"] > 0 else "Payment"
        balance = closing
        
    return records'''

IDBI_FUNC_NEW = '''def build_idbi_transactions(text, pdf_name, bank, st_from, st_to, opening_balance, seq_start):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    txs = []
    current = None

    for line in lines:
        if BOILER_RE.search(line):
            continue
        if DATE_START_RE.match(line):
            if current:
                txs.append(current)
            current = {"line": line, "continuation": []}
        elif current:
            current["continuation"].append(line)
    if current:
        txs.append(current)

    records = []
    balance = opening_balance
    seq = seq_start

    for tx in txs:
        raw_text = " ".join([tx["line"]] + tx["continuation"])
        
        date_matches = list(DATE_TOKEN_RE.finditer(tx["line"]))
        if not date_matches:
            continue
        tx_date = parse_any_date(date_matches[0].group(0))
        value_date = parse_any_date(date_matches[1].group(0)) if len(date_matches) > 1 else tx_date
        
        amount_matches = list(AMOUNT_RE.finditer(raw_text))
        if len(amount_matches) < 2:
            continue
            
        closing = parse_amount(amount_matches[-1].group(0))
        amount = parse_amount(amount_matches[-2].group(0))
        
        debit = Decimal("0.00")
        credit = Decimal("0.00")
        
        upper = raw_text.upper()
        credit_words = ["CR", "REC", "RECEIPT", "DEPOSIT", "BY CASH", "CASH RECEIPT", "NEFT/", "UPI/CR"]
        debit_words = ["DR", "PAY", "WDL", "WITHDRAW", "CHARG", "GST", "POS", "DEBIT", "FT - DR"]
        
        if any(w in upper for w in credit_words) and not any(w in upper for w in [" DR", "/DR/", "FT - DR"]):
            credit = amount
        elif any(w in upper for w in debit_words):
            debit = amount
        else:
            credit = amount
            
        cut = date_matches[1].end() if len(date_matches) > 1 else date_matches[0].end()
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
                "withdrawal": to_float(debit),
                "deposit": to_float(credit),
                "amount": to_float(credit if credit > 0 else debit),
                "closing_balance": to_float(closing),
                "bank": bank,
            }
        )
        
    if len(records) > 1 and records[0]["date"] > records[-1]["date"]:
        records.reverse()
        
    for i in range(len(records)):
        r = records[i]
        prev_bal = balance if i == 0 else Decimal(str(records[i-1]["closing_balance"]))
        closing = Decimal(str(r["closing_balance"]))
        amount = Decimal(str(r["amount"]))
        if prev_bal is not None:
            delta = closing - prev_bal
            if money_close(delta, amount):
                r["deposit"] = float(amount)
                r["withdrawal"] = 0.0
            elif money_close(delta, -amount):
                r["withdrawal"] = float(amount)
                r["deposit"] = 0.0
            elif amount < 0:
                r["withdrawal"] = float(abs(amount))
                r["deposit"] = 0.0
                r["amount"] = float(abs(amount))
            elif delta >= 0:
                r["deposit"] = float(amount)
                r["withdrawal"] = 0.0
            else:
                r["withdrawal"] = float(amount)
                r["deposit"] = 0.0
        r["direction"] = "Receipt" if r["deposit"] > 0 else "Payment"
        balance = closing
        
    return records'''

if IDBI_FUNC_OLD in content:
    content = content.replace(IDBI_FUNC_OLD, IDBI_FUNC_NEW)
    with open('extract_bank.py', 'w') as f:
        f.write(content)
    print('Patched successfully')
else:
    print('Failed to find IDBI_FUNC_OLD')
