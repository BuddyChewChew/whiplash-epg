#!/usr/bin/env python3
"""
Whiplash EPG + M3U generator.

Pulls live ErsatzTV XMLTV feeds from whiplash.cc, extracts only the channels
we care about, remaps their ids to stable local ids, and emits:
  - epg.xml      (merged XMLTV guide for all 6 known channels)
  - playlist.m3u (static playlist with tvg-id values filled in)

No external deps beyond `requests`. Designed to run on GitHub Actions.
"""

import re
import sys
import requests
import xml.etree.ElementTree as ET

WL_URL = "https://whiplash.cc/scheds/wl.xml"
WIN_URL = "https://whiplash.cc/scheds/win.xml"

# Stable local tvg-ids we control, mapped from the source XML's channel id.
# source_id -> (local_tvg_id, display_name, m3u_group, source)
CHANNEL_MAP = {
    "C1.1.146.ersatztv.org":  ("whiplash",        "WHIPLASH",          "whiplash", "wl"),
    "C2.1.147.ersatztv.org":  ("whiplash2",        "WHIPLASH 2",        "whiplash", "wl"),
    "C3.1.148.ersatztv.org":  ("whiplashcinema",   "WHIPLASH CINEMA",   "whiplash", "wl"),
    "C7.151.ersatztv.org":    ("whiplashatlas",    "WHIPLASH ATLAS",    "whiplash", "wl"),
    "C11.194.ersatztv.org":   ("whiplashplutotv",  "WHIPLASH PLUTO TV", "whiplash", "wl"),
    "C3.147.ersatztv.org":    ("whiplashwindowtv", "WHIPLASH WINDOW TV","whiplash", "win"),
}

# Logos taken from the existing m3u (kept stable rather than scraped each run)
LOGOS = {
    "whiplash":         "https://whiplash.cc/assets/img/channels/whiplash.png",
    "whiplash2":        "https://whiplash.cc/assets/img/channels/whiplash2.png",
    "whiplashcinema":   "https://whiplash.cc/assets/img/channels/whiplashcinema.png",
    "whiplashatlas":    "https://whiplash.cc/assets/img/channels/atlas.png",
    "whiplashplutotv":  "https://whiplash.cc/assets/img/channels/whiplash.png",
    "whiplashwindowtv": "https://whiplash.cc/assets/img/channels/windowtv.png",
}

STREAM_URLS = {
    "whiplash":         "https://cdn.whiplash.cc/whiplash/index.m3u8",
    "whiplash2":        "https://cdn.whiplash.cc/whiplash-2/index.m3u8",
    "whiplashcinema":   "https://cdn.whiplash.cc/whiplash-cinema/index.m3u8",
    "whiplashatlas":    "https://cdn.whiplash.cc/whiplash-atlas/index.m3u8",
    "whiplashplutotv":  "https://cdn.whiplash.cc/whiplash-pluto/index.m3u8",
    "whiplashwindowtv": "https://cdn.whiplash.cc/whiplash-windowtv/index.m3u8",
}

EPG_OUTPUT = "epg.xml"
M3U_OUTPUT = "playlist.m3u"
EPG_RAW_URL = "https://raw.githubusercontent.com/REPLACE_WITH_YOUR_REPO/main/epg.xml"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WhiplashEPGBot/1.0)"}


def fetch_xml(url: str) -> ET.Element:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    # Strip BOM/whitespace quirks before parsing
    text = resp.content.decode("utf-8-sig", errors="replace")
    return ET.fromstring(text)


def build_epg(wl_root: ET.Element, win_root: ET.Element) -> ET.Element:
    tv = ET.Element("tv", {"generator-info-name": "whiplash-epg-generator"})

    sources = {"wl": wl_root, "win": win_root}

    # Write <channel> blocks first, in CHANNEL_MAP order, using local ids
    for source_id, (local_id, display_name, group, source) in CHANNEL_MAP.items():
        chan_el = ET.SubElement(tv, "channel", {"id": local_id})
        name_el = ET.SubElement(chan_el, "display-name")
        name_el.text = display_name
        if local_id in LOGOS:
            ET.SubElement(chan_el, "icon", {"src": LOGOS[local_id]})

    # Copy over <programme> blocks, rewriting channel= to the local id
    for source_id, (local_id, display_name, group, source) in CHANNEL_MAP.items():
        root = sources[source]
        for prog in root.findall("programme"):
            if prog.get("channel") != source_id:
                continue
            new_prog = ET.fromstring(ET.tostring(prog))
            new_prog.set("channel", local_id)
            tv.append(new_prog)

    return tv


def build_m3u() -> str:
    lines = [f'#EXTM3U url-tvg="{EPG_RAW_URL}"', ""]
    # Keep playlist order matching the original upload
    order = ["whiplash", "whiplash2", "whiplashatlas", "whiplashcinema", "whiplashwindowtv"]
    display = {
        "whiplash": "WHIPLASH",
        "whiplash2": "WHIPLASH 2",
        "whiplashatlas": "WHIPLASH ATLAS",
        "whiplashcinema": "WHIPLASH CINEMA",
        "whiplashwindowtv": "WHIPLASH WINDOW TV",
    }
    for local_id in order:
        logo = LOGOS[local_id]
        name = display[local_id]
        stream = STREAM_URLS[local_id]
        lines.append(
            f'#EXTINF:-1 group-title="whiplash" tvg-id="{local_id}" tvg-logo="{logo}",{name}'
        )
        lines.append(stream)
    return "\n".join(lines) + "\n"


def indent(elem, level=0):
    # Minimal pretty-printer (avoids needing lxml)
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        for child in elem:
            indent(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = i + "  "
        if not elem[-1].tail or not elem[-1].tail.strip():
            elem[-1].tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


def main():
    print(f"Fetching {WL_URL} ...")
    wl_root = fetch_xml(WL_URL)
    print(f"Fetching {WIN_URL} ...")
    win_root = fetch_xml(WIN_URL)

    tv = build_epg(wl_root, win_root)
    indent(tv)
    tree = ET.ElementTree(tv)
    tree.write(EPG_OUTPUT, encoding="UTF-8", xml_declaration=True)
    print(f"Wrote {EPG_OUTPUT}")

    m3u_text = build_m3u()
    with open(M3U_OUTPUT, "w", encoding="utf-8") as f:
        f.write(m3u_text)
    print(f"Wrote {M3U_OUTPUT}")

    # Sanity report
    n_progs = len(tv.findall("programme"))
    n_chans = len(tv.findall("channel"))
    print(f"Channels: {n_chans}, programmes: {n_progs}")


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        print(f"ERROR fetching source XML: {e}", file=sys.stderr)
        sys.exit(1)
