/**
 * @module pos_cod/app/components/cod_banner/CodBanner
 *
 * Banner notification shown in the POS header when there are pending COD orders.
 *
 * Renders: "⚠ N unpaid COD orders"
 * Click:   navigates to CodOrdersScreen
 *
 * Visibility: hidden when cod_pending_count is 0.
 */

import { Component } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { codWarn } from "@pos_cod/app/utils/cod_logger";

const COMPONENT = "CodBanner";

export class CodBanner extends Component {
    static template = "pos_cod.CodBanner";
    static props = {};

    setup() {
        this.pos = usePos();
    }

    get pendingCount() {
        return this.pos.cod_pending_count || 0;
    }

    get isVisible() {
        return this.pendingCount > 0;
    }

    get label() {
        const n = this.pendingCount;
        return `⚠ ${n} unpaid COD order${n !== 1 ? "s" : ""}`;
    }

    onClick() {
        codWarn(COMPONENT, "onClick", `Banner clicked — navigating to CodOrdersScreen (${this.pendingCount} pending).`);
        this.pos.showScreen("CodOrdersScreen");
    }
}
