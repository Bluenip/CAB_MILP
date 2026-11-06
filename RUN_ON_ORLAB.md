# Tự chạy trên máy 100.71.200.54

Copy cả thư mục dự án, bao gồm `dataset/`, sang máy đích. Đứng trong thư mục đó và chạy đúng một dòng:

```bash
bash run_on_orlab.sh
```

Script không chứa đường dẫn Python cố định của máy nguồn. Nó tạo `.venv` nếu chưa có,
cài Gurobi 13.0.3 khi cần, kiểm tra khởi tạo license, rồi chạy tuần tự. Máy cần có
`python3` hỗ trợ `venv`/`pip` và `taskset`. Dùng license Gurobi đầy đủ cho benchmark;
license giới hạn kích thước có thể khởi tạo thành công nhưng không giải được bài lớn.
License không được đóng gói hoặc tự chuyển từ máy nguồn.

Nếu license nằm ngoài vị trí Gurobi mặc định:

```bash
GRB_LICENSE_FILE=/duong/dan/gurobi.lic bash run_on_orlab.sh
```

Có thể đặt file tại `.gurobi/gurobi.lic` trong dự án (không commit file này).
Không in nội dung license trong log.

## Cấu hình cố định

- Riêng các dataset trong manifest paper cũ: hiện có **157 lượt** (107 × 150s, 50 × 1800s).
- Mỗi cấu hình chạy hết nhóm 150s trước, rồi 1800s; trong nhóm chạy đồ thị ít đỉnh trước.
- Chạy lần lượt cấu hình **4 threads rồi 8 threads**, không có hai dataset chạy đồng thời.
- CPU `0–7`, đã kiểm tra trên máy đích là 4 P-cores / 8 luồng logic.
- Seed 0; Gurobi `SoftMemLimit=30 GB`; giữ mô hình `max K`, một optimize()/lượt.
- Không chuyển cận/heuristic riêng hypercube từ code cũ.
- Còn **28 mục paper thiếu file**, được ghi rõ trong manifest; không tạo dữ liệu thay thế.
- Tổng ngân sách hai cấu hình là **58h55m**, chưa tính overhead; các lượt chứng nhận tối ưu có thể kết thúc sớm.

Đây là cấu hình tài nguyên tương ứng gần paper trên máy hiện có. SAT-CAB dùng
4/8 tiến trình giải các ngưỡng k khác nhau, còn Gurobi dùng 4/8 threads trong một
mô hình tối ưu trực tiếp. CPU/hệ điều hành khác máy GCP của paper. SoftMemLimit
chỉ theo dõi bộ nhớ Gurobi, không phải hard limit cho toàn bộ Python/OS.

## Theo dõi và tiếp tục

Kết quả ở `paper_runs/paper_comparison_<timestamp>/`:

- `threads_4/` và `threads_8/`: CSV, nghiệm JSON, log từng lượt.
- `best_results.csv`: tự ghép sau khi hoàn thành cả hai cấu hình.
- `best_solutions/`: nghiệm từ lượt được chọn; không trộn 150s và 1800s.
- `protocol.json`, `machine.json`: cấu hình và máy chạy thực tế.

`best_results.csv` chỉ có cột SAT paper cho hypercube Table B4 đã đối chiếu;
các họ khác để trống, không suy đoán số liệu SAT.

Chạy tiếp một batch bị ngắt, dùng đúng thư mục output cũ:

```bash
OUTPUT=/duong/dan/paper_runs/paper_comparison_YYYYMMDD_HHMMSS bash run_on_orlab.sh
```

Nếu muốn đóng SSH mà vẫn chạy, tự khởi chạy bằng:

```bash
nohup bash run_on_orlab.sh > paper_console.log 2>&1 &
```

Chỉ xem danh sách, không cài đặt, không kiểm tra license, không giải bài nào:

```bash
bash run_on_orlab.sh --dry-run
```
