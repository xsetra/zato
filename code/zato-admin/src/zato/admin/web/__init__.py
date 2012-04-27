# -*- coding: utf-8 -*-

"""
Copyright (C) 2010 Dariusz Suchojad <dsuch at gefira.pl>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

# lxml
from lxml import etree
from lxml.objectify import Element

# Zato
from zato.admin.settings import TECH_ACCOUNT_NAME, TECH_ACCOUNT_PASSWORD
from zato.common.soap import invoke_admin_service as _invoke_admin_service

def invoke_admin_service(cluster, service, zato_message):
    """ A thin wrapper around zato.common.soap.invoke_admin_service that adds
    Django session-related information to the request headers.
    """
    headers = {'x-zato-session-type':'zato-admin/tech_acc', 
               'x-zato-user': TECH_ACCOUNT_NAME,
               'x-zato-password': TECH_ACCOUNT_PASSWORD
               }
    return _invoke_admin_service(cluster, service, etree.tostring(zato_message),
                                 headers)
