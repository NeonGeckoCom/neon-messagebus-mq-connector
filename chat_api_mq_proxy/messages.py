templates = {
    "recognizer_loop:utterance": {
        "msg_type": str,
        "data": {
            "audio_file": str,
            "lang": str
        },
        "context":{
            "ident": str
        }
    },
    "klat.shout": {
        "msg_type": str,
        "data": {
            "sid": str,
            "nick": str,
            "cid": str,
            "time": str,
            "title": str,
            "text": str
        },
        "context": {
            "neon_should_respond": bool
        }
    }
}