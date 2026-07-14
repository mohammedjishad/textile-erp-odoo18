from odoo import models, fields, api

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    material_cost = fields.Float(string="Material Cost", compute="_compute_mfg_costs", store=True)
    labour_cost = fields.Float(string="Labour Cost", compute="_compute_mfg_costs", store=True)
    machine_cost = fields.Float(string="Machine Cost", compute="_compute_mfg_costs", store=True)
    
    # Override overhead_cost from textile_mrp to compute it dynamically
    overhead_cost = fields.Float(string="Overhead Cost", compute="_compute_mfg_costs", store=True)
    total_manufacturing_cost = fields.Float(string="Total Manufacturing Cost", compute="_compute_mfg_costs", store=True)
    
    manufacturing_value = fields.Float(string="Manufacturing Value", compute="_compute_mfg_costs", store=True)
    cost_per_unit = fields.Float(string="Production Cost per Unit", compute="_compute_mfg_costs", store=True)
    manufacturing_profit = fields.Float(string="Manufacturing Profit/Loss", compute="_compute_mfg_costs", store=True)

    @api.depends('fabric_cost', 'thread_cost', 'accessories_cost', 'packaging_cost',
                 'labor_cost', 'machine_cost', 'qty_produced', 'qty_producing', 'product_qty',
                 'state', 'company_id.textile_overhead_rate', 'product_id.standard_price')
    def _compute_mfg_costs(self):
        for mo in self:
            mat_cost = mo.fabric_cost + mo.thread_cost + mo.accessories_cost + mo.packaging_cost
            lab_cost = mo.labor_cost
            mac_cost = mo.machine_cost
            overhead_rate = mo.company_id.textile_overhead_rate
            ovh_cost = (mat_cost + lab_cost + mac_cost) * (overhead_rate / 100.0)
            total_cost = mat_cost + lab_cost + mac_cost + ovh_cost
            
            finished_qty = mo.qty_produced if mo.state == 'done' else (mo.qty_producing or mo.product_qty)
            mfg_value = finished_qty * mo.product_id.standard_price
            unit_cost = (total_cost / finished_qty) if finished_qty > 0 else 0.0
            profit = mfg_value - total_cost

            mo.update({
                'material_cost': mat_cost,
                'labour_cost': lab_cost,
                'machine_cost': mac_cost,
                'overhead_cost': ovh_cost,
                'total_manufacturing_cost': total_cost,
                'manufacturing_value': mfg_value,
                'cost_per_unit': unit_cost,
                'manufacturing_profit': profit
            })
