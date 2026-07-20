import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError


_logger = logging.getLogger(__name__)


OPERATION_FAMILIES = [
    ("vendor_receipt", "Vendor Receipt"),
    ("vendor_return", "Vendor Return"),
    ("customer_delivery", "Customer Delivery"),
    ("customer_return", "Customer Return"),
    ("internal_transfer", "Internal Transfer"),
    ("manufacturing_consumption", "Manufacturing Consumption"),
    ("manufacturing_production", "Manufacturing Production"),
    ("manufacturing_byproduct", "Manufacturing By-product"),
    ("inventory_gain", "Inventory Gain"),
    ("inventory_loss", "Inventory Loss"),
    ("scrap", "Scrap"),
    ("dropship", "Dropship"),
    ("transit", "Transit"),
    ("other", "Other"),
]

BUSINESS_CHANNELS = [
    ("pos", "Point of Sale"),
    ("sales", "Sales"),
    ("purchase", "Purchase"),
    ("manufacturing", "Manufacturing"),
    ("inventory", "Inventory Adjustment"),
    ("scrap", "Scrap"),
    ("internal", "Internal Transfer"),
    ("other", "Other / Manual"),
]

TINT_MAPPING_STATUSES = [
    ("not_applicable", "Not Applicable"),
    ("mapped", "Mapped"),
    ("missing_base_product", "Missing Base Product"),
    ("missing_grade", "Missing Grade"),
    ("ambiguous_bom", "Ambiguous Tinting BOM"),
    ("failed", "Failed"),
]

GRADE_SOURCES = [
    ("product_tag", "Product Tag"),
    ("tinting_base_product", "Tinting Base Product"),
    ("none", "None"),
    ("failed", "Failed"),
]

MANUFACTURING_COMPONENT_ROLES = [
    ("not_applicable", "Not Applicable"),
    ("base_paint", "Base Paint"),
    ("colorant", "Colourant"),
    ("finished_tinted_product", "Finished Tinted Product"),
    ("byproduct", "By-product"),
    ("other_component", "Other Component"),
]


class ProductMovementVolume(models.Model):
    _name = "product.movement.volume"
    _description = "Product Movement Volume"
    _order = "date desc, id desc"
    _rec_name = "reference"

    reference = fields.Char(required=True, readonly=True, index=True)
    date = fields.Datetime(required=True, readonly=True, index=True)
    company_id = fields.Many2one("res.company", required=True, readonly=True, index=True)

    move_line_id = fields.Many2one(
        "stock.move.line", required=True, readonly=True, ondelete="restrict", index=True
    )
    move_id = fields.Many2one("stock.move", required=True, readonly=True, ondelete="restrict", index=True)
    picking_id = fields.Many2one("stock.picking", readonly=True, ondelete="set null", index=True)
    partner_id = fields.Many2one("res.partner", readonly=True, ondelete="set null", index=True)
    responsible_user_id = fields.Many2one("res.users", readonly=True, ondelete="set null", index=True)
    origin = fields.Char(readonly=True, index=True)

    product_id = fields.Many2one("product.product", required=True, readonly=True, index=True)
    product_tmpl_id = fields.Many2one("product.template", required=True, readonly=True, index=True)
    categ_id = fields.Many2one("product.category", required=True, readonly=True, index=True)
    grade_id = fields.Many2one("product.tag", readonly=True, ondelete="restrict", index=True)
    grade_source = fields.Selection(
        GRADE_SOURCES, default="none", readonly=True, index=True
    )
    tags_snapshot = fields.Char(readonly=True)
    tint_base_product_id = fields.Many2one(
        "product.product",
        string="Tint Base Product",
        readonly=True,
        ondelete="set null",
        index=True,
    )
    tint_base_categ_id = fields.Many2one(
        "product.category",
        string="Tint Base Category",
        readonly=True,
        ondelete="set null",
        index=True,
    )
    tint_mapping_status = fields.Selection(
        TINT_MAPPING_STATUSES,
        default="not_applicable",
        readonly=True,
        index=True,
    )
    tint_mapping_reason = fields.Char(readonly=True)
    tint_mapping_attempt_date = fields.Datetime(readonly=True)
    is_tinted_lineage_movement = fields.Boolean(readonly=True, index=True)
    manufacturing_component_role = fields.Selection(
        MANUFACTURING_COMPONENT_ROLES,
        default="not_applicable",
        readonly=True,
        index=True,
    )

    transaction_qty = fields.Float(
        string="Transaction Quantity", digits="Product Unit of Measure", readonly=True
    )
    transaction_uom_id = fields.Many2one("uom.uom", readonly=True, ondelete="restrict", index=True)
    conversion_ratio = fields.Float(string="UoM Ratio", digits=(16, 8), readonly=True)
    normalized_qty = fields.Float(
        string="Normalized Quantity", digits="Product Unit of Measure", readonly=True
    )
    reference_uom_id = fields.Many2one("uom.uom", readonly=True, ondelete="restrict", index=True)
    uom_category_id = fields.Many2one(
        "uom.category", string="UoM Category", readonly=True, ondelete="restrict", index=True
    )
    gross_movement_qty = fields.Float(
        string="Gross Movement", digits="Product Unit of Measure", readonly=True
    )
    inventory_signed_qty = fields.Float(
        string="Inventory Net Impact", digits="Product Unit of Measure", readonly=True
    )
    sales_net_qty = fields.Float(
        string="Net Sales Volume", digits="Product Unit of Measure", readonly=True
    )
    receipt_net_qty = fields.Float(
        string="Net Received Volume", digits="Product Unit of Measure", readonly=True
    )
    production_output_qty = fields.Float(
        string="Production Output", digits="Product Unit of Measure", readonly=True
    )
    production_consumption_qty = fields.Float(
        string="Production Consumption", digits="Product Unit of Measure", readonly=True
    )
    return_qty = fields.Float(string="Return Volume", digits="Product Unit of Measure", readonly=True)
    unit_physical_volume = fields.Float(string="Volume per Reference Unit", readonly=True)
    physical_volume = fields.Float(string="Physical Volume", readonly=True)
    physical_volume_uom_name = fields.Char(string="Physical Volume UoM", readonly=True)

    operation_family = fields.Selection(OPERATION_FAMILIES, required=True, readonly=True, index=True)
    business_channel = fields.Selection(BUSINESS_CHANNELS, required=True, readonly=True, index=True)
    is_return = fields.Boolean(readonly=True, index=True)

    source_location_id = fields.Many2one("stock.location", required=True, readonly=True, index=True)
    destination_location_id = fields.Many2one("stock.location", required=True, readonly=True, index=True)
    source_warehouse_id = fields.Many2one("stock.warehouse", readonly=True, index=True)
    destination_warehouse_id = fields.Many2one("stock.warehouse", readonly=True, index=True)
    picking_type_id = fields.Many2one("stock.picking.type", readonly=True, index=True)
    pos_order_id = fields.Many2one("pos.order", readonly=True, ondelete="set null", index=True)
    pos_session_id = fields.Many2one("pos.session", readonly=True, ondelete="set null", index=True)
    lot_id = fields.Many2one("stock.lot", readonly=True, index=True)
    package_id = fields.Many2one("stock.quant.package", readonly=True, index=True)
    result_package_id = fields.Many2one("stock.quant.package", readonly=True, index=True)
    owner_id = fields.Many2one("res.partner", readonly=True, index=True)
    source_write_date = fields.Datetime(readonly=True)
    build_source = fields.Selection(
        [("hook", "Live Hook"), ("backfill", "Backfill"), ("cron", "Reconciliation")],
        required=True,
        readonly=True,
        index=True,
    )

    _sql_constraints = [
        ("move_line_unique", "unique(move_line_id)", "A volume fact already exists for this stock move line."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("allow_volume_fact_create"):
            raise AccessError(_("Movement volume facts can only be created by the reporting engine."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get("allow_volume_fact_maintenance"):
            raise AccessError(_("Movement volume facts are immutable."))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get("allow_volume_fact_maintenance"):
            raise AccessError(_("Movement volume facts cannot be deleted."))
        return super().unlink()

    def _system_recalculate(self, reason="maintenance"):
        return self.env["product.movement.volume.builder"].recalculate_facts(
            self, reason=reason
        )

    def action_remap_tinting_lineage(self):
        result = self._system_recalculate(reason="manual_tinting_lineage_remap")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Tinting Lineage Remap"),
                "message": _(
                    "Checked: %(candidates)s, updated: %(updated)s, failed: %(failed)s",
                    **result,
                ),
                "type": "success" if not result["failed"] else "warning",
                "sticky": bool(result["failed"]),
            },
        }

    @api.model
    def _cron_remap_tinting_lineage(self, limit=1000):
        limit = max(1, min(int(limit or 1000), 10000))
        facts = self.sudo().search(
            [
                "|",
                ("tint_mapping_status", "in", ["missing_base_product", "missing_grade", "ambiguous_bom", "failed"]),
                "&",
                ("is_tinted_lineage_movement", "=", True),
                ("tint_mapping_status", "!=", "mapped"),
            ],
            order="date desc, id desc",
            limit=limit,
        )
        _logger.info("VOLUME_TINT_REMAP_CRON_START fact_count=%s limit=%s", len(facts), limit)
        result = facts._system_recalculate(reason="cron_tinting_lineage_remap")
        _logger.info("VOLUME_TINT_REMAP_CRON_DONE result=%s", result)
        return result

    @api.model
    def _cron_reconcile_missing_facts(self, limit=1000):
        limit = max(1, min(int(limit or 1000), 10000))
        self.env.cr.execute(
            """
                SELECT sml.id
                  FROM stock_move_line sml
             LEFT JOIN product_movement_volume fact ON fact.move_line_id = sml.id
                 WHERE sml.state = 'done'
                   AND sml.quantity != 0
                   AND fact.id IS NULL
              ORDER BY sml.id
                 LIMIT %s
            """,
            [limit],
        )
        line_ids = [row[0] for row in self.env.cr.fetchall()]
        _logger.info("VOLUME_RECONCILE_START missing_count=%s limit=%s", len(line_ids), limit)
        result = self.env["product.movement.volume.builder"].build_from_move_lines(
            self.env["stock.move.line"].browse(line_ids), source="cron"
        )
        pos_facts = self.sudo().search(
            [
                ("business_channel", "!=", "pos"),
                "|",
                ("picking_id.pos_order_id", "!=", False),
                ("picking_id.pos_session_id", "!=", False),
            ],
            limit=limit,
        )
        enrichment = pos_facts._system_recalculate(reason="cron_pos_enrichment")
        combined = {**result, "pos_enriched": enrichment["updated"]}
        _logger.info("VOLUME_RECONCILE_DONE result=%s", combined)
        return combined
