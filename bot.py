import os
import re
import json
import time
import calendar
import requests
from datetime import datetime, timezone, timedelta

# ==============================================================================
# 🛠️ KHU VỰC CẤU HÌNH HỆ THỐNG
# ==============================================================================
KPI_MESS = int(os.environ.get("KPI_GIA_MESS") or "60000")
THUE_VAT_FB = float(os.environ.get("THUE_VAT_FB") or "10.0")
GIO_BAO_CAO_SANG = 8
GIO_BAO_CAO_TOI = 20
THOI_GIAN_DUY_TRI_PHIEN = 54 * 60

FB_TOKEN = (os.environ.get("FB_ACCESS_TOKEN") or "").strip()
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
OPENAI_KEY = (os.environ.get("OPENAI_API_KEY") or "").strip()
TELE_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
if TELE_TOKEN.startswith("bot"):
    TELE_TOKEN = TELE_TOKEN[3:]

CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "5657736528").strip()
SHEET_WEBHOOK_URL = (os.environ.get("SHEET_WEBHOOK_URL") or "").strip()

AI_UU_TIEN = "gemini"

BO_NHO_BM = {}
BO_NHO_TK = {}
BO_NHO_AUDIT = {}
TRANG_THAI_LICH = {}
KY_TUY_CHINH = None
DA_BAO_CAO_TRONG_PHIEN = set()

NHAN_THOI_GIAN = {
    "today": "Hôm nay (Realtime)",
    "yesterday": "Hôm qua",
    "last_3d": "3 ngày qua",
    "last_7d": "7 ngày qua",
    "this_month": "Tháng này",
    "last_month": "Tháng trước",
    "last_30d": "30 ngày qua",
}

BAN_PHIM_CO_DINH = {
    "keyboard": [
        [{"text": "💳 Danh Sách Tài Khoản"}, {"text": "📊 Báo Cáo Tổng (4 TK)"}],
        [{"text": "💰 Rà Soát Ngân Sách"}, {"text": "🏦 Công Nợ & Cài Đặt"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}


# ==============================================================================
# 0. CÀI ĐẶT MENU LỆNH TELEGRAM & TIỆN ÍCH ĐỊNH DẠNG
# ==============================================================================
def cai_dat_menu_lenh_telegram():
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/setMyCommands"
    commands = [
        {"command": "menu", "description": "💳 Mở Danh sách Tài khoản"},
        {"command": "baocao", "description": "📊 Mở Báo cáo Tổng (4 TK)"},
        {"command": "rasoat", "description": "💰 Mở Rà soát Ngân sách"},
        {"command": "sheet", "description": "📥 Điền Cả Tháng (1 -> Nay) vào Google Sheet"},
        {"command": "congno", "description": "🏦 Kiểm tra Công nợ & Cài đặt AI"},
        {"command": "lich", "description": "📅 Mở Bảng Lịch chọn ngày"},
    ]
    try:
        requests.post(url, json={"commands": commands}, timeout=5)
    except Exception:
        pass


def lay_gio_viet_nam():
    return datetime.now(timezone(timedelta(hours=7)))


def rut_gon_ten_tk(ten):
    s = ten.replace("Nội Thất", "NT").replace("Nội thất", "NT")
    s = s.replace("Sản Phẩm", "SP").replace("Sản phẩm", "SP")
    s = re.sub(r"\s*-\s*", "-", s)
    return s[:18]


def dinh_dang_tien_gon(so_tien):
    if so_tien >= 1000000:
        return f"{so_tien/1000000:.2f}M".replace(".00M", "M")
    elif so_tien >= 1000:
        return f"{int(so_tien/1000)}k"
    return f"{so_tien}đ"


def lay_nhan_ky_du_lieu(tg):
    if tg == "custom" and KY_TUY_CHINH:
        return KY_TUY_CHINH[2]
    return NHAN_THOI_GIAN.get(tg, tg)


def tach_ten_cum(ten_camp):
    s = ten_camp.strip()
    s = re.sub(r"^\d+[\.\)\-\s]+", "", s).strip()
    parts = re.split(r"[\-\|\:\/–—]", s)
    if len(parts) > 1 and len(parts[0].strip()) >= 1:
        prefix = parts[0].strip().upper()
    else:
        words = s.split()
        prefix = words[0].upper() if words else "KHAC"

    if prefix in ["TRUS", "TRUST"]:
        return "TRUST"
    return prefix[:15]


def gom_cum_chien_dich(ds_camps_list):
    cum_dict = {}
    for c_info in ds_camps_list:
        ten_cum = tach_ten_cum(c_info["ten"])
        if ten_cum not in cum_dict:
            cum_dict[ten_cum] = {
                "ten_cum": ten_cum,
                "so_camp": 0,
                "chi_tieu": 0,
                "tin_nhan": 0,
                "binh_luan": 0,
                "clicks": 0,
                "impressions": 0,
                "reach": 0,
                "video_3s": 0,
                "thruplay": 0,
                "ds_camps": [],
            }
        g = cum_dict[ten_cum]
        g["so_camp"] += 1
        g["chi_tieu"] += c_info["chi_tieu"]
        g["tin_nhan"] += c_info["tin_nhan"]
        g["binh_luan"] += c_info["binh_luan"]
        g["clicks"] += c_info["clicks"]
        g["impressions"] += c_info["impressions"]
        g["reach"] += c_info["reach"]
        g["video_3s"] += c_info.get("video_3s", 0)
        g["thruplay"] += c_info.get("thruplay", 0)
        g["ds_camps"].append(c_info)

    ds_cum_sorted = sorted(cum_dict.values(), key=lambda x: x["chi_tieu"], reverse=True)
    for idx, item in enumerate(ds_cum_sorted):
        item["cum_idx"] = str(idx)
    return ds_cum_sorted


# ==============================================================================
# 1. ĐỒNG BỘ GOOGLE SHEET SIÊU TỐC (GỬI 1 LẦN, KHÔNG BAO GIỜ TIMEOUT)
# ==============================================================================
def xac_dinh_khoang_ngay_tu_preset(che_do):
    now_vn = lay_gio_viet_nam()
    hom_nay = now_vn.strftime("%Y-%m-%d")
    hom_qua = (now_vn - timedelta(days=1)).strftime("%Y-%m-%d")

    if che_do == "today":
        return hom_nay, hom_nay
    if che_do == "yesterday":
        return hom_qua, hom_qua
    if che_do == "last_3d":
        return (now_vn - timedelta(days=3)).strftime("%Y-%m-%d"), hom_qua
    if che_do == "last_7d":
        return (now_vn - timedelta(days=7)).strftime("%Y-%m-%d"), hom_qua
    if che_do == "this_month":
        return now_vn.replace(day=1).strftime("%Y-%m-%d"), hom_nay
    if che_do == "last_month":
        dau_thang_nay = now_vn.replace(day=1)
        cuoi_thang_truoc = dau_thang_nay - timedelta(days=1)
        dau_thang_truoc = cuoi_thang_truoc.replace(day=1)
        return dau_thang_truoc.strftime("%Y-%m-%d"), cuoi_thang_truoc.strftime("%Y-%m-%d")
    if che_do == "last_30d":
        return (now_vn - timedelta(days=30)).strftime("%Y-%m-%d"), hom_qua
    if che_do == "custom" and KY_TUY_CHINH:
        return KY_TUY_CHINH[0], KY_TUY_CHINH[1]
    return hom_qua, hom_qua


def dong_bo_khoang_ngay_len_sheet(since_ymd, until_ymd):
    """
    Quét dữ liệu tách theo từng ngày từ Facebook (chỉ 1 request mỗi TK),
    sau đó gửi 1 gói Batch lên Apps Script mới để điền vào bảng 6 cột trong 0.5 giây.
    """
    global BO_NHO_BM
    if not SHEET_WEBHOOK_URL:
        return False, "⚠️ Chưa có SHEET_WEBHOOK_URL trong GitHub Secrets."

    if not BO_NHO_BM:
        BO_NHO_BM = quet_danh_sach_tai_khoan()

    tong_theo_ngay = {}
    cum_theo_ngay = {}

    for tk_idx, tk_info in BO_NHO_BM.items():
        url_ins = f"https://graph.facebook.com/v21.0/{tk_info['id']}/insights"
        params = {
            "level": "campaign",
            "time_increment": 1,
            "time_range": json.dumps({"since": since_ymd, "until": until_ymd}),
            "fields": "campaign_name,spend,actions,date_start",
            "limit": 1000,
            "access_token": FB_TOKEN,
        }
        try:
            r_ins = requests.get(url_ins, params=params, timeout=20).json()
        except Exception:
            continue

        for row in r_ins.get("data", []):
            spend = int(float(row.get("spend", 0)))
            if spend <= 0:
                continue
            ngay = row.get("date_start")
            c_name = row.get("campaign_name", "Khác")
            ten_cum = tach_ten_cum(c_name)
            mess, cmt, _, _, _ = trich_xuat_ket_qua(row.get("actions", []))

            # 1. Cộng dồn vào Tab 'Tổng'
            if ngay not in tong_theo_ngay:
                tong_theo_ngay[ngay] = {"spend": 0, "mess": 0, "cmt": 0}
            tong_theo_ngay[ngay]["spend"] += spend
            tong_theo_ngay[ngay]["mess"] += mess
            tong_theo_ngay[ngay]["cmt"] += cmt

            # 2. Cộng dồn vào Tab từng Cụm riêng biệt
            key_cum = (ten_cum, ngay)
            if key_cum not in cum_theo_ngay:
                cum_theo_ngay[key_cum] = {"spend": 0, "mess": 0, "cmt": 0}
            cum_theo_ngay[key_cum]["spend"] += spend
            cum_theo_ngay[key_cum]["mess"] += mess
            cum_theo_ngay[key_cum]["cmt"] += cmt

    ds_items = []
    for ngay, val in sorted(tong_theo_ngay.items()):
        thue = int(val["spend"] * (THUE_VAT_FB / 100.0))
        ds_items.append({
            "tab_name": "Tổng",
            "ngay": ngay,
            "spend": val["spend"],
            "tax": thue,
            "total": val["spend"] + thue,
            "mess": val["mess"],
            "cmt": val["cmt"],
        })

    for (ten_cum, ngay), val in sorted(cum_theo_ngay.items()):
        thue = int(val["spend"] * (THUE_VAT_FB / 100.0))
        ds_items.append({
            "tab_name": ten_cum,
            "ngay": ngay,
            "spend": val["spend"],
            "tax": thue,
            "total": val["spend"] + thue,
            "mess": val["mess"],
            "cmt": val["cmt"],
        })

    if not ds_items:
        return True, f"ℹ️ Không có phát sinh chi tiêu nào trong kỳ ({since_ymd} ➔ {until_ymd})."

    try:
        r = requests.post(
            SHEET_WEBHOOK_URL,
            json={"items": ds_items},
            timeout=45,
            allow_redirects=True,
        )
        so_ngay = len(tong_theo_ngay)
        ds_cum = sorted(list({k[0] for k in cum_theo_ngay.keys()}))
        try:
            js = r.json()
            if js.get("status") == "success":
                return True, (
                    f"✅ Đã cập nhật thành công lên Google Sheet!\n"
                    f"• Kỳ dữ liệu: {since_ymd} ➔ {until_ymd} ({so_ngay} ngày có chi tiêu)\n"
                    f"• Các Tab đã điền (6 cột chuẩn): Tổng, {', '.join(ds_cum)}"
                )
            return False, f"⚠️ Lỗi từ Google Sheet: {js.get('message', 'Không rõ')}"
        except Exception:
            if r.status_code == 200:
                return True, (
                    f"✅ Đã đồng bộ thành công lên Google Sheet!\n"
                    f"• Kỳ dữ liệu: {since_ymd} ➔ {until_ymd} ({so_ngay} ngày)\n"
                    f"• Các Tab: Tổng, {', '.join(ds_cum)}"
                )
            return False, f"⚠️ HTTP Status: {r.status_code}"
    except Exception as e:
        return False, f"⚠️ Lỗi kết nối Google Sheet: {e}"


# ==============================================================================
# 2. BẢNG LỊCH 7 CỘT & PHÂN TÍCH NGÀY TÙY CHỈNH (ĐẦY ĐỦ 100%)
# ==============================================================================
def phan_tich_ngay_tuy_chinh(text_in):
    now_vn = lay_gio_viet_nam()
    nam_ht = now_vn.year
    s = re.sub(r"^(/ngay|/rasoat|ngay|ngày)\s*", "", text_in.strip(), flags=re.IGNORECASE).strip()

    m_range = re.match(
        r"^(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?\s*(?:đến|den|to|\-|\~)\s*(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?$",
        s,
    )
    if m_range:
        d1, m1, y1, d2, m2, y2 = m_range.groups()
        y1 = int(y1) if y1 else nam_ht
        y2 = int(y2) if y2 else nam_ht
        if y1 < 100:
            y1 += 2000
        if y2 < 100:
            y2 += 2000
        try:
            dt1 = datetime(y1, int(m1), int(d1))
            dt2 = datetime(y2, int(m2), int(d2))
            if dt1 > dt2:
                dt1, dt2 = dt2, dt1
            return (
                dt1.strftime("%Y-%m-%d"),
                dt2.strftime("%Y-%m-%d"),
                f"{dt1.strftime('%d/%m/%Y')} - {dt2.strftime('%d/%m/%Y')}",
            )
        except ValueError:
            return None

    m_single = re.match(r"^(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?$", s)
    if m_single:
        d1, m1, y1 = m_single.groups()
        y1 = int(y1) if y1 else nam_ht
        if y1 < 100:
            y1 += 2000
        try:
            dt1 = datetime(y1, int(m1), int(d1))
            ymd = dt1.strftime("%Y-%m-%d")
            return ymd, ymd, f"Ngày {dt1.strftime('%d/%m/%Y')}"
        except ValueError:
            return None

    return None


def hien_bang_lich(cid, msg_id=None, target="AUDIT", nam=None, thang=None):
    now_vn = lay_gio_viet_nam()
    if not nam or not thang:
        nam, thang = now_vn.year, now_vn.month

    st = TRANG_THAI_LICH.get(cid, {})
    ngay_bat_dau = st.get("start")

    thang_truoc = thang - 1 if thang > 1 else 12
    nam_truoc = nam if thang > 1 else nam - 1
    thang_sau = thang + 1 if thang < 12 else 1
    nam_sau = nam if thang < 12 else nam + 1

    nut = [
        [
            {"text": f"⏪ T{thang_truoc:02d}/{nam_truoc}", "callback_data": f"CAL_NAV|{target}|{nam_truoc}|{thang_truoc}"},
            {"text": f"🗓 THÁNG {thang:02d}/{nam}", "callback_data": "CAL_IGNORE"},
            {"text": f"T{thang_sau:02d}/{nam_sau} ⏩", "callback_data": f"CAL_NAV|{target}|{nam_sau}|{thang_sau}"},
        ],
        [{"text": t, "callback_data": "CAL_IGNORE"} for t in ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]],
    ]

    cal = calendar.Calendar(firstweekday=0)
    for tuan in cal.monthdayscalendar(nam, thang):
        hang = []
        for ngay in tuan:
            if ngay == 0:
                hang.append({"text": "·", "callback_data": "CAL_IGNORE"})
            else:
                ymd = f"{nam:04d}-{thang:02d}-{ngay:02d}"
                if ngay_bat_dau == ymd:
                    nhan = f"✅{ngay}"
                elif ymd == now_vn.strftime("%Y-%m-%d"):
                    nhan = f"{ngay}📍"
                else:
                    nhan = str(ngay)
                hang.append({"text": nhan, "callback_data": f"CAL_DAY|{target}|{ymd}"})
        nut.append(hang)

    if ngay_bat_dau:
        d_dep = datetime.strptime(ngay_bat_dau, "%Y-%m-%d").strftime("%d/%m/%Y")
        nut.append([{"text": f"🔍 Xem ngay 1 ngày ({d_dep})", "callback_data": f"CAL_SINGLE|{target}|{ngay_bat_dau}"}])
        nut.append([{"text": "🔄 Chọn lại ngày khác", "callback_data": f"CAL_RESET|{target}|{nam}|{thang}"}])
        huong_dan = (
            f"✅ Đã chọn mốc đầu: {d_dep}\n"
            f"👉 Bấm [🔍 Xem ngay 1 ngày] hoặc chạm tiếp vào ngày thứ 2 trên lịch để chọn KHOẢNG NGÀY (VD: 1/10 -> 19/10)!"
        )
    else:
        huong_dan = (
            "👉 Chạm vào 1 ngày trên lịch để chọn Ngày bắt đầu.\n"
            "• Xem 1 ngày: Chạm ngày đó ➔ Bấm [🔍 Xem ngay].\n"
            "• Xem & Đồng bộ nhiều ngày: Chạm ngày đầu ➔ Chạm tiếp ngày cuối."
        )

    nut.append([{"text": "⬅️ Quay lại", "callback_data": "MENU_AUDIT"}])
    gui_hoac_sua_menu(cid, f"📅 BẢNG LỊCH CHỌN NGÀY\n━━━━━━━━━━━━━━━━━━━━\n{huong_dan}", nut, msg_id)


# ==============================================================================
# 3. QUÉT DỮ LIỆU FACEBOOK 5 TẦNG & AI KÉP (GEMINI + CHATGPT)
# ==============================================================================
def trich_xuat_ket_qua(actions_list, video_thruplay_list=None):
    mess, cmt, lead, video_3s, thruplay = 0, 0, 0, 0, 0
    for item in actions_list or []:
        loai = item.get("action_type", "")
        val = int(float(item.get("value", 0)))
        if loai == "onsite_conversion.messaging_conversation_started_7d":
            mess = val
        elif loai == "comment":
            cmt = val
        elif loai in ["lead", "purchase", "onsite_conversion.lead_grouped"]:
            lead += val
        elif loai == "video_view":
            video_3s = val

    for v_item in video_thruplay_list or []:
        thruplay += int(float(v_item.get("value", 0)))

    return mess, cmt, lead, video_3s, thruplay


def quet_danh_sach_tai_khoan():
    url = "https://graph.facebook.com/v21.0/me/adaccounts"
    params = {
        "fields": "id,name,account_status,disable_reason,amount_spent,balance,spend_cap,ad_trust_dsl,currency",
        "limit": 200,
        "access_token": FB_TOKEN,
    }
    resp = requests.get(url, params=params, timeout=20).json()
    if "error" in resp:
        msg = resp["error"].get("message", "Lỗi không xác định")
        raise Exception(f"Lỗi FB Token: {msg}")

    ds_tk = {}
    icon_map = {1: "🟢", 2: "🔴", 3: "🟡", 7: "🟠", 9: "⏳"}
    status_text_map = {1: "Hoạt động", 2: "Vô hiệu hóa", 3: "Nợ cước / Lỗi thẻ", 7: "Đang duyệt", 9: "Ân hạn nợ"}
    for idx, acc in enumerate(resp.get("data", [])):
        tk_idx = str(idx)
        st_code = acc.get("account_status", 1)
        currency = acc.get("currency", "VND")
        he_so = 1 if currency == "VND" else 100
        ds_tk[tk_idx] = {
            "tk_idx": tk_idx,
            "id": acc.get("id"),
            "ten": acc.get("name") or acc.get("id"),
            "icon": icon_map.get(st_code, "⚪"),
            "status_code": st_code,
            "status_text": status_text_map.get(st_code, f"Mã {st_code}"),
            "balance": int(float(acc.get("balance", 0))) // he_so,
            "amount_spent": int(float(acc.get("amount_spent", 0))) // he_so,
            "threshold": int(float(acc.get("ad_trust_dsl", 0))),
            "currency": currency,
        }
    return ds_tk


def tai_du_lieu_5_tang(ma_tk, khoang_tg="today", since_date=None, until_date=None):
    if khoang_tg == "custom" and KY_TUY_CHINH and not (since_date and until_date):
        since_date, until_date = KY_TUY_CHINH[0], KY_TUY_CHINH[1]

    url_camp = f"https://graph.facebook.com/v21.0/{ma_tk}/campaigns"
    r_camp = requests.get(
        url_camp,
        params={"fields": "id,name,effective_status", "limit": 500, "access_token": FB_TOKEN},
        timeout=20,
    ).json()
    ds_camp_goc = r_camp.get("data", []) if "error" not in r_camp else []
    tong_so_camp = len(ds_camp_goc)
    so_camp_active = sum(1 for c in ds_camp_goc if c.get("effective_status") == "ACTIVE")
    trang_thai_camp = {c["id"]: ("🟢 Đang bật" if c.get("effective_status") == "ACTIVE" else "⚪ Đã tắt") for c in ds_camp_goc}

    url_ins = f"https://graph.facebook.com/v21.0/{ma_tk}/insights"
    params = {
        "level": "ad",
        "fields": "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,spend,reach,impressions,frequency,cpm,clicks,ctr,cpc,actions,video_thruplay_watched_actions",
        "limit": 500,
        "access_token": FB_TOKEN,
    }
    if since_date and until_date:
        params["time_range"] = json.dumps({"since": since_date, "until": until_date})
    else:
        params["date_preset"] = khoang_tg if khoang_tg != "custom" else "today"

    r_ins = requests.get(url_ins, params=params, timeout=25).json()
    camps_raw = {}
    tong_tien_tk, tong_mess_tk = 0, 0

    for row in r_ins.get("data", []):
        spend = int(float(row.get("spend", 0)))
        if spend <= 0:
            continue
        c_id, c_name = row.get("campaign_id"), row.get("campaign_name", "Không tên")
        g_id, g_name = row.get("adset_id"), row.get("adset_name", "Không tên")
        a_id, a_name = row.get("ad_id"), row.get("ad_name", "Không tên")
        mess, cmt, _, video_3s, thruplay = trich_xuat_ket_qua(
            row.get("actions", []), row.get("video_thruplay_watched_actions", [])
        )
        clicks = int(float(row.get("clicks", 0)))
        impr = int(float(row.get("impressions", 0)))
        reach = int(float(row.get("reach", 0)))

        tong_tien_tk += spend
        tong_mess_tk += mess

        if c_id not in camps_raw:
            camps_raw[c_id] = {
                "id": c_id,
                "ten": c_name,
                "trang_thai": trang_thai_camp.get(c_id, "🟢 Có tiêu tiền"),
                "chi_tieu": 0, "tin_nhan": 0, "binh_luan": 0,
                "clicks": 0, "impressions": 0, "reach": 0,
                "video_3s": 0, "thruplay": 0, "groups_raw": {},
            }
        c = camps_raw[c_id]
        c["chi_tieu"] += spend; c["tin_nhan"] += mess; c["binh_luan"] += cmt
        c["clicks"] += clicks; c["impressions"] += impr; c["reach"] += reach
        c["video_3s"] += video_3s; c["thruplay"] += thruplay

        if g_id not in c["groups_raw"]:
            c["groups_raw"][g_id] = {
                "id": g_id, "ten": g_name, "chi_tieu": 0, "tin_nhan": 0,
                "binh_luan": 0, "clicks": 0, "impressions": 0, "reach": 0,
                "video_3s": 0, "thruplay": 0, "ads_raw": {},
            }
        g = c["groups_raw"][g_id]
        g["chi_tieu"] += spend; g["tin_nhan"] += mess; g["binh_luan"] += cmt
        g["clicks"] += clicks; g["impressions"] += impr; g["reach"] += reach
        g["video_3s"] += video_3s; g["thruplay"] += thruplay

        hook_rate = round((video_3s / impr) * 100, 1) if impr > 0 and video_3s > 0 else 0
        hold_rate = round((thruplay / video_3s) * 100, 1) if video_3s > 0 and thruplay > 0 else 0

        g["ads_raw"][a_id] = {
            "id": a_id, "ten": a_name, "chi_tieu": spend, "tin_nhan": mess,
            "gia_mess": int(spend / mess) if mess > 0 else 0, "binh_luan": cmt,
            "clicks": clicks, "impressions": impr, "reach": reach,
            "video_3s": video_3s, "thruplay": thruplay,
            "hook_rate": hook_rate, "hold_rate": hold_rate,
            "ctr": round(float(row.get("ctr", 0)), 2), "cpc": int(float(row.get("cpc", 0))),
            "cpm": int(float(row.get("cpm", 0))), "frequency": round(float(row.get("frequency", 0)), 2),
            "cr_click_to_mess": round((mess / clicks) * 100, 1) if clicks > 0 else 0,
        }

    camps_list = sorted(camps_raw.values(), key=lambda x: x["chi_tieu"], reverse=True)
    for c_idx, c_info in enumerate(camps_list):
        c_info["c_idx"] = str(c_idx)
        g_list = sorted(c_info["groups_raw"].values(), key=lambda x: x["chi_tieu"], reverse=True)
        for g_idx, g_info in enumerate(g_list):
            g_info["g_idx"] = str(g_idx)
            a_list = sorted(g_info["ads_raw"].values(), key=lambda x: x["chi_tieu"], reverse=True)
            for a_idx, a_info in enumerate(a_list):
                a_info["a_idx"] = str(a_idx)
            g_info["ads_list"] = a_list
        c_info["groups_list"] = g_list

    cum_list = gom_cum_chien_dich(camps_list)

    return {
        "tong_so_camp": tong_so_camp,
        "so_camp_active": so_camp_active,
        "so_camp_co_tieu_tien": len(camps_list),
        "tong_tien_tk": tong_tien_tk,
        "tong_mess_tk": tong_mess_tk,
        "camps_list": camps_list,
        "cum_list": cum_list,
        "thoi_diem_cap_nhat": lay_gio_viet_nam().strftime("%H:%M - %d/%m/%Y"),
    }


def tinh_chi_so_phu(item):
    tien = item["chi_tieu"]
    mess = item["tin_nhan"]
    impr = item.get("impressions", 0)
    reach = item.get("reach", 0)
    clicks = item.get("clicks", 0)
    video_3s = item.get("video_3s", 0)
    thruplay = item.get("thruplay", 0)

    ctr = item.get("ctr") if "ctr" in item else (round((clicks / impr) * 100, 2) if impr > 0 else 0)
    cpm = item.get("cpm") if "cpm" in item else (int((tien / impr) * 1000) if impr > 0 else 0)
    freq = item.get("frequency") if "frequency" in item else (round(impr / reach, 2) if reach > 0 else 1.0)
    cr_mess = item.get("cr_click_to_mess") if "cr_click_to_mess" in item else (round((mess / clicks) * 100, 1) if clicks > 0 else 0)
    hook_rate = item.get("hook_rate") if "hook_rate" in item else (round((video_3s / impr) * 100, 1) if impr > 0 and video_3s > 0 else 0)
    hold_rate = item.get("hold_rate") if "hold_rate" in item else (round((thruplay / video_3s) * 100, 1) if video_3s > 0 and thruplay > 0 else 0)
    return ctr, cpm, freq, cr_mess, hook_rate, hold_rate


def rà_soat_chi_tieu_bm(che_do="this_month", since_date=None, until_date=None, nhan_hien_thi=""):
    global BO_NHO_BM, BO_NHO_AUDIT
    if not BO_NHO_BM:
        BO_NHO_BM = quet_danh_sach_tai_khoan()

    BO_NHO_AUDIT.clear()
    tong_chi_bm, tong_mess_bm, tong_cmt_bm = 0, 0, 0
    ds_ket_qua = []

    for tk_idx, tk_info in BO_NHO_BM.items():
        du_lieu_tk = tai_du_lieu_5_tang(tk_info["id"], khoang_tg=che_do, since_date=since_date, until_date=until_date)
        spend = du_lieu_tk["tong_tien_tk"]
        mess = du_lieu_tk["tong_mess_tk"]
        cmt = sum(c["binh_luan"] for c in du_lieu_tk["camps_list"])

        tong_chi_bm += spend
        tong_mess_bm += mess
        tong_cmt_bm += cmt

        if spend > 0:
            BO_NHO_AUDIT[tk_idx] = {
                "ten_tk": tk_info["ten"],
                "nhan_hien_thi": nhan_hien_thi,
                "data": du_lieu_tk,
            }

        ds_ket_qua.append({
            "tk_idx": tk_idx, "ten": tk_info["ten"], "icon": tk_info["icon"],
            "spend": spend, "mess": mess, "cmt": cmt, "cum_list": du_lieu_tk["cum_list"],
        })

    ds_ket_qua.sort(key=lambda x: x["spend"], reverse=True)
    tien_thue = int(tong_chi_bm * (THUE_VAT_FB / 100.0))
    tong_sau_thue = tong_chi_bm + tien_thue
    gia_tb_bm = int(tong_chi_bm / tong_mess_bm) if tong_mess_bm > 0 else 0

    lines = [
        f"💰 RÀ SOÁT NGÂN SÁCH ({nhan_hien_thi})",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🔥 Chi phí QC: {tong_chi_bm:,}đ",
        f"🧾 Thuế VAT ({THUE_VAT_FB}%): +{tien_thue:,}đ",
        f"💰 TỔNG CHI PHÍ (QC + Thuế): {tong_sau_thue:,}đ",
        f"💬 Kết quả: {tong_mess_bm:,} mess (TB: {gia_tb_bm:,}đ/m) | {tong_cmt_bm:,} cmt",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    nut_xem_nhom = []
    hang_nut_tk = []
    for idx, item in enumerate(ds_ket_qua, 1):
        if item["spend"] > 0:
            gia_m = int(item["spend"] / item["mess"]) if item["mess"] > 0 else 0
            thue_tk = int(item["spend"] * (THUE_VAT_FB / 100.0))
            tong_cp_tk = item["spend"] + thue_tk
            lines.append(
                f"{idx}. {item['icon']} {item['ten']}\n"
                f"   • QC: {item['spend']:,}đ + Thuế: {thue_tk:,}đ ➔ Tổng chi phí: {tong_cp_tk:,}đ\n"
                f"   • KQ: {item['mess']} mess ({dinh_dang_tien_gon(gia_m)}/m) | {item['cmt']} cmt"
            )
            for c_gr in item["cum_list"]:
                g_cum = int(c_gr["chi_tieu"] / c_gr["tin_nhan"]) if c_gr["tin_nhan"] > 0 else 0
                lines.append(
                    f"   🔹 Cụm [{c_gr['ten_cum']}] ({c_gr['so_camp']}c): {dinh_dang_tien_gon(c_gr['chi_tieu'])} ➔ {c_gr['tin_nhan']}m ({dinh_dang_tien_gon(g_cum)})"
                )

            hang_nut_tk.append({
                "text": f"📂 Nhóm: {rut_gon_ten_tk(item['ten'])}",
                "callback_data": f"AUDIT_TK|{item['tk_idx']}",
            })
            if len(hang_nut_tk) == 2:
                nut_xem_nhom.append(hang_nut_tk)
                hang_nut_tk = []
        else:
            lines.append(f"{idx}. {item['icon']} {item['ten']}: 0đ")

    if hang_nut_tk:
        nut_xem_nhom.append(hang_nut_tk)

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    nut_xem_nhom.append([
        {"text": f"📊 Đẩy Kỳ Này Lên Sheet ({nhan_hien_thi})", "callback_data": f"SYNC_SHEET|{che_do}"},
    ])
    nut_xem_nhom.append([
        {"text": "📥 Điền Cả Tháng Vào Sheet (1 -> Nay)", "callback_data": "SYNC_SHEET|this_month"},
    ])
    nut_xem_nhom.append([
        {"text": "📅 Mở Bảng Lịch", "callback_data": "CAL_OPEN|AUDIT"},
        {"text": "💰 Đổi mốc Rà soát", "callback_data": "MENU_AUDIT"},
    ])
    return "\n".join(lines), nut_xem_nhom


def tao_bang_chi_tiet_nhom_audit(tk_idx):
    if tk_idx not in BO_NHO_AUDIT:
        return "⚠️ Dữ liệu đã làm mới, vui lòng chọn lại mốc rà soát.", [[{"text": "⬅️ Quay lại", "callback_data": "MENU_AUDIT"}]]

    info = BO_NHO_AUDIT[tk_idx]
    ten_tk, nhan_tg, du_lieu = info["ten_tk"], info["nhan_hien_thi"], info["data"]
    tong_tien_tk = du_lieu["tong_tien_tk"]
    thue_tk = int(tong_tien_tk * (THUE_VAT_FB / 100.0))

    lines = [
        f"📂 CHI TIẾT NHÓM (ADSET) - {ten_tk}",
        f"📅 Kỳ: {nhan_tg}",
        f"💰 QC: {tong_tien_tk:,}đ + Thuế ({THUE_VAT_FB}%): {thue_tk:,}đ ➔ Tổng chi phí: {tong_tien_tk + thue_tk:,}đ",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    for c_idx, camp in enumerate(du_lieu["camps_list"], 1):
        lines.append(f"📌 {c_idx}. {camp['ten']} ({dinh_dang_tien_gon(camp['chi_tieu'])} • {camp['tin_nhan']}m)")
        for g_idx, grp in enumerate(camp["groups_list"], 1):
            gia_g = int(grp["chi_tieu"] / grp["tin_nhan"]) if grp["tin_nhan"] > 0 else 0
            ctr, cpm, freq, cr_mess, hook_r, hold_r = tinh_chi_so_phu(grp)
            icon_dg = "🟢" if (grp["tin_nhan"] > 0 and gia_g <= KPI_MESS) else ("🔴" if grp["tin_nhan"] == 0 else "🟡")
            video_str = f" | 🎬H:{hook_r}%-Hold:{hold_r}%" if hook_r > 0 else ""
            lines.append(
                f"   ↳ {icon_dg} {grp['ten']}: {grp['chi_tieu']:,}đ ➔ {grp['tin_nhan']}m ({dinh_dang_tien_gon(gia_g)})\n"
                f"      [CPM:{int(cpm/1000)}k | CTR:{ctr}% | CR:{cr_mess}%{video_str}]"
            )

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    nut_bam = [
        [
            {"text": "✨ Gemini Bắt Bệnh", "callback_data": f"AI_AUDIT|{tk_idx}|gemini"},
            {"text": "🤖 ChatGPT Bắt Bệnh", "callback_data": f"AI_AUDIT|{tk_idx}|chatgpt"},
        ],
        [
            {"text": "⬅️ Menu Rà Soát", "callback_data": "MENU_AUDIT"},
            {"text": "💳 DS Tài Khoản", "callback_data": "MENU_ACCOUNTS"},
        ],
    ]
    return "\n".join(lines), nut_bam


def tao_bang_so_sanh_text(tieu_de, ds_items, tong_tien_cha, che_do_gon=True):
    ds_sap_xep = sorted(ds_items, key=lambda x: (x["tin_nhan"], x["chi_tieu"]), reverse=True)
    lines = [f"📊 {tieu_de}", "━━━━━━━━━━━━━━━━━━━━"]
    for idx, item in enumerate(ds_sap_xep, 1):
        tien, mess = item["chi_tieu"], item["tin_nhan"]
        gia = int(tien / mess) if mess > 0 else 0
        ctr, cpm, freq, cr_mess, hook_r, hold_r = tinh_chi_so_phu(item)
        icon_dg = "🔴" if mess == 0 else ("🟢" if gia <= KPI_MESS else "🟡")
        kq_str = "0 mess (LỖ)" if mess == 0 else f"{mess} mess ({dinh_dang_tien_gon(gia)}/m)"
        vid_short = f" | 🎬H:{hook_r}%-Hold:{hold_r}%" if hook_r > 0 else ""
        lines.append(
            f"{idx}. {icon_dg} {item['ten']}\n"
            f"   💵 {tien:,}đ ➔ 💬 {kq_str}\n"
            f"   📈 CTR:{ctr}% | CR:{cr_mess}% | CPM:{int(cpm/1000)}k{vid_short}"
        )
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def tao_bang_gom_cum_text(ten_tk, cum_list, tong_tien_tk, chi_tiet_cho_ai=False):
    lines = [f"📦 TỔNG HỢP THEO CỤM ({ten_tk})", "━━━━━━━━━━━━━━━━━━━━"]
    for c_group in cum_list:
        ten_cum = c_group["ten_cum"]
        tien, mess = c_group["chi_tieu"], c_group["tin_nhan"]
        gia_tb = int(tien / mess) if mess > 0 else 0
        lines.append(f"🔷 CỤM [{ten_cum}] ({c_group['so_camp']} camp): {tien:,}đ ➔ {mess} mess ({dinh_dang_tien_gon(gia_tb)}/m)")
        for sub in sorted(c_group["ds_camps"], key=lambda x: x["chi_tieu"], reverse=True):
            sub_gia = int(sub["chi_tieu"] / sub["tin_nhan"]) if sub["tin_nhan"] > 0 else 0
            icon_dg = "🟢" if (sub["tin_nhan"] > 0 and sub_gia <= KPI_MESS) else ("🔴" if sub["tin_nhan"] == 0 else "🟡")
            lines.append(f"   {icon_dg} {sub['ten']}: {dinh_dang_tien_gon(sub['chi_tieu'])} ➔ {sub['tin_nhan']}m ({dinh_dang_tien_gon(sub_gia)})")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def tim_model_gemini():
    try:
        res = requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_KEY}", timeout=10).json()
        ds = [
            m.get("name", "")
            for m in res.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", []) and "gemini" in m.get("name", "")
        ]
        if ds:
            return ds
    except Exception:
        pass
    return ["models/gemini-2.5-flash-lite", "models/gemini-2.0-flash"]


def goi_gemini_api(prompt_text):
    if not GEMINI_KEY:
        return None
    payload = {"contents": [{"parts": [{"text": prompt_text}]}], "generationConfig": {"temperature": 0.2}}
    for m in tim_model_gemini():
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/{m}:generateContent?key={GEMINI_KEY}",
                json=payload,
                timeout=20,
            ).json()
            if "candidates" in r:
                return f"✨ [Phân tích bởi Gemini]\n\n{r['candidates'][0]['content']['parts'][0]['text']}"
        except Exception:
            continue
    return None


def goi_openai_gpt(prompt_text):
    if not OPENAI_KEY:
        return None
    try:
        res = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "Bạn là Giám đốc Tối ưu Quảng cáo Facebook (Senior Media Buyer)."},
                    {"role": "user", "content": prompt_text},
                ],
                "temperature": 0.2,
            },
            timeout=25,
        ).json()
        if "choices" in res and len(res["choices"]) > 0:
            return f"🤖 [Phân tích bởi ChatGPT]\n\n{res['choices'][0]['message']['content']}"
    except Exception:
        pass
    return None


def gemini_danh_gia_chuyen_sau(tieu_de, du_lieu_text, chon_ai=None):
    prompt = (
        f"Bạn là Senior Media Buyer. Đánh giá ngắn gọn dữ liệu [{tieu_de}] (KPI: {KPI_MESS:,}đ/mess):\n"
        f"{du_lieu_text}\n\n"
        f"Trình bày đúng 3 mục:\n"
        f"🟢 1. VÌ SAO TỐT (MỤC HIỆU QUẢ)\n"
        f"🔴 2. VÌ SAO CHƯA TỐT (Chỉ rõ lỗi tại 3s đầu Video, Giữ chân Video, Hình ảnh, Tệp hay Kịch bản chat)\n"
        f"💡 3. ĐỀ XUẤT HÀNH ĐỘNG NGAY (Tắt/Tăng vốn mục nào).\n"
        f"Không dùng dấu sao (*) hay dấu thăng (#)."
    )
    if (chon_ai or AI_UU_TIEN) == "chatgpt":
        return goi_openai_gpt(prompt) or goi_gemini_api(prompt) or "⚠️ Không kết nối được AI."
    return goi_gemini_api(prompt) or goi_openai_gpt(prompt) or "⚠️ Không kết nối được AI."


# ==============================================================================
# 4. GIAO DIỆN 4 LUỒNG & ĐIỀU HƯỚNG TELEGRAM
# ==============================================================================
def gui_ban_phim_co_dinh(chat_id, loi_nhan="⌨️ Đã bật Thanh Điều Hướng 4 Luồng dưới đáy màn hình!"):
    requests.post(
        f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": loi_nhan, "reply_markup": BAN_PHIM_CO_DINH},
    )


def gui_hoac_sua_menu(chat_id, van_ban, nut_bam=None, msg_id=None):
    if msg_id and len(van_ban) <= 3800:
        payload = {"chat_id": chat_id, "message_id": msg_id, "text": van_ban}
        if nut_bam:
            payload["reply_markup"] = {"inline_keyboard": nut_bam}
        r = requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/editMessageText", json=payload).json()
        if r.get("ok"):
            return

    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    cac_dong = van_ban.split("\n")
    doan, cac_phan = "", []
    for dong in cac_dong:
        if len(doan) + len(dong) + 1 > 3800:
            cac_phan.append(doan)
            doan = dong + "\n"
        else:
            doan += dong + "\n"
    if doan.strip():
        cac_phan.append(doan)

    for idx, p in enumerate(cac_phan):
        payload = {"chat_id": chat_id, "text": p}
        if idx == len(cac_phan) - 1:
            payload["reply_markup"] = {"inline_keyboard": nut_bam} if nut_bam else BAN_PHIM_CO_DINH
        requests.post(url, json=payload)


def tao_khung_thoi_gian_chuan(prefix_cmd, tg_hien_tai=None, target_lich="AUDIT"):
    hang_1 = [
        {"text": f"✅{n}" if tg_hien_tai == m else n, "callback_data": f"{prefix_cmd}|{m}"}
        for m, n in [("today", "⚡H.Nay"), ("yesterday", "📅H.Qua"), ("last_3d", "3 Ngày"), ("last_7d", "7 Ngày")]
    ]
    hang_2 = [
        {"text": f"✅{n}" if tg_hien_tai == m else n, "callback_data": f"{prefix_cmd}|{m}"}
        for m, n in [("this_month", "📆 Tháng này"), ("last_month", "⏪ Tháng trước"), ("last_30d", "30 Ngày")]
    ]
    nhan_lich = f"✅ 📅 {KY_TUY_CHINH[2]}" if (tg_hien_tai == "custom" and KY_TUY_CHINH) else "📅 Mở Bảng Lịch Chọn Ngày"
    return [hang_1, hang_2, [{"text": nhan_lich, "callback_data": f"CAL_OPEN|{target_lich}"}]]


def hien_luong_1_ds_tai_khoan(cid, msg_id=None, tg_mac_dinh="today"):
    global BO_NHO_BM
    if not BO_NHO_BM:
        BO_NHO_BM = quet_danh_sach_tai_khoan()
    nut, hang = [], []
    for idx, (tk_idx, tk_info) in enumerate(BO_NHO_BM.items(), 1):
        hang.append({"text": f"{tk_info['icon']} {idx}. {rut_gon_ten_tk(tk_info['ten'])}", "callback_data": f"TK|{tk_idx}|{tg_mac_dinh}"})
        if len(hang) == 2:
            nut.append(hang)
            hang = []
    if hang:
        nut.append(hang)
    ds = "\n".join([f"  {idx}. {tk['icon']} {tk['ten']}" for idx, tk in enumerate(BO_NHO_BM.values(), 1)])
    van_ban = (
        f"💳 DANH SÁCH TÀI KHOẢN QUẢNG CÁO\n"
        f"🕒 {lay_gio_viet_nam().strftime('%H:%M - %d/%m/%Y')} | 🧾 VAT: {THUE_VAT_FB}%\n"
        f"━━━━━━━━━━━━━━━━━━━━\n{ds}\n━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 Chạm vào Tài khoản để xem số liệu:"
    )
    gui_hoac_sua_menu(cid, van_ban, nut, msg_id)


def hien_luong_2_bao_cao_tong(cid, msg_id=None):
    van_ban = (
        "📊 BÁO CÁO TỔNG & AI BẮT BỆNH (4 TÀI KHOẢN)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Chọn khung thời gian để xuất báo cáo tổng hợp và đồng bộ vào Google Sheet:"
    )
    nut = tao_khung_thoi_gian_chuan("QuickReport", None, "REPORT")
    nut.append([{"text": "📥 Điền Cả Tháng Này Vào Sheet (1 -> Nay)", "callback_data": "SYNC_SHEET|this_month"}])
    gui_hoac_sua_menu(cid, van_ban, nut, msg_id)


def hien_luong_3_ra_soat_ngan_sach(cid, msg_id=None):
    van_ban = (
        "💰 RÀ SOÁT NGÂN SÁCH (TÀI KHOẢN / CỤM / NHÓM)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Chọn khung thời gian hoặc mở Bảng Lịch để kiểm toán: Tổng chi phí = Chi phí QC + Thuế VAT ({THUE_VAT_FB}%):"
    )
    nut = tao_khung_thoi_gian_chuan("AUDIT", None, "AUDIT")
    nut.append([{"text": "📥 Điền Cả Tháng Này Vào Sheet (1 -> Nay)", "callback_data": "SYNC_SHEET|this_month"}])
    gui_hoac_sua_menu(cid, van_ban, nut, msg_id)


def hien_luong_4_cong_no_va_cai_dat(cid, msg_id=None):
    global BO_NHO_BM
    BO_NHO_BM = quet_danh_sach_tai_khoan()
    tong_no = sum(acc["balance"] for acc in BO_NHO_BM.values())
    thue = int(tong_no * (THUE_VAT_FB / 100.0))
    lines = [
        "🏦 CÔNG NỢ, THẺ & ĐỒNG BỘ GOOGLE SHEET",
        f"🔥 Dư nợ QC: {tong_no:,}đ + VAT ({THUE_VAT_FB}%): {thue:,}đ",
        f"💰 TỔNG CẦN THANH TOÁN: {tong_no + thue:,}đ",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    for idx, acc in enumerate(BO_NHO_BM.values(), 1):
        lines.append(f"{idx}. {acc['icon']} {acc['ten']}: Nợ {acc['balance']:,}đ | Tổng tiêu: {acc['amount_spent']:,}đ")

    nut = [
        [{"text": "📥 Điền Cả Tháng Này Vào Sheet (1 -> Nay)", "callback_data": "SYNC_SHEET|this_month"}],
        [
            {"text": "📊 Đẩy Hôm Qua Lên Sheet", "callback_data": "SYNC_SHEET|yesterday"},
            {"text": "📊 Đẩy Hôm Nay Lên Sheet", "callback_data": "SYNC_SHEET|today"},
        ],
        [
            {"text": "✅ Ưu tiên Gemini" if AI_UU_TIEN == "gemini" else "✨ Ưu tiên Gemini", "callback_data": "SET_AI|gemini"},
            {"text": "✅ Ưu tiên ChatGPT" if AI_UU_TIEN == "chatgpt" else "🤖 Ưu tiên ChatGPT", "callback_data": "SET_AI|chatgpt"},
        ],
        [{"text": "🔄 Làm mới dữ liệu", "callback_data": "REFRESH_ALL"}],
    ]
    gui_hoac_sua_menu(cid, "\n".join(lines), nut, msg_id)


def hien_menu_chon_luong_cho_ngay_tuy_chinh(cid, msg_id=None):
    nhan_d = KY_TUY_CHINH[2] if KY_TUY_CHINH else "Ngày tùy chỉnh"
    nut = [
        [{"text": f"💰 1. Rà Soát Ngân Sách ({nhan_d})", "callback_data": "AUDIT|custom"}],
        [{"text": f"📥 2. Điền Kỳ [{nhan_d}] Vào Google Sheet", "callback_data": "SYNC_SHEET|custom"}],
        [{"text": f"📊 3. Báo Cáo Tổng + AI ({nhan_d})", "callback_data": "QuickReport|custom"}],
    ]
    gui_hoac_sua_menu(cid, f"📅 ĐÃ CHỌN KỲ: {nhan_d}\n━━━━━━━━━━━━━━━━━━━━\nChọn thao tác bạn muốn thực hiện:", nut, msg_id)


def hien_man_hinh_tai_khoan(cid, tk_idx, tg="today", msg_id=None, can_tai_lai=True):
    global BO_NHO_BM
    if not BO_NHO_BM:
        BO_NHO_BM = quet_danh_sach_tai_khoan()
    tk_info = BO_NHO_BM[tk_idx]
    du_lieu = tai_du_lieu_5_tang(tk_info["id"], tg) if (can_tai_lai or tk_idx not in BO_NHO_TK) else BO_NHO_TK[tk_idx]["data"]
    BO_NHO_TK[tk_idx] = {"tk_idx": tk_idx, "ten_tk": tk_info["ten"], "tg": tg, "data": du_lieu}

    tong_t = du_lieu["tong_tien_tk"]
    thue = int(tong_t * (THUE_VAT_FB / 100.0))
    tom_tat = (
        f"💳 {tk_info['ten']} ({lay_nhan_ky_du_lieu(tg)})\n"
        f"🔥 Chi phí QC: {tong_t:,}đ | 🧾 Thuế ({THUE_VAT_FB}%): +{thue:,}đ\n"
        f"💰 TỔNG CHI PHÍ: {tong_t + thue:,}đ | 💬 {du_lieu['tong_mess_tk']} mess\n\n"
        f"{tao_bang_gom_cum_text(tk_info['ten'], du_lieu['cum_list'], tong_t)}"
    )
    nut = tao_khung_thoi_gian_chuan(f"TK|{tk_idx}", tg, f"TK_{tk_idx}")
    if du_lieu["so_camp_co_tieu_tien"] > 0:
        hang_c = []
        for c_gr in du_lieu["cum_list"]:
            hang_c.append({
                "text": f"📦 {c_gr['ten_cum']} ({dinh_dang_tien_gon(c_gr['chi_tieu'])}•{c_gr['tin_nhan']}m)",
                "callback_data": f"CUM|{tk_idx}|{c_gr['cum_idx']}",
            })
            if len(hang_c) == 2:
                nut.append(hang_c)
                hang_c = []
        if hang_c:
            nut.append(hang_c)
    nut.append([{"text": "💳 Đổi Tài Khoản", "callback_data": "MENU_ACCOUNTS"}])
    gui_hoac_sua_menu(cid, tom_tat, nut, msg_id)


# ==============================================================================
# 5. BÁO CÁO ĐỊNH KỲ 8H SÁNG (TỰ ĐỘNG BÁO TELEGRAM + CẬP NHẬT GOOGLE SHEET)
# ==============================================================================
def chay_bao_cao_tu_dong(khoang_tg="yesterday", la_tu_dong_dinh_ky=False, since_date=None, until_date=None, nhan_tuy_chinh=None):
    global BO_NHO_BM
    BO_NHO_BM = quet_danh_sach_tai_khoan()

    if not (since_date and until_date):
        since_date, until_date = xac_dinh_khoang_ngay_tu_preset(khoang_tg)

    ten_ky = nhan_tuy_chinh or lay_nhan_ky_du_lieu(khoang_tg)
    tieu_de_buoi = f"☀️ BÁO CÁO 8H SÁNG & ĐỒNG BỘ SHEET ({ten_ky})" if la_tu_dong_dinh_ky else f"📊 BÁO CÁO TỔNG ({ten_ky})"

    co_tk_tieu_tien = False
    for tk_idx, tk_info in BO_NHO_BM.items():
        du_lieu = tai_du_lieu_5_tang(tk_info["id"], khoang_tg, since_date, until_date)
        if du_lieu["so_camp_co_tieu_tien"] > 0:
            co_tk_tieu_tien = True
            tong_qc = du_lieu["tong_tien_tk"]
            thue_tk = int(tong_qc * (THUE_VAT_FB / 100.0))
            tong_cp = tong_qc + thue_tk
            gia_tb = int(tong_qc / du_lieu["tong_mess_tk"]) if du_lieu["tong_mess_tk"] > 0 else 0

            bang_gon = tao_bang_gom_cum_text(tk_info["ten"], du_lieu["cum_list"], tong_qc)
            nhan_xet = gemini_danh_gia_chuyen_sau(f"{tk_info['ten']} ({ten_ky})", bang_gon)
            mo_dau = (
                f"{tieu_de_buoi}\n"
                f"💳 TK: {tk_info['ten']}\n"
                f"🔥 Chi phí QC: {tong_qc:,}đ | 🧾 Thuế ({THUE_VAT_FB}%): +{thue_tk:,}đ\n"
                f"💰 TỔNG CHI PHÍ: {tong_cp:,}đ | 💬 {du_lieu['tong_mess_tk']} mess ({gia_tb:,}đ/m)\n\n"
            )
            gui_hoac_sua_menu(CHAT_ID, mo_dau + bang_gon + "\n\n" + nhan_xet)

    if not co_tk_tieu_tien:
        gui_hoac_sua_menu(CHAT_ID, f"{tieu_de_buoi}\nℹ️ Chưa có tài khoản nào phát sinh chi tiêu trong kỳ [{ten_ky}].")

    # Đẩy dữ liệu vào bảng 6 cột trên Google Sheet
    _, msg_sheet = dong_bo_khoang_ngay_len_sheet(since_date, until_date)
    gui_hoac_sua_menu(CHAT_ID, msg_sheet)


def da_bao_cao_xuyen_phien(ma_ngay_gio):
    if ma_ngay_gio in DA_BAO_CAO_TRONG_PHIEN:
        return True
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELE_TOKEN}/getMyShortDescription", timeout=5).json()
        if f"[DONE:{ma_ngay_gio}]" in r.get("result", {}).get("short_description", ""):
            DA_BAO_CAO_TRONG_PHIEN.add(ma_ngay_gio)
            return True
    except Exception:
        pass
    return False


def danh_dau_da_bao_cao_xuyen_phien(ma_ngay_gio):
    DA_BAO_CAO_TRONG_PHIEN.add(ma_ngay_gio)
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELE_TOKEN}/setMyShortDescription",
            json={"short_description": f"Trợ lý Ads 24/7 [DONE:{ma_ngay_gio}]"},
            timeout=5,
        )
    except Exception:
        pass


def kiem_tra_den_gio_bao_cao_tu_dong():
    now_vn = lay_gio_viet_nam()
    ma_ngay_gio = now_vn.strftime("%Y-%m-%d_%H")
    # Đúng 8h sáng mỗi ngày: Tự báo cáo số liệu Hôm qua + Tự cập nhật vào Google Sheet
    if now_vn.hour == GIO_BAO_CAO_SANG and now_vn.minute <= 20:
        if not da_bao_cao_xuyen_phien(ma_ngay_gio):
            danh_dau_da_bao_cao_xuyen_phien(ma_ngay_gio)
            chay_bao_cao_tu_dong("yesterday", la_tu_dong_dinh_ky=True)


def xu_ly_ket_qua_chon_lich(cid, msg_id, target):
    since_d, until_d, nhan_d = KY_TUY_CHINH
    if target == "AUDIT":
        gui_hoac_sua_menu(cid, f"⏳ Đang rà soát ngân sách [{nhan_d}]...", None, msg_id)
        bc, nut = rà_soat_chi_tieu_bm("custom", since_d, until_d, nhan_d)
        gui_hoac_sua_menu(cid, bc, nut, msg_id)
    elif target == "REPORT":
        gui_hoac_sua_menu(cid, f"⏳ Đang xuất Báo Cáo Tổng & đồng bộ Sheet [{nhan_d}]...", None, msg_id)
        chay_bao_cao_tu_dong("custom", False, since_d, until_d, nhan_d)
    elif target.startswith("TK_"):
        tk_idx = target.split("_")[1]
        hien_man_hinh_tai_khoan(cid, tk_idx, "custom", msg_id)
    else:
        hien_menu_chon_luong_cho_ngay_tuy_chinh(cid, msg_id)


# ==============================================================================
# 6. VÒNG LẶP TRỰC CHIẾN 24/7
# ==============================================================================
def chay_vong_lap_truc_chien_247(offset_ban_dau=0):
    global AI_UU_TIEN, KY_TUY_CHINH
    offset = offset_ban_dau
    thoi_diem_bat_dau = time.time()
    print("🟢 Bot đang trực chiến 24/7 (Bản Full chuẩn 6 cột Google Sheet)...")

    while time.time() - thoi_diem_bat_dau < THOI_GIAN_DUY_TRI_PHIEN:
        try:
            kiem_tra_den_gio_bao_cao_tu_dong()
            res = requests.get(
                f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates?offset={offset}&timeout=20",
                timeout=25,
            ).json()

            for update in res.get("result", []):
                offset = update["update_id"] + 1

                if "message" in update and "text" in update["message"]:
                    cid = update["message"]["chat"]["id"]
                    if str(cid) != str(CHAT_ID):
                        continue

                    text_raw = update["message"]["text"].strip()
                    text_in = text_raw.lower()

                    kq_ngay = phan_tich_ngay_tuy_chinh(text_raw)
                    if kq_ngay:
                        KY_TUY_CHINH = kq_ngay
                        hien_menu_chon_luong_cho_ngay_tuy_chinh(cid)
                        continue

                    if text_in in ["/menu", "💳 danh sách tài khoản"]:
                        hien_luong_1_ds_tai_khoan(cid)
                    elif text_in in ["/baocao", "📊 báo cáo tổng (4 tk)"]:
                        hien_luong_2_bao_cao_tong(cid)
                    elif text_in in ["/rasoat", "💰 rà soát ngân sách"]:
                        hien_luong_3_ra_soat_ngan_sach(cid)
                    elif text_in in ["/congno", "🏦 công nợ & cài đặt"]:
                        hien_luong_4_cong_no_va_cai_dat(cid)
                    elif text_in in ["/sheet"]:
                        s_d, u_d = xac_dinh_khoang_ngay_tu_preset("this_month")
                        gui_hoac_sua_menu(cid, f"⏳ Đang đồng bộ siêu tốc từ {s_d} đến {u_d} vào Google Sheet...")
                        _, msg_sh = dong_bo_khoang_ngay_len_sheet(s_d, u_d)
                        gui_hoac_sua_menu(cid, msg_sh)
                    elif text_in in ["/lich"]:
                        TRANG_THAI_LICH[cid] = {"start": None}
                        hien_bang_lich(cid, target="CUSTOM_HUB")
                    else:
                        gui_ban_phim_co_dinh(cid)
                        hien_luong_1_ds_tai_khoan(cid)

                elif "callback_query" in update:
                    cb = update["callback_query"]
                    cid = cb["message"]["chat"]["id"]
                    if str(cid) != str(CHAT_ID):
                        continue

                    msg_id = cb["message"]["message_id"]
                    parts = cb["data"].strip().split("|")
                    lenh = parts[0]

                    requests.post(
                        f"https://api.telegram.org/bot{TELE_TOKEN}/answerCallbackQuery",
                        json={"callback_query_id": cb["id"]},
                    )

                    if lenh == "CAL_IGNORE":
                        continue
                    elif lenh == "SET_AI":
                        AI_UU_TIEN = parts[1]
                        hien_luong_4_cong_no_va_cai_dat(cid, msg_id)
                    elif lenh == "REFRESH_ALL":
                        BO_NHO_BM.clear(); BO_NHO_TK.clear(); BO_NHO_AUDIT.clear()
                        hien_luong_1_ds_tai_khoan(cid, msg_id)
                    elif lenh == "CAL_OPEN":
                        TRANG_THAI_LICH[cid] = {"start": None}
                        hien_bang_lich(cid, msg_id, parts[1])
                    elif lenh == "CAL_NAV":
                        hien_bang_lich(cid, msg_id, parts[1], int(parts[2]), int(parts[3]))
                    elif lenh == "CAL_RESET":
                        TRANG_THAI_LICH[cid] = {"start": None}
                        hien_bang_lich(cid, msg_id, parts[1], int(parts[2]), int(parts[3]))
                    elif lenh == "CAL_SINGLE":
                        KY_TUY_CHINH = (parts[2], parts[2], f"Ngày {datetime.strptime(parts[2], '%Y-%m-%d').strftime('%d/%m/%Y')}")
                        TRANG_THAI_LICH[cid] = {"start": None}
                        xu_ly_ket_qua_chon_lich(cid, msg_id, parts[1])
                    elif lenh == "CAL_DAY":
                        st = TRANG_THAI_LICH.setdefault(cid, {})
                        if not st.get("start"):
                            st["start"] = parts[2]
                            dt = datetime.strptime(parts[2], "%Y-%m-%d")
                            hien_bang_lich(cid, msg_id, parts[1], dt.year, dt.month)
                        else:
                            dt1, dt2 = sorted([datetime.strptime(st["start"], "%Y-%m-%d"), datetime.strptime(parts[2], "%Y-%m-%d")])
                            KY_TUY_CHINH = (
                                dt1.strftime("%Y-%m-%d"),
                                dt2.strftime("%Y-%m-%d"),
                                f"{dt1.strftime('%d/%m/%Y')} - {dt2.strftime('%d/%m/%Y')}",
                            )
                            st["start"] = None
                            xu_ly_ket_qua_chon_lich(cid, msg_id, parts[1])

                    elif lenh in ["HOME", "MENU_ACCOUNTS"]:
                        hien_luong_1_ds_tai_khoan(cid, msg_id)
                    elif lenh == "MENU_REPORT":
                        hien_luong_2_bao_cao_tong(cid, msg_id)
                    elif lenh == "MENU_AUDIT":
                        hien_luong_3_ra_soat_ngan_sach(cid, msg_id)
                    elif lenh == "AUDIT":
                        che_do_a = parts[1]
                        ten_ky_a = lay_nhan_ky_du_lieu(che_do_a)
                        gui_hoac_sua_menu(cid, f"⏳ Đang rà soát ngân sách [{ten_ky_a}]...", None, msg_id)
                        if che_do_a == "custom" and KY_TUY_CHINH:
                            bc, nut = rà_soat_chi_tieu_bm("custom", KY_TUY_CHINH[0], KY_TUY_CHINH[1], ten_ky_a)
                        else:
                            bc, nut = rà_soat_chi_tieu_bm(che_do_a, nhan_hien_thi=ten_ky_a)
                        gui_hoac_sua_menu(cid, bc, nut, msg_id)

                    elif lenh == "AUDIT_TK":
                        van_ban_nhom, nut_nhom = tao_bang_chi_tiet_nhom_audit(parts[1])
                        gui_hoac_sua_menu(cid, van_ban_nhom, nut_nhom, msg_id)

                    elif lenh == "AI_AUDIT":
                        tk_idx = parts[1]
                        chon_ai = parts[2] if len(parts) > 2 else None
                        if tk_idx not in BO_NHO_AUDIT:
                            hien_luong_3_ra_soat_ngan_sach(cid, msg_id)
                            continue
                        van_ban_nhom, nut_nhom = tao_bang_chi_tiet_nhom_audit(tk_idx)
                        gui_hoac_sua_menu(cid, van_ban_nhom + "\n\n⏳ AI đang phân tích các Nhóm...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(BO_NHO_AUDIT[tk_idx]["ten_tk"], van_ban_nhom, chon_ai=chon_ai)
                        gui_hoac_sua_menu(cid, van_ban_nhom + "\n\n" + nhan_xet, nut_nhom, msg_id)

                    elif lenh == "SYNC_SHEET":
                        che_do_s = parts[1]
                        s_d, u_d = xac_dinh_khoang_ngay_tu_preset(che_do_s)
                        gui_hoac_sua_menu(cid, f"⏳ Đang đồng bộ siêu tốc ({s_d} ➔ {u_d}) vào Google Sheet...")
                        _, msg_sh = dong_bo_khoang_ngay_len_sheet(s_d, u_d)
                        gui_hoac_sua_menu(cid, msg_sh)

                    elif lenh == "QuickReport":
                        ky_bc = parts[1]
                        gui_hoac_sua_menu(cid, "⏳ Đang xuất Báo Cáo Tổng & đồng bộ Google Sheet...", None, msg_id)
                        chay_bao_cao_tu_dong(ky_bc, la_tu_dong_dinh_ky=False)

                    elif lenh == "TK":
                        hien_man_hinh_tai_khoan(cid, parts[1], parts[2], msg_id)

                    elif lenh == "CUM":
                        tk_idx, cum_idx = parts[1], parts[2]
                        if tk_idx not in BO_NHO_TK:
                            hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id)
                            continue
                        tk_cache = BO_NHO_TK[tk_idx]
                        c_group = tk_cache["data"]["cum_list"][int(cum_idx)]
                        gui_hoac_sua_menu(
                            cid,
                            tao_bang_so_sanh_text(f"CỤM [{c_group['ten_cum']}]", c_group["ds_camps"], c_group["chi_tieu"]),
                            [[{"text": "⬅️ Về Tài khoản", "callback_data": f"TK|{tk_idx}|{tk_cache['tg']}"}]],
                            msg_id,
                        )

        except Exception as e:
            print("⚠️ Lỗi:", e)
            time.sleep(3)


if __name__ == "__main__":
    cai_dat_menu_lenh_telegram()
    res_check = requests.get(f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates?timeout=2").json()
    updates = res_check.get("result", [])
    next_offset = updates[-1]["update_id"] + 1 if updates else 0

    if os.environ.get("EVENT_NAME") == "workflow_dispatch":
        gui_ban_phim_co_dinh(CHAT_ID)
        hien_luong_1_ds_tai_khoan(CHAT_ID)

    chay_vong_lap_truc_chien_247(next_offset)
