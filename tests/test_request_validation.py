# NEON AI (TM) SOFTWARE, Software Development Kit & Application Framework
# All trademark and other rights reserved by their respective owners
# Copyright 2008-2025 Neongecko.com Inc.
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


import unittest
from copy import deepcopy
from pydantic import ValidationError

from neon_messagebus_mq_connector.messages import STTMessage, TTSMessage


class RequestTests(unittest.TestCase):
    default_stt_keys = dict(
        msg_type="neon.get_stt",
        data=dict(
            audio_data="123",
            lang="1"
        ),
        context=dict(
            ident="ident"
        )
    )

    default_tts_keys = dict(
        msg_type="neon.get_tts",
        data=dict(
            text="1",
            lang="en-us"
        ),
        context=dict(
            client_name="1",
            client="1",
            source="1",
            destination=["1"],
            ident="1",
            timing={"1": "1"},
            neon_should_respond=False,
            username="1",
            klat_data={"sid": "1",
                       "cid": "1"},
            user_profiles=[{"1": "1"}]
        )
    )

    def test_stt_proper(self):
        "Proper stt request structure"
        dict_keys = deepcopy(self.default_stt_keys)

        try:
            STTMessage(**dict_keys)
        except (ValidationError, ValueError) as err:
            self.fail(err)

    def test_stt_missing(self):
        "Missing fields in stt request structure"
        dict_keys = deepcopy(self.default_stt_keys)
        del dict_keys["data"]["audio_data"]

        with self.assertRaises(ValueError):
            STTMessage(**dict_keys)

    def test_tts_proper(self):
        "Proper tts request structure"
        dict_keys = deepcopy(self.default_tts_keys)
        try:
            TTSMessage(**dict_keys)
        except (ValidationError, ValueError) as err:
            self.fail(err)

    def test_stt_proper_missing(self):
        "Missing fields in tts request structure"
        dict_keys = deepcopy(self.default_tts_keys)
        del dict_keys["data"]["text"]

        with self.assertRaises(ValidationError):
            TTSMessage(**dict_keys)

    def test_tts_optional(self):
        "Optional fields fillment in tts request"
        dict_keys = deepcopy(self.default_tts_keys)
        del dict_keys["context"]["destination"]
        pydantic_message = TTSMessage(**dict_keys)
        dict_keys = pydantic_message.dict()

        # self.assertEqual(dict_keys["context"]["neon_should_respond"], True)
        self.assertEqual(dict_keys["context"]["destination"], ['audio'])
