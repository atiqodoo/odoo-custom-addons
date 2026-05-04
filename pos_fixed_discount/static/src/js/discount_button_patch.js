import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { DiscountTypePopup } from "./discount_type_popup";
import { patch } from "@web/core/utils/patch";

patch(ControlButtons.prototype, {
    /**
     * Replaces the native clickDiscount so both percentage and fixed-amount
     * modes open the same DiscountTypePopup (with an on-the-fly mode toggle).
     * The default mode is driven by pos.config.discount_type; the cashier can
     * override it per transaction via the toggle buttons in the popup.
     */
    async clickDiscount() {
        const discountType = this.pos.config.discount_type || "percentage";
        // Pre-fill the buffer with the configured default % when opening in
        // percentage mode; leave empty for fixed (no sensible default exists).
        const startingValue =
            discountType === "percentage" ? this.pos.config.discount_pc : "";

        this.dialog.add(DiscountTypePopup, {
            title: _t("Discount"),
            startingValue,
            defaultType: discountType,
            getPayload: ({ value, type }) => {
                const parsed = this.env.utils.parseValidFloat(value.toString());
                // NaN or negative: nothing to apply (do not clear existing lines)
                if (isNaN(parsed) || parsed < 0) return;
                if (type === "fixed") {
                    this.apply_fixed_discount(parsed);
                } else {
                    // Delegate to the existing pos_discount apply_discount method.
                    // Clamp to [0, 100] as percentage semantics require.
                    const pc = Math.max(0, Math.min(100, parsed));
                    this.apply_discount(pc);
                }
            },
        });
    },

    /**
     * Applies a fixed KES/currency amount as a global order discount.
     *
     * The amount is distributed proportionally across each tax group so that
     * every discount line carries the same tax as the products it reduces —
     * satisfying KRA VAT rules: the taxable base per rate is reduced correctly.
     *
     * A new order line using discount_product_id is added (negative price_unit).
     * No existing line prices are modified.
     *
     * @param {number} amount - positive fixed discount amount in order currency
     */
    async apply_fixed_discount(amount) {
        const order = this.pos.get_order();
        const product = this.pos.config.discount_product_id;

        if (product === undefined) {
            this.dialog.add(AlertDialog, {
                title: _t("No discount product found"),
                body: _t(
                    "The discount product seems misconfigured. Make sure it is flagged as 'Can be Sold' and 'Available in Point of Sale'."
                ),
            });
            return;
        }

        const lines = order.get_orderlines();

        // Remove any existing global-discount lines before re-applying.
        lines
            .filter((line) => line.get_product() === product)
            .forEach((line) => line.delete());

        // Group remaining lines by their effective tax key.
        const linesByTax = order.get_orderlines_grouped_by_tax_ids();

        // Compute the total eligible base (tax-inclusive, excl. non-included
        // tax amounts) across all groups — used as the proportioning denominator.
        const allEligible = Object.values(linesByTax)
            .flat()
            .filter((ll) => ll.isGlobalDiscountApplicable());

        const totalBase = order.calculate_base_amount(allEligible);
        if (totalBase <= 0) return;

        // Never discount more than the full order value.
        const clampedAmount = Math.min(amount, totalBase);

        for (const [tax_ids, taxLines] of Object.entries(linesByTax)) {
            const eligible = taxLines.filter((ll) => ll.isGlobalDiscountApplicable());
            if (!eligible.length) continue;

            const groupBase = order.calculate_base_amount(eligible);
            if (groupBase <= 0) continue;

            // Pro-rate the fixed amount to this tax group's share of the order.
            const proportion = groupBase / totalBase;
            const discountForGroup = -(clampedAmount * proportion);

            // discountForGroup is always negative here; the check guards against
            // floating-point noise producing a −0 or tiny positive rounding error.
            if (discountForGroup >= 0) continue;

            const tax_ids_array = tax_ids
                .split(",")
                .filter((id) => id !== "")
                .map((id) => Number(id));

            const taxes = tax_ids_array
                .map((taxId) => this.pos.models["account.tax"].get(taxId))
                .filter(Boolean);

            await this.pos.addLineToCurrentOrder(
                {
                    product_id: product,
                    price_unit: discountForGroup,
                    tax_ids: [["link", ...taxes]],
                },
                { merge: false }
            );
        }
    },
});
