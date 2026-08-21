# -*- coding: utf-8 -*-
from odoo import models, fields, api

class MrpProductionVariantLine(models.Model):
    _name = 'mrp.production.variant.line'
    _description = 'Manufacturing Order Variant Line'

    production_id = fields.Many2one(
        'mrp.production', string='Manufacturing Order',
        ondelete='cascade', required=True, index=True
    )
    product_tmpl_id = fields.Many2one(
        'product.template', related='production_id.product_tmpl_id',
        store=True, readonly=True
    )
    product_id = fields.Many2one(
        'product.product', string='Product Variant',
        required=True, domain="[('product_tmpl_id', '=', product_tmpl_id)]"
    )
    product_qty = fields.Float(
        string='Planned Quantity', default=1.0, required=True
    )
    qty_producing = fields.Float(
        string='Producing Quantity', default=0.0
    )
    qty_produced = fields.Float(
        string='Produced Quantity', default=0.0
    )
    product_uom_id = fields.Many2one(
        'uom.uom', string='Unit of Measure',
        related='product_id.uom_id', readonly=True
    )
