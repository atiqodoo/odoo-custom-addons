# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger("pos_uncleared_payment_guard.live_detector")


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._upg_trigger_live_uncleared_detection("statement_line_create")
        return lines

    def write(self, vals):
        result = super().write(vals)
        watched_fields = {
            "is_reconciled",
            "move_id",
            "amount",
            "payment_ref",
            "name",
            "ref",
            "journal_id",
        }
        if watched_fields.intersection(vals):
            self._upg_trigger_live_uncleared_detection(
                "statement_line_write:%s" % ",".join(sorted(watched_fields.intersection(vals)))
            )
        return result

    def _upg_trigger_live_uncleared_detection(self, reason):
        if self.env.context.get("upg_skip_live_detector"):
            return
        lines = self.sudo().filtered(lambda line: line.company_id and line.journal_id)
        if not lines:
            return
        _logger.warning(
            "[UPG][LiveDetector] statement trigger reason=%s lines=%s journals=%s",
            reason,
            lines.mapped("display_name"),
            lines.mapped("journal_id.display_name"),
        )
        self.env["pos.uncleared.payment.hold"].sudo().with_context(
            upg_skip_live_detector=True
        )._upg_detect_for_accounting_lines(lines, reason)


class AccountPartialReconcile(models.Model):
    _inherit = "account.partial.reconcile"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._upg_trigger_live_uncleared_detection("partial_reconcile_create")
        return records

    def unlink(self):
        lines = (self.debit_move_id | self.credit_move_id).mapped("statement_line_id")
        result = super().unlink()
        lines._upg_trigger_live_uncleared_detection("partial_reconcile_unlink")
        return result

    def _upg_trigger_live_uncleared_detection(self, reason):
        if self.env.context.get("upg_skip_live_detector"):
            return
        statement_lines = (self.debit_move_id | self.credit_move_id).mapped("statement_line_id").sudo()
        if not statement_lines:
            _logger.debug("[UPG][LiveDetector] partial reconcile trigger reason=%s no statement lines", reason)
            return
        _logger.warning(
            "[UPG][LiveDetector] partial reconcile trigger reason=%s statement_lines=%s",
            reason,
            statement_lines.mapped("display_name"),
        )
        self.env["pos.uncleared.payment.hold"].sudo().with_context(
            upg_skip_live_detector=True
        )._upg_detect_for_accounting_lines(statement_lines, reason)


class AccountMove(models.Model):
    _inherit = "account.move"

    def action_post(self):
        result = super().action_post()
        self.mapped("line_ids")._upg_trigger_live_uncleared_detection("move_action_post")
        return result

    def write(self, vals):
        result = super().write(vals)
        if "state" in vals:
            self.filtered(lambda move: move.state == "posted").mapped(
                "line_ids"
            )._upg_trigger_live_uncleared_detection("move_write:state")
        return result


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._upg_trigger_live_uncleared_detection("move_line_create")
        return lines

    def write(self, vals):
        result = super().write(vals)
        watched_fields = {
            "account_id",
            "balance",
            "debit",
            "credit",
            "amount_currency",
            "move_id",
            "journal_id",
            "name",
            "ref",
        }
        if watched_fields.intersection(vals):
            self._upg_trigger_live_uncleared_detection(
                "move_line_write:%s" % ",".join(sorted(watched_fields.intersection(vals)))
            )
        return result

    def _upg_trigger_live_uncleared_detection(self, reason):
        if self.env.context.get("upg_skip_live_detector"):
            return
        lines = self.sudo().filtered(
            lambda line: line.company_id and line.account_id and line.move_id.state == "posted"
        )
        if not lines:
            return
        _logger.warning(
            "[UPG][LiveDetector] move-line trigger reason=%s lines=%s accounts=%s journals=%s",
            reason,
            lines.ids,
            lines.mapped("account_id.display_name"),
            lines.mapped("journal_id.display_name"),
        )
        self.env["pos.uncleared.payment.hold"].sudo().with_context(
            upg_skip_live_detector=True
        )._upg_detect_for_move_lines(lines, reason)
