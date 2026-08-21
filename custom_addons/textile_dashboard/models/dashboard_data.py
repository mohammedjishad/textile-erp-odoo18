# -*- coding: utf-8 -*-
from odoo import models, api, fields
import datetime

class TextileDashboard(models.TransientModel):
    _name = 'textile.dashboard'
    _description = 'Textile Management Dashboard Data'

    def _get_scrap_cost(self, scrap):
        product = scrap.product_id
        qty = scrap.scrap_qty
        mo = scrap.production_id
        if mo:
            # If finished product template or variant
            if product.id == mo.product_id.id or product.product_tmpl_id.id == mo.product_id.product_tmpl_id.id:
                wos = sorted(mo.workorder_ids, key=lambda w: (w.sequence, w.id))
                scrap_wo = scrap.workorder_id
                if not scrap_wo and wos:
                    matching_wo = mo.workorder_ids.filtered(
                        lambda w: w.workcenter_id.wip_location_id.id == scrap.location_id.id
                    )
                    scrap_wo = matching_wo[0] if matching_wo else wos[-1]
                
                mat_cost = mo.fabric_cost + mo.thread_cost + mo.accessories_cost + mo.packaging_cost
                if scrap_wo:
                    cum_cost = mat_cost
                    for w in wos:
                        wc = w.workcenter_id
                        act_time = w.duration
                        w_labor = (act_time / 60.0) * (wc.costs_hour_labor if wc else 0.0)
                        w_machine = (act_time / 60.0) * (wc.costs_hour_machine if wc else 0.0)
                        cum_cost += w_labor + w_machine
                        if w.id == scrap_wo.id:
                            break
                    mo_planned_qty = mo.product_qty or 1.0
                    return qty * (cum_cost / mo_planned_qty)
                else:
                    mo_planned_qty = mo.product_qty or 1.0
                    total_cost = mat_cost + mo.labor_cost + mo.machine_cost
                    overhead_rate = mo.company_id.textile_overhead_rate
                    total_cost += total_cost * (overhead_rate / 100.0)
                    return qty * (product.standard_price or (total_cost / mo_planned_qty if mo_planned_qty else 0.0))
            else:
                return qty * product.standard_price
        else:
            return qty * product.standard_price

    def _get_product_wip_value(self, product, qty):
        if product.standard_price > 0:
            return qty * product.standard_price
        # If it's a finished garment variant, look up completed MOs for it
        mo = self.env['mrp.production'].search([
            ('product_id', '=', product.id),
            ('state', '=', 'done')
        ], order='date_finished desc', limit=1)
        if mo and mo.cost_per_unit > 0:
            return qty * mo.cost_per_unit
        return qty * product.product_tmpl_id.standard_price

    @api.model
    def get_dashboard_data(self, filters=None):
        if not filters:
            filters = {}

        # 1. Parse Date Filters
        period = filters.get('period', 'this_month')
        today = datetime.date.today()
        date_start = None
        date_end = None

        if period == 'this_month':
            date_start = today.replace(day=1)
            if today.month == 12:
                date_end = today.replace(year=today.year + 1, month=1, day=1) - datetime.timedelta(days=1)
            else:
                date_end = today.replace(month=today.month + 1, day=1) - datetime.timedelta(days=1)
        elif period == 'last_month':
            first_this_month = today.replace(day=1)
            date_end = first_this_month - datetime.timedelta(days=1)
            date_start = date_end.replace(day=1)
        elif period == 'this_quarter':
            quarter = (today.month - 1) // 3 + 1
            date_start = datetime.date(today.year, 3 * quarter - 2, 1)
            if quarter == 4:
                date_end = datetime.date(today.year + 1, 1, 1) - datetime.timedelta(days=1)
            else:
                date_end = datetime.date(today.year, 3 * quarter + 1, 1) - datetime.timedelta(days=1)
        elif period == 'this_year':
            date_start = datetime.date(today.year, 1, 1)
            date_end = datetime.date(today.year, 12, 31)

        so_domain = []
        mrp_domain = []
        po_domain = []
        qc_domain = []
        inv_domain = [('move_type', '=', 'out_invoice')]
        scrap_domain = [('state', '=', 'done')]

        if date_start and date_end:
            dt_start = datetime.datetime.combine(date_start, datetime.time.min)
            dt_end = datetime.datetime.combine(date_end, datetime.time.max)

            so_domain += [('date_order', '>=', dt_start), ('date_order', '<=', dt_end)]
            mrp_domain += [('create_date', '>=', dt_start), ('create_date', '<=', dt_end)]
            po_domain += [('date_order', '>=', dt_start), ('date_order', '<=', dt_end)]
            qc_domain += [('create_date', '>=', dt_start), ('create_date', '<=', dt_end)]
            inv_domain += [('invoice_date', '>=', date_start), ('invoice_date', '<=', date_end)]
            scrap_domain += [('create_date', '>=', dt_start), ('create_date', '<=', dt_end)]

        # 2. Sales Metrics
        sale_groups = self.env['sale.order'].read_group(so_domain, ['state'], ['state'])
        sales_data = {
            'quotations': sum(g.get('state_count', 0) for g in sale_groups if g.get('state') in ['draft', 'sent']),
            'sales_orders': sum(g.get('state_count', 0) for g in sale_groups if g.get('state') == 'sale'),
            'confirmed': sum(g.get('state_count', 0) for g in sale_groups if g.get('state') == 'sale'),
            'delivery_pending': self.env['sale.order'].search_count(so_domain + [('state', '=', 'sale'), ('delivery_status', 'in', ['pending', 'partial'])]) if 'delivery_status' in self.env['sale.order']._fields else 0,
            'delivered': self.env['sale.order'].search_count(so_domain + [('state', '=', 'sale'), ('delivery_status', '=', 'full')]) if 'delivery_status' in self.env['sale.order']._fields else 0,
        }

        # 3. Manufacturing Metrics
        mrp_groups = self.env['mrp.production'].read_group(mrp_domain, ['state'], ['state'])
        mrp_data = {
            'total': sum(g.get('state_count', 0) for g in mrp_groups),
            'draft': sum(g.get('state_count', 0) for g in mrp_groups if g.get('state') == 'draft'),
            'confirmed': sum(g.get('state_count', 0) for g in mrp_groups if g.get('state') == 'confirmed'),
            'in_progress': sum(g.get('state_count', 0) for g in mrp_groups if g.get('state') == 'progress'),
            'to_close': sum(g.get('state_count', 0) for g in mrp_groups if g.get('state') == 'to_close'),
            'done': sum(g.get('state_count', 0) for g in mrp_groups if g.get('state') == 'done'),
            'cancelled': sum(g.get('state_count', 0) for g in mrp_groups if g.get('state') == 'cancel'),
        }

        # 4. Purchase Metrics
        purchase_data = {'rfqs': 0, 'purchase_orders': 0, 'waiting_receipts': 0, 'completed': 0}
        if 'purchase.order' in self.env:
            po_groups = self.env['purchase.order'].read_group(po_domain, ['state'], ['state'])
            purchase_data['rfqs'] = sum(g.get('state_count', 0) for g in po_groups if g.get('state') in ['draft', 'sent'])
            purchase_data['purchase_orders'] = sum(g.get('state_count', 0) for g in po_groups if g.get('state') == 'purchase')
            purchase_data['completed'] = sum(g.get('state_count', 0) for g in po_groups if g.get('state') == 'done')

        # 5. Inventory Metrics (stock levels are live)
        inventory_data = {
            'total_products': self.env['product.product'].search_count([('is_storable', '=', True)]),
            'raw_materials': self.env['product.product'].search_count([('is_storable', '=', True), ('categ_id.name', 'ilike', 'raw')]),
            'finished_goods': self.env['product.product'].search_count([('is_storable', '=', True), ('categ_id.name', 'ilike', 'finish')]),
            'low_stock': self.env['product.product'].search_count([('is_storable', '=', True), ('qty_available', '<=', 5), ('qty_available', '>', 0)]),
            'out_of_stock': self.env['product.product'].search_count([('is_storable', '=', True), ('qty_available', '<=', 0)]),
        }

        # 6. Quality Metrics
        quality_data = {'pending': 0, 'passed': 0, 'failed': 0, 'rework': 0, 'scrap': 0}
        if 'textile.quality' in self.env:
            batches = self.env['textile.quality'].search(qc_domain)
            for b in batches:
                if b.state == 'draft':
                    quality_data['pending'] += b.received_qty
                elif b.state == 'done':
                    quality_data['passed'] += b.passed_qty
                    quality_data['failed'] += b.failed_qty
                    quality_data['rework'] += b.rework_qty
                    quality_data['scrap'] += b.scrap_qty

        # 7. Invoicing Metrics
        invoicing_data = {'draft': 0, 'posted': 0, 'paid': 0, 'unpaid': 0}
        if 'account.move' in self.env:
            inv_groups = self.env['account.move'].read_group(inv_domain, ['state', 'payment_state'], ['state', 'payment_state'], lazy=False)
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

        # 8. Live WIP tracking counts
        wip_data = {
            'pre_production': 0, 'cutting': 0, 'stitching': 0,
            'finishing': 0, 'quality_check': 0, 'packing': 0, 'finished_goods': 0,
        }
        
        # Pre-Production comes from MOs that are confirmed
        if 'mrp.production' in self.env:
            pre_prod_mos = self.env['mrp.production'].search([('state', '=', 'confirmed')])
            wip_data['pre_production'] = sum(mo.product_qty for mo in pre_prod_mos)

        # Finished Goods
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
                    wip_data['pre_production'] += qty
                else:
                    wip_data['stitching'] += qty

        # 9. Financial and Profitability Metrics
        sales_orders = self.env['sale.order'].search(so_domain + [('state', 'in', ['sale', 'done'])])
        revenue = sum(sales_orders.mapped('amount_total'))
        
        mrp_orders = self.env['mrp.production'].search(mrp_domain)
        done_mos = mrp_orders.filtered(lambda m: m.state == 'done')
        production_cost = sum(done_mos.mapped('total_manufacturing_cost'))
        
        scraps = self.env['stock.scrap'].search(scrap_domain)
        waste_cost = sum(self._get_scrap_cost(s) for s in scraps)
        
        financials = {
            'revenue': revenue,
            'production_cost': production_cost,
            'waste_cost': waste_cost,
            'profit': revenue - production_cost - waste_cost
        }

        # 10. Top Scrapped/Damaged Products Table
        scraps_grouped = {}
        for scrap in scraps:
            pid = scrap.product_id.id
            if pid not in scraps_grouped:
                scraps_grouped[pid] = {
                    'name': scrap.product_id.display_name,
                    'category': scrap.product_id.categ_id.name or 'General',
                    'qty': 0.0,
                    'uom': scrap.product_id.uom_id.name or 'pcs',
                    'cost': 0.0,
                }
            scraps_grouped[pid]['qty'] += scrap.scrap_qty
            scraps_grouped[pid]['cost'] += self._get_scrap_cost(scrap)
            
        top_scraps = list(scraps_grouped.values())
        top_scraps.sort(key=lambda x: x['cost'], reverse=True)
        top_scraps = top_scraps[:10]

        # 11. Workcenter Backlog Breakdown
        workcenter_backlog = []
        if 'mrp.workcenter' in self.env:
            workcenters = self.env['mrp.workcenter'].search([])
            for wc in workcenters:
                wos = self.env['mrp.workorder'].search([
                    ('workcenter_id', '=', wc.id),
                    ('state', 'in', ['waiting', 'pending', 'ready', 'progress'])
                ])
                pending_count = len(wos.filtered(lambda w: w.state in ['waiting', 'pending']))
                ready_count = len(wos.filtered(lambda w: w.state == 'ready'))
                progress_count = len(wos.filtered(lambda w: w.state == 'progress'))
                
                total_qty = 0.0
                for wo in wos:
                    if 'qty_remaining' in wo._fields:
                        total_qty += wo.qty_remaining
                    elif 'qty_production' in wo._fields:
                        total_qty += wo.qty_production - wo.qty_produced
                    else:
                        total_qty += wo.qty_producing or 0.0
                
                workcenter_backlog.append({
                    'workcenter_id': wc.id,
                    'name': wc.name,
                    'pending': pending_count,
                    'ready': ready_count,
                    'progress': progress_count,
                    'total_qty': max(0.0, total_qty),
                })

        # 12. Real-time WIP Inventory by Product (directly from SQL View report)
        wip_inventory = []
        if 'textile.wip.inventory.report' in self.env:
            wip_report_lines = self.env['textile.wip.inventory.report'].search([])
            wip_grouped = {}
            for line in wip_report_lines:
                wc_name = line.workcenter_id.name or 'Unknown'
                prod_id = line.product_id.id
                key = (wc_name, prod_id)
                if key not in wip_grouped:
                    wip_grouped[key] = {
                        'workcenter': wc_name,
                        'product': line.product_id.display_name,
                        'qty': 0.0,
                        'uom': line.uom_id.name or 'pcs',
                        'value': 0.0,
                    }
                wip_grouped[key]['qty'] += line.quantity
                wip_grouped[key]['value'] += self._get_product_wip_value(line.product_id, line.quantity)
            wip_inventory = list(wip_grouped.values())
            wip_inventory.sort(key=lambda x: x['value'], reverse=True)

        # 13. Recent MO Summary
        recent_mos = []
        recent_mos_records = self.env['mrp.production'].search(mrp_domain, order='create_date desc', limit=10)
        for mo in recent_mos_records:
            mo_scraps = mo.scrap_ids.filtered(lambda s: s.state == 'done')
            mo_waste_cost = sum(self._get_scrap_cost(s) for s in mo_scraps)
            
            if mo.is_multi_variant:
                prod_name = f"{mo.product_tmpl_id.name} (Multi-Variant)"
                planned_qty = sum(mo.variant_line_ids.mapped('product_qty'))
                produced_qty = sum(mo.variant_line_ids.mapped('qty_produced'))
            else:
                prod_name = mo.product_id.display_name
                planned_qty = mo.product_qty
                produced_qty = mo.qty_produced
                
            recent_mos.append({
                'id': mo.id,
                'name': mo.name,
                'product': prod_name,
                'planned_qty': planned_qty,
                'produced_qty': produced_qty,
                'state': dict(mo._fields['state'].selection).get(mo.state, mo.state),
                'state_raw': mo.state,
                'total_cost': mo.total_manufacturing_cost if hasattr(mo, 'total_manufacturing_cost') else 0.0,
                'waste_cost': mo_waste_cost,
            })

        currency_symbol = self.env.company.currency_id.symbol or '₹'

        return {
            'sales': sales_data,
            'manufacturing': mrp_data,
            'purchase': purchase_data,
            'inventory': inventory_data,
            'quality': quality_data,
            'invoicing': invoicing_data,
            'wip': wip_data,
            'financials': financials,
            'top_scraps': top_scraps,
            'workcenter_backlog': workcenter_backlog,
            'wip_inventory': wip_inventory,
            'recent_mos': recent_mos,
            'currency_symbol': currency_symbol
        }
