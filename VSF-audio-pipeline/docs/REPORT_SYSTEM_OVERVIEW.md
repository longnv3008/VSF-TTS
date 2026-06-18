# Báo Cáo Tổng Quan Hệ Thống Audio Crawl Pipeline

## 1. Tóm tắt điều hành

Hệ thống được xây dựng để tự động thu thập và xử lý audio tiếng Việt từ YouTube theo mô hình batch. Ngoài luồng thủ công do người dùng nhập URL, hệ thống còn có discovery agent để tự tìm URL mới khi toàn bộ batch hiện tại đã hoàn thành.

Hiện tại hệ thống đã có:

- Luồng xử lý batch rõ ràng
- Cơ chế retry thông minh theo loại lỗi
- Fallback `cookie chính -> cookie backup -> guest`
- Failover `IP chính -> proxy backup`
- Logging và Telegram để theo dõi vận hành
- Discovery agent tự tạo batch mới khi hệ thống rảnh

Đánh giá tổng thể:

| Hạng mục | Đánh giá |
|---|---|
| Mức độ hoàn thiện chức năng | Tốt |
| Mức độ sẵn sàng demo/vận hành nhỏ-vừa | Tốt |
| Mức độ sẵn sàng production lớn | Trung bình |
| Rủi ro lớn nhất hiện tại | Rate limit, tuổi thọ cookie, state runtime còn ở memory |

## 2. Mục tiêu hệ thống

| Mục tiêu | Mô tả |
|---|---|
| Tự động hóa ingest | Nhận URL từ người dùng hoặc tự tìm URL mới |
| Chuẩn hóa pipeline | Crawl audio, xử lý audio, tạo translation, ghi metadata |
| Giảm thao tác thủ công | Khi batch hoàn thành, agent có thể tự tìm URL và tạo batch kế tiếp |
| Tăng độ ổn định | Có cookie fallback, proxy failover, retry thông minh |
| Tăng khả năng quan sát | Có log và Telegram cho các sự kiện vận hành quan trọng |

## 3. Kiến trúc tổng quan

| Thành phần | Vai trò |
|---|---|
| API | Nhận request ingest, retry, resume, list jobs/batches |
| PostgreSQL | Lưu batch, job, URL, trạng thái xử lý |
| Worker | Chạy nền từng job |
| Pipeline Service | Xử lý crawl, retry, proxy, cookie, normalize, translation, metadata |
| Discovery Agent | Tự tìm URL mới khi hệ thống rảnh |
| Telegram Logging | Gửi cảnh báo và sự kiện vận hành quan trọng |

Luồng tổng quát:

1. Người dùng gửi URL hoặc hệ thống tự tìm URL mới.
2. Hệ thống tạo batch và chia thành các job nhỏ.
3. Worker xử lý từng URL.
4. Sau khi batch kết thúc, discovery agent kiểm tra DB.
5. Nếu không còn job active, hệ thống tìm URL mới và tạo batch tiếp theo.

## 4. Luồng xử lý nghiệp vụ

### 4.1. Luồng thủ công

| Bước | Mô tả |
|---|---|
| 1 | Người dùng gửi danh sách URL YouTube |
| 2 | Hệ thống chuẩn hóa URL và loại bỏ URL trùng |
| 3 | Batch được chia thành nhiều job nhỏ |
| 4 | Worker xử lý từng URL trong từng job |
| 5 | Kết quả được ghi ra file và DB |

### 4.2. Luồng tự động

| Bước | Mô tả |
|---|---|
| 1 | Một batch hoàn thành thành công |
| 2 | Discovery agent được trigger |
| 3 | Agent kiểm tra DB xem còn job active không |
| 4 | Nếu hệ thống rảnh, agent đợi một khoảng ngắn |
| 5 | Agent đọc topic, tìm URL, lọc kết quả |
| 6 | Agent tạo batch mới và đẩy vào luồng xử lý hiện có |

## 5. Pipeline xử lý hiện tại

Mỗi URL hiện đi qua 5 bước chính:

| Bước | Mục đích |
|---|---|
| `validate_urls` | Chuẩn hóa và kiểm tra URL |
| `crawl_audio` | Tải audio từ YouTube |
| `normalize_audio` | Chuẩn hóa audio đầu ra |
| `build_translations` | Tạo nội dung/bản dịch |
| `build_metadata` | Ghi metadata CSV tổng hợp |

Kết quả đầu ra chính:

| Đầu ra | Mô tả |
|---|---|
| Audio raw | File audio tải về ban đầu |
| Audio processed | File audio sau chuẩn hóa |
| Translation | File nội dung/dịch phục vụ bước sau |
| Metadata CSV | File tổng hợp kết quả theo batch |

## 6. Tổ chức batch và job

| Thành phần | Ý nghĩa |
|---|---|
| Batch | Nhóm xử lý lớn |
| Job | Đơn vị thực thi nhỏ trong batch |
| Job URL | Trạng thái riêng cho từng URL |

Thiết kế này giúp:

| Lợi ích | Ý nghĩa |
|---|---|
| Retry theo URL | Không phải chạy lại toàn bộ batch |
| Resume dễ hơn | Có thể tiếp tục phần còn dở |
| Theo dõi chi tiết | Biết URL nào failed/skipped/completed |
| Chống trùng | Có thể so `video_id` trong DB |

## 7. Cơ chế cookie

Hệ thống hiện dùng 3 tầng xác thực:

| Thứ tự | Cơ chế |
|---|---|
| 1 | Cookie chính |
| 2 | Cookie backup |
| 3 | Guest session |

Luồng hoạt động:

| Tình huống | Cách xử lý |
|---|---|
| Cookie chính hợp lệ | Dùng cookie chính |
| Cookie chính lỗi/hết hạn | Chuyển sang cookie backup |
| Cookie backup cũng lỗi | Bỏ cookie và chạy guest |

Đánh giá:

| Điểm mạnh | Điểm cần lưu ý |
|---|---|
| Không fail ngay khi 1 cookie hỏng | Cookie YouTube dễ bị rotate |
| Tăng khả năng crawl nội dung khó hơn guest | Cần export cookie đúng cách |
| Có đường lui sang guest | Guest vẫn dễ bị rate limit hơn |

Khuyến nghị sử dụng:

| Khuyến nghị | Lý do |
|---|---|
| Dùng 1 account phụ riêng cho crawl | Giảm ảnh hưởng account chính |
| Duy trì 1 cookie chính + 1 cookie backup | Tăng khả năng fallback |
| Theo dõi Telegram cookie warning/error | Phát hiện sớm cookie hỏng |
| Không đổi IP quá nhiều khi đang dùng cookie | Giảm nguy cơ session bị đánh dấu bất thường |

## 8. Cơ chế proxy

Hệ thống không dùng round-robin proxy mặc định. Chiến lược hiện tại là:

| Thứ tự ưu tiên | Route |
|---|---|
| 1 | IP chính của máy/server (`direct`) |
| 2 | Proxy backup 1 |
| 3 | Proxy backup 2 |
| 4 | Proxy backup 3... |

Khi IP hiện tại bị limit:

| Bước | Cách xử lý |
|---|---|
| 1 | Đánh dấu route hiện tại bị rate limit |
| 2 | Cho route đó vào cooldown |
| 3 | Chuyển sang route backup còn sống |
| 4 | Retry lại đúng URL đang dở |

Thông số hiện tại:

| Tham số | Giá trị hiện tại |
|---|---|
| Cooldown khi bị block | `900 giây` |
| Tương đương | `15 phút` |

Đánh giá:

| Điểm mạnh | Điểm cần lưu ý |
|---|---|
| Giảm nguy cơ dừng hẳn batch khi IP chính bị limit | Nếu không có proxy backup, batch có thể phải chờ |
| Hành vi tự nhiên hơn so với xoay IP liên tục | State cooldown hiện vẫn ở memory |
| Dễ giải thích và dễ vận hành | Restart app sẽ mất trạng thái cooldown |

Khuyến nghị sử dụng:

| Tình huống | Đề xuất |
|---|---|
| Chạy nhỏ, thử nghiệm | Có thể chỉ dùng IP chính |
| Chạy liên tục | Nên có ít nhất 2-3 proxy backup |
| Dùng cookie | Nên giữ IP tương đối ổn định |
| Bị rate limit thường xuyên | Ưu tiên nâng chất lượng proxy hơn là tăng số lượng proxy xoay vòng |

## 9. Retry thông minh

Hệ thống không retry mọi lỗi theo cùng một cách.

| Nhóm lỗi | Ví dụ | Cách xử lý |
|---|---|---|
| Lỗi mạng nhẹ | timeout, reset kết nối | Retry 1 lần trên cùng route |
| Lỗi limit/bot/block | 429, bot challenge | Cooldown route, đổi route, retry lại URL |
| Lỗi auth/nội dung cứng | private, members-only | Fail/skip sớm, không retry vô ích |

Ý nghĩa:

| Lợi ích | Mô tả |
|---|---|
| Tiết kiệm tài nguyên | Không retry bừa |
| Tăng ổn định | Đổi route đúng lúc |
| Giảm spam request | Chỉ retry khi có ý nghĩa |

## 10. Discovery agent

Discovery agent là phần tự tìm URL mới sau khi batch hoàn thành.

### 10.1. Điều kiện chạy

| Điều kiện | Ý nghĩa |
|---|---|
| Batch vừa hoàn thành | Agent được trigger |
| DB không còn job `queued/running/blocked` | Agent mới thật sự đi tìm URL |

### 10.2. Nguồn chủ đề

| Nguồn | Vai trò |
|---|---|
| `topic.txt` | Nguồn topic chính |
| `DISCOVERY_SEARCH_QUERIES` | Fallback nếu không có file topic |
| `DISCOVERY_CYCLE_LIMIT_PER_START` | Giới hạn số vòng discovery trong mỗi lần start backend, `0` là không giới hạn |

### 10.3. Cơ chế quét topic

Hiện tại:

| Chỉ số | Giá trị hiện tại |
|---|---|
| Số topic trong file | `70` |
| Số topic quét mỗi vòng | `20` |
| Số URL mục tiêu mỗi vòng discovery | `20` |
| Số vòng discovery tối đa mỗi lần start backend | `0` (không giới hạn) |
| Thời gian chờ trước khi search | `5-10 giây` |

Thay vì quét toàn bộ topic mỗi lần, hệ thống dùng cửa sổ topic:

| Thành phần | Vai trò |
|---|---|
| `DISCOVERY_QUERY_WINDOW_SIZE` | Số topic quét mỗi vòng |
| `data/discovery/topic_cursor.json` | Ghi nhớ lần trước đã quét tới đâu |

Ý nghĩa:

| Điểm tốt | Mô tả |
|---|---|
| Giảm tải search | Không phải quét hết toàn bộ file topic |
| Quét công bằng hơn | Các nhóm topic đều có lượt |
| Hợp với quy mô lớn | Dễ tăng số topic sau này |

## 11. Cơ chế an toàn cho discovery

Để tránh tạo batch tự động sai thời điểm, hiện hệ thống đã có 2 lớp bảo vệ:

| Cơ chế | Ý nghĩa |
|---|---|
| Re-check DB trước khi tạo batch | Nếu user vừa thêm batch mới thì agent sẽ dừng |
| PostgreSQL advisory lock | Ngăn 2 discovery cycle cùng tạo batch một lúc |

Tác động thực tế:

| Trước đây | Hiện tại |
|---|---|
| Có khe hở tạo batch auto sai thời điểm | Rủi ro này đã giảm đáng kể |

## 12. Logging và Telegram

Hệ thống hiện có khả năng quan sát vận hành khá tốt.

### 12.1. Sự kiện đang được log/bắn Telegram

| Nhóm sự kiện | Đã có hay chưa |
|---|---|
| Batch bắt đầu/kết thúc/dừng | Có |
| Cookie warning/error/switch | Có |
| Proxy switch/rate-limited/error | Có |
| Discovery bắt đầu/tìm URL/tạo batch | Có |
| Cảnh báo quyền file/đường dẫn | Có |

### 12.2. Dữ liệu hiện có thể theo dõi

| Chỉ số/Thông tin | Theo dõi được qua log hiện tại |
|---|---|
| Batch nào completed/failed | Có |
| URL nào skipped/failed | Có |
| Cookie còn dùng được không | Có |
| Proxy có đang bị limit không | Có |
| Mỗi vòng discovery tìm được bao nhiêu URL | Có |
| Agent đang dùng topic file hay env | Có |

### 12.3. Điều chưa có đầy đủ

| Chỉ số | Trạng thái hiện tại |
|---|---|
| Thời gian trung bình mỗi batch | Chưa có dashboard tổng hợp |
| Tỷ lệ thành công/thất bại toàn hệ thống | Chưa có dashboard tổng hợp |
| Số lần switch proxy/cookie theo chu kỳ | Có log rời rạc, chưa có dashboard |
| Hiệu suất discovery theo topic | Chưa tổng hợp thành báo cáo định kỳ |

## 13. Khác biệt local và Docker

| Hạng mục | Local | Docker |
|---|---|---|
| Cookie path | `cookies/...` hoặc path tuyệt đối | `/app/cookies/...` |
| Topic file | `topic.txt` ở root project | `/app/topic.txt` trong container |
| Kết nối DB | Theo `.env` local | `postgres:5432` nội bộ Docker |
| DB host port từ máy | Tùy `.env`, thường `5434` nếu dùng DB Docker | Không dùng host port, dùng network nội bộ Docker |

Lưu ý quan trọng:

| Vấn đề | Ý nghĩa |
|---|---|
| File do Docker tạo có thể thuộc user khác | Local backend có thể không ghi đè được |
| Sai cookie path giữa local và Docker | Hệ thống sẽ rơi về guest dù file có tồn tại trên máy |

## 14. Đo lường và đánh giá vận hành hiện tại

### 14.1. Cấu hình vận hành hiện tại

| Chỉ số | Giá trị |
|---|---|
| Số URL tối đa trong 1 job | `50` |
| Số URL mục tiêu mỗi vòng discovery | `20` |
| Số topic quét mỗi vòng | `20` |
| Số vòng discovery tối đa mỗi lần start backend | `0` (không giới hạn) |
| Discovery delay | `5-10 giây` |
| Cooldown khi route bị block | `15 phút` |

### 14.2. Ý nghĩa các con số

| Chỉ số | Ý nghĩa vận hành |
|---|---|
| `50 URL/job` | Giữ mỗi job vừa phải, không quá lớn |
| `20 URL discovery` | Mỗi vòng tìm kiếm không quá nặng |
| `20 topic/vòng` | Không quét hết file topic một lúc |
| `0` vòng/start backend | Mặc định giữ discovery chạy không giới hạn, có thể đặt `10` nếu muốn chặn agent gọi quá nhiều sau mỗi lần khởi động |
| `5-10 giây` | Tránh search ngay tức thì sau khi batch vừa xong |
| `15 phút cooldown` | Cho IP bị limit có thời gian hồi lại |

### 14.3. Đánh giá ảnh hưởng thực tế

| Tình huống | Ảnh hưởng |
|---|---|
| Chỉ có 1 IP chính, không có proxy | Batch có thể bị chậm nếu bị limit |
| Có proxy backup | Hệ thống có thể tiếp tục tốt hơn |
| Cookie hỏng nhưng video public | Guest vẫn có thể cứu được |
| Topic tăng nhiều | Cần window rotation như hiện tại để tránh quét quá tải |

## 15. Điểm mạnh hiện tại

| Điểm mạnh | Ý nghĩa |
|---|---|
| Có discovery agent | Không còn phụ thuộc hoàn toàn vào URL nhập tay |
| Có retry thông minh | Tối ưu hơn retry đơn thuần |
| Có fallback cookie và guest | Giảm nguy cơ dừng sớm |
| Có failover proxy | Tăng khả năng sống khi IP chính bị limit |
| Có Telegram logging | Dễ theo dõi từ xa |
| Có bảo vệ race condition cho discovery | Giảm tạo batch sai thời điểm |

## 16. Điểm hạn chế hiện tại

| Hạn chế | Tác động |
|---|---|
| State cooldown proxy vẫn ở memory | Restart app là mất trạng thái |
| Telegram dedupe vẫn ở memory | Restart app có thể gửi lại log lặp |
| Discovery vẫn là heuristic-based | Chưa phải tìm kiếm ngữ nghĩa sâu |
| Chưa có dashboard tổng hợp | Khó báo cáo KPI nhanh |
| Quyền file local/Docker còn nhạy | Dễ phát sinh lỗi ghi file |

## 17. Đề xuất sử dụng các biện pháp hiện có

### 17.1. Khi dùng cookie

| Đề xuất | Mục tiêu |
|---|---|
| Dùng account phụ cho crawl | Giảm rủi ro cho account chính |
| Duy trì cookie chính + backup | Tăng độ bền vận hành |
| Export cookie đúng quy trình | Kéo dài thời gian dùng được |
| Theo dõi log Telegram cookie | Thay cookie kịp thời |

### 17.2. Khi dùng proxy

| Đề xuất | Mục tiêu |
|---|---|
| Luôn ưu tiên IP chính trước | Giữ hành vi tự nhiên hơn |
| Chỉ dùng proxy khi bị limit | Tránh đảo IP quá nhiều |
| Chuẩn bị 2-3 proxy backup ổn định | Giảm nguy cơ batch phải chờ |
| Không phụ thuộc hoàn toàn vào 1 proxy | Tránh nghẽn toàn bộ khi proxy lỗi |

### 17.3. Khi dùng discovery agent

| Đề xuất | Mục tiêu |
|---|---|
| Giữ `topic.txt` sạch, rõ chủ đề | Tăng chất lượng URL tìm được |
| Theo dõi số URL discovery tìm ra mỗi vòng | Đánh giá hiệu quả topic |
| Tách nhóm topic nếu chủ đề quá rộng | Dễ tối ưu hơn sau này |

## 18. Đề xuất phát triển tiếp theo

### 18.1. Ngắn hạn

| Đề xuất | Lý do |
|---|---|
| Tạo dashboard hoặc endpoint metrics | Mentor và team dễ theo dõi hiệu quả |
| Lưu lịch sử discovery theo topic/video_id | Giảm trùng lặp URL cũ |
| Theo dõi số lần switch proxy/cookie | Đo hiệu quả các biện pháp chống limit |

### 18.2. Trung hạn

| Đề xuất | Lý do |
|---|---|
| Đưa state proxy/cooldown vào DB | Bền hơn sau restart, dễ scale nhiều worker |
| Chấm điểm topic hoặc channel | Ưu tiên nguồn cho ra nội dung tốt |
| Tạo báo cáo định kỳ discovery | Đo được hiệu quả tự động tìm URL |

### 18.3. Dài hạn

| Đề xuất | Lý do |
|---|---|
| Tách discovery thành service riêng | Dễ scale độc lập |
| Dùng worker queue chuyên dụng | Phù hợp khi tải tăng mạnh |
| Bổ sung monitoring hoàn chỉnh | Quản trị production tốt hơn |

## 19. Kết luận

| Kết luận | Đánh giá |
|---|---|
| Hệ thống đã vượt mức crawl thủ công đơn giản | Đúng |
| Hệ thống đã có nền tảng bán tự động tốt | Đúng |
| Phù hợp để demo và vận hành quy mô nhỏ-vừa | Đúng |
| Cần thêm đo lường, dashboard và bền state để tiến gần production lớn | Đúng |

Tóm lại, hệ thống hiện tại đã có nền tảng tốt cho:

- ingest theo batch
- retry thông minh
- fallback cookie
- failover proxy
- discovery agent tự tạo batch tiếp theo
- logging và Telegram hỗ trợ vận hành

Bước tiếp theo nên tập trung vào:

- đo lường
- quan sát hệ thống
- độ bền state
- tối ưu hiệu quả discovery và chống rate limit ở quy mô lớn hơn
