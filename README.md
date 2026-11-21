# SoraKanji — Capacitor native app

Native wrapper (iOS/Android) around the SoraKanji mobile web app.
`www/index.html` is the live mobile build from `donghung94/beta2.0`
(`mobile/index.html`), re-wrapped on the dev VM with 3 transforms
(see "Re-wrap" below). The app fetches YouTube captions on-device via
`CapacitorHttp` and plays shadowing video through a bridge page —
both need the native app, Safari/PWA cannot do this.

- Bundle id: `com.sorakanji.app`. Web dir: `www`.
- Store icon is committed: `ios/App/App/Assets.xcassets/AppIcon.appiconset/AppIcon-512@2x.png`
  (source: `assets/icon-1024.png`).
- Native login: `@capacitor-firebase/authentication` (Google + Apple).
  Needs `GoogleService-Info.plist` in `ios/App/App/` (Firebase Console,
  bundle `com.sorakanji.app`) for native sign-in to work; without it the
  app still launches, only native sign-in fails.

## Re-wrap (on the dev VM, after each live mobile update)

```bash
cd ~/workspace/sorakanji-capacitor
# 1. copy the latest live mobile index.html -> www/index.html (verify sha!)
# 2. transforms, in this order:
python3 apply-native-asset-urls.py www/index.html  # 67 asset refs -> githack
python3 apply-native-auth.py www/index.html        # native login (Capacitor only)
python3 apply-bridgeplayer.py www/index.html       # YouTube error-153 bridge
# 3. sync into the native projects
npx cap sync
```

All 3 transforms are idempotent and only affect the native copy — the PWA
is untouched. PWA behavior is unchanged: every native code path is gated
on `window.Capacitor` (`skIsNativeApp()` / `isNativeApp()`).

## iOS build (free, unsigned)

`.github/workflows/build-ios.yml`, trigger `workflow_dispatch` ONLY:
`npm ci` → `npx cap sync ios` → verify wrapped-code markers → unsigned
`xcodebuild archive` (`CODE_SIGNING_ALLOWED=NO`) → `App-unsigned.ipa`,
published as a release asset. Sideload with
[AltStore](https://altstore.io) using a free Apple ID (no $99 Developer
Program needed for testing; the app expires after 7 days and AltStore
refreshes it automatically).

## DO NOT DELETE these repo files

- **`www/yt-bridge.html`** — BridgePlayer loads it from
  `raw.githack.com/donghung94/sorakanji-app/main/www/yt-bridge.html`.
  Deleting it breaks ALL video playback in the native app (YouTube
  error 153). It is NOT bundled in the app on purpose (a `capacitor://`
  origin would fail the same way).
- `www/dict-ja-vi.json`, `www/yt-test.html` — leftovers from the old
  native app; harmless, keep them.

## Android

The `android/` project lives in this repo locally but is not used by the
iOS workflow. Gradle cannot run on the dev VM (sandbox blocks Java TCP);
see `BUILD-NOTES.md` for the offline/manual APK build that produced
`app-debug.apk`. A Play build via CI is a later step.
