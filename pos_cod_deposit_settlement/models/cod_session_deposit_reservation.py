# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger("pos_cod_deposit_settlement.reservation")


class PosCodSessionDepositReservation(models.Model):
    _name = "pos.cod.session.deposit.reservation"
    _description = "Same-Session Customer Deposit Reservation for COD"
    _inherit = ["mail.thread"]
    _order = "create_date desc, id desc"

    name = fields.Char(default=lambda self: _("New"), required=True, readonly=True, copy=False, index=True)
    operation_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    state = fields.Selection(
        [
            ("reserved", "Reserved - Pending Session Posting"),
            ("finalizing", "Finalizing"),
            ("finalized", "Accounting Finalized"),
            ("cancelled", "Cancelled"),
            ("error", "Finalization Error"),
        ],
        default="reserved",
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
    source_session_id = fields.Many2one("pos.session", required=True, readonly=True, ondelete="restrict", index=True)
    pos_config_id = fields.Many2one("pos.config", required=True, readonly=True, ondelete="restrict")
    cashier_id = fields.Many2one("res.users", required=True, readonly=True, default=lambda self: self.env.user)
    amount = fields.Monetary(required=True, readonly=True, currency_field="currency_id", tracking=True)
    source_payment_ids = fields.Many2many(
        "pos.payment",
        "pos_cod_session_deposit_reservation_payment_rel",
        "reservation_id",
        "payment_id",
        string="Source Deposit Payments",
        readonly=True,
        copy=False,
    )
    source_allocation_json = fields.Text(readonly=True, copy=False)
    application_id = fields.Many2one(
        "pos.cod.deposit.application", readonly=True, copy=False, ondelete="restrict", index=True
    )
    reserved_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    finalized_date = fields.Datetime(readonly=True)
    error_message = fields.Text(readonly=True, copy=False)

    _sql_constraints = [
        ("reservation_operation_company_unique", "unique(company_id, operation_uuid)", "This session-deposit reservation was already processed."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"].sudo()
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = sequence.next_by_code("pos.cod.session.deposit.reservation") or _("New")
        records = super().create(vals_list)
        for record in records:
            _logger.warning(
                "[COD-DEPOSIT][RESERVE][CREATED] reservation=%s operation=%s order=%s source_session=%s partner=%s amount=%.2f payments=%s",
                record.name, record.operation_uuid, record.order_id.name, record.source_session_id.name,
                record.commercial_partner_id.display_name, record.amount, record.source_payment_ids.ids,
            )
        return records

    def write(self, vals):
        if self.filtered(lambda record: record.state == "finalized") and not self.env.context.get("cdds_allow_reservation_write"):
            raise UserError(_("Finalized same-session COD deposit reservations are immutable."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda record: record.state in ("reserved", "finalizing", "finalized")):
            raise UserError(_("Active or finalized same-session COD deposit reservations cannot be deleted."))
        return super().unlink()

    def _cdds_finalize(self):
        self.ensure_one()
        if self.state == "finalized":
            _logger.warning("[COD-DEPOSIT][FINALIZE][IDEMPOTENT] reservation=%s already finalized", self.name)
            return self.application_id
        if self.state not in ("reserved", "error"):
            raise UserError(_("Reservation %s is not available for finalization.") % self.name)

        _logger.warning(
            "[COD-DEPOSIT][FINALIZE][START] reservation=%s order=%s session=%s amount=%.2f state=%s",
            self.name, self.order_id.name, self.source_session_id.name, self.amount, self.state,
        )
        self.with_context(cdds_allow_reservation_write=True).write({"state": "finalizing", "error_message": False})
        self.order_id.invalidate_recordset([
            "cod_session_deposit_reserved_amount", "cod_amount_paid", "cod_amount_open"
        ])
        result = self.env["pos.order"].with_context(
            cdds_finalize_reservation_id=self.id,
            cdds_allow_closed_source_session=True,
        ).cod_apply_deposit(
            self.order_id.id,
            self.amount,
            self.source_session_id.id,
            self.operation_uuid,
        )
        application = self.env["pos.cod.deposit.application"].sudo().browse(result["application_id"]).exists()
        if not application:
            raise UserError(_("Reservation %s produced no accounting application.") % self.name)
        application.with_context(cdds_allow_audit_write=True).write({"reservation_id": self.id})
        self.with_context(cdds_allow_reservation_write=True).write({
            "state": "finalized",
            "application_id": application.id,
            "finalized_date": fields.Datetime.now(),
        })
        _logger.warning(
            "[COD-DEPOSIT][FINALIZE][SUCCESS] reservation=%s application=%s order=%s move=%s amount=%.2f",
            self.name, application.name, self.order_id.name, application.move_id.name, self.amount,
        )
        return application
