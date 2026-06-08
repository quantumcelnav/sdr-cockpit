"""Antenna sweep — wraps rtl_power for wideband frequency response characterization."""

import subprocess
import threading
import tempfile
import csv
import os
import json
import time
import logging
from datetime import datetime

log = logging.getLogger(__name__)

SWEEPS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'sweeps')


class AntennaSweeeper:
    def __init__(self):
        self._proc    = None
        self._thread  = None
        self._running = False
        self.progress = 0.0       # 0.0–1.0
        self.status   = 'idle'    # idle | running | done | error
        self.current  = None      # most recent completed sweep result dict
        self._outfile = None

    # ── public API ────────────────────────────────────────────────────────────

    def start(self, freq_low_hz: int, freq_high_hz: int, bin_hz: int = 100_000,
              gain: float = 40.0, integration_sec: int = 5,
              total_sec: int = 30, label: str = ''):
        if self._running:
            return {'ok': False, 'error': 'Sweep already running'}

        os.makedirs(SWEEPS_DIR, exist_ok=True)
        self._outfile = tempfile.mktemp(suffix='.csv')
        self._label   = label or f'sweep_{datetime.now().strftime("%H%M%S")}'
        self._meta    = {
            'label':           self._label,
            'freq_low_hz':     freq_low_hz,
            'freq_high_hz':    freq_high_hz,
            'bin_hz':          bin_hz,
            'gain':            gain,
            'integration_sec': integration_sec,
            'total_sec':       total_sec,
            'started_at':      datetime.utcnow().isoformat(),
        }
        self.progress = 0.0
        self.status   = 'running'

        cmd = [
            'rtl_power',
            '-f', f'{freq_low_hz}:{freq_high_hz}:{bin_hz}',
            '-g', str(gain),
            '-i', str(integration_sec),
            '-e', str(total_sec),
            self._outfile
        ]
        log.info(f"Sweep: {freq_low_hz/1e6:.1f}–{freq_high_hz/1e6:.1f} MHz  bin={bin_hz/1e3:.0f}kHz  {total_sec}s")
        self._running = True
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._thread = threading.Thread(target=self._monitor, args=(total_sec,), daemon=True)
        self._thread.start()
        return {'ok': True, 'label': self._label}

    def stop(self):
        self._running = False
        if self._proc:
            try: self._proc.terminate(); self._proc.wait(timeout=2)
            except Exception: pass
            self._proc = None
        self.status = 'idle'

    def get_status(self):
        return {
            'status':   self.status,
            'progress': round(self.progress, 2),
            'label':    getattr(self, '_label', ''),
        }

    def get_result(self):
        return self.current

    def list_saved(self):
        os.makedirs(SWEEPS_DIR, exist_ok=True)
        out = []
        for fn in sorted(os.listdir(SWEEPS_DIR)):
            if fn.endswith('.json'):
                try:
                    with open(os.path.join(SWEEPS_DIR, fn)) as f:
                        meta = json.load(f).get('meta', {})
                    out.append({'filename': fn, **meta})
                except Exception:
                    pass
        return out

    def load_saved(self, filename: str):
        path = os.path.join(SWEEPS_DIR, filename)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def save_current(self, label: str = ''):
        if not self.current:
            return {'ok': False, 'error': 'No completed sweep'}
        if label:
            self.current['meta']['label'] = label
        slug = label.lower().replace(' ', '_') or self.current['meta']['label']
        ts   = datetime.now().strftime('%Y%m%d_%H%M%S')
        fn   = f'{ts}_{slug}.json'
        path = os.path.join(SWEEPS_DIR, fn)
        os.makedirs(SWEEPS_DIR, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(self.current, f)
        log.info(f"Sweep saved: {fn}")
        return {'ok': True, 'filename': fn}

    # ── internals ─────────────────────────────────────────────────────────────

    def _monitor(self, total_sec):
        start = time.time()
        while self._running and self._proc.poll() is None:
            elapsed = time.time() - start
            self.progress = min(0.99, elapsed / total_sec)
            time.sleep(0.5)

        self._running = False
        if self._proc and self._proc.returncode == 0 or os.path.exists(self._outfile or ''):
            try:
                self.current = self._parse_csv(self._outfile, self._meta)
                self.status  = 'done'
                self.progress = 1.0
                log.info(f"Sweep complete: {len(self.current.get('freqs', []))} bins")
            except Exception as e:
                log.error(f"Sweep parse error: {e}")
                self.status = 'error'
        else:
            self.status = 'error'

        if self._outfile and os.path.exists(self._outfile):
            os.unlink(self._outfile)
            self._outfile = None

    @staticmethod
    def _parse_csv(path, meta):
        """Parse rtl_power CSV into {meta, freqs, power_db} averaged across all integration periods."""
        bins = {}   # freq_hz -> list of dB values

        with open(path, newline='') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 7:
                    continue
                try:
                    hz_low  = float(row[2])
                    hz_high = float(row[3])
                    hz_step = float(row[4])
                    n_vals  = int(row[5])
                    dbs     = [float(v) for v in row[6:6+n_vals] if v.strip()]
                    for i, db in enumerate(dbs):
                        freq = hz_low + hz_step * i
                        bins.setdefault(freq, []).append(db)
                except (ValueError, IndexError):
                    continue

        if not bins:
            raise ValueError("No data parsed from sweep CSV")

        freqs    = sorted(bins.keys())
        power_db = [sum(bins[f]) / len(bins[f]) for f in freqs]

        return {
            'meta':     meta,
            'freqs':    freqs,
            'power_db': power_db,
        }
