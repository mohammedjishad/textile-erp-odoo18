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

    def action_return_rework(self):
        self.ensure_one()
        qc_workorder = self.workorder_ids.filtered(
            lambda wo: 'qc' in (wo.name or '').lower() or 'quality' in (wo.name or '').lower() or
                       'qc' in (wo.workcenter_id.name or '').lower() or 'quality' in (wo.workcenter_id.name or '').lower()
        )
        if not qc_workorder:
            raise UserError(_("No Quality Check Work Order found for this Manufacturing Order."))
            
        return {
            'type': 'ir.actions.act_window',
            'name': _('Return Repaired Products'),
            'res_model': 'textile.qc.rework.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_workorder_id': qc_workorder[0].id},
        }


    def button_mark_done(self):
        for rec in self:
            if rec.show_quality_check:
                # 1. Verify there are inspections
                inspections = self.env['textile.quality'].search([
                    ('production_id', '=', rec.id)
                ])
                if not inspections:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Quality Control Required'),
                            'message': _('Please perform the required Quality Inspections before completing the manufacturing order.'),
                            'type': 'warning',
                            'sticky': True,
                        }
                    }
                
                # 2. Verify all are done
                if any(ins.state != 'done' for ins in inspections):
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Quality Control Pending'),
                            'message': _('Please validate all Quality Check batches before completing the manufacturing order.'),
                            'type': 'warning',
                            'sticky': True,
                        }
                    }

                # 3. Verify Rework has been fully returned for this MO
                rework_loc = self.env['textile.quality']._get_rework_location()
                total_rework_logged = sum(inspections.mapped('variant_line_ids.rework_qty'))
                
                returned_moves = self.env['stock.move'].search([
                    ('origin', '=', rec.name),
                    ('location_id', '=', rework_loc.id),
                    ('state', '=', 'done')
                ])
                total_rework_returned = sum(returned_moves.mapped('quantity'))
                
                if total_rework_logged > total_rework_returned:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('WIP Inventory Incomplete'),
                            'message': _('There is still outstanding rework for this Manufacturing Order. Please return all rework products before finishing.'),
                            'type': 'warning',
                            'sticky': True,
                        }
                    }
                    
        return super(MrpProduction, self).button_mark_done()
