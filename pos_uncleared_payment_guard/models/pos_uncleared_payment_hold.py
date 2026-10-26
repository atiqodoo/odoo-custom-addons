# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger("pos_uncleared_payment_guard.hold")


class PosUnclearedPaymentHold(models.Model):
    _name = "pos.uncleared.payment.hold"
    _description = "POS Uncleared Payment Hold"
    _inherit = ["mail.thread"]
    _order = "create_date desc, id desc"

    name = fields.Char(default=lambda self: _("New"), copy=False, readonly=True, tracking=True)
    partner_id = fields.Many2one("res.partner", string="Customer", required=True, index=True, ondelete="restrict")
    commercial_partner_id = fields.Many2one("res.partner", required=True, index=True, ondelete="restrict")
    pos_order_id = fields.Many2one("pos.order", string="POS Order", required=True, index=True, ondelete="cascade")
    pos_payment_id = fields.Many2one("pos.payment", string="POS Payment", required=True, index=True, ondelete="cascade")
    payment_method_id = fields.Many2one("pos.payment.method", required=True, index=True, ondelete="restrict")
    pos_config_id = fields.Many2one("pos.config", string="POS", index=True, ondelete="set null")
    pos_session_id = fields.Many2one("pos.session", string="Session", index=True, ondelete="set null")
    company_id = fields.Many2one("res.company", required=True, index=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one("res.currency", required=True)
    amount = fields.Monetary(required=True, currency_field="currency_id", tracking=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("accounting_transfer_seen", "Transfer Seen"),
            ("accounting_cleared", "Accounting Cleared"),
            ("manual_cleared", "Manually Cleared"),
            ("cancelled", "Cancelled"),
        ],
        default="pending",
        required=True,
        index=True,
        tracking=True,
    )
    cleared_by_id = fields.Many2one("res.users", readonly=True, tracking=True)
    cleared_date = fields.Datetime(readonly=True, tracking=True)
    clear_reason = fields.Text(readonly=True)
    clear_reference = fields.Char(readonly=True)
    account_move_id = fields.Many2one(
        "account.move",
        string="Related Accounting Move",
        related="pos_payment_id.account_move_id",
        store=True,
        readonly=True,
    )
    deposit_bank_journal_id = fields.Many2one(
        "account.journal",
        string="Deposit Bank Journal",
        domain="[('type', '=', 'bank')]",
        index=True,
        readonly=True,
        tracking=True,
    )
    mapped_journal_id = fields.Many2one(
        "account.journal",
        string="Mapped Payment Journal",
        related="payment_method_id.journal_id",
        store=True,
        readonly=True,
    )
    mapped_account_id = fields.Many2one(
        "account.account",
        string="Mapped Ledger Account",
        compute="_compute_upg_accounting_accounts",
        store=True,
        readonly=True,
    )
    deposit_bank_account_id = fields.Many2one(
        "account.account",
        string="Deposit Bank Ledger Account",
        compute="_compute_upg_accounting_accounts",
        store=True,
        readonly=True,
    )
    accounting_transfer_move_id = fields.Many2one("account.move", string="Detected Internal Transfer", readonly=True)
    bank_statement_line_id = fields.Many2one("account.bank.statement.line", string="Detected Bank Statement Line", readonly=True)
    accounting_detection_note = fields.Text(string="Accounting Detection Debug", readonly=True)
    cheque_bank = fields.Char(readonly=True, tracking=True)
    cheque_account_number = fields.Char(readonly=True)
    cheque_number = fields.Char(readonly=True, tracking=True)
    cheque_date = fields.Date(readonly=True, tracking=True)
    is_session_open = fields.Boolean(compute="_compute_is_session_open", store=True)

    _sql_constraints = [
        (
            "pos_payment_unique",
            "unique(pos_payment_id)",
            "An uncleared payment hold already exists for this POS payment.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"].sudo()
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = seq.next_by_code("pos.uncleared.payment.hold") or _("New")
        records = super().create(vals_list)
        for record in records:
            _logger.warning(
                "[UPG][Hold] CREATED hold=%s payment=%s order=%s partner=%s amount=%.2f method=%s state=%s",
                record.name,
                record.pos_payment_id.id,
                record.pos_order_id.name,
                record.commercial_partner_id.display_name,
                record.amount,
                record.payment_method_id.display_name,
                record.state,
            )
        return records

    @api.depends(
        "payment_method_id.journal_id.default_account_id",
        "payment_method_id.outstanding_account_id",
        "deposit_bank_journal_id.default_account_id",
    )
    def _compute_upg_accounting_accounts(self):
        for hold in self:
            hold.mapped_account_id = (
                hold.payment_method_id.journal_id.default_account_id
                or hold.payment_method_id.outstanding_account_id
            )
            hold.deposit_bank_account_id = hold.deposit_bank_journal_id.default_account_id

    @api.depends("pos_session_id.state")
    def _compute_is_session_open(self):
        for hold in self:
            hold.is_session_open = hold.pos_session_id.state == "opened"

    def action_open_clear_wizard(self):
        self.ensure_one()
        if self.state not in ("pending", "accounting_transfer_seen"):
            raise UserError(_("Only uncleared holds can be manually cleared."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Clear Uncleared Payment Hold"),
            "res_model": "pos.uncleared.payment.clear.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_hold_id": self.id},
        }

    def action_cancel_hold(self):
        if not self.env.user.has_group("pos_uncleared_payment_guard.group_pos_uncleared_payment_manager"):
            raise UserError(_("Only Uncleared POS Payment Managers can cancel holds."))
        for hold in self:
            if hold.state not in ("pending", "accounting_transfer_seen"):
                continue
            hold.write({
                "state": "cancelled",
                "cleared_by_id": self.env.user.id,
                "cleared_date": fields.Datetime.now(),
                "clear_reason": _("Cancelled by %(user)s", user=self.env.user.display_name),
            })
            _logger.warning("[UPG][Hold] CANCELLED hold=%s by=%s", hold.name, self.env.user.login)

    def action_check_accounting_clearance(self):
        detector = self.env["pos.uncleared.payment.accounting.detector"].sudo()
        for hold in self:
            if hold.state not in ("pending", "accounting_transfer_seen", "manual_cleared", "accounting_cleared"):
                _logger.warning(
                    "[UPG][Hold] SKIP MANUAL ACCOUNTING CHECK hold=%s state=%s",
                    hold.name,
                    hold.state,
                )
                continue
            _logger.warning(
                "[UPG][Hold] MANUAL ACCOUNTING CHECK hold=%s amount=%.2f mapped=%s deposit=%s",
                hold.name,
                hold.amount,
                hold.mapped_account_id.display_name,
                hold.deposit_bank_account_id.display_name,
            )
            detector.upg_check_hold(hold)
        return True

    def _upg_mark_manual_cleared(self, reason, reference=False):
        if not self.env.user.has_group("pos_uncleared_payment_guard.group_pos_uncleared_payment_manager"):
            raise UserError(_("Only Uncleared POS Payment Managers can manually clear holds."))
        for hold in self:
            if hold.state not in ("pending", "accounting_transfer_seen"):
                raise UserError(_("Hold %s is not pending.") % hold.display_name)
            if not reason:
                raise UserError(_("A clearance reason is required."))
            hold.write({
                "state": "manual_cleared",
                "cleared_by_id": self.env.user.id,
                "cleared_date": fields.Datetime.now(),
                "clear_reason": reason,
                "clear_reference": reference,
            })
            hold.message_post(
                body=_("Manually cleared by %(user)s. Reference: %(ref)s<br/>Reason: %(reason)s",
                       user=self.env.user.display_name, ref=reference or "-", reason=reason)
            )
            _logger.warning(
                "[UPG][Hold] MANUAL CLEARED hold=%s user=%s reference=%s reason=%s",
                hold.name,
                self.env.user.login,
                reference,
                reason,
            )

    def _upg_mark_accounting_cleared(self):
        for hold in self:
            if hold.state not in ("pending", "accounting_transfer_seen", "manual_cleared"):
                continue
            previous_state = hold.state
            _logger.debug(
                "[UPG][ACCOUNTING_CLEARANCE][START] hold_id=%s previous_state=%s",
                hold.id, previous_state,
            )
            hold.write({
                "state": "accounting_cleared",
                "cleared_by_id": self.env.user.id,
                "cleared_date": fields.Datetime.now(),
                "clear_reason": _("Detected from read-only accounting reconciliation status."),
                "clear_reference": hold.accounting_transfer_move_id.name or hold.account_move_id.name or hold.clear_reference or "",
            })
            _logger.warning(
                "[UPG][ACCOUNTING_CLEARANCE][END] hold=%s transfer=%s move=%s payment=%s previous_state=%s",
                hold.name,
                hold.accounting_transfer_move_id.name if hold.accounting_transfer_move_id else "N/A",
                hold.account_move_id.name if hold.account_move_id else "N/A",
                hold.pos_payment_id.id,
                previous_state,
            )

    def _upg_mark_transfer_seen(self, move, note=False):
        for hold in self:
            if hold.state not in ("pending", "accounting_transfer_seen", "manual_cleared"):
                continue
            _logger.debug(
                "[UPG][TRANSFER_DETECTION][START] hold_id=%s state=%s move_id=%s",
                hold.id, hold.state, move.id if move else False,
            )
            hold.write({
                "state": "accounting_transfer_seen" if hold.state == "pending" else hold.state,
                "accounting_transfer_move_id": move.id if move else False,
                "accounting_detection_note": note or "",
            })
            _logger.warning(
                "[UPG][TRANSFER_DETECTION][END] hold=%s transfer=%s note=%s",
                hold.name,
                move.name if move else "N/A",
                note,
            )

    @api.model
    def _upg_pending_amounts_for_partner(self, commercial_partner, company_id=False):
        domain = [
            ("commercial_partner_id", "=", commercial_partner.id),
            ("state", "in", ("pending", "accounting_transfer_seen")),
        ]
        if company_id:
            domain.append(("company_id", "=", company_id))
        holds = self.sudo().search(domain)
        open_holds = holds.filtered(lambda h: h.pos_session_id.state == "opened")
        non_open_holds = holds - open_holds
        result = {
            "pending_total": round(sum(holds.mapped("amount")), 2),
            "pending_open_session": round(sum(open_holds.mapped("amount")), 2),
            "pending_accounting_effect": round(sum(non_open_holds.mapped("amount")), 2),
            "hold_count": len(holds),
            "hold_ids": holds.ids,
        }
        _logger.warning(
            "[UPG][Hold] pending amounts partner=%s company=%s result=%s",
            commercial_partner.display_name,
            company_id,
            result,
        )
        return result

    @api.model
    def _upg_detect_for_accounting_lines(self, statement_lines, reason):
        lines = statement_lines.filtered(lambda line: line.company_id and line.journal_id)
        if not lines:
            return self.browse()
        journals = lines.mapped("journal_id")
        companies = lines.mapped("company_id")
        amounts = {round(abs(line.amount or 0.0), 2) for line in lines}
        domain = [
            ("state", "in", ("pending", "accounting_transfer_seen", "manual_cleared", "accounting_cleared")),
            ("company_id", "in", companies.ids),
            "|",
            ("deposit_bank_journal_id", "in", journals.ids),
            ("mapped_journal_id", "in", journals.ids),
        ]
        candidate_holds = self.search(domain)
        if amounts:
            candidate_holds = candidate_holds.filtered(lambda hold: round(abs(hold.amount or 0.0), 2) in amounts)
        _logger.warning(
            "[UPG][Hold] LIVE ACCOUNTING DETECTION reason=%s statement_lines=%s journals=%s candidates=%s",
            reason,
            lines.mapped("display_name"),
            journals.mapped("display_name"),
            candidate_holds.mapped("name"),
        )
        detector = self.env["pos.uncleared.payment.accounting.detector"].sudo()
        cleared = self.browse()
        for hold in candidate_holds:
            try:
                if detector.upg_check_hold(hold):
                    cleared |= hold
            except Exception as exc:
                _logger.exception(
                    "[UPG][Hold] live accounting detection failed reason=%s hold=%s: %s",
                    reason,
                    hold.name,
                    exc,
                )
        if cleared:
            _logger.warning(
                "[UPG][Hold] LIVE ACCOUNTING DETECTION CLEARED reason=%s holds=%s",
                reason,
                cleared.mapped("name"),
            )
        return cleared

    @api.model
    def _upg_detect_for_move_lines(self, move_lines, reason):
        lines = move_lines.filtered(
            lambda line: line.company_id
            and line.account_id
            and line.move_id.state == "posted"
            and line.display_type not in ("line_section", "line_note")
        )
        if not lines:
            return self.browse()

        accounts = lines.mapped("account_id")
        journals = lines.mapped("journal_id")
        companies = lines.mapped("company_id")
        amounts = {round(abs(line.balance or 0.0), 2) for line in lines if round(abs(line.balance or 0.0), 2)}
        domain = [
            ("state", "in", ("pending", "accounting_transfer_seen", "manual_cleared", "accounting_cleared")),
            ("company_id", "in", companies.ids),
            "|",
            "|",
            "|",
            ("mapped_account_id", "in", accounts.ids),
            ("deposit_bank_account_id", "in", accounts.ids),
            ("mapped_journal_id", "in", journals.ids),
            ("deposit_bank_journal_id", "in", journals.ids),
        ]
        candidate_holds = self.search(domain)
        if amounts:
            candidate_holds = candidate_holds.filtered(lambda hold: round(abs(hold.amount or 0.0), 2) in amounts)
        _logger.warning(
            "[UPG][Hold] LIVE MOVE-LINE DETECTION reason=%s lines=%s accounts=%s journals=%s candidates=%s",
            reason,
            lines.ids,
            accounts.mapped("display_name"),
            journals.mapped("display_name"),
            candidate_holds.mapped("name"),
        )

        detector = self.env["pos.uncleared.payment.accounting.detector"].sudo()
        cleared = self.browse()
        for hold in candidate_holds:
            try:
                before_state = hold.state
                if detector.upg_check_hold(hold):
                    cleared |= hold
                elif before_state == "pending" and hold.state == "accounting_transfer_seen":
                    cleared |= hold
            except Exception as exc:
                _logger.exception(
                    "[UPG][Hold] live move-line detection failed reason=%s hold=%s: %s",
                    reason,
                    hold.name,
                    exc,
                )
        if cleared:
            _logger.warning(
                "[UPG][Hold] LIVE MOVE-LINE DETECTION UPDATED reason=%s holds=%s states=%s",
                reason,
                cleared.mapped("name"),
                cleared.mapped("state"),
            )
        return cleared

    @api.model
    def cron_detect_accounting_reconciliation(self):
        holds = self.sudo().search([
            "|", ("state", "in", ("pending", "accounting_transfer_seen", "manual_cleared")),
            "&", ("state", "=", "accounting_cleared"), ("linked_transfer_move_id", "!=", False),
        ])
        _logger.debug("[UPG][CRON_CLEARANCE][START] hold_count=%s", len(holds))
        detector = self.env["pos.uncleared.payment.accounting.detector"].sudo()
        for hold in holds:
            try:
                with self.env.cr.savepoint():
                    detector.upg_check_hold(hold)
            except Exception:
                _logger.exception("[UPG][CRON_CLEARANCE][ERROR] hold_id=%s", hold.id)
        _logger.debug("[UPG][CRON_CLEARANCE][END] hold_count=%s", len(holds))
