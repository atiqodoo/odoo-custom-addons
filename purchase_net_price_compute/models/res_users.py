import logging

from odoo import api, fields, models

from ..utils import validate_png_payload

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    lpo_signature_png = fields.Binary(
        string='LPO Signature PNG',
        attachment=True,
        copy=False,
        help='Transparent PNG signature used on LPO printouts and available for related models.',
    )
    lpo_signature_filename = fields.Char(string='LPO Signature Filename', copy=False)

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ['lpo_signature_png', 'lpo_signature_filename']

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ['lpo_signature_png', 'lpo_signature_filename']

    @api.model
    def _validate_lpo_signature_png_payload(self, payload, filename=None):
        return validate_png_payload(payload, filename=filename, label='LPO signature')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('lpo_signature_png'):
                self._validate_lpo_signature_png_payload(
                    vals['lpo_signature_png'],
                    vals.get('lpo_signature_filename'),
                )
        users = super().create(vals_list)
        for user, vals in zip(users, vals_list):
            if vals.get('lpo_signature_png'):
                _logger.info(
                    "Stored LPO signature PNG for user id=%s login=%s filename=%s",
                    user.id,
                    user.login,
                    vals.get('lpo_signature_filename') or '<none>',
                )
        return users

    def write(self, vals):
        if 'lpo_signature_png' in vals and vals.get('lpo_signature_png'):
            self._validate_lpo_signature_png_payload(
                vals['lpo_signature_png'],
                vals.get('lpo_signature_filename'),
            )

        signature_was_updated = 'lpo_signature_png' in vals
        filename = vals.get('lpo_signature_filename')
        result = super().write(vals)

        if signature_was_updated:
            action = 'cleared' if not vals.get('lpo_signature_png') else 'stored'
            for user in self:
                _logger.info(
                    "LPO signature PNG %s for user id=%s login=%s filename=%s",
                    action,
                    user.id,
                    user.login,
                    filename or user.lpo_signature_filename or '<none>',
                )
        return result
