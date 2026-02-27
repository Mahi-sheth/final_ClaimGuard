
from fpdf import FPDF
import io
from datetime import datetime
import re

class PDF(FPDF):
    def header(self):
        # Set font for header - using built-in fonts only
        self.set_font('Helvetica', 'B', 16)
        self.set_text_color(26, 35, 126)  # Navy blue
        self.cell(0, 10, 'ClaimGuard Insurance Report', 0, 1, 'C')
        self.ln(10)
    
    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')
    
    def chapter_title(self, title):
        self.set_font('Helvetica', 'B', 12)
        self.set_text_color(26, 35, 126)
        self.cell(0, 10, title, 0, 1, 'L')
        self.ln(5)
    
    def chapter_body(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(0, 0, 0)
        self.multi_cell(0, 6, text)
        self.ln(4)

def clean_text(text):
    """Clean text for PDF encoding"""
    if not text:
        return ""
    # Replace problematic characters
    text = text.replace('₹', 'Rs. ')
    text = text.replace('–', '-')
    text = text.replace('—', '-')
    text = text.replace('•', '*')
    text = text.replace('…', '...')
    # Remove other non-Latin-1 characters
    text = text.encode('latin-1', 'ignore').decode('latin-1')
    return text

def generate_pdf_report(policy):
    """Generate PDF report matching the sample format"""
    
    pdf = PDF()
    pdf.add_page()
    
    # Policy Information
    pdf.chapter_title('Policy Information')
    
    # Clean text for PDF
    filename = clean_text(policy['filename'])
    policy_id = clean_text(policy['id'])
    upload_time = clean_text(policy['upload_time'])
    policy_type = clean_text(policy['policy_type'])
    
    info_text = f"""File: {filename}
Policy ID: {policy_id}
Upload Date: {upload_time}
Policy Type: {policy_type}"""
    
    pdf.chapter_body(info_text)
    
    # Risk Assessment
    pdf.chapter_title('Risk Assessment')
    
    risks = policy['risks']
    overall_risk = policy.get('overall_risk', 
                            (risks['coverage'] * 0.4 + risks['cost'] * 0.35 + risks['delay'] * 0.25))
    
    risk_text = f"""Claim Coverage Risk: {risks['coverage']}%
Out-of-Pocket Risk: {risks['cost']}%
Claim Delay Risk: {risks['delay']}%
Overall Risk: {overall_risk:.1f}%"""
    
    pdf.chapter_body(risk_text)
    
    # Detected Policy Terms
    pdf.chapter_title('Detected Policy Terms')
    
    financial = policy.get('financial', {})
    co_pay = financial.get('co_pay', 0)
    deductible = financial.get('deductible', 0)
    
    clauses = policy.get('clauses', {})
    exclusion_text = clauses.get('Exclusions', '').lower()
    exclusion_count = 1 if 'exclusion' in exclusion_text or 'not cover' in exclusion_text else 0
    
    terms_text = ""
    if co_pay > 0:
        terms_text += f"- Co-pay: {co_pay}%\n"
    if deductible > 0:
        terms_text += f"- Deductible: Rs {deductible:,}\n"
    terms_text += f"- Exclusions Found: {exclusion_count}"
    
    pdf.chapter_body(terms_text)
    
    # Claim Simulation
    pdf.chapter_title('Claim Simulation Results')
    
    claim_amount = 500000
    insurance_pays = claim_amount
    
    if deductible > 0:
        insurance_pays = max(0, insurance_pays - deductible)
    if co_pay > 0:
        insurance_pays = insurance_pays * (1 - co_pay / 100)
    
    simulation_text = f"""Claim Amount: Rs {claim_amount:,}
Insurance Pays: Rs {int(insurance_pays):,}
You Pay: Rs {int(claim_amount - insurance_pays):,}"""
    
    pdf.chapter_body(simulation_text)
    
    # Key Policy Clauses
    pdf.chapter_title('Key Policy Clauses')
    
    for clause_name, clause_text in clauses.items():
        if clause_text and clause_text != 'Not mentioned in document':
            # Truncate long text
            if len(clause_text) > 100:
                clause_text = clause_text[:100] + '...'
            clean_clause = clean_text(clause_text)
            pdf.set_font('Helvetica', 'B', 9)
            pdf.cell(0, 5, f'{clause_name}:', 0, 1)
            pdf.set_font('Helvetica', '', 9)
            pdf.multi_cell(0, 5, clean_clause)
            pdf.ln(2)
    
    # Output to bytes buffer
    pdf_buffer = io.BytesIO()
    pdf.output(pdf_buffer)
    pdf_buffer.seek(0)
    

from fpdf import FPDF
import io
from datetime import datetime
import re

class PDF(FPDF):
    def header(self):
        # Set font for header - using built-in fonts only
        self.set_font('Helvetica', 'B', 16)
        self.set_text_color(26, 35, 126)  # Navy blue
        self.cell(0, 10, 'ClaimGuard Insurance Report', 0, 1, 'C')
        self.ln(10)
    
    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')
    
    def chapter_title(self, title):
        self.set_font('Helvetica', 'B', 12)
        self.set_text_color(26, 35, 126)
        self.cell(0, 10, title, 0, 1, 'L')
        self.ln(5)
    
    def chapter_body(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(0, 0, 0)
        self.multi_cell(0, 6, text)
        self.ln(4)

def clean_text(text):
    """Clean text for PDF encoding"""
    if not text:
        return ""
    # Replace problematic characters
    text = text.replace('₹', 'Rs. ')
    text = text.replace('–', '-')
    text = text.replace('—', '-')
    text = text.replace('•', '*')
    text = text.replace('…', '...')
    # Remove other non-Latin-1 characters
    text = text.encode('latin-1', 'ignore').decode('latin-1')
    return text

def generate_pdf_report(policy):
    """Generate PDF report matching the sample format"""
    
    pdf = PDF()
    pdf.add_page()
    
    # Policy Information
    pdf.chapter_title('Policy Information')
    
    # Clean text for PDF
    filename = clean_text(policy['filename'])
    policy_id = clean_text(policy['id'])
    upload_time = clean_text(policy['upload_time'])
    policy_type = clean_text(policy['policy_type'])
    
    info_text = f"""File: {filename}
Policy ID: {policy_id}
Upload Date: {upload_time}
Policy Type: {policy_type}"""
    
    pdf.chapter_body(info_text)
    
    # Risk Assessment
    pdf.chapter_title('Risk Assessment')
    
    risks = policy['risks']
    overall_risk = policy.get('overall_risk', 
                            (risks['coverage'] * 0.4 + risks['cost'] * 0.35 + risks['delay'] * 0.25))
    
    risk_text = f"""Claim Coverage Risk: {risks['coverage']}%
Out-of-Pocket Risk: {risks['cost']}%
Claim Delay Risk: {risks['delay']}%
Overall Risk: {overall_risk:.1f}%"""
    
    pdf.chapter_body(risk_text)
    
    # Detected Policy Terms
    pdf.chapter_title('Detected Policy Terms')
    
    financial = policy.get('financial', {})
    co_pay = financial.get('co_pay', 0)
    deductible = financial.get('deductible', 0)
    
    clauses = policy.get('clauses', {})
    exclusion_text = clauses.get('Exclusions', '').lower()
    exclusion_count = 1 if 'exclusion' in exclusion_text or 'not cover' in exclusion_text else 0
    
    terms_text = ""
    if co_pay > 0:
        terms_text += f"- Co-pay: {co_pay}%\n"
    if deductible > 0:
        terms_text += f"- Deductible: Rs {deductible:,}\n"
    terms_text += f"- Exclusions Found: {exclusion_count}"
    
    pdf.chapter_body(terms_text)
    
    # Claim Simulation
    pdf.chapter_title('Claim Simulation Results')
    
    claim_amount = 500000
    insurance_pays = claim_amount
    
    if deductible > 0:
        insurance_pays = max(0, insurance_pays - deductible)
    if co_pay > 0:
        insurance_pays = insurance_pays * (1 - co_pay / 100)
    
    simulation_text = f"""Claim Amount: Rs {claim_amount:,}
Insurance Pays: Rs {int(insurance_pays):,}
You Pay: Rs {int(claim_amount - insurance_pays):,}"""
    
    pdf.chapter_body(simulation_text)
    
    # Key Policy Clauses
    pdf.chapter_title('Key Policy Clauses')
    
    for clause_name, clause_text in clauses.items():
        if clause_text and clause_text != 'Not mentioned in document':
            # Truncate long text
            if len(clause_text) > 100:
                clause_text = clause_text[:100] + '...'
            clean_clause = clean_text(clause_text)
            pdf.set_font('Helvetica', 'B', 9)
            pdf.cell(0, 5, f'{clause_name}:', 0, 1)
            pdf.set_font('Helvetica', '', 9)
            pdf.multi_cell(0, 5, clean_clause)
            pdf.ln(2)
    
    # Output to bytes buffer
    pdf_buffer = io.BytesIO()
    pdf.output(pdf_buffer)
    pdf_buffer.seek(0)
    

    return pdf_buffer