#!/usr/bin/env python3
"""apply-iap.py — Transform MUA GOI TRONG APP (IAP, StoreKit 2) cho ban boc Capacitor.

Ap dung vao BAN COPY www/index.html khi re-wrap (KHONG sua file live beta2.0).
Chay sau apply-bridgeplayer.py, truoc npx cap sync:
  python3 apply-iap.py [path/to/index.html]   (mac dinh: www/index.html)

Van de: trong app boc, nut mua VietQR bi an (App Store 3.1.1) — user chi thay
huong dan mua bang chu (mo trinh duyet, chuyen khoan). Apple khong cho phep
huong dan mua ngoai app; mua trong app phai qua StoreKit (IAP).
Giai phap (theo ~/workspace/store-track/iap-plan/PLAN.md §5): plugin
@capgo/native-purchases v8.x (StoreKit 2, iOS 15+), lazy-load qua
window.Capacitor.registerPlugin("NativePurchases") — KHONG can bundle them JS.

  - Trang goi (#pwPlansOverlay): gia lay tu StoreKit (priceString) — BO gia
    hardcode 360.000đ/799.000đ/999.000đ/2.499.000đ + dong "Tiet kiem" + banner
    sale .pw-sale; nut Mua hien lai trong app boc (IAP), khoi .pw-guide doi
    thanh nut Khoi phuc giao dich (bat buoc theo App Store Review Guidelines)
    + Quan ly goi (manageSubscriptions) + ghi chu tu gia han.
  - Luong mua: purchaseProduct(autoAcknowledgePurchases:false) -> jws ->
    appleVerifyPurchase (onCall, fetch giong svuFetchFn) -> finish SAU KHI
    server xac thuc xong. autoFinishTransactions=false trong capacitor.config
    + configure() luc init. Server la nguon su that duy nhat — client KHONG
    BAO GIO tu mo Premium; Premium mo qua listener onSnapshot co san.
  - Khoi phuc: restorePurchases -> getPurchases -> verify tung giao dich
    (server idempotent). Doi chieu khi mo app: getPurchases -> verify giao
    dich chua verify (bat truong hop mua xong nhung crash/mat mang).
  - Sora FAQ topic premium: viet lai cho native (khong gia hardcode, khong
    huong dan mua web). Dieu khoan: GIU doan chuyen khoan web + THEM doan
    mua trong app qua Apple (tu gia han, huy trong Settings, hoan tien qua
    Apple); cau gia o §3 viet lai khong kem so gia cu the.
  - Y dinh mua song sot qua lan dang nhap: skStartCheckout re sang skIapBuy
    trong app boc nen skResumePendingGate + skPendingBuyPkg chay nhu cu.

PWA/WEB GIU NGUYEN 100%: transform chi ap len file boc; moi nhanh IAP deu
nam sau skIsNativeApp(). Luong VietQR tren PWA khong doi (skStartCheckout
van chay luong cu khi khong phai native).

Idempotent: danh dau SK-IAP-V1 — chay lai tren file da transform thi khong
doi gi. Anchor thieu -> FAIL LOUD (exit 1), khong bao gio bo qua lang le.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

MARKER = "SK-IAP-V1"

IAP_CSS = (
    "  .pw-iap-row{display:flex; gap:8px; margin-top:10px; flex-wrap:wrap;}\n"
    "  .pw-iap-row .ghostbtn{flex:1; justify-content:center; min-height:44px;}\n"
    "  .pw-guide .pw-iap-note{margin:8px 0 0; font-size:13px; color:var(--ink-2); line-height:1.5;}\n"
    "  .pw-guide .pw-iap-note:empty{display:none;}\n"
)

IAP_GUIDE = (
    '        <div class="pw-guide" id="pwGuide">\n'
    '          <b>Mua trong ứng dụng</b>\n'
    '          <p>Thanh toán qua Apple (App Store) — giá hiển thị trên từng gói trước khi bạn xác nhận mua. Gói Năm tự động gia hạn mỗi năm; bạn có thể hủy bất cứ lúc nào trong Cài đặt iPhone → Apple ID → Đăng ký.</p>\n'
    '          <div class="pw-iap-row">\n'
    '            <button class="ghostbtn" id="pwRestoreBtn" type="button">Khôi phục giao dịch</button>\n'
    '            <button class="ghostbtn" id="pwManageBtn" type="button">Quản lý gói</button>\n'
    '          </div>\n'
    '          <p class="pw-iap-note" id="pwIapNote"></p>\n'
    '        </div>'
)

# Khoi module JS — chen truoc "function doGoogleLogin(){" (sau khoi native-auth).
# Viet ES5 (var/function) cho khop style file.
IAP_JS = '''  /* ---------- Mua goi trong app (IAP, StoreKit 2) — SK-IAP-V1 ----------
     Chi chay trong app boc native (skIsNativeApp()). PWA/web giu nguyen:
     mua bang chuyen khoan VietQR. Plugin @capgo/native-purchases v8.x
     (StoreKit 2, iOS 15+) — lazy-load qua Capacitor.registerPlugin.
     Nguyen tac: server la nguon su that duy nhat — client KHONG BAO GIO
     tu mo Premium dua tren ket qua StoreKit; giao dich chi duoc finish
     SAU KHI server appleVerifyPurchase xac thuc xong (autoFinishTransactions
     = false trong capacitor.config + configure() + autoAcknowledgePurchases
     = false tung lan mua). Premium mo qua listener onSnapshot co san.
     Gia hien thi lay tu StoreKit (priceString) — KHONG hardcode gia. */
  var SK_IAP_PRODUCTS = {
    year: "com.sorakanji.app.premium.year",
    lifetime: "com.sorakanji.app.premium.lifetime"
  };
  var SK_IAP_FN_URL = "https://asia-northeast1-donghung-3208d.cloudfunctions.net/appleVerifyPurchase";
  var skIapPluginCache = null, skIapPluginTried = false;
  function skIapPlugin(){
    if(skIapPluginTried) return skIapPluginCache;
    skIapPluginTried = true;
    try{
      if(!skIsNativeApp()) return null;
      var cap = window.Capacitor;
      if(cap.isPluginAvailable && !cap.isPluginAvailable("NativePurchases")) return null;
      if(typeof cap.registerPlugin === "function"){
        skIapPluginCache = cap.registerPlugin("NativePurchases");
      }else if(cap.Plugins && cap.Plugins.NativePurchases){
        skIapPluginCache = cap.Plugins.NativePurchases;
      }
    }catch(_){ skIapPluginCache = null; }
    return skIapPluginCache;
  }
  /* Tat auto-finish o tang plugin (them lop bao hiem ngoai
     capacitor.config): giao dich chi finish sau khi server verify xong. */
  var skIapConfigured = false;
  function skIapConfigure(){
    if(skIapConfigured) return Promise.resolve();
    var p = skIapPlugin();
    if(!p || typeof p.configure !== "function"){ skIapConfigured = true; return Promise.resolve(); }
    return p.configure({autoFinishTransactions: false}).then(function(){ skIapConfigured = true; }).catch(function(){ skIapConfigured = true; });
  }
  /* Goi appleVerifyPurchase (onCall) — cung giao thuc fetch nhu svuFetchFn:
     POST {"data": {jws}} + Bearer ID token -> {"result": {...}}. */
  function skIapVerify(jws){
    var auth = null;
    try{ auth = skAuth(); }catch(_){ auth = null; }
    var user = auth && auth.currentUser;
    if(!user) return Promise.reject({code: "iap/login-required", message: ""});
    return Promise.resolve().then(function(){ return user.getIdToken(); }).then(function(token){
      return fetch(SK_IAP_FN_URL, {
        method: "POST",
        headers: {"Content-Type": "application/json", "Authorization": "Bearer " + token},
        body: JSON.stringify({data: {jws: jws}})
      });
    }).then(function(r){
      return r.json().then(function(j){
        if(j && j.result) return j.result;
        var e = (j && j.error) || {};
        var st = String(e.status || "INTERNAL").toLowerCase().replace(/_/g, "-");
        throw {code: "functions/" + st, message: e.message || ""};
      });
    });
  }
  /* Finish giao dich SAU KHI verify xong. Loi finish thi bo qua — giao dich
     o lai queue, lan mo app sau doi chieu lai. */
  function skIapFinish(txId){
    var p = skIapPlugin();
    if(!p || typeof p.finishTransaction !== "function" || !txId) return Promise.resolve();
    return p.finishTransaction({transactionId: txId}).catch(function(){});
  }
  /* Dich loi IAP sang tieng Viet. */
  function skIapIsCancel(err){
    var s = ((err && err.code) || "") + " " + ((err && err.message) || "");
    return /cancel/i.test(s);
  }
  function skIapErrVI(err){
    if(!err) return "Chưa mua được gói — kiểm tra kết nối rồi thử lại.";
    var code = err.code || "";
    var msg = err.message || "";
    if(code === "iap/no-jws") return "Chưa nhận được giao dịch từ App Store — bạn thử mua lại nhé.";
    if(code === "iap/login-required") return "Bạn cần đăng nhập trước khi mua gói.";
    if(code.indexOf("functions/unauthenticated") === 0) return "Phiên đăng nhập đã hết — đăng nhập lại rồi thử mua lại nhé.";
    if(code.indexOf("functions/") === 0){
      if(msg) return msg;
      return "Máy chủ chưa xác thực được giao dịch — bạn thử lại sau nhé.";
    }
    if(/Failed to fetch|NetworkError|network|TypeError/i.test(code + " " + msg)) return "Mất kết nối mạng — kiểm tra mạng rồi thử lại.";
    if(msg && msg.length < 160) return msg;
    return "Chưa mua được gói — kiểm tra kết nối rồi thử lại." + (code ? " (" + code + ")" : "");
  }
  /* Verify 1 giao dich roi finish neu server da grant. Tra Promise<boolean>
     (true = server da grant). Sandbox / het han / da hoan: chi ghi nhan,
     khong grant, khong finish. Loi mang/verify: false, khong finish. */
  function skIapHandleTransaction(tx){
    if(!tx || !tx.jwsRepresentation) return Promise.resolve(false);
    return skIapVerify(tx.jwsRepresentation).then(function(res){
      if(res && res.ok){
        return skIapFinish(tx.transactionId).then(function(){ return true; });
      }
      return false;
    }).catch(function(){ return false; });
  }
  /* Ghi chu trong khoi IAP cua trang goi (#pwIapNote). */
  function skIapNote(t){
    var el = document.getElementById("pwIapNote");
    if(el) el.textContent = t || "";
  }
  /* Tai gia tu StoreKit + dien vao the goi. Goi moi lan mo trang goi;
     cache sau lan thanh cong dau tien. */
  var skIapProductsCache = null, skIapProductsLoading = false;
  function skIapRenderPrices(prods){
    var map = {};
    (prods || []).forEach(function(p){ if(p && p.identifier) map[p.identifier] = p; });
    var y = map[SK_IAP_PRODUCTS.year], l = map[SK_IAP_PRODUCTS.lifetime];
    var yEl = document.getElementById("pwPriceYear");
    var lEl = document.getElementById("pwPriceLifetime");
    if(yEl) yEl.textContent = (y && y.priceString) ? y.priceString : "—";
    if(lEl) lEl.textContent = (l && l.priceString) ? l.priceString : "—";
  }
  function skIapLoadProducts(){
    if(!skIsNativeApp()) return;
    var plugin = skIapPlugin();
    var yEl = document.getElementById("pwPriceYear");
    var lEl = document.getElementById("pwPriceLifetime");
    if(!plugin){
      if(yEl) yEl.textContent = "—";
      if(lEl) lEl.textContent = "—";
      skShowPlansMsg("Chưa tải được bảng giá từ App Store — kiểm tra mạng rồi mở lại trang này nhé.");
      return;
    }
    if(skIapProductsCache){ skIapRenderPrices(skIapProductsCache); return; }
    if(skIapProductsLoading) return;
    skIapProductsLoading = true;
    plugin.getProducts({productIdentifiers: [SK_IAP_PRODUCTS.year, SK_IAP_PRODUCTS.lifetime]}).then(function(res){
      skIapProductsLoading = false;
      skIapProductsCache = (res && res.products) || [];
      skIapRenderPrices(skIapProductsCache);
    }).catch(function(){
      skIapProductsLoading = false;
      if(yEl) yEl.textContent = "—";
      if(lEl) lEl.textContent = "—";
      skShowPlansMsg("Chưa tải được bảng giá từ App Store — kiểm tra mạng rồi mở lại trang này nhé.");
    });
  }
  /* Mua goi qua StoreKit: purchase -> verify server -> finish.
     Chua dang nhap thi mo bang dang nhap truoc, y dinh mua song sot qua
     lan dang nhap (skPendingBuyPkg + skResumePendingGate -> skStartCheckout). */
  var skIapBuyBusy = false;
  function skIapBuy(pkg){
    pkg = (pkg === "lifetime") ? "lifetime" : "year";
    if(skIapBuyBusy) return;
    if(isPremium()){
      skShowPlansMsg("Bạn đang dùng Premium rồi — toàn bộ nội dung N3–N1 đã mở cho tài khoản của bạn.", true);
      return;
    }
    var u = skCheckoutUser();
    if(!u){
      skPendingBuyPkg = pkg;
      skPendingGate = true;
      if(!skAuth()){ skAuthGateShow(false); return; }
      openLogin();
      return;
    }
    var plugin = skIapPlugin();
    if(!plugin){
      skShowPlansError("Chưa kết nối được App Store trên máy này — kiểm tra mạng rồi thử lại.", pkg);
      return;
    }
    skIapBuyBusy = true;
    skClearPlansMsg();
    var btn = skBuyBtn(pkg);
    var btnLabel = btn ? btn.textContent : "";
    if(btn){ btn.disabled = true; btn.textContent = "Đang xử lý…"; }
    function done(){
      skIapBuyBusy = false;
      if(btn){ btn.disabled = false; btn.textContent = btnLabel; }
    }
    skIapConfigure().then(function(){
      return plugin.purchaseProduct({productIdentifier: SK_IAP_PRODUCTS[pkg], autoAcknowledgePurchases: false});
    }).then(function(tx){
      if(!tx || !tx.jwsRepresentation) throw {code: "iap/no-jws", message: ""};
      return skIapVerify(tx.jwsRepresentation).then(function(res){
        if(res && res.ok){
          return skIapFinish(tx.transactionId).then(function(){
            done();
            skShowPlansMsg("Mua thành công! Premium đã mở cho tài khoản của bạn.", true);
            try{ premiumRefresh(function(){}); }catch(_){}
          });
        }
        if(res && res.sandbox){
          done();
          skShowPlansMsg("Đây là giao dịch thử (sandbox) — không mở Premium thật. Bạn cần bản TestFlight hoặc bản chính thức để mua thật.", false);
          return;
        }
        done();
        skShowPlansError("Chưa xác thực được giao dịch — giao dịch vẫn còn trong hàng đợi App Store, bạn mở lại app để thử lại.", pkg);
      });
    }).catch(function(err){
      done();
      if(skIapIsCancel(err)){
        skShowPlansMsg("Bạn đã hủy mua — thử lại khi cần nhé.");
        return;
      }
      skShowPlansError(skIapErrVI(err), pkg);
    });
  }
  /* Khoi phuc giao dich (nut bat buoc theo App Store Review Guidelines):
     restorePurchases -> getPurchases -> verify tung giao dich (server
     idempotent). */
  var skIapRestoreBusy = false;
  function skIapRestore(){
    if(skIapRestoreBusy) return;
    var plugin = skIapPlugin();
    if(!plugin){ skIapNote("Chưa kết nối được App Store trên máy này — kiểm tra mạng rồi thử lại."); return; }
    var u = skCheckoutUser();
    if(!u){
      skPendingGate = true;
      if(!skAuth()){ skAuthGateShow(false); return; }
      openLogin();
      return;
    }
    skIapRestoreBusy = true;
    skIapNote("Đang khôi phục giao dịch…");
    skIapConfigure().then(function(){
      return plugin.restorePurchases();
    }).then(function(){
      return plugin.getPurchases({onlyCurrentEntitlements: true});
    }).then(function(res){
      var list = (res && res.purchases) || [];
      var withJws = list.filter(function(tx){ return tx && tx.jwsRepresentation; });
      if(!withJws.length){
        skIapRestoreBusy = false;
        skIapNote("Không tìm thấy giao dịch nào để khôi phục trên tài khoản Apple này.");
        return;
      }
      var chain = Promise.resolve();
      var granted = 0;
      withJws.forEach(function(tx){
        chain = chain.then(function(){
          return skIapHandleTransaction(tx).then(function(ok){ if(ok) granted++; });
        });
      });
      return chain.then(function(){
        skIapRestoreBusy = false;
        if(granted > 0){
          skIapNote("Đã khôi phục Premium cho tài khoản của bạn.");
          try{ premiumRefresh(function(){}); }catch(_){}
        }else{
          skIapNote("Đã kiểm tra xong — không có gói nào cần khôi phục (có thể bạn chưa từng mua, hoặc Premium đã mở sẵn).");
        }
      });
    }).catch(function(err){
      skIapRestoreBusy = false;
      skIapNote(skIapErrVI(err));
    });
  }
  /* Mo trang quan ly goi cua he thong (huy/tu gia han) — khong co nut huy
     trong app, dung chuan Apple. */
  function skIapManage(){
    var plugin = skIapPlugin();
    if(!plugin || typeof plugin.manageSubscriptions !== "function"){
      skIapNote("Chưa mở được trang quản lý gói — bạn vào Cài đặt iPhone → Apple ID → Đăng ký để quản lý gói nhé.");
      return;
    }
    plugin.manageSubscriptions().catch(function(){
      skIapNote("Chưa mở được trang quản lý gói — bạn vào Cài đặt iPhone → Apple ID → Đăng ký để quản lý gói nhé.");
    });
  }
  /* Doi chieu khi mo app (native + da dang nhap): getPurchases -> verify
     tung giao dich chua verify (bat truong hop mua xong nhung app crash /
     mat mang truoc khi verify). Chi chay 1 lan/phien; chua dang nhap thi
     doi applyAuthUser goi lai sau khi dang nhap. */
  var skIapReconciled = false;
  function skIapReconcile(){
    if(!skIsNativeApp() || skIapReconciled) return;
    var plugin = skIapPlugin();
    if(!plugin) return;
    var auth = null;
    try{ auth = skAuth(); }catch(_){ auth = null; }
    if(!auth || !auth.currentUser) return;
    skIapReconciled = true;
    plugin.getPurchases({onlyCurrentEntitlements: true}).then(function(res){
      var list = (res && res.purchases) || [];
      var chain = Promise.resolve();
      list.forEach(function(tx){
        if(tx && tx.jwsRepresentation){
          chain = chain.then(function(){ return skIapHandleTransaction(tx); });
        }
      });
      return chain;
    }).catch(function(){ skIapReconciled = false; });
  }
  /* Khoi tao IAP 1 lan khi app mo (goi tu skCheckoutInit): tat auto-finish,
     dang ky listener transactionUpdated (gia han / khoi phuc tu StoreKit),
     doi chieu giao dich ton. */
  var skIapInited = false;
  function skIapInit(){
    if(skIapInited || !skIsNativeApp()) return;
    skIapInited = true;
    var plugin = skIapPlugin();
    if(!plugin) return;
    skIapConfigure();
    try{
      if(typeof plugin.addListener === "function"){
        plugin.addListener("transactionUpdated", function(tx){
          skIapHandleTransaction(tx);
        });
      }
    }catch(_){}
    skIapReconcile();
  }
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
    if 'id="pwPlansOverlay"' not in s or "skCheckoutInit" not in s:
        fail("%s: khong phai mobile/index.html (thieu pwPlansOverlay/skCheckoutInit)" % target)

    # I1 — CSS khoi IAP (hang nut Khoi phuc/Quan ly + ghi chu).
    s = replace_once(
        s, "  .pw-buy[hidden]{display:none;}\n",
        "  .pw-buy[hidden]{display:none;}\n" + IAP_CSS,
        "I1 CSS IAP")
    print("ap dung I1 CSS IAP OK")

    # I1b — comment CSS nut mua: khong con "an nut mua trong app boc".
    s = replace_once(
        s, "Capacitor, nut mua bi an bang JS (skCheckoutInit) — chi con huong dan\n"
           "     mua bang chu. .cta co display:flex nen [hidden] can rule rieng. */",
        "Capacitor, nut mua chay IAP (StoreKit, SK-IAP-V1) thay cho VietQR.\n"
        "     .cta co display:flex nen [hidden] can rule rieng. */",
        "I1b comment CSS nut mua")
    print("ap dung I1b comment CSS nut mua OK")

    # I2 — comment tren trang goi: IAP thay cho "huong dan mua bang chu".
    s = replace_once(
        s, "    <!-- Trang giới thiệu gói Premium (mở từ dialog, nút \"Nâng cấp Premium\"\n"
           "         ở Tokutei, hoặc mục \"Nâng cấp Premium\" ở Cài đặt): nội dung như\n"
           "         trang #/nangcap bản web — 2 gói, quyền lợi từng gói, ghi chú giảm\n"
           "         giá. Trên mobile web (PWA) mỗi gói có nút mua mở trang thanh toán\n"
           "         VietQR (#skCheckoutOverlay); trong app bọc Capacitor nút mua bị ẩn\n"
           "         (quy tắc App Store 3.1.1 — IAP sau), chỉ còn hướng dẫn mua bằng chữ. -->",
        "    <!-- Trang giới thiệu gói Premium (mở từ dialog, nút \"Nâng cấp Premium\"\n"
        "         ở Tokutei, hoặc mục \"Nâng cấp Premium\" ở Cài đặt): 2 gói + quyền lợi\n"
        "         từng gói. Trong app bọc Capacitor, mua qua IAP (StoreKit 2,\n"
        "         SK-IAP-V1): giá lấy từ App Store, nút Mua + Khôi phục giao dịch +\n"
        "         Quản lý gói; KHÔNG có hướng dẫn mua trên web trong app (quy tắc\n"
        "         App Store 3.1.1). Bản PWA giữ luồng VietQR (#skCheckoutOverlay). -->",
        "I2 comment trang goi")
    print("ap dung I2 comment trang goi OK")

    # I2b — comment trang thanh toan VietQR: IAP da thay the (khong con "sau").
    s = replace_once(
        s, "         KHÔNG mở trong app bọc Capacitor (gate skIsNativeApp — App Store\n"
           "         3.1.1, IAP sẽ thay thế sau). Nút \"Tôi đã chuyển khoản\" chỉ ghi",
        "         KHÔNG mở trong app bọc Capacitor (gate skIsNativeApp — App Store\n"
        "         3.1.1, IAP đã thay thế — SK-IAP-V1). Nút \"Tôi đã chuyển khoản\" chỉ ghi",
        "I2b comment trang thanh toan")
    print("ap dung I2b comment trang thanh toan OK")

    # I3 — xoa banner sale .pw-sale (gia sale web khong ap cho IAP) + rule
    # CSS cua no (chet sau khi xoa banner).
    s = replace_once(
        s, '        <div class="pw-sale">🎉 Ưu đãi ra mắt — giảm giá đến <b>06/12/2026</b> (ngày thi JLPT). Sau thời gian này gói về giá gốc.</div>\n',
        "",
        "I3 xoa banner sale")
    s = replace_once(
        s, "  .pw-sale{background:var(--red-soft); border:1px solid var(--line); border-radius:14px; padding:12px 14px; font-size:13.5px; line-height:1.6; margin:0 0 14px;}\n",
        "",
        "I3 xoa CSS pw-sale")
    print("ap dung I3 xoa banner sale OK")

    # I4 — gia Goi Nam: bo hardcode + gia goc + "Tiet kiem" -> placeholder
    # StoreKit dien vao; dong "~990d/ngay" (suy ra tu gia web) -> tu gia han.
    s = replace_once(
        s, '            <span class="pw-price">360.000đ</span><span class="pw-old">799.000đ</span>\n'
           '            <span class="pw-save">Tiết kiệm 439.000đ</span>',
        '            <span class="pw-price" id="pwPriceYear">…</span>',
        "I4 gia Goi Nam")
    s = replace_once(
        s, '<div class="pw-per">Chỉ ~990đ/ngày</div>',
        '<div class="pw-per">Tự động gia hạn mỗi năm</div>',
        "I4 dong gia/ngay")
    print("ap dung I4 gia Goi Nam OK")

    # I5 — gia Goi Tron doi: tuong tu.
    s = replace_once(
        s, '            <span class="pw-price">999.000đ</span><span class="pw-old">2.499.000đ</span>\n'
           '            <span class="pw-save">Tiết kiệm 1.500.000đ</span>',
        '            <span class="pw-price" id="pwPriceLifetime">…</span>',
        "I5 gia Goi Tron doi")
    print("ap dung I5 gia Goi Tron doi OK")

    # I6 — khoi .pw-guide: huong dan mua web -> khoi IAP (Khoi phuc + Quan ly).
    s = replace_once(
        s, '        <div class="pw-guide" id="pwGuide">\n'
           '          <b>Cách mua gói</b>\n'
           '          <p>Mở trình duyệt Chrome trên điện thoại của bạn, đăng nhập tài khoản SoraKanji tại sorakanji.com, chọn gói và thanh toán bằng VND. Sau khi chuyển khoản thành công, Premium sẽ được mở cho tài khoản của bạn — thường trong vài phút, tối đa 24 giờ.</p>\n'
           '        </div>',
        IAP_GUIDE,
        "I6 khoi IAP thay pw-guide")
    print("ap dung I6 khoi IAP thay pw-guide OK")

    # I7 — Dieu khoan §3: cau gia viet lai khong kem so gia cu the.
    s = replace_once(
        s, '          <p>Giá gói theo bảng giá tại thời điểm mua (giá hiện tại: Gói Năm 360.000đ, Gói Trọn đời 999.000đ). SoraKanji có thể điều chỉnh bảng giá; giá đã thanh toán không thay đổi.</p>',
        '          <p>Giá gói theo bảng giá tại thời điểm mua, hiển thị trên trang gói trước khi bạn xác nhận mua. SoraKanji có thể điều chỉnh bảng giá; giá đã thanh toán không thay đổi.</p>',
        "I7 Dieu khoan §3 gia")
    print("ap dung I7 Dieu khoan §3 gia OK")

    # I8 — Dieu khoan §4: GIU doan chuyen khoan web + gioi han cau "khong tu
    # gia han" cho web + THEM doan mua trong app qua Apple.
    s = replace_once(
        s, '            <li>Gói trả phí <b>không tự động gia hạn</b>. Khi Gói Năm hết hạn, bạn có thể mua lại nếu muốn tiếp tục sử dụng.</li>',
        '            <li>Gói mua bằng chuyển khoản trên web <b>không tự động gia hạn</b>. Khi Gói Năm hết hạn, bạn có thể mua lại nếu muốn tiếp tục sử dụng.</li>\n'
        '            <li>Mua trong ứng dụng iOS: thanh toán qua Apple (App Store) — giá hiển thị trên trang gói trước khi bạn xác nhận mua. Gói Năm mua trong ứng dụng <b>tự động gia hạn mỗi năm</b> trừ khi bạn hủy ít nhất 24 giờ trước khi hết hạn; bạn quản lý và hủy gói trong Cài đặt iPhone → Apple ID → Đăng ký, hoặc qua liên kết “Quản lý gói” trong trang gói. Gói Trọn đời chỉ thanh toán một lần, không gia hạn.</li>\n'
        '            <li>Hoàn tiền cho gói mua trong ứng dụng iOS do Apple quyết định theo chính sách của Apple (yêu cầu tại reportaproblem.apple.com); SoraKanji không tự hoàn tiền các giao dịch qua App Store.</li>',
        "I8 Dieu khoan §4 IAP")
    print("ap dung I8 Dieu khoan §4 IAP OK")

    # I9 — Sora FAQ topic premium: viet lai cho native (khong gia hardcode,
    # khong huong dan mua web). 2 doan con lien tuc — thay tung doan.
    s = replace_once(
        s, 'Gói Premium mở toàn bộ nội dung N3–N1, ôn thi Tokutei xây dựng, xem trọn vẹn mọi video Shadowing và tạo video không giới hạn: Gói Năm 360.000đ (giá gốc 799.000đ, dùng 12 tháng), Gói Trọn đời 999.000đ (giá gốc 2.499.000đ, dùng vĩnh viễn). Giá giảm đến 06/12/2026.',
        'Gói Premium mở toàn bộ nội dung N3–N1, ôn thi Tokutei xây dựng, xem trọn vẹn mọi video Shadowing và tạo video không giới hạn: Gói Năm (dùng 12 tháng) và Gói Trọn đời (dùng vĩnh viễn) — giá hiển thị trên trang gói.',
        "I9 Sora FAQ gia")
    s = replace_once(
        s, 'Cách mua: mở trình duyệt Chrome trên điện thoại, đăng nhập tài khoản SoraKanji tại sorakanji.com, chọn gói và thanh toán bằng VND. Premium mở sau khi chuyển khoản thành công — thường trong vài phút, tối đa 24 giờ.',
        'Cách mua: mở trang Nâng cấp Premium trong app (Cài đặt → Nâng cấp Premium), chọn gói và thanh toán qua Apple — giá hiển thị trên từng gói trước khi bạn xác nhận. Gói Năm tự động gia hạn mỗi năm, hủy được bất cứ lúc nào trong Cài đặt iPhone → Apple ID → Đăng ký. Premium mở ngay sau khi thanh toán thành công.',
        "I9 Sora FAQ cach mua")
    print("ap dung I9 Sora FAQ premium OK")

    # I9b — khoi m-32 viet lai cau tra loi theo ngu canh (PWA: VietQR;
    # native: trinh duyet): trong ban boc, cau tra loi goc DA LA ban native
    # (I9) nen khoi nay khong con tac dung — xoa ca chuoi tim kiem cu (chua
    # huong dan mua web) khoi file.
    s = replace_once(
        s, '        /* m-32: câu trả lời cách mua theo ngữ cảnh — mobile web/PWA đã mua\n'
           '           trực tiếp trong app bằng VietQR (20/11), chỉ app bọc native mới\n'
           '           phải mua qua trình duyệt (chưa có IAP). */\n'
           '        if(t.id === "premium" && typeof skIsNativeApp === "function" && !skIsNativeApp()){\n'
           '          ans = ans.replace("Cách mua: mở trình duyệt Chrome trên điện thoại, đăng nhập tài khoản SoraKanji tại sorakanji.com, chọn gói và thanh toán bằng VND.",\n'
           '            "Cách mua: mua trực tiếp trong app — mở tab Cài đặt → Nâng cấp Premium, chọn gói rồi chuyển khoản qua mã VietQR hiện trong app.");\n'
           '        }\n',
        '        /* IAP: câu trả lời premium đã là bản native (mua qua Apple) —\n'
        '           không cần viết lại theo ngữ cảnh như m-32 trên PWA. */\n',
        "I9b xoa khoi m-32")
    print("ap dung I9b xoa khoi m-32 OK")

    # I10 — skStartCheckout: trong app boc thi re sang IAP thay cho return som
    # (y dinh mua + skResumePendingGate chay nhu cu).
    s = replace_once(
        s, "    if(skIsNativeApp()) return; /* GATE NATIVE: không tạo đơn trong app bọc */",
        "    if(skIsNativeApp()){ skIapBuy(pkg); return; } /* GATE NATIVE: mua trong app qua IAP (StoreKit) thay cho VietQR */",
        "I10 skStartCheckout re IAP")
    s = replace_once(
        s, "     đăng nhập — xem skResumePendingGate). Thứ tự kiểm tra:\n"
           "     native → đang tạo đơn → đã Premium → chưa đăng nhập → chưa có email →",
        "     đăng nhập — xem skResumePendingGate). Thứ tự kiểm tra:\n"
        "     native (IAP) → đang tạo đơn → đã Premium → chưa đăng nhập → chưa có email →",
        "I10 comment skStartCheckout")
    print("ap dung I10 skStartCheckout re IAP OK")

    # I11 — skCheckoutInit: trong app boc thi HIEN nut mua (IAP) thay cho an;
    # wire nut Khoi phuc / Quan ly + goi skIapInit().
    old_init = (
        "  /* Khởi tạo luồng mua (gọi trong setTimeout init của paywall): wire nút\n"
        "     mua + nút đóng trang thanh toán + mục \"Nâng cấp Premium\" ở Cài đặt.\n"
        "     GATE NATIVE — trong app bọc thì ẨN nút mua (chỉ còn hướng dẫn mua bằng\n"
        "     chữ), trên mobile web thì ẨN hướng dẫn mua bằng chữ (mua ngay tại đây). */\n"
        "  function skCheckoutInit(){\n"
        "    var native = skIsNativeApp();\n"
        "    var by = document.getElementById(\"pwBuyYear\");\n"
        "    var bl = document.getElementById(\"pwBuyLifetime\");\n"
        "    var guide = document.getElementById(\"pwGuide\");\n"
        "    if(by){\n"
        "      by.hidden = native;\n"
        "      if(!native) by.addEventListener(\"click\", function(){ skStartCheckout(\"year\"); });\n"
        "    }\n"
        "    if(bl){\n"
        "      bl.hidden = native;\n"
        "      if(!native) bl.addEventListener(\"click\", function(){ skStartCheckout(\"lifetime\"); });\n"
        "    }\n"
        "    if(guide) guide.hidden = !native;\n"
    )
    new_init = (
        "  /* Khởi tạo luồng mua (gọi trong setTimeout init của paywall): wire nút\n"
        "     mua + nút đóng trang thanh toán + mục \"Nâng cấp Premium\" ở Cài đặt.\n"
        "     Trong app bọc native, nút mua chạy IAP (StoreKit, SK-IAP-V1) thay cho\n"
        "     VietQR (skStartCheckout tự rẽ nhánh theo skIsNativeApp); khối IAP dưới\n"
        "     trang gói có nút Khôi phục giao dịch + Quản lý gói. Trên mobile web\n"
        "     thì nút mua mở trang thanh toán VietQR như cũ. */\n"
        "  function skCheckoutInit(){\n"
        "    var native = skIsNativeApp();\n"
        "    var by = document.getElementById(\"pwBuyYear\");\n"
        "    var bl = document.getElementById(\"pwBuyLifetime\");\n"
        "    var guide = document.getElementById(\"pwGuide\");\n"
        "    if(by){\n"
        "      by.hidden = false;\n"
        "      by.addEventListener(\"click\", function(){ skStartCheckout(\"year\"); });\n"
        "    }\n"
        "    if(bl){\n"
        "      bl.hidden = false;\n"
        "      bl.addEventListener(\"click\", function(){ skStartCheckout(\"lifetime\"); });\n"
        "    }\n"
        "    if(guide) guide.hidden = !native;\n"
        "    if(native){\n"
        "      var rb = document.getElementById(\"pwRestoreBtn\");\n"
        "      if(rb) rb.addEventListener(\"click\", skIapRestore);\n"
        "      var mb = document.getElementById(\"pwManageBtn\");\n"
        "      if(mb) mb.addEventListener(\"click\", skIapManage);\n"
        "      try{ skIapInit(); }catch(_){}\n"
        "    }\n"
    )
    s = replace_once(s, old_init, new_init, "I11 skCheckoutInit IAP")
    print("ap dung I11 skCheckoutInit IAP OK")

    # I12 — openPwPlans: tai gia tu StoreKit moi lan mo trang goi (native).
    s = replace_once(
        s, "    showOv(ov);\n  }\n  function closePwPlans(){",
        "    showOv(ov);\n    if(skIsNativeApp()) skIapLoadProducts(); /* IAP: tai gia tu StoreKit moi lan mo trang goi */\n  }\n  function closePwPlans(){",
        "I12 openPwPlans tai gia")
    print("ap dung I12 openPwPlans tai gia OK")

    # I13 — khoi module JS IAP (chen truoc doGoogleLogin, sau khoi native-auth).
    s = replace_once(
        s, "  function doGoogleLogin(){",
        IAP_JS + "  function doGoogleLogin(){",
        "I13 khoi module JS IAP")
    print("ap dung I13 khoi module JS IAP OK")

    # I14 — applyAuthUser: doi chieu giao dich sau khi dang nhap (bat truong
    # hop mo app luc chua dang nhap roi moi dang nhap).
    s = replace_once(
        s, "      skSyncOnLogin(user.uid);",
        "      skSyncOnLogin(user.uid);\n"
        "      try{ skIapReconcile(); }catch(_){} /* IAP: doi chieu giao dich chua verify sau khi dang nhap */",
        "I14 doi chieu sau dang nhap")
    print("ap dung I14 doi chieu sau dang nhap OK")

    # I16 — comment khoi VietQR: cap nhat GATE NATIVE + bo so gia cu the
    # (gia web chi con trong SK_PACKAGES — du lieu luong PWA, khong hien).
    s = replace_once(
        s, "     GATE NATIVE (App Store 3.1.1): trong app bọc Capacitor, KHÔNG hiện\n"
           "     luồng VietQR — nút mua ẩn (skCheckoutInit), chỉ còn hướng dẫn mua bằng\n"
           "     chữ; IAP sẽ thay thế sau theo plan riêng. Phát hiện native qua\n"
           "     window.Capacitor, an toàn khi Capacitor vắng mặt (PWA).\n"
           "     Giá: Năm 360.000đ, Trọn đời 999.000đ (giảm đến 06/12/2026, sau đó về\n"
           "     giá gốc 799.000đ / 2.499.000đ — cùng luật skPrice của web). */",
        "     GATE NATIVE (App Store 3.1.1): trong app bọc Capacitor, KHÔNG hiện\n"
        "     luồng VietQR — nút mua chạy IAP (StoreKit, SK-IAP-V1) thay cho VietQR.\n"
        "     Phát hiện native qua window.Capacitor, an toàn khi Capacitor vắng mặt\n"
        "     (PWA). Giá web lấy từ SK_PACKAGES + luật skPrice (sale đến 06/12/2026,\n"
        "     sau đó về giá gốc) — chỉ dùng cho luồng VietQR trên PWA; trong app\n"
        "     bọc, giá lấy từ StoreKit, không dùng các hằng này. */",
        "I16 comment khoi VietQR")
    print("ap dung I16 comment khoi VietQR OK")

    # Kiem tra sau: moi khoi chi xuat hien dung so lan du kien; gia hardcode
    # + huong dan mua web da bien mat khoi ban boc.
    checks = [
        (MARKER, 6, "marker SK-IAP-V1 (module JS + 5 comment)"),
        ('id="pwPriceYear"', 1, "span gia Nam"),
        ('id="pwPriceLifetime"', 1, "span gia Tron doi"),
        ('id="pwRestoreBtn"', 1, "nut Khoi phuc"),
        ('id="pwManageBtn"', 1, "nut Quan ly goi"),
        ('id="pwIapNote"', 1, "ghi chu IAP"),
        ("function skIapBuy(", 1, "skIapBuy"),
        ("function skIapRestore(", 1, "skIapRestore"),
        ("function skIapLoadProducts(", 1, "skIapLoadProducts"),
        ("function skIapReconcile(", 1, "skIapReconcile"),
        ("function skIapVerify(", 1, "skIapVerify"),
        ("function skIapPlugin(", 1, "skIapPlugin"),
        ("function skIapInit(", 1, "skIapInit"),
        ("function skIapManage(", 1, "skIapManage"),
        ("function skIapHandleTransaction(", 1, "skIapHandleTransaction"),
        ("pw-sale", 0, "banner sale + CSS cua no (da xoa)"),
        ("360.000đ", 0, "gia hardcode 360.000d"),
        ("799.000đ", 0, "gia hardcode 799.000d"),
        ("999.000đ", 0, "gia hardcode 999.000d"),
        ("2.499.000đ", 0, "gia hardcode 2.499.000d"),
        ("Tiết kiệm ", 0, "dong Tiet kiem"),
        ("Chỉ ~990đ/ngày", 0, "dong gia/ngay"),
        ("Cách mua gói", 0, "tieu de huong dan mua web"),
        ("sorakanji.com, chọn gói", 0, "huong dan mua web (trang goi/Sora)"),
        ("Giá giảm đến 06/12/2026", 0, "chuoi gia giam (trang goi/Sora)"),
    ]
    for sub, want, name in checks:
        n = s.count(sub)
        if n != want:
            fail("kiem tra sau: %s xuat hien %d lan (can %d)" % (name, n, want))
    node_check_inline(s)

    target.write_text(s, encoding="utf-8")
    print("%s: transform xong (%d byte)" % (target, len(s.encode("utf-8"))))


def update_capacitor_config():
    """I15 — tat auto-finish o tang plugin trong capacitor.config.json goc
    (cap sync se truyen xuong ban copy ios/android). Plugin doc
    plugins.NativePurchases.autoFinishTransactions truoc khi listener
    transactionUpdated chay — can thiet de giao dich khong bi finish som
    truoc khi server verify xong."""
    root = Path(__file__).resolve().parent
    cfg_path = root / "capacitor.config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    plugins = cfg.setdefault("plugins", {})
    np = plugins.setdefault("NativePurchases", {})
    if np.get("autoFinishTransactions") is False:
        print("capacitor.config.json: autoFinishTransactions da la false, khong doi gi")
        return
    np["autoFinishTransactions"] = False
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("capacitor.config.json: dat plugins.NativePurchases.autoFinishTransactions=false")


if __name__ == "__main__":
    main()
    update_capacitor_config()
