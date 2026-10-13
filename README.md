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
├── socket_io_min.js      # Thư viện Socket.IO (chỉ tải khi chơi online)
├── main.py               # Máy chủ chơi online (Flask-SocketIO), đồng thời phục vụ luôn index.html để chạy nội bộ
├── requirements.txt
├── _env.example          # Mẫu cấu hình, copy thành .env
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
const CACHE = 'snake-ai-v6';   // đổi thành snake-ai-v7, v8, ...
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

## Tim trên sân

Thỉnh thoảng có một trái tim xuất hiện trên sân (nhấp nháy khi sắp biến mất). Ăn để hồi 1 tim, tối đa 10 tim. Đã đủ tim thì được cộng điểm thưởng. Khi chơi một mình, các tham số `HEARTS`, `HEARTS_MAX`, `HEART_EVERY`, `HEART_LIFE` nằm trong `CONFIG`.

## Chạy nội bộ (main.py phục vụ luôn index.html)

Không cần Vercel hay Internet: `main.py` tự trả `index.html`, `sw.js`, `question.json`, `socket_io_min.js`, `manifest.webmanifest`, `icon-*.png` ngay tại `/`. Chỉ các file trong danh sách này được trả ra (`.env`, `snake.db`, `main.py` luôn trả 404).

```bash
# .env
HOST=0.0.0.0     # để máy khác trong cùng Wi-Fi/LAN vào được (mặc định 127.0.0.1 chỉ máy này)
PORT=8888
python3 main.py
```

Khi khởi động, server in ra địa chỉ để mở, ví dụ `http://192.168.1.20:8888/`. Trang tự phát hiện đang được chính máy chủ game phục vụ (gọi `/health`) và nối Socket.IO thẳng về cùng địa chỉ, nên không cần sửa `CONFIG.SERVER_URL`. Nếu mở bằng Vercel/GitHub Pages thì vẫn dùng `SERVER_URL` như cũ.

| Biến `.env` | Mặc định | Ý nghĩa |
|---|---|---|
| `SERVE_WEB` | `true` | `false`: chỉ chạy API/Socket.IO, không phục vụ giao diện |
| `WEB_DIR` | thư mục `main.py` | Thư mục chứa `index.html` |
| `WEB_EXTRA_FILES` | (trống) | Thêm file được phép trả ra, cách nhau bằng dấu phẩy (chỉ tên file, không có `/`) |

Lưu ý: `http://192.168.x.x` không phải HTTPS nên service worker (offline) không chạy, nhưng game vẫn chơi bình thường. Muốn cài như ứng dụng hoặc offline thì mở qua `http://localhost:8888` hoặc qua tên miền Cloudflare Tunnel (HTTPS).

## Chống lag, chống giật khi mạng yếu

- **Server chỉ gửi vùng quanh người chơi** (`INTEREST_R`, mặc định 14 ô), mỗi lần gửi nhẹ hơn nhiều so với gửi cả bản đồ.
- **Tự giảm tốc theo từng máy**: client báo `ack` mỗi 0,4 giây. Máy nào nhận chậm (trễ hơn `LAG_SOFT_MS`, mặc định 1500 ms) thì server gửi thưa đi (cách 2 hoặc 4 tick một lần) thay vì dồn hàng đợi gây trễ ngày càng nặng. State là ảnh chụp đầy đủ nên bỏ bớt không mất dữ liệu.
- **Tắt thuật toán Nagle** (`TCP_NODELAY`) để gói nhỏ không bị gom chờ.
- **Client phát lại có bộ đệm tự co giãn** theo độ trễ và độ giật mạng đo được; nội suy theo đường đi của rắn (kể cả khi ảnh cách nhau nhiều tick); hết dữ liệu thì rắn tiếp tục đi theo hướng cũ tối đa 1,5 tick thay vì đứng hình.
- Mất kết nối tạm thời không còn chặn màn hình: chỉ hiện dải thông báo nhỏ rồi tự nối lại.
- Vẽ nhanh hơn (cả thân rắn vẽ bằng một đường), bỏ qua rắn ngoài màn hình, tự giảm độ phân giải canvas nếu máy yếu.
- Ô **Ping** trên màn hình cho biết độ trễ hiện tại.

Cần giảm thêm: tăng `TICK_MS` (rắn chậm hơn nhưng nhẹ mạng hơn) hoặc giảm `MAX_PLAYERS`.

## Chế độ khán giả

Bấm **Xem trực tiếp (khán giả)** ở trang đầu (hoặc **Chỉ xem** ở màn hình nhập tên). Khán giả không có rắn, không chiếm chỗ trong phòng, không ảnh hưởng điểm số.

- **Toàn cảnh**: thấy cả bản đồ 40x40 (hợp để chiếu lên máy chiếu). Màn hình nhỏ thì mặc định là chế độ theo dõi.
- **Theo dõi 1 người**: camera đi theo một rắn, mặc định là người dẫn đầu; nút mũi tên chọn người khác.
- Phím tắt: mũi tên trái/phải (hoặc A, D) đổi người; Space hoặc F đổi giữa toàn cảnh và theo dõi.
- Nút **Vào chơi** để chuyển thành người chơi; dấu X để thoát.
- Giới hạn: `MAX_SPECTATORS` (mặc định 200).

## Chơi online

Trang tĩnh (Vercel) kết nối tới máy chủ `https://snake-ai.huskydg.io.vn` qua Socket.IO. Địa chỉ này nằm ở `CONFIG.SERVER_URL` trong `index.html` (nếu trang do chính `main.py` phục vụ thì tự dùng địa chỉ đó). Thư viện Socket.IO được nạp từ `socket_io_min.js` cùng thư mục, chỉ khi thiếu mới tải từ CDN.

- Nhập tên (2 đến 16 ký tự) để vào. Tên không được trùng (không phân biệt hoa thường, không dấu) với người đang chơi.
- Cả phòng cùng thấy một câu hỏi. Ai ăn đáp án đúng trước được điểm, câu hỏi chuyển sang câu mới.
- Cắn trúng thân rắn khác: bị trừ điểm và mất 1 tim. Ăn sai đáp án mất 1 tim. Hết tim phải bấm Chơi lại.
- Bản đồ 40x40, đi xuyên tường, màn hình chỉ hiện vùng quanh rắn. Đáp án và tim ở xa được chỉ bằng ô nhỏ ở mép màn hình.

### Chạy máy chủ

```bash
cp _env.example .env      # rồi điền TUNNEL_TOKEN
python3 main.py           # tự cài thư viện từ requirements.txt nếu thiếu
```

Với Cloudflare Tunnel: vào Zero Trust > Networks > Tunnels, tạo tunnel, chép token vào `TUNNEL_TOKEN`, thêm Public hostname `snake-ai.huskydg.io.vn` trỏ về `http://127.0.0.1:8888` (khớp `HOST` và `PORT`). Kiểm tra bằng `https://snake-ai.huskydg.io.vn/health`.

Mỗi lần sửa `index.html`, nhớ tăng số phiên bản cache trong `sw.js`.
