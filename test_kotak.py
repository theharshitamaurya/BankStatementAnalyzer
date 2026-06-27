import sys
sys.path.append('d:/Bank Statement Analyzer/app')
import extract_bank

mock_text = """Account Statement
01 Apr 2025 - 31 Mar 2026
Rohit Nitin Patil
CRN xxxxxx237
Room No 01 Govade Post
Dhuktan Palghar
Dhuktan
Thane - 401404
Maharashtra - India
MICR 400485028 IFSC Code KKBK0000672
Account No. 3048939684
Account Type Savings
Branch Tarapur
Branch Phone Number 9890787321
Account Status Active
Nominee Registered Yes
Currency INDIAN RUPEE
Savings Account Transactions
# Date Description Chq/Ref. No. Withdrawal (Dr.) Deposit (Cr.) Balance
- - Opening Balance - - - 6,381.00
1 11 Apr 2025 Chrg: ECS Mandate- 57525151 04-Mar-2025 TBMS-1674995698 59.00 6,322.00
2 30 Jun 2025 Int.Pd:3048939684:01-04-2025 to 30-06-2025 44.00 6,366.00
3 30 Sep 2025 Int.Pd:3048939684:01-07-2025 to 30-09-2025 40.00 6,406.00
4 30 Dec 2025 FUNDS TRANSFER FROM MANJULA VASUDEV
PATIL
BRB-0672301225397203
10,00,000.00 10,06,406.00
5 31 Dec 2025 CASH WITHDRAWAL BY SELF AT PALGHAR-MANOR ROAD 1 2,00,000.00 8,06,406.00
6 31 Dec 2025 Int.Pd:3048939684:01-10-2025 to 31-12-2025 164.00 8,06,570.00
7 13 Jan 2026 CASH WITHDRAWAL BY SELF AT PALGHAR-MANOR ROAD 2 2,00,000.00 6,06,570.00
8 27 Jan 2026 CLG TO YOGESH SHAMRAO KUDU HDFC BANK LTD. 4/NCRCTS_2701202669857 2,00,000.00 4,06,570.00
9 27 Jan 2026 BRB:Sent RTGS KKBKR52026012700933559/PRAFUL NARES 6/000509468556 2,00,000.00 2,06,570.00
10 29 Jan 2026 3:MICR INWARD 12:CLG TO MR AKSHAY NARESH PATIL BA 2,00,000.00 6,570.00
11 29 Jan 2026 I/W CHQ RTN:3:DRAWERS SIGNATURE DIFFER 2,00,000.00 2,06,570.00
12 02 Feb 2026 CASH WITHDRAWAL BY SELF AT PALGHAR-MANOR ROAD 7 2,00,000.00 6,570.00
13 13 Feb 2026 CHRG: RTGS ON 27-JAN-2026 23.60 6,546.40
14 13 Feb 2026 CHRG: CHQ ISSUE AND RETURN ON 29-JAN-2026 59.00 6,487.40
15 27 Feb 2026 KOTAK LIFE POLICY NO 78867491 PAYOUT FCM-260227LHIXNA 30,400.00 36,887.40
16 04 Mar 2026 Chrg: ECS Return on 20260304 Kotak Life Insurance 590.00 36,297.40
17 12 Mar 2026 UPI/ROHIT NITIN PAT/117772126558/Payment from Ph UPI-607158136938 20,000.00 56,297.40
18 13 Mar 2026 UPI/ROHIT NITIN PAT/194341459354/Payment from Ph UPI-607230335718 45,000.00 1,01,297.40
19 16 Mar 2026 DIRECT DEBIT-DR-KOTAK LIFE INSURANCE-78867491 NACHDD16032600377360 99,170.00 2,127.40
20 23 Mar 2026 UPI/ROHIT NITIN PAT/314296257332/Payment from Ph UPI-608271972439 2,000.00 127.40
21 26 Mar 2026 CHRG: DEBIT CARD ISSUANCE FEE X8913 FOR 2026 127.40 0.00
22 31 Mar 2026 Int.Pd:3048939684:01-01-2026 to 31-03-2026 1,399.00 1,399.00
"""

filename = "Kotak_Statement.pdf"
bank = extract_bank.detect_bank(mock_text, filename)
print(f"Bank detected: {bank}")

acc_name, acc_no = extract_bank.extract_account_details(mock_text)
print(f"Account Name: {acc_name}")
print(f"Account No: {acc_no}")

st_from, st_to = extract_bank.find_period(mock_text)
print(f"Period: {st_from} to {st_to}")

opening = extract_bank.extract_opening_balance(mock_text)
print(f"Opening Balance: {opening}")

records = extract_bank.build_kotak_transactions(mock_text, filename, bank, st_from, st_to, opening, 0)
for r in records[:3]:
    print(r)
print(f"Parsed {len(records)} transactions")
