# Rắn Săn Đáp Án AI

Game rắn săn mồi giúp học sinh ôn trắc nghiệm về trí tuệ nhân tạo (AI). Game chạy hoàn toàn trên trình duyệt, **không cần máy chủ, không cần mạng sau lần mở đầu tiên**, chơi được trên điện thoại, iPad và máy tính.

## Cách chơi

- Phía trên màn hình là câu hỏi cùng 4 đáp án **A, B, C, D**, mỗi đáp án có một màu riêng.
- Trên sân có các ô vuông cùng màu và chữ cái tương ứng. Điều khiển rắn ăn ô của đáp án mà em cho là đúng.
- Ăn đúng: **+10 điểm**, rắn dài thêm. Trả lời đúng liên tiếp được thưởng thêm điểm, và rắn chạy nhanh dần.
- Ăn sai: **mất 1 tim**, sau đó game hiện đáp án đúng kèm lời giải thích để em học.
- Cắn trúng đuôi: cũng mất 1 tim. Rắn đi xuyên tường nên không bị đụng tường (có thể đổi trong cấu hình).
- Hết 3 tim thì thua. Điểm cao nhất và top 5 lần chơi gần nhất được lưu ngay trên máy.

### Điều khiển

| Thiết bị | Cách điều khiển |
|---|---|
| Điện thoại, iPad | Nút mũi tên ảo trên màn hình, hoặc vuốt lên, xuống, trái, phải |
| Máy tính | Phím mũi tên hoặc W, A, S, D |
| Tạm dừng | Nút tạm dừng ở góc trên, hoặc phím Space, P |

Nút mũi tên ảo luôn hiện, kể cả khi iPad có gắn bàn phím.

## Cấu trúc thư mục

```
snake-ai/
├── index.html            # Toàn bộ giao diện và logic game
├── question.json         # Bộ câu hỏi (sửa file này để thêm, đổi câu hỏi)
├── sw.js                 # Service worker, giúp game chạy offline
├── manifest.webmanifest  # Cho phép cài game như một ứng dụng
├── icon-192.png
└── icon-512.png
```

## Chạy thử trên máy tính

Service worker chỉ hoạt động qua **HTTPS** hoặc `localhost`, nên đừng mở trực tiếp `index.html` bằng cách bấm đúp vào file. Hãy chạy một máy chủ tĩnh trong thư mục dự án:

```bash
cd snake-ai
python3 -m http.server 8000
```

Sau đó mở `http://localhost:8000` bằng trình duyệt.

## Đưa lên mạng để dùng trên điện thoại, iPad

Đưa cả thư mục lên một dịch vụ hosting tĩnh có HTTPS, ví dụ GitHub Pages, Netlify hoặc Cloudflare Pages. Sau khi có đường dẫn:

1. Mở đường dẫn một lần khi có mạng. Game tự lưu toàn bộ file vào máy.
2. Từ lần sau, game mở và chơi được cả khi mất mạng.

### Cài như một ứng dụng

- **iPad, iPhone:** mở bằng Safari, bấm Chia sẻ, chọn **Thêm vào Màn hình chính**.
- **Android:** mở bằng Chrome, chọn menu rồi **Cài đặt ứng dụng** (hoặc **Thêm vào màn hình chính**).

Lưu ý: mở game qua địa chỉ mạng nội bộ dạng `http://192.168.x.x` thì offline sẽ không hoạt động vì không phải HTTPS.

## Thêm hoặc sửa câu hỏi

Câu hỏi nằm trong `question.json`, là một mảng JSON, mỗi câu có dạng:

```json
{
  "question": "Dữ liệu (data) là gì?",
  "correct": "Thông tin như chữ, ảnh, âm thanh, con số",
  "wrong": ["Một loại nhạc cụ", "Một loại đồ ăn vặt", "Một loại cây trong vườn"],
  "explanation": "Dữ liệu là thông tin mà máy tính có thể lưu giữ và xử lý."
}
```

| Trường | Bắt buộc | Ý nghĩa |
|---|---|---|
| `question` | Có | Nội dung câu hỏi |
| `correct` | Có | Đáp án đúng |
| `wrong` | Có | Danh sách đáp án sai, từ 1 đến 3 đáp án. Nếu nhiều hơn 3, game chọn ngẫu nhiên 3 |
| `explanation` | Không | Lời giải thích, hiện khi em ăn sai hoặc hết tim |

Một số lưu ý:

- Mỗi lần chơi, vị trí các đáp án A, B, C, D được xáo ngẫu nhiên, và các câu hỏi không lặp lại cho đến khi đã hỏi hết cả bộ.
- Nên giữ câu hỏi dưới khoảng 120 ký tự và đáp án dưới khoảng 60 ký tự để hiển thị gọn trên điện thoại.
- Sau khi sửa file, hãy kiểm tra cú pháp JSON (ví dụ bằng jsonlint.com). Sai một dấu phẩy là game sẽ không đọc được file và quay về vài câu hỏi mẫu.
- Game cũng chấp nhận file có dạng `{ "questions": [ ... ] }`.

## Cập nhật bản mới trên các thiết bị đã cài

Service worker ưu tiên dùng bản đã lưu để mở nhanh và chạy offline. Vì vậy sau khi sửa `index.html`, `question.json` hoặc file khác, hãy **tăng số phiên bản** trong `sw.js`:

```js
const CACHE = 'snake-ai-v3';   // đổi thành snake-ai-v4, v5, ...
```

Lần mở tiếp theo khi có mạng, thiết bị sẽ tải bản mới. Nếu chưa thấy thay đổi, hãy đóng hẳn ứng dụng rồi mở lại.

## Tùy chỉnh game

Ở đầu phần `<script>` trong `index.html` có khối `CONFIG`:

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `COLS`, `ROWS` | 16, 16 | Kích thước sân |
| `HEARTS` | 3 | Số tim ban đầu |
| `POINTS` | 10 | Điểm khi ăn đúng |
| `STREAK_BONUS` | 2 | Điểm thưởng thêm cho mỗi câu đúng liên tiếp |
| `STREAK_BONUS_MAX` | 5 | Số lần thưởng tối đa |
| `GROW` | 2 | Số đốt rắn dài thêm sau mỗi câu đúng |
| `SPEED_START` | 170 | Thời gian mỗi bước, tính bằng ms (càng nhỏ rắn càng nhanh) |
| `SPEED_MIN` | 90 | Tốc độ nhanh nhất |
| `SPEED_STEP`, `SPEED_EVERY` | 8, 4 | Cứ mỗi 4 câu đúng, rắn nhanh hơn 8 ms |
| `WALL_WRAP` | `true` | `true`: đi xuyên tường. `false`: đụng tường mất 1 tim |
| `MIN_SPAWN_DIST` | 4 | Khoảng cách tối thiểu từ đầu rắn đến các ô đáp án khi xuất hiện |

## Dữ liệu lưu trên máy

Game dùng `localStorage` của trình duyệt với các khóa sau:

- `snakeai.best`: điểm cao nhất
- `snakeai.history`: top 5 điểm gần nhất
- `snakeai.sound`: bật hoặc tắt âm thanh

Muốn xóa điểm, hãy xóa dữ liệu trang web của game trong cài đặt trình duyệt. Dữ liệu chỉ nằm trên từng thiết bị, không gửi đi đâu cả.

## Trình duyệt hỗ trợ

Các trình duyệt hiện đại như Safari (iPadOS, iOS 14 trở lên), Chrome, Edge, Firefox. Game không dùng thư viện ngoài và không tải font từ mạng.