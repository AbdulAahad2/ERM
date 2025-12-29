/**@odoo-module */

import { patch } from "@web/core/utils/patch";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { EmployeeSelectionPopup } from "@pos_sales_commission/js/employee_selection_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { _t } from "@web/core/l10n/translation";

patch(ControlButtons.prototype, {
  setup() {
    super.setup(...arguments);
    this.pos = usePos();

    console.log("=== COMMISSION CONTROL BUTTON SETUP ===");
    console.log("Config:", this.pos.config);
    console.log(
      "is_use_pos_commission:",
      this.pos.config.is_use_pos_commission,
    );
    console.log(
      "show_apply_commission:",
      this.pos.config.show_apply_commission,
    );
  },

  shouldShowCommissionButton() {
    const pos = this.pos;

    if (!pos.config.is_use_pos_commission) {
      return false;
    }
    if (!pos.config.show_apply_commission) {
      return false;
    }

    return true;
  },

  async onClickApplyCommission() {
    console.log("=== Commission button clicked! ===");
    const order = this.pos.get_order();

    if (!order) {
      console.log("No order found!");
      return;
    }

    // CRITICAL: Patch the order's serialize method if not already patched
    if (!order._commissionSerializePatched) {
      console.log("🔧 Patching order serialize method NOW...");
      const OrderPrototype = Object.getPrototypeOf(order);

      if (!OrderPrototype._original_serialize) {
        OrderPrototype._original_serialize = OrderPrototype.serialize;

        OrderPrototype.serialize = function (options) {
          console.log("📤 SERIALIZE (patched)");
          const json = OrderPrototype._original_serialize.call(this, options);

          // Add commission fields
          json.is_commission = Boolean(this.is_commission);
          json.commission_employee_id =
            this.commission_employee_id !== null &&
            this.commission_employee_id !== undefined &&
            this.commission_employee_id !== false &&
            this.commission_employee_id !== 0
              ? parseInt(this.commission_employee_id)
              : null;
          json.commission_employee_name = this.commission_employee_name || null;

          console.log("  Commission in JSON:", {
            is_commission: json.is_commission,
            commission_employee_id: json.commission_employee_id,
            commission_employee_name: json.commission_employee_name,
          });

          return json;
        };

        console.log("✅ Order.serialize() patched!");
      }

      order._commissionSerializePatched = true;
    }

    console.log("Current order:", order);
    console.log("Order properties:", {
      uuid: order.uuid,
      server_id: order.server_id,
      id: order.id,
      is_commission: order.is_commission,
      commission_employee_id: order.commission_employee_id,
      commission_employee_name: order.commission_employee_name,
    });

    // If commission is already applied, toggle it off
    if (order.is_commission && order.commission_employee_id) {
      console.log("Removing commission from order...");
      order.is_commission = false;
      order.commission_employee_id = null;
      order.commission_employee_name = null;
      console.log("✓ Commission removed");
      this.render();
      return;
    }

    // Show employee selection popup
    console.log("Opening employee selection popup...");
    const payload = await makeAwaitable(this.dialog, EmployeeSelectionPopup, {
      title: _t("Select Employee for Commission"),
    });

    console.log("Popup result:", payload);

    if (payload && payload.employeeId) {
      console.log("Setting commission on order...");
      console.log(
        "Employee ID to set:",
        payload.employeeId,
        "Type:",
        typeof payload.employeeId,
      );

      // Set commission data on the order
      order.is_commission = true;
      order.commission_employee_id = parseInt(payload.employeeId);
      order.commission_employee_name = payload.employee.name;

      console.log("=== Commission Applied ===");
      console.log("Order object:", order);
      console.log("Employee ID (as number):", order.commission_employee_id);
      console.log("Type check:", typeof order.commission_employee_id);
      console.log("Employee Name:", order.commission_employee_name);
      console.log("is_commission:", order.is_commission);

      // Force UI update
      this.render();

      // Test serialization methods immediately
      console.log("=== Testing Serialization ===");

      // Test serialize
      try {
        console.log("Testing serialize()...");
        const serialized = order.serialize();
        console.log("Serialized commission data:", {
          is_commission: serialized.is_commission,
          commission_employee_id: serialized.commission_employee_id,
          commission_employee_name: serialized.commission_employee_name,
        });
      } catch (e) {
        console.error("Error calling serialize:", e);
      }
    } else {
      console.log("Popup cancelled or invalid payload");
    }
  },
});
