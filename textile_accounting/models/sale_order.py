from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    manufacturing_cost = fields.Float(string="Manufacturing Cost", compute="_compute_sales_profitability", store=True)
    gross_profit = fields.Float(string="Gross Profit", compute="_compute_sales_profitability", store=True)
    margin_percent = fields.Float(string="Margin %", compute="_compute_sales_profitability", store=True)

    @api.depends('order_line.manufacturing_cost', 'order_line.price_subtotal', 'amount_untaxed')
    def _compute_sales_profitability(self):
        for order in self:
            mfg_cost = sum(line.manufacturing_cost for line in order.order_line)
            selling_price = order.amount_untaxed
            profit = selling_price - mfg_cost
            margin = (profit / selling_price) if selling_price > 0 else 0.0

            order.update({
                'manufacturing_cost': mfg_cost,
                'gross_profit': profit,
                'margin_percent': margin,
            })


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    purchase_price = fields.Float(
        string="Cost", compute="_compute_purchase_price", store=True, precompute=False,
        readonly=False, copy=False, groups="base.group_user"
    )
    manufacturing_cost = fields.Float(string="Manufacturing Cost", compute="_compute_line_cost", store=True)
    gross_profit = fields.Float(string="Gross Profit", compute="_compute_line_cost", store=True)
    margin_percent = fields.Float(string="Margin %", compute="_compute_line_margin", store=True, precompute=False)
    margin = fields.Float(string="Margin", store=True, precompute=False)

    @api.depends('product_id', 'product_uom_qty', 'order_id.procurement_group_id', 'order_id.name')
    def _compute_purchase_price(self):
        for line in self:
            if not line.product_id:
                line.purchase_price = 0.0
                continue

            # Find linked Manufacturing Orders
            domain = []
            if line.order_id.procurement_group_id:
                domain.append(('procurement_group_id', '=', line.order_id.procurement_group_id.id))
            if line.order_id.name:
                domain.append(('origin', '=', line.order_id.name))

            mos = self.env['mrp.production']
            if domain:
                search_domain = ['|'] + domain if len(domain) > 1 else domain
                mos = self.env['mrp.production'].search(search_domain).filtered(
                    lambda m: m.state != 'cancel' and m.product_id == line.product_id
                )

            if mos:
                total_mo_cost = sum(mo.total_manufacturing_cost for mo in mos)
                total_mo_qty = sum(mo.qty_produced if mo.state == 'done' else (mo.qty_producing or mo.product_qty) for mo in mos)
                unit_cost = (total_mo_cost / total_mo_qty) if total_mo_qty > 0 else line.product_id._get_product_cost()
            else:
                unit_cost = line.product_id._get_product_cost()

            line.purchase_price = unit_cost

    @api.depends('purchase_price', 'product_uom_qty', 'price_subtotal')
    def _compute_line_cost(self):
        for line in self:
            if not line.product_id:
                line.manufacturing_cost = 0.0
                line.gross_profit = 0.0
                continue

            mfg_cost = line.purchase_price * line.product_uom_qty
            line.manufacturing_cost = mfg_cost
            line.gross_profit = line.price_subtotal - mfg_cost

    @api.depends('gross_profit', 'price_subtotal')
    def _compute_line_margin(self):
        for line in self:
            line.margin_percent = (line.gross_profit / line.price_subtotal) if line.price_subtotal > 0 else 0.0
