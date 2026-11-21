#!/usr/bin/env python3
"""apply-native-auth.py — Transform dang nhap NATIVE cho ban boc Capacitor.

Ap dung vao BAN COPY www/index.html khi re-wrap (KHONG sua file live beta2.0).
Chay sau apply-native-asset-urls.py, truoc npx cap sync:
  python3 apply-native-auth.py [path/to/index.html]   (mac dinh: www/index.html)

Van de: signInWithPopup + link email CHET trong WKWebView (popup bi chan,
Google tra disallowed_useragent cho OAuth trong webview, link email mo
trinh duyet ngoai khong quay lai app).
Giai phap (theo docs @capacitor-firebase/authentication, muc "Firebase
JavaScript SDK"): plugin lay credential o tang native (Google Sign-In SDK /
Sign in with Apple) voi skipNativeAuth=true, roi Firebase JS SDK compat
10.12.2 (da nap trong file) dang nhap bang signInWithCredential — phien,
Firestore, Premium, sync, xoa tai khoan deu chay qua JS SDK nhu cu, khong
co 2 phien song song. KHONG can bundle them JS: goi plugin truc tiep qua
window.Capacitor.registerPlugin('FirebaseAuthentication') (Capacitor tu
noi method native qua PluginHeaders).

  - Google native: plugin signInWithGoogle -> idToken -> JS signInWithCredential
  - Apple native: plugin signInWithApple (bat buoc skipNativeAuth=true theo
    docs) -> idToken + nonce -> JS signInWithCredential; ten Apple (chi tra
    lan dau) ghi vao profile truoc khi hien thi neu chua co ten.
  - Link email: CHUA dung duoc trong app (can universal link — buoc sau).
    Nut Gui link tren native bao ro, huong sang Google/Apple thay vi gui
    link roi mac ket o trinh duyet ngoai.
  - Dang xuat tren native: dang xuat them phien Google native (GIDSignIn)
    de lan sau hien lai bang chon tai khoan.

PWA GIU NGUYEN 100%: moi nhanh native deu nam sau skIsNativeApp()
(window.Capacitor + isNativePlatform()); tren PWA nut Apple an (hidden),
Google chay popup cu, link email chay nhu cu.

Tuong thich truoc (forward-compat) voi spec Apple PWA (mobile-apple-signin,
chua day live): neu file da co nut #loginApple / CSS .applebtn / binding
doAppleLogin / fallback skIsApple thi bo qua khoi tuong ung thay vi chen
trung, va binding Apple duoc chuyen sang skAppleLoginRouter (native ->
plugin, PWA -> doAppleLogin cu).

Tuong thich voi live f32e9ba (21/11): live da tu dinh nghia
function skIsNativeApp() (gate mua hang VietQR trong app boc, ngu nghia
GIONG HET ban trong khoi B3) — B3 bo qua phan dinh nghia skIsNativeApp
khi da co san, chi chen cac helper con lai (skNativeFBAuth,
doNativeGoogleLogin, doNativeAppleLogin, skAppleLoginRouter, ...).

Idempotent: danh dau SK-NATIVE-AUTH-V1 — chay lai tren file da transform
thi khong doi gi. Anchor thieu -> FAIL LOUD (exit 1), khong bao gio bo
qua lang le.
"""
import re
import subprocess
import sys
from pathlib import Path

MARKER = "SK-NATIVE-AUTH-V1"

APPLE_SVG = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
             '<path d="M12.152 6.896c-.948 0-2.415-1.078-3.96-1.04-2.04.027-3.91 1.183-4.961 3.014-2.117 3.675-.546 9.103 1.519 12.09 1.013 1.454 2.208 3.09 3.792 3.039 1.52-.065 2.09-.987 3.935-.987 1.831 0 2.35.987 3.96.948 1.637-.026 2.676-1.48 3.676-2.948 1.156-1.688 1.636-3.325 1.662-3.415-.039-.013-3.182-1.221-3.22-4.857-.026-3.04 2.48-4.494 2.597-4.559-1.429-2.09-3.623-2.324-4.39-2.376-2.088-.196-3.858 1.161-4.614 1.161-.731 0-1.878-1.113-3.088-1.113zM15.53 3.83c.843-1.012 1.4-2.427 1.245-3.83-1.207.052-2.662.805-3.532 1.818-.78.896-1.454 2.338-1.273 3.714 1.338.104 2.715-.688 3.56-1.702"/></svg>')

APPLE_CSS = (
    "  .applebtn{width:100%; min-height:50px; display:flex; align-items:center; justify-content:center; gap:10px; border-radius:12px; border:1.5px solid #000; background:#000; font-family:inherit; font-size:15px; font-weight:700; color:#fff; cursor:pointer; margin-bottom:12px;}\n"
    "  .applebtn:disabled{opacity:.6; cursor:default;}\n"
    "  .applebtn svg{flex:none;}\n"
)

# Khoi helper JS — chen truoc "function doGoogleLogin(){". Viet ES5
# (var/function) cho khop style file.
NATIVE_JS = '''  /* ---------- Dang nhap NATIVE (Capacitor) — SK-NATIVE-AUTH-V1 ----------
     Chi chay trong app boc native (skIsNativeApp() = window.Capacitor co
     san + isNativePlatform()). PWA giu nguyen 100%: popup Google + link
     email. Luong native (theo docs @capacitor-firebase/authentication,
     muc "Firebase JavaScript SDK"): plugin lay credential o tang native
     (Google Sign-In SDK / Sign in with Apple) voi skipNativeAuth=true,
     roi JS SDK (compat 10.12.2, da nap trong file) dang nhap bang
     signInWithCredential — phien, Firestore, Premium, sync, xoa tai khoan
     deu chay qua JS SDK nhu cu, khong co 2 phien song song. Link email
     CHUA dung duoc trong app (can universal link, lam o buoc sau) — nut
     Gui link bao ro, huong sang Google/Apple. */
  var skNativeFBAuthCache = null;
  var skNativeFBAuthTried = false;
  function skIsNativeApp(){
    try{
      return typeof window.Capacitor !== "undefined" && !!window.Capacitor &&
        typeof window.Capacitor.isNativePlatform === "function" &&
        window.Capacitor.isNativePlatform();
    }catch(_){ return false; }
  }
  function skNativeFBAuth(){
    if(skNativeFBAuthTried) return skNativeFBAuthCache;
    skNativeFBAuthTried = true;
    try{
      if(!skIsNativeApp()) return null;
      var cap = window.Capacitor;
      if(cap.isPluginAvailable && !cap.isPluginAvailable("FirebaseAuthentication")) return null;
      if(typeof cap.registerPlugin === "function"){
        skNativeFBAuthCache = cap.registerPlugin("FirebaseAuthentication");
      }else if(cap.Plugins && cap.Plugins.FirebaseAuthentication){
        skNativeFBAuthCache = cap.Plugins.FirebaseAuthentication;
      }
    }catch(_){ skNativeFBAuthCache = null; }
    return skNativeFBAuthCache;
  }
  /* Dich loi plugin native (khong phai ma Firebase) sang tieng Viet. */
  function skNativeAuthErrorVI(err, who){
    var msg = (err && err.message) || "";
    var code = (err && err.code) || "";
    if(/cancel/i.test(code + " " + msg) || code === "1001" || msg.indexOf("1001") !== -1){
      return "Bạn đã hủy đăng nhập" + (who ? " " + who : "") + " — thử lại khi cần nhé.";
    }
    if(code && code.indexOf("auth/") === 0) return skAuthErrorVI(err);
    return "Chưa đăng nhập được" + (code ? " (" + code + ")" : "") + " — bạn thử lại nhé.";
  }
  /* Dang nhap Google NATIVE: plugin mo bang chon tai khoan Google cua he
     thong -> lay idToken -> JS SDK signInWithCredential. */
  function doNativeGoogleLogin(auth){
    var fbAuth = skNativeFBAuth();
    if(!fbAuth){ loginShowErr("Chưa kết nối được đăng nhập Google trên app — bạn thử lại nhé."); return; }
    loginSetBusy(true);
    fbAuth.signInWithGoogle({ skipNativeAuth: true }).then(function(result){
      var idToken = result && result.credential && result.credential.idToken;
      if(!idToken){
        loginSetBusy(false);
        loginShowErr("Chưa lấy được thông tin đăng nhập Google — bạn thử lại nhé.");
        return;
      }
      var credential = firebase.auth.GoogleAuthProvider.credential(idToken);
      auth.signInWithCredential(credential).then(function(cred){
        loginSetBusy(false);
        if(cred && cred.user) applyAuthUser(cred.user);
        closeLogin();
      }).catch(function(err){
        loginSetBusy(false);
        loginShowErr(skAuthErrorVI(err));
      });
    }).catch(function(err){
      loginSetBusy(false);
      loginShowErr(skNativeAuthErrorVI(err, "Google"));
    });
  }
  /* Dang nhap Apple NATIVE: plugin mo Sign in with Apple cua he thong
     (bat buoc skipNativeAuth=true theo docs plugin khi dung kem JS SDK)
     -> lay idToken + nonce -> JS SDK signInWithCredential. Ten Apple chi
     tra o lan dang nhap dau (qua plugin, khong co trong ID token) nen ghi
     vao Firebase profile truoc khi hien thi neu chua co ten. */
  function doNativeAppleLogin(auth){
    var fbAuth = skNativeFBAuth();
    if(!fbAuth){ loginShowErr("Chưa kết nối được đăng nhập Apple trên app — bạn thử lại nhé."); return; }
    loginSetBusy(true);
    fbAuth.signInWithApple({ skipNativeAuth: true }).then(function(result){
      var idToken = result && result.credential && result.credential.idToken;
      var nonce = result && result.credential && result.credential.nonce;
      if(!idToken || !nonce){
        loginSetBusy(false);
        loginShowErr("Chưa lấy được thông tin đăng nhập Apple — bạn thử lại nhé.");
        return;
      }
      var displayName = result && result.user && result.user.displayName;
      var provider = new firebase.auth.OAuthProvider("apple.com");
      var credential = provider.credential({ idToken: idToken, rawNonce: nonce });
      auth.signInWithCredential(credential).then(function(cred){
        function skAppleDone(){
          loginSetBusy(false);
          if(cred && cred.user) applyAuthUser(cred.user);
          closeLogin();
        }
        if(displayName && cred && cred.user && !cred.user.displayName && cred.user.updateProfile){
          cred.user.updateProfile({ displayName: displayName }).then(skAppleDone, skAppleDone);
        }else{
          skAppleDone();
        }
      }).catch(function(err){
        loginSetBusy(false);
        loginShowErr(skAuthErrorVI(err));
      });
    }).catch(function(err){
      loginSetBusy(false);
      loginShowErr(skNativeAuthErrorVI(err, "Apple"));
    });
  }
  /* Router nut Apple: native -> plugin; PWA -> doAppleLogin (popup, khi
     spec Apple PWA da live; chua live thi nut an nen khong bao gio toi day). */
  function skAppleLoginRouter(){
    if(skIsNativeApp()){
      var auth = skAuth();
      if(!auth){ loginShowErr("Chưa kết nối được máy chủ đăng nhập — kiểm tra mạng rồi thử lại nhé."); return; }
      doNativeAppleLogin(auth);
      return;
    }
    if(typeof doAppleLogin === "function"){ doAppleLogin(); }
  }
  /* Hien nut Apple chi trong app native (PWA: nut an mac dinh bang thuoc
     tinh hidden; neu spec Apple PWA da live thi nut da hien san). */
  try{
    if(skIsNativeApp()){
      var skAppleBtn = document.getElementById("loginApple");
      if(skAppleBtn) skAppleBtn.hidden = false;
    }
  }catch(_){}
'''


def fail(msg):
    print("FAIL: %s" % msg, file=sys.stderr)
    sys.exit(1)


def replace_once(s, old, new, name):
    n = s.count(old)
    if n != 1:
        fail("%s: anchor xuat hien %d lan (can dung 1)" % (name, n))
    return s.replace(old, new)


def node_check_inline(html):
    """node --check tung script inline (bo qua script co src)."""
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    ok = 0
    for i, js in enumerate(scripts):
        p = subprocess.run(["node", "--check"],
                           input=js.encode("utf-8"), capture_output=True)
        if p.returncode != 0:
            fail("node --check FAIL script inline #%d: %s"
                 % (i, p.stderr.decode("utf-8", "replace")[:500]))
        ok += 1
    print("node --check %d/%d script inline OK" % (ok, len(scripts)))


def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent / "www" / "index.html"
    )
    if not target.exists():
        fail("khong thay file: %s" % target)
    s = target.read_text(encoding="utf-8")
    if MARKER in s:
        print("%s: da transform (tim thay %s), khong doi gi" % (target, MARKER))
        return
    if 'id="loginSheet"' not in s or "signInWithPopup" not in s:
        fail("%s: khong phai mobile/index.html (thieu loginSheet/signInWithPopup)" % target)

    # B1 — CSS .applebtn (bo qua neu spec Apple PWA da chen san).
    if ".applebtn{" in s:
        print("bo qua B1 CSS .applebtn (da co san)")
    else:
        s = replace_once(
            s, "  .googlebtn svg{flex:none;}\n",
            "  .googlebtn svg{flex:none;}\n" + APPLE_CSS,
            "B1 CSS .applebtn")
        print("ap dung B1 CSS .applebtn OK")

    # B2 — nut #loginApple (hidden mac dinh; JS native se hien).
    if 'id="loginApple"' in s:
        print("bo qua B2 nut #loginApple (da co san)")
    else:
        apple_btn = ('        <button class="applebtn" id="loginApple" type="button" hidden>'
                     + APPLE_SVG + '<span>Tiếp tục bằng Apple</span></button>\n')
        s = replace_once(
            s, '</span></button>\n        <div class="auth-or">',
            '</span></button>\n' + apple_btn + '        <div class="auth-or">',
            "B2 nut #loginApple")
        print("ap dung B2 nut #loginApple OK")

    # B3 — khoi helper JS native. Live f32e9ba tro di da tu dinh nghia
    # function skIsNativeApp() (ngu nghia giong het ban trong NATIVE_JS):
    # neu da co thi chen khoi helper KHONG kem dinh nghia do (tranh trung
    # 2 dinh nghia — kiem tra sau van yeu cau dung 1 lan).
    native_js = NATIVE_JS
    if "function skIsNativeApp()" in s:
        sk_fn = ('  function skIsNativeApp(){\n'
                 '    try{\n'
                 '      return typeof window.Capacitor !== "undefined" && !!window.Capacitor &&\n'
                 '        typeof window.Capacitor.isNativePlatform === "function" &&\n'
                 '        window.Capacitor.isNativePlatform();\n'
                 '    }catch(_){ return false; }\n'
                 '  }\n')
        if NATIVE_JS.count(sk_fn) != 1:
            fail("B3: khong tach duoc dinh nghia skIsNativeApp khoi NATIVE_JS")
        native_js = NATIVE_JS.replace(sk_fn, "")
        print("bo qua dinh nghia skIsNativeApp trong B3 (live da co san)")
    s = replace_once(
        s, "  function doGoogleLogin(){",
        native_js + "  function doGoogleLogin(){",
        "B3 khoi helper JS native")
    print("ap dung B3 khoi helper JS native OK")

    # B4 — nhanh native trong doGoogleLogin.
    s = replace_once(
        s, "    var provider = new firebase.auth.GoogleAuthProvider();",
        "    /* App native: dang nhap Google qua plugin (popup chet trong WKWebView). */\n"
        "    if(skIsNativeApp()){ doNativeGoogleLogin(auth); return; }\n"
        "    var provider = new firebase.auth.GoogleAuthProvider();",
        "B4 nhanh native doGoogleLogin")
    print("ap dung B4 nhanh native doGoogleLogin OK")

    # B5 — chan link email tren native (bao ro thay vi gui link roi mac ket).
    s = replace_once(
        s, '    var email = loginEmailInput ? loginEmailInput.value.trim() : "";',
        "    if(skIsNativeApp()){\n"
        "      /* Link email chua dung duoc trong app (can universal link — buoc sau):\n"
        "         bao ro, huong sang Google/Apple thay vi gui link roi mac ket. */\n"
        '      loginShowErr("Trong app, bạn đăng nhập bằng Google hoặc Apple nhé — link email chỉ dùng được trên bản web (sorakanji.com).");\n'
        "      return;\n"
        "    }\n"
        '    var email = loginEmailInput ? loginEmailInput.value.trim() : "";',
        "B5 chan link email tren native")
    print("ap dung B5 chan link email tren native OK")

    # B6 — loginSetBusy disable ca nut Apple.
    s = replace_once(
        s, '    var gBtn = document.getElementById("loginGoogle");\n'
           "    if(gBtn) gBtn.disabled = busy;",
        '    var gBtn = document.getElementById("loginGoogle");\n'
        "    if(gBtn) gBtn.disabled = busy;\n"
        '    var aBtn = document.getElementById("loginApple");\n'
        "    if(aBtn) aBtn.disabled = busy;",
        "B6 loginSetBusy disable Apple")
    print("ap dung B6 loginSetBusy disable Apple OK")

    # B7 — fallback ten theo provider (giong spec Apple PWA B11).
    if "skIsApple" in s:
        print("bo qua B7 fallback ten (da co skIsApple)")
    else:
        s = replace_once(
            s, '      signedInName = user.displayName || user.email || "Tài khoản Google";',
            '      var skIsApple = !!(user.providerData && user.providerData.some(function(p){ return p && p.providerId === "apple.com"; }));\n'
            '      signedInName = user.displayName || user.email || (skIsApple ? "Tài khoản Apple" : "Tài khoản Google");',
            "B7 fallback ten theo provider")
        print("ap dung B7 fallback ten theo provider OK")

    # B8 — dang xuat ca phien Google native.
    s = replace_once(
        s, "      if(auth){ auth.signOut().catch(function(){}); }",
        "      if(skIsNativeApp()){\n"
        "        /* Dang xuat ca phien Google native (GIDSignIn giu tai khoan da chon\n"
        "           — khong dang xuat thi lan sau khong hien bang chon tai khoan). */\n"
        "        try{ var skFbAuth = skNativeFBAuth(); if(skFbAuth) skFbAuth.signOut().catch(function(){}); }catch(_){}\n"
        "      }\n"
        "      if(auth){ auth.signOut().catch(function(){}); }",
        "B8 dang xuat native")
    print("ap dung B8 dang xuat native OK")

    # B9 — binding nut Apple (hoac chuyen binding PWA sang router).
    pwa_binding = 'document.getElementById("loginApple").addEventListener("click", doAppleLogin);'
    if pwa_binding in s:
        s = s.replace(pwa_binding,
                      'document.getElementById("loginApple").addEventListener("click", skAppleLoginRouter);')
        print("ap dung B9 binding Apple: chuyen doAppleLogin -> skAppleLoginRouter OK")
    elif 'getElementById("loginApple").addEventListener' in s:
        fail("B9: da co binding loginApple la (khong phai doAppleLogin) — kiem tra tay")
    else:
        s = replace_once(
            s, '  document.getElementById("loginGoogle").addEventListener("click", doGoogleLogin);',
            '  document.getElementById("loginGoogle").addEventListener("click", doGoogleLogin);\n'
            '  var skLoginAppleBtn = document.getElementById("loginApple");\n'
            '  if(skLoginAppleBtn) skLoginAppleBtn.addEventListener("click", skAppleLoginRouter);',
            "B9 binding nut Apple")
        print("ap dung B9 binding nut Apple OK")

    # B12 — comment signedInName (giong spec Apple PWA B12).
    new_comment = 'var signedInName = ""; /* tên hiển thị: displayName || email || "Tài khoản Google" (Apple: "Tài khoản Apple") */'
    if new_comment in s:
        print("bo qua B12 comment signedInName (da co)")
    else:
        s = replace_once(
            s, 'var signedInName = ""; /* tên hiển thị: displayName || email || "Tài khoản Google" */',
            new_comment,
            "B12 comment signedInName")
        print("ap dung B12 comment signedInName OK")

    # Kiem tra sau: moi khoi chi xuat hien dung 1 lan.
    checks = [
        (MARKER, 1, "marker"),
        ('id="loginApple"', 1, "nut #loginApple"),
        (".applebtn{", 1, "CSS .applebtn"),
        ("function doNativeGoogleLogin(auth)", 1, "doNativeGoogleLogin"),
        ("function doNativeAppleLogin(auth)", 1, "doNativeAppleLogin"),
        ("function skAppleLoginRouter()", 1, "skAppleLoginRouter"),
        ("function skIsNativeApp()", 1, "skIsNativeApp"),
        ("skAppleLoginRouter);", 1, "binding Apple"),
        ('"Tài khoản Apple"', 2, "nhan Tai khoan Apple (fallback + comment)"),
    ]
    for sub, want, name in checks:
        n = s.count(sub)
        if n != want:
            fail("kiem tra sau: %s xuat hien %d lan (can %d)" % (name, n, want))
    node_check_inline(s)

    target.write_text(s, encoding="utf-8")
    print("%s: transform xong (%d byte)" % (target, len(s.encode("utf-8"))))


if __name__ == "__main__":
    main()
