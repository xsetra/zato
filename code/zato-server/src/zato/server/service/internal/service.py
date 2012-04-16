# -*- coding: utf-8 -*-

"""
Copyright (C) 2011 Dariusz Suchojad <dsuch at gefira.pl>

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

from __future__ import absolute_import, division, print_function, unicode_literals

# stdlib
from contextlib import closing
from httplib import BAD_REQUEST, NOT_FOUND
from mimetypes import guess_type
from traceback import format_exc
from urlparse import parse_qs

# Zato
from zato.common import ZATO_OK, ZatoException
from zato.common.broker_message import MESSAGE_TYPE, SERVICE
from zato.common.odb.model import Cluster, ChannelAMQP, ChannelWMQ, ChannelZMQ, \
     DeployedService, HTTPSOAP, Server, Service
from zato.common.odb.query import service, service_list
from zato.common.util import payload_from_request
from zato.server.service import Boolean, Service as ServiceClass
from zato.server.service.internal import AdminService

class GetList(AdminService):
    """ Returns a list of services.
    """
    class SimpleIO:
        input_required = ('cluster_id',)
        output_required = ('id', 'name', 'is_active', 'impl_name', 'is_internal')
        output_repeated = True
        
    def handle(self):
        with closing(self.odb.session()) as session:
            self.response.payload[:] = service_list(session, self.request.input.cluster_id, False)
        
class GetByName(AdminService):
    """ Returns a particular service.
    """
    class SimpleIO:
        input_required = ('cluster_id', 'name')
        output_required = ('id', 'name', 'is_active', 'impl_name', 'is_internal')
        output_optional = ('usage_count',)

    def handle(self):
        with closing(self.odb.session()) as session:
            s = session.query(Service.id, Service.name, Service.is_active,
                                Service.impl_name, Service.is_internal).\
                            filter(Cluster.id==Service.cluster_id).\
                            filter(Cluster.id==self.request.input.cluster_id).\
                            filter(Service.name==self.request.input.name).one()
            
            self.response.payload.id = s.id
            self.response.payload.name = s.name
            self.response.payload.is_active = s.is_active
            self.response.payload.impl_name = s.impl_name
            self.response.payload.is_internal = s.is_internal
            self.response.payload.usage_count = 0

class Edit(AdminService):
    """ Updates a service.
    """
    class SimpleIO:
        input_required = ('id', 'is_active', 'name')
        output_required = ('id', 'name', 'impl_name', 'is_internal',)
        output_optional = (Boolean('usage_count'),)

    def handle(self):
        input = self.request.input
        with closing(self.odb.session()) as session:
            try:
                service = session.query(Service).filter_by(id=input.id).one()
                service.is_active = input.is_active
                service.name = input.name
                
                session.add(service)
                session.commit()
                
                input.action = SERVICE.EDIT
                self.broker_client.send_json(input, msg_type=MESSAGE_TYPE.TO_PARALLEL_SUB)
                
                self.response.payload = service
                
            except Exception, e:
                msg = 'Could not update the service, e=[{e}]'.format(e=format_exc(e))
                self.logger.error(msg)
                session.rollback()
                
                raise         
            
class GetWSDL(ServiceClass):
    """ Returns a WSDL for the given service. Either uses a user-uploaded one,
    or, optionally generates one on fly if the service uses SimpleIO.
    """
    input_optional = ('service',)
    def handle(self):
        if self.request.request_data.query:
            query = parse_qs(self.request.request_data.query)
            service_name = query.get('service')
        else:
            service_name = self.request.input.service
            
        if not service_name:
            self.response.status_code = BAD_REQUEST
            self.response.payload = 'The [service] parameter could not be found'
            return
        
        service_name = service_name[0]
        
        with closing(self.odb.session()) as session:
            service = session.query(Service).filter_by(name=service_name).first()
            if not service:
                self.response.status_code = NOT_FOUND
                self.response.payload = 'Service [{}] not found'.format(service_name)
                return
            
        if service.wsdl:
            content_type = guess_type(service.wsdl_name)[0] or 'application/octet-stream'
            self.set_attachment(service_name, service.wsdl, content_type)
            
        else:
            self.response.status_code = NOT_FOUND
            self.response.payload = 'No WSDL found'
                    
    def set_attachment(self, service_name, payload, content_type):
        """ Sets the information that we're returning an attachment to the user.
        """
        self.response.content_type = content_type
        self.response.payload = payload
        self.response.headers['Content-Disposition'] = 'attachment; filename={}.wsdl'.format(service_name)
        
class Delete(AdminService):
    """ Deletes a service
    """
    class SimpleIO:
        input_required = ('id',)

    def handle(self):
        with closing(self.odb.session()) as session:
            try:
                service = session.query(Service).\
                    filter(Service.id==self.request.input.id).\
                    one()
                
                session.delete(service)
                session.commit()

                msg = {'action': SERVICE.DELETE, 'id': self.request.input.id}
                self.broker_client.send_json(msg, msg_type=MESSAGE_TYPE.TO_PARALLEL_SUB)
                
            except Exception, e:
                session.rollback()
                msg = 'Could not delete the service, e=[{e}]'.format(e=format_exc(e))
                self.logger.error(msg)
                
                raise

class GetChannelList(AdminService):
    """ Returns a list of channels of a given type through which the service
    is being exposed.
    """
    class SimpleIO:
        input_required = ('id', 'channel_type')
        output_required = ('id', 'name')
        
    def handle(self):
        channel_type_class = {
            'plain_http': HTTPSOAP,
            'soap': HTTPSOAP,
            'amqp': ChannelAMQP,
            'jms-wmq': ChannelWMQ,
            'zmq': ChannelZMQ,
        }
        
        class_ = channel_type_class[self.request.input.channel_type]
        q_attrs = (class_.id, class_.name)
        
        with closing(self.odb.session()) as session:
            q = session.query(*q_attrs).\
                filter(class_.service_id == self.request.input.id)
            
            if self.request.input.channel_type == 'soap':
                q = q.filter(class_.soap_version != None)
            elif self.request.input.channel_type == 'plain_http':
                q = q.filter(class_.soap_version == None)
            
            self.response.payload[:] = q.all()
        
class Invoke(AdminService):
    """ Invokes the service directly, as though it was exposed through some channel
    which doesn't necessarily have to be true.
    """
    class SimpleIO:
        input_required = ('id', 'payload')
        input_optional = ('data_format', 'transport')
        output_required = ('response',)

    def handle(self):
        with closing(self.odb.session()) as session:
            service = session.query(Service).\
                filter(Service.id==self.request.input.id).\
                one()
            
        payload = payload_from_request(self.request.input.payload, self.request.input.data_format,
                        self.request.input.transport)
        
        service_instance = self.server.service_store.new_instance(service.impl_name)
        service_instance.update(service_instance, self.server, self.broker_client, 
            self.worker_store, self.cid, payload, self.request.input.payload, 
            self.request.input.transport, self.request.simple_io_config, 
            self.request.input.data_format, self.request.request_data)

        service_instance.handle()
        response = service_instance.response.payload
        if not isinstance(response, basestring):
            response = response.getvalue()

        self.response.payload.response = response

class GetDeploymentInfoList(AdminService):
    """ Returns detailed information regarding the service's deployment status
    on each of the servers it's been deployed to.
    """
    class SimpleIO:
        input_required = ('id',)
        output_required = ('server_id', 'server_name', 'details')
        
    def handle(self):
        with closing(self.odb.session()) as session:
            self.response.payload[:] = session.query(DeployedService.details,
                    Server.name.label('server_name'), 
                    Server.id.label('server_id')).\
                outerjoin(Server, DeployedService.server_id==Server.id).\
                filter(DeployedService.service_id==self.request.input.id).\
                all()