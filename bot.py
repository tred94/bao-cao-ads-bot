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


def day_du_lieu_len_google_sheet(tab_name, ngay_ymd, spend, mess, cmt):
    if not SHEET_WEBHOOK_URL:
        return
    thue = int(spend * (THUE_VAT_FB / 100.0))
    tong = spend + thue
    payload = {
        "tab_name": tab_name,
        "ngay": ngay_ymd,
        "spend": spend,
        "tax": thue,
        "total": tong,
        "mess": mess,
        "cmt": cmt
    }
    try:
        requests.post(SHEET_WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        print("⚠️ Lỗi đồng bộ Google Sheet:", e)


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
        if y1 < 100: y1 += 2000
        if y2 < 100: y2 += 2000
        try:
            dt1 = datetime(y1, int(m1), int(d1))
            dt2 = datetime(y2, int(m2), int(d2))
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
        huong_dan = f"✅ Đã chọn mốc đầu: {d_dep}\n👉 Bấm nút Xem ngay hoặc chạm tiếp ngày thứ 2."
    else:
        huong_dan = "👉 Chạm vào 1 ngày trên lịch để bắt đầu chọn."

    nut.append([{"text": "⬅️ Quay lại", "callback_data": "MENU_AUDIT"}])
    gui_hoac_sua_menu(cid, f"📅 BẢNG LỊCH CHỌN NGÀY\n━━━━━━━━━━━━━━━━━━━━\n{huong_dan}", nut, msg_id)


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
    resp = requests.get(url, params=params).json()
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
    r_camp = requests.get(url_camp, params={"fields": "id,name,effective_status", "limit": 500, "access_token": FB_TOKEN}).json()
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

    r_ins = requests.get(url_ins, params=params).json()
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
            "clicks": clicks, "impressions": impr, "reach": reach,
            "video_3s": v3s, "thruplay": thru,
            "hook_rate": round((v3s / impr) * 100, 1) if impr > 0 and v3s > 0 else 0,
            "hold_rate": round((thru / v3s) * 100, 1) if v3s > 0 and thru > 0 else 0,
            "ctr": round(float(row.get("ctr", 0)), 2), "cpc": int(float(row.get("cpc", 0))),
            "cpm": int(float(row.get("cpm", 0))), "frequency": round(float(row.get("frequency", 0)), 2),
            "cr_click_to_mess": round((mess / clicks) * 100, 1) if clicks > 0 else 0
        }

    camps_list = sorted(camps_raw.values(), key=lambda x: x["chi_tieu"], reverse=True)
    for c_info in camps_list:
        g_list = sorted(c_info["groups_raw"].values(), key=lambda x: x["chi_tieu"], reverse=True)
        for g_info in g_list:
            g_info["ads_list"] = sorted(g_info["ads_raw"].values(), key=lambda x: x["chi_tieu"], reverse=True)
        c_info["groups_list"] = g_list

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

        tong_chi_bm += spend
        tong_mess_bm += mess
        tong_cmt_bm += cmt

        if spend > 0:
            BO_NHO_AUDIT[tk_idx] = {"ten_tk": tk_info["ten"], "nhan_hien_thi": nhan_hien_thi, "data": du_lieu_tk}

        ds_ket_qua.append({
            "tk_idx": tk_idx, "ten": tk_info["ten"], "icon": tk_info["icon"],
            "spend": spend, "mess": mess, "cmt": cmt, "cum_list": du_lieu_tk["cum_list"]
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
        "━━━━━━━━━━━━━━━━━━━━"
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
                lines.append(f"   🔹 Cụm [{c_gr['ten_cum']}] ({c_gr['so_camp']}c): {dinh_dang_tien_gon(c_gr['chi_tieu'])} ➔ {c_gr['tin_nhan']}m ({dinh_dang_tien_gon(g_cum)})")

            hang_nut_tk.append({"text": f"📂 Nhóm: {rut_gon_ten_tk(item['ten'])}", "callback_data": f"AUDIT_TK|{item['tk_idx']}"})
            if len(hang_nut_tk) == 2:
                nut_xem_nhom.append(hang_nut_tk); hang_nut_tk = []
        else:
            lines.append(f"{idx}. {item['icon']} {item['ten']}: 0đ")
    if hang_nut_tk: nut_xem_nhom.append(hang_nut_tk)

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    nut_xem_nhom.append([
        {"text": "📊 Đẩy lên Google Sheet", "callback_data": f"SYNC_SHEET|{che_do}"},
        {"text": "📅 Bảng Lịch", "callback_data": "CAL_OPEN|AUDIT"}
    ])
    nut_xem_nhom.append([{"text": "💰 Đổi mốc Rà soát", "callback_data": "MENU_AUDIT"}])
    return "\n".join(lines), nut_xem_nhom


def tao_bang_chi_tiet_nhom_audit(tk_idx):
    if tk_idx not in BO_NHO_AUDIT:
        return "⚠️ Dữ liệu đã làm mới, vui lòng chọn lại mốc rà soát.", [[{"text": "⬅️ Quay lại", "callback_data": "MENU_AUDIT"}]]

    info = BO_NHO_AUDIT[tk_idx]
    ten_tk, nhan_tg, du_lieu = info["ten_tk"], info["nhan_hien_thi"], info["data"]
    tong_tien_tk = du_lieu["tong_tien_tk"]
    thue_tk = int(tong_tien_tk * (THUE_VAT_FB / 100.0))

    lines = [
        f"📂 CHI TIẾT NHÓM - {ten_tk}", f"📅 Kỳ: {nhan_tg}",
        f"💰 QC: {tong_tien_tk:,}đ + Thuế: {thue_tk:,}đ ➔ Tổng: {tong_tien_tk + thue_tk:,}đ",
        "━━━━━━━━━━━━━━━━━━━━"
    ]
    for c_idx, camp in enumerate(du_lieu["camps_list"], 1):
        lines.append(f"📌 {c_idx}. {camp['ten']} ({dinh_dang_tien_gon(camp['chi_tieu'])} • {camp['tin_nhan']}m)")
        for g_idx, grp in enumerate(camp["groups_list"], 1):
            gia_g = int(grp["chi_tieu"] / grp["tin_nhan"]) if grp["tin_nhan"] > 0 else 0
            lines.append(f"   ↳ 🟢 {grp['ten']}: {grp['chi_tieu']:,}đ ➔ {grp['tin_nhan']}m ({dinh_dang_tien_gon(gia_g)})")

    nut_bam = [
        [
            {"text": "✨ Gemini Bắt Bệnh", "callback_data": f"AI_AUDIT|{tk_idx}|gemini"},
            {"text": "🤖 ChatGPT Bắt Bệnh", "callback_data": f"AI_AUDIT|{tk_idx}|chatgpt"},
        ],
        [{"text": "⬅️ Menu Rà Soát", "callback_data": "MENU_AUDIT"}],
    ]
    return "\n".join(lines), nut_bam


def tinh_chi_so_phu(item):
    tien, mess, impr, reach, clicks = item["chi_tieu"], item["tin_nhan"], item.get("impressions", 0), item.get("reach", 0), item.get("clicks", 0)
    v3s, thru = item.get("video_3s", 0), item.get("thruplay", 0)
    return (
        round((clicks / impr) * 100, 2) if impr > 0 else 0,
        int((tien / impr) * 1000) if impr > 0 else 0,
        round(impr / reach, 2) if reach > 0 else 1.0,
        round((mess / clicks) * 100, 1) if clicks > 0 else 0,
        round((v3s / impr) * 100, 1) if impr > 0 and v3s > 0 else 0,
        round((thru / v3s) * 100, 1) if v3s > 0 and thru > 0 else 0
    )


def tao_bang_so_sanh_text(tieu_de, ds_items, tong_tien_cha, che_do_gon=True):
    ds_sap_xep = sorted(ds_items, key=lambda x: (x["tin_nhan"], x["chi_tieu"]), reverse=True)
    lines = [f"📊 {tieu_de}", "━━━━━━━━━━━━━━━━━━━━"]
    for idx, item in enumerate(ds_sap_xep, 1):
        tien, mess = item["chi_tieu"], item["tin_nhan"]
        gia = int(tien / mess) if mess > 0 else 0
        ctr, cpm, freq, cr_m, hook, hold = tinh_chi_so_phu(item)
        icon_dg = "🔴" if mess == 0 else ("🟢" if gia <= KPI_MESS else "🟡")
        kq_str = "0 mess (LỖ)" if mess == 0 else f"{mess} mess ({dinh_dang_tien_gon(gia)}/m)"
        lines.append(f"{idx}. {icon_dg} {item['ten']}\n   💵 {tien:,}đ ➔ 💬 {kq_str}\n   📈 CTR:{ctr}% | CR:{cr_m}% | CPM:{int(cpm/1000)}k")
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
        ds = [m.get("name", "") for m in res.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", []) and "gemini" in m.get("name", "")]
        if ds: return ds
    except Exception: pass
    return ["models/gemini-2.5-flash-lite", "models/gemini-2.0-flash"]


def goi_gemini_api(prompt_text):
    if not GEMINI_KEY: return None
    payload = {"contents": [{"parts": [{"text": prompt_text}]}], "generationConfig": {"temperature": 0.2}}
    for m in tim_model_gemini():
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/{m}:generateContent?key={GEMINI_KEY}", json=payload, timeout=20).json()
            if "candidates" in r:
                return f"✨ [Phân tích bởi Gemini]\n\n{r['candidates'][0]['content']['parts'][0]['text']}"
        except Exception: continue
    return None


def goi_openai_gpt(prompt_text):
    if not OPENAI_KEY: return None
    try:
        res = requests.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}, json={"model": "gpt-4o-mini", "messages": [{"role": "system", "content": "Bạn là Media Buyer."}, {"role": "user", "content": prompt_text}], "temperature": 0.2}, timeout=25).json()
        if "choices" in res:
            return f"🤖 [Phân tích bởi ChatGPT]\n\n{res['choices'][0]['message']['content']}"
    except Exception: pass
    return None


def gemini_danh_gia_chuyen_sau(tieu_de, du_lieu_text, chon_ai=None):
    prompt = f"Phân tích ngắn gọn dữ liệu Ads [{tieu_de}] (KPI: {KPI_MESS}đ/m):\n{du_lieu_text}\nTrình bày 3 mục: 🟢 Tốt, 🔴 Lỗi, 💡 Hành động ngay. Không dùng dấu sao."
    if (chon_ai or AI_UU_TIEN) == "chatgpt":
        return goi_openai_gpt(prompt) or goi_gemini_api(prompt) or "⚠️ Lỗi kết nối AI."
    return goi_gemini_api(prompt) or goi_openai_gpt(prompt) or "⚠️ Lỗi kết nối AI."


def gui_ban_phim_co_dinh(chat_id, loi_nhan="⌨️ Đã bật Menu 4 Luồng!"):
    requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": loi_nhan, "reply_markup": BAN_PHIM_CO_DINH})


def gui_hoac_sua_menu(chat_id, van_ban, nut_bam=None, msg_id=None):
    if msg_id and len(van_ban) <= 3800:
        r = requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/editMessageText", json={"chat_id": chat_id, "message_id": msg_id, "text": van_ban, "reply_markup": {"inline_keyboard": nut_bam} if nut_bam else None}).json()
        if r.get("ok"): return
    requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": van_ban, "reply_markup": {"inline_keyboard": nut_bam} if nut_bam else BAN_PHIM_CO_DINH})


def tao_khung_thoi_gian_chuan(prefix_cmd, tg_hien_tai=None, target_lich="AUDIT"):
    hang_1 = [{"text": f"✅{n}" if tg_hien_tai == m else n, "callback_data": f"{prefix_cmd}|{m}"} for m, n in [("today", "⚡H.Nay"), ("yesterday", "📅H.Qua"), ("last_3d", "3 Ngày"), ("last_7d", "7 Ngày")]]
    hang_2 = [{"text": f"✅{n}" if tg_hien_tai == m else n, "callback_data": f"{prefix_cmd}|{m}"} for m, n in [("this_month", "📆 Tháng này"), ("last_month", "⏪ Tháng trước"), ("last_30d", "30 Ngày")]]
    nhan_lich = f"✅ 📅 {KY_TUY_CHINH[2]}" if (tg_hien_tai == "custom" and KY_TUY_CHINH) else "📅 Mở Bảng Lịch Chọn Ngày"
    return [hang_1, hang_2, [{"text": nhan_lich, "callback_data": f"CAL_OPEN|{target_lich}"}]]


def hien_luong_1_ds_tai_khoan(cid, msg_id=None, tg_mac_dinh="today"):
    global BO_NHO_BM
    if not BO_NHO_BM: BO_NHO_BM = quet_danh_sach_tai_khoan()
    nut = []
    hang = []
    for idx, (tk_idx, tk_info) in enumerate(BO_NHO_BM.items(), 1):
        hang.append({"text": f"{tk_info['icon']} {idx}. {rut_gon_ten_tk(tk_info['ten'])}", "callback_data": f"TK|{tk_idx}|{tg_mac_dinh}"})
        if len(hang) == 2: nut.append(hang); hang = []
    if hang: nut.append(hang)
    ds = "\n".join([f"  {idx}. {tk['icon']} {tk['ten']}" for idx, tk in enumerate(BO_NHO_BM.values(), 1)])
    gui_hoac_sua_menu(cid, f"💳 DANH SÁCH TÀI KHOẢN\n━━━━━━━━━━━━━━━━━━━━\n{ds}\n━━━━━━━━━━━━━━━━━━━━\n👇 Chọn Tài khoản để soi chi tiết:", nut, msg_id)


def hien_luong_2_bao_cao_tong(cid, msg_id=None):
    gui_hoac_sua_menu(cid, "📊 BÁO CÁO TỔNG & AI BẮT BỆNH\n━━━━━━━━━━━━━━━━━━━━\nChọn khung thời gian:", tao_khung_thoi_gian_chuan("QuickReport", None, "REPORT"), msg_id)


def hien_luong_3_ra_soat_ngan_sach(cid, msg_id=None):
    gui_hoac_sua_menu(cid, "💰 RÀ SOÁT NGÂN SÁCH\n━━━━━━━━━━━━━━━━━━━━\nChọn khung thời gian:", tao_khung_thoi_gian_chuan("AUDIT", None, "AUDIT"), msg_id)


def hien_luong_4_cong_no_va_cai_dat(cid, msg_id=None):
    global BO_NHO_BM
    BO_NHO_BM = quet_danh_sach_tai_khoan()
    tong_no = sum(acc["balance"] for acc in BO_NHO_BM.values())
    thue = int(tong_no * (THUE_VAT_FB / 100.0))
    van_ban = f"🏦 CÔNG NỢ & THẺ\n━━━━━━━━━━━━━━━━━━━━\n💰 Tổng nợ: {tong_no:,}đ + VAT: {thue:,}đ ➔ Tổng: {tong_no + thue:,}đ"
    gui_hoac_sua_menu(cid, van_ban, [[{"text": "🔄 Làm mới", "callback_data": "REFRESH_ALL"}], [{"text": "🏠 Menu Chính", "callback_data": "HOME"}]], msg_id)


def hien_menu_chon_luong_cho_ngay_tuy_chinh(cid, msg_id=None):
    global BO_NHO_BM
    if not BO_NHO_BM: BO_NHO_BM = quet_danh_sach_tai_khoan()
    nhan_d = KY_TUY_CHINH[2] if KY_TUY_CHINH else "Ngày tùy chỉnh"
    nut = [
        [{"text": f"💰 1. Rà Soát ({nhan_d})", "callback_data": "AUDIT|custom"}],
        [{"text": f"📊 2. Báo Cáo Tổng ({nhan_d})", "callback_data": "QuickReport|custom"}]
    ]
    gui_hoac_sua_menu(cid, f"📅 KỲ ĐÃ CHỌN: {nhan_d}\n━━━━━━━━━━━━━━━━━━━━\nChọn luồng xem:", nut, msg_id)


def hien_man_hinh_tai_khoan(cid, tk_idx, tg="today", msg_id=None, can_tai_lai=True, bung_all_camp=False):
    global BO_NHO_BM
    if not BO_NHO_BM: BO_NHO_BM = quet_danh_sach_tai_khoan()
    tk_info = BO_NHO_BM[tk_idx]
    du_lieu = tai_du_lieu_5_tang(tk_info["id"], tg) if (can_tai_lai or tk_idx not in BO_NHO_TK) else BO_NHO_TK[tk_idx]["data"]
    BO_NHO_TK[tk_idx] = {"tk_idx": tk_idx, "ten_tk": tk_info["ten"], "tg": tg, "data": du_lieu}

    tong_t = du_lieu["tong_tien_tk"]
    thue = int(tong_t * (THUE_VAT_FB / 100.0))
    tom_tat = f"💳 {tk_info['ten']} ({lay_nhan_ky_du_lieu(tg)})\n💰 QC: {tong_t:,}đ + VAT: {thue:,}đ ➔ Tổng: {tong_t + thue:,}đ\n💬 {du_lieu['tong_mess_tk']}m\n\n{tao_bang_gom_cum_text(tk_info['ten'], du_lieu['cum_list'], tong_t)}"
    
    nut = tao_khung_thoi_gian_chuan(f"TK|{tk_idx}", tg, f"TK_{tk_idx}")
    if du_lieu["so_camp_co_tieu_tien"] > 0:
        hang_c = []
        for c_gr in du_lieu["cum_list"]:
            hang_c.append({"text": f"📦 {c_gr['ten_cum']} ({dinh_dang_tien_gon(c_gr['chi_tieu'])}•{c_gr['tin_nhan']}m)", "callback_data": f"CUM|{tk_idx}|{c_gr['cum_idx']}"})
            if len(hang_c) == 2: nut.append(hang_c); hang_c = []
        if hang_c: nut.append(hang_c)
    nut.append([{"text": "💳 Đổi Tài Khoản", "callback_data": "MENU_ACCOUNTS"}])
    gui_hoac_sua_menu(cid, tom_tat, nut, msg_id)


def chay_bao_cao_tu_dong(khoang_tg="today", la_tu_dong_dinh_ky=False, since_date=None, until_date=None, nhan_tuy_chinh=None):
    global BO_NHO_BM
    BO_NHO_BM = quet_danh_sach_tai_khoan()
    ymd_hom_qua = (lay_gio_viet_nam() - timedelta(days=1)).strftime("%Y-%m-%d")
    ymd_hom_nay = lay_gio_viet_nam().strftime("%Y-%m-%d")
    ngay_sync = ymd_hom_qua if (khoang_tg == "yesterday" or la_tu_dong_dinh_ky) else ymd_hom_nay

    for tk_idx, tk_info in BO_NHO_BM.items():
        du_lieu = tai_du_lieu_5_tang(tk_info["id"], khoang_tg, since_date, until_date)
        if du_lieu["tong_tien_tk"] > 0:
            # 1. Đẩy Tab Tổng cho tài khoản này
            day_du_lieu_len_google_sheet(rut_gon_ten_tk(tk_info["ten"]), ngay_sync, du_lieu["tong_tien_tk"], du_lieu["tong_mess_tk"], sum(c["binh_luan"] for c in du_lieu["camps_list"]))
            # 2. Đẩy từng Tab Cụm
            for c_gr in du_lieu["cum_list"]:
                day_du_lieu_len_google_sheet(f"{rut_gon_ten_tk(tk_info['ten'])}_{c_gr['ten_cum']}", ngay_sync, c_gr["chi_tieu"], c_gr["tin_nhan"], c_gr["binh_luan"])

    if not la_tu_dong_dinh_ky:
        gui_hoac_sua_menu(CHAT_ID, f"✅ Đã đồng bộ toàn bộ dữ liệu lên Google Sheet cho ngày {ngay_sync}!")


def da_bao_cao_xuyen_phien(ma_ngay_gio):
    if ma_ngay_gio in DA_BAO_CAO_TRONG_PHIEN: return True
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELE_TOKEN}/getMyShortDescription", timeout=5).json()
        if f"[DONE:{ma_ngay_gio}]" in r.get("result", {}).get("short_description", ""):
            DA_BAO_CAO_TRONG_PHIEN.add(ma_ngay_gio)
            return True
    except Exception: pass
    return False


def danh_dau_da_bao_cao_xuyen_phien(ma_ngay_gio):
    DA_BAO_CAO_TRONG_PHIEN.add(ma_ngay_gio)
    try:
        requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/setMyShortDescription", json={"short_description": f"Bot Ads [DONE:{ma_ngay_gio}]"}, timeout=5)
    except Exception: pass


def kiem_tra_den_gio_bao_cao_tu_dong():
    now_vn = lay_gio_viet_nam()
    ma_ngay_gio = now_vn.strftime("%Y-%m-%d_%H")
    if now_vn.hour == GIO_BAO_CAO_SANG and now_vn.minute <= 15:
        if not da_bao_cao_xuyen_phien(ma_ngay_gio):
            danh_dau_da_bao_cao_xuyen_phien(ma_ngay_gio)
            chay_bao_cao_tu_dong("yesterday", la_tu_dong_dinh_ky=True)


def xu_ly_ket_qua_chon_lich(cid, msg_id, target):
    since_d, until_d, nhan_d = KY_TUY_CHINH
    if target == "AUDIT":
        bc, nut = rà_soat_chi_tieu_bm("custom", since_d, until_d, nhan_d)
        gui_hoac_sua_menu(cid, bc, nut, msg_id)
    elif target == "REPORT":
        chay_bao_cao_tu_dong("custom", False, since_d, until_d, nhan_d)
        hien_luong_1_ds_tai_khoan(cid, tg_mac_dinh="custom")


def chay_vong_lap_truc_chien_247(offset_ban_dau=0):
    global KY_TUY_CHINH
    offset = offset_ban_dau
    thoi_diem_bat_dau = time.time()
    print("🟢 Bot đang trực chiến 24/7 (Tự động sync Google Sheet)...")

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
                    
                    if phan_tich_ngay_tuy_chinh(text_raw):
                        KY_TUY_CHINH = phan_tich_ngay_tuy_chinh(text_raw)
                        hien_menu_chon_luong_cho_ngay_tuy_chinh(cid)
                        continue

                    if text_raw.lower() in ["/menu", "💳 danh sách tài khoản", "🎛 bảng điều khiển"]: hien_luong_1_ds_tai_khoan(cid)
                    elif text_raw.lower() in ["/baocao", "📊 báo cáo tổng (4 tk)"]: hien_luong_2_bao_cao_tong(cid)
                    elif text_raw.lower() in ["/rasoat", "💰 rà soát ngân sách"]: hien_luong_3_ra_soat_ngan_sach(cid)
                    elif text_raw.lower() in ["/congno", "🏦 công nợ & cài đặt"]: hien_luong_4_cong_no_va_cai_dat(cid)
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

                    if lenh == "CAL_OPEN": hien_bang_lich(cid, msg_id, parts[1])
                    elif lenh == "CAL_NAV": hien_bang_lich(cid, msg_id, parts[1], int(parts[2]), int(parts[3]))
                    elif lenh == "CAL_SINGLE":
                        KY_TUY_CHINH = (parts[2], parts[2], f"Ngày {datetime.strptime(parts[2], '%Y-%m-%d').strftime('%d/%m/%Y')}")
                        xu_ly_ket_qua_chon_lich(cid, msg_id, parts[1])
                    elif lenh == "CAL_DAY":
                        st = TRANG_THAI_LICH.setdefault(cid, {})
                        if not st.get("start"):
                            st["start"] = parts[2]
                            dt = datetime.strptime(parts[2], "%Y-%m-%d")
                            hien_bang_lich(cid, msg_id, parts[1], dt.year, dt.month)
                        else:
                            dt1, dt2 = sorted([datetime.strptime(st["start"], "%Y-%m-%d"), datetime.strptime(parts[2], "%Y-%m-%d")])
                            KY_TUY_CHINH = (dt1.strftime("%Y-%m-%d"), dt2.strftime("%Y-%m-%d"), f"{dt1.strftime('%d/%m/%Y')} - {dt2.strftime('%d/%m/%Y')}")
                            st["start"] = None
                            xu_ly_ket_qua_chon_lich(cid, msg_id, parts[1])

                    elif lenh in ["HOME", "MENU_ACCOUNTS"]: hien_luong_1_ds_tai_khoan(cid, msg_id)
                    elif lenh == "MENU_REPORT": hien_luong_2_bao_cao_tong(cid, msg_id)
                    elif lenh == "MENU_AUDIT": hien_luong_3_ra_soat_ngan_sach(cid, msg_id)
                    elif lenh == "AUDIT":
                        bc, nut = rà_soat_chi_tieu_bm(parts[1], nhan_hien_thi=lay_nhan_ky_du_lieu(parts[1]))
                        gui_hoac_sua_menu(cid, bc, nut, msg_id)
                    elif lenh == "SYNC_SHEET":
                        chay_bao_cao_tu_dong(parts[1], la_tu_dong_dinh_ky=False)
                    elif lenh == "TK": hien_man_hinh_tai_khoan(cid, parts[1], parts[2], msg_id)
                    elif lenh == "CUM":
                        tk_cache = BO_NHO_TK[parts[1]]
                        c_group = tk_cache["data"]["cum_list"][int(parts[2])]
                        gui_hoac_sua_menu(cid, tao_bang_so_sanh_text(f"CỤM [{c_group['ten_cum']}]", c_group["ds_camps"], c_group["chi_tieu"]), [[{"text": "⬅️ Về Tài khoản", "callback_data": f"TK|{parts[1]}|{tk_cache['tg']}"}]], msg_id)

        except Exception as e:
            print("⚠️ Lỗi:", e)
            time.sleep(3)


if __name__ == "__main__":
    cai_dat_menu_lenh_telegram()
    if os.environ.get("EVENT_NAME") == "workflow_dispatch":
        gui_ban_phim_co_dinh(CHAT_ID)
        hien_luong_1_ds_tai_khoan(CHAT_ID)
    chay_vong_lap_truc_chien_247()
