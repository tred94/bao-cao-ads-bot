import os
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
# Thời gian tự động tắt nếu không bấm nút (mặc định 10 phút = 600 giây)
THOI_GIAN_CHO_BAM_NUT = 600

BO_NHO_BM = {}
BO_NHO_TK = {}


# ==============================================================================
# 1. CÁC HÀM QUÉT DỮ LIỆU FACEBOOK 5 TẦNG (BM -> TK -> CAMP -> GROUP -> ADS)
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
    tt_map = {1: "🟢 Hoạt động", 2: "🔴 Vô hiệu hóa", 3: "🟡 Nợ"}
    for acc in resp.get("data", []):
        acc_id = acc.get("id")
        acc_name = acc.get("name") or acc_id
        status_text = tt_map.get(acc.get("account_status", 1), "⚪ Khác")
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
    return {
        "tong_so_camp": tong_so_camp,
        "so_camp_active": so_camp_active,
        "so_camp_co_tieu_tien": len(camps),
        "tong_tien_tk": tong_tien_tk,
        "tong_mess_tk": tong_mess_tk,
        "camps": camps,
    }


# ==============================================================================
# 2. HÀM KẺ BẢNG SO SÁNH & GỌI GEMINI AI
# ==============================================================================
def tao_bang_so_sanh_text(tieu_de, ds_items, tong_tien_cha):
    ds_sap_xep = sorted(ds_items, key=lambda x: (x["tin_nhan"], x["chi_tieu"]), reverse=True)
    lines = [f"📊 BẢNG SO SÁNH: {tieu_de}", "━━━━━━━━━━━━━━━━━━━━"]
    for idx, item in enumerate(ds_sap_xep, 1):
        tien, mess = item["chi_tieu"], item["tin_nhan"]
        gia = int(tien / mess) if mess > 0 else 0
        ty_trong = round((tien / tong_tien_cha) * 100, 1) if tong_tien_cha > 0 else 0
        danh_gia = "🔴 LỖ (0 mess)" if mess == 0 else (f"🟢 TỐT ({int(gia/1000)}k/mess)" if gia <= KPI_MESS else f"🟡 ĐẮT ({int(gia/1000)}k/mess)")
        ctr_str = f"{item['ctr']}%" if "ctr" in item else (f"{round((item['clicks']/item['impressions'])*100, 2)}%" if item.get("impressions", 0) > 0 else "0%")
        lines.append(
            f"{idx}. {item['ten']}\n"
            f"   ├ 💰 Tiêu: {tien:,}đ ({ty_trong}% ngân sách)\n"
            f"   ├ 💬 KQ: {mess} mess | {item.get('binh_luan', 0)} cmt | CTR: {ctr_str}\n"
            f"   └ 🎯 {danh_gia}"
        )
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def tim_model_gemini():
    try:
        res = requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_KEY}", timeout=10).json()
        ds = [
            m.get("name", "") for m in res.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
            and "gemini" in m.get("name", "")
            and not any(k in m.get("name", "") for k in ["tts", "image", "audio", "embedding", "vision", "veo"])
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
        ĐẶT LÊN BÀN CÂN SO SÁNH các mục trong [{tieu_de}] (KPI: {KPI_MESS:,}đ/mess):
        {du_lieu_text}
        Trả lời sắc bén theo 3 mục:
        1. 🏆 XẾP HẠNG & SO SÁNH: Mục nào gánh team tốt nhất và mục nào đang đốt tiền.
        2. 🔬 BẮT BỆNH KỸ THUẬT: Giải thích nguyên nhân thắng/thua dựa trên CTR, tỷ trọng tiền, bình luận/tin nhắn.
        3. ⚡ PHÁC ĐỒ ĐIỀU CHỈNH VỐN NGAY: Đề xuất cụ thể tắt mục nào, tăng/giảm bao nhiêu % ngân sách.
        Không dùng dấu sao (*) hay dấu thăng (#).
        """
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.3}}
    for m in tim_model_gemini():
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/{m}:generateContent?key={GEMINI_KEY}", json=payload).json()
        if "candidates" in r:
            return r["candidates"][0]["content"]["parts"][0]["text"]
    return "⚠️ Không kết nối được Gemini API."


def gui_telegram(chat_id, van_ban, nut_bam=None):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    cac_dong = van_ban.split("\n")
    doan, cac_phan = "", []
    for dong in cac_dong:
        if len(doan) + len(dong) + 1 > 3800:
            cac_phan.append(doan); doan = dong + "\n"
        else:
            doan += dong + "\n"
    if doan.strip():
        cac_phan.append(doan)
    for idx, p in enumerate(cac_phan):
        payload = {"chat_id": chat_id, "text": p}
        if idx == len(cac_phan) - 1 and nut_bam:
            payload["reply_markup"] = {"inline_keyboard": nut_bam}
        requests.post(url, json=payload)


# ==============================================================================
# 3. CHẾ ĐỘ 1: GỬI BÁO CÁO TỰ ĐỘNG ĐỊNH KỲ (SÁNG / TỐI)
# ==============================================================================
def chay_bao_cao_tu_dong():
    global BO_NHO_BM
    BO_NHO_BM = quet_danh_sach_bm_va_tai_khoan()
    for bm_info in BO_NHO_BM.values():
        for tk_info in bm_info["tai_khoan"].values():
            du_lieu = tai_du_lieu_5_tang(tk_info["id"], "last_7d")
            if du_lieu["so_camp_co_tieu_tien"] > 0:
                bang = tao_bang_so_sanh_text(f"{tk_info['ten']} (7 ngày qua)", list(du_lieu["camps"].values()), du_lieu["tong_tien_tk"])
                nhan_xet = gemini_danh_gia_chuyen_sau(tk_info["ten"], bang)
                mo_dau = (
                    f"☀️ BÁO CÁO TỰ ĐỘNG ĐỊNH KỲ: {tk_info['ten']}\n"
                    f"📌 Tổng Camp: {du_lieu['tong_so_camp']} | Đang Active: {du_lieu['so_camp_active']} | Có tiêu tiền: {du_lieu['so_camp_co_tieu_tien']}\n"
                    f"💰 Tổng tiêu: {du_lieu['tong_tien_tk']:,}đ | 💬 {du_lieu['tong_mess_tk']} mess\n\n"
                )
                gui_telegram(CHAT_ID, mo_dau + bang + "\n\n" + nhan_xet)


# ==============================================================================
# 4. CHẾ ĐỘ 2: MENU TƯƠNG TÁC 5 TẦNG (CÓ TỰ ĐỘNG NGỦ KHI KHÔNG BẤM NÚT)
# ==============================================================================
def hien_menu_bm(cid):
    global BO_NHO_BM
    if not BO_NHO_BM:
        BO_NHO_BM = quet_danh_sach_bm_va_tai_khoan()
    tong_bm = len(BO_NHO_BM)

    if tong_bm == 1 and "bm_all" in BO_NHO_BM:
        bm_key = "bm_all"
        ds_tk = BO_NHO_BM[bm_key]["tai_khoan"]
        nut_tk = []
        for tk_key, tk_info in ds_tk.items():
            ten_ngan = tk_info["ten"][:22]
            nut_tk.append([
                {"text": f"💳 {ten_ngan} (7 ngày)", "callback_data": f"TK|{bm_key}|{tk_key}|last_7d"},
                {"text": "Hôm qua", "callback_data": f"TK|{bm_key}|{tk_key}|yesterday"},
                {"text": "Hôm nay", "callback_data": f"TK|{bm_key}|{tk_key}|today"},
            ])
        chi_tiet_tk = "\n".join(f"• {v['ten']} ({v['id']}) - {v['trang_thai']}" for v in ds_tk.values())
        van_ban = (
            f"🎛 BẢNG ĐIỀU KHIỂN ADS ĐA TẦNG\n"
            f"(Tài khoản ➡️ Camp ➡️ Group ➡️ Ads)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔍 Đã quét được {len(ds_tk)} Tài khoản:\n{chi_tiet_tk}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👇 Bấm chọn Tài khoản và kỳ dữ liệu bạn muốn kiểm tra:"
        )
        gui_telegram(cid, van_ban, nut_tk)
        return

    nut_bm = []
    for bm_key, bm_info in BO_NHO_BM.items():
        so_tk = len(bm_info["tai_khoan"])
        nut_bm.append([{"text": f"{bm_info['ten_bm']} ({so_tk} TK)", "callback_data": f"BM|{bm_key}"}])
    gui_telegram(cid, "🎛 HỆ THỐNG KIỂM TOÁN ADS 5 TẦNG\n👇 Chọn BM bạn muốn kiểm tra:", nut_bm)


def lang_nghe_nut_bam_thong_minh(offset_ban_dau=0):
    offset = offset_ban_dau
    lan_tuong_tac_cuoi = time.time()
    print("🟢 Đang mở phiên tương tác Menu 5 tầng (Tự động nghỉ sau 10 phút không bấm nút)...")

    while time.time() - lan_tuong_tac_cuoi < THOI_GIAN_CHO_BAM_NUT:
        try:
            url = f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates?offset={offset}&timeout=15"
            res = requests.get(url, timeout=20).json()

            for update in res.get("result", []):
                offset = update["update_id"] + 1
                lan_tuong_tac_cuoi = time.time()  # Gia hạn thêm 10 phút mỗi khi bạn bấm nút

                if "message" in update and "text" in update["message"]:
                    cid = update["message"]["chat"]["id"]
                    hien_menu_bm(cid)

                elif "callback_query" in update:
                    cb = update["callback_query"]
                    cid = cb["message"]["chat"]["id"]
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
                            hien_menu_bm(cid); continue
                        bm_info = BO_NHO_BM[bm_key]
                        ds_tk = bm_info["tai_khoan"]
                        nut_tk = []
                        for tk_key, tk_info in ds_tk.items():
                            ten_ngan = tk_info["ten"][:22]
                            nut_tk.append([
                                {"text": f"💳 {ten_ngan} (7 ngày)", "callback_data": f"TK|{bm_key}|{tk_key}|last_7d"},
                                {"text": "Hôm qua", "callback_data": f"TK|{bm_key}|{tk_key}|yesterday"},
                                {"text": "Hôm nay", "callback_data": f"TK|{bm_key}|{tk_key}|today"},
                            ])
                        if len(BO_NHO_BM) > 1:
                            nut_tk.append([{"text": "⬅️ Quay lại chọn BM", "callback_data": "HOME"}])
                        gui_telegram(cid, f"{bm_info['ten_bm']}\n👇 Chọn Tài khoản và kỳ dữ liệu:", nut_tk)

                    elif lenh == "TK":
                        bm_key, tk_key, tg = parts[1], parts[2], parts[3]
                        if not BO_NHO_BM:
                            BO_NHO_BM.update(quet_danh_sach_bm_va_tai_khoan())
                        tk_info = BO_NHO_BM[bm_key]["tai_khoan"][tk_key]
                        ma_act = tk_info["id"]

                        gui_telegram(cid, f"⏳ Đang quét dữ liệu [{tk_info['ten']}] ({tg})...")
                        du_lieu_tk = tai_du_lieu_5_tang(ma_act, tg)
                        BO_NHO_TK[ma_act] = {"bm_key": bm_key, "tk_key": tk_key, "ten_tk": tk_info["ten"], "tg": tg, "data": du_lieu_tk}

                        tong_tien, tong_mess = du_lieu_tk["tong_tien_tk"], du_lieu_tk["tong_mess_tk"]
                        gia_tb = int(tong_tien / tong_mess) if tong_mess > 0 else 0
                        tom_tat = (
                            f"💳 TÀI KHOẢN: {tk_info['ten']} ({tg})\n"
                            f"📌 Tổng Camp: {du_lieu_tk['tong_so_camp']} | 🟢 Active: {du_lieu_tk['so_camp_active']} | 🔥 Có tiêu tiền: {du_lieu_tk['so_camp_co_tieu_tien']}\n"
                            f"💰 Tổng tiêu: {tong_tien:,}đ | 💬 {tong_mess} mess (TB: {gia_tb:,}đ/mess)\n"
                            f"👇 Bấm So sánh các Camp hoặc chọn từng Camp:"
                        )
                        nut_camp = []
                        if du_lieu_tk["so_camp_co_tieu_tien"] > 0:
                            nut_camp.append([{"text": f"⚖️ ĐÁNH GIÁ & SO SÁNH CẢ {du_lieu_tk['so_camp_co_tieu_tien']} CAMP", "callback_data": f"CMP_CAMP|{ma_act}"}])
                            for c_id, c_info in du_lieu_tk["camps"].items():
                                nut_camp.append([{"text": f"📂 Camp: {c_info['ten'][:22]} ({int(c_info['chi_tieu']/1000):,}k | {c_info['tin_nhan']} mess)", "callback_data": f"CAMP|{ma_act}|{c_id}"}])
                        nut_camp.append([{"text": "⬅️ Quay lại danh sách Tài khoản", "callback_data": f"BM|{bm_key}"}])
                        gui_telegram(cid, tom_tat, nut_camp)

                    elif lenh == "CMP_CAMP":
                        ma_act = parts[1]
                        tk_cache = BO_NHO_TK[ma_act]
                        bang_text = tao_bang_so_sanh_text(f"CÁC CAMP TRONG [{tk_cache['ten_tk']}]", list(tk_cache["data"]["camps"].values()), tk_cache["data"]["tong_tien_tk"])
                        gui_telegram(cid, bang_text + "\n\n⏳ Gemini đang phân tích so sánh các Camp...")
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Tất cả Chiến dịch trong {tk_cache['ten_tk']}", bang_text)
                        gui_telegram(cid, nhan_xet, [[{"text": "⬅️ Quay lại danh sách Camp", "callback_data": f"BACK_TK|{ma_act}"}]])

                    elif lenh == "CAMP":
                        ma_act, c_id = parts[1], parts[2]
                        c_info = BO_NHO_TK[ma_act]["data"]["camps"][c_id]
                        so_group = len(c_info["groups"])
                        gia_tb = int(c_info["chi_tieu"] / c_info["tin_nhan"]) if c_info["tin_nhan"] > 0 else 0
                        tom_tat_c = (
                            f"📂 CAMP: {c_info['ten']} ({c_info['trang_thai']})\n"
                            f"• Số Group có tiêu tiền: {so_group} nhóm\n"
                            f"• Chi tiêu: {c_info['chi_tieu']:,}đ | {c_info['tin_nhan']} mess ({gia_tb:,}đ/mess)\n"
                            f"👇 Chọn so sánh các Group hoặc bấm vào từng Group:"
                        )
                        nut_g = [[{"text": f"🤖 AI ĐÁNH GIÁ CAMP & SO SÁNH {so_group} GROUP", "callback_data": f"CMP_GROUP|{ma_act}|{c_id}"}]]
                        for g_id, g_info in c_info["groups"].items():
                            nut_g.append([{"text": f"📁 Group: {g_info['ten'][:22]} ({int(g_info['chi_tieu']/1000):,}k | {g_info['tin_nhan']} mess)", "callback_data": f"GROUP|{ma_act}|{c_id}|{g_id}"}])
                        nut_g.append([{"text": "⬅️ Quay lại danh sách Camp", "callback_data": f"BACK_TK|{ma_act}"}])
                        gui_telegram(cid, tom_tat_c, nut_g)

                    elif lenh == "CMP_GROUP":
                        ma_act, c_id = parts[1], parts[2]
                        c_info = BO_NHO_TK[ma_act]["data"]["camps"][c_id]
                        bang_text = tao_bang_so_sanh_text(f"CÁC GROUP TRONG CAMP [{c_info['ten']}]", list(c_info["groups"].values()), c_info["chi_tieu"])
                        gui_telegram(cid, bang_text + "\n\n⏳ Gemini đang đánh giá Camp & các Group...")
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Chiến dịch {c_info['ten']}", bang_text)
                        gui_telegram(cid, nhan_xet, [[{"text": "⬅️ Quay lại Camp", "callback_data": f"CAMP|{ma_act}|{c_id}"}]])

                    elif lenh == "GROUP":
                        ma_act, c_id, g_id = parts[1], parts[2], parts[3]
                        g_info = BO_NHO_TK[ma_act]["data"]["camps"][c_id]["groups"][g_id]
                        ds_ads = list(g_info["ads"].values())
                        bang_text = tao_bang_so_sanh_text(f"CÁC BÀI ADS TRONG GROUP [{g_info['ten']}]", ds_ads, g_info["chi_tieu"])
                        nut_a = [[{"text": f"⚖️ AI SO SÁNH CẢ {len(ds_ads)} BÀI ADS", "callback_data": f"CMP_AD|{ma_act}|{c_id}|{g_id}"}]]
                        for a_id, a_info in g_info["ads"].items():
                            nut_a.append([{"text": f"📝 Soi Ads: {a_info['ten'][:22]} ({int(a_info['chi_tieu']/1000):,}k | {a_info['tin_nhan']} mess)", "callback_data": f"AD|{ma_act}|{c_id}|{g_id}|{a_id}"}])
                        nut_a.append([{"text": "⬅️ Quay lại chọn Group", "callback_data": f"CAMP|{ma_act}|{c_id}"}])
                        gui_telegram(cid, bang_text + "\n👇 Bấm vào từng Bài Ads bên dưới để đánh giá sâu:", nut_a)

                    elif lenh == "CMP_AD":
                        ma_act, c_id, g_id = parts[1], parts[2], parts[3]
                        g_info = BO_NHO_TK[ma_act]["data"]["camps"][c_id]["groups"][g_id]
                        bang_text = tao_bang_so_sanh_text(f"CÁC BÀI ADS TRONG GROUP [{g_info['ten']}]", list(g_info["ads"].values()), g_info["chi_tieu"])
                        gui_telegram(cid, "⏳ Gemini đang so sánh các Bài quảng cáo...")
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Nhóm {g_info['ten']}", bang_text)
                        gui_telegram(cid, nhan_xet, [[{"text": "⬅️ Quay lại Group", "callback_data": f"GROUP|{ma_act}|{c_id}|{g_id}"}]])

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
                        gui_telegram(cid, chi_tiet_ad + "\n\n⏳ Gemini đang khám bệnh riêng cho Bài Ads này...")
                        nhan_xet_ad = gemini_danh_gia_chuyen_sau(a_info["ten"], chi_tiet_ad, la_1_bai_le=True)
                        gui_telegram(cid, nhan_xet_ad, [[{"text": "⬅️ Quay lại Group", "callback_data": f"GROUP|{ma_act}|{c_id}|{g_id}"}]])

                    elif lenh == "BACK_TK":
                        ma_act = parts[1]
                        tk_cache = BO_NHO_TK[ma_act]
                        du_lieu_tk = tk_cache["data"]
                        nut_camp = [[{"text": f"⚖️ ĐÁNH GIÁ & SO SÁNH CẢ {du_lieu_tk['so_camp_co_tieu_tien']} CAMP", "callback_data": f"CMP_CAMP|{ma_act}"}]]
                        for c_id, c_info in du_lieu_tk["camps"].items():
                            nut_camp.append([{"text": f"📂 Camp: {c_info['ten'][:22]} ({int(c_info['chi_tieu']/1000):,}k | {c_info['tin_nhan']} mess)", "callback_data": f"CAMP|{ma_act}|{c_id}"}])
                        nut_camp.append([{"text": "⬅️ Quay lại danh sách Tài khoản", "callback_data": f"BM|{tk_cache['bm_key']}"}])
                        gui_telegram(cid, f"👇 Danh sách Camp của [{tk_cache['ten_tk']}]:", nut_camp)

                    elif lenh == "HOME":
                        hien_menu_bm(cid)

        except Exception as e:
            print("⚠️ Lỗi xử lý:", e)
            time.sleep(3)

    print("💤 Đã hết 10 phút không có thao tác bấm nút -> Tự động đóng phiên để tiết kiệm phút GitHub!")


# ==============================================================================
# 5. ĐIỀU PHỐI THÔNG MINH: TỰ BÁO CÁO ĐỊNH KỲ HOẶC ĐÁNH THỨC KHI CÓ TIN NHẮN
# ==============================================================================
if __name__ == "__main__":
    # Kiểm tra xem có tin nhắn hoặc nút bấm mới nào từ bạn trên Telegram không
    res_check = requests.get(f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates?timeout=2").json()
    updates = res_check.get("result", [])

    if LOAI_KICH_HOAT == "bao_cao_dinh_ky":
        # 1. Đúng giờ hẹn sáng/tối hoặc khi bạn bấm nút Run workflow trên web:
        chay_bao_cao_tu_dong()
        hien_menu_bm(CHAT_ID)
        next_offset = updates[-1]["update_id"] + 1 if updates else 0
        lang_nghe_nut_bam_thong_minh(next_offset)

    else:
        # 2. Nhịp kiểm tra tự động: Nếu bạn KHÔNG nhắn gì trên Telegram -> Thoát ngay trong 2 giây!
        if not updates:
            print("ℹ️ Không có lệnh mới từ Telegram -> Thoát ngay (0 tốn phút).")
        else:
            print("🔔 Phát hiện bạn vừa nhắn tin/bấm nút trên Telegram -> Bật ngay Bảng điều khiển!")
            lang_nghe_nut_bam_thong_minh(updates[0]["update_id"])
