"""Thin stock/accounting hooks for posted-bill-owned POS quantities."""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockValuationLayer(models.Model):
    _inherit = 'stock.valuation.layer'

    pos_neg_bill_costing = fields.Boolean(
        string='Cost from posted bill', readonly=True, copy=False, index=True,
        help='New POS oversell managed by posted-bill allocations. Legacy entries are not converted.')
    pos_neg_exposure_qty = fields.Float(readonly=True, copy=False, digits='Product Unit of Measure')

    def write(self, vals):
        if vals.get('pos_negative_origin'):
            for layer in self:
                values = dict(vals)
                if not layer.pos_negative_origin:
                    values.update(
                        pos_neg_bill_costing=layer.remaining_qty < 0 and layer.product_id.cost_method == 'average',
                        pos_neg_exposure_qty=abs(min(layer.remaining_qty, 0)))
                super(StockValuationLayer, layer).write(values)
            return True
        return super().write(vals)

    def _pos_neg_unreserved_quantity(self):
        self.ensure_one()
        allocations = self.env['pos.neg.receipt.allocation'].search([('neg_layer_id', '=', self.id)])
        settled = self.env['pos.neg.bill.settlement'].search([('allocation_id', 'in', allocations.ids)])
        return max(0.0, self.pos_neg_exposure_qty - self.reconciled_qty
                   - sum(allocations.mapped('quantity')) + sum(settled.mapped('quantity')))


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _prepare_fifo_vacuum_valuation_layer_values(self, svl_to_vacuum, corrected_value):
        vals = super()._prepare_fifo_vacuum_valuation_layer_values(svl_to_vacuum, corrected_value)
        if svl_to_vacuum.pos_neg_bill_costing and self.env.context.get('pos_neg_defer_receipt_cost'):
            # Keep core physical quantity bookkeeping, but do not finalize a cost
            # variance from the receipt price. The final negative correction SVL
            # is created by the bill settlement instead.
            vals.update(value=0, description=_('POS cost awaiting posted vendor bill'))
            _logger.debug('[POS_NEG][VACUUM][END] layer_id=%s deferred_receipt_difference=%s',
                          svl_to_vacuum.id, corrected_value)
        return vals

    @api.model
    def _create_fifo_vacuum_anglo_saxon_expense_entries(self, vacuum_pairs):
        return super()._create_fifo_vacuum_anglo_saxon_expense_entries(
            [(vacuum, original) for vacuum, original in vacuum_pairs
             if not (original.pos_neg_bill_costing and self.env.context.get('pos_neg_defer_receipt_cost'))])


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def write(self, vals):
        costing_fields = {'product_id', 'purchase_line_id', 'quantity', 'price_unit',
                          'discount', 'tax_ids', 'product_uom_id', 'currency_id',
                          'balance', 'amount_currency', 'debit', 'credit'}
        if costing_fields.intersection(vals):
            posted = self.filtered(lambda line: line.move_id.state == 'posted')
            if posted and self.env['pos.neg.bill.match'].sudo().search_count([
                    ('bill_line_id', 'in', posted.ids)]):
                raise UserError(_('This posted bill line supplies allocated POS costs. '
                                  'A coordinated accounting correction is required.'))
        return super().write(vals)

    def _pos_neg_posted_unit_cost(self):
        """Use the same posted amount, tax/discount and FX basis as stock_account.

        Custom vendor pricing must affect the posted line amount. A stored
        advisory net_price field is not an alternate accounting authority.
        """
        self.ensure_one()
        if self.move_id.state != 'posted' or self.move_id.move_type != 'in_invoice':
            raise UserError(_('Only posted vendor bills can finalize POS costs.'))
        if self.quantity <= 0 or not self.currency_rate:
            raise UserError(_('A positive billed quantity and a valid accounting exchange rate are required.'))
        return self.product_uom_id._compute_price(
            self._get_gross_unit_price() / self.currency_rate, self.product_id.uom_id)

    def _prepare_pdiff_vals(self, layer, aml, layer_price_unit, out_qty_to_invoice, qty_to_correct):
        """Keep the bill's stock correction for our provisionally valued units.

        Core has already consumed the physical receipt quantity through vacuum,
        but our negative units still carry the original sale value. Treat only
        that owned billed portion as needing a stock correction; do not also
        expense it through core's already-out branch. Ordinary units are intact.
        """
        owned = 0.0
        if self.move_id.move_type == 'in_invoice' and self.purchase_line_id:
            match = self.env['pos.neg.bill.match'].sudo().search([
                ('receipt_move_id', '=', layer.stock_move_id.id), ('bill_line_id', '=', self.id)], limit=1)
            if match:
                owned = min(out_qty_to_invoice, match._owned_out_quantity(out_qty_to_invoice, layer))
        vals = super()._prepare_pdiff_vals(
            layer, aml, layer_price_unit, out_qty_to_invoice - owned, qty_to_correct + owned)
        if owned:
            # Core increments remaining_value for its correction. Owned units
            # have no remaining physical quantity; keep that residual off the
            # receipt's remaining-value pool while retaining the correction SVL.
            unit_cost = aml.product_uom_id._compute_price(
                aml._get_gross_unit_price() / aml.currency_rate, self.product_id.uom_id)
            owned_adjustment = layer.currency_id.round((unit_cost - layer_price_unit) * owned)
            layer.remaining_value -= owned_adjustment
            match.sudo().owned_stock_adjustment += owned_adjustment
            _logger.debug('[POS_NEG][BILL_STOCK_CORRECTION][END] bill_line_id=%s receipt_layer_id=%s owned_quantity=%s',
                          self.id, layer.id, owned)
        return vals


class AccountMove(models.Model):
    _inherit = 'account.move'

    pos_neg_settlement_entry = fields.Boolean(readonly=True, copy=False, index=True)

    def _post(self, soft=True):
        bills = self.filtered(lambda m: m.move_type == 'in_invoice' and m.state != 'posted'
                              and (not soft or m.date <= fields.Date.context_today(m)))
        lines = bills.invoice_line_ids.filtered(lambda l: l.purchase_line_id and l.quantity > 0)
        # A refund needs explicit quantity/cost attribution. Fail before core
        # alters valuation rather than silently leaving settled POS costs stale.
        refunds = self.filtered(lambda m: m.move_type == 'in_refund')
        affected = refunds.invoice_line_ids.purchase_line_id
        if affected and self.env['pos.neg.receipt.allocation'].sudo().search_count([
                ('purchase_line_id', 'in', affected.ids)]):
            raise UserError(_('This credit note affects POS costs managed by posted bills. '
                              'An accountant must resolve the POS cost allocations before posting the credit note.'))
        Match = self.env['pos.neg.bill.match']
        try:
            Match.sudo()._match_purchase_lines(lines.purchase_line_id, posting_bills=bills)
        except Exception:
            _logger.exception('[POS_NEG][BILL_MATCH][ERROR] bill_ids=%s', bills.ids)
            raise
        posted = super()._post(soft=soft)
        actual = posted.filtered(lambda m: m.move_type == 'in_invoice' and m.state == 'posted')
        if actual:
            allocations = self.env['pos.neg.receipt.allocation'].search([
                ('purchase_line_id', 'in', actual.invoice_line_ids.purchase_line_id.ids)])
            _logger.debug('[POS_NEG][BILL_POST][START] bill_ids=%s allocation_ids=%s', actual.ids, allocations.ids)
            allocations._settle_available()
            _logger.debug('[POS_NEG][BILL_POST][END] bill_ids=%s', actual.ids)
        # Soft posting may schedule a draft bill. Its reservation is harmless;
        # settlement always independently verifies state == posted.
        return posted

    def button_draft(self):
        if self.env['pos.neg.bill.match'].sudo().search_count([('bill_line_id.move_id', 'in', self.ids)]):
            raise UserError(_('This bill is allocated to POS negative-stock receipts. '
                              'Resolve its cost allocations before resetting it to draft.'))
        if self.filtered('pos_neg_settlement_entry'):
            raise UserError(_('Posted POS cost settlements cannot be reset independently of their allocations.'))
        return super().button_draft()

    def button_cancel(self):
        if self.filtered('pos_neg_settlement_entry') or self.env['pos.neg.bill.match'].sudo().search_count([
                ('bill_line_id.move_id', 'in', self.ids)]):
            raise UserError(_('Allocated POS costs require a coordinated accounting correction before cancellation.'))
        return super().button_cancel()

    def _reverse_moves(self, default_values_list=None, cancel=False):
        if self.filtered('pos_neg_settlement_entry'):
            raise UserError(_('POS cost settlements require a coordinated accounting correction.'))
        return super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_done(self, cancel_backorder=False):
        returns = self.filtered(lambda m: m.origin_returned_move_id)
        if returns and self.env['pos.neg.receipt.allocation'].sudo().search_count([
                '|', ('receipt_move_id', 'in', returns.origin_returned_move_id.ids),
                ('neg_layer_id.stock_move_id', 'in', returns.origin_returned_move_id.ids)]):
            raise UserError(_('This return affects reserved POS negative-stock costs. '
                              'An accountant must resolve the cost allocations before validating the return.'))
        return super()._action_done(cancel_backorder=cancel_backorder)


class ReconciliationLine(models.Model):
    _inherit = 'pos.neg.reconciliation.line'

    bill_line_id = fields.Many2one('account.move.line', string='Posted Bill Line', readonly=True,
                                  check_company=True, ondelete='restrict')
    settlement_id = fields.Many2one('pos.neg.bill.settlement', readonly=True,
                                   check_company=True, ondelete='restrict')
