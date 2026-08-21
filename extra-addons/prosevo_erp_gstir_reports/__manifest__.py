{
    'name': 'GSTR Reports',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Localizations/Reporting',
    'summary': 'GST Returns Reports for Indian Taxation',
    'description': """
        Provides comprehensive GST Return reports including:
        - GSTR-1: Outward Supplies
        - GSTR-2A/2B: Inward Supplies & ITC
        - GSTR-3B: Monthly Summary Return
        - GSTR-9/9C: Annual Return & Reconciliation
    """,
    'author': 'Prosevo Technologies',
    'depends': [
        'base',
        'account',
        'l10n_in',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/gstirn1_reports_views.xml',
        'views/gstirn2b_reports.xml',
        'views/gstr3b_reports.xml',

    ],

    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}