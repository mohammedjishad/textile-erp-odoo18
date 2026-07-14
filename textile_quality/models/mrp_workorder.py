# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    def button_finish(self):
        qc_keywords = ['qc', 'quality', 'qualty', 'qulity']
        for record in self:
            is_qc = (
                any(kw in (record.name or '').lower() for kw in qc_keywords) or
                any(kw in (record.workcenter_id.name or '').lower() for kw in qc_keywords) or
                any(kw in (record.workcenter_id.code or '').lower() for kw in qc_keywords)
            )
            if is_qc:
                # Check for a passed Quality Inspection for the linked MO
                inspection = self.env['textile.quality'].search([
                    ('production_id', '=', record.production_id.id),
                    ('checkpoint', '=', 'final'),
                    ('state', '=', 'done'),
                    ('status', '=', 'pass')
                ], limit=1)
                
                if not inspection:
                    raise UserError(_(
                        "Quality Check Required!\n\n"
                        "Please perform and pass the Final Quality Inspection for Manufacturing Order %s "
                        "before finishing the Quality Control (QC) stage."
                    ) % record.production_id.name)
                    
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

        name_lower = (self.name or '').lower()
        wc_name_lower = (self.workcenter_id.name or '').lower()
        wc_code_lower = (self.workcenter_id.code or '').lower()

        # Checkpoint: Final Quality Inspection
        qc_keywords = ['qc', 'quality', 'qualty', 'qulity']
        is_qc = (
            any(kw in name_lower for kw in qc_keywords) or
            any(kw in wc_name_lower for kw in qc_keywords) or
            any(kw in wc_code_lower for kw in qc_keywords)
        )
        if is_qc and state in ('ready', 'progress'):
            self._create_draft_inspection('final')

    def _create_draft_inspection(self, checkpoint):
        self.ensure_one()
        existing = self.env['textile.quality'].search([
            ('production_id', '=', self.production_id.id),
            ('checkpoint', '=', checkpoint)
        ], limit=1)
        if not existing:
            self.env['textile.quality'].create({
                'production_id': self.production_id.id,
                'checkpoint': checkpoint,
                'state': 'draft',
            })
