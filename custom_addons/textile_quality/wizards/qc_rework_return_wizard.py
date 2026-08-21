# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class QcReworkReturnWizard(models.TransientModel):
    _name = 'textile.qc.rework.return.wizard'
    _description = 'Return Reworked Products to QC'

    workorder_id = fields.Many2one('mrp.workorder', string='Work Order', required=True)
    production_id = fields.Many2one('mrp.production', related='workorder_id.production_id', readonly=True)
    is_multi_variant = fields.Boolean(related='production_id.is_multi_variant', readonly=True)
    
    qty = fields.Float(string='Quantity to Return', default=1.0)
    line_ids = fields.One2many('textile.qc.rework.return.wizard.line', 'wizard_id', string='Variant Lines')

    @api.model
    def default_get(self, fields_list):
        res = super(QcReworkReturnWizard, self).default_get(fields_list)
        
        # Resolve the workorder_id regardless of which screen (MO or WorkOrder) we opened it from
        wo_id = self.env.context.get('default_workorder_id') or res.get('workorder_id')
        if not wo_id:
            active_model = self.env.context.get('active_model')
            active_id = self.env.context.get('active_id')
            if active_model == 'mrp.workorder' and active_id:
                wo_id = active_id
            elif active_model == 'mrp.production' and active_id:
                mo = self.env['mrp.production'].browse(active_id)
                qc_wos = mo.workorder_ids.filtered(
                    lambda wo: 'qc' in (wo.name or '').lower() or 'quality' in (wo.name or '').lower() or
                               'qc' in (wo.workcenter_id.name or '').lower() or 'quality' in (wo.workcenter_id.name or '').lower()
                )
                if qc_wos:
                    wo_id = qc_wos[0].id
                    
        if wo_id:
            wo = self.env['mrp.workorder'].browse(wo_id)
            res['workorder_id'] = wo.id
            
            rework_location = self.env['textile.quality']._get_rework_location()
            qc_location = wo.workcenter_id.wip_location_id
            if not qc_location:
                qc_location = self.env['stock.location'].search([
                    ('complete_name', 'ilike', 'Quality Check')
                ], limit=1)
                
            # Find the MO's finished products / variants
            mo_products = wo.production_id.move_finished_ids.mapped('product_id')
            if not mo_products:
                mo_products = wo.production_id.product_id
                
            # Calculate total rework generated in done QC batches for this MO
            done_batches = self.env['textile.quality'].search([
                ('production_id', '=', wo.production_id.id),
                ('state', '=', 'done')
            ])
            rework_qty_map = {}
            for batch in done_batches:
                if batch.has_variants:
                    for line in batch.variant_line_ids:
                        rework_qty_map[line.product_id.id] = rework_qty_map.get(line.product_id.id, 0.0) + line.rework_qty
                else:
                    product = batch.production_id.product_id
                    rework_qty_map[product.id] = rework_qty_map.get(product.id, 0.0) + batch.rework_qty
                    
            # Calculate total already returned via stock moves for this MO
            returned_moves = self.env['stock.move'].search([
                ('origin', '=', wo.production_id.name),
                ('location_id', '=', rework_location.id),
                ('location_dest_id', '=', qc_location.id),
                ('state', '=', 'done')
            ])
            returned_qty_map = {}
            for move in returned_moves:
                returned_qty_map[move.product_id.id] = returned_qty_map.get(move.product_id.id, 0.0) + move.quantity
                
            if wo.production_id.is_multi_variant:
                lines = []
                for prod in mo_products:
                    rework_total = rework_qty_map.get(prod.id, 0.0)
                    returned_total = returned_qty_map.get(prod.id, 0.0)
                    available_rework = max(0.0, rework_total - returned_total)
                    if available_rework > 0:
                        lines.append((0, 0, {
                            'product_id': prod.id,
                            'rework_qty': available_rework,
                            'qty': available_rework,
                        }))
                res['line_ids'] = lines
            else:
                prod = wo.product_id
                rework_total = rework_qty_map.get(prod.id, 0.0)
                returned_total = returned_qty_map.get(prod.id, 0.0)
                res['qty'] = max(0.0, rework_total - returned_total)
                
        return res


    def action_confirm(self):
        self.ensure_one()
        wo = self.workorder_id
        qc_location = wo.workcenter_id.wip_location_id
        if not qc_location:
            qc_location = self.env['stock.location'].search([
                ('complete_name', 'ilike', 'Quality Check')
            ], limit=1)
        if not qc_location:
            raise UserError(_("Please configure the WIP Location for the Quality Check Work Center."))
            
        rework_location = self.env['textile.quality']._get_rework_location()
        
        if self.is_multi_variant:
            valid_lines = self.line_ids.filtered(lambda l: l.product_id)
            total_qty = sum(valid_lines.mapped('qty'))
            if total_qty <= 0:
                raise UserError(_("Quantity to return must be strictly positive."))
                
            for line in valid_lines:
                if line.qty < 0:
                    raise UserError(_("Quantity cannot be negative."))
                if line.qty > line.rework_qty:
                    raise UserError(_("You cannot return more than the available rework quantity for variant %s (Max: %s).") % (line.product_id.display_name, line.rework_qty))
                if line.qty == 0:
                    continue
                
                # Move from Rework back to QC
                self.env['textile.quality']._create_wip_stock_move(line.product_id, line.qty, rework_location, qc_location, production_id=self.production_id)
        else:
            if self.qty <= 0:
                raise UserError(_("Quantity to return must be strictly positive."))
            
            # Find current rework quantity
            quant = self.env['stock.quant'].search([
                ('location_id', '=', rework_location.id),
                ('product_id', '=', wo.product_id.id),
                ('quantity', '>', 0)
            ], limit=1)
            rework_qty = quant.quantity if quant else 0.0
            
            if self.qty > rework_qty:
                raise UserError(_("You cannot return more than the available rework quantity (Max: %s).") % rework_qty)
                
            # Move from Rework back to QC
            self.env['textile.quality']._create_wip_stock_move(wo.product_id, self.qty, rework_location, qc_location, production_id=self.production_id)

            
        return {'type': 'ir.actions.client', 'tag': 'reload'}

class QcReworkReturnWizardLine(models.TransientModel):
    _name = 'textile.qc.rework.return.wizard.line'
    _description = 'Return Repaired Products Wizard Line'

    wizard_id = fields.Many2one('textile.qc.rework.return.wizard', string='Wizard', ondelete='cascade', required=True)
    product_id = fields.Many2one('product.product', string='Product Variant', required=False)
    rework_qty = fields.Float(string='Current Rework Qty', readonly=True)
    qty = fields.Float(string='Quantity to Return', default=0.0)

