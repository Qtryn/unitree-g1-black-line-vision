# Black Line Vision V3

Hệ thống nhận diện băng keo đen trên nền sáng dành cho prototype dò line của Unitree G1.

Phiên bản V3 bổ sung:

- chế độ hiệu chỉnh trực tiếp bằng trackbar;
- bốn chế độ tách line: grayscale cố định, adaptive grayscale, HSV black và hybrid;
- không dùng Hue để nhận màu đen;
- lưu tham số đã chỉnh vào YAML;
- tự động nạp lại tham số khi chạy;
- lọc nhiễu cứng theo độ dài, vị trí, độ tương phản và độ liên tục;
- dashboard hiển thị góc, sai lệch ngang, confidence và lệnh điều khiển.

## Chạy nhanh

### 1. Cài đặt

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Hoặc:

```powershell
.\setup_windows.bat
```

### 2. Hiệu chỉnh camera

Camera số 1:

```powershell
python calibrate_parameters.py --source 1 --profile balanced
```

Hoặc chạy:

```text
run_calibration_camera_1.bat
```

Khi mask đã đúng, nhấn `S` để lưu:

```text
calibration/tuned_parameters.yaml
```

### 3. Chạy detector với tham số đã lưu

```powershell
python app.py --source 1 --profile balanced
```

Hoặc:

```text
run_camera_1_tuned.bat
```

Ứng dụng tự tìm và nạp `calibration/tuned_parameters.yaml`.

## Tài liệu chi tiết

Đọc:

```text
HUONG_DAN_SU_DUNG_CHI_TIET.md
```

## Kiến trúc xử lý

```mermaid
flowchart TD
    A[Camera RGB] --> B[ROI mặt sàn]
    B --> C[Gaussian blur]
    C --> D[Grayscale + CLAHE]
    C --> E[HSV]
    D --> F1[Gray fixed]
    D --> F2[Adaptive threshold]
    D --> F3[Black-hat]
    E --> F4[HSV V/S black mask]
    F1 --> G[Hybrid voting]
    F2 --> G
    F3 --> G
    F4 --> G
    G --> H[Morphology]
    H --> I[Hard geometric filters]
    I --> J[Temporal candidate priority]
    J --> K[Scanline centers]
    K --> L[Continuity + width consistency]
    L --> M[RANSAC]
    M --> N[Linear/quadratic centerline]
    N --> O[Angle + lateral error]
    O --> P[Stable tracker]
    P --> Q[Control state]
```

## Phím trong cửa sổ calibration

| Phím | Chức năng |
|---|---|
| `S` | Lưu tuning YAML và ảnh preview |
| `P` | Pause/unpause |
| `R` | Reset temporal tracker |
| `Q` hoặc `Esc` | Thoát |

## Phím trong cửa sổ chạy chính

| Phím | Chức năng |
|---|---|
| `1` | Sensitive |
| `2` | Balanced |
| `3` | Strict |
| `M` | Bật/tắt mask overlay |
| `D` | Bật/tắt điểm debug |
| `T` | Bật/tắt mask panel |
| `R` | Reset tracker |
| `S` | Lưu dashboard và JSON |
| `P` | Pause |
| `[` / `]` | Chuyển processing preset khi dùng `--preset-file` |
| `Q` hoặc `Esc` | Thoát |

## Kiểm thử ảnh mẫu

```powershell
python tools\generate_test_images.py
python app.py --source samples\line_center.jpg --image --profile balanced --no-tuning
```

Chạy smoke test:

```powershell
python tests\smoke_test.py
```

## Video đánh giá trong HeinekenRobot

Chạy detector trên toàn bộ `lab/scripts/demo/line_video.mp4` theo đúng tốc độ
khung hình đã ghi và tự động phát lại:

```bash
cd externals/unitree-g1-black-line-vision
python app.py \
  --source ../../lab/scripts/demo/line_video.mp4 \
  --profile balanced \
  --preset-file video_processing_presets.yaml \
  --processing-preset stable \
  --loop-video
```

Các preset trong `video_processing_presets.yaml` đều dùng cùng pipeline
`hsv_black`; chúng chỉ thay đổi ROI và độ chặt. Nhấn `[` hoặc `]` trong cửa sổ
chính để chuyển preset trên cùng video. `stable` là mặc định vì thử nghiệm trên
117 frame cho kết quả cân bằng tốt nhất giữa tỷ lệ nhận và độ ổn định.

Mở giao diện calibration trên cùng video. Video tự động phát lại để có thể
chỉnh trackbar và xem ngay kết quả:

```bash
cd externals/unitree-g1-black-line-vision
python calibrate_parameters.py \
  --source ../../lab/scripts/demo/line_video.mp4 \
  --profile balanced
```

Trong cửa sổ, nhấn `P` để dừng tại một frame, `R` để reset tracker, và `Q` hoặc
`Esc` để thoát. Giao diện calibration tự động reset trạng thái temporal mỗi lần
video quay lại frame đầu.

## D435i MJPEG trực tiếp

Mở dashboard detector từ camera đầu D435i:

```bash
bash externals/unitree-g1-black-line-vision/run_d435i_mjpeg.sh
```

Hoặc chạy thủ công từ thư mục reference:

```bash
python app.py \
  --source 'http://172.28.182.149:8080/api/sensors/d435i/color/mjpeg?camera=d435i_head' \
  --profile balanced \
  --preset-file video_processing_presets.yaml \
  --processing-preset stable \
  --no-tuning
```

Endpoint là stream MJPEG liên tục 640x480 ở khoảng 25 FPS. Reader thread luôn
giữ frame mới nhất để tránh tích lũy độ trễ. Nhấn `[` hoặc `]` để so sánh các
processing preset trên live stream.

## Lưu ý an toàn

Các giá trị `yaw_command`, `lateral_command` và `forward_command` hiện chỉ là đầu ra giả lập. Chưa gửi trực tiếp sang Unitree G1.

Trước khi điều khiển robot thật cần bổ sung:

- emergency stop;
- watchdog;
- giới hạn vận tốc;
- kiểm tra thăng bằng;
- phát hiện vật cản;
- hiệu chuẩn camera–robot;
- kiểm thử ở tốc độ thấp.

## Cập nhật V3.1: nhận line nằm ngang

Phiên bản V3.1 sửa trường hợp băng keo nằm ngang hoàn toàn trong ảnh.

Nguyên nhân ở phiên bản cũ:

- candidate bắt buộc phải chiếm nhiều chiều cao ROI;
- thuật toán chỉ lấy tâm theo các dải ngang nên line ngang có quá ít điểm;
- góc lớn hơn `82°` bị loại.

Cách xử lý mới:

1. Candidate được đánh giá theo **trục dài nhất**, không chỉ chiều dọc.
2. Line dọc hoặc nghiêng tiếp tục dùng scanline + RANSAC.
3. Line gần ngang tự động chuyển sang **contour PCA fallback**.
4. Góc hợp lệ được mở đến `±90°`.
5. Giao diện calibration và giao diện chạy chỉ giữ camera + selected line.

### Quy ước góc

```text
0°       = line hướng thẳng từ dưới lên trên ảnh
+90°     = line nằm ngang theo một chiều
-90°     = line nằm ngang theo chiều tương đương còn lại
```

Line là một đường không có chiều nên `0°` và `180°` mô tả cùng một phương. Hệ thống chuẩn hóa về `[-90°, +90°]` để thuận tiện tạo lệnh quay.

### Không cần chỉnh trackbar để nhận line ngang

Sửa lỗi này nằm trong thuật toán, không phải chỉ ở threshold. Tuning cũ vẫn có thể dùng lại. Khi mở tuning cũ, kiểm tra:

```yaml
line_model:
  max_abs_angle_deg: 90.0
```

Nếu file tuning cũ không chứa tham số này thì hệ thống sẽ lấy giá trị `90.0` từ `config.yaml`.
