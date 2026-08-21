from odoo import models, fields, api

class StockLot(models.Model):
    _inherit = 'stock.lot'

    textile_mo_id = fields.Many2one('mrp.production', string="Manufacturing Order", compute="_compute_textile_traceability")
    textile_sale_order_id = fields.Many2one('sale.order', string="Sales Order", compute="_compute_textile_traceability")
    textile_customer_id = fields.Many2one('res.partner', string="Customer", compute="_compute_textile_traceability")
    textile_invoice_ids = fields.Many2many('account.move', string="Linked Invoices", compute="_compute_textile_traceability")
    textile_delivery_picking_ids = fields.Many2many('stock.picking', string="Delivery Pickings", compute="_compute_textile_traceability")
    textile_production_date = fields.Datetime(string="Production Date", compute="_compute_textile_traceability")
    textile_quality_inspection_ids = fields.Many2many('textile.quality', string="Quality Inspections", compute="_compute_textile_traceability")

    def _compute_textile_traceability(self):
        for lot in self:
            # 1. Find Manufacturing Order that produced this lot
            mfg_line = self.env['stock.move.line'].search([
                ('lot_id', '=', lot.id),
                ('move_id.production_id', '!=', False)
            ], limit=1)
            mo = mfg_line.move_id.production_id if mfg_line else self.env['mrp.production']

            # 2. Find delivery stock move lines for this lot
            delivery_lines = self.env['stock.move.line'].search([
                ('lot_id', '=', lot.id),
                ('picking_id.picking_type_id.code', '=', 'outgoing'),
                ('state', '=', 'done')
            ])
            deliveries = delivery_lines.mapped('picking_id')

            # 3. Find Sales Order
            so = self.env['sale.order']
            if delivery_lines:
                so = delivery_lines[0].move_id.sale_line_id.order_id
            if not so and mo:
                so = self.env['sale.order'].search([
                    '|',
                    ('procurement_group_id', '=', mo.procurement_group_id.id),
                    ('name', '=', mo.origin)
                ], limit=1)

            # 4. Find Customer
            customer = delivery_lines[0].picking_id.partner_id if delivery_lines else so.partner_id

            # 5. Find Invoices
            invoices = so.invoice_ids.filtered(lambda inv: inv.state != 'cancel') if so else self.env['account.move']

            # 6. Quality Inspections
            inspections = self.env['textile.quality'].search([
                ('production_id', '=', mo.id)
            ]) if mo else self.env['textile.quality']

            lot.update({
                'textile_mo_id': mo.id if mo else False,
                'textile_sale_order_id': so.id if so else False,
                'textile_customer_id': customer.id if customer else False,
                'textile_invoice_ids': [(6, 0, invoices.ids)],
                'textile_delivery_picking_ids': [(6, 0, deliveries.ids)],
                'textile_production_date': mo.date_finished if mo else lot.create_date,
                'textile_quality_inspection_ids': [(6, 0, inspections.ids)],
            })
