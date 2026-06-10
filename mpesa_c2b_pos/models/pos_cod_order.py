import logging

from odoo import api, models

_log = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def collect_cod_payment(self, *args, **kwargs):
        result = super().collect_cod_payment(*args, **kwargs)
        mpesa_ref = self._mpesa_cod_extract_ref(args, kwargs)
        if result.get('success') and mpesa_ref:
            self._mpesa_cod_link_collection(mpesa_ref, result)
        return result

    @staticmethod
    def _mpesa_cod_extract_ref(args, kwargs):
        if args and isinstance(args[0], dict):
            payload = args[0]
            return payload.get('mpesa_ref') or payload.get('mpesaRef') or False
        if len(args) >= 7 and args[3] in ('payment', 'return'):
            return args[6]
        if len(args) >= 8:
            return args[7]
        return kwargs.get('mpesa_ref') or kwargs.get('mpesaRef') or False

    def _mpesa_cod_link_collection(self, mpesa_ref, result):
        Txn = self.env['mpesa.transaction'].sudo()
        txn = Txn.search([('mpesa_ref', '=', mpesa_ref)], limit=1)
        if not txn:
            _log.warning("[M-Pesa COD] ref=%s collected but mpesa.transaction was not found", mpesa_ref)
            return

        order_name = result.get('order_name')
        order = self.search([('name', '=', order_name)], limit=1) if order_name else self.browse()
        if not order:
            _log.warning("[M-Pesa COD] ref=%s could not resolve COD order from result=%s", mpesa_ref, result)
            return

        collection = self.env['pos.cod.collection'].sudo().search([
            ('order_id', '=', order.id),
            ('mpesa_ref', '=', mpesa_ref),
        ], order='id desc', limit=1)
        if collection and not collection.mpesa_transaction_id:
            collection.write({'mpesa_transaction_id': txn.id})

        Usage = self.env['mpesa.transaction.usage'].sudo()
        amount = float(result.get('amount') or 0.0)
        if amount > 0 and not Usage.search([
            ('transaction_id', '=', txn.id),
            ('pos_order_id', '=', order.id),
            ('amount', '=', amount),
        ], limit=1):
            Usage.create({
                'transaction_id': txn.id,
                'pos_order_id': order.id,
                'amount': amount,
                'currency_id': order.currency_id.id or txn.currency_id.id,
                'cashier_id': self.env.uid,
                'session_id': collection.session_id.id if collection else False,
            })
        _log.info(
            "[M-Pesa COD] linked ref=%s txn=%s order=%s collection=%s amount=%.2f",
            mpesa_ref, txn.id, order.name, collection.id if collection else False, amount,
        )
