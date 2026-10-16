
                    elif lenh == "BACK_TK":
                        tk_idx = parts[1]
                        if tk_idx in BO_NHO_TK:
                            hien_man_hinh_tai_khoan(cid, tk_idx, BO_NHO_TK[tk_idx]["tg"], msg_id, can_tai_lai=False)
                        else:
                            hien_man_hinh_tai_khoan(cid, tk_idx, "yesterday", msg_id, can_tai_lai=True)

                    elif lenh == "ALL_C":
                        tk_idx = parts[1]
                        tk_cache = BO_NHO_TK[tk_idx]
                        bang_text = tao_bang_gom_cum_text(
                            tk_cache["ten_tk"],
                            tk_cache["data"]["cum_list"],
                            tk_cache["data"]["tong_tien_tk"],
                        )
                        gui_hoac_sua_menu(cid, bang_text + "\n\n⏳ Gemini đang bắt bệnh toàn bộ các Cụm & Camp...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Tất cả Cụm & Camp ({tk_cache['ten_tk']})", bang_text)
                        gui_hoac_sua_menu(
                            cid,
                            bang_text + "\n\n" + nhan_xet,
                            [[{"text": "⬅️ Quay lại Tài khoản", "callback_data": f"BACK_TK|{tk_idx}"}]],
                            msg_id,
                        )

                    elif lenh == "CUM":
                        tk_idx, cum_idx = parts[1], parts[2]
                        tk_cache = BO_NHO_TK[tk_idx]
                        c_group = tk_cache["data"]["cum_list"][int(cum_idx)]
                        ten_cum = c_group["ten_cum"]
                        bang_cum = tao_bang_so_sanh_text(
                            f"CỤM [{ten_cum}] ({c_group['so_camp']} camp)",
                            c_group["ds_camps"],
                            c_group["chi_tieu"],
                        )
                        nut_cum = [[{
                            "text": f"🤖 AI BẮT BỆNH RIÊNG CỤM [{ten_cum}]",
                            "callback_data": f"AI_CUM|{tk_idx}|{cum_idx}",
                        }]]
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
                        tk_cache = BO_NHO_TK[tk_idx]
                        c_group = tk_cache["data"]["cum_list"][int(cum_idx)]
                        ten_cum = c_group["ten_cum"]
                        bang_cum = tao_bang_so_sanh_text(
                            f"CỤM [{ten_cum}] ({c_group['so_camp']} camp)",
                            c_group["ds_camps"],
                            c_group["chi_tieu"],
                        )
                        gui_hoac_sua_menu(cid, bang_cum + f"\n\n⏳ Gemini đang bắt bệnh cụm [{ten_cum}]...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Cụm [{ten_cum}] ({tk_cache['ten_tk']})", bang_cum)
                        gui_hoac_sua_menu(
                            cid,
                            bang_cum + "\n\n" + nhan_xet,
                            [
                                [{"text": f"⬅️ Quay lại Cụm [{ten_cum}]", "callback_data": f"CUM|{tk_idx}|{cum_idx}"}],
                                [{"text": "🏠 Về màn hình Tài khoản", "callback_data": f"BACK_TK|{tk_idx}"}],
                            ],
                            msg_id,
                        )

                    # --- BẤM VÀO TỪNG CAMP -> HIỆN CÁC GROUP BÊN TRONG ---
                    elif lenh == "C":
                        tk_idx, c_idx = parts[1], parts[2]
                        hien_man_hinh_camp(cid, tk_idx, c_idx, msg_id)

                    elif lenh == "AI_C":
                        tk_idx, c_idx = parts[1], parts[2]
                        c_info = BO_NHO_TK[tk_idx]["data"]["camps_list"][int(c_idx)]
                        bang_group = tao_bang_so_sanh_text(
                            f"CÁC GROUP TRONG CAMP [{c_info['ten']}]",
                            c_info["groups_list"],
                            c_info["chi_tieu"],
                        )
                        gui_hoac_sua_menu(cid, bang_group + "\n\n⏳ Gemini đang bắt bệnh Camp & các Group...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Camp {c_info['ten']}", bang_group)
                        gui_hoac_sua_menu(
                            cid,
                            bang_group + "\n\n" + nhan_xet,
                            [[{"text": "⬅️ Quay lại Camp", "callback_data": f"C|{tk_idx}|{c_idx}"}]],
                            msg_id,
                        )

                    # --- BẤM VÀO TỪNG GROUP -> HIỆN CÁC BÀI ADS BÊN TRONG ---
                    elif lenh == "G":
                        tk_idx, c_idx, g_idx = parts[1], parts[2], parts[3]
                        hien_man_hinh_group(cid, tk_idx, c_idx, g_idx, msg_id)

                    elif lenh == "AI_G":
                        tk_idx, c_idx, g_idx = parts[1], parts[2], parts[3]
                        c_info = BO_NHO_TK[tk_idx]["data"]["camps_list"][int(c_idx)]
                        g_info = c_info["groups_list"][int(g_idx)]
                        bang_ads = tao_bang_so_sanh_text(
                            f"CÁC BÀI ADS TRONG GROUP [{g_info['ten']}]",
                            g_info["ads_list"],
                            g_info["chi_tieu"],
                        )
                        gui_hoac_sua_menu(cid, bang_ads + "\n\n⏳ Gemini đang bắt bệnh các Bài Ads...", None, msg_id)
                        nhan_xet = gemini_danh_gia_chuyen_sau(f"Group {g_info['ten']}", bang_ads)
                        gui_hoac_sua_menu(
                            cid,
                            bang_ads + "\n\n" + nhan_xet,
                            [[{"text": "⬅️ Quay lại Group", "callback_data": f"G|{tk_idx}|{c_idx}|{g_idx}"}]],
                            msg_id,
                        )

                    # --- BẤM VÀO TỪNG BÀI ADS LẺ -> KHÁM BỆNH CHI TIẾT BÀI ĐÓ ---
                    elif lenh == "A":
                        tk_idx, c_idx, g_idx, a_idx = parts[1], parts[2], parts[3], parts[4]
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
                        gui_hoac_sua_menu(cid, chi_tiet_ad + "\n\n⏳ Gemini đang bắt bệnh riêng cho Bài Ads này...", None, msg_id)
                        nhan_xet_ad = gemini_danh_gia_chuyen_sau(f"Bài Ads {a_info['ten']}", chi_tiet_ad)
                        gui_hoac_sua_menu(
                            cid,
                            chi_tiet_ad + "\n\n" + nhan_xet_ad,
                            [[{"text": "⬅️ Quay lại Group", "callback_data": f"G|{tk_idx}|{c_idx}|{g_idx}"}]],
                            msg_id,
                        )

        except Exception as e:
            print("⚠️ Lỗi xử lý:", e)
            time.sleep(3)


# ==============================================================================
# 7. ĐIỀU PHỐI CHÍNH (TỰ ĐỘNG CHỌN KỲ DỮ LIỆU THEO GIỜ SÁNG / TỐI VIỆT NAM)
# ==============================================================================
if __name__ == "__main__":
    # GitHub Actions phải truyền hai biến EVENT_NAME và CRON_SCHEDULE.
    event_name = os.environ.get("EVENT_NAME", "").strip()
    cron_schedule = os.environ.get("CRON_SCHEDULE", "").strip()
    che_do_input = os.environ.get("CHE_DO_INPUT", "menu").strip().lower()

    gio_vn = datetime.now(GIO_VIET_NAM).hour
    ky_mac_dinh_theo_gio = "yesterday" if gio_vn < 14 else "today"

    # Lấy offset trước khi làm báo cáo để không bỏ sót lệnh người dùng gửi trong lúc AI chạy.
    res_check = requests.get(
        f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates",
        params={"timeout": 3}, timeout=10,
    ).json()
    updates = res_check.get("result", [])
    next_offset = updates[-1]["update_id"] + 1 if updates else 0

    # Không tự đoán 'hôm qua' khi GitHub không truyền lịch hợp lệ.
    if event_name == "schedule":
        che_do_theo_cron = {
            "0 1 * * *": "yesterday",  # 08:00 giờ VN
            "0 13 * * *": "today",    # 20:00 giờ VN
        }.get(cron_schedule)
        if not che_do_theo_cron:
            raise RuntimeError(
                f"Lịch GitHub không hợp lệ: {cron_schedule!r}. "
                "Kiểm tra env CRON_SCHEDULE: ${{ github.event.schedule }}"
            )
        print(f"[SCHEDULE] cron={cron_schedule} => period={che_do_theo_cron}")
        chay_bao_cao_tu_dong(che_do_theo_cron)
        hien_menu_chinh(CHAT_ID, tg_mac_dinh=che_do_theo_cron)
        lang_nghe_nut_bam_thong_minh(next_offset)

    elif event_name == "workflow_dispatch":
        if che_do_input in ("yesterday", "today"):
            chay_bao_cao_tu_dong(che_do_input)
        hien_menu_chinh(
            CHAT_ID,
            tg_mac_dinh=che_do_input if che_do_input in ("today", "yesterday") else ky_mac_dinh_theo_gio,
        )
        lang_nghe_nut_bam_thong_minh(next_offset)

    else:
        # Chỉ kiểm tra Telegram, không gửi báo cáo ngày khác do thiếu biến lịch.
        if updates:
            hien_menu_chinh(CHAT_ID, tg_mac_dinh=ky_mac_dinh_theo_gio)
