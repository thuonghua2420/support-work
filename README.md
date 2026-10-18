# AutoCompare Tool

Compare CSV and Database use consistently styled checkbox/radio groups. CSV import can
scan the folder and import either all CSV tables or selected CSV tables; export
has a separate section sharing one CSV folder. SQL Workspace keeps its five
commands together and exposes Excel loading in the expandable "SQL tu Excel" row.
Import modes, database-write confirmations and saved input behavior are unchanged.

The workbook preview lists Sheet directly below File compare. In normal view the
whole sheet expands vertically with the page. Maximize uses the full browser viewport
and keeps the workbook selectors visible while the grid scrolls. Applying notes sends
every assigned note from all cases, workbooks and sheets in the current compare run;
the active sheet only controls what is visible.
Checkboxes selected in Workbook remain selected when changing sheets. The bulk
note action applies to every checked row across sheets and clears those ticks;
the current sheet's filter only controls which rows can be ticked there.

Trong tab Workbook, nút **Count record** mở bảng số record trái/phải cho mọi sheet
của file Compare đang chọn. Dòng lệch count được tô màu; có thể tìm sheet, lọc
chỉ dòng lệch và nhấp tên sheet để mở. Workbook mới lưu count gốc trong metadata
Excel mà không thêm sheet hoặc sửa dữ liệu ô. Với workbook cũ chưa có metadata,
bảng ghi nhãn **Ước tính** cho count suy ra từ các cặp record hiển thị.

## Giao diện Workspace

Giao diện dùng hệ thống màu trắng/xám trung tính và điểm nhấn slate, font Inter, các control
đồng bộ và sidebar chia nhóm chức năng. Các lựa chọn có trạng thái rõ ràng, vùng
nguồn Old/New tách biệt và các tùy chọn nâng cao có thể thu gọn. Compare có hai
tab Cấu hình và Workbook; sau khi xuất thành công sẽ mở workbook toàn màn hình.
Các bảng kết quả có nút phóng to; Escape trả về kích thước ban đầu. Menu trên màn
hình nhỏ đóng bằng Escape hoặc nhấn vùng bên ngoài.

Trang Excel chia riêng nguồn, định dạng và cách lưu. Database giữ các tab CSV,
SQL Workspace, đồng bộ và dialog kết nối. Các xác nhận ghi/xóa dữ liệu vẫn được giữ.
Font Inter và icon Lucide được phục vụ nội bộ, không cần CDN hoặc build frontend.

`web/workspace-theme.css` được tải cuối, quản lý màu sắc, typography, spacing,
control và responsive cho cả tám trang. `web/app.css` giữ các style bảng chuyên
biệt; `web/adminator.css` giữ cấu trúc workspace và chế độ phóng to;
`web/adminator.js` sắp xếp các control hiện có mà không thay đổi API nghiệp vụ.
Màu đánh dấu sai khác của workbook và màu cú pháp SQL được giữ riêng.
LOG nằm trong sidebar và ẩn khi xem workbook toàn màn hình. Các control hỗ trợ
focus bàn phím, giảm chuyển động và chế độ tương phản hệ thống.
CSV ↔ Database và Input SQL căn chiều cao vùng dữ liệu theo màn hình desktop;
nội dung dài cuộn bên trong khung. Màn hình hẹp hoặc khi mở hướng dẫn vẫn có thể
cuộn trang để không che nội dung. Đồng bộ chia thành chọn table và cách đồng bộ,
giữ cảnh báo xóa dữ liệu hiển thị, thu gọn tùy chọn batch/record limit.
`web/workspace-guides.js` cung cấp hướng dẫn thu gọn ở cuối từng chức năng, gồm
các thao tác nhỏ, cách đọc kết quả và cảnh báo ghi/xóa dữ liệu.
Hướng dẫn của các form nằm trong card tương ứng để không tràn chiều rộng;
hộp kết nối hai CSDL không có hướng dẫn riêng. File / Folder dùng icon nét
đồng bộ và hàng nút thao tác tách biệt khỏi vùng nhập liệu.
Không tải các script quảng cáo/analytics từ bản mẫu offline.

### Search & Replace — tìm và thay trong folder

Mở **Search & Replace**, nhập/chọn folder và **Load**. Sidebar có Search/Replace, cây kết quả theo file; vùng bên phải xem nội dung có số dòng, tô match và cú pháp. Kéo đường phân cách để đổi độ rộng; nội dung vừa viewport, từng vùng cuộn riêng.

- Tìm khi ngừng gõ 450 ms hoặc nhấn Enter; Shift+Enter nhập nhiều dòng. **Aa** Match Case, **ab** Whole Word, **.*** Regex; **AB** Preserve Case khi replace. Ctrl+Shift+F/H mở Search/Replace; Alt+C/W/R/P đổi tùy chọn, F4/Shift+F4 đi giữa matches. Có tìm lại, dừng, thu gọn và bỏ từng match/file khỏi kết quả.
- Include/exclude hỗ trợ `*`, `**`, `?`, `[a-z]`, `{sql,cs}`, nhiều mẫu cách bằng dấu phẩy; `./` neo tại folder gốc. Exclude ưu tiên và cắt cây con; mặc định bỏ `.git`, `node_modules`, `__pycache__`, `.venv`. **Không tự đọc `.gitignore` hoặc cấu hình VS Code**; nhập mẫu vào exclude nếu cần. Glob không phân biệt hoa/thường trên Windows.
- Regex chạy bằng **Python `re`**, không phải toàn bộ engine của VS Code. Hỗ trợ thêm named capture `(?<name>...)`, `\k<name>`; replacement có `$1`…`$99`, `$0`/`$&`, `$<name>`, `$$`, `\n`, `\r`, `\t`, `\u`, `\l`, `\U`, `\L`, `\E`. Ngoài chế độ regex, replacement là văn bản nguyên dạng. Search đối chiếu đúng LF/CRLF gốc, không tự chuẩn hóa; dùng `\r?\n` khi regex cần khớp cả hai.
- Replace một match, một file hoặc all đều tạo preview và cần xác nhận trước khi ghi. Bỏ kết quả bằng × sẽ loại nó khỏi Replace All. Thay đổi nội dung search hoặc replacement hủy preview cũ. Preview chỉ xem, không sửa trực tiếp source.
- Auto nhận BOM trước, rồi UTF-8 strict, sau đó CP932 (Windows Shift JIS). Có lựa chọn ép UTF-8/CP932/Shift JIS strict cho file không BOM. Nhận diện tự động có thể mơ hồ; chọn rõ encoding khi biết source. UTF-8/16/32 BOM giữ đúng byte/endian. Mọi byte **ngoài vùng replace** được giữ nguyên, kể cả LF/CRLF hỗn hợp và các mapping trùng của CP932. Chặn ký tự không encode/decode nguyên vẹn bằng encoding gốc; không dùng `errors=replace`.
- Trước ghi, kiểm tra toàn bộ file còn đúng snapshot; mỗi file được ghi qua file tạm cùng thư mục và atomic rename. Nếu lỗi I/O xảy ra giữa batch, báo số file đã ghi. **Undo replace** khôi phục nguyên byte của lần ghi gần nhất trong phiên server, kể cả batch ghi dở; chặn Undo nếu file đã đổi bên ngoài. Undo nằm trong RAM, không tồn tại sau khi restart. Đây không phải transaction đa file; tránh sửa source bằng chương trình khác trong lúc ghi.
- Search chạy trong tiến trình riêng, đọc đón tối đa 8 file song song, gửi kết quả dần và chỉ tạo số dòng khi có match. Có Dừng kể cả regex gây kẹt; giới hạn 120 giây/lượt, 100.000 file, 20.000 matches, 8 MiB/file. File nhị phân, lỗi encoding/quyền và symlink/junction được bỏ qua và báo trong giao diện. Kết quả bị giới hạn không được Replace All; thu hẹp include. Mỗi đợt replace giữ tối đa 128 MiB byte trước/sau. Search/replace text không lưu vào localStorage.

Triển khai riêng trong `search_replace.py`, `web/search-replace.js`, `web/search-replace.css`; dùng lại CodeMirror offline hiện có, không thêm dependency. Các tuỳ chọn tham chiếu [VS Code Search](https://code.visualstudio.com/docs/editing/codebasics#_search-across-files) và [glob reference](https://code.visualstudio.com/docs/editor/glob-patterns). Không khẳng định nhanh hơn VS Code trên mọi source.

Test backend: `.runtime-venv\Scripts\python.exe -B -m unittest discover -s tests -p test_search_replace.py`. Test browser: `node tests/web_search_replace_smoke.cjs` với Playwright (`NODE_PATH=.tmp/ui-check/node_modules`), Chrome và server cổng 8799 hoặc `AUTOCOMPARE_URL`. Chỉ ghi fixture trong `.tmp`/temp; bao phủ mixed encoding, BOM/EOL, CP932 aliases, regex, scope, giới hạn, conflict, lỗi ghi giữa batch, cancellation và Undo.

### File Compare — văn bản và cây thư mục

Mục **File Compare** trong menu có hai tab, độc lập với Compare CSV theo folder:

- **So sánh văn bản:** mở hai hoặc ba file bằng đường dẫn/bộ chọn file, hoặc dán vào editor. Ba file dùng B ở giữa làm mốc A↔B và B↔C, không tự merge. Tô màu dòng và đoạn ký tự khác, đánh số dòng, word-wrap, chỉnh sửa/undo, cú pháp theo tên file hoặc chọn thủ công, điều hướng Trước/Sau (Alt+↑/↓), thanh tổng quan có thể click và chế độ phóng to (Escape để thoát).
- Nhận diện dòng di chuyển dựa trên nguyên dòng trùng duy nhất ở hai bên và thuộc vùng thay đổi; đánh dấu tím, bấm ↔ để đến dòng đối ứng. Dòng lặp/đoạn đã sửa không được khẳng định là di chuyển. Đây không phải bản sao toàn bộ thuật toán WinMerge.
- Editor hỗ trợ UTF-8 (có/không BOM), UTF-16/32 có BOM và CP932, tối đa 1 MB / 10.000 dòng mỗi file. So màu dùng văn bản chuẩn hóa EOL; metadata và kết luận byte phân biệt BOM/encoding/LF/CRLF. Nội dung chỉ ở bộ nhớ trình duyệt, không lưu localStorage. Khi chưa chỉnh sửa, kết luận byte dựa trên SHA-256 của các file đã mở, không tự theo dõi thay đổi ngoài ứng dụng.
- **Lưu file** yêu cầu xác nhận, giữ encoding/BOM gốc, kiểm tra snapshot/byte hiện tại rồi thay file bằng bản tạm cùng thư mục. Chặn file chỉ đọc và file đổi bên ngoài, không tự tạo backup. File EOL hỗn hợp phải chọn LF/CRLF trước khi lưu. **Tải UTF-8** tải bản sao LF mà không ghi đè nguồn. Luôn sao lưu trước khi sửa tài liệu quan trọng.
- **So sánh thư mục:** quét đệ quy và đối chiếu byte (kể cả file nhị phân/lớn), phân loại giống/khác, Left only/Right only, khác loại, lỗi đọc, bỏ qua symlink/junction. Có cây thư mục thu gọn, danh sách phẳng, lọc trạng thái và mở cặp file bằng một click. Thư mục hai bên được hiển thị như nhóm, không được gắn nhãn "giống" chỉ vì tên khớp.
- Regex Python chạy trên đường dẫn tương đối dùng `/`, phân biệt hoa/thường; `(?i)` để không phân biệt. Bộ lọc loại trừ ưu tiên, cắt cả cây con; mặc định bỏ `.git`, `node_modules`, `__pycache__`, `.log`, `.tmp`. Bao gồm áp dụng cho file; nhóm thư mục được giữ để thể hiện cấu trúc. Tối đa 20.000 mục mỗi phía. Quét là read-only, chạy trong tiến trình riêng, có Hủy và giới hạn 30 giây cho bước không tiến triển (kể cả regex gây kẹt).

Triển khai: `text_compare.py` (đọc/lưu/quét), `web/text-compare.js` và `.css` (UI). Thư viện editor được đóng gói offline trong `web/vendor/codemirror`: CodeMirror 5.65.21 (MIT), diff-match-patch 1.0.5 (Apache-2.0), kèm LICENSE; bản diff-match-patch chỉ thêm guard CommonJS để chạy trực tiếp trong browser. Không cần npm hoặc Internet khi chạy ứng dụng. Cú pháp hỗ trợ JavaScript/TypeScript, JSON, Python, SQL, C/C++/C#/Java, HTML/XML, CSS, Markdown, Shell và YAML.

Kiểm thử: `python -B -m unittest discover -s tests -p test_text_compare.py`; kiểm thử trình duyệt `node tests/web_text_compare_smoke.cjs` với Playwright từ `.tmp/ui-check/node_modules` và server local cổng 8799. Smoke test chỉ ghi fixture trong `.tmp`, không ghi dữ liệu người dùng hay kết nối CSDL.

Kiểm tra theme với server local đang chạy (không chạy tác vụ, không ghi file dữ
liệu và không kết nối database; workbook kiểm thử dùng response giả lập):

```powershell
npm.cmd install --prefix .tmp/ui-check --no-save playwright
$env:NODE_PATH = "$PWD/.tmp/ui-check/node_modules"
$env:AUTOCOMPARE_URL = "http://127.0.0.1:8770"
node tests/web_theme_smoke.cjs
```

Test dùng Chrome đã cài, kiểm tra tám trang ở năm chiều rộng (390–1920px), các
tab/dialog, căn chữ SQL, menu, LOG và workbook toàn màn hình. Ảnh kiểm tra theme
được lưu trong `.tmp/theme-screenshots`.

Zoom sheet mặc định của file Excel xuất từ Compare CSV và compare theo folder là 85%, áp dụng cho mọi sheet khi xuất gộp hoặc xuất riêng từng file. Ô Zoom sheet trong cấu hình Compare CSV cho phép thay đổi mức zoom; trình duyệt vẫn ghi nhớ giá trị người dùng đã chọn.

Trong **Compare CSV > Cấu hình**, nhấn **Cấu trúc thư mục** để chỉnh tên các folder nguồn, Output, before/after HTM–HTC, folder Compare và ba file Excel ngay trên cây thư mục của case UT. **Lưu cấu hình** cập nhật `autocompare_config.ini` và áp dụng ngay cho các lần compare/load workbook tiếp theo, không cần khởi động lại. Thao tác này chỉ thay đổi cấu hình, không đổi tên hay di chuyển dữ liệu hiện có. Các tên cùng cấp phải khác nhau, tên file phải có đuôi `.xlsx`. **Tải lại** lấy bản cấu hình mới nhất từ file; hệ thống sẽ báo xung đột nếu file đã thay đổi ở nơi khác trước khi lưu, đồng thời giữ nguyên phần config và comment không liên quan.

Ô **Mẫu tên case** ở gốc cây được lưu thành `[folders] case_pattern`, mặc định `UT*` nếu config cũ chưa có mục này. Có thể nhập tên chính xác (`Scenario A`) hoặc mẫu tên (`Case*`, `Test_??`); `*` khớp nhiều ký tự, `?` khớp một ký tự, không phân biệt hoa/thường. Compare CSV, Load file Compare và trích xuất key theo thư mục dùng chung mẫu này. Chọn một case trực tiếp hoặc folder cha chứa các case; mẫu `*` cho phép quét mọi tên folder con. Compare theo folder không phụ thuộc mẫu tên case.

## Update Compare Keys

In Database > Trích xuất key, select a connected Database 1 or Database 2 and use
**Trich xuat key**. The tool reads primary-key metadata for all tables in the
selected database/schema and rewrites `[update_compare_keys]` with the complete
keys it can extract, including composite keys. The existing database adapters
support SQL Server, MySQL, PostgreSQL and Oracle. No database rows are written.
Tables without a primary key are skipped with a log entry. The saved table/key
list is used on the next compare without restarting. **Xoa key** clears all
entries in this section, including manual entries, after confirmation; other
config sections and CSV files are preserved.

A database primary key needs stable values between before and after for matching.
If an identity key changes, use a suitable stable business key instead. Per-table
keys in `autocompare_config.ini` use the CSV filename without `.csv`:

```ini
[update_compare_keys]
ORDERS = ORDER_NO, DETAIL_NO
```

Compare CSV > Cấu hình has two independent checkboxes, both off by default:

- **Copy các file từ folder input qua before** copies Input CSVs into both before
  folders, creating them as needed and overwriting matching filenames without
  clearing existing files. With this off, compare uses the existing before folders.
  After HTC versus HTM never requires Input or before and ignores this checkbox.
- **Sắp xếp record theo key và lưu vào CSV** sorts both sides of selected workflows
  in place by every configured key column, using ascending text order. The workbook
  then pairs records by position from top to bottom. Missing columns/config or
  duplicate/blank/NULL keys stop the selected workflow with an error instead of
  creating an unsorted workbook. Original CSV encoding, quoting,
  values and record counts are preserved, including NULL versus quoted empty string.

Default checkbox states are `copy_input_enabled` and `sort_by_key_enabled` under
`[compare_workflows]`. The UI also remembers choices in its existing input cache.
Compare never automatically filters/deletes records, CSV files or before folders,
and equal sheets are retained. Before-after workbooks include only tables present
in before (including before-only tables); after-only tables are excluded. Input is
never modified. With ordering off, after CSVs stay byte-for-byte unchanged.
Each export overwrites only the selected workbooks. Unselected workbooks from
earlier runs are retained; the compare output folder is never cleared.

AutoCompare là công cụ web chạy local dành cho kiểm thử CSV/UT trên Windows. Ứng dụng tái sử dụng các workflow Python hiện có để sao chép dữ liệu, tạo workbook so sánh, review FIXME, xử lý file và trao đổi dữ liệu với cơ sở dữ liệu.

## Khởi động

Yêu cầu Windows và Python 3.10–3.14. Python 3.15 hiện chưa phù hợp với các phiên bản `pyodbc`/`oracledb` trong `requirements.txt`.

```bat
run.bat
```

Lệnh trên ưu tiên môi trường `.runtime-venv` còn dùng được; nếu thiếu hoặc lỗi, nó chọn Python tương thích (ưu tiên bản mới hơn), tạo lại môi trường, cài dependencies, khởi động server tại `http://127.0.0.1:8765` và mở trình duyệt. Khi copy sang folder khác, không cần copy `.runtime-venv`; lần chạy đầu sẽ tạo lại. Máy mới vẫn cần có Python tương thích và mạng hoặc nguồn cài đặt dependency sẵn có.

Để dùng port khác:

```bat
run.bat 9000
```

Hoặc chạy trực tiếp:

```bat
.runtime-venv\Scripts\python.exe -m autocompare_tool --port 9000
```

Các tùy chọn hữu ích:

```bat
.runtime-venv\Scripts\python.exe -m autocompare_tool --host 127.0.0.1 --port 8765 --no-browser
```

Server mặc định chỉ bind vào `127.0.0.1`; không nên dùng `0.0.0.0` trên máy hoặc mạng không tin cậy vì ứng dụng có quyền thao tác file local và kết nối database.

Giao diện Tkinter cũ vẫn có thể mở tạm thời bằng:

```bat
.runtime-venv\Scripts\python.exe -m autocompare_tool --desktop
```

## Chức năng

- **So sánh UT**: chọn folder chứa các case `UT*`, chạy các workflow trong `autocompare_config.ini`, tạo Excel tại `Output\Compare`, xem trực tiếp workbook compare trên trình duyệt và review/apply ghi chú FIXME.
- **So sánh 2 folder CSV**: có thể export một workbook tổng hợp như cũ, hoặc quét CSV trực tiếp trong hai folder, chỉnh pair bằng kéo thả và export từng pair thành từng workbook riêng.
- **Compare Excel**: so sánh value từng cell giữa hai workbook OOXML. Sheet được ghép theo tên trước, sau đó theo thứ tự tab; mỗi cặp tạo bộ ba `<sheet>_Old`, `<sheet>_New`, `<sheet>_compare`. Sheet compare chỉ ghi các ô sai khác với nhãn `Old:` và `New:` in đậm; sheet không có cặp vẫn được đưa vào kết quả với phía còn lại để trống.
- **Compare PDF**: kiểm tra SHA-256 của file, text, form/annotation và ảnh render RGB 200 DPI của từng trang. Output gồm báo cáo PDF có ảnh Old/New/Diff tô đỏ và manifest JSON chứa hash, verdict, số pixel cùng tọa độ vùng khác biệt.
- **Compare Image**: paste bằng Ctrl+V / nút Paste, import hoặc kéo thả ảnh Old và New (PNG, JPEG, WebP, BMP; ảnh tĩnh 8-bit, tối đa 12 MB và 12 triệu pixel mỗi ảnh). So sánh chính xác RGBA, độ trong suốt, kích thước và thông tin màu sau khi áp dụng hướng EXIF; không tự resize hay bỏ qua pixel gần giống. Xem song song, kéo thanh Old/New hoặc tô đỏ vùng sai khác; zoom và chuyển từng vùng. Tải báo cáo HTML độc lập có ảnh + SHA-256, ảnh Diff PNG hoặc JSON. Ảnh được xử lý trên server local và không ghi đè file nguồn.
- **Tiện ích file**: đổi tên, xóa, di chuyển file/folder, đổi tên sheet Excel và tìm/xóa folder trống.
- **Format ảnh Excel**: resize và sắp xếp ảnh theo 6 vùng Evidence (hệ thống cũ/mới × Input/Steps/Output), đồng thời giữ nguyên ảnh, VBA và button.
- **SQL Studio**: format SQL và phân tích table/alias, điều kiện, CTE, subquery, SELECT expression theo cây cú pháp.
- **CSV ↔ Database**: test kết nối, quét CSV, import toàn bộ hoặc chỉ các table đã chọn, và export table cho SQL Server, MySQL, PostgreSQL và Oracle.
- **Đồng bộ 2 CSDL**: đồng bộ chênh lệch theo primary key, insert thêm hoặc truncate rồi đồng bộ lại.

Các thao tác xóa, import, export và đồng bộ luôn yêu cầu xác nhận rõ ràng trên giao diện web. DB import không tự truncate table.

Nhật ký tác vụ nằm ở bong bóng góc phải dưới. Log không tự xóa khi chạy tác vụ mới; mỗi tác vụ có thời gian bắt đầu/kết thúc, thời gian xử lý và dòng phân cách `-----------------------------------------`.

## Format workbook Excel

Chọn folder chứa workbook `.xlsx`, `.xlsm`, `.xlsb` hoặc `.xls`. Công cụ áp dụng font và cỡ chữ cho toàn bộ sheet, đưa mỗi sheet về ô `A1`, kéo thanh cuộn ngang/dọc về đầu và chọn sheet đầu tiên trước khi lưu. Ảnh và shape hiện có không bị di chuyển hoặc thay đổi kích thước.

Ô **Giữ nguyên size cho các row** nhận nhiều quy tắc, mỗi quy tắc một dòng:

- `Header`: giữ nguyên cỡ chữ của mọi row có cell bằng chính xác `Header` (không phân biệt hoa/thường).
- `(Header, A1)`: chỉ giữ nguyên cỡ chữ của row chứa `A1` khi giá trị tại `A1` bằng `Header`.

Font name vẫn được áp dụng cho các row này; phần loại trừ chỉ áp dụng cho font size. Có thể đặt tên và lưu font, size cùng toàn bộ quy tắc thành preset JSON local, sau đó chọn lại từ combobox ở những lần chạy sau.

Mặc định workbook được copy theo đúng cấu trúc folder vào thư mục con `Formatted` rồi mới xử lý. Chỉ chọn **Ghi đè file gốc** khi đã có backup. Cả hai chế độ đều yêu cầu xác nhận vì kết quả cũ cùng tên có thể bị ghi đè.

Workbook `.xlsx` đơn giản được xử lý bằng `openpyxl`. Với file có ảnh, VBA, button hoặc định dạng Excel cũ, cần Microsoft Excel Desktop trên Windows để giữ nguyên các thành phần đó. Các preset cá nhân được lưu trong `excel_format_presets.json` và file này không được commit vào Git.

## SQL Studio

Tab **SQL Studio** có hai thao tác độc lập và không thực thi SQL trên database:

- **Format SQL**: chuẩn hóa keyword, xuống dòng và thụt lề; hỗ trợ nhiều statement trong cùng input, phân tách bằng dấu `;`.
- **Load sheet & format**: đọc SQL từ workbook `.xlsx/.xlsm/.xltx/.xltm`. Sheet cần có số thứ tự ở cột A; nội dung SQL chỉ lấy từ cột B và gom từ số thứ tự hiện tại đến số thứ tự tiếp theo. Nếu cột C cùng row có note, note đó được chèn inline dạng `-- ...` vào phần SQL được format từ chính ô cột B cùng row. Output được đánh dấu theo dạng `-- SQL No.1`.
- **Phân tích toàn bộ**: parse SQL thành AST rồi liệt kê từng table/reference cùng alias, vai trò `FROM`/`JOIN`/DML target và scope. Kết quả còn gồm điều kiện `WHERE`, `JOIN ON/USING`, `HAVING`, `QUALIFY`, `MERGE ON`, `START WITH`, `CONNECT BY`, `CASE/IF`, CTE, subquery, SELECT expression, `GROUP BY`, `ORDER BY`, `LIMIT/OFFSET`.

Có thể chọn dialect SQL Server, MySQL, PostgreSQL, Oracle, SQLite, BigQuery, Snowflake, Spark, Databricks hoặc DuckDB. Chế độ tự động dùng SQL phổ thông; với cú pháp riêng của hệ quản trị nên chọn đúng dialect để parser không hiểu nhầm. Ứng dụng không đặt giới hạn riêng về số dòng/độ dài SQL; giới hạn thực tế phụ thuộc bộ nhớ khả dụng của máy và trình duyệt.

## Chọn đường dẫn

Trình duyệt web không cho phép website đọc đường dẫn tuyệt đối từ file picker thông thường. Vì AutoCompare xử lý trực tiếp dữ liệu local, các nút **Chọn folder/file** mở trình duyệt filesystem do server local cung cấp. Người dùng cũng có thể nhập hoặc dán đường dẫn Windows trực tiếp.

## Cấu hình

`autocompare_config.ini` chứa:

- `[folders]`: tên `Input`, `Output`, `Compare` và các folder before/after.
- `[workbooks]`: tên các workbook được tạo.
- `[excel_headers]`: header/text trong file compare Excel, gồm `FIXME`.
- `[excel_compare_style]`: mã màu font/fill dùng khi tạo file compare Excel; `diff_font_color` dùng cho cell sai khác, `a1_font_color` dùng riêng cho ô A1.
- `[compare_workflows]`: trạng thái mặc định của các luồng so sánh.
- `[excel_image_format]`: cấu hình cũ được giữ để tương thích; trang Format Excel không dùng các tùy chọn căn ảnh.

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

Chỉ copy CSV từ `Input` vào hai folder before khi bật checkbox copy. Compare không tự xóa record, CSV hay folder before. Checkbox sắp xếp ghi thứ tự theo key vào CSV và giữ nguyên số lượng record. Workbook của workflow không được chọn được giữ nguyên.

Record được ghép theo thứ tự từ trên xuống dưới của hai CSV, kể cả khi giá trị cột đầu tiên khác nhau. Nếu một phía ít record hơn, vị trí còn thiếu được để trống. Các cột metadata `ValidationErrors`, `HasErrors`, `TargetProperties` và `DataState` được bỏ qua khi compare.

## FIXME review

Sau compare, giao diện hiển thị case UT, workbook, sheet thật trong workbook, CSV nguồn, column, hai giá trị, số record và combobox chọn ghi chú. Combobox hiển thị phần `Ý nghĩa` để dễ đọc, nhưng khi áp dụng sẽ ghi nội dung `Ghi chú` vào cell FIXME. Mỗi header có filter riêng để tìm nhanh các nhóm FIXME có điểm chung.

Người dùng có thể tick dòng hoặc chọn toàn bộ dòng đang lọc, gán/xóa note hàng loạt rồi bấm **Áp dụng ghi chú** một lần để thay cell `FIXME` tương ứng trong workbook. Có thể bấm **Check FIXME** để kiểm tra file compare hiện tại còn cell nào giữ nguyên marker `FIXME` hay không. Nếu nhiều mismatch cùng trỏ đến một cell FIXME, các ghi chú duy nhất được nối theo thứ tự bằng xuống dòng. Danh sách note được lưu trong `fixme_notes.json`.

## Database CSV

Quy trình cơ bản:

1. Chọn loại CSDL và nhập thông tin kết nối.
2. Bấm **Test Database Connection**.
3. Chọn **Import CSV** để import toàn bộ CSV cấp trực tiếp, hoặc chọn **Quét file CSV**, chọn nhiều table trong danh sách rồi chọn **Import table đã chọn**.
4. Dùng vùng **Export CSV** nếu cần xuất table từ database ra folder CSV.

Mỗi CSV được map với table theo tên file không gồm `.csv`. Danh sách table import selected được tạo bằng cách quét các file `.csv` cấp trực tiếp trong folder import; nested folder không nằm trong phạm vi import. CSV không có table tương ứng được bỏ qua. CSV header không tồn tại trong table là lỗi. Import bỏ qua computed/generated/rowversion; identity chỉ được giữ khi người dùng bật tùy chọn và adapter hỗ trợ.

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

Chế độ chênh lệch yêu cầu table nguồn và đích có cùng primary key, hỗ trợ primary key ghép. Nếu key là identity phải bật **Giữ identity**. Dữ liệu được đọc bằng `fetchmany()` và thay đổi được ghi theo batch tối đa 500 record mỗi lượt (giá trị cũ lớn hơn được chia nhỏ), không nạp toàn bộ table vào RAM. Chế độ này không cho dùng giới hạn record vì việc dừng giữa table có thể khiến kết quả không còn phản ánh chính xác dữ liệu nguồn.

Đồng bộ trên web chạy trong tiến trình riêng (`database_sync_worker.py`), tách driver khỏi server và giao diện. **Hủy tác vụ** ngắt tiến trình cùng các kết nối của tác vụ, không chờ kết nối/SELECT/batch insert trả về. Mỗi bước có watchdog mặc định 120 giây, chỉnh từ 10–3600 giây trong Tùy chọn kỹ thuật; quá hạn sẽ ngắt và báo bước bị kẹt. LOG vẫn cập nhật trạng thái chờ mỗi 10 giây. Không tự retry thao tác ghi sau lỗi hoặc hủy.

Đây là ngắt ở phía ứng dụng, **không phải cam kết rollback tức thì trên server**. CSDL có thể cần thời gian phát hiện mất kết nối, rollback và giải phóng khóa. Table đã commit được giữ nguyên; ngắt đúng lúc commit thì kết quả có thể chưa xác định, cần kiểm tra đích trước khi chạy lại. TRUNCATE/DDL tự commit (ví dụ MySQL/Oracle), table không hỗ trợ transaction và tác động ngoài transaction của trigger không được đảm bảo hoàn tác. Không tự KILL các session khác hoặc khởi động lại dịch vụ CSDL. Cơ chế ngắt tiến trình này áp dụng cho đồng bộ web; các tác vụ khác vẫn hủy tại checkpoint.

Tối ưu đồng bộ: tra primary key theo nhóm tối đa 100 key/900 tham số thay cho từng record; dùng parameter-array batch trên Microsoft ODBC Driver 17/18; ghi backup theo điều kiện ra file trước mỗi lượt thay đổi. Với đồng bộ chênh lệch SQL Server, dữ liệu đối chiếu đích được đọc theo batch vào file tạm tự dọn rồi giải phóng transaction đọc trước khi ghi, tránh luồng đọc chặn luồng ghi của cùng tác vụ. Cần đủ dung lượng ổ tạm cho dữ liệu đích. Vẫn giữ transaction ghi theo table, không commit từng batch để đổi lấy tốc độ.

Không bật **Xóa record chỉ có ở đích** nếu muốn giữ dữ liệu riêng của database đích. Khi bật, sau khi chạy thành công database đích sẽ giống nguồn đối với các column có thể đồng bộ. Nên tránh ghi đồng thời vào hai table trong lúc đồng bộ; datatype và collation của primary key cần tương thích để thứ tự streaming nhất quán.

Đồng bộ chênh lệch vẫn phải đọc hai table để tìm khác biệt, nhưng chỉ ghi các record thực sự thay đổi. Muốn chỉ đọc phần thay đổi cho những lần chạy sau cần thêm CDC/Change Tracking hoặc column cập nhật đáng tin cậy ở cấp database.

Khi export, bỏ trống danh sách table để xuất toàn bộ table trong schema. Có thể phân tách danh sách table bằng dấu phẩy, chấm phẩy hoặc xuống dòng.

Ví dụ phân biệt empty string và `NULL`:

```csv
id,amount,empty_value,null_value,text
1,3456.0000,"",,"Alice"
```

Trong dòng trên, `empty_value` là chuỗi rỗng và `null_value` là `NULL`.

## Sao chép file UT (legacy)

Chức năng này đã được gỡ khỏi menu và API web. Các script legacy
`copy_ut_files.py` vẫn được giữ để tương thích công cụ cũ, không xóa dữ liệu/log:

- Sao chép từ `UT*/input` của nguồn sang cấu trúc input ở đích.
- Sao chép từ `UT*/output` của nguồn sang cấu trúc output hệ thống hiện tại ở đích.
- Nếu đích đã có CSV, công cụ so sánh value/raw format và ghi log trước khi ghi đè.
- Log được tạo trong `copy_logs` cạnh `copy_ut_files.py`.

## SQL Workspace trong Database

Trang Database dùng một hub kết nối nhỏ ở phần tiêu đề; bấm **Kết nối CSDL** để mở popup cấu hình dùng chung cho cả ba tab:

- **Database 1** dùng cho CSV import/export, SQL Workspace và làm nguồn đồng bộ.
- **Database 2** chỉ dùng làm database đích khi đồng bộ.

Lịch sử kết nối được lưu trong file local `database_connection_history.json` ở root project, bao gồm password để có thể tự động kết nối lại sau khi tắt/mở server. File này đã được ignore khỏi git; password không được trả về browser trong bootstrap, log hoặc kết quả job.

Tab **SQL Workspace** kế thừa formatter/analyzer cũ, đồng thời có thể chạy SQL trực tiếp trên Database 1. `Format SQL`, `Phân tích toàn bộ` và `Load sheet & format` dùng chung một editor; SQL đã format sẽ ghi đè trực tiếp vào vùng **SQL đầu vào**. Các chức năng format/phân tích vẫn chạy khi chưa kết nối DB. `Chạy hiện tại` chạy vùng đang bôi đen hoặc statement tại caret; `Chạy toàn bộ` chạy toàn bộ statement theo thứ tự. Mặc định backend chỉ cho statement đọc. DDL/DML cần bật **Ghi DB**, token tạm thời gắn với fingerprint của Database 1 và tự hết hạn theo `[database_workspace].write_mode_timeout_minutes`; đổi connection sẽ hủy verified state, tắt chế độ ghi và đánh dấu kết quả SQL cũ là stale.

Kết quả query được đọc bằng `fetchmany()` và spool tạm theo workspace để phân trang. Source Data tự truy vết primary key qua CTE/subquery trong FROM, kể cả projection đổi tên/tính toán và CTE dùng lại nhiều lần; điều kiện lọc và JOIN ngoài cùng vẫn quyết định record được lấy. User không cần tự đẩy predicate.

Source Data không tự chuyển sang lấy toàn bảng khi truy vấn phức tạp. Hệ thống truy ngược từng cấp CTE/derived table, subquery tương quan (EXISTS/IN/scalar, kể cả IN nhiều cột), CROSS/OUTER APPLY và LATERAL về primary key, kể cả key ghép. GROUP BY/HAVING, ROLLUP/CUBE/GROUPING SETS, DISTINCT/DISTINCT ON, UNION/INTERSECT/EXCEPT, PIVOT/UNPIVOT và TOP/LIMIT được xử lý theo kết quả trung gian, không chỉ theo vị trí record. Phép gom nhóm và DISTINCT giữ nguyên số dòng trung gian; chỉ thành viên của nhóm/kết quả được chọn mới được lấy. SEMI/ANTI/NATURAL JOIN được chuẩn hóa theo điều kiện join và metadata.

CTE đệ quy có luồng truy vết riêng để giữ các record trên đường dẫn đến kết quả được chọn, không lấy mọi nhánh cây. SQL Server tự nhận diện CTE đệ quy dù không có từ khóa RECURSIVE; OPTION(MAXRECURSION ...) được giữ ở cấp statement. Window được xử lý theo partition, thứ tự và frame ROWS/RANGE. LAG/LEAD giữ cả các dòng trung gian cần cho offset, gồm offset tính toán và IGNORE NULLS. ROW_NUMBER/RANK/DENSE_RANK cần phần dữ liệu đứng trước record được chọn; các hàm phân phối cần partition tương ứng. CSV export và Copy SQL dùng cùng tập record với Source Data.

Thiếu primary key/metadata, thiếu định nghĩa bên trong view/table-valued function hoặc lỗi truy vết sẽ hiển thị lý do tại source đó, không đọc toàn bảng thay thế. Các record phụ thuộc thứ tự/gom nhóm có thể nhiều hơn số dòng kết quả, và một phép tổng hợp toàn bảng thực sự có thể cần toàn bảng. Việc tái hiện còn phụ thuộc dữ liệu ổn định, cùng schema/môi trường SQL, thứ tự xác định khi giá trị sắp xếp trùng, các nhánh phủ định dùng lại cùng bảng và hàm thời gian/ngẫu nhiên. Không cam kết mọi biến thể riêng của từng database đều đã được kiểm chứng.

Source grid hiển thị header hai tầng gồm index column, icon key cho primary key, datatype và màu usage: JOIN ưu tiên cao nhất, WHERE màu xanh lá, SELECT màu vàng. Join group được hợp nhất bắc cầu, ví dụ `A.x = B.y` và `A.x = C.z` sẽ tô cùng màu cho cả ba column. Hover vào column JOIN hiển thị các column cùng group.

Export source CSV ghi theo chuẩn DBeaver: `NULL` là ô trống không quote, empty string là `""`, string được quote, numeric không quote và CRLF. CSV xuất đúng Source Data, không thêm negative record có thể làm thay đổi kết quả khi nạp lại. Inline Update chỉ bật cho source exact của base table có đầy đủ primary key; view/CTE/subquery/table không PK là read-only. Update dùng parameter, kiểm tra hash toàn row trước khi ghi và rollback toàn bộ nhóm nếu có conflict.

`autocompare_config.ini` có `[database_workspace]` để chỉnh page size, timeout, batch export và giới hạn spool tạm.

## Test

```bat
.runtime-venv\Scripts\python.exe -m unittest discover -s tests
```

Bộ kiểm thử Source Data chạy SQL trên dữ liệu mẫu, trích xuất record theo key rồi nạp vào database rỗng để đối chiếu kết quả SQL gốc. SQLite được dùng cho các ca cơ bản; bộ mở rộng dùng DuckDB cho APPLY, CTE đệ quy, PIVOT, grouping sets và window. Cài thêm dependency kiểm thử để không bỏ qua các ca mở rộng:

```bat
.runtime-venv\Scripts\python.exe -m pip install -r requirements-test.txt
.runtime-venv\Scripts\python.exe -m unittest tests.test_sql_source_lineage tests.test_sql_advanced_lineage tests.test_sql_database_workspace tests.test_sql_tools
```

Các bài kiểm thử dùng database trong bộ nhớ, không ghi vào database đang kết nối của người dùng. Kiểm thử qua DuckDB không thay thế kiểm chứng cú pháp/thực thi trên SQL Server, PostgreSQL, MySQL và Oracle thực tế.

Nếu `.runtime-venv` trỏ tới bản Python đã bị gỡ hoặc tải thư viện lỗi, `run.bat` sẽ tự tạo lại môi trường bằng Python 3.10–3.14 đang có trên máy; không cần xóa thủ công.
