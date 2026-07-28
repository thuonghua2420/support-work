# Công Cụ Python AutoCompare

Tool này sao chép CSV từ `Input` vào các folder `before...`, sau đó so sánh các cặp `before/after` và tạo Excel trong `Output\Compare`.

## Cách Chạy

1. Cài Python 3.10 trở lên và bật tùy chọn `Add Python to PATH`.
2. Double-click `run.bat`.
3. Dùng thanh `Menu chính` bên trái để chọn chức năng cần chạy.

Menu hiện có:

- `So sánh`: chọn folder cha chứa các folder `UT*`, chọn checkbox so sánh, bấm `Chạy so sánh`, và review/apply ghi chú FIXME.
- `So sánh 2 folder CSV`: chọn 2 folder CSV bất kỳ và tạo 1 file Excel so sánh.
- `Tiện ích file`: đổi tên, xóa, di chuyển file/folder và kiểm tra folder trống.
- `Sao chép file UT`: sao chép CSV từ nguồn sang đích theo luồng xử lý UT.
- `Cơ sở dữ liệu`: kiểm tra kết nối CSDL, chuẩn hóa CSV, nhập CSV vào CSDL và xuất CSDL ra CSV.

`run.bat` sẽ tự tạo `.venv`, cài các thư viện trong `requirements.txt`, và mở GUI.

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

## Tiện Ích File

Menu `Tiện ích file` dùng chung `Folder thao tác` cho các thao tác theo folder và có các tab:

- `Đổi tên`: đổi tên file/folder theo tên chính xác, hoặc thay thế text trong tên file/folder.
- `Xóa`: xóa file/folder khi tên có chứa text đã nhập.
- `Sheet Excel`: đổi tên sheet trong một file Excel khi tên sheet có chứa text đã nhập.
- `Di chuyển`: di chuyển file có tên chứa text vào folder đích cùng cấp với file, theo logic của `movefile.py`.
- `Folder trống`: kiểm tra folder trống hoặc xóa toàn bộ folder trống bên dưới `Folder thao tác`.

Các thao tác xóa sẽ hỏi xác nhận trước khi chạy.

## Cơ Sở Dữ Liệu

Menu `Cơ sở dữ liệu` có 2 vùng:

- `Thông tin kết nối CSDL`: chọn loại CSDL và nhập thông tin kết nối.
- `Nhập/Xuất CSV`: chọn `Folder CSV`, chạy chuẩn hóa, nhập CSV vào CSDL hoặc xuất CSDL ra CSV.

Các loại CSDL đang có adapter sẵn:

- SQL Server qua `pyodbc`.
- MySQL qua `mysql-connector-python`.
- PostgreSQL qua `psycopg`.
- Oracle qua `oracledb`.

Với SQL Server, máy chạy tool vẫn cần Microsoft ODBC Driver for SQL Server.

Quy trình cơ bản:

1. Chọn `Loại CSDL` và nhập thông tin kết nối.
2. Bấm `Kiểm tra kết nối CSDL`.
3. Sau khi kết nối thành công, chọn `Chuẩn hóa CSV`, `Nhập CSV vào CSDL` hoặc `Xuất CSDL ra CSV`.

Tool duyệt tất cả CSV trong `Folder CSV`, bao gồm cả CSV trong folder con bên dưới. Mỗi CSV được map với table thật trong CSDL theo tên file không gồm `.csv`.

```text
customers.csv -> <schema>.customers
orders.csv    -> <schema>.orders
```

Nếu không tìm thấy table tương ứng trong CSDL, CSV đó sẽ được bỏ qua và tool tiếp tục xử lý các file còn lại.

### Chuẩn Hóa CSV

Tool đọc metadata column order và datatype từ CSDL, sau đó reorder/normalize CSV tại chỗ theo thứ tự column trong table.

### Nhập CSV Vào CSDL

- CSV header phải tồn tại trong table tương ứng. Nếu CSV có cột không có trong CSDL, file đó sẽ báo lỗi.
- Column computed/generated/rowversion sẽ được bỏ qua khi nhập vì giá trị do CSDL tự sinh.
- Checkbox `Giữ nguyên giá trị identity khi nhập` quyết định có insert giá trị identity từ CSV hay để CSDL tự sinh.
- SQL Server sẽ bật/tắt `IDENTITY_INSERT` theo từng table khi cần giữ identity.
- PostgreSQL sẽ dùng `OVERRIDING SYSTEM VALUE` khi cần giữ identity.
- Oracle `GENERATED ALWAYS AS IDENTITY` không cho insert trực tiếp, nên column đó sẽ bị bỏ qua và ghi log.
- Tool không tự `TRUNCATE` table trước khi nhập.

### Xuất CSDL Ra CSV

Nếu `Bảng xuất` bỏ trống, tool xuất tất cả table trong schema hiện tại. Có thể nhập danh sách table, phân tách bằng dấu phẩy, chấm phẩy hoặc xuống dòng.

Format CSV:

- Delimiter: `,`
- Header: top, label, as-is
- Quote character: `"`
- Escape quote: double quote
- Giá trị `NULL`: ô trống không quote, ví dụ `,,`
- Empty string: `""`, ví dụ `,"",`
- Cột kiểu chuỗi: luôn được bọc bởi `"`
- Cột kiểu số: không quote; column có scale thập phân sẽ giữ số lẻ theo metadata CSDL
- Cột datetime/time: output có millisecond `.fff`

Ví dụ:

```csv
id,amount,empty_value,null_value,text
1,3456.0000,"",,"Alice"
```

Trong dòng data trên, `empty_value` là empty string, `null_value` là NULL.

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
