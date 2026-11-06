# Cyclic Antibandwidth — Gurobi MILP trực tiếp

Triển khai mô hình `max K` từ PDF ngày 30/10/2026, một lần gọi `optimize()`
cho mỗi lượt giải. Không sửa các thư mục code cũ bên ngoài dự án này.

## Chạy trên máy đích

Copy cả thư mục, gồm `dataset/`, sang máy đích rồi chạy:

```bash
bash run_on_orlab.sh
```

Chỉ xem danh sách, không cài đặt và không giải mô hình:

```bash
bash run_on_orlab.sh --dry-run
```

Hướng dẫn license, tiếp tục khi bị ngắt và chạy khi đóng SSH: [RUN_ON_ORLAB.md](RUN_ON_ORLAB.md).

## Phân thời gian đúng theo paper

| Thời gian | Bảng paper | Lượt có sẵn |
| --- | --- | ---: |
| 150s | 5, B3–B7 | 107 |
| 1800s | 6: 10 Harwell–Boeing; 7: 40 random graphs | 50 |

`paper_instances.json` là manifest đối chiếu paper. Có 28 mục thiếu file,
được báo riêng; không sinh dữ liệu thay thế hoặc thêm file ngoài manifest.
Mười dataset xuất hiện ở cả hai thời hạn được giữ thành hai lượt riêng.

Chạy tuần tự cấu hình 4 threads rồi 8 threads. Trong mỗi cấu hình chạy hết nhóm
150s trước rồi đến 1800s; trong nhóm chạy đồ thị ít đỉnh trước. CPU `0–7` trên
máy orlab đã kiểm tra là 4 P-cores/8 luồng logic. Seed 0 và Gurobi
`SoftMemLimit=30 GB`. Kết quả hai cấu hình được ghép, chọn CAB tốt nhất.

SAT-CAB dùng 4/8 tiến trình giải các ngưỡng khác nhau; ở đây dùng 4/8 Gurobi
threads cho mô hình tối ưu trực tiếp. Đây là cấu hình tài nguyên tương ứng,
không phải cùng kiến trúc solver hoặc cùng CPU/hệ điều hành của paper.

## Các file cần giữ

- `run_on_orlab.sh`: script bash duy nhất; chuẩn bị môi trường, kiểm tra cấu hình, chạy hai cấu hình và ghép kết quả.
- `run_benchmarks.py`: đọc manifest, xếp lịch, lưu kết quả và resume.
- `cab_milp.py`: mô hình và kiểm tra nghiệm.
- `collect_paper_best.py`: ghép hai cấu hình, kiểm tra lại nhãn.
- `paper_instances.json`, `requirements.txt`, `dataset/`: danh sách và đầu vào.
- `test_cab_milp.py`: bộ kiểm tra đối chiếu vét cạn trên đồ thị nhỏ.

Thư mục kết quả `paper_runs/` chỉ được tạo khi bạn tự chạy.

## Mô hình

Assignment nhị phân thưa `x[v,l]`, vị trí liên tục `p[v]`, biến hướng cạnh nhị phân
`b[u,v]`, biến nguyên K. Mỗi cạnh có hai hàng tuyến tính:

```
K <= p[u] - p[v] + n*b[u,v] <= n-K
maximize K
```

Có neo, phản xạ, sắp lá cùng cha, miền hàng xóm neo theo cận dưới L và MIP start
đầy đủ. L được đo từ nhãn thực tế; cận trên dùng n/2, cận bậc và clique đã xác thực
nếu có đầu vào JSON. Không dùng chú thích đáp án trong dataset làm cận.
Không kế thừa nhận diện/cận/heuristic riêng hypercube từ code cũ.

Mỗi nhãn xuất được kiểm tra song ánh và tính lại CAB trên mọi cạnh.
Kết quả có thể là `OPTIMAL`, `FEASIBLE_UNPROVEN`, hoặc `ERROR`.
Ngân sách gồm preprocessing/build/optimize; đọc file và khởi tạo license ở ngoài.
Deadline và giới hạn bộ nhớ Gurobi đều là mềm; bộ nhớ Python/OS không được
bao gồm toàn bộ trong `SoftMemLimit`.

API tham khảo: [Gurobi Model](https://docs.gurobi.com/projects/optimizer/en/current/reference/python/model.html)
và [parameters](https://docs.gurobi.com/projects/optimizer/en/current/reference/parameters.html).
