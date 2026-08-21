# -*- coding: utf-8 -*-
import datetime
from odoo import models, fields, api

class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_done(self, **kwargs):
        res = super(StockMove, self)._action_done(**kwargs)
        
        # Look for moves with destination equal to a Quality Check WIP location
        qc_keywords = ['qc', 'quality', 'qualty', 'qulity']
        qc_workcenters = self.env['mrp.workcenter'].search([])
        qc_locations = qc_workcenters.filtered(
            lambda wc: any(kw in (wc.name or '').lower() for kw in qc_keywords) or
                       any(kw in (wc.code or '').lower() for kw in qc_keywords)
        ).mapped('wip_location_id')
        
        if not qc_locations:
            qc_locations = self.env['stock.location'].search([
                ('complete_name', 'ilike', 'Quality Check')
            ])

        for move in self:
            if move.state == 'done' and move.location_dest_id in qc_locations:
                # Find matching MO by origin
                mo = self.env['mrp.production'].search([
                    ('name', '=', move.origin)
                ], limit=1)
                
                if mo:
                    # Find Quality Check workorder
                    qc_wo = mo.workorder_ids.filtered(
                        lambda wo: any(kw in (wo.name or '').lower() for kw in qc_keywords) or
                                   any(kw in (wo.workcenter_id.name or '').lower() for kw in qc_keywords) or
                                   any(kw in (wo.workcenter_id.code or '').lower() for kw in qc_keywords)
                    )
                    qc_wo_id = qc_wo[0].id if qc_wo else False
                    
                    # Find or create a draft QC batch created in the last 1 minute to group multiple moves
                    one_minute_ago = fields.Datetime.now() - datetime.timedelta(minutes=1)
                    draft_batch = self.env['textile.quality'].search([
                        ('production_id', '=', mo.id),
                        ('state', '=', 'draft'),
                        ('checkpoint', '=', 'final'),
                        ('create_date', '>=', one_minute_ago)
                    ], limit=1)
                    
                    if not draft_batch:
                        draft_batch = self.env['textile.quality'].create({
                            'production_id': mo.id,
                            'workorder_id': qc_wo_id,
                            'checkpoint': 'final',
                            'state': 'draft',
                            'received_qty': 0.0,
                            'passed_qty': 0.0,
                            'failed_qty': 0.0,
                            'rework_qty': 0.0,
                            'scrap_qty': 0.0,
                        })
                    
                    # Update quantities
                    if mo.is_multi_variant:
                        v_line = draft_batch.variant_line_ids.filtered(lambda l: l.product_id.id == move.product_id.id)
                        if v_line:
                            v_line.received_qty += move.quantity
                            v_line.passed_qty += move.quantity
                        else:
                            self.env['textile.quality.variant.line'].create({
                                'quality_id': draft_batch.id,
                                'product_id': move.product_id.id,
                                'received_qty': move.quantity,
                                'passed_qty': move.quantity,  # default to passed
                            })
                    else:
                        draft_batch.received_qty += move.quantity
                        draft_batch.passed_qty += move.quantity  # default to passed
                        
        return res
