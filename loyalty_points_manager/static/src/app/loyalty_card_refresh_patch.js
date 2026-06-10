/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";

patch(PosStore.prototype, {
    /**
     * Odoo returns the cached loyalty.card if it already exists in the POS store.
     * That leaves backend/manual point changes invisible until a full POS reload.
     * Refresh the cached card from the server whenever a partner's card is loaded.
     */
    async fetchLoyaltyCard(programId, partnerId) {
        const cachedCard = this.models["loyalty.card"].find(
            (card) => card.partner_id?.id === partnerId && card.program_id?.id === programId
        );

        if (cachedCard?.id > 0) {
            const [freshCard] = await this.fetchCoupons([
                ["partner_id", "=", partnerId],
                ["program_id", "=", programId],
            ]);
            if (freshCard && freshCard.id === cachedCard.id) {
                cachedCard.update({ points: freshCard.points });
            }
            return cachedCard;
        }

        return super.fetchLoyaltyCard(...arguments);
    },
});
