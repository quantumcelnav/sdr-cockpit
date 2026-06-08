"""Real-time IQ spectrogram — rtl_sdr → FFT → power spectrum frames."""

import subprocess
import threading
import signal
import time
import logging
import numpy as np

log = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 2_048_000
DEFAULT_FFT_SIZE    = 1024
DEFAULT_GAIN        = 'auto'
FRAME_RATE          = 20   # target FFT frames/sec sent to listeners


class SpectrumReceiver:
    def __init__(self):
        self._proc   = None
        self._thread = None
        self._lock   = threading.Lock()
        self._listeners = []   # callables: fn(frame_dict)

        self.center_hz   = 100_000_000
        self.sample_rate = DEFAULT_SAMPLE_RATE
        self.fft_size    = DEFAULT_FFT_SIZE
        self.gain        = DEFAULT_GAIN
        self._running    = False

    # ── public API ────────────────────────────────────────────────────────────

    def tune(self, center_hz: int, sample_rate: int = DEFAULT_SAMPLE_RATE,
             fft_size: int = DEFAULT_FFT_SIZE, gain=DEFAULT_GAIN, device_index: int = 0):
        self.stop()
        self.center_hz   = center_hz
        self.sample_rate = sample_rate
        self.fft_size    = fft_size
        self.gain        = gain
        self._device     = device_index
        self._running    = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        log.info(f"Spectrum RX: {center_hz/1e6:.3f} MHz  SR={sample_rate/1e6:.2f}MS/s  FFT={fft_size}")

    def stop(self):
        self._running = False
        if self._proc:
            try:
                self._proc.send_signal(signal.SIGTERM)
                self._proc.wait(timeout=2)
            except Exception:
                try: self._proc.kill()
                except Exception: pass
            self._proc = None

    def is_active(self):
        return self._running and self._proc is not None and self._proc.poll() is None

    def status(self):
        return {
            'active': self.is_active(),
            'center_hz': self.center_hz,
            'sample_rate': self.sample_rate,
            'fft_size': self.fft_size,
            'gain': self.gain,
            'bandwidth_hz': self.sample_rate,
            'freq_low':  self.center_hz - self.sample_rate // 2,
            'freq_high': self.center_hz + self.sample_rate // 2,
        }

    def add_listener(self, fn):
        self._listeners.append(fn)

    def remove_listener(self, fn):
        if fn in self._listeners:
            self._listeners.remove(fn)

    # ── capture loop ──────────────────────────────────────────────────────────

    def _capture_loop(self):
        """Stream raw uint8 IQ from rtl_sdr, batch into FFT frames."""
        cmd = [
            'rtl_sdr',
            '-f', str(self.center_hz),
            '-s', str(self.sample_rate),
            '-d', str(getattr(self, '_device', 0)),
            '-'
        ]
        if self.gain != 'auto':
            cmd = cmd[:1] + ['-g', str(self.gain)] + cmd[1:]

        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
            )
        except FileNotFoundError:
            log.error("rtl_sdr not found")
            self._running = False
            return

        fft_n   = self.fft_size
        bytes_per_frame = fft_n * 2       # 2 bytes per complex sample (I,Q uint8)
        frame_interval  = 1.0 / FRAME_RATE
        window  = np.hanning(fft_n).astype(np.float32)
        buf     = b''
        last_emit = 0.0

        while self._running and self._proc.poll() is None:
            try:
                chunk = self._proc.stdout.read(bytes_per_frame * 4)
                if not chunk:
                    break
                buf += chunk
                while len(buf) >= bytes_per_frame:
                    raw = np.frombuffer(buf[:bytes_per_frame], dtype=np.uint8).astype(np.float32)
                    buf = buf[bytes_per_frame:]

                    iq = (raw - 127.5) / 127.5
                    I  = iq[0::2]
                    Q  = iq[1::2]
                    if len(I) < fft_n:
                        continue
                    cplx = (I[:fft_n] + 1j * Q[:fft_n]) * window

                    spectrum = np.fft.fftshift(np.fft.fft(cplx))
                    power_db = 20 * np.log10(np.abs(spectrum) / fft_n + 1e-10)

                    now = time.time()
                    if now - last_emit >= frame_interval:
                        last_emit = now
                        frame = {
                            'center_hz':   self.center_hz,
                            'sample_rate': self.sample_rate,
                            'fft_size':    fft_n,
                            'power_db':    power_db.tolist(),
                            'ts':          now,
                        }
                        for fn in list(self._listeners):
                            try: fn(frame)
                            except Exception: pass
            except Exception as e:
                log.warning(f"Spectrum capture error: {e}")
                break

        self._running = False
        log.info("Spectrum RX stopped")
