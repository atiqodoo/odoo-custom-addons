{
    'name': 'Duplicate Remove Variants',
    'version': '1.0',
    'category': 'Inventory',
    'summary': 'Remove variants and attributes when duplicating products',
    'description': """
        This module modifies the duplication behavior for product templates.
        When duplicating a product, it checks for attributes/variants in the original
        and removes them from the copy, ensuring a simple product without variants.
    """,
    'depends': ['product'],
    'installable': True,
    'application': False,
    'auto_install': False,
}