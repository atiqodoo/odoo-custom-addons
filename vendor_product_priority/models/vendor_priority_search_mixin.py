import logging
import time

from odoo import api, models
from odoo.osv import expression
from odoo.tools import OrderedSet


_logger = logging.getLogger(__name__)


class VendorPrioritySearchMixin(models.AbstractModel):
    """Reusable vendor-ranked search behavior for products and templates."""

    _name = 'vendor.product.priority.search.mixin'
    _description = 'Vendor Product Priority Search Mixin'

    @api.model
    def _vps_is_enabled(self):
        return bool(
            self.env.context.get('vendor_priority_search')
            and self.env.context.get('partner_id')
        )

    @api.model
    def _vps_context_records(self):
        vendor = self.env['res.partner'].browse(self.env.context.get('partner_id')).exists()
        company_id = self.env.context.get('company_id')
        company = self.env['res.company'].browse(company_id).exists() if company_id else self.env.company
        return vendor, company

    @api.model
    def _vps_role_ids(self):
        vendor, company = self._vps_context_records()
        return self.env['vendor.product.priority.service'].get_record_ids_by_role(
            self._name,
            vendor,
            company=company,
        )

    @api.model
    def _vps_exact_ids(self, name, args):
        if not name:
            return []
        exact_domain = self._vps_exact_domain(name)
        if not exact_domain:
            return []
        return self.search(expression.AND([args or [], exact_domain]), limit=5).ids

    @api.model
    def _vps_exact_domain(self, name):
        return [('default_code', '=', name)]

    @api.model
    def _vps_rank_domains(self, role_ids):
        mapped_ids = OrderedSet()
        domains = []
        for role in (1, 2, 3):
            ids_for_role = role_ids.get(role, [])
            mapped_ids.update(ids_for_role)
            if ids_for_role:
                domains.append((role, [('id', 'in', ids_for_role)]))
        domains.append((4, [('id', 'not in', list(mapped_ids))]))
        return domains, list(mapped_ids)

    @api.model
    def _vps_ranked_name_search(self, super_name_search, name='', args=None, operator='ilike', limit=100):
        started = time.perf_counter()
        args = list(args or [])
        role_ids = self._vps_role_ids()
        rank_domains, mapped_ids = self._vps_rank_domains(role_ids)
        result = []
        seen = set()

        def append_rows(rows):
            for row in rows:
                if row[0] in seen:
                    continue
                seen.add(row[0])
                result.append(row)
                if limit and len(result) >= limit:
                    break

        exact_ids = self._vps_exact_ids(name, args)
        if exact_ids:
            append_rows(super_name_search(
                name=name,
                args=expression.AND([args, [('id', 'in', exact_ids)]]),
                operator=operator,
                limit=limit,
            ))

        for role, role_domain in rank_domains:
            if limit and len(result) >= limit:
                break
            remaining = None if limit is None else limit - len(result)
            domain = expression.AND([args, role_domain, [('id', 'not in', list(seen))]])
            rows = super_name_search(name=name, args=domain, operator=operator, limit=remaining)
            append_rows(rows)
            _logger.debug(
                'VPS_NAME_SEARCH_BUCKET model=%s role=%s returned=%s remaining=%s',
                self._name,
                role,
                len(rows),
                remaining,
            )

        vendor, company = self._vps_context_records()
        elapsed_ms = (time.perf_counter() - started) * 1000
        _logger.info(
            'VPS_NAME_SEARCH model=%s source=%s vendor=%s company=%s term=%r limit=%s '
            'mapped_pool=%s exact=%s returned=%s elapsed_ms=%.2f',
            self._name,
            self.env.context.get('vendor_priority_source', 'unknown'),
            vendor.id,
            company.id,
            name,
            limit,
            len(mapped_ids),
            len(exact_ids),
            len(result),
            elapsed_ms,
        )
        _logger.debug('VPS_NAME_SEARCH_RESULT model=%s ids=%s', self._name, [row[0] for row in result])
        return result

    @api.model
    def _vps_ranked_web_search_read(
        self,
        super_web_search_read,
        domain,
        specification,
        offset=0,
        limit=None,
        order=None,
        count_limit=None,
    ):
        """Rank paged Search More/Catalog data without hiding unmapped records."""
        started = time.perf_counter()
        role_ids = self._vps_role_ids()
        rank_domains, mapped_ids = self._vps_rank_domains(role_ids)
        total = self.search_count(domain, limit=count_limit)
        remaining_offset = offset
        remaining_limit = limit
        records = self.browse()
        bucket_counts = {}

        for role, role_domain in rank_domains:
            bucket_domain = expression.AND([domain, role_domain])
            bucket_count = self.search_count(bucket_domain)
            bucket_counts[role] = bucket_count
            if remaining_offset >= bucket_count:
                remaining_offset -= bucket_count
                continue
            bucket_limit = remaining_limit
            bucket_records = self.search(
                bucket_domain,
                offset=remaining_offset,
                limit=bucket_limit,
                order=order,
            )
            records |= bucket_records
            remaining_offset = 0
            if remaining_limit is not None:
                remaining_limit -= len(bucket_records)
                if remaining_limit <= 0:
                    break

        values = records.web_read(specification)
        vendor, company = self._vps_context_records()
        elapsed_ms = (time.perf_counter() - started) * 1000
        _logger.info(
            'VPS_WEB_SEARCH model=%s source=%s vendor=%s company=%s offset=%s limit=%s '
            'total=%s buckets=%s returned=%s elapsed_ms=%.2f',
            self._name,
            self.env.context.get('vendor_priority_source', 'unknown'),
            vendor.id,
            company.id,
            offset,
            limit,
            total,
            bucket_counts,
            len(values),
            elapsed_ms,
        )
        _logger.debug('VPS_WEB_SEARCH_RESULT model=%s ids=%s', self._name, records.ids)
        return {'length': total, 'records': values}

