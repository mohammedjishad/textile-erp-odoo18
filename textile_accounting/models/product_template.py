from odoo import models, fields, api

class ProductProduct(models.Model):
    _inherit = 'product.product'

    total_manufactured = fields.Float(string="Total Manufactured", compute="_compute_product_profitability")
    total_sold = fields.Float(string="Total Sold", compute="_compute_product_profitability")
    avg_manufacturing_cost = fields.Float(string="Avg Cost", compute="_compute_product_profitability")
    avg_selling_price = fields.Float(string="Avg Selling Price", compute="_compute_product_profitability")
    gross_profit = fields.Float(string="Gross Profit", compute="_compute_product_profitability")
    margin_percent = fields.Float(string="Margin %", compute="_compute_product_profitability")

    def _get_product_cost(self):
        self.ensure_one()
        # 1. Completed Manufacturing Orders
        mos = self.env['mrp.production'].search([
            ('product_id', '=', self.id),
            ('state', '=', 'done')
        ])
        if mos:
            total_mfg = sum(mos.mapped('qty_produced'))
            total_mfg_cost = sum(mos.mapped('total_manufacturing_cost'))
            if total_mfg > 0:
                return total_mfg_cost / total_mfg

        # 2. Confirmed Purchase Orders
        pols = self.env['purchase.order.line'].search([
            ('product_id', '=', self.id),
            ('state', 'in', ('purchase', 'done'))
        ])
        if pols:
            total_po_qty = sum(pols.mapped('product_qty'))
            total_po_cost = sum(pol.price_unit * pol.product_qty for pol in pols)
            if total_po_qty > 0:
                return total_po_cost / total_po_qty

        # 3. Vendor Pricelist
        if self.seller_ids:
            return self.seller_ids[0].price

        # 4. Standard Price fallback
        return self.standard_price

    def _compute_product_profitability(self):
        for product in self:
            # Completed Manufacturing Orders
            mos = self.env['mrp.production'].search([
                ('product_id', '=', product.id),
                ('state', '=', 'done')
            ])
            total_mfg = sum(mos.mapped('qty_produced'))
            avg_mfg_cost = product._get_product_cost()

            # Confirmed Sales Order Lines
            sols = self.env['sale.order.line'].search([
                ('product_id', '=', product.id),
                ('state', 'in', ('sale', 'done'))
            ])
            total_sold = sum(sols.mapped('product_uom_qty'))
            total_revenue = sum(sols.mapped('price_subtotal'))
            avg_price = (total_revenue / total_sold) if total_sold > 0 else product.list_price

            # Profitability
            gross_profit = sum(sols.mapped('gross_profit')) if sols else 0.0
            margin = (gross_profit / total_revenue * 100.0) if total_revenue > 0 else 0.0

            product.update({
                'total_manufactured': total_mfg,
                'total_sold': total_sold,
                'avg_manufacturing_cost': avg_mfg_cost,
                'avg_selling_price': avg_price,
                'gross_profit': gross_profit,
                'margin_percent': margin,
            })


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    total_manufactured = fields.Float(string="Total Manufactured", compute="_compute_template_profitability")
    total_sold = fields.Float(string="Total Sold", compute="_compute_template_profitability")
    avg_manufacturing_cost = fields.Float(string="Avg Cost", compute="_compute_template_profitability")
    avg_selling_price = fields.Float(string="Avg Selling Price", compute="_compute_template_profitability")
    gross_profit = fields.Float(string="Gross Profit", compute="_compute_template_profitability")
    margin_percent = fields.Float(string="Margin %", compute="_compute_template_profitability")

    def _compute_template_profitability(self):
        for template in self:
            variants = template.product_variant_ids
            total_mfg = sum(variants.mapped('total_manufactured'))
            total_sold = sum(variants.mapped('total_sold'))
            
            # Weighted average cost
            total_mfg_cost = sum(v.total_manufactured * v.avg_manufacturing_cost for v in variants)
            avg_mfg_cost = (total_mfg_cost / total_mfg) if total_mfg > 0 else template.standard_price

            # Weighted average price
            total_revenue = sum(v.total_sold * v.avg_selling_price for v in variants)
            avg_price = (total_revenue / total_sold) if total_sold > 0 else template.list_price

            gross_profit = sum(variants.mapped('gross_profit'))
            margin = (gross_profit / total_revenue * 100.0) if total_revenue > 0 else 0.0

            template.update({
                'total_manufactured': total_mfg,
                'total_sold': total_sold,
                'avg_manufacturing_cost': avg_mfg_cost,
                'avg_selling_price': avg_price,
                'gross_profit': gross_profit,
                'margin_percent': margin,
            })
