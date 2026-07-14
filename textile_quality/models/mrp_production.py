# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    quality_check_count = fields.Integer(compute='_compute_quality_check_count')
    show_quality_check = fields.Boolean(compute='_compute_show_quality_check')

    def _compute_quality_check_count(self):
        for rec in self:
            rec.quality_check_count = self.env['textile.quality'].search_count([('production_id', '=', rec.id)])

    @api.depends('state', 'workorder_ids.state', 'workorder_ids.name', 'workorder_ids.workcenter_id.name', 'workorder_ids.workcenter_id.code')
    def _compute_show_quality_check(self):
        qc_keywords = ['qc', 'quality', 'qualty', 'qulity']
        for rec in self:
            if not rec.workorder_ids:
                rec.show_quality_check = rec.state not in ('draft', 'cancel')
            else:
                qc_wos = rec.workorder_ids.filtered(
                    lambda wo: any(kw in (wo.name or '').lower() for kw in qc_keywords) or
                               any(kw in (wo.workcenter_id.name or '').lower() for kw in qc_keywords) or
                               any(kw in (wo.workcenter_id.code or '').lower() for kw in qc_keywords)
                )
                active_qc = qc_wos.filtered(lambda wo: wo.state in ('ready', 'progress', 'done'))
                rec.show_quality_check = bool(active_qc)

    def action_quality_control(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Quality Inspections'),
            'res_model': 'textile.quality',
            'view_mode': 'list,form',
            'domain': [('production_id', '=', self.id)],
            'context': {'default_production_id': self.id},
        }

    def button_mark_done(self):
        for rec in self:
            final_inspection = self.env['textile.quality'].search([
                ('production_id', '=', rec.id),
                ('checkpoint', '=', 'final'),
                ('state', '=', 'done')
            ], limit=1, order='id desc')
            
            if not final_inspection or final_inspection.status != 'pass':
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Quality Control Required'),
                        'message': _('Quantities produced! Please complete a Final Quality Inspection to finish the order.'),
                        'type': 'warning',
                        'sticky': True,
                    }
                }
                
        return super(MrpProduction, self).button_mark_done()
