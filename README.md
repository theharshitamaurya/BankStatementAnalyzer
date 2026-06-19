# Bank Statement Analyzer

Local web app for converting bank statement PDFs into an Excel analysis workbook.

## What It Does

- Upload one or more bank statement PDFs from the browser.
- Supports many Indian bank statement layouts, including HDFC, Axis, IDFC First, IDBI, ICICI, DCB, Bank of Baroda, Bank of Maharashtra, Union Bank, Federal/Kotak-style layouts, and cooperative-bank layouts present in the sample data.
- Automatically reads statement passwords when the password is included in the filename, such as `PSW-76681350` or `PW-AMBI909233582`.
- Generates an Excel workbook with:
  - Total receipts and payments
  - Cash
  - Recurring transactions
  - EMI
  - Salary
  - High transactions
  - UPI
  - LIC
  - FD interest
  - FD deposits and withdrawals
  - PPF/PF interest and contribution
  - Monthly summary
  - Transaction detail
  - Checks and source sheets

## How To Run

1. Open a terminal in this folder:

   `D:\Bank Statement Analyzer`

2. Start the dev server:

   `npm run dev`

   If you are using PowerShell and `npm run dev` is blocked by script execution policy, use:

   `npm.cmd run dev`

   Or start it and open the browser automatically:

   `npm run dev:open`

   PowerShell-safe version:

   `npm.cmd run dev:open`

3. Open:

   `http://127.0.0.1:8765/`

4. Drop/select PDF bank statements.

5. Click **Generate Excel**.

6. Download the generated workbook.

## Project Structure

- `package.json` - npm scripts for running the local app
- `app\dev-server.mjs` - npm dev-server wrapper
- `app\server.py` - local backend server
- `app\extract_bank.py` - PDF extraction and bank parsing logic
- `app\build_hdfc_workbook.mjs` - Excel workbook generator
- `app\public\index.html` - frontend page
- `app\public\styles.css` - frontend styling
- `app\public\app.js` - browser upload and download logic
- `outputs\` - generated Excel files

## Notes

- This is a BETA app. Your PDFs are processed on your own computer.
- Keep the Codex runtime installed at:

  `C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime`

  The npm dev server uses that bundled Python runtime automatically.

- If port `8765` is already busy, stop the old server process and run `npm run dev` again.
- `start_bank_statement_analyzer.bat` is still available as a legacy shortcut, but the recommended command is now `npm run dev`.
# BankStatementAnalyzer
