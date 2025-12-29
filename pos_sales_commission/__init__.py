# -*- coding: utf-8 -*-
from . import models


def pre_init_check(cr):
	from odoo.exceptions import UserError
	from odoo.service import common
	version_info = common.exp_version()
	server_serie =version_info.get('server_serie')
	# if server_serie!='17.0':
	# 	raise UserError('Module support Odoo series 17.0 found {}.'.format(server_serie))
	return True
