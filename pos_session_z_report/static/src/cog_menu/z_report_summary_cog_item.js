/** @odoo-module **/

import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { STATIC_ACTIONS_GROUP_NUMBER } from "@web/search/action_menus/action_menus";
import { Component } from "@odoo/owl";

const cogMenuRegistry = registry.category("cogMenu");

export class PosSessionZReportSummaryCogItem extends Component {
    static template = "pos_session_z_report.ZReportSummaryCogItem";
    static components = { DropdownItem };
    static props = {};

    setup() {
        this.action = useService("action");
    }

    openWizard() {
        this.action.doAction("pos_session_z_report.action_pos_session_z_report_range_wizard");
    }
}

export const zReportSummaryCogItem = {
    Component: PosSessionZReportSummaryCogItem,
    groupNumber: STATIC_ACTIONS_GROUP_NUMBER,
    isDisplayed: (env) =>
        env.config.viewType === "list" &&
        env.searchModel?.resModel === "pos.session" &&
        !env.model.root.selection.length,
};

cogMenuRegistry.add("pos-session-z-report-summary", zReportSummaryCogItem, { sequence: 12 });
