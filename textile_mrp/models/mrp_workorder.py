# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    qty_transferred = fields.Float(
        string='Qty Transferred to Next WIP',
        default=0.0,
        copy=False,
        help="Tracks how many finished pieces have already been transferred from this workcenter WIP location to the next."
    )

    # No custom stock moves are created between work centers to align with standard Odoo MRP.

