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


from typing import List
from pydantic import BaseModel as PydanticBaseModel, create_model


class BaseModel(PydanticBaseModel):
    class Config:
        extra = "allow"


class RecognizerMessage(BaseModel):
    msg_type: str = "recognizer_loop:utterance"
    data: create_model("Data",
                       utterances=(list, ...),
                       lang=(str, ...),
                       __base__=BaseModel,
                       )
    context: create_model("Context",
                          client_name=(str, "pyklatchat"),
                          client=(str, "browser"),
                          source=(str, "mq_api"),
                          destination=(list, ["skills"]),
                          timing=(dict, {}),
                          neon_should_respond=(bool, True),
                          username=(str, "guest"),
                          klat_data=(dict, {'key': 'val'}),
                          mq=(dict, None),
                          user_profiles=(list, []),
                          request_skills=(List[str], None),
                          __base__=BaseModel,
                          )


class STTMessage(BaseModel):
    msg_type: str = "neon.get_stt"
    data: create_model("Data",
                       audio_data=(str, ...),
                       lang=(str, ...),
                       __base__=BaseModel,
                       )
    context: create_model("Context",
                          source=(str, "mq_api"),
                          destination=(list, ["speech"]),
                          __base__=BaseModel,
                          )


class TTSMessage(BaseModel):
    msg_type: str = "neon.get_tts"
    data: create_model("Data",
                       text=(str, ...),
                       lang=(str, ...),
                       __base__=BaseModel,
                       )
    context: create_model("Context",
                          source=(str, "mq_api"),
                          destination=(list, ["audio"]),
                          __base__=BaseModel,
                          )


templates = {
    "stt": STTMessage,
    "tts": TTSMessage,
    "recognizer": RecognizerMessage,
}
