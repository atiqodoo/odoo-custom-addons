# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-
# © 2025 Sensible Consulting Services (<https://sensiblecs.com/>)
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class SblAppGateLog(models.Model):
    _name = 'sbl.app.gate.log'
    _description = 'App Gate Access Log'
    _order = 'create_date desc, id desc'

    app_xmlid = fields.Char(string='App XML ID', index=True)
    app_name = fields.Char(string='App Name')
    employee_id = fields.Many2one('hr.employee', string='Employee', ondelete='set null', index=True)
    user_id = fields.Many2one('res.users', string='User', ondelete='set null', index=True)
    status = fields.Selection(
        [('success', 'Success'), ('failed', 'Failed')],
        string='Status',
        required=True,
        index=True,
    )
    failure_reason = fields.Char(string='Failure Reason')
    # create_date auto-populated by ORM
