from odoo import models, fields

class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    incharge_user_ids = fields.Many2many(
        'res.users',
        string='Incharge Users'
    )