# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class TextileQuality(models.Model):
    _name = 'textile.quality'
    _description = 'Textile Quality Inspection'
    _order = 'inspection_date desc, id desc'

    name = fields.Char(
        string='QC Batch Number',
        required=True,
        copy=False,
        readonly=True,
        default='New'
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        required=True,
        ondelete='restrict'
    )
    workorder_id = fields.Many2one(
        'mrp.workorder',
        string='Work Order',
        ondelete='restrict'
    )
    inspector_id = fields.Many2one(
        'res.users',
        string='Inspector',
        required=True,
        default=lambda self: self.env.user
    )
    inspection_date = fields.Date(
        string='Inspection Date',
        required=True,
        default=fields.Date.context_today
    )
    checkpoint = fields.Selection([
        ('final', 'Final Quality Inspection'),
    ], string='Checkpoint', required=True, default='final')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
    ], string='State', default='draft', required=True)

    # QUALITY CHECKS
    stitching_check = fields.Boolean(string='Stitching Check Passed', default=True)
    measurement_check = fields.Boolean(string='Measurement Check Passed', default=True)
    finishing_check = fields.Boolean(string='Finishing Check Passed', default=True)


    defect_count = fields.Integer(string='Defect Count', default=0)
    
    # VARIANT MANAGEMENT
    has_variants = fields.Boolean(string='Has Variants', compute='_compute_has_variants', store=True)
    variant_line_ids = fields.One2many(
        'textile.quality.variant.line',
        'quality_id',
        string='Variant Lines',
        copy=True
    )

    # QUANTITIES
    received_qty = fields.Float(string='Received Qty', compute='_compute_qtys', store=True, readonly=False)
    passed_qty = fields.Float(string='Passed Qty', compute='_compute_qtys', store=True, readonly=False)
    failed_qty = fields.Float(string='Failed Qty', compute='_compute_qtys', store=True, readonly=False)
    rework_qty = fields.Float(string='Rework Qty', compute='_compute_qtys', store=True, readonly=False)
    scrap_qty = fields.Float(string='Scrap Qty', compute='_compute_qtys', store=True, readonly=False)

    @api.depends('production_id')
    def _compute_has_variants(self):
        for rec in self:
            rec.has_variants = rec.production_id.is_multi_variant if rec.production_id else False

    @api.depends('has_variants', 'variant_line_ids.received_qty', 'variant_line_ids.passed_qty',
                 'variant_line_ids.failed_qty', 'variant_line_ids.rework_qty', 'variant_line_ids.scrap_qty')
    def _compute_qtys(self):
        for rec in self:
            if rec.has_variants:
                rec.received_qty = sum(rec.variant_line_ids.mapped('received_qty'))
                rec.passed_qty = sum(rec.variant_line_ids.mapped('passed_qty'))
                rec.failed_qty = sum(rec.variant_line_ids.mapped('failed_qty'))
                rec.rework_qty = sum(rec.variant_line_ids.mapped('rework_qty'))
                rec.scrap_qty = sum(rec.variant_line_ids.mapped('scrap_qty'))

    @api.onchange('passed_qty', 'received_qty')
    def _onchange_passed_qty(self):
        for rec in self:
            if not rec.has_variants and rec.received_qty > 0:
                if rec.passed_qty > rec.received_qty:
                    rec.passed_qty = rec.received_qty
                rec.failed_qty = rec.received_qty - rec.passed_qty

    @api.onchange('failed_qty', 'received_qty')
    def _onchange_failed_qty(self):
        for rec in self:
            if not rec.has_variants and rec.received_qty > 0:
                if rec.failed_qty > rec.received_qty:
                    rec.failed_qty = rec.received_qty
                rec.passed_qty = rec.received_qty - rec.failed_qty

    @api.onchange('rework_qty', 'failed_qty')
    def _onchange_rework_qty(self):
        for rec in self:
            if not rec.has_variants and rec.failed_qty > 0:
                if rec.rework_qty > rec.failed_qty:
                    rec.rework_qty = rec.failed_qty
                rec.scrap_qty = rec.failed_qty - rec.rework_qty

    @api.onchange('scrap_qty', 'failed_qty')
    def _onchange_scrap_qty(self):
        for rec in self:
            if not rec.has_variants and rec.failed_qty > 0:
                if rec.scrap_qty > rec.failed_qty:
                    rec.scrap_qty = rec.failed_qty
                rec.rework_qty = rec.failed_qty - rec.scrap_qty

    # REJECT REASON
    reject_reason = fields.Selection([
        ('stitch_defect', 'Stitch Defect'),
        ('fabric_damage', 'Fabric Damage'),
        ('color_mismatch', 'Color Mismatch'),
        ('size_mismatch', 'Size Mismatch'),
        ('missing_accessories', 'Missing Accessories'),
        ('other', 'Other'),
    ], string='Reject Reason')
    remarks = fields.Text(string='Remarks')

    # RESULT (computed)
    status = fields.Selection([
        ('pending', 'Pending'),
        ('pass', 'Pass'),
        ('fail', 'Fail'),
    ], string='Result', compute='_compute_status', store=True, default='pending')

    @api.depends('state', 'stitching_check', 'measurement_check', 'finishing_check', 'passed_qty', 'failed_qty')
    def _compute_status(self):
        for rec in self:
            if rec.state == 'draft':
                rec.status = 'pending'
            else:
                # Standard Odoo condition: checks passed and no failed units
                if rec.stitching_check and rec.measurement_check and rec.finishing_check and rec.passed_qty > 0 and rec.failed_qty == 0:
                    rec.status = 'pass'
                else:
                    rec.status = 'fail'

    @api.constrains('received_qty', 'passed_qty', 'failed_qty', 'rework_qty', 'scrap_qty', 'variant_line_ids', 'state')
    def _check_quantities(self):
        for rec in self:
            if rec.state != 'done' or rec.received_qty <= 0:
                continue
            if rec.has_variants:


                for line in rec.variant_line_ids:
                    if line.received_qty < 0 or line.passed_qty < 0 or line.failed_qty < 0 or line.rework_qty < 0 or line.scrap_qty < 0:
                        raise UserError(_("Quantities cannot be negative."))
                    if round(line.passed_qty + line.failed_qty, 4) != round(line.received_qty, 4):
                        raise UserError(_("For variant %s, Passed Qty + Failed Qty must equal Received Qty.") % line.product_id.display_name)
                    if round(line.rework_qty + line.scrap_qty, 4) != round(line.failed_qty, 4):
                        raise UserError(_("For variant %s, Rework Qty + Scrap Qty must equal Failed Qty.") % line.product_id.display_name)
            else:
                if rec.received_qty < 0 or rec.passed_qty < 0 or rec.failed_qty < 0 or rec.rework_qty < 0 or rec.scrap_qty < 0:
                    raise UserError(_("Quantities cannot be negative."))
                if round(rec.passed_qty + rec.failed_qty, 4) != round(rec.received_qty, 4):
                    raise UserError(_("Passed Qty + Failed Qty must equal Received Qty."))
                if round(rec.rework_qty + rec.scrap_qty, 4) != round(rec.failed_qty, 4):
                    raise UserError(_("Rework Qty + Scrap Qty must equal Failed Qty."))


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('production_id') and (not vals.get('name') or vals.get('name') == 'New'):
                mo = self.env['mrp.production'].browse(vals['production_id'])
                existing_count = self.env['textile.quality'].search_count([('production_id', '=', mo.id)])
                seq = str(existing_count + 1).zfill(3)
                vals['name'] = f"{mo.name}-QC-{seq}"
        return super(TextileQuality, self).create(vals_list)

    def _get_rework_location(self):
        # Find or create a Rework location under TWH/Stock/Production
        rework_loc = self.env['stock.location'].search([
            ('name', '=ilike', '%rework%'),
            ('usage', '=', 'internal')
        ], limit=1)
        if not rework_loc:
            parent_loc = self.env['stock.location'].search([
                ('complete_name', '=', 'TWH/Stock/Production')
            ], limit=1)
            if not parent_loc:
                parent_loc = self.env['stock.location'].search([
                    ('usage', '=', 'internal')
                ], limit=1)
            rework_loc = self.env['stock.location'].create({
                'name': 'Rework',
                'location_id': parent_loc.id if parent_loc else False,
                'usage': 'internal',
            })
        return rework_loc

    def _create_wip_stock_move(self, product, qty, source_loc, dest_loc, production_id=None):
        if not source_loc or not dest_loc or qty <= 0:
            return False
        
        prod = production_id or self.production_id
        if not prod:
            return False
            
        move = self.env['stock.move'].with_context(
            default_production_id=False,
            default_raw_material_production_id=False,
            default_picking_type_id=False,
        ).create({
            'name': f"QC WIP Move: {prod.name}",
            'product_id': product.id,
            'product_uom': product.uom_id.id,
            'product_uom_qty': qty,
            'location_id': source_loc.id,
            'location_dest_id': dest_loc.id,
            'origin': prod.name,
            'state': 'draft',
        })
        move._action_confirm()
        move._action_assign()
        move.quantity = qty
        move.picked = True
        move._action_done()
        return move


    def _create_scrap_move(self, product, qty, location):
        if qty <= 0 or not location:
            return False
        scrap_vals = {
            'production_id': self.production_id.id,
            'product_id': product.id,
            'scrap_qty': qty,
            'product_uom_id': product.uom_id.id,
            'location_id': location.id,
            'company_id': self.production_id.company_id.id,
        }
        if self.workorder_id:
            scrap_vals['workorder_id'] = self.workorder_id.id
            
        scrap = self.env['stock.scrap'].create(scrap_vals)
        res = scrap.action_validate()
        if isinstance(res, dict) and res.get('res_model') == 'stock.warn.insufficient.qty.scrap':
            ctx = res.get('context', {})
            wizard_fields = self.env['stock.warn.insufficient.qty.scrap']._fields
            create_vals = {
                k.replace('default_', ''): v 
                for k, v in ctx.items() 
                if k.startswith('default_') and k.replace('default_', '') in wizard_fields
            }
            wizard = self.env['stock.warn.insufficient.qty.scrap'].with_context(ctx).create(create_vals)
            wizard.action_done()
        return scrap

    def action_validate(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_("This QC Batch is already validated."))
            
            # Enforce validations
            rec._check_quantities()

            # Find QC Location
            qc_location = rec.workorder_id.workcenter_id.wip_location_id if rec.workorder_id else False
            if not qc_location:
                # fallback: search for Quality Check location in DB
                qc_location = self.env['stock.location'].search([
                    ('complete_name', 'ilike', 'Quality Check')
                ], limit=1)
            
            if not qc_location:
                raise UserError(_("Please configure the WIP Location for the Quality Check Work Center."))

            # Find next stage location (e.g. Packing)
            dest_location = False
            if rec.workorder_id:
                next_wos = rec.production_id.workorder_ids.filtered(
                    lambda w: w.state != 'cancel' and w.sequence > rec.workorder_id.sequence
                ).sorted('sequence')
                next_wo = next_wos[0] if next_wos else False
                dest_location = next_wo.workcenter_id.wip_location_id if next_wo else False

            if not dest_location:
                dest_location = rec.production_id.production_location_id

            # Find Rework location
            rework_location = rec._get_rework_location()

            # Move stock based on results
            if rec.has_variants:
                for line in rec.variant_line_ids:
                    # Passed move to next stage (Packing or Virtual Production)
                    if line.passed_qty > 0:
                        rec._create_wip_stock_move(line.product_id, line.passed_qty, qc_location, dest_location)
                    # Rework move to Rework location
                    if line.rework_qty > 0:
                        rec._create_wip_stock_move(line.product_id, line.rework_qty, qc_location, rework_location)
                    # Scrap move
                    if line.scrap_qty > 0:
                        rec._create_scrap_move(line.product_id, line.scrap_qty, qc_location)
            else:
                # Non-variant case
                product = rec.production_id.product_id
                if rec.passed_qty > 0:
                    rec._create_wip_stock_move(product, rec.passed_qty, qc_location, dest_location)
                if rec.rework_qty > 0:
                    rec._create_wip_stock_move(product, rec.rework_qty, qc_location, rework_location)
                if rec.scrap_qty > 0:
                    rec._create_scrap_move(product, rec.scrap_qty, qc_location)

            # Mark as done
            rec.state = 'done'

            # Update MO qty_producing
            total_passed = sum(self.env['textile.quality'].search([
                ('production_id', '=', rec.production_id.id),
                ('state', '=', 'done')
            ]).mapped('passed_qty'))
            rec.production_id.qty_producing = total_passed
            
            # Post message to MO thread
            rec._post_to_production()

    def _post_to_production(self):
        self.ensure_one()
        checkpoint_labels = dict(self._fields['checkpoint'].selection)
        checkpoint_label = checkpoint_labels.get(self.checkpoint, self.checkpoint)
        
        if self.status == 'pass':
            body = _("Quality Batch %s PASSED. Inspector: %s. Cleared for next stage.") % (
                self.name, self.inspector_id.name
            )
        else:
            reject_reason_labels = dict(self._fields['reject_reason'].selection or [])
            reject_label = reject_reason_labels.get(self.reject_reason, self.reject_reason or 'None')
            body = _("Quality Batch %s FAILED. Passed: %s, Rework: %s, Scrap: %s. Inspector: %s.") % (
                self.name, self.passed_qty, self.rework_qty, self.scrap_qty, self.inspector_id.name
            )
        self.production_id.message_post(body=body)
