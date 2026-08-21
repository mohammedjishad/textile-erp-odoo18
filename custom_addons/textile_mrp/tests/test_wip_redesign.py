# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger('test_wip')

def run_tests(env):
    print("=================== STARTING WIP REDESIGN TESTS ===================")
    
    # 1. FIND OR CREATE TEST PRODUCTS
    product_model = env['product.product']
    categ_model = env['product.category']
    
    # Find or create finished product category
    finished_category = categ_model.search([('name', '=', 'Finished Goods')], limit=1)
    if not finished_category:
        finished_category = categ_model.create({
            'name': 'Finished Goods',
            'textile_cost_bucket': 'packaging' # default cost bucket
        })
        
    # Find or create raw material category
    raw_category = categ_model.search([('name', '=', 'Raw Materials')], limit=1)
    if not raw_category:
        raw_category = categ_model.create({
            'name': 'Raw Materials',
            'textile_cost_bucket': 'fabric'
        })
        
    # Create test product (finished)
    product_shirt = product_model.search([('default_code', '=', 'TSHIRT_WIP_TEST')], limit=1)
    if not product_shirt:
        product_shirt = product_model.create({
            'name': 'Test WIP Shirt',
            'default_code': 'TSHIRT_WIP_TEST',
            'is_storable': True,
            'categ_id': finished_category.id,
            'list_price': 100.0,
            'standard_price': 50.0,
        })
        
    # Create test raw material
    product_fabric = product_model.search([('default_code', '=', 'FABRIC_WIP_TEST')], limit=1)
    if not product_fabric:
        product_fabric = product_model.create({
            'name': 'Test WIP Fabric',
            'default_code': 'FABRIC_WIP_TEST',
            'is_storable': True,
            'categ_id': raw_category.id,
            'standard_price': 10.0,
        })

    # 2. DEFINE BOM
    bom_model = env['mrp.bom']
    bom = bom_model.search([('product_tmpl_id', '=', product_shirt.product_tmpl_id.id)], limit=1)
    if not bom:
        bom = bom_model.create({
            'product_tmpl_id': product_shirt.product_tmpl_id.id,
            'product_qty': 1.0,
            'type': 'normal',
            'bom_line_ids': [
                (0, 0, {
                    'product_id': product_fabric.id,
                    'product_qty': 2.0,
                })
            ]
        })

    # 3. CONFIGURE WORK CENTERS & ROUTINGS
    workcenters = env['mrp.workcenter'].search([])
    cutting_wc = workcenters.filtered(lambda wc: 'cut' in wc.name.lower())
    stitching_wc = workcenters.filtered(lambda wc: 'stitch' in wc.name.lower() or 'sew' in wc.name.lower())
    finishing_wc = workcenters.filtered(lambda wc: 'finish' in wc.name.lower())
    qc_wc = workcenters.filtered(lambda wc: 'qual' in wc.name.lower() or 'qc' in wc.name.lower() or 'check' in wc.name.lower())
    packing_wc = workcenters.filtered(lambda wc: 'pack' in wc.name.lower())
    
    if not (cutting_wc and stitching_wc and finishing_wc and qc_wc and packing_wc):
        print("Missing required workcenters! Please ensure Cutting, Stitching, Finishing, Quality, and Packing exist.")
        return

    # Clear out any previous routings/operations on this BOM to make it clean
    bom.operation_ids.unlink()
    
    # Add operations to BOM
    operations_data = [
        ('Cutting Operation', cutting_wc[0]),
        ('Stitching Operation', stitching_wc[0]),
        ('Finishing Operation', finishing_wc[0]),
        ('Quality Check Operation', qc_wc[0]),
        ('Packing Operation', packing_wc[0]),
    ]
    for seq, (op_name, wc) in enumerate(operations_data, start=1):
        env['mrp.routing.workcenter'].create({
            'name': op_name,
            'bom_id': bom.id,
            'workcenter_id': wc.id,
            'sequence': seq * 10,
            'time_cycle': 10.0,
        })

    # 4. RESET STOCK FOR TEST
    warehouse = env['stock.warehouse'].search([], limit=1)
    finished_goods_loc = env['stock.location'].search([('complete_name', 'ilike', 'Finished Goods')], limit=1)
    if not finished_goods_loc:
        finished_goods_loc = warehouse.lot_stock_id
        
    pre_production_loc = env['stock.location'].search([('complete_name', 'ilike', 'Pre-Production')], limit=1)
    if not pre_production_loc:
        pre_production_loc = warehouse.lot_stock_id

    # Reset test shirt stock in finished goods and WIP locations to 0
    quants = env['stock.quant'].search([('product_id', '=', product_shirt.id)])
    quants.write({'quantity': 0.0})
    
    # Set fabric stock in Pre-Production to 100 units
    fabric_quant = env['stock.quant'].search([
        ('product_id', '=', product_fabric.id),
        ('location_id', '=', pre_production_loc.id)
    ], limit=1)
    if fabric_quant:
        fabric_quant.write({'quantity': 100.0})
    else:
        env['stock.quant'].create({
            'product_id': product_fabric.id,
            'location_id': pre_production_loc.id,
            'quantity': 100.0
        })

    print(f"Initial Stock: {product_shirt.name} = {product_shirt.qty_available} units.")
    print(f"Initial Fabric Stock: {product_fabric.name} = {product_fabric.qty_available} units in Pre-Production.")

    # 5. RUN TEST CASE 1: NORMAL MO (5 units)
    print("\n--- RUNNING TEST CASE 1: NORMAL MO (5 units) ---")
    mo = env['mrp.production'].create({
        'product_id': product_shirt.id,
        'product_qty': 5.0,
        'bom_id': bom.id,
        'location_src_id': pre_production_loc.id,
        'location_dest_id': finished_goods_loc.id,
    })
    
    print(f"Created MO {mo.name} for {mo.product_qty} units.")
    mo.action_confirm()
    print(f"MO {mo.name} Confirmed. State: {mo.state}")
    
    # Assign components
    mo.action_assign()
    
    # Start and finish each workorder
    for wo in sorted(mo.workorder_ids, key=lambda w: (w.sequence, w.id)):
        print(f"Processing Work Order: {wo.name} (WC: {wo.workcenter_id.name})")
        wo.button_start()
        
        # If it is the QC workorder, we must handle the quality inspection creation and validation
        if 'quality' in (wo.workcenter_id.name or '').lower() or 'qc' in (wo.workcenter_id.name or '').lower():
            # Trigger inspection creation
            wo._handle_quality_inspection_creation('ready')
            inspection = env['textile.quality'].search([
                ('production_id', '=', mo.id),
                ('checkpoint', '=', 'final')
            ], limit=1)
            if inspection:
                print(f"Found draft quality inspection {inspection.id}. Validating it as PASS...")
                inspection.write({
                    'passed_qty': 5.0,
                    'failed_qty': 0.0,
                    'stitching_check': True,
                    'measurement_check': True,
                    'finishing_check': True,
                })
                inspection.action_validate()
                print(f"Quality inspection state: {inspection.state}, Result/Status: {inspection.status}")
                
        # Set qty_producing to match MO qty
        wo.write({'qty_producing': 5.0})
        wo.button_finish()
        print(f"Work Order {wo.name} Completed. State: {wo.state}")

    # Mark the MO as done
    mo.qty_producing = 5.0
    mo.button_mark_done()
    print(f"MO {mo.name} State after mark done: {mo.state}")
    
    # Check inventory distribution
    print("\nStock location inventory distribution after MO done:")
    all_locations = env['stock.location'].search([('usage', '=', 'internal')])
    for loc in all_locations:
        qty = sum(env['stock.quant'].search([
            ('product_id', '=', product_shirt.id),
            ('location_id', '=', loc.id)
        ]).mapped('quantity'))
        if qty != 0:
            print(f" - {loc.complete_name}: {qty} units")

    # 6. RUN TEST CASE 2: PARTIAL MANUFACTURING (SO = 15, Stock = 10, MO = 5)
    print("\n--- RUNNING TEST CASE 2: PARTIAL MANUFACTURING ---")
    
    # Set initial stock of product_shirt:
    # Finished Goods = 8
    # Packing WIP = 2
    print("Setting initial stock: Finished Goods = 8, Packing WIP = 2")
    
    # Reset all stock of shirt to 0 first
    env['stock.quant'].search([('product_id', '=', product_shirt.id)]).write({'quantity': 0.0})
    
    # Set Finished Goods to 8
    fg_quant = env['stock.quant'].search([
        ('product_id', '=', product_shirt.id),
        ('location_id', '=', finished_goods_loc.id)
    ], limit=1)
    if fg_quant:
        fg_quant.write({'quantity': 8.0})
    else:
        env['stock.quant'].create({
            'product_id': product_shirt.id,
            'location_id': finished_goods_loc.id,
            'quantity': 8.0
        })
        
    # Find Packing WIP location
    packing_wip_loc = packing_wc[0].wip_location_id
    if packing_wip_loc:
        pack_quant = env['stock.quant'].search([
            ('product_id', '=', product_shirt.id),
            ('location_id', '=', packing_wip_loc.id)
        ], limit=1)
        if pack_quant:
            pack_quant.write({'quantity': 2.0})
        else:
            env['stock.quant'].create({
                'product_id': product_shirt.id,
                'location_id': packing_wip_loc.id,
                'quantity': 2.0
            })
            
    # Verify Total On Hand before Sales Order
    product_shirt.invalidate_recordset()
    print(f"Total On Hand: {product_shirt.qty_available} (Finished Goods: 8.0, Packing WIP: 2.0)")

    # Create Sales Order for 15 units
    partner = env['res.partner'].search([], limit=1)
    so = env['sale.order'].create({
        'partner_id': partner.id,
        'order_line': [
            (0, 0, {
                'product_id': product_shirt.id,
                'product_uom_qty': 15.0,
                'price_unit': 100.0,
            })
        ]
    })
    print(f"Created Sales Order {so.name} for 15 units.")
    
    # Confirm Sale Order - should trigger automated MO for the shortage (15 - 10 = 5 units)
    so.action_confirm()
    print(f"Sales Order {so.name} Confirmed.")
    
    # Verify created MO
    mo_partial = env['mrp.production'].search([('origin', '=', so.name)], limit=1)
    if not mo_partial:
        # Fallback check if it maps via procurement group
        group = so.procurement_group_id
        if group:
            mo_partial = env['mrp.production'].search([('procurement_group_id', '=', group.id)], limit=1)
            
    if not mo_partial:
        print("ERROR: Manufacturing Order was not auto-created for the Sales Order!")
        return
        
    print(f"Auto-created MO {mo_partial.name} for {mo_partial.product_qty} units (expected 5.0).")
    
    # Set fabric stock in Pre-Production to ensure components can be assigned
    env['stock.quant'].create({
        'product_id': product_fabric.id,
        'location_id': pre_production_loc.id,
        'quantity': 20.0
    })
    
    # Process the MO for 5 units
    mo_partial.action_assign()
    for wo in sorted(mo_partial.workorder_ids, key=lambda w: (w.sequence, w.id)):
        print(f"Processing Work Order: {wo.name} (WC: {wo.workcenter_id.name})")
        wo.button_start()
        
        # QC Inspection validation
        if 'quality' in (wo.workcenter_id.name or '').lower() or 'qc' in (wo.workcenter_id.name or '').lower():
            wo._handle_quality_inspection_creation('ready')
            inspection = env['textile.quality'].search([
                ('production_id', '=', mo_partial.id),
                ('checkpoint', '=', 'final')
            ], limit=1)
            if inspection:
                inspection.write({
                    'passed_qty': 5.0,
                    'failed_qty': 0.0,
                    'stitching_check': True,
                    'measurement_check': True,
                    'finishing_check': True,
                })
                inspection.action_validate()
                print("Quality inspection validated as PASS.")
                
        wo.write({'qty_producing': 5.0})
        wo.button_finish()
        
    mo_partial.qty_producing = 5.0
    mo_partial.button_mark_done()
    print(f"MO {mo_partial.name} completed successfully. State: {mo_partial.state}")
    
    # Check inventory distribution after MO done
    product_shirt.invalidate_recordset()
    print(f"Total On Hand after MO Done: {product_shirt.qty_available} units.")
    for loc in all_locations:
        qty = sum(env['stock.quant'].search([
            ('product_id', '=', product_shirt.id),
            ('location_id', '=', loc.id)
        ]).mapped('quantity'))
        if qty != 0:
            print(f" - {loc.complete_name}: {qty} units")

    # Validate Customer Delivery
    picking = so.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
    if picking:
        print(f"Found delivery picking {picking.name} in state {picking.state}.")
        picking.action_assign()
        print(f"Picking availability assigned. State: {picking.state}")
        
        # Check stock move lines to ensure reservation is correct
        for move in picking.move_ids:
            print(f" - Move {move.product_id.name}: demand {move.product_uom_qty}, reserved {move.quantity}")
            
        # Validate delivery order
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.button_validate()
        print(f"Delivery picking {picking.name} validated successfully. State: {picking.state}")
    else:
        print("ERROR: No active delivery picking found for the Sales Order!")
        
    # Final stock validation
    product_shirt.invalidate_recordset()
    print(f"\nFinal Stock after delivery of 15 units:")
    print(f"Total On Hand: {product_shirt.qty_available} units.")
    for loc in all_locations:
        qty = sum(env['stock.quant'].search([
            ('product_id', '=', product_shirt.id),
            ('location_id', '=', loc.id)
        ]).mapped('quantity'))
        if qty != 0:
            print(f" - {loc.complete_name}: {qty} units")
            
    print("=================== WIP REDESIGN TESTS COMPLETED ===================")

# Execute tests if run inside Odoo shell
if 'env' in locals() or 'env' in globals():
    run_tests(env)
    import sys
    sys.exit(0)

