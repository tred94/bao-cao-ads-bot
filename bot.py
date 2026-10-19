import os
import re
import json
import time
import calendar
import requests
from datetime import datetime, timezone, timedelta

# ==============================================================================
# 🛠️ CẤU HÌNH HỆ THỐNG
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


def cai_dat_menu_lenh_telegram():
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/setMyCommands"
    commands = [
        {"command": "menu", "description": "💳 Mở Danh sách Tài khoản"},
        {"command": "baocao", "description": "📊 Mở Báo cáo Tổng (4 TK)"},
        {"command": "rasoat", "description": "💰 Mở Rà soát Ngân sách"},
        {"command": "sheet", "description": "📥 Đồng bộ Google Sheet"},
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
# HÀM ĐỒNG BỘ GOOGLE SHEET ỔN ĐỊNH (GỌI 1 LẦN NHANH CHÓNG)
# ==============================================================================
def dong_bo_khoang_ngay_len_sheet(since_ymd, until_ymd):
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

            if ngay not in tong_theo_ngay:
                tong_theo_ngay[ngay] = {"spend": 0, "mess": 0, "cmt": 0}
            tong_theo_ngay[ngay]["spend"] += spend
            tong_theo_ngay[ngay]["mess"] += mess
            tong_theo_ngay[ngay]["cmt"] += cmt

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
        return True, f"ℹ️ Không có phát sinh chi tiêu nào trong kỳ ({since_ymd} -> {until_ymd})."

    try:
        r = requests.post(SHEET_WEBHOOK_URL, json={"items": ds_items}, timeout=25)
        if r.status_code == 200:
            so_ngay = len(tong_theo_ngay)
            ds_cum = sorted(list({k[0] for k in cum_theo_ngay.keys()}))
            return True, f"✅ Đã đồng bộ thành công {so_ngay} ngày lên Google Sheet!\n• Các Tab: Tổng, {', '.join(ds_cum)}"
        return False, f"HTTP Error {r.status_code}"
    except Exception as e:
        return False, str(e)


def xac_dinh_khoang_ngay_tu_preset(che_do):
    now_vn = lay_gio_viet_nam()
    hom_nay = now_vn.strftime("%Y-%m-%d")
    hom_qua = (now_vn - timedelta(days=1)).strftime("%Y-%m-%d")

    if che_do == "today":
        return hom_nay, hom_nay
    if che_do == "yesterday":
        return hom_qua, hom_qua
    if che_do == "this_month":
        return now_vn.replace(day=1).strftime("%Y-%m-%d"), hom_nay
    if che_do == "custom" and KY_TUY_CHINH:
        return KY_TUY_CHINH[0], KY_TUY_CHINH[1]
    return hom_qua, hom_qua


# ==============================================================================
# CÁC HÀM XỬ LÝ GIAO DIỆN & FACEBOOK KHÁC
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
    params = {"fields": "id,name,account_status,amount_spent,balance,ad_trust_dsl,currency", "limit": 200, "access_token": FB_TOKEN}
    resp = requests.get(url, params=params, timeout=20).json()
    if "error" in resp:
        raise Exception(resp["error"].get("message"))

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
    if since_date and until_date:
        params["time_range"] = json.dumps({"since": since_date, "until": until_date})
    else:
        params["date_preset"] = khoang_tg if khoang_tg != "custom" else "today"

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
        g["ads_raw"][a_id] = {
            "id": a_id, "ten": a_name, "chi_tieu": spend, "tin_nhan": mess,
            "gia_mess": int(spend / mess) if mess > 0 else 0, "binh_luan": cmt,
            "clicks": clicks, "impressions": impr, "reach": reach, "video_3s": v3s, "thruplay": thru
        }

    camps_list = sorted(camps_raw.values(), key=lambda x: x["chi_tieu"], reverse=True)
    cum_list = gom_cum_chien_dich(camps_list)
    return {
        "tong_so_camp": len(ds_camp_goc), "so_camp_active": sum(1 for c in ds_camp_goc if c.get("effective_status") == "ACTIVE"),
        "so_camp_co_tieu_tien": len(camps_list), "tong_tien_tk": tong_tien_tk, "tong_mess_tk": tong_mess_tk,
        "camps_list": camps_list, "cum_list": cum_list, "thoi_diem_cap_nhat": lay_gio_viet_nam().strftime("%H:%M - %d/%m/%Y")
    }


def rà_soat_chi_tieu_bm(che_do="this_month", since_date=None, until_date=None, nhan_hien_thi=""):
    global BO_NHO_BM, BO_NHO_AUDIT
    if not BO_NHO_BM: BO_NHO_BM = quet_danh_sach_tai_khoan()
    BO_NHO_AUDIT.clear()
    tong_chi_bm, tong_mess_bm, tong_cmt_bm = 0, 0, 0
    ds_ket_qua = []

    for tk_idx, tk_info in BO_NHO_BM.items():
        du_lieu_tk = tai_du_lieu_5_tang(tk_info["id"], khoang_tg=che_do, since_date=since_date, until_date=until_date)
        spend = du_lieu_tk["tong_tien_tk"]
        mess = du_lieu_tk["tong_mess_tk"]
        cmt = sum(c["binh_luan"] for c in du_lieu_tk["camps_list"])
        tong_chi_bm += spend; tong_mess_bm += mess; tong_cmt_bm += cmt
        if spend > 0:
            BO_NHO_AUDIT[tk_idx] = {"ten_tk": tk_info["ten"], "nhan_hien_thi": nhan_hien_thi, "data": du_lieu_tk}
        ds_ket_qua.append({"tk_idx": tk_idx, "ten": tk_info["ten"], "icon": tk_info["icon"], "spend": spend, "mess": mess, "cmt": cmt, "cum_list": du_lieu_tk["cum_list"]})

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
        "━━━━━━━━━━━━━━━━━━━━"
    ]
    nut_xem_nhom = []
    for idx, item in enumerate(ds_ket_qua, 1):
        if item["spend"] > 0:
            gia_m = int(item["spend"] / item["mess"]) if item["mess"] > 0 else 0
            thue_tk = int(item["spend"] * (THUE_VAT_FB / 100.0))
            lines.append(f"{idx}. {item['icon']} {item['ten']}: QC {item['spend']:,}đ + Thuế {thue_tk:,}đ ➔ {item['mess']}m ({dinh_dang_tien_gon(gia_m)}/m)")
            nut_xem_nhom.append([{"text": f"📂 Nhóm: {rut_gon_ten_tk(item['ten'])}", "callback_data": f"AUDIT_TK|{item['tk_idx']}"}])

    nut_xem_nhom.append([
        {"text": f"📊 Đẩy Kỳ Này Lên Sheet ({nhan_hien_thi})", "callback_data": f"SYNC_SHEET|{che_do}"},
        {"text": "📥 Điền Cả Tháng (1->Nay)", "callback_data": "SYNC_SHEET|this_month"}
    ])
    nut_xem_nhom.append([{"text": "📅 Bảng Lịch", "callback_data": "CAL_OPEN|AUDIT"}])
    return "\n".join(lines), nut_xem_nhom


def tao_bang_gom_cum_text(ten_tk, cum_list, tong_tien_tk):
    lines = [f"📦 TỔNG HỢP THEO CỤM ({ten_tk})", "━━━━━━━━━━━━━━━━━━━━"]
    for c_group in cum_list:
        ten_cum = c_group["ten_cum"]
        tien, mess = c_group["chi_tieu"], c_group["tin_nhan"]
        gia_tb = int(tien / mess) if mess > 0 else 0
        lines.append(f"🔷 CỤM [{ten_cum}] ({c_group['so_camp']} camp): {tien:,}đ ➔ {mess} mess ({dinh_dang_tien_gon(gia_tb)}/m)")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def gui_ban_phim_co_dinh(chat_id, loi_nhan="⌨️ Đã bật Menu Điều Hướng!"):
    requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": loi_nhan, "reply_markup": BAN_PHIM_CO_DINH})


def gui_hoac_sua_menu(chat_id, van_ban, nut_bam=None, msg_id=None):
    if msg_id and len(van_ban) <= 3800:
        r = requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/editMessageText", json={"chat_id": chat_id, "message_id": msg_id, "text": van_ban, "reply_markup": {"inline_keyboard": nut_bam} if nut_bam else None}).json()
        if r.get("ok"): return
    requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": van_ban, "reply_markup": {"inline_keyboard": nut_bam} if nut_bam else BAN_PHIM_CO_DINH})


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
    gui_hoac_sua_menu(cid, f"💳 DANH SÁCH TÀI KHOẢN\n━━━━━━━━━━━━━━━━━━━━\n{ds}\n━━━━━━━━━━━━━━━━━━━━\n👇 Chọn Tài khoản để soi chi tiết:", nut, msg_id)


def hien_luong_2_bao_cao_tong(cid, msg_id=None):
    gui_hoac_sua_menu(cid, "📊 BÁO CÁO TỔNG\n━━━━━━━━━━━━━━━━━━━━\nChọn khung thời gian:", tao_khung_thoi_gian_chuan("QuickReport", None, "REPORT"), msg_id)


def hien_luong_3_ra_soat_ngan_sach(cid, msg_id=None):
    gui_hoac_sua_menu(cid, "💰 RÀ SOÁT NGÂN SÁCH\n━━━━━━━━━━━━━━━━━━━━\nChọn khung thời gian:", tao_khung_thoi_gian_chuan("AUDIT", None, "AUDIT"), msg_id)


def hien_luong_4_cong_no_va_cai_dat(cid, msg_id=None):
    global BO_NHO_BM
    BO_NHO_BM = quet_danh_sach_tai_khoan()
    tong_no = sum(acc["balance"] for acc in BO_NHO_BM.values())
    thue = int(tong_no * (THUE_VAT_FB / 100.0))
    van_ban = f"🏦 CÔNG NỢ & THẺ\n━━━━━━━━━━━━━━━━━━━━\n💰 Tổng nợ: {tong_no:,}đ + VAT: {thue:,}đ ➔ Tổng: {tong_no + thue:,}đ"
    nut = [
        [{"text": "📥 Điền Cả Tháng Này Vào Sheet", "callback_data": "SYNC_SHEET|this_month"}],
        [{"text": "🔄 Làm mới", "callback_data": "REFRESH_ALL"}],
        [{"text": "🏠 Menu Chính", "callback_data": "HOME"}]
    ]
    gui_hoac_sua_menu(cid, van_ban, nut, msg_id)


def hien_man_hinh_tai_khoan(cid, tk_idx, tg="today", msg_id=None):
    global BO_NHO_BM
    if not BO_NHO_BM: BO_NHO_BM = quet_danh_sach_tai_khoan()
    tk_info = BO_NHO_BM[tk_idx]
    du_lieu = tai_du_lieu_5_tang(tk_info["id"], tg)
    BO_NHO_TK[tk_idx] = {"tk_idx": tk_idx, "ten_tk": tk_info["ten"], "tg": tg, "data": du_lieu}
    tong_t = du_lieu["tong_tien_tk"]
    thue = int(tong_t * (THUE_VAT_FB / 100.0))
    tom_tat = f"💳 {tk_info['ten']} ({lay_nhan_ky_du_lieu(tg)})\n💰 QC: {tong_t:,}đ + VAT: {thue:,}đ ➔ Tổng: {tong_t + thue:,}đ\n💬 {du_lieu['tong_mess_tk']}m\n\n{tao_bang_gom_cum_text(tk_info['ten'], du_lieu['cum_list'], tong_t)}"
    nut = tao_khung_thoi_gian_chuan(f"TK|{tk_idx}", tg, f"TK_{tk_idx}")
    nut.append([{"text": "💳 Đổi Tài Khoản", "callback_data": "MENU_ACCOUNTS"}])
    gui_hoac_sua_menu(cid, tom_tat, nut, msg_id)


def chay_bao_cao_tu_dong(khoang_tg="yesterday", la_tu_dong_dinh_ky=False, since_date=None, until_date=None):
    if not (since_date and until_date):
        since_date, until_date = xac_dinh_khoang_ngay_tu_preset(khoang_tg)
    ok, msg = dong_bo_khoang_ngay_len_sheet(since_date, until_date)
    if not la_tu_dong_dinh_ky:
        gui_hoac_sua_menu(CHAT_ID, msg)


def kiem_tra_den_gio_bao_cao_tu_dong():
    now_vn = lay_gio_viet_nam()
    ma_ngay_gio = now_vn.strftime("%Y-%m-%d_%H")
    if now_vn.hour == GIO_BAO_CAO_SANG and now_vn.minute <= 15:
        if ma_ngay_gio not in DA_BAO_CAO_TRONG_PHIEN:
            DA_BAO_CAO_TRONG_PHIEN.add(ma_ngay_gio)
            chay_bao_cao_tu_dong("yesterday", la_tu_dong_dinh_ky=True)


def chay_vong_lap_truc_chien_247(offset_ban_dau=0):
    global KY_TUY_CHINH
    offset = offset_ban_dau
    thoi_diem_bat_dau = time.time()
    print("🟢 Bot đang trực chiến 24/7...")

    while time.time() - thoi_diem_bat_dau < THOI_GIAN_DUY_TRI_PHIEN:
        try:
            kiem_tra_den_gio_bao_cao_tu_dong()
            res = requests.get(f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates?offset={offset}&timeout=20", timeout=25).json()

            for update in res.get("result", []):
                offset = update["update_id"] + 1
                if "message" in update and "text" in update["message"]:
                    cid = update["message"]["chat"]["id"]
                    if str(cid) != str(CHAT_ID): continue
                    text_raw = update["message"]["text"].strip()
                    
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
                        gui_hoac_sua_menu(cid, f"⏳ Đang đồng bộ Google Sheet ({s_d} -> {u_d})...")
                        _, msg_sh = dong_bo_khoang_ngay_len_sheet(s_d, u_d)
                        gui_hoac_sua_menu(cid, msg_sh)
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

                    if lenh == "SYNC_SHEET":
                        s_d, u_d = xac_dinh_khoang_ngay_tu_preset(parts[1])
                        gui_hoac_sua_menu(cid, f"⏳ Đang đồng bộ Google Sheet kỳ [{lay_nhan_ky_du_lieu(parts[1])}]...", None, msg_id)
                        _, msg_sh = dong_bo_khoang_ngay_len_sheet(s_d, u_d)
                        gui_hoac_sua_menu(cid, msg_sh, None, msg_id)
                    elif lenh in ["HOME", "MENU_ACCOUNTS"]: hien_luong_1_ds_tai_khoan(cid, msg_id)
                    elif lenh == "MENU_AUDIT": hien_luong_3_ra_soat_ngan_sach(cid, msg_id)
                    elif lenh == "AUDIT":
                        bc, nut = rà_soat_chi_tieu_bm(parts[1], nhan_hien_thi=lay_nhan_ky_du_lieu(parts[1]))
                        gui_hoac_sua_menu(cid, bc, nut, msg_id)
                    elif lenh == "AUDIT_TK":
                        van_ban_nhom, nut_nhom = tao_bang_chi_tiet_nhom_audit(parts[1])
                        gui_hoac_sua_menu(cid, van_ban_nhom, nut_nhom, msg_id)
                    elif lenh == "TK": hien_man_hinh_tai_khoan(cid, parts[1], parts[2], msg_id)

        except Exception as e:
            print("⚠️ Lỗi:", e)
            time.sleep(3)


if __name__ == "__main__":
    cai_dat_menu_lenh_telegram()
    if os.environ.get("EVENT_NAME") == "workflow_dispatch":
        gui_ban_phim_co_dinh(CHAT_ID)
        hien_luong_1_ds_tai_khoan(CHAT_ID)
    chay_vong_lap_truc_chien_247()
