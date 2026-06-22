import sys
import openpyxl
from openpyxl.chart import BarChart, Reference

file_path = sys.argv[1]
wb = openpyxl.load_workbook(file_path)

if "Dashboard" in wb.sheetnames:
    ws = wb["Dashboard"]
    
    # Find the number of monthly rows. It starts at row 4.
    max_row = 3
    while ws.cell(row=max_row+1, column=9).value is not None:
        max_row += 1
        
    if max_row >= 4:
        chart = BarChart()
        chart.type = "col"
        chart.style = 10
        chart.title = "Receipts and Payments by Month"
        
        # Data is in columns 10 (Receipts) and 11 (Payments)
        data = Reference(ws, min_col=10, min_row=3, max_col=11, max_row=max_row)
        cats = Reference(ws, min_col=9, min_row=4, max_row=max_row)
        
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        
        chart.width = 15
        chart.height = 7.5
        
        # Position chart at I16
        ws.add_chart(chart, "I16")

# Ensure calculation is set to auto so formulas evaluate
if wb.calculation:
    wb.calculation.calcMode = 'auto'
    wb.calculation.fullCalcOnLoad = True

wb.save(file_path)
