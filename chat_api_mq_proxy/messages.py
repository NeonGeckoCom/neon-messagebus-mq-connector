from pydantic import BaseModel, create_model


class STT(BaseModel):
    msg_type: str
    data: create_model("Data",
        audio_file = (str, ...),
        lang = (str, ...)
    )
    context: create_model("Context"
    )


templates = {
    "recognizer_loop:utterance": STT,
}