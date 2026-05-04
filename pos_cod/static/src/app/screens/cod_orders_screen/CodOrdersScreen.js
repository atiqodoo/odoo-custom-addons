import { Component, useState } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { NumberPopup } from "@point_of_sale/app/utils/input_popups/number_popup";
import { CodReturnDialog } from "@pos_cod/app/components/cod_return_dialog/CodReturnDialog";
import { codWarn, codError } from "@pos_cod/app/utils/cod_logger";

const COMPONENT = "CodOrdersScreen";

export class CodOrdersScreen extends Component {
    static template = "pos_cod.CodOrdersScreen";
    static props = { isShown: { type: Boolean, optional: true } };

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.state = useState({
            selectedOrderId: null,
            paymentMethodId: null,
            collecting: false,
            message: "",
            messageType: "info",
            query: "",
        });
    }

    get orders() {
        const query = (this.state.query || "").trim().toLowerCase();
        const orders = this.pos.cod_pending_orders || [];
        if (!query) return orders;
        return orders.filter((order) =>
            [order.name, order.pos_reference, this.partnerName(order), this.employeeName(order), order.delivery_address]
                .some((value) => String(value || "").toLowerCase().includes(query))
        );
    }

    get isLoading() {
        return this.pos.cod_loading;
    }

    get paymentMethods() {
        return (this.pos.models["pos.payment.method"]?.getAll?.() || []).filter(
            (method) => method.type !== "pay_later"
        );
    }

    get hasOrders() {
        return this.orders.length > 0;
    }

    formatCurrency(amount) {
        const symbol = this.pos.currency?.symbol || "";
        return `${symbol}${parseFloat(amount || 0).toFixed(2)}`;
    }

    formatDate(dateStr) {
        if (!dateStr) return "";
        try {
            // Odoo sends UTC datetimes without a timezone marker (e.g. "2026-05-04 22:03:13").
            // Appending 'Z' tells JS to parse as UTC so toLocaleString() converts to
            // the browser's local timezone (e.g. Africa/Nairobi = UTC+3).
            const utc = dateStr.replace(" ", "T") + "Z";
            return new Date(utc).toLocaleString();
        } catch {
            return dateStr;
        }
    }

    partnerName(order) {
        if (!order.partner_id) return "-";
        return Array.isArray(order.partner_id) ? order.partner_id[1] : String(order.partner_id);
    }

    employeeName(order) {
        if (!order.delivery_employee_id) return "-";
        return Array.isArray(order.delivery_employee_id)
            ? order.delivery_employee_id[1]
            : String(order.delivery_employee_id);
    }

    openAmount(order) {
        return parseFloat(order.cod_amount_open ?? order.amount_total ?? 0);
    }

    paidAmount(order) {
        return parseFloat(order.cod_amount_paid || 0);
    }

    returnedAmount(order) {
        return parseFloat(order.cod_amount_returned || 0);
    }

    progress(order) {
        const total = parseFloat(order.amount_total || 0);
        if (!total) return 0;
        return Math.min(100, Math.round(((this.paidAmount(order) + this.returnedAmount(order)) / total) * 100));
    }

    async onRefresh() {
        this.state.message = "";
        await this.pos.cod_fetch_pending_orders();
    }

    onSelectOrder(orderId) {
        this.state.selectedOrderId = orderId === this.state.selectedOrderId ? null : orderId;
        this.state.message = "";
    }

    orderServerId(order) {
        return order.server_id || order.id;
    }

    onSelectPaymentMethod(ev) {
        const value = parseInt(ev.target.value, 10);
        this.state.paymentMethodId = isNaN(value) ? null : value;
    }

    async askAmount(title, order) {
        const max = this.openAmount(order);
        const value = await makeAwaitable(this.dialog, NumberPopup, {
            title,
            subtitle: `${order.name} - Open ${this.formatCurrency(max)}`,
            startingValue: String(max),
            confirmButtonLabel: "Apply",
            isValid: (buffer) => {
                const amount = parseFloat(buffer);
                return amount > 0 && amount <= max;
            },
            feedback: (buffer) => {
                const amount = parseFloat(buffer);
                if (!amount) return "Enter an amount.";
                if (amount > max) return `Maximum is ${this.formatCurrency(max)}.`;
                return false;
            },
        });
        return value === undefined ? null : parseFloat(value);
    }

    async processCod(order, action, amount, returnLines = null) {
        if (!this.state.paymentMethodId) {
            this.state.message = "Please select a payment method first.";
            this.state.messageType = "error";
            return;
        }
        if (!amount || amount <= 0) {
            return;
        }

        this.state.collecting = true;
        this.state.message = "";
        try {
            const result = await this.pos.cod_collect_payment(
                this.orderServerId(order),
                this.state.paymentMethodId,
                amount,
                this.pos.session?.id,
                action,
                order.name || order.pos_reference,
                returnLines
            );
            if (result.success) {
                this.state.message = `${result.order_name}: ${action === "return" ? "return recorded" : "payment received"} (${this.formatCurrency(result.amount)}).`;
                this.state.messageType = "success";
                if (!result.remaining) {
                    this.state.selectedOrderId = null;
                }
                codWarn(COMPONENT, "processCod", "COD action completed:", result);
            } else {
                this.state.message = `Error: ${result.message}`;
                this.state.messageType = "error";
                codError(COMPONENT, "processCod", result.message);
            }
        } catch (err) {
            this.state.message = "Network error. Please try again.";
            this.state.messageType = "error";
            codError(COMPONENT, "processCod", err?.message || err);
        } finally {
            this.state.collecting = false;
        }
    }

    async onReceivePayment(order) {
        await this.processCod(order, "payment", this.openAmount(order));
    }

    async onReceivePartial(order) {
        const amount = await this.askAmount("Partial COD Payment", order);
        await this.processCod(order, "payment", amount);
    }

    async onReturn(order) {
        await this.processCod(order, "return", this.openAmount(order));
    }

    async onPartialReturn(order) {
        const result = await makeAwaitable(this.dialog, CodReturnDialog, { order });
        if (!result || !result.amount) return;
        await this.processCod(order, "return", result.amount, result.lines);
    }

    onBack() {
        this.pos.showScreen("ProductScreen");
    }
}

registry.category("pos_screens").add("CodOrdersScreen", CodOrdersScreen);
