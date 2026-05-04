# -*- coding: utf-8 -*-
from odoo import api, models


class ResPartnerPaymentTerms(models.Model):
    # Responsibility: pushes credit_limit and property_payment_term_id
    # into the POS frontend store at session start.
    #
    # Why both fields here and not in res_partner_credit.py?
    #   Keeping all _load_pos_data_fields overrides in one file per model
    #   avoids MRO surprises. Both fields are partner fields; one file
    #   owns the partner-level POS data declaration.
    #
    # Why not load total_due (credit) here?
    #   `credit` is a computed aggregation field (SQL sum over move lines).
    #   Bulk-loading it for all partners at session start would execute
    #   one SQL aggregation per partner — prohibitively slow on large datasets.
    #   Instead, `credit` is fetched on-demand via the Gate 3 RPC.
    #
    # ACCOUNTING SAFETY: READ-ONLY. No writes to any model.
    _inherit = 'res.partner'

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Extend the partner fields sent to the POS browser store.

        Appends two fields to the base list:
            credit_limit             — Float; the customer's credit ceiling
            property_payment_term_id — Many2one; required for Gate 1 check

        Calls super() first so any other module that also extends this
        method participates in the chain correctly.

        Args:
            config_id (int): The pos.config primary key for this session.

        Returns:
            list[str]: Extended list of field names to serialise for POS.
        """
        fields = super()._load_pos_data_fields(config_id)

        fields += [
            'credit_limit',           # Gate 2: credit ceiling comparison
            'property_payment_term_id',  # Gate 1: payment terms existence check
        ]

        return fields
