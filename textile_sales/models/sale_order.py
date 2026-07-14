# -*- coding: utf-8 -*-
from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        # Call super first to let standard Odoo process the order normally
        res = super(SaleOrder, self).action_confirm()

        mto_route = self.env.ref('stock.route_warehouse0_mto', raise_if_not_found=False)

        for order in self:
            for line in order.order_line:
                if line.product_id.type not in ['consu', 'product']:
                    continue

                # Skip purchased products and raw materials from automatic MO creation
                categ_name = (line.product_id.categ_id.complete_name or '').lower()
                if 'purchased' in categ_name or 'raw materials' in categ_name:
                    continue

                # 1. Get available stock for the product in the order's warehouse
                available_qty = line.product_id.with_context(
                    warehouse=order.warehouse_id.id
                ).qty_available

                # 2. Calculate shortage
                manufacture_qty = max(0.0, line.product_uom_qty - available_qty)

                # Search if standard procurement generated an MO
                existing_mo = self.env['mrp.production'].search([
                    ('origin', '=', order.name),
                    ('product_id', '=', line.product_id.id),
                    ('state', 'not in', ('done', 'cancel'))
                ])

                # Check if MTO route is active on the product
                is_mto = mto_route and mto_route in line.product_id.route_ids

                # 3. Only if manufacture_qty > 0 and MTO is active
                if is_mto:
                    if manufacture_qty > 0:
                        if existing_mo:
                            # Update existing MO with the shortage qty using standard wizard
                            self.env['change.production.qty'].create({
                                'mo_id': existing_mo.id,
                                'product_qty': manufacture_qty,
                            }).change_prod_qty()
                        else:
                            # Create new MO if it wasn't auto-created
                            bom_dict = self.env['mrp.bom']._bom_find(line.product_id)
                            bom = bom_dict.get(line.product_id) if bom_dict else False
                            self.env['mrp.production'].create({
                                'product_id': line.product_id.id,
                                'product_qty': manufacture_qty,
                                'product_uom_id': line.product_uom.id,
                                'bom_id': bom.id if bom else False,
                                'origin': order.name,
                            })
                    else:
                        # 4. If manufacture_qty == 0, cancel/delete auto-created MO
                        if existing_mo:
                            existing_mo.action_cancel()
                            draft_mos = existing_mo.filtered(lambda m: m.state == 'draft')
                            if draft_mos:
                                draft_mos.unlink()
                                
                        # Change the procure_method of the delivery moves to make_to_stock
                        # so that the delivery order can reserve the available stock
                        moves = order.picking_ids.mapped('move_ids').filtered(lambda m: m.product_id.id == line.product_id.id)
                        moves.write({'procure_method': 'make_to_stock'})
                        for picking in moves.mapped('picking_id'):
                            picking.action_assign()
        return res
