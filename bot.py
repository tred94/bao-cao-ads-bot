
CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "5657736528").strip()

# Mặc định ưu tiên dùng Gemini ("gemini" hoặc "chatgpt")
AI_UU_TIEN = "gemini"

BO_NHO_BM = {}
BO_NHO_TK = {}
DA_BAO_CAO_TRONG_PHIEN = set()
@@ -350,8 +353,30 @@ def tim_model_gemini():
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
    """Hàm dự phòng: Gọi ChatGPT (gpt-4o-mini) khi Gemini quá tải hoặc lỗi"""
if not OPENAI_KEY:
return None
url = "https://api.openai.com/v1/chat/completions"
@@ -370,13 +395,17 @@ def goi_openai_gpt(prompt_text):
try:
res = requests.post(url, headers=headers, json=payload, timeout=25).json()
if "choices" in res and len(res["choices"]) > 0:
            return res["choices"][0]["message"]["content"]
            noi_dung = res["choices"][0]["message"]["content"]
            return f"🤖 [Phân tích bởi ChatGPT (gpt-4o-mini)]\n\n{noi_dung}"
except Exception as e:
print("⚠️ Lỗi gọi OpenAI:", e)
return None


def gemini_danh_gia_chuyen_sau(tieu_de, du_lieu_text):
def gemini_danh_gia_chuyen_sau(tieu_de, du_lieu_text, chon_ai=None):
    """Hỗ trợ chọn trực tiếp AI ('gemini' hoặc 'chatgpt') hoặc chạy theo AI_UU_TIEN mặc định"""
    ai_muc_tieu = chon_ai if chon_ai else AI_UU_TIEN

prompt = f"""
   Bạn là Giám đốc Tối ưu Quảng cáo Facebook (Senior Media Buyer).
   Đánh giá dữ liệu của [{tieu_de}] dưới đây (Mốc KPI mục tiêu: {KPI_MESS:,}đ/mess):
@@ -407,33 +436,22 @@ def gemini_danh_gia_chuyen_sau(tieu_de, du_lieu_text):
   Không dùng ký tự dấu sao (*) hay dấu thăng (#).
   """

    # 1. Ưu tiên gọi Gemini trước
    if GEMINI_KEY:
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
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

    # 2. Nếu Gemini lỗi hoặc hết hạn mức -> Tự động chuyển sang gọi ChatGPT (OpenAI)
    if OPENAI_KEY:
        kq_gpt = goi_openai_gpt(prompt)
        if kq_gpt:
            return f"🤖 [Phân tích bởi ChatGPT (gpt-4o-mini)]\n\n{kq_gpt}"

    return "⚠️ Không kết nối được cả Gemini API và OpenAI API."
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
@@ -483,11 +501,19 @@ def hien_menu_chinh(cid, msg_id=None, tg_mac_dinh="today"):
BO_NHO_BM = quet_danh_sach_tai_khoan()

gio_hien_tai = lay_gio_viet_nam().strftime("%H:%M - %d/%m/%Y")
    nhan_gemini = "✅ ✨ Ưu tiên Gemini" if AI_UU_TIEN == "gemini" else "✨ Ưu tiên Gemini"
    nhan_gpt = "✅ 🤖 Ưu tiên ChatGPT" if AI_UU_TIEN == "chatgpt" else "🤖 Ưu tiên ChatGPT"
    ten_ai_hien_tai = "Gemini (Google)" if AI_UU_TIEN == "gemini" else "ChatGPT (OpenAI)"

nut_tk = [
[
{"text": "⚡ Báo Cáo Tất Cả (Realtime)", "callback_data": "QuickReport|today"},
{"text": "📅 Báo Cáo Tất Cả (Hôm qua)", "callback_data": "QuickReport|yesterday"},
        ]
        ],
        [
            {"text": nhan_gemini, "callback_data": "SET_AI|gemini"},
            {"text": nhan_gpt, "callback_data": "SET_AI|chatgpt"},
        ],
]

for idx, (tk_idx, tk_info) in enumerate(BO_NHO_BM.items(), 1):
@@ -499,10 +525,11 @@ def hien_menu_chinh(cid, msg_id=None, tg_mac_dinh="today"):
van_ban = (
f"🎛 TRUNG TÂM KIỂM TOÁN ADS (REALTIME 24/7)\n"
f"🕒 Thời điểm check: {gio_hien_tai}\n"
        f"🧠 AI mặc định đang chọn: {ten_ai_hien_tai}\n"
f"━━━━━━━━━━━━━━━━━━━━\n"
f"🔍 Đã kết nối {len(BO_NHO_BM)} Tài khoản Quảng cáo.\n"
f"⚡ Mặc định khi bấm vào tài khoản sẽ lấy số liệu REALTIME HÔM NAY (từ 0h00 đến hiện tại).\n\n"
        f"👇 Chạm vào nút bên dưới để kiểm tra ngay:"
        f"👇 Chạm vào nút bên dưới để đổi AI hoặc kiểm tra tài khoản:"
)
gui_hoac_sua_menu(cid, van_ban, nut_tk, msg_id)

@@ -558,10 +585,9 @@ def hien_man_hinh_tai_khoan(cid, tk_idx, tg="today", msg_id=None, can_tai_lai=Tr
f"━━━━━━━━━━━━━━━━━━━━\n"
f"📦 TỔNG HỢP THEO CỤM TÊN CAMP:\n{text_cum}\n"
f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 Đổi kỳ dữ liệu, bấm Đánh giá theo Cụm hoặc chọn từng Camp bên dưới:"
        f"👇 Đổi kỳ dữ liệu, chọn AI Đánh giá hoặc bấm vào từng Camp bên dưới:"
)

    # Thanh chọn thời gian: Mặc định tô xanh "✅ Hôm nay" (Realtime)
cac_moc = [("today", "⚡ Hôm nay"), ("yesterday", "Hôm qua"), ("last_3d", "3 ngày"), ("last_7d", "7 ngày")]
hang_thoi_gian = []
for ma_tg, nhan_ngan in cac_moc:
@@ -572,17 +598,17 @@ def hien_man_hinh_tai_khoan(cid, tk_idx, tg="today", msg_id=None, can_tai_lai=Tr
})
nut_camp = [hang_thoi_gian]

    # Nút làm mới Realtime ngay tại chỗ
nut_camp.append([{
"text": f"🔄 Làm mới số liệu Realtime ({lay_gio_viet_nam().strftime('%H:%M')})",
"callback_data": f"TK|{tk_idx}|{tg}",
}])

if du_lieu_tk["so_camp_co_tieu_tien"] > 0:
        nut_camp.append([{
            "text": f"⚖️ AI ĐÁNH GIÁ TẤT CẢ ({du_lieu_tk['so_camp_co_tieu_tien']} CAMP)",
            "callback_data": f"ALL_C|{tk_idx}",
        }])
        # 2 lựa chọn AI ngay trên màn hình Tài khoản
        nut_camp.append([
            {"text": "✨ Gemini Đánh Giá Tất Cả", "callback_data": f"ALL_C|{tk_idx}|gemini"},
            {"text": "🤖 ChatGPT Đánh Giá Tất Cả", "callback_data": f"ALL_C|{tk_idx}|chatgpt"},
        ])

for c_gr in cum_list:
tien_k = int(c_gr["chi_tieu"] / 1000)
@@ -621,13 +647,13 @@ def hien_man_hinh_camp(cid, tk_idx, c_idx, msg_id=None):
f"• Trạng thái: {c_info['trang_thai']} | Số Group: {so_group} nhóm\n"
f"• Chi tiêu: {c_info['chi_tieu']:,}đ | KQ: {c_info['tin_nhan']} mess ({gia_tb:,}đ/mess)\n\n"
f"{bang_group}\n"
        f"👇 Bấm AI Đánh giá Camp này hoặc chạm vào từng Group để soi Bài Ads:"
        f"👇 Chọn Gemini hoặc ChatGPT bắt bệnh Camp này, hoặc chạm vào từng Group:"
)

    nut_g = [[{
        "text": f"🤖 AI BẮT BỆNH CAMP NÀY & {so_group} GROUP",
        "callback_data": f"AI_C|{tk_idx}|{c_idx}",
    }]]
    nut_g = [[
        {"text": "✨ Gemini Bắt Bệnh Camp", "callback_data": f"AI_C|{tk_idx}|{c_idx}|gemini"},
        {"text": "🤖 ChatGPT Bắt Bệnh Camp", "callback_data": f"AI_C|{tk_idx}|{c_idx}|chatgpt"},
    ]]
for idx, g_info in enumerate(groups_list, 1):
ten_g = g_info["ten"][:26]
tien_k = int(g_info["chi_tieu"] / 1000)
@@ -649,10 +675,10 @@ def hien_man_hinh_group(cid, tk_idx, c_idx, g_idx, msg_id=None):
ads_list,
g_info["chi_tieu"],
)
    nut_a = [[{
        "text": f"⚖️ AI ĐÁNH GIÁ CẢ {len(ads_list)} BÀI ADS TRONG GROUP",
        "callback_data": f"AI_G|{tk_idx}|{c_idx}|{g_idx}",
    }]]
    nut_a = [[
        {"text": "✨ Gemini Soi Group", "callback_data": f"AI_G|{tk_idx}|{c_idx}|{g_idx}|gemini"},
        {"text": "🤖 ChatGPT Soi Group", "callback_data": f"AI_G|{tk_idx}|{c_idx}|{g_idx}|chatgpt"},
    ]]
for idx, a_info in enumerate(ads_list, 1):
ten_a = a_info["ten"][:26]
tien_k = int(a_info["chi_tieu"] / 1000)
@@ -663,7 +689,7 @@ def hien_man_hinh_group(cid, tk_idx, c_idx, g_idx, msg_id=None):
nut_a.append([{"text": "⬅️ Quay lại Chiến dịch (Camp)", "callback_data": f"C|{tk_idx}|{c_idx}"}])
gui_hoac_sua_menu(
cid,
        bang_ads + "\n👇 Chạm vào từng Bài Ads bên dưới để bắt bệnh sâu:",
        bang_ads + "\n👇 Chọn AI đánh giá cả Group hoặc chạm vào từng Bài Ads bên dưới:",
nut_a,
msg_id,
)
@@ -744,6 +770,7 @@ def kiem_tra_den_gio_bao_cao_tu_dong():
# 6. VÒNG LẶP TRỰC CHIẾN 24/7
# ==============================================================================
def chay_vong_lap_truc_chien_247(offset_ban_dau=0):
    global AI_UU_TIEN
offset = offset_ban_dau
thoi_diem_bat_dau = time.time()
print("🟢 Bot đang trực chiến 24/7 (Mặc định Check Realtime Hôm nay)...")
@@ -779,7 +806,6 @@ def chay_vong_lap_truc_chien_247(offset_ban_dau=0):
hien_menu_chinh(cid, tg_mac_dinh="today")

else:
                        # Bất kỳ tin nhắn hay nút "/menu" nào -> Đều bật bàn phím cố định + Bảng điều khiển Realtime!
gui_ban_phim_co_dinh(cid)
hien_menu_chinh(cid, tg_mac_dinh="today")

@@ -788,14 +814,26 @@ def chay_vong_lap_truc_chien_247(offset_ban_dau=0):
cid = cb["message"]["chat"]["id"]
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

                    parts = data.split("|")
                    lenh = parts[0]

if lenh == "HOME":
hien_menu_chinh(cid, msg_id, tg_mac_dinh="today")

@@ -823,6 +861,7 @@ def chay_vong_lap_truc_chien_247(offset_ban_dau=0):

elif lenh == "ALL_C":
tk_idx = parts[1]
                        chon_ai = parts[2] if len(parts) > 2 else None
if tk_idx not in BO_NHO_TK:
hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id, can_tai_lai=True)
continue
@@ -832,12 +871,19 @@ def chay_vong_lap_truc_chien_247(offset_ban_dau=0):
tk_cache["data"]["cum_list"],
tk_cache["data"]["tong_tien_tk"],
)
                        gui_hoac_sua_menu(cid, bang_text + "\n\n⏳ AI đang bắt bệnh toàn bộ các Cụm & Camp...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Tất cả Cụm & Camp ({tk_cache['ten_tk']})", bang_text)
                        ten_ai_chay = "ChatGPT" if (chon_ai or AI_UU_TIEN) == "chatgpt" else "Gemini"
                        gui_hoac_sua_menu(cid, bang_text + f"\n\n⏳ {ten_ai_chay} đang bắt bệnh toàn bộ các Cụm & Camp...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Tất cả Cụm & Camp ({tk_cache['ten_tk']})", bang_text, chon_ai=chon_ai)
gui_hoac_sua_menu(
cid,
bang_text + "\n\n" + nhan_xet,
                            [[{"text": "⬅️ Quay lại Tài khoản", "callback_data": f"BACK_TK|{tk_idx}"}]],
                            [
                                [
                                    {"text": "✨ Hỏi lại bằng Gemini", "callback_data": f"ALL_C|{tk_idx}|gemini"},
                                    {"text": "🤖 Hỏi lại bằng ChatGPT", "callback_data": f"ALL_C|{tk_idx}|chatgpt"},
                                ],
                                [{"text": "⬅️ Quay lại Tài khoản", "callback_data": f"BACK_TK|{tk_idx}"}],
                            ],
msg_id,
)

@@ -854,10 +900,10 @@ def chay_vong_lap_truc_chien_247(offset_ban_dau=0):
c_group["ds_camps"],
c_group["chi_tieu"],
)
                        nut_cum = [[{
                            "text": f"🤖 AI BẮT BỆNH RIÊNG CỤM [{ten_cum}]",
                            "callback_data": f"AI_CUM|{tk_idx}|{cum_idx}",
                        }]]
                        nut_cum = [[
                            {"text": f"✨ Gemini Soi Cụm [{ten_cum}]", "callback_data": f"AI_CUM|{tk_idx}|{cum_idx}|gemini"},
                            {"text": f"🤖 ChatGPT Soi Cụm [{ten_cum}]", "callback_data": f"AI_CUM|{tk_idx}|{cum_idx}|chatgpt"},
                        ]]
for c_info in c_group["ds_camps"]:
ten_c = c_info["ten"][:25]
tien_k = int(c_info["chi_tieu"] / 1000)
@@ -870,6 +916,7 @@ def chay_vong_lap_truc_chien_247(offset_ban_dau=0):

elif lenh == "AI_CUM":
tk_idx, cum_idx = parts[1], parts[2]
                        chon_ai = parts[3] if len(parts) > 3 else None
if tk_idx not in BO_NHO_TK:
hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id, can_tai_lai=True)
continue
@@ -881,12 +928,17 @@ def chay_vong_lap_truc_chien_247(offset_ban_dau=0):
c_group["ds_camps"],
c_group["chi_tieu"],
)
                        gui_hoac_sua_menu(cid, bang_cum + f"\n\n⏳ AI đang bắt bệnh cụm [{ten_cum}]...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Cụm [{ten_cum}] ({tk_cache['ten_tk']})", bang_cum)
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
@@ -902,6 +954,7 @@ def chay_vong_lap_truc_chien_247(offset_ban_dau=0):

elif lenh == "AI_C":
tk_idx, c_idx = parts[1], parts[2]
                        chon_ai = parts[3] if len(parts) > 3 else None
if tk_idx not in BO_NHO_TK:
hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id, can_tai_lai=True)
continue
@@ -911,12 +964,19 @@ def chay_vong_lap_truc_chien_247(offset_ban_dau=0):
c_info["groups_list"],
c_info["chi_tieu"],
)
                        gui_hoac_sua_menu(cid, bang_group + "\n\n⏳ AI đang bắt bệnh Camp & các Group...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Camp {c_info['ten']}", bang_group)
                        ten_ai_chay = "ChatGPT" if (chon_ai or AI_UU_TIEN) == "chatgpt" else "Gemini"
                        gui_hoac_sua_menu(cid, bang_group + f"\n\n⏳ {ten_ai_chay} đang bắt bệnh Camp & các Group...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Camp {c_info['ten']}", bang_group, chon_ai=chon_ai)
gui_hoac_sua_menu(
cid,
bang_group + "\n\n" + nhan_xet,
                            [[{"text": "⬅️ Quay lại Camp", "callback_data": f"C|{tk_idx}|{c_idx}"}]],
                            [
                                [
                                    {"text": "✨ Soi bằng Gemini", "callback_data": f"AI_C|{tk_idx}|{c_idx}|gemini"},
                                    {"text": "🤖 Soi bằng ChatGPT", "callback_data": f"AI_C|{tk_idx}|{c_idx}|chatgpt"},
                                ],
                                [{"text": "⬅️ Quay lại Camp", "callback_data": f"C|{tk_idx}|{c_idx}"}],
                            ],
msg_id,
)

@@ -929,6 +989,7 @@ def chay_vong_lap_truc_chien_247(offset_ban_dau=0):

elif lenh == "AI_G":
tk_idx, c_idx, g_idx = parts[1], parts[2], parts[3]
                        chon_ai = parts[4] if len(parts) > 4 else None
if tk_idx not in BO_NHO_TK:
hien_man_hinh_tai_khoan(cid, tk_idx, "today", msg_id, can_tai_lai=True)
continue
@@ -939,17 +1000,25 @@ def chay_vong_lap_truc_chien_247(offset_ban_dau=0):
g_info["ads_list"],
g_info["chi_tieu"],
)
                        gui_hoac_sua_menu(cid, bang_ads + "\n\n⏳ AI đang bắt bệnh các Bài Ads...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Group {g_info['ten']}", bang_ads)
                        ten_ai_chay = "ChatGPT" if (chon_ai or AI_UU_TIEN) == "chatgpt" else "Gemini"
                        gui_hoac_sua_menu(cid, bang_ads + f"\n\n⏳ {ten_ai_chay} đang bắt bệnh các Bài Ads...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Group {g_info['ten']}", bang_ads, chon_ai=chon_ai)
gui_hoac_sua_menu(
cid,
bang_ads + "\n\n" + nhan_xet,
                            [[{"text": "⬅️ Quay lại Group", "callback_data": f"G|{tk_idx}|{c_idx}|{g_idx}"}]],
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
@@ -963,12 +1032,19 @@ def chay_vong_lap_truc_chien_247(offset_ban_dau=0):
f"• Tệp khách: CPM {a_info['cpm']:,}đ | Lặp (Freq) {a_info['frequency']} | Reach {a_info['reach']:,}\n"
f"• Nội dung & Phễu: CTR {a_info['ctr']}% | CPC {a_info['cpc']:,}đ | Click->Mess {a_info['cr_click_to_mess']}%"
)
                        gui_hoac_sua_menu(cid, chi_tiet_ad + "\n\n⏳ AI đang bắt bệnh riêng cho Bài Ads này...", None, msg_id)
                        nhan_xet_ad = gemini_danh_gia_chuyen_sau(f"Bài Ads {a_info['ten']}", chi_tiet_ad)
                        ten_ai_chay = "ChatGPT" if (chon_ai or AI_UU_TIEN) == "chatgpt" else "Gemini"
                        gui_hoac_sua_menu(cid, chi_tiet_ad + f"\n\n⏳ {ten_ai_chay} đang bắt bệnh riêng cho Bài Ads này...", None, msg_id)
                        nhan_xet_ad = gemini_danh_gia_chuyen_sau(f"Bài Ads {a_info['ten']}", chi_tiet_ad, chon_ai=chon_ai)
gui_hoac_sua_menu(
cid,
chi_tiet_ad + "\n\n" + nhan_xet_ad,
                            [[{"text": "⬅️ Quay lại Group", "callback_data": f"G|{tk_idx}|{c_idx}|{g_idx}"}]],
                            [
                                [
                                    {"text": "✨ Soi bằng Gemini", "callback_data": f"A|{tk_idx}|{c_idx}|{g_idx}|{a_idx}|gemini"},
                                    {"text": "🤖 Soi bằng ChatGPT", "callback_data": f"A|{tk_idx}|{c_idx}|{g_idx}|{a_idx}|chatgpt"},
                                ],
                                [{"text": "⬅️ Quay lại Group", "callback_data": f"G|{tk_idx}|{c_idx}|{g_idx}"}],
                            ],
msg_id,
)
