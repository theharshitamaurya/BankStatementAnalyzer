import sys
import re

with open('build_hdfc_workbook.mjs', 'r', encoding='utf8') as f:
    content = f.read()

# 1. Update Title function to be more compact
content = content.replace("ws.getRow(rowNum).height = 34;", "ws.getRow(rowNum).height = 24;")
content = content.replace("size:18", "size:14")

# 2. Update Detail Sheets
new_detail = """  ws.views = [{ state:'frozen', ySplit:2 }];
  const dRows   = rowsFor(match);
  const dHdrs   = [...TX_HDRS, 'View Source Row'];
  const dEnd    = dHdrs.length;

  // Row 1: Compact Toolbar
  ws.getRow(1).height = 24;
  ws.mergeCells(1, 1, 1, dEnd - 2);
  const titleCell = ws.getCell(1, 1);
  titleCell.value = `${label} Transactions (${dRows.length} rows)`;
  titleCell.fill = { type:'pattern', pattern:'solid', fgColor:{argb:DARK_BLUE} };
  titleCell.font = { bold:true, color:{argb:WHITE}, name:'Aptos Display', size:14 };
  titleCell.alignment = { horizontal:'left', vertical:'middle' };
  
  const backCell = ws.getCell(1, dEnd - 1);
  ws.mergeCells(1, dEnd - 1, 1, dEnd);
  returnButton(backCell);
  
  // Row 2: header
  hdrRow(ws, 2, dHdrs);

  // Data rows
  for (let di = 0; di < dRows.length; di++) {
    const data = dRows[di];
    const r    = ws.getRow(3+di);
    data.forEach((v,ci) => { r.getCell(ci+1).value = v; });
    rowBand(r, di % 2 === 1);
    const lc = r.getCell(dEnd);
    actionButton(lc, 'Source Row', `#'Transactions'!A${data[0]+1}`);
    [3,4,5,6,TX_END].forEach(ci => date(r.getCell(ci)));
    [10,11,12,13].forEach(ci => moneyAlign(r.getCell(ci)));
    r.getCell(7).alignment = { vertical:'top', wrapText:true };
  }
  if (!dRows.length) ws.getCell('A3').value = 'No matching transactions.';
  widths(ws, [8,16,14,14,12,12,44,18,12,14,14,14,16,28,12,18,...FLAG_CATS.map(()=>10),12,18]);
}"""

content = re.sub(r'ws\.views = \[\{ state:\'frozen\', ySplit:4 \}\];.*?widths\(ws,.*?\}\s*', new_detail + '\n', content, flags=re.DOTALL)

# 3. Update Dashboard
new_dash = """// ══ Dashboard ══════════════════════════════════════════════════════════════════
report('Dashboard');
wsDash.showGridLines = false;
wsDash.views = [{ state:'frozen', ySplit:1 }];

// Row 1: title A:N
wsDash.getRow(1).height = 24;
wsDash.mergeCells(1, 1, 1, 14);
const titleCell = wsDash.getCell(1, 1);
titleCell.value = `${bankName} Statement Analysis`;
titleCell.fill = { type:'pattern', pattern:'solid', fgColor:{argb:DARK_BLUE} };
titleCell.font = { bold:true, color:{argb:WHITE}, name:'Aptos Display', size:14 };
titleCell.alignment = { horizontal:'center', vertical:'middle' };

// Row 2: Customer Information & Summary
wsDash.getRow(2).height = 24;
['Period Covered:', `${monthLabel(`${monthKeys[0]}-01`)} to ${monthLabel(`${monthKeys[monthKeys.length-1]}-01`)}`, 
 'Statements:', statements.length, 
 'Transactions:', txRows.length].forEach((v, ci) => {
   const c = wsDash.getCell(2, ci+1);
   c.value = v;
   ci % 2 === 0 ? hilight(c) : body(c);
   if (ci % 2 === 1) c.alignment = { horizontal:'center', vertical:'middle' };
});

// Row 3: Summary KPI Cards
const catByLabel = Object.fromEntries(catSum.map(c => [c.label, c]));
const c0 = catByLabel.Total, c1 = catByLabel.Cash, c2 = catByLabel['Recurring Transaction'];
const c3 = catByLabel.EMI, c4 = catByLabel.Salary, c5 = catByLabel['High Transaction'];
const cUpi = catByLabel.UPI, cImps = catByLabel.IMPS, cLic = catByLabel.LIC;

const metrics = [
  ['Total Receipts', c0.recAmt],
  ['Total Payments', c0.payAmt],
  ['Net Movement', c0.net],
  ['Cash Receipts', c1.recAmt],
  ['High Tx Value', Math.round((c5.recAmt-c5.payAmt)*100)/100],
  ['Recurring Tx', Math.round((c2.recAmt-c2.payAmt)*100)/100],
  ['UPI/IMPS/LIC/EMI/Salary', Math.round((cUpi.net+cImps.net+cLic.net+c3.net+c4.net)*100)/100],
];

wsDash.getRow(3).height = 26;
for (let i = 0; i < metrics.length; i++) {
  const cTitle = wsDash.getCell(3, i*2 + 1);
  cTitle.value = metrics[i][0];
  hilight(cTitle);
  const cVal = wsDash.getCell(3, i*2 + 2);
  cVal.value = metrics[i][1];
  body(cVal);
  moneyAlign(cVal);
}

// Row 5: category table header A:G
sectionTitle(wsDash, 5, 'Transaction Categories', 1, 7);
hdrRow(wsDash, 6, ['Category','Receipt Count','Receipts','Payment Count','Payments','Net','Action / View Detail']);

// Rows 7+: category rows
for (let i = 0; i < catSum.length; i++) {
  const { label,recCount,recAmt,payCount,payAmt,net } = catSum[i];
  const dsName = sheetNameForDetail(label);
  const r = wsDash.getRow(7+i);
  [label, recCount, recAmt, payCount, payAmt, net].forEach((v,ci) => {
    const c = r.getCell(ci+1); c.value=v;
  });
  rowBand(r, i % 2 === 1);
  [2,4].forEach(ci => { integer(r.getCell(ci)); countAlign(r.getCell(ci)); });
  [3,5,6].forEach(ci => moneyAlign(r.getCell(ci)));
  
  const lc = r.getCell(7);
  lc.value = { text:'View Detail', hyperlink:`#'${dsName}'!A1` };
  body(lc);
  lc.font = { color:{argb:'FF135E75'}, underline:true, bold:true, name:'Aptos', size:10 };
}

// Row 5 cols I-N: monthly header
sectionTitle(wsDash, 5, 'Monthly Performance', 9, 14);
['Period','Receipts','Payments','Net','Closing Balance','Checks'].forEach((h,offset) => {
  const c = wsDash.getCell(6, 9+offset); c.value=h; hdr(c);
});

// Rows 7+: monthly data cols I-N
for (let i = 0; i < monthlyData.length; i++) {
  const m = monthlyData[i];
  const n = Math.round((m.recs-m.pays)*100)/100;
  [m.label, m.recs, m.pays, n, m.closing, 'OK/OK'].forEach((v,offset) => {
    const c = wsDash.getCell(7+i, 9+offset);
    c.value=v; body(c);
    if (offset>=1 && offset<=4) money(c);
  });
}

widths(wsDash, [20, 16, 20, 16, 20, 16, 20, 3, 14, 15, 15, 15, 16, 12]);
"""

content = re.sub(r'// ══ Dashboard ══════════════════════════════════════════════════════════════════.*?widths\(wsDash, \[.*?\]\);', new_dash, content, flags=re.DOTALL)

with open('build_hdfc_workbook.mjs', 'w', encoding='utf8') as f:
    f.write(content)
