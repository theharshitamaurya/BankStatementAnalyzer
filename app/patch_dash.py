import re

with open('build_hdfc_workbook.mjs', 'r', encoding='utf8') as f:
    content = f.read()

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

// Row 4+: KPI Cards grid (A to H)
const catByLabel = Object.fromEntries(catSum.map(c => [c.label, c]));
const cTotal = catByLabel['Total'];
const cCash = catByLabel['Cash'];
const cSalary = catByLabel['Salary'];
const cUPI = catByLabel['UPI'];
const cRecurring = catByLabel['Recurring Transaction'];
const cEMI = catByLabel['EMI'];
const cLIC = catByLabel['LIC'];
const cFD = catByLabel['FD Deposit and withdrawals'];
const cFDInt = catByLabel['FD interest'];
const cMF = catByLabel['Mutual Fund / Investment'];
const cHigh = catByLabel['High Transaction'];

const cards = [
  { title: 'Total Receipts', val: cTotal.recAmt },
  { title: 'Total Payments', val: cTotal.payAmt },
  { title: 'Net Movement', val: cTotal.net },
  { title: 'Cash Receipts', val: cCash.recAmt },
  { title: 'Cash Payments', val: cCash.payAmt },
  { title: 'Salary (Receipts)', val: cSalary.recAmt },
  { title: 'UPI (Net)', val: cUPI.net },
  { title: 'Recurring Tx (Net)', val: cRecurring.net },
  { title: 'EMI (Payments)', val: cEMI.payAmt },
  { title: 'LIC (Payments)', val: cLIC.payAmt },
  { title: 'FD Activity (Net)', val: cFD.net + cFDInt.net },
  { title: 'Mutual Funds (Net)', val: cMF.net },
  { title: 'High Value Tx (Net)', val: cHigh.net },
  { title: 'Quick Navigation', val: 'Scroll Down ↓', isNav: true }
];

let r = 4;
for (let i = 0; i < cards.length; i++) {
  const colIndex = (i % 4) * 2 + 1; // 1, 3, 5, 7
  if (i > 0 && i % 4 === 0) {
    r += 3; // Space between rows
  }
  
  // Merge Title
  wsDash.mergeCells(r, colIndex, r, colIndex + 1);
  const titleC = wsDash.getCell(r, colIndex);
  titleC.value = cards[i].title;
  titleC.fill = { type:'pattern', pattern:'solid', fgColor:{argb:HEADER_BG} };
  titleC.font = { bold:true, color:{argb:DARK_BLUE}, name:'Aptos', size:10 };
  titleC.alignment = { horizontal:'center', vertical:'middle' };
  titleC.border = ab(B_DARK);
  wsDash.getRow(r).height = 20;
  
  // Merge Value
  wsDash.mergeCells(r+1, colIndex, r+1, colIndex + 1);
  const valC = wsDash.getCell(r+1, colIndex);
  valC.value = cards[i].val;
  valC.fill = { type:'pattern', pattern:'solid', fgColor:{argb:PANEL} };
  valC.alignment = { horizontal:'center', vertical:'middle' };
  valC.border = ab(B_DARK);
  wsDash.getRow(r+1).height = 28;
  
  if (cards[i].isNav) {
      valC.font = { color:{argb:ACCENT}, bold:true, name:'Aptos', size:12 };
  } else {
      valC.font = { name:'Aptos', size:14, bold:Math.abs(cards[i].val) >= 100000, color:{argb:cards[i].val > 0 ? GREEN : (cards[i].val < 0 ? RED : INK)} };
      valC.numFmt = MONEY_FMT;
  }
}

let nextRow = r + 3;

// Category table
sectionTitle(wsDash, nextRow, 'Transaction Categories', 1, 7);
hdrRow(wsDash, nextRow+1, ['Category','Receipt Count','Receipts','Payment Count','Payments','Net','Action / View Detail']);

for (let i = 0; i < catSum.length; i++) {
  const { label,recCount,recAmt,payCount,payAmt,net } = catSum[i];
  const dsName = sheetNameForDetail(label);
  const rIdx = nextRow+2+i;
  const row = wsDash.getRow(rIdx);
  [label, recCount, recAmt, payCount, payAmt, net].forEach((v,ci) => {
    const c = row.getCell(ci+1); c.value=v;
  });
  rowBand(row, i % 2 === 1);
  [2,4].forEach(ci => { integer(row.getCell(ci)); countAlign(row.getCell(ci)); });
  [3,5,6].forEach(ci => moneyAlign(row.getCell(ci)));
  
  const lc = row.getCell(7);
  lc.value = { text:'View Detail', hyperlink:`#'${dsName}'!A1` };
  body(lc);
  lc.font = { color:{argb:'FF135E75'}, underline:true, bold:true, name:'Aptos', size:10 };
}

// Monthly header
sectionTitle(wsDash, 4, 'Monthly Performance', 9, 14);
['Period','Receipts','Payments','Net','Closing Balance','Checks'].forEach((h,offset) => {
  const c = wsDash.getCell(5, 9+offset); c.value=h; hdr(c);
});

// Monthly data
for (let i = 0; i < monthlyData.length; i++) {
  const m = monthlyData[i];
  const n = Math.round((m.recs-m.pays)*100)/100;
  [m.label, m.recs, m.pays, n, m.closing, 'OK/OK'].forEach((v,offset) => {
    const c = wsDash.getCell(6+i, 9+offset);
    c.value=v; body(c);
    if (offset>=1 && offset<=4) money(c);
  });
}

widths(wsDash, [20, 16, 20, 16, 20, 16, 20, 3, 14, 15, 15, 15, 16, 12]);
"""

content = re.sub(r'// ══ Dashboard ══════════════════════════════════════════════════════════════════.*?widths\(wsDash, \[.*?\]\);', new_dash, content, flags=re.DOTALL)

with open('build_hdfc_workbook.mjs', 'w', encoding='utf8') as f:
    f.write(content)
