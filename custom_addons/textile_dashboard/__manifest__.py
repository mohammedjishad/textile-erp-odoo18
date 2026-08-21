{
    'name': 'Textile Management Dashboard',
    'version': '18.0.1.0.1',
    'summary': 'OWL-based Management Dashboard for Garment ERP',
    'description': """
        A comprehensive, real-time OWL dashboard for the Textile Garment ERP.
        Displays KPIs for Sales, Manufacturing, Purchase, Inventory, Quality, and Invoicing.
    """,
    'category': 'Hidden',
    'author': 'textile',
    'depends': [
        'base',
        'web',
        'sale',
        'mrp',
        'purchase',
        'stock',
        'account',
        'textile_mrp',
        'textile_quality',
        'textile_sales',
        'spreadsheet_dashboard',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/dashboard_menu.xml',
        'views/mrp_workorder_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'textile_dashboard/static/src/components/textile_dashboard.js',
            'textile_dashboard/static/src/components/textile_dashboard.xml',
            'textile_dashboard/static/src/components/dashboard.scss',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
