# Textile ERP for Odoo 18 Community

A comprehensive, production-grade suite of custom Odoo 18 modules tailored specifically for the textile and garment manufacturing industry. This suite extends standard Odoo capabilities in **Sales, Manufacturing (MRP), Quality Control, Interactive Dashboards, and Financial Accounting** to support fabric-specific workflows, shortage-based production, rigorous quality locks, and detailed yield/profitability tracking.

---

## 🚀 Module Directory

This repository contains 5 highly decoupled custom modules that inherit and extend standard Odoo 18 features:

### 1. 📦 Textile Sales (`textile_sales`)
Implements **Shortage-Based Manufacturing** to prevent overproduction and optimize stock levels:
- **Shortage Check**: On confirming a Sales Order (SO), the module dynamically calculates the stock shortage (`ordered quantity - available stock`).
- **Shortage-Only MO**: Creates or updates Manufacturing Orders (MOs) *only* for the shortfall quantity.
- **Stock Reservation**: If stock is fully available, it cancels/deletes the draft MO and routes reservations directly from warehouse stock (`make_to_stock`).

### 2. 🧵 Textile MRP (`textile_mrp`)
Enables fabric-specific tracking, waste estimation, and material costing:
- **Textile Cost Buckets**: Maps product categories to specific material classifications (`fabric`, `thread`, `accessories`, `packaging`).
- **Yield & Consumption**: Tracks `Issued Fabric`, `Consumed Fabric`, `Returned Fabric`, and `Waste %` dynamically using Scrap Orders.
- **Routing & Workcenter Costing**: Automatically calculates direct Labor and Machine costs by matching workorder runtimes with workcenter hourly rates.
- **WIP Stage Tracker**: A live, visual progress bar showing quantities currently routing through *Cutting, Stitching, Quality, and Packing*.

### 3. 🛡️ Textile Quality (`textile_quality`)
Enforces strict quality inspection checkpoints and guards manufacturing completion:
- **Inspections & Defect Tracking**: Conducts checks on Stitching, Measurement, and Finishing with automatic scrap order creation for defective units.
- **Operation Gates**: Prevents workorders from finishing and MOs from validation unless a Final Quality Inspection is recorded and marked as **Pass**.
- **Delivery Protection**: Blocks the validation of Outgoing Deliveries if the linked manufacturing lot failed inspection or has no inspection records.
- **Automatic Lot Inheritance**: Automates raw material trace lines by copying component Lot numbers to the MO raw materials list upon internal picking validation.

### 4. 📊 Textile Dashboard (`textile_dashboard`)
A custom management control screen built on Odoo's OWL framework:
- **KPI Dashboards**: Highlights metrics across Sales, Purchases, Inventory, Quality Checks, and Invoicing.
- **WIP Analytics**: Shows real-time counts of products currently in Cutting, Stitching, Quality Control, and Finished Goods locations.

### 5. 💰 Textile Accounting (`textile_accounting`)
Integrates operational costs directly into the financial ledger:
- **Cost Sheets**: Compiles comprehensive Material, Labor, Machine, and Overhead expenses on Manufacturing Orders.
- **Sales Profitability**: Overrides native Odoo Cost (`purchase_price`) fields on Sales Order lines to dynamically fetch actual MO costs, Purchase Order costs, or Vendor Pricelist (`product.supplierinfo`) entries.
- **Analytics Dashboards**: Visualizes Product Profitability and Customer Profitability margins.
- **360-Degree Lot Traceability**: A comprehensive grid on the Lot/Serial form linking the Lot to all its related MOs, SOs, Pickings, Quality Checks, and Invoices.

---

## My Contributions

- Developed Textile Manufacturing workflows
- Implemented shortage-based Manufacturing Order generation
- Extended Odoo Manufacturing and Sales modules
- Developed Production Costing
- Implemented Quality Inspection workflows
- Built Textile Dashboard
- Integrated Accounting with Manufacturing Costs

---


## 🛠️ Tech Stack & Requirements

- **Platform**: Odoo 18 (Community or Enterprise)
- **Framework**: Python 3.10+, PostgreSQL, OWL (Odoo Web Library), JavaScript (ES6+), XML
- **Dependencies**: `sale_management`, `mrp`, `stock`, `purchase`, `account`

---

## ⚙️ Installation & Configuration

1. Clone this repository into your custom addons directory:
   ```bash
   git clone https://github.com/jishad1919/textile-erp-odoo18.git
   ```
2. Add the path to your Odoo configuration file (`odoo.conf`):
   ```ini
   addons_path = /path/to/odoo/addons, /path/to/your/custom_addons
   ```
3. Restart your Odoo server.
4. Activate Developer Mode, navigate to **Apps** $\rightarrow$ **Update Apps List**.
5. Search for the modules (`textile_sales`, `textile_mrp`, `textile_quality`, `textile_dashboard`, `textile_accounting`) and click **Install**.

---

## 🛡️ License

This project is licensed under the LGPL-3 License.

## Author

**Mohammed Jishad**

- Odoo 18 Developer
- Textile ERP Development
- Python | PostgreSQL | XML | OWL
