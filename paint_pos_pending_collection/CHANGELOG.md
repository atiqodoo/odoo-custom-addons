# Changelog

All notable changes to the POS Deferred / Pending Collection module will be documented in this file.

## [1.0.0] - 2025-11-28

### Added
- Initial release of POS Deferred / Pending Collection module
- Backend-only workflow for registering deferred collections
- Stock location integration with automatic moves to holding area
- Printable labels with barcode/QR codes
- Wizard for registering deferred collections from POS orders
- Wizard for processing customer collections
- Search and filter capabilities by customer, phone, POS receipt, barcode
- Aging reports (0-7 days, 8-30 days, 30+ days)
- Smart button on POS orders showing pending collection count
- Support for tint color codes on pending items
- Full audit trail linking back to original POS receipt
- Security groups for users and managers
- Mail threading and activity tracking
- Kanban, list, and form views for pending collections

### Features
- Zero changes to POS frontend interface
- Automatic sequence generation (PEND/YYYY/####)
- State management (draft → partial → done → cancelled)
- Partial collection support
- Stock move reversal on cancellation
- Customer Holding Area location auto-creation
- Integration with existing POS and inventory workflows

### Technical
- Compatible with Odoo 18 Enterprise
- Models: paint.pending.collection, paint.pending.collection.line
- Extended models: pos.order, pos.order.line
- Transient models: register.deferred.collection.wizard, collect.pending.items.wizard
- Reports: Pending Collection Label (PDF)
- Security: Two-tier access (User/Manager)

### Documentation
- Complete README with usage examples
- HTML description for app store
- Inline code comments and help text
- User guide in README

## Future Enhancements (Planned)

### [2.0.0] - Future
- SMS/Email reminders for pending collections
- Automated actions for aging items
- Shelf/bin location tracking per line
- Expiry policy with auto-return to stock after 60 days
- Dashboard with KPIs and statistics
- Multi-company support enhancements
- Mobile app integration for quick lookup

---

For support or feature requests, contact:
- Email: support@crownkenya.co.ke
- Developer: ATIQ - Crown Kenya PLC
