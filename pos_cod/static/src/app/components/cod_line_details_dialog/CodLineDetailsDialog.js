import { Component, useState, onMounted } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { codError } from "@pos_cod/app/utils/cod_logger";

export class CodLineDetailsDialog extends Component {
    static template = "pos_cod.CodLineDetailsDialog";
    static components = { Dialog };
    static props = {
        order: Object,
        close: Function,
    };

    setup() {
        this.pos = usePos();
        this.state = useState({
            lines: [],
            loading: true,
            error: null,
        });
        onMounted(() => this._loadLines());
    }

    async _loadLines() {
        const orderId = this.props.order.server_id || this.props.order.id;
        try {
            let lines;
            try {
                lines = await this.pos.data.call(
                    "pos.order",
                    "get_cod_order_lines",
                    [orderId, this.props.order.name || this.props.order.pos_reference]
                );
            } catch (err) {
                const message = err?.message || "";
                if (!message.includes("get_cod_order_lines")) {
                    throw err;
                }
                lines = await this._loadReturnLines(orderId);
            }
            this.state.lines = lines || [];
        } catch (err) {
            codError("CodLineDetailsDialog", "_loadLines", err?.message || err);
            this.state.error = "Failed to load order lines.";
        } finally {
            this.state.loading = false;
        }
    }

    async _loadReturnLines(orderId) {
        try {
            return await this.pos.data.call(
                "pos.order",
                "get_cod_return_lines",
                [orderId, this.props.order.name || this.props.order.pos_reference]
            );
        } catch (err) {
            const message = err?.message || "";
            if (!message.includes("get_cod_return_lines")) {
                throw err;
            }
            return await this._loadLegacyLines(orderId);
        }
    }

    async _loadLegacyLines(orderId) {
        return await this.pos.data.call(
            "pos.order.line",
            "search_read",
            [[["order_id", "=", orderId], ["qty", ">", 0]]],
            {
                fields: [
                    "id",
                    "product_id",
                    "full_product_name",
                    "qty",
                    "price_unit",
                    "price_subtotal_incl",
                    "discount",
                ],
                order: "id asc",
            }
        );
    }

    productName(line) {
        if (line.full_product_name) return line.full_product_name;
        return Array.isArray(line.product_id) ? line.product_id[1] : "Unknown";
    }

    lineQty(line) {
        return line.qty ?? 0;
    }

    returnedQty(line) {
        return line.returned_qty ?? 0;
    }

    remainingQty(line) {
        return line.remaining_qty ?? line.qty ?? 0;
    }

    get orderTotal() {
        return this.state.lines.reduce(
            (sum, line) => sum + parseFloat(line.price_subtotal_incl || 0),
            0
        );
    }

    formatCurrency(amount) {
        const symbol = this.pos.currency?.symbol || "";
        return `${symbol}${parseFloat(amount || 0).toFixed(2)}`;
    }

    onClose() {
        this.props.close();
    }
}
