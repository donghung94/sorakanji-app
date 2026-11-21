#!/usr/bin/env python3
"""Native-build asset URL transform for SoraKanji Capacitor (iOS).

The PWA loads ALL data (kanji/vocab/grammar/exam JS, images, audio, ONNX
model) from relative "assets/..." paths next to mobile/index.html. The
native app bundle ships ONLY www/index.html (no assets/ folder), so those
relative paths resolve to capacitor://localhost/assets/... which does not
exist -> every section hangs on "Dang tai du lieu..." forever.

Fix: rewrite every "assets/ reference in the NATIVE www/index.html to the
absolute githack URL of the live PWA assets. The app then downloads data
from the server exactly like the PWA does (WKWebView caches it after the
first load). The app already needs network for YouTube + Firebase, so this
adds no new requirement.

Usage: python3 apply-native-asset-urls.py [path/to/index.html]
Default target: www/index.html next to this script.
Idempotent: the replacement text contains no '"assets/' substring, so
re-running changes nothing.
"""
import sys
from pathlib import Path

BASE = "https://raw.githack.com/donghung94/beta2.0/main/mobile/assets/"

def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent / "www" / "index.html"
    )
    text = target.read_text(encoding="utf-8")
    n = text.count('"assets/')
    if n == 0:
        print(f"{target}: no relative asset refs left (already transformed)")
        return
    text = text.replace('"assets/', f'"{BASE}')
    target.write_text(text, encoding="utf-8")
    print(f"{target}: rewrote {n} asset refs to {BASE}")

if __name__ == "__main__":
    main()
