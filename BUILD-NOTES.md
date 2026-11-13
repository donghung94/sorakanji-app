# SoraKanji — Capacitor wrapper: build notes (2026-11-13)

## APK đã build xong
- `app-debug.apk` (4.174.110 byte, sha256 `9449d038…1f9c6`)
- package `com.sorakanji.app`, versionCode 1, minSdk 24, targetSdk 36,
  label `SoraKanji`, launchable `MainActivity`, ký debug (apksigner verify:
  v2+v3 OK). `aapt2 dump badging` đã kiểm chứng.
- `assets/public/index.html` trong APK = sha `6cebfd59…` — đúng bản www có
  code lấy phụ đề native (`svuNativeCaptions`, `svuCapHttp`,
  `CapacitorHttp`).

## Vì sao không build bằng Gradle thuần trên VM này
Sandbox của Muse chặn MỌI kết nối TCP từ process Java (`other_tcp: Deny`).
Hậu quả, đã kiểm chứng từng cái:
- Gradle daemon ↔ client (loopback TCP): "Could not receive a message
  from the daemon."
- Gradle tải dependency (Apache HttpClient): "The server failed to respond
  with a valid HTTP response" — sandbox chèn thông báo từ chối vào socket.
- Gradle Worker Daemon (javac/dex): "Never received a connection from
  Gradle Worker Daemon 1."
- `options.fork=false` không cứu được javac: AGP 8.13 gắn Java toolchain
  và finalize `javaCompiler`, toolchain luôn fork qua worker daemon.
- curl / node / python KHÔNG bị chặn — chỉ Java bị chặn.

**Cách sửa triệt để (cần user):** Muse Settings → Permissions →
Direct network protocols → `other_tcp`: Deny → Ask. Sau đó build Gradle
bình thường (`./gradlew assembleDebug`) sẽ chạy được cả daemon, tải
dependency và worker.

## Cách APK này được build (offline + thủ công)
1. Toolchain dưới home: JDK 21 Temurin (`~/workspace/jdk-21`, Capacitor 8
   bắt buộc Java 21), Android SDK (`~/workspace/android-sdk`: platform 36,
   build-tools 35.0.0 + 36.0.0, cmdline-tools 19.0), Gradle 8.14.3
   (`~/workspace/gradle-8.14.3`).
2. Dependency Maven tải bằng curl vào repo local `~/workspace/maven-local`
   (`tools/fetch-maven.py`, có xử lý packaging `bundle`→jar, classifier
   như `aapt2:…:linux`, KMP common artifact không có jar). Init script
   `~/.gradle/init.d/local-repo.gradle` trỏ mọi repository về repo local
   trước. `tools/resolve-loop.sh` lặp: chạy Gradle `--offline`, parse
   coord thiếu (`tools/parse-missing.py`), tải thêm, tới khi resolve đủ.
3. Gradle `--no-daemon --offline` (cần `GRADLE_OPTS` khớp đúng daemon
   defaults `-Xms256m -Xmx512m -XX:MaxMetaspaceSize=384m
   -XX:+HeapDumpOnOutOfMemoryError` thì mới chạy in-process, không fork
   single-use daemon) hoàn thành tới `processDebugResources`: manifest đã
   merge, `.ap_` đã link, R.jar đủ 3 module.
4. `tools/manual-build.py` làm phần còn lại, không cần TCP:
   javac 60 file capacitor-android + MainActivity → d8 → classes.dex →
   ráp `.ap_` + dex + assets → zipalign → apksigner (keystore
   `tools/debug.keystore`, alias/pass `androiddebugkey`/`android`).
   Script tự loại jar trùng class (kotlin-stdlib-jdk7/jdk8 ⊂ stdlib 2.x,
   R.jar từng module ⊂ R.jar đã merge của app).

## Code native + backend (đã xong, đã kiểm chứng)
- Native captions chỉ trong `www/index.html` (KHÔNG động file live):
  `svuCapHttp()` / `svuPickJaTrack()` / `svuNativeCaptions(videoId)` —
  POST youtubei/v1/player client ANDROID → GET timedtext fmt=json3 →
  gửi `{videoId, captions, title, captionSource}` cho function; lỗi thì
  fallback đường server cũ. Trên web không có `window.Capacitor` thì hành
  vi giữ nguyên 100%.
- Backend `~/workspace/sorakanji-backend` (đã deploy): gen-2
  `makeLessonFromVideo` nhận `data.captions` (validate chặt, sai → 400),
  bỏ qua Innertube + Gemini, chạy parse → dịch → furigana → notes →
  cache Firestore như cũ. `npm test` 14 PASS / 0 FAIL.
- Kiểm chứng curl: mKPRQF70PvA 26 câu, Marigold 42 câu (vi 42/42,
  reading/tokens 42/42, fromCache lần 2 <1s); captions rỗng → 400.
  **Notes vẫn 0/N do Gemini free-tier 503 quá tải** (đường code notes đã
  từng chạy tốt 10/13 trước đó; cần bật billing API để hết 503).
- iOS: `ios/` đầy đủ (bundle id `com.sorakanji.app`, Xcode project,
  `public/` đã sync) — sẵn sàng build IPA trên Mac/Codemagic; VM Linux
  không build được IPA.

## Đừng quên khi VM bị thay mới
- MẤT: firebase-tools global + vá apiv2 (cài lại + vá lại), mọi thứ trong
  `/tmp`, proxy bridge (chỉ là công cụ tạm, không cần nữa).
- CÒN: `~/workspace` (code, JDK, SDK, Gradle, maven-local, APK, tools),
  `~/.gradle` (init script + cache), token login `~/.config`.
