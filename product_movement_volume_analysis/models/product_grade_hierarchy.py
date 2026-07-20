import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class ProductTag(models.Model):
    _inherit = "product.tag"

    volume_grade_parent_id = fields.Many2one(
        "product.tag",
        string="Parent Volume Grade",
        index=True,
        ondelete="restrict",
        domain="[('is_volume_reporting_grade', '=', True)]",
        help="Parent grade used to structure volume reporting grades into a hierarchy.",
    )
    volume_grade_child_ids = fields.One2many(
        "product.tag",
        "volume_grade_parent_id",
        string="Child Volume Grades",
    )
    volume_grade_root_id = fields.Many2one(
        "product.tag",
        string="Root Volume Grade",
        compute="_compute_volume_grade_hierarchy",
        store=True,
        index=True,
        help="Top-most grade in the volume reporting grade hierarchy.",
    )
    volume_grade_path = fields.Char(
        string="Volume Grade Path",
        compute="_compute_volume_grade_hierarchy",
        store=True,
        index=True,
        help="Full hierarchy path, for example Premium / Decorative / Premium Paints.",
    )
    volume_grade_level = fields.Integer(
        string="Volume Grade Level",
        compute="_compute_volume_grade_hierarchy",
        store=True,
        help="Hierarchy depth where root grades are level 1.",
    )
    is_volume_grade_leaf = fields.Boolean(
        string="Leaf Volume Grade",
        compute="_compute_is_volume_grade_leaf",
        store=True,
        index=True,
        help="A leaf grade has no child volume reporting grades and is suitable for final variant mapping.",
    )

    @api.depends(
        "is_volume_reporting_grade",
        "volume_grade_parent_id",
        "volume_grade_parent_id.name",
        "volume_grade_parent_id.volume_grade_parent_id",
        "volume_grade_parent_id.volume_grade_path",
    )
    def _compute_volume_grade_hierarchy(self):
        for tag in self:
            if not tag.is_volume_reporting_grade:
                tag.volume_grade_root_id = False
                tag.volume_grade_path = False
                tag.volume_grade_level = 0
                continue

            lineage = tag._get_volume_grade_lineage()
            tag.volume_grade_root_id = lineage[:1]
            tag.volume_grade_path = " / ".join(lineage.mapped("name"))
            tag.volume_grade_level = len(lineage)

    @api.depends(
        "is_volume_reporting_grade",
        "volume_grade_child_ids",
        "volume_grade_child_ids.is_volume_reporting_grade",
    )
    def _compute_is_volume_grade_leaf(self):
        for tag in self:
            tag.is_volume_grade_leaf = bool(
                tag.is_volume_reporting_grade
                and not tag.volume_grade_child_ids.filtered("is_volume_reporting_grade")
            )

    @api.constrains("is_volume_reporting_grade", "volume_grade_parent_id")
    def _check_volume_grade_hierarchy(self):
        for tag in self:
            if tag.volume_grade_parent_id and not tag.is_volume_reporting_grade:
                raise ValidationError(
                    _(
                        "Only volume reporting grades can have a parent volume grade. "
                        "Enable Volume Reporting Grade on %(tag)s first.",
                        tag=tag.display_name,
                    )
                )
            if tag.volume_grade_parent_id and not tag.volume_grade_parent_id.is_volume_reporting_grade:
                raise ValidationError(
                    _(
                        "Parent grade %(parent)s must be marked as a Volume Reporting Grade.",
                        parent=tag.volume_grade_parent_id.display_name,
                    )
                )
            tag._check_volume_grade_cycle()

    def _check_volume_grade_cycle(self):
        for tag in self:
            seen = self.env["product.tag"]
            parent = tag.volume_grade_parent_id
            while parent:
                if parent == tag or parent in seen:
                    _logger.warning(
                        "VOLUME_GRADE_HIERARCHY_CYCLE tag_id=%s parent_id=%s seen_ids=%s",
                        tag.id,
                        parent.id,
                        seen.ids,
                    )
                    raise ValidationError(
                        _(
                            "Volume grade hierarchy cannot contain a circular parent chain for %(tag)s.",
                            tag=tag.display_name,
                        )
                    )
                seen |= parent
                parent = parent.volume_grade_parent_id

    def _get_volume_grade_lineage(self):
        self.ensure_one()
        lineage = self.env["product.tag"]
        current = self
        seen = self.env["product.tag"]
        while current:
            if current in seen:
                _logger.warning(
                    "VOLUME_GRADE_HIERARCHY_LINEAGE_CYCLE tag_id=%s current_id=%s seen_ids=%s",
                    self.id,
                    current.id,
                    seen.ids,
                )
                break
            seen |= current
            lineage = current | lineage
            current = current.volume_grade_parent_id
        return lineage
