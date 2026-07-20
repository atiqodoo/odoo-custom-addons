from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestVendorDepartmentContacts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({
            'name': 'Demo Vendor',
            'supplier_rank': 1,
        })
        cls.contact = cls.env['res.partner'].create({
            'name': 'Sales Contact',
            'parent_id': cls.vendor.id,
            'type': 'contact',
            'function': 'Head of Sales',
            'email': 'sales@example.com',
        })

    def test_department_contact_assignment(self):
        department = self.env['vendor.department'].create({
            'vendor_id': self.vendor.id,
            'name': 'Sales',
            'contact_line_ids': [(0, 0, {
                'contact_id': self.contact.id,
                'title': 'Head of Sales',
                'is_primary': True,
            })],
        })

        self.assertEqual(department.contact_count, 1)
        self.assertEqual(self.vendor.vendor_department_count, 1)
        self.assertEqual(department.contact_line_ids.vendor_id, self.vendor)

    def test_allow_contact_from_contacts_app(self):
        other_vendor = self.env['res.partner'].create({
            'name': 'Other Vendor',
            'supplier_rank': 1,
        })
        other_contact = self.env['res.partner'].create({
            'name': 'Other Contact',
            'parent_id': other_vendor.id,
            'type': 'contact',
        })
        department = self.env['vendor.department'].create({
            'vendor_id': self.vendor.id,
            'name': 'Dispatch',
        })

        line = self.env['vendor.department.contact'].create({
            'department_id': department.id,
            'contact_id': other_contact.id,
            'title': 'Supervisor',
        })

        self.assertEqual(line.contact_id, other_contact)
