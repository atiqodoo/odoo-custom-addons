from odoo import models, fields, api


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    fandeck_id = fields.Many2one(
        'colour.fandeck',
        string='Fandeck',
        help='Select or create a fandeck for this product.'
    )
    colour_code_id = fields.Many2one(
        'colour.code',
        string='Colour Code',
        help='Select or create a colour code for this product. Search by code or name.'
    )
    # Keep as Char for manual input capability
    colour_name = fields.Char(
        string='Colour Name',
        help='Type to search and match colour codes.',
        store=True
    )
    # Add a helper Many2one field for dropdown search by name
    colour_name_id = fields.Many2one(
        'colour.code',
        string='Search by Colour Name',
        help='Searchable dropdown to find colours by name.',
        compute='_compute_colour_name_id',
        inverse='_inverse_colour_name_id',
        store=False
    )

    @api.depends('colour_code_id')
    def _compute_colour_name_id(self):
        """Sync colour_name_id with colour_code_id."""
        for record in self:
            record.colour_name_id = record.colour_code_id

    def _inverse_colour_name_id(self):
        """When colour_name_id is set, update colour_code_id."""
        for record in self:
            if record.colour_name_id:
                record.colour_code_id = record.colour_name_id
                record.fandeck_id = record.colour_name_id.fandeck_id
                record.colour_name = record.colour_name_id.name

    @api.onchange('fandeck_id')
    def _onchange_fandeck_id(self):
        """When fandeck changes, try to keep the colour code if it belongs to new fandeck."""
        if self.fandeck_id and self.colour_code_id:
            if self.colour_code_id.fandeck_id != self.fandeck_id:
                same_code = self.env['colour.code'].search([
                    ('fandeck_id', '=', self.fandeck_id.id),
                    ('code', '=', self.colour_code_id.code)
                ], limit=1)
                
                if same_code:
                    self.colour_code_id = same_code
                    self.colour_name = same_code.name
                else:
                    self.colour_code_id = False
                    self.colour_name = False

    @api.onchange('colour_code_id')
    def _onchange_colour_code_id(self):
        """Auto-fill fandeck and colour name when colour code is selected."""
        if self.colour_code_id:
            self.fandeck_id = self.colour_code_id.fandeck_id
            self.colour_name = self.colour_code_id.name
        else:
            self.colour_name = False

    @api.onchange('colour_name')
    def _onchange_colour_name(self):
        """Search for matching colour code when colour name is typed."""
        if self.colour_name and len(self.colour_name) >= 3:  # Only search after 3 characters
            domain = ['|', ('code', 'ilike', self.colour_name), ('name', 'ilike', self.colour_name)]
            
            if self.fandeck_id:
                fandeck_match = self.env['colour.code'].search(
                    [('fandeck_id', '=', self.fandeck_id.id)] + domain, 
                    limit=1
                )
                if fandeck_match:
                    self.colour_code_id = fandeck_match
                    self.colour_name = fandeck_match.name
                    return
            
            colour = self.env['colour.code'].search(domain, limit=1)
            if colour:
                self.colour_code_id = colour
                self.fandeck_id = colour.fandeck_id
                self.colour_name = colour.name