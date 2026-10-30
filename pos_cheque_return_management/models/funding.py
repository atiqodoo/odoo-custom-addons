import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from .attempt import _TOKEN

_logger = logging.getLogger("pos_cheque_return_management.funding")


class ChequeCodFunding(models.Model):
    _name = "pos.cheque.cod.funding"
    _description = "Cheque Funding Allocated to COD"
    _check_company_auto = True

    hold_id = fields.Many2one("pos.uncleared.payment.hold", required=True, ondelete="restrict", check_company=True, index=True)
    company_id = fields.Many2one(related="hold_id.company_id", store=True)
    currency_id = fields.Many2one(related="hold_id.currency_id", store=True)
    application_id = fields.Many2one("pos.cod.deposit.application", check_company=True, ondelete="restrict")
    order_id = fields.Many2one("pos.order", required=True, check_company=True, ondelete="restrict")
    amount = fields.Monetary(required=True)
    debit_line_id = fields.Many2one("account.move.line", check_company=True, ondelete="set null")
    credit_line_id = fields.Many2one("account.move.line", check_company=True, ondelete="set null")
    returned_by_id = fields.Many2one("pos.cheque.bank.return", readonly=True, check_company=True, ondelete="restrict")
    recovery_of_id = fields.Many2one("pos.cheque.cod.funding", readonly=True, check_company=True, ondelete="restrict")

    @api.model_create_multi
    def create(self, values):
        _logger.debug("[CHEQUE][FUNDING][START] count=%s", len(values))
        internal = self.env.context.get("cheque_workflow") is _TOKEN
        for vals in values:
            hold = self.env["pos.uncleared.payment.hold"].browse(vals["hold_id"])
            hold._upg_check_transfer_link_access()
            hold._cheque_lock()
            if not internal:
                application = self.env["pos.cod.deposit.application"].browse(vals.get("application_id"))
                source = hold._cheque_original_attempt().receipt_credit_line_id
                if (not application or application.state != "posted"
                        or source not in application.source_credit_line_ids):
                    raise UserError(_("Select a posted application which identifies this customer's receipt as a source credit."))
                vals.update({"order_id": application.order_id.id, "debit_line_id": application.bridge_receivable_line_id.id, "credit_line_id": application.bridge_cod_line_id.id, "returned_by_id": False, "recovery_of_id": False})
        records = super().create(values)
        _logger.debug("[CHEQUE][FUNDING][END] funding_ids=%s", records.ids)
        return records

    def write(self, vals):
        if self.env.context.get("cheque_workflow") is not _TOKEN:
            raise UserError(_("Funding allocations are audit records. Record a correction instead."))
        return super().write(vals)

    def unlink(self):
        raise UserError(_("Funding allocations cannot be deleted."))

    @api.constrains("hold_id", "order_id", "amount", "application_id", "debit_line_id", "credit_line_id", "returned_by_id")
    def _validate_allocation(self):
        for record in self:
            hold = record.hold_id
            if (record.amount <= 0 or record.order_id.company_id != hold.company_id
                    or record.order_id.partner_id.commercial_partner_id != hold.commercial_partner_id
                    or record.credit_line_id.company_id != hold.company_id
                    or record.credit_line_id.move_id.state != "posted"):
                raise ValidationError(_("Funding must identify a positive amount for the same customer and company, backed by posted accounting."))
            active = self.search([("hold_id", "=", hold.id), ("returned_by_id", "=", False)])
            if hold.currency_id.compare_amounts(sum(active.mapped("amount")), hold.amount) > 0:
                raise ValidationError(_("COD funding exceeds this cheque's principal."))
            if record.application_id:
                # The same original application cannot be returned twice using
                # another cheque. Recovery uses a new funding record/move.
                allocations = self.search([("application_id", "=", record.application_id.id)])
                if hold.currency_id.compare_amounts(sum(allocations.mapped("amount")), record.application_id.amount) > 0:
                    raise ValidationError(_("Allocated cheque funds exceed the deposit application."))

    @api.model
    def _capture_receipt_funding(self, hold, source):
        if not source:
            return self.browse()
        existing = self.search([("hold_id", "=", hold.id), ("returned_by_id", "=", False)])
        if hold.cod_collection_id and not existing:
            return self.with_context(cheque_workflow=_TOKEN).create({
                "hold_id": hold.id, "order_id": hold.cod_collection_id.order_id.id,
                "amount": hold.amount, "credit_line_id": source.id,
            })
        applications = self.env["pos.cod.deposit.application"].search([
            ("source_credit_line_ids", "in", source.ids), ("state", "=", "posted"),
            ("company_id", "=", hold.company_id.id),
        ])
        for application in applications - existing.application_id:
            partials = source.matched_debit_ids.filtered(lambda partial: partial.debit_move_id == application.bridge_receivable_line_id)
            amount = sum(partials.mapped("amount"))
            if amount:
                existing |= self.with_context(cheque_workflow=_TOKEN).create({
                    "hold_id": hold.id, "application_id": application.id, "order_id": application.order_id.id,
                    "amount": amount, "debit_line_id": application.bridge_receivable_line_id.id,
                    "credit_line_id": application.bridge_cod_line_id.id,
                })
        return existing
