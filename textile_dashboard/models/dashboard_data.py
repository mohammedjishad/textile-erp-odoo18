from odoo import models, api

class TextileDashboard(models.TransientModel):
    _name = 'textile.dashboard'
    _description = 'Textile Management Dashboard Data'

    @api.model
    def get_dashboard_data(self, filters=None):
        if not filters:
            filters = {}

        # Sales
        sale_groups = self.env['sale.order'].read_group([], ['state'], ['state'])
        sales_data = {
            'quotations': sum(g.get('state_count', 0) for g in sale_groups if g.get('state') in ['draft', 'sent']),
            'sales_orders': sum(g.get('state_count', 0) for g in sale_groups if g.get('state') == 'sale'),
            'confirmed': sum(g.get('state_count', 0) for g in sale_groups if g.get('state') == 'sale'),
            'delivery_pending': self.env['sale.order'].search_count([('state', '=', 'sale'), ('delivery_status', 'in', ['pending', 'partial'])]) if 'delivery_status' in self.env['sale.order']._fields else 0,
            'delivered': self.env['sale.order'].search_count([('state', '=', 'sale'), ('delivery_status', '=', 'full')]) if 'delivery_status' in self.env['sale.order']._fields else 0,
        }

        # Manufacturing
        mrp_groups = self.env['mrp.production'].read_group([], ['state'], ['state'])
        mrp_data = {
            'total': sum(g.get('state_count', 0) for g in mrp_groups),
            'draft': sum(g.get('state_count', 0) for g in mrp_groups if g.get('state') == 'draft'),
            'confirmed': sum(g.get('state_count', 0) for g in mrp_groups if g.get('state') == 'confirmed'),
            'in_progress': sum(g.get('state_count', 0) for g in mrp_groups if g.get('state') == 'progress'),
            'to_close': sum(g.get('state_count', 0) for g in mrp_groups if g.get('state') == 'to_close'),
            'done': sum(g.get('state_count', 0) for g in mrp_groups if g.get('state') == 'done'),
            'cancelled': sum(g.get('state_count', 0) for g in mrp_groups if g.get('state') == 'cancel'),
        }

        # Purchase
        purchase_data = {'rfqs': 0, 'purchase_orders': 0, 'waiting_receipts': 0, 'completed': 0}
        if 'purchase.order' in self.env:
            po_groups = self.env['purchase.order'].read_group([], ['state'], ['state'])
            purchase_data['rfqs'] = sum(g.get('state_count', 0) for g in po_groups if g.get('state') in ['draft', 'sent'])
            purchase_data['purchase_orders'] = sum(g.get('state_count', 0) for g in po_groups if g.get('state') == 'purchase')
            purchase_data['completed'] = sum(g.get('state_count', 0) for g in po_groups if g.get('state') == 'done')

        # Inventory
        inventory_data = {
            'total_products': self.env['product.product'].search_count([('is_storable', '=', True)]),
            'raw_materials': self.env['product.product'].search_count([('is_storable', '=', True), ('categ_id.name', 'ilike', 'raw')]),
            'finished_goods': self.env['product.product'].search_count([('is_storable', '=', True), ('categ_id.name', 'ilike', 'finish')]),
            'low_stock': self.env['product.product'].search_count([('is_storable', '=', True), ('qty_available', '<=', 5), ('qty_available', '>', 0)]),
            'out_of_stock': self.env['product.product'].search_count([('is_storable', '=', True), ('qty_available', '<=', 0)]),
        }

        # Quality
        quality_data = {'pending': 0, 'passed': 0, 'failed': 0}
        if 'textile.quality' in self.env:
            q_groups = self.env['textile.quality'].read_group([], ['state', 'status'], ['state', 'status'], lazy=False)
            for g in q_groups:
                count = g.get('__count', 0)
                if g.get('state') == 'draft':
                    quality_data['pending'] += count
                elif g.get('state') == 'done':
                    if g.get('status') == 'pass':
                        quality_data['passed'] += count
                    elif g.get('status') == 'fail':
                        quality_data['failed'] += count

        # Invoicing
        invoicing_data = {'draft': 0, 'posted': 0, 'paid': 0, 'unpaid': 0}
        if 'account.move' in self.env:
            inv_groups = self.env['account.move'].read_group([('move_type', '=', 'out_invoice')], ['state', 'payment_state'], ['state', 'payment_state'], lazy=False)
            for g in inv_groups:
                count = g.get('__count', 1)
                state = g.get('state')
                pay_state = g.get('payment_state')
                if state == 'draft':
                    invoicing_data['draft'] += count
                elif state == 'posted':
                    invoicing_data['posted'] += count
                    if pay_state in ['paid', 'in_payment']:
                        invoicing_data['paid'] += count
                    elif pay_state in ['not_paid', 'partial']:
                        invoicing_data['unpaid'] += count

        # WIP
        wip_data = {
            'pre_production': 0, 'cutting': 0, 'stitching': 0,
            'finishing': 0, 'quality_check': 0, 'packing': 0, 'finished_goods': 0,
        }
        
        # Pre-Production comes from MOs that are confirmed (waiting to start cutting)
        if 'mrp.production' in self.env:
            pre_prod_mos = self.env['mrp.production'].search([('state', '=', 'confirmed')])
            wip_data['pre_production'] = sum(mo.product_qty for mo in pre_prod_mos)

        # Finished Goods comes from stock in the Finished Goods location
        if 'stock.quant' in self.env:
            fg_quants = self.env['stock.quant'].search([
                ('location_id.complete_name', 'ilike', 'Finished Goods'),
                ('quantity', '>', 0)
            ])
            wip_data['finished_goods'] = sum(fg_quants.mapped('quantity'))

        if 'mrp.workorder' in self.env:
            wos = self.env['mrp.workorder'].search([('state', 'in', ['pending', 'ready', 'progress'])])
            for wo in wos:
                wc_name = wo.workcenter_id.name.lower() if wo.workcenter_id else ''
                
                if 'qty_remaining' in wo._fields:
                    qty = wo.qty_remaining
                elif 'qty_production' in wo._fields:
                    qty = wo.qty_production
                else:
                    qty = wo.qty_producing or 0.0

                if 'cut' in wc_name:
                    wip_data['cutting'] += qty
                elif 'stitch' in wc_name or 'sew' in wc_name or 'assembl' in wc_name:
                    wip_data['stitching'] += qty
                elif 'finish' in wc_name:
                    wip_data['finishing'] += qty
                elif 'qual' in wc_name or 'qc' in wc_name or 'check' in wc_name:
                    wip_data['quality_check'] += qty
                elif 'pack' in wc_name:
                    wip_data['packing'] += qty
                elif 'pre' in wc_name or 'prep' in wc_name:
                    # Just in case they do have a prep workcenter, add it too
                    wip_data['pre_production'] += qty
                else:
                    # fallback
                    wip_data['stitching'] += qty

        return {
            'sales': sales_data,
            'manufacturing': mrp_data,
            'purchase': purchase_data,
            'inventory': inventory_data,
            'quality': quality_data,
            'invoicing': invoicing_data,
            'wip': wip_data
        }
