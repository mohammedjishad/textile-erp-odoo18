{
    'name': 'Custom Vendor Bill with Fast Purchase',
    'version': '18.0.1.0.0',
    'category': 'Purchase',
    'summary': 'Customized Vendor Bill with auto shipment creation on post',
    'description': """
        Custom Vendor Bill Module for Odoo 18
        ======================================
        - Custom fields: Warehouse, Is TCS Applicable, Delivery Challan, Remarks, Update Cost on Save
        - Extra tabs: Delivery Address, Handling Charges, E-Way Bill Details
        - Invoice lines: Stock, Label, Lot columns
        - Auto-create Incoming Shipment when bill is Posted
        - Shipment smart button on Vendor Bill
        - Fast Purchase Bill accessible from Purchase menu
    """,
    'author': 'Custom Development',
    'depends': [
        'purchase',
        'account',
        'stock',
        'purchase_stock',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/account_move_views.xml',
        'views/purchase_menu.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
