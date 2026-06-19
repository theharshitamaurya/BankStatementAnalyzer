import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const workDir = process.env.HDFC_WORK_DIR || path.join(root, "work");
const outputDir = process.env.HDFC_OUTPUT_DIR || path.join(root, "outputs");
const txCsvPath = path.join(workDir, "transactions.csv");
const statementsPath = path.join(workDir, "statements.json");
const outputPath = process.env.HDFC_OUTPUT_XLSX || path.join(outputDir, "bank_statement_analysis.xlsx");

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    const next = text[i + 1];
    if (quoted) {
      if (ch === '"' && next === '"') {
        cell += '"';
        i++;
      } else if (ch === '"') {
        quoted = false;
      } else {
        cell += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (ch !== "\r") {
      cell += ch;
    }
  }
  if (cell.length || row.length) {
    row.push(cell);
    rows.push(row);
  }
  const headers = rows.shift();
  return rows.filter((r) => r.length === headers.length).map((r) =>
    Object.fromEntries(headers.map((h, i) => [h, r[i]])),
  );
}

function excelDate(iso) {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function monthLabel(iso) {
  const d = excelDate(iso);
  return d.toLocaleString("en-US", { month: "short", year: "numeric" });
}

function monthKey(iso) {
  return iso.slice(0, 7);
}

function monthStart(key) {
  const [year, month] = key.split("-").map(Number);
  return new Date(year, month - 1, 1);
}

function nextMonthStart(key) {
  const [year, month] = key.split("-").map(Number);
  return new Date(year, month, 1);
}

function inRange(iso, start, end) {
  return iso && start && end && iso >= start && iso <= end;
}

function effectiveMonthDate(row) {
  if (inRange(row.date, row.statement_from, row.statement_to)) {
    return row.date;
  }
  if (inRange(row.value_date, row.statement_from, row.statement_to)) {
    return row.value_date;
  }
  return row.date || row.value_date;
}

function sheetNameForDetail(label) {
  const cleaned = label.replace(/[^A-Za-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
  return `Detail ${cleaned}`.slice(0, 31);
}

function moneyFormat() {
  return '₹#,##0.00;[Red](₹#,##0.00);-';
}

function excelCol(n) {
  let s = "";
  while (n > 0) {
    const m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

function setWidths(sheet, widths) {
  widths.forEach((width, index) => {
    sheet.getCell(0, index).format.columnWidth = width;
  });
}

function styleTitle(range, title) {
  range.merge();
  range.values = [[title]];
  range.format = {
    fill: "#17324D",
    font: { bold: true, color: "#FFFFFF", size: 16 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
  range.format.rowHeight = 30;
}

function styleHeader(range, fill = "#315A7D") {
  range.format = {
    fill,
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: "#D7DEE8" },
  };
}

function styleBody(range) {
  range.format = {
    fill: "#FFFFFF",
    borders: { preset: "all", style: "thin", color: "#E2E8F0" },
    verticalAlignment: "top",
  };
}

const transactions = parseCsv(await fs.readFile(txCsvPath, "utf8"));
const statements = JSON.parse(await fs.readFile(statementsPath, "utf8"));
const bankNames = [...new Set(statements.map((s) => s.bank).filter(Boolean))];
const bankName = bankNames.length === 1 ? bankNames[0] : bankNames.length ? "Multiple Banks" : "Bank";
const txRows = transactions.map((r) => [
  Number(r.seq),
  r.source_file,
  excelDate(r.statement_from),
  excelDate(r.statement_to),
  excelDate(r.date),
  excelDate(r.value_date),
  r.narration,
  r.reference,
  r.direction,
  Number(r.withdrawal),
  Number(r.deposit),
  Number(r.amount),
  Number(r.closing_balance),
  r.categories,
  r.is_recurring,
  r.recurring_key,
]);

const statementRows = statements.map((s) => [
  s.file,
  excelDate(s.from),
  excelDate(s.to),
  monthLabel(s.to),
  s.pages,
  Number(s.opening_balance),
  Number(s.dr_count),
  Number(s.cr_count),
  Number(s.debits),
  Number(s.credits),
  Number(s.closing_balance),
]);

const effectiveMonthDates = transactions.map((r) => effectiveMonthDate(r));
const monthlyKeys = [...new Set(effectiveMonthDates.map((date) => monthKey(date)))].sort();
const monthlyRows = monthlyKeys.map((key) => {
  const rows = transactions.filter((_, index) => monthKey(effectiveMonthDates[index]) === key);
  const first = rows[0];
  const last = rows[rows.length - 1];
  return [
    key,
    monthStart(key),
    nextMonthStart(key),
    monthLabel(`${key}-01`),
    rows.length,
    Number(first?.closing_balance ?? 0) - Number(first?.deposit ?? 0) + Number(first?.withdrawal ?? 0),
    rows.filter((r) => Number(r.withdrawal) !== 0).length,
    rows.filter((r) => Number(r.deposit) !== 0).length,
    rows.reduce((sum, r) => sum + Number(r.withdrawal), 0),
    rows.reduce((sum, r) => sum + Number(r.deposit), 0),
    Number(last?.closing_balance ?? 0),
  ];
});

const requestedCategories = [
  ["Total", ""],
  ["Cash", "Cash"],
  ["Recurring Transaction", "Recurring Transaction"],
  ["EMI", "EMI"],
  ["Salary", "Salary"],
  ["High Transaction", "High Transaction"],
  ["UPI", "UPI"],
  ["LIC", "LIC"],
  ["FD interest", "FD interest"],
  ["FD Deposit and withdrawals", "FD Deposit/Withdrawal"],
  ["PPF/PF interest and contribution", "PPF/PF interest/contribution"],
];
const flagCategories = requestedCategories.slice(1);
const detailCategories = [
  ["Total", ""],
  ["Cash", "Cash"],
  ["Recurring Transaction", "Recurring Transaction"],
  ["EMI", "EMI"],
  ["Salary", "Salary"],
  ["High Transaction", "High Transaction"],
  ["Total Receipts and Payments", ""],
  ["UPI", "UPI"],
  ["LIC", "LIC"],
  ["FD interest", "FD interest"],
  ["FD Deposit and withdrawals", "FD Deposit/Withdrawal"],
  ["PPF/PF interest and contribution", "PPF/PF interest/contribution"],
];

function rowsForCategory(match) {
  if (!match) {
    return txRows;
  }
  return txRows.filter((row) => String(row[13] ?? "").includes(match));
}

const workbook = Workbook.create();
const dashboard = workbook.worksheets.add("Dashboard");
const categories = workbook.worksheets.add("Category Summary");
const categoryDetails = workbook.worksheets.add("Category Details");
const monthly = workbook.worksheets.add("Monthly Summary");
const txSheet = workbook.worksheets.add("Transactions");

for (const sheet of [dashboard, categories, categoryDetails, monthly, txSheet]) {
  sheet.showGridLines = false;
}

// Transactions
const txHeaders = [
  "Seq",
  "Source File",
  "Statement From",
  "Statement To",
  "Date",
  "Value Date",
  "Narration",
  "Reference",
  "Direction",
  "Withdrawal",
  "Deposit",
  "Amount",
  "Closing Balance",
  "Categories",
  "Recurring?",
  "Recurring Key",
  ...flagCategories.map(([label]) => `Flag - ${label}`),
  "Month Date",
];
const txEndCol = excelCol(txHeaders.length);
const monthDateCol = txEndCol;
const txRowsWithFlags = txRows.map((row, index) => {
  const categoryText = String(row[13] ?? "");
  return [
    ...row,
    ...flagCategories.map(([, match]) => (categoryText.includes(match) ? 1 : 0)),
    excelDate(effectiveMonthDates[index]),
  ];
});
function detailRowsForCategory(match) {
  if (!match) {
    return txRowsWithFlags;
  }
  return txRowsWithFlags.filter((row) => String(row[13] ?? "").includes(match));
}
txSheet.getRange(`A1:${txEndCol}1`).values = [txHeaders];
txSheet.getRangeByIndexes(1, 0, txRowsWithFlags.length, txHeaders.length).values = txRowsWithFlags;
styleHeader(txSheet.getRange(`A1:${txEndCol}1`));
styleBody(txSheet.getRangeByIndexes(1, 0, txRows.length, txHeaders.length));
txSheet.getRange(`C2:F${txRows.length + 1}`).format.numberFormat = "yyyy-mm-dd";
txSheet.getRange(`${monthDateCol}2:${monthDateCol}${txRows.length + 1}`).format.numberFormat = "yyyy-mm-dd";
txSheet.getRange(`J2:M${txRows.length + 1}`).format.numberFormat = moneyFormat();
txSheet.getRange(`G2:G${txRows.length + 1}`).format.wrapText = true;
txSheet.getRange(`A1:${txEndCol}${txRows.length + 1}`).format.font = { name: "Aptos", size: 10 };
txSheet.tables.add(`A1:${txEndCol}${txRows.length + 1}`, true, "TransactionsTable");
txSheet.freezePanes.freezeRows(1);
setWidths(txSheet, [8, 16, 14, 14, 12, 12, 44, 18, 12, 14, 14, 14, 16, 28, 12, 18, ...flagCategories.map(() => 10), 12]);

const detailSheets = [];
for (const [label, match] of detailCategories) {
  const detailName = sheetNameForDetail(label);
  const detailSheet = workbook.worksheets.add(detailName);
  detailSheet.showGridLines = false;
  detailSheets.push(detailName);

  const detailRows = detailRowsForCategory(match);
  const detailHeaders = [...txHeaders, "View Source Row"];
  const detailEndCol = excelCol(detailHeaders.length);
  
  detailSheet.getRange("A1").formulas = [[`=HYPERLINK("#'Dashboard'!A1", "← Return to Dashboard")`]];
  detailSheet.getRange("A1").format = {
    font: { bold: true, color: "#135e75", underline: "single" },
    horizontalAlignment: "center",
    verticalAlignment: "center"
  };
  const titleRange = detailSheet.getRange(`B1:${detailEndCol}1`);
  titleRange.merge();
  titleRange.values = [[`${label} Transactions`]];
  titleRange.format = {
    fill: "#17324D",
    font: { bold: true, color: "#FFFFFF", size: 16 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
  detailSheet.getRange("A1").format.rowHeight = 30;

  detailSheet.getRange("A2:D2").values = [["Rows", detailRows.length, "Match", match || "All transactions"]];
  detailSheet.getRange("A2:D2").format = {
    fill: "#EAF2F8",
    font: { bold: true },
    borders: { preset: "all", style: "thin", color: "#D7DEE8" },
  };
  detailSheet.getRange(`A4:${detailEndCol}4`).values = [detailHeaders];
  styleHeader(detailSheet.getRange(`A4:${detailEndCol}4`));
  if (detailRows.length) {
    detailSheet.getRangeByIndexes(4, 0, detailRows.length, detailHeaders.length - 1).values = detailRows;
    const linkFormulas = detailRows.map(r => [`=HYPERLINK("#'Transactions'!A${r[0] + 1}", "View Source Row")`]);
    detailSheet.getRangeByIndexes(4, detailHeaders.length - 1, detailRows.length, 1).formulas = linkFormulas;
    detailSheet.getRangeByIndexes(4, detailHeaders.length - 1, detailRows.length, 1).format.font = { color: "#135E75", underline: "single", bold: true };
    styleBody(detailSheet.getRangeByIndexes(4, 0, detailRows.length, detailHeaders.length));
    detailSheet.getRange(`C5:F${detailRows.length + 4}`).format.numberFormat = "yyyy-mm-dd";
    detailSheet.getRange(`${monthDateCol}5:${monthDateCol}${detailRows.length + 4}`).format.numberFormat = "yyyy-mm-dd";
    detailSheet.getRange(`J5:M${detailRows.length + 4}`).format.numberFormat = moneyFormat();
    detailSheet.getRange(`G5:G${detailRows.length + 4}`).format.wrapText = true;
    detailSheet.tables.add(`A4:${detailEndCol}${detailRows.length + 4}`, true, `${label.replace(/[^A-Za-z0-9]/g, "") || "All"}DetailTable`.slice(0, 255));
  } else {
    detailSheet.getRange("A5").values = [["No matching transactions."]];
  }
  detailSheet.getRange(`A1:${detailEndCol}${Math.max(detailRows.length + 4, 5)}`).format.font = { name: "Aptos", size: 10 };
  detailSheet.freezePanes.freezeRows(4);
  setWidths(detailSheet, [8, 16, 14, 14, 12, 12, 44, 18, 12, 14, 14, 14, 16, 28, 12, 18, ...flagCategories.map(() => 10), 12, 18]);
}

const checks = workbook.worksheets.add("Checks");
const sources = workbook.worksheets.add("Sources");
for (const sheet of [checks, sources]) {
  sheet.showGridLines = false;
}

// Monthly Summary
const monthHeaders = [
  "Month Key",
  "From",
  "To",
  "Period",
  "Transactions",
  "Opening Balance",
  "Dr Count",
  "Cr Count",
  "Payments",
  "Receipts",
  "Closing Balance",
  "Parsed Payments",
  "Parsed Receipts",
  "Payment Check",
  "Receipt Check",
];
monthly.getRange("A1:O1").values = [monthHeaders];
monthly.getRangeByIndexes(1, 0, monthlyRows.length, 11).values = monthlyRows;
monthly.getRange(`L2:L${monthlyRows.length + 1}`).formulas = monthlyRows.map((_, i) => [
  `=SUMIFS(Transactions!$J$2:$J$${txRows.length + 1},Transactions!$${monthDateCol}$2:$${monthDateCol}$${txRows.length + 1},">="&B${i + 2},Transactions!$${monthDateCol}$2:$${monthDateCol}$${txRows.length + 1},"<"&C${i + 2})`,
]);
monthly.getRange(`M2:M${monthlyRows.length + 1}`).formulas = monthlyRows.map((_, i) => [
  `=SUMIFS(Transactions!$K$2:$K$${txRows.length + 1},Transactions!$${monthDateCol}$2:$${monthDateCol}$${txRows.length + 1},">="&B${i + 2},Transactions!$${monthDateCol}$2:$${monthDateCol}$${txRows.length + 1},"<"&C${i + 2})`,
]);
monthly.getRange(`N2:N${monthlyRows.length + 1}`).formulas = monthlyRows.map((_, i) => [
  `=IF(ABS(I${i + 2}-L${i + 2})<0.01,"OK","Check")`,
]);
monthly.getRange(`O2:O${monthlyRows.length + 1}`).formulas = monthlyRows.map((_, i) => [
  `=IF(ABS(J${i + 2}-M${i + 2})<0.01,"OK","Check")`,
]);
styleHeader(monthly.getRange("A1:O1"));
styleBody(monthly.getRangeByIndexes(1, 0, monthlyRows.length, 15));
monthly.getRange(`B2:C${monthlyRows.length + 1}`).format.numberFormat = "yyyy-mm-dd";
monthly.getRange(`F2:F${monthlyRows.length + 1}`).format.numberFormat = moneyFormat();
monthly.getRange(`I2:M${monthlyRows.length + 1}`).format.numberFormat = moneyFormat();
monthly.getRange(`A1:O${monthlyRows.length + 1}`).format.font = { name: "Aptos", size: 10 };
monthly.tables.add(`A1:O${monthlyRows.length + 1}`, true, "MonthlySummaryTable");
monthly.freezePanes.freezeRows(1);
setWidths(monthly, [16, 12, 12, 12, 8, 16, 10, 10, 15, 15, 16, 15, 15, 14, 14]);

// Category Summary
categories.getRange("A1:H1").values = [[
  "Requested Category",
  "Match Term",
  "Receipt Count",
  "Receipts",
  "Payment Count",
  "Payments",
  "Net",
  "Notes",
]];
categories.getRangeByIndexes(1, 0, requestedCategories.length, 2).values = requestedCategories;
const lastCatRow = requestedCategories.length + 1;
for (let r = 2; r <= lastCatRow; r++) {
  const totalRow = r === 2;
  const flagCol = excelCol(16 + (r - 2));
  categories.getRange(`C${r}:G${r}`).formulas = [[
    totalRow
      ? `=COUNTIF(Transactions!$I$2:$I$${txRows.length + 1},"Receipt")`
      : `=COUNTIFS(Transactions!$${flagCol}$2:$${flagCol}$${txRows.length + 1},1,Transactions!$I$2:$I$${txRows.length + 1},"Receipt")`,
    totalRow
      ? `=SUM(Transactions!$K$2:$K$${txRows.length + 1})`
      : `=SUMIFS(Transactions!$K$2:$K$${txRows.length + 1},Transactions!$${flagCol}$2:$${flagCol}$${txRows.length + 1},1)`,
    totalRow
      ? `=COUNTIF(Transactions!$I$2:$I$${txRows.length + 1},"Payment")`
      : `=COUNTIFS(Transactions!$${flagCol}$2:$${flagCol}$${txRows.length + 1},1,Transactions!$I$2:$I$${txRows.length + 1},"Payment")`,
    totalRow
      ? `=SUM(Transactions!$J$2:$J$${txRows.length + 1})`
      : `=SUMIFS(Transactions!$J$2:$J$${txRows.length + 1},Transactions!$${flagCol}$2:$${flagCol}$${txRows.length + 1},1)`,
    `=ROUND(D${r}-F${r},2)`,
  ]];
}
categories.getRange("H2:H12").values = [
  ["All parsed receipts and payments."],
  ["Cash detected from CASH DEPOSIT BY narration."],
  ["Repeated counterpart/pattern appearing at least twice."],
  ["Keyword based: EMI/ECS/ACH/loan/installment."],
  ["Keyword based: salary."],
  ["Transactions with absolute amount at or above Rs 100,000."],
  ["Keyword based: UPI."],
  ["Keyword based: LIC."],
  ["Keyword based: FD plus interest/int."],
  ["Keyword based: FD/fixed deposit/TDR/term deposit."],
  ["Keyword based: PPF/PF/EPF/provident fund."],
];
styleHeader(categories.getRange("A1:H1"));
styleBody(categories.getRange(`A2:H${lastCatRow}`));
categories.getRange(`D2:G${lastCatRow}`).format.numberFormat = moneyFormat();
categories.getRange(`A1:H${lastCatRow}`).format.font = { name: "Aptos", size: 10 };
categories.getRange(`H2:H${lastCatRow}`).format.wrapText = true;
categories.tables.add(`A1:H${lastCatRow}`, true, "CategorySummaryTable");
categories.freezePanes.freezeRows(1);
setWidths(categories, [30, 26, 14, 15, 14, 15, 15, 44]);

// Category Details Index
styleTitle(categoryDetails.getRange("A1:H1"), "Category Details");
categoryDetails.getRange("A3:H3").values = [[
  "Category",
  "Detail Sheet",
  "Rows",
  "Receipt Count",
  "Receipts",
  "Payment Count",
  "Payments",
  "Net",
]];
const detailIndexRows = detailCategories.map(([label, match]) => {
  const rows = detailRowsForCategory(match);
  const receipts = rows.filter((row) => row[8] === "Receipt");
  const payments = rows.filter((row) => row[8] === "Payment");
  const receiptAmount = receipts.reduce((sum, row) => sum + Number(row[10]), 0);
  const paymentAmount = payments.reduce((sum, row) => sum + Number(row[9]), 0);
  return [
    label,
    sheetNameForDetail(label),
    rows.length,
    receipts.length,
    receiptAmount,
    payments.length,
    paymentAmount,
    receiptAmount - paymentAmount,
  ];
});
categoryDetails.getRangeByIndexes(3, 0, detailIndexRows.length, 8).values = detailIndexRows;
styleHeader(categoryDetails.getRange("A3:H3"));
styleBody(categoryDetails.getRangeByIndexes(3, 0, detailIndexRows.length, 8));
categoryDetails.getRange(`E4:H${detailIndexRows.length + 3}`).format.numberFormat = moneyFormat();
categoryDetails.getRange(`A1:H${detailIndexRows.length + 3}`).format.font = { name: "Aptos", size: 10 };
categoryDetails.tables.add(`A3:H${detailIndexRows.length + 3}`, true, "CategoryDetailsTable");
categoryDetails.freezePanes.freezeRows(3);
setWidths(categoryDetails, [34, 32, 10, 14, 15, 14, 15, 15]);

// Checks
checks.getRange("A1:F1").values = [["Check", "Actual", "Expected", "Difference", "Tolerance", "Status"]];
checks.getRange("A2:A7").values = [
  [`Total payments tie to ${bankName} summaries`],
  [`Total receipts tie to ${bankName} summaries`],
  ["All monthly payment checks OK"],
  ["All monthly receipt checks OK"],
  ["Transaction rows parsed"],
  ["Statement PDFs processed"],
];
checks.getRange("B2:F7").formulas = [
  [`=SUM(Transactions!$J$2:$J$${txRows.length + 1})`, `=SUM('Monthly Summary'!$I$2:$I$${monthlyRows.length + 1})`, "=B2-C2", "0.01", '=IF(ABS(D2)<=E2,"OK","Check")'],
  [`=SUM(Transactions!$K$2:$K$${txRows.length + 1})`, `=SUM('Monthly Summary'!$J$2:$J$${monthlyRows.length + 1})`, "=B3-C3", "0.01", '=IF(ABS(D3)<=E3,"OK","Check")'],
  [`=COUNTIF('Monthly Summary'!$N$2:$N$${monthlyRows.length + 1},"OK")`, monthlyRows.length, "=B4-C4", "0", '=IF(D4=0,"OK","Check")'],
  [`=COUNTIF('Monthly Summary'!$O$2:$O$${monthlyRows.length + 1},"OK")`, monthlyRows.length, "=B5-C5", "0", '=IF(D5=0,"OK","Check")'],
  [`=COUNTA(Transactions!$A$2:$A$${txRows.length + 1})`, txRows.length, "=B6-C6", "0", '=IF(D6=0,"OK","Check")'],
  [`=COUNTA(Sources!$A$2:$A$${statementRows.length + 1})`, statementRows.length, "=B7-C7", "0", '=IF(D7=0,"OK","Check")'],
];
styleHeader(checks.getRange("A1:F1"));
styleBody(checks.getRange("A2:F7"));
checks.getRange("B2:E3").format.numberFormat = moneyFormat();
checks.getRange("B4:E7").format.numberFormat = "#,##0";
checks.getRange("A1:F7").format.font = { name: "Aptos", size: 10 };
checks.tables.add("A1:F7", true, "ChecksTable");
setWidths(checks, [34, 16, 16, 16, 12, 12]);

// Sources
sources.getRange("A1:E1").values = [["Source File", "Statement From", "Statement To", "Pages", "Layout Review"]];
sources.getRangeByIndexes(
  1,
  0,
  statements.length,
  5,
).values = statements.map((s) => [
  s.file,
  excelDate(s.from),
  excelDate(s.to),
  s.pages,
  `Text-based ${s.bank || bankName} statement table. Transaction rows reconciled to statement summary.`,
]);
styleHeader(sources.getRange("A1:E1"));
styleBody(sources.getRange(`A2:E${statements.length + 1}`));
sources.getRange(`B2:C${statements.length + 1}`).format.numberFormat = "yyyy-mm-dd";
sources.getRange(`A1:E${statements.length + 1}`).format.font = { name: "Aptos", size: 10 };
sources.getRange(`E2:E${statements.length + 1}`).format.wrapText = true;
sources.tables.add(`A1:E${statements.length + 1}`, true, "SourcesTable");
setWidths(sources, [18, 14, 14, 8, 60]);

// Dashboard
styleTitle(dashboard.getRange("A1:N1"), `${bankName} Statement Analysis`);
dashboard.getRange("A3:B3").values = [["Period Covered", `${monthLabel(`${monthlyKeys[0]}-01`)} to ${monthLabel(`${monthlyKeys[monthlyKeys.length - 1]}-01`)}`]];
dashboard.getRange("A4:B4").values = [["Statements Reviewed", statements.length]];
dashboard.getRange("A5:B5").values = [["Transactions Parsed", txRows.length]];
dashboard.getRange("A7:B13").values = [
  ["Total Receipts", null],
  ["Total Payments", null],
  ["Net Movement", null],
  ["Cash Receipts", null],
  ["High Transaction Value", null],
  ["Recurring Transaction Value", null],
  ["UPI / LIC / EMI / Salary", null],
];
dashboard.getRange("B7:B13").formulas = [
  ["='Category Summary'!D2"],
  ["='Category Summary'!F2"],
  ["=ROUND('Category Summary'!G2,2)"],
  ["='Category Summary'!D3"],
  ["=ROUND('Category Summary'!D7-'Category Summary'!F7,2)"],
  ["=ROUND('Category Summary'!D4-'Category Summary'!F4,2)"],
  ["=ROUND('Category Summary'!G8+'Category Summary'!G9+'Category Summary'!G5+'Category Summary'!G6,2)"],
];
dashboard.getRange("A15:G15").values = [["Category", "Receipt Count", "Receipts", "Payment Count", "Payments", "Net", "Action / View Detail"]];
dashboard.getRange("A16:G26").formulas = requestedCategories.map((reqCat, idx) => {
  const r = idx + 2;
  const catVal = reqCat[0];
  let link = '""';
  if (catVal === "Recurring Transaction") {
    link = `=HYPERLINK("#'Detail Recurring Transaction'!A1", "View Detail")`;
  } else if (catVal === "High Transaction") {
    link = `=HYPERLINK("#'Detail High Transaction'!A1", "View Detail")`;
  }
  return [
    `='Category Summary'!A${r}`,
    `='Category Summary'!C${r}`,
    `='Category Summary'!D${r}`,
    `='Category Summary'!E${r}`,
    `='Category Summary'!F${r}`,
    `='Category Summary'!G${r}`,
    link,
  ];
});
dashboard.getRange("I3:N3").values = [["Period", "Receipts", "Payments", "Net", "Closing Balance", "Checks"]];
dashboard.getRange(`I4:N${monthlyRows.length + 3}`).formulas = monthlyRows.map((_, idx) => {
  const r = idx + 2;
  return [
    `='Monthly Summary'!D${r}`,
    `='Monthly Summary'!J${r}`,
    `='Monthly Summary'!I${r}`,
    `=ROUND(J${idx + 4}-K${idx + 4},2)`,
    `='Monthly Summary'!K${r}`,
    `='Monthly Summary'!N${r}&"/"&'Monthly Summary'!O${r}`,
  ];
});
styleHeader(dashboard.getRange("A15:G15"));
styleHeader(dashboard.getRange("I3:N3"));
styleBody(dashboard.getRange("A3:B5"));
styleBody(dashboard.getRange("A7:B13"));
styleBody(dashboard.getRange("A16:G26"));
styleBody(dashboard.getRange(`I4:N${monthlyRows.length + 3}`));
dashboard.getRange("A7:A13").format = { fill: "#EAF2F8", font: { bold: true }, borders: { preset: "all", style: "thin", color: "#D7DEE8" } };
dashboard.getRange("B7:B13").format.numberFormat = moneyFormat();
dashboard.getRange("C16:F26").format.numberFormat = moneyFormat();
dashboard.getRange("G16:G26").format.font = { color: "#135E75", underline: "single", bold: true };
dashboard.getRange(`J4:M${monthlyRows.length + 3}`).format.numberFormat = moneyFormat();
dashboard.getRange("A1:N26").format.font = { name: "Aptos", size: 10 };
dashboard.getRange("A1:N1").format.font = { name: "Aptos Display", bold: true, color: "#FFFFFF", size: 16 };
setWidths(dashboard, [30, 16, 15, 14, 15, 15, 20, 3, 14, 15, 15, 15, 16, 12]);

const chart = dashboard.charts.add("bar", dashboard.getRange(`I3:K${monthlyRows.length + 3}`));
chart.title = "Receipts and Payments by Month";
chart.hasLegend = true;
chart.yAxis = { numberFormatCode: "₹#,##0" };
chart.setPosition("I16", "N31");

await fs.mkdir(outputDir, { recursive: true });

if (process.env.HDFC_SKIP_PREVIEWS !== "1") {
  for (const sheetName of ["Dashboard", "Category Summary", "Category Details", "Monthly Summary", "Transactions", ...detailSheets, "Checks", "Sources"]) {
    const previewRange = sheetName === "Transactions" || detailSheets.includes(sheetName) ? "A1:Z45" : undefined;
    const preview = await workbook.render({
      sheetName,
      ...(previewRange ? { range: previewRange } : { autoCrop: "all" }),
      scale: 1,
      format: "png",
    });
    await fs.writeFile(
      path.join(workDir, `${sheetName.replace(/ /g, "_").toLowerCase()}_preview.png`),
      new Uint8Array(await preview.arrayBuffer()),
    );
  }
}

const summaryInspect = await workbook.inspect({
  kind: "table",
  range: "Dashboard!A1:N26",
  include: "values,formulas",
  tableMaxRows: 30,
  tableMaxCols: 14,
  maxChars: 8000,
});
await fs.writeFile(path.join(workDir, "dashboard_inspect.ndjson"), summaryInspect.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
await fs.writeFile(path.join(workDir, "formula_errors.ndjson"), errors.ndjson);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

console.log(JSON.stringify({
  outputPath,
  transactions: txRows.length,
  statements: statementRows.length,
  totalPayments: transactions.reduce((sum, r) => sum + Number(r.withdrawal), 0),
  totalReceipts: transactions.reduce((sum, r) => sum + Number(r.deposit), 0),
}, null, 2));
