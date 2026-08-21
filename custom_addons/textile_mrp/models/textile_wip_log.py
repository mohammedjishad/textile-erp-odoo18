# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class TextileWipLog(models.Model):
    _name = 'textile.wip.log'
    _description = 'Work In Progress Tracking Log'
    _order = 'date desc, id desc'

    workorder_id = fields.Many2one(
        'mrp.workorder',
        string='Work Order',
        required=True,
        ondelete='cascade',
        index=True
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        related='workorder_id.production_id',
        store=True,
        index=True
    )
    user_id = fields.Many2one(
        'res.users',
        string='Operator',
        default=lambda self: self.env.user,
        required=True
    )
    date = fields.Datetime(
        string='Date',
        default=fields.Datetime.now,
        required=True
    )
    action_type = fields.Selection([
        ('produce', 'Produced'),
        ('transfer', 'Transferred')
    ], string='Action Type', required=True)
    
    qty = fields.Float(string='Quantity', required=True)
    
    notes = fields.Char(string='Notes')
