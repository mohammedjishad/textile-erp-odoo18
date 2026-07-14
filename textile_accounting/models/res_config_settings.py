from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    textile_overhead_rate = fields.Float(string="Overhead %", default=10.0)
    textile_factory_overhead_rate = fields.Float(string="Default Factory Overhead %", default=5.0)
    textile_waste_rate = fields.Float(string="Default Waste %", default=2.0)
    textile_enable_cost_sheet = fields.Boolean(string="Enable Cost Sheet", default=True)
    textile_enable_profitability = fields.Boolean(string="Enable Profitability", default=True)
    textile_enable_lot_traceability = fields.Boolean(string="Enable Lot Traceability", default=True)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    textile_overhead_rate = fields.Float(
        related='company_id.textile_overhead_rate', readonly=False, string="Overhead %"
    )
    textile_factory_overhead_rate = fields.Float(
        related='company_id.textile_factory_overhead_rate', readonly=False, string="Default Factory Overhead %"
    )
    textile_waste_rate = fields.Float(
        related='company_id.textile_waste_rate', readonly=False, string="Default Waste %"
    )
    textile_enable_cost_sheet = fields.Boolean(
        related='company_id.textile_enable_cost_sheet', readonly=False, string="Enable Cost Sheet"
    )
    textile_enable_profitability = fields.Boolean(
        related='company_id.textile_enable_profitability', readonly=False, string="Enable Profitability"
    )
    textile_enable_lot_traceability = fields.Boolean(
        related='company_id.textile_enable_lot_traceability', readonly=False, string="Enable Lot Traceability"
    )
