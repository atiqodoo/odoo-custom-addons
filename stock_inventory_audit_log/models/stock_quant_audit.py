import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    def _stock_audit_should_capture_write(self, vals):
        if self.env.context.get('stock_audit_skip_capture'):
            return False
        watched_fields = {
            'inventory_quantity',
            'inventory_quantity_auto_apply',
            'inventory_quantity_set',
            'inventory_diff_quantity',
        }
        return self._is_inventory_mode() and bool(watched_fields.intersection(vals))

    def _stock_audit_capture_counts(self, trigger):
        self.env['stock.audit.log.service'].capture_quant_counts(self, trigger=trigger)

    @api.model_create_multi
    def create(self, vals_list):
        create_self = self
        if self._stock_audit_should_merge_inventory_import(vals_list):
            create_self = self.with_context(
                import_file=False,
                stock_audit_import_file=True,
            )
        quants = super(StockQuant, create_self).create(vals_list)
        if self._is_inventory_mode():
            quants._stock_audit_capture_counts('stock.quant.create')
        return quants

    def _stock_audit_should_merge_inventory_import(self, vals_list):
        if not self.env.context.get('import_file') or not self._is_inventory_mode():
            return False
        inventory_fields = {'inventory_quantity', 'inventory_quantity_auto_apply'}
        return any(inventory_fields.intersection(vals) for vals in vals_list)

    def write(self, vals):
        should_capture = self._stock_audit_should_capture_write(vals)
        result = super().write(vals)
        if should_capture:
            self._stock_audit_capture_counts('stock.quant.write')
        return result

    def action_apply_inventory(self):
        audit_service = self.env['stock.audit.log.service']
        quants_to_apply = self.filtered(lambda quant: quant.inventory_quantity_set)
        audit_service.log_event(
            logging.DEBUG,
            'AUDIT_APPLY_START',
            quant_ids=quants_to_apply.ids,
            user_id=self.env.uid,
        )
        quants_to_apply._stock_audit_capture_counts('stock.quant.action_apply_inventory.before')
        draft_logs = self.env['stock.audit.log'].sudo().search([
            ('quant_id', 'in', quants_to_apply.ids),
            ('state', '=', 'draft'),
        ])
        result = super(StockQuant, self.with_context(stock_audit_skip_capture=True)).action_apply_inventory()
        if result:
            audit_service.log_event(
                logging.INFO,
                'AUDIT_APPLY_DEFERRED_WIZARD_RETURNED',
                quant_ids=quants_to_apply.ids,
                result_type=result.get('res_model') if isinstance(result, dict) else type(result).__name__,
            )
            return result
        audit_service.mark_logs_applied(draft_logs)
        return result

    def barcode_write(self, vals):
        return super(StockQuant, self.with_context(barcode_inventory=True)).barcode_write(vals)
