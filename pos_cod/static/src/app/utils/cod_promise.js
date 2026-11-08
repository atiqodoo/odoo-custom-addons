const { DateTime } = luxon;

export function promiseDateTime(date, hour, minute, period, timezone) {
    if (hour === "" || minute === "" || hour == null || minute == null) return null;
    const h = Number(hour), m = Number(minute);
    if (!date || !Number.isInteger(h) || h < 1 || h > 12 ||
        !Number.isInteger(m) || m < 0 || m > 59 || !["AM", "PM"].includes(period)) {
        return null;
    }
    const wallTime = `${date} ${String(h % 12 + (period === "PM" ? 12 : 0)).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
    const value = DateTime.fromFormat(wallTime, "yyyy-MM-dd HH:mm", { zone: timezone });
    // A DST gap must not silently move the customer's promise to another time.
    if (!value.isValid || value.toFormat("yyyy-MM-dd HH:mm") !== wallTime ||
        (value.getPossibleOffsets?.().length || 1) > 1) {
        return null;
    }
    return value;
}

export function formatPromise(value, timezone) {
    if (!value) return "Promise not set";
    const date = DateTime.fromSQL(value, { zone: "UTC" }).setZone(timezone);
    return date.isValid ? date.toFormat("dd/MM/yyyy hh:mm a") : "Invalid collection date";
}
