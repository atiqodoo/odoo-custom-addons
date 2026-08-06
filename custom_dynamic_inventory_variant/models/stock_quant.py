import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class StockQuant(models.Model):
    _inherit = "stock.quant"

    dynamic_product_tmpl_id = fields.Many2one(
        "product.template",
        string="Product Template",
        copy=False,
        help="Template used to create or find a dynamic variant for this physical count line.",
    )
    dynamic_attribute_value_ids = fields.Many2many(
        "product.template.attribute.value",
        "stock_quant_dynamic_ptav_rel",
        "quant_id",
        "ptav_id",
        string="Variant Values",
        copy=False,
        help="Template-specific attribute values used to create or find the product variant.",
    )
    dynamic_variant_debug_message = fields.Text(
        string="Dynamic Variant Debug",
        copy=False,
        readonly=True,
        help="Last dynamic variant resolution message for troubleshooting.",
    )

    @api.model
    def _get_inventory_fields_create(self):
        fields_list = super()._get_inventory_fields_create()
        return fields_list + self._get_dynamic_variant_inventory_fields()

    @api.model
    def _get_inventory_fields_write(self):
        fields_list = super()._get_inventory_fields_write()
        return fields_list + self._get_dynamic_variant_inventory_fields()

    @api.model
    def _get_dynamic_variant_inventory_fields(self):
        return [
            "dynamic_product_tmpl_id",
            "dynamic_attribute_value_ids",
            "dynamic_variant_debug_message",
        ]

    @api.onchange("dynamic_product_tmpl_id")
    def _onchange_dynamic_product_tmpl_id(self):
        for quant in self:
            if quant.dynamic_product_tmpl_id:
                _logger.debug(
                    "Dynamic variant onchange: template selected. quant=%s template_id=%s template=%s user=%s",
                    quant.id or "new",
                    quant.dynamic_product_tmpl_id.id,
                    quant.dynamic_product_tmpl_id.display_name,
                    self.env.user.id,
                )
            quant.dynamic_attribute_value_ids = [(5, 0, 0)]
            quant.product_id = False
            quant.dynamic_variant_debug_message = False

    @api.onchange("dynamic_product_tmpl_id", "dynamic_attribute_value_ids", "inventory_quantity", "inventory_quantity_auto_apply")
    def _onchange_dynamic_variant_values(self):
        for quant in self:
            if not quant.dynamic_product_tmpl_id or not quant.dynamic_attribute_value_ids:
                continue
            if quant.product_id:
                continue
            try:
                product = quant._resolve_dynamic_variant_from_record(raise_if_incomplete=False)
            except UserError as error:
                quant.product_id = False
                quant.dynamic_variant_debug_message = str(error)
                _logger.warning(
                    "Dynamic variant onchange failed. quant=%s template_id=%s value_ids=%s error=%s",
                    quant.id or "new",
                    quant.dynamic_product_tmpl_id.id,
                    quant.dynamic_attribute_value_ids.ids,
                    error,
                )
            else:
                if product:
                    quant.product_id = product
                    _logger.debug(
                        "Dynamic variant onchange assigned product. quant=%s product_id=%s",
                        quant.id or "new",
                        product.id,
                    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._prepare_dynamic_variant_product_id(vals)
        return super().create(vals_list)

    def action_generate_dynamic_variant(self):
        for quant in self:
            product = quant._resolve_dynamic_variant_from_record()
            quant.write(
                {
                    "product_id": product.id,
                    "dynamic_variant_debug_message": quant._dynamic_variant_success_message(product),
                }
            )
        return True

    @api.model
    def _prepare_dynamic_variant_product_id(self, vals):
        """Fill product_id from helper fields before Odoo's inventory create restrictions run."""
        if vals.get("product_id") or not vals.get("dynamic_product_tmpl_id"):
            return vals

        template = self.env["product.template"].browse(vals["dynamic_product_tmpl_id"]).exists()
        combination = self._get_dynamic_combination_from_vals(template, vals)

        _logger.debug(
            "Dynamic variant create fallback started. template_id=%s value_ids=%s context=%s",
            template.id if template else None,
            combination.ids,
            self._dynamic_variant_context_log(),
        )

        product = self._get_or_create_dynamic_variant(template, combination)
        vals["product_id"] = product.id
        vals["dynamic_variant_debug_message"] = self._dynamic_variant_success_message(product)

        _logger.info(
            "Dynamic variant create fallback resolved product. template_id=%s product_id=%s product=%s value_ids=%s",
            template.id,
            product.id,
            product.display_name,
            combination.ids,
        )
        return vals

    def _resolve_dynamic_variant_from_record(self, raise_if_incomplete=True):
        self.ensure_one()
        template = self.dynamic_product_tmpl_id
        combination = self.dynamic_attribute_value_ids

        if not template:
            if raise_if_incomplete:
                raise UserError(_("Select a product template before generating the variant."))
            return self.env["product.product"]

        if not combination:
            if raise_if_incomplete:
                raise UserError(_("Select at least one variant value before generating the variant."))
            return self.env["product.product"]

        _logger.debug(
            "Dynamic variant record resolution started. quant=%s template_id=%s value_ids=%s context=%s",
            self.id or "new",
            template.id,
            combination.ids,
            self._dynamic_variant_context_log(),
        )

        product = self._get_or_create_dynamic_variant(template, combination)
        self.dynamic_variant_debug_message = self._dynamic_variant_success_message(product)

        _logger.info(
            "Dynamic variant record resolution completed. quant=%s template_id=%s product_id=%s product=%s value_ids=%s",
            self.id or "new",
            template.id,
            product.id,
            product.display_name,
            combination.ids,
        )
        return product

    @api.model
    def _get_dynamic_combination_from_vals(self, template, vals):
        if not template:
            raise UserError(_("The selected product template could not be found."))

        value_ids = self._extract_many2many_ids(vals.get("dynamic_attribute_value_ids"))
        if not value_ids:
            raise UserError(_("Select variant values before saving the inventory adjustment line."))

        combination = self.env["product.template.attribute.value"].browse(value_ids).exists()
        if len(combination) != len(set(value_ids)):
            _logger.warning(
                "Dynamic variant value mismatch during create. template_id=%s requested_ids=%s existing_ids=%s",
                template.id,
                value_ids,
                combination.ids,
            )
            raise UserError(_("One or more selected variant values no longer exist."))

        return self._normalize_dynamic_combination(template, self._complete_dynamic_combination(template, combination))

    @api.model
    def _extract_many2many_ids(self, commands):
        if not commands:
            return []
        if isinstance(commands, int):
            return [commands]
        if isinstance(commands, (list, tuple)) and all(isinstance(item, int) for item in commands):
            return list(commands)

        ids = []
        for command in commands:
            if not isinstance(command, (list, tuple)) or not command:
                continue
            operation = command[0]
            if operation == 6:
                ids = list(command[2] or [])
            elif operation == 4:
                ids.append(command[1])
            elif operation == 5:
                ids = []
            elif operation == 3 and command[1] in ids:
                ids.remove(command[1])
        return ids

    @api.model
    def _get_or_create_dynamic_variant(self, template, combination):
        template.ensure_one()
        combination = self._normalize_dynamic_combination(
            template,
            self._complete_dynamic_combination(template, combination.exists()),
        )
        self._validate_dynamic_combination(template, combination)

        existing_product = template._get_variant_for_combination(combination)
        if existing_product:
            _logger.info(
                "Dynamic variant already exists. template_id=%s product_id=%s active=%s value_ids=%s",
                template.id,
                existing_product.id,
                existing_product.active,
                combination.ids,
            )
            return existing_product

        _logger.debug(
            "Calling Odoo dynamic variant creator. template_id=%s has_dynamic=%s value_ids=%s",
            template.id,
            template.has_dynamic_attributes(),
            combination.ids,
        )

        try:
            product = template._create_product_variant(combination, log_warning=True)
        except Exception:
            _logger.exception(
                "Odoo dynamic variant creation raised an exception. template_id=%s value_ids=%s user=%s",
                template.id,
                combination.ids,
                self.env.user.id,
            )
            raise

        if not product:
            _logger.warning(
                "Odoo dynamic variant creator returned no product. template_id=%s has_dynamic=%s value_ids=%s",
                template.id,
                template.has_dynamic_attributes(),
                combination.ids,
            )
            raise UserError(
                _(
                    "Odoo could not create this variant. Confirm the template uses dynamic attributes "
                    "and that the selected values form an allowed combination."
                )
            )

        if not product.is_storable:
            _logger.warning(
                "Dynamic variant creation resolved a non-storable product. template_id=%s product_id=%s value_ids=%s",
                template.id,
                product.id,
                combination.ids,
            )
            raise UserError(_("The resolved variant is not a storable product. Enable inventory tracking on the template."))

        _logger.info(
            "Dynamic variant created. template_id=%s product_id=%s product=%s value_ids=%s",
            template.id,
            product.id,
            product.display_name,
            combination.ids,
        )
        return product

    @api.model
    def _complete_dynamic_combination(self, template, combination):
        """Add deterministic single-value attributes so users only choose meaningful options."""
        if not template or not combination:
            return combination

        selected_lines = combination.mapped("attribute_line_id")
        lines_to_complete = template.valid_product_template_attribute_line_ids.filtered(
            lambda line: line not in selected_lines and len(line.product_template_value_ids._only_active()) == 1
        )
        completed_combination = combination | lines_to_complete.product_template_value_ids._only_active()

        if completed_combination != combination:
            _logger.debug(
                "Dynamic variant combination auto-completed with single-value lines. template_id=%s original_value_ids=%s completed_value_ids=%s completed_line_ids=%s",
                template.id,
                combination.ids,
                completed_combination.ids,
                lines_to_complete.ids,
            )

        return completed_combination

    @api.model
    def _normalize_dynamic_combination(self, template, combination):
        """Return values in template attribute-line order.

        Odoo's product configurator helpers compare recordsets of template
        attribute lines. Keeping the combination in the same order as the
        template avoids false negatives in editable list/onchange flows.
        """
        if not template or not combination:
            return combination

        sequence_by_line = {
            line.id: index
            for index, line in enumerate(template.valid_product_template_attribute_line_ids)
        }
        normalized = combination.sorted(
            lambda value: (
                sequence_by_line.get(value.attribute_line_id.id, 999999),
                value.attribute_line_id.sequence,
                value.attribute_line_id.id,
                value.id,
            )
        )

        if normalized.ids != combination.ids:
            _logger.debug(
                "Dynamic variant combination normalized. template_id=%s original_value_ids=%s normalized_value_ids=%s",
                template.id,
                combination.ids,
                normalized.ids,
            )

        return normalized

    @api.model
    def _validate_dynamic_combination(self, template, combination):
        if not combination:
            raise UserError(_("Select variant values before generating the variant."))

        if not template.is_storable:
            _logger.warning(
                "Dynamic variant validation rejected non-storable template. template_id=%s template=%s",
                template.id,
                template.display_name,
            )
            raise UserError(_("The selected product template is not configured to track inventory."))

        wrong_template_values = combination.filtered(lambda value: value.product_tmpl_id != template)
        if wrong_template_values:
            _logger.warning(
                "Dynamic variant validation rejected values from another template. template_id=%s wrong_value_ids=%s",
                template.id,
                wrong_template_values.ids,
            )
            raise UserError(_("All selected variant values must belong to the selected product template."))

        attributes = combination.mapped("attribute_id")
        if len(attributes) != len(combination):
            _logger.warning(
                "Dynamic variant validation rejected duplicate attributes. template_id=%s value_ids=%s attribute_ids=%s",
                template.id,
                combination.ids,
                attributes.ids,
            )
            raise UserError(_("Select only one value per attribute."))

        variant_lines = template.valid_product_template_attribute_line_ids._without_no_variant_attributes()
        missing_lines = variant_lines.filtered(lambda line: line.attribute_id not in attributes)
        if missing_lines:
            _logger.debug(
                "Dynamic variant validation found missing variant attributes. template_id=%s missing_line_ids=%s value_ids=%s",
                template.id,
                missing_lines.ids,
                combination.ids,
            )
            raise UserError(
                _(
                    "Select a value for every variant attribute on this template. Missing: %(attributes)s",
                    attributes=", ".join(missing_lines.mapped("attribute_id.display_name")),
                )
            )

        if not template._is_combination_possible(combination):
            diagnostics = self._get_dynamic_combination_diagnostics(template, combination)
            _logger.warning(
                "Dynamic variant validation rejected impossible combination. template_id=%s value_ids=%s diagnostics=%s",
                template.id,
                combination.ids,
                diagnostics,
            )
            raise UserError(_("The selected attribute values are not an allowed variant combination."))

        if not template.has_dynamic_attributes() and not template._get_variant_for_combination(combination):
            _logger.warning(
                "Dynamic variant validation rejected non-dynamic template without existing variant. template_id=%s value_ids=%s",
                template.id,
                combination.ids,
            )
            raise UserError(_("This product template does not use dynamic variant creation."))

        _logger.debug(
            "Dynamic variant validation passed. template_id=%s value_ids=%s",
            template.id,
            combination.ids,
        )

    @api.model
    def _get_dynamic_combination_diagnostics(self, template, combination):
        attribute_lines = template.valid_product_template_attribute_line_ids._without_no_variant_attributes()
        active_values = attribute_lines.product_template_value_ids._only_active()
        own_exclusions = template._get_own_attribute_exclusions(combination.ids)
        combination_ids = set(combination.ids)
        excluded_ids = set()
        for excluded in own_exclusions.values():
            excluded_ids.update(excluded)

        return {
            "template_attribute_line_ids": attribute_lines.ids,
            "combination_attribute_line_ids": combination.mapped("attribute_line_id").ids,
            "active_value_ids": active_values.ids,
            "combination_value_ids": combination.ids,
            "missing_from_active_values": list(combination_ids - set(active_values.ids)),
            "conflicting_excluded_value_ids": list(combination_ids & excluded_ids),
            "has_dynamic_attributes": template.has_dynamic_attributes(),
            "existing_variant_id": template._get_variant_for_combination(combination).id,
        }

    @api.model
    def _dynamic_variant_success_message(self, product):
        return _("Dynamic variant resolved: %(product)s [ID %(product_id)s]", product=product.display_name, product_id=product.id)

    @api.model
    def _dynamic_variant_context_log(self):
        return {
            "inventory_mode": self.env.context.get("inventory_mode"),
            "import_file": self.env.context.get("import_file"),
            "user_id": self.env.user.id,
            "company_id": self.env.company.id,
        }
