import logging

from odoo import _, api, Command, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class PurchaseReceiptFollowup(models.Model):
    _name = 'purchase.receipt.followup'
    _inherit = ['mail.thread']
    _description = 'Overdue purchase receipt follow-up'
    _rec_name = 'product_id'
    _order = 'first_expected_date, id'
    _check_company_auto = True

    orderpoint_id = fields.Many2one('stock.warehouse.orderpoint', required=True, ondelete='cascade',
                                   readonly=True, check_company=True, index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True)
    product_id = fields.Many2one('product.product', required=True, readonly=True, check_company=True)
    uom_id = fields.Many2one(related='product_id.uom_id')
    location_id = fields.Many2one(related='orderpoint_id.location_id')
    state = fields.Selection([('open', 'Follow-up Needed'), ('replaced', 'Replacement Requested'),
                              ('resolved', 'Resolved')], required=True, default='open', readonly=True, tracking=True)
    move_ids = fields.Many2many('stock.move', string='Overdue Receipt Lines', readonly=True, check_company=True)
    first_expected_date = fields.Datetime(readonly=True)
    overdue_qty = fields.Float(readonly=True, digits='Product Unit of Measure')
    forecast_qty = fields.Float(readonly=True, digits='Product Unit of Measure')
    reliable_forecast_qty = fields.Float(string='Forecast Excluding Overdue Supply', readonly=True,
                                        digits='Product Unit of Measure')
    suggested_qty = fields.Float(string='Suggested Replacement', readonly=True, digits='Product Unit of Measure')
    replacement_order_id = fields.Many2one('purchase.order', readonly=True, check_company=True, copy=False)
    replacement_reason = fields.Text(readonly=True, copy=False)
    replacement_user_id = fields.Many2one('res.users', readonly=True, copy=False)
    replacement_date = fields.Datetime(readonly=True, copy=False)

    _sql_constraints = [
        ('orderpoint_unique', 'unique(orderpoint_id)', 'A follow-up already exists for this reordering rule.'),
    ]

    def _check_purchase_access(self):
        self.ensure_one()
        self.check_access('read')
        if not self.env.user.has_group('purchase.group_purchase_user') or self.company_id not in self.env.companies:
            raise AccessError(_('A purchase user in the follow-up company is required.'))

    @api.model
    def _scan_orderpoints(self, orderpoints, now=None):
        now = now or fields.Datetime.now()
        policy = self.env['purchase.receiving.calendar']
        orderpoints = orderpoints.filtered(
            lambda op: op.active and op.trigger == 'auto' and op.company_id.receipt_followup_enabled
            and policy._is_open(op.company_id, now)
            and any(rule.action == 'buy' for rule in op.rule_ids))
        if not orderpoints:
            return
        _logger.debug('[OVERDUE_RECEIPT][SCAN][START] rule_ids=%s', orderpoints.ids)
        try:
            by_rule = self.env['purchase.overdue.supply']._moves_by_rule(orderpoints, now)
            late_rules = orderpoints.filtered(lambda op: by_rule[op.id])
            snapshots = self.env['purchase.overdue.supply']._replacement_snapshots(late_rules, by_rule)
            existing = {item.orderpoint_id.id: item for item in self.search([('orderpoint_id', 'in', orderpoints.ids)])}
            for op in orderpoints:
                # Serialize cron and POS scans per rule. SQL is only a parameterized row
                # lock; ORM remains authoritative for all reads and writes.
                self.env.cr.execute('SELECT id FROM stock_warehouse_orderpoint WHERE id = %s FOR UPDATE', [op.id])
                alert = existing.get(op.id) or self.search([('orderpoint_id', '=', op.id)], limit=1)
                if alert:
                    alert.invalidate_recordset()
                moves = by_rule[op.id]
                if not moves:
                    if alert and alert.state != 'resolved':
                        alert.write({'state': 'resolved', 'move_ids': [Command.clear()], 'overdue_qty': 0, 'suggested_qty': 0})
                    continue
                values = dict(snapshots[op.id])
                replacement_active = alert and alert.replacement_order_id and alert.replacement_order_id.state != 'cancel'
                values.update({'move_ids': [Command.set(moves.ids)],
                               'first_expected_date': min(moves.mapped('date')),
                               'state': 'replaced' if replacement_active else 'open'})
                if alert:
                    # Avoid write_date/chatter churn when nothing changed.
                    changed = set(alert.move_ids.ids) != set(moves.ids) or any(
                        alert[key] != value for key, value in values.items() if key != 'move_ids')
                    if changed:
                        alert.write(values)
                else:
                    self.create(dict(values, orderpoint_id=op.id, product_id=op.product_id.id,
                                     company_id=op.company_id.id))
            _logger.debug('[OVERDUE_RECEIPT][SCAN][END] rules=%s', len(orderpoints))
        except Exception:
            _logger.exception('[OVERDUE_RECEIPT][SCAN][ERROR] rule_ids=%s', orderpoints.ids)
            raise

    @api.model
    def _cron_scan(self):
        companies = self.env['res.company'].search([('receipt_followup_enabled', '=', True)])
        for company in companies:
            service = self.with_company(company).with_context(allowed_company_ids=[company.id])
            rules = self.env['stock.warehouse.orderpoint'].with_company(company).search([
                ('company_id', '=', company.id), ('trigger', '=', 'auto'), ('active', '=', True)])
            service._scan_orderpoints(rules)

    @api.model
    def get_popup_warning(self, seen_ids=None):
        """Read-only browser endpoint: respect ACLs, company selection and working hours."""
        if not self.env.user.has_group('purchase.group_purchase_user'):
            return False
        now = fields.Datetime.now()
        policy = self.env['purchase.receiving.calendar']
        companies = self.env.companies.filtered(
            lambda company: company.receipt_followup_enabled and policy._is_open(company, now))
        if not companies:
            return False
        alert = self.search([('state', '=', 'open'), ('company_id', 'in', companies.ids),
                             ('orderpoint_id.active', '=', True), ('orderpoint_id.trigger', '=', 'auto'),
                             ('id', 'not in', seen_ids or [])], limit=1)
        if not alert:
            return False
        return {'id': alert.id, 'message': _('Overdue incoming supply for %s. Follow up before relying on it.') % alert.product_id.display_name}

    def action_review(self):
        self._check_purchase_access()
        return self.env['purchase.receipt.replacement']._open(self)

    def action_compare_stock(self):
        self._check_purchase_access()
        return self.env['purchase.variant.stock.compare']._open_for_orderpoint(self.orderpoint_id)

    def action_open_receipts(self):
        self._check_purchase_access()
        return {'type': 'ir.actions.act_window', 'name': _('Overdue Receipts'),
                'res_model': 'stock.picking', 'view_mode': 'list,form',
                'domain': [('id', 'in', self.move_ids.picking_id.ids)]}

    def action_open_purchase_orders(self):
        self._check_purchase_access()
        return {'type': 'ir.actions.act_window', 'name': _('Related Purchase Orders'),
                'res_model': 'purchase.order', 'view_mode': 'list,form',
                'domain': [('id', 'in', self.move_ids.purchase_line_id.order_id.ids)]}
