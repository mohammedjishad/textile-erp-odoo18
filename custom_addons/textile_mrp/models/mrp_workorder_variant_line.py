# -*- coding: utf-8 -*-
from odoo import models, fields, api

class MrpWorkorderVariantLine(models.Model):
    _name = 'mrp.workorder.variant.line'
    _description = 'Work Order Variant Progress Line'

    workorder_id = fields.Many2one(
        'mrp.workorder', string='Work Order',
        ondelete='cascade', required=True, index=True
    )
    product_id = fields.Many2one(
        'product.product', string='Product Variant',
        required=True
    )
    planned_qty = fields.Float(
        string='Planned Qty', default=0.0
    )
    qty_produced = fields.Float(
        string='Done Qty', default=0.0
    )
    qty_transferred = fields.Float(
        string='Qty Transferred', default=0.0
    )
    qty_ready = fields.Float(
        string='Ready for Next Stage', compute='_compute_qty_ready', store=True
    )
    qty_remaining = fields.Float(
        string='Remaining Qty', compute='_compute_qty_remaining', store=True
    )
    product_uom_id = fields.Many2one(
        'uom.uom', string='Unit of Measure',
        related='product_id.uom_id', readonly=True
    )

    @api.depends('planned_qty', 'qty_produced')
    def _compute_qty_remaining(self):
        for line in self:
            line.qty_remaining = max(0.0, line.planned_qty - line.qty_produced)

    @api.depends('qty_produced', 'qty_transferred')
    def _compute_qty_ready(self):
        for line in self:
            line.qty_ready = max(0.0, line.qty_produced - line.qty_transferred)
