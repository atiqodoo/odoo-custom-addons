# Changelog

All notable changes to the Vendor Product Restriction module will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [18.0.1.0.0] - 2025-11-02

### Added
- Initial release for Odoo 18
- Dynamic product filtering based on vendor-product mapping
- Security group "Purchase: Vendor Restriction Override"
- Automatic assignment of override group to administrators and purchase managers
- Enhanced user feedback with detailed warning messages
- Alternative vendor suggestions with pricing information
- Visual indicators for filtered vs. unrestricted modes
- Integration compatibility with purchase_net_price_compute module
- Integration compatibility with vendor_price_check wizard
- Comprehensive documentation (README, INSTALL, TESTING)
- Odoo 18 compliance (list views, no deprecated attributes)

### Features
- **Domain Filtering**: Real-time product filtering on purchase order lines
- **onchange Validation**: Server-side validation with explicit user warnings
- **Vendor Synchronization**: Automatic line-level vendor context
- **Permission-Based Override**: Flexible access control for managers
- **Alternative Vendor Display**: Shows available suppliers with pricing
- **Visual Feedback**: Color-coded badges for user guidance
- **Error Prevention**: Clear messages prevent confusion about "missing" products

### Technical Details
- Model: `purchase.order` extension
- Model: `purchase.order.line` extension
- Views: Enhanced purchase order form with context indicators
- Security: New security group with implied purchase user rights
- Dependencies: purchase, purchase_stock
- Python version: 3.10+
- Odoo version: 18.0 (compatible with 17.0)

### Documentation
- Complete installation guide
- User training materials
- Administrator configuration guide
- Comprehensive testing procedures
- Integration notes for existing modules
- Troubleshooting reference

## [Future Releases]

### Planned for v18.0.1.1.0
- [ ] Add product availability indicator in dropdown
- [ ] Quick-switch vendor action in warning dialog
- [ ] Bulk vendor mapping tool
- [ ] Audit log for override usage
- [ ] Dashboard for mapping coverage analysis

### Planned for v18.0.2.0.0
- [ ] Advanced filtering rules engine
- [ ] Category-based restrictions
- [ ] Time-based vendor access control
- [ ] Automatic vendor suggestion based on history
- [ ] Mobile app optimization

### Considered Features
- [ ] Integration with inventory forecasting
- [ ] Vendor performance scoring in warnings
- [ ] Multi-level approval for override access
- [ ] Custom notification templates
- [ ] API endpoints for external systems

---

## Version History

| Version | Date | Odoo Version | Status |
|---------|------|--------------|--------|
| 18.0.1.0.0 | 2025-11-02 | 18.0 | Current |

---

## Migration Notes

### Upgrading from No Module
- First installation, no migration needed
- Configure vendor-product mappings after installation
- Assign user permissions as needed

### Future Upgrades
Will be documented here when new versions are released.

---

## Breaking Changes

### v18.0.1.0.0
- None (initial release)

---

## Bug Fixes

### v18.0.1.0.0
- None (initial release)

---

## Known Issues

### v18.0.1.0.0
- None currently identified

---

## Support

For support, feature requests, or bug reports:
- Email: support@yourcompany.com
- Documentation: See README.md
- Testing Guide: See TESTING.md

---

## Contributors

- Initial Development: Your Company Development Team
- QA Testing: Your Company QA Team
- Documentation: Your Company Technical Writers

---

## License

LGPL-3 - See LICENSE file for details
