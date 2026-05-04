import { Component, useState, onMounted } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { codError } from "@pos_cod/app/utils/cod_logger";

const round2 = (v) => Math.round(v * 100) / 100;

export class CodReturnDialog extends Component {
    static template = "pos_cod.CodReturnDialog";
    static components = { Dialog };
    static props = {
        order: Object,
        getPayload: Function,
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
                    "get_cod_return_lines",
                    [orderId, this.props.order.name || this.props.order.pos_reference]
                );
            } catch (err) {
                const message = err?.message || "";
                if (!message.includes("get_cod_return_lines")) {
                    throw err;
                }
                lines = await this._loadLegacyLines(orderId);
            }
            this.state.lines = (lines || []).map((l) => ({
                ...l,
                remaining_qty: l.remaining_qty ?? l.qty,
                return_qty: l.remaining_qty ?? l.qty,
            }));
        } catch (err) {
            codError("CodReturnDialog", "_loadLines", err?.message || err);
            this.state.error = "Failed to load order lines.";
        } finally {
            this.state.loading = false;
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

    lineReturnAmount(line) {
        if (!line.qty) return 0;
        return round2((line.return_qty / line.qty) * line.price_subtotal_incl);
    }

    get returnTotal() {
        return round2(
            this.state.lines.reduce((sum, l) => sum + this.lineReturnAmount(l), 0)
        );
    }

    get canConfirm() {
        return !this.state.loading && this.returnTotal > 0;
    }

    formatCurrency(amount) {
        const symbol = this.pos.currency?.symbol || "";
        return `${symbol}${parseFloat(amount || 0).toFixed(2)}`;
    }

    setReturnQty(line, rawValue) {
        let qty = parseFloat(rawValue);
        if (isNaN(qty) || qty < 0) qty = 0;
        if (qty > line.remaining_qty) qty = line.remaining_qty;
        line.return_qty = round2(qty);
    }

    onConfirm() {
        if (!this.canConfirm) return;
        this.props.getPayload({
            amount: this.returnTotal,
            lines: this.state.lines
                .filter((l) => l.return_qty > 0)
                .map((l) => ({
                    product_id: Array.isArray(l.product_id) ? l.product_id[0] : l.product_id,
                    qty: l.return_qty,
                })),
        });
        this.props.close();
    }

    onDiscard() {
        this.props.close();
    }
}
