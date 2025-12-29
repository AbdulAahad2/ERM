/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";

console.log("🔧 Commission module loading...");

// Patch PosStore to intercept order creation and add commission handling
patch(PosStore.prototype, {
  async setup() {
    await super.setup(...arguments);
    console.log("=== POS Store Setup - Commission Module ===");
    console.log("POS Store:", this);
    console.log("typeof add_new_order:", typeof this.add_new_order);

    // Patch the first order when it's available
    const checkAndPatchOrder = () => {
      const order = this.get_order();
      if (order && !order._commissionPatched) {
        console.log("🎯 Found order to patch!");
        this._patchOrderCommission(order);
      }
    };

    // Check immediately if order exists
    setTimeout(checkAndPatchOrder, 100);

    // Also intercept add_new_order if it exists
    if (typeof this.add_new_order === "function") {
      const originalAddNewOrder = this.add_new_order.bind(this);
      const self = this;

      this.add_new_order = function () {
        console.log("📝 add_new_order called");
        const order = originalAddNewOrder();

        if (order && !order._commissionPatched) {
          console.log("🎯 Patching new order");
          self._patchOrderCommission(order);
        }

        return order;
      };
      console.log("✅ add_new_order intercepted");
    } else {
      console.log("⚠️ add_new_order not found");
    }

    console.log("✅ Commission module initialized");
  },

  _patchOrderCommission(order) {
    console.log("🔧 Patching order commission methods...");

    // Initialize commission fields
    order.is_commission = order.is_commission || false;
    order.commission_employee_id = order.commission_employee_id || null;
    order.commission_employee_name = order.commission_employee_name || null;

    // Get the order's prototype
    const OrderPrototype = Object.getPrototypeOf(order);

    // Store original serialize if not already stored
    if (!OrderPrototype._original_serialize) {
      OrderPrototype._original_serialize = OrderPrototype.serialize;

      // Patch serialize on the prototype (affects all orders)
      OrderPrototype.serialize = function (options) {
        console.log("📤📤📤 SERIALIZE CALLED 📤📤📤");
        console.log("  Order UUID:", this.uuid);
        console.log("  this.is_commission:", this.is_commission);
        console.log(
          "  this.commission_employee_id:",
          this.commission_employee_id,
        );
        console.log(
          "  this.commission_employee_name:",
          this.commission_employee_name,
        );

        // Call original serialize
        const json = OrderPrototype._original_serialize.call(this, options);

        // Add commission fields to the result
        json.is_commission = Boolean(this.is_commission);

        // Handle employee ID - ensure it's a number, not false
        if (
          this.commission_employee_id !== null &&
          this.commission_employee_id !== undefined &&
          this.commission_employee_id !== false &&
          this.commission_employee_id !== 0
        ) {
          json.commission_employee_id = parseInt(this.commission_employee_id);
          console.log(
            "  ✅ Set commission_employee_id to:",
            json.commission_employee_id,
          );
        } else {
          json.commission_employee_id = null;
          console.log("  ⚠️ commission_employee_id is null/false/undefined");
        }

        json.commission_employee_name = this.commission_employee_name || null;

        console.log("  Final JSON commission data:");
        console.log("    json.is_commission:", json.is_commission);
        console.log(
          "    json.commission_employee_id:",
          json.commission_employee_id,
        );
        console.log(
          "    json.commission_employee_name:",
          json.commission_employee_name,
        );
        console.log("📤📤📤 SERIALIZE COMPLETE 📤📤📤");

        return json;
      };

      console.log("✅ Order.serialize() patched successfully!");
    }

    // Store original init_from_JSON if not already stored
    if (!OrderPrototype._original_init_from_JSON) {
      OrderPrototype._original_init_from_JSON = OrderPrototype.init_from_JSON;

      OrderPrototype.init_from_JSON = function (json) {
        OrderPrototype._original_init_from_JSON.call(this, json);

        // Restore commission fields
        this.is_commission = json.is_commission || false;
        this.commission_employee_id = json.commission_employee_id || null;
        this.commission_employee_name = json.commission_employee_name || null;

        console.log("📥 Restored commission from JSON:", {
          is_commission: this.is_commission,
          commission_employee_id: this.commission_employee_id,
        });
      };

      console.log("✅ Order.init_from_JSON() patched successfully!");
    }

    order._commissionPatched = true;
  },

  set_cashier(employee) {
    super.set_cashier(...arguments);
    if (!(employee.user_id && !employee.id)) {
      const emp = this.models["hr.employee"]?.get(employee.id);
      if (emp) {
        const shouldShow =
          emp.is_commission_applicable &&
          this.config.is_use_pos_commission &&
          this.config.show_apply_commission;

        const button = document.getElementById("apply_commission");
        if (button) {
          button.style.display = shouldShow ? "" : "none";
        }
      }
    }
  },
});

console.log("✅ Commission module loaded");
