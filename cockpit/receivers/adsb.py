"""ADS-B receiver — wraps dump1090 and parses its SBS-1 TCP output."""

import socket
import threading
import subprocess
import time
import logging

log = logging.getLogger(__name__)

DUMP1090_HOST = '127.0.0.1'
DUMP1090_SBS_PORT = 30003   # SBS-1 BaseStation format (text, easy to parse)
AIRCRAFT_TTL = 60           # seconds before dropping a silent aircraft


class Aircraft:
    def __init__(self, icao):
        self.icao = icao
        self.callsign = ''
        self.lat = None
        self.lon = None
        self.altitude = None
        self.speed = None
        self.heading = None
        self.squawk = None
        self.on_ground = False
        self.last_seen = time.time()

    def update(self, **kwargs):
        for k, v in kwargs.items():
            if v is not None and v != '':
                setattr(self, k, v)
        self.last_seen = time.time()

    def to_dict(self):
        return {
            'icao': self.icao,
            'callsign': self.callsign.strip(),
            'lat': self.lat,
            'lon': self.lon,
            'altitude': self.altitude,
            'speed': self.speed,
            'heading': self.heading,
            'squawk': self.squawk,
            'on_ground': self.on_ground,
            'last_seen': self.last_seen,
            'emergency': self.squawk in ('7500', '7600', '7700'),
        }


class ADSBReceiver:
    def __init__(self):
        self.aircraft = {}
        self._lock = threading.Lock()
        self._dump1090_proc = None
        self._reader_thread = None
        self._running = False

    def start(self):
        self._start_dump1090()
        time.sleep(2)
        self._running = True
        self._reader_thread = threading.Thread(target=self._read_sbs, daemon=True)
        self._reader_thread.start()
        self._reaper_thread = threading.Thread(target=self._reap_stale, daemon=True)
        self._reaper_thread.start()
        log.info("ADS-B receiver started")

    def stop(self):
        self._running = False
        if self._dump1090_proc:
            self._dump1090_proc.terminate()

    def get_aircraft(self):
        with self._lock:
            return [a.to_dict() for a in self.aircraft.values()]

    def _start_dump1090(self):
        try:
            # Check if already running
            s = socket.socket()
            s.connect((DUMP1090_HOST, DUMP1090_SBS_PORT))
            s.close()
            log.info("dump1090 already running, attaching")
            return
        except ConnectionRefusedError:
            pass
        cmd = ['dump1090', '--net', '--quiet', '--no-fix']
        self._dump1090_proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        log.info(f"Started dump1090 PID {self._dump1090_proc.pid}")

    def _read_sbs(self):
        while self._running:
            try:
                with socket.socket() as s:
                    s.connect((DUMP1090_HOST, DUMP1090_SBS_PORT))
                    s.settimeout(5.0)
                    buf = b''
                    while self._running:
                        try:
                            chunk = s.recv(4096)
                            if not chunk:
                                break
                            buf += chunk
                            while b'\n' in buf:
                                line, buf = buf.split(b'\n', 1)
                                self._parse_sbs(line.decode('ascii', errors='ignore').strip())
                        except socket.timeout:
                            continue
            except Exception as e:
                log.warning(f"SBS read error: {e}, retrying in 3s")
                time.sleep(3)

    def _parse_sbs(self, line):
        # SBS-1 format: MSG,<type>,<fields...>
        if not line.startswith('MSG,'):
            return
        parts = line.split(',')
        if len(parts) < 11:
            return
        icao = parts[4].upper()
        if not icao:
            return

        with self._lock:
            if icao not in self.aircraft:
                self.aircraft[icao] = Aircraft(icao)
            ac = self.aircraft[icao]

        msg_type = parts[1]
        def f(i):
            return parts[i] if i < len(parts) else ''

        if msg_type == '1':
            ac.update(callsign=f(10))
        elif msg_type == '2':
            ac.update(altitude=_int(f(11)), speed=_float(f(12)),
                      heading=_float(f(13)), on_ground=f(21)=='1')
        elif msg_type == '3':
            ac.update(altitude=_int(f(11)), lat=_float(f(14)),
                      lon=_float(f(15)), on_ground=f(21)=='1')
        elif msg_type == '4':
            ac.update(speed=_float(f(12)), heading=_float(f(13)))
        elif msg_type == '6':
            ac.update(squawk=f(17))

    def _reap_stale(self):
        while self._running:
            time.sleep(10)
            cutoff = time.time() - AIRCRAFT_TTL
            with self._lock:
                stale = [k for k, v in self.aircraft.items() if v.last_seen < cutoff]
                for k in stale:
                    del self.aircraft[k]


def _int(s):
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _float(s):
    try:
        return float(s)
    except (ValueError, TypeError):
        return None
