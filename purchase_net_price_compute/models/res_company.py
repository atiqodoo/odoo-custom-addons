import logging

from odoo import api, fields, models

from ..utils import validate_png_payload

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    lpo_rubber_stamp_png = fields.Binary(
        string='LPO Rubber Stamp PNG',
        attachment=True,
        copy=False,
        help='Transparent PNG company rubber stamp printed on LPO reports.',
    )
    lpo_rubber_stamp_filename = fields.Char(string='LPO Rubber Stamp Filename', copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('lpo_rubber_stamp_png'):
                validate_png_payload(
                    vals['lpo_rubber_stamp_png'],
                    filename=vals.get('lpo_rubber_stamp_filename'),
                    label='LPO rubber stamp',
                )
        companies = super().create(vals_list)
        for company, vals in zip(companies, vals_list):
            if vals.get('lpo_rubber_stamp_png'):
                _logger.info(
                    "Stored LPO rubber stamp PNG for company id=%s name=%s filename=%s",
                    company.id,
                    company.name,
                    vals.get('lpo_rubber_stamp_filename') or '<none>',
                )
        return companies

    def write(self, vals):
        if vals.get('lpo_rubber_stamp_png'):
            validate_png_payload(
                vals['lpo_rubber_stamp_png'],
                filename=vals.get('lpo_rubber_stamp_filename'),
                label='LPO rubber stamp',
            )

        stamp_was_updated = 'lpo_rubber_stamp_png' in vals
        filename = vals.get('lpo_rubber_stamp_filename')
        result = super().write(vals)

        if stamp_was_updated:
            action = 'cleared' if not vals.get('lpo_rubber_stamp_png') else 'stored'
            for company in self:
                _logger.info(
                    "LPO rubber stamp PNG %s for company id=%s name=%s filename=%s",
                    action,
                    company.id,
                    company.name,
                    filename or company.lpo_rubber_stamp_filename or '<none>',
                )
        return result
