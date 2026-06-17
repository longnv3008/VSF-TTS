# Kiểm thử và Cấu hình Voice Activity Detection (VAD) với Triton Server

## Bối cảnh & Mục tiêu dự án
Dự án sử dụng Triton Inference Server chạy mô hình **Silero V5 VAD** (`models/vad/1/vad.onnx`) kết hợp với thuật toán tính toán Âm lượng (Volume detection + Exponential smoothing) để phát hiện lượt nói (Turn detection) của người dùng:
- Nhận biết khi nào người dùng bắt đầu nói (`SPEAKING`).
- Nhận biết khi nào người dùng dừng nói (`QUIET`).
- Đây không chỉ đơn thuần là phân loại khung âm thanh (speech/nonspeech) mà là nhận diện sự kiện theo lượt (turn-based event detection).

## Dữ liệu kiểm thử (Test Data)
1. **API TTS Vinbase**: Dùng để tự sinh dữ liệu kiểm thử bằng lệnh `curl` gửi tới `https://dev-cloud.vinbase.ai/api/v2/tts/sync`.
   - Danh sách các speaker cấu hình cho tham số `style_speaker` nằm ở file [spakers.txt](file:///e:/VSF/TTS/spakers.txt).
2. **File lỗi thực tế**: File [clone_nam_6_tuoi-98-clone_nam_6_tuoi.wav](file:///e:/VSF/TTS/clone_nam_6_tuoi-98-clone_nam_6_tuoi.wav) là file ghi nhận lỗi phát hiện sai với VAD hiện tại. Đây là file testcase trọng tâm cần debug.
3. **Thư mục mẫu**: Thư mục [tmp/](file:///e:/VSF/TTS/tmp) chứa 67 file âm thanh sinh ra từ TTS để chạy thử nghiệm hàng loạt (batch test).

## Kiến trúc Triton VAD Server
- **Model Backend**: Python backend. Cấu hình tại [config.pbtxt](file:///e:/VSF/TTS/VAD/models/vad/config.pbtxt) và code logic xử lý tại [model.py](file:///e:/VSF/TTS/VAD/models/vad/1/model.py), [vad.py](file:///e:/VSF/TTS/VAD/models/vad/1/vad.py).
- **Các tham số cấu hình chính**:
  - `threshold` (mặc định `0.8`): Ngưỡng tin cậy của mô hình VAD Silero.
  - `min_volume` (mặc định `0.75`): Ngưỡng âm lượng tối thiểu để coi là giọng nói.
  - `start_secs` (mặc định `0.15`): Thời gian nói tối thiểu để kích hoạt trạng thái bắt đầu lượt nói (`SPEAKING`).
  - `stop_secs` (mặc định `0.45`): Thời gian im lặng tối thiểu để kết thúc lượt nói (`QUIET`).

## Các bước thực hiện

### 1. Phục vụ Triton Server
- Xây dựng Docker Image cho VAD server:
  ```bash
  docker build -f Dockerfile -t vad-server .
  ```
- Khởi chạy container:
  ```bash
  docker run -e TF_CPP_MIN_LOG_LEVEL=1 --shm-size=4096m -e DEBUG=true -d --name vad-server -v ./logs:/logs -it -p8001:8001 vad-server
  ```

### 2. Kiểm thử & Debug với file lỗi cụ thể
- Chạy kiểm thử trên file lỗi [clone_nam_6_tuoi-98-clone_nam_6_tuoi.wav](file:///e:/VSF/TTS/clone_nam_6_tuoi-98-clone_nam_6_tuoi.wav) bằng [client.py](file:///e:/VSF/TTS/VAD/client.py):
  ```bash
  python3 client.py 127.0.0.1:8001 ../clone_nam_6_tuoi-98-clone_nam_6_tuoi.wav
  ```
- Ghi nhận logs, phân tích các giá trị xác suất VAD (`probs`) và âm lượng (`volume`) của từng frame để xem tại sao turn detection bị sai lệch.

### 3. Kiểm thử hàng loạt trên thư mục tmp/
- Viết script tự động chạy qua toàn bộ 67 file trong thư mục [tmp/](file:///e:/VSF/TTS/tmp) để đánh giá tỷ lệ phát hiện turn của mô hình VAD hiện tại.

### 4. Tối ưu hóa & Hiệu chỉnh tham số
- Điều chỉnh các thông số `min_volume`, `threshold`, `start_secs`, và `stop_secs` để khắc phục lỗi phát hiện sai trên file `clone_nam_6_tuoi-98-clone_nam_6_tuoi.wav` mà không làm ảnh hưởng đến độ chính xác của các file test khác.

## Kế hoạch Xác minh (Verification Plan)

### Kiểm thử thủ công (Manual Verification)
- Xác nhận file [clone_nam_6_tuoi-98-clone_nam_6_tuoi.wav](file:///e:/VSF/TTS/clone_nam_6_tuoi-98-clone_nam_6_tuoi.wav) được phát hiện đúng thời điểm bắt đầu/kết thúc sau khi điều chỉnh tham số.
- Đảm bảo các file trong thư mục [tmp/](file:///e:/VSF/TTS/tmp) không bị suy giảm chất lượng nhận diện lượt nói.
