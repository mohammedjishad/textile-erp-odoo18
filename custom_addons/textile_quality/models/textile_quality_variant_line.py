# -*- coding: utf-8 -*-
from odoo import models, fields, api

class TextileQualityVariantLine(models.Model):
    _name = 'textile.quality.variant.line'
    _description = 'Textile Quality Variant Line'

    quality_id = fields.Many2one('textile.quality', string='Quality Inspection', ondelete='cascade', required=True)
    product_id = fields.Many2one('product.product', string='Product Variant', required=True)
    
    received_qty = fields.Float(string='Received Qty', default=0.0)
    passed_qty = fields.Float(string='Passed Qty', default=0.0)
    failed_qty = fields.Float(string='Failed Qty', default=0.0)
    rework_qty = fields.Float(string='Rework Qty', default=0.0)
    scrap_qty = fields.Float(string='Scrap Qty', default=0.0)
    
    defect_reason = fields.Selection([
        ('stitch_defect', 'Stitch Defect'),
        ('fabric_damage', 'Fabric Damage'),
        ('color_mismatch', 'Color Mismatch'),
        ('size_mismatch', 'Size Mismatch'),
        ('missing_accessories', 'Missing Accessories'),
        ('other', 'Other'),
    ], string='Defect Reason')
    remarks = fields.Char(string='Remarks')

    @api.onchange('passed_qty', 'received_qty')
    def _onchange_passed_qty(self):
        for rec in self:
            if rec.received_qty > 0:
                if rec.passed_qty > rec.received_qty:
                    rec.passed_qty = rec.received_qty
                rec.failed_qty = rec.received_qty - rec.passed_qty

    @api.onchange('failed_qty', 'received_qty')
    def _onchange_failed_qty(self):
        for rec in self:
            if rec.received_qty > 0:
                if rec.failed_qty > rec.received_qty:
                    rec.failed_qty = rec.received_qty
                rec.passed_qty = rec.received_qty - rec.failed_qty

    @api.onchange('rework_qty', 'failed_qty')
    def _onchange_rework_qty(self):
        for rec in self:
            if rec.failed_qty > 0:
                if rec.rework_qty > rec.failed_qty:
                    rec.rework_qty = rec.failed_qty
                rec.scrap_qty = rec.failed_qty - rec.rework_qty

    @api.onchange('scrap_qty', 'failed_qty')
    def _onchange_scrap_qty(self):
        for rec in self:
            if rec.failed_qty > 0:
                if rec.scrap_qty > rec.failed_qty:
                    rec.scrap_qty = rec.failed_qty
                rec.rework_qty = rec.failed_qty - rec.scrap_qty
