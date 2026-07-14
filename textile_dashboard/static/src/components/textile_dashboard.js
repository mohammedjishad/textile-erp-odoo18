/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

export class TextileDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        
        this.state = useState({
            data: null,
            isLoading: true,
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        this.state.isLoading = true;
        try {
            // Call the python model directly using the ORM service
            const data = await this.orm.call("textile.dashboard", "get_dashboard_data", [], {
                filters: {}
            });
            this.state.data = data;
        } catch (error) {
            console.error("Dashboard Data Load Error:", error);
        } finally {
            this.state.isLoading = false;
        }
    }

    // Drill down helper
    openAction(model, domain, title, views) {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: title,
            res_model: model,
            domain: domain,
            views: views || [[false, 'list'], [false, 'form']],
            target: 'current',
        });
    }

    // Sales Actions
    openSalesAction(type) {
        let domain = [];
        let title = '';
        if (type === 'quotations') {
            domain = [['state', 'in', ['draft', 'sent']]];
            title = 'Quotations';
        } else if (type === 'orders') {
            domain = [['state', 'in', ['sale', 'done']]];
            title = 'Sales Orders';
        } else if (type === 'delivered') {
            domain = [['state', 'in', ['sale', 'done']], ['delivery_status', '=', 'full']];
            title = 'Delivered Orders';
        }
        this.openAction('sale.order', domain, title);
    }

    // Manufacturing Actions
    openMrpAction(type) {
        let domain = [];
        let title = '';
        if (type === 'progress') {
            domain = [['state', '=', 'progress']];
            title = 'In Progress MOs';
        } else if (type === 'to_close') {
            domain = [['state', '=', 'to_close']];
            title = 'To Close MOs';
        } else if (type === 'done') {
            domain = [['state', '=', 'done']];
            title = 'Done MOs';
        }
        this.openAction('mrp.production', domain, title);
    }

    // Inventory Actions
    openInventoryAction(type) {
        let domain = [['is_storable', '=', true]];
        let title = 'Total Products';
        if (type === 'low') {
            domain.push(['qty_available', '<=', 5], ['qty_available', '>', 0]);
            title = 'Low Stock Products';
        } else if (type === 'out') {
            domain.push(['qty_available', '<=', 0]);
            title = 'Out of Stock Products';
        }
        this.openAction('product.product', domain, title, [[false, 'kanban'], [false, 'list'], [false, 'form']]);
    }

    // Quality Actions
    openQualityAction(type) {
        let domain = [];
        let title = '';
        if (type === 'pending') {
            domain = [['state', '=', 'draft']];
            title = 'Pending Inspections';
        } else if (type === 'passed') {
            domain = [['state', '=', 'done'], ['status', '=', 'pass']];
            title = 'Passed Inspections';
        } else if (type === 'failed') {
            domain = [['state', '=', 'done'], ['status', '=', 'fail']];
            title = 'Failed Inspections';
        }
        this.openAction('textile.quality', domain, title);
    }

    openWipAction(stage) {
        if (stage === 'pre') {
            this.openAction('mrp.production', [['state', '=', 'confirmed']], 'Pre-Production (Confirmed MOs)');
            return;
        }

        let domain = [['state', 'in', ['pending', 'ready', 'progress']]];
        let title = '';
        
        if (stage === 'cut') {
            domain.push(['workcenter_id.name', 'ilike', 'cut']);
            title = 'Cutting WIP';
        } else if (stage === 'stitch') {
            domain.push('|', '|', ['workcenter_id.name', 'ilike', 'stitch'], ['workcenter_id.name', 'ilike', 'sew'], ['workcenter_id.name', 'ilike', 'assembl']);
            title = 'Stitching WIP';
        } else if (stage === 'finish') {
            domain.push(['workcenter_id.name', 'ilike', 'finish']);
            title = 'Finishing WIP';
        } else if (stage === 'qc') {
            domain.push('|', '|', ['workcenter_id.name', 'ilike', 'qual'], ['workcenter_id.name', 'ilike', 'qc'], ['workcenter_id.name', 'ilike', 'check']);
            title = 'Quality Check WIP';
        } else if (stage === 'pack') {
            domain.push(['workcenter_id.name', 'ilike', 'pack']);
            title = 'Packing WIP';
        } else if (stage === 'finished_goods') {
            this.openAction('stock.quant', [['location_id.complete_name', 'ilike', 'Finished Goods'], ['quantity', '>', 0]], 'Finished Goods Stock');
            return;
        }

        this.openAction('mrp.workorder', domain, title);
    }

}

TextileDashboard.template = "textile_dashboard.DashboardTemplate";

registry.category("actions").add("textile_dashboard.management_dashboard", TextileDashboard);
