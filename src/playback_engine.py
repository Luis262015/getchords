"""
Real-time multitrack audio playback engine using sounddevice.
Mixes N stems with per-stem volume, pan, mute, and solo in the callback thread.
Supports variable playback speed (with linear interpolation) and A-B loop.
VU peak levels are written to shared numpy arrays for UI polling.
"""

import math
import threading
import numpy as np
from typing import Dict, Optional, Callable, Tuple

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False


BLOCK_SIZE = 512       # frames per callback (~11.6 ms at 44100 Hz)
PEAK_DECAY = 0.92      # peak level decay per block


class PlaybackEngine:
    def __init__(self):
        self._stems: Dict[str, np.ndarray] = {}    # name → (frames, 2) float32
        self._params: Dict[str, dict] = {}          # name → {volume, pan, muted, soloed}
        self._samplerate: int = 44100
        self._total_frames: int = 0

        # Fractional source position (supports variable speed)
        self._frac_pos: float = 0.0
        self._speed: float = 1.0

        # A-B loop points (in source frames, None = not set)
        self._loop_a: Optional[int] = None
        self._loop_b: Optional[int] = None

        self._playing: bool = False
        self._stream: Optional['sd.OutputStream'] = None
        self._lock = threading.Lock()

        # Peak levels per stem: [left, right]  float32 (UI polls these)
        self.peak_levels: Dict[str, np.ndarray] = {}
        self.master_peak: np.ndarray = np.zeros(2, dtype=np.float32)

        self._on_finished: Optional[Callable] = None

    # ── Public API ───────────────────────────────────────────────────

    @property
    def position(self) -> int:
        return int(self._frac_pos)

    @property
    def total_frames(self) -> int:
        return self._total_frames

    @property
    def samplerate(self) -> int:
        return self._samplerate

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def position_seconds(self) -> float:
        return self._frac_pos / max(1, self._samplerate)

    @property
    def duration_seconds(self) -> float:
        return self._total_frames / max(1, self._samplerate)

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def loop_points(self) -> Tuple[Optional[int], Optional[int]]:
        return (self._loop_a, self._loop_b)

    def set_speed(self, speed: float):
        with self._lock:
            self._speed = max(0.25, min(2.0, float(speed)))

    def set_loop_a(self, frame: int):
        with self._lock:
            self._loop_a = max(0, min(frame, max(0, self._total_frames - 1)))

    def set_loop_b(self, frame: int):
        with self._lock:
            self._loop_b = max(0, min(frame, max(0, self._total_frames - 1)))

    def clear_loop(self):
        with self._lock:
            self._loop_a = None
            self._loop_b = None

    def load_stems(self, stems: Dict[str, np.ndarray], samplerate: int):
        was_playing = self._playing
        if was_playing:
            self.stop()

        with self._lock:
            self._stems = dict(stems)
            self._samplerate = samplerate
            self._total_frames = max((len(a) for a in stems.values()), default=0)
            self._frac_pos = 0.0
            self._loop_a = None
            self._loop_b = None

            for name in stems:
                if name not in self._params:
                    self._params[name] = {
                        'volume': 1.0,
                        'pan': 0.0,
                        'muted': False,
                        'soloed': False,
                    }
                self.peak_levels.setdefault(name, np.zeros(2, dtype=np.float32))

            for name in list(self._params):
                if name not in stems:
                    del self._params[name]
            for name in list(self.peak_levels):
                if name not in stems:
                    del self.peak_levels[name]

    def set_param(self, stem: str, key: str, value):
        with self._lock:
            if stem in self._params:
                self._params[stem][key] = value

    def get_param(self, stem: str, key: str, default=None):
        return self._params.get(stem, {}).get(key, default)

    def get_all_params(self) -> Dict[str, dict]:
        with self._lock:
            return {k: dict(v) for k, v in self._params.items()}

    def play(self, from_frame: Optional[int] = None):
        if not self._stems or not SOUNDDEVICE_AVAILABLE:
            return
        if from_frame is not None:
            self._frac_pos = float(max(0, min(from_frame, self._total_frames - 1)))
        if int(self._frac_pos) >= self._total_frames:
            self._frac_pos = 0.0

        self._close_stream()
        self._playing = True
        self._stream = sd.OutputStream(
            samplerate=self._samplerate,
            channels=2,
            dtype='float32',
            blocksize=BLOCK_SIZE,
            callback=self._audio_callback,
            finished_callback=self._stream_finished,
        )
        self._stream.start()

    def pause(self):
        self._playing = False
        if self._stream:
            try:
                self._stream.stop()
            except Exception:
                pass

    def stop(self):
        self._playing = False
        self._close_stream()
        self._frac_pos = 0.0

    def seek(self, frame: int):
        was_playing = self._playing
        if was_playing:
            self.pause()
        self._frac_pos = float(max(0, min(frame, self._total_frames - 1)))
        if was_playing:
            self.play()

    def seek_seconds(self, seconds: float):
        self.seek(int(seconds * self._samplerate))

    def set_on_finished(self, cb: Callable):
        self._on_finished = cb

    def cleanup(self):
        self.stop()

    # ── Audio callback (runs in PortAudio thread) ─────────────────────

    def _audio_callback(self, outdata: np.ndarray, frames: int, time_info, status):
        _stop = False
        with self._lock:
            frac_pos = self._frac_pos
            speed    = self._speed
            total    = self._total_frames
            loop_a   = self._loop_a
            loop_b   = self._loop_b
            loop_active = (loop_a is not None and loop_b is not None
                           and loop_b > loop_a)

            if frac_pos >= total or not self._stems:
                outdata.fill(0)
                return

            # Fractional source positions for every output frame
            src = frac_pos + np.arange(frames, dtype=np.float64) * speed

            # Wrap positions that exceed loop_b back into [loop_a, loop_b)
            if loop_active:
                loop_len = float(loop_b - loop_a)
                over = src >= loop_b
                if over.any():
                    src[over] = loop_a + (src[over] - loop_b) % loop_len
                valid = np.ones(frames, dtype=bool)
            else:
                valid = src < total

            # Safe integer indices + fractional part for linear interpolation
            src_c = np.clip(src, 0.0, float(total - 1))
            idx0  = src_c.astype(np.int64)
            frac  = (src_c - idx0).astype(np.float32)
            idx1  = np.minimum(idx0 + 1, total - 1)

            mixed = np.zeros((frames, 2), dtype=np.float32)
            any_soloed = any(p.get('soloed', False) for p in self._params.values())

            for name, audio in self._stems.items():
                params = self._params.get(name)
                if params is None:
                    continue
                if params['muted']:
                    self.peak_levels[name][:] = 0.0
                    continue
                if any_soloed and not params['soloed']:
                    self.peak_levels[name][:] = 0.0
                    continue

                # Linear interpolation between consecutive samples
                chunk = (audio[idx0] * (1.0 - frac[:, None])
                         + audio[idx1] * frac[:, None])

                if not valid.all():
                    chunk[~valid] = 0.0

                vol   = float(params['volume'])
                pan   = float(params['pan'])
                angle = (pan + 1.0) * (math.pi / 4.0)
                l_g   = vol * math.cos(angle)
                r_g   = vol * math.sin(angle)

                mixed[:, 0] += chunk[:, 0] * l_g
                mixed[:, 1] += chunk[:, 1] * r_g

                pk = self.peak_levels[name]
                vc = chunk[valid] if not valid.all() else chunk
                if len(vc):
                    pk[0] = max(pk[0] * PEAK_DECAY,
                                float(np.max(np.abs(vc[:, 0]))) * vol)
                    pk[1] = max(pk[1] * PEAK_DECAY,
                                float(np.max(np.abs(vc[:, 1]))) * vol)
                else:
                    pk[0] *= PEAK_DECAY
                    pk[1] *= PEAK_DECAY

            np.clip(mixed, -1.0, 1.0, out=mixed)
            outdata[:] = mixed

            self.master_peak[0] = float(np.max(np.abs(mixed[:, 0])))
            self.master_peak[1] = float(np.max(np.abs(mixed[:, 1])))

            # Advance fractional position
            next_frac = frac_pos + frames * speed
            if loop_active:
                loop_len = float(loop_b - loop_a)
                if next_frac >= loop_b:
                    next_frac = loop_a + (next_frac - loop_b) % loop_len
            self._frac_pos = next_frac

            if not loop_active and next_frac >= total:
                _stop = True

        if _stop:
            self._playing = False
            raise sd.CallbackStop()

    def _stream_finished(self):
        self._playing = False
        if self._on_finished:
            self._on_finished()

    def _close_stream(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
