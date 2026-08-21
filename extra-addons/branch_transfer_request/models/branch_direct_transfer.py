# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class BranchDirectTransfer(models.Model):
    _name = 'branch.direct.transfer'
    _description = 'Direct Branch Transfer'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: 'New')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    transfer_type = fields.Selection([
        ('send', 'Send (Delivery)'),
        ('receive', 'Receive (Receipt)'),
    ], string='Transfer Type', default='send', required=True)

    warehouse_id = fields.Many2one('stock.warehouse', string='Source Warehouse', required=True, default=lambda self: self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1))
    other_warehouse_id = fields.Many2one('stock.warehouse', string='Destination Warehouse', required=True)

    date_transfer = fields.Datetime(string='Transfer Date', default=fields.Datetime.now)
    requested_by = fields.Many2one('res.users', string='Requested By', default=lambda self: self.env.user, readonly=True)
    
    line_ids = fields.One2many('branch.direct.transfer.line', 'transfer_id', string='Products')

    picking_id = fields.Many2one('stock.picking', string='Stock Operation', readonly=True)

    def action_done(self):
        """ Creates and validates the Stock Operation, generates sequence, and redirects """
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Please add at least one product line.'))
            
            # Generate sequence number upon validation if still 'New'
            if not rec.name or rec.name == 'New' or rec.name == _('New'):
                new_seq = self.env['ir.sequence'].next_by_code('branch.direct.transfer') or 'New'
                rec.write({'name': new_seq})
                rec.name = new_seq # Ensure memory is also updated

            transit_location = self.env['stock.location'].search([('usage', '=', 'transit')], limit=1)
            if not transit_location:
                raise UserError(_('No transit location found (Usage: Transit).'))

            if rec.transfer_type == 'send':
                # Create Delivery (Local -> Transit)
                picking_type = self.env['stock.picking.type'].search([
                    ('warehouse_id', '=', rec.warehouse_id.id),
                    ('code', '=', 'outgoing'),
                ], limit=1)
                location_id = rec.warehouse_id.lot_stock_id.id
                location_dest_id = transit_location.id
                # Partner for Deliver To
                partner_id = rec.other_warehouse_id.partner_id.id
            else:
                # Create Receipt (Transit -> Local)
                picking_type = self.env['stock.picking.type'].search([
                    ('warehouse_id', '=', rec.warehouse_id.id),
                    ('code', '=', 'incoming'),
                ], limit=1)
                location_id = transit_location.id
                location_dest_id = rec.warehouse_id.lot_stock_id.id
                # Partner for Receive From
                partner_id = rec.other_warehouse_id.partner_id.id

            if not picking_type:
                raise UserError(_('No suitable picking type found for warehouse %s.') % rec.warehouse_id.name)

            picking_vals = {
                'picking_type_id': picking_type.id,
                'location_id': location_id,
                'location_dest_id': location_dest_id,
                'origin': rec.name,
                'partner_id': partner_id,
                'move_ids': [(0, 0, {
                    'name': line.product_id.name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.qty,
                    'product_uom': line.product_uom_id.id,
                    'location_id': location_id,
                    'location_dest_id': location_dest_id,
                }) for line in rec.line_ids],
            }
            picking = self.env['stock.picking'].create(picking_vals)
            picking.action_confirm()
            picking.action_assign()
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
            picking.with_context(skip_backorder=True).button_validate()
            
            rec.picking_id = picking.id
            rec.state = 'done'

        # Redirect to the tree view of Direct Transfers
        return {
            'type': 'ir.actions.act_window',
            'name': _('Direct Transfers'),
            'res_model': 'branch.direct.transfer',
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_save(self):
        """ Empty method to trigger save from header button """
        return True

    def action_cancel(self):
        self.state = 'cancelled'

    def action_view_picking(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Stock Operation'),
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': self.picking_id.id,
            'target': 'current',
        }

class BranchDirectTransferLine(models.Model):
    _name = 'branch.direct.transfer.line'
    _description = 'Direct Branch Transfer Line'

    transfer_id = fields.Many2one('branch.direct.transfer', string='Transfer', ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    product_uom_id = fields.Many2one('uom.uom', string='UoM')
    qty = fields.Float(string='Quantity', default=1.0)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id
