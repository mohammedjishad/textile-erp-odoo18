from odoo import models, api, _
from odoo.exceptions import UserError

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        if self.picking_type_code == 'outgoing':
            # Gather linked Manufacturing Orders via origin name or procurement group
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
                    inspections = self.env['textile.quality'].search([
                        ('production_id', '=', mo.id)
                    ])
                    
                    final_inspection = inspections.filtered(lambda i: i.checkpoint == 'final')
                    
                    # Ensure a final inspection exists before delivering
                    if not final_inspection:
                        raise UserError(_(
                            "Cannot validate delivery. The final quality inspection has not been recorded for Manufacturing Order %s."
                        ) % mo.name)
                    
                    # Ensure no checkpoint has failed
                    failed_inspections = inspections.filtered(lambda i: i.status == 'fail')
                    if failed_inspections:
                        checkpoints = ", ".join(failed_inspections.mapped('checkpoint'))
                        raise UserError(_(
                            "Cannot validate delivery. Quality inspection FAILED for Manufacturing Order %s at checkpoint(s): %s."
                        ) % (mo.name, checkpoints))
                    
                    # Double check final inspection status
                    if final_inspection.status != 'pass':
                        raise UserError(_(
                            "Cannot validate delivery. The final quality inspection for Manufacturing Order %s is not marked as PASS."
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
                        mo_move = linked_mo.move_raw_ids.filtered(lambda m: m.product_id == move.product_id)
                        if mo_move:
                            pick_lots = move.move_line_ids.filtered(lambda l: l.state == 'done' and l.lot_id)
                            if pick_lots:
                                # Remove uncompleted move lines (draft/reserved) to clear old reservations
                                mo_move.move_line_ids.filtered(lambda l: l.state != 'done').unlink()
                                # Recreate them with the exact lot and quantity from the picking
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
