# -*- coding: utf-8 -*-
{
    'name': 'Branch Transfer Request',
    'version': '18.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Inter-branch product transfer requests with notifications',
    'author': 'My Company',
    'website': 'https://www.yourcompany.com',
    'depends': [
        'base',
        'stock',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/branch_transfer_security.xml',
        'data/sequence.xml',
        'views/branch_transfer_request_views.xml',
        'views/stock_warehouse.xml',
        'wizard/branch_transfer_return_wizard_views.xml',
        'views/branch_direct_transfer_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}