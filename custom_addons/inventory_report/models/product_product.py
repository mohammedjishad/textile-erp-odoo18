from odoo import models, fields, api


class ProductProduct(models.Model):
    _inherit = 'product.product'

    x_category_name = fields.Char(
        string='Category (Flat)',
        compute='_compute_inventory_report_values',
        store=True,
        help='Flat category name (avoids the All/Goods parent-child hierarchy expansion in pivot).',
    )
    x_qty_on_hand = fields.Float(
        string='On Hand',
        compute='_compute_inventory_report_values',
        store=True,
        help='Quantity currently on hand (copied for report aggregation).',
    )
    x_unit_cost = fields.Float(
        string='Unit Cost',
        compute='_compute_inventory_report_values',
        store=True,
        help='Unit cost (copied for report aggregation).',
    )
    x_total_value = fields.Float(
        string='Total Stock Value',
        compute='_compute_inventory_report_values',
        store=True,
        help='On hand quantity multiplied by unit cost.',
    )
    x_gross_profit = fields.Float(
        string='Inv. Gross Profit',
        compute='_compute_inventory_report_values',
        store=True,
        help='(Sales price - Unit cost) multiplied by on hand quantity.',
    )

    @api.depends('qty_available', 'standard_price', 'list_price', 'categ_id')
    def _compute_inventory_report_values(self):
        for product in self:
            product.x_category_name = product.categ_id.name
            product.x_qty_on_hand = product.qty_available
            product.x_unit_cost = product.standard_price
            product.x_total_value = product.qty_available * product.standard_price
            product.x_gross_profit = (product.list_price - product.standard_price) * product.qty_available
