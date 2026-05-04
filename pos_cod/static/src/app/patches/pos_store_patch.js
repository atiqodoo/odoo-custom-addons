/**
 * @module pos_cod/app/patches/pos_store_patch
 *
 * Extends PosStore with COD state and RPC methods.
 *
 * Added to PosStore:
 *   cod_pending_orders  — reactive array of pending COD order dicts
 *   cod_loading         — bool: fetch in progress
 *   cod_pending_count   — computed count (getter)
 *   cod_fetch_pending_orders()  — RPC: load pending COD orders from backend
 *   cod_create_order(orderData) — RPC: dispatch a new COD order
 *   cod_collect_payment(...)    — RPC: collect payment on a pending COD order
 *
 * Called from:
 *   setup()                     — on POS session open
 *   CodOrdersScreen             — on manual refresh
 *   CodWizard                   — after COD confirm
 */

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { codWarn, codError, codLog, codTable } from "@pos_cod/app/utils/cod_logger";

const COMPONENT = "PosStore";

patch(PosStore.prototype, {

    async setup(...args) {
        await super.setup(...args);

        // Reactive state for COD orders — drives the banner and orders screen.
        this.cod_pending_orders = [];
        this.cod_loading = false;

        codWarn(COMPONENT, "setup", "COD module loaded. Fetching pending orders...");
        await this.cod_fetch_pending_orders();
    },

    // ── Getters ────────────────────────────────────────────────────────────────

    get cod_pending_count() {
        return (this.cod_pending_orders || []).length;
    },

    // ── RPC: fetch pending COD orders ─────────────────────────────────────────

    async cod_fetch_pending_orders() {
        const companyId = this.config?.company_id?.id || false;

        codWarn(
            COMPONENT,
            "cod_fetch_pending_orders",
            `Fetching pending COD orders. company_id=${companyId}`,
        );

        this.cod_loading = true;

        try {
            const orders = await this.data.call(
                "pos.order",
                "search_read",
                [
                    [
                        ["is_cod", "=", true],
                        ["cod_state", "in", ["pending", "partial"]],
                        ...(companyId ? [["company_id", "=", companyId]] : []),
                    ],
                ],
                {
                    fields: [
                        "id",
                        "name",
                        "pos_reference",
                        "amount_total",
                        "cod_amount_paid",
                        "cod_amount_returned",
                        "cod_amount_open",
                        "partner_id",
                        "delivery_address",
                        "delivery_notes",
                        "delivery_employee_id",
                        "cod_state",
                        "date_order",
                    ],
                },
            );

            this.cod_pending_orders = (orders || []).map((order) => ({
                ...order,
                server_id: order.id,
            }));

            codWarn(
                COMPONENT,
                "cod_fetch_pending_orders",
                `Loaded ${this.cod_pending_orders.length} pending COD order(s).`,
            );

            if (this.cod_pending_orders.length) {
                codTable(COMPONENT, "cod_fetch_pending_orders", this.cod_pending_orders.map(o => ({
                    id: o.id,
                    name: o.name,
                    partner: Array.isArray(o.partner_id) ? o.partner_id[1] : o.partner_id,
                    amount: o.amount_total,
                    date: o.date_order,
                })));
            }

        } catch (err) {
            codError(COMPONENT, "cod_fetch_pending_orders", "RPC failed:", err?.message || err);
            this.cod_pending_orders = [];
        } finally {
            this.cod_loading = false;
        }
    },

    // ── RPC: dispatch new COD order ────────────────────────────────────────────

    async cod_create_order(orderData) {
        /**
         * Send a new COD order to the backend.
         * orderData must have: is_cod=true, partner_id set, lines, no statement_ids.
         *
         * The backend will:
         *   - Create pos.order in draft
         *   - Validate the stock picking immediately
         *   - Post DR COD AR / CR Sales journal entry
         *
         * Returns the create_from_ui result array on success, throws on failure.
         */
        codWarn(COMPONENT, "cod_create_order", "Dispatching COD order:", {
            name: orderData.name,
            partner_id: orderData.partner_id,
            amount_total: orderData.amount_total,
            lines: (orderData.lines || []).length,
        });

        try {
            const result = await this.data.call(
                "pos.order",
                "sync_from_ui",
                [[orderData]],
            );

            codWarn(COMPONENT, "cod_create_order", "COD order created:", result);

            // Refresh pending list so banner count is updated immediately.
            await this.cod_fetch_pending_orders();

            return result;

        } catch (err) {
            codError(COMPONENT, "cod_create_order", "Failed to create COD order:", err?.message || err);
            throw err;
        }
    },

    // ── RPC: collect payment on a pending COD order ───────────────────────────

    async cod_collect_payment(
        orderId,
        paymentMethodId,
        amount,
        sessionId = this.session?.id || false,
        action = "payment",
        orderRef = false,
        returnLines = null
    ) {
        /**
         * Collect cash/card payment for a pending COD order.
         *
         * The backend will:
         *   - Post DR Cash / CR COD AR journal entry
         *   - Reconcile with the original confirmation entry
         *   - Set cod_state='paid', state='paid'
         *
         * Returns: { success: bool, message: str, order_name: str, amount: number }
         */
        codWarn(COMPONENT, "cod_collect_payment", "Collecting COD payment:", {
            orderId,
            paymentMethodId,
            amount,
            sessionId,
            action,
            orderRef,
            returnLines,
        });

        try {
            const result = await this.data.call(
                "pos.order",
                "collect_cod_payment",
                [orderId, paymentMethodId, amount, sessionId, action, orderRef, returnLines],
            );

            if (result.success) {
                codWarn(
                    COMPONENT,
                    "cod_collect_payment",
                    `Payment collected for order ${result.order_name} (amount: ${result.amount}).`,
                );
                await this.cod_fetch_pending_orders();
            } else {
                codError(COMPONENT, "cod_collect_payment", "Backend error:", result.message);
            }

            return result;

        } catch (err) {
            codError(COMPONENT, "cod_collect_payment", "RPC failed:", err?.message || err);
            return { success: false, message: err?.message || "Network error" };
        }
    },

});
