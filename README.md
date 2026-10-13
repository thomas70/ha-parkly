# Parkly for Home Assistant

Shows how many spaces are in use in your company's **Parkly agreement parking**
(«Avtaleparkering») — one set of sensors per zone.

Unofficial. Read-only. Built with Claude.

## What you get

For each agreement zone on your Parkly account (numbered 1, 2, … in id order):

| Sensor | Example |
|---|---|
| `sensor.parkly_sone1_benyttet` | `7` spaces in use (attributes: parking lot, areas, company) |
| `sensor.parkly_sone1_ledige` | `18` free |
| `sensor.parkly_sone1_antall` | `25` spaces in total |
| `sensor.parkly_sone1_displaynavn` | `7/25` |
| `sensor.parkly_sone1_navn` | `Avtaleparkering: Sone 1 & 3` |

Polling: by default every minute on weekdays 07:00–17:00, otherwise every 15 minutes.
Change it under Settings → Devices & services → Parkly → Configure (interval during and
outside working hours, when working hours start and end, and whether weekends count).

## How it logs in

Parkly uses Azure AD B2C. The integration logs in with your e-mail and password using
plain HTTP (no browser), keeps the tokens in memory, renews them by itself and logs in
again when needed. If the password changes, Home Assistant asks you to re-authenticate.

## Install

1. HACS → ⋮ → Custom repositories → add this repository as type *Integration*.
2. Install **Parkly** and restart Home Assistant.
3. Settings → Devices & services → Add integration → **Parkly**, and sign in.

## Development

```
python -m pytest
```
