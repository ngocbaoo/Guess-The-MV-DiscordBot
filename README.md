# Crawler — bot "đoán MV qua frame" (Vpop)

Script thu thập dữ liệu cho bot Discord đoán MV qua frame ảnh. Đầu ra cuối:
`db/bot.db` (SQLite) + frame đã curate trong `db/frames/`.

## Triết lý cốt lõi (bất biến)

**Lưu sự thật thô, diễn giải lúc chơi.** Crawler **không** tính tier độ khó,
**không** lọc năm, **không** match đáp án — chỉ thu thập (`view_count`,
`duration`, `year`, frame) và lưu. Mọi suy diễn (tier dễ/khó, lọc năm) là việc
của bot lúc runtime. Lệnh `verify` ở đây chỉ *preview* để nghiệm thu, không phải
logic bot thật.

## Cài đặt

```bash
conda activate bot
pip install -r requirements.txt
# ffmpeg phải có sẵn trên PATH (binary hệ thống, không phải pip):
ffmpeg -version
```

## Quy trình

```bash
# 1) Test logic (không cần mạng): normalize() + ingest->verify trên fixture giả
python -m pytest tests/ -q

# 2) Extract: yt-dlp lấy metadata -> build/manifest.json,
#    rồi ffmpeg range-seek frame ứng viên (KHÔNG tải video)
python crawl.py extract

# 3) Curate TAY: xem build/candidates/{id:03d}-slug/, chọn frame đẹp,
#    CHÉP sang db/frames/{id:03d}-slug/.
#    Đặt hậu tố tên file để đánh dấu openness:
#       ..._easy.jpg  -> dễ nhận ra
#       ..._hard.jpg  -> khó
#       (không hậu tố) -> normal
python crawl.py ingest    # 4) seed U manifest -> db/bot.db (drop & recreate)
python crawl.py verify    # 5) in DB + preview tier + demo lọc year
```

### Thêm bài mới (KHÔNG phải làm lại bài cũ)

`extract` **incremental**: bài nào đã có manifest entry + frame ứng viên thì tự
**bỏ qua**. Nên khi thêm bài mới vào `seed/songs.json`, chỉ bài mới được tải:

```bash
python crawl.py extract --only 6-10   # chỉ extract id 6..10 (lượt mới)
# curate tay chỉ cho bài mới...
python crawl.py ingest                # rebuild DB từ toàn bộ seed + frame (local, tức thì)
python crawl.py verify
```

- `--only` nhận **range / id / slug**: `--only 1-5`, `--only 6 7`, `--only la-lung`
  (kết hợp được: `--only 6-10 12`).
- `--force` — làm lại cả bài đã có (khi muốn refresh frame/metadata).
- Không có cờ → extract tất cả nhưng **tự skip bài đã có frame** (incremental).

> `ingest`/`verify` luôn dựng lại toàn bộ DB nhưng là thao tác **local, không
> mạng, gần như tức thì** — chạy lại với 5 hay 500 bài đều rẻ, không cần duyệt
> lại gì. Chỉ `extract` (gọi YouTube + ffmpeg) mới đắt, và nó đã tự skip bài cũ.

## Seed — `seed/songs.json`

Là **sự thật do bạn làm chủ**. Mỗi bài: `id` (cố định), `title`, `artist`,
`url`, `slug`, `aliases`, và 2 override tùy chọn:

- `year_override`: ép năm (năm lấy từ YouTube).
- `difficulty_override`: ép tier (`easy`/`medium`/`hard`), bot dùng lúc chơi.

> 5 bài mẫu đã điền sẵn URL **đề xuất** — **xác minh/sửa URL trước khi extract**
> (xem `_comment` trong từng bài). `id` cố định; folder luôn là `{id:03d}-slug`.

## Cấu trúc dữ liệu

- `build/manifest.json` — thô từ yt-dlp, key theo `id`. `view_count`/`year` có
  thể `null` (video ẩn lượt xem / ẩn ngày) — đó là hợp lệ.
- `db/bot.db` — 3 bảng: `songs`, `aliases`, `frames`. `frames.file_path` luôn
  **tương đối so với `db/`**. Không có cột difficulty tier — tier do bot tính
  từ `view_count` lúc đọc.
- `normalize()` chuẩn hóa alias (lowercase → `đ`→`d` → bỏ dấu → chỉ giữ
  `[a-z0-9 ]` → gộp khoảng trắng). "Chạy Ngay Đi" và "chay ngay di" ra cùng chuỗi.

## Cứu hộ (sự cố vận hành thường gặp)

- **`extract` lỗi hàng loạt** (yt-dlp ném lỗi): YouTube vừa đổi backend — **không
  phải bug code**. Chạy `pip install -U yt-dlp` rồi thử lại. requirements không
  pin chính vì lý do này.
- **URL stream hết hạn**: không cache, không fetch lúc runtime. Chạy lại
  `extract` để lấy URL mới.
- **Curate dở** (thiếu thư mục `db/frames/{id:03d}-slug/`): bình thường —
  `ingest` cảnh báo 0-frame chứ không sập; `verify` liệt kê bài thiếu
  frame/alias để biết phải curate tiếp.
- **Một bài lỗi**: mỗi bài bọc `try/except`, lỗi 1 bài chỉ log + bỏ qua, không
  sập cả run.

## Ràng buộc (bất biến)

- Không tải/lưu video — chỉ range-seek frame (`ffmpeg -ss` đặt **trước** `-i`).
- `id` cố định; folder = `{id:03d}-slug`; path trong db tương đối so với `db/`.
- Idempotent: `ingest` drop & recreate, chạy lại không nhân đôi alias/frame.
