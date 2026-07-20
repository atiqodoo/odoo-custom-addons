# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    has_combined_lpo_billable_qty = fields.Boolean(
        string='Has Combined LPO Billable Quantity',
        compute='_compute_has_combined_lpo_billable_qty',
        search='_search_has_combined_lpo_billable_qty',
    )

    @api.depends(
        'order_line.qty_received',
        'order_line.qty_invoiced',
        'order_line.product_id',
        'order_line.display_type',
        'order_line.is_promotion_foc',
    )
    def _compute_has_combined_lpo_billable_qty(self):
        for order in self:
            order.has_combined_lpo_billable_qty = any(
                line._get_combined_lpo_billable_qty() > 0
                for line in order.order_line
            )

    def _search_has_combined_lpo_billable_qty(self, operator, value):
        if operator not in ('=', '!='):
            raise NotImplementedError(_('Unsupported operator for combined LPO billable search.'))
        want_true = (operator == '=' and bool(value)) or (operator == '!=' and not bool(value))
        orders = self.search([
            ('state', 'in', ('purchase', 'done')),
            ('invoice_status', '=', 'to invoice'),
        ])
        eligible_ids = [
            order.id
            for order in orders
            if any(line._get_combined_lpo_billable_qty() > 0 for line in order.order_line)
        ]
        _logger.info(
            '[CLPO_ELIGIBILITY] search_billable operator=%s value=%s want_true=%s '
            'candidate_count=%s eligible_ids=%s',
            operator,
            value,
            want_true,
            len(orders),
            eligible_ids,
        )
        return [('id', 'in' if want_true else 'not in', eligible_ids)]

    def _validate_combined_lpo_selection(self):
        orders = self.filtered(lambda order: order.state in ('purchase', 'done'))
        if not orders:
            raise ValidationError(_('Select at least one confirmed LPO.'))
        if len(orders) != len(self):
            invalid = self - orders
            _logger.warning(
                '[CLPO_OPEN] blocked reason=invalid_state purchase_ids=%s states=%s user_id=%s',
                invalid.ids,
                [(order.name, order.state) for order in invalid],
                self.env.user.id,
            )
            raise ValidationError(_(
                'Combined LPO billing only supports confirmed or done purchase orders. '
                'Invalid selections: %s'
            ) % ', '.join(invalid.mapped('name')))

        partners = orders.mapped('partner_id.commercial_partner_id')
        companies = orders.mapped('company_id')
        currencies = orders.mapped('currency_id')
        profiles = set()
        for order in orders:
            profiles.add(order.partner_id.get_vendor_invoice_profile())

        _logger.info(
            '[CLPO_OPEN] selection_validate purchase_ids=%s vendor_ids=%s company_ids=%s '
            'currency_ids=%s profiles=%s user_id=%s',
            orders.ids,
            partners.ids,
            companies.ids,
            currencies.ids,
            sorted(profiles),
            self.env.user.id,
        )

        if len(partners) != 1:
            raise ValidationError(_('Combined LPO billing requires one vendor/commercial partner.'))
        if len(companies) != 1:
            raise ValidationError(_('Combined LPO billing requires one company.'))
        if len(currencies) != 1:
            raise ValidationError(_('Combined LPO billing requires one currency.'))
        if len(profiles) != 1:
            raise ValidationError(_('Combined LPO billing requires one vendor invoice profile.'))
        not_billable = orders.filtered(lambda order: not order.has_combined_lpo_billable_qty)
        if not_billable:
            _logger.warning(
                '[CLPO_OPEN] blocked reason=no_billable_qty purchase_ids=%s names=%s user_id=%s',
                not_billable.ids,
                not_billable.mapped('name'),
                self.env.user.id,
            )
            raise ValidationError(_(
                'These LPOs are already fully billed or have no received uninvoiced quantities: %s'
            ) % ', '.join(not_billable.mapped('name')))
        return orders

    def action_create_combined_lpo_bill_wizard(self):
        orders = self._validate_combined_lpo_selection()
        partner = orders[:1].partner_id.commercial_partner_id
        profile = orders[:1].partner_id.get_vendor_invoice_profile()

        wizard = self.env['combined.lpo.bill.wizard'].create({
            'partner_id': partner.id,
            'purchase_ids': [(6, 0, orders.ids)],
            'company_id': orders[:1].company_id.id,
            'currency_id': orders[:1].currency_id.id,
            'vendor_invoice_profile': profile,
        })
        wizard.action_reload_lines()
        _logger.info(
            '[CLPO_OPEN] wizard_created wizard_id=%s vendor_id=%s purchase_ids=%s line_count=%s',
            wizard.id,
            partner.id,
            orders.ids,
            len(wizard.line_ids),
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Combined LPO Bill'),
            'res_model': 'combined.lpo.bill.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }
