from odoo import models, fields, api, _
from odoo.exceptions import UserError


class BranchTransferReturnWizard(models.TransientModel):
    _name = 'branch.transfer.return.wizard'
    _description = 'Return Request Wizard'

    request_id = fields.Many2one('branch.transfer.request', string='Transfer Request', readonly=True)
    return_reason = fields.Text(string='Return Reason')
    line_ids = fields.One2many('branch.transfer.return.wizard.line', 'wizard_id', string='Products')

    def action_confirm_return(self):
        self.ensure_one()
        if not self.return_reason:
            raise UserError(_('Please enter a return reason.'))
        rec = self.request_id

        # ✅ ADD THIS: Save return_qty back to each request line
        for wizard_line in self.line_ids:
            matching_line = rec.line_ids.filtered(
                lambda l: l.product_id.id == wizard_line.product_id.id
            )
            if matching_line:
                matching_line.return_qty = wizard_line.return_qty

        rec.return_reason = self.return_reason
        rec.return_state = 'requested'

        return_lines = ', '.join([
            '%s: %s' % (l.product_id.name, l.return_qty)
            for l in self.line_ids if l.return_qty > 0
        ])

        for user in rec.dest_warehouse_id.sudo().incharge_user_ids:
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=user.id,
                note=_(
                    '⚠️ <b>Damaged Products Reported</b><br/>'
                    'From: <b>%s</b><br/>'
                    'Request: <b>%s</b><br/>'
                    'Reason: <b>%s</b><br/>'
                    'Damaged: <b>%s</b><br/><br/>'
                    'Please create a return receipt.'
                ) % (rec.source_warehouse_id.name, rec.name, self.return_reason, return_lines),
                summary=_('⚠️ Return Requested: %s') % rec.name,
            )
        return {'type': 'ir.actions.act_window_close'}

class BranchTransferReturnWizardLine(models.TransientModel):
    _name = 'branch.transfer.return.wizard.line'
    _description = 'Return Wizard Line'

    wizard_id = fields.Many2one('branch.transfer.return.wizard', string='Wizard')
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    product_uom_id = fields.Many2one('uom.uom', string='Unit', readonly=True)
    qty_requested = fields.Float(string='Requested Qty', readonly=True)
    return_qty = fields.Float(string='Return Qty', required=True, default=0.0)