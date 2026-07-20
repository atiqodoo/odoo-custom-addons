import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class ProductTag(models.Model):
    _inherit = "product.tag"

    is_volume_reporting_grade = fields.Boolean(
        string="Volume Reporting Grade",
        help="Marks this tag as an exclusive grade used by movement-volume reports.",
    )

    @api.constrains(
        "is_volume_reporting_grade", "product_template_ids", "product_product_ids"
    )
    def _check_exclusive_volume_grade(self):
        templates = self.mapped("product_template_ids")
        for template in templates:
            grades = template.product_tag_ids.filtered("is_volume_reporting_grade")
            if len(grades) > 1:
                _logger.warning(
                    "VOLUME_GRADE_CONFLICT template_id=%s grade_ids=%s",
                    template.id,
                    grades.ids,
                )
                raise ValidationError(
                    _(
                        "Product %(product)s cannot have multiple volume reporting grades: %(grades)s.",
                        product=template.display_name,
                        grades=", ".join(grades.mapped("name")),
                    )
                )
                raise ValidationError(
                    _(
                        "Product %(product)s has more than one volume reporting grade: %(grades)s. "
                        "Keep only one grade tag.",
                        product=template.display_name,
                        grades=", ".join(grades.mapped("name")),
                    )
                )
        for product in self.mapped("product_ids"):
            grades = product.all_product_tag_ids.filtered("is_volume_reporting_grade")
            if len(grades) > 1:
                _logger.warning(
                    "VOLUME_GRADE_VARIANT_CONFLICT product_id=%s grade_ids=%s",
                    product.id,
                    grades.ids,
                )
                raise ValidationError(
                    _(
                        "Product variant %(product)s has more than one volume reporting grade: %(grades)s.",
                        product=product.display_name,
                        grades=", ".join(grades.mapped("name")),
                    )
                )


class ProductTemplate(models.Model):
    _inherit = "product.template"

    volume_reporting_grade_id = fields.Many2one(
        "product.tag",
        string="Volume Reporting Grade",
        compute="_compute_volume_reporting_grade_id",
        store=True,
        index=True,
        help="Automatically derived from the single product tag marked as a volume reporting grade.",
    )

    @api.depends("product_tag_ids", "product_tag_ids.is_volume_reporting_grade")
    def _compute_volume_reporting_grade_id(self):
        for template in self:
            grades = template.product_tag_ids.filtered("is_volume_reporting_grade")
            template.volume_reporting_grade_id = grades[:1]

    @api.constrains("product_tag_ids")
    def _check_single_volume_reporting_grade(self):
        for template in self:
            grades = template.product_tag_ids.filtered("is_volume_reporting_grade")
            if len(grades) > 1:
                _logger.warning(
                    "VOLUME_GRADE_CONFLICT template_id=%s grade_ids=%s",
                    template.id,
                    grades.ids,
                )


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.constrains("additional_product_tag_ids")
    def _check_single_variant_volume_reporting_grade(self):
        for product in self:
            grades = product.all_product_tag_ids.filtered("is_volume_reporting_grade")
            if len(grades) > 1:
                _logger.warning(
                    "VOLUME_GRADE_VARIANT_CONFLICT product_id=%s grade_ids=%s",
                    product.id,
                    grades.ids,
                )
                raise ValidationError(
                    _(
                        "Product variant %(product)s cannot have multiple volume reporting grades: %(grades)s.",
                        product=product.display_name,
                        grades=", ".join(grades.mapped("name")),
                    )
                )
