"""Detect connected SDR hardware and return the matching profile."""

import subprocess
import yaml
import os
import logging

log = logging.getLogger(__name__)

PROFILES_DIR = os.path.join(os.path.dirname(__file__), '..', 'hardware', 'profiles')

SIGNATURES = [
    ('RTL-SDR Blog V4',   'rtlsdr_v4'),
    ('RTL-SDR Blog V3',   'rtlsdr_v3'),
    ('Airspy Mini',       'airspy_mini'),
    ('HackRF',            'hackrf'),
    ('SDRplay',           'sdrplay'),
]


def detect():
    """Run rtl_test, match against known hardware signatures, return profile dict."""
    try:
        result = subprocess.run(
            ['rtl_test', '-t'],
            capture_output=True, text=True, timeout=5
        )
        output = result.stdout + result.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired):
        log.warning("rtl_test not found or timed out — no SDR hardware detected")
        return None

    for sig, profile_name in SIGNATURES:
        if sig in output:
            return _load_profile(profile_name)

    if 'Found' in output and 'device' in output.lower():
        log.warning("Unknown RTL-SDR device — using generic profile")
        return _generic_profile()

    return None


def _load_profile(name):
    path = os.path.join(PROFILES_DIR, f'{name}.yaml')
    if not os.path.exists(path):
        log.warning(f"Profile {name} not found at {path}")
        return _generic_profile()
    with open(path) as f:
        return yaml.safe_load(f)


def _generic_profile():
    return {
        'id': 'generic_rtlsdr',
        'name': 'Generic RTL-SDR',
        'freq_min_hz': 24000000,
        'freq_max_hz': 1766000000,
        'stable_sample_rate': 2048000,
        'hw_tier': 1,
        'concurrent_receivers': 1,
        'supported_modes': ['AM', 'FM', 'WFM'],
    }
