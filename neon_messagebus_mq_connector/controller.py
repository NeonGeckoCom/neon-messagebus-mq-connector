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
import time
from typing import List, Type, Tuple

import pika
from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message

from ovos_utils.log import LOG, log_deprecation
from neon_utils.socket_utils import b64_to_dict
from ovos_config.config import Configuration
from neon_mq_connector.connector import MQConnector
from pika.channel import Channel
from pydantic import ValidationError

from .enums import NeonResponseTypes
from .messages import templates, BaseModel


class ChatAPIProxy(MQConnector):
    """
    Proxy module for establishing connection between PyKlatchat and neon chat api"""

    def __init__(self, config: dict, service_name: str):
        config = config or Configuration()
        mq_config = config.get("MQ", config)
        super().__init__(mq_config, service_name)
        self.bus_config = config.get("websocket")
        if config.get("MESSAGEBUS"):
            log_deprecation("MESSAGEBUS config is deprecated. use `websocket`",
                            "1.0.0")
            self.bus_config = config.get("websocket")
        self._vhost = '/neon_chat_api'
        self._bus = None
        self.connect_bus()
        self.register_consumer(name=f'neon_api_request_{self.service_id}',
                               vhost=self.vhost,
                               queue=f'neon_chat_api_request_{self.service_id}',
                               callback=self.handle_user_message,
                               on_error=self.default_error_handler,
                               auto_ack=True,
                               restart_attempts=-1)
        self.register_consumer(name='neon_request_consumer',
                               vhost=self.vhost,
                               queue='neon_chat_api_request',
                               callback=self.handle_user_message,
                               on_error=self.default_error_handler,
                               auto_ack=True,
                               restart_attempts=-1)
        self.response_timeouts = {
            NeonResponseTypes.TTS: 60,
            NeonResponseTypes.STT: 60
        }

    def register_bus_handlers(self):
        """Convenience method to gather message bus handlers"""
        self._bus.on('klat.response', self.handle_neon_message)
        self._bus.on('complete.intent.failure', self.handle_neon_message)
        self._bus.on('neon.profile_update', self.handle_neon_profile_update)
        self._bus.on('neon.clear_data', self.handle_neon_message)
        self._bus.on('neon.get_tts.response', self.handle_neon_message)
        self._bus.on('neon.get_stt.response', self.handle_neon_message)

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

    def handle_neon_message(self, message: Message):
        """
            Handles responses from Neon Core

            :param message: Received Message object
        """

        if not message.data:
            message.data['msg'] = 'Failed to get response from Neon'
        message.context.setdefault('klat_data', {})
        if message.msg_type == 'neon.get_tts.response':
            body = self.format_response(response_type=NeonResponseTypes.TTS, message=message)
            message.context['klat_data'].setdefault('routing_key', 'neon_tts_response')
        elif message.msg_type == 'neon.get_stt.response':
            body = self.format_response(response_type=NeonResponseTypes.STT, message=message)
            message.context['klat_data'].setdefault('routing_key', 'neon_stt_response')
        else:
            body = {'msg_type': message.msg_type,
                    'data': message.data, 'context': message.context}
        LOG.debug(f'Received neon response body: {body}')
        if not body:
            LOG.warning('Something went wrong while formatting - received empty body')
        else:
            routing_key = message.context.get("mq",
                                              {}).get("routing_key",
                                                      'neon_chat_api_response')
            LOG.debug(f"Got routing_key={routing_key}")
            self.send_message(request_data=body, queue=routing_key)

    def handle_neon_profile_update(self, message: Message):
        """
        Handles profile updates from Neon Core. Ensures routing_key is defined
        to avoid publishing private profile values to a shared queue
        :param message: Message containing the updated user profile
        """
        if message.context.get('klat_data', {}).get('routing_key'):
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

        LOG.debug('Initiating template validation')
        for message_template in message_templates:
            try:
                msg_data = message_template(**msg_data).dict()
            except (ValueError, ValidationError) as err:
                LOG.error(f'Failed to validate {msg_data} with template = {message_template.__name__}, exception={err}')
                return str(err), msg_data
        LOG.debug('Template validation completed successfully')
        return '', msg_data

    @classmethod
    def validate_request(cls, msg_data: dict):
        """
            Fetches the relevant template models and validates provided message data iteratively through them

            :param msg_data: message data for validation

            :return: validation details(None if validation passed),
                     input data with proper data types and filled default fields
        """

        requested_templates = msg_data.get("context", {}).get("request_skills") or ["recognizer"]
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

    def validate_message_context(self, message: Message) -> bool:
        """ Validates message context so its relevant data could be fetched once received response """
        message_id = message.context.get('mq', {}).get('message_id')
        if not message_id:
            LOG.warning('Message context validation failed - message_id is None')
            return False
        else:
            message.context['created_on'] = int(time.time())
            if message.msg_type == 'neon.get_stt':
                message.context['lang'] = message.data.get('lang')
        return True

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
            mq_context = {"routing_key": dict_data.pop('routing_key', ''),
                          "message_id": dict_data.pop('message_id', '')}
            klat_context = {"cid": dict_data.pop('cid', ''),
                            "sid": dict_data.pop('sid', '')}
            # Klat Context for backwards-compat
            dict_data["context"].setdefault("mq",
                                            {**mq_context, **klat_context})
            dict_data["context"].setdefault("klat_data", klat_context)

            validation_error, dict_data = self.validate_request(dict_data)
            if validation_error:
                LOG.error(f"Validation failed with: {validation_error}")
                # Don't deserialize since this Message may be malformed
                context = dict_data.pop("context")
                response = Message("klat.error", {"error": validation_error,
                                                  "data": dict_data},
                                   context)
                response.context['klat_data'].setdefault('routing_key',
                                                         'neon_chat_api_error')
                self.handle_neon_message(response)
            else:
                # dict_data["context"].setdefault('ident', f"{dict_data['msg_type']}.response")
                message = Message(**dict_data)
                is_context_valid = self.validate_message_context(message)
                if is_context_valid:
                    self.bus.emit(message)
                else:
                    LOG.error(f'Message context is invalid - {message} is not emitted')
        else:
            channel.basic_nack()
            raise TypeError(f'Invalid body received, expected: bytes string;'
                            f' got: {type(body)}')

    def format_response(self, response_type: NeonResponseTypes, message: Message) -> dict:
        """
        Formats received response by Neon API based on type

        :param response_type: response type from NeonResponseTypes Enum
        :param message: Neon MessageBus Message object

        :returns formatted response dict
        """
        msg_error = message.data.get('error')
        if msg_error:
            LOG.error(f'Failed to fetch data for context={message.context} - '
                      f'{msg_error}')
            return {}
        timeout = self.response_timeouts.get(response_type, 30)
        if int(time.time()) - message.context.get('created_on', 0) > timeout:
            LOG.warning(f'Message = {message} received timeout on '
                        f'{response_type} (>{timeout} seconds)')
            response_data = {}
        else:
            if response_type == NeonResponseTypes.TTS:
                lang = list(message.data)[0]
                gender = message.data[lang].get('genders', ['female'])[0]
                audio_data_b64 = message.data[lang]['audio'][gender]

                response_data = {
                    'audio_data': audio_data_b64,
                    'lang': lang,
                    'gender': gender,
                    'context': message.context
                }
            elif response_type == NeonResponseTypes.STT:
                transcripts = message.data.get('transcripts', [''])
                if transcripts and transcripts[0]:
                    LOG.info(f'transcript candidates received - {transcripts}')
                    response_data = {
                        'transcript': transcripts[0],
                        'other_transcripts': [transcript for transcript in
                                              transcripts if
                                              transcript != transcripts[0]],
                        'lang': message.context.get('lang', 'en-us'),
                        'context': message.context
                    }
                else:
                    LOG.error('No transcripts received')
                    response_data = {}
            else:
                LOG.warning(f'Failed to response response type -> '
                            f'{response_type}')
                response_data = {}
        return response_data
