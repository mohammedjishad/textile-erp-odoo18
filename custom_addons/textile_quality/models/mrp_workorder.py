# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    qc_batch_count = fields.Integer(compute='_compute_qc_batch_count')
    is_qc_stage = fields.Boolean(compute='_compute_is_qc_stage')

    def _compute_qc_batch_count(self):
        for rec in self:
            rec.qc_batch_count = self.env['textile.quality'].search_count([('workorder_id', '=', rec.id)])

    def _compute_is_qc_stage(self):
        qc_keywords = ['qc', 'quality', 'qualty', 'qulity']
        for rec in self:
            rec.is_qc_stage = (
                any(kw in (rec.name or '').lower() for kw in qc_keywords) or
                any(kw in (rec.workcenter_id.name or '').lower() for kw in qc_keywords) or
                any(kw in (rec.workcenter_id.code or '').lower() for kw in qc_keywords)
            )

    def action_qc_batches(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Quality Checks'),
            'res_model': 'textile.quality',
            'view_mode': 'list,form',
            'domain': [('workorder_id', '=', self.id)],
            'context': {'default_workorder_id': self.id, 'default_production_id': self.production_id.id},
        }

    def action_return_rework(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Return Repaired Products'),
            'res_model': 'textile.qc.rework.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_workorder_id': self.id},
        }

    def button_finish(self):
        for record in self:
            if record.is_qc_stage:
                # 1. Verify no draft QC Batches exist
                draft_batches = self.env['textile.quality'].search([
                    ('production_id', '=', record.production_id.id),
                    ('checkpoint', '=', 'final'),
                    ('state', '=', 'draft')
                ])
                if draft_batches:
                    raise UserError(_(
                        "Cannot finish Quality Control stage. Please validate all Draft QC Batches first."
                    ))

                # 2. Verify all transferred stock has been inspected
                qc_location = record.workcenter_id.wip_location_id
                if not qc_location:
                    qc_location = self.env['stock.location'].search([
                        ('complete_name', 'ilike', 'Quality Check')
                    ], limit=1)

                if qc_location:
                    moves = self.env['stock.move'].search([
                        ('origin', '=', record.production_id.name),
                        ('location_dest_id', '=', qc_location.id),
                        ('state', '=', 'done')
                    ])
                    total_transferred = sum(moves.mapped('quantity'))
                    
                    done_batches = self.env['textile.quality'].search([
                        ('production_id', '=', record.production_id.id),
                        ('checkpoint', '=', 'final'),
                        ('state', '=', 'done')
                    ])
                    total_inspected = sum(done_batches.mapped('received_qty'))
                    
                    if round(total_transferred, 4) > round(total_inspected, 4):
                        raise UserError(_(
                            "Cannot finish Quality Control stage. There is still uninspected stock in the QC Location (Transferred: %s, Inspected: %s)."
                        ) % (total_transferred, total_inspected))
                    
                    if record.production_id.is_multi_variant and record.variant_line_ids:
                        for v_line in record.variant_line_ids:
                            passed = sum(done_batches.mapped('variant_line_ids').filtered(lambda l: l.product_id.id == v_line.product_id.id).mapped('passed_qty'))
                            v_line.qty_produced = passed
                            v_line.qty_transferred = passed
                    else:
                        passed = sum(done_batches.mapped('passed_qty'))
                        record.qty_produced = passed
                        record.qty_transferred = passed
            else:
                # Post-QC stage validation/capping
                qc_wos = record.production_id.workorder_ids.filtered(
                    lambda w: 'qc' in (w.name or '').lower() or 'quality' in (w.name or '').lower() or
                               'qc' in (w.workcenter_id.name or '').lower() or 'quality' in (w.workcenter_id.name or '').lower()
                )
                if qc_wos:
                    qc_wo = qc_wos[0]
                    # If this workorder sequence is equal or after QC sequence
                    if record.sequence >= qc_wo.sequence:
                        done_batches = self.env['textile.quality'].search([
                            ('production_id', '=', record.production_id.id),
                            ('checkpoint', '=', 'final'),
                            ('state', '=', 'done')
                        ])
                        if done_batches:
                            if record.production_id.is_multi_variant and record.variant_line_ids:
                                for v_line in record.variant_line_ids:
                                    passed = sum(done_batches.mapped('variant_line_ids').filtered(lambda l: l.product_id.id == v_line.product_id.id).mapped('passed_qty'))
                                    if v_line.qty_produced == 0 or v_line.qty_produced > passed:
                                        v_line.qty_produced = passed
                                record.qty_produced = sum(record.variant_line_ids.mapped('qty_produced'))
                                record.qty_producing = record.qty_produced
                            else:
                                passed = sum(done_batches.mapped('passed_qty'))
                                if record.qty_produced == 0 or record.qty_produced > passed:
                                    record.qty_produced = passed
                    
        return super(MrpWorkorder, self).button_finish()

    def write(self, vals):
        res = super(MrpWorkorder, self).write(vals)
        if 'state' in vals:
            for record in self:
                record._handle_quality_inspection_creation(vals['state'])
        return res

    def _handle_quality_inspection_creation(self, state):
        self.ensure_one()
        if not self.production_id:
            return

        if self.is_qc_stage and state in ('ready', 'progress'):
            self._create_draft_inspection('final')

    def _create_draft_inspection(self, checkpoint):
        self.ensure_one()
        qc_location = self.workcenter_id.wip_location_id
        if not qc_location:
            qc_location = self.env['stock.location'].search([
                ('complete_name', 'ilike', 'Quality Check')
            ], limit=1)
            
        if qc_location:
            moves = self.env['stock.move'].search([
                ('origin', '=', self.production_id.name),
                ('location_dest_id', '=', qc_location.id),
                ('state', '=', 'done')
            ])
            total_transferred = sum(moves.mapped('quantity'))
            
            done_batches = self.env['textile.quality'].search([
                ('production_id', '=', self.production_id.id),
                ('checkpoint', '=', checkpoint),
                ('state', '=', 'done')
            ])
            total_inspected = sum(done_batches.mapped('received_qty'))
            
            pending = total_transferred - total_inspected
            if pending > 0:
                draft_batch = self.env['textile.quality'].search([
                    ('production_id', '=', self.production_id.id),
                    ('checkpoint', '=', checkpoint),
                    ('state', '=', 'draft')
                ], limit=1)
                
                if not draft_batch:
                    batch = self.env['textile.quality'].create({
                        'production_id': self.production_id.id,
                        'workorder_id': self.id,
                        'checkpoint': checkpoint,
                        'state': 'draft',
                        'received_qty': 0.0,
                        'passed_qty': 0.0,
                        'failed_qty': 0.0,
                        'rework_qty': 0.0,
                        'scrap_qty': 0.0,
                    })
                    if self.production_id.is_multi_variant:
                        for mv_line in self.production_id.variant_line_ids:
                            var_moves = moves.filtered(lambda m: m.product_id == mv_line.product_id)
                            var_transferred = sum(var_moves.mapped('quantity'))
                            var_inspected = sum(done_batches.mapped('variant_line_ids').filtered(lambda l: l.product_id == mv_line.product_id).mapped('received_qty'))
                            var_pending = var_transferred - var_inspected
                            if var_pending > 0:
                                self.env['textile.quality.variant.line'].create({
                                    'quality_id': batch.id,
                                    'product_id': mv_line.product_id.id,
                                    'received_qty': var_pending,
                                    'passed_qty': var_pending,
                                })
                    else:
                        batch.received_qty = pending
                        batch.passed_qty = pending
