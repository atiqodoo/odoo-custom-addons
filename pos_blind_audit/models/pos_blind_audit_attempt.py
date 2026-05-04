# -*- coding: utf-8 -*-
import logging
from odoo import fields, models

_logger = logging.getLogger(__name__)


class PosBlindAuditAttempt(models.Model):
    """Audit trail for every cash-count attempt made during a blind-audit close.

    One record is created each time a cashier clicks "Close Register" and the
    discrepancy check fires.  Up to three blocked records are created before the
    system allows an automatic override on the third attempt.

    Records are always created via ``sudo()`` inside the RPC method so that
    cashiers do not need direct model access.
    """

    _name = 'pos.blind.audit.attempt'
    _description = 'POS Blind Audit – Cash Count Attempt Log'
    _order = 'timestamp desc, id desc'
    _rec_name = 'session_id'

    currency_id = fields.Many2one(
        'res.currency',
        related='config_id.currency_id',
        store=True,
        readonly=True,
    )
    session_id = fields.Many2one(
        'pos.session',
        string='Session',
        readonly=True,
        ondelete='cascade',
        index=True,
    )
    config_id = fields.Many2one(
        'pos.config',
        string='POS Register',
        readonly=True,
        store=True,
    )
    cashier_id = fields.Many2one(
        'res.users',
        string='Cashier',
        readonly=True,
        index=True,
    )
    attempt_number = fields.Integer(
        string='Attempt #',
        readonly=True,
        help="Sequential attempt number within this session (1, 2, 3).",
    )
    counted_amount = fields.Float(
        string='Counted Cash',
        digits=(16, 2),
        readonly=True,
        help="Amount the cashier reported counting in the till.",
    )
    expected_amount = fields.Float(
        string='Expected Cash',
        digits=(16, 2),
        readonly=True,
        help="Amount the system calculated should be in the till.",
    )
    cash_out = fields.Float(
        string='Cash Out',
        digits=(16, 2),
        readonly=True,
        help="Amount the cashier entered as cash-out (to safe).",
    )
    discrepancy = fields.Float(
        string='Discrepancy',
        digits=(16, 2),
        readonly=True,
        help="Absolute difference between Counted Cash and Expected Cash.",
    )
    variance_limit = fields.Float(
        string='Allowed Variance',
        digits=(16, 2),
        readonly=True,
        help="Maximum discrepancy allowed at the time of this attempt.",
    )
    outcome = fields.Selection(
        [
            ('blocked', 'Blocked'),
            ('override', 'Auto-Allowed (3rd attempt)'),
        ],
        string='Outcome',
        readonly=True,
        index=True,
    )
    timestamp = fields.Datetime(
        string='Timestamp',
        readonly=True,
        index=True,
    )
