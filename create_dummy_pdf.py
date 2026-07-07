from fpdf import FPDF
pdf = FPDF()
pdf.add_page()
pdf.set_font("Arial", size=15)
pdf.cell(200, 10, txt="Hello World, this is a test PDF for context upload.", ln=1, align='C')
pdf.output("private/test_document.pdf")
