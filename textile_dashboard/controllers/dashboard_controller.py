from odoo import http
from odoo.http import request

class TextileDashboardController(http.Controller):
    
    @http.route('/textile_dashboard/get_data', type='json', auth='user')
    def get_dashboard_data(self, filters=None):
        return request.env['textile.dashboard'].get_dashboard_data(filters=filters)
