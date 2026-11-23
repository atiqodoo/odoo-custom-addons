import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { DateTimeInput } from "@web/core/datetime/datetime_input";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { promiseDateTime } from "@pos_cod/app/utils/cod_promise";

const { DateTime } = luxon;

export class CodArrangementDialog extends Component {
    static template = "pos_cod.CodArrangementDialog";
    static components = { Dialog, DateTimeInput };
    static props = { order: Object, getPayload: Function, close: Function };

    setup() {
        this.pos = usePos();
        this.state = useState({
            promiseDate: "", promiseHour: 6, promiseMinute: 0, promisePeriod: "PM",
            timezone: this.pos.config.cod_collection_timezone, note: "", error: "", loading: true,
        });
        onWillStart(async () => {
            try {
                const defaults = await this.pos.data.call(
                    "pos.config", "cod_promise_defaults", [[this.pos.config.id]]
                );
                this.state.timezone = defaults.timezone;
                let due = DateTime.fromObject({
                    year: Number(defaults.date.slice(0, 4)),
                    month: Number(defaults.date.slice(5, 7)), day: Number(defaults.date.slice(8, 10)),
                    hour: defaults.hour, minute: defaults.minute,
                }, { zone: defaults.timezone });
                this.serverNow = DateTime.fromSQL(defaults.server_now, { zone: "UTC" }).toMillis();
                this.clockStart = performance.now();
                if (due.toMillis() <= this.serverNow) due = due.plus({ days: 1 });
                this.state.promiseDate = due.toISODate();
                this.state.promiseHour = due.hour % 12 || 12;
                this.state.promiseMinute = due.minute;
                this.state.promisePeriod = due.hour >= 12 ? "PM" : "AM";
            } catch {
                this.state.error = "Collection defaults could not be loaded. Reconnect and try again.";
            } finally {
                this.state.loading = false;
            }
        });
    }

    get title() {
        return this.props.order.cod_promised_payment_at
            ? "Record New Customer Promise" : "Activate Customer Arrangement";
    }

    get promiseCalendarDate() {
        return this.state.promiseDate ? DateTime.fromISO(this.state.promiseDate) : false;
    }

    onPromiseDateChange(value) {
        this.state.promiseDate = value?.isValid ? value.toISODate() : "";
    }

    onNoteInput(event) {
        this.state.note = event.target.value;
        this.state.error = "";
    }

    confirm() {
        const due = promiseDateTime(
            this.state.promiseDate, this.state.promiseHour, this.state.promiseMinute,
            this.state.promisePeriod, this.state.timezone
        );
        const now = this.serverNow + performance.now() - this.clockStart;
        if (!due || due.toMillis() <= now) {
            this.state.error = "Select a valid promised payment date and time in the future.";
            return;
        }
        const note = this.state.note.trim();
        if (!note) {
            this.state.error = "Record what the customer committed to and any follow-up details.";
            return;
        }
        if (note.length > 4000) {
            this.state.error = "The arrangement note cannot exceed 4,000 characters.";
            return;
        }
        this.props.getPayload({
            promised_at: due.toUTC().toFormat("yyyy-MM-dd HH:mm:ss"), note,
        });
        this.props.close();
    }

    cancel() {
        this.props.close();
    }
}
