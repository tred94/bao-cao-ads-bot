import os
import re
import json
import time
import calendar
import requests
from datetime import datetime, timezone, timedelta

# ==============================================================================
# 🛠️ KHU VỰC CẤU HÌNH DỄ CHỈNH SỬA
# ==============================================================================
KPI_MESS = int(os.environ.get("KPI_GIA_MESS") or "60000")      # Mốc KPI giá mỗi tin nhắn (VNĐ)
THUE_VAT_FB = float(os.environ.get("THUE_VAT_FB") or "5.0")    # % Thuế VAT Facebook (Mặc định 5%)
GIO_BAO_CAO_SANG = 8                                           # 8h sáng -> Tự báo số liệu HÔM QUA (yesterday)
GIO_BAO_CAO_TOI = 20                                           # 20h tối -> Tự báo số liệu HÔM NAY (today)
THOI_GIAN_DUY_TRI_PHIEN = 54 * 60                              # Giữ Bot thức liên tục 54 phút (nối tiếp mỗi giờ = 24/24)

FB_TOKEN = (os.environ.get("FB_ACCESS_TOKEN") or "").strip()
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
OPENAI_KEY = (os.environ.get("OPENAI_API_KEY") or "").strip()
TELE_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
if TELE_TOKEN.startswith("bot"):
    TELE_TOKEN = TELE_TOKEN[3:]

CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "5657736528").strip()

# Mặc định ưu tiên dùng Gemini ("gemini" hoặc "chatgpt")
AI_UU_TIEN = "gemini"

BO_NHO_BM = {}
BO_NHO_TK = {}
BO_NHO_AUDIT = {}
TRANG_THAI_LICH = {}
KY_TUY_CHINH = None  # Lưu (since, until, label) khi chọn từ Bảng Lịch hoặc gõ phím
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

# Bàn phím Đáy 4 Nút Gốc (Cây Thư Mục 4 Luồng)
BAN_PHIM_CO_DINH = {
    "keyboard": [
        [{"text": "💳 Danh Sách Tài Khoản"}, {"text": "📊 Báo Cáo Tổng (4 TK)"}],
        [{"text": "💰 Rà Soát Ngân Sách"}, {"text": "🏦 Công Nợ & Cài Đặt"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}


# ==============================================================================
# 0. ĐĂNG KÝ MENU LỆNH KHI GÕ DẤU "/" TRÊN TELEGRAM
# ==============================================================================
def cai_dat_menu_lenh_telegram():
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/setMyCommands"
    commands = [
        {"command": "menu", "description": "💳 Mở Danh sách Tài khoản"},
        {"command": "baocao", "description": "📊 Mở Báo cáo Tổng (4 TK)"},
        {"command": "rasoat", "description": "💰 Mở Rà soát Ngân sách"},
        {"command": "congno", "description": "🏦 Kiểm tra Công nợ & Cài đặt AI"},
        {"command": "lich", "description": "📅 Mở Bảng Lịch chọn ngày"},
    ]
    try:
        requests.post(url, json={"commands": commands}, timeout=5)
    except Exception:
        pass


# ==============================================================================
# 1. HÀM TIỆN ÍCH RÚT GỌN TÊN, GOM CỤM & BẢNG LỊCH 7 CỘT
# ==============================================================================
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
    if len(parts) > 1 and len(parts[0].strip()) >= 2:
        prefix = parts[0].strip().upper()
    else:
        words = s.split()
        prefix = words[0].upper() if words else "KHÁC"

    if prefix in ["TRUS", "TRUST"]:
        return "TRUST"
    return prefix[:12]


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
    """Vẽ Bảng Lịch Bấm 7 cột (Từ Thứ 2 -> Chủ Nhật) ngay trên Telegram"""
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

    ten_muc_tieu = {
        "AUDIT": "💰 Rà Soát Ngân Sách",
        "REPORT": "📊 Báo Cáo Tổng (4 TK)",
    }.get(target, "💳 Xem Tài Khoản")
    if target.startswith("TK_"):
        tk_idx = target.split("_")[1]
        ten_tk = BO_NHO_BM.get(tk_idx, {}).get("ten", f"TK {tk_idx}")
        ten_muc_tieu = f"💳 TK: {ten_tk}"

    if ngay_bat_dau:
        d_dep = datetime.strptime(ngay_bat_dau, "%Y-%m-%d").strftime("%d/%m/%Y")
        nut.append([
            {"text": f"🔍 Xem ngay 1 ngày ({d_dep})", "callback_data": f"CAL_SINGLE|{target}|{ngay_bat_dau}"},
        ])
        nut.append([
            {"text": "🔄 Chọn lại ngày khác", "callback_data": f"CAL_RESET|{target}|{nam}|{thang}"},
        ])
        huong_dan = (
            f"✅ Đã chọn mốc đầu: {d_dep}\n"
            f"👉 Bấm nút [🔍 Xem ngay 1 ngày ({d_dep})] bên dưới nếu chỉ xem 1 ngày.\n"
            f"👉 Hoặc chạm tiếp vào 1 ngày thứ 2 trên lịch để xem KHOẢNG NGÀY!"
        )
    else:
        huong_dan = (
            "👉 Chạm vào 1 ngày trên lịch để chọn Ngày bắt đầu.\n"
            "• Muốn xem 1 ngày: Chạm ngày đó ➔ Bấm [🔍 Xem ngay].\n"
            "• Muốn xem nhiều ngày: Chạm ngày đầu ➔ Chạm tiếp ngày cuối."
        )

    nut_quay_lai = "MENU_ACCOUNTS"
    if target == "AUDIT":
        nut_quay_lai = "MENU_AUDIT"
    elif target == "REPORT":
        nut_quay_lai = "MENU_REPORT"
    elif target.startswith("TK_"):
        nut_quay_lai = f"BACK_TK|{target.split('_')[1]}"

    nut.append([{"text": "⬅️ Quay lại", "callback_data": nut_quay_lai}])

    van_ban = (
        f"📅 BẢNG LỊCH CHỌN NGÀY TRỰC QUAN\n"
        f"🎯 Chế độ đang chọn: {ten_muc_tieu}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{huong_dan}"
    )
    gui_hoac_sua_menu(cid, van_ban, nut, msg_id)


# ==============================================================================
# 2. QUÉT DỮ LIỆU FACEBOOK 5 TẦNG (KÈM HOOK RATE, HOLD RATE & CÔNG NỢ)
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
    resp = requests.get(url, params=params).json()
    if "error" in resp:
        msg = resp["error"].get("message", "Lỗi không xác định")
        gui_hoac_sua_menu(
            CHAT_ID,
            f"⚠️ Cảnh báo lỗi Facebook Token:\n{msg}\n\n👉 Vui lòng kiểm tra lại FB_ACCESS_TOKEN trong GitHub Secrets.",
        )
        raise Exception(f"Lỗi FB Token: {msg}")

    ds_tk = {}
    icon_map = {1: "🟢", 2: "🔴", 3: "🟡", 7: "🟠", 9: "⏳"}
    status_text_map = {
        1: "Hoạt động",
        2: "Vô hiệu hóa",
        3: "Nợ cước / Lỗi thẻ",
        7: "Đang duyệt",
        9: "Ân hạn nợ",
    }
    for idx, acc in enumerate(resp.get("data", [])):
        tk_idx = str(idx)
        st_code = acc.get("account_status", 1)
        currency = acc.get("currency", "VND")
        he_so = 1 if currency == "VND" else 100

        balance_raw = int(float(acc.get("balance", 0))) // he_so
        spent_raw = int(float(acc.get("amount_spent", 0))) // he_so
        threshold_raw = int(float(acc.get("ad_trust_dsl", 0)))

        ds_tk[tk_idx] = {
            "tk_idx": tk_idx,
            "id": acc.get("id"),
            "ten": acc.get("name") or acc.get("id"),
            "icon": icon_map.get(st_code, "⚪"),
            "status_code": st_code,
            "status_text": status_text_map.get(st_code, f"Mã {st_code}"),
            "balance": balance_raw,
            "amount_spent": spent_raw,
            "threshold": threshold_raw,
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
    ).json()
    ds_camp_goc = r_camp.get("data", []) if "error" not in r_camp else []
    tong_so_camp = len(ds_camp_goc)
    so_camp_active = sum(1 for c in ds_camp_goc if c.get("effective_status") == "ACTIVE")
    trang_thai_camp = {
        c["id"]: ("🟢 Đang bật" if c.get("effective_status") == "ACTIVE" else "⚪ Đã tắt")
        for c in ds_camp_goc
    }

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

    r_ins = requests.get(url_ins, params=params).json()
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


def rà_soat_chi_tieu_bm(che_do="this_month", since_date=None, until_date=None, nhan_hien_thi=""):
    global BO_NHO_BM, BO_NHO_AUDIT
    if not BO_NHO_BM:
        BO_NHO_BM = quet_danh_sach_tai_khoan()

    BO_NHO_AUDIT.clear()
    tong_chi_bm = 0
    tong_mess_bm = 0
    tong_cmt_bm = 0
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
            "tk_idx": tk_idx,
            "ten": tk_info["ten"],
            "icon": tk_info["icon"],
            "spend": spend,
            "mess": mess,
            "cmt": cmt,
            "cum_list": du_lieu_tk["cum_list"],
        })

    ds_ket_qua.sort(key=lambda x: x["spend"], reverse=True)
    gia_tb_bm = int(tong_chi_bm / tong_mess_bm) if tong_mess_bm > 0 else 0
    tien_thue = int(tong_chi_bm * (THUE_VAT_FB / 100.0))
    tong_sau_thue = tong_chi_bm + tien_thue

    lines = [
        f"💰 RÀ SOÁT NGÂN SÁCH ({nhan_hien_thi})",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🔥 TỔNG CHI TIÊU ADS: {tong_chi_bm:,}đ",
        f"🧾 Thuế VAT ({THUE_VAT_FB}%): +{tien_thue:,}đ",
        f"💳 TỔNG THỰC TRỪ THẺ: {tong_sau_thue:,}đ",
        f"💬 Kết quả: {tong_mess_bm:,} mess (TB: {gia_tb_bm:,}đ/m) | {tong_cmt_bm:,} cmt",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    nut_xem_nhom = []
    hang_nut_tk = []
    for idx, item in enumerate(ds_ket_qua, 1):
        if item["spend"] > 0:
            gia_m = int(item["spend"] / item["mess"]) if item["mess"] > 0 else 0
            ty_trong = round((item["spend"] / tong_chi_bm) * 100, 1) if tong_chi_bm > 0 else 0
            thue_tk = int(item["spend"] * (THUE_VAT_FB / 100.0))
            lines.append(
                f"{idx}. {item['icon']} {item['ten']}: {item['spend']:,}đ ({ty_trong}%)\n"
                f"   • +Thuế: {item['spend'] + thue_tk:,}đ | {item['mess']} mess ({dinh_dang_tien_gon(gia_m)}/m)"
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
        {"text": "📅 Mở Bảng Lịch", "callback_data": "CAL_OPEN|AUDIT"},
        {"text": "💰 Đổi mốc Rà soát", "callback_data": "MENU_AUDIT"},
    ])
    return "\n".join(lines), nut_xem_nhom


def tao_bang_chi_tiet_nhom_audit(tk_idx):
    if tk_idx not in BO_NHO_AUDIT:
        return "⚠️ Dữ liệu đã làm mới, vui lòng chọn lại mốc rà soát.", [[{"text": "⬅️ Quay lại", "callback_data": "MENU_AUDIT"}]]

    info = BO_NHO_AUDIT[tk_idx]
    ten_tk = info["ten_tk"]
    nhan_tg = info["nhan_hien_thi"]
    du_lieu = info["data"]
    tong_tien_tk = du_lieu["tong_tien_tk"]

    lines = [
        f"📂 CHI TIẾT NHÓM (ADSET) - {ten_tk}",
        f"📅 Kỳ: {nhan_tg} | 💰 Tổng: {tong_tien_tk:,}đ",
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


# ==============================================================================
# 3. KẺ BẢNG SỐ LIỆU GỌN GÀNG & DỮ LIỆU NGẦM CHO AI BẮT BỆNH
# ==============================================================================
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

        if che_do_gon:
            lines.append(
                f"{idx}. {icon_dg} {item['ten']}\n"
                f"   💵 {tien:,}đ ➔ 💬 {kq_str}\n"
                f"   📈 CTR:{ctr}% | CR:{cr_mess}% | CPM:{int(cpm/1000)}k{vid_short}"
            )
        else:
            ty_trong = round((tien / tong_tien_cha) * 100, 1) if tong_tien_cha > 0 else 0
            lines.append(
                f"{idx}. {icon_dg} {item['ten']} | Tiêu: {tien:,}đ ({ty_trong}%) | KQ: {kq_str} | "
                f"CPM:{int(cpm/1000)}k | Freq:{freq} | CTR:{ctr}% | CR:{cr_mess}%{vid_short}"
            )
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def tao_bang_gom_cum_text(ten_tk, cum_list, tong_tien_tk, chi_tiet_cho_ai=False):
    lines = [f"📦 TỔNG HỢP THEO CỤM ({ten_tk})", "━━━━━━━━━━━━━━━━━━━━"]
    for c_group in cum_list:
        ten_cum = c_group["ten_cum"]
        so_camp = c_group["so_camp"]
        tien = c_group["chi_tieu"]
        mess = c_group["tin_nhan"]
        gia_tb = int(tien / mess) if mess > 0 else 0
        ty_trong = round((tien / tong_tien_tk) * 100, 1) if tong_tien_tk > 0 else 0

        lines.append(
            f"🔷 CỤM [{ten_cum}] ({so_camp} camp): {tien:,}đ ({ty_trong}%) ➔ {mess} mess ({dinh_dang_tien_gon(gia_tb)}/m)"
        )
        for sub in sorted(c_group["ds_camps"], key=lambda x: x["chi_tieu"], reverse=True):
            sub_gia = int(sub["chi_tieu"] / sub["tin_nhan"]) if sub["tin_nhan"] > 0 else 0
            ctr, cpm, freq, cr_mess, hook_r, hold_r = tinh_chi_so_phu(sub)
            icon_dg = "🟢" if (sub["tin_nhan"] > 0 and sub_gia <= KPI_MESS) else ("🔴" if sub["tin_nhan"] == 0 else "🟡")
            if chi_tiet_cho_ai:
                vid_info = f" | Hook:{hook_r}% Hold:{hold_r}%" if hook_r > 0 else ""
                lines.append(
                    f"   • {icon_dg} {sub['ten']}: {sub['chi_tieu']:,}đ | {sub['tin_nhan']} mess ({dinh_dang_tien_gon(sub_gia)}) [CPM:{int(cpm/1000)}k | Freq:{freq} | CTR:{ctr}% | CR:{cr_mess}%{vid_info}]"
                )
            else:
                kq_gon = "0 mess" if sub["tin_nhan"] == 0 else f"{sub['tin_nhan']}m ({dinh_dang_tien_gon(sub_gia)})"
                lines.append(f"   {icon_dg} {sub['ten']}: {dinh_dang_tien_gon(sub['chi_tieu'])} ➔ {kq_gon}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def tim_model_gemini():
    try:
        res = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_KEY}",
            timeout=10,
        ).json()
        ds = [
            m.get("name", "")
            for m in res.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
            and "gemini" in m.get("name", "")
            and not any(
                k in m.get("name", "")
                for k in ["tts", "image", "audio", "embedding", "vision", "veo"]
            )
        ]
        if ds:
            return ds
    except Exception:
        pass
    return ["models/gemini-2.5-flash-lite", "models/gemini-2.0-flash"]


def goi_gemini_api(prompt_text):
    if not GEMINI_KEY:
        return None
    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {"temperature": 0.2},
    }
    for m in tim_model_gemini():
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/{m}:generateContent?key={GEMINI_KEY}",
                json=payload,
                timeout=20,
            ).json()
            if "candidates" in r:
                ten_model = m.replace("models/", "")
                noi_dung = r["candidates"][0]["content"]["parts"][0]["text"]
                return f"✨ [Phân tích bởi Gemini ({ten_model})]\n\n{noi_dung}"
        except Exception:
            continue
    return None


def goi_openai_gpt(prompt_text):
    if not OPENAI_KEY:
        return None
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "Bạn là Giám đốc Tối ưu Quảng cáo Facebook (Senior Media Buyer)."},
            {"role": "user", "content": prompt_text}
        ],
        "temperature": 0.2
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=25).json()
        if "choices" in res and len(res["choices"]) > 0:
            noi_dung = res["choices"][0]["message"]["content"]
            return f"🤖 [Phân tích bởi ChatGPT (gpt-4o-mini)]\n\n{noi_dung}"
    except Exception as e:
        print("⚠️ Lỗi gọi OpenAI:", e)
    return None


def gemini_danh_gia_chuyen_sau(tieu_de, du_lieu_text, chon_ai=None):
    ai_muc_tieu = chon_ai if chon_ai else AI_UU_TIEN

    prompt = f"""
    Bạn là Giám đốc Tối ưu Quảng cáo Facebook (Senior Media Buyer).
    Đánh giá dữ liệu của [{tieu_de}] dưới đây (Mốc KPI mục tiêu: {KPI_MESS:,}đ/mess):

    {du_lieu_text}

    YÊU CẦU BẮT BUỘC:
    - Trả lời CỰC KỲ NGẮN GỌN, SÚC TÍCH, ĐI THẲNG VÀO TRỌNG TÂM.
    - Chẩn đoán nguyên nhân dựa trên chỉ số:
      + Do Nội dung (Content/Hình ảnh): dựa vào CTR (cao >2% là thu hút, thấp <1.5% là kém hấp dẫn).
      + Do Video (nếu có chỉ số Hook/Hold):
        * Hook Rate (3s đầu): >25% là tốt, <20% là 3 giây đầu nhàm chán, khách lướt qua ngay.
        * Hold Rate (Giữ chân): >25% là cuốn hút, <15% là nội dung giữa video lan man.
      + Do Tệp khách hàng (Audience): dựa vào CPM (đắt hay rẻ) và Tần suất lặp Freq (cao >2.2 là tệp hẹp/bão hòa).
      + Do Kịch bản chốt/Độ lệch phễu: dựa vào tỷ lệ chuyển đổi Click->Mess (CR%).

    Trình bày đúng 3 mục:
    🟢 1. VÌ SAO TỐT (MỤC HIỆU QUẢ):
    - [Tên mục tốt]: Giá mess bao nhiêu, nhờ CTR/Hook/Hold hay CPM/CR%.

    🔴 2. VÌ SAO CHƯA TỐT (MỤC ĐẮT / LỖ):
    - [Tên mục chưa tốt]: Giá mess bao nhiêu (hoặc tiêu bao nhiêu mà 0 mess). Chỉ rõ lỗi tại [3 GIÂY ĐẦU VIDEO], [NỘI DUNG GIỮA VIDEO], [HÌNH ẢNH/TIÊU ĐỀ], [TỆP KHÁCH], hay [KỊCH BẢN CHAT].

    💡 3. ĐỀ XUẤT HÀNH ĐỘNG NGAY:
    - Tắt / Giảm vốn: Chỉ đích danh mục nào.
    - Tăng vốn: Chỉ đích danh mục nào.
    - Cách khắc phục cụ thể.

    Không dùng ký tự dấu sao (*) hay dấu thăng (#).
    """

    if ai_muc_tieu == "chatgpt":
        kq = goi_openai_gpt(prompt)
        if kq:
            return kq
        kq_du_phong = goi_gemini_api(prompt)
        if kq_du_phong:
            return f"⚠️ (ChatGPT chưa phản hồi, tự động chuyển sang Gemini)\n{kq_du_phong}"
    else:
        kq = goi_gemini_api(prompt)
        if kq:
            return kq
        kq_du_phong = goi_openai_gpt(prompt)
        if kq_du_phong:
            return f"⚠️ (Gemini quá tải, tự động chuyển sang ChatGPT)\n{kq_du_phong}"

    return "⚠️ Không kết nối được cả Gemini API và OpenAI API."


# ==============================================================================
# 4. CÂY THƯ MỤC 4 LUỒNG ĐỒNG BỘ + KHUNG THỜI GIAN THỐNG NHẤT
# ==============================================================================
def gui_ban_phim_co_dinh(chat_id, loi_nhan="⌨️ Đã bật Thanh Điều Hướng 4 Luồng dưới đáy màn hình!"):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": loi_nhan, "reply_markup": BAN_PHIM_CO_DINH})


def gui_hoac_sua_menu(chat_id, van_ban, nut_bam=None, msg_id=None):
    if msg_id and len(van_ban) <= 3800:
        url_edit = f"https://api.telegram.org/bot{TELE_TOKEN}/editMessageText"
        payload = {"chat_id": chat_id, "message_id": msg_id, "text": van_ban}
        if nut_bam:
            payload["reply_markup"] = {"inline_keyboard": nut_bam}
        r = requests.post(url_edit, json=payload).json()
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
            if nut_bam:
                payload["reply_markup"] = {"inline_keyboard": nut_bam}
            else:
                payload["reply_markup"] = BAN_PHIM_CO_DINH
        requests.post(url, json=payload)


def tao_khung_thoi_gian_chuan(prefix_cmd, tg_hien_tai=None, target_lich="AUDIT"):
    """Bộ Khung Thời Gian Chuẩn (7 mốc + Bảng Lịch) dùng chung đồng bộ cho mọi luồng"""
    cac_moc_1 = [("today", "⚡H.Nay"), ("yesterday", "📅H.Qua"), ("last_3d", "3 Ngày"), ("last_7d", "7 Ngày")]
    hang_1 = [
        {"text": f"✅{n}" if tg_hien_tai == m else n, "callback_data": f"{prefix_cmd}|{m}"}
        for m, n in cac_moc_1
    ]

    cac_moc_2 = [("this_month", "📆 Tháng này"), ("last_month", "⏪ Tháng trước"), ("last_30d", "30 Ngày")]
    hang_2 = [
        {"text": f"✅{n}" if tg_hien_tai == m else n, "callback_data": f"{prefix_cmd}|{m}"}
        for m, n in cac_moc_2
    ]

    nhan_lich = f"✅ 📅 {KY_TUY_CHINH[2]}" if (tg_hien_tai == "custom" and KY_TUY_CHINH) else "📅 Mở Bảng Lịch Chọn Ngày"
    hang_3 = [{"text": nhan_lich, "callback_data": f"CAL_OPEN|{target_lich}"}]

    return [hang_1, hang_2, hang_3]


# --- LUỒNG 1: 💳 DANH SÁCH TÀI KHOẢN ---
def hien_luong_1_ds_tai_khoan(cid, msg_id=None, tg_mac_dinh="today"):
    global BO_NHO_BM
    if not BO_NHO_BM:
        BO_NHO_BM = quet_danh_sach_tai_khoan()

    gio_hien_tai = lay_gio_viet_nam().strftime("%H:%M - %d/%m/%Y")
    ten_ai = "Gemini" if AI_UU_TIEN == "gemini" else "ChatGPT"

    nut_tk = []
    hang_acc = []
    for idx, (tk_idx, tk_info) in enumerate(BO_NHO_BM.items(), 1):
        ten_ngan = rut_gon_ten_tk(tk_info["ten"])
        hang_acc.append({
            "text": f"{tk_info['icon']} {idx}. {ten_ngan}",
            "callback_data": f"TK|{tk_idx}|{tg_mac_dinh}",
        })
        if len(hang_acc) == 2:
            nut_tk.append(hang_acc)
            hang_acc = []
    if hang_acc:
        nut_tk.append(hang_acc)

    ds_ten_day_du = "\n".join(
        [f"  {idx}. {tk['icon']} {tk['ten']}" for idx, tk in enumerate(BO_NHO_BM.values(), 1)]
    )

    van_ban = (
        f"💳 DANH SÁCH TÀI KHOẢN QUẢNG CÁO\n"
        f"🕒 {gio_hien_tai} | 🧠 AI: {ten_ai} | 🧾 VAT: {THUE_VAT_FB}%\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{ds_ten_day_du}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 Chạm vào Tài khoản bên dưới để xem số liệu & chọn khung thời gian:"
    )
    gui_hoac_sua_menu(cid, van_ban, nut_tk, msg_id)


# --- LUỒNG 2: 📊 BÁO CÁO TỔNG (4 TK) ---
def hien_luong_2_bao_cao_tong(cid, msg_id=None):
    van_ban = (
        f"📊 BÁO CÁO TỔNG & AI BẮT BỆNH (CẢ {len(BO_NHO_BM) or 4} TÀI KHOẢN)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Chọn khung thời gian bên dưới để xuất báo cáo tổng hợp theo Cụm và gọi AI phân tích toàn bộ các Tài khoản có tiêu tiền:"
    )
    nut_bam = tao_khung_thoi_gian_chuan("QuickReport", tg_hien_tai=None, target_lich="REPORT")
    gui_hoac_sua_menu(cid, van_ban, nut_bam, msg_id)


# --- LUỒNG 3: 💰 RÀ SOÁT NGÂN SÁCH ---
def hien_luong_3_ra_soat_ngan_sach(cid, msg_id=None):
    van_ban = (
        f"💰 RÀ SOÁT NGÂN SÁCH (TÀI KHOẢN / CỤM / NHÓM)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Chọn khung thời gian hoặc mở Bảng Lịch bên dưới để kiểm toán tổng chi tiêu + Thuế VAT ({THUE_VAT_FB}%) và bóc tách từng Nhóm (AdSet):"
    )
    nut_bam = tao_khung_thoi_gian_chuan("AUDIT", tg_hien_tai=None, target_lich="AUDIT")
    gui_hoac_sua_menu(cid, van_ban, nut_bam, msg_id)


# --- LUỒNG 4: 🏦 CÔNG NỢ & CÀI ĐẶT ---
def hien_luong_4_cong_no_va_cai_dat(cid, msg_id=None):
    global BO_NHO_BM
    BO_NHO_BM = quet_danh_sach_tai_khoan()

    tong_no_bm = 0
    so_tk_loi = 0
    lines = [
        "🏦 KIỂM TRA CÔNG NỢ, THẺ & CÀI ĐẶT HỆ THỐNG",
        f"🕒 Cập nhật: {lay_gio_viet_nam().strftime('%H:%M - %d/%m/%Y')}",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    ds_acc = sorted(BO_NHO_BM.values(), key=lambda x: (x["status_code"] != 1, -x["balance"]))
    for idx, acc in enumerate(ds_acc, 1):
        no_hien_tai = acc["balance"]
        nguong = acc["threshold"]
        tong_tieu = acc["amount_spent"]
        tong_no_bm += no_hien_tai

        if acc["status_code"] != 1:
            so_tk_loi += 1

        ty_le_cham_nguong = round((no_hien_tai / nguong) * 100, 1) if nguong > 0 else 0
        canh_bao_nguong = " ⚠️Sắp chạm ngưỡng" if ty_le_cham_nguong >= 85 else ""
        canh_bao_the = " 🚨[LỖI THẺ]" if acc["status_code"] in [2, 3, 9] else ""

        nguong_str = f"{dinh_dang_tien_gon(nguong)} ({ty_le_cham_nguong}%){canh_bao_nguong}" if nguong > 0 else "K.xác định"
        lines.append(
            f"{idx}. {acc['icon']} {acc['ten']} ({acc['status_text']}){canh_bao_the}\n"
            f"   • Dư nợ: {no_hien_tai:,}đ | Ngưỡng: {nguong_str}\n"
            f"   • Tổng tiêu lũy kế: {tong_tieu:,}đ"
        )

    thue_du_kien = int(tong_no_bm * (THUE_VAT_FB / 100.0))
    tong_can_chuan_bi = tong_no_bm + thue_du_kien

    tom_tat_dau = [
        f"💰 TỔNG NỢ HIỆN TẠI: {tong_no_bm:,}đ",
        f"🧾 Thuế VAT ({THUE_VAT_FB}%): +{thue_du_kien:,}đ",
        f"💳 Cần chuẩn bị trong thẻ: {tong_can_chuan_bi:,}đ",
        f"🚨 Có {so_tk_loi} TK lỗi thanh toán!" if so_tk_loi > 0 else "✅ Tất cả thẻ & TK đều hoạt động tốt.",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    van_ban = "\n".join(lines[:3] + tom_tat_dau + lines[3:])

    nhan_gemini = "✅ ✨ Ưu tiên Gemini" if AI_UU_TIEN == "gemini" else "✨ Ưu tiên Gemini"
    nhan_gpt = "✅ 🤖 Ưu tiên ChatGPT" if AI_UU_TIEN == "chatgpt" else "🤖 Ưu tiên ChatGPT"

    nut_bam = [
        [
            {"text": nhan_gemini, "callback_data": "SET_AI|gemini"},
            {"text": nhan_gpt, "callback_data": "SET_AI|chatgpt"},
        ],
        [
            {"text": "🔄 Làm Mới Dữ Liệu & Bộ Nhớ", "callback_data": "REFRESH_ALL"},
        ],
    ]
    gui_hoac_sua_menu(cid, van_ban, nut_bam, msg_id)


def hien_menu_chon_luong_cho_ngay_tuy_chinh(cid, msg_id=None):
    """Khi người dùng gõ ngày (VD: 15/10) hoặc chọn xong trên Lịch -> Cho phép đi vào mọi luồng"""
    global BO_NHO_BM
    if not BO_NHO_BM:
        BO_NHO_BM = quet_danh_sach_tai_khoan()
    nhan_d = KY_TUY_CHINH[2] if KY_TUY_CHINH else "Ngày tùy chỉnh"

    van_ban = (
        f"📅 ĐÃ CHỌN KỲ DỮ LIỆU: {nhan_d}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Bạn muốn xem dữ liệu của kỳ [{nhan_d}] theo luồng nào bên dưới?"
    )

    nut = [
        [{"text": f"💰 1. Rà Soát Ngân Sách ({nhan_d})", "callback_data": "AUDIT|custom"}],
        [{"text": f"📊 2. Báo Cáo Tổng 4 TK + AI ({nhan_d})", "callback_data": "QuickReport|custom"}],
    ]

    hang_acc = []
    for idx, (tk_idx, tk_info) in enumerate(BO_NHO_BM.items(), 1):
        ten_ngan = rut_gon_ten_tk(tk_info["ten"])
        hang_acc.append({
            "text": f"{tk_info['icon']} {idx}. {ten_ngan}",
            "callback_data": f"TK|{tk_idx}|custom",
        })
        if len(hang_acc) == 2:
            nut.append(hang_acc)
            hang_acc = []
    if hang_acc:
        nut.append(hang_acc)

    nut.append([{"text": "📅 Chọn lại trên Bảng Lịch", "callback_data": "CAL_OPEN|CUSTOM_HUB"}])
    gui_hoac_sua_menu(cid, van_ban, nut, msg_id)


# --- MÀN HÌNH CHI TIẾT TÀI KHOẢN & CÂY THƯ MỤC 5 TẦNG ---
def hien_man_hinh_tai_khoan(cid, tk_idx, tg="today", msg_id=None, can_tai_lai=True, bung_all_camp=False):
    global BO_NHO_BM
    if not BO_NHO_BM:
        BO_NHO_BM = quet_danh_sach_tai_khoan()
    tk_info = BO_NHO_BM[tk_idx]
    ma_act = tk_info["id"]
    ten_tg = lay_nhan_ky_du_lieu(tg)

    if can_tai_lai or tk_idx not in BO_NHO_TK:
        gui_hoac_sua_menu(
            cid,
            f"⏳ Đang tải số liệu [{tk_info['ten']}]\n📅 Kỳ: {ten_tg}...",
            None,
            msg_id,
        )
        du_lieu_tk = tai_du_lieu_5_tang(ma_act, tg)
        BO_NHO_TK[tk_idx] = {
            "tk_idx": tk_idx,
            "ten_tk": tk_info["ten"],
            "tg": tg,
            "data": du_lieu_tk,
        }
    else:
        du_lieu_tk = BO_NHO_TK[tk_idx]["data"]
        tg = BO_NHO_TK[tk_idx]["tg"]
        ten_tg = lay_nhan_ky_du_lieu(tg)

    tong_tien = du_lieu_tk["tong_tien_tk"]
    tong_mess = du_lieu_tk["tong_mess_tk"]
    gia_tb = int(tong_tien / tong_mess) if tong_mess > 0 else 0
    thue_tk = int(tong_tien * (THUE_VAT_FB / 100.0))
    luc_cap_nhat = du_lieu_tk.get("thoi_diem_cap_nhat", lay_gio_viet_nam().strftime("%H:%M"))

    cum_list = du_lieu_tk.get("cum_list", [])
    bang_cum_gon = (
        tao_bang_gom_cum_text(tk_info["ten"], cum_list, tong_tien, chi_tiet_cho_ai=False)
        if cum_list
        else "• Chưa có chiến dịch tiêu tiền trong kỳ này."
    )

    tom_tat = (
        f"💳 {tk_info['ten']}\n"
        f"📅 Kỳ: {ten_tg} (Lúc {luc_cap_nhat})\n"
        f"📌 Bật: {du_lieu_tk['so_camp_active']}/{du_lieu_tk['tong_so_camp']} camp | 🔥 Có tiêu: {du_lieu_tk['so_camp_co_tieu_tien']} camp\n"
        f"💰 Tiêu: {tong_tien:,}đ (+VAT: {tong_tien + thue_tk:,}đ)\n"
        f"💬 KQ: {tong_mess} mess (TB: {gia_tb:,}đ/mess)\n\n"
        f"{bang_cum_gon}"
    )

    # Khung thời gian chuẩn đồng bộ cho riêng Tài khoản này
    nut_camp = tao_khung_thoi_gian_chuan(f"TK|{tk_idx}", tg_hien_tai=tg, target_lich=f"TK_{tk_idx}")

    if du_lieu_tk["so_camp_co_tieu_tien"] > 0:
        nut_camp.append([
            {"text": "✨ Gemini Bắt Bệnh TK", "callback_data": f"ALL_C|{tk_idx}|gemini"},
            {"text": "🤖 ChatGPT Bắt Bệnh TK", "callback_data": f"ALL_C|{tk_idx}|chatgpt"},
        ])

        hang_cum = []
        for c_gr in cum_list:
            tien_gon = dinh_dang_tien_gon(c_gr["chi_tieu"])
            hang_cum.append({
                "text": f"📦 {c_gr['ten_cum']} ({tien_gon}•{c_gr['tin_nhan']}m)",
                "callback_data": f"CUM|{tk_idx}|{c_gr['cum_idx']}",
            })
            if len(hang_cum) == 2:
                nut_camp.append(hang_cum)
                hang_cum = []
        if hang_cum:
            nut_camp.append(hang_cum)

        if not bung_all_camp:
            nut_camp.append([{
                "text": f"📂 Bung tất cả {du_lieu_tk['so_camp_co_tieu_tien']} Chiến dịch lẻ",
                "callback_data": f"EXPAND_C|{tk_idx}",
            }])
        else:
            nut_camp.append([{
                "text": "🔼 Thu gọn danh sách Chiến dịch lẻ",
                "callback_data": f"BACK_TK|{tk_idx}",
            }])
            for idx, c_info in enumerate(du_lieu_tk["camps_list"], 1):
                ten_c = c_info["ten"][:24]
                tien_gon = dinh_dang_tien_gon(c_info["chi_tieu"])
                nut_camp.append([{
                    "text": f"📂 {idx}. {ten_c} ({tien_gon} • {c_info['tin_nhan']}m)",
                    "callback_data": f"C|{tk_idx}|{c_info['c_idx']}",
                }])

    nut_camp.append([
        {"text": "🔄 Làm mới", "callback_data": f"TK|{tk_idx}|{tg}"},
        {"text": "💳 Đổi Tài Khoản", "callback_data": "MENU_ACCOUNTS"},
    ])
    gui_hoac_sua_menu(cid, tom_tat, nut_camp, msg_id)


def hien_man_hinh_camp(cid, tk_idx, c_idx, msg_id=None):
    tk_cache = BO_NHO_TK[tk_idx]
    c_info = tk_cache["data"]["camps_list"][int(c_idx)]
    groups_list = c_info["groups_list"]
    gia_tb = int(c_info["chi_tieu"] / c_info["tin_nhan"]) if c_info["tin_nhan"] > 0 else 0

    bang_group = tao_bang_so_sanh_text(
        f"NHÓM TRONG CAMP [{c_info['ten']}]",
        groups_list,
        c_info["chi_tieu"],
        che_do_gon=True,
    )
    tom_tat_c = (
        f"📂 CAMP: {c_info['ten']}\n"
        f"• Kỳ: {lay_nhan_ky_du_lieu(tk_cache['tg'])} | {c_info['trang_thai']}\n"
        f"• Tiêu: {c_info['chi_tieu']:,}đ ➔ {c_info['tin_nhan']} mess ({gia_tb:,}đ/m)\n\n"
        f"{bang_group}"
    )

    nut_g = [[
        {"text": "✨ Gemini Bắt Bệnh", "callback_data": f"AI_C|{tk_idx}|{c_idx}|gemini"},
        {"text": "🤖 ChatGPT Bắt Bệnh", "callback_data": f"AI_C|{tk_idx}|{c_idx}|chatgpt"},
    ]]
    for idx, g_info in enumerate(groups_list, 1):
        ten_g = g_info["ten"][:24]
        tien_gon = dinh_dang_tien_gon(g_info["chi_tieu"])
        nut_g.append([{
            "text": f"📁 Nhóm {idx}: {ten_g} ({tien_gon} • {g_info['tin_nhan']}m)",
            "callback_data": f"G|{tk_idx}|{c_idx}|{g_info['g_idx']}",
        }])
    nut_g.append([
        {"text": "⬅️ Về Tài khoản", "callback_data": f"BACK_TK|{tk_idx}"},
        {"text": "💳 DS Tài Khoản", "callback_data": "MENU_ACCOUNTS"},
    ])
    gui_hoac_sua_menu(cid, tom_tat_c, nut_g, msg_id)


def hien_man_hinh_group(cid, tk_idx, c_idx, g_idx, msg_id=None):
    c_info = BO_NHO_TK[tk_idx]["data"]["camps_list"][int(c_idx)]
    g_info = c_info["groups_list"][int(g_idx)]
    ads_list = g_info["ads_list"]

    bang_ads = tao_bang_so_sanh_text(
        f"BÀI ADS TRONG NHÓM [{g_info['ten']}]",
        ads_list,
        g_info["chi_tieu"],
        che_do_gon=True,
    )
    nut_a = [[
        {"text": "✨ Gemini Soi Nhóm", "callback_data": f"AI_G|{tk_idx}|{c_idx}|{g_idx}|gemini"},
        {"text": "🤖 ChatGPT Soi Nhóm", "callback_data": f"AI_G|{tk_idx}|{c_idx}|{g_idx}|chatgpt"},
    ]]
    for idx, a_info in enumerate(ads_list, 1):
        ten_a = a_info["ten"][:24]
        tien_gon = dinh_dang_tien_gon(a_info["chi_tieu"])
        nut_a.append([{
            "text": f"📝 Bài {idx}: {ten_a} ({tien_gon} • {a_info['tin_nhan']}m)",
            "callback_data": f"A|{tk_idx}|{c_idx}|{g_idx}|{a_info['a_idx']}",
        }])
    nut_a.append([
        {"text": "⬅️ Về Camp", "callback_data": f"C|{tk_idx}|{c_idx}"},
        {"text": "💳 Về Tài khoản", "callback_data": f"BACK_TK|{tk_idx}"},
    ])
    gui_hoac_sua_menu(cid, bang_ads, nut_a, msg_id)


# ==============================================================================
# 5. HÀM BÁO CÁO TỔNG (4 TK) & ĐỊNH KỲ 8H SÁNG / 20H TỐI
# ==============================================================================
def chay_bao_cao_tu_dong(khoang_tg="today", la_tu_dong_dinh_ky=False, since_date=None, until_date=None, nhan_tuy_chinh=None):
    global BO_NHO_BM
    BO_NHO_BM = quet_danh_sach_tai_khoan()
    now_vn = lay_gio_viet_nam()
    gio_str = now_vn.strftime("%H:%M")
    ngay_hom_nay_str = now_vn.strftime("%d/%m/%Y")
    ngay_hom_qua_str = (now_vn - timedelta(days=1)).strftime("%d/%m/%Y")

    if khoang_tg == "custom" and KY_TUY_CHINH and not (since_date and until_date):
        since_date, until_date, nhan_tuy_chinh = KY_TUY_CHINH

    if since_date and until_date:
        ten_ky = nhan_tuy_chinh or f"{since_date} -> {until_date}"
        tieu_de_buoi = f"📊 BÁO CÁO TỔNG THEO KỲ ({ten_ky})"
    elif khoang_tg == "yesterday":
        tieu_de_buoi = f"☀️ BÁO CÁO HÔM QUA ({ngay_hom_qua_str})"
        ten_ky = f"Hôm qua {ngay_hom_qua_str}"
    elif khoang_tg == "today":
        tieu_de_buoi = (
            f"🌙 BÁO CÁO 20H TỐI ({ngay_hom_nay_str})"
            if la_tu_dong_dinh_ky
            else f"⚡ BÁO CÁO REALTIME ({gio_str} - {ngay_hom_nay_str})"
        )
        ten_ky = f"Realtime Hôm nay ({gio_str})"
    else:
        ten_ky = NHAN_THOI_GIAN.get(khoang_tg, khoang_tg)
        tieu_de_buoi = f"📊 BÁO CÁO TỔNG ({ten_ky})"

    co_tk_tieu_tien = False
    for tk_idx, tk_info in BO_NHO_BM.items():
        du_lieu = tai_du_lieu_5_tang(tk_info["id"], khoang_tg, since_date=since_date, until_date=until_date)
        BO_NHO_TK[tk_idx] = {
            "tk_idx": tk_idx,
            "ten_tk": tk_info["ten"],
            "tg": "custom" if (since_date and until_date) else khoang_tg,
            "data": du_lieu,
        }
        if du_lieu["so_camp_co_tieu_tien"] > 0:
            co_tk_tieu_tien = True
            bang_hien_thi_gon = tao_bang_gom_cum_text(
                tk_info["ten"], du_lieu["cum_list"], du_lieu["tong_tien_tk"], chi_tiet_cho_ai=False
            )
            bang_day_du_cho_ai = tao_bang_gom_cum_text(
                f"{tk_info['ten']} ({ten_ky})", du_lieu["cum_list"], du_lieu["tong_tien_tk"], chi_tiet_cho_ai=True
            )
            nhan_xet = gemini_danh_gia_chuyen_sau(f"{tk_info['ten']} ({ten_ky})", bang_day_du_cho_ai)
            gia_tb = int(du_lieu["tong_tien_tk"] / du_lieu["tong_mess_tk"]) if du_lieu["tong_mess_tk"] > 0 else 0
            thue_tk = int(du_lieu["tong_tien_tk"] * (THUE_VAT_FB / 100.0))
            mo_dau = (
                f"{tieu_de_buoi}\n"
                f"💳 TK: {tk_info['ten']}\n"
                f"💰 Tiêu: {du_lieu['tong_tien_tk']:,}đ (+VAT: {du_lieu['tong_tien_tk'] + thue_tk:,}đ)\n"
                f"💬 KQ: {du_lieu['tong_mess_tk']} mess (TB: {gia_tb:,}đ/m)\n\n"
            )
            gui_hoac_sua_menu(CHAT_ID, mo_dau + bang_hien_thi_gon + "\n\n" + nhan_xet)

    if not co_tk_tieu_tien:
        gui_hoac_sua_menu(
            CHAT_ID,
            f"{tieu_de_buoi}\nℹ️ Chưa có tài khoản nào phát sinh chi tiêu trong kỳ [{ten_ky}].",
        )


def kiem_tra_den_gio_bao_cao_tu_dong():
    now_vn = lay_gio_viet_nam()
    ma_ngay_gio = now_vn.strftime("%Y-%m-%d_%H")

    if now_vn.hour == GIO_BAO_CAO_SANG and now_vn.minute <= 15 and ma_ngay_gio not in DA_BAO_CAO_TRONG_PHIEN:
        DA_BAO_CAO_TRONG_PHIEN.add(ma_ngay_gio)
        chay_bao_cao_tu_dong("yesterday", la_tu_dong_dinh_ky=True)
        hien_luong_1_ds_tai_khoan(CHAT_ID, tg_mac_dinh="today")

    elif now_vn.hour == GIO_BAO_CAO_TOI and now_vn.minute <= 15 and ma_ngay_gio not in DA_BAO_CAO_TRONG_PHIEN:
        DA_BAO_CAO_TRONG_PHIEN.add(ma_ngay_gio)
        chay_bao_cao_tu_dong("today", la_tu_dong_dinh_ky=True)
        hien_luong_1_ds_tai_khoan(CHAT_ID, tg_mac_dinh="today")


# ==============================================================================
# 6. VÒNG LẶP TRỰC CHIẾN 24/7 (ĐÃ KHÓA BẢO MẬT CHẶN NGƯỜI LẠ)
# ==============================================================================
def xu_ly_ket_qua_chon_lich(cid, msg_id, target):
    """Thực thi hành động sau khi người dùng chọn xong 1 ngày hoặc Khoảng ngày trên Bảng Lịch"""
    since_d, until_d, nhan_d = KY_TUY_CHINH
    if target == "AUDIT":
        gui_hoac_sua_menu(cid, f"⏳ Đang rà soát ngân sách [{nhan_d}]...", None, msg_id)
        bc_audit, nut_audit = rà_soat_chi_tieu_bm(che_do="custom", since_date=since_d, until_date=until_d, nhan_hien_thi=nhan_d)
        gui_hoac_sua_menu(cid, bc_audit, nut_audit, msg_id)
    elif target == "REPORT":
        gui_hoac_sua_menu(cid, f"⏳ Đang xuất Báo Cáo Tổng + AI cho cả 4 TK [{nhan_d}]...", None, msg_id)
        chay_bao_cao_tu_dong("custom", la_tu_dong_dinh_ky=False, since_date=since_d, until_date=until_d, nhan_tuy_chinh=nhan_d)
        hien_luong_1_ds_tai_khoan(cid, tg_mac_dinh="custom")
    elif target.startswith("TK_"):
        tk_idx = target.split("_")[1]
        hien_man_hinh_tai_khoan(cid, tk_idx, "custom", msg_id, can_tai_lai=True)
    else:
        hien_menu_chon_luong_cho_ngay_tuy_chinh(cid, msg_id)


def chay_vong_lap_truc_chien_247(offset_ban_dau=0):
    global AI_UU_TIEN, KY_TUY_CHINH
    offset = offset_ban_dau
    thoi_diem_bat_dau = time.time()
    print("🟢 Bot đang trực chiến 24/7 (Cây Thư Mục 4 Luồng & Bảng Lịch 7 Cột)...")

    while time.time() - thoi_diem_bat_dau < THOI_GIAN_DUY_TRI_PHIEN:
        try:
            kiem_tra_den_gio_bao_cao_tu_dong()

            url = f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates?offset={offset}&timeout=20"
            res = requests.get(url, timeout=25).json()

            for update in res.get("result", []):
                offset = update["update_id"] + 1

                # 🔒 KHÓA BẢO MẬT PHẦN TIN NHẮN TEXT
                if "message" in update and "text" in update["message"]:
                    cid = update["message"]["chat"]["id"]
                    if str(cid) != str(CHAT_ID):
                        continue

                    text_raw = update["message"]["text"].strip()
                    text_in = text_raw.lower()

                    # Nếu người dùng gõ ngày tùy chỉnh (VD: 15/10 hoặc 01/10 - 15/10)
                    kq_ngay = phan_tich_ngay_tuy_chinh(text_raw)
                    if kq_ngay:
                        KY_TUY_CHINH = kq_ngay
                        hien_menu_chon_luong_cho_ngay_tuy_chinh(cid)
                        continue

                    if text_in in ["/menu", "💳 danh sách tài khoản", "🎛 bảng điều khiển", "🎛 mở bảng điều khiển"]:
                        hien_luong_1_ds_tai_khoan(cid, tg_mac_dinh="today")

                    elif text_in in ["/baocao", "📊 báo cáo tổng (4 tk)"]:
                        hien_luong_2_bao_cao_tong(cid)

                    elif text_in in ["/rasoat", "💰 rà soát ngân sách", "💰 rà soát chi tiêu (tháng/ngày)"]:
                        hien_luong_3_ra_soat_ngan_sach(cid)

                    elif text_in in ["/congno", "🏦 công nợ & cài đặt", "💳 công nợ & thẻ", "💳 kiểm tra công nợ & thẻ"]:
                        gui_hoac_sua_menu(cid, "⏳ Đang kiểm tra công nợ, ngưỡng và trạng thái thẻ...")
                        hien_luong_4_cong_no_va_cai_dat(cid)

                    elif text_in in ["/lich"]:
                        TRANG_THAI_LICH[cid] = {"start": None}
                        hien_bang_lich(cid, target="CUSTOM_HUB")

                    elif text_in in ["/homnay", "⚡ báo cáo hôm nay"]:
                        gui_hoac_sua_menu(cid, "⏳ Đang xuất báo cáo REALTIME HÔM NAY...")
                        chay_bao_cao_tu_dong("today", la_tu_dong_dinh_ky=False)
                        hien_luong_1_ds_tai_khoan(cid, tg_mac_dinh="today")

                    elif text_in in ["/homqua", "📅 báo cáo hôm qua"]:
                        gui_hoac_sua_menu(cid, "⏳ Đang xuất báo cáo HÔM QUA...")
                        chay_bao_cao_tu_dong("yesterday", la_tu_dong_dinh_ky=False)
                        hien_luong_1_ds_tai_khoan(cid, tg_mac_dinh="today")

                    else:
                        gui_ban_phim_co_dinh(cid)
                        hien_luong_1_ds_tai_khoan(cid, tg_mac_dinh="today")

                # 🔒 KHÓA BẢO MẬT PHẦN NÚT BẤM (CALLBACK QUERY)
                elif "callback_query" in update:
                    cb = update["callback_query"]
                    cid = cb["message"]["chat"]["id"]
                    if str(cid) != str(CHAT_ID):
                        continue

                    msg_id = cb["message"]["message_id"]
                    data = cb["data"].strip()
                    parts = data.split("|")
                    lenh = parts[0]

                    if lenh == "CAL_IGNORE":
                        requests.post(
                            f"https://api.telegram.org/bot{TELE_TOKEN}/answerCallbackQuery",
                            json={"callback_query_id": cb["id"]},
                        )
                        continue

                    if lenh == "SET_AI":
                        AI_UU_TIEN = parts[1]
                        ten_chon = "Gemini" if AI_UU_TIEN == "gemini" else "ChatGPT"
                        requests.post(
                            f"https://api.telegram.org/bot{TELE_TOKEN}/answerCallbackQuery",
                            json={"callback_query_id": cb["id"], "text": f"✅ Đã chọn ưu tiên {ten_chon}!"},
                        )
                        hien_luong_4_cong_no_va_cai_dat(cid, msg_id)
                        continue

                    if lenh == "REFRESH_ALL":
                        BO_NHO_BM.clear()
                        BO_NHO_TK.clear()
                        BO_NHO_AUDIT.clear()
                        requests.post(
                            f"https://api.telegram.org/bot{TELE_TOKEN}/answerCallbackQuery",
                            json={"callback_query_id": cb["id"], "text": "✅ Đã làm mới toàn bộ dữ liệu!"},
                        )
                        gui_ban_phim_co_dinh(cid, "✅ Đã làm mới bộ nhớ & Thanh điều hướng 4 luồng!")
                        hien_luong_1_ds_tai_khoan(cid, tg_mac_dinh="today")
                        continue

                    requests.post(
                        f"https://api.telegram.org/bot{TELE_TOKEN}/answerCallbackQuery",
                        json={"callback_query_id": cb["id"]},
                    )

                    # --- XỬ LÝ SỰ KIỆN BẢNG LỊCH 7 CỘT ---
                    if lenh == "CAL_OPEN":
                        target = parts[1]
                        TRANG_THAI_LICH[cid] = {"start": None}
                        hien_bang_lich(cid, msg_id, target=target)

                    elif lenh == "CAL_NAV":
                        target, nam, thang = parts[1], int(parts[2]), int(parts[3])
                        hien_bang_lich(cid, msg_id, target=target, nam=nam, thang=thang)

                    elif lenh == "CAL_RESET":
                        target, nam, thang = parts[1], int(parts[2]), int(parts[3])
                        TRANG_THAI_LICH[cid] = {"start": None}
                        hien_bang_lich(cid, msg_id, target=target, nam=nam, thang=thang)

                    elif lenh == "CAL_SINGLE":
                        target, ymd = parts[1], parts[2]
                        d_str = datetime.strptime(ymd, "%Y-%m-%d").strftime("%d/%m/%Y")
                        KY_TUY_CHINH = (ymd, ymd, f"Ngày {d_str}")
                        TRANG_THAI_LICH[cid] = {"start": None}
                        xu_ly_ket_qua_chon_lich(cid, msg_id, target)

                    elif lenh == "CAL_DAY":
                        target, ymd = parts[1], parts[2]
                        st = TRANG_THAI_LICH.get(cid, {})
                        ngay_1 = st.get("start")
                        if not ngay_1:
                            TRANG_THAI_LICH[cid] = {"start": ymd}
                            dt_chon = datetime.strptime(ymd, "%Y-%m-%d")
                            hien_bang_lich(cid, msg_id, target=target, nam=dt_chon.year, thang=dt_chon.month)
                        else:
                            dt1 = datetime.strptime(ngay_1, "%Y-%m-%d")
                            dt2 = datetime.strptime(ymd, "%Y-%m-%d")
                            if dt1 > dt2:
                                dt1, dt2 = dt2, dt1
                            s1, s2 = dt1.strftime("%Y-%m-%d"), dt2.strftime("%Y-%m-%d")
                            nhan = (
                                f"Ngày {dt1.strftime('%d/%m/%Y')}"
                                if s1 == s2
                                else f"{dt1.strftime('%d/%m/%Y')} - {dt2.strftime('%d/%m/%Y')}"
                            )
                            KY_TUY_CHINH = (s1, s2, nhan)
                            TRANG_THAI_LICH[cid] = {"start": None}
                            xu_ly_ket_qua_chon_lich(cid, msg_id, target)

                    # --- ĐIỀU HƯỚNG 4 LUỒNG CHÍNH ---
                    elif lenh in ["HOME", "MENU_ACCOUNTS"]:
                        hien_luong_1_ds_tai_khoan(cid, msg_id, tg_mac_dinh="today")

                    elif lenh == "MENU_REPORT":
                        hien_luong_2_bao_cao_tong(cid, msg_id)

                    elif lenh == "MENU_AUDIT":
                        hien_luong_3_ra_soat_ngan_sach(cid, msg_id)

                    elif lenh == "CHECK_BILLING":
                        hien_luong_4_cong_no_va_cai_dat(cid, msg_id)

                    elif lenh == "AUDIT":
                        che_do_audit = parts[1]
                        ten_ky_audit = lay_nhan_ky_du_lieu(che_do_audit)
                        gui_hoac_sua_menu(cid, f"⏳ Đang rà soát ngân sách [{ten_ky_audit}]...", None, msg_id)
                        if che_do_audit == "custom" and KY_TUY_CHINH:
                            bc_audit, nut_audit = rà_soat_chi_tieu_bm(
                                che_do="custom", since_date=KY_TUY_CHINH[0], until_date=KY_TUY_CHINH[1], nhan_hien_thi=ten_ky_audit
                            )
                        else:
                            bc_audit, nut_audit = rà_soat_chi_tieu_bm(che_do=che_do_audit, nhan_hien_thi=ten_ky_audit)
                        gui_hoac_sua_menu(cid, bc_audit, nut_audit, msg_id)

                    elif lenh == "AUDIT_TK":
                        tk_idx = parts[1]
                        van_ban_nhom, nut_nhom = tao_bang_chi_tiet_nhom_audit(tk_idx)
                        gui_hoac_sua_menu(cid, van_ban_nhom, nut_nhom, msg_id)

                    elif lenh == "AI_AUDIT":
                        tk_idx = parts[1]
                        chon_ai = parts[2] if len(parts) > 2 else None
                        if tk_idx not in BO_NHO_AUDIT:
                            hien_luong_3_ra_soat_ngan_sach(cid, msg_id)
                            continue
                        van_ban_nhom, _ = tao_bang_chi_tiet_nhom_audit(tk_idx)
                        ten_ai_chay = "ChatGPT" if (chon_ai or AI_UU_TIEN) == "chatgpt" else "Gemini"
                        gui_hoac_sua_menu(cid, van_ban_nhom + f"\n\n⏳ {ten_ai_chay} đang phân tích các Nhóm...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(
                            f"Rà soát Nhóm ({BO_NHO_AUDIT[tk_idx]['ten_tk']} - {BO_NHO_AUDIT[tk_idx]['nhan_hien_thi']})",
                            van_ban_nhom,
                            chon_ai=chon_ai,
                        )
                        gui_hoac_sua_menu(
                            cid,
                            van_ban_nhom + "\n\n" + nhan_xet,
                            [
                                [
                                    {"text": "✨ Gemini Soi Lại", "callback_data": f"AI_AUDIT|{tk_idx}|gemini"},
                                    {"text": "🤖 ChatGPT Soi Lại", "callback_data": f"AI_AUDIT|{tk_idx}|chatgpt"},
                                ],
                                [
                                    {"text": "⬅️ Menu Rà Soát", "callback_data": "MENU_AUDIT"},
                                    {"text": "💳 DS Tài Khoản", "callback_data": "MENU_ACCOUNTS"},
                                ],
                            ],
                            msg_id,
                        )

                    elif lenh == "QuickReport":
                        ky_bc = parts[1]
                        ten_ky_bc = lay_nhan_ky_du_lieu(ky_bc)
                        gui_hoac_sua_menu(cid, f"⏳ Đang xuất Báo Cáo Tổng [{ten_ky_bc}] cho cả 4 TK...", None, msg_id)
                        chay_bao_cao_tu_dong(ky_bc, la_tu_dong_dinh_ky=False)
                        hien_luong_1_ds_tai_khoan(cid, tg_mac_dinh=ky_bc)

                    elif lenh == "TK":
                        tk_idx, tg = parts[1], parts[2]
                        hien_man_hinh_tai_khoan(cid, tk_idx, tg, msg_id, can_tai_lai=True, bung_all_camp=False)

                    elif lenh == "EXPAND_C":
                        tk_idx = parts[1]
                        if tk_idx in BO_NHO_TK:
                            hien_man_hinh_tai_khoan(cid, tk_idx, BO_NHO_TK[tk_idx]["tg"], msg_id, can_tai_lai=False, bung_all_camp=True)
                        else:
                            hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id, can_tai_lai=True, bung_all_camp=True)

                    elif lenh == "BACK_TK":
                        tk_idx = parts[1]
                        if tk_idx in BO_NHO_TK:
                            hien_man_hinh_tai_khoan(cid, tk_idx, BO_NHO_TK[tk_idx]["tg"], msg_id, can_tai_lai=False, bung_all_camp=False)
                        else:
                            hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id, can_tai_lai=True, bung_all_camp=False)

                    elif lenh == "ALL_C":
                        tk_idx = parts[1]
                        chon_ai = parts[2] if len(parts) > 2 else None
                        if tk_idx not in BO_NHO_TK:
                            hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id, can_tai_lai=True)
                            continue
                        tk_cache = BO_NHO_TK[tk_idx]
                        bang_gon = tao_bang_gom_cum_text(
                            tk_cache["ten_tk"], tk_cache["data"]["cum_list"], tk_cache["data"]["tong_tien_tk"], chi_tiet_cho_ai=False
                        )
                        bang_ai = tao_bang_gom_cum_text(
                            tk_cache["ten_tk"], tk_cache["data"]["cum_list"], tk_cache["data"]["tong_tien_tk"], chi_tiet_cho_ai=True
                        )
                        ten_ai_chay = "ChatGPT" if (chon_ai or AI_UU_TIEN) == "chatgpt" else "Gemini"
                        gui_hoac_sua_menu(cid, bang_gon + f"\n\n⏳ {ten_ai_chay} đang bắt bệnh toàn bộ Cụm & Camp...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Tất cả Cụm & Camp ({tk_cache['ten_tk']})", bang_ai, chon_ai=chon_ai)
                        gui_hoac_sua_menu(
                            cid,
                            bang_gon + "\n\n" + nhan_xet,
                            [
                                [
                                    {"text": "✨ Hỏi Gemini", "callback_data": f"ALL_C|{tk_idx}|gemini"},
                                    {"text": "🤖 Hỏi ChatGPT", "callback_data": f"ALL_C|{tk_idx}|chatgpt"},
                                ],
                                [{"text": "⬅️ Quay lại Tài khoản", "callback_data": f"BACK_TK|{tk_idx}"}],
                            ],
                            msg_id,
                        )

                    elif lenh == "CUM":
                        tk_idx, cum_idx = parts[1], parts[2]
                        if tk_idx not in BO_NHO_TK:
                            hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id, can_tai_lai=True)
                            continue
                        tk_cache = BO_NHO_TK[tk_idx]
                        c_group = tk_cache["data"]["cum_list"][int(cum_idx)]
                        ten_cum = c_group["ten_cum"]
                        bang_cum = tao_bang_so_sanh_text(
                            f"CỤM [{ten_cum}] ({c_group['so_camp']} camp)",
                            c_group["ds_camps"],
                            c_group["chi_tieu"],
                            che_do_gon=True,
                        )
                        nut_cum = [[
                            {"text": "✨ Gemini Soi Cụm", "callback_data": f"AI_CUM|{tk_idx}|{cum_idx}|gemini"},
                            {"text": "🤖 ChatGPT Soi Cụm", "callback_data": f"AI_CUM|{tk_idx}|{cum_idx}|chatgpt"},
                        ]]
                        for c_info in c_group["ds_camps"]:
                            ten_c = c_info["ten"][:24]
                            tien_gon = dinh_dang_tien_gon(c_info["chi_tieu"])
                            nut_cum.append([{
                                "text": f"📂 {ten_c} ({tien_gon} • {c_info['tin_nhan']}m)",
                                "callback_data": f"C|{tk_idx}|{c_info['c_idx']}",
                            }])
                        nut_cum.append([
                            {"text": "⬅️ Về Tài khoản", "callback_data": f"BACK_TK|{tk_idx}"},
                            {"text": "💳 DS Tài Khoản", "callback_data": "MENU_ACCOUNTS"},
                        ])
                        gui_hoac_sua_menu(cid, bang_cum, nut_cum, msg_id)

                    elif lenh == "AI_CUM":
                        tk_idx, cum_idx = parts[1], parts[2]
                        chon_ai = parts[3] if len(parts) > 3 else None
                        if tk_idx not in BO_NHO_TK:
                            hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id, can_tai_lai=True)
                            continue
                        tk_cache = BO_NHO_TK[tk_idx]
                        c_group = tk_cache["data"]["cum_list"][int(cum_idx)]
                        ten_cum = c_group["ten_cum"]
                        bang_cum_gon = tao_bang_so_sanh_text(
                            f"CỤM [{ten_cum}]", c_group["ds_camps"], c_group["chi_tieu"], che_do_gon=True
                        )
                        bang_cum_ai = tao_bang_so_sanh_text(
                            f"CỤM [{ten_cum}]", c_group["ds_camps"], c_group["chi_tieu"], che_do_gon=False
                        )
                        ten_ai_chay = "ChatGPT" if (chon_ai or AI_UU_TIEN) == "chatgpt" else "Gemini"
                        gui_hoac_sua_menu(cid, bang_cum_gon + f"\n\n⏳ {ten_ai_chay} đang bắt bệnh cụm [{ten_cum}]...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Cụm [{ten_cum}] ({tk_cache['ten_tk']})", bang_cum_ai, chon_ai=chon_ai)
                        gui_hoac_sua_menu(
                            cid,
                            bang_cum_gon + "\n\n" + nhan_xet,
                            [
                                [
                                    {"text": "✨ Soi bằng Gemini", "callback_data": f"AI_CUM|{tk_idx}|{cum_idx}|gemini"},
                                    {"text": "🤖 Soi bằng ChatGPT", "callback_data": f"AI_CUM|{tk_idx}|{cum_idx}|chatgpt"},
                                ],
                                [
                                    {"text": f"⬅️ Về Cụm [{ten_cum}]", "callback_data": f"CUM|{tk_idx}|{cum_idx}"},
                                    {"text": "💳 Về Tài khoản", "callback_data": f"BACK_TK|{tk_idx}"},
                                ],
                            ],
                            msg_id,
                        )

                    elif lenh == "C":
                        tk_idx, c_idx = parts[1], parts[2]
                        if tk_idx not in BO_NHO_TK:
                            hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id, can_tai_lai=True)
                            continue
                        hien_man_hinh_camp(cid, tk_idx, c_idx, msg_id)

                    elif lenh == "AI_C":
                        tk_idx, c_idx = parts[1], parts[2]
                        chon_ai = parts[3] if len(parts) > 3 else None
                        if tk_idx not in BO_NHO_TK:
                            hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id, can_tai_lai=True)
                            continue
                        c_info = BO_NHO_TK[tk_idx]["data"]["camps_list"][int(c_idx)]
                        bang_group_gon = tao_bang_so_sanh_text(
                            f"NHÓM TRONG CAMP [{c_info['ten']}]", c_info["groups_list"], c_info["chi_tieu"], che_do_gon=True
                        )
                        bang_group_ai = tao_bang_so_sanh_text(
                            f"NHÓM TRONG CAMP [{c_info['ten']}]", c_info["groups_list"], c_info["chi_tieu"], che_do_gon=False
                        )
                        ten_ai_chay = "ChatGPT" if (chon_ai or AI_UU_TIEN) == "chatgpt" else "Gemini"
                        gui_hoac_sua_menu(cid, bang_group_gon + f"\n\n⏳ {ten_ai_chay} đang bắt bệnh Camp...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Camp {c_info['ten']}", bang_group_ai, chon_ai=chon_ai)
                        gui_hoac_sua_menu(
                            cid,
                            bang_group_gon + "\n\n" + nhan_xet,
                            [
                                [
                                    {"text": "✨ Soi bằng Gemini", "callback_data": f"AI_C|{tk_idx}|{c_idx}|gemini"},
                                    {"text": "🤖 Soi bằng ChatGPT", "callback_data": f"AI_C|{tk_idx}|{c_idx}|chatgpt"},
                                ],
                                [{"text": "⬅️ Quay lại Camp", "callback_data": f"C|{tk_idx}|{c_idx}"}],
                            ],
                            msg_id,
                        )

                    elif lenh == "G":
                        tk_idx, c_idx, g_idx = parts[1], parts[2], parts[3]
                        if tk_idx not in BO_NHO_TK:
                            hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id, can_tai_lai=True)
                            continue
                        hien_man_hinh_group(cid, tk_idx, c_idx, g_idx, msg_id)

                    elif lenh == "AI_G":
                        tk_idx, c_idx, g_idx = parts[1], parts[2], parts[3]
                        chon_ai = parts[4] if len(parts) > 4 else None
                        if tk_idx not in BO_NHO_TK:
                            hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id, can_tai_lai=True)
                            continue
                        c_info = BO_NHO_TK[tk_idx]["data"]["camps_list"][int(c_idx)]
                        g_info = c_info["groups_list"][int(g_idx)]
                        bang_ads_gon = tao_bang_so_sanh_text(
                            f"BÀI ADS TRONG NHÓM [{g_info['ten']}]", g_info["ads_list"], g_info["chi_tieu"], che_do_gon=True
                        )
                        bang_ads_ai = tao_bang_so_sanh_text(
                            f"BÀI ADS TRONG NHÓM [{g_info['ten']}]", g_info["ads_list"], g_info["chi_tieu"], che_do_gon=False
                        )
                        ten_ai_chay = "ChatGPT" if (chon_ai or AI_UU_TIEN) == "chatgpt" else "Gemini"
                        gui_hoac_sua_menu(cid, bang_ads_gon + f"\n\n⏳ {ten_ai_chay} đang bắt bệnh các Bài Ads...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Group {g_info['ten']}", bang_ads_ai, chon_ai=chon_ai)
                        gui_hoac_sua_menu(
                            cid,
                            bang_ads_gon + "\n\n" + nhan_xet,
                            [
                                [
                                    {"text": "✨ Soi bằng Gemini", "callback_data": f"AI_G|{tk_idx}|{c_idx}|{g_idx}|gemini"},
                                    {"text": "🤖 Soi bằng ChatGPT", "callback_data": f"AI_G|{tk_idx}|{c_idx}|{g_idx}|chatgpt"},
                                ],
                                [{"text": "⬅️ Quay lại Nhóm", "callback_data": f"G|{tk_idx}|{c_idx}|{g_idx}"}],
                            ],
                            msg_id,
                        )

                    elif lenh == "A":
                        tk_idx, c_idx, g_idx, a_idx = parts[1], parts[2], parts[3], parts[4]
                        chon_ai = parts[5] if len(parts) > 5 else None
                        if tk_idx not in BO_NHO_TK:
                            hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id, can_tai_lai=True)
                            continue
                        c_info = BO_NHO_TK[tk_idx]["data"]["camps_list"][int(c_idx)]
                        g_info = c_info["groups_list"][int(g_idx)]
                        a_info = g_info["ads_list"][int(a_idx)]
                        dong_vid_ad = (
                            f"\n• 🎬 Video: Hook (3s) {a_info['hook_rate']}% ({a_info['video_3s']} lượt) | Hold {a_info['hold_rate']}% ({a_info['thruplay']} lượt)"
                            if a_info.get("hook_rate", 0) > 0
                            else ""
                        )
                        chi_tiet_ad = (
                            f"📝 BÀI ADS: {a_info['ten']}\n"
                            f"• Camp: {c_info['ten']} | Nhóm: {g_info['ten']}\n"
                            f"• Tiêu: {a_info['chi_tieu']:,}đ ➔ {a_info['tin_nhan']} mess ({a_info['gia_mess']:,}đ/m) | {a_info['binh_luan']} cmt\n"
                            f"• Tệp: CPM {a_info['cpm']:,}đ | Freq {a_info['frequency']} | Reach {a_info['reach']:,}\n"
                            f"• Phễu: CTR {a_info['ctr']}% | CPC {a_info['cpc']:,}đ | CR {a_info['cr_click_to_mess']}%{dong_vid_ad}"
                        )
                        ten_ai_chay = "ChatGPT" if (chon_ai or AI_UU_TIEN) == "chatgpt" else "Gemini"
                        gui_hoac_sua_menu(cid, chi_tiet_ad + f"\n\n⏳ {ten_ai_chay} đang bắt bệnh Bài Ads...", None, msg_id)
                        nhan_xet_ad = gemini_danh_gia_chuyen_sau(f"Bài Ads {a_info['ten']}", chi_tiet_ad, chon_ai=chon_ai)
                        gui_hoac_sua_menu(
                            cid,
                            chi_tiet_ad + "\n\n" + nhan_xet_ad,
                            [
                                [
                                    {"text": "✨ Soi bằng Gemini", "callback_data": f"A|{tk_idx}|{c_idx}|{g_idx}|{a_idx}|gemini"},
                                    {"text": "🤖 Soi bằng ChatGPT", "callback_data": f"A|{tk_idx}|{c_idx}|{g_idx}|{a_idx}|chatgpt"},
                                ],
                                [{"text": "⬅️ Quay lại Nhóm", "callback_data": f"G|{tk_idx}|{c_idx}|{g_idx}"}],
                            ],
                            msg_id,
                        )

        except Exception as e:
            print("⚠️ Lỗi xử lý:", e)
            time.sleep(3)


# ==============================================================================
# 7. KHỞI ĐỘNG HỆ THỐNG
# ==============================================================================
if __name__ == "__main__":
    cai_dat_menu_lenh_telegram()
    event_name = os.environ.get("EVENT_NAME", "")
    che_do_input = (os.environ.get("CHE_DO_INPUT") or "menu").strip().lower()

    res_check = requests.get(f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates?timeout=2").json()
    updates = res_check.get("result", [])
    next_offset = updates[-1]["update_id"] + 1 if updates else 0

    if event_name == "workflow_dispatch":
        gui_ban_phim_co_dinh(CHAT_ID)
        if che_do_input == "yesterday":
            chay_bao_cao_tu_dong("yesterday", la_tu_dong_dinh_ky=False)
        elif che_do_input == "today":
            chay_bao_cao_tu_dong("today", la_tu_dong_dinh_ky=False)
        hien_luong_1_ds_tai_khoan(CHAT_ID, tg_mac_dinh="today")

    chay_vong_lap_truc_chien_247(next_offset)
