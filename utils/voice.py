import threading
from faster_whisper import WhisperModel
from config import WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE

_lock = threading.Lock()
_model = None


def get_whisper_model() -> WhisperModel:
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = WhisperModel(
                    WHISPER_MODEL,
                    device=WHISPER_DEVICE,
                    device_index=0,
                    compute_type=WHISPER_COMPUTE_TYPE,
                )
    return _model


def transcribe_audio(path: str) -> str:
    model = get_whisper_model()
    segments, _ = model.transcribe(
        path,
        beam_size=5,
        vad_filter=True,
        language="zh",  # 如果你主要中文，固定更快更准
        temperature=0.0,
        condition_on_previous_text=False,
    )
    return "".join(seg.text for seg in segments).strip()
