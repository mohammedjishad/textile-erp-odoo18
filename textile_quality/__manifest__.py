{
    'name': 'Textile Quality',
    'version': '18.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'Multi-stage quality inspection for textile manufacturing',
    'depends': ['textile_mrp'],
    'data': [
        'security/ir.model.access.csv',
        'report/quality_report.xml',
        'report/quality_report_template.xml',
        'views/textile_quality_views.xml',
        'views/mrp_production_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
