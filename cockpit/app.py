#!/usr/bin/env python3
"""SDR Cockpit — Phase 1.0: ADS-B + Voice + Frequency Book."""

import json
import os
import time
import logging
import threading
import queue
from flask import Flask, jsonify, request, Response, stream_with_context

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cockpit import hw_detect
from cockpit.receivers.adsb import ADSBReceiver
from cockpit.receivers.voice import VoiceReceiver

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__, template_folder='ui/templates', static_folder='ui/static')

# ── Globals ──────────────────────────────────────────────────────────────────
FREQBOOK_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'frequencies', 'fort_collins.json')
hw_profile = None
adsb = ADSBReceiver()
voice = VoiceReceiver()
audio_listeners = []   # SSE queues for /stream/audio


def load_freqbook():
    with open(FREQBOOK_PATH) as f:
        return json.load(f)


# ── Startup ───────────────────────────────────────────────────────────────────
def startup():
    global hw_profile
    hw_profile = hw_detect.detect()
    if hw_profile:
        log.info(f"Hardware: {hw_profile['name']} (Tier {hw_profile.get('hw_tier',1)})")
        adsb.start()
    else:
        log.warning("No SDR hardware detected — running in demo mode")


# ── Audio broadcast ───────────────────────────────────────────────────────────
def _audio_broadcast(chunk):
    dead = []
    for q in audio_listeners:
        try:
            q.put_nowait(chunk)
        except Exception:
            dead.append(q)
    for q in dead:
        audio_listeners.remove(q)


voice.add_listener(_audio_broadcast)


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return app.send_static_file('index.html')


@app.route('/api/hw')
def api_hw():
    return jsonify(hw_profile or {'name': 'No hardware', 'hw_tier': 0})


@app.route('/api/freqbook')
def api_freqbook():
    return jsonify(load_freqbook())


@app.route('/api/adsb')
def api_adsb():
    return jsonify({'aircraft': adsb.get_aircraft(), 'ts': time.time()})


@app.route('/api/voice/status')
def api_voice_status():
    return jsonify(voice.status())


@app.route('/api/voice/tune', methods=['POST'])
def api_voice_tune():
    data = request.json
    freq = int(data.get('freq', 0))
    mode = data.get('mode', 'FM')
    squelch = int(data.get('squelch', -50))
    name = data.get('name', '')

    if not freq:
        return jsonify({'ok': False, 'error': 'No frequency'})
    if hw_profile is None:
        return jsonify({'ok': False, 'error': 'No SDR hardware detected'})
    if freq > hw_profile.get('freq_max_hz', 1766e6):
        return jsonify({'ok': False, 'error': f"Frequency exceeds hardware max ({hw_profile['freq_max_hz']/1e6:.0f} MHz)"})

    voice.current_name = name
    voice.tune(freq, mode, squelch)
    return jsonify({'ok': True, 'freq': freq, 'mode': mode, 'name': name})


@app.route('/api/voice/stop', methods=['POST'])
def api_voice_stop():
    voice.stop()
    return jsonify({'ok': True})


@app.route('/stream/audio')
def stream_audio():
    """Raw PCM audio stream — 16 kHz mono signed 16-bit little-endian."""
    q = queue.Queue(maxsize=50)
    audio_listeners.append(q)

    def generate():
        try:
            while True:
                try:
                    chunk = q.get(timeout=5)
                    yield chunk
                except queue.Empty:
                    yield b''   # keep-alive
        finally:
            if q in audio_listeners:
                audio_listeners.remove(q)

    return Response(
        stream_with_context(generate()),
        mimetype='audio/raw',
        headers={
            'X-Sample-Rate': '16000',
            'X-Channels': '1',
            'X-Bit-Depth': '16',
            'Cache-Control': 'no-cache',
        }
    )


@app.route('/api/adsb/stream')
def adsb_stream():
    """Server-Sent Events stream of ADS-B updates."""
    def generate():
        last = {}
        while True:
            aircraft = adsb.get_aircraft()
            current = {a['icao']: a for a in aircraft}
            # Send full state every 2s
            data = json.dumps({'aircraft': aircraft, 'ts': time.time()})
            yield f"data: {data}\n\n"
            time.sleep(2)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


if __name__ == '__main__':
    startup()
    print("\n  SDR COCKPIT starting on http://localhost:5556\n")
    app.run(host='127.0.0.1', port=5556, debug=False, threaded=True)
