# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class ShowWizardMessage(models.TransientModel):
	_name = "show.wizard.message"
	_description = "Show Wizard Message"
	text = fields.Text()
	
	def show_wizard_message(self,message,name='Message/Summary'):
		partial_id = self.create({'text':message}).id
		return {
			'name':name,
			'view_mode': 'form',
			'view_id': False,
			'view_type': 'form',
			'res_model': 'show.wizard.message',
			'res_id': partial_id.id,
			'type': 'ir.actions.act_window',
			'nodestroy': True,
			'target': 'new',
		}
