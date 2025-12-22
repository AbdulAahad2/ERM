import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    Pre-migration script to add branch_code column to res_company table.
    This runs BEFORE the model is loaded, preventing the UndefinedColumn error.
    """
    _logger.info("Running pre-migration for vet_test module version %s", version)
    
    # Check if the column already exists
    cr.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='res_company' 
        AND column_name='branch_code'
    """)
    
    if not cr.fetchone():
        _logger.info("Adding branch_code column to res_company table")
        
        # Add the column with appropriate type and constraints
        cr.execute("""
            ALTER TABLE res_company 
            ADD COLUMN branch_code VARCHAR(10)
        """)
        
        # Add the unique constraint
        cr.execute("""
            CREATE UNIQUE INDEX res_company_branch_code_unique 
            ON res_company(branch_code) 
            WHERE branch_code IS NOT NULL
        """)
        
        _logger.info("Successfully added branch_code column to res_company")
    else:
        _logger.info("branch_code column already exists in res_company, skipping")
    
    # Commit the changes
    cr.commit()
