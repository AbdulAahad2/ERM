from odoo import http
from odoo.http import request
from odoo.tools.safe_eval import safe_eval
import logging

_logger = logging.getLogger(__name__)

class AccountMoveDashboardController(http.Controller):
    @http.route('/vet_test/invoice_dashboard', type='json', auth='user')
    def invoice_dashboard(self, domain, **kwargs):
        """
        Controller to fetch invoice dashboard data and render the banner.
        """
        try:
            # Evaluate the domain safely
            invoice_domain = safe_eval(domain or '[]')
            _logger.debug("Invoice dashboard domain: %s", invoice_domain)
            
            # Get totals using the model's helper method
            totals = request.env['account.move']._get_dashboard_totals(invoice_domain)
            _logger.debug("Dashboard totals: %s", totals)
            
            # Render the QWeb template
            return request.env['ir.ui.view']._render_template(
                "vet_test.invoice_dashboard_banner",
                totals
            )
        except Exception as e:
            _logger.error("Error in invoice_dashboard controller: %s", str(e))
            return {'html': '<div class="alert alert-danger">Error loading dashboard totals</div>'}
