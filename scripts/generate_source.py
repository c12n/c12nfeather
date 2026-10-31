#!/usr/bin/env python3
"""
generate_source.py — builds the c12n Apps AltStore / Feather source.

Reads apps_config.json, asks the GitHub API for the latest releases of each
listed repo, extracts bundle ID / version / minimum OS / icon from the newest
IPA when it changes (cached in metadata_cache.json so large IPAs are only
downloaded once per release), and writes source.json + apps.json.

No GitHub token is required for public repos. If GITHUB_TOKEN is set it is
used (higher rate limits, and required if a listed repo is private — note a
public source can only link to publicly downloadable IPAs).

Copyright (c) 2026 c12n Apps
"""
import io
import json
import os
import plistlib
import re
import sys
import urllib.request
import zipfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "apps_config.json")
CACHE = os.path.join(ROOT, "metadata_cache.json")
ICONS_DIR = os.path.join(ROOT, "icons")

GITHUB_API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()


def gh_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "c12nfeather-source-generator",
        "Accept": "application/vnd.github+json",
        **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def download(url, dest=None, limit=None):
    req = urllib.request.Request(url, headers={"User-Agent": "c12nfeather-source-generator"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read(limit) if limit else r.read()
    if dest:
        with open(dest, "wb") as f:
            f.write(data)
    return data


# ---------- CgBI (Apple-crushed PNG) -> standard PNG ----------
def fix_cgbi(data):
    """Convert an iOS CgBI PNG to a standard PNG. Returns None if not CgBI."""
    if not data.startswith(b"\x89PNG"):
        return None
    if b"CgBI" not in data[:64]:
        return data  # already a standard PNG
    try:
        from PIL import Image
        pos = 8
        idat = bytearray()
        ihdr = None
        chunks = []
        while pos < len(data):
            ln = int.from_bytes(data[pos:pos + 4], "big")
            typ = data[pos + 4:pos + 8]
            chunk = data[pos + 8:pos + 8 + ln]
            if typ == b"IHDR":
                ihdr = chunk
            elif typ == b"IDAT":
                idat += chunk
            elif typ not in (b"CgBI",):
                chunks.append((typ, chunk))
            pos += 12 + ln
            if typ == b"IEND":
                break
        if ihdr is None:
            return None
        w = int.from_bytes(ihdr[0:4], "big")
        h = int.from_bytes(ihdr[4:8], "big")
        bit_depth, color_type = ihdr[8], ihdr[9]
        if bit_depth != 8 or color_type != 6:
            return None
        raw = zlib.decompress(bytes(idat), -zlib.MAX_WBITS)
        stride = w * 4 + 1
        px = bytearray(w * h * 4)
        prev = bytearray(w * 4)
        for y in range(h):
            row = raw[y * stride + 1:(y + 1) * stride]
            filt = raw[y * stride]
            cur = bytearray(row)
            if filt == 1:
                for i in range(4, len(cur)):
                    cur[i] = (cur[i] + cur[i - 4]) & 0xFF
            elif filt == 2:
                for i in range(len(cur)):
                    cur[i] = (cur[i] + prev[i]) & 0xFF
            elif filt == 3:
                for i in range(len(cur)):
                    a = cur[i - 4] if i >= 4 else 0
                    cur[i] = (cur[i] + ((a + prev[i]) >> 1)) & 0xFF
            elif filt == 4:
                for i in range(len(cur)):
                    a = cur[i - 4] if i >= 4 else 0
                    b = prev[i]
                    c = prev[i - 4] if i >= 4 else 0
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                    cur[i] = (cur[i] + pr) & 0xFF
            # BGRA premultiplied -> RGBA straight
            for x in range(w):
                i = (y * w + x) * 4
                b, g, r, a = cur[i], cur[i + 1], cur[i + 2], cur[i + 3]
                if a == 0:
                    px[i:i + 4] = b"\x00\x00\x00\x00"
                elif a == 255:
                    px[i:i + 4] = bytes((r, g, b, a))
                else:
                    px[i:i + 4] = bytes((
                        min(255, r * 255 // a), min(255, g * 255 // a),
                        min(255, b * 255 // a), a))
            prev = cur
        img = Image.frombytes("RGBA", (w, h), bytes(px))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
    except Exception as e:
        print(f"  CgBI fix failed: {e}", file=sys.stderr)
        return None


def extract_ipa_metadata(ipa_path):
    """Return (metadata dict, icon png bytes or None) from an IPA file."""
    meta = {}
    icon = None
    with zipfile.ZipFile(ipa_path) as z:
        names = z.namelist()
        infos = [n for n in names if re.match(r"Payload/[^/]+\.app/Info\.plist$", n)]
        if not infos:
            return meta, None
        info = plistlib.loads(z.read(infos[0]))
        meta = {
            "bundleIdentifier": info.get("CFBundleIdentifier", ""),
            "name": info.get("CFBundleDisplayName") or info.get("CFBundleName", ""),
            "version": str(info.get("CFBundleShortVersionString", "")),
            "buildVersion": str(info.get("CFBundleVersion", "")),
            "minOSVersion": str(info.get("MinimumOSVersion", "")),
        }
        appdir = infos[0].rsplit("/", 1)[0] + "/"
        cands = []
        for n in names:
            rest = n[len(appdir):] if n.startswith(appdir) else ""
            if rest and "/" not in rest and rest.lower().endswith(".png") and "icon" in rest.lower():
                cands.append((z.getinfo(n).file_size, n))
        cands.sort(reverse=True)
        for _, n in cands:
            fixed = fix_cgbi(z.read(n))
            if fixed:
                icon = fixed
                break
    return meta, icon


def tag_version(tag):
    return tag[1:] if tag.lower().startswith("v") and len(tag) > 1 and tag[1].isdigit() else tag


def main():
    with open(CONFIG) as f:
        config = json.load(f)
    src_cfg = config["source"]
    base = src_cfg["baseURL"].rstrip("/")

    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            cache = json.load(f)

    apps_out = []
    news_out = []
    featured = []

    for app in config["apps"]:
        repo = app["repo"]
        owner = app.get("owner", "c12n")
        print(f"== {repo}")

        # Hosted apps: the IPA lives in this repo (ipas/) because the app's
        # own repo is private, so GitHub release downloads are not public.
        # All metadata is pinned in apps_config.json under "hosted".
        hosted = app.get("hosted")
        if hosted:
            icon_path = f"icons/{repo}.png"
            icon_url = f"{base}/{icon_path}" if os.path.exists(os.path.join(ROOT, icon_path)) else ""
            ver = {
                "version": hosted["version"],
                "buildVersion": hosted.get("buildVersion", hosted["version"]),
                "date": hosted["date"],
                "localizedDescription": hosted.get("versionDescription", f"{app['name']} {hosted['version']}"),
                "downloadURL": f"{base}/{hosted['downloadPath']}",
                "size": hosted["size"],
                **({"minOSVersion": hosted["minOSVersion"]} if hosted.get("minOSVersion") else {}),
            }
            apps_out.append({
                "name": app["name"],
                "bundleIdentifier": hosted["bundleIdentifier"],
                "developerName": "c12n Apps",
                "subtitle": app.get("subtitle", ""),
                "localizedDescription": app["description"],
                "iconURL": icon_url,
                "tintColor": app.get("tintColor", src_cfg["tintColor"]),
                "category": app.get("category", "utilities"),
                "versions": [ver],
                "version": ver["version"],
                "versionDate": ver["date"],
                "versionDescription": ver["localizedDescription"],
                "downloadURL": ver["downloadURL"],
                "size": ver["size"],
                **({"minOSVersion": hosted["minOSVersion"]} if hosted.get("minOSVersion") else {}),
                "beta": False,
                "appPermissions": {"entitlements": [], "privacy": {}},
            })
            featured.append(hosted["bundleIdentifier"])
            news_out.append({
                "identifier": f"{hosted['bundleIdentifier']}-{ver['version']}",
                "title": f"{app['name']} {ver['version']} is out",
                "caption": f"Update {app['name']} to version {ver['version']}.",
                "date": ver["date"],
                "tintColor": app.get("tintColor", src_cfg["tintColor"]),
                "imageURL": icon_url,
                "notify": False,
                "appID": hosted["bundleIdentifier"],
            })
            print(f"  ok (hosted): {app['name']} {ver['version']}")
            continue
        try:
            releases = gh_json(f"{GITHUB_API}/repos/{owner}/{repo}/releases?per_page=30")
        except Exception as e:
            print(f"  ! release fetch failed: {e}", file=sys.stderr)
            continue

        excl = tuple(app.get("excludeTagPrefixes", []))
        ipa_releases = []
        for rel in releases:
            if rel.get("draft") or rel.get("prerelease"):
                continue
            if excl and rel["tag_name"].startswith(excl):
                continue
            ipas = [a for a in rel["assets"] if a["name"].lower().endswith(".ipa")]
            if ipas:
                ipa_releases.append((rel, ipas[0]))
        if not ipa_releases:
            print("  ! no IPA releases, skipped", file=sys.stderr)
            continue
        if app.get("onlyLatest"):
            ipa_releases = ipa_releases[:1]

        latest_rel, latest_asset = ipa_releases[0]
        key = repo
        cached = cache.get(key, {})

        # Refresh extracted metadata only when the latest tag changed.
        if cached.get("tag") != latest_rel["tag_name"] or not cached.get("bundleIdentifier"):
            tmp = f"/tmp/{repo}-latest.ipa"
            try:
                print(f"  downloading {latest_asset['name']} ({latest_asset['size']} B) for metadata…")
                download(latest_asset["browser_download_url"], tmp)
                meta, icon = extract_ipa_metadata(tmp)
                if meta.get("bundleIdentifier"):
                    cached.update(meta)
                    cached["tag"] = latest_rel["tag_name"]
                    cache[key] = cached
                if icon:
                    os.makedirs(ICONS_DIR, exist_ok=True)
                    with open(os.path.join(ICONS_DIR, f"{repo}.png"), "wb") as f:
                        f.write(icon)
                    print("  icon refreshed from IPA")
            except Exception as e:
                print(f"  ! metadata extraction failed: {e}", file=sys.stderr)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)

        bundle_id = cached.get("bundleIdentifier") or app.get("bundleIdentifier", "")
        if not bundle_id:
            print("  ! no bundle identifier known, skipped", file=sys.stderr)
            continue

        versions = []
        for rel, asset in ipa_releases:
            ver = tag_version(rel["tag_name"])
            if rel["tag_name"] == cached.get("tag") and cached.get("version"):
                ver = cached["version"]
            versions.append({
                "version": ver,
                "buildVersion": cached.get("buildVersion", "") if rel["tag_name"] == cached.get("tag") else ver,
                "date": rel["published_at"],
                "localizedDescription": (rel.get("body") or "").strip() or f"{app['name']} {ver}",
                "downloadURL": asset["browser_download_url"],
                "size": asset["size"],
                **({"minOSVersion": cached["minOSVersion"]} if cached.get("minOSVersion") else {}),
            })

        latest = versions[0]
        icon_path = f"icons/{repo}.png"
        icon_url = f"{base}/{icon_path}" if os.path.exists(os.path.join(ROOT, icon_path)) else ""
        apps_out.append({
            "name": app["name"],
            "bundleIdentifier": bundle_id,
            "developerName": "c12n Apps",
            "subtitle": app.get("subtitle", ""),
            "localizedDescription": app["description"],
            "iconURL": icon_url,
            "tintColor": app.get("tintColor", src_cfg["tintColor"]),
            "category": app.get("category", "utilities"),
            "versions": versions,
            # Legacy top-level fields for older AltStore / Feather versions:
            "version": latest["version"],
            "versionDate": latest["date"],
            "versionDescription": latest["localizedDescription"],
            "downloadURL": latest["downloadURL"],
            "size": latest["size"],
            **({"minOSVersion": cached["minOSVersion"]} if cached.get("minOSVersion") else {}),
            "beta": False,
            "appPermissions": {"entitlements": [], "privacy": {}},
        })
        featured.append(bundle_id)
        news_out.append({
            "identifier": f"{bundle_id}-{latest['version']}",
            "title": f"{app['name']} {latest['version']} is out",
            "caption": f"Update {app['name']} to version {latest['version']}.",
            "date": latest["date"],
            "tintColor": app.get("tintColor", src_cfg["tintColor"]),
            "imageURL": icon_url,
            "notify": False,
            "appID": bundle_id,
        })
        print(f"  ok: {app['name']} {latest['version']} ({bundle_id})")

    source = {
        "name": src_cfg["name"],
        "identifier": src_cfg["identifier"],
        "subtitle": src_cfg["subtitle"],
        "description": src_cfg["description"],
        "iconURL": f"{base}/icons/source-icon.png",
        # NOTE: no "headerURL" key at all. Feather's AltSourceKit decodes
        # headerURL as a URL with `try`, so an empty string makes the WHOLE
        # source fail to parse ("isn't in the correct format"). Omit, never "".
        "website": src_cfg["website"],
        "tintColor": src_cfg["tintColor"],
        "featuredApps": featured,
        "apps": apps_out,
        "news": news_out,
    }

    for fname in ("source.json", "apps.json"):
        with open(os.path.join(ROOT, fname), "w") as f:
            json.dump(source, f, indent=2, ensure_ascii=False)
            f.write("\n")
    with open(CACHE, "w") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\nWrote source with {len(apps_out)} apps.")


if __name__ == "__main__":
    main()
