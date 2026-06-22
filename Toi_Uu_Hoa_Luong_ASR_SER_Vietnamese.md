Tối ưu hóa Toàn diện Luồng Nhận dạng Giọng nói và Cảm xúc Tiếng Việt: Giải pháp Khắc phục Ảo giác và Nâng cao Độ chính xác đa Nhãn

Tổng quan thách thức nhận dạng đa nhiệm trong môi trường hội thoại

Trong các hệ thống tương tác giọng nói thế hệ mới, việc xử lý đồng thời hai nhiệm vụ nhận dạng giọng nói tự động (ASR) và nhận dạng cảm xúc giọng nói (SER) đang trở thành tiêu chuẩn cốt lõi.[1] Theo khuôn khổ chiến dịch đánh giá VLSP, hệ thống được yêu cầu phân tích một tệp âm thanh đầu vào để đưa ra hai nhãn đầu ra song song: chuỗi văn bản được nhận dạng và nhãn cảm xúc tương ứng, phân chia chủ yếu thành hai trạng thái là "trung tính" (neutral) và "tiêu cực" (negative).[1] Mô hình đánh giá hiệu năng dựa trên hai chỉ số chính là Tỷ lệ lỗi âm tiết ( $SyER_{ASR}$ ) và Độ chính xác nhận dạng cảm xúc ( $ACC_{SER}$ ).[1] Công thức xác định tỷ lệ lỗi âm tiết được mô tả cụ thể như sau: $$SyER_{ASR} = \frac{S + D + I}{N} \times 100%$$Trong đó $S$ đại diện cho số lượng âm tiết bị thay thế, $D$ là số lượng âm tiết bị xóa bỏ, $I$ là số lượng âm tiết bị chèn thêm, và $N$ là tổng số âm tiết trong chuỗi văn bản gốc.[1] Đối với nhãn cảm xóc, độ chính xác được tính toán độc lập cho từng nhóm trạng thái cảm xúc để đảm bảo tính khách quan trước sự mất cân bằng dữ liệu [1]:$$ACC_{SER} = \frac{NEU_{Corr} + NEG_{Corr}}{NEU + NEG} \times 100%$$ Thách thức lớn nhất hiện nay đối với luồng xử lý này là sự xuất hiện của các nhãn văn bản rác hoặc các phân đoạn nhận dạng sai lệch nghiêm trọng khi tệp âm thanh đầu vào chứa khoảng lặng kéo dài, nhiễu nền phức tạp hoặc các đoạn hội thoại tự nhiên có mật độ ngắt quãng cao.[2, 3] Hiện tượng này không chỉ làm tăng vọt chỉ số $SyER_{ASR}$ mà còn gián tiếp làm sai lệch kết quả phân tích đặc trưng âm học của mô hình SER, dẫn đến sự sụt giảm nghiêm trọng của cả hai nhãn đầu ra.[1, 2]

Phân tích căn nguyên hiện tượng ảo giác và lỗi nhãn văn bản rác

Sự suy giảm độ chính xác của nhãn văn bản (tạo ra văn bản rác hoặc lặp từ liên tục) xuất phát từ ba nguyên nhân kỹ thuật cốt lõi liên quan đến kiến trúc mô hình, cấu hình giải mã và sự không tương thích với quy chuẩn định dạng đầu ra.[1, 4]

Cơ chế hoạt động tự hồi quy của bộ giải mã dựa trên chú ý
Các mô hình ASR tiên tiến như họ mô hình Whisper được huấn luyện dựa trên kiến trúc Encoder-Decoder với cơ chế tự hồi quy (autoregressive).[4] Khác với các kiến trúc kết nối thời gian tuyến tính (CTC) hoặc Transducer vốn được thiết kế để xuất ra các token trống (blank tokens) khi gặp khoảng lặng, bộ giải mã của Whisper hoạt động tương tự như một mô hình ngôn ngữ lớn (LLM).[4] Khi năng lượng âm thanh đầu vào tiến dần về mức không (khoảng lặng tuyệt đối hoặc nhiễu trắng), vectơ biểu diễn âm học (audio embeddings) không mang thông tin hữu ích.[5] Lúc này, bộ giải mã tự hồi quy sẽ dựa hoàn toàn vào phân phối xác suất của ngôn ngữ đã học từ tập huấn luyện (phần lớn là các phụ đề video từ YouTube) để tự động "điền vào chỗ trống".[2, 4] Hệ quả là mô hình tự sinh ra các cụm từ phổ biến như lời chào, lời cảm ơn, yêu cầu đăng ký kênh hoặc các câu thoại không tồn tại trong thực tế.[3, 4]

Sự lan truyền lỗi do ngữ cảnh lịch sử
Khi cấu hình giải mã kích hoạt tính năng điều kiện hóa dựa trên văn bản trước đó, một lỗi ảo giác nhỏ xuất hiện ở phân đoạn trước sẽ được đưa ngược lại làm gợi ý đầu vào (prompt) cho phân đoạn tiếp theo.[4] Cơ chế phản hồi này tạo ra một vòng lặp phản hồi tích cực (feedback loop), khiến bộ giải mã liên tục lặp lại một cụm từ duy nhất trên nhiều phân đoạn âm thanh tiếp theo, ngay cả khi người dùng đã dừng nói.[4, 5]

Sự không tương thích với quy ước chuẩn hóa văn bản của VLSP
Một phần lớn lượng "rác" trong nhãn văn bản thực chất là các lỗi chính tả và lỗi định dạng không tuân thủ các quy ước nghiêm ngặt của hệ thống đánh giá.[1] Các mô hình ASR thông thường thường tự động phiên âm các từ tiếng Anh hoặc tên riêng theo dạng phiên âm âm học tiếng Việt, hoặc sử dụng các ký tự đặc biệt để phân tách từ viết tắt.[1] Việc không áp dụng một bộ chuẩn hóa đầu ra chuyên biệt sẽ trực tiếp làm tăng số lượng lỗi thay thế ( $S$ ) và lỗi chèn ( $I$ ) trong công thức tính $SyER_{ASR}$ .[1]

Tái cấu trúc luồng xử lý: Chuyển đổi từ hợp nhất sang phân rã

Để khắc phục triệt để hiện tượng suy giảm độ chính xác chéo giữa nhãn văn bản và nhãn cảm xúc, giải pháp tối ưu là chuyển đổi từ kiến trúc mô hình hợp nhất (Joint Multitask Model) sang kiến trúc phân rã (Decoupled Pipeline).[1] Mặc dù việc sử dụng một mô hình duy nhất cho cả hai nhiệm vụ có vẻ tối giản về mặt cấu trúc, các nghiên cứu thực nghiệm chỉ ra rằng sự can thiệp của các đặc trưng ngữ nghĩa văn bản có thể làm nhiễu loạn các bộ lọc đặc trưng tần số thấp của mô hình SER.[1] Việc phân rã hệ thống thành hai nhánh độc lập hoạt động song song cho phép tối ưu hóa chuyên sâu từng thành phần mà không gây ảnh hưởng tiêu cực lẫn nhau.[1]

Trong luồng xử lý phân rã, tín hiệu âm thanh sau khi đi qua cổng kiểm soát hoạt động giọng nói (VAD) và bộ lọc nhiễu sẽ được nhân bản thành hai luồng dữ liệu độc lập.[2, 4] Nhánh thứ nhất chuyển dữ liệu đến bộ nhận dạng giọng nói chuyên dụng, trong khi nhánh thứ hai chuyển dữ liệu đến bộ phân loại cảm xúc (SER) dựa trên các kiến trúc trích xuất đặc trưng âm học mạnh mẽ như wav2vec2-base-vi.[1, 6] Mô hình phân loại cảm xúc được tinh chỉnh chuyên biệt để nhận diện các trạng thái "neutral" và "negative" từ phổ âm thanh thô, hoàn toàn không bị ảnh hưởng bởi lỗi giải mã của nhánh ASR.[1, 20]

Thay thế công nghệ: Lựa chọn mô hình ASR và SER tối ưu cho tiếng Việt

Việc lựa chọn mô hình thay thế đóng vai trò quyết định trong việc cải thiện độ chính xác toàn diện của luồng pipeline.[7, 8] Dưới đây là bảng so sánh chi tiết các công nghệ nhận dạng giọng nói tiếng Việt SOTA nhất trong giai đoạn 2025 - 2026:

| Tên mô hình | Số lượng tham số | Kiến trúc cốt lõi | Khả năng kháng ảo giác khoảng lặng | Miền ứng dụng tối ưu | Ràng buộc bản quyền |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Gipformer-65M-rnnt [7] | 65 Triệu [7] | Zipformer Transducer [7] | Tuyệt đối (Do đặc thù cơ chế hoạt động của bộ giải mã Transducer) [4] | Tổng đài tài chính, y tế, viễn thông; hỗ trợ đa giọng địa phương và lọc nhiễu đường truyền thoại tốt.[7] | Thương mại tự do / On-premise [7] |
| Zipformer-30M-RNNT-6000h [8, 9] | 30 Triệu [8] | Zipformer Transducer [8, 9] | Tuyệt đối [4] | Thiết bị nhúng, ứng dụng di động ngoại tuyến, hệ thống yêu cầu độ trễ cực thấp.[8] | CC-BY-NC-ND-4.0 (Phi thương mại) [10] |
| PhoWhisper-medium [11] | 769 Triệu [11] | Encoder-Decoder Transformer [11] | Thấp (Cần có sự hỗ trợ của cổng VAD ngoại vi) [2, 4] | Hội thoại tự nhiên, podcast, phân tích ngữ cảnh hội thoại sâu.[11] | MIT (Mở rộng tự do) [11] |

Ưu thế vượt trội của kiến trúc Zipformer Transducer (Gipformer)
Đối với các ứng dụng thực tế yêu cầu tính ổn định cao và loại bỏ hoàn toàn văn bản rác, các mô hình dựa trên kiến trúc Zipformer Transducer như gipformer-65M-rnnt thể hiện sự vượt trội rõ rệt.[7] Nhờ cơ chế hoạt động của bộ giải mã Transducer (RNN-T), mô hình chỉ sinh ra token văn bản khi và chỉ khi có sự xuất hiện đồng thời của tín hiệu căn chỉnh thời gian từ bộ mã hóa âm thanh.[4, 7] Khi gặp khoảng lặng, mô hình sẽ liên tục phát ra token trống mà không cần áp dụng bất kỳ thuật toán hậu xử lý phức tạp nào, loại bỏ hoàn toàn khả năng phát sinh ảo giác tự hồi quy.[4] Hơn nữa, with dung lượng cực nhẹ chỉ 65 triệu tham số, mô hình dễ dàng đạt tốc độ xử lý thời gian thực trên các CPU phổ thông.[7]

Tối ưu hóa mô hình nhận dạng cảm xúc giọng nói (SER)
Đối với nhánh SER, thay vì sử dụng các đặc trưng thủ công như MFCC, việc sử dụng các mô hình tự giám sát (self-supervised) như wav2vec2-base-vi làm bộ trích xuất đặc trưng nền tảng mang lại hiệu năng vượt trội.[6] Mô hình này đã học được cấu trúc âm học tiếng Việt phong phú qua hàng trăm giờ dữ liệu đa giọng điệu.[6] Khi được tinh chỉnh bằng một đầu phân loại tuyến tính (linear classification head) trên tập dữ liệu cảm xúc của VLSP, mô hình có khả năng trích xuất các biến đổi cao độ, nhịp điệu và năng lượng biểu cảm một cách chính xác [1, 6], giúp chỉ số $ACC_{SER}$ duy trì ở mức cao ngay cả trong môi trường có nhiễu nền.[1, 12]

Giải pháp kỹ thuật loại bỏ văn bản rác và tối ưu hóa tham số giải mã

Để giải quyết triệt để lỗi sinh văn bản rác từ các mô hình ASR hiện tại mà không cần thay đổi hoàn toàn kiến trúc phần cứng, hệ thống cần áp dụng đồng bộ ba lớp phòng ngự: tiền xử lý âm thanh, kiểm soát tham số giải mã và bộ lọc hậu xử lý.[2, 4]

Thiết lập luồng tiền xử lý âm thanh đa tầng
Tín hiệu âm thanh thô phải được chuẩn hóa và làm sạch thông qua một chuỗi các bước xử lý liên tục để đảm bảo chất lượng đầu vào tốt nhất cho các mô hình học sâu.[9, 13]
- **Chuẩn hóa định dạng vật lý**: Toàn bộ dữ liệu âm thanh đầu vào được chuyển đổi về định dạng chuẩn hóa đơn kênh (mono), tần số lấy mẫu $16	ext{ kHz}$ , độ sâu bit $16	ext{-bit}$ PCM WAV.[9, 13] Việc này giúp đồng bộ hóa phân phối phổ tần số với tập dữ liệu huấn luyện của các mô hình SOTA.[13]
- **Tích hợp cổng kích hoạt giọng nói (VAD Gate)**: Sử dụng mô hình Silero VAD để quét toàn bộ tệp âm thanh trước khi đưa vào mô hình ASR.[4, 14] Hệ thống thiết lập ngưỡng xác suất giọng nói (speech threshold) ở mức $0.5$ .[4] Bất kỳ đoạn âm thanh nào có thời lượng giọng người liên tục dưới $1.5	ext{ giây}$ (tương đương khoảng $24,000$ mẫu) sẽ bị chặn lại và không gửi đến bộ giải mã.[15]
- **Nén khoảng lặng bảo tồn cấu trúc**: Để tránh việc cắt nhỏ âm thanh làm mất các dấu câu và ngữ điệu tự nhiên, hệ thống áp dụng thuật toán nén khoảng lặng thích ứng.[2] Các khoảng lặng có độ dài vượt quá $1.5	ext{ giây}$ sẽ được tự động rút ngắn xuống một khoảng thời gian cố định từ $0.3$ đến $0.5	ext{ giây}$ .[2] Điều này giúp duy trì các tín hiệu phân tách câu tự nhiên cho mô hình ASR mà không tạo ra các khoảng trống đủ dài để kích hoạt cơ chế ảo giác.[2]
- **Lọc nhiễu thích ứng bằng DeepFilterNet3**: Tích hợp mô hình DeepFilterNet3 để loại bỏ các tạp âm không thuộc dải tần số giọng người.[16] Nhằm ngăn ngừa hiện tượng méo tiếng (robotic voice) do lọc nhiễu quá mức, hệ thống áp dụng cơ chế pha trộn năng lượng thông minh.[13] Khi phát hiện phân đoạn chứa giọng nói, hệ thống sẽ pha trộn $70\%$ tín hiệu đã lọc nhiễu với $30\%$ tín hiệu âm thanh thô ban đầu để bảo toàn các họa âm tự nhiên của giọng nói.[13]

Cấu hình tối ưu tham số giải mã cho bộ giải mã tự hồi quy
Đối với các phân đoạn âm thanh bắt buộc phải xử lý qua họ mô hình Whisper, các tham số giải mã cần được cấu hình lại một cách nghiêm ngặt để triệt tiêu các hành vi sinh chữ ngoài tầm kiểm soát [4]:

| Tham số cấu hình | Giá trị thiết lập | Cơ chế tác động đến việc giảm thiểu văn bản rác |
| :--- | :--- | :--- |
| `condition_on_previous_text` [4] | False [4] | Ngắt hoàn toàn sự phụ thuộc ngữ cảnh giữa các phân đoạn.[4, 17] Ngăn chặn hiện tượng lặp lại dây chuyền khi một phân đoạn trước đó vô tình bị ảo giác.[4] |
| `beam_size` [4] | 1 [4] | Chuyển sang chế độ giải mã tham lam (Greedy Decoding).[4] Buộc mô hình dừng lại ngay lập tức khi độ tự tin giảm sâu thay vì tiếp tục tìm kiếm các đường đi có xác suất tích lũy cao trong khoảng lặng.[4] |
| `temperature` [18] | 0 [18] | Đảm bảo kết quả giải mã mang tính tất định cao nhất, loại bỏ sự ngẫu nhiên trong việc sinh từ.[18] |
| `no_speech_threshold` [2] | 0.6 [2] | Thiết lập bộ lọc mềm dựa trên xác suất không chứa giọng nói của chính mô hình Whisper nhằm loại bỏ sớm các phân đoạn nghi ngờ.[2] |

Bộ lọc hậu giải mã và chuẩn hóa theo quy ước VLSP
Sau khi chuỗi văn bản được tạo ra từ bộ giải mã, hệ thống cần đưa qua một lớp hậu xử lý logic để lọc sạch các lỗi định dạng và áp dụng các quy chuẩn của VLSP [1, 2]:
- **Bộ lọc từ chối dựa trên xác suất**: Nếu một phân đoạn văn bản ngắn có chỉ số xác suất không chứa giọng nói (no_speech_prob) vượt quá $0.6$ đồng thời có điểm log-probability trung bình (avg_logprob) quá thấp, hệ thống sẽ hủy bỏ toàn bộ chuỗi ký tự của phân đoạn đó và trả về chuỗi rỗng.[2]
- **Danh sách chặn chuỗi ký tự cố định (Exact-string Blocklist)**: Duy trì một danh sách các cụm từ ảo giác phổ biến đã được ghi nhận trong thực tế vận hành (ví dụ: "Cảm ơn các bạn đã theo dõi", "Hãy đăng ký kênh", "Thank you for watching").[4] Nếu kết quả giải mã trùng khớp với các chuỗi này, hệ thống sẽ tự động chuyển đổi đầu ra thành chuỗi rỗng.[4]
- **Thuật toán phát hiện vòng lặp lặp lại (Repetitive Loop Detection)**: Nếu hệ thống phát hiện một từ hoặc cụm từ bị lặp lại liên tục quá $10	ext{ lần}$ , bộ giải mã sẽ bị buộc dừng tại phân đoạn đó và dịch chuyển mốc thời gian (timestamp) giải mã tiếp theo lên phía trước để thoát khỏi trạng thái kẹt.[4]
- **Lớp chuẩn hóa quy ước VLSP**: Triển khai bộ ánh xạ ký tự tự động tuân thủ nghiêm ngặt các quy định phát ngôn [1]:
  - Các từ viết tắt thông dụng như "nato", "fifa" phải được viết liền thành một từ duy nhất, không chứa dấu gạch nối hoặc dấu chấm phân tách, bất kể người nói phát âm liền hay đánh vần từng chữ.[1]
  - Các chuỗi đánh vần chữ cái khác phải được phân tách bằng khoảng trắng giữa từng chữ cái.[1]
  - Các danh từ riêng tiếng Anh phổ biến (ví dụ: "youtube", "facebook") phải được giữ nguyên định dạng chữ viết gốc, không được phép phiên âm theo cách phát âm tiếng Việt.[1]

Nâng cao chất lượng nhãn văn bản bằng mô hình ngôn ngữ hậu xử lý

Để tối ưu hóa hơn nữa chỉ số $SyER_{ASR}$ , việc tích hợp một mô hình ngôn ngữ nhỏ (SLM) để sửa lỗi chính tả và khôi phục dấu thanh sau quá trình nhận dạng thô là một giải pháp vô cùng hiệu quả.[19, 20]

Ứng dụng mô hình Seq2Seq dựa trên BARTpho
Sử dụng mô hình yammdd/vietnamese-error-correction, một phiên bản tinh chỉnh từ nền tảng vinai/bartpho-syllable bằng kỹ thuật LoRA, cho phép sửa lỗi chính tả ở cấp độ âm tiết một cách nhanh chóng.[20] Mô hình này đạt độ chính xác từ vựng lên đến $93.28\%$ và điểm BLEU đạt $86.34$ trên các tập dữ liệu thử nghiệm tiếng Việt.[20] Do mô hình được tối ưu hóa cho các chuỗi văn bản ngắn dưới $30	ext{ từ}$ , luồng xử lý cần thực hiện cắt nhỏ văn bản theo các mốc ranh giới câu trước khi đưa vào bộ sửa lỗi để tránh hiện tượng suy giảm hiệu năng trên các câu dài.[20]

Phương pháp hiệu chỉnh hậu xử lý dựa trên tài liệu tham chiếu cục bộ
Trong các miền nghiệp vụ có tính kiểm soát thông tin cao (như các kịch bản tổng đài chăm sóc khách hàng, hướng dẫn thủ tục hành chính hoặc các văn bản quy phạm), hệ thống có thể áp dụng phương pháp hiệu chỉnh dựa trên tài liệu tham chiếu sử dụng mô hình ngôn ngữ lớn (LLM).[19, 21] Quy trình kỹ thuật được thực hiện thông qua các bước sau [21]:
1. Sử dụng thuật toán tìm kiếm ngữ nghĩa (Semantic Search) để so khớp đoạn văn bản ASR thô với cơ sở dữ liệu tri thức dạng số (như các tài liệu hướng dẫn, kịch bản hội thoại đã được phê duyệt) nhằm tìm ra phân đoạn có độ tương đồng cao nhất.[21]
2. Đưa cả đoạn văn bản tham chiếu và đoạn văn bản ASR thô vào LLM dưới dạng một Prompt có cấu trúc kiểm soát nghiêm ngặt.[21] Prompt này yêu cầu LLM thực hiện hiệu chỉnh các lỗi di lặc, lỗi thanh điệu và lỗi từ đồng âm dựa trên từ vựng của tài liệu tham chiếu, nhưng nghiêm cấm việc tự ý sinh thêm thông tin mới hoặc thay đổi cấu trúc câu gốc của người nói.[21]
3. Áp dụng thuật toán so khớp chuỗi (String Alignment) sau khi LLM phản hồi để loại bỏ các từ dư thừa nếu LLM vô tình sinh thêm văn bản ngoài tầm kiểm soát.[21]
Nghiên cứu thực nghiệm tại hội nghị AAAI-25 chỉ ra rằng phương pháp này giúp đạt điểm đánh giá chất lượng trung bình từ chuyên gia lên tới $8.72/10$ , vượt trội hoàn toàn so với việc chỉ sử dụng các mô hình sửa lỗi chính tả truyền thống vốn chỉ đạt mức $7.03/10$ .[19, 21]

Chiến lược tối ưu hóa dữ liệu huấn luyện cho mô hình ASR chuyên biệt

Để cải thiện tận gốc độ chính xác của mô hình ASR tự huấn luyện, việc xây dựng và tinh lọc dữ liệu đóng vai trò then chốt.[6, 22] Một tập dữ liệu huấn luyện có quy mô vừa phải nhưng được làm sạch triệt để luôn mang lại hiệu năng tốt hơn một tập dữ liệu khổng lồ nhưng chứa nhiều nhãn lỗi.[6]

Quy trình tinh lọc dữ liệu theo kiến trúc PhoASR
Theo các nghiên cứu mới nhất tại EACL 2026 về việc xây dựng tập dữ liệu PhoASR chất lượng cao, các nguồn dữ liệu mở thường chứa tỷ lệ nhãn lỗi rất lớn.[6, 22] Việc áp dụng một luồng lọc dữ liệu nghiêm ngặt giúp loại bỏ các mẫu nhiễu và chuẩn hóa dữ liệu hiệu quả.[6, 22] Bảng số liệu dưới đây minh họa tỷ lệ giữ lại dữ liệu sau khi đi qua luồng lọc lọc chất lượng của PhoASR đối với các tập dữ liệu tiếng Việt phổ biến [6]:

| Tên tập dữ liệu gốc | Dung lượng ban đầu (Giờ) | Dung lượng sau khi tinh lọc (Giờ) | Tỷ lệ dữ liệu sạch được giữ lại | Đặc trưng chất lượng ban đầu |
| :--- | :--- | :--- | :--- | :--- |
| VIVOS [6] | 15.00 | 13.92 | ~92.8% [6] | Rất cao. Do được ghi âm trong môi trường studio chuyên nghiệp theo kịch bản chuẩn bị sẵn.[6] |
| CMV-vi-14 [6] | 24.00 | 21.84 | ~91.0% [6] | Cao. Giọng đọc sách văn bản rõ ràng.[6] |
| VietMed-L [6] | 15.93 | 4.20 | ~26.3% [6] | Rất thấp. Chứa nhiều thuật ngữ y khoa chuyên ngành phức tạp, nhiễu tạp âm phòng khám cao và nhãn tự động chứa nhiều lỗi.[6] |
| Tổng thể PhoASR [6] | 809.07 | 502.67 | ~62.1% [6] | Trung bình. Tích hợp từ nhiều nguồn mở khác nhau, cần lọc bỏ khoảng 38% mẫu lỗi.[6] |

Quy trình tinh lọc dữ liệu này cho thấy đối với các miền dữ liệu tự động hoặc ghi âm thực tế (như các cuộc gọi thoại y tế hay tổng đài), việc loại bỏ các mẫu lỗi (chỉ giữ lại khoảng $26\%$ dữ liệu sạch nhất) là bắt buộc để tránh làm hỏng phân phối xác suất của mô hình ASR.[6]

Tận dụng tập dữ liệu hội thoại tự nhiên VietSuperSpeech
Để giải quyết bài toán nhận dạng giọng nói trong môi trường đàm thoại thực tế (vốn chứa nhiều disfluencies, từ lóng và giọng địa phương), hệ thống nên tận dụng tập dữ liệu VietSuperSpeech mới được công bố.[9] Đây là tập dữ liệu quy mô $267.39	ext{ giờ}$ bao gồm $52,023$ phân đoạn âm thanh được khai thác trực tiếp từ các kênh trò chuyện tự nhiên, vlogs và thảo luận cộng đồng trên YouTube.[9] Tập dữ liệu này đã được dán nhãn chất lượng cao bằng mô hình Zipformer-30M-RNNT-6000h và được phân vùng cố định theo tỷ lệ $89/11$ cho luồng huấn luyện và đánh giá.[9] Việc tinh chỉnh (fine-tuning) mô hình Gipformer-65M hoặc PhoWhisper trên tập dữ liệu VietSuperSpeech sẽ giúp nâng cao đáng kể khả năng nhận dạng các biến thể phát âm tự nhiên của cả ba miền Bắc, Trung, Nam.[6, 9]

Hướng dẫn triển khai thực nghiệm luồng xử lý tối ưu

Dưới đây là thiết kế cấu trúc mã nguồn Python minh họa việc tích hợp toàn diện luồng pipeline tối ưu hóa, bao gồm cổng Silero VAD, bộ giải mã mô hình Gipformer qua công cụ Sherpa-ONNX, và lớp chuẩn hóa hậu xử lý tuân thủ quy ước của VLSP.[1, 4, 7] Giải pháp tái cấu trúc và thay thế công nghệ này mang lại khả năng kiểm soát tuyệt đối đối với các phân đoạn âm thanh không hoạt động, ngăn chặn từ gốc rễ các hành vi sinh văn bản ngoài ý muốn.[4, 7] Việc kết hợp đồng bộ giữa mô hình ASR kháng ảo giác (Gipformer-65M) [7], nhánh phân loại cảm xúc phân rã [1], luồng lọc tiền xử lý âm thanh đa tầng [2, 13], và lớp chuẩn hóa văn bản hậu giải mã [1] giúp hệ thống đạt được sự tối ưu toàn diện về cả tốc độ xử lý lẫn độ chính xác của cả hai nhãn đầu ra.[1, 7]

### Tài liệu tham khảo

1. VLSP 2025 Automatic Speech Recognition and Speech Emotion Recognition | Association for Vietnamese Language and Speech Processing, https://vlsp.org.vn/vlsp2025/eval/asr-ser
2. Whisper hallucinations ("Thank you for watching!") during silence ..., https://github.com/OpenWhispr/openwhispr/issues/462
3. AI speech-to-text can hallucinate violent language | Cornell Chronicle, https://news.cornell.edu/stories/2024/06/ai-speech-text-can-hallucinate-violent-language
4. We collected 135 phrases Whisper hallucinates during silence — here's what it says when nobody's talking and how we stopped it : r/LocalLLaMA - Reddit, https://www.reddit.com/r/LocalLLaMA/comments/1rlqfd7/we_collected_135_phrases_whisper_hallucinates/?tl=en
5. Whisper Hallucination on Silence: Why Your Transcript Loops the Same Phrase, https://dev.to/nareshipme/whisper-hallucination-on-silence-why-your-transcript-loops-the-same-phrase-2pg4
6. Vietnamese Automatic Speech Recognition: A Revisit - ACL Anthology, https://aclanthology.org/2026.findings-eacl.345.pdf
7. ggroup-ai-lab/gipformer: Efficient Vietnamese Speech ... - GitHub, https://github.com/ggroup-ai-lab/gipformer
8. hynt/Zipformer-30M-RNNT-6000h · Hugging Face, https://huggingface.co/hynt/Zipformer-30M-RNNT-6000h
9. VietSuperSpeech: A Large-Scale Vietnamese Conversational Speech Dataset for ASR Fine-Tuning in Chatbot, Customer Support, and Call Center Applications - arXiv, https://arxiv.org/html/2603.01894v1
10. Vietnam's Sovereign AI Conversation Is Stuck One Layer Too High, https://www.vietanh.dev/blog/2026-05-03-sovereign-ai-vietnam
11. vinai/PhoWhisper-medium - Hugging Face, https://huggingface.co/vinai/PhoWhisper-medium
12. Vietnamese speech to text transcription API - Speechmatics, https://www.speechmatics.com/speech-to-text/vietnamese
13. Cleaning the Signal: Our 6-Step Audio Enhancement Pipeline using DeepFilterNet & FFmpeg | Uday Devnani, https://udaydevnani.in/posts/audio_enhancement_pipeline/
14. Optimizing Speech Pipelines Using Voice Activity Detection | by Dhanalakshmi Saravanan, https://medium.com/@dhanam2k03/optimizing-speech-pipelines-using-voice-activity-detection-d7323e53178e
15. How to Implement High-Speed Voice Recognition in Chatbot Systems with WhisperX & Silero-VAD | by Aiden Koh | Medium, https://medium.com/@aidenkoh/how-to-implement-high-speed-voice-recognition-in-chatbot-systems-with-whisperx-silero-vad-cdd45ea30904
16. DeepFilterNet Vs DeepFilterNet2 Vs DeepFilterNet3 Vs RNNoise - Noise Reducer AI, https://noisereducerai.com/blogs/deepfilternet-ai-noise-reduction/
17. A possible solution to Whisper hallucination · openai whisper · Discussion #679 - GitHub, https://github.com/openai/whisper/discussions/679
18. How to avoid Hallucinations in Whisper transcriptions? - OpenAI Developer Community, https://community.openai.com/t/how-to-avoid-hallucinations-in-whisper-transcriptions/125300?page=2
19. Reference-Based Post-OCR Processing with LLM for Precise Diacritic Text in - AI2 Lab, https://www.ai2lab.kaist.ac.kr/highlights/reference-based-post-ocr-processing-with-llm-for-precise-diacritic-text-in
20. yammdd/vietnamese-error-correction · Hugging Face, https://huggingface.co/yammdd/vietnamese-error-correction
21. Reference-Based Post-OCR Processing with LLM for Precise Diacritic Text in Historical Document Recognition - arXiv, https://arxiv.org/html/2410.13305v3
22. Vietnamese Automatic Speech Recognition: A Revisit - ACL Anthology, https://aclanthology.org/2026.findings-eacl.345/
