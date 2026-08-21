# -*- coding: utf-8 -*-
import base64
import io
import logging

from datetime import date

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependencies (PDF / Excel) – fail gracefully at import time
# ---------------------------------------------------------------------------
try:
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    REPORTLAB_OK = True
except ImportError:
    REPORTLAB_OK = False

try:
    import xlsxwriter
    XLSXWRITER_OK = True
except ImportError:
    XLSXWRITER_OK = False


class GSTR3BReport(models.TransientModel):
    _name = 'gstr3b.report'
    _description = 'GSTR-3B Report'

    # ── Filter fields ─────────────────────────────────────────────────────────
    date_from = fields.Date(
        string='From',
        required=True,
        default=lambda self: date.today().replace(day=1),
    )
    date_to = fields.Date(
        string='To',
        required=True,
        default=fields.Date.today,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Branch / Warehouse',
        domain="[('company_id', '=', company_id)]",
    )

    # ── Output fields ─────────────────────────────────────────────────────────
    report_data = fields.Html(string='Report Preview', readonly=True)
    report_file_pdf = fields.Binary('PDF File', readonly=True)
    report_file_pdf_name = fields.Char('PDF File Name', readonly=True)
    report_file_excel = fields.Binary('Excel File', readonly=True)
    report_file_excel_name = fields.Char('Excel File Name', readonly=True)

    # =========================================================================
    # Private helpers
    # =========================================================================

    def _classify_tax_group(self, tax_group):
        """Classify a tax group dynamically into igst/cgst/sgst/cess based on name."""
        name = (tax_group.name or '').upper().strip()
        if 'IGST' in name:
            return 'igst'
        if 'CGST' in name:
            return 'cgst'
        if 'SGST' in name or 'UTGST' in name:
            return 'sgst'
        if 'CESS' in name:
            return 'cess'
        return None

    def _get_gstin_field(self):
        """Determine field name on account.move for customer's GSTIN."""
        if 'l10n_in_gstin' in self.env['account.move']._fields:
            return 'l10n_in_gstin'
        elif 'vat' in self.env['account.move']._fields:
            return 'vat'
        return 'partner_id.vat'

    def _get_company_state_tin(self):
        """Determine the company state's TIN code dynamically."""
        company = self.company_id
        # 1. Try from VAT / GSTIN first two digits
        company_vat = company.partner_id.vat or company.vat or ''
        if company_vat and len(company_vat) >= 2 and company_vat[:2].isdigit():
            return int(company_vat[:2])
        # 2. Try from company's partner state's l10n_in_tin
        state = company.partner_id.state_id or company.state_id
        if state and hasattr(state, 'l10n_in_tin') and state.l10n_in_tin:
            try:
                return int(state.l10n_in_tin)
            except ValueError:
                pass
        # 3. Fallback default (32 = Kerala)
        return 32

    def _base_invoice_domain(self, move_type, extra=None):
        """Build a base domain for account.move searches."""
        domain = [
            ('move_type', '=', move_type),
            ('state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
            ('invoice_date', '>=', self.date_from),
            ('invoice_date', '<=', self.date_to),
        ]
        if self.warehouse_id:
            # Since warehouse_id is not a standard field on account.move, we resolve it
            # via stock.valuation.layer and stock.move.
            svl_moves = self.env['stock.valuation.layer'].search([
                ('stock_move_id.warehouse_id', '=', self.warehouse_id.id),
                ('account_move_id', '!=', False)
            ])
            allowed_move_ids = svl_moves.mapped('account_move_id').ids

            # Also check direct stock_move_id relation if any exists on account.move
            direct_moves = self.env['account.move'].search([
                ('stock_move_id.warehouse_id', '=', self.warehouse_id.id),
                ('move_type', '=', move_type),
                ('state', '=', 'posted'),
                ('company_id', '=', self.company_id.id),
                ('invoice_date', '>=', self.date_from),
                ('invoice_date', '<=', self.date_to),
            ])
            allowed_move_ids = list(set(allowed_move_ids + direct_moves.ids))

            domain += [('id', 'in', allowed_move_ids)]
        if extra:
            domain += extra
        return domain

    def _sum_lines(self, moves):
        """Sum price_subtotal of all invoice lines across *moves*."""
        return sum(
            line.price_subtotal
            for move in moves
            for line in move.invoice_line_ids
        )

    def _collect_taxes(self, moves, sign=1):
        """
        Return dict with igst/cgst/sgst/cess totals from posted tax lines.
        *sign* should be +1 for sales (credit the output tax) and +1 for
        purchases (debit the input tax); the balance direction handles the rest.
        """
        igst = cgst = sgst = cess = 0.0
        for move in moves:
            for tl in move.line_ids.filtered(lambda l: l.tax_line_id):
                category = self._classify_tax_group(tl.tax_line_id.tax_group_id)
                if not category:
                    continue
                # For sales:
                # - invoice tax lines are credits (negative balance) -> we want positive output tax.
                # - refund tax lines are debits (positive balance) -> we want to reduce the output tax.
                # So we can use the invoice type/refund type or just net them out correctly.
                # Taking abs(tl.balance):
                amt = abs(tl.balance)
                if move.move_type == 'out_refund':
                    amt = -amt

                if category == 'igst':
                    igst += amt
                elif category == 'cgst':
                    cgst += amt
                elif category == 'sgst':
                    sgst += amt
                elif category == 'cess':
                    cess += amt
        return {'igst': igst, 'cgst': cgst, 'sgst': sgst, 'cess': cess}

    # =========================================================================
    # Table 3.1 – Outward Supplies
    # =========================================================================

    def _get_table_3_1_data(self):
        """
        Compute Table 3.1 outward supply totals.

        Categories:
          B2B  – registered buyers (GSTIN present)
          B2CL – unregistered, inter-state, > threshold
          B2CS – all remaining (intra-state or small inter-state)
        """
        gstin_field = self._get_gstin_field()
        threshold = 250000.0
        home_tin = self._get_company_state_tin()

        # ── B2B ──────────────────────────────────────────────────────────────
        b2b_inv = self.env['account.move'].search(
            self._base_invoice_domain('out_invoice', [(gstin_field, '!=', False)])
        )
        b2b_cn = self.env['account.move'].search(
            self._base_invoice_domain('out_refund', [(gstin_field, '!=', False)])
        )
        b2b_taxable = self._sum_lines(b2b_inv) - self._sum_lines(b2b_cn)

        # ── B2CL ─────────────────────────────────────────────────────────────
        b2cl_inv = self.env['account.move'].search(
            self._base_invoice_domain('out_invoice', [
                (gstin_field, '=', False),
                ('amount_total', '>', threshold),
                ('partner_id.state_id.l10n_in_tin', 'not in', [str(home_tin), home_tin]),
            ])
        )
        b2cl_cn = self.env['account.move'].search(
            self._base_invoice_domain('out_refund', [
                (gstin_field, '=', False),
                ('amount_total', '>', threshold),
                ('partner_id.state_id.l10n_in_tin', 'not in', [str(home_tin), home_tin]),
            ])
        )
        b2cl_taxable = self._sum_lines(b2cl_inv) - self._sum_lines(b2cl_cn)

        # ── B2CS ─────────────────────────────────────────────────────────────
        excluded_inv_ids = (b2b_inv + b2cl_inv).ids
        excluded_cn_ids = (b2b_cn + b2cl_cn).ids

        b2cs_inv = self.env['account.move'].search(
            self._base_invoice_domain('out_invoice', [
                (gstin_field, '=', False),
                ('id', 'not in', excluded_inv_ids),
            ])
        )
        b2cs_cn = self.env['account.move'].search(
            self._base_invoice_domain('out_refund', [
                (gstin_field, '=', False),
                ('id', 'not in', excluded_cn_ids),
            ])
        )
        b2cs_taxable = self._sum_lines(b2cs_inv) - self._sum_lines(b2cs_cn)

        total_taxable = b2b_taxable + b2cl_taxable + b2cs_taxable

        # ── Tax amounts from ALL outward moves ────────────────────────────────
        all_out = b2b_inv + b2b_cn + b2cl_inv + b2cl_cn + b2cs_inv + b2cs_cn
        taxes = self._collect_taxes(all_out, sign=1)

        return {
            'total_taxable_value': total_taxable,
            **taxes,
        }

    # =========================================================================
    # Table 4 – Inward Supplies / ITC
    # =========================================================================

    def _get_table_4_data(self):
        """Compute Table 4 ITC totals from purchase invoices and credit notes."""
        purchases = self.env['account.move'].search(
            self._base_invoice_domain('in_invoice')
        )
        pur_refunds = self.env['account.move'].search(
            self._base_invoice_domain('in_refund')
        )

        igst = cgst = sgst = cess = 0.0
        for move in purchases:
            for tl in move.line_ids.filtered(lambda l: l.tax_line_id):
                category = self._classify_tax_group(tl.tax_line_id.tax_group_id)
                if category == 'igst':
                    igst += abs(tl.balance)
                elif category == 'cgst':
                    cgst += abs(tl.balance)
                elif category == 'sgst':
                    sgst += abs(tl.balance)
                elif category == 'cess':
                    cess += abs(tl.balance)

        # Subtract credit note ITC reversals (to net out returned goods)
        for move in pur_refunds:
            for tl in move.line_ids.filtered(lambda l: l.tax_line_id):
                category = self._classify_tax_group(tl.tax_line_id.tax_group_id)
                if category == 'igst':
                    igst -= abs(tl.balance)
                elif category == 'cgst':
                    cgst -= abs(tl.balance)
                elif category == 'sgst':
                    sgst -= abs(tl.balance)
                elif category == 'cess':
                    cess -= abs(tl.balance)

        return {'igst': igst, 'cgst': cgst, 'sgst': sgst, 'cess': cess}

    # =========================================================================
    # Report header info
    # =========================================================================

    def _report_header_info(self):
        company_name = self.company_id.name
        date_range = f"{self.date_from.strftime('%d-%b-%Y')} to {self.date_to.strftime('%d-%b-%Y')}"
        branch = self.warehouse_id.name if self.warehouse_id else ''
        return company_name, date_range, branch

    # =========================================================================
    # HTML Preview
    # =========================================================================

    def _generate_html_report(self):
        d31 = self._get_table_3_1_data()
        d4 = self._get_table_4_data()
        company_name, date_range, branch = self._report_header_info()

        tv = d31['total_taxable_value']
        io_ = d31['igst']
        co = d31['cgst']
        so = d31['sgst']
        ce_o = d31['cess']

        ii = d4['igst']
        ci = d4['cgst']
        si = d4['sgst']
        ce_i = d4['cess']

        def fmt(v):
            return f"{v:,.2f}"

        def row_zero():
            return '<td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>' * 5

        html = f"""
<div style="font-family:Arial,sans-serif;font-size:13px;">
  <h2 style="text-align:center;margin-bottom:2px;">{company_name}</h2>
  <h3 style="text-align:center;margin-top:0;">GSTR-3B Report</h3>
  <p style="text-align:center;margin:4px 0;">Period: <b>{date_range}</b>
     {"&nbsp;&nbsp;|&nbsp;&nbsp;Branch: <b>" + branch + "</b>" if branch else ""}
  </p>

  <h4 style="margin-top:24px;">3.1 &ndash; Outward Supplies (Sales)</h4>
  <table style="width:100%;border-collapse:collapse;margin-top:8px;">
    <thead>
      <tr style="background:#e8e8e8;">
        <th style="border:1px solid #000;padding:8px;text-align:center;width:38%;">Nature of Supplies</th>
        <th style="border:1px solid #000;padding:8px;text-align:center;">Total Taxable Value (₹)</th>
        <th style="border:1px solid #000;padding:8px;text-align:center;">Integrated Tax (₹)</th>
        <th style="border:1px solid #000;padding:8px;text-align:center;">Central Tax (₹)</th>
        <th style="border:1px solid #000;padding:8px;text-align:center;">State/UT Tax (₹)</th>
        <th style="border:1px solid #000;padding:8px;text-align:center;">Cess (₹)</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td style="border:1px solid #000;padding:6px;">(a) Outward taxable supplies (other than zero rated, nil rated and exempted)</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">{fmt(tv)}</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">{fmt(abs(io_))}</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">{fmt(abs(co))}</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">{fmt(abs(so))}</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">{fmt(ce_o)}</td>
      </tr>
      <tr><td style="border:1px solid #000;padding:6px;">(b) Outward taxable supplies (zero rated)</td>{row_zero()}</tr>
      <tr><td style="border:1px solid #000;padding:6px;">(c) Other outward supplies (nil rated, exempted)</td>{row_zero()}</tr>
      <tr><td style="border:1px solid #000;padding:6px;">(d) Inward supplies liable to reverse charge</td>{row_zero()}</tr>
      <tr><td style="border:1px solid #000;padding:6px;">(e) Non-GST outward supplies</td>{row_zero()}</tr>
    </tbody>
  </table>

  <h4 style="margin-top:32px;">4 &ndash; Eligible ITC (Inward Supplies / Purchases)</h4>
  <table style="width:100%;border-collapse:collapse;margin-top:8px;">
    <thead>
      <tr style="background:#e8e8e8;">
        <th style="border:1px solid #000;padding:8px;text-align:center;width:38%;">Details</th>
        <th style="border:1px solid #000;padding:8px;text-align:center;">Integrated Tax (₹)</th>
        <th style="border:1px solid #000;padding:8px;text-align:center;">Central Tax (₹)</th>
        <th style="border:1px solid #000;padding:8px;text-align:center;">State/UT Tax (₹)</th>
        <th style="border:1px solid #000;padding:8px;text-align:center;">Cess (₹)</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td colspan="5" style="border:1px solid #000;padding:6px;font-weight:bold;background:#f5f5f5;">
          A. ITC Available (whether in full or part)
        </td>
      </tr>
      <tr>
        <td style="border:1px solid #000;padding:6px;">(1) Import of goods</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>
      </tr>
      <tr>
        <td style="border:1px solid #000;padding:6px;">(2) Import of services</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>
      </tr>
      <tr>
        <td style="border:1px solid #000;padding:6px;">(3) Inward supplies liable to reverse charge (other than 1 &amp; 2)</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>
      </tr>
      <tr>
        <td style="border:1px solid #000;padding:6px;">(4) Inward supplies from ISD</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">0.00</td>
      </tr>
      <tr>
        <td style="border:1px solid #000;padding:6px;">(5) All other ITC</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">{fmt(ii)}</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">{fmt(ci)}</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">{fmt(si)}</td>
        <td style="border:1px solid #000;padding:6px;text-align:right;">{fmt(ce_i)}</td>
      </tr>
    </tbody>
  </table>
</div>
"""
        self.report_data = html

    # =========================================================================
    # PDF Export
    # =========================================================================

    def _generate_pdf(self):
        if not REPORTLAB_OK:
            raise UserError(_(
                "ReportLab is not installed. Please install it:\n"
                "pip install reportlab"
            ))

        d31 = self._get_table_3_1_data()
        d4 = self._get_table_4_data()
        company_name, date_range, branch = self._report_header_info()

        tv = d31['total_taxable_value']
        io_ = abs(d31['igst'])
        co = abs(d31['cgst'])
        so = abs(d31['sgst'])
        ce_o = d31['cess']
        ii = d4['igst']
        ci = d4['cgst']
        si = d4['sgst']
        ce_i = d4['cess']

        def fmt(v):
            return f"{v:,.2f}"

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=30, bottomMargin=30)
        styles = getSampleStyleSheet()
        elements = []

        center = ParagraphStyle('center', alignment=TA_CENTER, fontSize=12, leading=16, spaceAfter=4)
        small = ParagraphStyle('small', fontSize=8, leading=10)

        elements.append(Paragraph(company_name, ParagraphStyle('co', alignment=TA_CENTER, fontSize=14, leading=18, fontName='Helvetica-Bold')))
        elements.append(Paragraph('GSTR-3B Report', center))
        elements.append(Paragraph(f'Period: {date_range}' + (f'  |  Branch: {branch}' if branch else ''), center))
        elements.append(Spacer(1, 16))

        # ── Table 3.1 ─────────────────────────────────────────────────────────
        elements.append(Paragraph('3.1 – Outward Supplies (Sales)', styles['Heading3']))
        col_w = [175, 65, 55, 60, 60, 50]
        out_data = [
            ['Nature of Supplies', 'Total Taxable', 'IGST', 'CGST', 'SGST/UTGST', 'Cess'],
            [Paragraph('(a) Outward taxable supplies (other than zero rated, nil rated and exempted)', small),
             fmt(tv), fmt(io_), fmt(co), fmt(so), fmt(ce_o)],
            [Paragraph('(b) Outward taxable supplies (zero rated)', small), '0.00', '0.00', '0.00', '0.00', '0.00'],
            [Paragraph('(c) Other outward supplies (nil rated, exempted)', small), '0.00', '0.00', '0.00', '0.00', '0.00'],
            [Paragraph('(d) Inward supplies liable to reverse charge', small), '0.00', '0.00', '0.00', '0.00', '0.00'],
            [Paragraph('(e) Non-GST outward supplies', small), '0.00', '0.00', '0.00', '0.00', '0.00'],
        ]
        t_out = Table(out_data, colWidths=col_w, hAlign='CENTER')
        t_out.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#D3D3D3')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9F9F9')]),
        ]))
        elements.append(t_out)
        elements.append(Spacer(1, 20))

        # ── Table 4 ──────────────────────────────────────────────────────────
        elements.append(Paragraph('4 – Eligible ITC (Inward Supplies)', styles['Heading3']))
        col_w4 = [215, 75, 65, 75, 65]
        in_data = [
            ['Details', 'IGST', 'CGST', 'SGST/UTGST', 'Cess'],
            ['A. ITC Available (whether in full or part)', '', '', '', ''],
            ['(1) Import of goods', '0.00', '0.00', '0.00', '0.00'],
            ['(2) Import of services', '0.00', '0.00', '0.00', '0.00'],
            ['(3) Inward supplies liable to reverse charge', '0.00', '0.00', '0.00', '0.00'],
            ['(4) Inward supplies from ISD', '0.00', '0.00', '0.00', '0.00'],
            ['(5) All other ITC', fmt(ii), fmt(ci), fmt(si), fmt(ce_i)],
        ]
        t_in = Table(in_data, colWidths=col_w4, hAlign='CENTER')
        t_in.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#D3D3D3')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#EFEFEF')),
            ('SPAN', (0, 1), (-1, 1)),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0, 2), (-1, -1), [colors.white, colors.HexColor('#F9F9F9')]),
        ]))
        elements.append(t_in)

        doc.build(elements)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes

    # =========================================================================
    # Excel Export
    # =========================================================================

    def _generate_excel(self):
        if not XLSXWRITER_OK:
            raise UserError(_(
                "XlsxWriter is not installed. Please install it:\n"
                "pip install xlsxwriter"
            ))

        d31 = self._get_table_3_1_data()
        d4 = self._get_table_4_data()
        company_name, date_range, branch = self._report_header_info()

        tv = d31['total_taxable_value']
        io_ = abs(d31['igst'])
        co = abs(d31['cgst'])
        so = abs(d31['sgst'])
        ce_o = d31['cess']
        ii = d4['igst']
        ci = d4['cgst']
        si = d4['sgst']
        ce_i = d4['cess']

        def fmt(v):
            return f"{v:,.2f}"

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output)
        ws = wb.add_worksheet('GSTR3B Report')

        # Formats
        f_title = wb.add_format({'bold': True, 'font_size': 14, 'align': 'center', 'valign': 'vcenter'})
        f_sub = wb.add_format({'align': 'center', 'border': 1})
        f_hdr = wb.add_format({'bold': True, 'align': 'center', 'bg_color': '#D3D3D3', 'border': 1, 'text_wrap': True})
        f_sect = wb.add_format({'bold': True, 'border': 1, 'bg_color': '#EFEFEF'})
        f_label = wb.add_format({'border': 1, 'align': 'left', 'text_wrap': True})
        f_num = wb.add_format({'border': 1, 'align': 'right', 'num_format': '#,##0.00'})
        f_section_title = wb.add_format({'bold': True, 'font_size': 11})

        ws.set_column('A:A', 70)
        ws.set_column('B:G', 16)
        ws.set_row(0, 22)
        ws.set_row(1, 18)

        # Header
        ws.merge_range('A1:G1', company_name, f_title)
        ws.merge_range('A2:G2', 'GSTR-3B Report', f_title)
        ws.merge_range('A3:G3', f'Period: {date_range}' + (f'  |  Branch: {branch}' if branch else ''), f_sub)

        row = 4  # 0-indexed

        # ── Outward Supplies ─────────────────────────────────────────────────
        ws.merge_range(row, 0, row, 5, '3.1 – Outward Supplies (Sales)', f_section_title)
        row += 1
        for col, h in enumerate(['Nature of Supplies', 'Total Taxable Value (₹)',
                                 'Integrated Tax (₹)', 'Central Tax (₹)',
                                 'State/UT Tax (₹)', 'Cess (₹)']):
            ws.write(row, col, h, f_hdr)
        row += 1

        out_rows = [
            ('(a) Outward taxable supplies (other than zero rated, nil rated and exempted)',
             tv, io_, co, so, ce_o),
            ('(b) Outward taxable supplies (zero rated)', 0, 0, 0, 0, 0),
            ('(c) Other outward supplies (nil rated, exempted)', 0, 0, 0, 0, 0),
            ('(d) Inward supplies liable to reverse charge', 0, 0, 0, 0, 0),
            ('(e) Non-GST outward supplies', 0, 0, 0, 0, 0),
        ]
        for label, *vals in out_rows:
            ws.set_row(row, 30)
            ws.write(row, 0, label, f_label)
            for col, v in enumerate(vals, 1):
                ws.write(row, col, v, f_num)
            row += 1

        row += 1  # spacer

        # ── Inward Supplies / ITC ─────────────────────────────────────────────
        ws.merge_range(row, 0, row, 4, '4 – Eligible ITC (Inward Supplies / Purchases)', f_section_title)
        row += 1
        for col, h in enumerate(['Details', 'Integrated Tax (₹)', 'Central Tax (₹)',
                                 'State/UT Tax (₹)', 'Cess (₹)']):
            ws.write(row, col, h, f_hdr)
        row += 1
        ws.merge_range(row, 0, row, 4, 'A. ITC Available (whether in full or part)', f_sect)
        row += 1

        in_rows = [
            ('(1) Import of goods', 0, 0, 0, 0),
            ('(2) Import of services', 0, 0, 0, 0),
            ('(3) Inward supplies liable to reverse charge (other than 1 & 2)', 0, 0, 0, 0),
            ('(4) Inward supplies from ISD', 0, 0, 0, 0),
            ('(5) All other ITC', ii, ci, si, ce_i),
        ]
        for label, *vals in in_rows:
            ws.write(row, 0, label, f_label)
            for col, v in enumerate(vals, 1):
                ws.write(row, col, v, f_num)
            row += 1

        wb.close()
        output.seek(0)
        return output.read()

    # =========================================================================
    # Public actions
    # =========================================================================

    def action_generate_report(self):
        self.ensure_one()
        self._generate_html_report()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'gstr3b.report',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }

    def action_generate_pdf(self):
        self.ensure_one()
        pdf = self._generate_pdf()
        self.report_file_pdf = base64.b64encode(pdf)
        self.report_file_pdf_name = 'GSTR3B_Report.pdf'
        return {
            'type': 'ir.actions.act_url',
            'url': (
                f'/web/content/?model=gstr3b.report'
                f'&id={self.id}&field=report_file_pdf'
                f'&download=true&filename={self.report_file_pdf_name}'
            ),
            'target': 'new',
        }

    def action_generate_excel(self):
        self.ensure_one()
        excel = self._generate_excel()
        self.report_file_excel = base64.b64encode(excel)
        self.report_file_excel_name = 'GSTR3B_Report.xlsx'
        return {
            'type': 'ir.actions.act_url',
            'url': (
                f'/web/content/?model=gstr3b.report'
                f'&id={self.id}&field=report_file_excel'
                f'&download=true&filename={self.report_file_excel_name}'
            ),
            'target': 'new',
        }