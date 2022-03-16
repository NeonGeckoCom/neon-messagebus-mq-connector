# NEON AI (TM) SOFTWARE, Software Development Kit & Application Development System
#
# Copyright 2008-2021 Neongecko.com Inc. | All Rights Reserved
#
# Notice of License - Duplicating this Notice of License near the start of any file containing
# a derivative of this software is a condition of license for this software.
# Friendly Licensing:
# No charge, open source royalty free use of the Neon AI software source and object is offered for
# educational users, noncommercial enthusiasts, Public Benefit Corporations (and LLCs) and
# Social Purpose Corporations (and LLCs). Developers can contact developers@neon.ai
# For commercial licensing, distribution of derivative works or redistribution please contact licenses@neon.ai
# Distributed on an "AS IS” basis without warranties or conditions of any kind, either express or implied.
# Trademarks of Neongecko: Neon AI(TM), Neon Assist (TM), Neon Communicator(TM), Klat(TM)
# Authors: Guy Daniels, Daniel McKnight, Elon Gasper, Richard Leeds, Kirill Hrymailo
#
# Specialized conversational reconveyance options from Conversation Processing Intelligence Corp.
# US Patents 2008-2021: US7424516, US20140161250, US20140177813, US8638908, US8068604, US8553852, US10530923, US10530924
# China Patent: CN102017585  -  Europe Patent: EU2156652  -  Patents Pending

import pika
from mycroft_bus_client import MessageBusClient, Message

from neon_utils import LOG
from neon_utils.socket_utils import b64_to_dict
from neon_utils.messagebus_utils import get_neon_bus_config
from neon_mq_connector.connector import MQConnector
from pika.channel import Channel
from pydantic import ValidationError

from .messages import templates


class ChatAPIProxy(MQConnector):
    """
    Proxy module for establishing connection between PyKlatchat and neon chat api"""

    def __init__(self, config: dict, service_name: str):
        super().__init__(config, service_name)

        self.vhost = '/neon_chat_api'
        self.bus_config = config.get('MESSAGEBUS') or get_neon_bus_config()
        self._bus = None
        self.connect_bus()
        self.register_consumer(name=f'neon_api_request_{self.service_id}',
                               vhost=self.vhost,
                               queue=f'neon_chat_api_request_{self.service_id}',
                               callback=self.handle_user_message,
                               on_error=self.default_error_handler,
                               auto_ack=False)
        self.register_consumer(name='neon_request_consumer',
                               vhost=self.vhost,
                               queue='neon_chat_api_request',
                               callback=self.handle_user_message,
                               on_error=self.default_error_handler,
                               auto_ack=False)

    def register_bus_handlers(self):
        """Convenience method to gather message bus handlers"""
        self._bus.on('klat.response', self.handle_neon_message)

    def connect_bus(self, refresh: bool = False):
        """
            Convenience method for establishing connection to message bus

            :param refresh: To refresh existing connection
        """
        if not self._bus or refresh:
            self._bus = MessageBusClient(host=self.bus_config['host'],
                                         port=int(self.bus_config.get('port',
                                                                      8181)),
                                         route=self.bus_config.get('route',
                                                                   '/core'))
            self.register_bus_handlers()
            self._bus.run_in_thread()

    @property
    def bus(self):
        """
            Connects to Message Bus if no connection was established

            :return: connected message bus client instance
        """
        if not self._bus:
            self.connect_bus()
        return self._bus

    def handle_neon_message(self, message: Message,
                            routing_key: str = None):
        """
        Handles responses from Neon Core

        :param message: Received Message object
        :param routing_key: Queue to post response to
        """

        if len(list(message.data)) > 0:
            body = {'data': message.data, 'context': message.context}
        else:
            body = {'data': {'msg': 'Failed to get response from Neon'}}
        LOG.debug(f'Received neon response body: {body}')
        routing_key = routing_key or \
            message.context.get("klat", {}).get("routing_key") or \
            'neon_chat_api_response'
        with self.create_mq_connection(vhost=self.vhost) as mq_connection:
            self.emit_mq_message(connection=mq_connection,
                                 request_data=body,
                                 queue=routing_key)

    def validate_request(self, dict_data: dict):
        """
        Validate dict_data dictionary structure by using tamplate
        All templates are located in messages.py file

        :param dict_data: request for validation
        :return: validation details(None if validation passed),
                 input data with proper data types and filled default fields
        """
        def check_keys_presence(dict_data, message_templates):
            try:
                for message_template in message_templates:
                    dict_data = message_template(**dict_data).dict()
            except (ValueError, ValidationError) as err:
                return err, dict_data
            return None, dict_data

        # TODO: This is really `templates`, not `skills`
        request_skills = dict_data["context"].get("request_skills",
                                                  ["default"])
        if len(request_skills) == 0:
            request_skills = ["default"]
        try:
            message_templates = [templates[request_type]
                                 for request_type in request_skills]
        except KeyError:
            return None, dict_data
        check_error, dict_data = check_keys_presence(dict_data,
                                                     message_templates)
        return check_error, dict_data

    def handle_user_message(self,
                            channel: pika.channel.Channel,
                            method: pika.spec.Basic.Return,
                            properties: pika.spec.BasicProperties,
                            body: bytes):
        """
        Handles requests from MQ to Neon Chat API received on queue
        "neon_chat_api_request"

        :param channel: MQ channel object (pika.channel.Channel)
        :param method: MQ return method (pika.spec.Basic.Return)
        :param properties: MQ properties (pika.spec.BasicProperties)
        :param body: request body (bytes)

        """
        if body and isinstance(body, bytes):
            dict_data = b64_to_dict(body)
            LOG.info(f'Received user message: {dict_data}')
            dict_data["context"].setdefault("mq", dict())
            if "routing_key" in dict_data:
                dict_data["context"]["mq"]["routing_key"] = \
                    dict_data.pop("routing_key")
            if "message_id" in dict_data:
                dict_data["context"]["mq"]["message_id"] = \
                    dict_data.pop("message_id")
            check_error, dict_data = self.validate_request(dict_data)
            if check_error is not None:
                response = Message(msg_type="klat.error",
                                   data=dict(error=str(check_error),
                                             message=dict_data))
                self.handle_neon_message(response, "neon_chat_api_error")
            else:
                self.bus.emit(Message(**dict_data))
            channel.basic_ack(method.delivery_tag)
        else:
            channel.basic_nack()
            raise TypeError(f'Invalid body received, expected: bytes string;'
                            f' got: {type(body)}')
