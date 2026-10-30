from pathlib import Path

from lxml import etree

from odoo.addons.base.models.ir_ui_view import get_view_arch_from_file
from odoo.modules.module import get_module_path
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestChequeViews(TransactionCase):
    def test_every_view_loads_from_xml_files(self):
        """Exercise the XML debug reader, not just the database arch."""
        root = Path(get_module_path("pos_cheque_return_management"))
        count = 0
        for folder in ("views", "wizard"):
            for path in (root / folder).glob("*.xml"):
                document = etree.parse(str(path))
                for record in document.xpath("//record[@model='ir.ui.view']"):
                    xmlid = "pos_cheque_return_management." + record.get("id")
                    with self.subTest(xmlid=xmlid):
                        arch = get_view_arch_from_file(str(path), xmlid)
                        self.assertTrue(arch)
                        etree.fromstring(arch.encode())
                        count += 1
        self.assertGreater(count, 0)

    def test_workflow_wizard_get_views_in_file_mode(self):
        for model, xmlid in (
            ("pos.cheque.return.wizard", "return_wizard_form"),
            ("pos.cheque.funding.wizard", "funding_wizard_form"),
            ("pos.cheque.bank.return", "return_form"),
            ("pos.cheque.bank.attempt", "attempt_form"),
        ):
            view = self.env.ref("pos_cheque_return_management." + xmlid)
            with self.subTest(model=model):
                result = self.env[model].with_context(read_arch_from_file=True).get_views(
                    [(view.id, "form")], options={"toolbar": False},
                )
                arch = result["views"]["form"]["arch"]
                self.assertEqual(etree.fromstring(arch.encode()).tag, "form")
