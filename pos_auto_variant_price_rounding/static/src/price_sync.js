/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { computeProductPricelistCache } from "@point_of_sale/utils";

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        this.variantPriceRevision = false;
        this.variantPriceSyncPending = false;
        this.data.connectWebSocket("VARIANT_PRICES_CHANGED", () => this.syncVariantPrices());
        this.bus.addEventListener("connect", () => this.syncVariantPrices());
        browser.addEventListener("online", () => this.syncVariantPrices());
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden) {
                this.syncVariantPrices();
            }
        });
        await this.syncVariantPrices();
    },

    async syncVariantPrices() {
        if (this.variantPriceSyncRunning) {
            this.variantPriceSyncPending = true;
            return;
        }
        this.variantPriceSyncRunning = true;
        browser.clearTimeout(this.variantPriceSyncTimer);
        try {
            do {
                this.variantPriceSyncPending = false;
                const productIds = this.models["product.product"].getAll().map((p) => p.id);
                const snapshot = await this.data.call("pos.config", "get_variant_price_snapshot", [
                    [this.config.id], productIds, this.variantPriceRevision,
                ]);
                this.variantPriceSyncInterval = snapshot.interval * 1000;
                if (snapshot.rules !== null) {
                    // Remove stale/deleted rules locally, without issuing ORM deletes.
                    for (const item of [...this.models["product.pricelist.item"].getAll()]) {
                        item.delete({ silent: true });
                    }
                    this.data.models.loadData({ "product.pricelist.item": snapshot.rules });
                }
                // Native cache computation appends rules: clear first to restore priority
                // and expire date-limited rules even when no database writes occurred.
                for (const product of this.models["product.product"].getAll()) {
                    product.cachedPricelistRules = {};
                }
                computeProductPricelistCache(this.data);
                this.variantPriceRevision = snapshot.revision;
                this.variantPriceSyncWarning = false;
            } while (this.variantPriceSyncPending);
        } catch (error) {
            // Keep cached prices and order lines intact; reconnect/timer retries later.
            if (!this.variantPriceSyncWarning) {
                this.notification.add(_t("Price synchronization is unavailable. Cached prices remain active; synchronization will retry automatically."), {
                    type: "warning",
                });
                this.variantPriceSyncWarning = true;
            }
        } finally {
            this.variantPriceSyncRunning = false;
            const seconds = this.config.auto_variant_price_sync_interval || 60;
            this.variantPriceSyncTimer = browser.setTimeout(
                () => this.syncVariantPrices(), this.variantPriceSyncInterval || Math.max(10, seconds) * 1000
            );
        }
    },
});
