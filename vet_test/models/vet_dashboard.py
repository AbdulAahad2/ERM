from datetime import datetime, timedelta

from odoo import api, fields, models


class VetDashboard(models.Model):
    _name = "vet.dashboard"
    _description = "Vet Dashboard"
    _auto = False  # This is a SQL view, not a regular table

    name = fields.Char(string="Metric Name")
    value = fields.Integer(string="Count")
    value_secondary = fields.Float(string="Secondary Value")
    color = fields.Selection([
        ('primary', 'Blue'),
        ('success', 'Green'),
        ('warning', 'Yellow'),
        ('danger', 'Red'),
        ('info', 'Cyan'),
        ('purple', 'Purple'),
        ('graph', 'Graph Card'),
        ('chart', 'Chart Card'),
        ('stats', 'Stats Card')
    ], string="Card Color")
    pending_count = fields.Integer(string="Pending")
    paid_count = fields.Integer(string="Paid")
    icon = fields.Char(string="Icon Class")
    url = fields.Char(compute='_compute_url', string="Action URL")
    card_type = fields.Char(string="Card Type")
    percentage_change = fields.Float(string="Change %")
    subtitle = fields.Char(string="Subtitle")
    trend = fields.Selection([
        ('up', 'Increasing'),
        ('down', 'Decreasing'),
        ('stable', 'Stable')
    ], string="Trend")
    extra_info = fields.Char(string="Additional Info")
    company_id = fields.Many2one('res.company', string='Company')

    @api.depends('card_type')
    def _compute_url(self):
        """Dynamically compute URLs based on XML IDs"""
        action_mapping = {
            'animals': 'vet_test.action_vet_animal',
            'owners': 'vet_test.action_vet_animal_owner',
            'doctors': 'vet_test.action_vet_animal_doctor',
            'invoices': 'vet_test.action_invoices_graph',
            'visits_today': 'vet_test.action_vet_animal_visit',
            'visits_week': 'vet_test.action_vet_animal_visit',
            'revenue': 'vet_test.action_account_move',
            'species': 'vet_test.action_vet_animal',
            'services': 'vet_test.action_vet_service',
            'unpaid': 'vet_test.action_account_move',
        }
        
        for record in self:
            if record.card_type and record.card_type in action_mapping:
                try:
                    action = self.env.ref(action_mapping[record.card_type])
                    record.url = f'/web#action={action.id}'
                except ValueError:
                    record.url = '#'
            else:
                record.url = '#'

    def _compute_dashboard_values(self, record_data):
        """Compute actual dashboard values for current company"""
        company_id = self.env.company.id
        card_type = record_data.get('card_type')
        
        if card_type == 'animals':
            record_data['value'] = self.env['vet.animal'].search_count([('active', '=', True)])
            new_count = self.env['vet.animal'].search_count([
                ('active', '=', True),
                ('create_date', '>=', fields.Datetime.now() - timedelta(days=30))
            ])
            record_data['extra_info'] = f"{new_count} added this month"
            
        elif card_type == 'owners':
            record_data['value'] = self.env['vet.animal.owner'].search_count([('active', '=', True)])
            new_count = self.env['vet.animal.owner'].search_count([
                ('active', '=', True),
                ('create_date', '>=', fields.Datetime.now() - timedelta(days=30))
            ])
            record_data['extra_info'] = f"{new_count} new clients"
            
        elif card_type == 'doctors':
            record_data['value'] = self.env['vet.animal.doctor'].search_count([
                ('active', '=', True),
                ('company_id', '=', company_id)
            ])
            record_data['extra_info'] = 'Available for consultations'
            
        elif card_type == 'visits_today':
            record_data['value'] = self.env['vet.animal.visit'].search_count([
                ('date', '>=', fields.Date.today()),
                ('date', '<', fields.Date.today() + timedelta(days=1)),
                ('company_id', '=', company_id)
            ])
            pending = self.env['vet.animal.visit'].search_count([
                ('state', '=', 'draft'),
                ('company_id', '=', company_id)
            ])
            record_data['extra_info'] = f"{pending} pending visits"
            
        elif card_type == 'visits_week':
            week_ago = fields.Datetime.now() - timedelta(days=7)
            record_data['value'] = self.env['vet.animal.visit'].search_count([
                ('date', '>=', week_ago),
                ('company_id', '=', company_id)
            ])
            completed = self.env['vet.animal.visit'].search_count([
                ('state', '=', 'done'),
                ('company_id', '=', company_id)
            ])
            record_data['extra_info'] = f"{completed} completed"
            
        elif card_type == 'invoices':
            invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('company_id', '=', company_id)
            ])
            record_data['value'] = len(invoices)
            record_data['value_secondary'] = sum(inv.amount_total for inv in invoices)
            record_data['pending_count'] = len([inv for inv in invoices if inv.payment_state in ('not_paid', 'partial')])
            record_data['paid_count'] = len([inv for inv in invoices if inv.payment_state == 'paid'])
            record_data['extra_info'] = 'Click for detailed analysis'
            
        elif card_type == 'species':
            animals = self.env['vet.animal'].search([('species', '!=', False)])
            species_set = set(animals.mapped('species'))
            record_data['value'] = len(species_set)
            record_data['pending_count'] = self.env['vet.animal'].search_count([('species', '=', 'canine')])
            record_data['paid_count'] = self.env['vet.animal'].search_count([('species', '=', 'feline')])
            record_data['extra_info'] = 'Canine & Feline tracked'
            
        elif card_type == 'services':
            record_data['value'] = self.env['vet.service'].search_count([])
            record_data['pending_count'] = self.env['vet.service'].search_count([('service_type', '=', 'vaccine')])
            record_data['paid_count'] = self.env['vet.service'].search_count([('service_type', '=', 'service')])
            record_data['extra_info'] = 'Vaccines & Services'
            
        elif card_type == 'unpaid':
            unpaid_invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('payment_state', 'in', ['not_paid', 'partial']),
                ('company_id', '=', company_id)
            ])
            record_data['value'] = len(unpaid_invoices)
            record_data['value_secondary'] = sum(inv.amount_residual for inv in unpaid_invoices)
            record_data['extra_info'] = 'Requires attention'
        
        return record_data

    def read(self, fields=None, load='_classic_read'):
        """Override read to compute values dynamically"""
        result = super(VetDashboard, self).read(fields=fields, load=load)
        
        # Compute actual values for each record
        for record_data in result:
            self._compute_dashboard_values(record_data)
        
        return result

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None):
        """Override search_read to compute values dynamically for current company"""
        # Get base records
        records = super(VetDashboard, self).search_read(domain=domain, fields=fields, offset=offset, limit=limit, order=order)
        
        # Compute actual values for each record
        for record in records:
            self._compute_dashboard_values(record)
        
        return records

    def init(self):
        """Create comprehensive dashboard with veterinary-specific metrics"""
        cr = self._cr
        table = self._table
        
        # Create a simple view with static IDs - filtering will happen in read/search_read
        cr.execute(f"DROP VIEW IF EXISTS {table} CASCADE")
        cr.execute(f"""
            CREATE OR REPLACE VIEW {table} AS (
                SELECT 
                    1 AS id,
                    'Total Animals' AS name,
                    'Registered in system' AS subtitle,
                    0 AS value,
                    0.0 AS value_secondary,
                    'primary' AS color,
                    'fa-paw' AS icon,
                    'animals' AS card_type,
                    0 AS pending_count,
                    0 AS paid_count,
                    NULL::text AS trend,
                    '' AS extra_info,
                    0.0 AS percentage_change,
                    NULL::integer AS company_id
                    
                UNION ALL SELECT 2, 'Pet Owners', 'Active clients', 0, 0.0, 'success', 'fa-users', 'owners', 0, 0, NULL, '', 0.0, NULL
                UNION ALL SELECT 3, 'Veterinarians', 'Medical staff on duty', 0, 0.0, 'info', 'fa-user-md', 'doctors', 0, 0, NULL, '', 0.0, NULL
                UNION ALL SELECT 4, 'Visits Today', 'Appointments completed today', 0, 0.0, 'warning', 'fa-calendar', 'visits_today', 0, 0, NULL, '', 0.0, NULL
                UNION ALL SELECT 5, 'Weekly Visits', 'Last 7 days activity', 0, 0.0, 'purple', 'fa-calendar', 'visits_week', 0, 0, NULL, '', 0.0, NULL
                UNION ALL SELECT 6, 'Outstanding Balance', 'Unpaid invoices total', 0, 0.0, 'danger', 'fa-exclamation-triangle', 'unpaid', 0, 0, NULL, '', 0.0, NULL
                UNION ALL SELECT 7, 'Invoice Overview', 'Payment status breakdown', 0, 0.0, 'graph', 'fa-file', 'invoices', 0, 0, NULL, '', 0.0, NULL
                UNION ALL SELECT 8, 'Species Diversity', 'Animal types registered', 0, 0.0, 'chart', 'fa-paw', 'species', 0, 0, NULL, '', 0.0, NULL
                UNION ALL SELECT 9, 'Available Services', 'Medical services & vaccines', 0, 0.0, 'stats', 'fa-archive', 'services', 0, 0, NULL, '', 0.0, NULL
            )
        """)


class VetDashboardReport(models.AbstractModel):
    _name = 'report.vet_test.vet_dashboard_report'
    _description = 'Vet Dashboard Report'

    @api.model
    def get_dashboard_data(self):
        """Get additional dashboard data for advanced analytics - filtered by company"""
        today = fields.Date.today()
        first_day_month = today.replace(day=1)
        company_id = self.env.company.id
        
        return {
            'recent_visits': self._get_recent_visits(company_id),
            'top_species': self._get_top_species(company_id),
            'monthly_revenue': self._get_monthly_revenue(company_id),
            'doctor_performance': self._get_doctor_performance(company_id),
            'popular_services': self._get_popular_services(company_id),
        }
    
    def _get_recent_visits(self, company_id):
        """Get last 5 visits for current company"""
        visits = self.env['vet.animal.visit'].search(
            [('company_id', '=', company_id)], 
            limit=5, 
            order='date desc'
        )
        return [{
            'name': v.name,
            'animal': v.animal_id.name,
            'owner': v.owner_id.name,
            'date': v.date,
            'state': v.state,
        } for v in visits]
    
    def _get_top_species(self, company_id):
        """Get top 5 species by count"""
        query = """
            SELECT species, COUNT(*) as count
            FROM vet_animal
            WHERE species IS NOT NULL AND active = true 
            GROUP BY species
            ORDER BY count DESC
            LIMIT 5
        """
        self.env.cr.execute(query)
        return self.env.cr.dictfetchall()
    
    def _get_monthly_revenue(self, company_id):
        """Get revenue for last 6 months for current company"""
        query = """
            SELECT 
                TO_CHAR(invoice_date, 'Mon YYYY') as month,
                SUM(amount_total) as revenue,
                COUNT(*) as invoice_count
            FROM account_move
            WHERE move_type = 'out_invoice'
                AND payment_state = 'paid'
                AND invoice_date >= CURRENT_DATE - INTERVAL '6 months'
                AND company_id = %s
            GROUP BY TO_CHAR(invoice_date, 'Mon YYYY'), DATE_TRUNC('month', invoice_date)
            ORDER BY DATE_TRUNC('month', invoice_date) DESC
            LIMIT 6
        """
        self.env.cr.execute(query, (company_id,))
        return self.env.cr.dictfetchall()
    
    def _get_doctor_performance(self, company_id):
        """Get visit count by doctor for current company"""
        query = """
            SELECT 
                d.name as doctor_name,
                COUNT(v.id) as visit_count
            FROM vet_animal_doctor d
            LEFT JOIN vet_animal_visit v ON v.doctor_id = d.id
            WHERE d.active = true
                AND d.company_id = %s
            GROUP BY d.id, d.name
            ORDER BY visit_count DESC
            LIMIT 5
        """
        self.env.cr.execute(query, (company_id,))
        return self.env.cr.dictfetchall()
    
    def _get_popular_services(self, company_id):
        """Get most used services"""
        query = """
            SELECT 
                s.name as service_name,
                s.service_type,
                COUNT(vl.id) as usage_count,
                SUM(vl.subtotal) as total_revenue
            FROM vet_service s
            LEFT JOIN vet_animal_visit_line vl ON vl.service_id = s.id
            GROUP BY s.id, s.name, s.service_type
            ORDER BY usage_count DESC
            LIMIT 5
        """
        self.env.cr.execute(query)
        return self.env.cr.dictfetchall()
