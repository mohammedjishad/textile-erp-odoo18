from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime
from collections import defaultdict
import xlsxwriter
from io import BytesIO
import base64
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import KeepTogether
from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet


class Gstirn1Report(models.TransientModel):
    _name = 'gstirn1.report'
    _rec_name = 'type'

    start_date = fields.Date(string="Start Date", default=lambda self: self._get_default_start_date())
    end_date = fields.Date(string="End Date", default=fields.Date.today)
    report_data = fields.Html(compute='_compute_report_data', default="", sanitize=False)
    display_report_details = fields.Boolean(string='Display Report Details', transient=True)
    warehouse_id = fields.Many2one('stock.warehouse', string="Branch")

    type = fields.Selection([
        ('b2b', 'B2B'),
        ('b2c_large', 'B2C-Large'),
        ('b2c_small', 'B2C-Small'),
        ('d/c_reg_customer', 'Debit/Credit Note - Registered Customer'),
        ('d/c_unreg_customer', 'Debit/Credit Note - UnRegistered Customer'),
        ('hsn', 'HSN'),
        ('tcs_input', 'TCS Input'),
        ('tcs_output', 'TCS Output'),
        # ('doc_summary', 'Document Summary'),
        # ('gstr1_summary', 'GSTR1 Summary'),
    ], string="Type", required=True)

    hsn_type = fields.Selection([('hsn_b2b', 'B 2 B'),
                                 ('hsn_b2c', 'B 2 C'),
                                 ('all', 'All'),
                                 ])

    excel_file = fields.Binary('Excel File', readonly=True)
    excel_file_name = fields.Char('Excel File Name')
    pdf_file = fields.Binary('PDF File', readonly=True)
    pdf_file_name = fields.Char('PDF File Name')
    invoice_details = fields.Text('Invoice Details', compute='_compute_report_data')

    def generate_report(self):
        self.display_report_details = True
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
            'views': [(False, 'form')],
        }

    def _get_default_start_date(self):
        today = datetime.today()
        default_start_date = today.replace(day=1)
        return default_start_date.date()

    # @api.depends('type', 'start_date', 'end_date', 'warehouse_id','hsn_type')
    def _compute_report_data(self):
        for record in self:
            try:
                invoice_details = record._gather_report_data()
                result = record._format_report_data_to_html(invoice_details)
                record.report_data = result if result else ""
            except Exception:
                record.report_data = ""
            record.invoice_details = ""

    def _get_total_tax_rate(self, invoice):
        if not invoice.amount_untaxed:
            return "0%"
        total_tax = invoice.amount_total - invoice.amount_untaxed
        tax_percentage = (total_tax / invoice.amount_untaxed) * 100
        return f"{round(tax_percentage)}%"

    def _gather_report_data(self):
        domain = []
        other_domain = []
        doc_domain = []
        pay_domain = []
        sale_final_data = []
        for rec in self:
            if not rec.start_date or not rec.end_date:
                raise UserError("Please provide both Start Date and End Date.")
            if rec.start_date:
                domain.append(('invoice_date', '>=', rec.start_date))
            if rec.end_date:
                domain.append(('invoice_date', '<=', rec.end_date))
            if rec.warehouse_id:
                domain.append(('warehouse_id', '=', rec.warehouse_id.id))
            if rec.type == 'b2b':
                domain.append(('partner_id.vat', '!=', False))
                domain.append(('move_type', 'in', ['out_invoice']))
                domain.append(('state', '=', 'posted'))
                sale_data = rec.env['account.move'].search(domain, order='invoice_date asc, name asc')
                sale_final_data = []
                sl_no = 1
                for rec in sale_data:
                    line_untaxed_total = sum(line.price_subtotal for line in rec.invoice_line_ids)
                    sale_final_data.append({
                        'sl_no': sl_no,
                        'gstin_customer': rec.partner_id.vat,
                        'customer_name': rec.partner_id.name,
                        'inv_no': rec.name,
                        'date': rec.invoice_date.strftime('%d-%b-%Y') if rec.invoice_date else '',
                        'inv_value': round(rec.amount_total, 2),
                        'place_of_supply': f"{rec.State_id.l10n_in_tin}-{rec.State_id.name}" if rec.State_id else '',
                        'reverse_charge': "N",
                        'inv_type': "Regular",
                        'rate': self._get_total_tax_rate(rec),
                        'taxable_value': round(line_untaxed_total or '', 2)
                    })
                    sl_no += 1
            elif rec.type == 'b2c_large':
                domain.append(('partner_id.vat', '=', False))
                # domain.append(('customer_type', 'in', ['register_customer', 'non_register_customer']))
                domain.append(('move_type', 'in', ['out_invoice']))
                domain.append(('state', '=', 'posted'))
                domain.append(('partner_id.state_id.l10n_in_tin', '!=', '32'))
                domain.append(('amount_total', '>', 250000))
                sale_data = rec.env['account.move'].search(domain, order='invoice_date asc, name asc')
                sale_final_data = []
                sl_no = 1
                for rec in sale_data:
                    line_untaxed_total = sum(line.price_subtotal for line in rec.invoice_line_ids)
                    sale_final_data.append({
                        'sl_no': sl_no,
                        'gstin_customer': rec.partner_id.vat,
                        'customer_name': rec.partner_id.name,
                        'inv_no': rec.name,
                        'date': rec.invoice_date.strftime('%d-%b-%Y') if rec.invoice_date else '',
                        'inv_value': round(rec.amount_total),
                        'place_of_supply': f"{rec.State_id.l10n_in_tin}-{rec.State_id.name}" if rec.State_id else '',
                        'reverse_charge': "N",
                        'inv_type': "Regular",
                        'rate': self._get_total_tax_rate(rec),
                        'taxable_value': round(line_untaxed_total or '', 2)
                    })
                    sl_no += 1
            elif rec.type == 'b2c_small':

                # Helper function to round to nearest standard GST rate
                def round_to_nearest_gst_rate(calculated_rate):
                    """Round to nearest standard GST rate"""
                    if calculated_rate == 0:
                        return 0
                    standard_rates = [0, 5, 12, 18, 28]
                    # Find the closest standard rate
                    nearest_rate = min(standard_rates, key=lambda x: abs(x - calculated_rate))
                    return nearest_rate

                # Identify B2C Large Invoices (to be excluded) - Add date filter for consistency and efficiency
                large_domain = [
                    ('partner_id.vat', '=', False),
                    # ('customer_type', 'in', ['register_customer', 'non_register_customer']),
                    ('move_type', '=', 'out_invoice'),
                    ('state', '=', 'posted'),
                    ('partner_id.state_id.l10n_in_tin', '!=', 32),
                    ('amount_total', '>', 250000)
                ]
                if rec.start_date:
                    large_domain.append(('invoice_date', '>=', rec.start_date))
                if rec.end_date:
                    large_domain.append(('invoice_date', '<=', rec.end_date))
                if rec.warehouse_id:
                    large_domain.append(('warehouse_id', '=', rec.warehouse_id.id))
                sale_all_data = rec.env['account.move'].search(large_domain, order='invoice_date asc')
                b2c_large_ids = sale_all_data.ids

                # Filter B2C Small Invoices
                other_domain = [
                    ('partner_id.vat', '=', False),
                    # ('customer_type', 'in', ['register_customer', 'non_register_customer']),
                    ('invoice_date', '>=', rec.start_date),
                    ('invoice_date', '<=', rec.end_date),
                    ('move_type', '=', 'out_invoice'),
                    ('state', '=', 'posted'),
                    ('id', 'not in', b2c_large_ids)
                ]
                if rec.warehouse_id:
                    other_domain.append(('warehouse_id', '=', rec.warehouse_id.id))
                other_invoices = rec.env['account.move'].search(other_domain, order='invoice_date asc')

                # Step 1: Group by Place of Supply and Rate (Invoices) - Use defaultdict for simplicity
                from collections import defaultdict
                grouped_data = defaultdict(
                    lambda: {'place_of_supply': '', 'rate': 0, 'taxable_value': 0.0, 'tax_amount': 0.0})
                for invoice in other_invoices:
                    if not invoice.l10n_in_state_id or not invoice.l10n_in_state_id.l10n_in_tin:
                        continue  # Skip if place of supply is unknown

                    place_of_supply = f"{invoice.l10n_in_state_id.l10n_in_tin}-{invoice.l10n_in_state_id.name}"
                    taxable_value = sum(line.price_subtotal for line in invoice.invoice_line_ids)
                    tax_amount = invoice.amount_total - taxable_value
                    calculated_rate = (tax_amount / taxable_value * 100) if taxable_value else 0
                    rate = round_to_nearest_gst_rate(calculated_rate)  # CHANGED: Use helper function

                    key = (place_of_supply, rate)
                    grouped_data[key]['place_of_supply'] = place_of_supply
                    grouped_data[key]['rate'] = rate
                    grouped_data[key]['taxable_value'] += taxable_value
                    grouped_data[key]['tax_amount'] += tax_amount

                # Step 2: Include Credit Notes (subtract values) - Group by same key
                credit_note_domain = [
                    ('partner_id.vat', '=', False),
                    # ('customer_type', 'in', ['register_customer', 'non_register_customer']),
                    ('invoice_date', '>=', rec.start_date),
                    ('invoice_date', '<=', rec.end_date),
                    ('move_type', '=', 'out_refund'),
                    ('state', '=', 'posted')
                ]
                if rec.warehouse_id:
                    credit_note_domain.append(('warehouse_id', '=', rec.warehouse_id.id))

                credit_notes = rec.env['account.move'].search(credit_note_domain)

                for credit in credit_notes:
                    if not credit.l10n_in_state_id or not credit.l10n_in_state_id.l10n_in_tin:
                        continue

                    place_of_supply = f"{credit.l10n_in_state_id.l10n_in_tin}-{credit.l10n_in_state_id.name}"
                    taxable_value = sum(line.price_subtotal for line in credit.invoice_line_ids)
                    tax_amount = credit.amount_total - taxable_value
                    calculated_rate = (tax_amount / taxable_value * 100) if taxable_value else 0
                    rate = round_to_nearest_gst_rate(calculated_rate)  # CHANGED: Use helper function

                    key = (place_of_supply, rate)
                    if key in grouped_data:
                        grouped_data[key]['taxable_value'] -= taxable_value
                        grouped_data[key]['tax_amount'] -= tax_amount
                    else:
                        # If no matching group, create one with negative values
                        grouped_data[key]['place_of_supply'] = place_of_supply
                        grouped_data[key]['rate'] = rate
                        grouped_data[key]['taxable_value'] = -taxable_value
                        grouped_data[key]['tax_amount'] = -tax_amount

                # Step 3: Format data for output - One line per unique (place_of_supply, rate) group
                sale_final_data = []
                sl_no = 1
                # Sort by place_of_supply, then by rate for consistent ordering
                for key, data in sorted(grouped_data.items(), key=lambda x: (x[0][0], x[0][1])):
                    taxable_value = data['taxable_value']
                    # Recalculate rate from aggregated values to ensure accuracy
                    recalculated_rate_raw = (data['tax_amount'] / taxable_value * 100) if taxable_value else 0
                    recalculated_rate = round_to_nearest_gst_rate(
                        recalculated_rate_raw)  # CHANGED: Use helper function
                    sale_final_data.append({
                        'sl_no': sl_no,
                        'place_of_supply': data['place_of_supply'],
                        'rate': recalculated_rate,  # Use recalculated for precision
                        'taxable_value': round(taxable_value, 2),
                    })
                    sl_no += 1

            elif rec.type == 'd/c_reg_customer':
                domain.append(('partner_id.vat', '!=', False))
                # domain.append(('customer_type', 'in', ['register_company']))
                domain.append(('move_type', 'in', ['out_refund', 'in_refund']))
                domain.append(('state', '=', 'posted'))
                sale_data = rec.env['account.move'].search(domain, order='invoice_date asc, name asc')
                sale_final_data = []
                sl_no = 1
                for rec in sale_data:
                    line_untaxed_total = sum(line.price_subtotal for line in rec.invoice_line_ids)
                    sale_final_data.append({
                        'sl_no': sl_no,
                        'gstin_customer': rec.partner_id.vat if rec.partner_id.vat else '',
                        'supplier_name': rec.partner_id.name if rec.partner_id else '',
                        'inv_ref': rec.invoice_ref if rec.invoice_ref else '',
                        'inv_ref_date': '',
                        'inv_no': rec.name,
                        'date': rec.invoice_date.strftime('%d-%b-%Y') if rec.invoice_date else '',
                        'doc_type': 'Debit Note' if rec.move_type == 'in_refund' else 'Credit Note' if rec.move_type == 'out_refund' else rec.move_type,
                        'place_of_supply': f"{rec.State_id.l10n_in_tin}-{rec.State_id.name}" if rec.State_id else '',
                        'total_value': round(rec.amount_total, 2),
                        'rate': self._get_total_tax_rate(rec),
                        'untaxed_value': round(rec.amount_untaxed, 2),
                        'total_value': round(rec.amount_total, 2),
                        'taxable_value': round(line_untaxed_total or '', 2),
                    })
                    sl_no += 1
            elif rec.type == 'd/c_unreg_customer':
                domain.append(('partner_id.vat', '=', False))
                # domain.append(('customer_type', 'in', ['non_register_customer','register_customer']))
                domain.append(('move_type', 'in', ['out_refund']))
                domain.append(('state', '=', 'posted'))
                sale_data = rec.env['account.move'].search(domain, order='invoice_date asc, name asc')
                sale_final_data = []
                sl_no = 1
                for rec in sale_data:
                    line_untaxed_total = sum(line.price_subtotal for line in rec.invoice_line_ids)
                    sale_final_data.append({
                        'sl_no': sl_no,
                        'gstin_customer': rec.partner_id.vat if rec.partner_id.vat else '',
                        'supplier_name': rec.partner_id.name if rec.partner_id else '',
                        'inv_ref': rec.invoice_ref if rec.invoice_ref else '',
                        'inv_ref_date': '',
                        'inv_no': rec.name,
                        'date': rec.invoice_date.strftime('%d-%b-%Y') if rec.invoice_date else '',
                        'doc_type': 'Debit Note' if rec.move_type == 'in_refund' else 'Credit Note' if rec.move_type == 'out_refund' else rec.move_type,
                        'place_of_supply': f"{rec.State_id.l10n_in_tin}-{rec.State_id.name}" if rec.State_id else '',
                        'total_value': round(rec.amount_total, 2),
                        'rate': self._get_total_tax_rate(rec),
                        'untaxed_value': round(rec.amount_untaxed, 2),
                        'total_value': round(rec.amount_total, 2),
                        'taxable_value': round(line_untaxed_total or '', 2),
                    })
                    sl_no += 1
            elif rec.type == 'tcs_input':
                domain = [
                    ('move_type', '=', 'in_invoice'),
                    ('state', '=', 'posted'),
                    ('line_ids.tax_line_id.tax_group_id.name', 'ilike', 'TCS'),
                ]
                sale_data = rec.env['account.move'].search(domain, order='invoice_date asc, name asc')
                sale_final_data = []
                sl_no = 1
                for move in sale_data:  # renamed to avoid shadowing 'rec'
                    tcs_amount = sum(
                        line.credit or line.debit
                        for line in move.line_ids
                        if line.tax_line_id and 'TCS' in (line.tax_line_id.tax_group_id.name or '')
                    )
                    total_without_tcs = move.amount_total - tcs_amount

                    # Odoo 18: GSTIN is on partner
                    gstin = (
                            move.partner_id.l10n_in_gstin
                            or getattr(move, 'l10n_in_gstin', '')
                            or ''
                    )

                    sale_final_data.append({
                        'sl_no': sl_no,
                        'date': move.invoice_date.strftime('%d-%b-%Y') if move.invoice_date else '',
                        'inv_no': move.name,
                        'customer_name': move.partner_id.name,
                        'gstin_customer': gstin,
                        'tcs_rate': '0.10' if tcs_amount != 0 else '0',
                        'total_without_tcs': round(total_without_tcs, 2) if total_without_tcs else '',
                        'tcs_amount': round(tcs_amount, 2),
                        'total_value': round(move.amount_total, 2),
                    })
                    sl_no += 1
            elif rec.type == 'tcs_output':
                domain.append(('move_type', '=', 'out_invoice'))
                domain.append(('state', '=', 'posted'))
                domain.append(('line_ids.tax_line_id.tax_group_id.name', 'ilike', 'TCS'))
                sale_data = rec.env['account.move'].search(domain, order='invoice_date asc, name asc')
                sale_final_data = []
                sl_no = 1
                for rec in sale_data:
                    tcs_amount = sum(
                        line.credit or line.debit
                        for line in rec.line_ids
                        if line.tax_line_id and 'TCS' in (line.tax_line_id.tax_group_id.name or '')
                    )
                    total_without_tcs = rec.amount_total - tcs_amount
                    sale_final_data.append({
                        'sl_no': sl_no,
                        'date': rec.invoice_date.strftime('%d-%b-%Y') if rec.invoice_date else '',
                        'inv_no': rec.name,
                        'customer_name': rec.partner_id.name,
                        'gstin_customer': rec.partner_id.vat if rec.partner_id.vat else '',
                        'tcs_rate': '0.10' if tcs_amount != 0 else '0',
                        'total_without_tcs': round(total_without_tcs, 2) if total_without_tcs else '',
                        'tcs_amount': round(tcs_amount, 2),
                        'total_value': round(rec.amount_total, 2),
                    })
                    sl_no += 1
            elif rec.type == 'hsn':
                if rec.hsn_type == 'all':
                    new_domain = []
                    if rec.start_date:
                        new_domain.append(('move_id.invoice_date', '>=', rec.start_date))
                    if rec.end_date:
                        new_domain.append(('move_id.invoice_date', '<=', rec.end_date))
                    if rec.warehouse_id:
                        new_domain.append(('move_id.warehouse_id', '=', rec.warehouse_id.id))
                    new_domain.append(('product_id', '!=', False))
                    new_domain.append(('product_id.product_tmpl_id.type', 'in', ['consu', 'service', 'product']))
                    new_domain.append(('move_id.state', '=', 'posted'))

                    # Step 2: Domains for B2B and B2C
                    common_domain = new_domain.copy()
                    b2b_domain = common_domain + [('move_id.partner_id.vat', '!=', False)]
                    b2c_domain = common_domain + [('move_id.partner_id.vat', '=', False)]

                    # Step 3: Fetch lines
                    b2b_invoice_lines = rec.env['account.move.line'].search(
                        b2b_domain + [('move_id.move_type', '=', 'out_invoice')])
                    b2b_credit_lines = rec.env['account.move.line'].search(
                        b2b_domain + [('move_id.move_type', '=', 'out_refund')])
                    b2c_invoice_lines = rec.env['account.move.line'].search(
                        b2c_domain + [('move_id.move_type', '=', 'out_invoice')])
                    b2c_credit_lines = rec.env['account.move.line'].search(
                        b2c_domain + [('move_id.move_type', '=', 'out_refund')])

                    # Step 4: Modified Group function with warehouse info
                    def group_lines(invoice_lines, credit_lines):
                        grouped = {}

                        def process(line, is_credit=False):
                            igst = cgst = sgst = rate = 0.0
                            taxes = line.tax_ids.compute_all(
                                line.price_unit,
                                currency=line.move_id.currency_id,
                                quantity=line.quantity,
                                product=line.product_id,
                                partner=line.move_id.partner_id
                            )
                            for tax_data in taxes['taxes']:
                                tax_obj = rec.env['account.tax'].browse(tax_data['id'])
                                group_name = tax_obj.tax_group_id.name.lower()
                                rate += tax_obj.amount if tax_obj.amount_type == 'percent' else 0
                                if 'igst' in group_name:
                                    igst += tax_data['amount']
                                elif 'cgst' in group_name:
                                    cgst += tax_data['amount']
                                elif 'sgst' in group_name:
                                    sgst += tax_data['amount']

                            hsn_code = line.product_id.l10n_in_hsn_code or 'Undefined'
                            warehouse_name = line.move_id.warehouse_id.name if line.move_id.warehouse_id else 'No Warehouse'
                            sign = -1 if is_credit else 1
                            # Modified key to include warehouse
                            key = (hsn_code, round(rate, 2), warehouse_name)

                            if key not in grouped:
                                grouped[key] = {
                                    'hsn': hsn_code,
                                    'warehouse': warehouse_name,
                                    'rate': round(rate, 2),
                                    'desc': line.product_id.categ_id.name or '',
                                    'uqc': line.product_uom_id.name or '',
                                    'total_qty': 0.0,
                                    'total_value': 0.0,
                                    'taxable_value': 0.0,
                                    'igst': 0.0,
                                    'cgst': 0.0,
                                    'sgst': 0.0,
                                }

                            grouped[key]['total_qty'] += sign * (line.quantity or 0.0)
                            grouped[key]['total_value'] += sign * (line.price_total or 0.0)
                            grouped[key]['taxable_value'] += sign * (line.price_subtotal or 0.0)
                            grouped[key]['igst'] += sign * igst
                            grouped[key]['cgst'] += sign * cgst
                            grouped[key]['sgst'] += sign * sgst

                        for line in invoice_lines:
                            process(line, is_credit=False)
                        for line in credit_lines:
                            process(line, is_credit=True)

                        return grouped

                    # Step 5: Get grouped data
                    b2b_data = group_lines(b2b_invoice_lines, b2b_credit_lines)
                    b2c_data = group_lines(b2c_invoice_lines, b2c_credit_lines)

                    # Step 6: Convert to list and group by Warehouse first, then HSN
                    def format_hsn_lines(grouped_data):
                        # Group by warehouse first, then HSN within each warehouse
                        warehouse_groups = {}
                        for (hsn_code, rate, warehouse), data in grouped_data.items():
                            if warehouse not in warehouse_groups:
                                warehouse_groups[warehouse] = {
                                    'warehouse': warehouse,
                                    'hsn_codes': {}
                                }

                            if hsn_code not in warehouse_groups[warehouse]['hsn_codes']:
                                warehouse_groups[warehouse]['hsn_codes'][hsn_code] = []

                            warehouse_groups[warehouse]['hsn_codes'][hsn_code].append({
                                'rate': data['rate'],
                                'desc': data['desc'],
                                'uqc': data['uqc'],
                                'total_qty': data['total_qty'],
                                'total_value': round(data['total_value'], 2),
                                'taxable_value': round(data['taxable_value'], 2),
                                'igst': round(data['igst'], 2),
                                'cgst': round(data['cgst'], 2),
                                'sgst': round(data['sgst'], 2),
                            })

                        # Convert to final format
                        formatted_lines = []
                        sl_no = 1

                        for warehouse in sorted(warehouse_groups.keys()):
                            warehouse_group = warehouse_groups[warehouse]

                            # Add warehouse header
                            formatted_lines.append({
                                'warehouse': warehouse_group['warehouse'],
                                'is_warehouse_header': True
                            })

                            # Add HSN codes for this warehouse
                            for hsn_code in sorted(warehouse_group['hsn_codes'].keys()):
                                hsn_data_list = warehouse_group['hsn_codes'][hsn_code]

                                # If multiple rates for same HSN, show each separately
                                for hsn_data in hsn_data_list:
                                    formatted_lines.append({
                                        'sl_no': sl_no,
                                        'hsn': hsn_code,
                                        'rate': hsn_data['rate'],
                                        'desc': hsn_data['desc'],
                                        'uqc': hsn_data['uqc'],
                                        'total_qty': hsn_data['total_qty'],
                                        'total_value': hsn_data['total_value'],
                                        'taxable_value': hsn_data['taxable_value'],
                                        'igst': hsn_data['igst'],
                                        'cgst': hsn_data['cgst'],
                                        'sgst': hsn_data['sgst'],
                                        'is_hsn_row': True
                                    })
                                    sl_no += 1

                        return formatted_lines

                    b2b_lines = format_hsn_lines(b2b_data)
                    b2c_lines = format_hsn_lines(b2c_data)
                    return {
                        'b2b_lines': b2b_lines,
                        'b2c_lines': b2c_lines,
                    }
                    # Updated _gather_report_data method - HSN B2B section
                elif rec.hsn_type == 'hsn_b2b':
                    new_domain = []
                    if rec.start_date:
                        new_domain.append(('move_id.invoice_date', '>=', rec.start_date))
                    if rec.end_date:
                        new_domain.append(('move_id.invoice_date', '<=', rec.end_date))
                    if rec.warehouse_id:
                        new_domain.append(('move_id.warehouse_id', '=', rec.warehouse_id.id))
                    new_domain.append(('product_id', '!=', False))
                    new_domain.append(('product_id.product_tmpl_id.type', 'in', ['consu', 'service', 'product']))
                    new_domain.append(('move_id.state', '=', 'posted'))

                    # Step 2: Domains for B2B
                    common_domain = new_domain.copy()
                    b2b_domain = common_domain + [('move_id.partner_id.vat', '!=', False)]

                    # Step 3: Fetch lines
                    b2b_invoice_lines = rec.env['account.move.line'].search(
                        b2b_domain + [('move_id.move_type', '=', 'out_invoice')])
                    b2b_credit_lines = rec.env['account.move.line'].search(
                        b2b_domain + [('move_id.move_type', '=', 'out_refund')])

                    # Step 4: Modified Group function with warehouse info (same as 'all')
                    def group_lines(invoice_lines, credit_lines):
                        grouped = {}

                        def process(line, is_credit=False):
                            igst = cgst = sgst = rate = 0.0
                            taxes = line.tax_ids.compute_all(
                                line.price_unit,
                                currency=line.move_id.currency_id,
                                quantity=line.quantity,
                                product=line.product_id,
                                partner=line.move_id.partner_id
                            )
                            for tax_data in taxes['taxes']:
                                tax_obj = rec.env['account.tax'].browse(tax_data['id'])
                                group_name = tax_obj.tax_group_id.name.lower()
                                rate += tax_obj.amount if tax_obj.amount_type == 'percent' else 0
                                if 'igst' in group_name:
                                    igst += tax_data['amount']
                                elif 'cgst' in group_name:
                                    cgst += tax_data['amount']
                                elif 'sgst' in group_name:
                                    sgst += tax_data['amount']

                            hsn_code = line.product_id.l10n_in_hsn_code or 'Undefined'
                            warehouse_name = line.move_id.warehouse_id.name if line.move_id.warehouse_id else 'No Warehouse'
                            sign = -1 if is_credit else 1
                            # Modified key to include warehouse
                            key = (hsn_code, round(rate, 2), warehouse_name)

                            if key not in grouped:
                                grouped[key] = {
                                    'hsn': hsn_code,
                                    'warehouse': warehouse_name,
                                    'rate': round(rate, 2),
                                    'desc': line.product_id.categ_id.name or '',
                                    'uqc': line.product_uom_id.name or '',
                                    'total_qty': 0.0,
                                    'total_value': 0.0,
                                    'taxable_value': 0.0,
                                    'igst': 0.0,
                                    'cgst': 0.0,
                                    'sgst': 0.0,
                                }

                            grouped[key]['total_qty'] += sign * (line.quantity or 0.0)
                            grouped[key]['total_value'] += sign * (line.price_total or 0.0)
                            grouped[key]['taxable_value'] += sign * (line.price_subtotal or 0.0)
                            grouped[key]['igst'] += sign * igst
                            grouped[key]['cgst'] += sign * cgst
                            grouped[key]['sgst'] += sign * sgst

                        for line in invoice_lines:
                            process(line, is_credit=False)
                        for line in credit_lines:
                            process(line, is_credit=True)

                        return grouped

                    # Step 5: Get grouped data
                    b2b_data = group_lines(b2b_invoice_lines, b2b_credit_lines)

                    # Step 6: Convert to list and group by Warehouse first, then HSN (same as 'all')
                    def format_hsn_lines(grouped_data):
                        # Group by warehouse first, then HSN within each warehouse
                        warehouse_groups = {}
                        for (hsn_code, rate, warehouse), data in grouped_data.items():
                            if warehouse not in warehouse_groups:
                                warehouse_groups[warehouse] = {
                                    'warehouse': warehouse,
                                    'hsn_codes': {}
                                }

                            if hsn_code not in warehouse_groups[warehouse]['hsn_codes']:
                                warehouse_groups[warehouse]['hsn_codes'][hsn_code] = []

                            warehouse_groups[warehouse]['hsn_codes'][hsn_code].append({
                                'rate': data['rate'],
                                'desc': data['desc'],
                                'uqc': data['uqc'],
                                'total_qty': data['total_qty'],
                                'total_value': round(data['total_value'], 2),
                                'taxable_value': round(data['taxable_value'], 2),
                                'igst': round(data['igst'], 2),
                                'cgst': round(data['cgst'], 2),
                                'sgst': round(data['sgst'], 2),
                            })

                        # Convert to final format
                        formatted_lines = []
                        sl_no = 1

                        for warehouse in sorted(warehouse_groups.keys()):
                            warehouse_group = warehouse_groups[warehouse]

                            # Add warehouse header
                            formatted_lines.append({
                                'warehouse': warehouse_group['warehouse'],
                                'is_warehouse_header': True
                            })

                            # Add HSN codes for this warehouse
                            for hsn_code in sorted(warehouse_group['hsn_codes'].keys()):
                                hsn_data_list = warehouse_group['hsn_codes'][hsn_code]

                                # If multiple rates for same HSN, show each separately
                                for hsn_data in hsn_data_list:
                                    formatted_lines.append({
                                        'sl_no': sl_no,
                                        'hsn': hsn_code,
                                        'rate': hsn_data['rate'],
                                        'desc': hsn_data['desc'],
                                        'uqc': hsn_data['uqc'],
                                        'total_qty': hsn_data['total_qty'],
                                        'total_value': hsn_data['total_value'],
                                        'taxable_value': hsn_data['taxable_value'],
                                        'igst': hsn_data['igst'],
                                        'cgst': hsn_data['cgst'],
                                        'sgst': hsn_data['sgst'],
                                        'is_hsn_row': True
                                    })
                                    sl_no += 1

                        return formatted_lines

                    b2b_lines = format_hsn_lines(b2b_data)
                    return {
                        'b2b_lines': b2b_lines}
                    # Updated _gather_report_data method - HSN B2C section
                elif rec.hsn_type == 'hsn_b2c':
                    new_domain = []
                    if rec.start_date:
                        new_domain.append(('move_id.invoice_date', '>=', rec.start_date))
                    if rec.end_date:
                        new_domain.append(('move_id.invoice_date', '<=', rec.end_date))
                    if rec.warehouse_id:
                        new_domain.append(('move_id.warehouse_id', '=', rec.warehouse_id.id))
                    new_domain.append(('product_id', '!=', False))
                    new_domain.append(('product_id.product_tmpl_id.type', 'in', ['consu', 'service', 'product']))
                    new_domain.append(('move_id.state', '=', 'posted'))

                    # Step 2: Domains for B2C
                    common_domain = new_domain.copy()
                    b2c_domain = common_domain + [('move_id.partner_id.vat', '=', False)]

                    # Step 3: Fetch lines
                    b2c_invoice_lines = rec.env['account.move.line'].search(
                        b2c_domain + [('move_id.move_type', '=', 'out_invoice')])
                    b2c_credit_lines = rec.env['account.move.line'].search(
                        b2c_domain + [('move_id.move_type', '=', 'out_refund')])

                    # Step 4: Modified Group function with warehouse info (same as 'all')
                    def group_lines(invoice_lines, credit_lines):
                        grouped = {}

                        def process(line, is_credit=False):
                            igst = cgst = sgst = rate = 0.0
                            taxes = line.tax_ids.compute_all(
                                line.price_unit,
                                currency=line.move_id.currency_id,
                                quantity=line.quantity,
                                product=line.product_id,
                                partner=line.move_id.partner_id
                            )
                            for tax_data in taxes['taxes']:
                                tax_obj = rec.env['account.tax'].browse(tax_data['id'])
                                group_name = tax_obj.tax_group_id.name.lower()
                                rate += tax_obj.amount if tax_obj.amount_type == 'percent' else 0
                                if 'igst' in group_name:
                                    igst += tax_data['amount']
                                elif 'cgst' in group_name:
                                    cgst += tax_data['amount']
                                elif 'sgst' in group_name:
                                    sgst += tax_data['amount']

                            hsn_code = line.product_id.l10n_in_hsn_code or 'Undefined'
                            warehouse_name = line.move_id.warehouse_id.name if line.move_id.warehouse_id else 'No Warehouse'
                            sign = -1 if is_credit else 1
                            # Modified key to include warehouse
                            key = (hsn_code, round(rate, 2), warehouse_name)

                            if key not in grouped:
                                grouped[key] = {
                                    'hsn': hsn_code,
                                    'warehouse': warehouse_name,
                                    'rate': round(rate, 2),
                                    'desc': line.product_id.categ_id.name or '',
                                    'uqc': line.product_uom_id.name or '',
                                    'total_qty': 0.0,
                                    'total_value': 0.0,
                                    'taxable_value': 0.0,
                                    'igst': 0.0,
                                    'cgst': 0.0,
                                    'sgst': 0.0,
                                }

                            grouped[key]['total_qty'] += sign * (line.quantity or 0.0)
                            grouped[key]['total_value'] += sign * (line.price_total or 0.0)
                            grouped[key]['taxable_value'] += sign * (line.price_subtotal or 0.0)
                            grouped[key]['igst'] += sign * igst
                            grouped[key]['cgst'] += sign * cgst
                            grouped[key]['sgst'] += sign * sgst

                        for line in invoice_lines:
                            process(line, is_credit=False)
                        for line in credit_lines:
                            process(line, is_credit=True)

                        return grouped

                    # Step 5: Get grouped data
                    b2c_data = group_lines(b2c_invoice_lines, b2c_credit_lines)

                    # Step 6: Convert to list and group by Warehouse first, then HSN (same as 'all')
                    def format_hsn_lines(grouped_data):
                        # Group by warehouse first, then HSN within each warehouse
                        warehouse_groups = {}
                        for (hsn_code, rate, warehouse), data in grouped_data.items():
                            if warehouse not in warehouse_groups:
                                warehouse_groups[warehouse] = {
                                    'warehouse': warehouse,
                                    'hsn_codes': {}
                                }

                            if hsn_code not in warehouse_groups[warehouse]['hsn_codes']:
                                warehouse_groups[warehouse]['hsn_codes'][hsn_code] = []

                            warehouse_groups[warehouse]['hsn_codes'][hsn_code].append({
                                'rate': data['rate'],
                                'desc': data['desc'],
                                'uqc': data['uqc'],
                                'total_qty': data['total_qty'],
                                'total_value': round(data['total_value'], 2),
                                'taxable_value': round(data['taxable_value'], 2),
                                'igst': round(data['igst'], 2),
                                'cgst': round(data['cgst'], 2),
                                'sgst': round(data['sgst'], 2),
                            })

                        # Convert to final format
                        formatted_lines = []
                        sl_no = 1

                        for warehouse in sorted(warehouse_groups.keys()):
                            warehouse_group = warehouse_groups[warehouse]

                            # Add warehouse header
                            formatted_lines.append({
                                'warehouse': warehouse_group['warehouse'],
                                'is_warehouse_header': True
                            })

                            # Add HSN codes for this warehouse
                            for hsn_code in sorted(warehouse_group['hsn_codes'].keys()):
                                hsn_data_list = warehouse_group['hsn_codes'][hsn_code]

                                # If multiple rates for same HSN, show each separately
                                for hsn_data in hsn_data_list:
                                    formatted_lines.append({
                                        'sl_no': sl_no,
                                        'hsn': hsn_code,
                                        'rate': hsn_data['rate'],
                                        'desc': hsn_data['desc'],
                                        'uqc': hsn_data['uqc'],
                                        'total_qty': hsn_data['total_qty'],
                                        'total_value': hsn_data['total_value'],
                                        'taxable_value': hsn_data['taxable_value'],
                                        'igst': hsn_data['igst'],
                                        'cgst': hsn_data['cgst'],
                                        'sgst': hsn_data['sgst'],
                                        'is_hsn_row': True
                                    })
                                    sl_no += 1

                        return formatted_lines

                    b2c_lines = format_hsn_lines(b2c_data)
                    return {
                        'b2c_lines': b2c_lines,
                    }

            # elif rec.type == 'doc_summary':
            #     if not rec.start_date or not rec.end_date:
            #         raise UserError("Please provide both Start Date and End Date.")
            #     base_domain = []
            #     dc_domain = []
            #     if rec.start_date:
            #         base_domain.append(('invoice_date', '>=', rec.start_date))
            #     if rec.end_date:
            #         base_domain.append(('invoice_date', '<=', rec.end_date))
            #     if rec.warehouse_id:
            #         base_domain.append(('warehouse_id', '=', rec.warehouse_id.id))
            #     sale_final_data = []
            #
            #     # If branch selected, only that; else all
            #     warehouses = rec.warehouse_id or rec.env['stock.warehouse'].search([])
            #
            #     for wh in warehouses:
            #         wh_domain = base_domain + [('warehouse_id', '=', wh.id)]
            #
            #         # 1. B2B Sale
            #         b2b_sale_domain = wh_domain + [
            #             ('partner_id.vat', '!=', False),
            #             ('move_type', '=', 'out_invoice'),
            #         ]
            #         b2b_sale_data = rec.env['account.move'].search(b2b_sale_domain, order='invoice_date asc, name asc')
            #         b2b_sale_posted = b2b_sale_data.filtered(lambda x: x.state == 'posted')
            #
            #         if b2b_sale_data:
            #             sale_final_data.append({
            #                 'doc_type': 'B2B Sale',
            #                 'branch': wh.name,
            #                 'from_no': b2b_sale_posted[0].name if b2b_sale_posted else '',
            #                 'to_no': b2b_sale_posted[-1].name if b2b_sale_posted else '',
            #                 'vch_count': len(b2b_sale_data.filtered(lambda x: x.state in ('cancel', 'posted'))),
            #                 'cancel_count': len(b2b_sale_data.filtered(lambda x: x.state == 'cancel')),
            #                 'net_count': len(b2b_sale_data.filtered(lambda x: x.state == 'posted')),
            #             })
            #
            #         # 2. B2C sale
            #         b2c_sale_domain = wh_domain + [
            #             ('partner_id.vat', '=', False),
            #             # ('customer_type', 'in', ['non_register_customer', 'register_customer']),
            #             ('move_type', '=', 'out_invoice'),
            #         ]
            #         b2c_sale_data = rec.env['account.move'].search(b2c_sale_domain, order='invoice_date asc, name asc')
            #         b2c_sale_posted = b2c_sale_data.filtered(lambda x: x.state == 'posted')
            #
            #         if b2c_sale_data:
            #             sale_final_data.append({
            #                 'doc_type': 'B2C Sale',
            #                 'branch': wh.name,
            #                 'from_no': b2c_sale_posted[0].name if b2c_sale_posted else '',
            #                 'to_no': b2c_sale_posted[-1].name if b2c_sale_posted else '',
            #                 'vch_count': len(b2c_sale_data.filtered(lambda x: x.state in ('cancel', 'posted'))),
            #                 'cancel_count': len(b2c_sale_data.filtered(lambda x: x.state == 'cancel')),
            #                 'net_count': len(b2c_sale_data.filtered(lambda x: x.state == 'posted')),
            #             })
            #         # 3. Credit Note B2B
            #         credit_b2b_domain = wh_domain + [
            #             ('move_type', '=', 'out_refund'),
            #             # ('customer_type', 'in', ['register_company']),
            #             ('partner_id.vat', '!=', False),
            #         ]
            #         credit_b2b_data = rec.env['account.move'].search(credit_b2b_domain,
            #                                                          order='invoice_date asc, name asc')
            #         credit_b2b_posted = credit_b2b_data.filtered(lambda x: x.state == 'posted')
            #
            #         if credit_b2b_data:
            #             sale_final_data.append({
            #                 'doc_type': 'B2B Credit Note',
            #                 'branch': wh.name,
            #                 'from_no': credit_b2b_posted[0].name if credit_b2b_posted else '',
            #                 'to_no': credit_b2b_posted[-1].name if credit_b2b_posted else '',
            #                 'vch_count': len(credit_b2b_data.filtered(lambda x: x.state in ('cancel', 'posted'))),
            #                 'cancel_count': len(credit_b2b_data.filtered(lambda x: x.state == 'cancel')),
            #                 'net_count': len(credit_b2b_data.filtered(lambda x: x.state == 'posted')),
            #             })
            #         # 4. Credit Note B2C
            #         credit_b2c_domain = wh_domain + [
            #             ('move_type', '=', 'out_refund'),
            #             # ('customer_type', 'in', ['non_register_customer', 'register_customer']),
            #             ('partner_id.vat', '=', False),
            #         ]
            #         credit_b2c_data = rec.env['account.move'].search(credit_b2c_domain,
            #                                                          order='invoice_date asc, name asc')
            #         credit_b2c_posted = credit_b2c_data.filtered(lambda x: x.state == 'posted')
            #
            #         if credit_b2c_data:
            #             sale_final_data.append({
            #                 'doc_type': 'B2C Credit Note',
            #                 'branch': wh.name,
            #                 'from_no': credit_b2c_posted[0].name if credit_b2c_posted else '',
            #                 'to_no': credit_b2c_posted[-1].name if credit_b2c_posted else '',
            #                 'vch_count': len(credit_b2c_data.filtered(lambda x: x.state in ('cancel', 'posted'))),
            #                 'cancel_count': len(credit_b2c_data.filtered(lambda x: x.state == 'cancel')),
            #                 'net_count': len(credit_b2c_data.filtered(lambda x: x.state == 'posted')),
            #             })
            #         # 5. Purchase
            #         purchase_domain = wh_domain + [
            #             ('move_type', '=', 'in_invoice')
            #         ]
            #         purchase_data = rec.env['account.move'].search(purchase_domain, order='invoice_date asc, name asc')
            #         purchase_posted = purchase_data.filtered(lambda x: x.state == 'posted')
            #
            #         if purchase_data:
            #             sale_final_data.append({
            #                 'doc_type': 'Purchase',
            #                 'branch': wh.name,
            #                 'from_no': purchase_posted[0].name if purchase_posted else '',
            #                 'to_no': purchase_posted[-1].name if purchase_posted else '',
            #                 'vch_count': len(purchase_data.filtered(lambda x: x.state in ('cancel', 'posted'))),
            #                 'cancel_count': len(purchase_data.filtered(lambda x: x.state == 'cancel')),
            #                 'net_count': len(purchase_data.filtered(lambda x: x.state == 'posted')),
            #             })
            #         # 6. Debit Note
            #         debit_note_domain = wh_domain + [
            #             ('move_type', '=', 'in_refund')
            #         ]
            #         debit_note_data = rec.env['account.move'].search(debit_note_domain,
            #                                                          order='invoice_date asc, name asc')
            #         debit_note_posted = debit_note_data.filtered(lambda x: x.state == 'posted')
            #
            #         if debit_note_data:
            #             sale_final_data.append({
            #                 'doc_type': 'Debit Note',
            #                 'branch': wh.name,
            #                 'from_no': debit_note_posted[0].name if debit_note_posted else '',
            #                 'to_no': debit_note_posted[-1].name if debit_note_posted else '',
            #                 'vch_count': len(debit_note_data.filtered(lambda x: x.state in ('posted', 'cancel'))),
            #                 'cancel_count': len(debit_note_data.filtered(lambda x: x.state == 'cancel')),
            #                 'net_count': len(debit_note_data.filtered(lambda x: x.state == 'posted')),
            #             })
            #
            #         # 7. Receipt
            #         pay_domain = [('warehouse_id', '=', wh.id)]
            #
            #         if rec.start_date:
            #             pay_domain.append(('date', '>=', rec.start_date))
            #         if rec.end_date:
            #             pay_domain.append(('date', '<=', rec.end_date))
            #
            #         receipt_domain = pay_domain + [('payment_type', '=', 'inbound')]
            #
            #         receipt_data = rec.env['account.payment'].search(receipt_domain, order='date asc, name asc')
            #         receipt_posted = receipt_data.filtered(lambda x: x.state == 'posted')
            #
            #         if receipt_data:
            #             sale_final_data.append({
            #                 'doc_type': 'Receipt',
            #                 'branch': wh.name,
            #                 'from_no': receipt_posted[0].name if receipt_posted else '',
            #                 'to_no': receipt_posted[-1].name if receipt_posted else '',
            #                 'vch_count': len(receipt_data.filtered(lambda x: x.state in ('cancel', 'posted'))),
            #                 'cancel_count': len(receipt_data.filtered(lambda x: x.state == 'cancel')),
            #                 'net_count': len(receipt_data.filtered(lambda x: x.state == 'posted')),
            #             })
            #         # 8. Payment
            #         # pay_domain = [('warehouse_id', '=', wh.id)]
            #         payment_domain = pay_domain + [('payment_type', '=', 'outbound')]
            #         payment_data = rec.env['account.payment'].search(payment_domain, order='date asc,name asc')
            #         payment_posted = payment_data.filtered(lambda x: x.state == 'posted')
            #
            #         if payment_data:
            #             sale_final_data.append({
            #                 'doc_type': 'Payment',
            #                 'branch': wh.name,
            #                 'from_no': payment_posted[0].name if payment_posted else '',
            #                 'to_no': payment_posted[-1].name if payment_posted else '',
            #                 'vch_count': len(payment_data.filtered(lambda x: x.state in ('cancel', 'posted'))),
            #                 'cancel_count': len(payment_data.filtered(lambda x: x.state == 'cancel')),
            #                 'net_count': len(payment_data.filtered(lambda x: x.state == 'posted')),
            #             })
        #     elif rec.type == 'gstr1_summary':
        #         # 1. B2B sale
        #         b2b_domain = []
        #         if rec.start_date:
        #             b2b_domain.append(('invoice_date', '>=', rec.start_date))
        #         if rec.end_date:
        #             b2b_domain.append(('invoice_date', '<=', rec.end_date))
        #         if rec.warehouse_id:
        #             b2b_domain.append(('warehouse_id', '=', rec.warehouse_id.id))
        #         b2b_domain.append(('GSTIN', '!=', False))
        #         b2b_domain.append(('move_type', 'in', ['out_invoice']))
        #         b2b_domain.append(('state', '=', 'posted'))
        #         sale_data = rec.env['account.move'].search(b2b_domain, order='invoice_date asc, name asc')
        #         voucher_count = len(sale_data)
        #         sale_final_data = []
        #         b2b_total_inv_value = 0
        #         b2b_total_tax_value = 0
        #         b2b_total_untax_value = 0
        #         for data in sale_data:
        #             # b2b_line_untaxed_total = sum(line.price_subtotal for line in rec.invoice_line_ids)
        #             b2b_total_inv_value += data.amount_total
        #             b2b_total_tax_value += data.amount_tax
        #             b2b_total_untax_value += data.amount_untaxed
        #         sale_final_data.append({
        #             'doc_type': 'B2B Invoices',
        #             'voucher_count': voucher_count,
        #             'total_inv_value': round(b2b_total_inv_value, 2),
        #             'total_tax_value': round(b2b_total_tax_value, 2),
        #             'total_untax_value': round(b2b_total_untax_value, 2)
        #         })
        #         # 2. B2C Large
        #         b2c_large_domain = []
        #         if rec.start_date:
        #             b2c_large_domain.append(('invoice_date', '>=', rec.start_date))
        #         if rec.end_date:
        #             b2c_large_domain.append(('invoice_date', '<=', rec.end_date))
        #         if rec.warehouse_id:
        #             b2c_large_domain.append(('warehouse_id', '=', rec.warehouse_id.id))
        #         b2c_large_domain.append(('partner_id.vat', '=', False))
        #         # b2c_large_domain.append(('customer_type', 'in', ['register_customer', 'non_register_customer']))
        #         b2c_large_domain.append(('move_type', 'in', ['out_invoice']))
        #         b2c_large_domain.append(('state', '=', 'posted'))
        #         b2c_large_domain.append(('partner_id.state_id.l10n_in_tin', '!=', 32))
        #         b2c_large_domain.append(('amount_total', '>', 250000))
        #         sale_data = rec.env['account.move'].search(b2c_large_domain, order='invoice_date asc, name asc')
        #         voucher_count = len(sale_data)
        #         b2c_large_total_inv_value = 0
        #         b2c_large_total_tax_value = 0
        #         b2c_large_total_untax_value = 0
        #         for data in sale_data:
        #             # b2b_line_untaxed_total = sum(line.price_subtotal for line in rec.invoice_line_ids)
        #             b2c_large_total_inv_value += data.amount_total
        #             b2c_large_total_tax_value += data.amount_tax
        #             b2c_large_total_untax_value += data.amount_untaxed
        #         sale_final_data.append({
        #             'doc_type': 'B2C Large',
        #             'voucher_count': voucher_count,
        #             'total_untax_value': round(b2c_large_total_untax_value, 2),
        #             'total_inv_value': round(b2c_large_total_inv_value, 2),
        #             'total_tax_value': round(b2c_large_total_tax_value, 2)
        #         })
        #         # 3. B2C Small
        #         # Identify B2C Large Invoices (to be excluded)
        #         domain = [
        #             ('partner_id.vat', '=', False),
        #             # ('customer_type', 'in', ['register_customer', 'non_register_customer']),
        #             ('move_type', '=', 'out_invoice'),
        #             ('state', '=', 'posted'),
        #             ('partner_id.state_id.l10n_in_tin', '!=', 32),  # Assuming 32 is Kerala
        #             ('amount_total', '>', 250000)
        #         ]
        #         sale_all_data = rec.env['account.move'].search(domain, order='invoice_date asc')
        #         b2c_large_ids = sale_all_data.ids
        #         # Filter B2C Small Invoices
        #         other_domain = [
        #             ('partner_id.vat', '=', False),
        #             # ('customer_type', 'in', ['register_customer', 'non_register_customer']),
        #             ('invoice_date', '>=', rec.start_date),
        #             ('invoice_date', '<=', rec.end_date),
        #             ('move_type', '=', 'out_invoice'),
        #             ('state', '=', 'posted'),
        #             ('id', 'not in', b2c_large_ids)
        #         ]
        #         if rec.warehouse_id:
        #             other_domain.append(('warehouse_id', '=', rec.warehouse_id.id))
        #         other_invoices = rec.env['account.move'].search(other_domain, order='invoice_date asc')
        #         voucher_count = len(other_invoices)
        #         # Include Credit Notes (subtract values)
        #         credit_note_domain = [
        #             ('partner_id.vat', '=', False),
        #             # ('customer_type', 'in', ['register_customer', 'non_register_customer']),
        #             ('invoice_date', '>=', rec.start_date),
        #             ('invoice_date', '<=', rec.end_date),
        #             ('move_type', '=', 'out_refund'),
        #             ('state', '=', 'posted')
        #         ]
        #         if rec.warehouse_id:
        #             credit_note_domain.append(('warehouse_id', '=', rec.warehouse_id.id))
        #         credit_notes = rec.env['account.move'].search(credit_note_domain)
        #         # Calculate B2C Small Totals
        #         b2c_small_total_inv_value = sum(inv.amount_total for inv in other_invoices)
        #         b2c_small_total_tax_value = sum(inv.amount_tax for inv in other_invoices)
        #         b2c_small_total_untax_value = sum(inv.amount_untaxed for inv in other_invoices)
        #         # Calculate Credit Note Totals
        #         credit_note_total_inv_value = sum(ref.amount_total for ref in credit_notes)
        #         credit_note_total_tax_value = sum(ref.amount_tax for ref in credit_notes)
        #         credit_note_total_untax_value = sum(ref.amount_untaxed for ref in credit_notes)
        #         # Compute Net Values
        #         net_total_inv_value = b2c_small_total_inv_value - credit_note_total_inv_value
        #         net_total_tax_value = b2c_small_total_tax_value - credit_note_total_tax_value
        #         net_total_untax_value = b2c_small_total_untax_value - credit_note_total_untax_value
        #         # Prepare Final Data Output
        #         sale_final_data.append({
        #             'doc_type': 'B2C Small',
        #             'voucher_count': voucher_count,
        #             'total_untax_value': round(net_total_untax_value, 2),
        #             'total_inv_value': round(net_total_inv_value, 2),
        #             'total_tax_value': round(net_total_tax_value, 2),
        #         })
        #         # 4. Credit/Debit Registered
        #         cb_registered_domain = []
        #         if rec.start_date:
        #             cb_registered_domain.append(('invoice_date', '>=', rec.start_date))
        #         if rec.end_date:
        #             cb_registered_domain.append(('invoice_date', '<=', rec.end_date))
        #         if rec.warehouse_id:
        #             cb_registered_domain.append(('warehouse_id', '=', rec.warehouse_id.id))
        #         cb_registered_domain.append(('GSTIN', '!=', False))
        #         # cb_registered_domain.append(('customer_type', 'in', ['register_customer', 'register_company']))
        #         cb_registered_domain.append(('move_type', 'in', ['out_refund', 'in_refund']))
        #         cb_registered_domain.append(('state', '=', 'posted'))
        #         sale_data = rec.env['account.move'].search(cb_registered_domain, order='invoice_date asc, name asc')
        #         voucher_count = len(sale_data)
        #         cb_reg_total_inv_value = 0
        #         cb_reg_total_tax_value = 0
        #         cb_reg_total_untax_value = 0
        #         for data in sale_data:
        #             cb_reg_total_inv_value += data.amount_total
        #             cb_reg_total_tax_value += data.amount_tax
        #             cb_reg_total_untax_value += data.amount_untaxed
        #         sale_final_data.append({
        #             'doc_type': 'Credit/Debit Registered',
        #             'voucher_count': voucher_count,
        #             'total_untax_value': round(cb_reg_total_untax_value, 2),
        #             'total_inv_value': round(cb_reg_total_inv_value, 2),
        #             'total_tax_value': round(cb_reg_total_tax_value, 2)
        #         })
        #         # 5. Credit/Debit UnRegistered
        #         cb_unregistered_domain = []
        #         if rec.start_date:
        #             cb_unregistered_domain.append(('invoice_date', '>=', rec.start_date))
        #         if rec.end_date:
        #             cb_unregistered_domain.append(('invoice_date', '<=', rec.end_date))
        #         if rec.warehouse_id:
        #             cb_unregistered_domain.append(('warehouse_id', '=', rec.warehouse_id.id))
        #         cb_unregistered_domain.append(('partner_id.vat', '=', False))
        #         # cb_unregistered_domain.append(('customer_type', 'in', ['non_register_customer']))
        #         cb_unregistered_domain.append(('move_type', 'in', ['out_refund', 'in_refund']))
        #         cb_unregistered_domain.append(('state', '=', 'posted'))
        #         sale_data = rec.env['account.move'].search(cb_unregistered_domain, order='invoice_date asc, name asc')
        #         voucher_count = len(sale_data)
        #         cb_unreg_total_inv_value = 0
        #         cb_unreg_total_tax_value = 0
        #         cb_unreg_total_untax_value = 0
        #         for data in sale_data:
        #             cb_unreg_total_inv_value += data.amount_total
        #             cb_unreg_total_tax_value += data.amount_tax
        #             cb_unreg_total_untax_value += data.amount_untaxed
        #         sale_final_data.append({
        #             'doc_type': 'Credit/Debit UnRegistered',
        #             'voucher_count': voucher_count,
        #             'total_untax_value': round(cb_unreg_total_untax_value, 2),
        #             'total_inv_value': round(cb_unreg_total_inv_value, 2),
        #             'total_tax_value': round(cb_unreg_total_tax_value, 2)
        #         })
        # else:
        #     pass
        return {
            'lines': sale_final_data,
        }

    def _format_report_data_to_html(self, report_data):
        if self.type == 'hsn':
            if not self.hsn_type:
                raise UserError("HSN Type is required. Please fill it before generating the report.")

        report_html = ''
        for rec in self:
            if not report_data:
                return "No data found for the selected filters"
            invoice_details = report_data.get('lines', [])
            if rec.type == 'b2b':
                total_inv_value = 0.0
                total_taxable_value = 0.0
                report_html = f"""
                   <style>
                       table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
                       th, td {{ border: 1px solid #999; padding: 6px; text-align: center; }}
                       th {{ background-color: #f2f2f2;}}
                   </style>
                   <table>
                       <thead>
                           <tr>
                                <th>SL.NO</th>
                                <th>GSTIN</th>
                                <th>Customer Name</th>
                                <th>Invoice No</th>
                                <th>Date</th>
                                <th>Invoice Value</th>
                                <th>Place of Supply</th>
                                <th>Reverse Charge</th>
                                <th>Invoice Type</th>
                                <th>Rate</th>
                                <th>Taxable Value</th>
                           </tr>
                       </thead>
                       <tbody>
                   """
                for detail in invoice_details:
                    total_inv_value += detail['inv_value']
                    total_taxable_value += detail['taxable_value']
                    report_html += f"""
                           <tr>
                               <td>{detail['sl_no']}</td>
                               <td>{detail['gstin_customer']}</td>
                               <td>{detail['customer_name']}</td>
                               <td>{detail['inv_no']}</td>
                               <td>{detail['date']}</td>
                               <td>{'{:,.2f}'.format(detail['inv_value'])}</td>
                               <td>{detail['place_of_supply']}</td>
                               <td>{detail['reverse_charge']}</td>
                               <td>{detail['inv_type']}</td>
                               <td>{detail['rate']}</td>
                               <td>{'{:,.2f}'.format(detail['taxable_value'])}</td>
                           </tr>
                       """
                report_html += f"""
                            <tr>
                                <td colspan="5"><strong>Total</strong></td>
                                <td><strong>{'{:,.2f}'.format(total_inv_value)}</strong></td>
                                <td colspan="4"></td>
                                <td><strong>{'{:,.2f}'.format(total_taxable_value)}</strong></td>
                            </tr>
                      </tbody>
                  </table>
                  """
            elif rec.type == 'b2c_large':
                total_inv_value = 0.0
                total_taxable_value = 0.0
                report_html = f"""
                           <style>
                               table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
                               th, td {{ border: 1px solid #999; padding: 6px; text-align: center; }}
                               th {{ background-color: #f2f2f2; }}
                           </style>
                           <table>
                               <thead>
                                   <tr>
                                       <th>SL.NO</th>
                                       <th>Invoice No</th>
                                       <th>Invoice Date</th>
                                       <th>Invoice Value</th>
                                       <th>Place of Supply</th>
                                       <th>Rate</th>
                                       <th>Taxable Value</th>
                                   </tr>
                               </thead>
                               <tbody>
                           """
                for detail in invoice_details:
                    total_inv_value += detail['inv_value']
                    total_taxable_value += detail['taxable_value']
                    report_html += f"""
                               <tr>
                                   <td>{detail['sl_no']}</td>
                                   <td>{detail['inv_no']}</td>
                                   <td>{detail['date']}</td>
                                   <td>{'{:,.2f}'.format(detail['inv_value'])}</td>
                                   <td>{detail['place_of_supply']}</td>
                                   <td>{detail['rate']}</td>
                                   <td>{'{:,.2f}'.format(detail['taxable_value'])}</td>
                               </tr>
                             """
                report_html += f"""
                            <tr>
                                <td colspan="3"><strong>Total</strong></td>
                                <td><strong>{'{:,.2f}'.format(total_inv_value)}</strong></td>
                                <td colspan="2"></td>
                                <td><strong>{'{:,.2f}'.format(total_taxable_value)}</strong></td>
                            </tr>
                          </tbody>
                      </table>
                      """
            elif rec.type == 'b2c_small':
                total_taxable_value = 0.0
                report_html = f"""
                                   <style>
                                       table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
                                       th, td {{ border: 1px solid #999; padding: 6px; text-align: center; }}
                                       th {{ background-color: #f2f2f2; }}
                                   </style>
                                   <table>
                                       <thead>
                                           <tr>
                                               <th>SL NO</th>
                                               <th>Place of Supply</th>
                                               <th>Rate</th>
                                               <th>Taxable Value</th>                                                                                                                                         
                                           </tr>
                                       </thead>
                                       <tbody>
                                   """
                for detail in invoice_details:
                    total_taxable_value += detail['taxable_value']
                    report_html += f"""
                                       <tr>
                                           <td>{detail['sl_no']}</td>
                                           <td>{detail['place_of_supply']}</td>
                                           <td>{detail['rate']}</td>
                                           <td>{'{:,.2f}'.format(detail['taxable_value'])}</td>                                                                   
                                       </tr>
                                     """
                report_html += f"""
                                    <tr>
                                        <td colspan="3"><strong>Total</strong></td>
                                        <td><strong>{'{:,.2f}'.format(total_taxable_value)}</strong></td>
                                    </tr>
                                  </tbody>
                              </table>
                              """
            elif rec.type == 'd/c_reg_customer':
                total_note_value = 0.0
                total_taxable_value = 0.0
                report_html = f"""
                                   <style>
                                       table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
                                       th, td {{ border: 1px solid #999; padding: 6px; text-align: center; }}
                                       th {{ background-color: #f2f2f2; }}
                                   </style>
                                   <table>
                                       <thead>
                                           <tr>
                                               <th>SL NO</th>
                                               <th>GSTIN of Recipient</th>
                                               <th>Supplier Name</th>
                                               <th>Invoice/Advance Receipt Number</th>
                                               <th>Invoice/Advance Receipt date</th>
                                               <th>Note/Refund Voucher Number</th>
                                               <th>Note/Refund Voucher date</th>                                                                                                                                         
                                               <th>Document Type</th>                                                                                                                                         
                                               <th>Place Of Supply</th>                                                                                                                                         
                                               <th>Note/Refund Voucher Value</th>                                                                                                                                         
                                               <th>Rate</th>                                                                                                                                         
                                               <th>Taxable Value</th>                                                                                                                                         
                                           </tr>
                                       </thead>
                                       <tbody>
                                   """
                for detail in invoice_details:
                    total_note_value += detail['total_value']
                    total_taxable_value += detail['taxable_value']
                    report_html += f"""
                                       <tr>
                                           <td>{detail['sl_no']}</td>
                                           <td>{detail['gstin_customer']}</td>
                                           <td>{detail.get('supplier_name', '')}</td>
                                           <td>{detail['inv_ref']}</td>
                                           <td>{detail['inv_ref_date']}</td>
                                           <td>{detail['inv_no']}</td>
                                           <td>{detail['date']}</td>
                                           <td>{detail['doc_type']}</td>
                                           <td>{detail['place_of_supply']}</td>
                                           <td>{detail['total_value']}</td>
                                           <td>{detail['rate']}</td>
                                           <td>{'{:,.2f}'.format(detail['taxable_value'])}</td>                                                                   
                                       </tr>
                                     """
                report_html += f"""
                                    <tr>
                                        <td colspan="9"><strong>Total</strong></td>
                                        <td><strong>{'{:,.2f}'.format(total_note_value)}</strong></td>
                                        <td></td>
                                        <td><strong>{'{:,.2f}'.format(total_taxable_value)}</strong></td>
                                    </tr>
                                  </tbody>
                              </table>
                              """
            elif rec.type == 'd/c_unreg_customer':
                total_note_value = 0.0
                total_taxable_value = 0.0
                report_html = f"""
                                   <style>
                                       table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
                                       th, td {{ border: 1px solid #999; padding: 6px; text-align: center; }}
                                       th {{ background-color: #f2f2f2; }}
                                   </style>
                                   <table>
                                       <thead>
                                           <tr>
                                               <th>SL NO</th>
                                               <th>GSTIN of Recipient</th>
                                               <th>Supplier Name</th>
                                               <th>Invoice/Advance Receipt Number</th>
                                               <th>Invoice/Advance Receipt date</th>
                                               <th>Note/Refund Voucher Number</th>
                                               <th>Note/Refund Voucher date</th>                                                                                                                                         
                                               <th>Document Type</th>                                                                                                                                         
                                               <th>Place Of Supply</th>                                                                                                                                         
                                               <th>Note/Refund Voucher Value</th>                                                                                                                                         
                                               <th>Rate</th>                                                                                                                                         
                                               <th>Taxable Value</th>                                                                                                                                         
                                           </tr>
                                       </thead>
                                       <tbody>
                                   """
                for detail in invoice_details:
                    total_note_value += detail['total_value']
                    total_taxable_value += detail['taxable_value']
                    report_html += f"""
                                       <tr>
                                           <td>{detail['sl_no']}</td>
                                           <td>{detail['gstin_customer']}</td>
                                           <td>{detail.get('supplier_name', '')}</td>
                                           <td>{detail['inv_ref']}</td>
                                           <td>{detail['inv_ref_date']}</td>
                                           <td>{detail['inv_no']}</td>
                                           <td>{detail['date']}</td>
                                           <td>{detail['doc_type']}</td>
                                           <td>{detail['place_of_supply']}</td>
                                           <td>{detail['total_value']}</td>
                                           <td>{detail['rate']}</td>
                                           <td>{'{:,.2f}'.format(detail['taxable_value'])}</td>                                                                   
                                       </tr>
                                     """
                report_html += f"""
                                    <tr>
                                        <td colspan="9"><strong>Total</strong></td>
                                        <td><strong>{'{:,.2f}'.format(total_note_value)}</strong></td>
                                        <td></td>
                                        <td><strong>{'{:,.2f}'.format(total_taxable_value)}</strong></td>
                                    </tr>                
                                  </tbody>
                              </table>
                              """
            elif rec.type == 'tcs_input':
                total_without_tcs = 0.0
                total_tcs_amount = 0.0
                grand_total = 0.0
                report_html = f"""
                                   <style>
                                       table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
                                       th, td {{ border: 1px solid #999; padding: 6px; text-align: center; }}
                                       th {{ background-color: #f2f2f2; }}
                                   </style>
                                   <table>
                                       <thead>
                                           <tr>
                                               <th>SL NO</th>
                                               <th>Date</th>
                                               <th>Voucher No</th>
                                               <th>Party Name</th>
                                               <th>GSTIN</th>
                                               <th>TCS Per</th>                                                                                                                                         
                                               <th>Total Amount</th>                                                                                                                                         
                                               <th>TCS Amount</th>                                                                                                                                         
                                               <th>Grand Total</th>                                                                                                                                                                                                                                                                         
                                           </tr>
                                       </thead>
                                       <tbody>
                                   """
                for detail in invoice_details:
                    total_without_tcs += detail['total_without_tcs']
                    total_tcs_amount += detail['tcs_amount']
                    grand_total += detail['total_value']
                    report_html += f"""
                                       <tr>
                                           <td>{detail['sl_no']}</td>
                                           <td>{detail['date']}</td>
                                           <td>{detail['inv_no']}</td>
                                           <td>{detail['customer_name']}</td>
                                           <td>{detail['gstin_customer']}</td>
                                           <td>{detail['tcs_rate']}</td>
                                           <td>{detail['total_without_tcs']}</td>
                                           <td>{detail['tcs_amount']}</td>
                                           <td>{'{:,.2f}'.format(detail['total_value'])}</td>
                                       </tr>
                                     """
                report_html += f"""
                                    <tr>
                                        <td colspan="6"><strong>Total</strong></td>
                                        <td><strong>{'{:,.2f}'.format(total_without_tcs)}</strong></td>
                                        <td><strong>{'{:,.2f}'.format(total_tcs_amount)}</strong></td>
                                        <td><strong>{'{:,.2f}'.format(grand_total)}</strong></td>
                                    </tr>
                                  </tbody>
                              </table>
                              """
            elif rec.type == 'tcs_output':
                total_without_tcs = 0.0
                total_tcs_amount = 0.0
                grand_total = 0.0
                report_html = f"""
                                   <style>
                                       table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
                                       th, td {{ border: 1px solid #999; padding: 6px; text-align: center; }}
                                       th {{ background-color: #f2f2f2; }}
                                   </style>
                                   <table>
                                       <thead>
                                           <tr>
                                               <th>SL NO</th>
                                               <th>Date</th>
                                               <th>Voucher No</th>
                                               <th>Party Name</th>
                                               <th>GSTIN</th>
                                               <th>TCS Per</th>
                                               <th>Total Amount</th>
                                               <th>TCS Amount</th>
                                               <th>Grand Total</th>
                                           </tr>
                                       </thead>
                                       <tbody>
                                   """
                for detail in invoice_details:
                    total_without_tcs += detail['total_without_tcs']
                    total_tcs_amount += detail['tcs_amount']
                    grand_total += detail['total_value']
                    report_html += f"""
                                       <tr>
                                           <td>{detail['sl_no']}</td>
                                           <td>{detail['date']}</td>
                                           <td>{detail['inv_no']}</td>
                                           <td>{detail['customer_name']}</td>
                                           <td>{detail['gstin_customer']}</td>
                                           <td>{detail['tcs_rate']}</td>
                                           <td>{detail['total_without_tcs']}</td>
                                           <td>{detail['tcs_amount']}</td>
                                           <td>{'{:,.2f}'.format(detail['total_value'])}</td>
                                       </tr>
                                     """
                report_html += f"""
                                    <tr>
                                        <td colspan="6"><strong>Total</strong></td>
                                        <td><strong>{'{:,.2f}'.format(total_without_tcs)}</strong></td>
                                        <td><strong>{'{:,.2f}'.format(total_tcs_amount)}</strong></td>
                                        <td><strong>{'{:,.2f}'.format(grand_total)}</strong></td>
                                    </tr>
                                  </tbody>
                              </table>
                              """
            elif rec.type == 'hsn':
                if rec.hsn_type == 'all':
                    b2b_lines = report_data.get('b2b_lines', [])
                    b2c_lines = report_data.get('b2c_lines', [])

                    report_html = """
                                                <style>
                                                    table {
                                                        border-collapse: collapse;
                                                        width: 100%;
                                                        font-size: 13px;
                                                    }
                                                    th, td {
                                                        border: 1px solid #999;
                                                        padding: 6px;
                                                        text-align: center;
                                                    }
                                                    th {
                                                        background-color: #f2f2f2;
                                                    }
                                                    h3 {
                                                        margin-top: 30px;
                                                        text-align: left;
                                                    }
                                                    .warehouse-header {
                                                        background-color: #eaeaea;
                                                        font-weight: bold;
                                                        text-align: left;
                                                        font-size: 14px;
                                                        color: #0A0A0A;
                                                    }
                                                    .hsn-row {
                                                        background-color: #f8f9fa;
                                                    }
                                                    .grand-total-row {
                                                        background-color: #d4edda;
                                                        font-weight: bold;
                                                        color: #155724;
                                                    }
                                                </style>
                                            """

                    def build_section(title, data):
                        section_html = f"""<h3>{title}</h3>
                                                <table>
                                                    <thead>
                                                        <tr>
                                                            <th>SL NO</th>
                                                            <th>HSN</th>
                                                            <th>Description</th>
                                                            <th>UQC</th>
                                                            <th>Total Quantity</th>
                                                            <th>Total Value</th>
                                                            <th>Rate (%)</th>
                                                            <th>Taxable Value</th>
                                                            <th>Integrated Tax Amount</th>
                                                            <th>Central Tax Amount</th>
                                                            <th>State/UT Tax Amount</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody>
                                            """

                        # Warehouse-wise totals
                        total_qty = total_val = total_taxable = total_igst = total_cgst = total_sgst = 0.0
                        # Grand totals across all warehouses
                        grand_total_qty = grand_total_val = grand_total_taxable = grand_total_igst = grand_total_cgst = grand_total_sgst = 0.0
                        current_warehouse = None
                        sl_no = 0  # Initialize serial number counter

                        for detail in data:
                            if detail.get('is_warehouse_header'):
                                # Before starting new warehouse, print total for previous warehouse
                                if current_warehouse is not None:
                                    section_html += f"""
                                                            <tr style="font-weight: bold; background-color: #dfe3e6;">
                                                                <td colspan="4" style="text-align: right;">Total:</td>
                                                                <td>{total_qty}</td>
                                                                <td>{'{:,.2f}'.format(total_val)}</td>
                                                                <td></td>
                                                                <td>{'{:,.2f}'.format(total_taxable)}</td>
                                                                <td>{'{:,.2f}'.format(total_igst)}</td>
                                                                <td>{'{:,.2f}'.format(total_cgst)}</td>
                                                                <td>{'{:,.2f}'.format(total_sgst)}</td>
                                                            </tr>
                                                        """
                                    # Add warehouse totals to grand totals
                                    grand_total_qty += total_qty
                                    grand_total_val += total_val
                                    grand_total_taxable += total_taxable
                                    grand_total_igst += total_igst
                                    grand_total_cgst += total_cgst
                                    grand_total_sgst += total_sgst

                                # Reset totals and serial number for new warehouse
                                sl_no = 0  # Reset serial number for new branch
                                total_qty = total_val = total_taxable = total_igst = total_cgst = total_sgst = 0.0
                                current_warehouse = detail['warehouse']

                                # Warehouse Header Row
                                section_html += f"""
                                                        <tr class="warehouse-header">
                                                            <td colspan="11">Branch: {detail['warehouse']}</td>
                                                        </tr>
                                                    """
                            elif detail.get('is_hsn_row'):
                                sl_no += 1  # Increment serial number for each HSN row

                                qty = float(detail.get('total_qty', 0))
                                val = float(detail.get('total_value', 0))
                                taxable = float(detail.get('taxable_value', 0))
                                rate = float(detail.get('rate', 0.0))
                                igst = float(detail.get('igst', 0))
                                cgst = float(detail.get('cgst', 0))
                                sgst = float(detail.get('sgst', 0))

                                # Accumulate warehouse totals
                                total_qty += qty
                                total_val += val
                                total_taxable += taxable
                                total_igst += igst
                                total_cgst += cgst
                                total_sgst += sgst

                                section_html += f"""
                                                        <tr class="hsn-row">
                                                            <td>{sl_no}</td>
                                                            <td>{detail['hsn']}</td>
                                                            <td>{detail['desc']}</td>
                                                            <td>{detail['uqc']}</td>
                                                            <td>{qty}</td>
                                                            <td>{'{:,.2f}'.format(val)}</td>
                                                            <td>{'{:.2f}'.format(rate)}</td>
                                                            <td>{'{:,.2f}'.format(taxable)}</td>
                                                            <td>{'{:,.2f}'.format(igst)}</td>
                                                            <td>{'{:,.2f}'.format(cgst)}</td>
                                                            <td>{'{:,.2f}'.format(sgst)}</td>
                                                        </tr>
                                                    """

                        # Add total for the last warehouse
                        if current_warehouse is not None:
                            section_html += f"""
                                                    <tr style="font-weight: bold; background-color: #dfe3e6;">
                                                        <td colspan="4" style="text-align: right;">Total:</td>
                                                        <td>{total_qty}</td>
                                                        <td>{'{:,.2f}'.format(total_val)}</td>
                                                        <td></td>
                                                        <td>{'{:,.2f}'.format(total_taxable)}</td>
                                                        <td>{'{:,.2f}'.format(total_igst)}</td>
                                                        <td>{'{:,.2f}'.format(total_cgst)}</td>
                                                        <td>{'{:,.2f}'.format(total_sgst)}</td>
                                                    </tr>
                                                """
                            # Add last warehouse totals to grand totals
                            grand_total_qty += total_qty
                            grand_total_val += total_val
                            grand_total_taxable += total_taxable
                            grand_total_igst += total_igst
                            grand_total_cgst += total_cgst
                            grand_total_sgst += total_sgst

                        # Add Grand Total Row
                        section_html += f"""
                                                <tr class="grand-total-row">
                                                    <td colspan="4" style="text-align: right;">Grand Total:</td>
                                                    <td>{grand_total_qty}</td>
                                                    <td>{'{:,.2f}'.format(grand_total_val)}</td>
                                                    <td></td>
                                                    <td>{'{:,.2f}'.format(grand_total_taxable)}</td>
                                                    <td>{'{:,.2f}'.format(grand_total_igst)}</td>
                                                    <td>{'{:,.2f}'.format(grand_total_cgst)}</td>
                                                    <td>{'{:,.2f}'.format(grand_total_sgst)}</td>
                                                </tr>
                                            """

                        section_html += "</tbody></table>"
                        return section_html

                    report_html += build_section("B2B", b2b_lines)
                    report_html += build_section("B2C", b2c_lines)

                    return report_html

                elif rec.hsn_type == 'hsn_b2b':
                    b2b_lines = report_data.get('b2b_lines', [])

                    report_html = """
                                                <style>
                                                    table {
                                                        border-collapse: collapse;
                                                        width: 100%;
                                                        font-size: 13px;
                                                    }
                                                    th, td {
                                                        border: 1px solid #999;
                                                        padding: 6px;
                                                        text-align: center;
                                                    }
                                                    th {
                                                        background-color: #f2f2f2;
                                                    }
                                                    h3 {
                                                        margin-top: 30px;
                                                        text-align: left;
                                                    }
                                                    .warehouse-header {
                                                        background-color: #eaeaea;
                                                        font-weight: bold;
                                                        text-align: left;
                                                        font-size: 14px;
                                                        color: #0A0A0A;
                                                    }
                                                    .hsn-row {
                                                        background-color: #f8f9fa;
                                                    }
                                                    .grand-total-row {
                                                        background-color: #d4edda;
                                                        font-weight: bold;
                                                        color: #155724;
                                                    }
                                                </style>
                                            """

                    def build_section(title, data):
                        section_html = f"""<h3>{title}</h3>
                                                <table>
                                                    <thead>
                                                        <tr>
                                                            <th>SL NO</th>
                                                            <th>HSN</th>
                                                            <th>Description</th>
                                                            <th>UQC</th>
                                                            <th>Total Quantity</th>
                                                            <th>Total Value</th>
                                                            <th>Rate (%)</th>
                                                            <th>Taxable Value</th>
                                                            <th>Integrated Tax Amount</th>
                                                            <th>Central Tax Amount</th>
                                                            <th>State/UT Tax Amount</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody>
                                            """

                        # Warehouse-wise totals
                        total_qty = total_val = total_taxable = total_igst = total_cgst = total_sgst = 0.0
                        # Grand totals across all warehouses
                        grand_total_qty = grand_total_val = grand_total_taxable = grand_total_igst = grand_total_cgst = grand_total_sgst = 0.0
                        current_warehouse = None
                        sl_no = 0  # Initialize serial number counter

                        for detail in data:
                            if detail.get('is_warehouse_header'):
                                # Before starting new warehouse, print total for previous warehouse
                                if current_warehouse is not None:
                                    section_html += f"""
                                                            <tr style="font-weight: bold; background-color: #dfe3e6;">
                                                                <td colspan="4" style="text-align: right;">Total:</td>
                                                                <td>{total_qty}</td>
                                                                <td>{'{:,.2f}'.format(total_val)}</td>
                                                                <td></td>
                                                                <td>{'{:,.2f}'.format(total_taxable)}</td>
                                                                <td>{'{:,.2f}'.format(total_igst)}</td>
                                                                <td>{'{:,.2f}'.format(total_cgst)}</td>
                                                                <td>{'{:,.2f}'.format(total_sgst)}</td>
                                                            </tr>
                                                        """
                                    # Add warehouse totals to grand totals
                                    grand_total_qty += total_qty
                                    grand_total_val += total_val
                                    grand_total_taxable += total_taxable
                                    grand_total_igst += total_igst
                                    grand_total_cgst += total_cgst
                                    grand_total_sgst += total_sgst

                                # Reset totals and serial number for new warehouse
                                sl_no = 0  # Reset serial number for new branch
                                total_qty = total_val = total_taxable = total_igst = total_cgst = total_sgst = 0.0
                                current_warehouse = detail['warehouse']

                                # Warehouse Header Row
                                section_html += f"""
                                                        <tr class="warehouse-header">
                                                            <td colspan="11">Branch: {detail['warehouse']}</td>
                                                        </tr>
                                                    """
                            elif detail.get('is_hsn_row'):
                                sl_no += 1  # Increment serial number for each HSN row

                                qty = float(detail.get('total_qty', 0))
                                val = float(detail.get('total_value', 0))
                                taxable = float(detail.get('taxable_value', 0))
                                rate = float(detail.get('rate', 0.0))
                                igst = float(detail.get('igst', 0))
                                cgst = float(detail.get('cgst', 0))
                                sgst = float(detail.get('sgst', 0))

                                # Accumulate warehouse totals
                                total_qty += qty
                                total_val += val
                                total_taxable += taxable
                                total_igst += igst
                                total_cgst += cgst
                                total_sgst += sgst

                                section_html += f"""
                                                        <tr class="hsn-row">
                                                            <td>{sl_no}</td>
                                                            <td>{detail['hsn']}</td>
                                                            <td>{detail['desc']}</td>
                                                            <td>{detail['uqc']}</td>
                                                            <td>{qty}</td>
                                                            <td>{'{:,.2f}'.format(val)}</td>
                                                            <td>{'{:.2f}'.format(rate)}</td>
                                                            <td>{'{:,.2f}'.format(taxable)}</td>
                                                            <td>{'{:,.2f}'.format(igst)}</td>
                                                            <td>{'{:,.2f}'.format(cgst)}</td>
                                                            <td>{'{:,.2f}'.format(sgst)}</td>
                                                        </tr>
                                                    """

                        # Add total for the last warehouse
                        if current_warehouse is not None:
                            section_html += f"""
                                                    <tr style="font-weight: bold; background-color: #dfe3e6;">
                                                        <td colspan="4" style="text-align: right;">Total:</td>
                                                        <td>{total_qty}</td>
                                                        <td>{'{:,.2f}'.format(total_val)}</td>
                                                        <td></td>
                                                        <td>{'{:,.2f}'.format(total_taxable)}</td>
                                                        <td>{'{:,.2f}'.format(total_igst)}</td>
                                                        <td>{'{:,.2f}'.format(total_cgst)}</td>
                                                        <td>{'{:,.2f}'.format(total_sgst)}</td>
                                                    </tr>
                                                """
                            # Add last warehouse totals to grand totals
                            grand_total_qty += total_qty
                            grand_total_val += total_val
                            grand_total_taxable += total_taxable
                            grand_total_igst += total_igst
                            grand_total_cgst += total_cgst
                            grand_total_sgst += total_sgst

                        # Add Grand Total Row
                        section_html += f"""
                                                <tr class="grand-total-row">
                                                    <td colspan="4" style="text-align: right;">Grand Total:</td>
                                                    <td>{grand_total_qty}</td>
                                                    <td>{'{:,.2f}'.format(grand_total_val)}</td>
                                                    <td></td>
                                                    <td>{'{:,.2f}'.format(grand_total_taxable)}</td>
                                                    <td>{'{:,.2f}'.format(grand_total_igst)}</td>
                                                    <td>{'{:,.2f}'.format(grand_total_cgst)}</td>
                                                    <td>{'{:,.2f}'.format(grand_total_sgst)}</td>
                                                </tr>
                                            """

                        section_html += "</tbody></table>"
                        return section_html

                    report_html += build_section("B2B", b2b_lines)
                    return report_html

                elif rec.hsn_type == 'hsn_b2c':
                    b2c_lines = report_data.get('b2c_lines', [])

                    report_html = """
                                                <style>
                                                    table {
                                                        border-collapse: collapse;
                                                        width: 100%;
                                                        font-size: 13px;
                                                    }
                                                    th, td {
                                                        border: 1px solid #999;
                                                        padding: 6px;
                                                        text-align: center;
                                                    }
                                                    th {
                                                        background-color: #f2f2f2;
                                                    }
                                                    h3 {
                                                        margin-top: 30px;
                                                        text-align: left;
                                                    }
                                                    .warehouse-header {
                                                        background-color: #eaeaea;
                                                        font-weight: bold;
                                                        text-align: left;
                                                        font-size: 14px;
                                                        color: #0A0A0A;
                                                    }
                                                    .hsn-row {
                                                        background-color: #f8f9fa;
                                                    }
                                                    .grand-total-row {
                                                        background-color: #d4edda;
                                                        font-weight: bold;
                                                        color: #155724;
                                                    }
                                                </style>
                                            """

                    def build_section(title, data):
                        section_html = f"""<h3>{title}</h3>
                                                <table>
                                                    <thead>
                                                        <tr>
                                                            <th>SL NO</th>
                                                            <th>HSN</th>
                                                            <th>Description</th>
                                                            <th>UQC</th>
                                                            <th>Total Quantity</th>
                                                            <th>Total Value</th>
                                                            <th>Rate (%)</th>
                                                            <th>Taxable Value</th>
                                                            <th>Integrated Tax Amount</th>
                                                            <th>Central Tax Amount</th>
                                                            <th>State/UT Tax Amount</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody>
                                            """

                        # Warehouse-wise totals
                        total_qty = total_val = total_taxable = total_igst = total_cgst = total_sgst = 0.0
                        # Grand totals across all warehouses
                        grand_total_qty = grand_total_val = grand_total_taxable = grand_total_igst = grand_total_cgst = grand_total_sgst = 0.0
                        current_warehouse = None
                        sl_no = 0  # Initialize serial number counter

                        for detail in data:
                            if detail.get('is_warehouse_header'):
                                # Before starting new warehouse, print total for previous warehouse
                                if current_warehouse is not None:
                                    section_html += f"""
                                                            <tr style="font-weight: bold; background-color: #dfe3e6;">
                                                                <td colspan="4" style="text-align: right;">Total:</td>
                                                                <td>{total_qty}</td>
                                                                <td>{'{:,.2f}'.format(total_val)}</td>
                                                                <td></td>
                                                                <td>{'{:,.2f}'.format(total_taxable)}</td>
                                                                <td>{'{:,.2f}'.format(total_igst)}</td>
                                                                <td>{'{:,.2f}'.format(total_cgst)}</td>
                                                                <td>{'{:,.2f}'.format(total_sgst)}</td>
                                                            </tr>
                                                        """
                                    # Add warehouse totals to grand totals
                                    grand_total_qty += total_qty
                                    grand_total_val += total_val
                                    grand_total_taxable += total_taxable
                                    grand_total_igst += total_igst
                                    grand_total_cgst += total_cgst
                                    grand_total_sgst += total_sgst

                                # Reset totals and serial number for new warehouse
                                sl_no = 0  # Reset serial number for new branch
                                total_qty = total_val = total_taxable = total_igst = total_cgst = total_sgst = 0.0
                                current_warehouse = detail['warehouse']

                                # Warehouse Header Row
                                section_html += f"""
                                                        <tr class="warehouse-header">
                                                            <td colspan="11">Branch: {detail['warehouse']}</td>
                                                        </tr>
                                                    """
                            elif detail.get('is_hsn_row'):
                                sl_no += 1  # Increment serial number for each HSN row

                                qty = float(detail.get('total_qty', 0))
                                val = float(detail.get('total_value', 0))
                                taxable = float(detail.get('taxable_value', 0))
                                rate = float(detail.get('rate', 0.0))
                                igst = float(detail.get('igst', 0))
                                cgst = float(detail.get('cgst', 0))
                                sgst = float(detail.get('sgst', 0))

                                # Accumulate warehouse totals
                                total_qty += qty
                                total_val += val
                                total_taxable += taxable
                                total_igst += igst
                                total_cgst += cgst
                                total_sgst += sgst

                                section_html += f"""
                                                        <tr class="hsn-row">
                                                            <td>{sl_no}</td>
                                                            <td>{detail['hsn']}</td>
                                                            <td>{detail['desc']}</td>
                                                            <td>{detail['uqc']}</td>
                                                            <td>{qty}</td>
                                                            <td>{'{:,.2f}'.format(val)}</td>
                                                            <td>{'{:.2f}'.format(rate)}</td>
                                                            <td>{'{:,.2f}'.format(taxable)}</td>
                                                            <td>{'{:,.2f}'.format(igst)}</td>
                                                            <td>{'{:,.2f}'.format(cgst)}</td>
                                                            <td>{'{:,.2f}'.format(sgst)}</td>
                                                        </tr>
                                                    """

                        # Add total for the last warehouse
                        if current_warehouse is not None:
                            section_html += f"""
                                                    <tr style="font-weight: bold; background-color: #dfe3e6;">
                                                        <td colspan="4" style="text-align: right;">Total:</td>
                                                        <td>{total_qty}</td>
                                                        <td>{'{:,.2f}'.format(total_val)}</td>
                                                        <td></td>
                                                        <td>{'{:,.2f}'.format(total_taxable)}</td>
                                                        <td>{'{:,.2f}'.format(total_igst)}</td>
                                                        <td>{'{:,.2f}'.format(total_cgst)}</td>
                                                        <td>{'{:,.2f}'.format(total_sgst)}</td>
                                                    </tr>
                                                """
                            # Add last warehouse totals to grand totals
                            grand_total_qty += total_qty
                            grand_total_val += total_val
                            grand_total_taxable += total_taxable
                            grand_total_igst += total_igst
                            grand_total_cgst += total_cgst
                            grand_total_sgst += total_sgst

                        # Add Grand Total Row
                        section_html += f"""
                                                <tr class="grand-total-row">
                                                    <td colspan="4" style="text-align: right;">Grand Total:</td>
                                                    <td>{grand_total_qty}</td>
                                                    <td>{'{:,.2f}'.format(grand_total_val)}</td>
                                                    <td></td>
                                                    <td>{'{:,.2f}'.format(grand_total_taxable)}</td>
                                                    <td>{'{:,.2f}'.format(grand_total_igst)}</td>
                                                    <td>{'{:,.2f}'.format(grand_total_cgst)}</td>
                                                    <td>{'{:,.2f}'.format(grand_total_sgst)}</td>
                                                </tr>
                                            """

                        section_html += "</tbody></table>"
                        return section_html

                    report_html += build_section("B2C", b2c_lines)
                    return report_html
            elif rec.type == 'doc_summary':
                report_html = f"""
                   <style>
                       table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
                       th, td {{ border: 1px solid #999; padding: 6px; text-align: center; }}
                       th {{ background-color: #f2f2f2; }}
                       .doc-header {{ background-color: #eaeaea; font-weight: bold; text-align: left; }}
                   </style>
                   <table>
                       <thead>
                           <tr>
                                <th>Nature Of Document</th>
                                <th>Branch</th>
                                <th>From Voucher No</th>
                                <th>To Voucher No</th>
                                <th>Voucher Count</th>
                                <th>Cancelled</th>
                                <th>Net Issued</th>
                           </tr>
                       </thead>
                       <tbody>
                   """
                # 🔹 group invoice_details by doc_type
                doc_grouped = {}
                for detail in invoice_details:
                    doc_type = detail.get("doc_type", "Unknown")
                    doc_grouped.setdefault(doc_type, []).append(detail)
                # 🔹 fixed order of doc types
                doc_order = [
                    "B2B Sale",
                    "B2C Sale",
                    "B2B Credit Note",
                    "B2C Credit Note",
                    "Purchase",
                    "Debit Note",
                    "Delivery Challan",
                    "Receipt",
                    "Payment",
                ]
                for doc_type in doc_order:
                    if doc_type in doc_grouped:
                        # add doc_type row
                        report_html += f"""
                            <tr>
                                <td class="doc-header" colspan="7">{doc_type}</td>
                            </tr>
                        """
                        # add warehouse rows
                        for detail in doc_grouped[doc_type]:
                            report_html += f"""
                                <tr>
                                    <td></td> <!-- empty because doc_type is already shown -->
                                    <td>{detail.get('branch', '')}</td>
                                    <td>{detail.get('from_no', '')}</td>
                                    <td>{detail.get('to_no', '')}</td>
                                    <td>{detail.get('vch_count', '')}</td>
                                    <td>{detail.get('cancel_count', '')}</td>
                                    <td>{detail.get('net_count', '')}</td>
                                </tr>
                            """
                report_html += """
                      </tbody>
                  </table>
                  """

            elif rec.type == 'gstr1_summary':
                report_html = f"""
                       <style>
                           table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
                           th, td {{ border: 1px solid #999; padding: 6px; text-align: center; }}
                           th {{ background-color: #f2f2f2; }}
                       </style>
                       <table>
                           <thead>
                               <tr>
                                    <th></th>
                                    <th>Voucher Count</th>
                                    <th>Taxable Amount</th>
                                    <th>Tax Amount</th>
                                    <th>Invoice Amount</th>
                               </tr>
                           </thead>
                           <tbody>
                       """
                doc_types = ['B2B Invoices', 'B2C Large', 'B2C Small', 'Credit/Debit Registered',
                             'Credit/Debit UnRegistered']
                # Initialize totals
                total_voucher_count = 0
                total_untax_value = 0.0
                total_tax_value = 0.0
                total_inv_value = 0.0
                for doc_type in doc_types:
                    matched_detail = next((d for d in invoice_details if d.get('doc_type') == doc_type), None)
                    if matched_detail:
                        tax_value = matched_detail.get('total_tax_value', 0.0)
                        voucher_count = matched_detail.get('voucher_count', 0)
                        inv_value = matched_detail.get('total_inv_value', 0.0)
                        untax_value = matched_detail.get('total_untax_value', 0.0)
                        total_voucher_count += voucher_count or 0
                        total_untax_value += untax_value or 0.0
                        total_tax_value += tax_value or 0.0
                        total_inv_value += inv_value or 0.0
                    else:
                        tax_value = voucher_count = inv_value = untax_value = ''
                    report_html += f"""
                               <tr>
                                   <td>{doc_type}</td>
                                   <td>{voucher_count}</td>
                                   <td>{round(untax_value, 2) if untax_value != '' else ''}</td>
                                   <td>{round(tax_value, 2) if tax_value != '' else ''}</td>
                                   <td>{round(inv_value, 2) if inv_value != '' else ''}</td>
                               </tr>
                           """
                # Append totals row
                report_html += f"""
                           <tr style="font-weight: bold; background-color: #e2e2e2;">
                               <td>Total</td>
                               <td>{total_voucher_count}</td>
                               <td>{round(total_untax_value, 2)}</td>
                               <td>{round(total_tax_value, 2)}</td>
                               <td>{round(total_inv_value, 2)}</td>
                           </tr>
                       """
                report_html += """
                          </tbody>
                      </table>
                      """
            else:
                report_html = ""
        return report_html

    def generate_excel_report(self):
        if self.type == 'b2b':
            return self.export_b2b_excel()
        elif self.type == 'b2c_large':
            return self.export_b2c_large_excel()
        elif self.type == 'b2c_small':
            return self.export_b2c_small_excel()
        elif self.type == 'd/c_reg_customer':
            return self.export_dc_reg_customer_excel()
        elif self.type == 'd/c_unreg_customer':
            return self.export_dc_unreg_customer_excel()
        elif self.type == 'tcs_input':
            return self.export_tcs_input_excel()
        elif self.type == 'tcs_output':
            return self.export_tcs_output_excel()
        elif self.type == 'hsn' and self.hsn_type != 'all':
            return self.export_hsn_excel()
        elif self.type == 'hsn' and self.hsn_type == 'all':
            return self.export_hsn_all_excel()
        elif self.type == 'doc_summary':
            return self.export_doc_summary_excel()
        elif self.type == 'gstr1_summary':
            return self.export_gstr1_summary_excel()
        else:
            raise UserError("No Excel export template defined for this type.")

    def _download_xlsx(self, workbook_generator, file_name):
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        workbook_generator(workbook)
        workbook.close()
        output.seek(0)
        attachment = self.env['ir.attachment'].create({
            'name': file_name,
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def export_b2b_excel(self):
        self.ensure_one()
        def gen(workbook):
            self.env['report.prosevo_erp_accounts_management.gstirn1_b2b_xlsx_temp'].generate_xlsx_report(workbook, {}, self)
        return self._download_xlsx(gen, f"B2B_{self.start_date.strftime('%Y%m%d')}.xlsx")

    def export_b2c_large_excel(self):
        self.ensure_one()
        def gen(workbook):
            self.env['report.prosevo_erp_accounts_management.b2c_large_xlsx_temp'].generate_xlsx_report(workbook, {}, self)
        return self._download_xlsx(gen, f"B2C_Large_{self.start_date.strftime('%Y%m%d')}.xlsx")

    def export_b2c_small_excel(self):
        self.ensure_one()
        def gen(workbook):
            self.env['report.prosevo_erp_accounts_management.b2c_small_xlsx_temp'].generate_xlsx_report(workbook, {}, self)
        return self._download_xlsx(gen, f"B2C_Small_{self.start_date.strftime('%Y%m%d')}.xlsx")

    def export_dc_reg_customer_excel(self):
        self.ensure_one()
        def gen(workbook):
            self.env['report.prosevo_erp_accounts_management.dc_reg_cust_xlsx_temp'].generate_xlsx_report(workbook, {}, self)
        return self._download_xlsx(gen, f"DC_Registered_{self.start_date.strftime('%Y%m%d')}.xlsx")

    def export_dc_unreg_customer_excel(self):
        self.ensure_one()
        def gen(workbook):
            self.env['report.prosevo_erp_accounts_management.dc_unreg_cust_xlsx_temp'].generate_xlsx_report(workbook, {}, self)
        return self._download_xlsx(gen, f"DC_Unregistered_{self.start_date.strftime('%Y%m%d')}.xlsx")

    def export_tcs_input_excel(self):
        self.ensure_one()
        def gen(workbook):
            self.env['report.prosevo_erp_accounts_management.tcs_input_xlsx_temp'].generate_xlsx_report(workbook, {}, self)
        return self._download_xlsx(gen, f"TCS_Input_{self.start_date.strftime('%Y%m%d')}.xlsx")

    def export_tcs_output_excel(self):
        self.ensure_one()
        def gen(workbook):
            self.env['report.prosevo_erp_accounts_management.tcs_output_xlsx_temp'].generate_xlsx_report(workbook, {}, self)
        return self._download_xlsx(gen, f"TCS_Output_{self.start_date.strftime('%Y%m%d')}.xlsx")

    def export_hsn_excel(self):
        self.ensure_one()
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet("HSN Report")

        title_format = workbook.add_format({'bold': True, 'font_size': 16, 'align': 'center'})
        subtitle_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'})
        label_format = workbook.add_format({'bold': True})
        header_format = workbook.add_format({'bold': True, 'bg_color': '#B7DEE8', 'border': 1, 'align': 'center'})
        warehouse_format = workbook.add_format({'bold': True, 'bg_color': '#eaeaea', 'border': 1, 'align': 'left'})
        normal_format = workbook.add_format({'border': 1, 'align': 'center'})
        total_format = workbook.add_format({'bold': True, 'border': 1, 'align': 'center'})
        grand_total_format = workbook.add_format({'bold': True, 'border': 1, 'align': 'center', 'bg_color': '#FFE6CC'})

        # Set column widths
        worksheet.set_column('A:A', 8)
        worksheet.set_column('B:B', 12)
        worksheet.set_column('C:C', 30)
        worksheet.set_column('D:D', 8)
        worksheet.set_column('E:K', 15)

        # Title
        worksheet.merge_range('A1:K1', self.env.company.name, title_format)
        worksheet.merge_range('A2:K2', 'GSTR1 HSN Report', subtitle_format)

        # Date Range
        worksheet.write('A4', 'From:', label_format)
        worksheet.write('B4', self.start_date.strftime('%d-%b-%Y') if self.start_date else '')
        worksheet.write('A5', 'To:', label_format)
        worksheet.write('B5', self.end_date.strftime('%d-%b-%Y') if self.end_date else '')
        worksheet.write('A6', 'Branch:', label_format)
        worksheet.write('B6', self.warehouse_id.name if self.warehouse_id else 'All Branches')

        # Section Heading
        if self.hsn_type == 'hsn_b2b':
            section_title = "B2B"
        elif self.hsn_type == 'hsn_b2c':
            section_title = "B2C"
        else:
            section_title = "All"

        worksheet.merge_range('A7:K7', section_title, header_format)

        # Header Row
        headers = ['SL NO', 'HSN', 'Description', 'UQC', 'Total Quantity', 'Total Value', 'Rate (%)',
                   'Taxable Value', 'IGST', 'CGST', 'SGST']
        for col, header in enumerate(headers):
            worksheet.write(7, col, header, header_format)

        # Get report data
        report_data = self._gather_report_data()
        if self.hsn_type == 'hsn_b2b':
            lines = report_data.get('b2b_lines', [])
        elif self.hsn_type == 'hsn_b2c':
            lines = report_data.get('b2c_lines', [])
        else:
            lines = report_data.get('b2b_lines', []) + report_data.get('b2c_lines', [])

        row = 8

        branch_totals = {
            'qty': 0.0,
            'val': 0.0,
            'taxable': 0.0,
            'igst': 0.0,
            'cgst': 0.0,
            'sgst': 0.0,
        }
        grand_totals = {
            'qty': 0.0,
            'val': 0.0,
            'taxable': 0.0,
            'igst': 0.0,
            'cgst': 0.0,
            'sgst': 0.0,
        }

        current_branch = None
        branch_sl_no = 0

        for line in lines:
            if line.get('is_warehouse_header'):
                branch_sl_no = 0
                # If switching branch, write previous branch totals
                if current_branch:
                    worksheet.write(row, 0, "Total", total_format)
                    worksheet.write_blank(row, 1, None, total_format)
                    worksheet.write_blank(row, 2, None, total_format)
                    worksheet.write_blank(row, 3, None, total_format)
                    worksheet.write_number(row, 4, branch_totals['qty'], total_format)
                    worksheet.write_number(row, 5, branch_totals['val'], total_format)
                    worksheet.write_blank(row, 6, None, total_format)
                    worksheet.write_number(row, 7, branch_totals['taxable'], total_format)
                    worksheet.write_number(row, 8, branch_totals['igst'], total_format)
                    worksheet.write_number(row, 9, branch_totals['cgst'], total_format)
                    worksheet.write_number(row, 10, branch_totals['sgst'], total_format)
                    row += 1

                    # Add branch totals to grand totals
                    for k in grand_totals:
                        grand_totals[k] += branch_totals[k]

                    # Reset branch totals
                    branch_totals = {k: 0.0 for k in branch_totals}

                current_branch = line.get('warehouse')
                # Write warehouse header row
                worksheet.merge_range(row, 0, row, 10, f"Branch: {current_branch}", warehouse_format)
                row += 1

            elif line.get('is_hsn_row', True):
                branch_sl_no += 1
                qty = float(line.get('total_qty', 0))
                val = float(line.get('total_value', 0))
                rate = float(line.get('rate', 0))
                taxable = float(line.get('taxable_value', 0))
                igst = float(line.get('igst', 0))
                cgst = float(line.get('cgst', 0))
                sgst = float(line.get('sgst', 0))

                # Write HSN row
                worksheet.write(row, 0, branch_sl_no, normal_format)
                worksheet.write(row, 1, line.get('hsn'), normal_format)
                worksheet.write(row, 2, line.get('desc'), normal_format)
                worksheet.write(row, 3, line.get('uqc'), normal_format)
                worksheet.write_number(row, 4, qty, normal_format)
                worksheet.write_number(row, 5, val, normal_format)
                worksheet.write_number(row, 6, rate, normal_format)
                worksheet.write_number(row, 7, taxable, normal_format)
                worksheet.write_number(row, 8, igst, normal_format)
                worksheet.write_number(row, 9, cgst, normal_format)
                worksheet.write_number(row, 10, sgst, normal_format)

                # Update branch totals
                branch_totals['qty'] += qty
                branch_totals['val'] += val
                branch_totals['taxable'] += taxable
                branch_totals['igst'] += igst
                branch_totals['cgst'] += cgst
                branch_totals['sgst'] += sgst

                row += 1

        # Write last branch total
        if current_branch:
            worksheet.write(row, 0, "Total", total_format)
            worksheet.write_blank(row, 1, None, total_format)
            worksheet.write_blank(row, 2, None, total_format)
            worksheet.write_blank(row, 3, None, total_format)
            worksheet.write_number(row, 4, branch_totals['qty'], total_format)
            worksheet.write_number(row, 5, branch_totals['val'], total_format)
            worksheet.write_blank(row, 6, None, total_format)
            worksheet.write_number(row, 7, branch_totals['taxable'], total_format)
            worksheet.write_number(row, 8, branch_totals['igst'], total_format)
            worksheet.write_number(row, 9, branch_totals['cgst'], total_format)
            worksheet.write_number(row, 10, branch_totals['sgst'], total_format)
            row += 1

            # Add last branch totals to grand totals
            for k in grand_totals:
                grand_totals[k] += branch_totals[k]

        # Write Grand Total row
        if grand_totals['qty'] > 0 or grand_totals['val'] > 0:  # Only write if there's data
            row += 1  # Add a blank row for separation
            worksheet.write(row, 0, "GRAND TOTAL", grand_total_format)
            worksheet.write_blank(row, 1, None, grand_total_format)
            worksheet.write_blank(row, 2, None, grand_total_format)
            worksheet.write_blank(row, 3, None, grand_total_format)
            worksheet.write_number(row, 4, grand_totals['qty'], grand_total_format)
            worksheet.write_number(row, 5, grand_totals['val'], grand_total_format)
            worksheet.write_blank(row, 6, None, grand_total_format)
            worksheet.write_number(row, 7, grand_totals['taxable'], grand_total_format)
            worksheet.write_number(row, 8, grand_totals['igst'], grand_total_format)
            worksheet.write_number(row, 9, grand_totals['cgst'], grand_total_format)
            worksheet.write_number(row, 10, grand_totals['sgst'], grand_total_format)

        workbook.close()
        output.seek(0)

        # Download as attachment
        file_name = f"HSN_{section_title}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': file_name,
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def export_hsn_all_excel(self):
        """Export HSN All report to Excel with B2B and B2C sections like HTML report"""
        self.ensure_one()
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet("HSN All Report")

        # Define formats
        title_format = workbook.add_format({'bold': True, 'font_size': 16, 'align': 'center'})
        subtitle_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'})
        section_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'left', 'bg_color': '#D9D9D9'})
        warehouse_format = workbook.add_format(
            {'bold': True, 'bg_color': '#EAEAEA', 'align': 'left', 'font_color': '#0A0A0A'})
        header_format = workbook.add_format({'bold': True, 'bg_color': '#F2F2F2', 'border': 1, 'align': 'center'})
        hsn_format = workbook.add_format({'bg_color': '#F8F9FA', 'border': 1, 'align': 'center'})
        normal_format = workbook.add_format({'border': 1, 'align': 'center'})
        total_format = workbook.add_format({'bold': True, 'border': 1, 'align': 'center', 'bg_color': '#E2E2E2'})
        warehouse_total_format = workbook.add_format(
            {'bold': True, 'border': 1, 'align': 'center', 'bg_color': '#dfe3e6'})
        label_format = workbook.add_format({'bold': True})

        # Set column widths
        worksheet.set_column('A:A', 8)  # SL NO
        worksheet.set_column('B:B', 12)  # HSN
        worksheet.set_column('C:C', 30)  # Description
        worksheet.set_column('D:D', 8)  # UQC
        worksheet.set_column('E:K', 15)  # Numeric columns

        # Title and header info
        worksheet.merge_range('A1:K1', self.env.company.name, title_format)
        worksheet.merge_range('A2:K2', 'GSTR1 HSN All Report', subtitle_format)

        # Date Range
        worksheet.write('A4', 'From:', label_format)
        worksheet.write('B4', self.start_date.strftime('%d-%b-%Y') if self.start_date else '')
        worksheet.write('A5', 'To:', label_format)
        worksheet.write('B5', self.end_date.strftime('%d-%b-%Y') if self.end_date else '')

        # Branch info
        worksheet.write('A6', 'Branch:', label_format)
        worksheet.write('B6', self.warehouse_id.name if self.warehouse_id else 'All Branches', label_format)

        # Get report data
        report_data = self._gather_report_data()
        b2b_lines = report_data.get('b2b_lines', [])
        b2c_lines = report_data.get('b2c_lines', [])

        current_row = 8  # Start from row 8 (0-based indexing, so this is row 8)

        def write_section(section_title, data, start_row):
            """Write a section (B2B or B2C) to the worksheet"""
            row = start_row

            # Section header
            worksheet.merge_range(f'A{row}:K{row}', section_title, section_format)
            row += 1

            # Column headers - FIXED: Write at current row, not row-1
            headers = ['SL NO', 'HSN', 'Description', 'UQC', 'Total Quantity', 'Total Value',
                       'Rate (%)', 'Taxable Value', 'Integrated Tax Amount', 'Central Tax Amount',
                       'State/UT Tax Amount']
            for col, header in enumerate(headers):
                worksheet.write(row - 1, col, header, header_format)  # Fixed: Use row-1 correctly
            row += 1  # Move to next row after headers

            # Initialize section totals
            section_total_qty = section_total_val = section_total_taxable = 0.0
            section_total_igst = section_total_cgst = section_total_sgst = 0.0

            # Initialize warehouse totals
            warehouse_total_qty = warehouse_total_val = warehouse_total_taxable = 0.0
            warehouse_total_igst = warehouse_total_cgst = warehouse_total_sgst = 0.0
            current_warehouse = None
            warehouse_sl_no = 0

            for detail in data:
                if detail.get('is_warehouse_header'):
                    # Before starting new warehouse, print total for previous warehouse
                    if current_warehouse is not None:
                        worksheet.merge_range(f'A{row}:D{row}', f'Total :', warehouse_total_format)
                        worksheet.write_number(row - 1, 4, warehouse_total_qty, warehouse_total_format)
                        worksheet.write_number(row - 1, 5, warehouse_total_val, warehouse_total_format)
                        worksheet.write(row - 1, 6, '', warehouse_total_format)
                        worksheet.write_number(row - 1, 7, warehouse_total_taxable, warehouse_total_format)
                        worksheet.write_number(row - 1, 8, warehouse_total_igst, warehouse_total_format)
                        worksheet.write_number(row - 1, 9, warehouse_total_cgst, warehouse_total_format)
                        worksheet.write_number(row - 1, 10, warehouse_total_sgst, warehouse_total_format)
                        row += 1

                    # Reset warehouse totals for new warehouse
                    warehouse_total_qty = warehouse_total_val = warehouse_total_taxable = 0.0
                    warehouse_total_igst = warehouse_total_cgst = warehouse_total_sgst = 0.0

                    warehouse_sl_no = 0
                    current_warehouse = detail['warehouse']

                    # Warehouse Header Row
                    worksheet.merge_range(f'A{row}:K{row}', f"Branch: {detail['warehouse']}", warehouse_format)
                    row += 1

                elif detail.get('is_hsn_row'):
                    warehouse_sl_no += 1
                    # HSN Data Row
                    qty = float(detail.get('total_qty', 0))
                    val = float(detail.get('total_value', 0))
                    rate = float(detail.get('rate', 0.0))
                    taxable = float(detail.get('taxable_value', 0))
                    igst = float(detail.get('igst', 0))
                    cgst = float(detail.get('cgst', 0))
                    sgst = float(detail.get('sgst', 0))

                    # Write HSN row data
                    worksheet.write(row - 1, 0, warehouse_sl_no, hsn_format)
                    worksheet.write(row - 1, 1, detail.get('hsn'), hsn_format)
                    worksheet.write(row - 1, 2, detail.get('desc'), hsn_format)
                    worksheet.write(row - 1, 3, detail.get('uqc'), hsn_format)
                    worksheet.write_number(row - 1, 4, qty, hsn_format)
                    worksheet.write_number(row - 1, 5, val, hsn_format)
                    worksheet.write_number(row - 1, 6, rate, hsn_format)
                    worksheet.write_number(row - 1, 7, taxable, hsn_format)
                    worksheet.write_number(row - 1, 8, igst, hsn_format)
                    worksheet.write_number(row - 1, 9, cgst, hsn_format)
                    worksheet.write_number(row - 1, 10, sgst, hsn_format)

                    # Add to warehouse totals
                    warehouse_total_qty += qty
                    warehouse_total_val += val
                    warehouse_total_taxable += taxable
                    warehouse_total_igst += igst
                    warehouse_total_cgst += cgst
                    warehouse_total_sgst += sgst

                    # Add to section totals
                    section_total_qty += qty
                    section_total_val += val
                    section_total_taxable += taxable
                    section_total_igst += igst
                    section_total_cgst += cgst
                    section_total_sgst += sgst

                    row += 1

            # Write total for the last warehouse
            if current_warehouse is not None:
                worksheet.merge_range(f'A{row}:D{row}', f'Total :', warehouse_total_format)
                worksheet.write_number(row - 1, 4, warehouse_total_qty, warehouse_total_format)
                worksheet.write_number(row - 1, 5, warehouse_total_val, warehouse_total_format)
                worksheet.write(row - 1, 6, '', warehouse_total_format)
                worksheet.write_number(row - 1, 7, warehouse_total_taxable, warehouse_total_format)
                worksheet.write_number(row - 1, 8, warehouse_total_igst, warehouse_total_format)
                worksheet.write_number(row - 1, 9, warehouse_total_cgst, warehouse_total_format)
                worksheet.write_number(row - 1, 10, warehouse_total_sgst, warehouse_total_format)
                row += 1

            # Write section totals
            worksheet.write(row - 1, 0, '', total_format)
            worksheet.write(row - 1, 1, '', total_format)
            worksheet.write(row - 1, 2, '', total_format)
            worksheet.write(row - 1, 3, ' Grand Total', total_format)
            worksheet.write_number(row - 1, 4, section_total_qty, total_format)
            worksheet.write_number(row - 1, 5, section_total_val, total_format)
            worksheet.write(row - 1, 6, '', total_format)
            worksheet.write_number(row - 1, 7, section_total_taxable, total_format)
            worksheet.write_number(row - 1, 8, section_total_igst, total_format)
            worksheet.write_number(row - 1, 9, section_total_cgst, total_format)
            worksheet.write_number(row - 1, 10, section_total_sgst, total_format)

            return row + 2  # Return next available row with some spacing

        # Write B2B Section
        if b2b_lines:
            current_row = write_section("B2B", b2b_lines, current_row)

        # Write B2C Section
        if b2c_lines:
            current_row = write_section("B2C", b2c_lines, current_row)

        workbook.close()
        output.seek(0)

        # Create attachment for download
        file_name = f"HSN_All_Report_{self.start_date.strftime('%Y%m%d')}_{self.end_date.strftime('%Y%m%d')}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': file_name,
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    # def export_doc_summary_excel(self):
    #     self.ensure_one()  # Good practice to avoid looping unless needed
    #     data = {
    #         'ids': self.ids,
    #         'model': self._name,
    #         'form': {
    #             'date_from': self.start_date,
    #             'date_to': self.end_date,
    #             'warehouse_id': self.warehouse_id.id if self.warehouse_id else False,
    #             'type': self.type if self.type else False,
    #         },
    #     }
    #     file_name = 'Document Summary From %s to %s' % (
    #         self.start_date.strftime('%Y-%m-%d'),
    #         self.end_date.strftime('%Y-%m-%d')
    #     )
    #     # Optional: set file name on the report record (if used in the UI)
    #     self.env.ref('prosevo_erp_accounts_management.doc_summary_excel').sudo().report_file = file_name
    #     # Trigger the report download
    #     return self.env.ref('prosevo_erp_accounts_management.doc_summary_excel').report_action(self, data=data)
    #
    # def export_gstr1_summary_excel(self):
    #     self.ensure_one()  # Good practice to avoid looping unless needed
    #     data = {
    #         'ids': self.ids,
    #         'model': self._name,
    #         'form': {
    #             'date_from': self.start_date,
    #             'date_to': self.end_date,
    #             'warehouse_id': self.warehouse_id.id if self.warehouse_id else False,
    #             'type': self.type if self.type else False,
    #         },
    #     }
    #     file_name = 'Gstr1 Summary From %s to %s' % (
    #         self.start_date.strftime('%Y-%m-%d'),
    #         self.end_date.strftime('%Y-%m-%d')
    #     )
    #     # Optional: set file name on the report record (if used in the UI)
    #     self.env.ref('prosevo_erp_accounts_management.gstr1_summary_excel').sudo().report_file = file_name
    #     # Trigger the report download
    #     return self.env.ref('prosevo_erp_accounts_management.gstr1_summary_excel').report_action(self, data=data)

    def generate_pdf_report(self):

        self.ensure_one()
        pdf_content = self._generate_pdf_content()

        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=landscape(letter))
        elements = []

        # Add content to PDF
        styles = getSampleStyleSheet()
        elements.append(
            Paragraph("GST Report - " + dict(self._fields['type'].selection).get(self.type), styles['Title']))
        elements.append(Spacer(1, 0.2 * inch))

        # Add filter information
        filter_info = [
            f"From : {self.start_date.strftime('%d-%b-%Y')}",
            f"To : {self.end_date.strftime('%d-%b-%Y')}",
            f"Branch: {self.warehouse_id.name or 'ALL BRANCHES'}"
        ]

        for info in filter_info:
            elements.append(Paragraph(info, styles['Normal']))
            elements.append(Spacer(1, 0.1 * inch))

        elements.append(Spacer(1, 0.2 * inch))
        # Handle pdf_content as a list of flowables or a single flowable
        if isinstance(pdf_content, list):
            elements.extend(pdf_content)
        else:
            elements.append(pdf_content)

        doc.build(elements)

        pdf_buffer.seek(0)
        pdf_data = pdf_buffer.read()
        # Determine filename dynamically
        if self.type == 'hsn':
            if self.hsn_type == 'hsn_b2b':
                filename = f"B2B_HSN_Report_{fields.Date.today()}.pdf"
            elif self.hsn_type == 'hsn_b2c':
                filename = f"B2C_HSN_Report_{fields.Date.today()}.pdf"
            else:
                filename = f"HSN_Report_{fields.Date.today()}.pdf"
        else:
            filename = f"GST_{self.type}_Report_{fields.Date.today()}.pdf"

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(pdf_data),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf'
        })


        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
    def _generate_pdf_content(self):
        report_data = self._gather_report_data()
        lines = report_data.get('lines', [])
        table_data = []

        if self.type == 'b2b':
            headers = ['SL.NO', 'GSTIN', 'Customer Name', 'Invoice No', 'Date',
                       'Invoice Value', 'Place of Supply', 'Reverse Charge',
                       'Invoice Type', 'Rate', 'Taxable Value']
            table_data = [headers]
            total_invoice_value = 0
            total_taxable_value = 0

            for line in lines:
                inv_value = line.get('inv_value', 0)
                taxable_value = line.get('taxable_value', 0)
                total_invoice_value += inv_value
                total_taxable_value += taxable_value
                table_data.append([
                    line.get('sl_no', ''),
                    line.get('gstin_customer', ''),
                    line.get('customer_name', ''),
                    line.get('inv_no', ''),
                    line.get('date', ''),
                    '{:,.2f}'.format(inv_value),
                    line.get('place_of_supply', ''),
                    line.get('reverse_charge', ''),
                    line.get('inv_type', ''),
                    line.get('rate', ''),
                    '{:,.2f}'.format(taxable_value)
                ])

            # Append total row only once at the bottom
            table_data.append([
                '', '', '', '', 'Total',
                '{:,.2f}'.format(total_invoice_value),
                '', '', '', '',
                '{:,.2f}'.format(total_taxable_value)
            ])

        elif self.type == 'b2c_large':
            lines = report_data.get('lines', [])
            headers = ['SL.NO', 'Invoice No', 'Invoice Date', 'Invoice Value',
                       'Place of Supply', 'Rate', 'Taxable Value']
            table_data = [headers]
            total_invoice_value = 0.0
            total_taxable_value = 0.0

            for line in lines:
                inv_value = line.get('inv_value', 0.0)
                taxable_value = line.get('taxable_value', 0.0)
                total_invoice_value += inv_value
                total_taxable_value += taxable_value
                table_data.append([
                    line.get('sl_no', ''),
                    line.get('inv_no', ''),
                    line.get('date', ''),
                    '{:,.2f}'.format(inv_value),
                    line.get('place_of_supply', ''),
                    line.get('rate', ''),
                    '{:,.2f}'.format(taxable_value),
                ])

            if not lines:
                table_data.append(['', '', 'Total', '0.00', '', '', '0.00'])
            else:
                table_data.append([
                    '', '', 'Total',
                    '{:,.2f}'.format(total_invoice_value),
                    '', '',
                    '{:,.2f}'.format(total_taxable_value),
                ])

        elif self.type == 'b2c_small':
            headers = ['SL.NO', 'Place of Supply', 'Rate', 'Taxable Value']
            table_data = [headers]
            total_taxable_value = 0
            for line in lines:
                taxable_value = line.get('taxable_value', 0)
                total_taxable_value += taxable_value
                table_data.append([
                    line.get('sl_no', ''),
                    line.get('place_of_supply', ''),
                    line.get('rate', ''),
                    '{:,.2f}'.format(taxable_value)
                ])
            table_data.append([
                '', 'Total', '',
                '{:,.2f}'.format(total_taxable_value)
            ])

        elif self.type == 'd/c_reg_customer':
            domain = [
                ('partner_id.vat', '!=', False),
                ('move_type', 'in', ['out_refund', 'in_refund']),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', self.start_date),
                ('invoice_date', '<=', self.end_date)
            ]
            if self.warehouse_id:
                domain.append(('warehouse_id', '=', self.warehouse_id.id))
            invoices = self.env['account.move'].search(domain, order='invoice_date asc, name asc')
            lines = []
            for i, inv in enumerate(invoices, 1):
                line_untaxed_total = sum(line.price_subtotal for line in inv.invoice_line_ids)
                inv_ref_date = ''
                if inv.invoice_ref:
                    original_inv = self.env['account.move'].search([('name', '=', inv.invoice_ref)], limit=1)
                    if original_inv and original_inv.invoice_date:
                        inv_ref_date = original_inv.invoice_date.strftime('%d-%b-%Y')
                lines.append({
                    'sl_no': i,
                    'gstin_customer': inv.partner_id.vat or '',
                    'supplier_name': inv.partner_id.name if inv.partner_id else '',  # ADD THIS LINE
                    'inv_ref': inv.invoice_ref or '',
                    'inv_ref_date': inv_ref_date,
                    'inv_no': inv.name,
                    'date': inv.invoice_date.strftime('%d-%b-%Y') if inv.invoice_date else '',
                    'doc_type': 'Debit Note' if inv.move_type == 'in_refund' else 'Credit Note',
                    'place_of_supply': f"{inv.State_id.l10n_in_tin}-{inv.State_id.name}" if inv.State_id else '',
                    'total_value': round(inv.amount_total, 2),
                    'rate': self._get_total_tax_rate(inv),
                    'taxable_value': round(line_untaxed_total, 2)
                })

            headers = [
                'SL NO', 'GSTIN of Recipient', 'Supplier Name',  # ADD 'Supplier Name'
                'Invoice/Advance Receipt Number',
                'Invoice/Advance Receipt date', 'Note/Refund Voucher Number',
                'Note/Refund Voucher date', 'Document Type', 'Place Of Supply',
                'Note/Refund Voucher Value', 'Rate', 'Taxable Value'
            ]
            table_data = [headers]
            total_value = 0.0
            total_taxable = 0.0
            for line in lines:
                table_data.append([
                    line['sl_no'],
                    line['gstin_customer'],
                    line['supplier_name'],  # ADD THIS LINE
                    line['inv_ref'],
                    line['inv_ref_date'],
                    line['inv_no'],
                    line['date'],
                    line['doc_type'],
                    line['place_of_supply'],
                    '{:,.2f}'.format(line['total_value']),
                    line['rate'],
                    '{:,.2f}'.format(line['taxable_value'])
                ])
                total_value += line['total_value']
                total_taxable += line['taxable_value']
            # Add totals row - UPDATE COLSPAN POSITION
            table_data.append([
                '', '', '', '', '', '', '', '', 'Total',  # Changed from 7 empty strings to 8
                '{:,.2f}'.format(total_value),
                '',
                '{:,.2f}'.format(total_taxable)
            ])

        elif self.type == 'd/c_unreg_customer':
            domain = [
                ('partner_id.vat', '!=', False),
                ('move_type', 'in', ['out_refund', 'in_refund']),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', self.start_date),
                ('invoice_date', '<=', self.end_date)
            ]
            if self.warehouse_id:
                domain.append(('warehouse_id', '=', self.warehouse_id.id))
            invoices = self.env['account.move'].search(domain, order='invoice_date asc, name asc')
            lines = []
            for i, inv in enumerate(invoices, 1):
                line_untaxed_total = sum(line.price_subtotal for line in inv.invoice_line_ids)
                inv_ref_date = ''
                if inv.invoice_ref:
                    original_inv = self.env['account.move'].search([('name', '=', inv.invoice_ref)], limit=1)
                    if original_inv and original_inv.invoice_date:
                        inv_ref_date = original_inv.invoice_date.strftime('%d-%b-%Y')
                lines.append({
                    'sl_no': i,
                    'gstin_customer': '',  # Unregistered customers won't have GSTIN
                    'supplier_name': inv.partner_id.name if inv.partner_id else '',  # ADD THIS LINE
                    'inv_ref': inv.invoice_ref or '',
                    'inv_ref_date': inv_ref_date,
                    'inv_no': inv.name,
                    'date': inv.invoice_date.strftime('%d-%b-%Y') if inv.invoice_date else '',
                    'doc_type': 'Debit Note' if inv.move_type == 'in_refund' else 'Credit Note',
                    'place_of_supply': f"{inv.State_id.l10n_in_tin}-{inv.State_id.name}" if inv.State_id else '',
                    'total_value': round(inv.amount_total, 2),
                    'rate': self._get_total_tax_rate(inv),
                    'taxable_value': round(line_untaxed_total, 2)
                })
            headers = [
                'SL NO', 'GSTIN of Recipient', 'Supplier Name',  # ADD 'Supplier Name'
                'Invoice/Advance Receipt Number',
                'Invoice/Advance Receipt date', 'Note/Refund Voucher Number',
                'Note/Refund Voucher date', 'Document Type', 'Place Of Supply',
                'Note/Refund Voucher Value', 'Rate', 'Taxable Value'
            ]
            table_data = [headers]
            total_value = 0.0
            total_taxable = 0.0

            for line in lines:
                table_data.append([
                    line['sl_no'],
                    line['gstin_customer'],
                    line['supplier_name'],  # ADD THIS LINE
                    line['inv_ref'],
                    line['inv_ref_date'],
                    line['inv_no'],
                    line['date'],
                    line['doc_type'],
                    line['place_of_supply'],
                    '{:,.2f}'.format(line['total_value']),
                    line['rate'],
                    '{:,.2f}'.format(line['taxable_value'])
                ])
                total_value += line['total_value']
                total_taxable += line['taxable_value']

            # Add totals row - UPDATE COLSPAN POSITION
            table_data.append([
                '', '', '', '', '', '', '', '', 'Total',  # Changed from 7 empty strings to 8
                '{:,.2f}'.format(total_value),
                '',
                '{:,.2f}'.format(total_taxable)
            ])

        elif self.type == 'hsn':

            hsn_data = self._gather_report_data()

            headers = [
                'SL NO', 'HSN', 'Description', 'UQC', 'Total Quantity',
                'Total Value', 'Rate (%)', 'Taxable Value', 'IGST', 'CGST', 'SGST'
            ]

            elements = []
            styles = getSampleStyleSheet()

            # Define styles
            header_style = styles['Normal']
            header_style.fontSize = 8
            header_style.leading = 10
            header_style.alignment = 0
            normal_style = styles['Normal']
            normal_style.fontSize = 7
            normal_style.leading = 9
            warehouse_style = styles['Normal']
            warehouse_style.fontSize = 8
            warehouse_style.leading = 10
            warehouse_style.alignment = 0  # Left align
            warehouse_style.textColor = colors.HexColor('#0A0A0A')
            section_style = styles['Heading3']
            section_style.fontSize = 12
            section_style.spaceAfter = 6

            def build_table_with_warehouses(data, title):
                """Build table that handles warehouse headers, HSN rows, and warehouse totals"""

                section_elements = []

                # Add section title
                section_elements.append(Paragraph(title, section_style))

                section_elements.append(Spacer(1, 0.1 * inch))

                # Initialize table data with headers

                table_data = [headers]

                section_total_qty = section_total_val = section_total_taxable = 0.0

                section_total_igst = section_total_cgst = section_total_sgst = 0.0

                # Warehouse totals tracking

                warehouse_total_qty = warehouse_total_val = warehouse_total_taxable = 0.0

                warehouse_total_igst = warehouse_total_cgst = warehouse_total_sgst = 0.0

                current_warehouse = None

                warehouse_sl_no = 0  # Serial number counter for each warehouse

                for detail in data:

                    if detail.get('is_warehouse_header'):

                        # Before starting new warehouse, add total for previous warehouse

                        if current_warehouse is not None:
                            warehouse_total_row = [
                                f"Total :", '', '', '',
                                '{:,.2f}'.format(warehouse_total_qty),
                                '{:,.2f}'.format(warehouse_total_val),
                                '',
                                '{:,.2f}'.format(warehouse_total_taxable),
                                '{:,.2f}'.format(warehouse_total_igst),
                                '{:,.2f}'.format(warehouse_total_cgst),
                                '{:,.2f}'.format(warehouse_total_sgst),
                            ]
                            table_data.append(warehouse_total_row)

                        # Reset warehouse totals and serial number for new warehouse
                        warehouse_total_qty = warehouse_total_val = warehouse_total_taxable = 0.0
                        warehouse_total_igst = warehouse_total_cgst = warehouse_total_sgst = 0.0
                        warehouse_sl_no = 0  # Reset serial number for new warehouse
                        current_warehouse = detail['warehouse']
                        # Add warehouse header row that spans all columns
                        warehouse_row = [f"Branch: {detail['warehouse']}"] + [''] * (len(headers) - 1)
                        table_data.append(warehouse_row)

                    elif detail.get('is_hsn_row'):
                        # Increment warehouse serial number
                        warehouse_sl_no += 1
                        # Add HSN data row
                        qty = float(detail.get('total_qty', 0.0))
                        val = float(detail.get('total_value', 0.0))
                        taxable = float(detail.get('taxable_value', 0.0))
                        rate = float(detail.get('rate', 0.0))
                        igst = float(detail.get('igst', 0.0))
                        cgst = float(detail.get('cgst', 0.0))
                        sgst = float(detail.get('sgst', 0.0))
                        # Add to warehouse totals
                        warehouse_total_qty += qty
                        warehouse_total_val += val
                        warehouse_total_taxable += taxable
                        warehouse_total_igst += igst
                        warehouse_total_cgst += cgst
                        warehouse_total_sgst += sgst
                        # Add to section totals
                        section_total_qty += qty
                        section_total_val += val
                        section_total_taxable += taxable
                        section_total_igst += igst
                        section_total_cgst += cgst
                        section_total_sgst += sgst
                        table_data.append([
                            str(warehouse_sl_no),  # Use warehouse-specific serial number
                            detail.get('hsn', ''),
                            detail.get('desc', ''),
                            detail.get('uqc', ''),
                            '{:,.2f}'.format(qty),
                            '{:,.2f}'.format(val),
                            '{:.2f}'.format(rate),
                            '{:,.2f}'.format(taxable),
                            '{:,.2f}'.format(igst),
                            '{:,.2f}'.format(cgst),
                            '{:,.2f}'.format(sgst),
                        ])

                # Add total for the last warehouse
                if current_warehouse is not None:
                    warehouse_total_row = [
                        f"Total ", '', '', '',
                        '{:,.2f}'.format(warehouse_total_qty),
                        '{:,.2f}'.format(warehouse_total_val),
                        '',
                        '{:,.2f}'.format(warehouse_total_taxable),
                        '{:,.2f}'.format(warehouse_total_igst),
                        '{:,.2f}'.format(warehouse_total_cgst),
                        '{:,.2f}'.format(warehouse_total_sgst),
                    ]

                    table_data.append(warehouse_total_row)

                # Add section totals row

                table_data.append([

                    'GRAND Total', '', '', '',
                    '{:,.2f}'.format(section_total_qty),
                    '{:,.2f}'.format(section_total_val),
                    '',
                    '{:,.2f}'.format(section_total_taxable),
                    '{:,.2f}'.format(section_total_igst),
                    '{:,.2f}'.format(section_total_cgst),
                    '{:,.2f}'.format(section_total_sgst),
                ])

                # Format table data with proper styles
                formatted_data = []
                for row_index, row in enumerate(table_data):
                    formatted_row = []
                    for col_index, cell in enumerate(row):
                        if isinstance(cell, str):
                            if row_index == 0:  # Header row
                                formatted_row.append(Paragraph(cell, header_style))
                            elif col_index == 0 and cell.startswith('Branch:'):  # Warehouse header
                                formatted_row.append(Paragraph(cell, warehouse_style))
                            elif col_index == 0 and cell.startswith('Total'):  # Warehouse total row
                                warehouse_total_style = styles['Normal']
                                warehouse_total_style.fontSize = 7
                                warehouse_total_style.leading = 9
                                warehouse_total_style.alignment = 0  # Left align
                                formatted_row.append(Paragraph(f"<b>{cell}</b>", warehouse_total_style))
                            elif row_index == len(table_data) - 1:  # Final total row
                                total_style = styles['Normal']
                                total_style.fontSize = 7
                                total_style.leading = 9
                                total_style.alignment = 1
                                formatted_row.append(Paragraph(f"<b>{cell}</b>", total_style))
                            else:  # Normal data row
                                formatted_row.append(Paragraph(cell, normal_style))
                        else:
                            formatted_row.append(cell)
                    formatted_data.append(formatted_row)
                # Create table with proper column widths
                available_width = landscape(A4)[0] - 1 * inch
                num_columns = len(headers)

                col_width = available_width / num_columns

                col_widths = [col_width] * num_columns

                table = Table(formatted_data, colWidths=col_widths, repeatRows=1)

                # Apply table styles
                table_styles = [

                    # Header styling
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#edeceb')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 6),

                    # General styling
                    ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('FONTSIZE', (0, 1), (-1, -1), 7),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                    ('LEFTPADDING', (0, 0), (-1, -1), 2),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                    ('WORDWRAP', (0, 0), (-1, -1)),
                ]

                # Apply warehouse header, warehouse total, and HSN row styling

                for row_index, row in enumerate(table_data):

                    if row_index > 0 and row_index < len(table_data) - 1:  # Skip header and final total rows

                        if row[0] and isinstance(row[0], str):

                            if row[0].startswith('Branch:'):

                                # Warehouse header row styling

                                table_styles.extend([

                                    ('SPAN', (0, row_index), (len(headers) - 1, row_index)),

                                    ('BACKGROUND', (0, row_index), (-1, row_index), colors.HexColor('#EAEAEA')),

                                    ('FONTNAME', (0, row_index), (-1, row_index), 'Helvetica-Bold'),

                                    ('ALIGN', (0, row_index), (-1, row_index), 'LEFT'),

                                    ('TEXTCOLOR', (0, row_index), (-1, row_index), colors.HexColor('#0A0A0A')),

                                ])

                            elif row[0].startswith('Total for '):

                                # Warehouse total row styling

                                table_styles.extend([

                                    ('BACKGROUND', (0, row_index), (-1, row_index), colors.HexColor('#dfe3e6')),

                                    ('FONTNAME', (0, row_index), (-1, row_index), 'Helvetica-Bold'),

                                    ('ALIGN', (0, row_index), (3, row_index), 'LEFT'),
                                    # Left align the "Total for" text

                                    ('ALIGN', (4, row_index), (-1, row_index), 'CENTER'),  # Center align numbers

                                ])

                            else:

                                # HSN data row styling (alternating colors)

                                if row_index % 2 == 0:
                                    table_styles.append(
                                        ('BACKGROUND', (0, row_index), (-1, row_index), colors.HexColor('#f8f9fa')))

                # Final total row styling

                table_styles.extend([

                    ('BACKGROUND', (0, len(table_data) - 1), (-1, len(table_data) - 1), colors.HexColor('#E2E2E2')),

                    ('FONTNAME', (0, len(table_data) - 1), (-1, len(table_data) - 1), 'Helvetica-Bold'),

                ])

                table.setStyle(TableStyle(table_styles))

                section_elements.append(table)

                return section_elements

            if self.hsn_type == 'all':

                b2b_lines = hsn_data.get('b2b_lines', [])

                b2c_lines = hsn_data.get('b2c_lines', [])

                if b2b_lines:

                    b2b_elements = build_table_with_warehouses(b2b_lines, "B2B")

                    elements.extend(b2b_elements)

                    if b2c_lines:
                        elements.append(Spacer(1, 0.3 * inch))

                if b2c_lines:
                    b2c_elements = build_table_with_warehouses(b2c_lines, "B2C")

                    elements.extend(b2c_elements)


            elif self.hsn_type == 'hsn_b2b':

                b2b_lines = hsn_data.get('b2b_lines', [])

                b2b_elements = build_table_with_warehouses(b2b_lines, "B2B")

                elements.extend(b2b_elements)


            elif self.hsn_type == 'hsn_b2c':

                b2c_lines = hsn_data.get('b2c_lines', [])

                b2c_elements = build_table_with_warehouses(b2c_lines, "B2C")

                elements.extend(b2c_elements)

            return elements


        elif self.type in ['tcs_input', 'tcs_output']:
            headers = [
                'SL NO', 'Date', 'Voucher No', 'Party Name', 'GSTIN',
                'TCS Per', 'Total Amount', 'TCS Amount', 'Grand Total'
            ]
            table_data = [headers]
            total_amount = 0.0
            total_tcs = 0.0
            total_grand = 0.0

            for line in lines:
                total_amt = float(line.get('total_without_tcs', 0.0))
                tcs_amt = float(line.get('tcs_amount', 0.0))
                grand_total = float(line.get('total_value', 0.0))
                total_amount += total_amt
                total_tcs += tcs_amt
                total_grand += grand_total
                table_data.append([
                    line.get('sl_no', ''),
                    line.get('date', ''),
                    line.get('inv_no', ''),
                    line.get('customer_name', ''),
                    line.get('gstin_customer', ''),
                    line.get('tcs_rate', ''),
                    '{:,.2f}'.format(total_amt),
                    '{:,.2f}'.format(tcs_amt),
                    '{:,.2f}'.format(grand_total),
                ])
            if not lines:
                table_data.append(['Total', '', '', '', '', '', '0.00', '0.00', '0.00'])
            else:
                table_data.append([
                    'Total', '', '', '', '', '',
                    '{:,.2f}'.format(total_amount),
                    '{:,.2f}'.format(total_tcs),
                    '{:,.2f}'.format(total_grand),
                ])

        elif self.type == 'doc_summary':

            elements = []
            filters = []

            if self.start_date:
                filters.append(['From:', self.start_date.strftime('%d-%b-%Y')])
            if self.end_date:
                filters.append(['To:', self.end_date.strftime('%d-%b-%Y')])
            filters.append(['Branch:', self.warehouse_id.name if self.warehouse_id else 'All Branches'])

            headers = [
                'Nature of Document',
                'Branch',
                'From Voucher No',
                'To Voucher No',
                'Voucher Count',
                'Cancelled',
                'Net Issued'
            ]

            table_data = [headers]

            doc_types = [
                'B2B Sale',
                'B2C Sale',
                'B2B Credit Note',
                'B2C Credit Note',
                'Purchase',
                'Debit Note',
                'Delivery Challan',
                'Receipt',
                'Payment'
            ]

            doc_grouped = {}

            for line in lines:
                doc_grouped.setdefault(line.get('doc_type', ''), []).append(line)

            for doc in doc_types:
                if doc in doc_grouped:

                    table_data.append([doc, '', '', '', '', '', ''])

                    for line in doc_grouped[doc]:
                        table_data.append([
                            line.get('', ''),
                            line.get('branch', ''),
                            line.get('from_no', ''),
                            line.get('to_no', ''),
                            line.get('vch_count', 0),
                            line.get('cancel_count', 0),
                            line.get('net_count', 0),
                        ])

            pdf_table = Table(table_data, repeatRows=1, hAlign='LEFT')
            pdf_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#48585d')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
            ]))

            elements.append(pdf_table)
            return elements

        elif self.type == 'gstr1_summary':
            sale_final_data = []
            b2b_domain = [
                ('partner_id.vat', '!=', False),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', self.start_date),
                ('invoice_date', '<=', self.end_date)
            ]

            if self.warehouse_id:
                b2b_domain.append(('warehouse_id', '=', self.warehouse_id.id))

            b2b_invoices = self.env['account.move'].search(b2b_domain, order='invoice_date asc, name asc')
            total_inv_value = 0.0
            total_taxable_value = 0.0
            total_tax_value = 0.0

            for inv in b2b_invoices:
                line_untaxed_total = sum(line.price_subtotal for line in inv.invoice_line_ids)
                total_inv_value += inv.amount_total
                total_taxable_value += line_untaxed_total
                total_tax_value += (inv.amount_total - line_untaxed_total)

            sale_final_data.append({
                'doc_type': 'B2B Invoices',
                'voucher_count': len(b2b_invoices),
                'total_inv_value': round(total_inv_value, 2),
                'total_tax_value': round(total_tax_value, 2),
                'total_untax_value': round(total_taxable_value, 2)
            })

            b2c_large_domain = [
                ('partner_id.vat', '!=', False),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('partner_id.state_id.l10n_in_tin', '!=', 32),
                ('amount_total', '>', 250000),
                ('invoice_date', '>=', self.start_date),
                ('invoice_date', '<=', self.end_date)
            ]

            if self.warehouse_id:
                b2c_large_domain.append(('warehouse_id', '=', self.warehouse_id.id))

            b2c_large_invoices = self.env['account.move'].search(b2c_large_domain)
            sale_final_data.append({
                'doc_type': 'B2C Large',
                'voucher_count': len(b2c_large_invoices),
                'total_inv_value': round(sum(inv.amount_total for inv in b2c_large_invoices), 2),
                'total_tax_value': round(sum(inv.amount_tax for inv in b2c_large_invoices), 2),
                'total_untax_value': round(sum(inv.amount_untaxed for inv in b2c_large_invoices), 2),
            })

            b2c_small_domain = [
                ('partner_id.vat', '!=', False),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', self.start_date),
                ('invoice_date', '<=', self.end_date),
                ('id', 'not in', b2c_large_invoices.ids)
            ]

            if self.warehouse_id:
                b2c_small_domain.append(('warehouse_id', '=', self.warehouse_id.id))

            b2c_small_invoices = self.env['account.move'].search(b2c_small_domain)

            credit_note_domain = [
                ('partner_id.vat', '!=', False),
                ('move_type', '=', 'out_refund'),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', self.start_date),
                ('invoice_date', '<=', self.end_date)
            ]

            if self.warehouse_id:
                credit_note_domain.append(('warehouse_id', '=', self.warehouse_id.id))

            credit_notes = self.env['account.move'].search(credit_note_domain)

            b2c_small_total_inv = sum(inv.amount_total for inv in b2c_small_invoices) - sum(
                cn.amount_total for cn in credit_notes)

            b2c_small_total_tax = sum(inv.amount_tax for inv in b2c_small_invoices) - sum(
                cn.amount_tax for cn in credit_notes)

            b2c_small_total_untax = sum(inv.amount_untaxed for inv in b2c_small_invoices) - sum(
                cn.amount_untaxed for cn in credit_notes)

            sale_final_data.append({
                'doc_type': 'B2C Small',
                'voucher_count': len(b2c_small_invoices) + len(credit_notes),
                'total_inv_value': round(b2c_small_total_inv, 2),
                'total_tax_value': round(b2c_small_total_tax, 2),
                'total_untax_value': round(b2c_small_total_untax, 2),
            })

            cb_registered_domain = [
                ('partner_id.vat', '!=', False),
                ('move_type', 'in', ['out_refund', 'in_refund']),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', self.start_date),
                ('invoice_date', '<=', self.end_date)
            ]

            if self.warehouse_id:
                cb_registered_domain.append(('warehouse_id', '=', self.warehouse_id.id))

            cb_registered = self.env['account.move'].search(cb_registered_domain)
            sale_final_data.append({
                'doc_type': 'Credit/Debit Registered',
                'voucher_count': len(cb_registered),
                'total_inv_value': round(sum(inv.amount_total for inv in cb_registered), 2),
                'total_tax_value': round(sum(inv.amount_tax for inv in cb_registered), 2),
                'total_untax_value': round(sum(inv.amount_untaxed for inv in cb_registered), 2),
            })

            cb_unregistered_domain = [
                ('partner_id.vat', '!=', False),
                ('move_type', 'in', ['out_refund', 'in_refund']),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', self.start_date),
                ('invoice_date', '<=', self.end_date)
            ]

            if self.warehouse_id:
                cb_unregistered_domain.append(('warehouse_id', '=', self.warehouse_id.id))

            cb_unregistered = self.env['account.move'].search(cb_unregistered_domain)

            sale_final_data.append({
                'doc_type': 'Credit/Debit UnRegistered',
                'voucher_count': len(cb_unregistered),
                'total_inv_value': round(sum(inv.amount_total for inv in cb_unregistered), 2),
                'total_tax_value': round(sum(inv.amount_tax for inv in cb_unregistered), 2),
                'total_untax_value': round(sum(inv.amount_untaxed for inv in cb_unregistered), 2),
            })

            headers = ['Document Type', 'Voucher Count', 'Taxable Amount', 'Tax Amount', 'Invoice Amount']

            table_data = [headers]
            total_count = 0
            total_untax = 0.0
            total_tax = 0.0
            total_invoice = 0.0

            for line in sale_final_data:
                table_data.append([
                    line['doc_type'],
                    str(line['voucher_count']),
                    '{:,.2f}'.format(line['total_untax_value']),
                    '{:,.2f}'.format(line['total_tax_value']),
                    '{:,.2f}'.format(line['total_inv_value']),
                ])

                total_count += line['voucher_count']
                total_untax += line['total_untax_value']
                total_tax += line['total_tax_value']
                total_invoice += line['total_inv_value']

            table_data.append([
                'Total',
                str(total_count),
                '{:,.2f}'.format(total_untax),
                '{:,.2f}'.format(total_tax),
                '{:,.2f}'.format(total_invoice),
            ])

        if self.type != 'hsn':
            styles = getSampleStyleSheet()
            header_style = styles['Normal']
            header_style.fontSize = 8
            header_style.leading = 10
            header_style.alignment = 1
            normal_style = styles['Normal']
            normal_style.fontSize = 7
            normal_style.leading = 9

            formatted_data = []
            for row_index, row in enumerate(table_data):
                formatted_row = []
                for cell in row:
                    if isinstance(cell, str):
                        if row_index == 0:
                            formatted_row.append(Paragraph(cell, header_style))
                        else:
                            formatted_row.append(Paragraph(cell, normal_style))
                    else:
                        formatted_row.append(cell)
                formatted_data.append(formatted_row)

            available_width = landscape(A4)[0] - 1 * inch
            num_columns = len(table_data[0])
            col_width = available_width / num_columns
            col_widths = [col_width] * num_columns

            table = Table(formatted_data, colWidths=col_widths, repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#edeceb')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                ('WORDWRAP', (0, 0), (-1, -1)),
            ]))
            for i in range(1, len(table_data) - 1):
                if i % 2 == 0:
                    table.setStyle(TableStyle([
                        ('BACKGROUND', (0, i), (-1, i), colors.HexColor('#f2f2f2'))
                    ]))
            return table


class GstrB2BXlsxReport(models.AbstractModel):
    _name = 'report.prosevo_erp_accounts_management.gstirn1_b2b_xlsx_temp'

    def generate_xlsx_report(self, workbook, data, wizard):
        # Define Styles
        date_format = workbook.add_format({'num_format': 'dd-mmm-yyyy', 'border': True, 'align': 'left'})
        title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'font_size': 16
        })
        report_title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'valign': 'vcenter',
            'font_size': 12  # Smaller than 16
        })
        # Format for bold key
        bold_key_format = workbook.add_format({
            'bold': True, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })

        # Format for normal value
        normal_value_format = workbook.add_format({
            'bold': False, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })

        sub_header = workbook.add_format({
            'font_color': 'white', 'bg_color': '#48585d', 'font_size': 12,
            'text_wrap': True, 'border': True, 'align': 'center'
        })
        common_data = workbook.add_format({
            'bold': False, 'font_color': 'black', 'text_wrap': True, 'border': True, 'align': 'left'
        })
        float_format = workbook.add_format({
            'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter', 'border': 1
        })

        # Sheet Setup
        sheet = workbook.add_worksheet("GSTR1 B2B")
        sheet.set_row(0, 30)
        sheet.set_row(1, 20)
        sheet.set_column(0, 0, 8)  # Sl No
        sheet.set_column(1, 1, 20)  # GSTIN
        sheet.set_column(2, 2, 45)  # Customer Name
        sheet.set_column(3, 3, 18)  # Invoice No
        sheet.set_column(4, 4, 12)  # Date
        sheet.set_column(5, 5, 15)  # Invoice Value
        sheet.set_column(6, 6, 20)  # Place of Supply
        sheet.set_column(7, 7, 15)  # Reverse Charge
        sheet.set_column(8, 8, 15)  # Invoice Type
        sheet.set_column(9, 9, 10)  # Rate
        sheet.set_column(10, 10, 18)  # Taxable Value

        row = 1
        sheet.merge_range('A1:K1', self.env.company.name, title_style)
        row += 1
        sheet.merge_range('A2:K2', "GSTR1 B2B Report", report_title_style)

        # Filters Info
        if wizard.start_date:
            row += 1
            sheet.merge_range(row, 0, row, 3, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'From:    ', normal_value_format,
                                    wizard.start_date.strftime('%d-%b-%Y'))

        if wizard.end_date:
            row += 1
            sheet.merge_range(row, 0, row, 3, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'To:      ', normal_value_format,
                                    wizard.end_date.strftime('%d-%b-%Y'))

        row += 1
        sheet.merge_range(row, 0, row, 3, "", normal_value_format)
        branch_value = wizard.warehouse_id.name if wizard.warehouse_id else 'All'
        sheet.write_rich_string(row, 0, bold_key_format, 'Branch:  ', normal_value_format, branch_value)

        # Header Row
        row += 1
        headers = [
            'Sl No', 'GSTIN', 'Customer Name', 'Invoice No', 'Date',
            'Invoice Value', 'Place of Supply', 'Reverse Charge',
            'Invoice Type', 'Rate', 'Taxable Value'
        ]
        for col, header in enumerate(headers):
            sheet.write(row, col, header, sub_header)
        sheet.set_row(row, 22)

        # Data Rows
        report_data = wizard._gather_report_data()
        row += 1
        total_invoice = 0.0
        total_taxable = 0.0
        for line in report_data.get('lines', []):
            sheet.write(row, 0, line.get('sl_no', ''), common_data)
            sheet.write(row, 1, line.get('gstin_customer', ''), common_data)
            sheet.write(row, 2, line.get('customer_name', ''), common_data)
            sheet.write(row, 3, line.get('inv_no', ''), common_data)
            sheet.write(row, 4, line.get('date', ''), date_format)
            sheet.write(row, 5, line.get('inv_value', 0), float_format)
            sheet.write(row, 6, line.get('place_of_supply', ''), common_data)
            sheet.write(row, 7, line.get('reverse_charge', ''), common_data)
            sheet.write(row, 8, line.get('inv_type', ''), common_data)
            sheet.write(row, 9, line.get('rate', 0.0), float_format)
            sheet.write(row, 10, line.get('taxable_value', 0.0), float_format)
            sheet.set_row(row, 19)
            total_invoice += line.get('inv_value', 0.0)
            total_taxable += line.get('taxable_value', 0.0)
            row += 1
        sheet.write(row, 4, 'Total', bold_key_format)
        sheet.write(row, 5, total_invoice, float_format)
        sheet.write(row, 10, total_taxable, float_format)
        sheet.set_row(row, 22)


class B2CLargeXlsxReport(models.AbstractModel):
    _name = 'report.prosevo_erp_accounts_management.b2c_large_xlsx_temp'

    def generate_xlsx_report(self, workbook, data, wizard):
        # Define Styles
        date_format = workbook.add_format({'num_format': 'dd-mmm-yyyy', 'border': True, 'align': 'left'})
        title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'font_size': 16
        })
        report_title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'valign': 'vcenter',
            'font_size': 12
        })
        bold_key_format = workbook.add_format({
            'bold': True, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })
        normal_value_format = workbook.add_format({
            'bold': False, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })
        sub_header = workbook.add_format({
            'font_color': 'white', 'bg_color': '#48585d', 'font_size': 12,
            'text_wrap': True, 'border': True, 'align': 'center'
        })
        common_data = workbook.add_format({
            'bold': False, 'font_color': 'black', 'text_wrap': True, 'border': True, 'align': 'left'
        })
        float_format = workbook.add_format({
            'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter', 'border': 1
        })

        # Sheet Setup
        sheet = workbook.add_worksheet("GSTR1 B2C Large")
        sheet.set_row(0, 30)
        sheet.set_row(1, 20)
        sheet.set_column(0, 0, 16)  # Sl No
        sheet.set_column(1, 1, 23)  # Invoice No
        sheet.set_column(2, 2, 20)  # Invoice Date
        sheet.set_column(3, 3, 23)  # Invoice Value
        sheet.set_column(4, 4, 28)  # Place of Supply
        sheet.set_column(5, 5, 18)  # Rate
        sheet.set_column(6, 6, 26)  # Taxable Value

        row = 1
        sheet.merge_range('A1:G1', self.env.company.name, title_style)
        row += 1
        sheet.merge_range('A2:G2', "GSTR1 B2C Large Report", report_title_style)

        # Filters Info
        if wizard.start_date:
            row += 1
            sheet.merge_range(row, 0, row, 3, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'From:    ', normal_value_format,
                                    wizard.start_date.strftime('%d-%b-%Y'))

        if wizard.end_date:
            row += 1
            sheet.merge_range(row, 0, row, 3, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'To:      ', normal_value_format,
                                    wizard.end_date.strftime('%d-%b-%Y'))

        if wizard.warehouse_id:
            row += 1
            sheet.merge_range(row, 0, row, 3, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'Branch:  ', normal_value_format, wizard.warehouse_id.name)

        # Header Row
        row += 1
        headers = ['Sl No', 'Invoice No', 'Invoice Date', 'Invoice Value', 'Place of Supply', 'Rate', 'Taxable Value']
        for col, header in enumerate(headers):
            sheet.write(row, col, header, sub_header)
        sheet.set_row(row, 22)

        # Data Rows
        report_data = wizard._gather_report_data()
        row += 1
        total_inv_value = 0.0
        total_rate = 0.0  # Optional, usually not summed
        total_taxable_value = 0.0
        for line in report_data.get('lines', []):
            sheet.write(row, 0, line.get('sl_no', ''), common_data)
            sheet.write(row, 1, line.get('inv_no', ''), common_data)
            sheet.write(row, 2, line.get('date', ''), date_format)
            sheet.write(row, 3, line.get('inv_value', 0), float_format)
            sheet.write(row, 4, line.get('place_of_supply', ''), common_data)
            sheet.write(row, 5, line.get('rate', 0.0), float_format)
            sheet.write(row, 6, line.get('taxable_value', 0.0), float_format)
            sheet.set_row(row, 19)
            row += 1

            total_inv_value += line.get('inv_value', 0.0)
            total_taxable_value += line.get('taxable_value', 0.0)
            row += 1

        # Add Total Row
        sheet.write(row, 2, 'Total', bold_key_format)
        sheet.write(row, 3, total_inv_value, float_format)
        sheet.write(row, 4, '', common_data)
        sheet.write(row, 5, '', common_data)  # Not summing rate
        sheet.write(row, 6, total_taxable_value, float_format)
        sheet.set_row(row, 22)


class B2CSmallXlsxReport(models.AbstractModel):
    _name = 'report.prosevo_erp_accounts_management.b2c_small_xlsx_temp'

    def generate_xlsx_report(self, workbook, data, wizard):
        # Define Styles
        date_format = workbook.add_format({'num_format': 'dd-mmm-yyyy', 'border': True, 'align': 'left'})
        title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'font_size': 16
        })
        report_title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'valign': 'vcenter',
            'font_size': 12
        })
        bold_key_format = workbook.add_format({
            'bold': True, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })
        normal_value_format = workbook.add_format({
            'bold': False, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })
        sub_header = workbook.add_format({
            'font_color': 'white', 'bg_color': '#48585d', 'font_size': 12,
            'text_wrap': True, 'border': True, 'align': 'center'
        })
        common_data = workbook.add_format({
            'bold': False, 'font_color': 'black', 'text_wrap': True, 'border': True, 'align': 'left'
        })
        float_format = workbook.add_format({
            'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter', 'border': 1
        })
        # Sheet Setup
        sheet = workbook.add_worksheet("GSTR1 B2C Small")
        sheet.set_row(0, 36)
        sheet.set_row(1, 26)
        sheet.set_column(0, 0, 32)  # Sl No
        sheet.set_column(1, 1, 44)  # Place of Supply
        sheet.set_column(2, 2, 34)  # Rate
        sheet.set_column(3, 3, 42)  # Taxable Value

        row = 1
        sheet.merge_range('A1:D1', self.env.company.name, title_style)
        row += 1
        sheet.merge_range('A2:D2', "GSTR1 B2C Small Report", report_title_style)

        # Filters Info
        if wizard.start_date:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'From:    ', normal_value_format,
                                    wizard.start_date.strftime('%d-%b-%Y'))

        if wizard.end_date:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'To:      ', normal_value_format,
                                    wizard.end_date.strftime('%d-%b-%Y'))

        if wizard.warehouse_id:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'Branch:  ', normal_value_format, wizard.warehouse_id.name)

        # Header Row
        row += 1
        headers = ['Sl No', 'Place of Supply', 'Rate', 'Taxable Value']
        for col, header in enumerate(headers):
            sheet.write(row, col, header, sub_header)
        sheet.set_row(row, 22)

        # Data Rows
        report_data = wizard._gather_report_data()
        row += 1
        total_taxable_value = 0.0
        for line in report_data.get('lines', []):
            sheet.write(row, 0, line.get('sl_no', ''), common_data)
            sheet.write(row, 1, line.get('place_of_supply', ''), common_data)
            sheet.write(row, 2, line.get('rate', 0.0), float_format)
            sheet.write(row, 3, line.get('taxable_value', 0.0), float_format)
            sheet.set_row(row, 19)
            total_taxable_value += line.get('taxable_value', 0.0)
            row += 1
        sheet.write(row, 2, 'TOTAL', bold_key_format)
        sheet.write(row, 3, total_taxable_value, float_format)
        sheet.set_row(row, 22)


class DCRegCustomerXlsxReport(models.AbstractModel):
    _name = 'report.prosevo_erp_accounts_management.dc_reg_cust_xlsx_temp'

    def generate_xlsx_report(self, workbook, data, wizard):
        # Define Styles
        title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'font_size': 16
        })
        report_title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'valign': 'vcenter',
            'font_size': 12
        })
        bold_key_format = workbook.add_format({
            'bold': True, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })
        normal_value_format = workbook.add_format({
            'bold': False, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })
        sub_header = workbook.add_format({
            'font_color': 'white', 'bg_color': '#48585d', 'font_size': 12,
            'text_wrap': True, 'border': True, 'align': 'center'
        })
        common_data = workbook.add_format({
            'bold': False, 'font_color': 'black', 'text_wrap': True, 'border': True, 'align': 'left'
        })
        float_format = workbook.add_format({
            'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter', 'border': 1
        })
        date_col_format = workbook.add_format({
            'num_format': 'dd-mmm-yyyy', 'align': 'left', 'valign': 'vcenter', 'border': 1
        })

        # Sheet Setup - UPDATED COLUMN WIDTHS
        sheet = workbook.add_worksheet("GSTR1 D/C REGISTERED CUSTOMER")
        sheet.set_row(0, 30)
        sheet.set_row(1, 20)
        sheet.set_column(0, 0, 5)  # SL NO
        sheet.set_column(1, 1, 16)  # GSTIN
        sheet.set_column(2, 2, 25)  # Supplier Name - NEW COLUMN
        sheet.set_column(3, 3, 19)  # Invoice/Advance Receipt Number
        sheet.set_column(4, 4, 17)  # Invoice/Advance Receipt Date
        sheet.set_column(5, 5, 20)  # Note/Refund Voucher Number
        sheet.set_column(6, 6, 18)  # Note/Refund Voucher Date
        sheet.set_column(7, 7, 13)  # Document Type
        sheet.set_column(8, 8, 20)  # Place Of Supply
        sheet.set_column(9, 9, 18)  # Note/Refund Voucher Value
        sheet.set_column(10, 10, 10)  # Rate
        sheet.set_column(11, 11, 18)  # Taxable Value

        row = 1
        sheet.merge_range('A1:L1', self.env.company.name, title_style)  # Changed K1 to L1
        row += 1
        sheet.merge_range('A2:L2', "GSTR1 D/C Registered Customer Report", report_title_style)  # Changed K2 to L2

        # Filters Info
        if wizard.start_date:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'From:    ', normal_value_format,
                                    wizard.start_date.strftime('%d-%b-%Y'))

        if wizard.end_date:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'To:      ', normal_value_format,
                                    wizard.end_date.strftime('%d-%b-%Y'))

        if wizard.warehouse_id:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'Branch:  ', normal_value_format, wizard.warehouse_id.name)

        # Header Row - UPDATED WITH NEW COLUMN
        row += 1
        headers = [
            'SL NO', 'GSTIN of Recipient', 'Supplier Name',  # ADDED Supplier Name
            'Invoice/Advance Receipt Number', 'Invoice/Advance Receipt date',
            'Note/Refund Voucher Number', 'Note/Refund Voucher date', 'Document Type', 'Place Of Supply',
            'Note/Refund Voucher Value', 'Rate', 'Taxable Value'
        ]
        for col, header in enumerate(headers):
            sheet.write(row, col, header, sub_header)
        sheet.set_row(row, 30)

        # Data Rows - UPDATED WITH NEW COLUMN
        report_data = wizard._gather_report_data()
        row += 1
        # Initialize totals
        total_note_value = 0.0
        total_taxable_value = 0.0
        for line in report_data.get('lines', []):
            sheet.write(row, 0, line.get('sl_no', ''), common_data)
            sheet.write(row, 1, line.get('gstin_customer', ''), common_data)
            sheet.write(row, 2, line.get('supplier_name', ''), common_data)  # NEW COLUMN
            sheet.write(row, 3, line.get('inv_ref', ''), common_data)
            sheet.write(row, 4, line.get('inv_ref_date', ''), date_col_format)
            sheet.write(row, 5, line.get('inv_no', ''), common_data)
            sheet.write(row, 6, line.get('date', ''), date_col_format)
            sheet.write(row, 7, line.get('doc_type', ''), common_data)
            sheet.write(row, 8, line.get('place_of_supply', ''), common_data)
            sheet.write(row, 9, line.get('total_value', 0.0), float_format)
            sheet.write(row, 10, line.get('rate', 0.0), float_format)
            sheet.write(row, 11, line.get('taxable_value', 0.0), float_format)  # Changed from column 10 to 11
            sheet.set_row(row, 19)
            row += 1
            total_note_value += line.get('total_value', 0.0)
            total_taxable_value += line.get('taxable_value', 0.0)
        sheet.write(row, 8, 'TOTAL', bold_key_format)  # Changed from column 7 to 8
        sheet.write(row, 9, total_note_value, float_format)  # Changed from column 8 to 9
        sheet.write(row, 10, '', common_data)  # Changed from column 9 to 10 - Leave Rate blank
        sheet.write(row, 11, total_taxable_value, float_format)  # Changed from column 10 to 11
        sheet.set_row(row, 22)


class DCUnRegCustomerXlsxReport(models.AbstractModel):
    _name = 'report.prosevo_erp_accounts_management.dc_unreg_cust_xlsx_temp'

    def generate_xlsx_report(self, workbook, data, wizard):
        # Define Styles
        title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'font_size': 16
        })
        report_title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'valign': 'vcenter',
            'font_size': 12
        })
        bold_key_format = workbook.add_format({
            'bold': True, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })
        normal_value_format = workbook.add_format({
            'bold': False, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })
        sub_header = workbook.add_format({
            'font_color': 'white', 'bg_color': '#48585d', 'font_size': 12,
            'text_wrap': True, 'border': True, 'align': 'center'
        })
        common_data = workbook.add_format({
            'bold': False, 'font_color': 'black', 'text_wrap': True, 'border': True, 'align': 'left'
        })
        float_format = workbook.add_format({
            'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter', 'border': 1
        })
        date_col_format = workbook.add_format({
            'num_format': 'dd-mmm-yyyy', 'align': 'left', 'valign': 'vcenter', 'border': 1
        })

        # Sheet Setup - UPDATED COLUMN WIDTHS
        sheet = workbook.add_worksheet("GSTR1 D/C UNREGISTERED CUSTOMER")
        sheet.set_row(0, 30)
        sheet.set_row(1, 20)
        sheet.set_column(0, 0, 5)  # SL NO
        sheet.set_column(1, 1, 16)  # GSTIN (blank for unregistered)
        sheet.set_column(2, 2, 25)  # Supplier Name - NEW COLUMN
        sheet.set_column(3, 3, 19)  # Invoice/Advance Receipt Number
        sheet.set_column(4, 4, 17)  # Invoice/Advance Receipt Date
        sheet.set_column(5, 5, 20)  # Note/Refund Voucher Number
        sheet.set_column(6, 6, 18)  # Note/Refund Voucher Date
        sheet.set_column(7, 7, 13)  # Document Type
        sheet.set_column(8, 8, 20)  # Place Of Supply
        sheet.set_column(9, 9, 18)  # Note/Refund Voucher Value
        sheet.set_column(10, 10, 10)  # Rate
        sheet.set_column(11, 11, 18)  # Taxable Value

        row = 1
        sheet.merge_range('A1:L1',self.env.company.name, title_style)  # Changed K1 to L1
        row += 1
        sheet.merge_range('A2:L2', "GSTR1 D/C Unregistered Customer Report", report_title_style)  # Changed K2 to L2

        # Filters Info
        if wizard.start_date:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'From:    ', normal_value_format,
                                    wizard.start_date.strftime('%d-%b-%Y'))

        if wizard.end_date:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'To:      ', normal_value_format,
                                    wizard.end_date.strftime('%d-%b-%Y'))

        if wizard.warehouse_id:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'Branch:  ', normal_value_format, wizard.warehouse_id.name)

        # Header Row - UPDATED WITH NEW COLUMN
        row += 1
        headers = [
            'SL NO', 'GSTIN of Recipient', 'Supplier Name',  # ADDED Supplier Name
            'Invoice/Advance Receipt Number', 'Invoice/Advance Receipt date',
            'Note/Refund Voucher Number', 'Note/Refund Voucher date', 'Document Type', 'Place Of Supply',
            'Note/Refund Voucher Value', 'Rate', 'Taxable Value'
        ]
        for col, header in enumerate(headers):
            sheet.write(row, col, header, sub_header)
        sheet.set_row(row, 30)

        # Data Rows - UPDATED WITH NEW COLUMN
        report_data = wizard._gather_report_data()
        row += 1
        # Initialize totals
        total_note_value = 0.0
        total_taxable_value = 0.0

        for line in report_data.get('lines', []):
            sheet.write(row, 0, line.get('sl_no', ''), common_data)
            sheet.write(row, 1, line.get('gstin_customer', ''), common_data)
            sheet.write(row, 2, line.get('supplier_name', ''), common_data)  # NEW COLUMN
            sheet.write(row, 3, line.get('inv_ref', ''), common_data)
            sheet.write(row, 4, line.get('inv_ref_date', ''), date_col_format)
            sheet.write(row, 5, line.get('inv_no', ''), common_data)
            sheet.write(row, 6, line.get('date', ''), date_col_format)
            sheet.write(row, 7, line.get('doc_type', ''), common_data)
            sheet.write(row, 8, line.get('place_of_supply', ''), common_data)
            sheet.write(row, 9, line.get('total_value', 0.0), float_format)
            sheet.write(row, 10, line.get('rate', 0.0), float_format)
            sheet.write(row, 11, line.get('taxable_value', 0.0), float_format)  # Changed from column 10 to 11
            sheet.set_row(row, 19)
            row += 1
            total_note_value += line.get('total_value', 0.0)
            total_taxable_value += line.get('taxable_value', 0.0)

        sheet.write(row, 8, 'TOTAL', bold_key_format)  # Changed from column 7 to 8
        sheet.write(row, 9, total_note_value, float_format)  # Changed from column 8 to 9
        sheet.write(row, 10, '', common_data)  # Changed from column 9 to 10 - Leave Rate blank
        sheet.write(row, 11, total_taxable_value, float_format)  # Changed from column 10 to 11
        sheet.set_row(row, 22)


class TCSInputXlsxReport(models.AbstractModel):
    _name = 'report.prosevo_erp_accounts_management.tcs_input_xlsx_temp'

    def generate_xlsx_report(self, workbook, data, wizard):
        # Define Styles
        date_format = workbook.add_format({'num_format': 'dd-mmm-yyyy', 'border': True, 'align': 'left'})
        title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'font_size': 16
        })
        report_title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'valign': 'vcenter',
            'font_size': 12
        })
        bold_key_format = workbook.add_format({
            'bold': True, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })
        normal_value_format = workbook.add_format({
            'bold': False, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })
        sub_header = workbook.add_format({
            'font_color': 'white', 'bg_color': '#48585d', 'font_size': 12,
            'text_wrap': True, 'border': True, 'align': 'center'
        })
        common_data = workbook.add_format({
            'bold': False, 'font_color': 'black', 'text_wrap': True, 'border': True, 'align': 'left'
        })
        float_format = workbook.add_format({
            'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter', 'border': 1
        })
        date_col_format = workbook.add_format({
            'num_format': 'dd-mmm-yyyy', 'align': 'left', 'valign': 'vcenter', 'border': 1
        })

        # Sheet Setup
        sheet = workbook.add_worksheet("GSTR1 TCS INPUT")
        sheet.set_row(0, 30)
        sheet.set_row(1, 20)
        sheet.set_column(0, 0, 8)  # SL NO
        sheet.set_column(1, 1, 16)  # Date
        sheet.set_column(2, 2, 21)  # Voucher No
        sheet.set_column(3, 3, 26)  # Party Name
        sheet.set_column(4, 4, 21)  # GSTIN
        sheet.set_column(5, 5, 11)  # TCS Per
        sheet.set_column(6, 6, 19)  # Total Amount
        sheet.set_column(7, 7, 19)  # TCS Amount
        sheet.set_column(8, 8, 19)  # Grand Total

        row = 1
        sheet.merge_range('A1:I1', self.env.company.name, title_style)
        row += 1
        sheet.merge_range('A2:I2', "GSTR1 TCS Input Report", report_title_style)

        # Filters Info
        if wizard.start_date:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'From:    ', normal_value_format,
                                    wizard.start_date.strftime('%d-%b-%Y'))

        if wizard.end_date:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'To:      ', normal_value_format,
                                    wizard.end_date.strftime('%d-%b-%Y'))

        if wizard.warehouse_id:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'Branch:  ', normal_value_format, wizard.warehouse_id.name)

        # Header Row
        row += 1
        headers = [
            'SL NO', 'Date', 'Voucher No', 'Party Name', 'GSTIN',
            'TCS %', 'Total Amount', 'TCS Amount', 'Grand Total'
        ]
        for col, header in enumerate(headers):
            sheet.write(row, col, header, sub_header)
        sheet.set_row(row, 22)

        # Data Rows
        report_data = wizard._gather_report_data()
        row += 1
        total_amount = 0.0
        total_tcs = 0.0
        total_grand = 0.0
        for line in report_data.get('lines', []):
            sheet.write(row, 0, line.get('sl_no', ''), common_data)
            sheet.write(row, 1, line.get('date', ''), date_col_format)
            sheet.write(row, 2, line.get('inv_no', ''), common_data)
            sheet.write(row, 3, line.get('customer_name', ''), common_data)
            sheet.write(row, 4, line.get('gstin_customer', ''), common_data)
            sheet.write(row, 5, line.get('tcs_rate', 0.0), float_format)
            sheet.write(row, 6, line.get('total_without_tcs', 0.0), float_format)
            sheet.write(row, 7, line.get('tcs_amount', 0.0), float_format)
            sheet.write(row, 8, line.get('total_value', 0.0), float_format)
            sheet.set_row(row, 19)
            total_amount += line.get('total_without_tcs', 0.0)
            total_tcs += line.get('tcs_amount', 0.0)
            total_grand += line.get('total_value', 0.0)
            row += 1

        # Write Total Row
        total_label_format = workbook.add_format({
            'bold': True, 'bg_color': '#d3d3d3', 'border': 1, 'align': 'right'
        })
        total_value_format = workbook.add_format({
            'bold': True, 'bg_color': '#d3d3d3', 'border': 1,
            'num_format': '#,##0.00', 'align': 'right'
        })
        sheet.merge_range(row, 0, row, 5, "Total", total_label_format)
        sheet.write(row, 6, total_amount, total_value_format)
        sheet.write(row, 7, total_tcs, total_value_format)
        sheet.write(row, 8, total_grand, total_value_format)
        sheet.set_row(row, 22)


class TCSOutputXlsxReport(models.AbstractModel):
    _name = 'report.prosevo_erp_accounts_management.tcs_output_xlsx_temp'

    def generate_xlsx_report(self, workbook, data, wizard):
        # Define Styles
        date_format = workbook.add_format({'num_format': 'dd-mmm-yyyy', 'border': True, 'align': 'left'})
        title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'font_size': 16
        })
        report_title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'valign': 'vcenter',
            'font_size': 12
        })
        bold_key_format = workbook.add_format({
            'bold': True, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })
        normal_value_format = workbook.add_format({
            'bold': False, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })
        sub_header = workbook.add_format({
            'font_color': 'white', 'bg_color': '#48585d', 'font_size': 12,
            'text_wrap': True, 'border': True, 'align': 'center'
        })
        common_data = workbook.add_format({
            'bold': False, 'font_color': 'black', 'text_wrap': True, 'border': True, 'align': 'left'
        })
        float_format = workbook.add_format({
            'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter', 'border': 1
        })
        date_col_format = workbook.add_format({
            'num_format': 'dd-mmm-yyyy', 'align': 'left', 'valign': 'vcenter', 'border': 1
        })

        # Sheet Setup
        sheet = workbook.add_worksheet("GSTR1 TCS OUTPUT")
        sheet.set_row(0, 30)
        sheet.set_row(1, 20)
        sheet.set_column(0, 0, 8)  # SL NO
        sheet.set_column(1, 1, 15)  # Date
        sheet.set_column(2, 2, 20)  # Voucher No
        sheet.set_column(3, 3, 25)  # Party Name
        sheet.set_column(4, 4, 20)  # GSTIN
        sheet.set_column(5, 5, 10)  # TCS Per
        sheet.set_column(6, 6, 18)  # Total Amount
        sheet.set_column(7, 7, 18)  # TCS Amount
        sheet.set_column(8, 8, 18)  # Grand Total

        row = 1
        sheet.merge_range('A1:I1', self.env.company.name, title_style)
        row += 1
        sheet.merge_range('A2:I2', "GSTR1 TCS Output Report", report_title_style)

        # Filters Info
        if wizard.start_date:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'From:    ', normal_value_format,
                                    wizard.start_date.strftime('%d-%b-%Y'))

        if wizard.end_date:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'To:      ', normal_value_format,
                                    wizard.end_date.strftime('%d-%b-%Y'))

        if wizard.warehouse_id:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'Branch:  ', normal_value_format, wizard.warehouse_id.name)

        # Header Row
        row += 1
        headers = [
            'SL NO', 'Date', 'Voucher No', 'Party Name', 'GSTIN',
            'TCS %', 'Total Amount', 'TCS Amount', 'Grand Total'
        ]
        for col, header in enumerate(headers):
            sheet.write(row, col, header, sub_header)
        sheet.set_row(row, 22)

        # Data Rows
        report_data = wizard._gather_report_data()
        row += 1
        total_amount = 0.0
        total_tcs = 0.0
        total_grand = 0.0
        for line in report_data.get('lines', []):
            sheet.write(row, 0, line.get('sl_no', ''), common_data)
            sheet.write(row, 1, line.get('date', ''), date_col_format)
            sheet.write(row, 2, line.get('inv_no', ''), common_data)
            sheet.write(row, 3, line.get('customer_name', ''), common_data)
            sheet.write(row, 4, line.get('gstin_customer', ''), common_data)
            sheet.write(row, 5, line.get('tcs_rate', 0.0), float_format)
            sheet.write(row, 6, line.get('total_without_tcs', 0.0), float_format)
            sheet.write(row, 7, line.get('tcs_amount', 0.0), float_format)
            sheet.write(row, 8, line.get('total_value', 0.0), float_format)
            sheet.set_row(row, 19)
            total_amount += line.get('total_without_tcs', 0.0)
            total_tcs += line.get('tcs_amount', 0.0)
            total_grand += line.get('total_value', 0.0)

            row += 1

        # Write Total Row
        total_label_format = workbook.add_format({
            'bold': True, 'bg_color': '#d3d3d3', 'border': 1, 'align': 'right'
        })
        total_value_format = workbook.add_format({
            'bold': True, 'bg_color': '#d3d3d3', 'border': 1,
            'num_format': '#,##0.00', 'align': 'right'
        })
        sheet.merge_range(row, 0, row, 5, "Total", total_label_format)
        sheet.write(row, 6, total_amount, total_value_format)
        sheet.write(row, 7, total_tcs, total_value_format)
        sheet.write(row, 8, total_grand, total_value_format)
        sheet.set_row(row, 22)


class HSNXlsxReport(models.AbstractModel):
    _name = 'report.prosevo_erp_accounts_management.hsn_xlsx_temp'

    def generate_xlsx_report(self, workbook, data, wizard):
        # Define Styles
        date_format = workbook.add_format({'num_format': 'dd-mmm-yyyy', 'border': True, 'align': 'left'})
        title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'font_size': 16
        })
        report_title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'valign': 'vcenter',
            'font_size': 12
        })
        bold_key_format = workbook.add_format({
            'bold': True, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })
        normal_value_format = workbook.add_format({
            'bold': False, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })
        sub_header = workbook.add_format({
            'font_color': 'white', 'bg_color': '#48585d', 'font_size': 12,
            'text_wrap': True, 'border': True, 'align': 'center'
        })
        common_data = workbook.add_format({
            'bold': False, 'font_color': 'black', 'text_wrap': True, 'border': True, 'align': 'left'
        })
        float_format = workbook.add_format({
            'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter', 'border': 1
        })

        # Sheet Setup
        sheet = workbook.add_worksheet("GSTR1 HSN")
        sheet.set_row(0, 30)
        sheet.set_row(1, 20)
        sheet.set_column(0, 0, 8)  # SL NO
        sheet.set_column(1, 1, 15)  # HSN
        sheet.set_column(2, 2, 25)  # Description
        sheet.set_column(3, 3, 10)  # UQC
        sheet.set_column(4, 4, 18)  # Total Quantity
        sheet.set_column(5, 5, 18)  # Total Value
        sheet.set_column(6, 6, 18)  # Taxable Value
        sheet.set_column(7, 7, 18)  # Integrated Tax Amount
        sheet.set_column(8, 8, 18)  # Central Tax Amount
        sheet.set_column(9, 9, 18)  # State/UT Tax Amount

        row = 1
        sheet.merge_range('A1:J1', self.env.company.name, title_style)
        row += 1
        sheet.merge_range('A2:J2', "GSTR1 HSN Report", report_title_style)

        # Filters Info
        if wizard.start_date:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'From:    ', normal_value_format,
                                    wizard.start_date.strftime('%d-%b-%Y'))

        if wizard.end_date:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'To:      ', normal_value_format,
                                    wizard.end_date.strftime('%d-%b-%Y'))

        if wizard.warehouse_id:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'Branch:  ', normal_value_format, wizard.warehouse_id.name)

        # Header Row
        row += 1
        headers = [
            'SL NO', 'HSN', 'Description', 'UQC', 'Total Quantity', 'Total Value', 'Taxable Value',
            'Integrated Tax Amount', 'Central Tax Amount', 'State/UT Tax Amount'
        ]
        for col, header in enumerate(headers):
            sheet.write(row, col, header, sub_header)
        sheet.set_row(row, 30)

        # Data Rows
        report_data = wizard._gather_report_data()
        row += 1
        total_qty = 0.0
        total_value = 0.0
        taxable_value = 0.0
        igst = 0.0
        cgst = 0.0
        sgst = 0.0
        for line in report_data.get('lines', []):
            sheet.write(row, 0, line.get('sl_no', ''), common_data)
            sheet.write(row, 1, line.get('hsn', ''), common_data)
            sheet.write(row, 2, line.get('desc', ''), common_data)
            sheet.write(row, 3, line.get('uqc', ''), common_data)
            sheet.write(row, 4, line.get('total_qty', 0.0), float_format)
            sheet.write(row, 5, line.get('total_value', 0.0), float_format)
            sheet.write(row, 6, line.get('taxable_value', 0.0), float_format)
            sheet.write(row, 7, line.get('igst', 0.0), float_format)
            sheet.write(row, 8, line.get('cgst', 0.0), float_format)
            sheet.write(row, 9, line.get('sgst', 0.0), float_format)
            sheet.set_row(row, 19)

            total_qty += line.get('total_qty', 0.0)
            total_value += line.get('total_value', 0.0)
            taxable_value += line.get('taxable_value', 0.0)
            igst += line.get('igst', 0.0)
            cgst += line.get('cgst', 0.0)
            sgst += line.get('sgst', 0.0)
            row += 1

        # Add Totals Row
        sheet.write(row, 0, 'Total', bold_key_format)
        sheet.write(row, 4, total_qty, float_format)
        sheet.write(row, 5, total_value, float_format)
        sheet.write(row, 6, taxable_value, float_format)
        sheet.write(row, 7, igst, float_format)
        sheet.write(row, 8, cgst, float_format)
        sheet.write(row, 9, sgst, float_format)
        sheet.set_row(row, 30)


class HSNAllXlsxReport(models.AbstractModel):
    _name = 'report.prosevo_erp_accounts_management.hsn_all_xlsx_temp'

    def generate_xlsx_report(self, workbook, data, wizard):
        # Styles
        title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'font_size': 16
        })
        report_title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'valign': 'vcenter',
            'font_size': 12
        })
        bold_key_format = workbook.add_format({'bold': True, 'font_size': 12})
        normal_value_format = workbook.add_format({'font_size': 12})
        sub_header = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'border': True, 'align': 'center', 'text_wrap': True
        })
        float_format = workbook.add_format({
            'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter', 'border': 1
        })
        common_data = workbook.add_format({
            'text_wrap': True, 'border': True, 'align': 'left'
        })

        # Sheet Setup
        sheet = workbook.add_worksheet("GSTR1 HSN ALL")
        sheet.set_column(0, 0, 8)  # SL NO
        sheet.set_column(1, 1, 15)  # HSN
        sheet.set_column(2, 2, 25)  # Description
        sheet.set_column(3, 3, 10)  # UQC
        sheet.set_column(4, 4, 18)  # Total Quantity
        sheet.set_column(5, 5, 18)  # Total Value
        sheet.set_column(6, 6, 10)  # Rate
        sheet.set_column(7, 7, 18)  # Taxable Value
        sheet.set_column(8, 8, 18)  # IGST
        sheet.set_column(9, 9, 18)  # CGST
        sheet.set_column(10, 10, 18)  # SGST

        row = 0
        sheet.merge_range(row, 0, row, 10, self.env.company.name, title_style)
        row += 1
        sheet.merge_range(row, 0, row, 10, "GSTR1 HSN Report", report_title_style)

        # Filters
        if wizard.start_date:
            row += 1
            sheet.write(row, 0, "From:", bold_key_format)
            sheet.write(row, 1, wizard.start_date.strftime('%d-%b-%Y'), normal_value_format)
        if wizard.end_date:
            row += 1
            sheet.write(row, 0, "To:", bold_key_format)
            sheet.write(row, 1, wizard.end_date.strftime('%d-%b-%Y'), normal_value_format)
        if wizard.warehouse_id:
            row += 1
            sheet.write(row, 0, "Branch:", bold_key_format)
            sheet.write(row, 1, wizard.warehouse_id.name, normal_value_format)

        def write_section(title, lines):
            nonlocal row
            row += 2
            sheet.merge_range(row, 0, row, 10, title, report_title_style)
            row += 1
            headers = [
                'SL NO', 'HSN', 'Description', 'UQC', 'Total Quantity', 'Total Value', 'Rate (%)',
                'Taxable Value', 'IGST', 'CGST', 'SGST'
            ]
            for col, header in enumerate(headers):
                sheet.write(row, col, header, sub_header)
            row += 1

            total_qty = total_val = total_taxable = total_igst = total_cgst = total_sgst = 0.0
            for line in lines:
                sheet.write(row, 0, line.get('sl_no', ''), common_data)
                sheet.write(row, 1, line.get('hsn', ''), common_data)
                sheet.write(row, 2, line.get('desc', ''), common_data)
                sheet.write(row, 3, line.get('uqc', ''), common_data)
                qty = float(line.get('total_qty', 0.0))
                val = float(line.get('total_value', 0.0))
                rate = float(line.get('rate', 0.0))
                taxable = float(line.get('taxable_value', 0.0))
                igst = float(line.get('igst', 0.0))
                cgst = float(line.get('cgst', 0.0))
                sgst = float(line.get('sgst', 0.0))

                sheet.write(row, 4, qty, float_format)
                sheet.write(row, 5, val, float_format)
                sheet.write(row, 6, rate, float_format)
                sheet.write(row, 7, taxable, float_format)
                sheet.write(row, 8, igst, float_format)
                sheet.write(row, 9, cgst, float_format)
                sheet.write(row, 10, sgst, float_format)

                total_qty += qty
                total_val += val
                total_taxable += taxable
                total_igst += igst
                total_cgst += cgst
                total_sgst += sgst
                row += 1

            # Totals
            sheet.write(row, 3, "Total", bold_key_format)
            sheet.write(row, 4, total_qty, float_format)
            sheet.write(row, 5, total_val, float_format)
            sheet.write(row, 7, total_taxable, float_format)
            sheet.write(row, 8, total_igst, float_format)
            sheet.write(row, 9, total_cgst, float_format)
            sheet.write(row, 10, total_sgst, float_format)
            row += 1

        # Get Data
        report_data = wizard._gather_report_data()
        if wizard.hsn_type == 'all':
            write_section("B2B", report_data.get('b2b_lines', []))
            write_section("B2C", report_data.get('b2c_lines', []))


class DocSummaryXlsxReport(models.AbstractModel):
    _name = 'report.prosevo_erp_accounts_management.doc_sum_xlsx_temp'

    def generate_xlsx_report(self, workbook, data, wizard):
        # Styles
        title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'align': 'center', 'valign': 'vcenter', 'border': 1, 'font_size': 16
        })
        report_title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'align': 'center', 'valign': 'vcenter', 'border': 1, 'font_size': 12
        })
        header_format = workbook.add_format({
            'bold': True, 'bg_color': '#f2f2f2', 'border': 1,
            'align': 'center', 'valign': 'vcenter'
        })
        group_format = workbook.add_format({
            'bold': True, 'bg_color': '#eaeaea', 'border': 1,
            'align': 'left', 'valign': 'vcenter'
        })
        normal_format = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter'
        })
        int_format = workbook.add_format({
            'border': 1, 'align': 'right', 'valign': 'vcenter',
            'num_format': '#,##0'
        })

        # Worksheet
        sheet = workbook.add_worksheet("Document Summary")
        sheet.set_column(0, 0, 25)  # Nature Of Document
        sheet.set_column(1, 1, 25)  # Branch
        sheet.set_column(2, 3, 22)  # From / To Voucher No
        sheet.set_column(4, 6, 15)  # Counts

        row = 0
        # Title
        sheet.merge_range(row, 0, row, 6, self.env.company.name, title_style)
        row += 1
        sheet.merge_range(row, 0, row, 6, "Document Summary Report", report_title_style)
        row += 2

        # Filters
        if wizard.start_date:
            sheet.write(row, 0, "From:", header_format)
            sheet.write(row, 1, wizard.start_date.strftime('%d-%b-%Y'), normal_format)
            row += 1
        if wizard.end_date:
            sheet.write(row, 0, "To:", header_format)
            sheet.write(row, 1, wizard.end_date.strftime('%d-%b-%Y'), normal_format)
            row += 1

        sheet.write(row, 0, "Branch:", header_format)
        sheet.write(row, 1, wizard.warehouse_id.name if wizard.warehouse_id else 'ALL Branches', normal_format)
        row += 1
        row += 1

        # Table Header
        headers = [
            "Nature Of Document", "Branch", "From Voucher No", "To Voucher No",
            "Voucher Count", "Cancelled", "Net Issued"
        ]
        for col, head in enumerate(headers):
            sheet.write(row, col, head, header_format)
        row += 1

        # Grouped Data
        report_data = wizard._gather_report_data()
        doc_grouped = {}
        for line in report_data.get('lines', []):
            doc_grouped.setdefault(line.get('doc_type', 'Unknown'), []).append(line)

        doc_order = [
            "B2B Sale", "B2C Sale", "B2B Credit Note", "B2C Credit Note",
            "Purchase", "Debit Note", "Delivery Challan", "Receipt", "Payment"
        ]

        for doc_type in doc_order:
            if doc_type in doc_grouped:
                # Group Header Row
                sheet.merge_range(row, 0, row, 6, doc_type, group_format)
                row += 1
                # Detail Rows
                for line in doc_grouped[doc_type]:
                    sheet.write(row, 0, "", normal_format)  # Empty Nature Of Document
                    sheet.write(row, 1, line.get('branch', ''), normal_format)
                    sheet.write(row, 2, line.get('from_no', ''), normal_format)
                    sheet.write(row, 3, line.get('to_no', ''), normal_format)
                    sheet.write(row, 4, line.get('vch_count', 0), int_format)
                    sheet.write(row, 5, line.get('cancel_count', 0), int_format)
                    sheet.write(row, 6, line.get('net_count', 0), int_format)
                    row += 1


class Gstr1SummaryXlsxReport(models.AbstractModel):
    _name = 'report.prosevo_erp_accounts_management.gstr1_sum_xlsx_temp'

    def generate_xlsx_report(self, workbook, data, wizard):
        # Define Styles
        title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'font_size': 16
        })
        report_title_style = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#48585d',
            'text_wrap': True, 'border': True, 'align': 'center', 'valign': 'vcenter',
            'font_size': 12
        })
        bold_key_format = workbook.add_format({
            'bold': True, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })
        normal_value_format = workbook.add_format({
            'bold': False, 'font_color': 'black', 'font_size': 12,
            'align': 'left', 'valign': 'vcenter'
        })
        sub_header = workbook.add_format({
            'font_color': 'white', 'bg_color': '#48585d', 'font_size': 12,
            'text_wrap': True, 'border': True, 'align': 'center'
        })
        common_data = workbook.add_format({
            'bold': False, 'font_color': 'black', 'text_wrap': True, 'border': True, 'align': 'left'
        })
        int_format = workbook.add_format({
            'num_format': '#,##0', 'align': 'right', 'valign': 'vcenter', 'border': 1
        })
        # Sheet Setup
        sheet = workbook.add_worksheet("Gstrn1 Summary")
        sheet.set_row(0, 30)
        sheet.set_row(1, 20)
        sheet.set_column(0, 0, 25)
        sheet.set_column(1, 1, 22)  # Voucher Count
        sheet.set_column(2, 2, 22)  # Taxable Amount.
        sheet.set_column(3, 3, 15)  # Tax Amount.
        sheet.set_column(4, 4, 15)  # Total Inv Amount
        row = 1
        sheet.merge_range('A1:E1', self.env.company.name, title_style)
        row += 1
        sheet.merge_range('A2:E2', "Gstrn1 Summary Report", report_title_style)
        # Filters Info
        if wizard.start_date:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'From:    ', normal_value_format,
                                    wizard.start_date.strftime('%d-%b-%Y'))
        if wizard.end_date:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'To:      ', normal_value_format,
                                    wizard.end_date.strftime('%d-%b-%Y'))
        if wizard.warehouse_id:
            row += 1
            sheet.merge_range(row, 0, row, 2, "", normal_value_format)
            sheet.write_rich_string(row, 0, bold_key_format, 'Branch:  ', normal_value_format, wizard.warehouse_id.name)
        # Header Row
        row += 1
        headers = ['Document Type', 'Voucher Count', 'Taxable Amount', 'Tax Amount', 'Invoice Amount']
        for col, header in enumerate(headers):
            sheet.write(row, col, header, sub_header)
        sheet.set_row(row, 30)
        row += 1
        # Document types
        doc_types = ['B2B Invoices', 'B2C Large', 'B2C Small', 'Credit/Debit Registered',
                     'Credit/Debit UnRegistered']
        # Initialize totals
        total_voucher_count = 0
        total_untax_value = 0.0
        total_tax_value = 0.0
        total_inv_value = 0.0
        # Get report data lines
        report_data = wizard._gather_report_data()
        invoice_details = report_data.get('lines', [])
        for doc_type in doc_types:
            matched_detail = next((d for d in invoice_details if d.get('doc_type') == doc_type), None)
            if matched_detail:
                voucher_count = matched_detail.get('voucher_count', 0)
                untax_value = matched_detail.get('total_untax_value', 0.0)
                tax_value = matched_detail.get('total_tax_value', 0.0)
                inv_value = matched_detail.get('total_inv_value', 0.0)
                # Update totals
                total_voucher_count += voucher_count or 0
                total_untax_value += untax_value or 0.0
                total_tax_value += tax_value or 0.0
                total_inv_value += inv_value or 0.0
            else:
                voucher_count = untax_value = tax_value = inv_value = ''
            # Write row
            sheet.write(row, 0, doc_type, common_data)
            sheet.write(row, 1, voucher_count, int_format)
            sheet.write(row, 2, untax_value, int_format)
            sheet.write(row, 3, tax_value, int_format)
            sheet.write(row, 4, inv_value, int_format)
            row += 1
        # Total Row
        total_style = workbook.add_format({
            'bold': True, 'bg_color': '#e2e2e2', 'border': 1, 'align': 'center'
        })
        sheet.write(row, 0, 'Total', total_style)
        sheet.write(row, 1, total_voucher_count, int_format)
        sheet.write(row, 2, total_untax_value, int_format)
        sheet.write(row, 3, total_tax_value, int_format)
        sheet.write(row, 4, total_inv_value, int_format)
