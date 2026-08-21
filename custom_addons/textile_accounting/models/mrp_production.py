from odoo import models, fields, api
from odoo.exceptions import UserError

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    material_cost = fields.Float(string="Material Cost", compute="_compute_mfg_costs", store=True)
    labour_cost = fields.Float(string="Labour Cost", compute="_compute_mfg_costs", store=True)
    machine_cost = fields.Float(string="Machine Cost", compute="_compute_mfg_costs", store=True)
    
    # Override overhead_cost from textile_mrp to compute it dynamically
    overhead_cost = fields.Float(string="Overhead Cost", compute="_compute_mfg_costs", store=True)
    total_manufacturing_cost = fields.Float(string="Total Manufacturing Cost", compute="_compute_mfg_costs", store=True)
    
    manufacturing_value = fields.Float(string="Manufacturing Value", compute="_compute_mfg_costs", store=True)
    cost_per_unit = fields.Float(string="Production Cost per Unit", compute="_compute_mfg_costs", store=True)
    manufacturing_profit = fields.Float(string="Manufacturing Profit/Loss", compute="_compute_mfg_costs", store=True)
    
    cost_sheet_dashboard = fields.Html(string="Cost Sheet Dashboard", compute="_compute_mfg_costs", store=True)

    @api.depends(
        'fabric_cost', 'thread_cost', 'accessories_cost', 'packaging_cost',
        'labor_cost', 'machine_cost', 'qty_produced', 'qty_producing', 'product_qty',
        'state', 'company_id.textile_overhead_rate', 'product_id.standard_price',
        'is_multi_variant', 'variant_line_ids.product_qty', 'variant_line_ids.qty_producing',
        'variant_line_ids.qty_produced', 'workorder_ids.state', 'workorder_ids.duration',
        'workorder_ids.duration_expected', 'workorder_ids.qty_produced', 'scrap_ids.state',
        'scrap_ids.scrap_qty', 'scrap_ids.product_id', 'scrap_ids.workorder_id'
    )
    def _compute_mfg_costs(self):
        for mo in self:
            # 1. Standard Odoo Totals
            mat_cost = mo.fabric_cost + mo.thread_cost + mo.accessories_cost + mo.packaging_cost
            lab_cost = mo.labor_cost
            mac_cost = mo.machine_cost
            overhead_rate = mo.company_id.textile_overhead_rate
            ovh_cost = (mat_cost + lab_cost + mac_cost) * (overhead_rate / 100.0)
            total_cost = mat_cost + lab_cost + mac_cost + ovh_cost
            
            finished_qty = mo.qty_produced if mo.state == 'done' else (mo.qty_producing or mo.product_qty)
            mfg_value = finished_qty * mo.product_id.standard_price
            unit_cost = (total_cost / finished_qty) if finished_qty > 0 else 0.0
            profit = mfg_value - total_cost

            # Format helper
            symbol = mo.company_id.currency_id.symbol or '₹'
            
            def fmt(val):
                return f"{symbol}{val:,.2f}"
            
            def format_duration(minutes):
                if minutes <= 0:
                    return "0 min"
                hrs = int(minutes // 60)
                mins = int(minutes % 60)
                if hrs > 0:
                    return f"{hrs} hr {mins} min" if mins > 0 else f"{hrs} hr"
                return f"{mins} min"

            # 2. Gather Operations / Workorders
            wos = sorted(mo.workorder_ids, key=lambda w: (w.sequence, w.id))
            
            # --- E1: Stage-wise Cost Breakdown ---
            stage_rows = []
            total_qty_processed = 0.0
            total_actual_time = 0.0
            total_wo_labor_cost = 0.0
            total_wo_machine_cost = 0.0
            total_wo_op_cost = 0.0
            
            for wo in wos:
                wc = wo.workcenter_id
                wc_name = wc.name if wc else "Unknown Work Center"
                qty_proc = wo.qty_produced
                actual_time = wo.duration
                
                wc_labor_rate = wc.costs_hour_labor if wc else 0.0
                wc_machine_rate = wc.costs_hour_machine if wc else 0.0
                
                wo_labor = (actual_time / 60.0) * wc_labor_rate
                wo_machine = (actual_time / 60.0) * wc_machine_rate
                wo_op = wo_labor + wo_machine
                
                total_qty_processed += qty_proc
                total_actual_time += actual_time
                total_wo_labor_cost += wo_labor
                total_wo_machine_cost += wo_machine
                total_wo_op_cost += wo_op
                
                stage_rows.append({
                    'name': wo.name.title(),
                    'workcenter': wc_name,
                    'qty_processed': qty_proc,
                    'actual_time': actual_time,
                    'labor_cost': wo_labor,
                    'machine_cost': wo_machine,
                    'total_op_cost': wo_op
                })

            # --- E2: Cost Accumulation ---
            accum_rows = []
            current_accum_val = mat_cost
            accum_rows.append({
                'stage': 'Raw Material',
                'value': current_accum_val
            })
            for row in stage_rows:
                current_accum_val += row['total_op_cost']
                accum_rows.append({
                    'stage': row['name'],
                    'value': current_accum_val
                })

            # --- E3: Live WIP Cost Tracking ---
            scrap_by_wo_id = {}
            done_scraps = mo.scrap_ids.filtered(lambda s: s.state == 'done')
            for scrap in done_scraps:
                wo_id = scrap.workorder_id.id
                if not wo_id and wos:
                    matching_wo = mo.workorder_ids.filtered(
                        lambda w: w.workcenter_id.wip_location_id.id == scrap.location_id.id
                    )
                    if matching_wo:
                        wo_id = matching_wo[0].id
                    else:
                        if scrap.product_id.id == mo.product_id.id:
                            qc_wo = mo.workorder_ids.filtered(
                                lambda w: 'quality' in w.workcenter_id.name.lower() or 'qc' in w.workcenter_id.name.lower()
                            )
                            if qc_wo:
                                wo_id = qc_wo[0].id
                    if not wo_id:
                        wo_id = wos[0].id
                if wo_id:
                    scrap_by_wo_id[wo_id] = scrap_by_wo_id.get(wo_id, 0.0) + scrap.scrap_qty

            wip_rows = []
            cumulative_cost = mat_cost
            mo_planned_qty = mo.product_qty or 1.0
            
            for idx, wo in enumerate(wos):
                if mo.state in ('done', 'cancel'):
                    wip_qty = 0.0
                elif idx == 0:
                    entered = mo.product_qty
                    left = wo.qty_produced
                    scrapped = scrap_by_wo_id.get(wo.id, 0.0)
                    wip_qty = max(0.0, entered - left - scrapped)
                else:
                    entered = wos[idx - 1].qty_produced
                    left = wo.qty_produced
                    scrapped = scrap_by_wo_id.get(wo.id, 0.0)
                    wip_qty = max(0.0, entered - left - scrapped)
                
                wc = wo.workcenter_id
                actual_time = wo.duration
                wc_labor_rate = wc.costs_hour_labor if wc else 0.0
                wc_machine_rate = wc.costs_hour_machine if wc else 0.0
                wo_op = ((actual_time / 60.0) * wc_labor_rate) + ((actual_time / 60.0) * wc_machine_rate)
                cumulative_cost += wo_op
                
                unit_cost_at_stage = cumulative_cost / mo_planned_qty
                wip_value = wip_qty * unit_cost_at_stage
                wip_rows.append({
                    'stage': wo.name.title(),
                    'qty': wip_qty,
                    'value': wip_value
                })

            # --- E4: Waste Cost Analysis ---
            waste_rows = []
            total_waste_qty = 0.0
            total_waste_cost = 0.0
            
            for scrap in done_scraps:
                product = scrap.product_id
                qty = scrap.scrap_qty
                
                if product.id == mo.product_id.id:
                    scrap_wo = scrap.workorder_id
                    if not scrap_wo and wos:
                        matching_wo = mo.workorder_ids.filtered(
                            lambda w: w.workcenter_id.wip_location_id.id == scrap.location_id.id
                        )
                        scrap_wo = matching_wo[0] if matching_wo else wos[-1]
                    
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
                        unit_cost_scrap = cum_cost / mo_planned_qty
                    else:
                        unit_cost_scrap = product.standard_price or (total_cost / mo_planned_qty if mo_planned_qty else 0.0)
                else:
                    unit_cost_scrap = product.standard_price
                
                cost = qty * unit_cost_scrap
                total_waste_qty += qty
                total_waste_cost += cost
                
                stage_name = scrap.workorder_id.name.title() if scrap.workorder_id else "Inventory"
                waste_rows.append({
                    'type': f"{stage_name} - {product.name}",
                    'qty': qty,
                    'uom': product.uom_id.name or 'pcs',
                    'cost': cost
                })

            # --- E5: Work Center Performance & Cost Variance ---
            perf_rows = []
            highest_variance_wo = "N/A"
            highest_variance_val = -999999.0
            
            for wo in wos:
                wc = wo.workcenter_id
                planned_time = wo.duration_expected
                actual_time = wo.duration
                
                labor_rate = wc.costs_hour_labor if wc else 0.0
                machine_rate = wc.costs_hour_machine if wc else 0.0
                hourly_rate = labor_rate + machine_rate
                
                planned_cost = (planned_time / 60.0) * hourly_rate
                actual_cost = (actual_time / 60.0) * hourly_rate
                cost_variance = actual_cost - planned_cost
                
                efficiency = 100.0
                if actual_time > 0:
                    efficiency = (planned_time / actual_time) * 100.0
                elif planned_time > 0:
                    efficiency = 0.0
                
                if cost_variance > highest_variance_val:
                    highest_variance_val = cost_variance
                    highest_variance_wo = wo.name.title()
                
                perf_rows.append({
                    'name': wo.name.title(),
                    'workcenter': wc.name if wc else "Unknown",
                    'planned_time': planned_time,
                    'actual_time': actual_time,
                    'efficiency': efficiency,
                    'cost_variance': cost_variance
                })

            # --- E6: Variant-wise Costing ---
            variant_rows = []
            if mo.is_multi_variant and mo.variant_line_ids:
                total_var_qty = sum(mo.variant_line_ids.mapped('product_qty')) or 1.0
                for v_line in mo.variant_line_ids:
                    qty = v_line.product_qty
                    prop = qty / total_var_qty
                    
                    var_mat = mat_cost * prop
                    var_lab = lab_cost * prop
                    var_mac = mac_cost * prop
                    var_total = var_mat + var_lab + var_mac
                    var_unit = var_total / qty if qty > 0 else 0.0
                    
                    v_name = v_line.product_id.product_template_attribute_value_ids.mapped('name')
                    v_label = "/".join(v_name) if v_name else v_line.product_id.display_name
                    
                    variant_rows.append({
                        'label': v_label,
                        'qty': qty,
                        'material': var_mat,
                        'labor': var_lab,
                        'machine': var_mac,
                        'total': var_total,
                        'unit': var_unit
                    })

            # --- E7: KPI Metrics ---
            highest_cost_wo = "N/A"
            highest_cost_val = -1.0
            for row in stage_rows:
                if row['total_op_cost'] > highest_cost_val:
                    highest_cost_val = row['total_op_cost']
                    highest_cost_wo = row['workcenter']
            highest_cost_wc_name = highest_cost_wo
            
            waste_stage_map = {}
            for row in waste_rows:
                parts = row['type'].split(" - ")
                stage = parts[0] if parts else "Unknown"
                waste_stage_map[stage] = waste_stage_map.get(stage, 0.0) + row['cost']
            highest_waste_stage = "N/A"
            highest_waste_val = -1.0
            for stage, val in waste_stage_map.items():
                if val > highest_waste_val:
                    highest_waste_val = val
                    highest_waste_stage = stage
            highest_waste_stage_name = highest_waste_stage

            # --- 3. Build HTML Dashboard Layout ---
            html = '<div style="background-color: #f8fafc; border-radius: 16px; padding: 24px; font-family: system-ui, -apple-system, sans-serif; color: #1e293b; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">'
            
            # KPI SUMMARY SECTION
            html += '  <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px;">'
            
            kpis = [
                ("Material Cost", fmt(mat_cost), "#3b82f6"),
                ("Labour Cost", fmt(lab_cost), "#10b981"),
                ("Machine Cost", fmt(mac_cost), "#8b5cf6"),
                ("Overhead", fmt(ovh_cost), "#f59e0b"),
                ("Total Mfg Cost", fmt(total_cost), "#0f172a"),
                ("Cost per Piece", fmt(unit_cost), "#06b6d4"),
                ("Total Waste Cost", fmt(total_waste_cost), "#ef4444"),
                ("Highest Cost Stage", highest_cost_wc_name, "#ec4899"),
                ("Highest Waste Stage", highest_waste_stage_name, "#f97316"),
            ]
            
            for label, val, color in kpis:
                html += f'    <div style="background: #ffffff; padding: 16px; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.02); border-top: 4px solid {color};">'
                html += f'      <div style="font-size: 11px; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px;">{label}</div>'
                html += f'      <div style="font-size: 18px; font-weight: 700; color: #0f172a; margin-top: 6px;">{val}</div>'
                html += '    </div>'
            html += '  </div>'
            
            # TABLES GRID (2 columns)
            html += '  <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px; flex-wrap: wrap;">'
            
            # LEFT COLUMN: Stage Breakdown & Performance
            html += '    <div style="display: flex; flex-direction: column; gap: 24px;">'
            
            # Enhancement 1 Table
            html += '      <div style="background: #ffffff; padding: 20px; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.02);">'
            html += '        <h4 style="margin: 0 0 16px 0; color: #0f172a; font-size: 15px; font-weight: 600; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px;">Production Cost Breakdown (Stage-wise)</h4>'
            html += '        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">'
            html += '          <thead>'
            html += '            <tr style="border-bottom: 2px solid #e2e8f0; color: #475569; text-align: left; font-weight: 600;">'
            html += '              <th style="padding: 8px;">Work Center</th>'
            html += '              <th style="padding: 8px; text-align: right;">Qty Processed</th>'
            html += '              <th style="padding: 8px; text-align: right;">Actual Time</th>'
            html += '              <th style="padding: 8px; text-align: right;">Labour Cost</th>'
            html += '              <th style="padding: 8px; text-align: right;">Machine Cost</th>'
            html += '              <th style="padding: 8px; text-align: right; font-weight: bold;">Total Operation Cost</th>'
            html += '            </tr>'
            html += '          </thead>'
            html += '          <tbody>'
            for idx, r in enumerate(stage_rows):
                bg = '#f8fafc' if idx % 2 == 1 else '#ffffff'
                html += f'            <tr style="background: {bg}; border-bottom: 1px solid #f1f5f9;">'
                html += f'              <td style="padding: 8px; font-weight: 500; color: #1e293b;">{r["name"]}<br/><span style="font-size:11px; color:#94a3b8;">{r["workcenter"]}</span></td>'
                html += f'              <td style="padding: 8px; text-align: right;">{int(r["qty_processed"])} pcs</td>'
                html += f'              <td style="padding: 8px; text-align: right;">{format_duration(r["actual_time"])}</td>'
                html += f'              <td style="padding: 8px; text-align: right; color: #475569;">{fmt(r["labor_cost"])}</td>'
                html += f'              <td style="padding: 8px; text-align: right; color: #475569;">{fmt(r["machine_cost"])}</td>'
                html += f'              <td style="padding: 8px; text-align: right; font-weight: 600; color: #0f172a;">{fmt(r["total_op_cost"])}</td>'
                html += '            </tr>'
            # Totals
            html += '            <tr style="border-top: 2px solid #e2e8f0; font-weight: 700; background: #f8fafc;">'
            html += '              <td style="padding: 10px;">Total</td>'
            html += f'             <td style="padding: 10px; text-align: right;">{int(total_qty_processed)} pcs</td>'
            html += f'             <td style="padding: 10px; text-align: right;">{format_duration(total_actual_time)}</td>'
            html += f'             <td style="padding: 10px; text-align: right;">{fmt(total_wo_labor_cost)}</td>'
            html += f'             <td style="padding: 10px; text-align: right;">{fmt(total_wo_machine_cost)}</td>'
            html += f'             <td style="padding: 10px; text-align: right; color: #1e3a8a;">{fmt(total_wo_op_cost)}</td>'
            html += '            </tr>'
            html += '          </tbody>'
            html += '        </table>'
            html += '      </div>'
            
            # Enhancement 5 Table (Performance)
            html += '      <div style="background: #ffffff; padding: 20px; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.02);">'
            html += '        <h4 style="margin: 0 0 16px 0; color: #0f172a; font-size: 15px; font-weight: 600; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px;">Work Center Performance &amp; Time Efficiency</h4>'
            html += '        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">'
            html += '          <thead>'
            html += '            <tr style="border-bottom: 2px solid #e2e8f0; color: #475569; text-align: left; font-weight: 600;">'
            html += '              <th style="padding: 8px;">Work Center</th>'
            html += '              <th style="padding: 8px; text-align: right;">Planned Time</th>'
            html += '              <th style="padding: 8px; text-align: right;">Actual Time</th>'
            html += '              <th style="padding: 8px; text-align: right;">Time Efficiency</th>'
            html += '              <th style="padding: 8px; text-align: right;">Cost Variance</th>'
            html += '            </tr>'
            html += '          </thead>'
            html += '          <tbody>'
            for idx, r in enumerate(perf_rows):
                bg = '#f8fafc' if idx % 2 == 1 else '#ffffff'
                
                # Efficiency badge
                eff = r["efficiency"]
                if eff >= 100.0:
                    eff_badge = f'<span style="background: #dcfce7; color: #15803d; padding: 2px 6px; border-radius: 6px; font-weight: 600;">{int(eff)}%</span>'
                elif eff >= 80.0:
                    eff_badge = f'<span style="background: #fef3c7; color: #b45309; padding: 2px 6px; border-radius: 6px; font-weight: 600;">{int(eff)}%</span>'
                else:
                    eff_badge = f'<span style="background: #fee2e2; color: #b91c1c; padding: 2px 6px; border-radius: 6px; font-weight: 600;">{int(eff)}%</span>'
                
                # Cost Variance badge
                cv = r["cost_variance"]
                if cv > 0:
                    cv_badge = f'<span style="background: #fee2e2; color: #b91c1c; padding: 2px 6px; border-radius: 6px; font-weight: 600;">+{fmt(cv)}</span>'
                elif cv < 0:
                    cv_badge = f'<span style="background: #dcfce7; color: #15803d; padding: 2px 6px; border-radius: 6px; font-weight: 600;">-{fmt(abs(cv))}</span>'
                else:
                    cv_badge = f'<span style="color: #64748b;">{fmt(0.0)}</span>'
                
                # Highlight if highest variance
                highlight_style = 'border-left: 4px solid #ef4444;' if (r["name"] == highest_variance_wo and cv > 0) else ''
                
                html += f'            <tr style="background: {bg}; border-bottom: 1px solid #f1f5f9; {highlight_style}">'
                html += f'              <td style="padding: 8px; font-weight: 500; color: #1e293b;">{r["name"]}<br/><span style="font-size:11px; color:#94a3b8;">{r["workcenter"]}</span></td>'
                html += f'              <td style="padding: 8px; text-align: right;">{format_duration(r["planned_time"])}</td>'
                html += f'              <td style="padding: 8px; text-align: right;">{format_duration(r["actual_time"])}</td>'
                html += f'              <td style="padding: 8px; text-align: right;">{eff_badge}</td>'
                html += f'              <td style="padding: 8px; text-align: right;">{cv_badge}</td>'
                html += '            </tr>'
            html += '          </tbody>'
            html += '        </table>'
            html += '      </div>'
            
            html += '    </div>' # End Left Column
            
            # RIGHT COLUMN: Cost Accumulation, WIP, Waste, Variants
            html += '    <div style="display: flex; flex-direction: column; gap: 24px;">'
            
            # Enhancement 2 & 3 combined: Cost Accumulation & Live WIP
            html += '      <div style="background: #ffffff; padding: 20px; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.02);">'
            html += '        <h4 style="margin: 0 0 16px 0; color: #0f172a; font-size: 15px; font-weight: 600; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px;">Cost Accumulation &amp; Live WIP Cost Tracking</h4>'
            html += '        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">'
            html += '          <thead>'
            html += '            <tr style="border-bottom: 2px solid #e2e8f0; color: #475569; text-align: left; font-weight: 600;">'
            html += '              <th style="padding: 8px;">Production Stage</th>'
            html += '              <th style="padding: 8px; text-align: right;">Cumulative Batch Value</th>'
            html += '              <th style="padding: 8px; text-align: right;">WIP Quantity</th>'
            html += '              <th style="padding: 8px; text-align: right; font-weight: bold;">WIP Inventory Value</th>'
            html += '            </tr>'
            html += '          </thead>'
            html += '          <tbody>'
            # Raw materials row
            raw_wip_val = 0.0 # Raw material WIP is usually 0 since they are transferred immediately or are not in operations
            html += '            <tr style="border-bottom: 1px solid #f1f5f9;">'
            html += '              <td style="padding: 8px; font-weight: 500; color: #64748b;">Raw Material Stage</td>'
            html += f'             <td style="padding: 8px; text-align: right; color: #475569;">{fmt(accum_rows[0]["value"])}</td>'
            html += '              <td style="padding: 8px; text-align: right; color: #94a3b8;">-</td>'
            html += '              <td style="padding: 8px; text-align: right; color: #94a3b8;">-</td>'
            html += '            </tr>'
            
            total_wip_qty = 0.0
            total_wip_value = 0.0
            for idx, r in enumerate(wip_rows):
                bg = '#f8fafc' if idx % 2 == 1 else '#ffffff'
                accum_val = accum_rows[idx + 1]["value"]
                
                total_wip_qty += r["qty"]
                total_wip_value += r["value"]
                
                wip_qty_str = f"{int(r['qty'])} pcs" if r['qty'] > 0 else "-"
                wip_val_str = fmt(r['value']) if r['qty'] > 0 else "-"
                
                # Bold WIP if active
                wip_style = 'font-weight: 600; color: #1e3a8a;' if r['qty'] > 0 else 'color: #94a3b8;'
                
                html += f'            <tr style="background: {bg}; border-bottom: 1px solid #f1f5f9;">'
                html += f'              <td style="padding: 8px; font-weight: 500; color: #1e293b;">{r["stage"]}</td>'
                html += f'              <td style="padding: 8px; text-align: right; color: #475569;">{fmt(accum_val)}</td>'
                html += f'              <td style="padding: 8px; text-align: right; {wip_style}">{wip_qty_str}</td>'
                html += f'              <td style="padding: 8px; text-align: right; {wip_style}">{wip_val_str}</td>'
                html += '            </tr>'
                
            # Totals
            html += '            <tr style="border-top: 2px solid #e2e8f0; font-weight: 700; background: #f8fafc;">'
            html += '              <td style="padding: 10px;" colspan="2">Total WIP in Production</td>'
            html += f'             <td style="padding: 10px; text-align: right; color: #1e3a8a;">{int(total_wip_qty)} pcs</td>'
            html += f'             <td style="padding: 10px; text-align: right; color: #1e3a8a;">{fmt(total_wip_value)}</td>'
            html += '            </tr>'
            html += '          </tbody>'
            html += '        </table>'
            html += '      </div>'

            # Enhancement 4: Waste Cost Analysis
            html += '      <div style="background: #ffffff; padding: 20px; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.02);">'
            html += '        <h4 style="margin: 0 0 16px 0; color: #ef4444; font-size: 15px; font-weight: 600; border-bottom: 1px solid #fee2e2; padding-bottom: 10px;">Waste &amp; Damage Cost Analysis</h4>'
            if not waste_rows:
                html += '        <div style="color: #64748b; font-size: 13px; font-style: italic; padding: 10px 0;">No waste or scrap recorded for this Manufacturing Order.</div>'
            else:
                html += '        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">'
                html += '          <thead>'
                html += '            <tr style="border-bottom: 2px solid #fee2e2; color: #475569; text-align: left; font-weight: 600;">'
                html += '              <th style="padding: 8px;">Waste Stage / Product</th>'
                html += '              <th style="padding: 8px; text-align: right;">Quantity</th>'
                html += '              <th style="padding: 8px; text-align: right; font-weight: bold; color: #b91c1c;">Waste Cost</th>'
                html += '            </tr>'
                html += '          </thead>'
                html += '          <tbody>'
                for idx, r in enumerate(waste_rows):
                    bg = '#fff5f5' if idx % 2 == 1 else '#ffffff'
                    html += f'            <tr style="background: {bg}; border-bottom: 1px solid #fee2e2;">'
                    html += f'              <td style="padding: 8px; font-weight: 500; color: #1e293b;">{r["type"]}</td>'
                    html += f'              <td style="padding: 8px; text-align: right;">{r["qty"]:,.2f} {r["uom"]}</td>'
                    html += f'              <td style="padding: 8px; text-align: right; font-weight: 600; color: #b91c1c;">{fmt(r["cost"])}</td>'
                    html += '            </tr>'
                # Totals
                html += '            <tr style="border-top: 2px solid #fca5a5; font-weight: 700; background: #fff5f5;">'
                html += '              <td style="padding: 10px;">Total Waste Loss</td>'
                html += f'             <td style="padding: 10px; text-align: right;">{total_waste_qty:,.2f} units</td>'
                html += f'             <td style="padding: 10px; text-align: right; color: #b91c1c;">{fmt(total_waste_cost)}</td>'
                html += '            </tr>'
                html += '          </tbody>'
                html += '        </table>'
            html += '      </div>'

            # Enhancement 6: Variant-wise Costing
            if variant_rows:
                html += '      <div style="background: #ffffff; padding: 20px; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.02);">'
                html += '        <h4 style="margin: 0 0 16px 0; color: #0f172a; font-size: 15px; font-weight: 600; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px;">Product Variant Cost Breakdown</h4>'
                html += '        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">'
                html += '          <thead>'
                html += '            <tr style="border-bottom: 2px solid #e2e8f0; color: #475569; text-align: left; font-weight: 600;">'
                html += '              <th style="padding: 8px;">Variant</th>'
                html += '              <th style="padding: 8px; text-align: right;">Planned Qty</th>'
                html += '              <th style="padding: 8px; text-align: right;">Material</th>'
                html += '              <th style="padding: 8px; text-align: right;">Labour</th>'
                html += '              <th style="padding: 8px; text-align: right;">Machine</th>'
                html += '              <th style="padding: 8px; text-align: right;">Total Cost</th>'
                html += '              <th style="padding: 8px; text-align: right; font-weight: bold; color: #1e3a8a;">Cost / Unit</th>'
                html += '            </tr>'
                html += '          </thead>'
                html += '          <tbody>'
                for idx, r in enumerate(variant_rows):
                    bg = '#f8fafc' if idx % 2 == 1 else '#ffffff'
                    html += f'            <tr style="background: {bg}; border-bottom: 1px solid #f1f5f9;">'
                    html += f'              <td style="padding: 8px; font-weight: 600; color: #0f172a;">{r["label"]}</td>'
                    html += f'              <td style="padding: 8px; text-align: right;">{int(r["qty"])} pcs</td>'
                    html += f'              <td style="padding: 8px; text-align: right; color: #475569;">{fmt(r["material"])}</td>'
                    html += f'              <td style="padding: 8px; text-align: right; color: #475569;">{fmt(r["labor"])}</td>'
                    html += f'              <td style="padding: 8px; text-align: right; color: #475569;">{fmt(r["machine"])}</td>'
                    html += f'              <td style="padding: 8px; text-align: right; font-weight: 600; color: #0f172a;">{fmt(r["total"])}</td>'
                    html += f'              <td style="padding: 8px; text-align: right; font-weight: 700; color: #1e3a8a; background: #eff6ff;">{fmt(r["unit"])}</td>'
                    html += '            </tr>'
                html += '          </tbody>'
                html += '        </table>'
                html += '      </div>'

            html += '    </div>' # End Right Column
            
            html += '  </div>' # End Tables Grid
            html += '</div>' # End Dashboard
            
            mo.cost_sheet_dashboard = html

            # 4. Standard Odoo Writes (kept intact)
            mo.update({
                'material_cost': mat_cost,
                'labour_cost': lab_cost,
                'machine_cost': mac_cost,
                'overhead_cost': ovh_cost,
                'total_manufacturing_cost': total_cost,
                'manufacturing_value': mfg_value,
                'cost_per_unit': unit_cost,
                'manufacturing_profit': profit
            })
