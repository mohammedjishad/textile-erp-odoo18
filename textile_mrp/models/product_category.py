# -*- coding: utf-8 -*-
from odoo import models, fields

class ProductCategory(models.Model):
    _inherit = 'product.category'

    textile_cost_bucket = fields.Selection([
        ('fabric', 'Fabric Cost'),
        ('thread', 'Thread Cost'),
        ('accessories', 'Accessories Cost'),
        ('packaging', 'Packaging Cost'),
    ], string='Textile Cost Bucket', help="Group products under this category in textile costing calculations.")
