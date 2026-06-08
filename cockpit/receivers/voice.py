"""Voice receiver — wraps rtl_fm and streams audio to the browser."""

import subprocess
import threading
import logging
import time
import os
import signal

log = logging.getLogger(__name__)

# rtl_fm mode strings
MODE_MAP = {
    'AM':  'am',
    'FM':  'fm',
    'WFM': 'wbfm',
    'USB': 'usb',
    'LSB': 'lsb',
}

AUDIO_SAMPLE_RATE = 16000   # Hz, good enough for voice


class VoiceReceiver:
    def __init__(self):
        self._proc = None
        self._lock = threading.Lock()
        self.current_freq = None
        self.current_mode = None
        self.current_name = None
        self._listeners = []     # callables receiving audio chunks

    def tune(self, freq_hz: int, mode: str = 'FM', squelch: int = -50, gain: str = 'auto', device_index: int = 0):
        self.stop()
        rtl_mode = MODE_MAP.get(mode, 'fm')
        squelch_level = abs(squelch)    # rtl_fm uses positive dB

        cmd = [
            'rtl_fm',
            '-f', str(freq_hz),
            '-M', rtl_mode,
            '-s', str(AUDIO_SAMPLE_RATE),
            '-l', str(squelch_level),
            '-d', str(device_index),
            '-'
        ]
        if gain != 'auto':
            cmd = cmd[:1] + ['-g', str(gain)] + cmd[1:]

        log.info(f"Tuning to {freq_hz/1e6:.4f} MHz {mode} squelch={squelch} dB")
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        self.current_freq = freq_hz
        self.current_mode = mode

        self._reader = threading.Thread(target=self._read_audio, daemon=True)
        self._reader.start()

    def stop(self):
        if self._proc:
            try:
                self._proc.send_signal(signal.SIGTERM)
                self._proc.wait(timeout=2)
            except Exception:
                self._proc.kill()
            self._proc = None
        self.current_freq = None
        self.current_mode = None

    def is_active(self):
        return self._proc is not None and self._proc.poll() is None

    def status(self):
        return {
            'active': self.is_active(),
            'freq': self.current_freq,
            'mode': self.current_mode,
            'name': self.current_name,
        }

    def add_listener(self, fn):
        self._listeners.append(fn)

    def remove_listener(self, fn):
        self._listeners.remove(fn)

    def _read_audio(self):
        CHUNK = 4096
        while self._proc and self._proc.poll() is None:
            try:
                data = self._proc.stdout.read(CHUNK)
                if data:
                    for fn in list(self._listeners):
                        try:
                            fn(data)
                        except Exception:
                            pass
            except Exception:
                break
