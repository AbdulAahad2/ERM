import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    Pre-migration script to add custom columns to database tables.
    This runs BEFORE the model is loaded, preventing the UndefinedColumn error.
    """
    _logger.info("Running pre-migration for vet_test module version %s", version)
    
    # Add branch_code column to res_company
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
    
    # Add is_vet_owner column to res_partner
    cr.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='res_partner' 
        AND column_name='is_vet_owner'
    """)
    
    if not cr.fetchone():
        _logger.info("Adding is_vet_owner column to res_partner table")
        
        # Add the column with appropriate type and default value
        cr.execute("""
            ALTER TABLE res_partner 
            ADD COLUMN is_vet_owner BOOLEAN DEFAULT FALSE
        """)
        
        # Update existing records that have an associated vet.animal.owner record
        cr.execute("""
            UPDATE res_partner 
            SET is_vet_owner = TRUE 
            WHERE id IN (
                SELECT DISTINCT partner_id 
                FROM vet_animal_owner 
                WHERE partner_id IS NOT NULL
            )
        """)
        
        _logger.info("Successfully added is_vet_owner column to res_partner")
    else:
        _logger.info("is_vet_owner column already exists in res_partner, skipping")
    
    # Commit the changes
    cr.commit()
