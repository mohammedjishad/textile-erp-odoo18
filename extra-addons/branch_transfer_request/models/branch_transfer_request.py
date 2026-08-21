# -*- coding: utf-8 -*-

# ============================================================
# WHAT THIS FILE DOES:
# This file defines the main Branch Transfer Request model.
# When Branch 1 needs to send products to Branch 2,
# they create a record here. The workflow goes:
#   Draft → Confirmed → Approved → Done
# When the request is Confirmed, this file automatically sends
# a real-time bell notification + activity task to ALL users
# of the destination branch so they know a request is waiting.
# The model stores who requested it, source branch/warehouse/location,
# destination branch/warehouse/location, and the product lines.
# It also logs every state change in the chatter automatically.
# ============================================================

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class BranchTransferRequest(models.Model):
    _name = 'branch.transfer.request'
    _description = 'Branch Transfer Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_request desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
        tracking=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('approved', 'Approved'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
        ('return_requested', 'Return Requested'),
        ('return_approved', 'Return Approved'),
        ('return_done', 'Return Done'),
    ], string='Status', default='draft', tracking=True, copy=False)

    date_request = fields.Datetime(
        string='Request Date',
        default=fields.Datetime.now,
        required=True,
        tracking=True,
    )
    date_approved = fields.Datetime(string='Approved Date', readonly=True)
    date_done = fields.Datetime(string='Done Date', readonly=True)

    # Source Branch & Warehouse
    source_branch_id = fields.Many2one(
        'res.company',
        string='Source Branch',
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )
    source_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Source Warehouse',
        default=lambda self: self.env['stock.warehouse'].sudo().search([
            ('incharge_user_ids', 'in', self.env.user.id)
        ], limit=1),
    )
    source_location_id = fields.Many2one(
        'stock.location',
        string='Source Location',
    )
    dest_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Destination Warehouse',
        tracking=True,
        check_company=False,
    )
    dest_location_id = fields.Many2one(
        'stock.location',
        string='Destination Location',
        check_company=False,
    )

    # Request Details
    requested_by = fields.Many2one(
        'res.users',
        string='Requested By',
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )
    approved_by = fields.Many2one(
        'res.users',
        string='Approved By',
        readonly=True,
        tracking=True,
    )
    notes = fields.Text(string='Notes')

    line_ids = fields.One2many(
        'branch.transfer.request.line',
        'request_id',
        string='Products',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
    )
    qty_requested = fields.Float(
        string='Requested Qty',
        default=1.0,
        digits='Product Unit of Measure',
    )
    qty_approved = fields.Float(
        string='Approved Qty',
        digits='Product Unit of Measure',
    )

    line_count = fields.Integer(compute='_compute_line_count', string='# Products')

    delivery_id = fields.Many2one(
        'stock.picking',
        string='Delivery Order',
        readonly=True,
        copy=False,
    )
    receipt_id = fields.Many2one(
        'stock.picking',
        string='Receipt',
        readonly=True,
        copy=False,
    )
    delivery_name = fields.Char(string='Delivery Ref', readonly=True, copy=False)
    receipt_name = fields.Char(string='Receipt Ref', readonly=True, copy=False)

    # =====================================
    # return damage products
    # =====================================
    return_state = fields.Selection([
        ('none', 'None'),
        ('requested', 'Return Requested'),
        ('done', 'Return Done'),
    ], default='none', string='Return Status')

    return_reason = fields.Text(string='Return Reason')

    is_source_incharge = fields.Boolean(compute='_compute_is_source_incharge')
    is_dest_incharge = fields.Boolean(compute='_compute_is_dest_incharge')
    has_approved_lines = fields.Boolean(compute='_compute_has_approved_lines')
    has_done_lines = fields.Boolean(compute='_compute_has_done_lines')

    @api.depends('line_ids.is_approved')
    def _compute_has_approved_lines(self):
        for rec in self:
            rec.has_approved_lines = any(rec.line_ids.mapped('is_approved'))

    @api.depends('line_ids.is_done')
    def _compute_has_done_lines(self):
        for rec in self:
            rec.has_done_lines = any(rec.line_ids.mapped('is_done'))

    @api.depends('source_warehouse_id')
    def _compute_is_source_incharge(self):
        for rec in self:
            rec.is_source_incharge = self.env.user in rec.source_warehouse_id.sudo().incharge_user_ids

    @api.depends('dest_warehouse_id')
    def _compute_is_dest_incharge(self):
        for rec in self:
            rec.is_dest_incharge = self.env.user in rec.dest_warehouse_id.sudo().incharge_user_ids

    # =====================================================================
    # ONCHANGE METHODS
    # =====================================================================

    @api.onchange('source_branch_id')
    def _onchange_source_branch(self):
        self.source_warehouse_id = False
        self.source_location_id = False
        self.dest_warehouse_id = False
        self.dest_location_id = False
        if self.source_branch_id:
            warehouses = self.env['stock.warehouse'].sudo().search([
                ('company_id', '=', self.source_branch_id.id)
            ])
            return {
                'domain': {
                    'source_warehouse_id': [('id', 'in', warehouses.ids)],
                    'dest_warehouse_id': [('id', 'in', warehouses.ids)],
                }
            }

    @api.onchange('source_warehouse_id')
    def _onchange_source_warehouse(self):
        self.source_location_id = False
        if self.source_warehouse_id:
            return {
                'domain': {
                    'source_location_id': [
                        ('warehouse_id', '=', self.source_warehouse_id.id),
                        ('usage', '=', 'internal'),
                    ]
                }
            }

    @api.onchange('dest_warehouse_id')
    def _onchange_dest_warehouse(self):
        self.dest_location_id = False
        if self.dest_warehouse_id:
            locations = self.env['stock.location'].sudo().search([
                ('warehouse_id', '=', self.dest_warehouse_id.id),
                ('usage', '=', 'internal'),
            ])
            return {
                'domain': {
                    'dest_location_id': [('id', 'in', locations.ids)]
                }
            }

    # =====================================================================
    # COMPUTE METHODS
    # =====================================================================

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'branch.transfer.request') or _('New')
        return super().create(vals_list)

    # =====================================================================
    # ACTION METHODS
    # =====================================================================

    def action_confirm(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Please add at least one product before confirming.'))
            rec.state = 'confirmed'
            rec._notify_destination_branch()

    def action_approve(self):
        for rec in self:
            if self.env.user not in rec.dest_warehouse_id.sudo().incharge_user_ids:
                raise UserError(_('Only the destination warehouse incharge can approve this request.'))
            if rec.state != 'confirmed':
                raise UserError(_('Only confirmed requests can be approved.'))
            if not any(rec.line_ids.mapped('is_approved')):
                raise UserError(_('Please check at least one product line before approving.'))

            rec.state = 'approved'
            rec.approved_by = self.env.user
            rec.date_approved = fields.Datetime.now()

            # Auto create delivery from BR2 — only checked lines
            picking_type = self.env['stock.picking.type'].sudo().search([
                ('warehouse_id', '=', rec.dest_warehouse_id.id),
                ('code', '=', 'outgoing'),
            ], limit=1)

            if not picking_type:
                raise UserError(_('No delivery operation type found for destination warehouse.'))

            source_location = rec.source_location_id or rec.source_warehouse_id.sudo().lot_stock_id
            dest_location = rec.dest_location_id or rec.dest_warehouse_id.sudo().lot_stock_id

            approved_lines = rec.line_ids.filtered(lambda l: l.is_approved)

            transit_location = self.env['stock.location'].sudo().search([('usage', '=', 'transit')], limit=1)
            if not transit_location:
                raise UserError(_('No transit location found. Please configure a transit location.'))

            delivery_seq = self.env['ir.sequence'].next_by_code('branch.transfer.delivery') or _('New')

            picking_vals = {
                'name': delivery_seq,
                'picking_type_id': picking_type.id,
                'location_id': dest_location.id,
                'location_dest_id': transit_location.id,
                'origin': rec.name,
                'partner_id': rec.source_branch_id.partner_id.id,
                'move_ids': [(0, 0, {
                    'name': line.product_id.name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.qty_approved,
                    'product_uom': line.product_uom_id.id,
                    'location_id': dest_location.id,
                    'location_dest_id': transit_location.id,
                }) for line in approved_lines],
            }

            picking = self.env['stock.picking'].sudo().create(picking_vals)
            picking.sudo().action_confirm()
            picking.sudo().action_assign()

            for move in picking.move_ids:
                move.quantity = move.product_uom_qty

            picking.sudo().with_context(skip_backorder=True).button_validate()

            rec.delivery_id = picking.id
            rec.delivery_name = delivery_seq

            rec.with_context(
                mail_notify_force_send=False,
                notify=False
            ).message_post(
                body=_('Request approved by <b>%s</b>. Delivery <b>%s</b> auto-created and validated.') % (
                    self.env.user.name, picking.name),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )

            # Notify BR1
            rec._notify_source_branch_approved()

    def action_done(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Only approved requests can be marked as done.'))

            if not any(rec.line_ids.mapped('is_done')):
                raise UserError(_('Please check at least one product line before clicking Done.'))

            # Auto create receipt for BR1 — only checked lines
            picking_type = self.env['stock.picking.type'].sudo().search([
                ('warehouse_id', '=', rec.source_warehouse_id.id),
                ('code', '=', 'incoming'),
            ], limit=1)

            if not picking_type:
                raise UserError(_('No receipt operation type found for source warehouse.'))

            source_location = rec.source_location_id or rec.source_warehouse_id.sudo().lot_stock_id
            dest_location = rec.dest_location_id or rec.dest_warehouse_id.sudo().lot_stock_id

            valid_lines = [
                (line, line.qty_done)
                for line in rec.line_ids.filtered(lambda l: l.is_done)
                if line.qty_done > 0
            ]

            if not valid_lines:
                raise UserError(_('Cannot create receipt. All products reported as damaged.'))

            transit_location = self.env['stock.location'].sudo().search([('usage', '=', 'transit')], limit=1)
            if not transit_location:
                raise UserError(_('No transit location found.'))

            receipt_seq = self.env['ir.sequence'].next_by_code('branch.transfer.receipt') or _('New')

            picking_vals = {
                'name': receipt_seq,
                'picking_type_id': picking_type.id,
                'location_id': transit_location.id,
                'location_dest_id': source_location.id,
                'origin': rec.name,
                'partner_id': rec.dest_warehouse_id.company_id.partner_id.id,
                'move_ids': [(0, 0, {
                    'name': line.product_id.name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': net_qty,
                    'product_uom': line.product_uom_id.id,
                    'location_id': transit_location.id,
                    'location_dest_id': source_location.id,
                }) for line, net_qty in valid_lines],
            }

            picking = self.env['stock.picking'].sudo().create(picking_vals)
            picking.sudo().action_confirm()
            picking.sudo().action_assign()

            for move in picking.move_ids:
                move.quantity = move.product_uom_qty

            picking.sudo().with_context(skip_backorder=True).button_validate()

            rec.receipt_id = picking.id
            rec.receipt_name = receipt_seq
            rec.state = 'done'
            rec.date_done = fields.Datetime.now()

            rec.with_context(
                mail_notify_force_send=False,
                notify=False
            ).message_post(
                body=_('Receipt <b>%s</b> auto-created and validated. Transfer complete.') % picking.name,
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )

    def action_cancel(self):
        for rec in self:
            if self.env.user not in rec.dest_warehouse_id.sudo().incharge_user_ids:
                raise UserError(_('Only the destination warehouse incharge can cancel this request.'))
            if rec.state == 'done':
                raise UserError(_('Done requests cannot be cancelled.'))
            rec.state = 'cancelled'
            rec.with_context(
                mail_notify_force_send=False,
                notify=False
            ).message_post(
                body=_('Transfer request has been <b>Cancelled</b>.'),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )

    def action_reset_draft(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('Only cancelled requests can be reset to draft.'))
            rec.state = 'draft'

    # ==================================
    # for create return
    # ==================================
    def action_request_return(self):
        self.ensure_one()
        wizard = self.env['branch.transfer.return.wizard'].create({
            'request_id': self.id,
            'line_ids': [(0, 0, {
                'product_id': line.product_id.id,
                'product_uom_id': line.product_uom_id.id,
                'qty_requested': line.qty_requested,
                'return_qty': 0.0,
            }) for line in self.line_ids],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Report Damaged Products'),
            'res_model': 'branch.transfer.return.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }

    def action_confirm_return(self):
        self.ensure_one()
        if not self.return_reason:
            raise UserError(_('Please enter a return reason.'))

    def action_create_return_receipt(self):
        for rec in self:
            if rec.state != 'done':
                raise UserError(_('Only done requests can create a return receipt.'))

            picking_type = self.env['stock.picking.type'].sudo().search([
                ('warehouse_id', '=', rec.dest_warehouse_id.id),
                ('code', '=', 'incoming'),
            ], limit=1)

            if not picking_type:
                raise UserError(_('No receipt operation type found for destination warehouse.'))

            picking_vals = {
                'picking_type_id': picking_type.id,
                'location_id': rec.dest_location_id.id or picking_type.default_location_src_id.id,
                'location_dest_id': rec.source_location_id.id or picking_type.default_location_dest_id.id,
                'origin': rec.name,
                'move_ids': [(0, 0, {
                    'name': line.product_id.name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.qty_requested,
                    'product_uom': line.product_uom_id.id,
                    'location_id': rec.dest_location_id.id or picking_type.default_location_src_id.id,
                    'location_dest_id': rec.source_location_id.id or picking_type.default_location_dest_id.id,
                }) for line in rec.line_ids],
            }

            picking = self.env['stock.picking'].sudo().create(picking_vals)
            rec.state = 'done'
            rec.date_done = fields.Datetime.now()

            return {
                'type': 'ir.actions.act_window',
                'name': _('Receipt'),
                'res_model': 'stock.picking',
                'res_id': picking.id,
                'view_mode': 'form',
                'target': 'current',
            }

    # =====================================================================
    # SMART BUTTON ACTIONS
    # =====================================================================

    def action_view_delivery(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Delivery Order'),
            'res_model': 'stock.picking',
            'res_id': self.delivery_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_receipt(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Receipt'),
            'res_model': 'stock.picking',
            'res_id': self.receipt_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # =====================================================================
    # NOTIFICATION METHODS
    # =====================================================================

    def _notify_destination_branch(self):
        self.ensure_one()

        dest_incharge_users = self.dest_warehouse_id.sudo().incharge_user_ids
        source_incharge_users = self.source_warehouse_id.sudo().incharge_user_ids

        for user in dest_incharge_users:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=user.id,
                note=_(
                    'Transfer Request received from <b>%s</b>. '
                    'Reference: <b>%s</b>. Please review and approve.'
                ) % (self.source_warehouse_id.name, self.name),
                summary=_('Branch Transfer Request: %s') % self.name,
            )

        for user in source_incharge_users:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=user.id,
                note=_(
                    'Your Transfer Request <b>%s</b> has been sent to <b>%s</b>. '
                    'Waiting for approval.'
                ) % (self.name, self.dest_warehouse_id.name),
                summary=_('Transfer Request Sent: %s') % self.name,
            )

    def _notify_source_branch_approved(self):
        self.ensure_one()
        source_incharge_users = self.source_warehouse_id.sudo().incharge_user_ids
        for user in source_incharge_users:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=user.id,
                note=_(
                    'Your Transfer Request <b>%s</b> has been <b>approved</b> by <b>%s</b>. '
                    'Products are on the way. Click <b>Done</b> to receive them.'
                ) % (self.name, self.dest_warehouse_id.name),
                summary=_('Transfer Approved - Action Required: %s') % self.name,
            )

    def _notify_get_recipients(self, message, msg_vals, **kwargs):
        return []