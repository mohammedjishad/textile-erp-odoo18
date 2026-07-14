# -*- coding: utf-8 -*-
from odoo import models, fields, api

class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    costs_hour_machine = fields.Float(string='Machine Cost per hour', default=0.0)
    costs_hour_labor = fields.Float(string='Labor Cost per hour', default=0.0)
    wip_location_id = fields.Many2one(
        'stock.location',
        string='WIP Location',
        domain="[('usage', '=', 'internal')]",
        help="Inventory location associated with this work center for tracking raw components and WIP."
    )

    costs_hour = fields.Float(
        compute='_compute_costs_hour',
        store=True,
        readonly=True
    )

    @api.depends('costs_hour_machine', 'costs_hour_labor')
    def _compute_costs_hour(self):
        for wc in self:
            wc.costs_hour = wc.costs_hour_machine + wc.costs_hour_labor
