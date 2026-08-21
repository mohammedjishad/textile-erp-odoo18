# -*- coding: utf-8 -*-
from odoo import models, api, _
from odoo.exceptions import UserError

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        if self.picking_type_code == 'outgoing':
            group_ids = self.move_ids.mapped('group_id')
            
            domain = []
            if group_ids:
                domain.append(('procurement_group_id', 'in', group_ids.ids))
            if self.origin:
                domain.append(('origin', '=', self.origin))
                
            if domain:
                if len(domain) > 1:
                    search_domain = ['|'] + domain
                else:
                    search_domain = domain
                    
                linked_mos = self.env['mrp.production'].search(search_domain).filtered(lambda m: m.state != 'cancel')
                
                for mo in linked_mos:
                    if mo.show_quality_check:
                        inspections = self.env['textile.quality'].search([
                            ('production_id', '=', mo.id)
                        ])
                        
                        if not inspections:
                            raise UserError(_(
                                "Cannot validate delivery. Quality inspections have not been recorded for Manufacturing Order %s."
                            ) % mo.name)
                        
                        if any(ins.state != 'done' for ins in inspections):
                            raise UserError(_(
                                "Cannot validate delivery. There are still pending/unvalidated Quality Check batches for Manufacturing Order %s."
                            ) % mo.name)
                        
                        # Verify Rework and QC locations are empty
                        rework_loc = self.env['textile.quality']._get_rework_location()
                        qc_keyword_wcs = mo.workorder_ids.filtered(
                            lambda wo: 'qc' in (wo.name or '').lower() or 'quality' in (wo.name or '').lower() or
                                       'qc' in (wo.workcenter_id.name or '').lower() or 'quality' in (wo.workcenter_id.name or '').lower()
                        )
                        qc_locs = qc_keyword_wcs.mapped('workcenter_id.wip_location_id')
                        if not qc_locs:
                            qc_locs = self.env['stock.location'].search([
                                ('complete_name', 'ilike', 'Quality Check')
                            ])
                        
                        target_locations = rework_loc + qc_locs
                        
                        quants = self.env['stock.quant'].search([
                            ('location_id', 'in', target_locations.ids),
                            ('quantity', '>', 0)
                        ])
                        
                        mo_products = mo.move_finished_ids.mapped('product_id')
                        if not mo_products:
                            mo_products = mo.product_id
                        mo_quants = quants.filtered(lambda q: q.product_id in mo_products)
                        
                        if mo_quants:
                            raise UserError(_(
                                "Cannot validate delivery. There is still stock sitting in the Quality Check / Rework WIP locations for Manufacturing Order %s. Please resolve all defects."
                            ) % mo.name)
                            
        return super(StockPicking, self).button_validate()

    def _action_done(self):
        res = super(StockPicking, self)._action_done()
        
        # Automatically assign/reserve lot numbers on linked MO after validating the component transfer
        for picking in self:
            if picking.state == 'done' and picking.picking_type_id.code == 'internal' and picking.origin:
                self.env.flush_all()
                self.env.invalidate_all()
                linked_mo = self.env['mrp.production'].search([
                    ('name', '=', picking.origin)
                ], limit=1)
                if linked_mo and linked_mo.state not in ('done', 'cancel'):
                    for move in picking.move_ids:
                        mo_moves = linked_mo.move_raw_ids.filtered(lambda m: m.product_id == move.product_id)
                        for mo_move in mo_moves:
                            pick_lots = move.move_line_ids.filtered(lambda l: l.state == 'done' and l.lot_id)
                            if pick_lots:
                                mo_move.move_line_ids.filtered(lambda l: l.state != 'done').unlink()
                                for pl in pick_lots:
                                    self.env['stock.move.line'].create({
                                        'move_id': mo_move.id,
                                        'product_id': mo_move.product_id.id,
                                        'product_uom_id': mo_move.product_uom.id,
                                        'quantity': pl.quantity,
                                        'location_id': mo_move.location_id.id,
                                        'location_dest_id': mo_move.location_dest_id.id,
                                        'lot_id': pl.lot_id.id,
                                        'company_id': mo_move.company_id.id,
                                    })
                                    
        return res
