# Purchase Overdue Receipt Follow-up

## Vendor delivery defaults and RFQ overrides (18.0.2.0.0)

Purchase managers configure policies under **Purchase > Configuration > Vendor
Delivery Policies**, or on the commercial vendor's **Delivery Policies** page.
There is one policy per vendor/company. Buyers can read policies but cannot change
global defaults. Archive unused policies; policies referenced by POs cannot be
deleted. Existing confirmed orders are not rescheduled when a policy changes.

Each policy has lead-time **days plus additional working hours**, an optional
receiving calendar (otherwise the company's), and an optional preferred local
arrival time. Purchase settings provide **Hours per lead-time day** (default 9)
and a configurable planning lookahead. Thus 1 day + 3 hours = 12 working hours;
Saturday contributes only its actual 5 open hours. This is working-duration
arithmetic, not counting Saturday as a full day. Calendar holidays are excluded.
Preferred time chooses the next valid occurrence at or after the duration result,
never earlier. A promise at closing time is valid; after-hours starts move to the
next receiving opening. Planning is bounded by the company's lookahead.
Delivery-calendar overrides govern arrival calculation. The overdue warning's
operating hours and grace remain governed by the company receiving calendar.

The RFQ **Delivery Planning** tab offers:

- **Vendor Default**: uses the current vendor policy when previewing/finalizing a
  new order. Without a policy, normal Odoo supplier lead-time scheduling remains.
- **RFQ Lead Time Override**: independently entered days/hours, calendar and
  optional preferred time; global vendor defaults are unchanged.
- **Fixed Expected Arrival**: exact agreed date/time, checked against receiving
  hours and the calculation start. Confirmation preserves this agreement.
- **Preview Arrival**: uses the explicitly shown Preview Start; provisional only.
- **Restore Vendor Default**: resets a draft to current vendor defaults (or standard
  Odoo scheduling if no policy exists).

Draft Expected Arrival is populated automatically from the policy on creation,
vendor/input changes and product-line date preparation. Quantity/price recomputation
uses the same planner, so it cannot silently restore the ordinary supplier delay.
Preview Arrival remains available for an explicit refresh. All draft dates are
provisional and actual approval still establishes the final calculation start.

Finalization runs on actual PO approval (`date_approve`), including final approval
after a two-step approval request. It updates the purchase lines and outstanding
receipt schedules in the same transaction. Sending an RFQ does not start the
delivery clock. No auto-confirmation, supplier email or PO approval bypass is added.

Optional product-line columns **Line Arrival Override / Line Agreed Arrival**
allow split promises. Use Preview/confirmation to apply them. Fixed dates and
overrides must be at or after confirmation and in receiving hours. Calendar times
are interpreted in the calendar's timezone and stored in UTC.

Confirmed unlocked POs use **Reschedule Delivery**, which requires a fresh reason.
The dialog stages changes until Apply, supports a new duration, exact date/time,
current vendor defaults and individual pending-line overrides. Only outstanding
receipt/backorder dates change. Completed receipt dates and original promised
arrivals remain historical. For partially received lines the standard line date
remains historical; **Current Expected Arrival** shows the revised planning date,
and pending receipt moves carry the operative date for overdue checks.

Managed orders' ordinary date fields cannot bypass the revision workflow; orders
using standard Odoo scheduling retain the standard date-editing behavior. Original
promises, calculation snapshots, revision user/time and chatter provide the audit
trail. Existing POs first opting in preserve their previous promise as the original.
No existing PO is opted in or rescheduled merely by installing this version.

Upgrade this addon and restart Odoo to create the new fields/models and load the
Python extensions. No vendor policies are created automatically. Configure the
receiving calendar and day-hour conversion per company before creating policies.

Delivery-planning release validation: 65 Odoo tests passed with zero failures/errors
in the isolated validation database, plus eight client warning contract checks.
Python/XML syntax, inherited view loading, backend asset compilation and structured
planning/rescheduling logs were verified. The running business database was not
upgraded during this implementation; interactive browser visual QA was unavailable.

Monitors active **Auto / Buy** reordering rules for outstanding supplier receipts,
including backorders. Normal Odoo forecasts and procurement remain authoritative;
late receipts are not silently cancelled or excluded from normal replenishment.

## Enable per company

Install this addon (which installs Purchase Variant Stock Compare), then enable
**Purchase > Configuration > Settings > Overdue Receipt Follow-up** per company.
Select a receiving calendar and optional grace in working hours. Existing companies
are not enabled automatically.

The editable shared receiving-calendar template is configured for Africa/Nairobi:
Monday–Friday 08:00–17:00, Saturday 08:00–13:00, Sunday closed. Assign a separate
company calendar if schedules or holidays differ. Global calendar leave intervals
are respected. Employee calendars are not changed.

Settings edits are staged on the wizard and written to the company together when
saved, so enabling monitoring and selecting the first receiving calendar in the
same save does not trigger premature validation. Invalid calendars and negative
grace periods are still rejected. Version 18.0.1.0.1 includes this save-order fix.

## Deadline policy

The outstanding supplier stock move's scheduled date/time is the expected arrival.
The company must currently be open, the expected time must have passed, and elapsed
**working** time since it must exceed the configured grace. A Sunday/closed-time
deadline becomes late after the next opening, not during the closure. At exactly
opening, no working time has yet elapsed. Cancelled/done moves and internal receipt
legs are excluded. Final destination supports multi-step receipt routes.

The editable scheduled action **Purchases: Check Overdue Receipts** runs every
five minutes by default. Automatic replenishment/POS scheduler entry points also
scan their selected rules. Scans record one follow-up per rule and are retryable.
They do not create replacement orders.

## Run from the RFQ home page

On **Purchase > Requests for Quotation**, the list control panel has a **Run
Scheduler** button next to the creation controls. It is always displayed for
system administrators, with no RFQ selection or menu navigation required.
It queues the existing Procurement and Overdue Receipt scheduled actions for the
next cron-worker wake-up, and shows a notification while remaining on the RFQ
page. It does not claim that processing is already complete. Pending requests
are reused; the jobs' normal schedules and execution users are not changed.

This is the standard database-wide scheduler, so the button is restricted to
system administrators on the server as well as in the view. It does not run only
selected RFQs or only the currently selected company. Working-hour and overdue
grace rules remain in force, including no Sunday warnings. Both jobs must be
enabled, and the Odoo cron worker must be running.

## Warning and review

Purchase users in an active backend session receive a sticky warning with a
**Review / Compare Stock** button during receiving hours. The button opens the
follow-up dialog. Notifications are checked every minute while the browser is
visible, once per alert per page session; the system does not interrupt unsaved
forms with a forced modal. All alerts remain accessible under
**Purchase > Orders > Overdue Receipt Follow-ups**.

The dialog opens original receipts/POs, compares similar stock, and lets the buyer
request a replacement draft RFQ or add a separate line to a compatible draft RFQ.
Vendor pricing, expected arrival, quantity and a follow-up reason are validated
server-side. New RFQs also collect the existing extension's vendor reference and
contact fields; its business constraints are preserved.

## Replacement calculation and duplicate protection

For this decision only, calculate location forecast plus eligible draft purchasing
in progress, minus the overdue supplier quantities under review. If that adjusted
forecast is below Min, suggest enough to reach Max. Other supply, even later dated
supply, is conservatively retained. This is not a time-phased demand planner.

Refresh this calculation at authorization; reject nonpositive or excessive
quantities and stale/rescheduled/received alerts. A parameterized row lock prevents
two users from replacing the same follow-up twice. A non-cancelled replacement
suppresses repeat requests; cancelling it allows a later scan to reopen follow-up.
Original receipts stay open: coordinate cancellation/rescheduling with the vendor
to avoid duplicate delivery. Partial replacement suppresses further requests on
that follow-up too; manage the resulting RFQ normally.

RFQ creation uses current-user ORM permissions and standard purchase preparation,
including supplier prices, currency, taxes and the existing net-price extension.
Only system-maintained alert recording/audit updates use narrowly scoped elevation.
Company record rules protect alerts and replacement wizards. No outgoing emails
or vendor messages are sent by these addons.

## Validation

Run `--test-enable --test-tags /purchase_overdue_receipt_followup`. Tests include
calendar boundaries/weekends, working-time grace, holidays, idempotent scans,
cancelled/rescheduled receipts, other RFQs, replacement validation, repeat clicks,
permissions and company isolation. Backend operations log clear
`[OVERDUE_RECEIPT][OPERATION][START/END/ERROR]` prefixes without credentials.

### Existing clean-install dependency issue

On a completely empty database, the existing `paint_colour_master` POS constraint
can reject the standard `pos_sale` down-payment product if the colour addon loads
first. No existing code was changed to bypass this. For isolated validation,
`product_movement_volume_analysis`, `vendor_department_contacts`, `sale_management`
and `pos_sale` were installed first, then these two addons. Existing databases
with those dependencies already installed do not need that staging step.

### Validation performed

Both addons installed/upgraded in the separate database
`codex_purchase_followup_validation_20261101`: 26 Odoo tests passed, with zero
failures/errors, including backend asset compilation. The standalone client
warning service passed eight contract checks. Python/XML syntax and structured
backend operation logs were checked. Interactive browser visual verification
could not run because the browser connection failed. The running business
database was not modified or used for these tests.
