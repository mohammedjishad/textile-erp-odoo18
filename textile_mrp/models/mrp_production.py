# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    # SECTION A — Production consumption tracking
    issued_fabric = fields.Float(
        string='Issued Fabric (m)',
        compute='_compute_fabric_consumption',
        store=True
    )
    consumed_fabric = fields.Float(
        string='Consumed Fabric (m)',
        compute='_compute_fabric_consumption',
        store=True
    )
    returned_fabric = fields.Float(
        string='Returned Fabric (m)',
        compute='_compute_fabric_consumption',
        store=True
    )
    waste_qty = fields.Float(
        string='Waste Quantity',
        compute='_compute_fabric_consumption',
        store=True
    )
    waste_pct = fields.Float(
        string='Waste %',
        compute='_compute_waste_pct',
        store=True
    )

    # SECTION B — Production efficiency
    efficiency = fields.Float(
        string='Efficiency (%)',
        compute='_compute_efficiency',
        store=True
    )

    # SECTION B2 — Backorder Relationships
    backorder_id = fields.Many2one(
        'mrp.production',
        string='Parent Backorder',
        readonly=True,
        copy=False
    )
    backorder_ids = fields.One2many(
        'mrp.production',
        'backorder_id',
        string='Child Backorders',
        readonly=True
    )

    # SECTION C — Textile costing fields
    fabric_cost = fields.Float(
        string='Fabric Cost',
        compute='_compute_textile_costs',
        store=True,
        readonly=False
    )
    thread_cost = fields.Float(
        string='Thread Cost',
        compute='_compute_textile_costs',
        store=True,
        readonly=False
    )
    accessories_cost = fields.Float(
        string='Accessories Cost',
        compute='_compute_textile_costs',
        store=True,
        readonly=False
    )
    labor_cost = fields.Float(
        string='Labor Cost',
        compute='_compute_textile_costs',
        store=True,
        readonly=False
    )
    machine_cost = fields.Float(
        string='Machine Cost',
        compute='_compute_textile_costs',
        store=True,
        readonly=False
    )
    packaging_cost = fields.Float(
        string='Packaging Cost',
        compute='_compute_textile_costs',
        store=True,
        readonly=False
    )
    overhead_cost = fields.Float(string='Overhead Cost', default=0.0)
    total_textile_cost = fields.Float(
        string='Total Textile Cost',
        compute='_compute_total_textile_cost',
        store=True
    )
    raw_wip_transferred = fields.Boolean(
        string='Raw Materials Transferred to WIP',
        default=False,
        copy=False
    )

    @api.depends(
        'move_raw_ids.state', 'move_raw_ids.product_uom_qty', 'move_raw_ids.quantity',
        'move_raw_ids.product_id.categ_id.textile_cost_bucket',
        'scrap_ids.state', 'scrap_ids.scrap_qty', 'scrap_ids.product_id'
    )
    def _compute_fabric_consumption(self):
        for rec in self:
            fabric_moves = rec.move_raw_ids.filtered(lambda m: m.product_id.categ_id.textile_cost_bucket == 'fabric')
            issued = sum(fabric_moves.mapped('product_uom_qty'))
            consumed = sum(fabric_moves.filtered(lambda m: m.state == 'done').mapped('quantity'))
            
            # Find scrap records for fabric products associated with this MO
            fabric_products = fabric_moves.mapped('product_id')
            scraps = rec.scrap_ids.filtered(lambda s: s.product_id.id in fabric_products.ids and s.state == 'done')
            waste = sum(scraps.mapped('scrap_qty'))
            
            returned = max(0.0, issued - consumed - waste)
            
            rec.issued_fabric = issued
            rec.consumed_fabric = consumed
            rec.waste_qty = waste
            rec.returned_fabric = returned

    @api.depends('waste_qty', 'product_qty')
    def _compute_waste_pct(self):
        for rec in self:
            if rec.product_qty:
                rec.waste_pct = (rec.waste_qty / rec.product_qty) * 100
            else:
                rec.waste_pct = 0.0

    @api.depends('qty_produced', 'product_qty')
    def _compute_efficiency(self):
        for rec in self:
            if rec.product_qty:
                rec.efficiency = (rec.qty_produced / rec.product_qty) * 100
            else:
                rec.efficiency = 0.0

    @api.depends(
        'move_raw_ids.state', 'move_raw_ids.quantity',
        'move_raw_ids.product_id.standard_price', 'move_raw_ids.product_id.categ_id.textile_cost_bucket',
        'workorder_ids.state', 'workorder_ids.duration',
        'workorder_ids.workcenter_id.costs_hour_labor', 'workorder_ids.workcenter_id.costs_hour_machine'
    )
    def _compute_textile_costs(self):
        for rec in self:
            fabric = thread = acc = pkg = labor = machine = 0.0
            for move in rec.move_raw_ids.filtered(lambda m: m.state == 'done'):
                cost_val = move.quantity * move.product_id.standard_price
                bucket = move.product_id.categ_id.textile_cost_bucket
                if bucket == 'fabric':
                    fabric += cost_val
                elif bucket == 'thread':
                    thread += cost_val
                elif bucket == 'accessories':
                    acc += cost_val
                elif bucket == 'packaging':
                    pkg += cost_val
            
            for wo in rec.workorder_ids.filtered(lambda w: w.state == 'done' or w.duration > 0):
                hours = wo.duration / 60.0
                labor += hours * wo.workcenter_id.costs_hour_labor
                machine += hours * wo.workcenter_id.costs_hour_machine
                
            rec.fabric_cost = fabric
            rec.thread_cost = thread
            rec.accessories_cost = acc
            rec.packaging_cost = pkg
            rec.labor_cost = labor
            rec.machine_cost = machine

    @api.depends(
        'fabric_cost', 'thread_cost', 'accessories_cost', 'labor_cost',
        'machine_cost', 'packaging_cost', 'overhead_cost'
    )
    def _compute_total_textile_cost(self):
        for rec in self:
            rec.total_textile_cost = (
                rec.fabric_cost + rec.thread_cost + rec.accessories_cost +
                rec.labor_cost + rec.machine_cost + rec.packaging_cost +
                rec.overhead_cost
            )

    def action_record_waste(self):
        self.ensure_one()
        if self.waste_qty <= 0:
            raise UserError(_('Waste quantity must be greater than zero.'))
        scrap_vals = {
            'product_id': (
                self.move_raw_ids[0].product_id.id
                if self.move_raw_ids
                else self.product_id.id
            ),
            'scrap_qty': self.waste_qty,
            'production_id': self.id,
        }
        scrap = self.env['stock.scrap'].create(scrap_vals)
        scrap.action_validate()
        self.message_post(
            body=_("Waste of %s units recorded and posted to scrap.") % self.waste_qty
        )

    # DASHBOARD
    wip_dashboard = fields.Html(
        string='WIP Location Tracking Dashboard',
        compute='_compute_wip_dashboard'
    )

    @api.depends('state', 'product_qty', 'workorder_ids.state', 'workorder_ids.qty_produced', 'scrap_ids.state', 'scrap_ids.scrap_qty')
    def _compute_wip_dashboard(self):
        for rec in self:
            html = '<div style="background: #f8fafc; border-radius: 12px; padding: 20px; border: 1px solid #e2e8f0; font-family: sans-serif;">'
            html += '  <h4 style="margin: 0 0 15px 0; color: #1e293b; font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 8px;">'
            html += '    <span style="display:inline-block; width:8px; height:8px; background:#3b82f6; border-radius:50%;"></span> Live WIP Stage Tracking'
            html += '  </h4>'
            html += '  <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 15px;">'
            
            # Find all workorders, sort by sequence and ID
            wos = sorted(rec.workorder_ids, key=lambda w: (w.sequence, w.id))
            
            if not wos:
                html += '    <div style="color: #64748b; font-size: 14px; font-style: italic;">No operations/routing configured on this Manufacturing Order.</div>'
            else:
                # Group scraps by workorder_id to account for them at the correct stage
                scrap_by_wo_id = {}
                done_scraps = rec.scrap_ids.filtered(lambda s: s.state == 'done')
                for scrap in done_scraps:
                    wo_id = scrap.workorder_id.id
                    if not wo_id:
                        # Fallback 1: match by WIP location
                        matching_wo = rec.workorder_ids.filtered(lambda w: w.workcenter_id.wip_location_id.id == scrap.location_id.id)
                        if matching_wo:
                            wo_id = matching_wo[0].id
                        else:
                            # Fallback 2: if scrap product is the MO finished product, default to QC workorder
                            if scrap.product_id.id == rec.product_id.id:
                                qc_wo = rec.workorder_ids.filtered(lambda w: 'quality' in w.workcenter_id.name.lower() or 'qc' in w.workcenter_id.name.lower())
                                if qc_wo:
                                    wo_id = qc_wo[0].id
                    # Fallback 3: default to first workorder
                    if not wo_id and rec.workorder_ids:
                        wo_id = wos[0].id
                    if wo_id:
                        scrap_by_wo_id[wo_id] = scrap_by_wo_id.get(wo_id, 0.0) + scrap.scrap_qty

                steps = []
                for index, wo in enumerate(wos):
                    wc = wo.workcenter_id
                    
                    # Compute dynamic quantity for this stage
                    if rec.state == 'draft':
                        qty = 0.0
                    elif index == 0:
                        # First workorder: input is MO product_qty
                        entered = rec.product_qty
                        left = wo.qty_produced
                        scrapped = scrap_by_wo_id.get(wo.id, 0.0)
                        qty = max(0.0, entered - left - scrapped)
                    else:
                        # Subsequent workorder: input is previous stage's qty_produced
                        entered = wos[index - 1].qty_produced
                        left = wo.qty_produced
                        scrapped = scrap_by_wo_id.get(wo.id, 0.0)
                        qty = max(0.0, entered - left - scrapped)
                    
                    # If MO is Done or Cancelled, force all WIP to 0
                    if rec.state in ('done', 'cancel'):
                        qty = 0.0
                        
                    steps.append((wo.name.title(), qty, wc.name))

                for index, (step_name, qty, wc_name) in enumerate(steps):
                    is_active = qty > 0
                    bg_color = '#eff6ff' if is_active else '#f1f5f9'
                    border_color = '#bfdbfe' if is_active else '#cbd5e1'
                    text_color = '#1e3a8a' if is_active else '#475569'
                    
                    html += f'    <div style="flex: 1; min-width: 150px; background: {bg_color}; border: 1px solid {border_color}; border-radius: 10px; padding: 12px 15px; position: relative; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">'
                    html += f'      <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #64748b; margin-bottom: 4px; font-weight: 500;">{step_name}</div>'
                    html += f'      <div style="font-size: 20px; font-weight: 700; color: {text_color}; margin: 5px 0;">{int(qty)} <span style="font-size: 13px; font-weight: normal; color: #64748b;">pcs</span></div>'
                    html += f'      <div style="font-size: 11px; color: #94a3b8; font-style: italic;">{wc_name}</div>'
                    html += '    </div>'
                    
                    # Add arrow separator between steps
                    if index < len(steps) - 1:
                        html += '    <div style="color: #cbd5e1; font-size: 18px; font-weight: bold; display: flex; align-items: center;">➔</div>'
                        
            html += '  </div>'
            html += '</div>'
            rec.wip_dashboard = html

    # Confirms MO natively without routing stock through Packing WIP location.


    # Handle Manufacturing Order backorders.
    # Reset cancelled work orders to 'pending'
    # so they can be processed in the new backorder MO.
    def _split_productions(self, amounts=False, cancel_remaining_qty=False, set_consumed_qty=False):
        res = super(MrpProduction, self)._split_productions(amounts=amounts, cancel_remaining_qty=cancel_remaining_qty, set_consumed_qty=set_consumed_qty)
        # Identify backorders created during this split
        backorders = res - self
        for bo in backorders:
            # Explicitly synchronize parent-child relation and origin
            bo.backorder_id = self.id
            bo.origin = self.name
            # Force all cancelled work orders to start fresh for the backorder quantity
            for wo in bo.workorder_ids:
                if wo.state == 'cancel':
                    wo.state = 'pending'
                    wo.qty_producing = bo.product_qty

            # Automatically generate a "Pick Components" transfer for the backorder raw materials
            if bo.warehouse_id and bo.warehouse_id.pbm_type_id and bo.location_src_id != bo.warehouse_id.lot_stock_id:
                picking_vals = {
                    'picking_type_id': bo.warehouse_id.pbm_type_id.id,
                    'location_id': bo.warehouse_id.lot_stock_id.id,
                    'location_dest_id': bo.location_src_id.id,
                    'origin': bo.name,
                    'company_id': bo.company_id.id,
                }
                if bo.procurement_group_id:
                    picking_vals['group_id'] = bo.procurement_group_id.id
                picking = self.env['stock.picking'].create(picking_vals)
                
                for move in bo.move_raw_ids:
                    move_vals = {
                        'name': move.product_id.display_name,
                        'picking_id': picking.id,
                        'product_id': move.product_id.id,
                        'product_uom': move.product_uom.id,
                        'product_uom_qty': move.product_uom_qty,
                        'location_id': bo.warehouse_id.lot_stock_id.id,
                        'location_dest_id': bo.location_src_id.id,
                        'origin': bo.name,
                    }
                    if bo.procurement_group_id:
                        move_vals['group_id'] = bo.procurement_group_id.id
                    self.env['stock.move'].create(move_vals)
                
                picking.action_confirm()
                picking.action_assign()

        return res


