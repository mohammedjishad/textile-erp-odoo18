# -*- coding: utf-8 -*-
from odoo import models, fields, api, tools

class TextileWipInventoryReport(models.Model):
    _name = 'textile.wip.inventory.report'
    _description = 'WIP Inventory Report'
    _auto = False
    _order = 'workcenter_id, product_id'

    workcenter_id = fields.Many2one('mrp.workcenter', string='Work Center', readonly=True)
    location_id = fields.Many2one('stock.location', string='WIP Location', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    quantity = fields.Float(string='Quantity on Hand', readonly=True)
    reserved_quantity = fields.Float(string='Reserved Quantity', readonly=True)
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE or REPLACE VIEW {self._table} AS (
                SELECT
                    q.id as id,
                    wc.id as workcenter_id,
                    q.location_id as location_id,
                    q.product_id as product_id,
                    q.quantity as quantity,
                    q.reserved_quantity as reserved_quantity,
                    t.uom_id as uom_id
                FROM
                    stock_quant q
                JOIN
                    product_product p ON p.id = q.product_id
                JOIN
                    product_template t ON t.id = p.product_tmpl_id
                JOIN
                    mrp_workcenter wc ON wc.wip_location_id = q.location_id
                WHERE
                    q.quantity > 0
            )
        """)
