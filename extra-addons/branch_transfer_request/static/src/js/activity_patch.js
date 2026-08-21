/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ActivityRecord } from "@mail/activity/activity_record";

patch(ActivityRecord.prototype, {
    get filteredActivities() {
        const currentUserId = this.env.services.user.userId;
        return this.activities.filter(
            (activity) => activity.user_id[0] === currentUserId
        );
    }
});