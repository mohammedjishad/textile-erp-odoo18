{
    'name': 'Textile WIP Inventory Report',
    'version': '18.0.1.0.0',
    'category': 'Inventory',
    'summary': 'WIP Inventory Reporting showing product quantities currently at each manufacturing stage/work center location',
    'depends': ['stock', 'mrp', 'textile_mrp'],
    'data': [
        'security/ir.model.access.csv',
        'views/textile_wip_inventory_report_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
