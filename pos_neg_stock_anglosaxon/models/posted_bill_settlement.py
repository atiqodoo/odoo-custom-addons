"""Quantity allocations and posted-bill costing for new POS oversells.

Receipt ownership is immutable. Billing consumes receipt capacity (including
ordinary, non-negative units) before the owned quantities are costed. This is
deliberately separate from stock on hand and from the legacy reconciliation log.
"""
import logging
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class PosNegReceiptAllocation(models.Model):
    _name = 'pos.neg.receipt.allocation'
    _description = 'POS Negative Stock Receipt Allocation'
    _order = 'id'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True)
    neg_layer_id = fields.Many2one('stock.valuation.layer', required=True, readonly=True,
                                  check_company=True, ondelete='restrict', index=True)
    receipt_move_id = fields.Many2one('stock.move', required=True, readonly=True,
                                     check_company=True, ondelete='restrict', index=True)
    product_id = fields.Many2one(related='neg_layer_id.product_id', store=True)
    purchase_line_id = fields.Many2one(related='receipt_move_id.purchase_line_id', store=True)
    quantity = fields.Float(required=True, readonly=True, digits='Product Unit of Measure')
    receipt_offset = fields.Float(readonly=True, digits='Product Unit of Measure')
    settled_quantity = fields.Float(compute='_compute_settled_quantity')
    state = fields.Selection([('waiting_bill', 'Awaiting posted bill'),
                              ('partial', 'Partly finalized'), ('done', 'Finalized'),
                              ('missing_link', 'Missing purchase linkage'),
                              ('error', 'Needs attention')], compute='_compute_settled_quantity')
    error_message = fields.Char(readonly=True)

    _sql_constraints = [
        ('layer_receipt_unique', 'unique(neg_layer_id, receipt_move_id)',
         'A receipt can reserve a negative layer only once.'),
        ('positive_quantity', 'check(quantity > 0 AND receipt_offset >= 0)',
         'Allocated quantities must be positive.'),
    ]

    def _compute_settled_quantity(self):
        grouped = self.env['pos.neg.bill.settlement']._read_group(
            [('allocation_id', 'in', self.ids)], ['allocation_id'], ['quantity:sum'])
        quantities = {allocation.id: qty for allocation, qty in grouped}
        for allocation in self:
            qty = quantities.get(allocation.id, 0.0)
            allocation.settled_quantity = qty
            allocation.state = (
                'error' if allocation.error_message else
                'missing_link' if not allocation.purchase_line_id else
                'done' if qty >= allocation.quantity - 1e-9 else
                'partial' if qty else 'waiting_bill')

    @api.model
    def _reserve_receipt(self, move, capacity, consumed=None):
        """Reserve before core vacuum, respecting non-POS negative layers too."""
        if capacity <= 0:
            return self.browse()
        consumed = consumed if consumed is not None else {}
        _logger.debug('[POS_NEG][RESERVE][START] receipt_move_id=%s capacity=%s', move.id, capacity)
        layers = self.env['stock.valuation.layer'].search([
            ('product_id', '=', move.product_id.id), ('company_id', '=', move.company_id.id),
            ('remaining_qty', '<', 0), ('stock_move_id', '!=', False),
        ], order='create_date, id')
        if move.product_id.lot_valuated:
            layers = layers.filtered(lambda layer: layer.lot_id in move.move_line_ids.lot_id)
        if not layers:
            return self.browse()
        # Row locks serialize receipts/adjustments for the same negative layers.
        self.env.cr.execute('SELECT id FROM stock_valuation_layer WHERE id IN %s ORDER BY id FOR UPDATE',
                            [tuple(layers.ids)])
        layers.invalidate_recordset(['reconciled_qty', 'remaining_qty'])
        existing = self.search([('neg_layer_id', 'in', layers.ids)])
        if existing.filtered(lambda a: a.receipt_move_id == move):
            return existing.filtered(lambda a: a.receipt_move_id == move)
        created = self.browse()
        slots = [(False, capacity, 0.0)]
        if move.product_id.lot_valuated:
            # Same insertion order and UoM as stock.move._get_in_svl_vals.
            lot_quantities = defaultdict(float)
            for line in move._get_in_move_lines():
                lot_quantities[line.lot_id.id] += line.quantity_product_uom
            slots, offset = [], 0.0
            for lot_id, quantity in lot_quantities.items():
                slots.append((lot_id, quantity, offset))
                offset += quantity
        for lot_id, slot_quantity, slot_offset in slots:
            remaining_slot = slot_quantity
            for layer in layers:
                if lot_id and layer.lot_id.id != lot_id:
                    continue
                remaining = abs(layer.remaining_qty) - consumed.get(layer.id, 0.0)
                quantity = min(remaining_slot, max(remaining, 0.0))
                if quantity <= 1e-9:
                    continue
                consumed[layer.id] = consumed.get(layer.id, 0.0) + quantity
                if layer.pos_neg_bill_costing:
                    created |= self.create({
                        'company_id': move.company_id.id, 'neg_layer_id': layer.id,
                        'receipt_move_id': move.id, 'quantity': quantity,
                        'receipt_offset': slot_offset + slot_quantity - remaining_slot,
                    })
                remaining_slot -= quantity
                if remaining_slot <= 1e-9:
                    break
        _logger.debug('[POS_NEG][RESERVE][END] receipt_move_id=%s allocation_ids=%s quantity=%s',
                      move.id, created.ids, sum(created.mapped('quantity')))
        return created

    def action_retry(self):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_('Only accounting managers can retry POS cost finalization.'))
        self.check_access('read')
        _logger.debug('[POS_NEG][RETRY][START] allocation_ids=%s user_id=%s', self.ids, self.env.uid)
        self.env['pos.neg.bill.match']._match_purchase_lines(self.purchase_line_id)
        self._settle_available()
        _logger.debug('[POS_NEG][RETRY][END] allocation_ids=%s', self.ids)
        return True

    def _settle_available(self):
        for allocation in self:
            allocation = allocation.with_company(allocation.company_id)
            matches = self.env['pos.neg.bill.match'].search([
                ('receipt_move_id', '=', allocation.receipt_move_id.id),
                ('bill_line_id.move_id.state', '=', 'posted')], order='id')
            for match in matches:
                start = max(allocation.receipt_offset, match.receipt_offset)
                end = min(allocation.receipt_offset + allocation.quantity,
                          match.receipt_offset + match.quantity)
                quantity = max(end - start, 0.0)
                if quantity <= 1e-9:
                    continue
                try:
                    with self.env.cr.savepoint():
                        self.env['pos.neg.bill.settlement']._finalize(allocation, match, quantity)
                        allocation.sudo().error_message = False
                except Exception:
                    _logger.exception('[POS_NEG][FINALIZE][ERROR] allocation_id=%s match_id=%s',
                                      allocation.id, match.id)
                    allocation.sudo().error_message = _('Cost finalization failed. Review server logs and retry.')


class PosNegBillMatch(models.Model):
    _name = 'pos.neg.bill.match'
    _description = 'Vendor Bill Quantity Allocated to Receipt'
    _check_company_auto = True
    _order = 'id'

    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True)
    receipt_move_id = fields.Many2one('stock.move', required=True, readonly=True,
                                     check_company=True, ondelete='restrict', index=True)
    bill_line_id = fields.Many2one('account.move.line', required=True, readonly=True,
                                  check_company=True, ondelete='restrict', index=True)
    purchase_line_id = fields.Many2one(related='receipt_move_id.purchase_line_id', store=True)
    quantity = fields.Float(required=True, readonly=True, digits='Product Unit of Measure')
    receipt_offset = fields.Float(readonly=True, digits='Product Unit of Measure')
    bill_offset = fields.Float(readonly=True, digits='Product Unit of Measure')
    owned_stock_adjustment = fields.Float(readonly=True, digits='Account',
        help='Bill-to-receipt stock correction already generated by stock_account for owned units.')

    _sql_constraints = [
        ('receipt_bill_unique', 'unique(receipt_move_id, bill_line_id)',
         'A bill line can be matched to a receipt only once.'),
        ('positive_quantity', 'check(quantity > 0)', 'Matched quantities must be positive.'),
    ]

    @api.model
    def _match_purchase_lines(self, purchase_lines, posting_bills=None):
        """Allocate all billed units, not just oversold units, under a PO-line lock.

        During _post, include the bills being posted so Odoo's own price-difference
        hook can identify our portion before it generates correction layers.
        """
        if not purchase_lines:
            return
        _logger.debug('[POS_NEG][BILL_MATCH][START] purchase_line_ids=%s', purchase_lines.ids)
        created_count = 0
        purchase_lines.check_access('read')
        self.env.cr.execute('SELECT id FROM purchase_order_line WHERE id IN %s ORDER BY id FOR UPDATE',
                            [tuple(purchase_lines.ids)])
        for po_line in purchase_lines:
            if not self.env['pos.neg.receipt.allocation'].search_count([
                    ('purchase_line_id', '=', po_line.id)]):
                continue
            receipts = po_line.move_ids.filtered(lambda m:
                m.state == 'done' and m.location_id.usage == 'supplier'
                and m.location_dest_id.usage == 'internal' and not m.origin_returned_move_id
            ).sorted(lambda m: (m.date, m.id))
            lines = po_line.invoice_lines.filtered(lambda line:
                line.move_id.move_type == 'in_invoice' and line.display_type == 'product'
                and line.quantity > 0 and line.product_id == po_line.product_id
                and (line.move_id.state == 'posted' or line.move_id in (posting_bills or self.env['account.move']))
            ).sorted(lambda line: (line.move_id.id, line.id))
            existing = self.search([('purchase_line_id', '=', po_line.id)])
            receipt_used, bill_used = defaultdict(float), defaultdict(float)
            for match in existing:
                receipt_used[match.receipt_move_id.id] += match.quantity
                bill_used[match.bill_line_id.id] += match.quantity
            for line in lines:
                billed = line.product_uom_id._compute_quantity(line.quantity, line.product_id.uom_id, round=False)
                for receipt in receipts:
                    received = receipt.product_uom._compute_quantity(receipt.quantity, receipt.product_id.uom_id, round=False)
                    quantity = min(billed - bill_used[line.id], received - receipt_used[receipt.id])
                    if quantity <= 1e-9:
                        continue
                    old_match = existing.filtered(lambda m: m.bill_line_id == line and m.receipt_move_id == receipt)
                    # The same pair can grow only when a bill's receipt completes in
                    # separate moves; completed moves themselves are immutable here.
                    if old_match:
                        _logger.error('[POS_NEG][BILL_MATCH][ERROR] bill_line_id=%s receipt_move_id=%s reason=changed_quantities',
                                      line.id, receipt.id)
                        raise UserError(_('Receipt/bill quantities changed after allocation. Accounting review is required.'))
                    self.create({'company_id': po_line.company_id.id, 'receipt_move_id': receipt.id,
                                 'bill_line_id': line.id, 'quantity': quantity,
                                 'receipt_offset': receipt_used[receipt.id], 'bill_offset': bill_used[line.id]})
                    created_count += 1
                    receipt_used[receipt.id] += quantity
                    bill_used[line.id] += quantity
        _logger.debug('[POS_NEG][BILL_MATCH][END] purchase_line_ids=%s created=%s',
                      purchase_lines.ids, created_count)

    def _owned_out_quantity(self, out_quantity, receipt_layer=None):
        self.ensure_one()
        allocations = self.env['pos.neg.receipt.allocation'].search([
            ('receipt_move_id', '=', self.receipt_move_id.id)])
        start = self.receipt_offset
        if receipt_layer:
            earlier_layers = self.receipt_move_id.stock_valuation_layer_ids.filtered(
                lambda layer: layer.quantity > 0 and layer.id < receipt_layer.id)
            start = max(start, sum(earlier_layers.mapped('quantity')))
        end = min(self.receipt_offset + self.quantity, start + out_quantity)
        return sum(max(0.0, min(a.receipt_offset + a.quantity, end)
                       - max(a.receipt_offset, start)) for a in allocations)


class PosNegBillSettlement(models.Model):
    _name = 'pos.neg.bill.settlement'
    _description = 'Finalized POS Negative Stock Bill Cost'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True)
    allocation_id = fields.Many2one('pos.neg.receipt.allocation', required=True, readonly=True,
                                   check_company=True, ondelete='restrict', index=True)
    match_id = fields.Many2one('pos.neg.bill.match', required=True, readonly=True,
                              check_company=True, ondelete='restrict', index=True)
    bill_line_id = fields.Many2one(related='match_id.bill_line_id', store=True)
    quantity = fields.Float(readonly=True, digits='Product Unit of Measure')
    unit_cost = fields.Float(readonly=True, digits='Product Price')
    price_diff_move_id = fields.Many2one('account.move', readonly=True, check_company=True, ondelete='restrict')
    valuation_layer_id = fields.Many2one('stock.valuation.layer', readonly=True, check_company=True, ondelete='restrict')
    receipt_adjustment_move_id = fields.Many2one('account.move', readonly=True, check_company=True, ondelete='restrict')

    _sql_constraints = [('allocation_match_unique', 'unique(allocation_id, match_id)',
                         'This billed quantity has already been finalized.')]

    @api.model
    def _post_stock_delta(self, parent, bill_line, amount, counterpart, label, link_bill=False):
        """One authoritative JE/SVL pair for a signed stock-value correction."""
        company = parent.company_id
        if company.currency_id.is_zero(amount):
            return self.env['account.move'], self.env['stock.valuation.layer']
        category = parent.product_id.with_company(company).categ_id
        stock_account, journal = category.property_stock_valuation_account_id, category.property_stock_journal
        if not counterpart or not stock_account or not journal:
            raise UserError(_('Configure the category correction accounts and stock journal.'))
        entry = self.env['account.move'].with_company(company).create({
            'move_type': 'entry', 'journal_id': journal.id, 'company_id': company.id,
            'date': max(fields.Date.context_today(self), bill_line.move_id.date),
            'ref': label, 'pos_neg_settlement_entry': True,
            'line_ids': [(0, 0, {
                'account_id': account.id, 'name': label, 'product_id': parent.product_id.id,
                'partner_id': bill_line.move_id.commercial_partner_id.id,
                'debit': max(balance, 0), 'credit': max(-balance, 0),
            }) for account, balance in [(stock_account, amount), (counterpart, -amount)]],
        })
        entry._post()  # Accounting permissions are never elevated.
        correction = self.env['stock.valuation.layer'].sudo().create({
            'company_id': company.id, 'product_id': parent.product_id.id,
            'quantity': 0, 'unit_cost': 0, 'value': amount,
            'remaining_qty': 0, 'remaining_value': 0,
            'stock_valuation_layer_id': parent.id, 'stock_move_id': parent.stock_move_id.id,
            'lot_id': parent.lot_id.id, 'account_move_id': entry.id,
            'account_move_line_id': bill_line.id if link_bill else False, 'description': label,
        })
        return entry, correction

    @api.model
    def _ensure_receipt_basis(self, allocation, match, quantity, unit_cost):
        """Catch up a pre-billed receipt without repeating core bill corrections."""
        layer = allocation.neg_layer_id.sudo()
        receipt_layer = allocation.receipt_move_id.sudo().stock_valuation_layer_ids.filtered(
            lambda svl: svl.quantity > 0 and (not layer.product_id.lot_valuated or svl.lot_id == layer.lot_id))
        if len(receipt_layer) != 1:
            raise UserError(_('Cannot identify one receipt valuation layer for this allocation.'))
        owned_quantity = match.sudo()._owned_out_quantity(match.quantity)
        applied = match.owned_stock_adjustment * quantity / owned_quantity if owned_quantity else 0.0
        amount = layer.currency_id.round(quantity * (unit_cost - receipt_layer.unit_cost) - applied)
        if layer.currency_id.is_zero(amount):
            return self.env['account.move']
        bill_line = match.bill_line_id
        input_account = self.env['account.account'].browse(allocation.receipt_move_id.sudo()._get_src_account(
            layer.product_id.product_tmpl_id.get_product_accounts(fiscal_pos=bill_line.move_id.fiscal_position_id)))
        entry, _correction = self._post_stock_delta(
            receipt_layer, bill_line, amount, input_account,
            _('POS posted bill receipt correction: %s', bill_line.move_id.name), link_bill=True)
        return entry

    @api.model
    def _refresh_average_cost(self, layer):
        product = layer.product_id.with_company(layer.company_id)
        if product.quantity_svl:
            product.sudo().with_context(disable_auto_svl=True).standard_price = product.value_svl / product.quantity_svl
        if product.lot_valuated and layer.lot_id and layer.lot_id.quantity_svl:
            lot = layer.lot_id.with_company(layer.company_id)
            lot.sudo().with_context(disable_auto_svl=True).standard_price = lot.value_svl / lot.quantity_svl

    @api.model
    def _finalize(self, allocation, match, quantity):
        # SQL is used only for a row lock; accounting/persistence use the ORM.
        self.env.cr.execute('SELECT id FROM pos_neg_receipt_allocation WHERE id = %s FOR UPDATE',
                            [allocation.id])
        if self.search_count([('allocation_id', '=', allocation.id), ('match_id', '=', match.id)]):
            return
        bill_line = match.bill_line_id
        bill_line.check_access('read')
        allocation.check_access('read')
        if bill_line.move_id.state != 'posted' or bill_line.move_id.move_type != 'in_invoice':
            raise UserError(_('A posted vendor bill is required.'))
        # Derived valuation bookkeeping, as in stock_account; journal posting
        # below deliberately retains the caller's accounting permissions.
        layer = allocation.neg_layer_id.sudo()
        self.env.cr.execute('SELECT id FROM stock_valuation_layer WHERE id = %s FOR UPDATE', [layer.id])
        layer.invalidate_recordset(['reconciled_qty'])
        company = allocation.company_id
        currency = company.currency_id
        unit_cost = bill_line._pos_neg_posted_unit_cost()
        difference = currency.round(quantity * (unit_cost - layer.unit_cost))
        _logger.debug('[POS_NEG][FINALIZE][START] allocation_id=%s bill_line_id=%s quantity=%s difference=%s',
                      allocation.id, bill_line.id, quantity, difference)
        receipt_adjustment = self._ensure_receipt_basis(allocation, match, quantity, unit_cost)
        label = _('POS posted bill price difference: %s / %s',
                  bill_line.move_id.name, layer.product_id.display_name)
        journal_entry, correction = self._post_stock_delta(
            layer, bill_line, -difference,
            layer.product_id.with_company(company).categ_id._get_price_diff_account(), label)
        if journal_entry or receipt_adjustment:
            self._refresh_average_cost(layer)
        settlement = self.sudo().create({'company_id': company.id, 'allocation_id': allocation.id,
                                  'match_id': match.id, 'quantity': quantity, 'unit_cost': unit_cost,
                                  'price_diff_move_id': journal_entry.id, 'valuation_layer_id': correction.id,
                                  'receipt_adjustment_move_id': receipt_adjustment.id})
        layer.sudo().reconciled_qty += quantity
        if journal_entry:
            layer.sudo().price_diff_move_ids = [(4, journal_entry.id)]
        self.env['pos.neg.reconciliation.line'].sudo().create({
            'neg_layer_id': layer.id, 'source_picking_id': allocation.receipt_move_id.picking_id.id,
            'reconcile_qty': quantity, 'original_cost': layer.unit_cost, 'incoming_cost': unit_cost,
            'price_diff_move_id': journal_entry.id, 'reconcile_type': 'receipt',
            'bill_line_id': bill_line.id, 'settlement_id': settlement.id,
            'note': _('Finalized from posted bill %s. No purchase-order price fallback.', bill_line.move_id.name),
        })
        _logger.debug('[POS_NEG][FINALIZE][END] settlement_id=%s journal_entry_id=%s',
                      settlement.id, journal_entry.id)
