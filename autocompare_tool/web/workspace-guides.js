"use strict";

// Help is local, read-only and independent of workflow/API state.
function prepareWorkspaceGuides() {
  const guides = [
    ["#workbench-compare-form", [
      ["So sánh tự động theo cấu trúc folder", "Chọn thư mục gốc là một case hoặc thư mục cha chứa nhiều case. Mọi case khớp mẫu tên được so sánh cùng lúc; bảng “Case sẽ so sánh” cho biết case nào đủ folder cho các luồng đã chọn.", "Nhấn Chạy so sánh. Workbook được lưu trong thư mục Compare của từng case và hiện ở tab Kết quả khi hoàn tất."],
      ["Xem và sửa cấu trúc folder", "Cây bên phải cho biết mỗi case cần những folder nào: “cần có” do bạn chuẩn bị, “tự tạo” do tool ghi ra, “tùy chọn” chỉ cần khi bật Copy. Mục mờ là folder không dùng bởi các luồng đang chọn.", "Nhấn Chỉnh sửa để đổi tên folder, mẫu tên case hoặc tên workbook (lưu vào autocompare_config.ini, áp dụng cho lần so sánh sau). Dữ liệu hiện có không bị đổi tên hay di chuyển."],
      ["Copy input và sắp xếp theo key", "Chỉ bật Copy input khi muốn ghi đè các CSV tương ứng trong before. Các file khác không bị dọn xóa.", "Sắp xếp theo key sẽ thay đổi thứ tự record của CSV được xử lý. Cấu hình key ở Database → Trích xuất key; để tắt nếu muốn giữ thứ tự file."],
    ]],
    ["#compare-preview-card", [
      ["Xem workbook và điều hướng", "Chọn Case → File compare → Sheet. Bốn nút mũi tên đưa vùng xem về đầu/cuối theo mỗi chiều. Tải lại view dùng để đọc lại kết quả.", "Nút thu/phóng dùng toàn màn hình; Escape để thu nhỏ. Click một ô để chọn/copy giá trị."],
      ["Filter sai khác và số record", "Bật Filter sai khác để chỉ xem các dòng có ô ghi note sai khác.", "Khi hai phía lệch số record, bật Bỏ qua lệch số record để ẩn các cặp cột không có record tương ứng; bỏ tick để xem lại toàn bộ."],
      ["Check FIXME và gán note", "Check FIXME quét toàn bộ file/sheet của kết quả compare hiện tại. Chọn vị trí trong kết quả để mở sheet tương ứng.", "Tick dòng cần ghi chú, chọn note rồi Gán note cho dòng đã tick; cũng có thể nhập/chọn note ngay tại dòng.", "Quản lý Note dùng để quản lý danh sách mẫu. Áp dụng tất cả Note ghi các note đã gán trên toàn bộ kết quả, không chỉ sheet đang xem."],
    ]],
    ["#folder-compare-form", [
      ["Chọn hai thư mục và kiểu xuất", "Chọn thư mục Old (trái) và New (phải); nút mũi tên đổi chỗ hai bên. Không cần cấu trúc case: CSV cùng tên được ghép với nhau.", "1 file tổng hợp: một workbook, mỗi CSV một sheet. Mỗi cặp một file: xuất workbook riêng cho từng cặp vào một thư mục. Gộp cặp vào 1 file: mỗi cặp một sheet, tên theo CSV bên phải."],
      ["Chỉnh cặp CSV", "Ở hai kiểu xuất theo cặp, danh sách cặp được quét tự động khi đã có cả hai thư mục; bấm Quét lại sau khi thay đổi file.", "Kéo thả ô CSV trong cùng một cột để ghép lại cặp (hữu ích khi tên file có dấu thời gian khác nhau), rồi bấm So sánh. Kết quả hiện ở tab Kết quả."],
    ]],
    ["#excel-compare-form", [
      ["Cách so sánh", "Chọn file cũ (Old) và file mới (New) rồi bấm So sánh. Sheet cùng tên được ghép với nhau; sheet khác tên được ghép theo thứ tự tab (có thể tắt trong Tùy chọn nâng cao).", "Chỉ so sánh nội dung ô: giá trị và công thức (kèm kết quả đã lưu trong file nếu cả hai file có). Định dạng, hình ảnh và biểu đồ không được so sánh."],
      ["Đọc kết quả", "Mỗi sheet cho biết số ô khác nhau; bấm vào sheet để xem trước các ô đầu tiên. Sheet chỉ có ở một phía được đánh dấu riêng.", "File kết quả có bộ ba sheet _Old, _New, _compare. Ô giống nhau để trống, ô khác ghi Old:… # New:…. Chèn hoặc xóa dòng làm các dòng bên dưới bị lệch và cùng được tính là khác."],
    ]],
    ["#pdf-compare-form", [
      ["Cách so sánh", "Chọn file cũ (Old) và file mới (New) rồi bấm So sánh. Hệ thống đối chiếu từng trang: chữ, form/chú thích và hình ảnh render ở 200 DPI.", "Chỉ kết luận giống nhau khi số trang, chữ, form/chú thích và từng pixel đều trùng khớp. Giống nội dung không đồng nghĩa hai file giống từng byte; kết quả cho biết cả hai."],
      ["Đọc kết quả", "Danh sách chỉ hiện các trang khác nhau; bấm vào trang để xem khác biệt về chữ. Bật “Hiện cả trang giống nhau” nếu cần xem đủ.", "Mở báo cáo PDF để xem ảnh Old / New / vùng khác biệt của từng trang. File JSON cạnh báo cáo lưu bằng chứng (hash, số pixel khác, tọa độ vùng)."],
    ]],
    ["#page-image-compare", [
      ["Paste / Import / đổi ảnh", "Nhấn Ctrl+V để dán ảnh: ảnh đầu vào ô Old, ảnh thứ hai vào ô New. Cũng có thể kéo thả hoặc Import ảnh vào đúng ô. Xóa để chọn lại; Đổi Old ↔ New để đảo hai ảnh.", "Hỗ trợ PNG/JPEG/WebP/BMP tĩnh, tối đa 12 MB và 12 triệu pixel mỗi ảnh. Kết quả tự hiện khi đã có đủ hai ảnh; thay ảnh sẽ so sánh lại."],
      ["Xem sai khác và lưu báo cáo", "Chọn Vùng sai khác, Song song hoặc Kéo Old/New. Dùng Zoom và mũi tên để xem từng vùng; màu đỏ chỉ pixel khác.", "Ảnh khác kích thước được căn góc trái trên, không tự co giãn; phần thiếu cũng tính là sai khác. Xem thông tin kiểm chứng rồi tải HTML, ảnh Diff hoặc JSON."],
    ]],
    ["#rename-exact-form", [["Đổi tên chính xác", "Chọn folder gốc dùng chung, nhập tên cũ và tên mới; chọn File/Folder cần áp dụng.", "Chỉ tên khớp hoàn toàn được đổi. Kiểm tra phạm vi và xác nhận trước khi chạy; xem LOG để biết các mục đã xử lý."]]],
    ["#rename-contains-form", [["Thay text trong tên", "Nhập đoạn cần tìm và đoạn thay thế; chọn áp dụng cho File, Folder hoặc cả hai.", "Thao tác đổi nhiều tên trong cây thư mục. Kiểm tra kỹ từ khóa và sao lưu trước khi xác nhận."]]],
    ["#delete-contains-form", [["Xóa theo tên", "Chọn đúng folder gốc và từ khóa, rồi chọn File/Folder cần xóa.", "Đọc kỹ xác nhận: các mục khớp có thể bị xóa vĩnh viễn. Hãy sao lưu trước; không dùng từ khóa quá rộng."]]],
    ["#rename-sheets-form", [["Đổi tên sheet", "Chọn workbook, nhập đoạn trong tên sheet cần tìm và đoạn thay thế.", "Xác nhận thao tác và kiểm tra kết quả trong LOG. Nên tạo bản sao workbook trước khi thay đổi."]]],
    ["#move-files-form", [["Di chuyển file", "Nhập đoạn tên file cần tìm và tên folder đích.", "File phù hợp được chuyển vào folder đích nằm cạnh file đó. Kiểm tra folder gốc dùng chung và xác nhận trước khi chạy."]]],
    ['[data-tab-panel="file:empty"] > .tool-card', [["Kiểm tra / xóa folder trống", "Chọn folder gốc rồi Kiểm tra folder trống để xem phạm vi trong LOG.", "Chỉ nhấn Xóa folder trống sau khi đã kiểm tra và đồng ý với xác nhận."]]],
    ["#excel-format-form", [
      ["Nguồn và định dạng chữ", "Chọn folder Excel và bật Quét folder con nếu cần. Tick riêng Đổi font chữ / Đổi cỡ chữ rồi nhập giá trị; mục không tick được giữ nguyên.", "Ảnh và nội dung không bị format lại. File có ảnh, VBA hoặc định dạng phức tạp cần Microsoft Excel Desktop theo thông báo của ứng dụng."],
      ["Ngoại lệ và preset", "Mở Quy tắc ngoại lệ và preset. Bật giữ cỡ chữ cho row khớp quy tắc; nhập mỗi quy tắc một dòng theo ví dụ trong ô.", "Chọn preset để dùng lại; nhập tên và Lưu để lưu bộ quy tắc. Xóa chỉ dùng cho preset được chọn."],
      ["Vị trí mở và lưu kết quả", "Chọn độc lập: ô A1, cuộn về đầu sheet và mở sheet đầu tiên. Bỏ tick để giữ trạng thái tương ứng.", "Chọn Bản sao trong Formatted để giữ file gốc; Ghi đè file gốc luôn yêu cầu xác nhận. Nhấn Format workbook rồi xem LOG."],
    ]],
    ['[data-tab-panel="database:csv"]', [
      ["Kết nối và quét CSV", "Cấu hình Database 1 trong Kết nối CSDL, test kết nối rồi chọn folder CSV. Quét file CSV chỉ đọc các CSV trực tiếp trong folder.", "Chọn một table rồi Ctrl+A để chọn toàn bộ danh sách. Copy all table sao chép tất cả tên table vừa quét."],
      ["Import All / Import Single", "Chọn Insert thêm, Xóa record trùng key hoặc Truncate toàn table. Bật giữ identity nếu cần và database hỗ trợ.", "Import All xử lý mọi CSV đã quét; Import Single xử lý các table đang chọn. Import là ghi dữ liệu: kiểm tra database, chế độ và phạm vi trong xác nhận. Truncate xóa sạch dữ liệu của table tương ứng."],
      ["Export CSV", "Nhập tên table cần export, mỗi dòng một tên hoặc phân cách bằng dấu phẩy. Để trống để xuất toàn bộ table trong phạm vi kết nối/schema.", "Nhấn Export CSV; kết quả được ghi vào folder CSV đã chọn. Kiểm tra đường dẫn và LOG, tránh ghi đè bộ dữ liệu cần giữ."],
    ]],
    ["#sql-input-panel", [
      ["Input SQL, Copy và Format", "Dán SQL; chọn dialect phù hợp. Copy SQL sao chép nội dung, Format SQL định dạng lại editor.", "Chạy hiện tại dùng statement tại vị trí con trỏ; Chạy toàn bộ xử lý các statement trong input. Cần test Database 1 trước khi run; câu ghi dữ liệu yêu cầu xác nhận."],
      ["SQL từ Excel", "Mở SQL từ Excel, chọn file và tên sheet rồi Load sheet & format.", "Cột A là số thứ tự; SQL lấy từ B. Nội dung C trở thành comment ở đúng dòng B tương ứng, không chuyển sang câu khác."],
      ["Phân tích", "Nhấn Phân tích để phân tích SQL trong input; kết quả chuyển sang Analysis SQL.", "Phân tích cú pháp không thay thế kiểm tra thực thi trên database. Kiểm tra cảnh báo/dialect trước khi run."],
    ]],
    ["#sql-results-panel", [
      ["Results SQL và Source Data", "Sau khi run, xem kết quả từng statement, số thứ tự record và tên column theo database. [NULL] khác với chuỗi rỗng.", "Khi có Source Data, xem dữ liệu theo table; alias cùng table/key được gộp. Dùng Copy SQL của nguồn để lấy truy vấn tương ứng."],
      ["Export và cập nhật dữ liệu", "Chọn output folder rồi Export All hoặc export từng kết quả khi nút có sẵn.", "Nếu có thao tác cập nhật từ kết quả, kiểm tra key/record và xác nhận ghi trước khi thực hiện. Không suy ra toàn bộ table từ một kết quả đã bị giới hạn."],
    ]],
    ["#sql-analysis-panel", [
      ["Table và alias", "Xem nhóm table riêng cho từng câu SQL, sau đó phần tổng hợp toàn bộ. Nút copy trong mỗi nhóm chỉ copy table của câu đó.", "Sao chép toàn bộ table lấy danh sách table vật lý tổng hợp; CTE và subquery không phải table vật lý."],
      ["Điều kiện, CTE, subquery và biểu thức", "Xem WHERE/JOIN/HAVING cùng alias, column và scope để hiểu điều kiện của từng câu.", "Các mục CTE, Subquery, SELECT expressions và GROUP BY/ORDER BY/LIMIT giải thích cấu trúc; đây không phải kết quả dữ liệu chạy query."],
    ]],
    ['[data-tab-panel="database:sync"]', [
      ["Kết nối và chọn table", "Database 1 là nguồn, Database 2 là đích. Test cả hai trong Kết nối CSDL; hai phía cần cấu trúc column tương thích.", "Lọc rồi nhấn + để chọn table, hoặc nhập nhiều tên phân cách bằng dấu phẩy rồi Enter. Nhấn × để bỏ từng table hoặc Bỏ chọn tất cả. Bật Đồng bộ toàn bộ table nguồn sẽ bỏ qua danh sách chọn; kiểm tra phạm vi trước khi chạy."],
      ["Theo key / chênh lệch", "Cần primary key tương thích ở hai phía. Chỉ insert/update phần khác biệt.", "Xóa record chỉ có ở đích là tùy chọn phá hủy dữ liệu: bật chỉ khi muốn đích phản ánh đúng nguồn. Giữ identity khi key là identity và database hỗ trợ."],
      ["Insert thêm / Truncate", "Insert thêm không so sánh: có thể lỗi key trùng nếu đích đã có dữ liệu.", "Truncate & insert lại xóa sạch table đích trước khi nhập nguồn. Có thể giới hạn số record trong Tùy chọn kỹ thuật; hãy sao lưu và kiểm tra xác nhận."],
      ["Đồng bộ theo điều kiện", "Nhập WHERE áp dụng cho mỗi table; không nhập dấu ; hoặc comment. Các table phải có column dùng trong điều kiện.", "Bật xử lý trùng key để backup record đích trước khi xóa/insert hoặc upsert. Tắt tùy chọn có thể gây lỗi duplicate key."],
      ["Batch, thời gian chờ và hủy", "Mỗi lượt đọc/ghi tối đa 500 record. Giới hạn record chỉ dùng cho append/truncate; đồng bộ chính xác cần toàn bộ record. Giới hạn chờ mỗi bước mặc định 120 giây (có thể chọn 10–3600 giây).", "Hủy ngắt tiến trình đồng bộ ngay, kể cả đang chờ kết nối hoặc batch insert. CSDL có thể còn rollback; table đã commit được giữ nguyên. Nếu ngắt lúc commit, kiểm tra đích trước khi chạy lại. TRUNCATE/DDL trên CSDL tự commit không được đảm bảo hoàn tác."],
    ]],
    ['[data-tab-panel="database:primary-key"]', [["Trích xuất / xóa key compare", "Chọn Database 1 hoặc 2 đã kết nối, nhấn Trích xuất key để đọc primary key của các table và lưu cấu hình compare.", "Danh sách bên dưới cho biết table/key đã lưu. Xóa key xóa cấu hình key, không xóa primary key trong database."]]],
    ["#notes-dialog .modal-shell", [["Quản lý Note", "Chọn mẫu để sửa hoặc nhập Ghi chú và Ý nghĩa rồi Lưu ghi chú. Nút Xóa dùng để xóa mẫu đang chọn.", "Quản lý mẫu không tự ghi vào workbook. Quay lại Workbook, gán note cho dòng rồi Áp dụng tất cả Note."]]],
    [".activity-body", [["Nhật ký, xóa log và hủy tác vụ", "Mở LOG trong menu để xem tiến độ, lỗi và đường dẫn kết quả. Nhấn × hoặc header để đóng; Clear log chỉ xóa nội dung nhật ký đang hiển thị, không xóa file kết quả.", "Khi có Hủy tác vụ, nhấn để yêu cầu dừng và đợi thông báo kết thúc. Việc đóng khung LOG không dừng tác vụ đang chạy."]]],
    ["#path-dialog .modal-shell", [["Chọn đường dẫn", "Đi đến thư mục cần dùng trong hộp chọn đường dẫn; chỉ các file đúng loại được hiển thị khi chọn file.", "Kiểm tra đường dẫn đã chọn trước khi xác nhận. Hủy hoặc × để quay lại mà không chạy thao tác trên file."]]],
  ];
  for (const [selector, topics] of guides) {
    const target = document.querySelector(selector);
    if (!target || target.querySelector(":scope > .feature-guide")) continue;
    const guide = document.createElement("details");
    guide.className = "feature-guide";
    const summary = document.createElement("summary");
    summary.textContent = `Hướng dẫn sử dụng · ${topics.length} mục`;
    guide.append(summary);
    const content = document.createElement("div");
    content.className = "guide-topics";
    for (const [title, ...steps] of topics) {
      const section = document.createElement("section");
      const heading = document.createElement("h4");
      heading.textContent = title;
      const list = document.createElement("ol");
      steps.forEach(text => { const li = document.createElement("li"); li.textContent = text; list.append(li); });
      section.append(heading, list);
      content.append(section);
    }
    guide.append(content);
    target.append(guide);
    guide.addEventListener("toggle", () => window.scheduleSqlEditorViewportFit?.());
  }
}
