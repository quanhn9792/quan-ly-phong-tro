# Quản lý cho thuê nhà / phòng (Python + Flask + SQL Server)

Ứng dụng web chạy trên máy cá nhân để quản lý **nhiều nhà cho thuê** và thu tiền hằng tháng:

- **Nhà trọ / chung cư mini** – cho thuê từng phòng.
- **Nhà riêng** hoặc **căn hộ chung cư** – cho thuê nguyên căn.
- Loại **khác** (mặt bằng, kho, văn phòng…).

Mỗi tháng nhập chỉ số điện/nước, hệ thống tự tính tiền thuê + dịch vụ + máy giặt + điện + nước, tạo ảnh thông báo kèm QR ngân hàng để gửi Zalo hoặc email cho khách.

## Tính năng

| Màn hình | Chức năng |
| --- | --- |
| Tổng quan | Tình trạng từng phòng trong tháng (đã/chưa nhập hóa đơn), tổng cần thu |
| Nhập điện nước | Chọn phòng, chỉ số cũ tự lấy từ tháng trước, tạm tính trực tiếp, lưu xong tự chuyển phòng tiếp theo |
| Báo cáo & gửi khách | Biểu đồ 12 tháng, chi tiết từng hóa đơn, tải ảnh (zip), xuất Excel (CSV), gửi email hàng loạt |
| Gửi Zalo cả tháng | Bấm "Gửi Zalo" → ảnh hóa đơn được copy + mở khung chat `zalo.me/<số Zalo của khách>` → Ctrl+V, Enter. Đánh dấu phòng đã gửi |
| Nhà & căn hộ | Thêm/sửa nhà, loại hình, địa chỉ; ngừng quản lý nhà |
| Phòng & căn | Thêm phòng, đổi tên/chuyển nhà, giá theo giai đoạn (tự tính lại hóa đơn trong giai đoạn) |
| Khách thuê | Lượt thuê theo ngày vào/ra, giá thỏa thuận riêng |
| Cài đặt | Đơn giá dự phòng theo tháng, QR ngân hàng, SMTP gửi email |
| Thu tiền | Đánh dấu Đã thu / Chưa thu ngay trên Tổng quan, Báo cáo, Gửi Zalo, chi tiết hóa đơn; tổng đã thu / còn phải thu; danh sách **còn nợ các tháng trước** |
| Tài khoản | Đổi mật khẩu ngay trên app (đăng xuất các thiết bị khác) |
| Cài lên điện thoại | Mã QR mở app, hướng dẫn cài iPhone / Android, tự kiểm tra cấu hình tunnel |
| App của khách | Mỗi khách 1 link riêng (không cần mật khẩu): xem hóa đơn các tháng, QR thanh toán, lưu ảnh, báo "Tôi đã chuyển khoản", gọi / nhắn Zalo chủ nhà; cài lên màn hình chính như app |

Khi có từ 2 nhà trở lên, ô **"Đang xem"** ở thanh bên cho phép lọc mọi màn hình theo một nhà.

## Cài đặt

Yêu cầu: Python 3.10+, SQL Server (LocalDB / Express / bản đầy đủ), ODBC Driver 17 hoặc 18 for SQL Server.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Tạo database + bảng (chạy lại nhiều lần vẫn an toàn, không ghi đè dữ liệu)
python main.py init-db

# Tạo tài khoản đăng nhập cho chủ nhà (chạy lại để đổi mật khẩu — mọi thiết bị đang đăng nhập sẽ bị đăng xuất)
python main.py create-owner

# Chạy web
python web.py          # mở http://127.0.0.1:5000
```

### Cấu hình (biến môi trường hoặc file `instance\web.env`)

Có thể đặt các biến dưới đây trong file `instance\web.env` (xem mẫu `web.env.example`) thay vì biến môi trường Windows.

| Biến | Mặc định | Ghi chú |
| --- | --- | --- |
| `MSSQL_SERVER` | `(localdb)\QuanLyPhongTro2025` | VD: `localhost\SQLEXPRESS` |
| `MSSQL_DATABASE` | `QuanLyPhongTro` | |
| `MSSQL_USERNAME` / `MSSQL_PASSWORD` | (trống) | Trống = Windows Authentication |
| `MSSQL_DRIVER` | tự chọn | Tên ODBC driver |
| `HOST` / `PORT` | `127.0.0.1` / `5000` | Giữ `127.0.0.1` khi dùng tunnel |
| `TRUST_PROXY` | (trống) | Đặt `1` khi chạy sau Tailscale Funnel / Cloudflare Tunnel |
| `ANDROID_PACKAGE` / `ANDROID_CERT_SHA256` | (trống) | Chỉ khi đóng gói app Android bằng PWABuilder (xem dưới) |
| `PUBLIC_URL` | (trống) | Địa chỉ tunnel, vd `https://may-nha.tail1234.ts.net` — dùng để tạo link gửi khách |
| `FLASK_SECRET_KEY` | tự sinh, lưu ở `instance/secret_key` | |

### Tự chạy khi đăng nhập Windows

`scripts/start_web.ps1` khởi động LocalDB, chạy `init-db` rồi chạy web ẩn (log ở `logs/`). Tạo shortcut tới script trong thư mục Startup (`shell:startup`).

## Dùng trên điện thoại (iOS / Android)

Ứng dụng là một **PWA**: mở bằng trình duyệt điện thoại rồi "Thêm vào màn hình chính" là có biểu tượng như app thật, mở toàn màn hình, có thanh tab dưới đáy. Máy Windows vẫn là máy chủ giữ dữ liệu, nên **máy phải bật** thì điện thoại mới dùng được.

**Cách nhanh:** cài [Tailscale](https://tailscale.com/download), đăng nhập, rồi chạy
`powershell -ExecutionPolicy Bypass -File scripts\setup_mobile.ps1` — script tự tạo tài khoản, bật Tailscale Funnel và ghi cấu hình (bước 1–3 dưới đây). Sau đó khởi động lại web và làm bước 4.

1. Tạo tài khoản: `python main.py create-owner` (bắt buộc — web sẽ mở ra Internet).
2. Mở web ra ngoài bằng một tunnel có HTTPS (PWA và nút Chia sẻ đều cần HTTPS):
   - **Tailscale Funnel** (miễn phí, địa chỉ cố định dạng `https://<tên-máy>.<tailnet>.ts.net`): cài Tailscale, đăng nhập, rồi chạy `tailscale funnel --bg 5000`.
   - Hoặc **Cloudflare Tunnel** nếu đã có tên miền trên Cloudflare: `cloudflared tunnel` trỏ về `http://127.0.0.1:5000`.
3. Copy `web.env.example` thành `instance\web.env`, bỏ dấu `#` ở 2 dòng `TRUST_PROXY=1` và `PUBLIC_URL=<địa chỉ tunnel>` rồi khởi động lại web.
   Trong Windows: *Settings › System › Power* đặt **Sleep = Never** khi cắm điện, nếu không máy ngủ là điện thoại mất kết nối.
4. Trên điện thoại mở địa chỉ tunnel (hoặc vào **Cài đặt › Cài lên điện thoại** trên máy tính rồi quét mã QR), đăng nhập:
   - **iPhone (Safari)**: nút Chia sẻ → *Thêm vào MH chính*.
   - **Android (Chrome)**: menu ⋮ → *Cài đặt ứng dụng* / *Thêm vào màn hình chính*.

### Đóng gói lên Google Play / App Store (tùy chọn)

Cài PWA từ trình duyệt (bước 4 ở trên) là đủ dùng. Nếu muốn có file cài đặt / đưa lên store:

- **Android (APK/AAB):** vào [pwabuilder.com](https://www.pwabuilder.com), nhập địa chỉ tunnel → *Package for stores* → *Android*. Tải về sẽ có file `.apk` (cài thử trực tiếp) và `.aab` (đưa lên Google Play), kèm `assetlinks.json`. Lấy `package_name` và `sha256_cert_fingerprints` trong đó, đặt vào biến môi trường `ANDROID_PACKAGE` và `ANDROID_CERT_SHA256` rồi khởi động lại web — app Android sẽ mở toàn màn hình, không còn thanh địa chỉ.
- **iOS:** PWABuilder cũng xuất được project Xcode, nhưng build và đưa lên App Store cần máy Mac + tài khoản Apple Developer (99 USD/năm). Không có Mac thì dùng "Thêm vào MH chính" trong Safari — trải nghiệm gần như app thật.

Lưu ý: app đóng gói vẫn chỉ là "vỏ" mở địa chỉ tunnel, nên địa chỉ tunnel phải cố định (Tailscale Funnel / tên miền Cloudflare).

### App cho khách thuê

Ở trang **Khách thuê**, bấm *Tạo link app cho khách* → *Copy link* (hoặc *Chia sẻ* trên điện thoại) → gửi qua Zalo. Khách mở link sẽ thấy số tiền cần trả, QR thanh toán và lịch sử hóa đơn các tháng mình ở; bấm "Thêm vào màn hình chính" để có app riêng. Link là mã ngẫu nhiên 256 bit, chỉ xem được hóa đơn của đúng phòng trong thời gian khách đó thuê. Bấm *Thu hồi* để vô hiệu hóa link ngay (vd khi khách chuyển đi hoặc lỡ gửi nhầm).

Cần đặt `PUBLIC_URL` là địa chỉ tunnel để link gửi khách không bị là `127.0.0.1`.

Trên điện thoại, nút **Gửi Zalo** mở bảng Chia sẻ của hệ điều hành kèm ảnh hóa đơn → chọn Zalo → chọn khách (số Zalo của khách hiện ngay sau khi chia sẻ để chọn đúng người).

**Xem offline:** các trang đã mở được lưu trên điện thoại. Khi máy chủ tắt hoặc mất mạng, app vẫn hiện bản lưu gần nhất (có dải "Đang offline"); khách vẫn xem hóa đơn và quét QR chuyển khoản được. Đăng xuất sẽ xóa toàn bộ bản lưu trên máy đó.

Bảo mật: đăng nhập bắt buộc cho mọi trang, mật khẩu được băm, chặn 15 phút sau 5 lần nhập sai, mọi thao tác ghi đều có CSRF token, trang dữ liệu không được trình duyệt lưu cache. Hãy đặt mật khẩu mạnh và cài Windows Update / bản vá thường xuyên cho máy chủ.

## Cấu trúc

```
main.py               python main.py init-db | create-owner
web.py                chạy web Flask
database/schema.sql   toàn bộ bảng + view (idempotent, có phần nâng cấp DB cũ)
src/db.py             kết nối SQL Server, chạy schema
src/queries.py        truy vấn và quy tắc tính giá
src/notify.py         ảnh thông báo, QR, gửi email
src/formatting.py     đọc/định dạng số tiền, ngày
src/web.py            các route Flask
src/auth.py           đăng nhập, phiên, CSRF, chặn dò mật khẩu
src/portal.py         app của khách thuê (/k/<mã>)
static/sw.js, manifest.webmanifest, icons/   PWA
templates/, static/   giao diện
```

## Thiết kế dữ liệu

- `Properties` – nhà / tòa / căn hộ (`PropertyType`: `ROOMING_HOUSE`, `WHOLE_HOUSE`, `APARTMENT`, `OTHER`).
- `Rooms` – đơn vị cho thuê thuộc một nhà (`PropertyId`); mã phòng duy nhất trong từng nhà. Nhà cho thuê nguyên căn có 1 đơn vị "Nguyên căn".
- `Tenants` – mỗi dòng là một lượt thuê (ngày vào/ra, giá thỏa thuận).
- `RoomPricePeriods` – giá theo giai đoạn tháng của từng phòng.
- `BillingMonths` – tháng tính tiền + đơn giá dự phòng.
- `RoomMonthlyBills` – hóa đơn phòng/tháng, các cột tiền điện/nước được tính sẵn.
- `PaymentSettings`, `BillDeliveryLogs` – cấu hình QR/SMTP và lịch sử gửi.
- `AppUsers` – tài khoản đăng nhập của chủ nhà.
- `Tenants.PortalToken` – mã link app của khách; `RoomMonthlyBills.PaidAt` – thời điểm đánh dấu đã thu tiền. Khi nâng cấp DB cũ, hóa đơn các tháng trước tháng hiện tại được coi là đã thu (trước đây chưa theo dõi).
- View `v_MonthlyRoomBills` – hóa đơn kèm **khách thuê của đúng tháng đó** (theo ngày vào/ra), không phải khách hiện tại.

**Quy tắc tính giá** (ưu tiên từ trên xuống): giai đoạn đơn giá đặt tay của phòng → giá thỏa thuận của lượt thuê trong tháng → giá mặc định của phòng. Phòng không có khách trong tháng chỉ tính điện nước.

## Kiểm thử

```powershell
pip install -r requirements-dev.txt
python -m playwright install chromium webkit   # cho test giao diện điện thoại (tùy chọn)
pytest
```

Test chạy trên database riêng `QuanLyPhongTro_PyTest` (tạo mới mỗi lần), không đụng dữ liệu thật. `tests/test_e2e_mobile.py` mở app trong trình duyệt giả lập Android (Chromium, Pixel 7) và iPhone (WebKit, iPhone 13): kiểm tra tràn màn hình, menu, đánh dấu thu tiền, app của khách; tự bỏ qua nếu chưa cài Playwright.

## Xem database bằng giao diện

Dùng extension **SQL Server (mssql)** trong VS Code hoặc SSMS, kết nối tới `(localdb)\QuanLyPhongTro2025` bằng Windows Authentication.
