/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";

patch(PosStore.prototype, {
  async setup() {
    await super.setup(...arguments);

    console.log("=== POS STORE DEBUG ===");
    console.log("All POS data:", this);
    console.log("Models:", this.models);
    console.log("Data:", this.data);

    // Check all possible employee locations
    if (this.models) {
      console.log("Available models:", Object.keys(this.models));
      if (this.models["hr.employee"]) {
        console.log("hr.employee model found!");
        const employees = this.models["hr.employee"].getAll();
        console.log("Employees:", employees);
      }
    }

    if (this.employees) {
      console.log("this.employees:", this.employees);
    }

    if (this.hr_employee) {
      console.log("this.hr_employee:", this.hr_employee);
    }
  },
});
