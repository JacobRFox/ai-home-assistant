"""Speech pieces for the voice plugin: wake word, end-of-speech detection, transcription.

Audio everywhere is 16 kHz mono int16, delivered in 80 ms frames (1280 samples).
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME = 1280  # 80 ms
INSTALL_HINT = "Voice needs extra packages: pip install -r requirements-voice.txt"


def pcm_frame(data: bytes) -> np.ndarray:
    """Browser audio frame (little-endian int16 PCM) -> numpy array."""
    return np.frombuffer(data, dtype="<i2")


# ---- wake word -------------------------------------------------------------------
# openWakeWord changed its API between releases. 0.4.x (the newest that installs on
# Python 3.14, since later ones need tflite-runtime) bundles its models in the package
# and takes file paths; 0.5+ downloads models on demand and takes names.
def _oww():
    try:
        import openwakeword
        from openwakeword.model import Model
    except ImportError as e:
        raise RuntimeError(INSTALL_HINT) from e
    return openwakeword, Model


def _builtin_models() -> dict[str, str]:
    """Built-in wake word name -> model path (0.4) or name (0.5+)."""
    oww, _ = _oww()
    if hasattr(oww, "models"):  # 0.4
        return {name: info["model_path"] for name, info in oww.models.items()}
    return {name: name for name in getattr(oww, "MODELS", {})}


def prepare_wake_word(name_or_path: str) -> str:
    """Resolve a wake word name or model file and make sure it's on disk.
    Returns what to pass to WakeWordDetector."""
    oww, _ = _oww()
    if Path(name_or_path).suffix in (".onnx", ".tflite"):
        if not Path(name_or_path).is_file():
            raise RuntimeError(f"Wake word model not found: {name_or_path}")
        return str(Path(name_or_path).resolve())
    builtin = _builtin_models()
    if name_or_path not in builtin:
        raise RuntimeError(f"Unknown wake word {name_or_path!r}. Built-in: {', '.join(sorted(builtin))}, "
                           "or give the path to a custom .onnx model.")
    if not hasattr(oww, "models"):  # 0.5+: fetch on first use
        from openwakeword.utils import download_models
        download_models(model_names=[name_or_path])
    return builtin[name_or_path]


class WakeWordDetector:
    """Stateful: create one per audio stream. `model` comes from prepare_wake_word()."""

    COOLDOWN_FRAMES = 15  # ~1.2 s after a reset during which detections are ignored

    def __init__(self, model: str, threshold: float) -> None:
        oww, Model = _oww()
        # The wake word model is tiny and runs on the CPU; silence onnxruntime's "no CUDA" warning.
        warnings.filterwarnings("ignore", message=".*CUDAExecutionProvider.*")
        if hasattr(oww, "models"):  # 0.4
            self.model = Model(wakeword_model_paths=[model])
        else:
            self.model = Model(wakeword_models=[model], inference_framework="onnx")
        self.threshold = threshold
        self.cooldown = 0

    def __call__(self, frame: np.ndarray) -> float | None:
        """Feed one frame. Returns the score when the wake word fires, else None."""
        score = float(max(self.model.predict(frame).values()))
        if self.cooldown:
            self.cooldown -= 1
            return None
        return score if score >= self.threshold else None

    def reset(self) -> None:
        # The model keeps ~1-2 s of recent audio features that reset() doesn't clear,
        # so also ignore detections briefly; otherwise the end of the last command
        # (or the reply) could re-trigger the wake word.
        self.model.reset()
        self.cooldown = self.COOLDOWN_FRAMES


# ---- end of speech ----------------------------------------------------------------
class CommandRecorder:
    """Collects the spoken command after the wake word and decides when it's finished.

    Energy-based: speech is anything clearly louder than the room's background noise,
    which is learned while waiting for the wake word.
    """

    def __init__(self, silence_s: float = 0.8, max_s: float = 10.0, start_timeout_s: float = 4.0) -> None:
        self.silence_frames = round(silence_s * SAMPLE_RATE / FRAME)
        self.max_frames = round(max_s * SAMPLE_RATE / FRAME)
        self.start_timeout_frames = round(start_timeout_s * SAMPLE_RATE / FRAME)
        self.noise = 200.0  # running background RMS estimate
        self.reset()

    def reset(self) -> None:
        self.frames: list[np.ndarray] = []
        self.speaking = False
        self.quiet = 0

    def observe_background(self, frame: np.ndarray) -> None:
        """Called on frames heard while waiting for the wake word."""
        rms = _rms(frame)
        # Fall fast, rise slowly, so speech doesn't inflate the noise floor much.
        self.noise = rms if rms < self.noise else 0.995 * self.noise + 0.005 * rms

    def add(self, frame: np.ndarray) -> bool:
        """Add a frame of the command. Returns True when the command is complete."""
        self.frames.append(frame)
        loud = _rms(frame) > max(self.noise * 3.0, 300.0)
        if loud:
            self.speaking, self.quiet = True, 0
        elif self.speaking:
            self.quiet += 1
        n = len(self.frames)
        return (self.speaking and self.quiet >= self.silence_frames) or n >= self.max_frames or (
            not self.speaking and n >= self.start_timeout_frames)

    def audio(self) -> np.ndarray:
        """The recording as float32 in [-1, 1], or empty if nobody spoke."""
        if not self.speaking or not self.frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self.frames).astype(np.float32) / 32768.0


def _rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2))) if frame.size else 0.0


# ---- transcription ------------------------------------------------------------------
class Transcriber:
    def __init__(self, model: str = "base.en", device: str = "auto", language: str | None = "en") -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise RuntimeError(INSTALL_HINT) from e
        self.language = language
        self.model: Any = None
        attempts = [("cuda", "float16"), ("cpu", "int8")] if device == "auto" else [(device, "float16" if device == "cuda" else "int8")]
        for dev, compute in attempts:
            try:
                self.model = WhisperModel(model, device=dev, compute_type=compute)
                self._warm_up()
                self.device = dev
                break
            except Exception as e:  # e.g. CUDA libraries missing: fall back to CPU
                log.info("Whisper on %s unavailable (%s)", dev, e)
        if self.model is None:
            raise RuntimeError(f"Couldn't load the Whisper model {model!r}.")
        log.info("Whisper %s ready on %s", model, self.device)

    def _warm_up(self) -> None:
        # Running once surfaces CUDA problems now rather than on the first command.
        list(self.model.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), language=self.language)[0])

    def __call__(self, audio: np.ndarray) -> str:
        if audio.size < SAMPLE_RATE * 0.3:
            return ""
        segments, _ = self.model.transcribe(
            audio, language=self.language, beam_size=1, condition_on_previous_text=False, vad_filter=True,
        )
        # Whisper "hears" phrases like "Thank you." in near-silence; drop low-confidence segments.
        return " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6).strip()
