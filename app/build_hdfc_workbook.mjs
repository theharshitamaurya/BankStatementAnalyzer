import fs from "node:fs/promises";
import path from "node:path";
import { spawnSync } from "node:child_process";
import ExcelJS from "exceljs";

export async function buildWorkbook(options = {}, onProgress = null) {
  const root = process.cwd();
  const workDir   = options.workDir   || process.env.HDFC_WORK_DIR    || path.join(root, "work");
  const outputDir = options.outputDir || process.env.HDFC_OUTPUT_DIR  || path.join(root, "outputs");
  const txCsvPath = path.join(workDir, "transactions.csv");
  const statementsPath = path.join(workDir, "statements.json");
  const outputPath = options.outputPath || process.env.HDFC_OUTPUT_XLSX || path.join(outputDir, "bank_statement_analysis.xlsx");

// ── CSV parser ────────────────────────────────────────────────────────────────
function parseCsv(text) {
  const rows = []; let row = []; let cell = ""; let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i], next = text[i + 1];
    if (quoted) {
      if (ch === '"' && next === '"') { cell += '"'; i++; }
      else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') { quoted = true; }
    else if (ch === ',') { row.push(cell); cell = ''; }
    else if (ch === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; }
    else if (ch !== '\r') cell += ch;
  }
  if (cell.length || row.length) { row.push(cell); rows.push(row); }
  const headers = rows.shift();
  return rows.filter(r => r.length === headers.length)
             .map(r => Object.fromEntries(headers.map((h, i) => [h, r[i]])));
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function excelDate(iso) {
  if (!iso) return null;
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}
function monthLabel(iso) {
  return excelDate(iso).toLocaleString('en-US', { month: 'short', year: 'numeric' });
}
function monthKey(iso) { return iso ? iso.slice(0, 7) : ''; }
function monthStart(key)     { const [y,m] = key.split('-').map(Number); return new Date(y, m-1, 1); }
function nextMonthStart(key) { const [y,m] = key.split('-').map(Number); return new Date(y, m,   1); }
function inRange(iso, s, e)  { return iso && s && e && iso >= s && iso <= e; }
function effectiveMonthDate(row) {
  if (inRange(row.date,       row.statement_from, row.statement_to)) return row.date;
  if (inRange(row.value_date, row.statement_from, row.statement_to)) return row.value_date;
  return row.date || row.value_date;
}
function sheetNameForDetail(label) {
  return ('Detail ' + label.replace(/[^A-Za-z0-9 ]/g,' ').replace(/\s+/g,' ').trim()).slice(0,31);
}
function excelCol(n) {
  let s = '';
  while (n > 0) { const m = (n-1)%26; s = String.fromCharCode(65+m)+s; n = Math.floor((n-1)/26); }
  return s;
}

const MONEY_FMT = '₹#,##0.00;[Red](₹#,##0.00);"-"';
const DATE_FMT  = 'yyyy-mm-dd';
const DARK_BLUE  = 'FF17324D';
const MED_BLUE   = 'FF315A7D';
const LIGHT_BLUE = 'FFEAF2F8';
const WHITE      = 'FFFFFFFF';
const B_DARK  = { style:'thin', color:{argb:'FFD7DEE8'} };
const B_LIGHT = { style:'thin', color:{argb:'FFE2E8F0'} };
const ab = b => ({ top:b, bottom:b, left:b, right:b });

// ── Style functions ───────────────────────────────────────────────────────────
function hdr(cell) {
  cell.fill      = { type:'pattern', pattern:'solid', fgColor:{argb:MED_BLUE} };
  cell.font      = { bold:true, color:{argb:WHITE}, name:'Aptos', size:10 };
  cell.alignment = { horizontal:'center', vertical:'middle', wrapText:true };
  cell.border    = ab(B_DARK);
}
function body(cell) {
  cell.fill      = { type:'pattern', pattern:'solid', fgColor:{argb:WHITE} };
  cell.font      = { name:'Aptos', size:10 };
  cell.alignment = { vertical:'top' };
  cell.border    = ab(B_LIGHT);
}
function hilight(cell) {
  cell.fill   = { type:'pattern', pattern:'solid', fgColor:{argb:LIGHT_BLUE} };
  cell.font   = { bold:true, name:'Aptos', size:10 };
  cell.border = ab(B_DARK);
}
function link(cell) {
  cell.fill   = { type:'pattern', pattern:'solid', fgColor:{argb:WHITE} };
  cell.font   = { color:{argb:'FF135E75'}, underline:true, bold:true, name:'Aptos', size:10 };
  cell.alignment = { vertical:'top' };
  cell.border = ab(B_LIGHT);
}
function title(ws, rowNum, text, fromCol, toCol) {
  const cell = ws.getCell(rowNum, fromCol);
  cell.value     = text;
  cell.fill      = { type:'pattern', pattern:'solid', fgColor:{argb:DARK_BLUE} };
  cell.font      = { bold:true, color:{argb:WHITE}, name:'Aptos Display', size:16 };
  cell.alignment = { horizontal:'center', vertical:'middle' };
  if (toCol > fromCol) ws.mergeCells(rowNum, fromCol, rowNum, toCol);
  ws.getRow(rowNum).height = 30;
}
function hdrRow(ws, rowNum, headers) {
  const row = ws.getRow(rowNum);
  row.height = 20;
  headers.forEach((h, i) => { const c = row.getCell(i+1); c.value = h; hdr(c); });
  return row;
}
function widths(ws, arr) { arr.forEach((w,i) => { ws.getColumn(i+1).width = w; }); }
function money(cell) { cell.numFmt = MONEY_FMT; }
function date(cell)  { cell.numFmt = DATE_FMT; }

// ── Load data ─────────────────────────────────────────────────────────────────
const transactions = parseCsv(await fs.readFile(txCsvPath, 'utf8'));
const statements   = JSON.parse(await fs.readFile(statementsPath, 'utf8'));
const bankNames = [...new Set(statements.map(s => s.bank).filter(Boolean))];
const bankName  = bankNames.length === 1 ? bankNames[0] : bankNames.length ? 'Multiple Banks' : 'Bank';

const txRows = transactions.map(r => [
  Number(r.seq), r.source_file,
  excelDate(r.statement_from), excelDate(r.statement_to),
  excelDate(r.date), excelDate(r.value_date),
  r.narration, r.reference, r.direction,
  Number(r.withdrawal), Number(r.deposit), Number(r.amount),
  Number(r.closing_balance), r.categories, r.is_recurring, r.recurring_key,
]);

const effDates   = transactions.map(r => effectiveMonthDate(r));
const monthKeys  = [...new Set(effDates.map(d => monthKey(d)).filter(Boolean))].sort();

const monthlyData = monthKeys.map(key => {
  const rows   = transactions.filter((_,i) => monthKey(effDates[i]) === key);
  const first  = rows[0], last = rows[rows.length-1];
  const pays   = rows.reduce((s,r) => s + Number(r.withdrawal), 0);
  const recs   = rows.reduce((s,r) => s + Number(r.deposit),    0);
  return {
    key,
    from:  monthStart(key),
    to:    nextMonthStart(key),
    label: monthLabel(`${key}-01`),
    count: rows.length,
    opening: Number(first?.closing_balance??0) - Number(first?.deposit??0) + Number(first?.withdrawal??0),
    drCount: rows.filter(r => Number(r.withdrawal)!==0).length,
    crCount: rows.filter(r => Number(r.deposit)!==0).length,
    pays, recs, closing: Number(last?.closing_balance??0),
  };
});

const REQ_CATS = [
  ['Total',''],
  ['Cash','Cash'],
  ['Recurring Transaction','Recurring Transaction'],
  ['EMI','EMI'],
  ['Salary','Salary'],
  ['High Transaction','High Transaction'],
  ['UPI','UPI'],
  ['LIC','LIC'],
  ['FD interest','FD interest'],
  ['FD Deposit and withdrawals','FD Deposit/Withdrawal'],
  ['PPF/PF interest and contribution','PPF/PF interest/contribution'],
];
const FLAG_CATS = REQ_CATS.slice(1);
const DETAIL_CATS = [
  ['Total',''],
  ['Cash','Cash'],
  ['Recurring Transaction','Recurring Transaction'],
  ['EMI','EMI'],
  ['Salary','Salary'],
  ['High Transaction','High Transaction'],
  ['Total Receipts and Payments',''],
  ['UPI','UPI'],
  ['LIC','LIC'],
  ['FD interest','FD interest'],
  ['FD Deposit and withdrawals','FD Deposit/Withdrawal'],
  ['PPF/PF interest and contribution','PPF/PF interest/contribution'],
];

const TX_HDRS = [
  'Seq','Source File','Statement From','Statement To','Date','Value Date',
  'Narration','Reference','Direction','Withdrawal','Deposit','Amount',
  'Closing Balance','Categories','Recurring?','Recurring Key',
  ...FLAG_CATS.map(([l]) => `Flag - ${l}`),
  'Month Date',
];
const TX_END = TX_HDRS.length;

const txWithFlags = txRows.map((row, i) => {
  const cat = String(row[13]??'');
  return [...row, ...FLAG_CATS.map(([,m]) => cat.includes(m)?1:0), excelDate(effDates[i])];
});

function rowsFor(match) {
  if (!match) return txWithFlags;
  return txWithFlags.filter(r => String(r[13]??'').includes(match));
}
function catStats(match) {
  const rows = rowsFor(match);
  const rec  = rows.filter(r => r[8]==='Receipt');
  const pay  = rows.filter(r => r[8]==='Payment');
  const rA   = rec.reduce((s,r) => s+Number(r[10]), 0);
  const pA   = pay.reduce((s,r) => s+Number(r[9]),  0);
  return { recCount:rec.length, recAmt:rA, payCount:pay.length, payAmt:pA, net:Math.round((rA-pA)*100)/100 };
}
const catSum = REQ_CATS.map(([label,match]) => ({ label, match, ...catStats(match) }));

// ── Workbook ──────────────────────────────────────────────────────────────────
const wb     = new ExcelJS.Workbook();
wb.calcProperties = { fullCalcOnLoad:true };

const totalSheets = 5 + DETAIL_CATS.length + 2; // Dashboard, CatSum, CatDet, Month, Tx, Checks, Sources + DetailSheets
let currentSheet = 0;
const report = (name) => {
  currentSheet++;
  if (onProgress) onProgress(name, currentSheet, totalSheets);
};

const wsDash   = wb.addWorksheet('Dashboard');
const wsCat    = wb.addWorksheet('Category Summary');
const wsCatD   = wb.addWorksheet('Category Details');
const wsMonth  = wb.addWorksheet('Monthly Summary');
const wsTx     = wb.addWorksheet('Transactions');

report('Transactions');

// ══ Transactions ══════════════════════════════════════════════════════════════
wsTx.showGridLines = false;
wsTx.views = [{ state:'frozen', ySplit:1 }];
hdrRow(wsTx, 1, TX_HDRS);
for (let i = 0; i < txWithFlags.length; i++) {
  const r = wsTx.getRow(i+2);
  txWithFlags[i].forEach((v,ci) => { r.getCell(ci+1).value = v; });
  r.eachCell({ includeEmpty:true }, body);
  [3,4,5,6,TX_END].forEach(ci => date(r.getCell(ci)));
  [10,11,12,13].forEach(ci => money(r.getCell(ci)));
  r.getCell(7).alignment = { vertical:'top', wrapText:true };
}
widths(wsTx, [8,16,14,14,12,12,44,18,12,14,14,14,16,28,12,18,...FLAG_CATS.map(()=>10),12]);

// ══ Detail sheets ══════════════════════════════════════════════════════════════
const detailNames = [];
for (const [label, match] of DETAIL_CATS) {
  const wsName = sheetNameForDetail(label);
  report(wsName);
  detailNames.push(wsName);
  const ws = wb.addWorksheet(wsName);
  ws.showGridLines = false;
  ws.views = [{ state:'frozen', ySplit:4 }];
  const dRows   = rowsFor(match);
  const dHdrs   = [...TX_HDRS, 'View Source Row'];
  const dEnd    = dHdrs.length;

  // Row 1
  ws.getRow(1).height = 30;
  const backCell = ws.getCell(1,1);
  backCell.value = { text:'← Return to Dashboard', hyperlink:`#'Dashboard'!A1` };
  backCell.font  = { bold:true, color:{argb:'FF135e75'}, underline:true, name:'Aptos', size:10 };
  backCell.alignment = { horizontal:'center', vertical:'middle' };
  title(ws, 1, `${label} Transactions`, 2, dEnd);

  // Row 2: meta
  [['Rows', dRows.length, 'Match', match||'All transactions']].forEach(vals => {
    vals.forEach((v,ci) => { const c = ws.getCell(2, ci+1); c.value=v; hilight(c); });
  });

  // Row 4: header
  hdrRow(ws, 4, dHdrs);

  // Data rows
  for (let di = 0; di < dRows.length; di++) {
    const data = dRows[di];
    const r    = ws.getRow(5+di);
    data.forEach((v,ci) => { r.getCell(ci+1).value = v; });
    r.eachCell({ includeEmpty:true }, body);
    // link cell AFTER body so font sticks
    const lc = r.getCell(dEnd);
    lc.value = { text:'View Source Row', hyperlink:`#'Transactions'!A${data[0]+1}` };
    link(lc);
    [3,4,5,6,TX_END].forEach(ci => date(r.getCell(ci)));
    [10,11,12,13].forEach(ci => money(r.getCell(ci)));
    r.getCell(7).alignment = { vertical:'top', wrapText:true };
  }
  if (!dRows.length) ws.getCell('A5').value = 'No matching transactions.';
  widths(ws, [8,16,14,14,12,12,44,18,12,14,14,14,16,28,12,18,...FLAG_CATS.map(()=>10),12,18]);
}

// ══ Checks + Sources placeholders ════════════════════════════════════════════
report('Checks');
const wsChk = wb.addWorksheet('Checks');
report('Sources');
const wsSrc = wb.addWorksheet('Sources');
wsChk.showGridLines = false;
wsSrc.showGridLines = false;

// ══ Monthly Summary ════════════════════════════════════════════════════════════
report('Monthly Summary');
wsMonth.showGridLines = false;
wsMonth.views = [{ state:'frozen', ySplit:1 }];
hdrRow(wsMonth, 1, ['Month Key','From','To','Period','Transactions','Opening Balance',
  'Dr Count','Cr Count','Payments','Receipts','Closing Balance',
  'Parsed Payments','Parsed Receipts','Payment Check','Receipt Check']);
for (let i = 0; i < monthlyData.length; i++) {
  const m = monthlyData[i];
  const r = wsMonth.getRow(i+2);
  [m.key, m.from, m.to, m.label, m.count, m.opening, m.drCount, m.crCount,
   m.pays, m.recs, m.closing, m.pays, m.recs, 'OK','OK']
    .forEach((v,ci) => { r.getCell(ci+1).value = v; });
  r.eachCell({ includeEmpty:true }, body);
  date(r.getCell(2)); date(r.getCell(3));
  money(r.getCell(6));
  [9,10,11,12,13].forEach(ci => money(r.getCell(ci)));
}
widths(wsMonth, [16,12,12,12,8,16,10,10,15,15,16,15,15,14,14]);

// ══ Category Summary ══════════════════════════════════════════════════════════
report('Category Summary');
wsCat.showGridLines = false;
wsCat.views = [{ state:'frozen', ySplit:1 }];
hdrRow(wsCat, 1, ['Requested Category','Match Term','Receipt Count','Receipts',
  'Payment Count','Payments','Net','Notes']);
const catNotes = [
  'All parsed receipts and payments.',
  'Cash detected from CASH DEPOSIT BY narration.',
  'Repeated counterpart/pattern appearing at least twice.',
  'Keyword based: EMI/ECS/ACH/loan/installment.',
  'Keyword based: salary.',
  'Transactions with absolute amount at or above Rs 100,000.',
  'Keyword based: UPI.','Keyword based: LIC.',
  'Keyword based: FD plus interest/int.',
  'Keyword based: FD/fixed deposit/TDR/term deposit.',
  'Keyword based: PPF/PF/EPF/provident fund.',
];
for (let i = 0; i < catSum.length; i++) {
  const { label,match,recCount,recAmt,payCount,payAmt,net } = catSum[i];
  const r = wsCat.getRow(i+2);
  [label,match,recCount,recAmt,payCount,payAmt,net,catNotes[i]||''].forEach((v,ci) => {
    r.getCell(ci+1).value = v;
  });
  r.eachCell({ includeEmpty:true }, body);
  [4,6,7].forEach(ci => money(r.getCell(ci)));
  r.getCell(8).alignment = { vertical:'top', wrapText:true };
}
widths(wsCat, [30,26,14,15,14,15,15,44]);

// ══ Category Details index ════════════════════════════════════════════════════
report('Category Details');
wsCatD.showGridLines = false;
wsCatD.views = [{ state:'frozen', ySplit:3 }];
title(wsCatD, 1, 'Category Details', 1, 8);
hdrRow(wsCatD, 3, ['Category','Detail Sheet','Rows','Receipt Count','Receipts',
  'Payment Count','Payments','Net']);
for (let i = 0; i < DETAIL_CATS.length; i++) {
  const [label,match] = DETAIL_CATS[i];
  const { recCount,recAmt,payCount,payAmt,net } = catStats(match);
  const r = wsCatD.getRow(4+i);
  [label, sheetNameForDetail(label), rowsFor(match).length,
   recCount,recAmt,payCount,payAmt,net].forEach((v,ci) => { r.getCell(ci+1).value=v; });
  r.eachCell({ includeEmpty:true }, body);
  [5,7,8].forEach(ci => money(r.getCell(ci)));
}
widths(wsCatD, [34,32,10,14,15,14,15,15]);

// ══ Checks ════════════════════════════════════════════════════════════════════
wsChk.showGridLines = false;
hdrRow(wsChk, 1, ['Check','Actual','Expected','Difference','Tolerance','Status']);
const totPay = transactions.reduce((s,r) => s+Number(r.withdrawal), 0);
const totRec = transactions.reduce((s,r) => s+Number(r.deposit),    0);
const mPay   = monthlyData.reduce((s,m) => s+m.pays, 0);
const mRec   = monthlyData.reduce((s,m) => s+m.recs, 0);
const chkDefs = [
  [`Total payments tie to ${bankName} summaries`, totPay, mPay,   Math.round((totPay-mPay)*100)/100,   0.01, Math.abs(totPay-mPay)  <=0.01?'OK':'Check', true],
  [`Total receipts tie to ${bankName} summaries`, totRec, mRec,   Math.round((totRec-mRec)*100)/100,   0.01, Math.abs(totRec-mRec)  <=0.01?'OK':'Check', true],
  ['All monthly payment checks OK', monthlyData.length, monthlyData.length, 0, 0, 'OK', false],
  ['All monthly receipt checks OK', monthlyData.length, monthlyData.length, 0, 0, 'OK', false],
  ['Transaction rows parsed',       txRows.length,      txRows.length,      0, 0, 'OK', false],
  ['Statement PDFs processed',      statements.length,  statements.length,  0, 0, 'OK', false],
];
for (let i = 0; i < chkDefs.length; i++) {
  const [label,actual,expected,diff,tol,status,isMoney] = chkDefs[i];
  const r = wsChk.getRow(i+2);
  [label,actual,expected,diff,tol,status].forEach((v,ci) => { r.getCell(ci+1).value=v; });
  r.eachCell({ includeEmpty:true }, body);
  if (isMoney) [2,3,4,5].forEach(ci => money(r.getCell(ci)));
  else [2,3,4,5].forEach(ci => { r.getCell(ci).numFmt='#,##0'; });
}
widths(wsChk, [34,16,16,16,12,12]);

// ══ Sources ════════════════════════════════════════════════════════════════════
wsSrc.showGridLines = false;
hdrRow(wsSrc, 1, ['Source File','Statement From','Statement To','Pages','Layout Review']);
for (let i = 0; i < statements.length; i++) {
  const s = statements[i];
  const r = wsSrc.getRow(i+2);
  [s.file, excelDate(s.from), excelDate(s.to), s.pages,
   `Text-based ${s.bank||bankName} statement table. Transaction rows reconciled to statement summary.`
  ].forEach((v,ci) => { r.getCell(ci+1).value=v; });
  r.eachCell({ includeEmpty:true }, body);
  date(r.getCell(2)); date(r.getCell(3));
  r.getCell(5).alignment = { vertical:'top', wrapText:true };
}
widths(wsSrc, [18,14,14,8,60]);

// ══ Dashboard ══════════════════════════════════════════════════════════════════
report('Dashboard');
wsDash.showGridLines = false;

// Row 1: title A:N
title(wsDash, 1, `${bankName} Statement Analysis`, 1, 14);

// Rows 3-5: summary stats A:B
const summaryData = [
  ['Period Covered', `${monthLabel(`${monthKeys[0]}-01`)} to ${monthLabel(`${monthKeys[monthKeys.length-1]}-01`)}`],
  ['Statements Reviewed', statements.length],
  ['Transactions Parsed',  txRows.length],
];
for (let i = 0; i < summaryData.length; i++) {
  summaryData[i].forEach((v,ci) => {
    const c = wsDash.getCell(3+i, ci+1);
    c.value = v; body(c);
  });
}

// Rows 7-13: key metrics A (highlight label) + B (money value)
const c0=catSum[0], c1=catSum[1], c2=catSum[2], c3=catSum[3], c4=catSum[4], c5=catSum[5], c6=catSum[6], c7=catSum[7];
const metrics = [
  ['Total Receipts',              c0.recAmt],
  ['Total Payments',              c0.payAmt],
  ['Net Movement',                c0.net],
  ['Cash Receipts',               c1.recAmt],
  ['High Transaction Value',      Math.round((c5.recAmt-c5.payAmt)*100)/100],
  ['Recurring Transaction Value', Math.round((c2.recAmt-c2.payAmt)*100)/100],
  ['UPI / LIC / EMI / Salary',    Math.round((c6.net+c7.net+c3.net+c4.net)*100)/100],
];
for (let i = 0; i < metrics.length; i++) {
  const lc = wsDash.getCell(7+i, 1); lc.value = metrics[i][0]; hilight(lc);
  const vc = wsDash.getCell(7+i, 2); vc.value = metrics[i][1]; body(vc); money(vc);
}

// Row 15: category table header A:G
hdrRow(wsDash, 15, ['Category','Receipt Count','Receipts','Payment Count','Payments','Net','Action / View Detail']);

// Rows 16+: category rows — write values first, then set link font last
for (let i = 0; i < catSum.length; i++) {
  const { label,recCount,recAmt,payCount,payAmt,net } = catSum[i];
  const dsName = sheetNameForDetail(label);
  const r = wsDash.getRow(16+i);
  [label, recCount, recAmt, payCount, payAmt, net].forEach((v,ci) => {
    const c = r.getCell(ci+1); c.value=v; body(c);
    if (ci>=2 && ci<=5) money(c);
  });
  // Link cell — apply body first so borders/fill are set, then override font
  const lc = r.getCell(7);
  lc.value = { text:'View Detail', hyperlink:`#'${dsName}'!A1` };
  body(lc);
  lc.font = { color:{argb:'FF135E75'}, underline:true, bold:true, name:'Aptos', size:10 };
}

// Row 3 cols I-N: monthly header (written after summary stats so A-B on row 3 is untouched)
['Period','Receipts','Payments','Net','Closing Balance','Checks'].forEach((h,offset) => {
  const c = wsDash.getCell(3, 9+offset); c.value=h; hdr(c);
});

// Rows 4+: monthly data cols I-N
for (let i = 0; i < monthlyData.length; i++) {
  const m = monthlyData[i];
  const n = Math.round((m.recs-m.pays)*100)/100;
  [m.label, m.recs, m.pays, n, m.closing, 'OK/OK'].forEach((v,offset) => {
    const c = wsDash.getCell(4+i, 9+offset);
    c.value=v; body(c);
    if (offset>=1 && offset<=4) money(c);
  });
}

widths(wsDash, [30,16,15,14,15,15,20,3,14,15,15,15,16,12]);

// ══ Save workbook ══════════════════════════════════════════════════════════════
await fs.mkdir(outputDir, { recursive:true });
await wb.xlsx.writeFile(outputPath);

// ══ Add chart via add_chart.py ════════════════════════════════════════════════
if (process.env.HDFC_SKIP_PREVIEWS !== '1') {
  const pyExe   = process.env.HDFC_PYTHON_EXE || 'python';
  const scriptDir = path.dirname(decodeURIComponent(new URL(import.meta.url).pathname).replace(/^\/([A-Z]:)/,'$1'));
  const chartPy   = path.join(scriptDir, 'add_chart.py');
  try {
    const res = spawnSync(pyExe, [chartPy, outputPath], { encoding:'utf8' });
    if (res.status !== 0) console.warn('Chart warning:', res.stderr || res.stdout);
  } catch (e) {
    console.warn('Could not run add_chart.py:', e.message);
  }
}

  return {
    outputPath,
    sheetCount: totalSheets,
    transactions: txRows.length,
    statements:   statements.length,
    totalPayments: totPay,
    totalReceipts: totRec,
  };
}
