from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    sales_revenue = fields.Float(string="Total Sales", compute="_compute_customer_profitability")
    manufacturing_cost = fields.Float(string="Total Mfg Cost", compute="_compute_customer_profitability")
    profit = fields.Float(string="Total Profit", compute="_compute_customer_profitability")
    margin_percent = fields.Float(string="Margin %", compute="_compute_customer_profitability")

    def _compute_customer_profitability(self):
        for partner in self:
            # Find all confirmed sales orders for this customer (including its contacts)
            sales = self.env['sale.order'].search([
                ('partner_id', 'child_of', partner.id),
                ('state', 'in', ('sale', 'done'))
            ])
            total_revenue = sum(sales.mapped('amount_untaxed'))
            total_mfg_cost = sum(sales.mapped('manufacturing_cost'))
            profit = total_revenue - total_mfg_cost
            margin = (profit / total_revenue * 100.0) if total_revenue > 0 else 0.0

            partner.update({
                'sales_revenue': total_revenue,
                'manufacturing_cost': total_mfg_cost,
                'profit': profit,
                'margin_percent': margin,
            })
