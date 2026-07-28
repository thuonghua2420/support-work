# Công Cụ Python AutoCompare

Tool này sao chép CSV từ `Input` vào các folder `before...`, sau đó so sánh các cặp `before/after` và tạo Excel trong `Output\Compare`.

## Cách Chạy

1. Cài Python 3.10 trở lên và bật tùy chọn `Add Python to PATH`.
2. Double-click `run.bat`.
3. Dùng thanh `Menu chính` bên trái để chọn chức năng cần chạy.

Menu hiện có:

- `So sánh`: chọn folder cha chứa các folder `UT*`, chọn checkbox so sánh, bấm `Chạy so sánh`, và review/apply ghi chú FIXME.
- `So sánh 2 folder CSV`: chọn 2 folder CSV bất kỳ và tạo 1 file Excel so sánh.
- `Sao chép file UT`: sao chép CSV từ nguồn sang đích theo luồng xử lý UT.
- `Kết nối SQL Server`: kiểm tra đăng nhập DB và chuẩn hóa CSV theo metadata SQL Server.

`run.bat` sẽ tự tạo `.venv`, cài `openpyxl`, và mở GUI.

## File Config

Những giá trị dùng để thay đổi cấu trúc folder/output nằm trong `autocompare_config.ini`.

File này có comment cho từng config:

- `[folders]`: tên folder `Input`, `Output`, `Compare`, các folder before/after của HTM và HTC.
- `[workbooks]`: tên các file Excel xuất ra.
- `[excel_headers]`: các header/text trong file compare Excel, bao gồm `FIXME`.
- `[compare_workflows]`: checkbox nào được chọn mặc định khi mở GUI.

## Sao Chép File UT

Menu `Sao chép file UT` gồm 2 path:

- `Đường dẫn nguồn 1`: folder nguồn chứa các folder `UT*`.
- `Đường dẫn đích 2`: folder đích để tạo hoặc sao chép cấu trúc các folder `UT*`.

Bấm `Chạy sao chép file UT` để chạy logic trong `copy_ut_files.py`.

Logic sao chép hiện có:

- Sao chép từ `UT*/input` của nguồn sang `UT*/入力` của đích.
- Sao chép từ `UT*/output` của nguồn sang `UT*/出力/現在のシステム以降` của đích.
- Nếu đích đã có file CSV, tool so sánh value/raw format và ghi chi tiết vào log trước khi ghi đè.
- Log được tạo trong folder `copy_logs` cạnh `copy_ut_files.py`.

## So Sánh 2 Folder CSV

Menu `So sánh 2 folder CSV` gồm 3 path:

- `Folder bên trái`: folder CSV nguồn bên trái.
- `Folder bên phải`: folder CSV nguồn bên phải.
- `File Excel xuất ra`: file Excel so sánh sẽ được tạo.

Bấm `Chạy so sánh folder CSV` để tạo workbook so sánh. Luồng này dùng cùng logic compare hiện tại và quét đệ quy toàn bộ file CSV ở cả 2 folder; file chỉ tồn tại ở một bên vẫn được đưa vào workbook xuất ra.

## Chuẩn Hóa CSV SQL Server

Menu `Kết nối SQL Server`:

- Driver: mặc định `ODBC Driver 18 for SQL Server`.
- Máy chủ, cơ sở dữ liệu.
- Xác thực Windows hoặc người dùng/mật khẩu.
- Schema: mặc định `dbo`.

Máy chạy tool cần có Microsoft ODBC Driver for SQL Server, vì `pyodbc` sẽ dùng driver này để kết nối.

Quy trình:

1. Nhập thông tin DB.
2. Bấm `Kiểm tra đăng nhập DB`.
3. Sau khi login thành công, bấm `Chuẩn hóa CSV`.

Tool sẽ duyệt tất cả CSV trong folder đang chọn, bao gồm cả CSV trong folder con bên dưới. Mỗi CSV được map với table thật trong DB theo tên file không gồm `.csv`.

```text
customers.csv -> <schema>.customers
orders.csv    -> <schema>.orders
```

Nếu không tìm thấy table tương ứng trong DB, CSV đó sẽ được bỏ qua và tool tiếp tục xử lý các file còn lại.

Tool chỉ đọc metadata column order và datatype từ SQL Server, sau đó reorder/normalize CSV tại chỗ theo thứ tự column trong DB.

Tool không `TRUNCATE`, không `INSERT`, và không ghi đè value thông qua datatype/constraint/trigger của SQL Server.

Format export:

- Delimiter: `,`
- Header: top, label, as-is
- Quote character: `"`
- Escape quote: double quote
- Quote always strings
- NULL string: blank
- Empty string: `""`
- Cột `datetime`, `datetime2`, `smalldatetime`: output `yyyy-MM-dd HH:mm:ss.fff`
- Cột `decimal`, `numeric`, `money`, `smallmoney`: output 4 số sau dấu chấm, ví dụ `3456.0` -> `3456.0000`

Ví dụ:

```csv
id,empty_value,null_value
"1","",
```

Trong dòng data trên, `empty_value` là empty string, `null_value` là NULL.

Lưu ý: cột CSV phải tồn tại trong table DB tương ứng. Nếu CSV có cột không có trong DB, tool sẽ báo lỗi và không ghi đè file đó.

## Cấu Trúc Folder Dự Kiến

```text
Root
  UT01-001
    Input
      customers.csv
      orders.csv
    Output
      before新システム出力データ
      after新システム出力データ
      before現行システム出力データ
      after現行システム出力データ
      Compare
```

## Kết Quả

Mỗi `UT*` có thể tạo tối đa 3 file, tùy theo checkbox đã chọn:

- `Output\Compare\Compare新_Before_After.xlsx`
- `Output\Compare\Compare現行_Before_After.xlsx`
- `Output\Compare\Compare現行_vs_新_After_After.xlsx`

Với compare before/after, danh sách sheet lấy theo các file CSV trong folder bên phải/after. Với compare after/after của 2 hệ thống, danh sách sheet lấy theo tập hợp file CSV của cả 2 folder after. Tên sheet là tên file không gồm `.csv`. Record được map bằng cột đầu tiên của mỗi CSV.

Nếu một checkbox không được chọn, workbook xuất ra tương ứng trong `Output\Compare` sẽ bị xóa nếu đang tồn tại từ lần chạy trước.

## Kiểm Tra FIXME

Sau khi `Chạy so sánh`, GUI sẽ hiển thị toàn bộ dòng sai khác đang có `FIXME` theo dạng table:

```text
Tên folder UT -> Tên file Excel -> Tên sheet -> Tên cột -> Giá trị bên trái -> Giá trị bên phải -> STT record -> Combobox ghi chú
```

Để thêm ghi chú cho combobox:

1. Bấm `Thêm giá trị combobox`.
2. Nhập `Ghi chú` và `Ý nghĩa`.
3. Bấm `Lưu ghi chú`.

Có thể chọn ghi chú trong danh sách bên dưới để cập nhật hoặc xóa. Sau khi chọn ghi chú cho các dòng sai khác, bấm `Áp dụng ghi chú đã chọn` để thay thế các cell `FIXME` tương ứng trong file Excel.

Danh sách ghi chú được lưu trong `fixme_notes.json` sau khi người dùng bấm `Lưu ghi chú`.

## Quy Tắc Xử Lý

- Mỗi lần chạy sẽ xóa CSV cũ trong 2 folder `before...`, rồi sao chép lại toàn bộ CSV từ `Input`.
- File CSV chỉ có trong `before...` sẽ bị xóa khỏi folder `before...` sau bước sao chép, vì folder `after...` là nguồn ưu tiên.
- Record chỉ có trong `after` sẽ để trống cột before.
- Record chỉ có trong `before` sẽ để trống cột after.
- Nếu key trùng nhau, tool dùng key + thứ tự xuất hiện để map deterministic.
- Các cột metadata giống nguồn mẫu sẽ bị bỏ qua: `ValidationErrors`, `HasErrors`, `TargetProperties`, `DataState`.
- Compare after/after của 2 hệ thống dùng folder after HTC làm bên trái và after HTM làm bên phải.

## Chạy Test

Sau khi các thư viện phụ thuộc đã được cài:

```bat
.venv\Scripts\python.exe -m unittest discover -s tests
```

## Tài Liệu Quản Lý Dự Án

- `AGENTS.md`: hướng dẫn nhanh cho coding agent.
- `.agents/`: project memory gồm context, architecture, conventions, roadmap, và decisions.
