{
    'name': 'Inventory Report Dashboard',
    'version': '18.0.1.0.0',
    'summary': 'Category/Product wise inventory pivot report with PDF export',
    'category': 'Inventory',
    'depends': ['stock', 'product'],
    'data': [
        'views/inventory_report_views.xml',
        'views/inventory_report_menu.xml',
        'report/inventory_report_template.xml',
        'report/inventory_report_action.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
