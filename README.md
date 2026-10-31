# c12n Apps — AltStore / Feather Source

The official source for every iOS app by **c12n Apps**, for **Feather** and **AltStore**.

## Add the source

**Source URL:**

```
https://c12nfeather.07051969.xyz/source.json
```

- **Feather:** Sources → + → paste the URL — or open this link on your iPhone: `feather://source?url=https://c12nfeather.07051969.xyz/source.json`
- **AltStore:** Sources → + → paste the URL — or: `altstore://source?url=https://c12nfeather.07051969.xyz/source.json`
- Landing page with the full app list: https://c12nfeather.07051969.xyz

Fallback URL (same file, via GitHub Pages): https://c12n.github.io/c12nfeather/source.json

## Apps in this source

| App | What it is |
|---|---|
| Al Rashid Prayer | AlRashid Mosque Edmonton prayer times, widgets and Live Activity |
| DATS Edmonton | Edmonton's DATS paratransit, in a big-type, high-contrast app |
| Viu Live TV | Live TV from Viu, natively on iOS |
| Matcha Music | Multi-server (Subsonic / Jellyfin / Plex) and on-device music player |
| Tap Tap Phoenix | The rhythm game, remade for iOS 26 / 27 |
| RetroPhone | iPhone OS 3.1.3 and iOS 4.2.1, emulated on modern iPhones |
| S5LBox | Boot real iPhone OS 3 / iOS 4 in an app |
| Tether | Share your iPhone internet over WireGuard |
| Calculator | A modern SwiftUI calculator |
| Fastfetch | Neofetch-style system info for iPhone |

## How auto-update works

A GitHub Action in this repo runs **every hour** (and on demand). It checks the
latest GitHub Release of every app repo listed in `apps_config.json`, and
rebuilds `source.json` with the newest version, download URL, size, release
notes, bundle ID and minimum iOS version — extracting fresh metadata and icons
from the IPA itself whenever a new release appears (cached in
`metadata_cache.json`, so big IPAs are only downloaded once per release).

Ship a new app version the usual way — publish a GitHub Release with the IPA
attached — and it shows up in Feather / AltStore on its own within the hour.
To add a brand-new app to the source, add one entry to `apps_config.json`.

Two apps — **Al Rashid Prayer** and **DATS Edmonton** — live in private
repos, so their release downloads are not public. Their current IPAs are
hosted in this repo under `ipas/` (served at
`https://c12nfeather.07051969.xyz/ipas/…`) and pinned as `hosted` entries in
`apps_config.json`; the generator carries them into the source unchanged.
Refreshing one means replacing its file in `ipas/` and updating its pinned
version, size and date in the config.

All IPAs are unsigned sideload builds. Install them with your own certificate
in Feather, or your Apple ID in AltStore.

Copyright (c) 2026 c12n Apps
