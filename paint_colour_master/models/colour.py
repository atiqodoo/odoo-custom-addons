from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ColourFandeck(models.Model):
    _name = 'colour.fandeck'
    _description = 'Paint Colour Fandeck'

    name = fields.Char(string='Fandeck Name', required=True)
    description = fields.Text(string='Description')
    colour_code_ids = fields.One2many('colour.code', 'fandeck_id', string='Colours')

    _sql_constraints = [
        ('unique_fandeck_name', 'UNIQUE(name)', 'Fandeck name must be unique.')
    ]


class ColourCode(models.Model):
    _name = 'colour.code'
    _description = 'Paint Colour Code'
    _rec_name = 'code'  # Set code as the primary name field

    fandeck_id = fields.Many2one('colour.fandeck', string='Fandeck', required=True, ondelete='cascade', index=True)
    code = fields.Char(string='Colour Code', required=True, index=True)
    name = fields.Char(string='Colour Name', required=True, index=True)
    vendor_id = fields.Many2one('res.partner', string='Vendor', required=True, domain=[('supplier_rank', '>', 0)], index=True)

    _sql_constraints = [
        ('unique_code_per_vendor', 'UNIQUE(vendor_id, code)',
         'This colour code already exists for this vendor across all fandecks. Codes must be unique per vendor.')
    ]

    @api.constrains('code', 'vendor_id')
    def _check_unique_code_per_vendor(self):
        """Ensure no duplicate colour codes exist for the same vendor across different fandecks."""
        for record in self:
            if record.code and record.vendor_id:
                existing_records = self.search([
                    ('id', '!=', record.id),
                    ('code', '=', record.code),
                    ('vendor_id', '=', record.vendor_id.id),
                ])
                if existing_records:
                    raise ValidationError(
                        f'Colour code "{record.code}" already exists for vendor "{record.vendor_id.name}". '
                        'Codes must be unique per vendor across all fandecks. '
                        'Please use a different code or resolve the existing duplicate.'
                    )

    @api.constrains('code')
    def _check_code_format(self):
        """Ensure colour codes contain no spaces and only uppercase letters."""
        for record in self:
            if record.code:
                if ' ' in record.code:
                    raise ValidationError('Colour code cannot contain spaces.')
                if any(c.isalpha() and c.islower() for c in record.code):
                    raise ValidationError('Colour code must contain only uppercase letters.')

    def name_get(self):
        """Display format: [CODE] Name"""
        result = []
        for record in self:
            display_name = f"[{record.code}] {record.name}"
            result.append((record.id, display_name))
        return result

    @api.model
    def name_search(self, name, args=None, operator='ilike', limit=100):
        """Customize name_search to search both code and name, prioritizing code matches.
        This method is called when searching in Many2one fields - no fandeck restriction needed."""
        args = args or []
        
        if name:
            # First, try exact code match
            domain = [('code', '=', name)]
            record_ids = self._search(domain + args, limit=limit)
            
            # If no exact match, try partial matches on both code and name
            if not record_ids:
                domain = ['|', ('code', operator, name), ('name', operator, name)]
                record_ids = self._search(domain + args, limit=limit)
        else:
            record_ids = self._search(args, limit=limit)
        
        if record_ids:
            return self.browse(record_ids).name_get()
        return []
    
    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=None, order=None):
        """Override _name_search to remove fandeck domain restriction during search."""
        domain = domain or []
        # Remove any fandeck_id domain restrictions during search
        domain = [d for d in domain if not (isinstance(d, (list, tuple)) and len(d) == 3 and d[0] == 'fandeck_id')]
        return super()._name_search(name, domain=domain, operator=operator, limit=limit, order=order)