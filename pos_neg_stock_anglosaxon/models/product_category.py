# -*- coding: utf-8 -*-
"""product_category.py

Extends product.category to surface a computed warning flag when the
Price Difference Account (property_account_creditor_price_difference) is
absent on categories that use AVCO costing with automated inventory valuation.

This flag drives a visible warning banner in the product category form view,
allowing accountants / system configurators to discover missing accounts before
they encounter a silent JE-skip at receipt validation time.

The constraint is implemented as a soft warning (logged, not blocking save).
A commented-out ValidationError block is provided for sites that prefer
a hard block.
"""

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ProductCategory(models.Model):
    """Extends product.category with AVCO reconciliation account health checks.

    The ``property_account_creditor_price_difference`` and
    ``property_stock_valuation_account_id`` fields are standard Odoo fields
    inherited from stock_account.  This extension adds computed boolean warning
    flags that the form view uses to render a contextual alert.
    """

    _inherit = 'product.category'

    # ── Warning Flags ─────────────────────────────────────────────────────────

    pos_neg_missing_price_diff_acc = fields.Boolean(
        string='Missing Price Diff Account',
        compute='_compute_pos_neg_account_warnings',
        help=(
            'True when property_account_creditor_price_difference is not set '
            'on an AVCO + automated valuation category.  When True, the module '
            'will skip price difference JE creation and log an ERROR.'
        ),
    )

    pos_neg_missing_stock_val_acc = fields.Boolean(
        string='Missing Stock Valuation Account',
        compute='_compute_pos_neg_account_warnings',
        help=(
            'True when property_stock_valuation_account_id is not set.  '
            'Required for the price difference JE credit/debit.'
        ),
    )

    pos_neg_is_avco_auto = fields.Boolean(
        string='AVCO + Automated Valuation',
        compute='_compute_pos_neg_account_warnings',
        help='True when cost_method=average AND valuation=real_time.',
    )

    # ── Compute ───────────────────────────────────────────────────────────────

    @api.depends(
        'property_cost_method',
        'property_valuation',
        'property_stock_valuation_account_id',
        # NOTE: property_account_creditor_price_difference is intentionally
        # omitted here.  It lives on product.category only when the 'purchase'
        # module is installed.  Adding it to @api.depends would crash module
        # loading if 'purchase' is absent.  We read it defensively at runtime
        # via _get_price_diff_account() instead.
    )
    def _compute_pos_neg_account_warnings(self):
        """Derive account-health warning flags for the form view banner.

        These flags are purely informational — they do not block saves.
        The logic in stock_move._create_price_diff_journal_entry() performs
        its own field validation at runtime and logs errors independently.

        property_account_creditor_price_difference is read via
        _get_price_diff_account() to guard against installations where the
        'purchase' module is not yet loaded.

        Sets:
            pos_neg_is_avco_auto            : True for AVCO + automated categories.
            pos_neg_missing_price_diff_acc  : True when price diff account absent.
            pos_neg_missing_stock_val_acc   : True when stock val account absent.
        """
        for categ in self:
            is_avco = categ.property_cost_method == 'average'
            is_auto = categ.property_valuation == 'real_time'
            categ.pos_neg_is_avco_auto = is_avco and is_auto

            price_diff_acc = categ._get_price_diff_account()
            missing_pd = not price_diff_acc
            missing_sv = not categ.property_stock_valuation_account_id

            categ.pos_neg_missing_price_diff_acc = missing_pd
            categ.pos_neg_missing_stock_val_acc = missing_sv

            if is_avco and is_auto and missing_pd:
                _logger.debug(
                    '[NegStock] ProductCategory "%s" (id=%d): '
                    'property_account_creditor_price_difference is NOT SET.  '
                    'POS negative stock price difference JEs will be skipped.',
                    categ.complete_name, categ.id,
                )

    def _get_price_diff_account(self):
        """Return the price difference account for this category if available.

        In Odoo 18, the field on product.category is
        ``property_account_creditor_price_difference_categ`` (defined by
        ``purchase_stock/models/product.py``).  The product-level field (without
        ``_categ`` suffix) lives on product.template.

        This method checks the category-level field first.  If absent (module not
        installed), it returns False rather than raising AttributeError so that
        all callers degrade gracefully.

        Resolution order matches Odoo's own account_invoice logic:
            categ.property_account_creditor_price_difference_categ

        Returns:
            account.account record | False
        """
        self.ensure_one()
        field_name = 'property_account_creditor_price_difference_categ'
        if field_name not in self._fields:
            _logger.debug(
                '[NegStock] Field "%s" not found on product.category. '
                'purchase_stock module may not be installed.  '
                'Price diff JEs will be skipped.',
                field_name,
            )
            return False
        acc = self[field_name]
        _logger.debug(
            '[NegStock] _get_price_diff_account: categ="%s" → %s',
            self.complete_name,
            acc.code if acc else 'NOT SET',
        )
        return acc

    # ── Constraint (soft — log only) ──────────────────────────────────────────

    @api.constrains('property_cost_method', 'property_valuation')
    def _check_price_diff_account_on_avco_auto(self):
        """Soft constraint: log a warning when an AVCO+auto category lacks the
        price difference account.

        Triggered on cost_method / valuation changes rather than on
        property_account_creditor_price_difference directly to avoid a
        @api.constrains crash when that field doesn't exist yet.

        Does NOT raise ValidationError by default.  Uncomment the raise block
        below to enforce a hard constraint.

        Raises:
            Nothing by default.
        """
        for categ in self:
            is_avco = categ.property_cost_method == 'average'
            is_auto = categ.property_valuation == 'real_time'
            if not (is_avco and is_auto):
                continue

            missing = not categ._get_price_diff_account()
            if missing:
                _logger.warning(
                    '[NegStock] SOFT CONSTRAINT | ProductCategory "%s" (id=%d): '
                    'AVCO + automated valuation but price difference account is empty.  '
                    'POS negative stock reconciliation JEs will NOT be generated '
                    'until this is corrected.',
                    categ.complete_name, categ.id,
                )
                # ── Uncomment to make this a HARD block ───────────────────────
                # from odoo.exceptions import ValidationError
                # raise ValidationError(_(
                #     'Product Category "%s" uses AVCO with automated inventory '
                #     'valuation.  Please set the "Price Difference Account" to '
                #     'enable POS negative stock AVCO reconciliation journal entries.'
                # ) % categ.complete_name)
