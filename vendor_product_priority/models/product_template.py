from odoo import api, fields, models
from odoo.osv import expression


class ProductTemplate(models.Model):
    _name = 'product.template'
    _inherit = ['product.template', 'vendor.product.priority.search.mixin']

    vps_template_primary_vendor_id = fields.Many2one(
        'res.partner',
        string='Template Primary Vendor',
        compute='_compute_vps_vendor_mapping',
        search='_search_vps_template_primary_vendor_id',
        compute_sudo=True,
        help='First distinct vendor in this template Purchase-tab sequence.',
    )
    vps_template_secondary_vendor_id = fields.Many2one(
        'res.partner',
        string='Template Secondary Vendor',
        compute='_compute_vps_vendor_mapping',
        search='_search_vps_template_secondary_vendor_id',
        compute_sudo=True,
        help='Second distinct vendor in this template Purchase-tab sequence.',
    )
    vps_template_mapping_state = fields.Selection(
        [
            ('none', 'No Vendor'),
            ('primary_only', 'Primary Only'),
            ('complete', 'Primary and Secondary'),
        ],
        string='Template Mapping Status',
        compute='_compute_vps_vendor_mapping',
        compute_sudo=True,
    )

    @api.depends(
        'seller_ids.sequence',
        'seller_ids.partner_id',
        'seller_ids.product_id',
        'seller_ids.company_id',
        'seller_ids.min_qty',
        'seller_ids.price',
        'seller_ids.partner_id.active',
    )
    @api.depends_context('company')
    def _compute_vps_vendor_mapping(self):
        mapping = self.env['vendor.product.priority.service'].get_mapping(
            'product.template',
            self,
            company=self.env.company,
        )
        for template in self:
            values = mapping.get(template.id, {})
            template.vps_template_primary_vendor_id = values.get('primary_vendor_id')
            template.vps_template_secondary_vendor_id = values.get('secondary_vendor_id')
            if template.vps_template_secondary_vendor_id:
                template.vps_template_mapping_state = 'complete'
            elif template.vps_template_primary_vendor_id:
                template.vps_template_mapping_state = 'primary_only'
            else:
                template.vps_template_mapping_state = 'none'

    @api.model
    def _search_vps_vendor_role(self, operator, value, role):
        if operator not in ('=', 'in', '!=', 'not in'):
            raise NotImplementedError('Vendor mapping fields support =, !=, in, and not in searches.')
        vendor_ids = value if operator in ('in', 'not in') else [value]
        matching_ids = set()
        service = self.env['vendor.product.priority.service']
        for vendor in self.env['res.partner'].browse(vendor_ids).exists():
            matching_ids.update(service.get_record_ids_by_role(
                'product.template', vendor, company=self.env.company,
            ).get(role, []))
        positive = operator in ('=', 'in')
        return [('id', 'in' if positive else 'not in', list(matching_ids))]

    @api.model
    def _search_vps_template_primary_vendor_id(self, operator, value):
        return self._search_vps_vendor_role(operator, value, 1)

    @api.model
    def _search_vps_template_secondary_vendor_id(self, operator, value):
        return self._search_vps_vendor_role(operator, value, 2)

    @api.model
    def _vps_exact_domain(self, name):
        return expression.OR([
            [('default_code', '=', name)],
            [('product_variant_ids.default_code', '=', name)],
            [('product_variant_ids.barcode', '=', name)],
        ])

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        if not self._vps_is_enabled():
            return super().name_search(name=name, args=args, operator=operator, limit=limit)
        return self._vps_ranked_name_search(
            super().name_search,
            name=name,
            args=args,
            operator=operator,
            limit=limit,
        )

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        if not self._vps_is_enabled():
            return super().web_search_read(
                domain, specification, offset=offset, limit=limit,
                order=order, count_limit=count_limit,
            )
        return self._vps_ranked_web_search_read(
            super().web_search_read,
            domain,
            specification,
            offset=offset,
            limit=limit,
            order=order,
            count_limit=count_limit,
        )
