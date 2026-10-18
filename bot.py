import os
import re
import time
import requests
from datetime import datetime, timezone, timedelta

# ==============================================================================
# 🛠️ KHU VỰC CẤU HÌNH DỄ CHỈNH SỬA
# ==============================================================================
KPI_MESS = int(os.environ.get("KPI_GIA_MESS") or "60000")      # Mốc KPI giá mỗi tin nhắn (VNĐ)
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
DA_BAO_CAO_TRONG_PHIEN = set()

NHAN_THOI_GIAN = {
    "today": "Realtime Hôm nay",
    "yesterday": "Hôm qua",
    "last_3d": "3 ngày qua",
    "last_7d": "7 ngày qua",
}

# Bàn phím nút bấm cố định luôn nằm ở dưới đáy màn hình Telegram
BAN_PHIM_CO_DINH = {
    "keyboard": [
        [{"text": "🎛 Mở Bảng Điều Khiển"}, {"text": "⚡ Báo Cáo Realtime (Hôm nay)"}],
        [{"text": "📅 Báo Cáo Hôm Qua"}, {"text": "🔄 Làm Mới Dữ Liệu"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}


# ==============================================================================
# 0. ĐĂNG KÝ MENU LỆNH KHI GÕ DẤU "/" TRÊN TELEGRAM
# ==============================================================================
def cai_dat_menu_lenh_telegram():
    """Giúp khi bạn gõ dấu '/' trên Telegram sẽ hiện ngay danh sách nút lệnh"""
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/setMyCommands"
    commands = [
        {"command": "menu", "description": "🎛 Mở Bảng điều khiển (Check Realtime)"},
        {"command": "homnay", "description": "⚡ Xuất báo cáo Realtime Hôm nay"},
        {"command": "homqua", "description": "📅 Xuất báo cáo tổng kết Hôm qua"},
    ]
    try:
        requests.post(url, json={"commands": commands}, timeout=5)
    except Exception:
        pass


# ==============================================================================
# 1. TỰ ĐỘNG NHẬN DIỆN & GOM CỤM CHIẾN DỊCH (HOÀNG, TRUST...)
# ==============================================================================
def lay_gio_viet_nam():
    return datetime.now(timezone(timedelta(hours=7)))


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
        g["ds_camps"].append(c_info)

    ds_cum_sorted = sorted(cum_dict.values(), key=lambda x: x["chi_tieu"], reverse=True)
    for idx, item in enumerate(ds_cum_sorted):
        item["cum_idx"] = str(idx)
    return ds_cum_sorted


# ==============================================================================
# 2. QUÉT DỮ LIỆU FACEBOOK 5 TẦNG (MẶC ĐỊNH REALTIME = TODAY)
# ==============================================================================
def trich_xuat_ket_qua(actions_list):
    mess, cmt, lead = 0, 0, 0
    for item in actions_list or []:
        loai = item.get("action_type", "")
        val = int(float(item.get("value", 0)))
        if loai == "onsite_conversion.messaging_conversation_started_7d":
            mess = val
        elif loai == "comment":
            cmt = val
        elif loai in ["lead", "purchase", "onsite_conversion.lead_grouped"]:
            lead += val
    return mess, cmt, lead


def quet_danh_sach_tai_khoan():
    url = "https://graph.facebook.com/v21.0/me/adaccounts"
    params = {
        "fields": "id,name,account_status,amount_spent",
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
    icon_map = {1: "🟢", 2: "🔴", 3: "🟡"}
    for idx, acc in enumerate(resp.get("data", [])):
        tk_idx = str(idx)
        st_code = acc.get("account_status", 1)
        ds_tk[tk_idx] = {
            "tk_idx": tk_idx,
            "id": acc.get("id"),
            "ten": acc.get("name") or acc.get("id"),
            "icon": icon_map.get(st_code, "⚪"),
        }
    return ds_tk


def tai_du_lieu_5_tang(ma_tk, khoang_tg="today"):
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
        "date_preset": khoang_tg,
        "fields": "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,spend,reach,impressions,frequency,cpm,clicks,ctr,cpc,actions",
        "limit": 500,
        "access_token": FB_TOKEN,
    }
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
        mess, cmt, _ = trich_xuat_ket_qua(row.get("actions", []))
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
                "clicks": 0, "impressions": 0, "reach": 0, "groups_raw": {},
            }
        c = camps_raw[c_id]
        c["chi_tieu"] += spend; c["tin_nhan"] += mess; c["binh_luan"] += cmt
        c["clicks"] += clicks; c["impressions"] += impr; c["reach"] += reach

        if g_id not in c["groups_raw"]:
            c["groups_raw"][g_id] = {
                "id": g_id, "ten": g_name, "chi_tieu": 0, "tin_nhan": 0,
                "binh_luan": 0, "clicks": 0, "impressions": 0, "reach": 0, "ads_raw": {},
            }
        g = c["groups_raw"][g_id]
        g["chi_tieu"] += spend; g["tin_nhan"] += mess; g["binh_luan"] += cmt
        g["clicks"] += clicks; g["impressions"] += impr; g["reach"] += reach

        g["ads_raw"][a_id] = {
            "id": a_id, "ten": a_name, "chi_tieu": spend, "tin_nhan": mess,
            "gia_mess": int(spend / mess) if mess > 0 else 0, "binh_luan": cmt,
            "clicks": clicks, "impressions": impr, "reach": reach,
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
        "thoi_diem_cap_nhat": lay_gio_viet_nam().strftime("%H:%M:%S - %d/%m/%Y"),
    }


# ==============================================================================
# 3. KẺ BẢNG SỐ LIỆU & AI (GEMINI + CHATGPT) BẮT BỆNH NGẮN GỌN TRỌNG TÂM
# ==============================================================================
def tinh_chi_so_phu(item):
    tien = item["chi_tieu"]
    mess = item["tin_nhan"]
    impr = item.get("impressions", 0)
    reach = item.get("reach", 0)
    clicks = item.get("clicks", 0)

    ctr = item.get("ctr") if "ctr" in item else (round((clicks / impr) * 100, 2) if impr > 0 else 0)
    cpm = item.get("cpm") if "cpm" in item else (int((tien / impr) * 1000) if impr > 0 else 0)
    freq = item.get("frequency") if "frequency" in item else (round(impr / reach, 2) if reach > 0 else 1.0)
    cr_mess = item.get("cr_click_to_mess") if "cr_click_to_mess" in item else (round((mess / clicks) * 100, 1) if clicks > 0 else 0)
    return ctr, cpm, freq, cr_mess


def tao_bang_so_sanh_text(tieu_de, ds_items, tong_tien_cha):
    ds_sap_xep = sorted(ds_items, key=lambda x: (x["tin_nhan"], x["chi_tieu"]), reverse=True)
    lines = [f"📊 SỐ LIỆU: {tieu_de}", "━━━━━━━━━━━━━━━━━━━━"]
    for idx, item in enumerate(ds_sap_xep, 1):
        tien, mess = item["chi_tieu"], item["tin_nhan"]
        gia = int(tien / mess) if mess > 0 else 0
        ty_trong = round((tien / tong_tien_cha) * 100, 1) if tong_tien_cha > 0 else 0
        ctr, cpm, freq, cr_mess = tinh_chi_so_phu(item)

        danh_gia = (
            "🔴 LỖ (0 mess)"
            if mess == 0
            else (
                f"🟢 TỐT ({int(gia/1000)}k/mess)"
                if gia <= KPI_MESS
                else f"🟡 ĐẮT ({int(gia/1000)}k/mess)"
            )
        )
        lines.append(
            f"{idx}. {item['ten']} [{danh_gia}]\n"
            f"   • Tiêu: {tien:,}đ ({ty_trong}%) | KQ: {mess} mess | {item.get('binh_luan', 0)} cmt\n"
            f"   • Tệp: CPM {int(cpm/1000)}k, Lặp {freq} | Content: CTR {ctr}%, Click->Mess {cr_mess}%"
        )
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def tao_bang_gom_cum_text(ten_tk, cum_list, tong_tien_tk):
    lines = [f"📦 TỔNG HỢP THEO CỤM ({ten_tk})", "━━━━━━━━━━━━━━━━━━━━"]
    for c_group in cum_list:
        ten_cum = c_group["ten_cum"]
        so_camp = c_group["so_camp"]
        tien = c_group["chi_tieu"]
        mess = c_group["tin_nhan"]
        gia_tb = int(tien / mess) if mess > 0 else 0
        ty_trong = round((tien / tong_tien_tk) * 100, 1) if tong_tien_tk > 0 else 0

        lines.append(
            f"🔷 CỤM [{ten_cum}] ({so_camp} camp): {tien:,}đ ({ty_trong}%) | {mess} mess (TB: {gia_tb:,}đ/mess)"
        )
        for sub in sorted(c_group["ds_camps"], key=lambda x: x["chi_tieu"], reverse=True):
            sub_gia = int(sub["chi_tieu"] / sub["tin_nhan"]) if sub["tin_nhan"] > 0 else 0
            ctr, cpm, freq, cr_mess = tinh_chi_so_phu(sub)
            icon_dg = "🟢" if (sub["tin_nhan"] > 0 and sub_gia <= KPI_MESS) else ("🔴" if sub["tin_nhan"] == 0 else "🟡")
            lines.append(
                f"   • {sub['ten']}: {sub['chi_tieu']:,}đ | {sub['tin_nhan']} mess ({int(sub_gia/1000)}k) {icon_dg} [CPM:{int(cpm/1000)}k | Freq:{freq} | CTR:{ctr}% | CR:{cr_mess}%]"
            )
        lines.append("")
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
    """Hỗ trợ chọn trực tiếp AI ('gemini' hoặc 'chatgpt') hoặc chạy theo AI_UU_TIEN mặc định"""
    ai_muc_tieu = chon_ai if chon_ai else AI_UU_TIEN

    prompt = f"""
    Bạn là Giám đốc Tối ưu Quảng cáo Facebook (Senior Media Buyer).
    Đánh giá dữ liệu của [{tieu_de}] dưới đây (Mốc KPI mục tiêu: {KPI_MESS:,}đ/mess):

    {du_lieu_text}

    YÊU CẦU BẮT BUỘC:
    - Trả lời CỰC KỲ NGẮN GỌN, SÚC TÍCH, ĐI THẲNG VÀO TRỌNG TÂM.
    - Chẩn đoán nguyên nhân dựa trên chỉ số:
      + Do Nội dung (Content/Media): dựa vào CTR (cao >2% là thu hút, thấp <1.5% là nội dung/hình ảnh kém hấp dẫn).
      + Do Tệp khách hàng (Audience): dựa vào CPM (đắt hay rẻ) và Tần suất lặp Freq (cao >2.2 là tệp hẹp/bão hòa).
      + Do Kịch bản chốt/Độ lệch phễu: dựa vào tỷ lệ chuyển đổi Click->Mess (CR%).

    Trình bày đúng 3 mục:
    🟢 1. VÌ SAO TỐT (MỤC HIỆU QUẢ):
    - [Tên mục tốt]: Giá mess bao nhiêu.
    - Nguyên nhân: Chỉ rõ nhờ Nội dung (CTR cao...), Tệp khách (CPM...), hay Tỷ lệ chuyển đổi chat (CR%...).

    🔴 2. VÌ SAO CHƯA TỐT (MỤC ĐẮT / LỖ):
    - [Tên mục chưa tốt]: Giá mess bao nhiêu (hoặc tiêu bao nhiêu mà 0 mess).
    - Nguyên nhân: Chỉ rõ lỗi tại [NỘI DUNG] (CTR thấp), tại [TỆP KHÁCH] (CPM cao/Freq cao), hay tại [KỊCH BẢN CHAT] (Click nhiều nhưng CR% thấp).

    💡 3. ĐỀ XUẤT HÀNH ĐỘNG NGAY:
    - Tắt / Giảm vốn: Chỉ đích danh mục nào.
    - Tăng vốn: Chỉ đích danh mục nào.
    - Cách khắc phục: Sửa nội dung 3s đầu, mở rộng tệp hay sửa kịch bản tin nhắn.

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

    return "⚠️ Không kết nối được cả Gemini API và OpenAI API (Vui lòng kiểm tra lại Key trong GitHub Secrets)."


# ==============================================================================
# 4. HIỂN THỊ GIAO DIỆN ĐA TẦNG & BÀN PHÍM NÚT BẤM CỐ ĐỊNH
# ==============================================================================
def gui_ban_phim_co_dinh(chat_id, loi_nhan="⌨️ Đã bật thanh Menu nút bấm nhanh ở dưới đáy màn hình!"):
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


def hien_menu_chinh(cid, msg_id=None, tg_mac_dinh="today"):
    """MẶC ĐỊNH KHI BẠN CHỦ ĐỘNG BẤM CHECK -> LUÔN LẤY REALTIME HÔM NAY (today)"""
    global BO_NHO_BM
    if not BO_NHO_BM:
        BO_NHO_BM = quet_danh_sach_tai_khoan()

    gio_hien_tai = lay_gio_viet_nam().strftime("%H:%M - %d/%m/%Y")
    nhan_gemini = "✅ ✨ Ưu tiên Gemini" if AI_UU_TIEN == "gemini" else "✨ Ưu tiên Gemini"
    nhan_gpt = "✅ 🤖 Ưu tiên ChatGPT" if AI_UU_TIEN == "chatgpt" else "🤖 Ưu tiên ChatGPT"
    ten_ai_hien_tai = "Gemini (Google)" if AI_UU_TIEN == "gemini" else "ChatGPT (OpenAI)"

    nut_tk = [
        [
            {"text": "⚡ Báo Cáo Tất Cả (Realtime)", "callback_data": "QuickReport|today"},
            {"text": "📅 Báo Cáo Tất Cả (Hôm qua)", "callback_data": "QuickReport|yesterday"},
        ],
        [
            {"text": nhan_gemini, "callback_data": "SET_AI|gemini"},
            {"text": nhan_gpt, "callback_data": "SET_AI|chatgpt"},
        ],
    ]

    for idx, (tk_idx, tk_info) in enumerate(BO_NHO_BM.items(), 1):
        nut_tk.append([{
            "text": f"{tk_info['icon']} {idx}. {tk_info['ten']} (Xem Realtime)",
            "callback_data": f"TK|{tk_idx}|{tg_mac_dinh}",
        }])

    van_ban = (
        f"🎛 TRUNG TÂM KIỂM TOÁN ADS (REALTIME 24/7)\n"
        f"🕒 Thời điểm check: {gio_hien_tai}\n"
        f"🧠 AI mặc định đang chọn: {ten_ai_hien_tai}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 Đã kết nối {len(BO_NHO_BM)} Tài khoản Quảng cáo.\n"
        f"⚡ Mặc định khi bấm vào tài khoản sẽ lấy số liệu REALTIME HÔM NAY (từ 0h00 đến hiện tại).\n\n"
        f"👇 Chạm vào nút bên dưới để đổi AI hoặc kiểm tra tài khoản:"
    )
    gui_hoac_sua_menu(cid, van_ban, nut_tk, msg_id)


def hien_man_hinh_tai_khoan(cid, tk_idx, tg="today", msg_id=None, can_tai_lai=True):
    global BO_NHO_BM
    if not BO_NHO_BM:
        BO_NHO_BM = quet_danh_sach_tai_khoan()
    tk_info = BO_NHO_BM[tk_idx]
    ma_act = tk_info["id"]
    ten_tg = NHAN_THOI_GIAN.get(tg, tg)

    if can_tai_lai or tk_idx not in BO_NHO_TK:
        gui_hoac_sua_menu(
            cid,
            f"⏳ Đang quét dữ liệu Realtime [{tk_info['ten']}]\n📅 Kỳ dữ liệu: {ten_tg}...",
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
        ten_tg = NHAN_THOI_GIAN.get(tg, tg)

    tong_tien = du_lieu_tk["tong_tien_tk"]
    tong_mess = du_lieu_tk["tong_mess_tk"]
    gia_tb = int(tong_tien / tong_mess) if tong_mess > 0 else 0
    luc_cap_nhat = du_lieu_tk.get("thoi_diem_cap_nhat", lay_gio_viet_nam().strftime("%H:%M:%S"))

    cum_list = du_lieu_tk.get("cum_list", [])
    dong_cum = []
    for c_gr in cum_list:
        g_tb = int(c_gr["chi_tieu"] / c_gr["tin_nhan"]) if c_gr["tin_nhan"] > 0 else 0
        dong_cum.append(
            f"• Cụm [{c_gr['ten_cum']}] ({c_gr['so_camp']} camp): {int(c_gr['chi_tieu']/1000):,}k | {c_gr['tin_nhan']} mess ({int(g_tb/1000)}k/mess)"
        )
    text_cum = "\n".join(dong_cum) if dong_cum else "• Chưa có chiến dịch tiêu tiền trong kỳ này."

    tom_tat = (
        f"💳 TÀI KHOẢN: {tk_info['ten']}\n"
        f"📅 Kỳ dữ liệu: {ten_tg} (Cập nhật lúc: {luc_cap_nhat})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Tổng: {du_lieu_tk['tong_so_camp']} camp | 🟢 Active: {du_lieu_tk['so_camp_active']} | 🔥 Có tiêu tiền: {du_lieu_tk['so_camp_co_tieu_tien']}\n"
        f"💰 Tổng chi tiêu: {tong_tien:,}đ\n"
        f"💬 Tổng tin nhắn: {tong_mess} mess (TB: {gia_tb:,}đ/mess)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 TỔNG HỢP THEO CỤM TÊN CAMP:\n{text_cum}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 Đổi kỳ dữ liệu, chọn AI Đánh giá hoặc bấm vào từng Camp bên dưới:"
    )

    cac_moc = [("today", "⚡ Hôm nay"), ("yesterday", "Hôm qua"), ("last_3d", "3 ngày"), ("last_7d", "7 ngày")]
    hang_thoi_gian = []
    for ma_tg, nhan_ngan in cac_moc:
        hien_thi = f"✅ {nhan_ngan}" if tg == ma_tg else nhan_ngan
        hang_thoi_gian.append({
            "text": hien_thi,
            "callback_data": f"TK|{tk_idx}|{ma_tg}",
        })
    nut_camp = [hang_thoi_gian]

    nut_camp.append([{
        "text": f"🔄 Làm mới số liệu Realtime ({lay_gio_viet_nam().strftime('%H:%M')})",
        "callback_data": f"TK|{tk_idx}|{tg}",
    }])

    if du_lieu_tk["so_camp_co_tieu_tien"] > 0:
        # 2 lựa chọn AI ngay trên màn hình Tài khoản
        nut_camp.append([
            {"text": "✨ Gemini Đánh Giá Tất Cả", "callback_data": f"ALL_C|{tk_idx}|gemini"},
            {"text": "🤖 ChatGPT Đánh Giá Tất Cả", "callback_data": f"ALL_C|{tk_idx}|chatgpt"},
        ])

        for c_gr in cum_list:
            tien_k = int(c_gr["chi_tieu"] / 1000)
            nut_camp.append([{
                "text": f"📦 Cụm [{c_gr['ten_cum']}]: {c_gr['so_camp']} camp ({tien_k:,}k • {c_gr['tin_nhan']} mess)",
                "callback_data": f"CUM|{tk_idx}|{c_gr['cum_idx']}",
            }])

        for idx, c_info in enumerate(du_lieu_tk["camps_list"], 1):
            ten_c = c_info["ten"][:26]
            tien_k = int(c_info["chi_tieu"] / 1000)
            nut_camp.append([{
                "text": f"📂 {idx}. {ten_c} ({tien_k:,}k • {c_info['tin_nhan']} mess)",
                "callback_data": f"C|{tk_idx}|{c_info['c_idx']}",
            }])

    nut_camp.append([{"text": "⬅️ Đổi Tài khoản Quảng cáo khác", "callback_data": "HOME"}])
    gui_hoac_sua_menu(cid, tom_tat, nut_camp, msg_id)


def hien_man_hinh_camp(cid, tk_idx, c_idx, msg_id=None):
    tk_cache = BO_NHO_TK[tk_idx]
    c_info = tk_cache["data"]["camps_list"][int(c_idx)]
    groups_list = c_info["groups_list"]
    so_group = len(groups_list)
    gia_tb = int(c_info["chi_tieu"] / c_info["tin_nhan"]) if c_info["tin_nhan"] > 0 else 0

    bang_group = tao_bang_so_sanh_text(
        f"CÁC GROUP TRONG CAMP [{c_info['ten']}]",
        groups_list,
        c_info["chi_tieu"],
    )
    tom_tat_c = (
        f"📂 CHIẾN DỊCH: {c_info['ten']}\n"
        f"• Kỳ dữ liệu: {NHAN_THOI_GIAN.get(tk_cache['tg'], tk_cache['tg'])}\n"
        f"• Trạng thái: {c_info['trang_thai']} | Số Group: {so_group} nhóm\n"
        f"• Chi tiêu: {c_info['chi_tieu']:,}đ | KQ: {c_info['tin_nhan']} mess ({gia_tb:,}đ/mess)\n\n"
        f"{bang_group}\n"
        f"👇 Chọn Gemini hoặc ChatGPT bắt bệnh Camp này, hoặc chạm vào từng Group:"
    )

    nut_g = [[
        {"text": "✨ Gemini Bắt Bệnh Camp", "callback_data": f"AI_C|{tk_idx}|{c_idx}|gemini"},
        {"text": "🤖 ChatGPT Bắt Bệnh Camp", "callback_data": f"AI_C|{tk_idx}|{c_idx}|chatgpt"},
    ]]
    for idx, g_info in enumerate(groups_list, 1):
        ten_g = g_info["ten"][:26]
        tien_k = int(g_info["chi_tieu"] / 1000)
        nut_g.append([{
            "text": f"📁 Group {idx}: {ten_g} ({tien_k:,}k • {g_info['tin_nhan']} mess)",
            "callback_data": f"G|{tk_idx}|{c_idx}|{g_info['g_idx']}",
        }])
    nut_g.append([{"text": "⬅️ Quay lại danh sách Camp", "callback_data": f"BACK_TK|{tk_idx}"}])
    gui_hoac_sua_menu(cid, tom_tat_c, nut_g, msg_id)


def hien_man_hinh_group(cid, tk_idx, c_idx, g_idx, msg_id=None):
    c_info = BO_NHO_TK[tk_idx]["data"]["camps_list"][int(c_idx)]
    g_info = c_info["groups_list"][int(g_idx)]
    ads_list = g_info["ads_list"]

    bang_ads = tao_bang_so_sanh_text(
        f"CÁC BÀI ADS TRONG GROUP [{g_info['ten']}]",
        ads_list,
        g_info["chi_tieu"],
    )
    nut_a = [[
        {"text": "✨ Gemini Soi Group", "callback_data": f"AI_G|{tk_idx}|{c_idx}|{g_idx}|gemini"},
        {"text": "🤖 ChatGPT Soi Group", "callback_data": f"AI_G|{tk_idx}|{c_idx}|{g_idx}|chatgpt"},
    ]]
    for idx, a_info in enumerate(ads_list, 1):
        ten_a = a_info["ten"][:26]
        tien_k = int(a_info["chi_tieu"] / 1000)
        nut_a.append([{
            "text": f"📝 Bài {idx}: {ten_a} ({tien_k:,}k • {a_info['tin_nhan']} mess)",
            "callback_data": f"A|{tk_idx}|{c_idx}|{g_idx}|{a_info['a_idx']}",
        }])
    nut_a.append([{"text": "⬅️ Quay lại Chiến dịch (Camp)", "callback_data": f"C|{tk_idx}|{c_idx}"}])
    gui_hoac_sua_menu(
        cid,
        bang_ads + "\n👇 Chọn AI đánh giá cả Group hoặc chạm vào từng Bài Ads bên dưới:",
        nut_a,
        msg_id,
    )


# ==============================================================================
# 5. HÀM BÁO CÁO TỰ ĐỘNG: 8H SÁNG (HÔM QUA) & 20H TỐI / REALTIME (HÔM NAY)
# ==============================================================================
def chay_bao_cao_tu_dong(khoang_tg="today", la_tu_dong_dinh_ky=False):
    global BO_NHO_BM
    BO_NHO_BM = quet_danh_sach_tai_khoan()
    now_vn = lay_gio_viet_nam()
    gio_str = now_vn.strftime("%H:%M")
    ngay_hom_nay_str = now_vn.strftime("%d/%m/%Y")
    ngay_hom_qua_str = (now_vn - timedelta(days=1)).strftime("%d/%m/%Y")

    if khoang_tg == "yesterday":
        tieu_de_buoi = f"☀️ BÁO CÁO TỔNG KẾT NGÀY HÔM QUA ({ngay_hom_qua_str})"
        ten_ky = f"Hôm qua {ngay_hom_qua_str}"
    else:
        if la_tu_dong_dinh_ky:
            tieu_de_buoi = f"🌙 BÁO CÁO 20H TỐI — SỐ LIỆU HÔM NAY ({ngay_hom_nay_str})"
        else:
            tieu_de_buoi = f"⚡ BÁO CÁO REALTIME HÔM NAY (Tính đến {gio_str} - {ngay_hom_nay_str})"
        ten_ky = f"Realtime Hôm nay ({gio_str})"

    co_tk_tieu_tien = False
    for tk_idx, tk_info in BO_NHO_BM.items():
        du_lieu = tai_du_lieu_5_tang(tk_info["id"], khoang_tg)
        BO_NHO_TK[tk_idx] = {
            "tk_idx": tk_idx,
            "ten_tk": tk_info["ten"],
            "tg": khoang_tg,
            "data": du_lieu,
        }
        if du_lieu["so_camp_co_tieu_tien"] > 0:
            co_tk_tieu_tien = True
            bang_cum = tao_bang_gom_cum_text(
                f"{tk_info['ten']} ({ten_ky})",
                du_lieu["cum_list"],
                du_lieu["tong_tien_tk"],
            )
            nhan_xet = gemini_danh_gia_chuyen_sau(f"{tk_info['ten']} ({ten_ky})", bang_cum)
            gia_tb = int(du_lieu["tong_tien_tk"] / du_lieu["tong_mess_tk"]) if du_lieu["tong_mess_tk"] > 0 else 0
            mo_dau = (
                f"{tieu_de_buoi}\n"
                f"💳 Tài khoản: {tk_info['ten']}\n"
                f"📌 Tổng: {du_lieu['tong_so_camp']} camp | 🟢 Active: {du_lieu['so_camp_active']} | 🔥 Có tiêu tiền: {du_lieu['so_camp_co_tieu_tien']}\n"
                f"💰 Tổng tiêu: {du_lieu['tong_tien_tk']:,}đ | 💬 {du_lieu['tong_mess_tk']} mess (TB: {gia_tb:,}đ/mess)\n\n"
            )
            gui_hoac_sua_menu(CHAT_ID, mo_dau + bang_cum + "\n\n" + nhan_xet)

    if not co_tk_tieu_tien:
        gui_hoac_sua_menu(
            CHAT_ID,
            f"{tieu_de_buoi}\nℹ️ Chưa có tài khoản nào phát sinh chi tiêu trong kỳ [{ten_ky}].",
        )


def kiem_tra_den_gio_bao_cao_tu_dong():
    now_vn = lay_gio_viet_nam()
    ma_ngay_gio = now_vn.strftime("%Y-%m-%d_%H")

    # 8h00 sáng -> Tự động báo số liệu NGÀY HÔM QUA (yesterday)
    if now_vn.hour == GIO_BAO_CAO_SANG and now_vn.minute <= 15 and ma_ngay_gio not in DA_BAO_CAO_TRONG_PHIEN:
        DA_BAO_CAO_TRONG_PHIEN.add(ma_ngay_gio)
        chay_bao_cao_tu_dong("yesterday", la_tu_dong_dinh_ky=True)
        hien_menu_chinh(CHAT_ID, tg_mac_dinh="today")

    # 20h00 tối -> Tự động báo số liệu NGÀY HÔM NAY (today)
    elif now_vn.hour == GIO_BAO_CAO_TOI and now_vn.minute <= 15 and ma_ngay_gio not in DA_BAO_CAO_TRONG_PHIEN:
        DA_BAO_CAO_TRONG_PHIEN.add(ma_ngay_gio)
        chay_bao_cao_tu_dong("today", la_tu_dong_dinh_ky=True)
        hien_menu_chinh(CHAT_ID, tg_mac_dinh="today")


# ==============================================================================
# 6. VÒNG LẶP TRỰC CHIẾN 24/7
# ==============================================================================
def chay_vong_lap_truc_chien_247(offset_ban_dau=0):
    global AI_UU_TIEN
    offset = offset_ban_dau
    thoi_diem_bat_dau = time.time()
    print("🟢 Bot đang trực chiến 24/7 (Mặc định Check Realtime Hôm nay)...")

    while time.time() - thoi_diem_bat_dau < THOI_GIAN_DUY_TRI_PHIEN:
        try:
            kiem_tra_den_gio_bao_cao_tu_dong()

            url = f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates?offset={offset}&timeout=20"
            res = requests.get(url, timeout=25).json()

            for update in res.get("result", []):
                offset = update["update_id"] + 1

                if "message" in update and "text" in update["message"]:
                    cid = update["message"]["chat"]["id"]
                    
                    # 🔒 KHÓA BẢO MẬT: Chỉ cho phép đúng Chat ID của bạn được tương tác!
                    if str(cid) != str(CHAT_ID):
                        continue

                    text_in = update["message"]["text"].strip().lower()

                    if text_in in ["/homqua", "📅 báo cáo hôm qua"]:
                        gui_hoac_sua_menu(cid, "⏳ Đang tổng hợp báo cáo NGÀY HÔM QUA cho toàn bộ tài khoản...")
                        chay_bao_cao_tu_dong("yesterday", la_tu_dong_dinh_ky=False)
                        hien_menu_chinh(cid, tg_mac_dinh="today")

                    elif text_in in ["/homnay", "⚡ báo cáo realtime (hôm nay)"]:
                        gui_hoac_sua_menu(cid, "⏳ Đang quét báo cáo REALTIME HÔM NAY cho toàn bộ tài khoản...")
                        chay_bao_cao_tu_dong("today", la_tu_dong_dinh_ky=False)
                        hien_menu_chinh(cid, tg_mac_dinh="today")

                    elif text_in in ["🔄 làm mới dữ liệu"]:
                        BO_NHO_BM.clear()
                        BO_NHO_TK.clear()
                        gui_ban_phim_co_dinh(cid, "✅ Đã làm mới bộ nhớ! Đang tải lại số liệu Realtime...")
                        hien_menu_chinh(cid, tg_mac_dinh="today")

                    else:
                        gui_ban_phim_co_dinh(cid)
                        hien_menu_chinh(cid, tg_mac_dinh="today")

                elif "callback_query" in update:
        cb = update["callback_query"]
        cid = cb["message"]["chat"]["id"]
        
        # 🔒 KHÓA BẢO MẬT: Chặn tuyệt đối người lạ bấm nút
        if str(cid) != str(CHAT_ID):
            continue

        msg_id = cb["message"]["message_id"]
        data = cb["data"].strip()

                    parts = data.split("|")
                    lenh = parts[0]

                    # Đổi AI ưu tiên ngay trên bảng điều khiển chính
                    if lenh == "SET_AI":
                        AI_UU_TIEN = parts[1]
                        ten_chon = "Gemini" if AI_UU_TIEN == "gemini" else "ChatGPT"
                        requests.post(
                            f"https://api.telegram.org/bot{TELE_TOKEN}/answerCallbackQuery",
                            json={"callback_query_id": cb["id"], "text": f"✅ Đã chuyển ưu tiên sang {ten_chon}!"},
                        )
                        hien_menu_chinh(cid, msg_id, tg_mac_dinh="today")
                        continue

                    requests.post(
                        f"https://api.telegram.org/bot{TELE_TOKEN}/answerCallbackQuery",
                        json={"callback_query_id": cb["id"]},
                    )

                    if lenh == "HOME":
                        hien_menu_chinh(cid, msg_id, tg_mac_dinh="today")

                    elif lenh == "QuickReport":
                        ky_bc = parts[1]
                        gui_hoac_sua_menu(
                            cid,
                            f"⏳ Đang xuất báo cáo [{NHAN_THOI_GIAN.get(ky_bc, ky_bc)}] cho tất cả tài khoản...",
                            None,
                            msg_id,
                        )
                        chay_bao_cao_tu_dong(ky_bc, la_tu_dong_dinh_ky=False)
                        hien_menu_chinh(cid, tg_mac_dinh="today")

                    elif lenh == "TK":
                        tk_idx, tg = parts[1], parts[2]
                        hien_man_hinh_tai_khoan(cid, tk_idx, tg, msg_id, can_tai_lai=True)

                    elif lenh == "BACK_TK":
                        tk_idx = parts[1]
                        if tk_idx in BO_NHO_TK:
                            hien_man_hinh_tai_khoan(cid, tk_idx, BO_NHO_TK[tk_idx]["tg"], msg_id, can_tai_lai=False)
                        else:
                            hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id, can_tai_lai=True)

                    elif lenh == "ALL_C":
                        tk_idx = parts[1]
                        chon_ai = parts[2] if len(parts) > 2 else None
                        if tk_idx not in BO_NHO_TK:
                            hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id, can_tai_lai=True)
                            continue
                        tk_cache = BO_NHO_TK[tk_idx]
                        bang_text = tao_bang_gom_cum_text(
                            tk_cache["ten_tk"],
                            tk_cache["data"]["cum_list"],
                            tk_cache["data"]["tong_tien_tk"],
                        )
                        ten_ai_chay = "ChatGPT" if (chon_ai or AI_UU_TIEN) == "chatgpt" else "Gemini"
                        gui_hoac_sua_menu(cid, bang_text + f"\n\n⏳ {ten_ai_chay} đang bắt bệnh toàn bộ các Cụm & Camp...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Tất cả Cụm & Camp ({tk_cache['ten_tk']})", bang_text, chon_ai=chon_ai)
                        gui_hoac_sua_menu(
                            cid,
                            bang_text + "\n\n" + nhan_xet,
                            [
                                [
                                    {"text": "✨ Hỏi lại bằng Gemini", "callback_data": f"ALL_C|{tk_idx}|gemini"},
                                    {"text": "🤖 Hỏi lại bằng ChatGPT", "callback_data": f"ALL_C|{tk_idx}|chatgpt"},
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
                        )
                        nut_cum = [[
                            {"text": f"✨ Gemini Soi Cụm [{ten_cum}]", "callback_data": f"AI_CUM|{tk_idx}|{cum_idx}|gemini"},
                            {"text": f"🤖 ChatGPT Soi Cụm [{ten_cum}]", "callback_data": f"AI_CUM|{tk_idx}|{cum_idx}|chatgpt"},
                        ]]
                        for c_info in c_group["ds_camps"]:
                            ten_c = c_info["ten"][:25]
                            tien_k = int(c_info["chi_tieu"] / 1000)
                            nut_cum.append([{
                                "text": f"📂 Vào Camp: {ten_c} ({tien_k:,}k • {c_info['tin_nhan']} mess)",
                                "callback_data": f"C|{tk_idx}|{c_info['c_idx']}",
                            }])
                        nut_cum.append([{"text": "⬅️ Quay lại Tài khoản", "callback_data": f"BACK_TK|{tk_idx}"}])
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
                        bang_cum = tao_bang_so_sanh_text(
                            f"CỤM [{ten_cum}] ({c_group['so_camp']} camp)",
                            c_group["ds_camps"],
                            c_group["chi_tieu"],
                        )
                        ten_ai_chay = "ChatGPT" if (chon_ai or AI_UU_TIEN) == "chatgpt" else "Gemini"
                        gui_hoac_sua_menu(cid, bang_cum + f"\n\n⏳ {ten_ai_chay} đang bắt bệnh cụm [{ten_cum}]...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Cụm [{ten_cum}] ({tk_cache['ten_tk']})", bang_cum, chon_ai=chon_ai)
                        gui_hoac_sua_menu(
                            cid,
                            bang_cum + "\n\n" + nhan_xet,
                            [
                                [
                                    {"text": "✨ Soi bằng Gemini", "callback_data": f"AI_CUM|{tk_idx}|{cum_idx}|gemini"},
                                    {"text": "🤖 Soi bằng ChatGPT", "callback_data": f"AI_CUM|{tk_idx}|{cum_idx}|chatgpt"},
                                ],
                                [{"text": f"⬅️ Quay lại Cụm [{ten_cum}]", "callback_data": f"CUM|{tk_idx}|{cum_idx}"}],
                                [{"text": "🏠 Về màn hình Tài khoản", "callback_data": f"BACK_TK|{tk_idx}"}],
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
                        bang_group = tao_bang_so_sanh_text(
                            f"CÁC GROUP TRONG CAMP [{c_info['ten']}]",
                            c_info["groups_list"],
                            c_info["chi_tieu"],
                        )
                        ten_ai_chay = "ChatGPT" if (chon_ai or AI_UU_TIEN) == "chatgpt" else "Gemini"
                        gui_hoac_sua_menu(cid, bang_group + f"\n\n⏳ {ten_ai_chay} đang bắt bệnh Camp & các Group...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Camp {c_info['ten']}", bang_group, chon_ai=chon_ai)
                        gui_hoac_sua_menu(
                            cid,
                            bang_group + "\n\n" + nhan_xet,
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
                        bang_ads = tao_bang_so_sanh_text(
                            f"CÁC BÀI ADS TRONG GROUP [{g_info['ten']}]",
                            g_info["ads_list"],
                            g_info["chi_tieu"],
                        )
                        ten_ai_chay = "ChatGPT" if (chon_ai or AI_UU_TIEN) == "chatgpt" else "Gemini"
                        gui_hoac_sua_menu(cid, bang_ads + f"\n\n⏳ {ten_ai_chay} đang bắt bệnh các Bài Ads...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Group {g_info['ten']}", bang_ads, chon_ai=chon_ai)
                        gui_hoac_sua_menu(
                            cid,
                            bang_ads + "\n\n" + nhan_xet,
                            [
                                [
                                    {"text": "✨ Soi bằng Gemini", "callback_data": f"AI_G|{tk_idx}|{c_idx}|{g_idx}|gemini"},
                                    {"text": "🤖 Soi bằng ChatGPT", "callback_data": f"AI_G|{tk_idx}|{c_idx}|{g_idx}|chatgpt"},
                                ],
                                [{"text": "⬅️ Quay lại Group", "callback_data": f"G|{tk_idx}|{c_idx}|{g_idx}"}],
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
                        chi_tiet_ad = (
                            f"📝 BÀI ADS: {a_info['ten']}\n"
                            f"• Thuộc Camp: {c_info['ten']} | Group: {g_info['ten']}\n"
                            f"• Chi tiêu: {a_info['chi_tieu']:,}đ | KQ: {a_info['tin_nhan']} mess ({a_info['gia_mess']:,}đ/mess) | {a_info['binh_luan']} cmt\n"
                            f"• Tệp khách: CPM {a_info['cpm']:,}đ | Lặp (Freq) {a_info['frequency']} | Reach {a_info['reach']:,}\n"
                            f"• Nội dung & Phễu: CTR {a_info['ctr']}% | CPC {a_info['cpc']:,}đ | Click->Mess {a_info['cr_click_to_mess']}%"
                        )
                        ten_ai_chay = "ChatGPT" if (chon_ai or AI_UU_TIEN) == "chatgpt" else "Gemini"
                        gui_hoac_sua_menu(cid, chi_tiet_ad + f"\n\n⏳ {ten_ai_chay} đang bắt bệnh riêng cho Bài Ads này...", None, msg_id)
                        nhan_xet_ad = gemini_danh_gia_chuyen_sau(f"Bài Ads {a_info['ten']}", chi_tiet_ad, chon_ai=chon_ai)
                        gui_hoac_sua_menu(
                            cid,
                            chi_tiet_ad + "\n\n" + nhan_xet_ad,
                            [
                                [
                                    {"text": "✨ Soi bằng Gemini", "callback_data": f"A|{tk_idx}|{c_idx}|{g_idx}|{a_idx}|gemini"},
                                    {"text": "🤖 Soi bằng ChatGPT", "callback_data": f"A|{tk_idx}|{c_idx}|{g_idx}|{a_idx}|chatgpt"},
                                ],
                                [{"text": "⬅️ Quay lại Group", "callback_data": f"G|{tk_idx}|{c_idx}|{g_idx}"}],
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
        hien_menu_chinh(CHAT_ID, tg_mac_dinh="today")

    chay_vong_lap_truc_chien_247(next_offset)
