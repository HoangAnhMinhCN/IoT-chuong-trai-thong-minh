# Làm việc từ xa với ESP32

Hướng dẫn cho thành viên trong nhóm điều khiển, đọc cảm biến và nạp code cho ESP32
khi không ngồi cạnh board. Dự án cuối cùng vẫn chạy trong LAN; đường từ xa chỉ để
cộng tác khi phát triển.

## Mô hình

Laptop chủ nhóm chạy broker Mosquitto (Docker), hotspot Windows và backend chính.
ESP32 `esp32-383e51cb0328` nối vào hotspot và nói chuyện với broker bằng MQTT thường.
Broker mở thêm một cổng TLS qua tunnel trên VPS: `mqtt.xuanthieu.site:20083`.

Bạn chạy **backend riêng trên máy mình**, kết nối tới broker qua domain đó:

```
Máy bạn                         VPS (tunnel)          Laptop chủ nhóm              Hotspot
backend :8000  --TLS 20083-->   mqtt.xuanthieu.site  --> Mosquitto :8883 / :1883  <-- ESP32
  ^ Swagger, curl, web demo,
    ota_push.py
```

Mọi thao tác (lệnh, đọc cảm biến, OTA) đều đi theo đường này. Cần đồng thời:

- laptop chủ nhóm bật, broker chạy kèm cấu hình tunnel, hotspot bật;
- ESP32 có nguồn và đang online.

Nếu một trong các điều trên không đúng, backend của bạn sẽ báo mất broker hoặc thiết bị
offline. Khi đó nhắn chủ nhóm.

## Tài khoản

Cả nhóm dùng chung tài khoản MQTT `backend`. Đây là tài khoản admin của broker: toàn
quyền, kể cả nạp code lên board. Chủ nhóm gửi mật khẩu (`MQTT_BACKEND_PASSWORD`) qua
kênh riêng.

- Không commit mật khẩu, không dán vào issue, PR hay nhóm chat chung.
- Lộ mật khẩu thì báo chủ nhóm để đổi.

## Cài đặt (Windows, Python 3.11)

```powershell
git clone https://github.com/thieuhua/IoT-chuong-trai-thong-minh.git
cd IoT-chuong-trai-thong-minh\backend
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Tạo file `deployment\.env` (Git bỏ qua file này) với nội dung:

```
MQTT_BACKEND_PASSWORD=<mật khẩu chủ nhóm gửi>
IOT_BROKER_HOST=mqtt.xuanthieu.site
IOT_BROKER_PORT=20083
IOT_BROKER_TLS=1
IOT_ADOPT_DEVICES=1
```

| Biến | Ý nghĩa |
| --- | --- |
| `IOT_BROKER_TLS=1` | Bật TLS, xác minh chứng chỉ và hostname bằng CA của hệ điều hành |
| `IOT_ADOPT_DEVICES=1` | Database của bạn (`backend\data\iot.sqlite3`) ban đầu trống. Cờ này cho backend tự thêm các thiết bị đã được duyệt từ gói `meta` lưu trên broker. Chỉ bật ở máy làm từ xa, không bật trên backend chính của laptop chủ nhóm |

Không copy `.env.example` đè lên `.env`: mật khẩu sẽ mất.

Kiểm tra đường mạng tới broker:

```powershell
Test-NetConnection mqtt.xuanthieu.site -Port 20083
```

`TcpTestSucceeded` phải là `True`.

## Chạy backend

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

- Mở <http://localhost:8000/docs> (Swagger).
- `GET /health` trả `{"broker_connected": true}`.
- Sau vài giây, `GET /devices` có `esp32-383e51cb0328` với `online: true`.

## Điều khiển thiết bị

Gửi `POST /devices/esp32-383e51cb0328/commands` với body `{"name": ..., "args": {...}}`.

Phần cứng hiện tại: servo SG90 ở G14, relay ở G26, DHT11 ở G25 (cảm biến tên `room`;
`sim` là cảm biến giả lập).

| Lệnh | `args` | Kết quả |
| --- | --- | --- |
| `ping` | `{}` | `{"uptime_s": ...}` |
| `get_info` | `{}` | meta, `fw` (phiên bản firmware), `uptime_s`, `mem_free`, `rssi`, `ip` |
| `read` | `{"sensor": "room"}` hoặc `{}` | số đo |
| `set_interval` | `{"seconds": 10}` (1–3600) | chu kỳ gửi telemetry |
| `servo_set` | `{"angle": 90}` (0–180) | quay tới góc, dừng chuỗi góc |
| `servo_sequence` | `{"run": true}` hoặc `{"run": false}`; tùy chọn `angles`, `step_ms` | chạy/dừng chuỗi góc |
| `relay_set` | `{"on": true, "duration_ms": 5000}` (`duration_ms` tùy chọn) | bật/tắt; ESP32 tự tắt sau `duration_ms` |
| `actuator_state` | `{}` hoặc `{"name": "relay"}` | trạng thái servo/relay |
| `reboot` | `{}` | khởi động lại board |

Ví dụ PowerShell:

```powershell
$dev = "http://localhost:8000/devices/esp32-383e51cb0328"
Invoke-RestMethod "$dev/commands" -Method Post -ContentType "application/json" `
  -Body '{"name":"relay_set","args":{"on":true,"duration_ms":3000}}'
Invoke-RestMethod "$dev/telemetry/latest"
```

| HTTP | Nghĩa |
| --- | --- |
| 404 | Backend chưa biết thiết bị: chờ vài giây, kiểm tra `IOT_ADOPT_DEVICES=1` |
| 409 | Thiết bị offline |
| 504 | ESP32 không phản hồi kịp |
| 502 + `code` | Thiết bị từ chối lệnh: `unknown_command` (firmware chưa có lệnh), `bad_args`, `actuator_not_found`, `sensor_error` |

## Web demo

Từ thư mục gốc repo:

```powershell
.\backend\.venv\Scripts\python.exe -B .\demo\servo_slider\server.py --device esp32-383e51cb0328
```

Mở <http://127.0.0.1:8081>: thanh trượt servo, nhiệt độ, độ ẩm và relay. Server demo
chỉ đọc `index.html` lúc khởi động, nên sửa giao diện xong phải chạy lại.

## Nạp code qua Wi-Fi (OTA)

1. `git pull` để có code mới nhất (xem quy tắc nhóm bên dưới).
2. Sửa code trong `firmware/src`. Riêng `main.py` là loader, chỉ nạp được bằng USB tại chỗ.
3. Chạy test (không cần board, không cần broker), từ thư mục gốc:

   ```powershell
   .\backend\.venv\Scripts\python.exe -m pytest -q firmware/tests
   ```

4. Báo nhóm, rồi nạp:

   ```powershell
   cd backend
   .venv\Scripts\python.exe -m tools.ota_push --device esp32-383e51cb0328
   ```

   Tool chỉ gửi file khác với trên board và chờ board xác nhận. Thành công khi in
   `OK: <version> confirmed`.
5. Commit và push (hoặc mở PR) đúng code vừa nạp.

Không dùng `--with-config`: `firmware/src/config.json` chứa mật khẩu Wi-Fi nên không có
trong repo. Muốn đổi chân hay cấu hình thì nhờ chủ nhóm.

Cơ chế an toàn: bản mới chạy thử trước. Board tự quay về bản cũ khi bản mới treo
(watchdog 120 s), không được xác nhận trong 300 s, hoặc khởi động lỗi 2 lần; khi đó
`ota_push` báo lỗi rollback. Bản mới được giữ khi đã online 30 s và xử lý được ít nhất
một lệnh (`ota_push` tự gửi lệnh này).

Nếu board mất hẳn kết nối và không quay lại online, cần người tại chỗ cắm USB và chạy
`firmware/tools/deploy.ps1`.

## Quy tắc làm việc nhóm

- **Một người nạp một lúc.** Báo trong nhóm trước khi OTA.
- **Luôn `git pull` trước khi nạp.** `ota_push` gửi code từ checkout của bạn; checkout
  cũ hơn code trên board sẽ vô tình gỡ thay đổi của người khác. Xem bản đang chạy bằng
  `get_info` (trường `fw`).
- **Push code đã nạp.** Board không được chạy code mà repo không có.
- **Không duyệt, từ chối hay thu hồi thiết bị từ máy mình.** Mỗi backend có database
  riêng; việc này làm trên laptop chủ nhóm.
- **Không chạy `tools/sim_device.py` hay test tích hợp trỏ vào broker chung**, vì chúng
  tạo thiết bị giả rác. `pytest` bình thường không cần broker.
- **Lệnh tác động lên phần cứng thật.** Đừng để relay bật lâu khi không có ai ở đó;
  dùng `duration_ms`.

## Giới hạn

- ESP32 dùng MQTT không mã hóa trong LAN; chỉ đoạn backend tới broker qua Internet có TLS.
- Gói firmware chưa được ký: ai có mật khẩu `backend` là nạp được code.
- Mọi thứ phụ thuộc laptop chủ nhóm và VPS tunnel. Nguồn cho servo/relay yếu có thể làm
  board khởi động lại.
- Chứng chỉ TLS hết hạn 13/02/2027; chủ nhóm gia hạn trước ngày đó.

## Xử lý sự cố

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
| --- | --- | --- |
| `broker_connected: false` | Sai mật khẩu hoặc `.env`; laptop/tunnel tắt | Kiểm tra `.env`, chạy `Test-NetConnection`; nếu TCP lỗi thì nhắn chủ nhóm |
| `GET /devices` trống | Thiếu `IOT_ADOPT_DEVICES=1`; ESP32 chưa online | Sửa `.env`, chạy lại backend; hỏi chủ nhóm tình trạng board |
| 409 offline | ESP32 mất Wi-Fi hoặc mất nguồn | Nhắn chủ nhóm |
| 504 timeout | Hotspot hoặc Wi-Fi chập chờn | Thử lại sau ít phút |
| `unknown_command` | Firmware trên board cũ hơn code của bạn | `git pull`, nạp OTA |
| OTA báo rollback | Bản mới lỗi lúc chạy thử | Đọc lỗi, sửa, chạy test, nạp lại |
