# Sports Shorts — video dài → YouTube Shorts tự động

Đưa vào 1 link (hoặc file) trận đấu dài, pipeline sẽ:

1. **Tải** video (yt-dlp, tối đa 1080p) hoặc dùng file có sẵn
2. **Phân tích**: âm lượng mỗi 0.5s (tiếng hò reo, bình luận viên hét), điểm chuyển cảnh, lời bình luận theo từng từ (whisper)
3. **Tìm highlight**: chấm điểm từng thời điểm, chọn các đoạn hay nhất không trùng nhau
4. **Cắt dọc 9:16** (1080×1920), bỏ âm thanh gốc, thêm SFX (whoosh, bass hit, khán giả) canh đúng lúc ghi bàn
5. **Tiêu đề + hiệu ứng lúc ghi bàn** (zoom, rung, flash) bằng HyperFrames, xuất MP4. Bài nhạc thịnh hành thì ghép trong app YouTube khi đăng

## Dùng với Claude Code (khuyên dùng)

```
/make-shorts https://www.youtube.com/watch?v=XXXX 5
```

Claude chạy hết các bước bên dưới. Ở giữa, Claude duyệt hình từng clip để chốt đầu/cuối và đúng khoảnh khắc ghi bàn, rồi viết tiêu đề và tự kiểm tra video xuất ra. Cuối cùng Claude hỏi bạn output ổn chưa: cần sửa thì sửa tiếp; OK thì dọn sạch file trung gian, chỉ giữ `output/<id>/`. Skill nằm ở `.claude/skills/make-shorts/SKILL.md`.

## Chạy nhanh (không duyệt hình)

```bash
python3 shorts.py run "https://www.youtube.com/watch?v=XXXX" --count 5
```

Lệnh này không viết tiêu đề và không duyệt hình. Với video tổng hợp hay chọn lệch, nên dùng skill ở trên hoặc quy trình duyệt tay bên dưới.

Kết quả: `output/<id>/01-....mp4`, `02-....mp4`… và `output/<id>/upload.md` (gợi ý tiêu đề, mô tả, ghi nguồn).

Tuỳ chọn hay dùng: `--count 5` (số short), `--target 30` (giây mỗi short), `--mode blur|crop`, `--lang vi|en|auto` (ngôn ngữ bình luận), `--quality draft` (render nhanh để xem thử).

## Quy trình khuyên dùng (có duyệt tay)

Chạy từng bước để sửa giữa chừng — đây là chỗ tạo khác biệt cho kênh:

```bash
python3 shorts.py download "https://www.youtube.com/watch?v=XXXX"   # in ra <id>
python3 shorts.py analyze <id> --lang en
python3 shorts.py detect <id> --count 6
```

Mở `work/<id>/highlights.json` và ảnh xem nhanh `work/<id>/thumbs/NN.jpg` (đầu | đỉnh | cuối). Muốn xem kỹ hơn thì dùng ảnh lưới:

```bash
python3 shorts.py sheet <id> 190 230            # 2 khung/giây từ giây 190 đến 230 của video gốc
python3 shorts.py sheet <id> 202 206 --fps 8    # tìm đúng khung bóng vào lưới → impact
python3 shorts.py sheet <id> --output 2         # xem lại short 02 đã render
```

Ảnh lưu ở `work/<id>/sheets/`, đọc trái→phải, trên→dưới. Lệnh in giờ bắt đầu của mỗi hàng; mỗi ô cách nhau 1/fps giây.

Các trường trong `highlights.json`:

| Trường | Ý nghĩa |
| --- | --- |
| `enabled` | `false` để bỏ clip |
| `start` / `end` | giây trong video gốc — chỉnh để bắt đầu sớm/muộn hơn |
| `title` | tiêu đề hook hiện trên video (kênh tiếng Anh: viết tiếng Anh) |
| `impact` | giây (trong video gốc) bóng vào lưới — mốc cho zoom/flash/bass/khán giả. `null` = tự đoán từ tiếng hô "goal" (với video tổng hợp hay lệch, nên đặt tay) |
| `music` | (khi `audio.music = true`) tên/tiêu đề bài trong `assets/music/library.json` (vd `"epic"`), `"none"` để tắt, trống = tự xoay vòng |
| `mode` | `blur` (mặc định) · `crop` — xem "Hai kiểu khung dọc" |
| `zoom` | (blur) phóng to khung 16:9, cắt bớt 2 bên; video Fad3nHD đang dùng 1.55 |
| `mode`, `zoom`, `crop_x`, `offset_y` | ghi đè cách cắt dọc cho riêng clip này |

```bash
python3 shorts.py cut <id>                 # hoặc --only 1,3
```

Sửa phụ đề trong `work/<id>/clips/NN/captions.json`: sửa trường `text` của từng dòng (thời gian từng từ tự chia lại), xoá dòng để bỏ. Cắt lại mà không đổi `start/end` thì file này được giữ nguyên. Mỗi lần `cut`, ảnh `thumbs/NN.jpg` được tạo lại theo khung và `impact` mới.

```bash
python3 shorts.py render <id> --quality draft --only 1   # xem thử nhanh
python3 shorts.py render <id>                            # bản cuối
```

`render` giữ `output/<id>/` khớp với `highlights.json`. Đổi `title` thì file tên cũ bị xoá. Clip đặt `enabled: false` thì file của nó bị xoá và `upload.md` được viết lại.

Muốn chỉnh tay bằng giao diện kéo-thả: `npx hyperframes preview work/<id>/clips/01`.

Mẹo: nhờ Claude đọc `highlights.json` + ảnh thumbs để viết tiêu đề tiếng Việt cuốn hút và dịch `captions.json` sang tiếng Việt trước khi render.

## Âm thanh & hiệu ứng

Mặc định (`config.json` → `audio`): **bỏ hết âm thanh gốc, không phụ đề**, file xuất ra chỉ có hiệu ứng, và bạn **ghép bài thịnh hành trong app YouTube** khi đăng.

| Lớp | Nguồn | Ghi chú |
| --- | --- | --- |
| SFX | `assets/sfx/` | whoosh khi tiêu đề hiện; swell dâng lên → bass hit đúng `impact`; khán giả (CC0) dâng dần rồi gầm ngay sau bàn thắng |
| Hình | template | zoom 1.14× + rung + flash trắng tại `impact` |
| Nhạc | **thêm trong app** | `upload.md` ghi mốc ghi bàn (vd `0:07.6`) để canh *drop* của bài + danh sách gợi ý |

File chỉ có hiệu ứng được để ở −18 LUFS để bài hát thêm trong app át lên. Vì sao không ghép sẵn bài thịnh hành vào file: thêm trong app thì YouTube tự lo bản quyền (chia doanh thu) và Short được gắn vào trang của âm thanh đó, nhờ vậy mới ăn theo trend. Ghép sẵn bài có bản quyền vào file thì bị Content ID claim/chặn và không được tính vào trend.

Các chế độ khác:

| Tuỳ chọn | Giá trị |
| --- | --- |
| `audio.original` | `"none"` bỏ tiếng gốc · `"voice"` giữ bình luận + cổ động viên, bỏ nhạc gốc (Demucs) · `"full"` giữ nguyên |
| `audio.music` | `true` = nhúng sẵn nhạc CC0 từ `assets/music/` (tự hạ khi có bình luận, tắt 0.6s lúc ghi bàn), dùng khi đăng từ máy tính |
| `audio.ambience` | `true` = thêm nền sân vận động (CC0) |
| `style.captions` | `true` = bật phụ đề karaoke lời bình luận |

Có giọng hoặc nhạc thì bản cuối được nén nhẹ và chuẩn hoá −14 LUFS. Ghi công nhạc/âm thanh CC0 tự động vào `upload.md`. Danh sách bài gợi ý nằm ở `upload.sound_suggestions`. Đó là danh sách tham khảo (10/2026), nên xem mục *Thịnh hành* trong app.

Chế độ `"voice"` cần Demucs trong `.venv` (~630 MB, Python 3.14 vì torch chưa có bản cho 3.15):

```bash
brew install python@3.14
/opt/homebrew/opt/python@3.14/bin/python3.14 -m venv .venv && .venv/bin/pip install torch torchaudio demucs numpy soundfile
```

Python 3.14 phải được cài bằng `brew install` như trên. Nếu nó chỉ là phụ thuộc của gói khác, Homebrew có thể tự gỡ khi nâng cấp (từng xảy ra khi `brew upgrade yt-dlp` chuyển sang 3.15), làm `.venv` hỏng. Kiểm tra: `python3 -c "from pipeline import audio; print(audio.demucs_available())"`.

## Hai kiểu khung dọc

- **blur** (mặc định): giữ nguyên toàn bộ khung 16:9 ở giữa, nền là chính video làm mờ; tiêu đề ở trên, phụ đề ở dưới. An toàn cho bóng đá/góc quay rộng. Tăng `zoom` (1.3–1.6) để hình to hơn nhưng mất 2 mép.
- **crop**: phủ kín màn hình, giữ lát cắt 9:16 tại `crop_x` (0 = trái, 0.5 = giữa, 1 = phải). Hợp với cận cảnh, bóng rổ, võ thuật, tennis — không hợp góc rộng bóng đá vì bóng hay ra khỏi khung.

## Cấu hình — `config.json`

- `highlights.keywords`: từ khoá bình luận được cộng điểm (Anh + Việt). Thêm từ theo môn của bạn.
- `highlights.weights`: trọng số âm lượng / từ khoá / dồn cảnh (replay).
- `highlights.max_seconds`: giữ ≤ 58. Short dài hơn 60s mà dính Content ID sẽ bị **chặn toàn cầu**.
- `highlights.pre_roll_ratio`: 0.55 = 55% thời lượng nằm trước khoảnh khắc đỉnh.
- `style`: màu nhấn, màu dải tiêu đề, `channel_handle` (vd `"@tenkenh"` hiện mờ trên cùng), `captions: false` để tắt phụ đề.
- `render.fps`: 30 (60 đẹp hơn cho thể thao nhưng render lâu gấp đôi).

## Cấu trúc thư mục

```
shorts.py            lệnh chính
config.json          cấu hình mặc định
pipeline/            download · analyze · highlights · cut · audio · render · review (sheet)
template/index.html  giao diện tiêu đề + phụ đề (HyperFrames)
assets/              nhạc + SFX CC0/Pixabay, giấy phép trong library.json
.claude/skills/      skill /make-shorts cho Claude Code
work/<id>/           dữ liệu trung gian (source, audio, highlights.json, clips/NN/, sheets/, .hf-history/)
output/<id>/         video Shorts cuối + upload.md
```

## Ổ đĩa

Kiểm tra bằng `df -h .`. Một trận 90 phút 1080p ≈ 1.5–3 GB; `.venv` (Demucs) chiếm ~630 MB. Sau khi xong:

```bash
python3 shorts.py clean <id>         # xoá source + audio, giữ clip đã cắt (vẫn render lại được) và output
python3 shorts.py clean <id> --all   # xoá cả work/<id> + lịch sử HyperFrames, chỉ giữ output
```

HyperFrames lưu lịch sử hoàn tác của mỗi clip, gồm một bản sao `clip.mp4` cho mỗi lần cắt lại. Lịch sử này đã được chuyển vào `work/<id>/.hf-history/` nên `clean --all` xoá luôn. Các clip render trước thay đổi này, hoặc mở bằng `hyperframes preview`, thì lịch sử nằm ở `~/.cache/hyperframes/history/`; `clean --all` cũng tìm và xoá đúng phần của video đó.

## Tốc độ (đo trên M4, video giả lập 3 phút)

Phân tích ~30s · cắt 2 clip ~8s · render ~25s mỗi short 30s (`draft` ~16s). Toàn bộ: ~1.5 phút. Trận 90 phút: phần whisper tốn nhiều nhất (ước vài phút, theo dõi `work/<id>/whisper.log`).

## Giới hạn đã biết

- Highlight dựa vào **âm thanh và lời bình luận**. Video không có bình luận/khán giả (camera tập luyện, nhạc nền phủ kín) sẽ chọn kém — khi đó chỉnh `start/end` tay.
- Với **video tổng hợp** (đã cắt ghép sẵn), tiếng hô "goal" thường bị dời so với hình và một đoạn 30s có thể lẫn sang trận khác: luôn xem `thumbs/NN.jpg`, chỉnh `start/end/impact` trước khi cắt.
- Chế độ crop cắt cố định, **chưa bám theo bóng/cầu thủ**.
- Whisper có thể nghe sai tên cầu thủ — xem lại `captions.json`.
- Nên cập nhật yt-dlp thường xuyên vì YouTube hay đổi: `brew upgrade yt-dlp`.

## Bản quyền — đọc trước khi đăng

Cắt lại cảnh quay thi đấu của đài/giải đấu (Premier League, NBA, UEFA, V-League…) gần như chắc chắn bị **Content ID** nhận diện: bị chặn, mất doanh thu, hoặc strike (3 strike = mất kênh). Thêm phụ đề và tiêu đề **không** đủ để được coi là nội dung mới theo chính sách "reused content" của YouTube Partner Program.

Nguồn an toàn: video của chính bạn, giải phong trào/địa phương có sự đồng ý của người quay, video có giấy phép **Creative Commons** (bước `download` tự báo giấy phép), hoặc nguồn bạn được cấp phép. Muốn kiếm tiền bền vững thì nên thêm giá trị riêng: bình luận/thuyết minh, phân tích chiến thuật, so sánh số liệu.
