# Python AutoCompare Tool

Tool nay copy CSV tu `Input` vao cac folder `before...`, sau do compare cac cap `before/after` va tao Excel trong `Output\Compare`.

## Cach chay

1. Cai Python 3.10 tro len va bat tuy chon `Add Python to PATH`.
2. Double-click `run.bat`.
3. Chon folder cha chua cac folder `UT*`, vi du `D:\project\autocompare`.
4. Bam `Run Compare`.

`run.bat` se tu tao `.venv`, cai `openpyxl`, va mo GUI.

## Copy UT Files

GUI co them khu vuc `Copy UT Files` gom 2 path:

- `Source Path1`: folder nguon chua cac folder `UT*`.
- `Target Path2`: folder dich de tao/mirror cac folder `UT*`.

Bam `Run Copy UT Files` de chay logic trong `copy_ut_files.py`.

Logic copy hien co:

- Copy tu `UT*/input` cua source sang `UT*/入力` cua target.
- Copy tu `UT*/output` cua source sang `UT*/出力/現在のシステム以降` cua target.
- Neu target da co file CSV, tool compare value/raw format va ghi chi tiet vao log truoc khi overwrite.
- Log duoc tao trong folder `copy_logs` canh `copy_ut_files.py`.

## Chuc nang 2: SQL Server CSV normalize

GUI co them khu vuc `SQL Server`:

- Driver: mac dinh `ODBC Driver 18 for SQL Server`.
- Server, Database.
- Windows Authentication hoac User/Password.
- Schema: mac dinh `dbo`.

May chay tool can co Microsoft ODBC Driver for SQL Server, vi `pyodbc` se dung driver nay de connect.

Quy trinh:

1. Nhap thong tin DB.
2. Bam `Test DB Login`.
3. Sau khi login thanh cong, bam `Normalize CSV`.

Tool se duyet tat ca CSV trong folder dang chon, bao gom ca CSV trong folder con ben duoi. Moi CSV duoc map voi table that trong DB theo ten file khong gom `.csv`.

```text
customers.csv -> <schema>.customers
orders.csv    -> <schema>.orders
```

Neu khong tim thay table tuong ung trong DB, CSV do se duoc skip va tool tiep tuc xu ly cac file con lai.

Tool chi doc metadata column order va datatype tu SQL Server, sau do reorder/normalize CSV tai cho theo thu tu column trong DB.

Tool khong `TRUNCATE`, khong `INSERT`, va khong overwrite value qua datatype/constraint/trigger cua SQL Server.

Format export:

- Delimiter: `,`
- Header: top, label, as-is
- Quote character: `"`
- Escape quote: double quote
- Quote always strings
- NULL string: blank
- Empty string: `""`
- Column `datetime`, `datetime2`, `smalldatetime`: output `yyyy-MM-dd HH:mm:ss.fff`
- Column `decimal`, `numeric`, `money`, `smallmoney`: output 4 so sau dau cham, vi du `3456.0` -> `3456.0000`

Vi du:

```csv
id,empty_value,null_value
"1","",
```

Trong dong data tren, `empty_value` la empty string, `null_value` la NULL.

Luu y: CSV column phai ton tai trong table DB tuong ung. Neu CSV co column khong co trong DB, tool se bao loi va khong overwrite file do.

## Cau truc folder du kien

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

## Ket qua

Moi `UT*` tao 2 file:

- `Output\Compare\Compare新_Before_After.xlsx`
- `Output\Compare\Compare現行_Before_After.xlsx`

Danh sach sheet lay theo cac file CSV trong folder `after...`. Ten sheet la ten file khong gom `.csv`. Record duoc map bang cot dau tien cua moi CSV.

## Quy tac xu ly

- Moi lan run se xoa CSV cu trong 2 folder `before...`, roi copy lai toan bo CSV tu `Input`.
- File CSV chi co trong `before...` se bi xoa khoi folder `before...` sau buoc copy, vi folder `after...` la nguon uu tien.
- Record chi co trong `after` se de trong cot before.
- Record chi co trong `before` se de trong cot after.
- Neu key trung nhau, tool dung key + thu tu xuat hien de map deterministic.
- Cac cot metadata giong source mau se bi bo qua: `ValidationErrors`, `HasErrors`, `TargetProperties`, `DataState`.

## Chay test

Sau khi dependency da duoc cai:

```bat
.venv\Scripts\python.exe -m unittest discover -s tests
```
