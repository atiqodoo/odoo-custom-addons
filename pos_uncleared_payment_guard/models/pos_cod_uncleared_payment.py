# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger("pos_uncleared_payment_guard.cod")


class PosUnclearedPaymentHold(models.Model):
    _inherit = "pos.uncleared.payment.hold"

    pos_payment_id = fields.Many2one(
        "pos.payment",
        string="POS Payment",
        required=False,
        index=True,
        ondelete="cascade",
    )
    cod_collection_id = fields.Many2one(
        "pos.cod.collection",
        string="COD Collection",
        readonly=True,
        index=True,
        ondelete="cascade",
        copy=False,
    )
    cod_account_move_id = fields.Many2one(
        "account.move",
        string="COD Accounting Move",
        related="cod_collection_id.move_id",
        store=True,
        readonly=True,
    )
    is_cod_uncleared_hold = fields.Boolean(
        string="COD Uncleared Hold",
        compute="_compute_is_cod_uncleared_hold",
        store=True,
        readonly=True,
    )

    _sql_constraints = [
        (
            "cod_collection_unique",
            "unique(cod_collection_id)",
            "An uncleared payment hold already exists for this COD collection.",
        ),
    ]

    @api.depends("cod_collection_id")
    def _compute_is_cod_uncleared_hold(self):
        for hold in self:
            hold.is_cod_uncleared_hold = bool(hold.cod_collection_id)

    def _upg_mark_manual_cleared(self, reason, reference=False):
        result = super()._upg_mark_manual_cleared(reason, reference)
        self._upg_sync_cod_order_clearance("manual_cleared")
        return result

    def _upg_mark_accounting_cleared(self):
        result = super()._upg_mark_accounting_cleared()
        self._upg_sync_cod_order_clearance("accounting_cleared")
        return result

    def _upg_sync_cod_order_clearance(self, reason):
        for hold in self.filtered("cod_collection_id"):
            order = hold.cod_collection_id.order_id
            if not order or not order.exists():
                continue
            if hold.state == "accounting_cleared":
                target_state = "paid" if order._cod_open_amount() <= 0.01 else "partial"
                order.write({"cod_state": target_state})
                _logger.warning(
                    "[UPG][COD] accounting-cleared hold=%s order=%s -> cod_state=%s",
                    hold.name,
                    order.name,
                    target_state,
                )
            else:
                _logger.warning(
                    "[UPG][COD] hold=%s state=%s reason=%s order=%s remains visible",
                    hold.name,
                    hold.state,
                    reason,
                    order.name,
                )

    @api.model
    def _upg_pending_amounts_for_partner(self, commercial_partner, company_id=False):
        result = super()._upg_pending_amounts_for_partner(commercial_partner, company_id=company_id)
        cod_holds = self.sudo().search([
            ("id", "in", result.get("hold_ids") or []),
            ("cod_collection_id", "!=", False),
        ])
        if not cod_holds:
            return result
        kept_holds = self.sudo().browse(result.get("hold_ids") or []) - cod_holds
        open_cod_holds = cod_holds.filtered(lambda h: h.pos_session_id.state == "opened")
        non_open_cod_holds = cod_holds - open_cod_holds
        adjusted = {
            "pending_total": round(result.get("pending_total", 0.0) - sum(cod_holds.mapped("amount")), 2),
            "pending_open_session": round(
                result.get("pending_open_session", 0.0) - sum(open_cod_holds.mapped("amount")),
                2,
            ),
            "pending_accounting_effect": round(
                result.get("pending_accounting_effect", 0.0) - sum(non_open_cod_holds.mapped("amount")),
                2,
            ),
            "hold_count": len(kept_holds),
            "hold_ids": kept_holds.ids,
            "cod_hold_count_excluded": len(cod_holds),
            "cod_hold_ids_excluded": cod_holds.ids,
        }
        result.update(adjusted)
        _logger.warning(
            "[UPG][COD] excluded COD uncleared holds from partner credit/deposit guard partner=%s excluded=%s adjusted=%s",
            commercial_partner.display_name,
            cod_holds.mapped("name"),
            result,
        )
        return result


class PosCodCollection(models.Model):
    _inherit = "pos.cod.collection"

    upg_uncleared_hold_id = fields.Many2one(
        "pos.uncleared.payment.hold",
        string="Uncleared Payment Hold",
        compute="_compute_upg_uncleared_hold_id",
        store=True,
        readonly=True,
    )

    @api.depends("order_id", "payment_method_id")
    def _compute_upg_uncleared_hold_id(self):
        Hold = self.env["pos.uncleared.payment.hold"].sudo()
        for collection in self:
            collection.upg_uncleared_hold_id = Hold.search(
                [("cod_collection_id", "=", collection.id)],
                limit=1,
            )

    @api.model_create_multi
    def create(self, vals_list):
        collections = super().create(vals_list)
        collections._upg_create_cod_uncleared_holds_from_collections()
        return collections

    def _upg_is_uncleared_cod_collection(self):
        self.ensure_one()
        if self.kind != "payment" or not self.payment_method_id:
            return False
        config = self.session_id.config_id
        method = self.payment_method_id
        return bool(
            method.upg_is_uncleared_guard_method
            or (config and method in config.upg_uncleared_payment_method_ids)
        )

    def _upg_create_cod_uncleared_holds_from_collections(self):
        Hold = self.env["pos.uncleared.payment.hold"].sudo()
        for collection in self:
            try:
                if not collection._upg_is_uncleared_cod_collection():
                    continue
                order = collection.order_id
                if not order or not order.partner_id:
                    _logger.warning(
                        "[UPG][COD] skip collection=%s hold creation: missing order/customer",
                        collection.id,
                    )
                    continue
                hold = Hold.search([("cod_collection_id", "=", collection.id)], limit=1)
                if not hold:
                    partner = order.partner_id
                    commercial = partner.commercial_partner_id
                    hold = Hold.create({
                        "partner_id": partner.id,
                        "commercial_partner_id": commercial.id,
                        "pos_order_id": order.id,
                        "cod_collection_id": collection.id,
                        "payment_method_id": collection.payment_method_id.id,
                        "pos_config_id": collection.session_id.config_id.id,
                        "pos_session_id": collection.session_id.id,
                        "company_id": order.company_id.id,
                        "currency_id": order.currency_id.id,
                        "amount": abs(collection.amount or 0.0),
                        "state": "pending",
                    })
                    _logger.warning(
                        "[UPG][COD] collection safety-net created hold=%s order=%s collection=%s method=%s amount=%.2f",
                        hold.name,
                        order.name,
                        collection.id,
                        collection.payment_method_id.display_name,
                        hold.amount,
                    )
                if hold.state != "accounting_cleared" and order.cod_state == "paid":
                    order.write({"cod_state": "partial"})
                    _logger.warning(
                        "[UPG][COD] collection safety-net kept order visible order=%s hold=%s state=%s",
                        order.name,
                        hold.name,
                        hold.state,
                    )
            except Exception as exc:
                _logger.exception(
                    "[UPG][COD] collection safety-net failed collection=%s: %s",
                    collection.id,
                    exc,
                )

    @api.model
    def _upg_backfill_cod_uncleared_holds(self):
        collections = self.sudo().search([
            ("kind", "=", "payment"),
            ("payment_method_id", "!=", False),
        ])
        guarded = collections.filtered(lambda collection: collection._upg_is_uncleared_cod_collection())
        before = self.env["pos.uncleared.payment.hold"].sudo().search_count([
            ("cod_collection_id", "!=", False),
        ])
        guarded._upg_create_cod_uncleared_holds_from_collections()
        after = self.env["pos.uncleared.payment.hold"].sudo().search_count([
            ("cod_collection_id", "!=", False),
        ])
        _logger.warning(
            "[UPG][COD] backfill checked=%s guarded=%s created=%s",
            len(collections),
            len(guarded),
            after - before,
        )
        return {
            "checked": len(collections),
            "guarded": len(guarded),
            "created": after - before,
        }


class PosOrder(models.Model):
    _inherit = "pos.order"

    upg_cod_uncleared_state = fields.Selection(
        [
            ("none", "None"),
            ("pending", "Pending"),
            ("accounting_transfer_seen", "Transfer Seen"),
            ("manual_cleared", "Manual Cleared"),
            ("accounting_cleared", "Accounting Cleared"),
        ],
        string="COD Uncleared State",
        compute="_compute_upg_cod_uncleared_status",
        store=False,
    )
    upg_cod_uncleared_label = fields.Char(
        string="COD Uncleared Label",
        compute="_compute_upg_cod_uncleared_status",
        store=False,
    )
    upg_cod_uncleared_hold_id = fields.Many2one(
        "pos.uncleared.payment.hold",
        string="COD Uncleared Hold",
        compute="_compute_upg_cod_uncleared_status",
        store=False,
    )

    def _compute_upg_cod_uncleared_status(self):
        Hold = self.env["pos.uncleared.payment.hold"].sudo()
        state_label = {
            "pending": _("Uncleared payment"),
            "accounting_transfer_seen": _("Transfer seen"),
            "manual_cleared": _("Manual cleared"),
            "accounting_cleared": _("Accounting cleared"),
            "cancelled": _("Uncleared cancelled"),
        }
        for order in self:
            hold = Hold.search(
                [
                    ("pos_order_id", "=", order.id),
                    ("cod_collection_id", "!=", False),
                    ("state", "!=", "cancelled"),
                ],
                order="create_date desc, id desc",
                limit=1,
            )
            order.upg_cod_uncleared_hold_id = hold
            order.upg_cod_uncleared_state = hold.state if hold else "none"
            order.upg_cod_uncleared_label = state_label.get(hold.state, "") if hold else ""

    @api.model
    def _upg_extract_cod_capture(self, order_id=None, payment_method_id=None, amount=None, session_id=False, **kwargs):
        payload = order_id if isinstance(order_id, dict) else kwargs
        capture = payload.get("upg_capture") if payload else kwargs.get("upg_capture")
        method_id = payment_method_id
        session = session_id
        action = kwargs.get("action", "payment")
        order_ref = kwargs.get("order_ref")
        if payload:
            method_id = payload.get("payment_method_id") or payload.get("paymentMethodId") or method_id
            session = payload.get("session_id") or payload.get("sessionId") or session
            action = payload.get("action") or action
            order_ref = payload.get("order_ref") or payload.get("orderRef") or order_ref
        return capture or {}, method_id, session, action, order_ref

    @api.model
    def collect_cod_payment(self, *args, **kwargs):
        capture, payment_method_id, session_id, action, order_ref = self._upg_extract_cod_capture(*args, **kwargs)
        result = super().collect_cod_payment(*args, **kwargs)
        if not result.get("success") or action != "payment":
            return result

        session = self.env["pos.session"].browse(int(session_id)) if session_id else self.env["pos.session"]
        payment_method = self.env["pos.payment.method"].browse(int(payment_method_id)) if payment_method_id else self.env["pos.payment.method"]
        config = session.config_id if session.exists() else self.env["pos.config"]
        guarded = bool(
            payment_method
            and payment_method.exists()
            and (
                payment_method in config.upg_uncleared_payment_method_ids
                or payment_method.upg_is_uncleared_guard_method
            )
        )
        if not guarded:
            return result

        order = self.browse()
        order_name = result.get("order_name") or order_ref
        if order_name:
            order = self.search(
                [
                    ("is_cod", "=", True),
                    "|",
                    ("name", "=", order_name),
                    ("pos_reference", "=", order_name),
                ],
                limit=1,
            )
        if not order:
            _logger.warning("[UPG][COD] guarded COD collection succeeded but order not found result=%s", result)
            return result

        collection = order.cod_collection_ids.filtered(
            lambda c: c.kind == "payment"
            and c.payment_method_id == payment_method
            and round(abs(c.amount or 0.0), 2) == round(abs(result.get("amount") or 0.0), 2)
        )[:1]
        if not collection:
            collection = order.cod_collection_ids.filtered(lambda c: c.kind == "payment")[:1]
        if not collection:
            _logger.warning("[UPG][COD] no COD collection found for guarded order=%s", order.name)
            return result

        collection._upg_create_cod_uncleared_holds_from_collections()
        hold = self.env["pos.uncleared.payment.hold"].sudo().search(
            [("cod_collection_id", "=", collection.id)],
            limit=1,
        )
        if not hold:
            partner = order.partner_id
            commercial = partner.commercial_partner_id
            deposit_bank_journal_id = capture.get("deposit_bank_journal_id") or False
            hold = self.env["pos.uncleared.payment.hold"].sudo().create({
                "partner_id": partner.id,
                "commercial_partner_id": commercial.id,
                "pos_order_id": order.id,
                "cod_collection_id": collection.id,
                "payment_method_id": payment_method.id,
                "pos_config_id": config.id,
                "pos_session_id": session.id,
                "company_id": order.company_id.id,
                "currency_id": order.currency_id.id,
                "amount": abs(collection.amount or 0.0),
                "state": "pending",
                "deposit_bank_journal_id": deposit_bank_journal_id,
                "cheque_bank": capture.get("cheque_bank") or "",
                "cheque_account_number": capture.get("cheque_account_number") or "",
                "cheque_number": capture.get("cheque_number") or "",
                "cheque_date": capture.get("cheque_date") or False,
            })
            _logger.warning(
                "[UPG][COD] created uncleared COD hold=%s order=%s collection=%s method=%s amount=%.2f capture=%s",
                hold.name,
                order.name,
                collection.id,
                payment_method.display_name,
                hold.amount,
                capture,
            )
        elif capture:
            write_vals = {
                "deposit_bank_journal_id": capture.get("deposit_bank_journal_id") or hold.deposit_bank_journal_id.id or False,
                "cheque_bank": capture.get("cheque_bank") or hold.cheque_bank or "",
                "cheque_account_number": capture.get("cheque_account_number") or hold.cheque_account_number or "",
                "cheque_number": capture.get("cheque_number") or hold.cheque_number or "",
                "cheque_date": capture.get("cheque_date") or hold.cheque_date or False,
            }
            hold.write(write_vals)
            _logger.warning(
                "[UPG][COD] updated COD hold capture hold=%s collection=%s capture=%s",
                hold.name,
                collection.id,
                write_vals,
            )

        if result.get("remaining", 0.0) <= 0.01 and hold.state != "accounting_cleared":
            order.write({"cod_state": "partial"})
            result["cod_state"] = "partial"
            result["upg_uncleared_hold_id"] = hold.id
            result["upg_uncleared_state"] = hold.state
            result["upg_uncleared_label"] = _("Uncleared payment")
            _logger.warning(
                "[UPG][COD] keeping fully-paid uncleared COD order visible order=%s hold=%s state=%s",
                order.name,
                hold.name,
                hold.state,
            )
        return result

    @api.model
    def upg_cod_uncleared_status(self, order_ids):
        orders = self.browse([int(order_id) for order_id in (order_ids or [])]).exists()
        return {
            order.id: {
                "upg_cod_uncleared_state": order.upg_cod_uncleared_state,
                "upg_cod_uncleared_label": order.upg_cod_uncleared_label,
                "upg_cod_uncleared_hold_id": order.upg_cod_uncleared_hold_id.id,
            }
            for order in orders
        }
