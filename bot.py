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
# 0. CÀI ĐẶT LỆNH & TIỆN ÍCH ĐỊNH DẠNG
# ==============================================================================
def cai_dat_menu_lenh_telegram():
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/setMyCommands"
    commands = [
        {"command": "menu", "description": "💳 Mở Danh sách Tài khoản"},
        {"command": "baocao", "description": "📊 Mở Báo cáo Tổng (4 TK)"},
        {"command": "rasoat", "description": "💰 Mở Rà soát Ngân sách"},
        {"command": "sheet", "description": "📥 Điền Cả Tháng vào Google Sheet"},
        {"command": "congno", "description": "🏦 Kiểm tra Công nợ & Cài đặt"},
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
                "ten_cum": ten_cum, "so_camp": 0, "chi_tieu": 0,
                "tin_nhan": 0, "binh_luan": 0, "clicks": 0,
                "impressions": 0, "reach": 0, "video_3s": 0,
                "thruplay": 0, "ds_camps": [],
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
# 1. ĐỒNG BỘ GOOGLE SHEET SIÊU TỐC
# ==============================================================================
def xac_dinh_khoang_ngay_tu_preset(che_do):
    now_vn = lay_gio_viet_nam()
    hom_nay = now_vn.strftime("%Y-%m-%d")
    hom_qua = (now_vn - timedelta(days=1)).strftime("%Y-%m-%d")

    if che_do == "today": return hom_nay, hom_nay
    if che_do == "yesterday": return hom_qua, hom_qua
    if che_do == "last_3d": return (now_vn - timedelta(days=3)).strftime("%Y-%m-%d"), hom_qua
    if che_do == "last_7d": return (now_vn - timedelta(days=7)).strftime("%Y-%m-%d"), hom_qua
    if che_do == "this_month": return now_vn.replace(day=1).strftime("%Y-%m-%d"), hom_nay
    if che_do == "last_month":
        dau_thang_nay = now_vn.replace(day=1)
        cuoi_thang_truoc = dau_thang_nay - timedelta(days=1)
        return cuoi_thang_truoc.replace(day=1).strftime("%Y-%m-%d"), cuoi_thang_truoc.strftime("%Y-%m-%d")
    if che_do == "last_30d": return (now_vn - timedelta(days=30)).strftime("%Y-%m-%d"), hom_qua
    if che_do == "custom" and KY_TUY_CHINH: return KY_TUY_CHINH[0], KY_TUY_CHINH[1]
    return hom_qua, hom_qua


def dong_bo_khoang_ngay_len_sheet(since_ymd, until_ymd):
    global BO_NHO_BM
    if not SHEET_WEBHOOK_URL: return False, "⚠️ Chưa có SHEET_WEBHOOK_URL trong GitHub Secrets."
    if not BO_NHO_BM: BO_NHO_BM = quet_danh_sach_tai_khoan()

    tong_theo_ngay, cum_theo_ngay = {}, {}
    for tk_idx, tk_info in BO_NHO_BM.items():
        url_ins = f"https://graph.facebook.com/v21.0/{tk_info['id']}/insights"
        params = {
            "level": "campaign", "time_increment": 1,
            "time_range": json.dumps({"since": since_ymd, "until": until_ymd}),
            "fields": "campaign_name,spend,actions,date_start", "limit": 1000,
            "access_token": FB_TOKEN,
        }
        try:
            r_ins = requests.get(url_ins, params=params, timeout=20).json()
        except Exception:
            continue

        for row in r_ins.get("data", []):
            spend = int(float(row.get("spend", 0)))
            if spend <= 0: continue
            ngay = row.get("date_start")
            c_name = row.get("campaign_name", "Khác")
            ten_cum = tach_ten_cum(c_name)
            mess, cmt, _, _, _ = trich_xuat_ket_qua(row.get("actions", []))

            if ngay not in tong_theo_ngay: tong_theo_ngay[ngay] = {"spend": 0, "mess": 0, "cmt": 0}
            tong_theo_ngay[ngay]["spend"] += spend
            tong_theo_ngay[ngay]["mess"] += mess
            tong_theo_ngay[ngay]["cmt"] += cmt

            key_cum = (ten_cum, ngay)
            if key_cum not in cum_theo_ngay: cum_theo_ngay[key_cum] = {"spend": 0, "mess": 0, "cmt": 0}
            cum_theo_ngay[key_cum]["spend"] += spend
            cum_theo_ngay[key_cum]["mess"] += mess
            cum_theo_ngay[key_cum]["cmt"] += cmt

    ds_items = []
    for ngay, val in sorted(tong_theo_ngay.items()):
        thue = int(val["spend"] * (THUE_VAT_FB / 100.0))
        ds_items.append({"tab_name": "Tổng", "ngay": ngay, "spend": val["spend"], "tax": thue, "total": val["spend"] + thue, "mess": val["mess"], "cmt": val["cmt"]})

    for (ten_cum, ngay), val in sorted(cum_theo_ngay.items()):
        thue = int(val["spend"] * (THUE_VAT_FB / 100.0))
        ds_items.append({"tab_name": ten_cum, "ngay": ngay, "spend": val["spend"], "tax": thue, "total": val["spend"] + thue, "mess": val["mess"], "cmt": val["cmt"]})

    if not ds_items: return True, f"ℹ️ Không có phát sinh chi tiêu trong kỳ ({since_ymd} ➔ {until_ymd})."

    try:
        r = requests.post(SHEET_WEBHOOK_URL, json={"items": ds_items}, timeout=45, allow_redirects=True)
        so_ngay = len(tong_theo_ngay)
        ds_cum = sorted(list({k[0] for k in cum_theo_ngay.keys()}))
        if r.status_code == 200:
            return True, f"✅ Đã đồng bộ thành công {so_ngay} ngày lên Google Sheet!\n• Các Tab: Tổng, {', '.join(ds_cum)}"
        return False, f"HTTP Error {r.status_code}"
    except Exception as e:
        return False, str(e)


# ==============================================================================
# 2. BẢNG LỊCH & PHÂN TÍCH NGÀY TÙY CHỈNH
# ==============================================================================
def phan_tich_ngay_tuy_chinh(text_in):
    now_vn = lay_gio_viet_nam()
    nam_ht = now_vn.year
    s = re.sub(r"^(/ngay|/rasoat|ngay|ngày)\s*", "", text_in.strip(), flags=re.IGNORECASE).strip()
    m_range = re.match(r"^(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?\s*(?:đến|den|to|\-|\~)\s*(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?$", s)
    if m_range:
        d1, m1, y1, d2, m2, y2 = m_range.groups()
        y1, y2 = (int(y1) if y1 else nam_ht), (int(y2) if y2 else nam_ht)
        if y1 < 100: y1 += 2000
        if y2 < 100: y2 += 2000
        try:
            dt1, dt2 = datetime(y1, int(m1), int(d1)), datetime(y2, int(m2), int(d2))
            if dt1 > dt2: dt1, dt2 = dt2, dt1
            return (dt1.strftime("%Y-%m-%d"), dt2.strftime("%Y-%m-%d"), f"{dt1.strftime('%d/%m/%Y')} - {dt2.strftime('%d/%m/%Y')}")
        except ValueError:
            return None
    m_single = re.match(r"^(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?$", s)
    if m_single:
        d1, m1, y1 = m_single.groups()
        y1 = int(y1) if y1 else nam_ht
        if y1 < 100: y1 += 2000
        try:
            dt1 = datetime(y1, int(m1), int(d1))
            return dt1.strftime("%Y-%m-%d"), dt1.strftime("%Y-%m-%d"), f"Ngày {dt1.strftime('%d/%m/%Y')}"
        except ValueError:
            return None
    return None


def hien_bang_lich(cid, msg_id=None, target="AUDIT", nam=None, thang=None):
    now_vn = lay_gio_viet_nam()
    if not nam or not thang: nam, thang = now_vn.year, now_vn.month
    st = TRANG_THAI_LICH.get(cid, {})
    ngay_bat_dau = st.get("start")
    thang_truoc, nam_truoc = (thang - 1, nam) if thang > 1 else (12, nam - 1)
    thang_sau, nam_sau = (thang + 1, nam) if thang < 12 else (1, nam + 1)

    nut = [
        [{"text": f"⏪ T{thang_truoc:02d}/{nam_truoc}", "callback_data": f"CAL_NAV|{target}|{nam_truoc}|{thang_truoc}"},
         {"text": f"🗓 THÁNG {thang:02d}/{nam}", "callback_data": "CAL_IGNORE"},
         {"text": f"T{thang_sau:02d}/{nam_sau} ⏩", "callback_data": f"CAL_NAV|{target}|{nam_sau}|{thang_sau}"}],
        [{"text": t, "callback_data": "CAL_IGNORE"} for t in ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]],
    ]
    cal = calendar.Calendar(firstweekday=0)
    for tuan in cal.monthdayscalendar(nam, thang):
        hang = []
        for ngay in tuan:
            if ngay == 0: hang.append({"text": "·", "callback_data": "CAL_IGNORE"})
            else:
                ymd = f"{nam:04d}-{thang:02d}-{ngay:02d}"
                nhan = f"✅{ngay}" if ngay_bat_dau == ymd else (f"{ngay}📍" if ymd == now_vn.strftime("%Y-%m-%d") else str(ngay))
                hang.append({"text": nhan, "callback_data": f"CAL_DAY|{target}|{ymd}"})
        nut.append(hang)

    if ngay_bat_dau:
        d_dep = datetime.strptime(ngay_bat_dau, "%Y-%m-%d").strftime("%d/%m/%Y")
        nut.append([{"text": f"🔍 Xem ngay 1 ngày ({d_dep})", "callback_data": f"CAL_SINGLE|{target}|{ngay_bat_dau}"}])
        nut.append([{"text": "🔄 Chọn lại ngày khác", "callback_data": f"CAL_RESET|{target}|{nam}|{thang}"}])
        huong_dan = f"✅ Đã chọn mốc đầu: {d_dep}\n👉 Bấm Xem ngay hoặc chạm tiếp ngày thứ 2."
    else:
        huong_dan = "👉 Chạm vào 1 ngày trên lịch để bắt đầu chọn."

    nut.append([{"text": "⬅️ Quay lại", "callback_data": "MENU_AUDIT"}])
    gui_hoac_sua_menu(cid, f"📅 BẢNG LỊCH CHỌN NGÀY\n━━━━━━━━━━━━━━━━━━━━\n{huong_dan}", nut, msg_id)


# ==============================================================================
# 3. QUÉT DỮ LIỆU FACEBOOK & AI "THỰC CHIẾN - KHÔNG VĂN VỞ"
# ==============================================================================
def trich_xuat_ket_qua(actions_list, video_thruplay_list=None):
    mess, cmt, lead, video_3s, thruplay = 0, 0, 0, 0, 0
    for item in actions_list or []:
        loai = item.get("action_type", "")
        val = int(float(item.get("value", 0)))
        if loai == "onsite_conversion.messaging_conversation_started_7d": mess = val
        elif loai == "comment": cmt = val
        elif loai in ["lead", "purchase", "onsite_conversion.lead_grouped"]: lead += val
        elif loai == "video_view": video_3s = val
    for v_item in video_thruplay_list or []:
        thruplay += int(float(v_item.get("value", 0)))
    return mess, cmt, lead, video_3s, thruplay


def quet_danh_sach_tai_khoan():
    url = "https://graph.facebook.com/v21.0/me/adaccounts"
    params = {"fields": "id,name,account_status,amount_spent,balance,ad_trust_dsl,currency", "limit": 200, "access_token": FB_TOKEN}
    resp = requests.get(url, params=params, timeout=20).json()
    if "error" in resp: raise Exception(resp["error"].get("message"))

    ds_tk = {}
    icon_map = {1: "🟢", 2: "🔴", 3: "🟡", 7: "🟠", 9: "⏳"}
    status_text_map = {1: "Hoạt động", 2: "Vô hiệu hóa", 3: "Lỗi thẻ", 7: "Đang duyệt", 9: "Ân hạn"}
    for idx, acc in enumerate(resp.get("data", [])):
        tk_idx = str(idx)
        st_code = acc.get("account_status", 1)
        he_so = 1 if acc.get("currency", "VND") == "VND" else 100
        ds_tk[tk_idx] = {
            "tk_idx": tk_idx, "id": acc.get("id"), "ten": acc.get("name") or acc.get("id"),
            "icon": icon_map.get(st_code, "⚪"), "status_code": st_code,
            "status_text": status_text_map.get(st_code, f"Mã {st_code}"),
            "balance": int(float(acc.get("balance", 0))) // he_so,
            "amount_spent": int(float(acc.get("amount_spent", 0))) // he_so,
            "threshold": int(float(acc.get("ad_trust_dsl", 0)))
        }
    return ds_tk


def tai_du_lieu_5_tang(ma_tk, khoang_tg="today", since_date=None, until_date=None):
    if khoang_tg == "custom" and KY_TUY_CHINH and not (since_date and until_date):
        since_date, until_date = KY_TUY_CHINH[0], KY_TUY_CHINH[1]

    url_camp = f"https://graph.facebook.com/v21.0/{ma_tk}/campaigns"
    r_camp = requests.get(url_camp, params={"fields": "id,name,effective_status", "limit": 500, "access_token": FB_TOKEN}, timeout=20).json()
    ds_camp_goc = r_camp.get("data", []) if "error" not in r_camp else []
    trang_thai_camp = {c["id"]: ("🟢 Đang bật" if c.get("effective_status") == "ACTIVE" else "⚪ Đã tắt") for c in ds_camp_goc}

    url_ins = f"https://graph.facebook.com/v21.0/{ma_tk}/insights"
    params = {
        "level": "ad",
        "fields": "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,spend,reach,impressions,frequency,cpm,clicks,ctr,cpc,actions,video_thruplay_watched_actions",
        "limit": 500, "access_token": FB_TOKEN
    }
    if since_date and until_date: params["time_range"] = json.dumps({"since": since_date, "until": until_date})
    else: params["date_preset"] = khoang_tg if khoang_tg != "custom" else "today"

    r_ins = requests.get(url_ins, params=params, timeout=25).json()
    camps_raw = {}
    tong_tien_tk, tong_mess_tk = 0, 0

    for row in r_ins.get("data", []):
        spend = int(float(row.get("spend", 0)))
        if spend <= 0: continue
        c_id, c_name = row.get("campaign_id"), row.get("campaign_name", "Không tên")
        mess, cmt, _, v3s, thru = trich_xuat_ket_qua(row.get("actions", []), row.get("video_thruplay_watched_actions", []))
        clicks, impr, reach = int(float(row.get("clicks", 0))), int(float(row.get("impressions", 0))), int(float(row.get("reach", 0)))

        tong_tien_tk += spend
        tong_mess_tk += mess

        if c_id not in camps_raw:
            camps_raw[c_id] = {
                "id": c_id, "ten": c_name, "trang_thai": trang_thai_camp.get(c_id, "🟢 Có tiêu tiền"),
                "chi_tieu": 0, "tin_nhan": 0, "binh_luan": 0, "clicks": 0, "impressions": 0, "reach": 0,
                "video_3s": 0, "thruplay": 0, "groups_raw": {}
            }
        c = camps_raw[c_id]
        c["chi_tieu"] += spend; c["tin_nhan"] += mess; c["binh_luan"] += cmt
        c["clicks"] += clicks; c["impressions"] += impr; c["reach"] += reach
        c["video_3s"] += v3s; c["thruplay"] += thru

        g_id, g_name = row.get("adset_id"), row.get("adset_name", "Không tên")
        if g_id not in c["groups_raw"]:
            c["groups_raw"][g_id] = {"id": g_id, "ten": g_name, "chi_tieu": 0, "tin_nhan": 0, "binh_luan": 0, "ads_raw": {}}
        g = c["groups_raw"][g_id]
        g["chi_tieu"] += spend; g["tin_nhan"] += mess; g["binh_luan"] += cmt

        a_id, a_name = row.get("ad_id"), row.get("ad_name", "Không tên")
        hook_r = round((v3s / impr) * 100, 1) if impr > 0 and v3s > 0 else 0
        hold_r = round((thru / v3s) * 100, 1) if v3s > 0 and thru > 0 else 0
        cr_m = round((mess / clicks) * 100, 1) if clicks > 0 else 0

        g["ads_raw"][a_id] = {
            "id": a_id, "ten": a_name, "chi_tieu": spend, "tin_nhan": mess,
            "gia_mess": int(spend / mess) if mess > 0 else 0, "binh_luan": cmt,
            "clicks": clicks, "impressions": impr, "reach": reach,
            "video_3s": v3s, "thruplay": thru, "hook_rate": hook_r, "hold_rate": hold_r,
            "ctr": round(float(row.get("ctr", 0)), 2), "cpc": int(float(row.get("cpc", 0))),
            "cpm": int(float(row.get("cpm", 0))), "cr": cr_m
        }

    camps_list = sorted(camps_raw.values(), key=lambda x: x["chi_tieu"], reverse=True)
    for c in camps_list:
        g_list = sorted(c["groups_raw"].values(), key=lambda x: x["chi_tieu"], reverse=True)
        for g in g_list:
            g["ads_list"] = sorted(g["ads_raw"].values(), key=lambda x: x["chi_tieu"], reverse=True)
        c["groups_list"] = g_list

    cum_list = gom_cum_chien_dich(camps_list)
    return {
        "tong_so_camp": len(ds_camp_goc), "so_camp_active": sum(1 for c in ds_camp_goc if c.get("effective_status") == "ACTIVE"),
        "so_camp_co_tieu_tien": len(camps_list), "tong_tien_tk": tong_tien_tk, "tong_mess_tk": tong_mess_tk,
        "camps_list": camps_list, "cum_list": cum_list, "thoi_diem_cap_nhat": lay_gio_viet_nam().strftime("%H:%M - %d/%m/%Y")
    }


def goi_gemini_api(prompt):
    if not GEMINI_KEY: return None
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2}}
    for m in ["models/gemini-2.5-flash-lite", "models/gemini-2.0-flash"]:
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/{m}:generateContent?key={GEMINI_KEY}", json=payload, timeout=20).json()
            if "candidates" in r: return r["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            continue
    return None


def goi_openai_gpt(prompt):
    if not OPENAI_KEY: return None
    try:
        res = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "Bạn là Senior Media Buyer thực chiến. Báo cáo ngắn gọn, tập trung hoàn toàn vào số liệu, chỉ rõ Camp nào tốt/lỗ và lệnh hành động ngay, tuyệt đối không văn vở mở bài kết bài."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2
            },
            timeout=25
        ).json()
        if "choices" in res: return res["choices"][0]["message"]["content"]
    except Exception:
        pass
    return None


def ai_bat_benh_thuc_chien(tieu_de, du_lieu_text, chon_ai=None):
    prompt = (
        f"Phân tích dữ liệu thực chiến [{tieu_de}] (KPI giá mess: {KPI_MESS:,}đ/mess):\n"
        f"{du_lieu_text}\n\n"
        f"YÊU CẦU TUYỆT ĐỐI:\n"
        f"- Không văn vở, không có lời chào/lời chúc.\n"
        f"- Trình bày thẳng 3 mục ngắn gọn:\n"
        f"🟢 1. NHÓM HIỆU QUẢ (Kèm tên Camp/Nhóm, Chi tiêu, Số mess, Giá mess, CTR, CR): Nêu lý do để tăng vốn.\n"
        f"🔴 2. NHÓM LỖ / ĐẮT (Kèm số liệu chi tiết, chỉ rõ lỗi tại Hook 3s đầu, CTR hay CR nhắn tin):\n"
        f"⚡ 3. LỆNH HÀNH ĐỘNG NGAY: Ghi rõ [Tăng vốn X%] cho nhóm nào và [Tắt ngay] nhóm nào."
    )
    ket_qua = (goi_openai_gpt(prompt) if (chon_ai or AI_UU_TIEN) == "chatgpt" else (goi_gemini_api(prompt) or goi_openai_gpt(prompt)))
    return f"⚡ **PHÂN TÍCH THỰC CHIẾN (AI)**\n━━━━━━━━━━━━━━━━━━━━\n{ket_qua or '⚠️ Không kết nối được AI.'}"


# ==============================================================================
# 4. GIAO DIỆN "1 TIN NHẮN DUY NHẤT" & ĐIỀU HƯỚNG SIÊU TỐC
# ==============================================================================
def gui_ban_phim_co_dinh(chat_id):
    requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "⌨️ Điều hướng nhanh:", "reply_markup": BAN_PHIM_CO_DINH})


def xu_ly_giao_dien_don_trang(chat_id, msg_id, text_in, nut_bam=None):
    """Cập nhật nội dung trực tiếp trên đúng 1 tin nhắn hiện tại để không làm rác chat"""
    payload = {"chat_id": chat_id, "message_id": msg_id, "text": text_in}
    if nut_bam: payload["reply_markup"] = {"inline_keyboard": nut_bam}
    r = requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/editMessageText", json=payload).json()
    if not r.get("ok"):
        requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text_in, "reply_markup": {"inline_keyboard": nut_bam} if nut_bam else None})


def tao_khung_thoi_gian_chuan(prefix_cmd, tg_hien_tai=None, target_lich="AUDIT"):
    hang_1 = [{"text": f"✅{n}" if tg_hien_tai == m else n, "callback_data": f"{prefix_cmd}|{m}"} for m, n in [("today", "⚡H.Nay"), ("yesterday", "📅H.Qua"), ("last_3d", "3 Ngày"), ("last_7d", "7 Ngày")]]
    hang_2 = [{"text": f"✅{n}" if tg_hien_tai == m else n, "callback_data": f"{prefix_cmd}|{m}"} for m, n in [("this_month", "📆 Tháng này"), ("last_month", "⏪ Tháng trước"), ("last_30d", "30 Ngày")]]
    return [hang_1, hang_2, [{"text": "📅 Mở Bảng Lịch Chọn Ngày", "callback_data": f"CAL_OPEN|{target_lich}"}]]


def hien_luong_1_ds_tai_khoan(cid, msg_id=None, tg_mac_dinh="today"):
    global BO_NHO_BM
    if not BO_NHO_BM: BO_NHO_BM = quet_danh_sach_tai_khoan()
    nut, hang = [], []
    for idx, (tk_idx, tk_info) in enumerate(BO_NHO_BM.items(), 1):
        hang.append({"text": f"{tk_info['icon']} {idx}. {rut_gon_ten_tk(tk_info['ten'])}", "callback_data": f"TK|{tk_idx}|{tg_mac_dinh}"})
        if len(hang) == 2: nut.append(hang); hang = []
    if hang: nut.append(hang)
    ds = "\n".join([f"  {idx}. {tk['icon']} {tk['ten']}" for idx, tk in enumerate(BO_NHO_BM.values(), 1)])
    van_ban = f"💳 DANH SÁCH TÀI KHOẢN\n━━━━━━━━━━━━━━━━━━━━\n{ds}\n━━━━━━━━━━━━━━━━━━━━\n👇 Chọn Tài khoản để soi chi tiết:"
    if msg_id: xu_ly_giao_dien_don_trang(cid, msg_id, van_ban, nut)
    else: requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", json={"chat_id": cid, "text": van_ban, "reply_markup": {"inline_keyboard": nut}})


def hien_luong_2_bao_cao_tong(cid, msg_id=None):
    van_ban = "📊 BÁO CÁO TỔNG & AI THỰC CHIẾN\n━━━━━━━━━━━━━━━━━━━━\nChọn khung thời gian:"
    nut = tao_khung_thoi_gian_chuan("QuickReport", None, "REPORT")
    nut.append([{"text": "📥 Điền Cả Tháng Này Vào Sheet", "callback_data": "SYNC_SHEET|this_month"}])
    if msg_id: xu_ly_giao_dien_don_trang(cid, msg_id, van_ban, nut)
    else: requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", json={"chat_id": cid, "text": van_ban, "reply_markup": {"inline_keyboard": nut}})


def hien_luong_3_ra_soat_ngan_sach(cid, msg_id=None):
    van_ban = f"💰 RÀ SOÁT NGÂN SÁCH (KPI: {KPI_MESS:,}đ/m)\n━━━━━━━━━━━━━━━━━━━━\nChọn mốc thời gian kiểm toán:"
    nut = tao_khung_thoi_gian_chuan("AUDIT", None, "AUDIT")
    nut.append([{"text": "📥 Điền Cả Tháng Này Vào Sheet", "callback_data": "SYNC_SHEET|this_month"}])
    if msg_id: xu_ly_giao_dien_don_trang(cid, msg_id, van_ban, nut)
    else: requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", json={"chat_id": cid, "text": van_ban, "reply_markup": {"inline_keyboard": nut}})


def hien_luong_4_cong_no_va_cai_dat(cid, msg_id=None):
    global BO_NHO_BM
    BO_NHO_BM = quet_danh_sach_tai_khoan()
    tong_no = sum(acc["balance"] for acc in BO_NHO_BM.values())
    thue = int(tong_no * (THUE_VAT_FB / 100.0))
    van_ban = f"🏦 CÔNG NỢ & THẺ\n━━━━━━━━━━━━━━━━━━━━\n💰 Tổng nợ: {tong_no:,}đ + VAT ({THUE_VAT_FB}%): {thue:,}đ ➔ Tổng: {tong_no + thue:,}đ"
    nut = [
        [{"text": "📥 Điền Cả Tháng Này Vào Sheet", "callback_data": "SYNC_SHEET|this_month"}],
        [{"text": "🔄 Làm mới dữ liệu", "callback_data": "REFRESH_ALL"}]
    ]
    if msg_id: xu_ly_giao_dien_don_trang(cid, msg_id, van_ban, nut)
    else: requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", json={"chat_id": cid, "text": van_ban, "reply_markup": {"inline_keyboard": nut}})


def hien_man_hinh_tai_khoan(cid, tk_idx, tg="today", msg_id=None):
    global BO_NHO_BM
    if not BO_NHO_BM: BO_NHO_BM = quet_danh_sach_tai_khoan()
    tk_info = BO_NHO_BM[tk_idx]
    du_lieu = tai_du_lieu_5_tang(tk_info["id"], tg)
    BO_NHO_TK[tk_idx] = {"tk_idx": tk_idx, "ten_tk": tk_info["ten"], "tg": tg, "data": du_lieu}
    
    tong_t = du_lieu["tong_tien_tk"]
    thue = int(tong_t * (THUE_VAT_FB / 100.0))
    lines = [f"💳 {tk_info['ten']} ({lay_nhan_ky_du_lieu(tg)})", f"🔥 QC: {tong_t:,}đ + VAT: {thue:,}đ ➔ Tổng: {tong_t + thue:,}đ | 💬 {du_lieu['tong_mess_tk']}m", "━━━━━━━━━━━━━━━━━━━━"]
    for c in du_lieu["cum_list"]:
        gia = int(c["chi_tieu"] / c["tin_nhan"]) if c["tin_nhan"] > 0 else 0
        lines.append(f"🔷 [{c['ten_cum']}] ({c['so_camp']}c): {c['chi_tieu']:,}đ ➔ {c['tin_nhan']}m ({dinh_dang_tien_gon(gia)})")
    
    nut = tao_khung_thoi_gian_chuan(f"TK|{tk_idx}", tg, f"TK_{tk_idx}")
    nut.append([{"text": "✨ AI Bắt Bệnh Thực Chiến", "callback_data": f"AI_TK|{tk_idx}"}])
    nut.append([{"text": "💳 Đổi Tài Khoản", "callback_data": "MENU_ACCOUNTS"}])
    xu_ly_giao_dien_don_trang(cid, msg_id, "\n".join(lines), nut)


# ==============================================================================
# 5. BÁO CÁO ĐỊNH KỲ 8H SÁNG & ĐỒNG BỘ TỰ ĐỘNG
# ==============================================================================
def chay_bao_cao_tu_dong(khoang_tg="yesterday", la_tu_dong_dinh_ky=False, since_date=None, until_date=None):
    if not (since_date and until_date): since_date, until_date = xac_dinh_khoang_ngay_tu_preset(khoang_tg)
    ok, msg = dong_bo_khoang_ngay_len_sheet(since_date, until_date)
    if not la_tu_dong_dinh_ky:
        requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg})
    else:
        requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": f"☀️ BÁO CÁO 8H SÁNG\n{msg}"})


def kiem_tra_den_gio_bao_cao_tu_dong():
    now_vn = lay_gio_viet_nam()
    ma_ngay_gio = now_vn.strftime("%Y-%m-%d_%H")
    if now_vn.hour == GIO_BAO_CAO_SANG and now_vn.minute <= 15:
        if ma_ngay_gio not in DA_BAO_CAO_TRONG_PHIEN:
            DA_BAO_CAO_TRONG_PHIEN.add(ma_ngay_gio)
            chay_bao_cao_tu_dong("yesterday", la_tu_dong_dinh_ky=True)


# ==============================================================================
# 6. VÒNG LẶP TRỰC CHIẾN 24/7
# ==============================================================================
def chay_vong_lap_truc_chien_247(offset_ban_dau=0):
    global KY_TUY_CHINH
    offset = offset_ban_dau
    thoi_diem_bat_dau = time.time()
    print("🟢 Bot đang trực chiến 24/7 (Chế độ Giao diện đơn trang & AI thực chiến)...")

    while time.time() - thoi_diem_bat_dau < THOI_GIAN_DUY_TRI_PHIEN:
        try:
            kiem_tra_den_gio_bao_cao_tu_dong()
            res = requests.get(f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates?offset={offset}&timeout=20", timeout=25).json()

            for update in res.get("result", []):
                offset = update["update_id"] + 1
                
                # Tự động xóa tin nhắn chữ của người dùng để không làm rác khung chat
                if "message" in update and "text" in update["message"]:
                    msg_obj = update["message"]
                    cid = msg_obj["chat"]["id"]
                    if str(cid) != str(CHAT_ID): continue
                    
                    try:
                        requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/deleteMessage", json={"chat_id": cid, "message_id": msg_obj["message_id"]})
                    except Exception:
                        pass

                    text_raw = msg_obj["text"].strip()
                    kq_ngay = phan_tich_ngay_tuy_chinh(text_raw)
                    if kq_ngay:
                        KY_TUY_CHINH = kq_ngay
                        hien_luong_3_ra_soat_ngan_sach(cid)
                        continue

                    if text_raw.lower() in ["/menu", "💳 danh sách tài khoản"]: hien_luong_1_ds_tai_khoan(cid)
                    elif text_raw.lower() in ["/baocao", "📊 báo cáo tổng (4 tk)"]: hien_luong_2_bao_cao_tong(cid)
                    elif text_raw.lower() in ["/rasoat", "💰 rà soát ngân sách"]: hien_luong_3_ra_soat_ngan_sach(cid)
                    elif text_raw.lower() in ["/congno", "🏦 công nợ & cài đặt"]: hien_luong_4_cong_no_va_cai_dat(cid)
                    elif text_raw.lower() in ["/sheet"]:
                        s_d, u_d = xac_dinh_khoang_ngay_tu_preset("this_month")
                        r_msg = requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", json={"chat_id": cid, "text": f"⏳ Đang đồng bộ Google Sheet ({s_d} -> {u_d})..."}).json()
                        _, msg_sh = dong_bo_khoang_ngay_len_sheet(s_d, u_d)
                        if "result" in r_msg:
                            requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/editMessageText", json={"chat_id": cid, "message_id": r_msg["result"]["message_id"], "text": msg_sh})
                    elif text_raw.lower() in ["/lich"]:
                        TRANG_THAI_LICH[cid] = {"start": None}
                        hien_bang_lich(cid, target="CUSTOM_HUB")
                    else:
                        gui_ban_phim_co_dinh(cid)
                        hien_luong_1_ds_tai_khoan(cid)

                elif "callback_query" in update:
                    cb = update["callback_query"]
                    cid = cb["message"]["chat"]["id"]
                    if str(cid) != str(CHAT_ID): continue
                    msg_id = cb["message"]["message_id"]
                    parts = cb["data"].strip().split("|")
                    lenh = parts[0]

                    requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/answerCallbackQuery", json={"callback_query_id": cb["id"]})

                    if lenh == "SYNC_SHEET":
                        s_d, u_d = xac_dinh_khoang_ngay_tu_preset(parts[1])
                        xu_ly_giao_dien_don_trang(cid, msg_id, f"⏳ Đang đồng bộ Google Sheet kỳ [{lay_nhan_ky_du_lieu(parts[1])}]...")
                        _, msg_sh = dong_bo_khoang_ngay_len_sheet(s_d, u_d)
                        xu_ly_giao_dien_don_trang(cid, msg_id, msg_sh)
                    elif lenh in ["HOME", "MENU_ACCOUNTS"]: hien_luong_1_ds_tai_khoan(cid, msg_id)
                    elif lenh == "MENU_AUDIT": hien_luong_3_ra_soat_ngan_sach(cid, msg_id)
                    elif lenh == "AUDIT":
                        che_do = parts[1]
                        s_d, u_d = xac_dinh_khoang_ngay_tu_preset(che_do)
                        nhan_tg = lay_nhan_ky_du_lieu(che_do)
                        xu_ly_giao_dien_don_trang(cid, msg_id, f"⏳ Đang rà soát ngân sách [{nhan_tg}]...")
                        
                        # Gom dữ liệu để AI phân tích thực chiến
                        tong_chi, tong_m = 0, 0
                        noi_dung_ai = []
                        for tk_idx, tk_info in BO_NHO_BM.items():
                            dl = tai_du_lieu_5_tang(tk_info["id"], che_do, s_d, u_d)
                            tong_chi += dl["tong_tien_tk"]
                            tong_m += dl["tong_mess_tk"]
                            for c in dl["cum_list"]:
                                noi_dung_ai.append(f"• Cụm [{c['ten_cum']}] ({c['so_camp']} camp): Chi {c['chi_tieu']:,}đ ➔ {c['tin_nhan']}m")
                                for sub in c["ds_camps"]:
                                    gia_sub = int(sub["chi_tieu"]/sub["tin_nhan"]) if sub["tin_nhan"] > 0 else 0
                                    noi_dung_ai.append(f"  - {sub['ten']}: {sub['chi_tieu']:,}đ ➔ {sub['tin_nhan']}m ({gia_sub:,}đ/m) | CTR:{sub.get('ctr',0)}% | CR:{sub.get('cr',0)}%")
                        
                        nhan_xet_ai = ai_bat_benh_thuc_chien(nhan_tg, "\n".join(noi_dung_ai))
                        ket_qua_hien_thi = f"💰 RÀ SOÁT NGÂN SÁCH ({nhan_tg})\n━━━━━━━━━━━━━━━━━━━━\n🔥 Tổng chi: {tong_chi:,}đ | 💬 Tổng mess: {tong_m:,}m\n━━━━━━━━━━━━━━━━━━━━\n\n{nhan_xet_ai}"
                        nut = [
                            [{"text": f"📊 Đẩy Kỳ Này Lên Sheet", "callback_data": f"SYNC_SHEET|{che_do}"}],
                            [{"text": "🔄 Đổi mốc Rà soát", "callback_data": "MENU_AUDIT"}, {"text": "🏠 Menu Chính", "callback_data": "HOME"}]
                        ]
                        xu_ly_giao_dien_don_trang(cid, msg_id, ket_qua_hien_thi, nut)

                    elif lenh == "AI_TK":
                        tk_idx = parts[1]
                        tk_info = BO_NHO_BM[tk_idx]
                        cached = BO_NHO_TK.get(tk_idx, {})
                        dl = cached.get("data", tai_du_lieu_5_tang(tk_info["id"], "today"))
                        
                        txt_ds = []
                        for c in dl["camps_list"]:
                            gia_c = int(c["chi_tieu"]/c["tin_nhan"]) if c["tin_nhan"] > 0 else 0
                            txt_ds.append(f"• Camp: {c['ten']} ➔ {c['chi_tieu']:,}đ | {c['tin_nhan']}m ({gia_c:,}đ/m)")
                        
                        nhan_xet = ai_bat_benh_thuc_chien(tk_info["ten"], "\n".join(txt_ds))
                        nut = [[{"text": "⬅️ Quay lại Tài khoản", "callback_data": f"TK|{tk_idx}|today"}]]
                        xu_ly_giao_dien_don_trang(cid, msg_id, nhan_xet, nut)

                    elif lenh == "TK": hien_man_hinh_tai_khoan(cid, parts[1], parts[2], msg_id)

        except Exception as e:
            print("⚠️ Lỗi:", e)
            time.sleep(2)


if __name__ == "__main__":
    cai_dat_menu_lenh_telegram()
    if os.environ.get("EVENT_NAME") == "workflow_dispatch":
        gui_ban_phim_co_dinh(CHAT_ID)
        hien_luong_1_ds_tai_khoan(CHAT_ID)
    chay_vong_lap_truc_chien_247()
