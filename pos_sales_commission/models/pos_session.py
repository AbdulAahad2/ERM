from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def _loader_params_res_users(self):
        result = super()._loader_params_res_users()
        result["search_params"]["fields"].append("is_commission_applicable")
        return result

    def _loader_params_hr_employee(self):
        result = super()._loader_params_hr_employee()
        # Add is_veterinarian field
        result["search_params"]["fields"].extend([
            "is_commission_applicable", 
            "job_title",
            "is_veterinarian",
            "company_id"
        ])
        # Remove domain filter to load ALL employees, we'll filter in frontend
        if "domain" in result["search_params"]:
            result["search_params"]["domain"] = []
        return result
    
    def _pos_data_process(self, loaded_data):
        """Add commission employees to POS data"""
        super()._pos_data_process(loaded_data)
        
        # Get current session's company
        current_company_id = self.config_id.company_id.id if self.config_id else self.env.company.id
        
        # Load commission-applicable veterinarian employees from same company
        commission_employees = self.env['hr.employee'].search_read(
            domain=[
                ('is_commission_applicable', '=', True),
                ('is_veterinarian', '=', True),
                ('company_id', '=', current_company_id)
            ],
            fields=['name', 'id', 'is_commission_applicable', 'job_title', 'is_veterinarian', 'company_id']
        )
        
        # Add to loaded data
        loaded_data['commission_employees'] = commission_employees
        
    def _pos_ui_models_to_load(self):
        """Ensure hr.employee is in the models to load"""
        result = super()._pos_ui_models_to_load()
        # Make sure hr.employee is included
        if 'hr.employee' not in result:
            result.append('hr.employee')
        return result
