---
name: make-shorts
description: Tạo YouTube Shorts bóng đá tự động từ một link video YouTube dài. Skill tải video, chọn highlight, duyệt hình từng clip, cắt dọc 9:16 và render. Sau đó hỏi người dùng output đã ổn chưa; nếu ổn thì dọn sạch file trung gian để không tốn ổ đĩa. Dùng khi người dùng đưa link và số lượng short, ví dụ "/make-shorts <link> 5" hoặc "làm 5 short từ video này".
argument-hint: <youtube-link> [số-short=5]
allowed-tools: Bash(python3 shorts.py *) Bash(df *) Bash(open *) Read Edit Write
---

# Make Shorts

Đầu vào: `$ARGUMENTS`. Trong đó có một link YouTube (hoặc đường dẫn file video) và số short N; thiếu N thì lấy 5. Không có link thì hỏi lại.

Làm trọn từ đầu đến cuối, không hỏi giữa chừng; chỉ hỏi ở bước 6 (duyệt output). Chạy mọi lệnh từ thư mục gốc dự án, mỗi lệnh một lần gọi (không `cd … &&`).

Với `download`, `analyze`, `cut` và `render`, đặt timeout Bash 600000. Nếu video gốc dài hơn 20 phút hoặc N > 6 thì chạy nền (`run_in_background`) và chờ thông báo xong, không poll.

## 0. Chuẩn bị

- Chạy `df -h .`, cần còn ≥ 5 GB trống (một trận 90 phút 1080p ≈ 1.5–3 GB). Không đủ thì báo người dùng, kể các `work/<id>` cũ có thể xoá bằng `python3 shorts.py clean <id> --all`, rồi dừng.

## 1. Tải

- `python3 shorts.py download "<link>"`. Dòng cuối có dạng `ID video: <id>`.
- Gặp HTTP 403 hoặc lỗi trích xuất: `brew upgrade yt-dlp` rồi chạy lại.
- Nếu `output/<id>/` đã có short của video này, hỏi người dùng làm lại hay giữ bản cũ.
- Ghi nhớ nếu lệnh cảnh báo video không có giấy phép Creative Commons; bước 6 sẽ nhắc lại.

## 2. Phân tích và dò highlight

```
python3 shorts.py analyze <id>
python3 shorts.py detect <id> --count <N+3>
```

Lấy dư 3 ứng viên để còn loại.

## 3. Duyệt hình và chốt từng clip (bước quyết định chất lượng)

Dò tự động dựa vào âm thanh, nên với video tổng hợp hay sai: trượt mất bàn thắng, hoặc lẫn sang trận khác. Luôn duyệt bằng mắt bằng `sheet`.

`sheet` ghép khung hình thành ảnh lưới, đọc trái→phải, trên→dưới. Lệnh in giờ bắt đầu của từng hàng; thời điểm một ô = giờ đầu hàng + cột / fps.

Với mỗi ứng viên trong `work/<id>/highlights.json`:

1. Chạy `python3 shorts.py sheet <id> <start-8> <end+8> --fps 1` rồi Read từng trang. Kiểm tra:
   - Có pha bóng thật không (bàn thắng, cứu thua, kỹ thuật)?
   - Giữa chừng có chuyển sang trận hay cảnh khác không? Dấu hiệu: áo đấu, bảng tỉ số hoặc ánh sáng đổi.
2. Chốt `start` và `end`:
   - `start`: 3–6 giây trước cú dứt điểm (đầu pha tấn công), ngay sau một lần chuyển cảnh nếu có.
   - `end`: 3–8 giây sau khi bắt đầu ăn mừng, trước khi sang cảnh khác. Có thể giữ 1 replay hay nhất.
   - Độ dài 15–58 giây, tốt nhất 20–35 giây.
3. Ghim `impact` bằng `python3 shorts.py sheet <id> <t-2> <t+2> --fps 8`. `impact` là giây bóng chạm lưới hoặc qua vạch, tính trong video gốc.
   - Hai bàn trong một clip: ghi danh sách `[t1, t2]`, cách nhau ≥ 2.5 giây.
4. Loại trùng: video tổng hợp hay chiếu lại cùng một bàn, chỉ giữ một.

Không đủ N pha tốt thì quét cả video với `python3 shorts.py sheet <id> 0 <duration> --fps 0.2` (`duration` lấy trong `work/<id>/info.json`). Tìm các cảnh ghi bàn hoặc ăn mừng, rồi chốt như trên.

Viết lại `highlights.json` chỉ còn N clip tốt nhất. Đánh lại `n` từ 1 đến N theo thứ tự nên đăng (pha mạnh nhất trước). Mỗi clip:

- `title`: tiếng Anh (kênh tiếng Anh), ≤ 40 ký tự. Là hook gây tò mò nhưng đúng sự thật trong clip.
  - Tên cầu thủ lấy từ tiêu đề video hoặc lời bình (`excerpt`). Không bịa tỉ số, giải đấu, kỷ lục.
  - Ví dụ đã dùng: "Messi crowns it all himself", "2 free kicks. Same result."
- `mode: "blur"`, `zoom: 1.55` (hình to, cắt bớt 2 mép). Hạ về 1.3 hoặc 1.0 nếu pha bóng hay cầu thủ chính nằm sát mép.
- `enabled: true`, `music: ""`. `peak` và `score` để nguyên.
- `excerpt`: một câu mô tả pha bóng. `reasons: ["chọn tay sau khi duyệt hình"]`.

## 4. Cắt và render

```
python3 shorts.py cut <id>
python3 shorts.py render <id>
```

Mỗi short render mất khoảng 20–40 giây. Mỗi clip phải in `✓ 1080x1920`.

## 5. Tự kiểm tra output

Với từng short, chạy `python3 shorts.py sheet <id> --output <n>` rồi Read ảnh. Kiểm tra:

- Tiêu đề đọc được, không tràn hay mất chữ.
- Pha bóng nằm trọn trong khung, không bị zoom cắt mất.
- Ô ở mốc ghi bàn có zoom hoặc flash (mốc ghi trong `output/<id>/upload.md`).
- Không có khung đen, không lẫn cảnh khác ở đầu hoặc cuối.

Có lỗi thì sửa `highlights.json` và chạy lại:

- Đổi `start`, `end`, `zoom` hoặc `impact`: `python3 shorts.py cut <id> --only <n>` rồi `python3 shorts.py render <id> --only <n>`.
- Chỉ đổi `title`: chỉ cần `render --only <n>`; file tên cũ tự bị xoá.

Kiểm tra lại sau khi sửa.

## 6. Báo cáo và hỏi duyệt

- `open output/<id>` để mở thư mục cho người dùng xem video.
- Bảng tóm tắt: file · tiêu đề · độ dài · mốc ghi bàn.
- Nhắc `output/<id>/upload.md`: có tiêu đề, mô tả kèm ghi nguồn, và cách thêm nhạc thịnh hành trong app YouTube, canh *drop* đúng mốc ghi bàn.
- Video gốc không phải Creative Commons: thêm 1 dòng nhắc rủi ro Content ID.
- Hỏi bằng AskUserQuestion "Output ổn chưa?" với hai lựa chọn: "OK — dọn dẹp" và "Cần sửa".

## 7. Sửa theo góp ý

Người dùng nói clip nào cần sửa gì thì làm như bước 5, rồi quay lại bước 6.

Bỏ hẳn một clip: đặt `enabled: false` rồi chạy `python3 shorts.py render <id>`. Lệnh này tự xoá file của clip đó và cập nhật `upload.md`.

## 8. Dọn dẹp khi OK

Chạy `python3 shorts.py clean <id> --all`. Lệnh xoá video nguồn, audio, clip trung gian, ảnh duyệt và lịch sử HyperFrames của video này. Lệnh giữ lại `output/<id>/` (video và `upload.md`).

Xoá các file tạm đã tạo trong scratchpad (nếu có). Báo số GB đã giải phóng và kết quả `df -h .`. Nhắc người dùng: đăng xong có thể xoá `output/<id>/` để lấy lại thêm dung lượng.

## Giữ đúng lựa chọn đã có của người dùng

- Không âm thanh gốc, không phụ đề (`config.json`: `audio.original = "none"`, `style.captions = false`).
- Không ghép bài hát có bản quyền vào file. Nhạc thịnh hành do người dùng thêm trong app YouTube.
- Luôn giữ dòng `Source:` ghi nguồn trong mô tả.
- Không đề xuất crop tự bám bóng. Người dùng đã thử và chọn kiểu blur + zoom.
