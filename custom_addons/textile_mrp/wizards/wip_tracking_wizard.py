# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class WipTrackingWizard(models.TransientModel):
    _name = 'textile.wip.tracking.wizard'
    _description = 'WIP Tracking Wizard'

    workorder_id = fields.Many2one('mrp.workorder', string='Work Order', required=True)
    action_type = fields.Selection([
        ('produce', 'Log Production'),
        ('transfer', 'Transfer to Next Stage')
    ], string='Action', required=True)
    
    is_multi_variant = fields.Boolean(related='workorder_id.production_id.is_multi_variant', readonly=True)
    qty = fields.Float(string='Quantity', required=True, default=1.0)
    notes = fields.Char(string='Notes')
    
    line_ids = fields.One2many(
        'textile.wip.tracking.wizard.line', 'wizard_id',
        string='Variant Quantities', copy=True
    )

    @api.model
    def default_get(self, fields_list):
        res = super(WipTrackingWizard, self).default_get(fields_list)
        active_id = self.env.context.get('active_id') or res.get('workorder_id')
        action_type = self.env.context.get('default_action_type') or res.get('action_type')
        if active_id:
            wo = self.env['mrp.workorder'].browse(active_id)
            res['workorder_id'] = wo.id
            
            # Find previous workorder to determine logical limits
            previous_wos = wo.production_id.workorder_ids.filtered(
                lambda w: w.state != 'cancel' and w.sequence < wo.sequence
            ).sorted('sequence', reverse=True)
            prev_wo = previous_wos[0] if previous_wos else False

            if wo.production_id.is_multi_variant and wo.variant_line_ids:
                lines = []
                for v_line in wo.variant_line_ids:
                    if action_type == 'transfer':
                        default_qty = v_line.qty_ready
                    else:
                        # Log Production
                        if prev_wo:
                            prev_v_line = prev_wo.variant_line_ids.filtered(lambda l: l.product_id.id == v_line.product_id.id)
                            prev_qty = prev_v_line[0].qty_transferred if prev_v_line else 0.0
                            default_qty = max(0.0, prev_qty - v_line.qty_produced)
                        else:
                            default_qty = v_line.qty_remaining
                    lines.append((0, 0, {
                        'product_id': v_line.product_id.id,
                        'qty': default_qty,
                    }))
                res['line_ids'] = lines
            else:
                # Single-product Flow default calculations
                if action_type == 'transfer':
                    res['qty'] = max(0.0, wo.qty_produced - wo.qty_transferred)
                else:
                    # Log Production
                    if prev_wo:
                        res['qty'] = max(0.0, prev_wo.qty_transferred - wo.qty_produced)
                    else:
                        res['qty'] = max(0.0, wo.qty_production - wo.qty_produced)
        return res

    def _create_wip_stock_move(self, product, qty, source_loc, dest_loc):
        self.ensure_one()
        return self.workorder_id._create_wip_stock_move(product, qty, source_loc, dest_loc)

    def action_confirm(self):
        self.ensure_one()
        wo = self.workorder_id

        # Determine stage sequence details
        previous_wos = wo.production_id.workorder_ids.filtered(
            lambda w: w.state != 'cancel' and w.sequence < wo.sequence
        ).sorted('sequence', reverse=True)
        prev_wo = previous_wos[0] if previous_wos else False

        next_wos = wo.production_id.workorder_ids.filtered(
            lambda w: w.state != 'cancel' and w.sequence > wo.sequence
        ).sorted('sequence')
        next_wo = next_wos[0] if next_wos else False

        if self.is_multi_variant:
            # Multi-variant Batch Logic
            total_wizard_qty = sum(self.line_ids.mapped('qty'))
            if total_wizard_qty <= 0:
                raise UserError(_("Total quantity must be strictly positive."))

            for line in self.line_ids:
                if line.qty < 0:
                    raise UserError(_("Quantity for variant cannot be negative."))
                if line.qty == 0:
                    continue

                v_line = wo.variant_line_ids.filtered(lambda l: l.product_id.id == line.product_id.id)
                if not v_line:
                    continue
                v_line = v_line[0]

                if self.action_type == 'produce':
                    if prev_wo:
                        prev_v_line = prev_wo.variant_line_ids.filtered(lambda l: l.product_id.id == line.product_id.id)
                        prev_v_line = prev_v_line[0] if prev_v_line else False
                        max_allowed = (prev_v_line.qty_transferred - v_line.qty_produced) if prev_v_line else 0.0
                        if line.qty > max_allowed:
                            raise UserError(_("You cannot produce more than what has been transferred from the previous stage for variant %s (Max allowed: %s).") % (line.product_id.display_name, max_allowed))

                    if v_line.qty_produced + line.qty > v_line.planned_qty:
                        raise UserError(_("You cannot produce more than the planned quantity for variant %s.") % line.product_id.display_name)
                    
                    v_line.qty_produced += line.qty

                    # Stage 1: Produce move from Virtual Production to Cutting location
                    if not prev_wo and wo.workcenter_id.wip_location_id:
                        self._create_wip_stock_move(
                            product=line.product_id,
                            qty=line.qty,
                            source_loc=wo.production_id.production_location_id,
                            dest_loc=wo.workcenter_id.wip_location_id
                        )

                elif self.action_type == 'transfer':
                    qty_ready = v_line.qty_ready
                    if line.qty > qty_ready:
                        raise UserError(_("You cannot transfer more than the ready quantity for variant %s (Ready: %s).") % (line.product_id.display_name, qty_ready))
                    v_line.qty_transferred += line.qty

                    # Stage-to-stage transfer move
                    if next_wo:
                        if wo.workcenter_id.wip_location_id and next_wo.workcenter_id.wip_location_id:
                            self._create_wip_stock_move(
                                product=line.product_id,
                                qty=line.qty,
                                source_loc=wo.workcenter_id.wip_location_id,
                                dest_loc=next_wo.workcenter_id.wip_location_id
                            )
                    else:
                        # Final stage transfer: move back to Virtual Production location
                        if wo.workcenter_id.wip_location_id:
                            self._create_wip_stock_move(
                                product=line.product_id,
                                qty=line.qty,
                                source_loc=wo.workcenter_id.wip_location_id,
                                dest_loc=wo.production_id.production_location_id
                            )

            # Update Work Order Aggregates
            total_produced = sum(wo.variant_line_ids.mapped('qty_produced'))
            total_transferred = sum(wo.variant_line_ids.mapped('qty_transferred'))
            wo.qty_produced = total_produced
            wo.qty_producing = total_produced
            wo.qty_transferred = total_transferred

            # Create Log
            self.env['textile.wip.log'].create({
                'workorder_id': wo.id,
                'action_type': self.action_type,
                'qty': total_wizard_qty,
                'notes': self.notes,
            })

            # Check if all variant production completed
            if all(v.qty_remaining <= 0 for v in wo.variant_line_ids):
                wo.button_finish()

        else:
            # Standard Single-product Flow Logic
            if self.qty <= 0:
                raise UserError(_("Quantity must be strictly positive."))

            if self.action_type == 'produce':
                if prev_wo:
                    max_allowed = prev_wo.qty_transferred - wo.qty_produced
                    if self.qty > max_allowed:
                        raise UserError(_("You cannot produce more than what has been transferred from the previous stage (Max allowed: %s).") % max_allowed)

                if wo.qty_produced + self.qty > wo.qty_production:
                    raise UserError(_("You cannot produce more than the total required quantity."))
                wo.qty_produced += self.qty

                # Stage 1: Produce move from Virtual Production to Cutting location
                if not prev_wo and wo.workcenter_id.wip_location_id:
                    self._create_wip_stock_move(
                        product=wo.product_id,
                        qty=self.qty,
                        source_loc=wo.production_id.production_location_id,
                        dest_loc=wo.workcenter_id.wip_location_id
                    )
                
                self.env['textile.wip.log'].create({
                    'workorder_id': wo.id,
                    'action_type': 'produce',
                    'qty': self.qty,
                    'notes': self.notes,
                })
                
                if wo.qty_remaining <= 0:
                    wo.button_finish()

            elif self.action_type == 'transfer':
                qty_ready = wo.qty_produced - wo.qty_transferred
                if self.qty > qty_ready:
                    raise UserError(_("You cannot transfer more than the ready quantity (%(ready)s).") % {'ready': qty_ready})
                wo.qty_transferred += self.qty

                # Stage-to-stage transfer move
                if next_wo:
                    if wo.workcenter_id.wip_location_id and next_wo.workcenter_id.wip_location_id:
                        self._create_wip_stock_move(
                            product=wo.product_id,
                            qty=self.qty,
                            source_loc=wo.workcenter_id.wip_location_id,
                            dest_loc=next_wo.workcenter_id.wip_location_id
                        )
                else:
                    # Final stage transfer: move back to Virtual Production location
                    if wo.workcenter_id.wip_location_id:
                        self._create_wip_stock_move(
                            product=wo.product_id,
                            qty=self.qty,
                            source_loc=wo.workcenter_id.wip_location_id,
                            dest_loc=wo.production_id.production_location_id
                        )
                
                self.env['textile.wip.log'].create({
                    'workorder_id': wo.id,
                    'action_type': 'transfer',
                    'qty': self.qty,
                    'notes': self.notes,
                })
        
        return {'type': 'ir.actions.client', 'tag': 'reload'}


class WipTrackingWizardLine(models.TransientModel):
    _name = 'textile.wip.tracking.wizard.line'
    _description = 'WIP Tracking Wizard Line'

    wizard_id = fields.Many2one('textile.wip.tracking.wizard', string='Wizard', ondelete='cascade', required=True)
    product_id = fields.Many2one('product.product', string='Product Variant', required=True)
    qty = fields.Float(string='Quantity to Process', default=0.0)
