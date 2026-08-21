# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase

class TestMultiVariantMO(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.attr_size = cls.env['product.attribute'].create({
            'name': 'Size MVMO Test',
            'create_variant': 'always',
        })
        cls.val_s = cls.env['product.attribute.value'].create({
            'name': 'S',
            'attribute_id': cls.attr_size.id,
        })
        cls.val_m = cls.env['product.attribute.value'].create({
            'name': 'M',
            'attribute_id': cls.attr_size.id,
        })
        cls.val_l = cls.env['product.attribute.value'].create({
            'name': 'L',
            'attribute_id': cls.attr_size.id,
        })

        cls.polo_template = cls.env['product.template'].create({
            'name': 'Polo Shirt MVMO Test',
            'is_storable': True,
            'attribute_line_ids': [(0, 0, {
                'attribute_id': cls.attr_size.id,
                'value_ids': [(6, 0, [cls.val_s.id, cls.val_m.id, cls.val_l.id])]
            })]
        })

        cls.variants = cls.polo_template.product_variant_ids
        cls.var_s = cls.variants.filtered(lambda v: cls.val_s in v.product_template_attribute_value_ids.mapped('product_attribute_value_id'))
        cls.var_m = cls.variants.filtered(lambda v: cls.val_m in v.product_template_attribute_value_ids.mapped('product_attribute_value_id'))
        cls.var_l = cls.variants.filtered(lambda v: cls.val_l in v.product_template_attribute_value_ids.mapped('product_attribute_value_id'))

        cls.fabric = cls.env['product.product'].create({
            'name': 'Cotton Fabric MVMO Test',
            'is_storable': True,
            'standard_price': 10.0,
        })

        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.polo_template.id,
            'product_qty': 1.0,
            'type': 'normal',
            'bom_line_ids': [(0, 0, {
                'product_id': cls.fabric.id,
                'product_qty': 1.5,
            })]
        })

        # Provide stock of fabric for test
        warehouse = cls.env['stock.warehouse'].search([], limit=1)
        cls.env['stock.quant'].create({
            'product_id': cls.fabric.id,
            'location_id': warehouse.lot_stock_id.id,
            'quantity': 500.0,
        })

    def test_direct_multi_variant_mo(self):
        """Test creating a Multi-Variant MO directly for S (50), M (50), L (10)"""
        mo = self.env['mrp.production'].create({
            'is_multi_variant': True,
            'product_tmpl_id': self.polo_template.id,
            'bom_id': self.bom.id,
            'variant_line_ids': [
                (0, 0, {'product_id': self.var_s.id, 'product_qty': 50.0}),
                (0, 0, {'product_id': self.var_m.id, 'product_qty': 50.0}),
                (0, 0, {'product_id': self.var_l.id, 'product_qty': 10.0}),
            ]
        })

        self.assertEqual(mo.product_qty, 110.0, "Total MO quantity should equal 110")

        mo.action_confirm()
        self.assertEqual(mo.state, 'confirmed')

        mo.action_assign()

        raw_moves = mo.move_raw_ids
        self.assertTrue(raw_moves)
        fabric_move = raw_moves.filtered(lambda m: m.product_id.id == self.fabric.id)
        self.assertAlmostEqual(fabric_move.product_uom_qty, 165.0, msg="Combined Fabric requirement should equal 165m")

        finished_moves = mo.move_finished_ids
        self.assertEqual(len(finished_moves), 3, "There should be 3 separate finished moves for S, M, L")

        if mo.workorder_ids:
            for wo in mo.workorder_ids:
                self.assertEqual(len(wo.variant_line_ids), 3, "Each workorder should have 3 variant progress lines")

        # Mark finished quantities
        for move in mo.move_raw_ids:
            move.quantity = move.product_uom_qty
            move.picked = True

        for move in mo.move_finished_ids:
            move.quantity = move.product_uom_qty
            move.picked = True

        mo.button_mark_done()
        self.assertEqual(mo.state, 'done', "MO should be marked as Done")

        self.assertEqual(self.var_s.qty_available, 50.0)
        self.assertEqual(self.var_m.qty_available, 50.0)
        self.assertEqual(self.var_l.qty_available, 10.0)
