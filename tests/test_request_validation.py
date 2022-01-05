import unittest
from pydantic import ValidationError

import os, sys
sys.path.append(os.path.abspath(os.path.dirname(os.path.realpath(__file__))+"/../chat_api_mq_proxy"))

from messages import STT


class RequestTests(unittest.TestCase):

    default_stt_keys = dict(
            msg_type = "recognizer_loop:utterance",
            data = dict(
                audio_file = "1",
                lang = "1"
            ),
            context = dict(
            )
        )

    def test_001_stt(self):
        "Proper stt request structure"
        dict_keys = self.default_stt_keys.copy()

        try:
            STT(**dict_keys)
        except (ValidationError, ValueError) as err:
            self.fail(err)

    def test_002_stt(self):
        "Missing fields in stt request structure"
        dict_keys = self.default_stt_keys.copy()
        del dict_keys["data"]["audio_file"]

        with self.assertRaises(ValueError):
            STT(**dict_keys)