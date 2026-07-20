# -*- coding: utf-8 -*-
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.osv import expression

_logger = logging.getLogger(__name__)


class VendorDepartmentContact(models.Model):
    _inherit = 'vendor.department.contact'

    def name_get(self):
        result = []
        for line in self:
            contact_name = line.contact_id.display_name or _('Unnamed Contact')
            details = []
            if line.department_id:
                details.append(line.department_id.display_name)
            if line.title:
                details.append(line.title)
            name = (
                f"{contact_name} ({' / '.join(details)})"
                if details
                else contact_name
            )
            result.append((line.id, name))
        return result

    def _purchase_selector_usage_months(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'purchase_net_price_compute.rfq_vendor_contact_usage_months',
            '6',
        )
        try:
            return max(int(value or 0), 0)
        except ValueError:
            _logger.warning(
                "Invalid RFQ vendor contact usage months config value=%s; falling back to 6",
                value,
            )
            return 6

    def _purchase_selector_usage_counts(self, vendor_id, contact_line_ids):
        months = self._purchase_selector_usage_months()
        if not months or not vendor_id or not contact_line_ids:
            _logger.debug(
                "RFQ contact usage ranking skipped vendor_id=%s months=%s contact_line_count=%s",
                vendor_id,
                months,
                len(contact_line_ids),
            )
            return {}

        cutoff = fields.Datetime.now() - relativedelta(months=months)
        groups = self.env['purchase.order'].read_group(
            [
                ('partner_id', '=', vendor_id),
                ('date_order', '>=', cutoff),
                ('vendor_promised_cost_contact_id', 'in', contact_line_ids),
            ],
            ['vendor_promised_cost_contact_id'],
            ['vendor_promised_cost_contact_id'],
        )
        counts = {
            group['vendor_promised_cost_contact_id'][0]: group['vendor_promised_cost_contact_id_count']
            for group in groups
            if group.get('vendor_promised_cost_contact_id')
        }
        _logger.debug(
            "RFQ contact usage ranking vendor_id=%s months=%s cutoff=%s counts=%s",
            vendor_id,
            months,
            cutoff,
            counts,
        )
        return counts

    def _purchase_selector_ordered_ids(self, vendor_id, department_id=False):
        domain = [('vendor_id', '=', vendor_id), ('active', '=', True)]
        contact_lines = self.search(domain)
        if not contact_lines:
            _logger.info(
                "RFQ contact selector found no saved vendor contacts vendor_id=%s",
                vendor_id,
            )
            return []

        usage_counts = self._purchase_selector_usage_counts(
            vendor_id,
            contact_lines.ids,
        )
        has_usage = bool(usage_counts)
        primary_ids = set(contact_lines.filtered('is_primary').ids)

        def sort_key(line):
            usage_count = usage_counts.get(line.id, 0)
            department_match = bool(department_id and line.department_id.id == department_id)
            return (
                0 if usage_count else 1,
                -usage_count,
                0 if line.id in primary_ids else 1,
                0 if department_match else 1,
                line.sequence or 0,
                line.contact_id.display_name or '',
                line.id,
            )

        ordered = contact_lines.sorted(sort_key)
        _logger.debug(
            "RFQ contact selector ordered vendor_id=%s department_id=%s has_usage=%s primary_ids=%s ordered_ids=%s",
            vendor_id,
            department_id,
            has_usage,
            sorted(primary_ids),
            ordered.ids,
        )
        return ordered.ids

    def _purchase_selector_search_domain(self, name, operator):
        if not name:
            return []
        return [
            '|', '|', '|', '|',
            ('contact_id.name', operator, name),
            ('contact_id.email', operator, name),
            ('contact_id.phone', operator, name),
            ('contact_id.mobile', operator, name),
            ('title', operator, name),
        ]

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        if not self.env.context.get('purchase_vendor_contact_selector'):
            return super().name_search(
                name=name,
                args=args,
                operator=operator,
                limit=limit,
            )

        args = args or []
        vendor_id = self.env.context.get('purchase_vendor_id')
        department_id = self.env.context.get('purchase_vendor_department_id')
        if not vendor_id:
            _logger.debug(
                "RFQ contact selector called without vendor context name=%s args=%s",
                name,
                args,
            )
            return []

        ordered_ids = self._purchase_selector_ordered_ids(
            vendor_id,
            department_id=department_id,
        )
        domain = expression.AND([
            args,
            [('id', 'in', ordered_ids)],
            self._purchase_selector_search_domain(name, operator),
        ])
        records = self.search(domain)
        order_index = {record_id: index for index, record_id in enumerate(ordered_ids)}
        records = records.sorted(lambda record: order_index.get(record.id, len(order_index)))
        if limit:
            records = records[:limit]
        _logger.debug(
            "RFQ contact selector name_search vendor_id=%s department_id=%s name=%s result_ids=%s",
            vendor_id,
            department_id,
            name,
            records.ids,
        )
        return records.name_get()

    @api.model
    def name_create(self, name):
        if not self.env.context.get('purchase_vendor_contact_selector'):
            return super().name_create(name)

        vendor_id = self.env.context.get('purchase_vendor_id')
        department_id = self.env.context.get(
            'purchase_vendor_department_id'
        ) or self.env.context.get('default_department_id')
        if not vendor_id:
            raise UserError(_('Select a vendor before creating a vendor contact.'))
        if not department_id:
            raise UserError(
                _('Select a vendor department before creating a new vendor contact.')
            )

        department = self.env['vendor.department'].browse(department_id).exists()
        if not department or department.vendor_id.id != vendor_id:
            raise UserError(
                _('The selected department must belong to the selected vendor.')
            )

        contact = self.env['res.partner'].create({
            'name': name,
            'parent_id': vendor_id,
            'type': 'contact',
        })
        line = self.create({
            'department_id': department.id,
            'contact_id': contact.id,
            'title': contact.function or department.name,
        })
        _logger.info(
            "RFQ quick-created vendor contact vendor_id=%s department_id=%s contact_id=%s contact_line_id=%s name=%s user_id=%s",
            vendor_id,
            department.id,
            contact.id,
            line.id,
            name,
            self.env.user.id,
        )
        return line.name_get()[0]
