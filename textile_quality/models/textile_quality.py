# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class TextileQuality(models.Model):
    _name = 'textile.quality'
    _description = 'Textile Quality Inspection'
    _order = 'inspection_date desc, id desc'

    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        required=True,
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
    stitching_check = fields.Boolean(string='Stitching Check Passed', default=False)
    measurement_check = fields.Boolean(string='Measurement Check Passed', default=False)
    finishing_check = fields.Boolean(string='Finishing Check Passed', default=False)
    defect_count = fields.Integer(string='Defect Count', default=0)
    
    inspected_qty = fields.Float(string='Inspected Qty', related='production_id.product_qty', readonly=True)
    failed_qty = fields.Float(string='Failed Qty', default=0.0)
    passed_qty = fields.Float(string='Passed Qty', compute='_compute_passed_qty', store=True)

    @api.onchange('defect_count')
    def _onchange_defect_count(self):
        for rec in self:
            rec.failed_qty = float(rec.defect_count)

    @api.depends('inspected_qty', 'failed_qty')
    def _compute_passed_qty(self):
        for rec in self:
            rec.passed_qty = rec.inspected_qty - rec.failed_qty

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

    @api.depends('state', 'stitching_check', 'measurement_check', 'finishing_check', 'passed_qty')
    def _compute_status(self):
        for rec in self:
            if rec.state == 'draft':
                rec.status = 'pending'
            else:
                if rec.stitching_check and rec.measurement_check and rec.finishing_check and rec.passed_qty > 0:
                    rec.status = 'pass'
                else:
                    rec.status = 'fail'

    @api.model_create_multi
    def create(self, vals_list):
        return super(TextileQuality, self).create(vals_list)

    def write(self, vals):
        return super(TextileQuality, self).write(vals)

    def action_validate(self):
        for rec in self:
            rec.state = 'done'
            
            # Auto-Scrap and Quantity Update Logic
            if rec.failed_qty > 0:
                # 1. Create Scrap from MO production location
                scrap_vals = {
                    'production_id': rec.production_id.id,
                    'product_id': rec.production_id.product_id.id,
                    'scrap_qty': rec.failed_qty,
                    'product_uom_id': rec.production_id.product_uom_id.id,
                    'location_id': rec.production_id.production_location_id.id,
                    'company_id': rec.production_id.company_id.id,
                }
                # Find Quality Check workorder to associate with the scrap
                qc_wo = rec.production_id.workorder_ids.filtered(lambda w: 'quality' in w.workcenter_id.name.lower() or 'qc' in w.workcenter_id.name.lower())
                if qc_wo:
                    scrap_vals['workorder_id'] = qc_wo[0].id
                    
                scrap = self.env['stock.scrap'].create(scrap_vals)
                scrap.action_validate()
                
                # 2. Update MO Quantity to trigger standard Backorder popup
                rec.production_id.qty_producing = rec.passed_qty

            rec._post_to_production()


    def _post_to_production(self):
        self.ensure_one()
        checkpoint_labels = dict(self._fields['checkpoint'].selection)
        checkpoint_label = checkpoint_labels.get(self.checkpoint, self.checkpoint)
        
        if self.status == 'pass':
            body = _("Quality inspection passed at checkpoint: %s. Inspector: %s. Cleared for next stage.") % (
                checkpoint_label, self.inspector_id.name
            )
        else:
            reject_reason_labels = dict(self._fields['reject_reason'].selection or [])
            reject_label = reject_reason_labels.get(self.reject_reason, self.reject_reason or 'None')
            body = _("Quality inspection FAILED at checkpoint: %s. Defects: %s. Reason: %s. Remarks: %s. This order requires review before proceeding.") % (
                checkpoint_label, self.defect_count, reject_label, self.remarks or 'None'
            )
        self.production_id.message_post(body=body)

    _sql_constraints = [
        ('unique_production_checkpoint',
         'UNIQUE(production_id, checkpoint)',
         'An inspection already exists for this MO at this checkpoint.')
    ]
