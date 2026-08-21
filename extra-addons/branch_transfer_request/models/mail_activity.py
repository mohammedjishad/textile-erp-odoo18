# -*- coding: utf-8 -*-
import logging
from odoo import models, _, SUPERUSER_ID
from odoo.exceptions import UserError, AccessError

_logger = logging.getLogger(__name__)

BRANCH_TRANSFER_MODEL = 'branch.transfer.request'


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    def _get_real_uid(self):
        """Get the real logged-in user ID even through sudo calls."""
        return self._context.get('uid') or self.env.uid

    def _check_activity_user(self):
        real_uid = self._get_real_uid()

        for activity in self.sudo():
            if activity.res_model != BRANCH_TRANSFER_MODEL:
                continue

            transfer = self.env[BRANCH_TRANSFER_MODEL].sudo().browse(
                activity.res_id
            )

            if not transfer.exists():
                continue

            if activity.user_id.id != real_uid:
                raise AccessError(_(
                    'Only %s can Done/Cancel this activity.'
                ) % activity.user_id.name)

    def action_done(self):
        self._check_activity_user()
        return super().action_done()

    def action_done_schedule_next(self):
        self._check_activity_user()
        return super().action_done_schedule_next()

    def _action_done(self, feedback=False, attachment_ids=None):
        self._check_activity_user()
        return super()._action_done(
            feedback=feedback,
            attachment_ids=attachment_ids,
        )

    def action_cancel_multi(self):
        self._check_activity_user()
        return super().action_cancel_multi()

    def unlink(self):
        real_uid = self._get_real_uid()

        if real_uid and real_uid != SUPERUSER_ID:
            for activity in self.sudo():
                if activity.res_model != BRANCH_TRANSFER_MODEL:
                    continue

                transfer = self.env[BRANCH_TRANSFER_MODEL].sudo().browse(
                    activity.res_id
                )

                if not transfer.exists():
                    continue

                if activity.user_id.id != real_uid:
                    _logger.warning(
                        "Blocked unlink of mail.activity %s by user #%s",
                        activity.id, real_uid
                    )
                    return True

        return super().unlink()

    def write(self, vals):
        real_uid = self._get_real_uid()

        if real_uid and real_uid != SUPERUSER_ID:
            safe_vals = {
                'date_deadline',
                'note',
                'summary',
                'activity_type_id',
                'user_id',
            }
            if any(key in safe_vals for key in vals.keys()):
                self._check_activity_user()

        return super().write(vals)