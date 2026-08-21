from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime, date
from collections import defaultdict
import xlsxwriter
from io import BytesIO
import base64
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.lib.enums import TA_LEFT


class Gstirn2bReport(models.TransientModel):
    _name = 'gstirn2b.report'

    start_date = fields.Date(string="Start Date", default=lambda self: self._get_default_start_date())
    end_date = fields.Date(string="End Date", default=fields.Date.today)
    report_data = fields.Text(compute='_compute_report_data')
    display_report_details = fields.Boolean(string='Display Report Details', transient=True)
    warehouse_id = fields.Many2one('stock.warehouse', string="Branch")
    excel_file = fields.Binary('Excel File', readonly=True)
    excel_file_name = fields.Char('Excel File Name')
    pdf_file = fields.Binary("PDF File", readonly=True)
    pdf_file_name = fields.Char("PDF Filename", readonly=True)
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

    @api.depends('display_report_details')
    def _compute_report_data(self):
        for record in self:
            invoice_details = record._gather_report_data()
            record.report_data = self._format_report_data_to_html(invoice_details)

    def _gather_report_data(self):
        domain = []
        for rec in self:
            if not rec.start_date or not rec.end_date:
                raise UserError("Please provide both Start Date and End Date.")
            if rec.start_date:
                domain.append(('invoice_date', '>=', rec.start_date))
            if rec.end_date:
                domain.append(('invoice_date', '<=', rec.end_date))
            if rec.warehouse_id:
                domain.append(('warehouse_id', '=', rec.warehouse_id.id))
            domain.append(('move_type', 'in', ['in_invoice']))
            domain.append(('state', '=', 'posted'))
            purchase_data = rec.env['account.move'].search(domain, order='invoice_date asc, name asc')
            purchase_final_data = []
            sl_no = 1
            for rec in purchase_data:
                line_untaxed_total = sum(line.price_subtotal for line in rec.invoice_line_ids)
                cgst = sgst = igst = 0.0

                for line in rec.invoice_line_ids:
                    for tax in line.tax_ids:
                        if tax.tax_group_id.name.lower() == 'cgst':
                            cgst += line.price_subtotal * (tax.amount / 100)
                        elif tax.tax_group_id.name.lower() == 'sgst':
                            sgst += line.price_subtotal * (tax.amount / 100)
                        elif tax.tax_group_id.name.lower() == 'igst':
                            igst += line.price_subtotal * (tax.amount / 100)
                purchase_final_data.append({
                    'sl_no': sl_no,
                    'date': rec.invoice_date.strftime('%d-%b-%Y') if rec.invoice_date else '',
                    'type': 'Purchase',
                    'customer_name': rec.partner_id.name,
                    'inv_no': rec.ref or rec.name or '',
                    'inv_value': round(line_untaxed_total, 2),
                    'cgst': round(cgst, 2),
                    'sgst': round(sgst, 2),
                    'igst': round(igst, 2),
                    'total_amount': round(rec.amount_total or 0.0, 2)
                })
                sl_no += 1
        return {
            'lines': purchase_final_data,
        }

    def _format_report_data_to_html(self, report_data):
        for rec in self:
            if not report_data:
                return "No data found for the selected filters"
            invoice_details = report_data.get('lines', [])
            # Initialize totals
            total_inv_value = 0.0
            total_cgst = 0.0
            total_sgst = 0.0
            total_igst = 0.0
            total_amount = 0.0
            report_html = f"""
               <style>
                   table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
                   th, td {{ border: 1px solid #999; padding: 6px; text-align: center; }}
                   th {{ background-color: #f2f2f2; }}
               </style>
               <table>
                   <thead>
                       <tr>
                            <th>Sl No</th>
                            <th>Date</th>
                            <th>Type</th>
                            <th>Ledger</th>
                            <th>Invoice No</th>
                            <th>Amount</th>
                            <th>CGST</th>
                            <th>SGST
                            <th>IGST</th>
                            <th>Total Amount</th>
                       </tr>
                   </thead>
                   <tbody>
               """
            for detail in invoice_details:
                report_html += f"""
                       <tr>
                           <td>{detail['sl_no']}</td>
                           <td>{detail['date']}</td>
                           <td>{detail['type']}</td>
                           <td>{detail['customer_name']}</td>
                           <td>{detail['inv_no']}</td>
                           <td>{detail['inv_value']}</td>
                           <td>{detail['cgst']}</td>
                           <td>{detail['sgst']}</td>
                           <td>{detail['igst']}</td>
                           <td>{detail['total_amount']}</td>
                       </tr>
                   """
                # Add to totals
                total_inv_value += detail.get('inv_value', 0.0)
                total_cgst += detail.get('cgst', 0.0)
                total_sgst += detail.get('sgst', 0.0)
                total_igst += detail.get('igst', 0.0)
                total_amount += detail.get('total_amount', 0.0)
            report_html += f"""
                        <tr style="font-weight: bold; background-color: #e6e6e6;">
                           <td colspan="5">Total</td>
                           <td>{total_inv_value:.2f}</td>
                           <td>{total_cgst:.2f}</td>
                           <td>{total_sgst:.2f}</td>
                           <td>{total_igst:.2f}</td>
                           <td>{total_amount:.2f}</td>
                       </tr>
                  </tbody>
              </table>
              """
        return report_html

    def generate_pdf_report(self):
        """ Called from the PDF button to trigger the download """
        self.generate_pdf()
        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content?model=gstirn2b.report&id={self.id}&field=pdf_file&download=true&filename={self.pdf_file_name}",
            'target': 'self',
        }

    def _add_page_number(self, canvas, doc):
        page_num_text = f"Page {doc.page}"
        canvas.setFont('Helvetica', 8)
        width = doc.pagesize[0]  # Total width of the page
        canvas.drawCentredString(width / 2.0, 15 * mm, page_num_text)

    def generate_pdf(self):
        for rec in self:
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
            elements = []

            styles = getSampleStyleSheet()
            styles.add(ParagraphStyle(name='CenterTitle', alignment=1, fontSize=14, spaceAfter=6))
            styles.add(ParagraphStyle(name='MainTitle', alignment=1, fontSize=16, spaceAfter=5, leading=20,
                                      fontName="Helvetica-Bold"))

            # Paragraph style for wrapping Ledger column
            wrap_style = ParagraphStyle(
                name='WrapStyle',
                fontSize=8,
                alignment=TA_LEFT,
                wordWrap='CJK',
            )

            # Add title
            elements.append(Paragraph(self.env.company.name, styles['MainTitle']))
            elements.append(Paragraph("GSTR - 2B Report", styles['CenterTitle']))
            date_text = f"Date : {self.start_date.strftime('%d-%b-%Y')} to {self.end_date.strftime('%d-%b-%Y')}"
            elements.append(Paragraph(date_text, styles['CenterTitle']))
            if self.warehouse_id:
                branch = f"Branch : {self.warehouse_id.name}"
                elements.append(Paragraph(branch, styles['CenterTitle']))
            elements.append(Spacer(1, 0.2 * inch))

            # Table data header
            table_data = [
                ['Date', 'Type', 'Ledger', 'Invoice No', 'Amount', 'CGST', 'SGST', 'IGST', 'Total']
            ]

            # Column widths in points (1 inch = 72 points)
            col_widths = [50, 40, 105, 75, 50, 50, 50, 50, 60]  # Ledger column is fixed at 100 pts

            sl_no = 1
            total_amount = total_cgst = total_sgst = total_igst = total_grand = 0.0

            for line in rec._gather_report_data().get('lines', []):
                ledger_cell = Paragraph(line['customer_name'] or '', wrap_style)

                table_data.append([
                    line['date'],
                    line['type'],
                    ledger_cell,
                    line['inv_no'] or '',
                    "{:,.2f}".format(line['inv_value']),
                    "{:,.2f}".format(line['cgst']),
                    "{:,.2f}".format(line['sgst']),
                    "{:,.2f}".format(line['igst']),
                    "{:,.2f}".format(line['total_amount']),
                    ])
                total_amount += line['inv_value']
                total_cgst += line['cgst']
                total_sgst += line['sgst']
                total_igst += line['igst']
                total_grand += line['total_amount']
                sl_no += 1

            # Add Grand Total row
            table_data.append([
                '', '', '', 'Grand Total',
                "{:,.2f}".format(total_amount),
                "{:,.2f}".format(total_cgst),
                "{:,.2f}".format(total_sgst),
                "{:,.2f}".format(total_igst),
                "{:,.2f}".format(total_grand),
            ])

            # Create table with column widths
            table = Table(table_data, repeatRows=1, colWidths=col_widths)

            # Table styling
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#d3d3d3')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                ('BACKGROUND', (0, 1), (-1, -2), colors.white),
                ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
            ]))

            elements.append(table)
            doc.build(elements, onFirstPage=self._add_page_number, onLaterPages=self._add_page_number)

            pdf_content = buffer.getvalue()
            buffer.close()

            rec.pdf_file = base64.b64encode(pdf_content)
            rec.pdf_file_name = f"GSTR2B_Report_{date.today().strftime('%d-%b-%Y')}.pdf"

    # def generate_excel_report(self):
    #     self.ensure_one()  # Good practice to avoid looping unless needed
    #     data = {
    #         'ids': self.ids,
    #         'model': self._name,
    #         'form': {
    #             'date_from': self.start_date,
    #             'date_to': self.end_date,
    #             'warehouse_id': self.warehouse_id.id if self.warehouse_id else False,
    #         },
    #     }
    #     file_name = 'GSTRN2 From %s to %s' % (
    #         self.start_date.strftime('%Y-%m-%d'),
    #         self.end_date.strftime('%Y-%m-%d')
    #     )
    #     # Optional: set file name on the report record (if used in the UI)
    #     self.env.ref('prosevo_erp_accounts_management.gstirn2b_xlsx_report').sudo().report_file = file_name
    #     # Trigger the report download
    #     return self.env.ref('prosevo_erp_accounts_management.gstirn2b_xlsx_report').report_action(self, data=data)

    def generate_xlsx_report_gstrin2b(self):
        self.ensure_one()  # Ensure we're working with a single record

        # Create the Excel file in memory
        output = BytesIO()

        try:
            # Create workbook and worksheet
            workbook = xlsxwriter.Workbook(output)
            worksheet = workbook.add_worksheet("GSTR2B Report")

            # Define formats
            header_format = workbook.add_format({
                'bold': True,
                'align': 'center',
                'bg_color': '#D3D3D3',
                'border': 1,
                'valign': 'vcenter'
            })
            cell_format = workbook.add_format({
                'border': 1,
                'align': 'center',
                'valign': 'vcenter'
            })
            number_format = workbook.add_format({
                'border': 1,
                'align': 'right',
                'valign': 'vcenter',
                'num_format': '#,##0.00'
            })
            title_format = workbook.add_format({
                'bold': True,
                'font_size': 14,
                'align': 'center',
                'valign': 'vcenter'
            })
            total_format = workbook.add_format({
                'bold': True,
                'border': 1,
                'align': 'center',
                'valign': 'vcenter',
                'bg_color': '#E6E6E6'
            })
            total_number_format = workbook.add_format({
                'bold': True,
                'border': 1,
                'align': 'right',
                'valign': 'vcenter',
                'bg_color': '#E6E6E6',
                'num_format': '#,##0.00'
            })
            left_align_format = workbook.add_format({
                'border': 1,
                'align': 'left',
                'valign': 'vcenter'
            })

            # Set column width
            worksheet.set_column('A:A', 8)  # Sl No
            worksheet.set_column('B:B', 12)  # Date
            worksheet.set_column('C:C', 12)  # Type
            worksheet.set_column('D:D', 50)  # Ledger
            worksheet.set_column('E:E', 20)  # Invoice No
            worksheet.set_column('F:F', 15)  # Amount
            worksheet.set_column('G:G', 12)  # CGST
            worksheet.set_column('H:H', 12)  # SGST
            worksheet.set_column('I:I', 12)  # IGST
            worksheet.set_column('J:J', 15)  # Total Amount

            # Write header information
            worksheet.merge_range('A1:J1', self.env.company.name, title_format)
            worksheet.merge_range('A2:J2', 'GSTR2B Report', title_format)

            date_text = f"Date: {self.start_date.strftime('%d-%b-%Y')} to {self.end_date.strftime('%d-%b-%Y')}"
            worksheet.write(2, 0, date_text, left_align_format)

            if self.warehouse_id:
                branch = f"Branch: {self.warehouse_id.name}"
                worksheet.write(3, 0, branch, left_align_format)

            # Write column headers
            headers = [
                'Sl No', 'Date', 'Type', 'Ledger', 'Invoice No',
                'Amount', 'CGST', 'SGST', 'IGST', 'Total Amount'
            ]

            for col, header in enumerate(headers):
                worksheet.write(4, col, header, header_format)
            # Get report data
            report_data = self._gather_report_data()
            invoice_details = report_data.get('lines', [])

            # Initialize totals
            totals = {
                'inv_value': 0.0,
                'cgst': 0.0,
                'sgst': 0.0,
                'igst': 0.0,
                'total_amount': 0.0
            }

            # Write data rows
            for row_idx, detail in enumerate(invoice_details, start=5):  # Start at row 5
                worksheet.write(row_idx, 0, detail['sl_no'], cell_format)
                worksheet.write(row_idx, 1, detail['date'], cell_format)
                worksheet.write(row_idx, 2, detail['type'], cell_format)
                worksheet.write(row_idx, 3, detail['customer_name'], cell_format)
                worksheet.write(row_idx, 4, detail['inv_no'], cell_format)
                worksheet.write(row_idx, 5, detail['inv_value'], number_format)
                worksheet.write(row_idx, 6, detail['cgst'], number_format)
                worksheet.write(row_idx, 7, detail['sgst'], number_format)
                worksheet.write(row_idx, 8, detail['igst'], number_format)
                worksheet.write(row_idx, 9, detail['total_amount'], number_format)

                # Update totals
                totals['inv_value'] += detail.get('inv_value', 0.0)
                totals['cgst'] += detail.get('cgst', 0.0)
                totals['sgst'] += detail.get('sgst', 0.0)
                totals['igst'] += detail.get('igst', 0.0)
                totals['total_amount'] += detail.get('total_amount', 0.0)

            # Write totals row
            last_row = 5 + len(invoice_details)
            worksheet.write(last_row, 4, 'TOTAL', total_format)
            worksheet.write(last_row, 5, totals['inv_value'], total_number_format)
            worksheet.write(last_row, 6, totals['cgst'], total_number_format)
            worksheet.write(last_row, 7, totals['sgst'], total_number_format)
            worksheet.write(last_row, 8, totals['igst'], total_number_format)
            worksheet.write(last_row, 9, totals['total_amount'], total_number_format)

            workbook.close()
            output.seek(0)
            excel_data = output.read()

            # Save the file to the record
            self.write({
                'excel_file': base64.b64encode(excel_data),
                'excel_file_name': f"GSTR2B_Report_{fields.Date.today().strftime('%d-%b-%Y')}.xlsx"
            })

            # Return download action
            return {
                'type': 'ir.actions.act_url',
                'url': f"/web/content/?model=gstirn2b.report&id={self.id}&field=excel_file&download=true&filename={self.excel_file_name}",
                'target': 'self',
            }

        except Exception as e:
            raise UserError(f"Error generating Excel report: {str(e)}")
        finally:
            output.close()

class Gstr2bXlsxReport(models.AbstractModel):
    _name = 'report.prosevo_erp_accounts_management.gstrn2b_xlsx_temp'
    _inherit = 'report.report_xlsx.abstract'

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
        sheet.set_column(1, 1, 14)  # Date
        sheet.set_column(2, 2, 19)  # Type
        sheet.set_column(3, 3, 25)  # Ledger
        sheet.set_column(4, 4, 20)  # Invoice No
        sheet.set_column(5, 5, 15)  # Amount
        sheet.set_column(6, 6, 15)  # CGST
        sheet.set_column(7, 7, 15)  # SGST
        sheet.set_column(8, 8, 15)  # IGST
        sheet.set_column(9, 9, 15)  # Total Amount

        row = 1
        sheet.merge_range('A1:J1', self.env.company.name, title_style)
        row += 1
        sheet.merge_range('A2:J2', "GSTR2B Report", report_title_style)

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
        headers = [
            'Sl No', 'Date', 'Type', 'Ledger', 'Invoice No',
            'Amount', 'CGST', 'SGST',
            'IGST', 'Total Amount'
        ]
        for col, header in enumerate(headers):
            sheet.write(row, col, header, sub_header)
        sheet.set_row(row, 30)

        # Data Rows
        report_data = wizard._gather_report_data()
        row += 1
        # Initialize totals
        total_inv_value = 0.0
        total_cgst = 0.0
        total_sgst = 0.0
        total_igst = 0.0
        total_amount = 0.0
        for line in report_data.get('lines', []):
            sheet.write(row, 0, line.get('sl_no', ''), common_data)
            sheet.write(row, 1, line.get('date', ''), common_data)
            sheet.write(row, 2, line.get('type', ''), common_data)
            sheet.write(row, 3, line.get('customer_name', ''), common_data)
            sheet.write(row, 4, line.get('inv_no', ''), date_format)
            sheet.write(row, 5, line.get('inv_value', 0), float_format)
            sheet.write(row, 6, line.get('cgst', ''), common_data)
            sheet.write(row, 7, line.get('sgst', ''), common_data)
            sheet.write(row, 8, line.get('igst', ''), common_data)
            sheet.write(row, 9, line.get('total_amount', 0.0), float_format)
            sheet.set_row(row, 19)
            # Accumulate totals
            total_inv_value += line.get('inv_value', 0.0)
            total_cgst += line.get('cgst', 0.0)
            total_sgst += line.get('sgst', 0.0)
            total_igst += line.get('igst', 0.0)
            total_amount += line.get('total_amount', 0.0)
            row += 1
        # Add Total Row
        sheet.merge_range(row, 0, row, 4, "Total", sub_header)
        sheet.write(row, 5, total_inv_value, float_format)
        sheet.write(row, 6, total_cgst, float_format)
        sheet.write(row, 7, total_sgst, float_format)
        sheet.write(row, 8, total_igst, float_format)
        sheet.write(row, 9, total_amount, float_format)
