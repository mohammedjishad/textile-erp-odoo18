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

    bom_usage_type = fields.Selection([
        ('manufactured', 'Manufactured Product'),
        ('raw_material', 'Raw Material'),
    ], string='BoM Usage Type',
        help="Controls where products in this category can be selected: "
             "'Manufactured Product' categories appear in the BoM header Product field, "
             "'Raw Material' categories appear in the BoM Component lines.")


