/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { tkWarn } from "@team_kubwa_cashout/app/utils/team_kubwa_logger";
patch(ProductScreen.prototype, {
    get teamKubwaButtonVisible() {
        return Boolean(this.pos.team_kubwa_config?.enabled);
    },
    async onTeamKubwaButtonClick() {
        tkWarn("ProductScreen", "Opening Team Kubwa screen");
        return await this.pos.sblGuardedAction(
            "team_kubwa_open",
            () => this.pos.showScreen("TeamKubwaCashoutScreen"),
            { label: "Team Kubwa" }
        );
    },
});

