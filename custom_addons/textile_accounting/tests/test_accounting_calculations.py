from odoo.tests.common import TransactionCase

class TestTextileAccounting(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super(TestTextileAccounting, cls).setUpClass()

        # 1. Setup Company Config
        cls.company = cls.env.company
        cls.company.write({
            'textile_overhead_rate': 10.0,
            'textile_factory_overhead_rate': 5.0,
            'textile_waste_rate': 2.0,
        })

        # 2. Setup Category with Cost Bucket
        cls.category = cls.env['product.category'].create({
            'name': 'Test Fabric Category',
            'textile_cost_bucket': 'fabric',
        })

        # 3. Setup Products
        cls.component = cls.env['product.product'].create({
            'name': 'Cotton Fabric Raw',
            'type': 'consu',
            'categ_id': cls.category.id,
            'standard_price': 50.0,
        })
        cls.finished_product = cls.env['product.product'].create({
            'name': 'Garment T-Shirt',
            'type': 'consu',
            'standard_price': 150.0,
            'list_price': 250.0,
        })

        # 4. Setup Workcenter (reusing fields from textile_mrp)
        cls.workcenter = cls.env['mrp.workcenter'].create({
            'name': 'Cutting & Sewing Workcenter',
            'costs_hour_labor': 12.0,
            'costs_hour_machine': 18.0,
        })

        # 5. Setup BoM
        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.finished_product.product_tmpl_id.id,
            'product_qty': 1.0,
            'type': 'normal',
            'bom_line_ids': [
                (0, 0, {
                    'product_id': cls.component.id,
                    'product_qty': 2.0,
                })
            ],
            'operation_ids': [
                (0, 0, {
                    'name': 'Sewing Operation',
                    'workcenter_id': cls.workcenter.id,
                    'time_cycle': 60.0, # 1 hour
                })
            ]
        })

        # 6. Setup Customer/Partner
        cls.customer = cls.env['res.partner'].create({
            'name': 'Textile Global Buyer',
        })

    def test_01_mfg_costs_calculations(self):
        """ Test MRP Production cost sheet calculations using textile_mrp costing fields """
        mo = self.env['mrp.production'].create({
            'product_id': self.finished_product.id,
            'bom_id': self.bom.id,
            'product_qty': 1.0,
        })
        mo.action_confirm()

        # Set workorder duration to 60 minutes and mark workorders active
        workorder = mo.workorder_ids[0]
        workorder.duration = 60.0
        workorder.state = 'done'

        # Simulate component consumption and mark moves done so textile_mrp detects them
        move = mo.move_raw_ids[0]
        move.write({
            'quantity': 2.0,
            'state': 'done',
        })

        # Force textile_mrp computation first
        mo._compute_textile_costs()

        # Check raw costs computed by textile_mrp
        self.assertEqual(mo.fabric_cost, 100.0)
        self.assertEqual(mo.labor_cost, 12.0)
        self.assertEqual(mo.machine_cost, 18.0)

        # Force textile_accounting cost sheet computation
        mo._compute_mfg_costs()

        # Material cost: 2 qty * 50 standard_price = 100.0
        self.assertEqual(mo.material_cost, 100.0)
        # Labour cost: 1 hour * 12.0 rate = 12.0
        self.assertEqual(mo.labour_cost, 12.0)
        # Machine cost: 1 hour * 18.0 rate = 18.0
        self.assertEqual(mo.machine_cost, 18.0)
        # Overhead cost: (100 + 12 + 18) * 10% = 13.0
        self.assertEqual(mo.overhead_cost, 13.0)
        # Total cost: 100 + 12 + 18 + 13 = 143.0
        self.assertEqual(mo.total_manufacturing_cost, 143.0)
        # Manufacturing value: 1 qty * 150 standard_price = 150.0
        self.assertEqual(mo.manufacturing_value, 150.0)
        # Profit: 150 - 143 = 7.0
        self.assertEqual(mo.manufacturing_profit, 7.0)

    def test_02_sale_order_profitability(self):
        """ Test Sales Order profitability and margins """
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [
                (0, 0, {
                    'product_id': self.finished_product.id,
                    'product_uom_qty': 1.0,
                    'price_unit': 250.0,
                })
            ]
        })
        so.action_confirm()

        # Check Sale Order profitability fallback to standard_price
        self.assertEqual(so.manufacturing_cost, 150.0)
        self.assertEqual(so.gross_profit, 100.0)
        self.assertEqual(so.margin_percent, 0.4)

    def test_03_purchased_product_profitability(self):
        """ Test profitability and cost calculations for a purchased product """
        # Create a purchased product
        purchased_product = self.env['product.product'].create({
            'name': 'Allen Solly Formal Shirt Test',
            'type': 'consu',
            'standard_price': 0.0,  # Starts at 0 cost
            'list_price': 2000.0,
        })

        # Create a Purchase Order for this product to set purchase cost
        po = self.env['purchase.order'].create({
            'partner_id': self.customer.id,
            'order_line': [
                (0, 0, {
                    'product_id': purchased_product.id,
                    'product_qty': 10.0,
                    'price_unit': 1200.0,
                })
            ]
        })
        po.button_confirm()

        # Create a Sale Order for this product
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [
                (0, 0, {
                    'product_id': purchased_product.id,
                    'product_uom_qty': 2.0,
                    'price_unit': 2000.0,
                })
            ]
        })
        so.action_confirm()

        # Cost should pull from PO: 1200.0 instead of standard_price 0.0
        # Manufacturing cost (COGS): 1200.0 * 2 = 2400.0
        self.assertEqual(so.manufacturing_cost, 2400.0)
        # Gross profit: 4000.0 - 2400.0 = 1600.0
        self.assertEqual(so.gross_profit, 1600.0)
        # Margin %: (1600 / 4000) = 40.0%
        self.assertEqual(so.margin_percent, 0.4)

        # Force product profitability calculation
        purchased_product._compute_product_profitability()
        # Average cost: 1200.0
        self.assertEqual(purchased_product.avg_manufacturing_cost, 1200.0)
        # Total sold: 2.0
        self.assertEqual(purchased_product.total_sold, 2.0)

    def test_04_vendor_pricelist_profitability(self):
        """ Test profitability and cost calculations when cost is pulled from Vendor Pricelist (supplierinfo) """
        # Create a product with vendor pricelist
        pricelist_product = self.env['product.product'].create({
            'name': 'Allen Solly Formal Shirt Test Vendor',
            'type': 'consu',
            'standard_price': 0.0,
            'list_price': 2299.0,
            'seller_ids': [
                (0, 0, {
                    'partner_id': self.customer.id,
                    'price': 1700.0,
                    'min_qty': 1.0,
                })
            ]
        })

        # Create a Sale Order for this product
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [
                (0, 0, {
                    'product_id': pricelist_product.id,
                    'product_uom_qty': 1.0,
                    'price_unit': 2299.0,
                })
            ]
        })
        so.action_confirm()

        # Cost should pull from Vendor Pricelist: 1700.0
        self.assertEqual(so.order_line[0].purchase_price, 1700.0)
        self.assertEqual(so.manufacturing_cost, 1700.0)
        # Gross profit: 2299.0 - 1700.0 = 599.0
        self.assertEqual(so.gross_profit, 599.0)


