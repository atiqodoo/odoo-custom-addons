# -*- coding: utf-8 -*-
from odoo import _
from odoo.exceptions import UserError


DISABLED_PARAM_VALUES = {'0', 'false', 'no', 'off'}


def is_attachment_requirement_enabled(env, config_parameter):
    value = env['ir.config_parameter'].sudo().get_param(config_parameter, 'True')
    return str(value).strip().lower() not in DISABLED_PARAM_VALUES


def has_linked_attachment(record):
    if not record.id:
        return False
    return bool(record.env['ir.attachment'].sudo().search([
        ('res_model', '=', record._name),
        ('res_id', '=', record.id),
    ], limit=1))


def ensure_linked_attachment(records, config_parameter, error_message):
    if not is_attachment_requirement_enabled(records.env, config_parameter):
        return

    missing_records = records.filtered(lambda record: not has_linked_attachment(record))
    if not missing_records:
        return

    names = ', '.join(missing_records.mapped('display_name')[:5])
    if len(missing_records) > 5:
        names = _("%(names)s and %(count)s more", names=names, count=len(missing_records) - 5)
    raise UserError(_("%(message)s\n\nMissing attachment on: %(records)s", message=error_message, records=names))
