from odoo import models, fields, api, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    # ─── Custom Header Fields ───────────────────────────────────────────────

    x_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
        help='Warehouse where goods will be received',
    )
    x_is_tcs_applicable = fields.Boolean(
        string='Is TCS Applicable',
        default=False,
    )
    x_delivery_challan = fields.Char(
        string='Delivery Challan',
        help='Delivery Challan number from the vendor',
    )
    x_remarks = fields.Text(
        string='Remarks',
    )
    x_update_cost_on_save = fields.Boolean(
        string='Update Cost on Save',
        default=False,
        help='If enabled, product standard price will be updated when bill is saved',
    )

    # ─── Delivery Address Tab Fields ────────────────────────────────────────

    x_delivery_partner_id = fields.Many2one(
        'res.partner',
        string='Delivery Address',
        help='Address where the shipment will be delivered',
    )
    x_delivery_street = fields.Char(string='Street')
    x_delivery_street2 = fields.Char(string='Street2')
    x_delivery_city = fields.Char(string='City')
    x_delivery_state_id = fields.Many2one('res.country.state', string='State')
    x_delivery_zip = fields.Char(string='ZIP')
    x_delivery_country_id = fields.Many2one('res.country', string='Country')

    # ─── Handling Charges Tab Fields ────────────────────────────────────────

    x_freight_charge = fields.Float(string='Freight Charge', digits=(16, 2))
    x_loading_charge = fields.Float(string='Loading Charge', digits=(16, 2))
    x_unloading_charge = fields.Float(string='Unloading Charge', digits=(16, 2))
    x_packing_charge = fields.Float(string='Packing Charge', digits=(16, 2))
    x_other_charge = fields.Float(string='Other Charge', digits=(16, 2))
    x_handling_remarks = fields.Char(string='Handling Remarks')
    x_total_handling_charge = fields.Float(
        string='Total Handling Charge',
        compute='_compute_total_handling',
        store=True,
    )

    # ─── E-Way Bill Details Tab Fields ──────────────────────────────────────

    x_eway_bill_no = fields.Char(string='E-Way Bill No')
    x_eway_bill_date = fields.Date(string='E-Way Bill Date')
    x_eway_valid_upto = fields.Date(string='Valid Upto')
    x_transporter_name = fields.Char(string='Transporter Name')
    x_transporter_id_no = fields.Char(string='Transporter ID / GSTIN')
    x_transport_doc_no = fields.Char(string='Transport Doc No')
    x_transport_doc_date = fields.Date(string='Transport Doc Date')
    x_mode_of_transport = fields.Selection([
        ('1', 'Road'),
        ('2', 'Rail'),
        ('3', 'Air'),
        ('4', 'Ship'),
    ], string='Mode of Transport')
    x_approx_distance = fields.Float(string='Approx Distance (KM)')

    # ─── Shipment Relation ──────────────────────────────────────────────────

    x_stock_picking_ids = fields.Many2many(
        'stock.picking',
        'account_move_stock_picking_rel',
        'move_id',
        'picking_id',
        string='Shipments',
        copy=False,
    )
    x_shipment_count = fields.Integer(
        string='Shipment Count',
        compute='_compute_shipment_count',
    )

    # ─── Compute Methods ────────────────────────────────────────────────────

    @api.depends('x_freight_charge', 'x_loading_charge', 'x_unloading_charge',
                 'x_packing_charge', 'x_other_charge')
    def _compute_total_handling(self):
        for rec in self:
            rec.x_total_handling_charge = (
                rec.x_freight_charge +
                rec.x_loading_charge +
                rec.x_unloading_charge +
                rec.x_packing_charge +
                rec.x_other_charge
            )

    @api.depends('x_stock_picking_ids')
    def _compute_shipment_count(self):
        for rec in self:
            rec.x_shipment_count = len(rec.x_stock_picking_ids)

    # ─── Onchange: Delivery Partner fills address ───────────────────────────

    @api.onchange('x_delivery_partner_id')
    def _onchange_delivery_partner(self):
        if self.x_delivery_partner_id:
            partner = self.x_delivery_partner_id
            self.x_delivery_street = partner.street
            self.x_delivery_street2 = partner.street2
            self.x_delivery_city = partner.city
            self.x_delivery_state_id = partner.state_id
            self.x_delivery_zip = partner.zip
            self.x_delivery_country_id = partner.country_id

    # ─── Auto-create Shipment on Post ───────────────────────────────────────

    def action_post(self):
        res = super().action_post()
        for move in self:
            if move.move_type == 'in_invoice' and not move.x_stock_picking_ids:
                move._create_incoming_shipment()
        return res

    def _create_incoming_shipment(self):
        """Create an incoming shipment (receipt) from the vendor bill lines."""
        self.ensure_one()

        # Determine warehouse
        warehouse = self.x_warehouse_id
        if not warehouse:
            warehouse = self.env['stock.warehouse'].search(
                [('company_id', '=', self.company_id.id)], limit=1
            )
        if not warehouse:
            raise UserError(_('No warehouse found. Please set a warehouse on the bill.'))

        # Get picking type for incoming
        picking_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', warehouse.id),
            ('code', '=', 'incoming'),
        ], limit=1)
        if not picking_type:
            raise UserError(_('No incoming operation type found for warehouse: %s') % warehouse.name)

        # Determine source location (vendor) and destination (stock)
        location_src = self.env.ref('stock.stock_location_suppliers', raise_if_not_found=False)
        if not location_src:
            location_src = picking_type.default_location_src_id
        location_dest = picking_type.default_location_dest_id

        # Build move lines from invoice lines (only product lines)
        stock_move_vals = []
        for line in self.invoice_line_ids.filtered(
            lambda l: l.display_type == 'product' and l.product_id and
                      l.product_id.type in ('product', 'consu')
        ):
            stock_move_vals.append((0, 0, {
                'name': line.product_id.name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.quantity,
                'product_uom': line.product_uom_id.id or line.product_id.uom_id.id,
                'location_id': location_src.id,
                'location_dest_id': location_dest.id,
                # 'x_lot_id': line.x_lot_id.id if line.x_lot_id else False,
            }))

        if not stock_move_vals:
            return  # No storable/consumable products, skip

        picking_vals = {
            'partner_id': self.partner_id.id,
            'picking_type_id': picking_type.id,
            'location_id': location_src.id,
            'location_dest_id': location_dest.id,
            'origin': self.name,
            'move_ids': stock_move_vals,
            # 'x_vendor_bill_id': self.id,
        }

        picking = self.env['stock.picking'].with_context({}).create(picking_vals)
        picking.action_confirm()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.with_context(skip_backorder=True).button_validate()

        self.x_stock_picking_ids = [(4, picking.id)]

        # Update cost if flag is set
        if self.x_update_cost_on_save:
            self._update_product_standard_price()

        return picking

    def _update_product_standard_price(self):
        """Update standard price of products from bill lines."""
        for line in self.invoice_line_ids.filtered(
            lambda l: l.display_type == 'product' and l.product_id
        ):
            if line.product_id.categ_id.property_cost_method == 'standard':
                line.product_id.standard_price = line.price_unit

    # ─── Smart Button Action ─────────────────────────────────────────────────

    def action_view_shipments(self):
        self.ensure_one()
        if self.x_shipment_count == 1:
            return {
                'name': _('Shipment'),
                'type': 'ir.actions.act_window',
                'res_model': 'stock.picking',
                'view_mode': 'form',
                'res_id': self.x_stock_picking_ids.id,
                'target': 'current',
            }
        return {
            'name': _('Shipments'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.x_stock_picking_ids.ids)],
            'context': {'default_origin': self.name},
        }
