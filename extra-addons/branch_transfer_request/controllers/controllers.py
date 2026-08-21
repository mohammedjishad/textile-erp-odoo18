# -*- coding: utf-8 -*-
# from odoo import http


# class BranchTransferRequest(http.Controller):
#     @http.route('/branch_transfer_request/branch_transfer_request', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/branch_transfer_request/branch_transfer_request/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('branch_transfer_request.listing', {
#             'root': '/branch_transfer_request/branch_transfer_request',
#             'objects': http.request.env['branch_transfer_request.branch_transfer_request'].search([]),
#         })

#     @http.route('/branch_transfer_request/branch_transfer_request/objects/<model("branch_transfer_request.branch_transfer_request"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('branch_transfer_request.object', {
#             'object': obj
#         })

