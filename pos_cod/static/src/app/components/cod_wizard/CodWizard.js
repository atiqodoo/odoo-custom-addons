/**
 * @module pos_cod/app/components/cod_wizard/CodWizard
 *
 * COD Dispatch Wizard — Odoo 18 Dialog pattern.
 *
 * Open with: makeAwaitable(dialog, CodWizard, { partner_id })
 * Returns: { confirmed: true, payload: { partner_id, employee_id, delivery_address, delivery_notes } }
 *      or: undefined (if cancelled)
 */

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { PartnerList } from "@point_of_sale/app/screens/partner_list/partner_list";
import { useService } from "@web/core/utils/hooks";
import { codWarn, codError } from "@pos_cod/app/utils/cod_logger";

const COMPONENT = "CodWizard";

export class CodWizard extends Component {
    static template = "pos_cod.CodWizard";
    static components = { Dialog };
    static props = {
        partner_id: { optional: true },
        getPayload: Function,
        close: Function,
    };
    static defaultProps = {
        partner_id: null,
    };

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.state = useState({
            partner_id:       this.props.partner_id || null,
            partner_name:     this.partnerName(this.props.partner_id),
            employee_id:      null,
            delivery_address: "",
            delivery_notes:   "",
            error:            "",
        });
        codWarn(COMPONENT, "setup", "Wizard opened. Initial partner_id:", this.state.partner_id);
    }

    get partners() {
        return this.pos.models["res.partner"]?.getAll?.() || [];
    }

    get employees() {
        return this.pos.models["hr.employee"]?.getAll?.() || [];
    }

    get isValid() {
        return !!this.state.partner_id && !!this.state.employee_id;
    }

    onPartnerChange(ev) {
        const val = parseInt(ev.target.value, 10);
        this.state.partner_id = isNaN(val) ? null : val;
        this.state.partner_name = this.partnerName(this.state.partner_id);
        this.state.error = "";
    }

    partnerName(partnerId) {
        if (!partnerId) return "";
        return this.pos.models["res.partner"]?.get(partnerId)?.name || "";
    }

    async selectCustomer() {
        const current = this.state.partner_id
            ? this.pos.models["res.partner"]?.get(this.state.partner_id)
            : null;
        const partner = await makeAwaitable(this.dialog, PartnerList, {
            partner: current,
            getPayload: (newPartner) => newPartner,
        });
        if (partner) {
            this.state.partner_id = partner.id;
            this.state.partner_name = partner.name;
            this.state.error = "";
        }
    }

    onEmployeeChange(ev) {
        const val = parseInt(ev.target.value, 10);
        this.state.employee_id = isNaN(val) ? null : val;
        this.state.error = "";
    }

    onAddressInput(ev) {
        this.state.delivery_address = ev.target.value;
    }

    onNotesInput(ev) {
        this.state.delivery_notes = ev.target.value;
    }

    confirm() {
        if (!this.state.partner_id) {
            this.state.error = "Please select a customer.";
            codError(COMPONENT, "confirm", "Blocked: no customer selected.");
            return;
        }
        if (!this.state.employee_id) {
            this.state.error = "Please select a delivery employee.";
            codError(COMPONENT, "confirm", "Blocked: no employee selected.");
            return;
        }
        codWarn(COMPONENT, "confirm", "Wizard confirmed — dispatching COD payload.");
        this.props.getPayload({
            confirmed: true,
            payload: {
                partner_id:       this.state.partner_id,
                employee_id:      this.state.employee_id,
                delivery_address: this.state.delivery_address,
                delivery_notes:   this.state.delivery_notes,
            },
        });
        this.props.close();
    }

    cancel() {
        codWarn(COMPONENT, "cancel", "Wizard cancelled.");
        this.props.close();
    }
}
