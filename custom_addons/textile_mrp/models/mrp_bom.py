# -*- coding: utf-8 -*-
from odoo import models, fields

class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    manufactured_categ_ids = fields.Many2many(
        'product.category',
        compute='_compute_bom_categ_ids',
        string='Manufactured Categories (Technical)',
    )
    raw_material_categ_ids = fields.Many2many(
        'product.category',
        compute='_compute_bom_categ_ids',
        string='Raw Material Categories (Technical)',
    )

    def _compute_bom_categ_ids(self):
        manufactured = self.env['product.category'].search([('bom_usage_type', '=', 'manufactured')])
        raw_material = self.env['product.category'].search([('bom_usage_type', '=', 'raw_material')])
        for rec in self:
            rec.manufactured_categ_ids = manufactured
            rec.raw_material_categ_ids = raw_material