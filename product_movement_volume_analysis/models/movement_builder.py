import logging

from psycopg2 import IntegrityError

from odoo import fields, models
from odoo.tools.float_utils import float_is_zero


_logger = logging.getLogger(__name__)


class ProductMovementVolumeBuilder(models.AbstractModel):
    _name = "product.movement.volume.builder"
    _description = "Movement Volume Fact Builder"

    def build_from_move_lines(self, move_lines, source="hook"):
        if source not in ("hook", "backfill", "cron"):
            raise ValueError(f"Unsupported movement fact source: {source}")

        candidate_lines = move_lines.exists().filtered(
            lambda line: line.state == "done"
            and not float_is_zero(
                line.quantity,
                precision_rounding=line.product_uom_id.rounding,
            )
        )
        existing_line_ids = set(
            self.env["product.movement.volume"]
            .sudo()
            .search([("move_line_id", "in", candidate_lines.ids)])
            .mapped("move_line_id")
            .ids
        )

        result = {
            "candidates": len(candidate_lines),
            "created": 0,
            "skipped": len(existing_line_ids),
            "failed": 0,
        }
        _logger.info(
            "VOLUME_BUILD_START source=%s candidates=%s existing=%s move_line_ids=%s",
            source,
            len(candidate_lines),
            len(existing_line_ids),
            candidate_lines.ids,
        )

        for line in candidate_lines.filtered(lambda rec: rec.id not in existing_line_ids):
            try:
                with self.env.cr.savepoint():
                    vals = self._prepare_fact_values(line, source)
                    self.env["product.movement.volume"].sudo().with_context(
                        allow_volume_fact_create=True
                    ).create(vals)
                    result["created"] += 1
                    _logger.info(
                        "VOLUME_FACT_CREATED source=%s move_line_id=%s move_id=%s operation=%s "
                        "channel=%s transaction_qty=%s transaction_uom_id=%s ratio=%s "
                        "normalized_qty=%s reference_uom_id=%s grade_id=%s",
                        source,
                        line.id,
                        line.move_id.id,
                        vals["operation_family"],
                        vals["business_channel"],
                        vals["transaction_qty"],
                        vals["transaction_uom_id"],
                        vals["conversion_ratio"],
                        vals["normalized_qty"],
                        vals["reference_uom_id"],
                        vals.get("grade_id"),
                    )
            except IntegrityError:
                result["skipped"] += 1
                _logger.info(
                    "VOLUME_FACT_DUPLICATE source=%s move_line_id=%s move_id=%s",
                    source,
                    line.id,
                    line.move_id.id,
                )
            except Exception:
                result["failed"] += 1
                _logger.exception(
                    "VOLUME_FACT_FAILED source=%s move_line_id=%s move_id=%s product_id=%s",
                    source,
                    line.id,
                    line.move_id.id,
                    line.product_id.id,
                )

        _logger.info("VOLUME_BUILD_DONE source=%s result=%s", source, result)
        return result

    def recalculate_facts(self, facts, reason="maintenance"):
        facts = facts.sudo().exists()
        result = {"candidates": len(facts), "updated": 0, "failed": 0}
        _logger.info(
            "VOLUME_RECALCULATE_START reason=%s fact_ids=%s",
            reason,
            facts.ids,
        )
        for fact in facts:
            try:
                with self.env.cr.savepoint():
                    line = fact.move_line_id.exists()
                    if not line or line.state != "done":
                        _logger.warning(
                            "VOLUME_RECALCULATE_SKIP reason=%s fact_id=%s move_line_id=%s state=%s",
                            reason,
                            fact.id,
                            line.id,
                            line.state if line else "missing",
                        )
                        continue
                    vals = self._prepare_fact_values(line, fact.build_source)
                    old_values = {
                        "channel": fact.business_channel,
                        "ratio": fact.conversion_ratio,
                        "normalized_qty": fact.normalized_qty,
                        "reference_uom_id": fact.reference_uom_id.id,
                        "grade_id": fact.grade_id.id,
                        "tint_mapping_status": fact.tint_mapping_status,
                    }
                    fact.with_context(allow_volume_fact_maintenance=True).write(vals)
                    result["updated"] += 1
                    _logger.info(
                        "VOLUME_FACT_RECALCULATED reason=%s fact_id=%s move_line_id=%s "
                        "old=%s new_channel=%s new_ratio=%s new_normalized_qty=%s "
                        "new_reference_uom_id=%s new_grade_id=%s new_tint_mapping_status=%s",
                        reason,
                        fact.id,
                        line.id,
                        old_values,
                        vals["business_channel"],
                        vals["conversion_ratio"],
                        vals["normalized_qty"],
                        vals["reference_uom_id"],
                        vals.get("grade_id"),
                        vals.get("tint_mapping_status"),
                    )
            except Exception:
                result["failed"] += 1
                _logger.exception(
                    "VOLUME_RECALCULATE_FAILED reason=%s fact_id=%s move_line_id=%s",
                    reason,
                    fact.id,
                    fact.move_line_id.id,
                )
        _logger.info("VOLUME_RECALCULATE_DONE reason=%s result=%s", reason, result)
        return result

    def _prepare_fact_values(self, line, source):
        move = line.move_id
        product = line.product_id
        template = product.product_tmpl_id
        transaction_qty = abs(line.quantity)
        reference_uom = self._get_category_reference_uom(line.product_uom_id)
        normalized_qty = abs(
            line.product_uom_id._compute_quantity(
                line.quantity,
                reference_uom,
                round=False,
            )
        )
        conversion_ratio = normalized_qty / transaction_qty if transaction_qty else 0.0
        product_uom_qty = abs(
            line.product_uom_id._compute_quantity(
                line.quantity,
                product.uom_id,
                round=False,
            )
        )
        classification = self.env["product.movement.volume.classifier"].classify(line)
        measures = self._prepare_measures(
            normalized_qty,
            classification["operation_family"],
            line.location_id.usage,
            line.location_dest_id.usage,
        )

        all_tags = product.all_product_tag_ids
        grade_tags = all_tags.filtered("is_volume_reporting_grade").sorted(
            key=lambda tag: (tag.sequence, tag.id)
        )
        if len(grade_tags) > 1:
            _logger.error(
                "VOLUME_GRADE_AMBIGUOUS move_line_id=%s product_id=%s grade_ids=%s; using grade_id=%s",
                line.id,
                product.id,
                grade_tags.ids,
                grade_tags[0].id,
            )
        direct_grade = grade_tags[:1]
        picking = move.picking_id
        pos_order = picking.pos_order_id if picking and "pos_order_id" in picking._fields else False
        pos_session = (
            picking.pos_session_id
            if picking and "pos_session_id" in picking._fields
            else pos_order.session_id if pos_order else False
        )
        tint_lineage = self._resolve_tinting_lineage(line, direct_grade)
        if tint_lineage["manufacturing_component_role"] == "colorant":
            grade = self.env["product.tag"]
        else:
            grade = tint_lineage["grade"] or direct_grade
        partner = move.partner_id or (picking.partner_id if picking else self.env["res.partner"])
        responsible = (
            picking.user_id
            if picking and "user_id" in picking._fields and picking.user_id
            else move.create_uid
        )

        vals = {
            "reference": move.reference or (picking.name if picking else False) or move.name or str(move.id),
            "date": line.date or move.date,
            "company_id": move.company_id.id,
            "move_line_id": line.id,
            "move_id": move.id,
            "picking_id": picking.id,
            "partner_id": partner.id,
            "responsible_user_id": responsible.id,
            "origin": move.origin or (picking.origin if picking else False),
            "product_id": product.id,
            "product_tmpl_id": template.id,
            "categ_id": template.categ_id.id,
            "grade_id": grade.id,
            "grade_source": tint_lineage["grade_source"] or ("product_tag" if grade else "none"),
            "tags_snapshot": ", ".join(all_tags.sorted("name").mapped("name")),
            "tint_base_product_id": tint_lineage["tint_base_product"].id,
            "tint_base_categ_id": tint_lineage["tint_base_product"].categ_id.id,
            "tint_mapping_status": tint_lineage["status"],
            "tint_mapping_reason": tint_lineage["reason"],
            "tint_mapping_attempt_date": fields.Datetime.now(),
            "is_tinted_lineage_movement": tint_lineage["is_tinted_lineage_movement"],
            "manufacturing_component_role": tint_lineage["manufacturing_component_role"],
            "transaction_qty": transaction_qty,
            "transaction_uom_id": line.product_uom_id.id,
            "conversion_ratio": conversion_ratio,
            "normalized_qty": normalized_qty,
            "reference_uom_id": reference_uom.id,
            "uom_category_id": reference_uom.category_id.id,
            "unit_physical_volume": product.volume,
            "physical_volume": product_uom_qty * product.volume,
            "physical_volume_uom_name": template._get_volume_uom_name_from_ir_config_parameter(),
            "source_location_id": line.location_id.id,
            "destination_location_id": line.location_dest_id.id,
            "source_warehouse_id": line.location_id.warehouse_id.id,
            "destination_warehouse_id": line.location_dest_id.warehouse_id.id,
            "picking_type_id": picking.picking_type_id.id if picking else False,
            "pos_order_id": pos_order.id if pos_order else False,
            "pos_session_id": pos_session.id if pos_session else False,
            "lot_id": line.lot_id.id,
            "package_id": line.package_id.id,
            "result_package_id": line.result_package_id.id,
            "owner_id": line.owner_id.id,
            "source_write_date": line.write_date,
            "build_source": source,
            **classification,
            **measures,
        }
        return vals

    def _resolve_tinting_lineage(self, line, direct_grade):
        product = line.product_id
        template = product.product_tmpl_id
        default = {
            "is_tinted_lineage_movement": False,
            "tint_base_product": self.env["product.product"],
            "grade": self.env["product.tag"],
            "grade_source": "product_tag" if direct_grade else "none",
            "status": "not_applicable",
            "reason": "not_tinting_lineage",
            "manufacturing_component_role": "not_applicable",
        }
        try:
            mo = self._get_tinting_mo(line)
            bom, bom_status, bom_count = self._get_tinting_bom(product, mo)
            is_tinted_template = bool(
                "is_tinted_product" in template._fields and template.is_tinted_product
            )
            is_tinting_mo = bool(
                mo and "is_tinting_mo" in mo._fields and mo.is_tinting_mo
            )
            if not is_tinted_template and not is_tinting_mo and not bom:
                return default

            role = self._get_tinting_component_role(line, mo, bom)
            if role == "colorant":
                result = {
                    **default,
                    "is_tinted_lineage_movement": True,
                    "grade_source": "none",
                    "status": "not_applicable",
                    "reason": "colorant_uses_no_grade",
                    "manufacturing_component_role": role,
                }
                self._log_tint_mapping("SKIP", line, product, result, bom, bom_status, bom_count)
                return result

            if not bom:
                result = {
                    **default,
                    "is_tinted_lineage_movement": True,
                    "status": "ambiguous_bom" if bom_status == "ambiguous" else "missing_base_product",
                    "reason": bom_status or "no_tinting_bom_found",
                    "manufacturing_component_role": role,
                }
                self._log_tint_mapping("MISSED", line, product, result, bom, bom_status, bom_count)
                return result

            base_product = (
                bom.base_variant_id
                if "base_variant_id" in bom._fields and bom.base_variant_id
                else self.env["product.product"]
            )
            if not base_product:
                result = {
                    **default,
                    "is_tinted_lineage_movement": True,
                    "status": "missing_base_product",
                    "reason": "no_base_variant_on_bom",
                    "manufacturing_component_role": role,
                }
                self._log_tint_mapping("MISSED", line, product, result, bom, bom_status, bom_count)
                return result

            base_grade = self._get_reporting_grade(base_product, line.id)
            if not base_grade and role == "base_paint":
                base_grade = direct_grade

            result = {
                **default,
                "is_tinted_lineage_movement": True,
                "tint_base_product": base_product,
                "grade": base_grade,
                "grade_source": "tinting_base_product" if base_grade else "none",
                "status": "mapped" if base_grade else "missing_grade",
                "reason": "mapped_from_tinting_base_product" if base_grade else "base_product_has_no_reporting_grade",
                "manufacturing_component_role": role,
            }
            self._log_tint_mapping(
                "SUCCESS" if base_grade else "MISSED",
                line,
                product,
                result,
                bom,
                bom_status,
                bom_count,
            )
            return result
        except Exception as error:
            result = {
                **default,
                "is_tinted_lineage_movement": True,
                "grade_source": "failed",
                "status": "failed",
                "reason": str(error)[:255],
            }
            _logger.exception(
                "VOLUME_TINT_MAPPING_FAILED move_line_id=%s move_id=%s product_id=%s product=%s error=%s",
                line.id,
                line.move_id.id,
                product.id,
                product.display_name,
                error,
            )
            return result

    def _get_tinting_mo(self, line):
        move = line.move_id
        if "raw_material_production_id" in move._fields and move.raw_material_production_id:
            return move.raw_material_production_id
        if "production_id" in move._fields and move.production_id:
            return move.production_id
        return self.env["mrp.production"]

    def _get_tinting_bom(self, product, mo=False):
        if mo and mo.bom_id and "is_tinting_bom" in mo.bom_id._fields and mo.bom_id.is_tinting_bom:
            return mo.bom_id, "from_mo", 1

        Bom = self.env["mrp.bom"].sudo()
        if "is_tinting_bom" not in Bom._fields:
            return self.env["mrp.bom"], "paint_tinting_fields_missing", 0

        exact_boms = Bom.search(
            [
                ("is_tinting_bom", "=", True),
                ("product_id", "=", product.id),
            ],
            order="sequence, id",
            limit=2,
        )
        if len(exact_boms) == 1:
            return exact_boms, "from_product_bom", 1
        if len(exact_boms) > 1:
            return exact_boms[:1], "ambiguous", len(exact_boms)

        template_boms = Bom.search(
            [
                ("is_tinting_bom", "=", True),
                ("product_tmpl_id", "=", product.product_tmpl_id.id),
            ],
            order="sequence, id",
            limit=2,
        )
        if len(template_boms) == 1:
            return template_boms, "from_template_bom", 1
        if len(template_boms) > 1:
            return template_boms[:1], "ambiguous", len(template_boms)
        return self.env["mrp.bom"], "no_tinting_bom_found", 0

    def _get_tinting_component_role(self, line, mo, bom):
        move = line.move_id
        product = line.product_id
        template = product.product_tmpl_id
        if (
            bom
            and "base_variant_id" in bom._fields
            and bom.base_variant_id
            and product == bom.base_variant_id
        ):
            return "base_paint"
        if "bom_line_id" in move._fields and move.bom_line_id and "is_colorant_line" in move.bom_line_id._fields and move.bom_line_id.is_colorant_line:
            return "colorant"
        if "is_colorant" in template._fields and template.is_colorant:
            return "colorant"
        if "production_id" in move._fields and move.production_id:
            if mo and product == mo.product_id:
                return "finished_tinted_product"
            return "byproduct"
        if "is_tinted_product" in template._fields and template.is_tinted_product:
            return "finished_tinted_product"
        if "raw_material_production_id" in move._fields and move.raw_material_production_id:
            return "other_component"
        return "not_applicable"

    def _get_reporting_grade(self, product, move_line_id=False):
        tags = product.all_product_tag_ids.filtered("is_volume_reporting_grade").sorted(
            key=lambda tag: (tag.sequence, tag.id)
        )
        if len(tags) > 1:
            _logger.error(
                "VOLUME_TINT_BASE_GRADE_AMBIGUOUS move_line_id=%s base_product_id=%s grade_ids=%s; using grade_id=%s",
                move_line_id,
                product.id,
                tags.ids,
                tags[0].id,
            )
        return tags[:1]

    def _log_tint_mapping(self, outcome, line, product, result, bom, bom_status, bom_count):
        log_method = _logger.info if outcome in ("SUCCESS", "SKIP") else _logger.warning
        base_product = result.get("tint_base_product")
        grade = result.get("grade")
        log_method(
            "VOLUME_TINT_MAPPING_%s move_line_id=%s move_id=%s product_id=%s product=%s "
            "role=%s status=%s reason=%s base_product_id=%s base_product=%s grade_id=%s "
            "grade=%s grade_source=%s bom_id=%s bom_status=%s bom_count=%s",
            outcome,
            line.id,
            line.move_id.id,
            product.id,
            product.display_name,
            result.get("manufacturing_component_role"),
            result.get("status"),
            result.get("reason"),
            base_product.id if base_product else False,
            base_product.display_name if base_product else False,
            grade.id if grade else False,
            grade.display_name if grade else False,
            result.get("grade_source"),
            bom.id if bom else False,
            bom_status,
            bom_count,
        )

    def _get_category_reference_uom(self, transaction_uom):
        reference_uom = self.env["uom.uom"].with_context(active_test=False).search(
            [
                ("category_id", "=", transaction_uom.category_id.id),
                ("uom_type", "=", "reference"),
            ],
            limit=1,
        )
        if not reference_uom:
            raise ValueError(
                f"No active reference UoM for category {transaction_uom.category_id.display_name}"
            )
        return reference_uom


    def _prepare_measures(self, quantity, operation, source_usage, destination_usage):
        inventory_signed = 0.0
        if source_usage != "internal" and destination_usage == "internal":
            inventory_signed = quantity
        elif source_usage == "internal" and destination_usage != "internal":
            inventory_signed = -quantity

        return {
            "gross_movement_qty": quantity,
            "inventory_signed_qty": inventory_signed,
            "sales_net_qty": (
                quantity
                if operation == "customer_delivery"
                else -quantity if operation == "customer_return" else 0.0
            ),
            "receipt_net_qty": (
                quantity
                if operation == "vendor_receipt"
                else -quantity if operation == "vendor_return" else 0.0
            ),
            "production_output_qty": (
                quantity
                if operation in ("manufacturing_production", "manufacturing_byproduct")
                else 0.0
            ),
            "production_consumption_qty": (
                quantity if operation == "manufacturing_consumption" else 0.0
            ),
            "return_qty": (
                quantity if operation in ("customer_return", "vendor_return") else 0.0
            ),
        }
