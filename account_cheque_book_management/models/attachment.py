from odoo import api, models, _
from odoo.exceptions import UserError
from .audit import operation


class ChequeEvidenceAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _cheque_copy_payments(self):
        copies = self.filtered(lambda attachment: attachment.res_model == 'account.payment'
            and attachment.res_field == 'cheque_copy' and attachment.res_id)
        return self.env['account.payment'].browse(copies.mapped('res_id')).exists().filtered('cheque_leaf_id')

    @api.model_create_multi
    def create(self, vals_list):
        copies = [values for values in vals_list if values.get('res_model') == 'account.payment'
            and values.get('res_field') == 'cheque_copy' and values.get('res_id')]
        if copies:
            payments = self.env['account.payment'].browse([values['res_id'] for values in copies]).exists().filtered('cheque_leaf_id')
            with operation(payments, 'COPY_ATTACH'):
                payments.check_access('write')
                payments._check_cheque_copy_editable()
                if any(values.get('public') or values.get('access_token') for values in copies):
                    raise UserError(_('Cheque copies must remain private.'))
                return super().create(vals_list)
        return super().create(vals_list)

    def write(self, vals):
        payments = self._cheque_copy_payments()
        # Also protect a new binding: an unrelated attachment cannot be reassigned
        # to overwrite evidence of an already confirmed payment.
        if {'res_model', 'res_id', 'res_field'}.intersection(vals):
            for attachment in self:
                if (vals.get('res_model', attachment.res_model) == 'account.payment'
                        and vals.get('res_field', attachment.res_field) == 'cheque_copy'):
                    payments |= self.env['account.payment'].browse(vals.get('res_id', attachment.res_id)).exists().filtered('cheque_leaf_id')
        if payments:
            with operation(payments, 'COPY_UPDATE'):
                payments.check_access('write')
                payments._check_cheque_copy_editable()
                if vals.get('public') or vals.get('access_token'):
                    raise UserError(_('Cheque copies must remain private.'))
                return super().write(vals)
        return super().write(vals)

    def unlink(self):
        payments = self._cheque_copy_payments()
        if payments:
            with operation(payments, 'COPY_REMOVE'):
                payments.check_access('write')
                payments._check_cheque_copy_editable()
                return super().unlink()
        return super().unlink()
