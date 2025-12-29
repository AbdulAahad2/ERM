/** @odoo-module */
import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class EmployeeSelectionPopup extends Component {
  static template = "pos_sales_commission.EmployeeSelectionPopup";
  static components = { Dialog };

  setup() {
    this.pos = usePos();
    this.orm = useService("orm");

    this.state = useState({
      selectedEmployeeId: null,
      searchTerm: "",
      employees: [],
      loading: true,
    });

    // Load employees when popup opens
    onWillStart(async () => {
      await this.loadEmployees();
    });
  }

  async loadEmployees() {
    try {
      console.log("Loading employees via RPC...");
      console.log("Current company ID:", this.pos.company.id);

      // Fetch commission-applicable veterinarian employees from same company
      const employees = await this.orm.searchRead(
        "hr.employee",
        [
          ["is_commission_applicable", "=", true],
          ["is_veterinarian", "=", true],
          ["company_id", "=", this.pos.company.id],
        ],
        [
          "id",
          "name",
          "is_commission_applicable",
          "is_veterinarian",
          "job_title",
          "company_id",
        ],
      );

      console.log("Loaded employees:", employees);
      console.log("Total eligible employees:", employees.length);

      this.state.employees = employees;
      this.state.loading = false;
    } catch (error) {
      console.error("Error loading employees:", error);
      this.state.employees = [];
      this.state.loading = false;
    }
  }

  get eligibleEmployees() {
    console.log("Getting eligible employees from state...");
    let employees = this.state.employees || [];

    console.log("Total employees:", employees.length);

    // Apply search filter
    if (this.state.searchTerm) {
      const searchLower = this.state.searchTerm.toLowerCase();
      const searchFiltered = employees.filter((emp) =>
        emp.name?.toLowerCase().includes(searchLower),
      );
      console.log("After search filter:", searchFiltered.length);
      return searchFiltered;
    }

    return employees;
  }

  selectEmployee(employeeId) {
    console.log("Selected employee ID:", employeeId);
    this.state.selectedEmployeeId = employeeId;
  }

  isSelected(employeeId) {
    return this.state.selectedEmployeeId === employeeId;
  }

  async confirm() {
    if (!this.state.selectedEmployeeId) {
      console.log("No employee selected");
      return;
    }

    // Find the selected employee
    const selectedEmployee = this.state.employees.find(
      (emp) => emp.id === this.state.selectedEmployeeId,
    );

    console.log("Selected employee:", selectedEmployee);

    if (selectedEmployee) {
      this.props.getPayload({
        employee: selectedEmployee,
        employeeId: this.state.selectedEmployeeId,
      });
      this.props.close();
    }
  }

  cancel() {
    this.props.close();
  }
}
