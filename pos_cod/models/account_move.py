# -*- coding: utf-8 -*-
import logging
from odoo import fields, models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    is_cod_entry = fields.Boolean(
        string='COD Entry',
        default=False,
        copy=False,
        help=(
            'True on the confirmation journal entry created when a COD order is dispatched. '
            'Used by pos_credit_limit.get_credit_info() to exclude this AR balance from '
            'the customer credit-limit calculation, keeping COD and credit-sale pools separate. '
            'Also used to identify the AR debit line for reconciliation when COD is paid.'
        ),
    )
