from odoo import fields, models,api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Technical Specifications
    installed_capacity_kwp = fields.Float(
        string='Installed Capacity (kWp)',
        help='Total Solar Array Rating (e.g., 28.61 kWp)'
    )
    inverter_rated_capacity_kwa = fields.Float(
        string='Inverter Rated Capacity (kWA)',
        help='AC Output for Grid & Load (e.g., 31 kWA)'
    )
    product_performance_guarantee_years = fields.Integer(
        string='Product Performance Guarantee (Years)',
        help='Solar Panel Output Warranty (e.g., 25 Years)'
    )

    # Financial Rationale & Projected Value
    est_annual_cost_saving = fields.Monetary(
        string='Est. Annual Cost Saving',
        currency_field='currency_id',
        help='Based on current average tariff (e.g., Rs 900,000/-)'
    )
    projected_payback_period = fields.Float(
        string='Projected Payback Period (Years)',
        help='Time to full Capital Recovery (e.g., 2.5 Years)'
    )
    value_projection_million = fields.Float(
        string='25-Year Value Projection (M)',
        help='Projected cumulative savings with escalation (e.g., Rs 85M+)'
    )

    # Guarantees and Service Level
    pv_performance_life_years = fields.Integer(
        string='PV Performance Life (Years)',
        help='(e.g., 25 Years)'
    )
    inverter_warranty_years = fields.Integer(
        string='Inverter Warranty (Years)',
        help='(e.g., 5 Years)'
    )
    battery_warranty_years = fields.Integer(
        string='Battery Warranty (Years)',
        help='(e.g., 10 Years)'
    )

    report_action_id = fields.Integer(
        string="Report Action ID",
        compute='_compute_report_action_id',
        store=False,  # Does not need to be stored in DB
    )
    default_installation_time = fields.Char(
        string="Standard Installation Time",
        default="0",  # you can even set the default here
        help="Typical installation timeframe shown on quotations"
    )
    ENERGY_INDEPENDENCE_METRIC = fields.Integer(
        string="ENERGY INDEPENDENCE",

    )

    @api.depends('name')  # Dummy dependency to ensure computation on load
    def _compute_report_action_id(self):
        # Look up the XML ID via the API and store the numeric ID
        xml_id = 'solar_quote_extention.action_report_solar_quotation'
        report_action = self.env.ref(xml_id, raise_if_not_found=False)
        for record in self:
            record.report_action_id = report_action.id if report_action else False

    def print_custom_report_action(self):
        # Call the action directly by looking up the XML ID
        report_action = self.env.ref('solar_quote_extention.action_report_solar_quotation')
        if report_action:
            # Return the action dictionary
            action = report_action.read()[0]
            action.update({'context': self.env.context})
            return action
        return False

    def get_top_cards(self):
        """Return a list of dictionaries for top summary cards."""
        return [
            {
                'label': 'INSTALLED CAPACITY (PV)',
                'value': f"{self.installed_capacity_kwp} kWp",
                'desc': 'Total Solar Array Rating',
                'color': 'blue',
            },
            {
                'label': 'TOTAL INVESTMENT (EXCL. TAX)',
                'value': f"Rs {self.amount_untaxed:,.2f} ",
                'desc': 'Fixed Quotation Amount',
            },
            {
                'label': 'PRODUCT PERFORMANCE GUARANTEE',
                'value': f"{self.product_performance_guarantee_years} Years",
                'desc': 'Solar Panel Output Warranty',
            },
            {
                'label': 'INVERTER RATED CAPACITY',
                'value': f"{self.inverter_rated_capacity_kwa} kW AC",
                'desc': 'AC Output for Load & Grid',
            },
        ]

    def get_financial_cards(self):
        """Return a list of dictionaries for financial summary cards."""
        return [
            {
                'label': 'EST. ANNUAL COST SAVING',
                'value': f"Rs {self.est_annual_cost_saving:,.2f} ",
                'desc': 'Based on current average tariff.',
            },
            {
                'label': 'PROJECTED PAYBACK PERIOD',
                'value': f"~{self.projected_payback_period} Years",
                'desc': 'Time to full Capital Recovery.',
            },
            {
                'label': '25-YEAR VALUE PROJECTION',
                'value': f"Rs {self.value_projection_million}M+",
                'desc': 'Projected cumulative savings with escalation.',
            },
            {
                'label': 'ENERGY INDEPENDENCE METRIC',
                'value': f"~{self.ENERGY_INDEPENDENCE_METRIC} %",
                'desc': 'Estimated annual self-sufficiency.',
            },
        ]