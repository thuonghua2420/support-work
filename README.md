# AutoCompare Tool

AutoCompare là công cụ web chạy local dành cho kiểm thử CSV/UT trên Windows. Ứng dụng tái sử dụng các workflow Python hiện có để sao chép dữ liệu, tạo workbook so sánh, review FIXME, xử lý file và trao đổi dữ liệu với cơ sở dữ liệu.

## Khởi động

Yêu cầu Python 3.10 trở lên.

```bat
run.bat
```

Lệnh trên tự tạo `.venv`, cài dependencies, khởi động server tại `http://127.0.0.1:8765` và mở trình duyệt.

Để dùng port khác:

```bat
run.bat 9000
```

Hoặc chạy trực tiếp:

```bat
.venv\Scripts\python.exe -m autocompare_tool --port 9000
```

Các tùy chọn hữu ích:

```bat
.venv\Scripts\python.exe -m autocompare_tool --host 127.0.0.1 --port 8765 --no-browser
```

Server mặc định chỉ bind vào `127.0.0.1`; không nên dùng `0.0.0.0` trên máy hoặc mạng không tin cậy vì ứng dụng có quyền thao tác file local và kết nối database.

Giao diện Tkinter cũ vẫn có thể mở tạm thời bằng:

```bat
.venv\Scripts\python.exe -m autocompare_tool --desktop
```

## Chức năng

- **So sánh UT**: chọn folder chứa các case `UT*`, chạy các workflow trong `autocompare_config.ini`, tạo Excel tại `Output\Compare`, xem trực tiếp workbook compare trên trình duyệt và review/apply ghi chú FIXME.
- **So sánh 2 folder CSV**: quét đệ quy hai folder bất kỳ và tạo một workbook tổng hợp, bao gồm file chỉ tồn tại ở một phía.
- **Tiện ích file**: đổi tên, xóa, di chuyển file/folder, đổi tên sheet Excel và tìm/xóa folder trống.
- **Sao chép file UT**: chạy logic tương thích từ `copy_ut_files.py` và tạo log chi tiết trong `copy_logs`.
- **Format ảnh Excel**: resize và sắp xếp ảnh trong workbook theo vùng Input/Steps/Output, đồng thời giữ nguyên ảnh, VBA và button.
- **SQL Studio**: format SQL và phân tích table/alias, điều kiện, CTE, subquery, SELECT expression theo cây cú pháp.
- **CSV ↔ Database**: test kết nối, chuẩn hóa CSV, import CSV và export table cho SQL Server, MySQL, PostgreSQL và Oracle.
- **Đồng bộ 2 CSDL**: đồng bộ chênh lệch theo primary key, insert thêm hoặc truncate rồi đồng bộ lại.

Các thao tác xóa, import, export và đồng bộ luôn yêu cầu xác nhận rõ ràng trên giao diện web. DB import không tự truncate table.

Nhật ký tác vụ nằm ở bong bóng góc phải dưới. Log không tự xóa khi chạy tác vụ mới; mỗi tác vụ có thời gian bắt đầu/kết thúc, thời gian xử lý và dòng phân cách `-----------------------------------------`.

## Format ảnh và workbook Excel

Chọn folder chứa workbook `.xlsx`, `.xlsm`, `.xlsb` hoặc `.xls`. Công cụ áp dụng font và cỡ chữ cho toàn bộ sheet, đưa mỗi sheet về ô `A1`, kéo thanh cuộn ngang/dọc về đầu và chọn sheet đầu tiên trước khi lưu. Khi bật căn ảnh, công cụ dùng logic tham khảo từ `sampleformatimage/sample.vba` để resize ảnh, tách ảnh trái/phải, ghép theo row overlap và sắp xếp lại trong các vùng `Input`, `Steps`, `Output` để ảnh không đè lên nhau. Logic này chạy trực tiếp qua Excel COM nên `.xlsx` cũng căn ảnh được, không cần workbook chứa macro.

Ô **Giữ nguyên size cho các row** nhận nhiều quy tắc, mỗi quy tắc một dòng:

- `Header`: giữ nguyên cỡ chữ của mọi row có cell bằng chính xác `Header` (không phân biệt hoa/thường).
- `(Header, A1)`: chỉ giữ nguyên cỡ chữ của row chứa `A1` khi giá trị tại `A1` bằng `Header`.

Font name vẫn được áp dụng cho các row này; phần loại trừ chỉ áp dụng cho font size. Có thể đặt tên và lưu font, size cùng toàn bộ quy tắc thành preset JSON local, sau đó chọn lại từ combobox ở những lần chạy sau.

Mặc định workbook được copy theo đúng cấu trúc folder vào thư mục con `Formatted` rồi mới xử lý. Chỉ chọn **Ghi đè file gốc** khi đã có backup. Cả hai chế độ đều yêu cầu xác nhận vì kết quả cũ cùng tên có thể bị ghi đè.

Các marker sheet/shape/vùng ảnh và thông số layout như cột ảnh trái/phải, range width, border/header được cấu hình trong `[excel_image_format]` của `autocompare_config.ini`. Các chuỗi Nhật bị mojibake từ `sample.vba` được giữ trong config để dễ chỉnh khi gặp workbook khác encoding.

Tính năng này cần Microsoft Excel Desktop trên máy Windows. Dùng Excel COM thay vì `openpyxl` để không làm mất VBA, ảnh hoặc button có sẵn. Các preset cá nhân được lưu trong `excel_format_presets.json` và file này không được commit vào Git.

## SQL Studio

Tab **SQL Studio** có hai thao tác độc lập và không thực thi SQL trên database:

- **Format SQL**: chuẩn hóa keyword, xuống dòng và thụt lề; hỗ trợ nhiều statement trong cùng input, phân tách bằng dấu `;`.
- **Load sheet & format**: đọc SQL từ workbook `.xlsx/.xlsm/.xltx/.xltm`. Sheet cần có số thứ tự ở cột A; nội dung SQL chỉ lấy từ cột B và gom từ số thứ tự hiện tại đến số thứ tự tiếp theo. Nếu cột C cùng row có note, note đó được chèn vào output dạng comment `-- ...` cho dòng SQL tương ứng. Output được đánh dấu theo dạng `-- SQL No.1`.
- **Phân tích toàn bộ**: parse SQL thành AST rồi liệt kê từng table/reference cùng alias, vai trò `FROM`/`JOIN`/DML target và scope. Kết quả còn gồm điều kiện `WHERE`, `JOIN ON/USING`, `HAVING`, `QUALIFY`, `MERGE ON`, `START WITH`, `CONNECT BY`, `CASE/IF`, CTE, subquery, SELECT expression, `GROUP BY`, `ORDER BY`, `LIMIT/OFFSET`.

Có thể chọn dialect SQL Server, MySQL, PostgreSQL, Oracle, SQLite, BigQuery, Snowflake, Spark, Databricks hoặc DuckDB. Chế độ tự động dùng SQL phổ thông; với cú pháp riêng của hệ quản trị nên chọn đúng dialect để parser không hiểu nhầm. Ứng dụng không đặt giới hạn riêng về số dòng/độ dài SQL; giới hạn thực tế phụ thuộc bộ nhớ khả dụng của máy và trình duyệt.

## Chọn đường dẫn

Trình duyệt web không cho phép website đọc đường dẫn tuyệt đối từ file picker thông thường. Vì AutoCompare xử lý trực tiếp dữ liệu local, các nút **Chọn folder/file** mở trình duyệt filesystem do server local cung cấp. Người dùng cũng có thể nhập hoặc dán đường dẫn Windows trực tiếp.

## Cấu hình

`autocompare_config.ini` chứa:

- `[folders]`: tên `Input`, `Output`, `Compare` và các folder before/after.
- `[workbooks]`: tên các workbook được tạo.
- `[excel_headers]`: header/text trong file compare Excel, gồm `FIXME`.
- `[excel_compare_style]`: mã màu font/fill dùng khi tạo file compare Excel.
- `[compare_workflows]`: trạng thái mặc định của các luồng so sánh.
- `[excel_image_format]`: marker và thông số layout cho chức năng căn ảnh Excel.

Giá trị ghi chú FIXME do người dùng tạo được lưu tại `fixme_notes.json`.

## Quy tắc CSV quan trọng

- Compare CSV hỗ trợ `utf-8-sig`, `utf-8` và `cp932`.
- DBeaver CSV phân biệt ô trống không quote (`NULL`) với chuỗi rỗng có quote (`""`).
- Export DB ghi string có quote, numeric không quote và `NULL` là ô trống không quote.
- Normalize/import quét đệ quy mọi file `*.csv` bên dưới folder đã chọn và map table theo tên file.

## Cấu trúc UT và kết quả compare

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

Mỗi case có thể tạo tối đa ba workbook theo các checkbox đang bật:

- `Compare新_Before_After.xlsx`
- `Compare現行_Before_After.xlsx`
- `Compare現行_vs_新_After_After.xlsx`

Mỗi lần chạy, CSV cũ trong hai folder before được làm mới từ `Input`. File before không có file after tương ứng bị loại bỏ. Workbook của workflow đang tắt cũng được xóa để tránh đọc nhầm kết quả cũ.

Record được ghép bằng cột đầu tiên của CSV cộng với thứ tự xuất hiện khi key bị trùng. Record chỉ có ở một phía được giữ lại với giá trị phía còn lại để trống. Các cột metadata `ValidationErrors`, `HasErrors`, `TargetProperties` và `DataState` được bỏ qua khi compare.

## FIXME review

Sau compare, giao diện hiển thị case UT, workbook, sheet thật trong workbook, CSV nguồn, column, hai giá trị, số record và combobox ghi chú. Mỗi header có filter riêng để tìm nhanh các nhóm FIXME có điểm chung.

Người dùng có thể tick dòng hoặc chọn toàn bộ dòng đang lọc, gán/xóa note hàng loạt rồi bấm **Áp dụng ghi chú** một lần để thay cell `FIXME` tương ứng trong workbook. Nếu nhiều mismatch cùng trỏ đến một cell FIXME, các ghi chú duy nhất được nối theo thứ tự bằng xuống dòng. Danh sách note được lưu trong `fixme_notes.json`.

## Database CSV

Quy trình cơ bản:

1. Chọn loại CSDL và nhập thông tin kết nối.
2. Bấm **Test Database Connection**.
3. Chọn **Chuẩn hóa CSV**, **Import CSV** hoặc **Export CSV**.

Mỗi CSV được map với table theo tên file không gồm `.csv`. CSV không có table tương ứng được bỏ qua. CSV header không tồn tại trong table là lỗi. Import bỏ qua computed/generated/rowversion; identity chỉ được giữ khi người dùng bật tùy chọn và adapter hỗ trợ.

Trước khi bấm **Import**, chọn một trong ba chế độ xử lý dữ liệu hiện có:

- **Insert thêm**: giữ nguyên dữ liệu hiện có và chỉ insert các dòng CSV.
- **Xóa record trùng key**: xóa record có cùng toàn bộ primary key (hỗ trợ key ghép) rồi insert. CSV phải có đủ primary key; nếu primary key là identity thì phải bật giữ identity.
- **Truncate toàn table**: truncate từng table tương ứng với CSV trước khi insert. Chế độ này xóa toàn bộ dữ liệu cũ và luôn hiển thị cảnh báo xác nhận.

CSV có primary key `NULL` hoặc lặp key ngay trong chính CSV sẽ bị từ chối trước khi chạy lệnh xóa. Table không có primary key không dùng được chế độ xóa record trùng key. Một số database tự commit `TRUNCATE`, vì vậy bước truncate có thể không rollback được nếu insert sau đó lỗi.

### Đồng bộ 2 CSDL

Giao diện cung cấp ba phương thức:

- **Chỉ đồng bộ chênh lệch**: stream hai table theo primary key, chỉ insert record có ở nguồn, update record cùng key nhưng khác dữ liệu và tùy chọn delete record chỉ có ở đích. Đây là chế độ mặc định.
- **Insert thêm**: insert toàn bộ record nguồn mà không so sánh dữ liệu hiện có.
- **Truncate & insert lại**: xóa toàn bộ table đích rồi insert lại dữ liệu nguồn.

Chế độ chênh lệch yêu cầu table nguồn và đích có cùng primary key, hỗ trợ primary key ghép. Nếu key là identity phải bật **Giữ identity**. Dữ liệu được đọc bằng `fetchmany()` và thay đổi được ghi theo batch, mặc định 5.000 record, nên không nạp toàn bộ table vào RAM. Chế độ này không cho dùng giới hạn record vì việc dừng giữa table có thể khiến kết quả không còn phản ánh chính xác dữ liệu nguồn.

Không bật **Xóa record chỉ có ở đích** nếu muốn giữ dữ liệu riêng của database đích. Khi bật, sau khi chạy thành công database đích sẽ giống nguồn đối với các column có thể đồng bộ. Nên tránh ghi đồng thời vào hai table trong lúc đồng bộ; datatype và collation của primary key cần tương thích để thứ tự streaming nhất quán.

Đồng bộ chênh lệch vẫn phải đọc hai table để tìm khác biệt, nhưng chỉ ghi các record thực sự thay đổi. Muốn chỉ đọc phần thay đổi cho những lần chạy sau cần thêm CDC/Change Tracking hoặc column cập nhật đáng tin cậy ở cấp database.

Khi export, bỏ trống danh sách table để xuất toàn bộ table trong schema. Có thể phân tách danh sách table bằng dấu phẩy, chấm phẩy hoặc xuống dòng.

Ví dụ phân biệt empty string và `NULL`:

```csv
id,amount,empty_value,null_value,text
1,3456.0000,"",,"Alice"
```

Trong dòng trên, `empty_value` là chuỗi rỗng và `null_value` là `NULL`.

## Sao chép file UT

Workflow này tiếp tục dùng `copy_ut_files.py`:

- Sao chép từ `UT*/input` của nguồn sang cấu trúc input ở đích.
- Sao chép từ `UT*/output` của nguồn sang cấu trúc output hệ thống hiện tại ở đích.
- Nếu đích đã có CSV, công cụ so sánh value/raw format và ghi log trước khi ghi đè.
- Log được tạo trong `copy_logs` cạnh `copy_ut_files.py`.

## SQL Workspace trong Database

Trang Database dùng một hub kết nối nhỏ ở phần tiêu đề; bấm **Kết nối CSDL** để mở popup cấu hình dùng chung cho cả ba tab:

- **Database 1** dùng cho CSV import/export, SQL Workspace và làm nguồn đồng bộ.
- **Database 2** chỉ dùng làm database đích khi đồng bộ.

Tab **SQL Workspace** kế thừa formatter/analyzer cũ, đồng thời có thể chạy SQL trực tiếp trên Database 1. `Format SQL`, `Phân tích toàn bộ` và `Load sheet & format` dùng chung một editor; SQL đã format sẽ ghi đè trực tiếp vào vùng **SQL đầu vào**. Các chức năng format/phân tích vẫn chạy khi chưa kết nối DB. `Chạy hiện tại` chạy vùng đang bôi đen hoặc statement tại caret; `Chạy toàn bộ` chạy toàn bộ statement theo thứ tự. Mặc định backend chỉ cho statement đọc. DDL/DML cần bật **Ghi DB**, token tạm thời gắn với fingerprint của Database 1 và tự hết hạn theo `[database_workspace].write_mode_timeout_minutes`; đổi connection sẽ hủy verified state, tắt chế độ ghi và đánh dấu kết quả SQL cũ là stale.

Kết quả query được đọc bằng `fetchmany()` và spool tạm theo workspace để phân trang, không `fetchall()` toàn bộ result set. Source Data chỉ hiển thị record khi module lineage chứng minh được query rewrite exact; nếu gặp aggregate, CTE/derived phức tạp, correlated subquery hoặc cấu trúc chưa hỗ trợ thì card vẫn hiện nhưng không fallback sang toàn table.

Source grid hiển thị header hai tầng gồm index column, icon key cho primary key, datatype và màu usage: JOIN ưu tiên cao nhất, WHERE màu xanh lá, SELECT màu vàng. Join group được hợp nhất bắc cầu, ví dụ `A.x = B.y` và `A.x = C.z` sẽ tô cùng màu cho cả ba column. Hover vào column JOIN hiển thị các column cùng group.

Export source CSV ghi theo chuẩn DBeaver: `NULL` là ô trống không quote, empty string là `""`, string được quote, numeric không quote và CRLF. Khi xác định được complement exact, CSV có thêm đúng một negative record ở dòng cuối nhưng record này không hiển thị trên web. Inline Update chỉ bật cho base table có đầy đủ primary key; view/CTE/subquery/table không PK là read-only. Update dùng parameter, kiểm tra hash toàn row trước khi ghi và rollback toàn bộ nhóm nếu có conflict.

`autocompare_config.ini` có `[database_workspace]` để chỉnh page size, timeout, batch export và giới hạn spool tạm.

## Test

```bat
.venv\Scripts\python.exe -m unittest discover -s tests
```

Nếu `.venv` trỏ tới bản Python đã bị gỡ, hãy xóa `.venv` rồi chạy lại `run.bat` sau khi cài Python 3.10+ để tạo lại môi trường.
