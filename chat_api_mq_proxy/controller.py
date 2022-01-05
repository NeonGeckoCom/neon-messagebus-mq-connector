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
from neon_utils.socket_utils import b64_to_dict, dict_to_b64
from neon_mq_connector.connector import MQConnector
from pika.channel import Channel

from messages import templates


class ChatAPIProxy(MQConnector):
    """Proxy module for establishing connection between PyKlatchat and neon chat api"""

    def __init__(self, config: dict, service_name: str):
        super().__init__(config, service_name)

        self.vhost = '/neon_chat_api'
        self.bus_config = config['MESSAGEBUS']
        self._bus = None
        self.connect_bus()
        self.register_consumer(name='neon_request_consumer',
                               vhost=self.vhost,
                               queue='neon_api_request',
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
                                         port=int(self.bus_config.get('port', 8181)),
                                         route=self.bus_config.get('route', '/core'))
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

    def handle_neon_message(self, message: Message):
        """
            Handles responses from Neon Chat API

            :param message: Received Message object
        """

        if len(list(message.data)) > 0:
            body = {'data': message.data, 'context': message.context}
        else:
            body = {'data': {'msg': 'Failed to get response from Neon'}}
        LOG.info(f'Received neon response body: {body}')
        mq_connection = self.create_mq_connection(vhost=self.vhost)
        connection_channel = mq_connection.channel()
        connection_channel.queue_declare(queue='neon_api_response')
        connection_channel.basic_publish(exchange='',
                                         routing_key='neon_api_response',
                                         body=dict_to_b64(body),
                                         properties=pika.BasicProperties(expiration='1000')
                                         )
        connection_channel.close()
        mq_connection.close()

    def validate_request(self, message: dict):
        def check_keys_presence(message, message_template, parent_name = "message"):
            for key in message_template.keys():
                #Presence
                if key not in message:
                    return KeyError(f"No {key} provided in {parent_name}")
                #Type
                child_template = message_template[key]
                chield_message = message[key]
                template_type = type(child_template)
                chield_type = type(chield_message)
                if not isinstance(chield_message, template_type):
                    return TypeError(f"{key} in {parent_name} type should be {template_type}, but {chield_type} provided")
                #Recurent call
                if chield_type is dict:
                    child_name = f"{parent_name}.{key}"
                    check_error = check_keys_presence(chield_message, child_template, child_name)
                    if check_error is not None:
                        return check_error

        if not "msg_type" in message:
            return KeyError("No msg_type provided in message")
        message_template = templates[message["msg_type"]]
        check_error = check_keys_presence(message, message_template)
        return check_error

    def handle_user_message(self,
                            channel: pika.channel.Channel,
                            method: pika.spec.Basic.Return,
                            properties: pika.spec.BasicProperties,
                            body: bytes):
        """
            Handles requests from MQ to Neon Chat API received on queue "neon_api_request"

            :param channel: MQ channel object (pika.channel.Channel)
            :param method: MQ return method (pika.spec.Basic.Return)
            :param properties: MQ properties (pika.spec.BasicProperties)
            :param body: request body (bytes)

        """
        if body and isinstance(body, bytes):
            dict_data = b64_to_dict(body)
            LOG.info(f'Received user message: {dict_data}')
            message_id = dict_data.get('messageID', None)

            if message_id:
                self.bus.emit(Message(msg_type='klat.shout',
                                      data=dict(sid=message_id,
                                                nick=dict_data.get('nick', 'pyklatchat_user'),
                                                cid=dict_data.get('cid'),
                                                time=dict_data.get('timeCreated'),
                                                title='Klatchat User Shout',
                                                text=dict_data.get('messageText', '').strip()),
                                      context=dict(neon_should_respond=True)))

        else:
            raise TypeError(f'Invalid body received, expected: bytes string; got: {type(body)}')

    def run(self, **kwargs):
        """Generic method to run all the relevant submodules"""
        super().run(run_consumers=True, run_sync=True)
