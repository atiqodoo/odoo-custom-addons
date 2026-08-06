/** @odoo-module */
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";

patch(PaymentScreen.prototype, {
    async validateOrder(isForceValidate = false) {
        const order = this.pos.get_order();
        
        // Ensure settings are active and the order exists
        if (!order || !this.pos.config.block_below_cost) {
            return super.validateOrder(...arguments);
        }

        const problematicLines = [];
        for (const line of order.get_orderlines()) {
            const product = line.get_product();
            const qty = line.get_quantity();
            if (qty <= 0) continue;

            const cost = product.standard_price || 0;
            const taxes = this.pos.get_taxes_after_fp(product.taxes_id, order.fiscal_position_id);
            
            // Fixed Odoo 18 compute_all service call
            const taxRes = this.pos.models["account.tax"].compute_all(
                cost,
                this.pos.currency,
                1,
                taxes,
                order.fiscal_position_id
            );

            const cost_incl = taxRes.total_included;
            const selling_incl = line.get_price_with_tax() / qty;

            if (selling_incl < cost_incl - 0.01) {
                problematicLines.push({
                    name: product.display_name,
                    cost: cost_incl.toFixed(2),
                    price: selling_incl.toFixed(2)
                });
            }
        }

        if (problematicLines.length > 0) {
            const linesMsg = problematicLines
                .map(l => `• ${l.name} (Cost: ${l.cost} | Price: ${l.price})`)
                .join("\n");

            // CRITICAL: Must use this.env.services.popup in Odoo 18
            await this.env.services.popup.add(ErrorPopup, {
                title: _t("Loss Prevention: Price Too Low"),
                body: _t("The following items are below cost (VAT incl):\n\n") + linesMsg,
            });
            return false; 
        }
        return super.validateOrder(...arguments);
    },
});