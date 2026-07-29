# Hướng dẫn sử dụng Black Line Vision V3

## 1. Mục tiêu của bản V3

Bản V3 giải quyết hai vấn đề của bản trước:

1. Line đen lúc nhận được, lúc mất do ánh sáng và exposure thay đổi.
2. Detector bắt nhầm bóng, vật tối, khe sàn hoặc vùng đen không phải line.

Giải pháp không dựa vào một threshold duy nhất. Hệ thống kết hợp nhiều mask và bắt buộc vùng được chọn phải có hình học phù hợp với một đường băng keo dài.

## 2. Vì sao không dùng thanh Hue

Màu đen không có Hue ổn định. Khi độ sáng rất thấp, nhiễu camera có thể làm giá trị Hue thay đổi mạnh dù mắt người vẫn nhìn thấy màu đen.

Vì vậy cửa sổ calibration chỉ dùng:

- `Gray max`: ngưỡng độ tối trên grayscale;
- `HSV V max`: ngưỡng độ sáng của HSV;
- `HSV S max`: điều kiện phụ về độ bão hòa;
- không dùng `H min` và `H max`.

Mặc định `HSV S max = 255`, nghĩa là không hạn chế saturation. Chỉ giảm giá trị này khi detector bắt nhầm vật tối có màu rõ.

## 3. Chuẩn bị camera

Để tuning có ý nghĩa, camera phải được đặt gần giống cấu hình sẽ dùng trên robot:

- chiều cao gần đúng;
- góc camera gần đúng;
- độ phân giải giống lúc chạy;
- line có độ rộng thật;
- nền sàn thật;
- ánh sáng thực tế.

Nên cố định camera. Khi camera hỗ trợ, hạn chế autofocus và auto exposure thay đổi liên tục.

## 4. Cài đặt lần đầu

Mở PowerShell tại thư mục project:

```powershell
cd C:\Users\quang\Downloads\line_following_cv_calibration_v3
```

Tạo môi trường:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Kiểm tra Python đang dùng đúng môi trường:

```powershell
where python
python --version
```

Đường dẫn đầu tiên nên nằm trong:

```text
line_following_cv_calibration_v3\.venv\Scripts\python.exe
```

## 5. Mở cửa sổ calibration

Camera 1:

```powershell
python calibrate_parameters.py --source 1 --profile balanced
```

Camera 0:

```powershell
python calibrate_parameters.py --source 0 --profile balanced
```

Video có sẵn:

```powershell
python calibrate_parameters.py --source samples\line_video.mp4 --profile balanced
```

Nạp lại tuning cũ để chỉnh tiếp:

```powershell
python calibrate_parameters.py --source 1 --profile balanced --load-existing
```

## 6. Cấu trúc giao diện calibration

Cửa sổ preview có bốn vùng:

```text
┌────────────────────────┬────────────────────────┐
│ Camera + selected line │ Grayscale + CLAHE      │
├────────────────────────┼────────────────────────┤
│ Raw threshold mask     │ Final filtered mask    │
└────────────────────────┴────────────────────────┘
```

### Camera + selected line

Hiển thị:

- ROI;
- mask vàng;
- các tâm scanline;
- centerline màu xanh;
- điểm điều khiển màu đỏ;
- tâm camera.

### Grayscale + CLAHE

Dùng để kiểm tra line có thật sự tối hơn nền hay không.

### Raw threshold mask

Cho biết threshold màu/độ sáng đang nhận những pixel nào.

Nếu line không trắng ở vùng này thì vấn đề nằm ở ngưỡng màu hoặc độ sáng.

### Final filtered mask

Cho biết vùng còn lại sau morphology và bộ lọc hình học.

Nếu raw mask có line nhưng final mask mất line thì bộ lọc hình học đang quá chặt.

## 7. Quy trình chỉnh khuyến nghị

### Bước 1 — Chỉnh ROI trước

Trackbar:

```text
ROI top %
ROI left %
ROI right %
```

Mục tiêu là chỉ giữ vùng sàn mà robot cần theo dõi.

Loại khỏi ROI càng nhiều vật tối không liên quan càng tốt, chẳng hạn:

- chân bàn;
- tường;
- khung cửa;
- giày;
- dây cáp;
- vùng ngoài hành lang line.

Không thu hẹp ROI đến mức line dễ rời khỏi vùng quan sát khi robot lệch.

Giá trị khởi đầu:

```text
ROI top: 35–45%
ROI left: 5–12%
ROI right: 88–95%
```

### Bước 2 — Chọn detection mode

Trackbar:

```text
Mode 0G 1A 2V 3H
```

Ý nghĩa:

```text
0 = Gray fixed
1 = Adaptive grayscale
2 = HSV black
3 = Hybrid
```

Khuyến nghị sử dụng:

```text
3 = Hybrid
```

Ba mode đầu dùng để chẩn đoán xem mask nào hoạt động tốt nhất. Mode Hybrid dùng để chạy cuối.

### Bước 3 — Chỉnh Gray max

`Gray max` là ngưỡng tối trên grayscale.

- Tăng giá trị: nhạy hơn, line dễ xuất hiện nhưng nhiễu tăng.
- Giảm giá trị: chỉ nhận vùng rất đen, ít nhiễu nhưng dễ mất line.

Giá trị thử:

```text
80–115
```

Cách chỉnh:

1. Chuyển mode về `0`.
2. Tăng `Gray max` cho đến khi toàn bộ line xuất hiện trắng.
3. Giảm nhẹ cho đến khi phần lớn nền biến mất.
4. Chuyển lại mode `3`.

### Bước 4 — Chỉnh HSV V max

Kênh `V` biểu diễn độ sáng.

- Tăng `HSV V max`: nhận cả vùng tối vừa, nhạy hơn.
- Giảm `HSV V max`: chỉ nhận vùng rất tối.

Giá trị thử:

```text
85–120
```

Cách chỉnh:

1. Chuyển mode về `2`.
2. Tăng `HSV V max` đến khi line liên tục.
3. Kiểm tra bóng đổ có bị nhận quá nhiều không.
4. Chuyển lại mode `3`.

### Bước 5 — Chỉnh HSV S max

Mặc định:

```text
255
```

Giữ nguyên nếu line đen được nhận đúng.

Chỉ giảm khi có vật tối có màu đậm bị bắt nhầm. Giá trị thử:

```text
80–180
```

Giảm quá thấp có thể làm băng keo đen bị mất do color noise của camera.

### Bước 6 — Chỉnh Adaptive threshold

Các thanh:

```text
Adaptive block
Adaptive C
```

`Adaptive block` là kích thước vùng lân cận dùng tính ngưỡng cục bộ.

- Giá trị lớn: ổn định với vùng sáng rộng nhưng có thể mất chi tiết nhỏ.
- Giá trị nhỏ: nhạy với thay đổi cục bộ nhưng dễ bắt texture sàn.

Giá trị thử:

```text
41–71
```

`Adaptive C` được trừ khỏi ngưỡng cục bộ.

Với mask đảo dùng trong project:

- tăng `C`: lọc chặt hơn, ít vùng tối được nhận;
- giảm `C`: nhạy hơn, nhiễu tăng.

Giá trị thử:

```text
5–12
```

### Bước 7 — Chỉnh Hybrid voting

Các thanh:

```text
Vote required
Use Otsu
Use Blackhat
Very dark
```

#### Vote required

Số phương pháp phải đồng ý rằng pixel thuộc line.

```text
1 = rất nhạy, nhiều nhiễu
2 = cân bằng, khuyến nghị
3 = chặt, ít nhiễu nhưng dễ mất line
```

Khuyến nghị bắt đầu:

```text
2
```

#### Use Otsu

Otsu dùng ngưỡng tự động toàn ảnh ROI.

Bật khi sàn và line tạo thành hai nhóm độ sáng rõ. Tắt khi Otsu làm xuất hiện quá nhiều vùng nền.

#### Use Blackhat

Black-hat làm nổi vùng tối nhỏ hơn cấu trúc nền.

Nên bật. Tắt thử nếu khe sàn hoặc texture tối bị làm nổi quá mạnh.

#### Very dark

Pixel tối hơn giá trị này được giữ ngay cả khi chưa đủ vote.

Giá trị thử:

```text
40–60
```

Tăng quá cao sẽ đưa nhiều vật tối trở lại mask.

### Bước 8 — Chỉnh morphology

Các thanh:

```text
Close kernel
Close iter
Open kernel
Open iter
```

#### Closing

Nối các đoạn line bị đứt và lấp lỗ.

Tăng khi line xuất hiện thành nhiều đoạn rời.

Giá trị thử:

```text
Close kernel: 11–23
Close iter: 1–3
```

Closing quá mạnh có thể nối line với nhiễu gần đó.

#### Opening

Xóa đốm nhiễu nhỏ.

Giá trị thử:

```text
Open kernel: 3–7
Open iter: 1–2
```

Opening quá mạnh có thể làm line mỏng bị mất.

### Bước 9 — Chỉnh bộ lọc hình học

Nếu raw mask có nhiều vùng đen, đây là nhóm tham số quan trọng nhất.

#### Min area x10000

Diện tích component tối thiểu.

Ví dụ:

```text
12 = 0.0012 diện tích ROI
```

Tăng để loại đốm nhỏ. Không tăng quá cao khi line ở xa camera và trông nhỏ.

#### Min elong x10

Độ dài so với độ rộng tối thiểu.

Ví dụ:

```text
17 = elongation 1.7
25 = elongation 2.5
```

Tăng để loại vật tròn hoặc hình vuông tối.

#### Min vertical %

Candidate phải chiếm ít nhất bao nhiêu phần trăm chiều cao ROI.

Giá trị thử:

```text
30–50%
```

Tăng giá trị này giúp loại nhiều vùng tối ngắn.

#### Min bottom %

Candidate phải tiến gần đáy ROI đến mức nào.

Giá trị thử:

```text
70–88%
```

Line robot đang bám thường đi vào vùng gần đáy ảnh. Tham số này đặc biệt hiệu quả để loại vật tối ở xa.

#### Min contrast %

Độ sáng quanh candidate phải cao hơn bên trong candidate.

Giá trị thử:

```text
12–30%
```

Tăng để loại bóng mờ. Giảm khi sàn cũng tối hoặc line không đủ đen.

#### Continuity %

Tỷ lệ scanline phải cắt trúng line.

Giá trị thử:

```text
50–75%
```

Tăng để loại vật tối rời rạc. Giảm khi line bị che hoặc bị đứt.

#### Max width CV %

Giới hạn độ thay đổi bất thường của chiều rộng line giữa các scanline.

Giá trị thử:

```text
70–120%
```

Giảm để loại candidate có hình dạng thất thường. Do phối cảnh làm line rộng dần về phía camera, không nên đặt quá thấp.

### Bước 10 — Chỉnh Lookahead

```text
Lookahead %
```

Đây là vị trí theo chiều dọc nơi hệ thống tính sai lệch ngang.

Giá trị lớn hơn nghĩa là dùng điểm gần đáy ảnh, gần robot hơn.

Khuyến nghị:

```text
75–88%
```

## 8. Cách biết tuning đã tốt

Một bộ tuning tốt cần đạt đồng thời:

1. Raw mask chứa line tương đối đầy đủ.
2. Final mask chỉ còn line chính.
3. Centerline màu xanh chạy giữa băng keo.
4. Khi line đứng giữa, lateral error gần `0`.
5. Khi line hướng thẳng, angle gần `0°`.
6. Khi đưa vật đen khác vào ROI, detector không nhảy khỏi line.
7. Khi thay đổi ánh sáng nhẹ, line không chớp tắt liên tục.
8. Khi line rời frame thật, hệ thống chuyển sang `LINE_LOST` hoặc `LINE_END`.

Không tuning chỉ trên một frame đẹp. Sau khi chỉnh:

- unpause;
- nghiêng camera nhẹ;
- dịch line trái/phải;
- thử vùng sáng và vùng tối;
- đặt một vật đen gây nhiễu;
- kiểm tra nhiều khoảng cách.

## 9. Lưu tham số

Nhấn:

```text
S
```

Hệ thống lưu:

```text
calibration/tuned_parameters.yaml
calibration/tuned_parameters.jpg
```

File YAML chỉ chứa các giá trị đã hiệu chỉnh, không ghi đè toàn bộ `config.yaml`.

## 10. Chạy bằng tuning đã lưu

```powershell
python app.py --source 1 --profile balanced
```

Khi nạp thành công, terminal hiển thị:

```text
Loaded tuning: calibration/tuned_parameters.yaml
```

Trên dashboard, profile có thêm chữ:

```text
tuned
```

## 11. Chạy không dùng tuning

Để so sánh với cấu hình gốc:

```powershell
python app.py --source 1 --profile balanced --no-tuning
```

## 12. Dùng một tuning file khác

```powershell
python app.py --source 1 --profile balanced --tuning calibration\factory_floor.yaml
```

Điều này hữu ích khi có nhiều môi trường:

```text
factory_floor.yaml
lab_floor.yaml
corridor_floor.yaml
```

## 13. Thứ tự xử lý khi vẫn bắt nhầm

Thực hiện đúng thứ tự:

1. Thu hẹp ROI.
2. Giữ Hybrid, `Vote required = 2`.
3. Giảm `Gray max` và `HSV V max` một ít.
4. Tăng `Min contrast`.
5. Tăng `Min vertical`.
6. Tăng `Min bottom`.
7. Tăng `Min elongation`.
8. Tăng `Continuity`.
9. Chỉ dùng Strict nếu các bước trên chưa đủ.

Không tăng toàn bộ ngưỡng cùng lúc vì sẽ khó biết tham số nào làm mất line.

## 14. Thứ tự xử lý khi line lúc có lúc không

1. Kiểm tra line có xuất hiện trong raw mask không.
2. Tăng `Gray max` hoặc `HSV V max` từng 5 đơn vị.
3. Giảm `Adaptive C` từng 1 đơn vị.
4. Giảm `Vote required` từ 2 xuống 1 để kiểm tra.
5. Tăng `Close kernel` nhẹ.
6. Giảm `Min contrast`.
7. Giảm `Continuity`.
8. Giảm `Min vertical`.
9. Cố định exposure hoặc bổ sung ánh sáng nếu camera thay đổi quá mạnh.

Sau khi tìm được nguyên nhân, nên đưa `Vote required` về 2 nếu có thể.

## 15. Ý nghĩa đầu ra điều khiển

### Góc

```text
angle_deg = 0
```

Line đi thẳng theo hướng camera.

### Sai lệch ngang

```text
lateral_error_norm < 0
```

Line nằm bên trái tâm camera.

```text
lateral_error_norm > 0
```

Line nằm bên phải tâm camera.

### Trạng thái

```text
TURN_LEFT
TURN_RIGHT
MOVE_LEFT
MOVE_RIGHT
FORWARD
HOLD_...
LINE_LOST
LINE_END
```

## 16. Giới hạn hiện tại

- Khoảng dịch ngang hiện là sai lệch chuẩn hóa, chưa phải centimet.
- Góc tính từ hình ảnh, chưa phải góc quay đã hiệu chuẩn chính xác cho robot.
- Khoảng đi thẳng đến cuối line không thể suy ra chính xác chỉ từ một camera chưa hiệu chuẩn.
- Chưa kết nối Unitree SDK.
- Chưa có obstacle detection.

Muốn chuyển sang đơn vị thật cần hiệu chuẩn camera và bird's-eye view.

# Bổ sung V3.1 — line nằm ngang hoàn toàn

Không cần tăng `Gray max`, `HSV V max` hoặc giảm bộ lọc màu chỉ để nhận line ngang. Vấn đề cũ xuất phát từ bộ lọc hình học và mô hình scanline.

Phiên bản V3.1 tự động:

```text
line dọc/nghiêng → scanline + RANSAC
line gần ngang   → contour + PCA
```

Khi line nằm ngang, dashboard có thể hiển thị:

```text
Angle = +90.00 deg
```

hoặc:

```text
Angle = -90.00 deg
```

Cả hai đều biểu diễn phương ngang. Dấu quyết định hướng quay hiệu chỉnh.

Giao diện preview hiện chỉ còn:

```text
Camera + selected line
```

Các thanh kéo vẫn nằm trong cửa sổ `V3 Calibration Controls`.
