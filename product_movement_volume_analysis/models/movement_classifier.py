import logging

from odoo import models


_logger = logging.getLogger(__name__)


class ProductMovementVolumeClassifier(models.AbstractModel):
    _name = "product.movement.volume.classifier"
    _description = "Movement Volume Classifier"

    def classify(self, move_line):
        move = move_line.move_id
        source_move = move.origin_returned_move_id or move
        source_usage = move_line.location_id.usage
        destination_usage = move_line.location_dest_id.usage

        operation = self._classify_operation(
            move, source_usage=source_usage, destination_usage=destination_usage
        )
        channel = self._classify_channel(source_move)
        is_return = bool(
            move.origin_returned_move_id
            or operation in ("customer_return", "vendor_return")
        )
        result = {
            "operation_family": operation,
            "business_channel": channel,
            "is_return": is_return,
        }
        _logger.debug(
            "VOLUME_CLASSIFY move_line_id=%s move_id=%s source_usage=%s destination_usage=%s "
            "operation=%s channel=%s is_return=%s",
            move_line.id,
            move.id,
            source_usage,
            destination_usage,
            operation,
            channel,
            is_return,
        )
        return result

    def _classify_operation(self, move, source_usage, destination_usage):
        if move.scrapped:
            return "scrap"
        if move.raw_material_production_id:
            return "manufacturing_consumption"
        if move.production_id:
            if move.product_id != move.production_id.product_id:
                return "manufacturing_byproduct"
            return "manufacturing_production"
        if move.is_inventory:
            if destination_usage == "internal" and source_usage != "internal":
                return "inventory_gain"
            return "inventory_loss"
        if source_usage == "supplier" and destination_usage == "internal":
            return "vendor_receipt"
        if source_usage == "internal" and destination_usage == "supplier":
            return "vendor_return"
        if source_usage == "internal" and destination_usage == "customer":
            return "customer_delivery"
        if source_usage == "customer" and destination_usage == "internal":
            return "customer_return"
        if source_usage == "supplier" and destination_usage == "customer":
            return "dropship"
        if source_usage == "internal" and destination_usage == "internal":
            return "internal_transfer"
        if "transit" in (source_usage, destination_usage):
            return "transit"
        return "other"

    def _classify_channel(self, move):
        if move.raw_material_production_id or move.production_id:
            return "manufacturing"

        picking = move.picking_id
        if picking and (
            ("pos_order_id" in picking._fields and picking.pos_order_id)
            or ("pos_session_id" in picking._fields and picking.pos_session_id)
        ):
            return "pos"
        if move.purchase_line_id:
            return "purchase"
        if move.sale_line_id:
            return "sales"
        if move.is_inventory:
            return "inventory"
        if move.scrapped:
            return "scrap"
        if move.location_id.usage == "internal" and move.location_dest_id.usage == "internal":
            return "internal"
        return "other"
