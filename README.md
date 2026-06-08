# SDR Cockpit

Personal SDR command center for Fort Collins, CO. Web UI for ADS-B aircraft tracking, voice receive (ATC/NOAA/public safety), and a frequency book tuned to the local RF environment. Built to grow with hardware.

## Current hardware: RTL-SDR Blog V4 (Tier 1)

```
brew install librtlsdr dump1090
pip3 install flask pyyaml --break-system-packages
python3 cockpit/app.py
```

Open `http://localhost:5556`

## Hardware tiers

| Tier | Hardware | Unlocks |
|------|----------|---------|
| 1 | RTL-SDR Blog V4 ✅ | ADS-B, AM/FM voice, NOAA, scanner |
| 1.5 | RTL-SDR V4 + op25 | P25 digital voice (Larimer County) |
| 2 | + 2nd RTL-SDR | Parallel ADS-B + voice |
| 3 | + HackRF One | Wideband waterfall |
| 4 | + wideband hw | 2.4/5.8 GHz drone detect |
| 5 | + DF antenna array | Doppler direction finding |

See [docs/DESIGN.md](docs/DESIGN.md) for full architecture and phase plan.

## Frequency coverage (Fort Collins)

- FNL Tower/Ground/ATIS/UNICOM
- Denver Approach + Center
- NOAA Weather WXJ28 162.400
- Larimer County Sheriff/Fire/PD/EMS (P25 — Tier 1.5)
- APRS 144.390
- 433/915 MHz drone RC links
- ISS downlink
