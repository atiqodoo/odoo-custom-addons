import logging
from collections import defaultdict

from odoo import api, models


_logger = logging.getLogger(__name__)


class VendorPriorityService(models.AbstractModel):
    """Central source of truth for position-derived vendor roles.

    Roles are calculated from applicable ``product.supplierinfo`` rows.  The
    first distinct commercial vendor is primary, the second is secondary, and
    all later vendors are alternatives.  A vendor with several quantity/price
    rows is deliberately counted once.
    """

    _name = 'vendor.product.priority.service'
    _description = 'Vendor Product Priority Service'

    ROLE_PRIMARY = 1
    ROLE_SECONDARY = 2
    ROLE_ALTERNATIVE = 3

    @api.model
    def _normalise_company(self, company=None):
        return company or self.env.company

    @api.model
    def _normalise_vendor(self, vendor):
        vendor = vendor.exists()
        return vendor.commercial_partner_id if vendor else vendor

    @api.model
    def _ranked_vendor_rows(self, model_name, company=None, record_ids=None):
        """Return ``[(record_id, commercial_vendor_id, rank), ...]``.

        SQL window functions keep the work in PostgreSQL and avoid per-product
        ORM loops.  Returned record ids are still passed through normal ORM
        searches by consumers, so access rules remain authoritative.
        """
        company = self._normalise_company(company)
        record_ids = tuple(set(record_ids or ()))

        # Raw SQL must see pending ORM changes immediately after users reorder
        # vendor rows or tests create mappings inside the current transaction.
        self.env['product.supplierinfo'].flush_model([
            'product_tmpl_id', 'product_id', 'partner_id', 'company_id',
            'sequence', 'min_qty', 'price',
        ])
        self.env['res.partner'].flush_model(['active', 'commercial_partner_id'])
        if model_name == 'product.product':
            self.env['product.product'].flush_model(['product_tmpl_id'])

        if model_name == 'product.product':
            record_column = 'pp.id'
            record_filter = 'AND pp.id IN %s' if record_ids else ''
            join_product = """
                JOIN product_product pp
                  ON pp.product_tmpl_id = si.product_tmpl_id
                 AND (si.product_id IS NULL OR si.product_id = pp.id)
            """
        elif model_name == 'product.template':
            record_column = 'pt.id'
            record_filter = 'AND pt.id IN %s' if record_ids else ''
            join_product = """
                JOIN product_template pt ON pt.id = si.product_tmpl_id
            """
        else:
            raise ValueError(f'Unsupported vendor priority model: {model_name}')

        params = [company.id]
        if record_ids:
            params.append(record_ids)

        query = f"""
            WITH applicable_lines AS (
                SELECT
                    {record_column} AS record_id,
                    rp.commercial_partner_id AS vendor_id,
                    si.sequence,
                    si.min_qty,
                    si.price,
                    si.id AS supplierinfo_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY {record_column}, rp.commercial_partner_id
                        ORDER BY si.sequence, si.min_qty DESC, si.price, si.id
                    ) AS vendor_line_number
                FROM product_supplierinfo si
                {join_product}
                JOIN res_partner rp ON rp.id = si.partner_id
                WHERE rp.active
                  AND (si.company_id IS NULL OR si.company_id = %s)
                  {record_filter}
            ), distinct_vendors AS (
                SELECT *
                  FROM applicable_lines
                 WHERE vendor_line_number = 1
            ), ranked_vendors AS (
                SELECT
                    record_id,
                    vendor_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY record_id
                        ORDER BY sequence, min_qty DESC, price, supplierinfo_id
                    ) AS vendor_rank
                  FROM distinct_vendors
            )
            SELECT record_id, vendor_id, vendor_rank
              FROM ranked_vendors
             ORDER BY record_id, vendor_rank
        """
        self.env.cr.execute(query, params)
        rows = self.env.cr.fetchall()
        _logger.debug(
            'VPS_MAP_SQL model=%s company=%s restricted_records=%s rows=%s',
            model_name,
            company.id,
            len(record_ids),
            len(rows),
        )
        return rows

    @api.model
    def get_mapping(self, model_name, records, company=None):
        """Return primary/secondary vendor ids for every requested record."""
        records = records.exists()
        result = {
            record.id: {'primary_vendor_id': False, 'secondary_vendor_id': False}
            for record in records
        }
        if not records:
            return result

        for record_id, vendor_id, rank in self._ranked_vendor_rows(
            model_name,
            company=company,
            record_ids=records.ids,
        ):
            if rank == self.ROLE_PRIMARY:
                result[record_id]['primary_vendor_id'] = vendor_id
            elif rank == self.ROLE_SECONDARY:
                result[record_id]['secondary_vendor_id'] = vendor_id

        _logger.debug(
            'VPS_MAP_COMPUTE model=%s company=%s records=%s mapped_primary=%s mapped_secondary=%s',
            model_name,
            (company or self.env.company).id,
            len(records),
            sum(bool(value['primary_vendor_id']) for value in result.values()),
            sum(bool(value['secondary_vendor_id']) for value in result.values()),
        )
        return result

    @api.model
    def get_record_ids_by_role(self, model_name, vendor, company=None):
        """Return record ids grouped into primary/secondary/alternative roles."""
        vendor = self._normalise_vendor(vendor)
        grouped = defaultdict(list)
        if not vendor:
            return grouped

        for record_id, vendor_id, rank in self._ranked_vendor_rows(
            model_name,
            company=company,
        ):
            if vendor_id != vendor.id:
                continue
            role = min(rank, self.ROLE_ALTERNATIVE)
            grouped[role].append(record_id)

        _logger.debug(
            'VPS_ROLE_IDS model=%s vendor=%s company=%s primary=%s secondary=%s alternative=%s',
            model_name,
            vendor.id,
            (company or self.env.company).id,
            len(grouped[self.ROLE_PRIMARY]),
            len(grouped[self.ROLE_SECONDARY]),
            len(grouped[self.ROLE_ALTERNATIVE]),
        )
        return grouped
