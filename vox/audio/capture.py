"""Hotkey-gated mic capture. Push-to-talk only (spec Section 8.5): capture
begins on hotkey press, ends on release. No wake word, no always-on
listening. `ChordTracker` and `Recorder` are pure state machines so they're
unit-testable without a real global keyboard listener or microphone."""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable

import numpy as np
import sounddevice as sd
from pynput import keyboard

logger = logging.getLogger("vox.audio.capture")

SAMPLE_RATE = 16000
CHANNELS = 1

_Key = keyboard.Key | keyboard.KeyCode

_MODIFIER_ALIASES: dict[str, frozenset[keyboard.Key]] = {
    "ctrl": frozenset({keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}),
    "alt": frozenset({keyboard.Key.alt_l, keyboard.Key.alt_r}),
    "shift": frozenset({keyboard.Key.shift_l, keyboard.Key.shift_r}),
    "win": frozenset({keyboard.Key.cmd_l, keyboard.Key.cmd_r}),
    "cmd": frozenset({keyboard.Key.cmd_l, keyboard.Key.cmd_r}),
}

_NAMED_KEYS: dict[str, keyboard.Key] = {
    "space": keyboard.Key.space,
    "esc": keyboard.Key.esc,
    "escape": keyboard.Key.esc,
    "tab": keyboard.Key.tab,
    "enter": keyboard.Key.enter,
}


def parse_chord(chord: str) -> list[frozenset[_Key]]:
    """Parse 'ctrl+alt+space' into one acceptable-key-set per token. A chord
    is held when at least one key from every group is currently pressed."""
    groups: list[frozenset[_Key]] = []
    for raw_token in chord.lower().split("+"):
        token = raw_token.strip()
        if not token:
            continue
        if token in _MODIFIER_ALIASES:
            groups.append(_MODIFIER_ALIASES[token])
        elif token in _NAMED_KEYS:
            groups.append(frozenset({_NAMED_KEYS[token]}))
        elif len(token) == 1:
            groups.append(frozenset({keyboard.KeyCode.from_char(token)}))
        else:
            raise ValueError(f"unrecognised hotkey token: {token!r}")
    if not groups:
        raise ValueError(f"empty hotkey: {chord!r}")
    return groups


class ChordTracker:
    """Tracks currently-held keys and reports whether a chord is fully
    held."""

    def __init__(self, groups: list[frozenset[_Key]]) -> None:
        self._groups = groups
        self._held: set[_Key] = set()

    def press(self, key: _Key) -> None:
        self._held.add(key)

    def release(self, key: _Key) -> None:
        self._held.discard(key)

    def is_held(self) -> bool:
        return all(any(k in self._held for k in group) for group in self._groups)

    def is_chord_key(self, key: _Key) -> bool:
        return any(key in group for group in self._groups)


class Recorder:
    """Accumulates mic frames into a buffer until stopped. Wraps
    sounddevice.InputStream so it's mockable in tests."""

    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    def _callback(self, indata: np.ndarray, frames: int, time_info: object, status: object) -> None:
        if status:
            logger.warning("sounddevice status: %s", status)
        with self._lock:
            self._frames.append(indata[:, 0].copy())

    def start(self) -> None:
        with self._lock:
            self._frames = []
        t0 = time.monotonic()
        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=CHANNELS,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
        logger.info("Recorder.start(): stream construct+start took %.3fs", time.monotonic() - t0)

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            n_callbacks = len(self._frames)
            if not self._frames:
                logger.info("Recorder.stop(): 0 callback invocations before stop")
                return np.array([], dtype=np.float32)
            result = np.concatenate(self._frames)
            logger.info(
                "Recorder.stop(): %d callback invocations, %d samples total", n_callbacks, len(result)
            )
            return result


class HotkeyCapture:
    """Wires a pynput global keyboard listener to Recorder: starts
    recording when the configured chord becomes fully held, stops and
    invokes on_recorded(pcm) when any key in the chord is released.

    _on_press/_on_release run on pynput's low-level keyboard hook thread,
    which Windows expects to return near-instantly — a slow hook callback
    can make Windows silently delay or drop events for it. Both callbacks
    therefore only touch the (cheap) ChordTracker and hand real work
    (opening the mic stream, and especially on_recorded — which runs VAD,
    Whisper, and TTS synchronously) to a dedicated worker thread via a
    queue, processed strictly in order so start always completes before
    stop is handled. Found and fixed after live acceptance testing showed
    intermittent 0.00s recordings even on an uncontested hotkey — see
    DECISIONS.md."""

    def __init__(
        self,
        chord: str,
        on_recorded: Callable[[np.ndarray], None],
        sample_rate: int = SAMPLE_RATE,
        on_start: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
    ) -> None:
        self._tracker = ChordTracker(parse_chord(chord))
        self._recorder = Recorder(sample_rate=sample_rate)
        self._on_recorded = on_recorded
        self._on_start = on_start
        self._on_stop = on_stop
        self._recording = False
        self._listener: keyboard.Listener | None = None
        self._work: queue.Queue[str] = queue.Queue()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        self._held_since: float | None = None

    def _worker_loop(self) -> None:
        while True:
            command = self._work.get()
            try:
                if command == "_shutdown":
                    return
                if command == "start":
                    if self._on_start is not None:
                        self._on_start()
                    self._recorder.start()
                elif command == "stop":
                    if self._on_stop is not None:
                        self._on_stop()
                    pcm = self._recorder.stop()
                    self._on_recorded(pcm)
            finally:
                self._work.task_done()

    def _on_press(self, key: _Key | None) -> None:
        if key is None:
            return
        self._tracker.press(key)
        if not self._recording and self._tracker.is_held():
            self._recording = True
            self._held_since = time.monotonic()
            self._work.put("start")

    def _on_release(self, key: _Key | None) -> None:
        if key is None:
            return
        was_relevant = self._recording and self._tracker.is_chord_key(key)
        self._tracker.release(key)
        if was_relevant:
            self._recording = False
            if self._held_since is not None:
                logger.info(
                    "Wall-clock chord hold duration: %.3fs (press-to-release, "
                    "independent of audio frames)",
                    time.monotonic() - self._held_since,
                )
                self._held_since = None
            self._work.put("stop")

    def start(self) -> None:
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self._work.put("_shutdown")
