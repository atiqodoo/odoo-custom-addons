import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class StockAuditLogService(models.AbstractModel):
    _name = 'stock.audit.log.service'
    _description = 'Stock Audit Logging Service'

    def _debug_enabled(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'stock_inventory_audit_log.debug_logging'
        ) == 'True'

    def log_event(self, level, event, **payload):
        if level <= logging.DEBUG and not self._debug_enabled():
            return
        message = ' '.join('%s=%s' % (key, value) for key, value in sorted(payload.items()))
        _logger.log(level, '%s %s', event, message)

    def get_source(self):
        context = self.env.context
        if context.get('import_file') or context.get('stock_audit_import_file'):
            return 'import'
        if context.get('set_inventory_quantity_auto_apply'):
            return 'auto_apply'
        if context.get('barcode_view') or context.get('from_barcode') or context.get('barcode_inventory'):
            return 'barcode_inventory'
        if context.get('inventory_mode') or context.get('inventory_report_mode'):
            return 'manual_inventory'
        return 'unknown'

    def _get_quant_system_quantity(self, quant, company):
        """Return the real stock baseline for the quant identity being counted.

        Inventory imports can create a fresh stock.quant row for an existing
        product/location pair. That new row has quantity 0, while the real stock
        may still be on another matching quant row. The audit baseline must be
        the stock represented by the full quant identity, not only the imported
        row's own quantity.
        """
        domain = [
            ('product_id', '=', quant.product_id.id),
            ('location_id', '=', quant.location_id.id),
            ('lot_id', '=', quant.lot_id.id or False),
            ('package_id', '=', quant.package_id.id or False),
            ('owner_id', '=', quant.owner_id.id or False),
        ]
        if company:
            domain.append(('company_id', 'in', [company.id, False]))
        else:
            domain.append(('company_id', '=', False))

        groups = self.env['stock.quant'].sudo().read_group(domain, ['quantity:sum'], [])
        system_quantity = groups[0]['quantity'] if groups else quant.quantity
        if system_quantity != quant.quantity:
            self.log_event(
                logging.INFO,
                'AUDIT_SYSTEM_QUANTITY_AGGREGATED',
                quant_id=quant.id,
                product_id=quant.product_id.id,
                location_id=quant.location_id.id,
                row_quantity=quant.quantity,
                system_quantity=system_quantity,
            )
        return system_quantity

    def _build_quant_values(self, quant, trigger):
        company = quant.company_id or quant.location_id.company_id or self.env.company
        product = quant.product_id
        cost_service = self.env['stock.audit.cost.service']
        tax_service = self.env['stock.audit.tax.service']
        cost_values = cost_service.get_cost_values(product, company)
        currency = self.env['res.currency'].browse(cost_values['currency_id'])
        vat_amount = tax_service.get_vat_amount_per_unit(
            product,
            company,
            cost_values['unit_cost_excl_vat'],
            currency,
        )
        barcode_values = product._get_stock_audit_barcode_values()
        return {
            'quant_id': quant.id,
            'product_id': product.id,
            'location_id': quant.location_id.id,
            'lot_id': quant.lot_id.id or False,
            'package_id': quant.package_id.id or False,
            'owner_id': quant.owner_id.id or False,
            'company_id': company.id,
            'currency_id': currency.id,
            'product_uom_id': quant.product_uom_id.id or product.uom_id.id,
            'system_quant': self._get_quant_system_quantity(quant, company),
            'counted_quant': quant.inventory_quantity,
            'employee_counted_id': self.env.user.id,
            'source': self.get_source(),
            'debug_reference': '%s:%s' % (trigger, quant.id),
            'unit_cost_excl_vat': cost_values['unit_cost_excl_vat'],
            'vat_amount_per_unit': vat_amount,
            **barcode_values,
        }

    def capture_quant_counts(self, quants, trigger='unknown'):
        matching_service = self.env['stock.audit.matching.service']
        AuditLog = self.env['stock.audit.log'].sudo().with_context(stock_audit_internal=True)
        for quant in quants.exists():
            if not quant.product_id or not quant.location_id:
                self.log_event(
                    logging.WARNING,
                    'AUDIT_CAPTURE_SKIPPED_INCOMPLETE_QUANT',
                    quant_id=quant.id,
                    trigger=trigger,
                )
                continue
            if not quant.inventory_quantity_set:
                continue

            vals = self._build_quant_values(quant, trigger)
            draft_log = matching_service.find_draft_for_quant(quant)
            if draft_log:
                draft_log.with_context(stock_audit_internal=True).write(vals)
                event = 'AUDIT_DRAFT_UPDATED'
                log_id = draft_log.id
            else:
                vals['timestamp_counted'] = fields.Datetime.now()
                vals['state'] = 'draft'
                draft_log = AuditLog.create(vals)
                event = 'AUDIT_DRAFT_CREATED'
                log_id = draft_log.id

            if vals['counted_quant'] == vals['system_quant']:
                self.log_event(
                    logging.INFO,
                    'AUDIT_ZERO_VARIANCE_CAPTURED',
                    log_id=log_id,
                    quant_id=quant.id,
                    product_id=quant.product_id.id,
                    location_id=quant.location_id.id,
                    system_quant=vals['system_quant'],
                    counted_quant=vals['counted_quant'],
                    trigger=trigger,
                )
            self.log_event(
                logging.DEBUG,
                event,
                log_id=log_id,
                quant_id=quant.id,
                product_id=quant.product_id.id,
                location_id=quant.location_id.id,
                system_quant=vals['system_quant'],
                counted_quant=vals['counted_quant'],
                trigger=trigger,
            )

    def mark_quant_logs_applied(self, quants):
        matching_service = self.env['stock.audit.matching.service']
        logs = self.env['stock.audit.log']
        for quant in quants.exists():
            logs |= matching_service.find_draft_for_quant(quant)
        self.mark_logs_applied(logs)

    def mark_logs_applied(self, logs):
        applied_at = fields.Datetime.now()
        for draft_log in logs.exists():
            draft_log.sudo().with_context(stock_audit_internal=True).write({
                'timestamp_applied': applied_at,
                'employee_applied_id': self.env.user.id,
                'state': 'applied',
            })
            self.log_event(
                logging.INFO,
                'AUDIT_APPLIED',
                log_id=draft_log.id,
                quant_id=draft_log.quant_id.id,
                product_id=draft_log.product_id.id,
                location_id=draft_log.location_id.id,
            )
