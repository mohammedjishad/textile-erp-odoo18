import logging
from odoo import models, api, _

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        for company in companies:
            company.sudo()._create_branch_journals()
        return companies

    def _create_branch_journals(self):
        self.ensure_one()

        # Search for the highest code number across all asset_cash accounts in the database
        self.env.cr.execute("SELECT code_store FROM account_account WHERE account_type = 'asset_cash'")
        res = self.env.cr.fetchall()
        codes = []
        for (code_dict,) in res:
            if code_dict:
                for val in code_dict.values():
                    if val and val.isdigit():
                        codes.append(int(val))
        
        # Prioritize 6-digit codes starting with '1' to stay in the standard range
        prefix_codes = [c for c in codes if str(c).startswith('1') and len(str(c)) == 6]
        if prefix_codes:
            highest_code = max(prefix_codes)
        elif codes:
            highest_code = max(codes)
        else:
            highest_code = 100100

        cash_account_code = highest_code + 10
        bank_account_code = cash_account_code + 10

        for journal_type, prefix in [('cash', 'Cash'), ('bank', 'Bank')]:
            name = '%s - %s' % (prefix, self.name)

            existing = self.env['account.journal'].sudo().search([
                ('name', '=', name),
                ('company_id', '=', self.id),
            ], limit=1)

            if not existing:
                journal = self.env['account.journal'].sudo().create({
                    'name': name,
                    'type': journal_type,
                    'company_id': self.id,
                })
                code = self._unique_code(journal_type)
                # Bypass ORM and write directly to DB
                self.env.cr.execute(
                    "UPDATE account_journal SET code = %s WHERE id = %s",
                    (code, journal.id)
                )
                journal.invalidate_recordset()

                # Fix the code of the default account of the journal
                if journal.default_account_id:
                    account_code = cash_account_code if journal_type == 'cash' else bank_account_code
                    journal.default_account_id.sudo().with_company(self).write({
                        'code': str(account_code),
                    })

                _logger.info('Created journal "%s" (code: %s) for company "%s".', name, code, self.name)

    def _unique_code(self, journal_type):
        base = 10011 if journal_type == 'cash' else 10021
        Journal = self.env['account.journal'].sudo()

        prefix = str(base)[:4]
        journals = Journal.search([('code', 'like', prefix)])

        if journals:
            codes = []
            for j in journals:
                try:
                    codes.append(int(j.code))
                except (ValueError, TypeError):
                    continue
            if codes:
                return str(max(codes) + 1)

        return str(base)