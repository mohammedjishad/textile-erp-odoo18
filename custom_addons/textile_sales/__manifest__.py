{
    'name': 'Textile Sales',
    'version': '18.0.1.0.0',
    'category': 'Sales',
    'summary': 'Textile-specific fields for products and sales orders',
    'depends': ['sale_management', 'mrp', 'stock', 'product'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/product_template_views.xml',
        'views/sale_order_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
