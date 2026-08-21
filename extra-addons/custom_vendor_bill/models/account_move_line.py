from odoo import models, fields, api


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    # Stock column — shows available qty of product in selected warehouse
    x_stock_qty = fields.Float(
        string='Stock',
        compute='_compute_stock_qty',
        digits=(16, 2),
        help='Current stock quantity of this product in the bill warehouse',
    )

    # Label / description override
    x_label = fields.Char(
        string='Label',
        help='Custom label or description for this line',
    )

    # Lot / Serial Number
    x_lot_id = fields.Many2one(
        'stock.lot',
        string='Lot/Serial',
        domain="[('product_id', '=', product_id)]",
        help='Lot or serial number for this product',
    )

    @api.depends('product_id', 'move_id.x_warehouse_id')
    def _compute_stock_qty(self):
        for line in self:
            if line.product_id and line.product_id.type in ('product', 'consu'):
                warehouse = line.move_id.x_warehouse_id
                if warehouse and warehouse.lot_stock_id:
                    location = warehouse.lot_stock_id
                    quants = self.env['stock.quant'].search([
                        ('product_id', '=', line.product_id.id),
                        ('location_id', 'child_of', location.id),
                    ])
                    line.x_stock_qty = sum(quants.mapped('quantity'))
                else:
                    line.x_stock_qty = line.product_id.qty_available
            else:
                line.x_stock_qty = 0.0

    @api.onchange('product_id')
    def _onchange_product_set_label(self):
        if self.product_id and not self.x_label:
            self.x_label = self.product_id.name
