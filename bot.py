import os
import re
import json
import time
import requests

# Lấy mã từ GitHub Secrets
FB_TOKEN = os.environ.get("FB_ACCESS_TOKEN", "").strip()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELE_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if TELE_TOKEN.startswith("bot"):
    TELE_TOKEN = TELE_TOKEN[3:]

CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "5657736528").strip()
KPI_MESS = int(os.environ.get("KPI_GIA_MESS", "60000"))
LOAI_KICH_HOAT = os.environ.get("LOAI_KICH_HOAT", "kiem_tra_nhanh")
THOI_GIAN_CHO_BAM_NUT = 600  # Tự động nghỉ sau 10 phút không thao tác

BO_NHO_BM = {}
BO_NHO_TK = {}

NHAN_THOI_GIAN = {
    "today": "Hôm nay",
    "yesterday": "Hôm qua",
    "last_3d": "3 ngày qua",
    "last_7d": "7 ngày qua",
}


# ==============================================================================
# 1. HÀM TỰ ĐỘNG TÁCH TÊN CỤM CHIẾN DỊCH (VD: HOÀNG, TRUST...)
# ==============================================================================
def tach_ten_cum(ten_camp):
    """Tự động nhận diện tiền tố nhóm chiến dịch (VD: 'Hoàng - Nám' -> 'HOÀNG', 'trus-triệt' -> 'TRUST')"""
    s = ten_camp.strip()
    # Bỏ số thứ tự đầu dòng nếu có (VD: "1. Hoàng - Nám" -> "Hoàng - Nám")
    s = re.sub(r"^\d+[\.\)\-\s]+", "", s).strip()

    # Tách theo dấu gạch ngang (-), dấu gạch đứng (|), dấu hai chấm (:) hoặc gạch chéo (/)
    parts = re.split(r"[\-\|\:\/–—]", s)
    if len(parts) > 1 and len(parts[0].strip()) >= 2:
        prefix = parts[0].strip().upper()
    else:
        words = s.split()
        prefix = words[0].upper() if words else "KHÁC"

    # Gom chung lỗi gõ tắt phổ biến (VD: TRUS -> TRUST)
    if prefix in ["TRUS", "TRUST"]:
        return "TRUST"
    return prefix[:15]


def gom_cum_chien_dich(camps_dict):
    """Gom các chiến dịch có cùng tên tiền tố vào chung 1 cụm để cộng tổng & đánh giá"""
    cum = {}
    for c_id, c_info in camps_dict.items():
        ten_cum = tach_ten_cum(c_info["ten"])
        if ten_cum not in cum:
            cum[ten_cum] = {
                "ten_cum": ten_cum,
                "so_camp": 0,
                "chi_tieu": 0,
                "tin_nhan": 0,
                "binh_luan": 0,
                "clicks": 0,
                "impressions": 0,
                "ds_camps": [],
            }
        g = cum[ten_cum]
        g["so_camp"] += 1
        g["chi_tieu"] += c_info["chi_tieu"]
        g["tin_nhan"] += c_info["tin_nhan"]
        g["binh_luan"] += c_info["binh_luan"]
        g["clicks"] += c_info["clicks"]
        g["impressions"] += c_info["impressions"]
        g["ds_camps"].append(c_info)
    return cum


# ==============================================================================
# 2. CÁC HÀM QUÉT DỮ LIỆU FACEBOOK 5 TẦNG
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


def quet_danh_sach_bm_va_tai_khoan():
    url = "https://graph.facebook.com/v21.0/me/adaccounts"
    params = {
        "fields": "id,name,account_status,business{id,name},amount_spent",
        "limit": 200,
        "access_token": FB_TOKEN,
    }
    resp = requests.get(url, params=params).json()
    if "error" in resp:
        params = {
            "fields": "id,name,account_status,amount_spent",
            "limit": 200,
            "access_token": FB_TOKEN,
        }
        resp = requests.get(url, params=params).json()
    if "error" in resp:
        raise Exception(f"Lỗi FB Token: {resp['error'].get('message')}")

    ds_bm = {}
    icon_map = {1: "🟢", 2: "🔴", 3: "🟡"}
    tt_map = {1: "Hoạt động", 2: "Vô hiệu hóa", 3: "Nợ"}

    for acc in resp.get("data", []):
        acc_id = acc.get("id")
        acc_name = acc.get("name") or acc_id
        st_code = acc.get("account_status", 1)
        icon_st = icon_map.get(st_code, "⚪")
        status_text = tt_map.get(st_code, "Khác")

        biz = acc.get("business")
        bm_id = f"bm_{biz['id']}" if (biz and biz.get("id")) else "bm_all"
        bm_name = (
            f"🏢 BM: {biz.get('name')}"
            if (biz and biz.get("id"))
            else "🏢 Danh sách Tài khoản Quảng cáo"
        )

        if bm_id not in ds_bm:
            ds_bm[bm_id] = {"ten_bm": bm_name, "tai_khoan": {}}
        tk_key = f"tk_{len(ds_bm[bm_id]['tai_khoan']) + 1}"
        ds_bm[bm_id]["tai_khoan"][tk_key] = {
            "id": acc_id,
            "ten": acc_name,
            "icon": icon_st,
            "trang_thai": status_text,
        }
    return ds_bm


def tai_du_lieu_5_tang(ma_tk, khoang_tg="last_7d"):
    url_camp = f"https://graph.facebook.com/v21.0/{ma_tk}/campaigns"
    r_camp = requests.get(
        url_camp,
        params={
            "fields": "id,name,effective_status",
            "limit": 500,
            "access_token": FB_TOKEN,
        },
    ).json()
    ds_camp_goc = r_camp.get("data", []) if "error" not in r_camp else []
    tong_so_camp = len(ds_camp_goc)
    so_camp_active = sum(
        1 for c in ds_camp_goc if c.get("effective_status") == "ACTIVE"
    )
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
    camps = {}
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

        tong_tien_tk += spend
        tong_mess_tk += mess

        if c_id not in camps:
            camps[c_id] = {
                "id": c_id,
                "ten": c_name,
                "trang_thai": trang_thai_camp.get(c_id, "🟢 Có tiêu tiền"),
                "chi_tieu": 0, "tin_nhan": 0, "binh_luan": 0,
                "clicks": 0, "impressions": 0, "groups": {},
            }
        c = camps[c_id]
        c["chi_tieu"] += spend; c["tin_nhan"] += mess; c["binh_luan"] += cmt
        c["clicks"] += clicks; c["impressions"] += impr

        if g_id not in c["groups"]:
            c["groups"][g_id] = {
                "id": g_id, "ten": g_name, "chi_tieu": 0, "tin_nhan": 0,
                "binh_luan": 0, "clicks": 0, "impressions": 0, "ads": {},
            }
        g = c["groups"][g_id]
        g["chi_tieu"] += spend; g["tin_nhan"] += mess; g["binh_luan"] += cmt
        g["clicks"] += clicks; g["impressions"] += impr

        g["ads"][a_id] = {
            "id": a_id, "ten": a_name, "chi_tieu": spend, "tin_nhan": mess,
            "gia_mess": int(spend / mess) if mess > 0 else 0, "binh_luan": cmt,
            "clicks": clicks, "impressions": impr, "reach": int(float(row.get("reach", 0))),
            "ctr": round(float(row.get("ctr", 0)), 2), "cpc": int(float(row.get("cpc", 0))),
            "cpm": int(float(row.get("cpm", 0))), "frequency": round(float(row.get("frequency", 0)), 2),
            "cr_click_to_mess": round((mess / clicks) * 100, 1) if clicks > 0 else 0,
        }

    # Tự động gom cụm các camp có tên giống nhau (Hoàng, Trust...)
    cum_camps = gom_cum_chien_dich(camps)

    return {
        "tong_so_camp": tong_so_camp,
        "so_camp_active": so_camp_active,
        "so_camp_co_tieu_tien": len(camps),
        "tong_tien_tk": tong_tien_tk,
        "tong_mess_tk": tong_mess_tk,
        "camps": camps,
        "cum_camps": cum_camps,
    }


# ==============================================================================
# 3. HÀM KẺ BẢNG SO SÁNH & GỌI GEMINI AI
# ==============================================================================
def tao_bang_so_sanh_text(tieu_de, ds_items, tong_tien_cha):
    ds_sap_xep = sorted(ds_items, key=lambda x: (x["tin_nhan"], x["chi_tieu"]), reverse=True)
    lines = [f"📊 BẢNG CHI TIẾT: {tieu_de}", "━━━━━━━━━━━━━━━━━━━━"]
    for idx, item in enumerate(ds_sap_xep, 1):
        tien, mess = item["chi_tieu"], item["tin_nhan"]
        gia = int(tien / mess) if mess > 0 else 0
        ty_trong = round((tien / tong_tien_cha) * 100, 1) if tong_tien_cha > 0 else 0
        danh_gia = (
            "🔴 LỖ (0 mess)"
            if mess == 0
            else (
                f"🟢 TỐT ({int(gia/1000)}k/mess)"
                if gia <= KPI_MESS
                else f"🟡 ĐẮT ({int(gia/1000)}k/mess)"
            )
        )
        ctr_str = (
            f"{item['ctr']}%"
            if "ctr" in item
            else (
                f"{round((item['clicks']/item['impressions'])*100, 2)}%"
                if item.get("impressions", 0) > 0
                else "0%"
            )
        )
        lines.append(
            f"{idx}. {item['ten']}\n"
            f"   ├ 💰 Tiêu: {tien:,}đ ({ty_trong}% ngân sách)\n"
            f"   ├ 💬 KQ: {mess} mess | {item.get('binh_luan', 0)} cmt | CTR: {ctr_str}\n"
            f"   └ 🎯 {danh_gia}"
        )
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def tao_bang_gom_cum_text(ten_tk, cum_camps_dict, tong_tien_tk):
    """Tạo bảng tổng hợp theo từng Cụm (VD: Cụm HOÀNG, Cụm TRUST) kèm các camp con bên trong"""
    lines = [f"📦 TỔNG HỢP THEO CỤM CHIẾN DỊCH ({ten_tk})", "━━━━━━━━━━━━━━━━━━━━"]
    cum_sorted = sorted(cum_camps_dict.values(), key=lambda x: x["chi_tieu"], reverse=True)

    for c_group in cum_sorted:
        ten_cum = c_group["ten_cum"]
        so_camp = c_group["so_camp"]
        tien = c_group["chi_tieu"]
        mess = c_group["tin_nhan"]
        gia_tb = int(tien / mess) if mess > 0 else 0
        ty_trong = round((tien / tong_tien_tk) * 100, 1) if tong_tien_tk > 0 else 0

        lines.append(
            f"🔷 CỤM [{ten_cum}] ({so_camp} camp): {tien:,}đ ({ty_trong}%) | {mess} mess | TB: {gia_tb:,}đ/mess"
        )
        for sub in sorted(c_group["ds_camps"], key=lambda x: x["chi_tieu"], reverse=True):
            sub_gia = int(sub["chi_tieu"] / sub["tin_nhan"]) if sub["tin_nhan"] > 0 else 0
            icon_dg = "🟢" if (sub["tin_nhan"] > 0 and sub_gia <= KPI_MESS) else ("🔴" if sub["tin_nhan"] == 0 else "🟡")
            lines.append(
                f"   • {sub['ten']}: {sub['chi_tieu']:,}đ | {sub['tin_nhan']} mess ({sub_gia:,}đ) {icon_dg}"
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


def gemini_danh_gia_chuyen_sau(tieu_de, du_lieu_text, la_1_bai_le=False):
    if la_1_bai_le:
        prompt = f"""
        Bạn là Giám đốc Tối ưu Quảng cáo Facebook (Senior Media Buyer).
        ĐÁNH GIÁ CHUYÊN SÂU 1 BÀI QUẢNG CÁO (Ad): [{tieu_de}] (KPI: {KPI_MESS:,}đ/mess).
        Thông số:
        {du_lieu_text}
        Hãy phân tích ngắn gọn, sắc bén:
        1. 📊 ĐÁNH GIÁ HIỆU SUẤT (Giá mess so với KPI, CTR, tỷ lệ Click-ra-Mess).
        2. 🔬 BẮT BỆNH KỸ THUẬT (Tần suất Frequency, CPM, điểm mạnh/yếu của nội dung hoặc kịch bản chat).
        3. ⚡ QUYẾT ĐỊNH HÀNH ĐỘNG (Giữ, tăng vốn, sửa nội dung hay tắt?).
        Không dùng dấu sao (*) hay dấu thăng (#).
        """
    else:
        prompt = f"""
        Bạn là Giám đốc Tối ưu Quảng cáo Facebook (Senior Media Buyer).
        ĐẶT LÊN BÀN CÂN SO SÁNH & ĐÁNH GIÁ CỤM [{tieu_de}] (KPI mục tiêu: {KPI_MESS:,}đ/mess):
        {du_lieu_text}
        Hãy phân tích sắc bén theo 3 mục:
        1. 🏆 ĐÁNH GIÁ TỔNG QUAN CỤM & XẾP HẠNG: Đánh giá hiệu quả chung của cụm này và chỉ rõ chiến dịch con nào đang gánh team, chiến dịch con nào đang kéo tụt hiệu suất.
        2. 🔬 BẮT BỆNH KỸ THUẬT: Giải thích nguyên nhân thắng/thua giữa các mục dựa trên CTR, tỷ trọng chi tiêu, lượng bình luận và tin nhắn.
        3. ⚡ PHÁC ĐỒ ĐIỀU CHỈNH VỐN NGAY: Đề xuất cụ thể tắt mục nào, dịch chuyển bao nhiêu % ngân sách từ mục nào sang mục nào.
        Không dùng dấu sao (*) hay dấu thăng (#).
        """
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3},
    }
    for m in tim_model_gemini():
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/{m}:generateContent?key={GEMINI_KEY}",
            json=payload,
        ).json()
        if "candidates" in r:
            return r["candidates"][0]["content"]["parts"][0]["text"]
    return "⚠️ Không kết nối được Gemini API."


# ==============================================================================
# 4. HÀM HIỂN THỊ MENU TRỰC TIẾP TRÊN 1 TIN NHẮN (SINGLE-PAGE UI)
# ==============================================================================
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
        if idx == len(cac_phan) - 1 and nut_bam:
            payload["reply_markup"] = {"inline_keyboard": nut_bam}
        requests.post(url, json=payload)


def hien_menu_chinh(cid, msg_id=None):
    global BO_NHO_BM
    if not BO_NHO_BM:
        BO_NHO_BM = quet_danh_sach_bm_va_tai_khoan()
    tong_bm = len(BO_NHO_BM)

    if tong_bm == 1 and "bm_all" in BO_NHO_BM:
        bm_key = "bm_all"
        ds_tk = BO_NHO_BM[bm_key]["tai_khoan"]
        nut_tk = []
        for idx, (tk_key, tk_info) in enumerate(ds_tk.items(), 1):
            nut_tk.append([{
                "text": f"{tk_info['icon']} {idx}. {tk_info['ten']}",
                "callback_data": f"TK|{bm_key}|{tk_key}|last_7d",
            }])

        van_ban = (
            f"🎛 TRUNG TÂM KIỂM TOÁN ADS ĐA TẦNG (BẢN MỚI)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔍 Đã kết nối {len(ds_tk)} Tài khoản Quảng cáo.\n"
            f"👇 Chạm vào Tài khoản bạn muốn kiểm tra (Mỗi tài khoản 1 hàng rõ tên 100%):"
        )
        gui_hoac_sua_menu(cid, van_ban, nut_tk, msg_id)
        return

    nut_bm = []
    for bm_key, bm_info in BO_NHO_BM.items():
        so_tk = len(bm_info["tai_khoan"])
        nut_bm.append([{
            "text": f"{bm_info['ten_bm']} ({so_tk} TK)",
            "callback_data": f"BM|{bm_key}",
        }])
    gui_hoac_sua_menu(
        cid,
        "🎛 TRUNG TÂM KIỂM TOÁN ADS 5 TẦNG\n👇 Chọn cụm BM bạn muốn kiểm tra:",
        nut_bm,
        msg_id,
    )


def hien_man_hinh_tai_khoan(cid, bm_key, tk_key, tg, msg_id=None, can_tai_lai=True):
    if not BO_NHO_BM:
        BO_NHO_BM.update(quet_danh_sach_bm_va_tai_khoan())
    tk_info = BO_NHO_BM[bm_key]["tai_khoan"][tk_key]
    ma_act = tk_info["id"]
    ten_tg = NHAN_THOI_GIAN.get(tg, tg)

    if can_tai_lai or ma_act not in BO_NHO_TK:
        gui_hoac_sua_menu(
            cid,
            f"⏳ Đang tải số liệu [{tk_info['ten']}]\n📅 Kỳ dữ liệu: {ten_tg}...",
            None,
            msg_id,
        )
        du_lieu_tk = tai_du_lieu_5_tang(ma_act, tg)
        BO_NHO_TK[ma_act] = {
            "bm_key": bm_key,
            "tk_key": tk_key,
            "ten_tk": tk_info["ten"],
            "tg": tg,
            "data": du_lieu_tk,
        }
    else:
        du_lieu_tk = BO_NHO_TK[ma_act]["data"]
        tg = BO_NHO_TK[ma_act]["tg"]
        ten_tg = NHAN_THOI_GIAN.get(tg, tg)

    tong_tien = du_lieu_tk["tong_tien_tk"]
    tong_mess = du_lieu_tk["tong_mess_tk"]
    gia_tb = int(tong_tien / tong_mess) if tong_mess > 0 else 0

    # Tóm tắt nhanh các cụm chiến dịch ngay trên màn hình Tài khoản
    cum_camps = du_lieu_tk.get("cum_camps", {})
    dong_cum = []
    for c_gr in sorted(cum_camps.values(), key=lambda x: x["chi_tieu"], reverse=True):
        g_tb = int(c_gr["chi_tieu"] / c_gr["tin_nhan"]) if c_gr["tin_nhan"] > 0 else 0
        dong_cum.append(
            f"• Cụm [{c_gr['ten_cum']}] ({c_gr['so_camp']} camp): {int(c_gr['chi_tieu']/1000):,}k | {c_gr['tin_nhan']} mess ({int(g_tb/1000)}k/mess)"
        )
    text_cum = "\n".join(dong_cum) if dong_cum else "• Chưa có chiến dịch tiêu tiền."

    tom_tat = (
        f"💳 TÀI KHOẢN: {tk_info['ten']}\n"
        f"📅 Kỳ dữ liệu: {ten_tg}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Tổng: {du_lieu_tk['tong_so_camp']} camp | 🟢 Active: {du_lieu_tk['so_camp_active']} | 🔥 Có tiêu tiền: {du_lieu_tk['so_camp_co_tieu_tien']}\n"
        f"💰 Tổng chi tiêu: {tong_tien:,}đ\n"
        f"💬 Tổng tin nhắn: {tong_mess} mess (TB: {gia_tb:,}đ/mess)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 TỔNG HỢP THEO CỤM TÊN CAMP:\n{text_cum}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 Đổi mốc thời gian, bấm Đánh giá theo Cụm (Hoàng/Trust...) hoặc chọn từng Camp:"
    )

    # 1. Hàng nút chọn nhanh mốc thời gian: Hôm nay | Hôm qua | 3 ngày | 7 ngày
    cac_moc = [("today", "Hôm nay"), ("yesterday", "Hôm qua"), ("last_3d", "3 ngày"), ("last_7d", "7 ngày")]
    hang_thoi_gian = []
    for ma_tg, nhan_ngan in cac_moc:
        hien_thi = f"✅ {nhan_ngan}" if tg == ma_tg else nhan_ngan
        hang_thoi_gian.append({
            "text": hien_thi,
            "callback_data": f"TK|{bm_key}|{tk_key}|{ma_tg}",
        })
    nut_camp = [hang_thoi_gian]

    if du_lieu_tk["so_camp_co_tieu_tien"] > 0:
        # 2. Nút đánh giá tổng thể tất cả các cụm & camp
        nut_camp.append([{
            "text": f"⚖️ AI ĐÁNH GIÁ TẤT CẢ CÁC CỤM & {du_lieu_tk['so_camp_co_tieu_tien']} CAMP",
            "callback_data": f"CMP_CAMP|{ma_act}",
        }])

        # 3. Các nút bấm đánh giá riêng từng Cụm (VD: Cụm HOÀNG, Cụm TRUST...)
        for c_gr in sorted(cum_camps.values(), key=lambda x: x["chi_tieu"], reverse=True):
            ten_cum = c_gr["ten_cum"]
            tien_k = int(c_gr["chi_tieu"] / 1000)
            nut_camp.append([{
                "text": f"📦 Cụm [{ten_cum}]: {c_gr['so_camp']} camp ({tien_k:,}k • {c_gr['tin_nhan']} mess)",
                "callback_data": f"CUM|{ma_act}|{ten_cum}",
            }])

        # 4. Danh sách từng Camp lẻ (nếu muốn bấm thẳng vào 1 camp)
        camps_sorted = sorted(
            du_lieu_tk["camps"].items(),
            key=lambda x: x[1]["chi_tieu"],
            reverse=True,
        )
        for idx, (c_id, c_info) in enumerate(camps_sorted, 1):
            ten_c = c_info["ten"][:28]
            tien_k = int(c_info["chi_tieu"] / 1000)
            nut_camp.append([{
                "text": f"📂 {idx}. {ten_c} ({tien_k:,}k • {c_info['tin_nhan']} mess)",
                "callback_data": f"CAMP|{ma_act}|{c_id}",
            }])

    nut_quay_lai = "HOME" if (len(BO_NHO_BM) == 1 and "bm_all" in BO_NHO_BM) else f"BM|{bm_key}"
    nut_camp.append([{"text": "⬅️ Đổi Tài khoản Quảng cáo khác", "callback_data": nut_quay_lai}])
    gui_hoac_sua_menu(cid, tom_tat, nut_camp, msg_id)


# ==============================================================================
# 5. CHẾ ĐỘ BÁO CÁO TỰ ĐỘNG & LẮNG NGHE TƯƠNG TÁC
# ==============================================================================
def chay_bao_cao_tu_dong():
    global BO_NHO_BM
    BO_NHO_BM = quet_danh_sach_bm_va_tai_khoan()
    for bm_info in BO_NHO_BM.values():
        for tk_info in bm_info["tai_khoan"].values():
            du_lieu = tai_du_lieu_5_tang(tk_info["id"], "last_7d")
            if du_lieu["so_camp_co_tieu_tien"] > 0:
                bang_cum = tao_bang_gom_cum_text(
                    f"{tk_info['ten']} (7 ngày qua)",
                    du_lieu["cum_camps"],
                    du_lieu["tong_tien_tk"],
                )
                nhan_xet = gemini_danh_gia_chuyen_sau(tk_info["ten"], bang_cum)
                mo_dau = (
                    f"☀️ BÁO CÁO TỰ ĐỘNG THEO CỤM: {tk_info['ten']}\n"
                    f"📌 Tổng Camp: {du_lieu['tong_so_camp']} | 🟢 Active: {du_lieu['so_camp_active']} | 🔥 Có tiêu tiền: {du_lieu['so_camp_co_tieu_tien']}\n"
                    f"💰 Tổng tiêu: {du_lieu['tong_tien_tk']:,}đ | 💬 {du_lieu['tong_mess_tk']} mess\n\n"
                )
                gui_hoac_sua_menu(CHAT_ID, mo_dau + bang_cum + "\n\n" + nhan_xet)


def lang_nghe_nut_bam_thong_minh(offset_ban_dau=0):
    offset = offset_ban_dau
    lan_tuong_tac_cuoi = time.time()
    print("🟢 Đang mở phiên tương tác Menu mới (Có gom cụm chiến dịch)...")

    while time.time() - lan_tuong_tac_cuoi < THOI_GIAN_CHO_BAM_NUT:
        try:
            url = f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates?offset={offset}&timeout=15"
            res = requests.get(url, timeout=20).json()

            for update in res.get("result", []):
                offset = update["update_id"] + 1
                lan_tuong_tac_cuoi = time.time()

                if "message" in update and "text" in update["message"]:
                    cid = update["message"]["chat"]["id"]
                    hien_menu_chinh(cid)

                elif "callback_query" in update:
                    cb = update["callback_query"]
                    cid = cb["message"]["chat"]["id"]
                    msg_id = cb["message"]["message_id"]
                    data = cb["data"]
                    requests.post(
                        f"https://api.telegram.org/bot{TELE_TOKEN}/answerCallbackQuery",
                        json={"callback_query_id": cb["id"]},
                    )

                    parts = data.split("|")
                    lenh = parts[0]

                    if lenh == "BM":
                        bm_key = parts[1]
                        if bm_key not in BO_NHO_BM:
                            hien_menu_chinh(cid, msg_id)
                            continue
                        bm_info = BO_NHO_BM[bm_key]
                        ds_tk = bm_info["tai_khoan"]
                        nut_tk = []
                        for idx, (tk_key, tk_info) in enumerate(ds_tk.items(), 1):
                            nut_tk.append([{
                                "text": f"{tk_info['icon']} {idx}. {tk_info['ten']}",
                                "callback_data": f"TK|{bm_key}|{tk_key}|last_7d",
                            }])
                        if len(BO_NHO_BM) > 1:
                            nut_tk.append([{"text": "⬅️ Quay lại chọn BM", "callback_data": "HOME"}])
                        gui_hoac_sua_menu(
                            cid,
                            f"{bm_info['ten_bm']}\n👇 Chạm vào Tài khoản bạn muốn kiểm tra:",
                            nut_tk,
                            msg_id,
                        )

                    elif lenh == "TK":
                        bm_key, tk_key, tg = parts[1], parts[2], parts[3]
                        hien_man_hinh_tai_khoan(cid, bm_key, tk_key, tg, msg_id, can_tai_lai=True)

                    elif lenh == "BACK_TK":
                        ma_act = parts[1]
                        tk_cache = BO_NHO_TK[ma_act]
                        hien_man_hinh_tai_khoan(
                            cid,
                            tk_cache["bm_key"],
                            tk_cache["tk_key"],
                            tk_cache["tg"],
                            msg_id,
                            can_tai_lai=False,
                        )

                    # --- XEM & ĐÁNH GIÁ RIÊNG 1 CỤM CHIẾN DỊCH (VD: CỤM HOÀNG, CỤM TRUST) ---
                    elif lenh == "CUM":
                        ma_act, ten_cum = parts[1], parts[2]
                        tk_cache = BO_NHO_TK[ma_act]
                        c_group = tk_cache["data"]["cum_camps"][ten_cum]
                        bang_cum_chi_tiet = tao_bang_so_sanh_text(
                            f"CỤM [{ten_cum}] ({c_group['so_camp']} camp)",
                            c_group["ds_camps"],
                            c_group["chi_tieu"],
                        )
                        gia_tb = int(c_group["chi_tieu"] / c_group["tin_nhan"]) if c_group["tin_nhan"] > 0 else 0
                        dau_trang = (
                            f"📦 CHI TIẾT CỤM CHIẾN DỊCH: [{ten_cum}]\n"
                            f"• Số lượng: {c_group['so_camp']} camp\n"
                            f"• Tổng tiêu cụm [{ten_cum}]: {c_group['chi_tieu']:,}đ\n"
                            f"• Tổng kết quả: {c_group['tin_nhan']} mess (TB: {gia_tb:,}đ/mess)\n\n"
                        )

                        nut_cum = [[{
                            "text": f"🤖 AI ĐÁNH GIÁ CHUYÊN SÂU CỤM [{ten_cum}]",
                            "callback_data": f"AI_CUM|{ma_act}|{ten_cum}",
                        }]]
                        for idx, c_info in enumerate(
                            sorted(c_group["ds_camps"], key=lambda x: x["chi_tieu"], reverse=True), 1
                        ):
                            nut_cum.append([{
                                "text": f"📂 Vào Camp: {c_info['ten'][:25]} ({int(c_info['chi_tieu']/1000):,}k • {c_info['tin_nhan']} mess)",
                                "callback_data": f"CAMP|{ma_act}|{c_info['id']}",
                            }])
                        nut_cum.append([{"text": "⬅️ Quay lại Tài khoản", "callback_data": f"BACK_TK|{ma_act}"}])
                        gui_hoac_sua_menu(cid, dau_trang + bang_cum_chi_tiet, nut_cum, msg_id)

                    elif lenh == "AI_CUM":
                        ma_act, ten_cum = parts[1], parts[2]
                        tk_cache = BO_NHO_TK[ma_act]
                        c_group = tk_cache["data"]["cum_camps"][ten_cum]
                        bang_cum_chi_tiet = tao_bang_so_sanh_text(
                            f"CỤM [{ten_cum}] ({c_group['so_camp']} camp)",
                            c_group["ds_camps"],
                            c_group["chi_tieu"],
                        )
                        gui_hoac_sua_menu(
                            cid,
                            bang_cum_chi_tiet + f"\n\n⏳ Gemini đang phân tích riêng cụm [{ten_cum}]...",
                            None,
                            msg_id,
                        )
                        nhan_xet = gemini_danh_gia_chuyen_sau(
                            f"Cụm chiến dịch [{ten_cum}] trong tài khoản {tk_cache['ten_tk']}",
                            bang_cum_chi_tiet,
                        )
                        gui_hoac_sua_menu(
                            cid,
                            bang_cum_chi_tiet + "\n\n" + nhan_xet,
                            [
                                [{"text": f"⬅️ Quay lại Cụm [{ten_cum}]", "callback_data": f"CUM|{ma_act}|{ten_cum}"}],
                                [{"text": "🏠 Về màn hình Tài khoản", "callback_data": f"BACK_TK|{ma_act}"}],
                            ],
                            msg_id,
                        )

                    elif lenh == "CMP_CAMP":
                        ma_act = parts[1]
                        tk_cache = BO_NHO_TK[ma_act]
                        bang_text = tao_bang_gom_cum_text(
                            tk_cache["ten_tk"],
                            tk_cache["data"]["cum_camps"],
                            tk_cache["data"]["tong_tien_tk"],
                        )
                        gui_hoac_sua_menu(
                            cid,
                            bang_text + "\n\n⏳ Gemini đang phân tích so sánh toàn bộ các Cụm & Camp...",
                            None,
                            msg_id,
                        )
                        nhan_xet = gemini_danh_gia_chuyen_sau(
                            f"Tất cả các Cụm & Chiến dịch trong {tk_cache['ten_tk']}", bang_text
                        )
                        gui_hoac_sua_menu(
                            cid,
                            bang_text + "\n\n" + nhan_xet,
                            [[{"text": "⬅️ Quay lại Tài khoản", "callback_data": f"BACK_TK|{ma_act}"}]],
                            msg_id,
                        )

                    elif lenh == "CAMP":
                        ma_act, c_id = parts[1], parts[2]
                        c_info = BO_NHO_TK[ma_act]["data"]["camps"][c_id]
                        so_group = len(c_info["groups"])
                        gia_tb = int(c_info["chi_tieu"] / c_info["tin_nhan"]) if c_info["tin_nhan"] > 0 else 0
                        tom_tat_c = (
                            f"📂 CHIẾN DỊCH: {c_info['ten']}\n"
                            f"• Trạng thái: {c_info['trang_thai']}\n"
                            f"• Số Nhóm (Group) có tiêu tiền: {so_group} nhóm\n"
                            f"• Chi tiêu: {c_info['chi_tieu']:,}đ | {c_info['tin_nhan']} mess ({gia_tb:,}đ/mess)\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"👇 Chạm để so sánh hoặc chọn từng Group bên dưới:"
                        )
                        nut_g = [[{
                            "text": f"🤖 AI ĐÁNH GIÁ CAMP & SO SÁNH {so_group} GROUP",
                            "callback_data": f"CMP_GROUP|{ma_act}|{c_id}",
                        }]]
                        groups_sorted = sorted(
                            c_info["groups"].items(),
                            key=lambda x: x[1]["chi_tieu"],
                            reverse=True,
                        )
                        for idx, (g_id, g_info) in enumerate(groups_sorted, 1):
                            ten_g = g_info["ten"][:28]
                            tien_k = int(g_info["chi_tieu"] / 1000)
                            nut_g.append([{
                                "text": f"📁 {idx}. {ten_g} ({tien_k:,}k • {g_info['tin_nhan']} mess)",
                                "callback_data": f"GROUP|{ma_act}|{c_id}|{g_id}",
                            }])
                        nut_g.append([{"text": "⬅️ Quay lại danh sách Camp", "callback_data": f"BACK_TK|{ma_act}"}])
                        gui_hoac_sua_menu(cid, tom_tat_c, nut_g, msg_id)

                    elif lenh == "CMP_GROUP":
                        ma_act, c_id = parts[1], parts[2]
                        c_info = BO_NHO_TK[ma_act]["data"]["camps"][c_id]
                        bang_text = tao_bang_so_sanh_text(
                            f"CÁC GROUP TRONG CAMP [{c_info['ten']}]",
                            list(c_info["groups"].values()),
                            c_info["chi_tieu"],
                        )
                        gui_hoac_sua_menu(
                            cid,
                            bang_text + "\n\n⏳ Gemini đang đánh giá Camp & các Group...",
                            None,
                            msg_id,
                        )
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Chiến dịch {c_info['ten']}", bang_text)
                        gui_hoac_sua_menu(
                            cid,
                            bang_text + "\n\n" + nhan_xet,
                            [[{"text": "⬅️ Quay lại Camp", "callback_data": f"CAMP|{ma_act}|{c_id}"}]],
                            msg_id,
                        )

                    elif lenh == "GROUP":
                        ma_act, c_id, g_id = parts[1], parts[2], parts[3]
                        g_info = BO_NHO_TK[ma_act]["data"]["camps"][c_id]["groups"][g_id]
                        ds_ads = list(g_info["ads"].values())
                        bang_text = tao_bang_so_sanh_text(
                            f"CÁC BÀI ADS TRONG GROUP [{g_info['ten']}]",
                            ds_ads,
                            g_info["chi_tieu"],
                        )
                        nut_a = [[{
                            "text": f"⚖️ AI SO SÁNH CẢ {len(ds_ads)} BÀI ADS TRONG NHÓM",
                            "callback_data": f"CMP_AD|{ma_act}|{c_id}|{g_id}",
                        }]]
                        ads_sorted = sorted(
                            g_info["ads"].items(),
                            key=lambda x: x[1]["chi_tieu"],
                            reverse=True,
                        )
                        for idx, (a_id, a_info) in enumerate(ads_sorted, 1):
                            ten_a = a_info["ten"][:28]
                            tien_k = int(a_info["chi_tieu"] / 1000)
                            nut_a.append([{
                                "text": f"📝 {idx}. {ten_a} ({tien_k:,}k • {a_info['tin_nhan']} mess)",
                                "callback_data": f"AD|{ma_act}|{c_id}|{g_id}|{a_id}",
                            }])
                        nut_a.append([{"text": "⬅️ Quay lại chọn Group", "callback_data": f"CAMP|{ma_act}|{c_id}"}])
                        gui_hoac_sua_menu(
                            cid,
                            bang_text + "\n👇 Chạm vào từng Bài Ads bên dưới để khám bệnh sâu:",
                            nut_a,
                            msg_id,
                        )

                    elif lenh == "CMP_AD":
                        ma_act, c_id, g_id = parts[1], parts[2], parts[3]
                        g_info = BO_NHO_TK[ma_act]["data"]["camps"][c_id]["groups"][g_id]
                        bang_text = tao_bang_so_sanh_text(
                            f"CÁC BÀI ADS TRONG GROUP [{g_info['ten']}]",
                            list(g_info["ads"].values()),
                            g_info["chi_tieu"],
                        )
                        gui_hoac_sua_menu(cid, "⏳ Gemini đang so sánh các Bài quảng cáo...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Nhóm {g_info['ten']}", bang_text)
                        gui_hoac_sua_menu(
                            cid,
                            bang_text + "\n\n" + nhan_xet,
                            [[{"text": "⬅️ Quay lại Group", "callback_data": f"GROUP|{ma_act}|{c_id}|{g_id}"}]],
                            msg_id,
                        )

                    elif lenh == "AD":
                        ma_act, c_id, g_id, a_id = parts[1], parts[2], parts[3], parts[4]
                        c_info = BO_NHO_TK[ma_act]["data"]["camps"][c_id]
                        g_info = c_info["groups"][g_id]
                        a_info = g_info["ads"][a_id]
                        chi_tiet_ad = (
                            f"📝 CHI TIẾT BÀI ADS: {a_info['ten']}\n"
                            f"• Camp: {c_info['ten']} | Group: {g_info['ten']}\n"
                            f"• Chi tiêu: {a_info['chi_tieu']:,}đ | Tin nhắn: {a_info['tin_nhan']} mess ({a_info['gia_mess']:,}đ/mess)\n"
                            f"• Bình luận: {a_info['binh_luan']} | Impressions: {a_info['impressions']:,} | Reach: {a_info['reach']:,}\n"
                            f"• Frequency: {a_info['frequency']} | CPM: {a_info['cpm']:,}đ\n"
                            f"• Clicks: {a_info['clicks']} | CTR: {a_info['ctr']}% | CPC: {a_info['cpc']:,}đ\n"
                            f"• Tỷ lệ Click-ra-Mess: {a_info['cr_click_to_mess']}%"
                        )
                        gui_hoac_sua_menu(
                            cid,
                            chi_tiet_ad + "\n\n⏳ Gemini đang khám bệnh riêng cho Bài Ads này...",
                            None,
                            msg_id,
                        )
                        nhan_xet_ad = gemini_danh_gia_chuyen_sau(
                            a_info["ten"], chi_tiet_ad, la_1_bai_le=True
                        )
                        gui_hoac_sua_menu(
                            cid,
                            chi_tiet_ad + "\n\n" + nhan_xet_ad,
                            [[{"text": "⬅️ Quay lại Group", "callback_data": f"GROUP|{ma_act}|{c_id}|{g_id}"}]],
                            msg_id,
                        )

                    elif lenh == "HOME":
                        hien_menu_chinh(cid, msg_id)

        except Exception as e:
            print("⚠️ Lỗi xử lý:", e)
            time.sleep(3)


if __name__ == "__main__":
    res_check = requests.get(f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates?timeout=2").json()
    updates = res_check.get("result", [])

    if LOAI_KICH_HOAT == "bao_cao_dinh_ky":
        chay_bao_cao_tu_dong()
        hien_menu_chinh(CHAT_ID)
        next_offset = updates[-1]["update_id"] + 1 if updates else 0
        lang_nghe_nut_bam_thong_minh(next_offset)
    else:
        if not updates:
            print("ℹ️ Không có lệnh mới từ Telegram -> Thoát ngay.")
        else:
            lang_nghe_nut_bam_thong_minh(updates[0]["update_id"])
