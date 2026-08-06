import hashlib
import json


def format_qty(quantity):
    return f'{quantity:.4f}'.rstrip('0').rstrip('.')


def mismatch_fingerprint(env, picking, rows):
    payload = {
        'company_id': picking.company_id.id,
        'picking_id': picking.id,
        'picking_name': picking.name,
        'user_id': env.user.id,
        'rows': [
            {
                'source_move_id': row['source_move'].id,
                'foc_line_id': row['foc_line'].id,
                'substitute_product_id': row['substitute_product'].id,
                'quantity': row['quantity'],
                'substitute_uom_id': row['substitute_uom'].id,
                'substitute_category_id': row['substitute_category'].id,
                'charged_line_ids': row['charged_lines'].ids,
                'charged_uom_ids': sorted(row['charged_uoms'].ids),
                'charged_category_ids': sorted(row['charged_categories'].ids),
            }
            for row in rows
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_mismatch_rows(env, grouped_lines):
    Application = env['vendor.purchase.promotion.application']
    rows = []
    for source_move_id, substitute_lines in grouped_lines.items():
        source_move = env['stock.move'].browse(source_move_id)
        application = Application.search([
            ('foc_line_id', '=', source_move.purchase_line_id.id),
        ], limit=1)
        charged_lines = (
            application.charged_line_ids or application.charged_line_id
        ).filtered(lambda line: line.product_id and not line.display_type)
        charged_uoms = charged_lines.mapped('product_uom')
        charged_categories = charged_lines.mapped('product_id.categ_id')

        for substitute_line in substitute_lines:
            product = substitute_line.product_id
            product_uom = product.uom_id
            product_category = product.categ_id
            matching_charged_lines = charged_lines.filtered(
                lambda charged: charged.product_uom == product_uom
                and charged.product_id.categ_id == product_category
            )
            if matching_charged_lines:
                continue
            rows.append({
                'source_move': source_move,
                'application': application,
                'foc_line': source_move.purchase_line_id,
                'expected_product': source_move.purchase_line_id.product_id,
                'substitute_product': product,
                'substitute_uom': product_uom,
                'substitute_category': product_category,
                'quantity': substitute_line.quantity,
                'charged_lines': charged_lines,
                'charged_uoms': charged_uoms,
                'charged_categories': charged_categories,
            })
    return rows
