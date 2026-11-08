/**
 * @module pos_cod/app/components/cod_wizard/CodWizard
 *
 * COD Dispatch Wizard — Odoo 18 Dialog pattern.
 *
 * Open with: makeAwaitable(dialog, CodWizard, { partner_id })
 * Returns: { confirmed: true, payload: { partner_id, employee_id, delivery_address, delivery_notes } }
 *      or: undefined (if cancelled)
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { DateTimeInput } from "@web/core/datetime/datetime_input";
import { promiseDateTime } from "@pos_cod/app/utils/cod_promise";
import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { PartnerList } from "@point_of_sale/app/screens/partner_list/partner_list";
import { useService } from "@web/core/utils/hooks";
import { codWarn, codError } from "@pos_cod/app/utils/cod_logger";

const COMPONENT = "CodWizard";
const { DateTime } = luxon;

export class CodWizard extends Component {
    static template = "pos_cod.CodWizard";
    static components = { Dialog, DateTimeInput };
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
            promiseEnabled: !!this.pos.config.cod_collection_promises_enabled,
            promiseDate: "", promiseHour: 6, promiseMinute: 0, promisePeriod: "PM",
            promiseTimezone: this.pos.config.cod_collection_timezone,
            defaultsFailed: false,
        });
        onWillStart(async () => {
            if (!this.state.promiseEnabled) return;
            try {
                const defaults = await this.pos.data.call("pos.config", "cod_promise_defaults", [[this.pos.config.id]]);
                this.state.promiseEnabled = defaults.enabled;
                this.state.promiseTimezone = defaults.timezone;
                this.state.promiseDate = defaults.date;
                this.state.promiseHour = defaults.hour % 12 || 12;
                this.state.promiseMinute = defaults.minute;
                this.state.promisePeriod = defaults.hour >= 12 ? "PM" : "AM";
                this.promiseServerNow = DateTime.fromSQL(defaults.server_now, { zone: "UTC" }).toMillis();
                this.promiseClockStart = performance.now();
            } catch {
                this.state.defaultsFailed = true;
                this.state.error = "Collection defaults could not be loaded. Close and reopen this dialog when connected.";
            }
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
        return !!this.state.partner_id && !!this.state.employee_id && !this.state.defaultsFailed;
    }

    get promiseCalendarDate() {
        return this.state.promiseDate ? DateTime.fromISO(this.state.promiseDate) : false;
    }

    onPromiseDateChange(value) {
        this.state.promiseDate = value?.isValid ? value.toISODate() : "";
    }

    get promiseValue() {
        return promiseDateTime(this.state.promiseDate, this.state.promiseHour,
            this.state.promiseMinute, this.state.promisePeriod, this.state.promiseTimezone);
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
        if (this.state.defaultsFailed) return;
        let promisedAt = false;
        if (this.state.promiseEnabled) {
            const due = this.promiseValue;
            const now = this.promiseServerNow + performance.now() - this.promiseClockStart;
            if (!due || due.toMillis() <= now) {
                this.state.error = "Select a valid collection date and time later than dispatch time. The default cutoff may have passed.";
                return;
            }
            promisedAt = due.toUTC().toFormat("yyyy-MM-dd HH:mm:ss");
        }
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
                cod_promised_payment_at: promisedAt,
            },
        });
        this.props.close();
    }

    cancel() {
        codWarn(COMPONENT, "cancel", "Wizard cancelled.");
        this.props.close();
    }
}
