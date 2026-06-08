#!/usr/bin/env python3
"""SDR Cockpit — Phase 1.1: ADS-B + Voice + Spectrogram + Antenna Sweep."""

import json
import os
import sys
import time
import logging
import queue
import threading
from flask import Flask, jsonify, request, Response, stream_with_context

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cockpit import hw_detect
from cockpit.receivers.adsb import ADSBReceiver
from cockpit.receivers.voice import VoiceReceiver
from cockpit.receivers.spectrum import SpectrumReceiver
from cockpit.receivers.sweep import AntennaSweeeper
from cockpit.training.trainer import training_bp

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__, template_folder='ui/templates', static_folder='ui/static')
app.register_blueprint(training_bp)

FREQBOOK_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'frequencies', 'fort_collins.json')

hw_profile  = None
adsb        = ADSBReceiver()
voice       = VoiceReceiver()
spectrum    = SpectrumReceiver()
sweeper     = AntennaSweeeper()
audio_q_list  = []   # SSE queues for /stream/audio
spectrum_q_list = []  # SSE queues for /stream/spectrum


def load_freqbook():
    with open(FREQBOOK_PATH) as f:
        return json.load(f)


def startup():
    global hw_profile
    hw_profile = hw_detect.detect()
    if hw_profile:
        log.info(f"Hardware: {hw_profile['name']} (Tier {hw_profile.get('hw_tier',1)})")
        adsb.start()
    else:
        log.warning("No SDR hardware — demo mode")


# ── Audio fan-out ─────────────────────────────────────────────────────────────
def _audio_fanout(chunk):
    dead = []
    for q in audio_q_list:
        try: q.put_nowait(chunk)
        except Exception: dead.append(q)
    for q in dead: audio_q_list.remove(q)

voice.add_listener(_audio_fanout)


# ── Spectrum fan-out ──────────────────────────────────────────────────────────
def _spectrum_fanout(frame):
    dead = []
    for q in spectrum_q_list:
        try: q.put_nowait(frame)
        except Exception: dead.append(q)
    for q in dead: spectrum_q_list.remove(q)

spectrum.add_listener(_spectrum_fanout)


# ═══════════════════════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return app.send_static_file('index.html')


# ── Hardware ──────────────────────────────────────────────────────────────────
@app.route('/api/hw')
def api_hw():
    return jsonify(hw_profile or {'name': 'No hardware', 'hw_tier': 0})


# ── Freq book ─────────────────────────────────────────────────────────────────
@app.route('/api/freqbook')
def api_freqbook():
    return jsonify(load_freqbook())


# ── ADS-B ─────────────────────────────────────────────────────────────────────
@app.route('/api/adsb')
def api_adsb():
    return jsonify({'aircraft': adsb.get_aircraft(), 'ts': time.time()})


@app.route('/api/adsb/stream')
def adsb_stream():
    def generate():
        while True:
            data = json.dumps({'aircraft': adsb.get_aircraft(), 'ts': time.time()})
            yield f"data: {data}\n\n"
            time.sleep(2)
    return Response(stream_with_context(generate()),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


# ── Voice ─────────────────────────────────────────────────────────────────────
@app.route('/api/voice/status')
def api_voice_status():
    return jsonify(voice.status())


@app.route('/api/voice/tune', methods=['POST'])
def api_voice_tune():
    d = request.json
    freq = int(d.get('freq', 0))
    mode = d.get('mode', 'FM')
    squelch = int(d.get('squelch', -50))
    name = d.get('name', '')
    if not freq:
        return jsonify({'ok': False, 'error': 'No frequency'})
    if hw_profile is None:
        return jsonify({'ok': False, 'error': 'No SDR hardware'})
    if freq > hw_profile.get('freq_max_hz', 1766e6):
        return jsonify({'ok': False, 'error': f"Exceeds hardware max {hw_profile['freq_max_hz']/1e6:.0f} MHz"})
    # All three compete for the single USB device — stop everything first
    if spectrum.is_active():
        spectrum.stop()
    if sweeper.status == 'running':
        sweeper.stop()
    adsb.pause_device()
    voice.current_name = name
    voice.tune(freq, mode, squelch)
    return jsonify({'ok': True, 'freq': freq, 'mode': mode, 'name': name})


@app.route('/api/voice/stop', methods=['POST'])
def api_voice_stop():
    voice.stop()
    adsb.resume_device()
    return jsonify({'ok': True})


@app.route('/stream/audio')
def stream_audio():
    q = queue.Queue(maxsize=60)
    audio_q_list.append(q)
    def generate():
        try:
            while True:
                try: yield q.get(timeout=5)
                except queue.Empty: yield b''
        finally:
            if q in audio_q_list: audio_q_list.remove(q)
    return Response(stream_with_context(generate()), mimetype='audio/raw',
                    headers={'X-Sample-Rate':'16000','X-Channels':'1',
                             'X-Bit-Depth':'16','Cache-Control':'no-cache'})


# ── Spectrum ──────────────────────────────────────────────────────────────────
@app.route('/api/spectrum/status')
def api_spectrum_status():
    return jsonify(spectrum.status())


@app.route('/api/spectrum/tune', methods=['POST'])
def api_spectrum_tune():
    d = request.json
    center_hz   = int(d.get('center_hz', 100_000_000))
    sample_rate = int(d.get('sample_rate', 2_048_000))
    fft_size    = int(d.get('fft_size', 1024))
    gain        = d.get('gain', 'auto')

    if hw_profile is None:
        return jsonify({'ok': False, 'error': 'No SDR hardware'})
    if center_hz > hw_profile.get('freq_max_hz', 1766e6):
        return jsonify({'ok': False, 'error': 'Frequency out of range'})

    # Single device — stop everything else, then pause dump1090
    if voice.is_active():   voice.stop()
    if sweeper.status == 'running': sweeper.stop()
    adsb.pause_device()

    spectrum.tune(center_hz, sample_rate, fft_size, gain)
    return jsonify({'ok': True, **spectrum.status()})


@app.route('/api/spectrum/stop', methods=['POST'])
def api_spectrum_stop():
    spectrum.stop()
    adsb.resume_device()
    return jsonify({'ok': True})


@app.route('/stream/spectrum')
def stream_spectrum():
    """SSE stream of FFT power frames — one JSON object per frame."""
    q = queue.Queue(maxsize=30)
    spectrum_q_list.append(q)
    def generate():
        try:
            while True:
                try:
                    frame = q.get(timeout=5)
                    yield f"data: {json.dumps(frame)}\n\n"
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            if q in spectrum_q_list: spectrum_q_list.remove(q)
    return Response(stream_with_context(generate()), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


# ── Antenna sweep ─────────────────────────────────────────────────────────────
@app.route('/api/sweep/start', methods=['POST'])
def api_sweep_start():
    d = request.json
    if hw_profile is None:
        return jsonify({'ok': False, 'error': 'No SDR hardware'})
    if voice.is_active():  voice.stop()
    if spectrum.is_active(): spectrum.stop()

    adsb.pause_device()    # free USB before rtl_power opens it

    result = sweeper.start(
        freq_low_hz=int(d.get('freq_low_hz', 50_000_000)),
        freq_high_hz=int(d.get('freq_high_hz', 1_200_000_000)),
        bin_hz=int(d.get('bin_hz', 100_000)),
        gain=float(d.get('gain', 40.0)),
        integration_sec=int(d.get('integration_sec', 5)),
        total_sec=int(d.get('total_sec', 30)),
        label=d.get('label', ''),
        on_done=adsb.resume_device,   # restart dump1090 when sweep finishes
    )
    return jsonify(result)


@app.route('/api/sweep/stop', methods=['POST'])
def api_sweep_stop():
    sweeper.stop()
    adsb.resume_device()
    return jsonify({'ok': True})


@app.route('/api/sweep/status')
def api_sweep_status():
    return jsonify(sweeper.get_status())


@app.route('/api/sweep/result')
def api_sweep_result():
    r = sweeper.get_result()
    if not r:
        return jsonify({'ok': False, 'error': 'No sweep result available'})
    return jsonify({'ok': True, **r})


@app.route('/api/sweep/save', methods=['POST'])
def api_sweep_save():
    label = request.json.get('label', '')
    return jsonify(sweeper.save_current(label))


@app.route('/api/sweep/profiles')
def api_sweep_profiles():
    return jsonify(sweeper.list_saved())


@app.route('/api/sweep/load/<filename>')
def api_sweep_load(filename):
    if '..' in filename or '/' in filename:
        return jsonify({'ok': False, 'error': 'Invalid filename'}), 400
    data = sweeper.load_saved(filename)
    if not data:
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    return jsonify({'ok': True, **data})


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    startup()
    print("\n  SDR COCKPIT  http://localhost:5556\n")
    app.run(host='127.0.0.1', port=5556, debug=False, threaded=True)
