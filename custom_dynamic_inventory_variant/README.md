# Custom Dynamic Inventory Variant Creation

This Odoo 18 module lets stock users create or resolve a dynamic product variant while entering a normal physical inventory adjustment line.

Workflow:

1. Open Inventory Adjustments.
2. Add one physical count line.
3. Select the product template.
4. Select template-specific variant values.
5. Odoo resolves the matching `product.product`; if the template uses dynamic attributes and the variant does not exist, Odoo creates it through `product.template._create_product_variant()`.
6. Enter the counted quantity and apply the adjustment using standard Odoo stock logic.

The module intentionally does not add a bulk import parser or custom import tool.
