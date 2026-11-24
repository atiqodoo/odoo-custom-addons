# Purchase arrival alarms

Install **Native Alarms - Purchase Arrival** alongside Native Record Alarms. On a
confirmed purchase order, choose **Set Arrival Alarm** beside Expected Arrival.
Select the delivery and sound settings and save. Each user can set their own alarm.
The user can change **Alarm At** without changing the purchase order. When the
order's arrival changes, the alarm retains the chosen time difference from it.
The alarm tracks the order header's expected arrival; it is not a separate alarm
for each product or receipt. When that date changes, active alarms follow it on
the next browser or registered PC synchronization. Snooze remains in effect until
the arrival changes. Stopped or cancelled alarms are not reactivated.

Alarms are suppressed when the order is cancelled, the date is removed, access is
lost, or the order's stock receipt status is fully received. For orders without
stock receipts, completion must be managed by stopping or cancelling the alarm.
Split deliveries can retain an earlier historical header date; review the order's
individual receipt dates. Normal Odoo access and company rules apply.

Browser sound requires Odoo to remain open and sound enabled with the top-bar
button; registered PCs require the existing companion. Synchronization intervals,
missed-alarm tolerance, browser audio rules, offline behavior and sound settings
are those of Native Record Alarms. Installing this addon does not modify purchase
orders or delivery dates, and purchase transactions do not depend on alarm sync.
