#!/usr/bin/env python3
"""BridgePlayer transform for the SoraKanji Capacitor (iOS/Android) wrap.

WHY: the native app runs on capacitor://localhost, which YouTube's IFrame
player rejects with error 153 ("Video player configuration error"). The
native build therefore plays YouTube video through a bridge page served
from a real https origin (yt-bridge.html on raw.githack.com) and drives it
via postMessage. BridgePlayer mimics the YT.Player methods the app uses,
so the karaoke/shadowing code does not change.

WHAT THIS DOES (applied to a COPY of mobile/index.html at wrap time --
never to the live beta2.0 file):
  A. Inserts the BridgePlayer block (YT_BRIDGE_URL, YT_BRIDGE_ORIGIN,
     isNativeApp(), BridgePlayer) right before `function svLoadPlayer`.
     BridgePlayer is a faithful port of the old native build
     (donghung94/sorakanji-app @39bd25b www/index.html lines 9860-9913),
     plus destroy() -- live now calls sv2Player.destroy() when a lesson
     closes -- and an onError passthrough (the bridge page already posts
     {t:"error"}; the old player ignored it).
  B. Kanji story-video facade: on native, load the bridge URL with
     autoplay instead of the direct youtube-nocookie embed.
  C. svLoadPlayer create(): on native, build a BridgePlayer (host
     "youtube") instead of YT.Player.
  D. sv2LoadPlayer create(): on native, build a BridgePlayer (host
     "nocookie") instead of YT.Player.
  E. Both player-load guards: on native, create() immediately (no need
     to wait for the YouTube IFrame API script, which the bridge page
     loads itself on its own https origin).

PWA SAFETY: every new code path is gated on isNativeApp(), which is true
only when window.Capacitor exists. On the web the transformed file behaves
exactly like the original (verified: the only diff hunks are the ones
listed above).

DEPENDENCY (not bundled -- must stay hosted on https): yt-bridge.html
must remain reachable at
  https://raw.githack.com/donghung94/sorakanji-app/main/www/yt-bridge.html
Do NOT copy it into www/ -- served from capacitor:// it would hit the
same error 153 it exists to avoid. A reference copy lives next to this
script (yt-bridge.html); if the sorakanji-app repo ever moves, update
YT_BRIDGE_URL / YT_BRIDGE_ORIGIN here.

Usage: python3 apply-bridgeplayer.py [path/to/index.html]
Default target: www/index.html next to this script.
Idempotent: re-running on an already transformed file changes nothing
(the BRIDGEPLAYER-TRANSFORM marker is detected first).
Fails closed: if any anchor is missing or appears an unexpected number of
times, nothing is written and the script exits non-zero.
"""
import sys
from pathlib import Path

MARKER = "BRIDGEPLAYER-TRANSFORM"

BRIDGE_BLOCK = """  /* NATIVE-ONLY [BRIDGEPLAYER-TRANSFORM]: YouTube IFrame API loi 153 tren origin
     capacitor://, nen ban native phat video qua trang cau noi https (yt-bridge.html
     tren githack) bang postMessage. BridgePlayer bat chuoc dung cac method cua
     YT.Player ma app dung (play/pause/seek/getCurrentTime/getDuration/
     getPlayerState/setPlaybackRate/destroy) nen code karaoke khong doi gi. Tren web
     van dung YT.Player truc tiep nhu cu. Chen luc boc boi apply-bridgeplayer.py --
     KHONG co trong file live beta2.0. */
  var YT_BRIDGE_URL = "https://raw.githack.com/donghung94/sorakanji-app/main/www/yt-bridge.html";
  var YT_BRIDGE_ORIGIN = "https://raw.githack.com";
  function isNativeApp(){ return !!(window.Capacitor && window.Capacitor.Plugins); }
  function BridgePlayer(elId, videoId, host, cbs){
    var self = this;
    var holder = document.getElementById(elId);
    var iframe = document.createElement("iframe");
    iframe.src = YT_BRIDGE_URL + "?v=" + encodeURIComponent(videoId) + "&host=" + (host === "nocookie" ? "nocookie" : "youtube");
    iframe.setAttribute("allow", "accelerometer; autoplay; encrypted-media; picture-in-picture");
    iframe.setAttribute("allowfullscreen", "");
    holder.innerHTML = "";
    holder.appendChild(iframe);
    var ready = false, queue = [], destroyed = false;
    var lastT = 0, lastD = 0, lastState = -1, lastAt = 0, rate = 1;
    function post(m){
      if(destroyed) return;
      if(ready) iframe.contentWindow.postMessage(m, YT_BRIDGE_ORIGIN);
      else queue.push(m);
    }
    function onMsg(ev){
      if(destroyed) return;
      if(ev.origin !== YT_BRIDGE_ORIGIN || ev.source !== iframe.contentWindow) return;
      var m = ev.data; if(!m || typeof m !== "object") return;
      if(m.t === "ready"){
        ready = true;
        var q = queue; queue = [];
        q.forEach(function(x){ iframe.contentWindow.postMessage(x, YT_BRIDGE_ORIGIN); });
        if(cbs.onReady) cbs.onReady({target: self});
      } else if(m.t === "state"){
        lastState = m.s;
        if(cbs.onStateChange) cbs.onStateChange({data: m.s});
      } else if(m.t === "time"){
        lastT = m.c; lastD = m.d; lastAt = Date.now();
      } else if(m.t === "error"){
        if(cbs.onError) cbs.onError({data: m.code});
      }
    }
    window.addEventListener("message", onMsg);
    this.playVideo = function(){ post({t:"play"}); };
    this.pauseVideo = function(){ post({t:"pause"}); };
    this.seekTo = function(s){ post({t:"seek", s:s}); lastT = s; lastAt = Date.now(); };
    this.setPlaybackRate = function(r){ rate = r; post({t:"rate", r:r}); };
    this.getCurrentTime = function(){
      if(lastState === 1 && lastAt) return lastT + (Date.now() - lastAt) / 1000 * rate;
      return lastT;
    };
    this.getDuration = function(){ return lastD; };
    this.getPlayerState = function(){ return lastState; };
    /* YT.Player.destroy() -- live goi o sv2 khi dong bai (co guard if(...destroy)).
       Ban BridgePlayer cu khong co ham nay: iframe cu chi bien mat khi wrap bi
       innerHTML lai. Port moi don sach: go listener + go iframe khoi DOM. */
    this.destroy = function(){
      if(destroyed) return;
      destroyed = true;
      window.removeEventListener("message", onMsg);
      if(iframe.parentNode) iframe.parentNode.removeChild(iframe);
      lastState = -1;
    };
  }
"""

# (label, old, new, expected_count)
REPLACEMENTS = [
    (
        "A: insert BridgePlayer block before svLoadPlayer",
        "  function svLoadPlayer(autoplay){",
        BRIDGE_BLOCK + "  function svLoadPlayer(autoplay){",
        1,
    ),
    (
        "B: kanji facade comment",
        "    /* Facade video: b\u1ea5m thumbnail m\u1edbi n\u1ea1p iframe YouTube (nocookie + referrerpolicy + autoplay) */",
        "    /* Facade video: b\u1ea5m thumbnail m\u1edbi n\u1ea1p iframe YouTube (nocookie + referrerpolicy + autoplay).\n"
        "       B\u1ea3n native ch\u1ea1y qua c\u1ea7u n\u1ed1i https (tr\u00e1nh l\u1ed7i 153 tr\u00ean origin capacitor://). */",
        1,
    ),
    (
        "B: kanji facade native branch",
        """      wrap.innerHTML = '<iframe src="https://www.youtube-nocookie.com/embed/' + vid + '?autoplay=1&playsinline=1" title="Video Kanji qua c\u00e2u chuy\u1ec7n" allow="accelerometer; autoplay; encrypted-media; picture-in-picture" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe>';""",
        """      if(isNativeApp()){
        wrap.innerHTML = '<iframe src="' + YT_BRIDGE_URL + '?v=' + vid + '&autoplay=1" title="Video Kanji qua c\u00e2u chuy\u1ec7n" allow="accelerometer; autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>';
      } else {
        wrap.innerHTML = '<iframe src="https://www.youtube-nocookie.com/embed/' + vid + '?autoplay=1&playsinline=1" title="Video Kanji qua c\u00e2u chuy\u1ec7n" allow="accelerometer; autoplay; encrypted-media; picture-in-picture" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe>';
      }""",
        1,
    ),
    (
        "C: svLoadPlayer native branch",
        """    function create(){
      svPlayer = new YT.Player("svPlayer", {""",
        """    function create(){
      if(isNativeApp()){
        svPlayer = new BridgePlayer("svPlayer", SV_ID, "youtube", {
          onReady: function(e){
            svReady = true;
            if(svPlayer.setPlaybackRate) svPlayer.setPlaybackRate(svRates[svRateIdx]);
            if(autoplay) e.target.playVideo();
          },
          onStateChange: function(e){ svPlayBtn(e.data === 1); }
        });
        return;
      }
      svPlayer = new YT.Player("svPlayer", {""",
        1,
    ),
    (
        "D: sv2LoadPlayer native branch",
        """    function create(){
      sv2Player = new YT.Player("sv2Player", {""",
        """    function create(){
      if(isNativeApp()){
        sv2Player = new BridgePlayer("sv2Player", SV2_ID, "nocookie", {
          onReady: function(e){
            sv2Ready = true;
            if(autoplay) e.target.playVideo();
          },
          onStateChange: function(e){ sv2PlayBtn(e.data === 1); }
        });
        return;
      }
      sv2Player = new YT.Player("sv2Player", {""",
        1,
    ),
    (
        "E: player-load guards (sv + sv2)",
        "    if(window.YT && YT.Player){ create(); }",
        "    if(isNativeApp()){ create(); }\n    else if(window.YT && YT.Player){ create(); }",
        2,
    ),
]


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent / "www" / "index.html"
    )
    text = target.read_text(encoding="utf-8")
    if MARKER in text:
        print(f"{target}: already transformed (marker {MARKER} present), no changes")
        return 0
    for label, old, new, expected in REPLACEMENTS:
        n = text.count(old)
        if n != expected:
            print(f"ABORT: {label}: expected {expected} occurrence(s), found {n} -- nothing written", file=sys.stderr)
            return 1
        text = text.replace(old, new)
        print(f"  {label}: {n} replacement(s)")
    target.write_text(text, encoding="utf-8")
    print(f"{target}: BridgePlayer transform applied ({len(REPLACEMENTS)} steps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
