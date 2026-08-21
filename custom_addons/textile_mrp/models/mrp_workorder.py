# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    qty_transferred = fields.Float(
        string='Qty Transferred to Next WIP',
        compute='_compute_qty_transferred',
        store=True,
        readonly=False,
        copy=False,
        help="Tracks how many finished pieces have already been transferred from this workcenter WIP location to the next."
    )

    variant_line_ids = fields.One2many(
        'mrp.workorder.variant.line',
        'workorder_id',
        string='Variant Production Progress',
        copy=True
    )
    qty_ready = fields.Float(
        string='Ready for Next Stage',
        compute='_compute_qty_ready',
        store=True,
        help="Quantity produced but not yet transferred."
    )

    wip_log_ids = fields.One2many(
        'textile.wip.log',
        'workorder_id',
        string='Tracking Logs'
    )

    @api.onchange('variant_line_ids')
    def _onchange_variant_line_ids(self):
        if self.production_id.is_multi_variant and self.variant_line_ids:
            total_done = sum(self.variant_line_ids.mapped('qty_produced'))
            self.qty_produced = total_done
            self.qty_producing = total_done

    def _create_wip_stock_move(self, product, qty, source_loc, dest_loc):
        self.ensure_one()
        if not source_loc or not dest_loc or qty <= 0:
            return False
        
        move = self.env['stock.move'].with_context(
            default_production_id=False,
            default_raw_material_production_id=False,
            default_picking_type_id=False,
        ).create({
            'name': f"WIP Transfer: {self.production_id.name}",
            'product_id': product.id,
            'product_uom': product.uom_id.id,
            'product_uom_qty': qty,
            'location_id': source_loc.id,
            'location_dest_id': dest_loc.id,
            'origin': self.production_id.name,
            'state': 'draft',
        })
        move._action_confirm()
        move._action_assign()
        move.quantity = qty
        move.picked = True
        move._action_done()
        return move

    def _auto_transfer_remaining_wip(self):
        for rec in self:
            # Determine next workorder
            next_wos = rec.production_id.workorder_ids.filtered(
                lambda w: w.state != 'cancel' and w.sequence > rec.sequence
            ).sorted('sequence')
            next_wo = next_wos[0] if next_wos else False

            source_loc = rec.workcenter_id.wip_location_id
            if not source_loc:
                continue

            if next_wo:
                dest_loc = next_wo.workcenter_id.wip_location_id
            else:
                dest_loc = rec.production_id.production_location_id

            if not dest_loc:
                continue

            if rec.production_id.is_multi_variant and rec.variant_line_ids:
                for v_line in rec.variant_line_ids:
                    qty_to_transfer = v_line.qty_produced - v_line.qty_transferred
                    if qty_to_transfer > 0:
                        rec._create_wip_stock_move(v_line.product_id, qty_to_transfer, source_loc, dest_loc)
                        v_line.qty_transferred += qty_to_transfer
            else:
                qty_produced = rec.qty_produced or rec.qty_producing or rec.production_id.product_qty
                qty_to_transfer = qty_produced - rec.qty_transferred
                if qty_to_transfer > 0:
                    rec._create_wip_stock_move(rec.product_id, qty_to_transfer, source_loc, dest_loc)
                    rec.qty_transferred += qty_to_transfer

    def button_finish(self):
        for rec in self:
            if rec.production_id.is_multi_variant and rec.variant_line_ids:
                total_done = sum(rec.variant_line_ids.mapped('qty_produced'))
                if total_done == 0:
                    for v_line in rec.variant_line_ids:
                        v_line.qty_produced = v_line.planned_qty
                    total_done = sum(rec.variant_line_ids.mapped('qty_produced'))
                rec.qty_produced = total_done
                rec.qty_producing = total_done
                wos = sorted(rec.production_id.workorder_ids, key=lambda w: (w.sequence, w.id))
                if wos and rec.id == wos[-1].id:
                    for v_line in rec.variant_line_ids:
                        mo_v_line = rec.production_id.variant_line_ids.filtered(lambda l: l.product_id.id == v_line.product_id.id)
                        if mo_v_line:
                            mo_v_line[0].qty_produced = v_line.qty_produced
            
            # Auto-transfer any remaining ready WIP to next stage or Virtual Production
            rec._auto_transfer_remaining_wip()
            
        return super().button_finish()

    @api.depends('variant_line_ids.qty_transferred', 'production_id.is_multi_variant')
    def _compute_qty_transferred(self):
        for wo in self:
            if wo.production_id.is_multi_variant and wo.variant_line_ids:
                wo.qty_transferred = sum(wo.variant_line_ids.mapped('qty_transferred'))

    @api.depends('qty_produced', 'qty_transferred', 'variant_line_ids.qty_ready', 'production_id.is_multi_variant')
    def _compute_qty_ready(self):
        for wo in self:
            if wo.production_id.is_multi_variant and wo.variant_line_ids:
                wo.qty_ready = sum(wo.variant_line_ids.mapped('qty_ready'))
            else:
                wo.qty_ready = max(0.0, wo.qty_produced - wo.qty_transferred)

    def action_log_production(self):
        self.ensure_one()
        return {
            'name': _('Log Production'),
            'type': 'ir.actions.act_window',
            'res_model': 'textile.wip.tracking.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_workorder_id': self.id,
                'default_action_type': 'produce',
                'default_qty': 1.0,
            }
        }

    def action_transfer_wip(self):
        self.ensure_one()
        return {
            'name': _('Transfer to Next Stage'),
            'type': 'ir.actions.act_window',
            'res_model': 'textile.wip.tracking.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_workorder_id': self.id,
                'default_action_type': 'transfer',
                'default_qty': self.qty_ready,
            }
        }
