# NEON AI (TM) SOFTWARE, Software Development Kit & Application Framework
# All trademark and other rights reserved by their respective owners
# Copyright 2008-2022 Neongecko.com Inc.
# Contributors: Daniel McKnight, Guy Daniels, Elon Gasper, Richard Leeds,
# Regina Bloomstine, Casimiro Ferreira, Andrii Pernatii, Kirill Hrymailo
# BSD-3 License
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from this
#    software without specific prior written permission.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS  BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
# OR PROFITS;  OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE,  EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from typing import List, Type, Tuple

import pika
from mycroft_bus_client import MessageBusClient, Message

from neon_utils.logger import LOG
from neon_utils.socket_utils import b64_to_dict
from ovos_config.config import Configuration
from neon_mq_connector.connector import MQConnector
from pika.channel import Channel
from pydantic import ValidationError

from .messages import templates, BaseModel


class ChatAPIProxy(MQConnector):
    """
    Proxy module for establishing connection between PyKlatchat and neon chat api"""

    def __init__(self, config: dict, service_name: str):
        super().__init__(config, service_name)

        self._vhost = '/neon_chat_api'
        self.bus_config = config.get('MESSAGEBUS') or \
            dict(Configuration()).get("websocket")
        self._bus = None
        self.connect_bus()
        self.register_consumer(name=f'neon_api_request_{self.service_id}',
                               vhost=self.vhost,
                               queue=f'neon_chat_api_request_{self.service_id}',
                               callback=self.handle_user_message,
                               on_error=self.default_error_handler,
                               auto_ack=True)
        self.register_consumer(name='neon_request_consumer',
                               vhost=self.vhost,
                               queue='neon_chat_api_request',
                               callback=self.handle_user_message,
                               on_error=self.default_error_handler,
                               auto_ack=True)

    def register_bus_handlers(self):
        """Convenience method to gather message bus handlers"""
        self._bus.on('klat.response', self.handle_neon_message)
        self._bus.on('complete.intent.failure', self.handle_neon_message)
        self._bus.on('neon.profile_update', self.handle_neon_profile_update)
        self._bus.on('neon.clear_data', self.handle_neon_message)

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
    def bus(self) -> MessageBusClient:
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

        if not message.data:
            message.data['msg'] = 'Failed to get response from Neon'

        body = {'msg_type': message.msg_type,
                'data': message.data, 'context': message.context}
        LOG.debug(f'Received neon response body: {body}')
        routing_key = message.context.get("klat", {}).get("routing_key") or \
            routing_key or 'neon_chat_api_response'
        self.send_message(request_data=body, queue=routing_key)

    def handle_neon_profile_update(self, message: Message):
        """
        Handles profile updates from Neon Core. Ensures routing_key is defined
        to avoid publishing private profile values to a shared queue
        :param message: Message containing the updated user profile
        """
        if message.context.get('klat', {}).get('routing_key'):
            LOG.info(f"handling profile update for "
                     f"user={message.data['profile']['user']['username']}")
            self.handle_neon_message(message)
        else:
            LOG.debug(f"ignoring profile update for "
                      f"user={message.data['profile']['user']['username']}")

    @staticmethod
    def __validate_message_templates(msg_data: dict, message_templates: List[Type[BaseModel]] = None) -> Tuple[str, dict]:
        """
            Validate selected pydantic message templates into provided message data

            :param msg_data: Message data to fetch
            :param message_templates: list of pydantic templates to fetch into data

            :returns tuple containing 2 values:
                     1) validation error if detected;
                     2) fetched message data;
        """

        if not message_templates:
            LOG.warning('No matching templates found, skipping template fetching')
            return '', msg_data

        LOG.info('Initiating template validation')
        for message_template in message_templates:
            try:
                msg_data = message_template(**msg_data).dict()
            except (ValueError, ValidationError) as err:
                LOG.error(f'Failed to validate {msg_data} with template = {message_template.__name__}, exception={err}')
                return str(err), msg_data
        LOG.info('Template validation completed successfully')
        return '', msg_data

    @classmethod
    def validate_request(cls, msg_data: dict):
        """
            Fetches the relevant template models and validates provided message data iteratively through them

            :param msg_data: message data for validation

            :return: validation details(None if validation passed),
                     input data with proper data types and filled default fields
        """

        requested_templates = msg_data.get("context", {}).get("request_skills") or ["default"]
        message_templates = []

        for requested_template in requested_templates:
            matching_template_model = templates.get(requested_template)
            if not matching_template_model:
                LOG.warning(f'Template under keyword "{requested_template}" does not exist')
            else:
                message_templates.append(matching_template_model)

        detected_error, msg_data = cls.__validate_message_templates(msg_data=msg_data,
                                                                    message_templates=message_templates)
        return detected_error, msg_data

    def handle_user_message(self,
                            channel: pika.channel.Channel,
                            method: pika.spec.Basic.Return,
                            properties: pika.spec.BasicProperties,
                            body: bytes):
        """
            Transfers requests from MQ API to Neon Message Bus API

            :param channel: MQ channel object (pika.channel.Channel)
            :param method: MQ return method (pika.spec.Basic.Return)
            :param properties: MQ properties (pika.spec.BasicProperties)
            :param body: request body (bytes)

        """
        if body and isinstance(body, bytes):
            dict_data = b64_to_dict(body)
            LOG.info(f'Received user message: {dict_data}')
            dict_data["context"].setdefault("mq", dict(routing_key=dict_data.pop('routing_key', ''),
                                                       message_id=dict_data.pop('message_id', '')))
            validation_error, dict_data = self.validate_request(dict_data)
            if validation_error:
                response = Message(msg_type="klat.error",
                                   data=dict(error=validation_error,
                                             message=dict_data))
                self.handle_neon_message(response, "neon_chat_api_error")
            else:
                message = Message(**dict_data)
                if message.msg_type in ("neon.get_stt", "neon.get_tts",
                                        "neon.audio_input"):
                    # Transactional message, get response
                    reply_type = message.context.get("ident")
                    response = self.bus.wait_for_response(message, reply_type,
                                                          timeout=30)
                    # Replace response message type for MQ client to handle
                    response.msg_type = f'{message.msg_type}.response'
                    response = response or \
                        message.response(data={"success": False,
                                               "error": "no response"})
                    self.handle_neon_message(response)
                else:
                    # Probable user input to generate klat.response message
                    self.bus.emit(message)

            channel.basic_ack(method.delivery_tag)
        else:
            channel.basic_nack()
            raise TypeError(f'Invalid body received, expected: bytes string;'
                            f' got: {type(body)}')
