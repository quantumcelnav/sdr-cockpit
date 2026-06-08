# SDR Cockpit — Design Document

**Owner:** Justin Fritz  
**Location:** Fort Collins, CO  
**Hardware baseline:** RTL-SDR Blog V4 (Rafael Micro R828D, 500 kHz–1766 MHz)  
**Started:** 2026-06-08

---

## Vision

A self-hosted web cockpit that puts full situational awareness of the RF environment in one browser tab. Tunable presets for every operationally useful channel in the FoCo area, live ADS-B aircraft tracking, voice receive with squelch, and a hardware capability matrix that grows as new SDR hardware is added. Each hardware upgrade unlocks new capability tiers tracked in this document and integrated as a discrete module.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Browser (UI)                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │  ADS-B   │ │  Voice   │ │  Scan    │ │  DF /  │ │
│  │  Panel   │ │  Panel   │ │  Panel   │ │ Drone  │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────┘ │
└───────────────────┬─────────────────────────────────┘
                    │ WebSocket + REST
┌───────────────────▼─────────────────────────────────┐
│              Flask Backend (cockpit/app.py)           │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │  ReceiverMgr │  │  FreqBook    │  │  HWDetect │  │
│  └──────┬───────┘  └──────────────┘  └───────────┘  │
│         │                                            │
│  ┌──────▼──────────────────────────────────────┐    │
│  │              Hardware Abstraction Layer       │    │
│  │  RTLSDRReceiver  |  HackRFReceiver  |  ...   │    │
│  └──────┬──────────────────────────────────────-┘    │
└─────────┼───────────────────────────────────────────┘
          │ subprocess
┌─────────▼───────────────────────────────────────────┐
│         System Tools                                  │
│  dump1090  │  rtl_fm  │  rtl_power  │  op25          │
└─────────────────────────────────────────────────────┘
```

### Key design decisions

- **subprocess, not GnuRadio python bindings** — rtl_fm and dump1090 are battle-tested. GnuRadio is the upgrade path for DSP work (DF, drone detect) but not needed for voice + ADS-B.
- **WebSocket for streaming** — audio, ADS-B updates, signal level all stream over a single WS connection to the browser.
- **Hardware profiles as YAML** — each hardware tier is a YAML file describing frequency range, sample rate caps, and which receiver modules it supports. HWDetect reads `rtl_test` output and selects the correct profile at startup.
- **FreqBook is local JSON** — frequency presets are a simple JSON file. User-editable, version-controlled.

---

## Hardware Tiers

### Tier 1 — RTL-SDR Blog V4 ✅ (current)
**Hardware:** RTL-SDR Blog V4, R828D tuner, SN 00000001  
**Range:** ~500 kHz – 1766 MHz (HF via direct sampling)  
**Sample rate:** up to 3.2 MS/s (stable: 2.048 MS/s)  
**Limitation:** single-channel receive only — cannot do ADS-B + voice simultaneously

Unlocks:
- [x] ADS-B aircraft tracking (1090 MHz via dump1090)
- [x] FM voice receive — ATC, NOAA, CTAF, fire/police conventional FM
- [x] NOAA weather radio
- [x] HF with direct sampling (ham bands, WSPR, shortwave)
- [x] APRS decode (144.390 MHz)
- [x] Frequency scanner (rtl_power)
- [ ] P25 digital voice (needs op25 integration — Phase 1.5)

### Tier 2 — Add second RTL-SDR dongle
**Hardware:** Any RTL-SDR (V3 or V4)  
**Cost:** ~$30  
**Unlock:** Parallel receive — ADS-B on dongle 0 dedicated, voice/scan on dongle 1 simultaneously

Unlocks:
- [ ] Always-on ADS-B + concurrent voice receive
- [ ] Dual-watch (two voice channels simultaneously)
- [ ] APRS + ADS-B concurrent

### Tier 3 — Airspy Mini or HackRF One
**Hardware:** Airspy Mini (~$99) or HackRF One (~$340)  
**Unlock:** Higher dynamic range, wider instantaneous bandwidth (HackRF: 20 MHz)

Unlocks:
- [ ] Wideband spectrum survey
- [ ] Drone RF detection (2.4 GHz out of range — needs separate hardware)
- [ ] Better P25 decode reliability

### Tier 4 — Wideband drone detection array
**Hardware:** Wi-Fi SDR or dedicated 2.4/5.8 GHz receiver  
**Hardware options:** XHDATA D-808, HackRF + upconverter, or SDRplay RSP1A  
**Unlock:** Drone RF fingerprinting at 2.4/5.8 GHz (DJI OcuSync, Mavic, etc.)

Unlocks:
- [ ] Drone RF detect (2.4 GHz DJI, 5.8 GHz FPV)
- [ ] Signal classification (drone vs WiFi vs BT)

### Tier 5 — Direction Finding array
**Hardware:** 4-element Doppler DF antenna (e.g. Arrow Antenna or DIY)  
**Software:** Modified rtl_fm + bearing algorithm  
**Unlock:** Bearing to any transmitter

Unlocks:
- [ ] Doppler DF bearing display on map
- [ ] Drone bearing + range estimation
- [ ] APRS mobile station tracking

---

## Frequency Book — Fort Collins, CO

### Aviation (AM, 8.33 kHz or 25 kHz steps)
| Name | Freq (MHz) | Mode | Notes |
|------|-----------|------|-------|
| FNL Tower | 118.700 | AM | Northern Colorado Regional Airport |
| FNL Ground | 121.800 | AM | |
| FNL ATIS | 120.275 | AM | Recorded weather/notices |
| FNL UNICOM | 122.800 | AM | General aviation advisory |
| Denver Approach (N) | 124.000 | AM | FNL area approach |
| Denver Center | 132.750 | AM | En-route, varies by sector |
| Guard | 121.500 | AM | Emergency, always monitor |
| CTAF / FNL | 122.800 | AM | Pattern traffic |
| Boulder Muni Tower | 119.750 | AM | KBDU |

### ADS-B
| Name | Freq (MHz) | Mode | Notes |
|------|-----------|------|-------|
| ADS-B Mode S | 1090.000 | ADS-B | dump1090, all commercial aircraft |
| UAT (ADS-B 978) | 978.000 | UAT | GA aircraft, weather uplink — needs Tier 2 |

### Public Safety (Larimer County)
| Name | Freq (MHz) | Mode | Notes |
|------|-----------|------|-------|
| Larimer Co Sheriff | 855.9875 | P25 | Trunked P25 Phase I, control channel |
| Larimer Fire Dispatch | 856.9875 | P25 | Trunked |
| FC Police Dispatch | 857.9875 | P25 | Trunked |
| EMS / LCSO | 858.9875 | P25 | Trunked |
| NOAA Weather WXJ28 | 162.400 | WFM | Primary for Fort Collins |
| NOAA Weather backup | 162.550 | WFM | Boulder/Denver |
| Wildfire Air-to-Ground | 168.625 | FM | NIFC standard |
| CAP Colorado Wing | 148.150 | FM | Civil Air Patrol |

### Amateur / APRS
| Name | Freq (MHz) | Mode | Notes |
|------|-----------|------|-------|
| APRS National | 144.390 | FM | 1200 baud AFSK |
| FoCo 2m Repeater | 146.940 | FM | -0.6 offset, 100 Hz PL |
| FoCo 70cm Repeater | 447.925 | FM | -5 offset |
| ISS Downlink | 145.800 | FM | When overhead |

### Drone / UAS RF
| Name | Freq (MHz) | Mode | Notes |
|------|-----------|------|-------|
| DJI OcuSync 2/3 | 2400 | Spread | Tier 4 hardware required |
| DJI FPV | 5800 | Spread | Tier 4 hardware required |
| 433 MHz RC | 433.920 | OOK/FSK | Hobby drones, RTL-SDR V4 covers |
| 915 MHz RC | 915.000 | FHSS | FrSky, ExpressLRS |
| Remote ID (FAA) | 2400/5800 | WiFi | Broadcast Remote ID (Tier 4) |

---

## Module Specifications

### ADS-B Receiver (`cockpit/receivers/adsb.py`)
- Wraps `dump1090 --net --quiet`
- Reads Beast binary format from TCP port 30002
- Parses: ICAO, callsign, lat/lon, altitude, speed, heading, squawk
- Maintains live aircraft dict with 60-second TTL
- Streams updates to WebSocket `/ws/adsb`

### Voice Receiver (`cockpit/receivers/voice.py`)
- Wraps `rtl_fm` with configurable frequency, mode (AM/FM), squelch
- Pipes audio to browser via chunked HTTP audio stream
- Presets: select from FreqBook
- AM mode for aviation (ATC), FM for public safety / NOAA

### Scanner (`cockpit/receivers/scanner.py`)
- Wraps `rtl_power` for spectrum survey
- Configurable range, step, dwell
- Outputs signal-level heatmap to frontend

### P25 Decoder (`cockpit/decoders/p25.py`) — Phase 1.5
- Wraps `op25` (GnuRadio-based)
- Trunked P25 Phase I: follows control channel, decodes voice
- Larimer County trunking system profile

### APRS Decoder (`cockpit/decoders/aprs.py`)
- `rtl_fm 144.390 | multimon-ng -t raw -a AFSK1200`
- Parses APRS frames: position, weather, messages
- Plots mobile stations on map panel

---

## UI Panels

### ADS-B Panel
- Leaflet.js map centered on FNL (40.4519° N, 105.0113° W)
- Aircraft icons with heading vectors
- Click aircraft → callsign, altitude, speed, squawk, track history
- Emergency squawk highlight: 7500 (hijack), 7600 (comms loss), 7700 (emergency)

### Voice Panel
- Frequency preset list (FreqBook)
- One-click tune
- Squelch slider
- Audio volume
- TX history (timestamps when squelch opened)

### Spectrum Panel
- Lightweight waterfall using Canvas (no heavy deps)
- rtl_power JSON feed
- Clickable to tune voice receiver to that frequency

### DF / Bearing Panel (Tier 5)
- Compass rose overlay on map
- Bearing line from home QTH
- Multiple bearings → triangulation

---

## Development Phases

| Phase | Milestone | Hardware |
|-------|-----------|----------|
| 1.0 | ADS-B + NOAA weather + AM voice (ATC) | RTL-SDR V4 |
| 1.5 | P25 decode for Larimer County public safety | RTL-SDR V4 + op25 |
| 2.0 | Parallel receive (ADS-B always-on + voice) | + 2nd RTL-SDR |
| 2.5 | APRS decode + map | RTL-SDR V4 |
| 3.0 | HackRF wideband waterfall | + HackRF One |
| 4.0 | 433/915 MHz drone RF detect | RTL-SDR V4 |
| 4.5 | 2.4/5.8 GHz drone detect + Remote ID | + wideband hw |
| 5.0 | Doppler DF bearing | + antenna array |
