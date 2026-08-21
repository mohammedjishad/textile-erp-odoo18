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

    # SECTION D — Multi-Variant Manufacturing Order (MVMO) Fields
    is_multi_variant = fields.Boolean(
        string='Multi-Variant MO',
        default=False,
        help='Check to manufacture multiple variants of the same product template in a single Manufacturing Order.'
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product Template'
    )
    variant_line_ids = fields.One2many(
        'mrp.production.variant.line',
        'production_id',
        string='Variant Lines',
        copy=True
    )

    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        if self.is_multi_variant and self.product_tmpl_id:
            bom = self.env['mrp.bom'].search([('product_tmpl_id', '=', self.product_tmpl_id.id)], limit=1)
            if bom:
                self.bom_id = bom.id
            if self.product_tmpl_id.product_variant_ids:
                self.product_id = self.product_tmpl_id.product_variant_ids[0].id

    @api.onchange('is_multi_variant')
    def _onchange_is_multi_variant(self):
        if not self.is_multi_variant:
            self.variant_line_ids = [(5, 0, 0)]
        elif self.product_id:
            self.product_tmpl_id = self.product_id.product_tmpl_id

    @api.onchange('variant_line_ids', 'is_multi_variant')
    def _onchange_variant_line_ids(self):
        if self.is_multi_variant and self.variant_line_ids:
            total = sum(self.variant_line_ids.mapped('product_qty'))
            self.product_qty = total if total > 0 else 1.0
            first_variant = self.variant_line_ids[0].product_id
            if first_variant:
                self.product_id = first_variant.id
                self.product_tmpl_id = first_variant.product_tmpl_id.id
                if not self.bom_id:
                    bom = self.env['mrp.bom'].search([('product_tmpl_id', '=', first_variant.product_tmpl_id.id)],
                                                     limit=1)
                    if bom:
                        self.bom_id = bom.id

    @api.depends('is_multi_variant', 'variant_line_ids.product_qty')
    def _compute_product_qty(self):
        super()._compute_product_qty()
        for rec in self:
            if rec.is_multi_variant and rec.variant_line_ids:
                total = sum(rec.variant_line_ids.mapped('product_qty'))
                rec.product_qty = total if total > 0 else rec.product_qty

    def _get_moves_raw_values(self):
        moves = []
        for production in self:
            if production.is_multi_variant and production.variant_line_ids and production.bom_id:
                component_totals = {}
                for line in production.variant_line_ids:
                    factor = line.product_uom_id._compute_quantity(line.product_qty,
                                                                   production.bom_id.product_uom_id) / production.bom_id.product_qty
                    boms, lines = production.bom_id.explode(line.product_id, factor,
                                                            picking_type=production.bom_id.picking_type_id)

                    for bom_line, line_data in lines:
                        if bom_line.child_bom_id and bom_line.child_bom_id.type == 'phantom':
                            continue

                        comp_product = bom_line.product_id
                        comp_uom = bom_line.product_uom_id
                        comp_qty = line_data['qty']
                        op_id = bom_line.operation_id.id if bom_line.operation_id else False

                        key = (comp_product.id, comp_uom.id, op_id)
                        if key not in component_totals:
                            component_totals[key] = {'qty': 0.0, 'bom_line_id': bom_line.id}
                        component_totals[key]['qty'] += comp_qty

                for (comp_prod_id, comp_uom_id, op_id), comp_info in component_totals.items():
                    total_qty = comp_info['qty']
                    bom_line_id = comp_info['bom_line_id']
                    comp_product = self.env['product.product'].browse(comp_prod_id)
                    move_val = {
                        'name': production.name,
                        'product_id': comp_prod_id,
                        'product_uom_qty': total_qty,
                        'product_uom': comp_uom_id,
                        'location_id': production.location_src_id.id,
                        'location_dest_id': comp_product.with_company(
                            production.company_id).property_stock_production.id,
                        'raw_material_production_id': production.id,
                        'company_id': production.company_id.id,
                        'operation_id': op_id,
                        'bom_line_id': bom_line_id,
                        'price_unit': comp_product.standard_price,
                        'procure_method': 'make_to_stock',
                        'origin': production.name,
                        'warehouse_id': production.location_src_id.warehouse_id.id,
                    }
                    moves.append(move_val)
            else:
                moves.extend(super(MrpProduction, production)._get_moves_raw_values())
        return moves

    def _get_moves_finished_values(self):
        moves = []
        for production in self:
            if production.is_multi_variant:
                for line in production.variant_line_ids:
                    move_val = {
                        'name': line.product_id.display_name,
                        'product_id': line.product_id.id,
                        'product_uom_qty': line.product_qty,
                        'product_uom': line.product_uom_id.id,
                        'location_id': line.product_id.with_company(production.company_id).property_stock_production.id,
                        'location_dest_id': production.location_dest_id.id,
                        'production_id': production.id,
                        'company_id': production.company_id.id,
                        'operation_id': False,
                        'price_unit': line.product_id.standard_price,
                        'origin': production.name,
                        'warehouse_id': production.location_dest_id.warehouse_id.id,
                    }
                    moves.append(move_val)
            else:
                moves.extend(super(MrpProduction, production)._get_moves_finished_values())
        return moves

    def action_confirm(self):
        res = super().action_confirm()
        for rec in self:
            if rec.is_multi_variant and rec.variant_line_ids:
                expected_variant_ids = set(rec.variant_line_ids.mapped('product_id.id'))
                extra_finished = rec.move_finished_ids.filtered(lambda m: m.product_id.id not in expected_variant_ids)
                if extra_finished:
                    extra_finished.unlink()
                for move in rec.move_finished_ids:
                    v_line = rec.variant_line_ids.filtered(lambda l: l.product_id.id == move.product_id.id)
                    if v_line:
                        move.product_uom_qty = v_line[0].product_qty
            if rec.is_multi_variant and rec.variant_line_ids and rec.workorder_ids:
                for wo in rec.workorder_ids:
                    wo.variant_line_ids.unlink()
                    for v_line in rec.variant_line_ids:
                        self.env['mrp.workorder.variant.line'].create({
                            'workorder_id': wo.id,
                            'product_id': v_line.product_id.id,
                            'planned_qty': v_line.product_qty,
                            'qty_produced': 0.0,
                        })
            # shortage-based purchase logic
            purchase_lines = []
            picking_moves = rec.picking_ids.mapped('move_ids')
            for move in rec.move_raw_ids:
                product = move.product_id
                product_picking_moves = picking_moves.filtered(lambda m: m.product_id.id == product.id)
                if product_picking_moves:
                    required = sum(m.product_uom_qty for m in product_picking_moves)
                    reserved = sum(m.quantity for m in product_picking_moves)
                else:
                    required = move.product_uom_qty
                    reserved = move.quantity
                balance = required - reserved
                if balance > 0:
                    purchase_lines.append((0, 0, {
                        'product_id': product.id,
                        'name': product.display_name,
                        'product_qty': balance,
                        'product_uom': move.product_uom.id,
                        'price_unit': product.standard_price,
                        'date_planned': fields.Datetime.now(),
                    }))
            if purchase_lines:
                vendor = self.env['res.partner'].search(
                    [('supplier_rank', '>', 0)],
                    limit=1
                )
                if not vendor:
                    raise UserError("No Vendor Found")
                self.env['purchase.order'].create({
                    'partner_id': vendor.id,
                    'origin': rec.name,
                    'order_line': purchase_lines,
                })
        return res

    def button_mark_done(self):
        for rec in self:
            if rec.is_multi_variant and rec.variant_line_ids:
                # Find the QC workorder
                qc_wos = rec.workorder_ids.filtered(
                    lambda w: 'qc' in (w.name or '').lower() or 'quality' in (w.name or '').lower() or
                               'qc' in (w.workcenter_id.name or '').lower() or 'quality' in (w.workcenter_id.name or '').lower()
                )
                qc_wo = qc_wos[0] if qc_wos else False
                
                # Get the done QC batches
                done_batches = rec.env['textile.quality'].search([
                    ('production_id', '=', rec.id),
                    ('checkpoint', '=', 'final'),
                    ('state', '=', 'done')
                ]) if 'textile.quality' in rec.env.registry else False
                
                # Calculate produced qty for each variant
                produced_qty_map = {}
                backorder_needed = False
                for v_line in rec.variant_line_ids:
                    if qc_wo and done_batches:
                        passed = sum(done_batches.mapped('variant_line_ids').filtered(lambda l: l.product_id.id == v_line.product_id.id).mapped('passed_qty'))
                        produced = passed
                    else:
                        wos = sorted(rec.workorder_ids, key=lambda w: (w.sequence, w.id))
                        last_wo = wos[-1] if wos else False
                        if last_wo:
                            wo_v_line = last_wo.variant_line_ids.filtered(lambda l: l.product_id.id == v_line.product_id.id)
                            produced = wo_v_line[0].qty_produced if wo_v_line else v_line.qty_produced or v_line.product_qty
                        else:
                            produced = v_line.qty_produced or v_line.product_qty
                            
                    produced_qty_map[v_line.product_id.id] = produced
                    if produced < v_line.product_qty:
                        backorder_needed = True

                if backorder_needed:
                    # Duplicate current MO to create the backorder MO in draft state
                    backorder_vals = rec.copy_data({
                        'state': 'draft',
                        'backorder_id': rec.id,
                        'origin': rec.name,
                    })[0]
                    backorder_mo = rec.create(backorder_vals)
                    
                    # Update variant lines on backorder MO
                    for bo_v_line in backorder_mo.variant_line_ids:
                        parent_produced = produced_qty_map.get(bo_v_line.product_id.id, 0.0)
                        parent_v_line = rec.variant_line_ids.filtered(lambda l: l.product_id.id == bo_v_line.product_id.id)
                        parent_planned = parent_v_line[0].product_qty if parent_v_line else 0.0
                        
                        bo_qty = max(0.0, parent_planned - parent_produced)
                        if bo_qty > 0:
                            bo_v_line.product_qty = bo_qty
                        else:
                            bo_v_line.unlink()
                            
                    # Remove variant lines from backorder that have 0 quantity
                    backorder_mo.variant_line_ids = backorder_mo.variant_line_ids.filtered(lambda l: l.product_qty > 0)
                    backorder_mo._compute_product_qty()
                    
                    # Update parent MO variant lines to the actual produced quantity
                    for parent_v_line in rec.variant_line_ids:
                        prod_qty = produced_qty_map.get(parent_v_line.product_id.id, 0.0)
                        if prod_qty > 0:
                            parent_v_line.product_qty = prod_qty
                        else:
                            parent_v_line.unlink()
                    rec._compute_product_qty()
                    
                    # Re-confirm the backorder MO to generate its workorders and moves!
                    backorder_mo.action_confirm()
                    
                    # Log in message thread
                    rec.message_post(body=_(
                        "Backorder Manufacturing Order %s has been created for the remaining scrapped/failed quantities."
                    ) % backorder_mo.name)
                
                # Now set the finished moves to the correct produced quantity
                for move in rec.move_finished_ids:
                    prod = produced_qty_map.get(move.product_id.id, 0.0)
                    move.quantity = prod
                    move.picked = True
                    
                # Consume raw materials: if there is done scrap, consume the full planned quantity on the parent MO.
                has_done_scrap = bool(rec.scrap_ids.filtered(lambda s: s.state == 'done'))
                for move in rec.move_raw_ids:
                    if has_done_scrap:
                        move.quantity = move.product_uom_qty
                        move.picked = True
                    elif not move.picked:
                        move.quantity = move.product_uom_qty
                        move.picked = True
                        
                (rec.move_raw_ids | rec.move_finished_ids)._action_done()
                rec.write({'state': 'done', 'date_finished': fields.Datetime.now()})
                return True
            else:
                # Single-product Flow: if there is done scrap, consume the full planned quantity on the parent MO.
                if rec.scrap_ids.filtered(lambda s: s.state == 'done'):
                    for move in rec.move_raw_ids:
                        move.quantity = move.product_uom_qty
                        move.picked = True
        return super().button_mark_done()

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
                    rec.fabric_cost +
                    rec.thread_cost +
                    rec.accessories_cost +
                    rec.labor_cost +
                    rec.machine_cost +
                    rec.packaging_cost +
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

    @api.depends('state', 'product_qty', 'is_multi_variant', 'variant_line_ids.product_qty', 'workorder_ids.state',
                 'workorder_ids.qty_produced', 'workorder_ids.variant_line_ids.qty_produced', 'scrap_ids.state',
                 'scrap_ids.scrap_qty')
    def _compute_wip_dashboard(self):
        for rec in self:
            html = '<div style="background: #f8fafc; border-radius: 12px; padding: 20px; border: 1px solid #e2e8f0; font-family: sans-serif;">'
            html += '  <h4 style="margin: 0 0 15px 0; color: #1e293b; font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 8px;">'
            html += '    <span style="display:inline-block; width:8px; height:8px; background:#3b82f6; border-radius:50%;"></span> Live WIP Stage Tracking'
            if rec.is_multi_variant:
                html += ' <span style="font-size:12px; background:#dbeafe; color:#1e40af; padding:2px 8px; border-radius:12px; font-weight:500;">Multi-Variant Batch</span>'
            html += '  </h4>'

            html += '  <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 15px;">'

            # Find all workorders, sort by sequence and ID

            wos = sorted(rec.workorder_ids, key=lambda w: (w.sequence, w.id))

            if not wos:
                html += '  <div style="color: #64748b; font-size: 14px; font-style: italic;">No operations/routing configured on this Manufacturing Order.</div>'
            elif rec.is_multi_variant and rec.variant_line_ids:
                # Build Variant-wise WIP Matrix Table
                html += '  <div style="overflow-x: auto;">'
                html += '    <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 13px;">'
                html += '      <thead>'
                html += '        <tr style="background: #f1f5f9; color: #475569; border-bottom: 2px solid #e2e8f0;">'
                html += '          <th style="padding: 10px 12px;">Operation Stage</th>'

                variants = rec.variant_line_ids.mapped('product_id')
                for v in variants:
                    # Extract size / variant name snippet
                    v_name = v.product_template_attribute_value_ids.mapped('name')
                    v_label = "/".join(v_name) if v_name else v.display_name
                    html += f'          <th style="padding: 10px 12px; text-align: center;">{v_label}</th>'
                html += '        </tr>'
                html += '      </thead>'
                html += '      <tbody>'

                for idx, wo in enumerate(wos):
                    wc_name = wo.workcenter_id.name if wo.workcenter_id else ''
                    status_badge = ''
                    if wo.state == 'done':
                        status_badge = ' <span style="font-size:10px; background:#dcfce7; color:#15803d; padding:2px 6px; border-radius:4px; font-weight:600;">Done</span>'
                    elif wo.state == 'progress':
                        status_badge = ' <span style="font-size:10px; background:#fef3c7; color:#b45309; padding:2px 6px; border-radius:4px; font-weight:600;">In Progress</span>'
                    elif wo.state == 'ready':
                        status_badge = ' <span style="font-size:10px; background:#e0f2fe; color:#0369a1; padding:2px 6px; border-radius:4px; font-weight:600;">Ready</span>'

                    html += f'        <tr style="border-bottom: 1px solid #e2e8f0;">'
                    html += f'          <td style="padding: 10px 12px; font-weight: 600; color: #1e293b;">{wo.name.title()}{status_badge}<br/><span style="font-size:11px; color:#94a3b8; font-weight:normal;">{wc_name}</span></td>'

                    for v in variants:
                        v_line = wo.variant_line_ids.filtered(lambda l: l.product_id.id == v.id)
                        qty_done = v_line[0].qty_produced if v_line else 0.0
                        
                        is_qc = 'qc' in (wo.name or '').lower() or 'quality' in (wo.name or '').lower() or \
                                'qc' in (wo.workcenter_id.name or '').lower() or 'quality' in (wo.workcenter_id.name or '').lower()
                                
                        if is_qc:
                            done_batches = rec.env['textile.quality'].search([
                                ('production_id', '=', rec.id),
                                ('checkpoint', '=', 'final'),
                                ('state', '=', 'done')
                            ])
                            if done_batches:
                                qty_done = sum(done_batches.mapped('variant_line_ids').filtered(lambda l: l.product_id.id == v.id).mapped('passed_qty'))
                            else:
                                qty_done = 0.0
                        else:
                            # Capping check for any stage after QC (such as Packing)
                            qc_wos = rec.workorder_ids.filtered(
                                lambda w: 'qc' in (w.name or '').lower() or 'quality' in (w.name or '').lower() or
                                           'qc' in (w.workcenter_id.name or '').lower() or 'quality' in (w.workcenter_id.name or '').lower()
                            )
                            if qc_wos:
                                qc_wo = qc_wos[0]
                                if wo.sequence >= qc_wo.sequence:
                                    done_batches = rec.env['textile.quality'].search([
                                        ('production_id', '=', rec.id),
                                        ('checkpoint', '=', 'final'),
                                        ('state', '=', 'done')
                                    ])
                                    qc_passed = sum(done_batches.mapped('variant_line_ids').filtered(lambda l: l.product_id.id == v.id).mapped('passed_qty'))
                                    if wo.state == 'done':
                                        qty_done = min(qty_done or qc_passed, qc_passed)
                                    else:
                                        qty_done = min(qty_done, qc_passed)

                        if wo.state == 'done' and not is_qc and qty_done == 0:
                            qc_wos = rec.workorder_ids.filtered(
                                lambda w: 'qc' in (w.name or '').lower() or 'quality' in (w.name or '').lower() or
                                           'qc' in (w.workcenter_id.name or '').lower() or 'quality' in (w.workcenter_id.name or '').lower()
                            )
                            qc_passed = 0.0
                            if qc_wos:
                                done_batches = rec.env['textile.quality'].search([
                                    ('production_id', '=', rec.id),
                                    ('checkpoint', '=', 'final'),
                                    ('state', '=', 'done')
                                ])
                                qc_passed = sum(done_batches.mapped('variant_line_ids').filtered(lambda l: l.product_id.id == v.id).mapped('passed_qty'))
                            
                            if not qc_wos or qc_passed > 0:
                                mo_v = rec.variant_line_ids.filtered(lambda l: l.product_id.id == v.id)
                                qty_done = min(mo_v[0].product_qty if mo_v else 0.0, qc_passed) if qc_wos else (mo_v[0].product_qty if mo_v else 0.0)

                        is_act = qty_done > 0
                        color = '#15803d' if wo.state == 'done' else (
                            '#b45309' if wo.state == 'progress' else '#94a3b8')
                        bold = 'font-weight:700;' if is_act else ''
                        html += f'          <td style="padding: 10px 12px; text-align: center; color:{color}; {bold}">{int(qty_done)} pcs</td>'
                    html += '        </tr>'

                html += '      </tbody>'
                html += '    </table>'
                html += '  </div>'
            else:
                # Standard Single-Variant WIP Tracking Flow
                html += '  <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 15px;">'
                scrap_by_wo_id = {}
                done_scraps = rec.scrap_ids.filtered(lambda s: s.state == 'done')
                for scrap in done_scraps:
                    wo_id = scrap.workorder_id.id
                    if not wo_id:
                        # Fallback 1: match by WIP location
                        matching_wo = rec.workorder_ids.filtered(
                            lambda w: w.workcenter_id.wip_location_id.id == scrap.location_id.id
                        )
                        if matching_wo:
                            wo_id = matching_wo[0].id
                        else:
                            # Fallback 2: if scrap product is the MO finished product, default to QC workorder
                            if scrap.product_id.id == rec.product_id.id:
                                qc_wo = rec.workorder_ids.filtered(
                                    lambda w: 'quality' in w.workcenter_id.name.lower()
                                              or 'qc' in w.workcenter_id.name.lower()
                                )
                                if qc_wo:
                                    wo_id = qc_wo[0].id

                        # Fallback 3: default to first workorder
                        if not wo_id and rec.workorder_ids:
                            wo_id = wos[0].id

                        if wo_id:
                            scrap_by_wo_id[wo_id] = (
                                    scrap_by_wo_id.get(wo_id, 0.0) + scrap.scrap_qty
                            )
                steps = []

                for index, wo in enumerate(wos):
                    wc = wo.workcenter_id

                    # Compute dynamic quantity for this stage
                    if rec.state == 'draft':
                        qty = 0.0
                    elif index == 0:
                        entered = rec.product_qty
                        left = wo.qty_produced
                        scrapped = scrap_by_wo_id.get(wo.id, 0.0)
                        qty = max(0.0, entered - left - scrapped)
                    else:
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
        res = super(MrpProduction, self)._split_productions(
            amounts=amounts,
            cancel_remaining_qty=cancel_remaining_qty,
            set_consumed_qty=set_consumed_qty
        )

        # Identify backorders created during this split
        backorders = res - self

        for bo in backorders:
            bo.backorder_id = self.id
            bo.origin = self.name

            # Inherit the raw_wip_transferred state to prevent double-transfer of components
            bo.raw_wip_transferred = self.raw_wip_transferred

            # Force all cancelled work orders to start fresh for the backorder quantity
            for wo in bo.workorder_ids:
                if wo.state == 'cancel':
                    wo.state = 'pending'
                    wo.qty_producing = bo.product_qty

            if (
                bo.warehouse_id
                and bo.warehouse_id.pbm_type_id
                and bo.location_src_id != bo.warehouse_id.lot_stock_id
            ):
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