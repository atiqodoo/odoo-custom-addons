# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

_logger = logging.getLogger("pos_cod_deposit_settlement.audit")


class PosCodDepositApplication(models.Model):
    _name = "pos.cod.deposit.application"
    _description = "COD Customer Deposit Application"
    _inherit = ["mail.thread"]
    _order = "create_date desc, id desc"

    name = fields.Char(default=lambda self: _("New"), required=True, readonly=True, copy=False, index=True)
    operation_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    reservation_id = fields.Many2one(
        "pos.cod.session.deposit.reservation",
        string="Source Same-Session Reservation",
        readonly=True,
        copy=False,
        ondelete="restrict",
        index=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("posted", "Posted"), ("cancelled", "Cancelled")],
        default="draft",
        required=True,
        readonly=True,
        tracking=True,
        index=True,
    )
    order_id = fields.Many2one("pos.order", required=True, readonly=True, ondelete="restrict", index=True)
    partner_id = fields.Many2one("res.partner", required=True, readonly=True, ondelete="restrict", index=True)
    commercial_partner_id = fields.Many2one("res.partner", required=True, readonly=True, ondelete="restrict", index=True)
    company_id = fields.Many2one("res.company", required=True, readonly=True, index=True)
    currency_id = fields.Many2one("res.currency", required=True, readonly=True)
    pos_config_id = fields.Many2one("pos.config", required=True, readonly=True, ondelete="restrict")
    pos_session_id = fields.Many2one("pos.session", required=True, readonly=True, ondelete="restrict")
    cashier_id = fields.Many2one("res.users", required=True, readonly=True, default=lambda self: self.env.user)
    requested_amount = fields.Monetary(required=True, readonly=True, currency_field="currency_id")
    amount = fields.Monetary(required=True, readonly=True, currency_field="currency_id", tracking=True)
    deposit_before = fields.Monetary(readonly=True, currency_field="currency_id")
    deposit_after = fields.Monetary(readonly=True, currency_field="currency_id")
    cod_open_before = fields.Monetary(readonly=True, currency_field="currency_id")
    cod_open_after = fields.Monetary(readonly=True, currency_field="currency_id")
    default_receivable_account_id = fields.Many2one("account.account", required=True, readonly=True)
    cod_receivable_account_id = fields.Many2one("account.account", required=True, readonly=True)
    transfer_journal_id = fields.Many2one("account.journal", required=True, readonly=True)
    move_id = fields.Many2one("account.move", readonly=True, copy=False, ondelete="restrict")
    transaction_log_id = fields.Many2one(
        "pos.cod.collection",
        string="COD Deposit Transaction Log",
        readonly=True,
        copy=False,
        ondelete="restrict",
    )
    source_credit_line_ids = fields.Many2many(
        "account.move.line",
        "pos_cod_deposit_application_source_rel",
        "application_id",
        "move_line_id",
        string="Source Customer Credits",
        readonly=True,
        copy=False,
    )
    source_pos_invoice_debit_line_ids = fields.Many2many(
        "account.move.line",
        "pos_cod_deposit_application_pos_debit_rel",
        "application_id",
        "move_line_id",
        string="Netted POS Invoice Debits",
        readonly=True,
        copy=False,
    )
    cod_source_line_ids = fields.Many2many(
        "account.move.line",
        "pos_cod_deposit_application_cod_rel",
        "application_id",
        "move_line_id",
        string="Source COD Receivables",
        readonly=True,
        copy=False,
    )
    bridge_receivable_line_id = fields.Many2one("account.move.line", readonly=True, copy=False)
    bridge_cod_line_id = fields.Many2one("account.move.line", readonly=True, copy=False)
    debug_snapshot = fields.Text(readonly=True, copy=False)

    _sql_constraints = [
        ("operation_uuid_company_unique", "unique(company_id, operation_uuid)", "This COD deposit operation was already processed."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"].sudo()
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = sequence.next_by_code("pos.cod.deposit.application") or _("New")
        records = super().create(vals_list)
        for record in records:
            _logger.warning(
                "[COD-DEPOSIT][AUDIT] CREATED application=%s operation=%s order=%s partner=%s amount=%.2f state=%s",
                record.name, record.operation_uuid, record.order_id.name,
                record.commercial_partner_id.display_name, record.amount, record.state,
            )
        return records

    def write(self, vals):
        posted = self.filtered(lambda record: record.state == "posted")
        if posted and not self.env.context.get("cdds_allow_audit_write"):
            raise UserError(_("Posted COD deposit applications are immutable."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda record: record.state == "posted"):
            raise UserError(_("Posted COD deposit applications cannot be deleted."))
        return super().unlink()

    def _cdds_create_transaction_log(self):
        """Create the pos_cod audit row only after accounting is fully finalized."""
        Collection = self.env["pos.cod.collection"].sudo()
        for application in self:
            existing = Collection.search(
                [("cod_deposit_application_id", "=", application.id)], limit=1
            )
            if existing:
                if application.transaction_log_id != existing:
                    application.with_context(cdds_allow_audit_write=True).write(
                        {"transaction_log_id": existing.id}
                    )
                _logger.warning(
                    "[COD-DEPOSIT][TRANSACTION-LOG][IDEMPOTENT] application=%s log_id=%s order=%s move=%s",
                    application.name, existing.id, application.order_id.name,
                    application.move_id.name,
                )
                continue

            currency = application.currency_id
            default_residual = application.bridge_receivable_line_id.amount_residual
            cod_residual = application.bridge_cod_line_id.amount_residual
            _logger.warning(
                "[COD-DEPOSIT][TRANSACTION-LOG][VALIDATE] application=%s state=%s move=%s move_state=%s default_line=%s default_residual=%.2f default_reconciled=%s cod_line=%s cod_residual=%.2f cod_reconciled=%s",
                application.name, application.state, application.move_id.name,
                application.move_id.state, application.bridge_receivable_line_id.id,
                default_residual, application.bridge_receivable_line_id.reconciled,
                application.bridge_cod_line_id.id, cod_residual,
                application.bridge_cod_line_id.reconciled,
            )
            if application.state != "posted" or application.move_id.state != "posted":
                raise UserError(_("The deposit transaction cannot be logged before its journal entry is posted."))
            if (
                not application.bridge_receivable_line_id
                or not application.bridge_cod_line_id
                or not float_is_zero(default_residual, precision_rounding=currency.rounding)
                or not float_is_zero(cod_residual, precision_rounding=currency.rounding)
                or not application.bridge_receivable_line_id.reconciled
                or not application.bridge_cod_line_id.reconciled
            ):
                raise UserError(_(
                    "The deposit transaction cannot be logged until both receivable reconciliations are complete."
                ))

            reservation_name = application.reservation_id.name or "-"
            transaction = Collection.create({
                "order_id": application.order_id.id,
                "session_id": application.pos_session_id.id,
                "kind": "deposit",
                "amount": application.amount,
                "move_id": application.move_id.id,
                "cod_deposit_application_id": application.id,
                "note": _(
                    "Customer deposit applied after accounting reconciliation. Application: %(application)s; Reservation: %(reservation)s"
                ) % {
                    "application": application.name,
                    "reservation": reservation_name,
                },
            })
            application.with_context(cdds_allow_audit_write=True).write(
                {"transaction_log_id": transaction.id}
            )
            _logger.warning(
                "[COD-DEPOSIT][TRANSACTION-LOG][CREATED] application=%s log_id=%s order=%s session=%s amount=%.2f move=%s default_reconcile=%s cod_reconcile=%s",
                application.name, transaction.id, application.order_id.name,
                application.pos_session_id.name, application.amount, application.move_id.name,
                application.bridge_receivable_line_id.full_reconcile_id.id,
                application.bridge_cod_line_id.full_reconcile_id.id,
            )
        return True

    @api.model
    def _cdds_backfill_transaction_logs(self):
        applications = self.sudo().search([
            ("state", "=", "posted"),
            ("transaction_log_id", "=", False),
        ])
        _logger.warning(
            "[COD-DEPOSIT][TRANSACTION-LOG][BACKFILL-START] applications=%s ids=%s",
            len(applications), applications.ids,
        )
        for application in applications:
            application._cdds_create_transaction_log()
        _logger.warning(
            "[COD-DEPOSIT][TRANSACTION-LOG][BACKFILL-DONE] applications=%s",
            len(applications),
        )
        return True
