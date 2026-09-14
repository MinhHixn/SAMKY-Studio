# Phân tích lượt chạy TP.HCM — `sim_09c6fe8e0318`

## Phạm vi thực tế

Lượt chạy hoàn tất 60/60 rounds trên cả Twitter và Reddit, với 64 agent. Cấu hình quy định **60 giờ mô phỏng** (mỗi round một giờ), dù bối cảnh nói về một chương trình thí điểm 90 ngày. Chạy từ 17:47:09 đến 18:42:35 ngày 13/09/2026, khoảng 55 phút 26 giây theo đồng hồ thực. Đây là phản ứng của agent trong khoảng thời gian mô phỏng ngắn, không phải quan sát đầy đủ 90 ngày.

Nguồn: [`run_state.json`](../backend/uploads/simulations/sim_09c6fe8e0318/run_state.json), [`simulation_config.json`](../backend/uploads/simulations/sim_09c6fe8e0318/simulation_config.json).

## Hành động quan sát được

| Loại | Twitter | Reddit | Tổng |
| --- | ---: | ---: | ---: |
| Bài đăng | 19 | 27 | 46 |
| Bình luận | 0 | 71 | 71 |
| Thích bài/bình luận | 88 | 131 | 219 |
| Theo dõi | 14 | 35 | 49 |
| Trích dẫn/chia sẻ | 5 | 0 | 5 |
| Tìm kiếm/xu hướng | 0 | 4 | 4 |
| Đo telemetry | 320 | 320 | 640 |
| **Tổng** | **446** | **588** | **1.034** |

Chỉ **394/1.034** bản ghi là hành động xã hội hoặc tìm kiếm; **640 (61,9%)** là phép đo telemetry ở các round 12, 24, 36, 48 và 60. Các phép đo này không nên tính như bài đăng hay phản ứng công khai. Nguồn: [`twitter/actions.jsonl`](../backend/uploads/simulations/sim_09c6fe8e0318/twitter/actions.jsonl), [`reddit/actions.jsonl`](../backend/uploads/simulations/sim_09c6fe8e0318/reddit/actions.jsonl).

Các chủ đề có căn cứ trong bản ghi:

- Từ đầu, truyền thông địa phương hỏi rõ tiêu chí miễn trừ, mức phạt và đăng ký xe giao hàng; cư dân và doanh nghiệp lo gián đoạn đi lại, mua sắm, giao hàng.
- Tài xế giao hàng nói chi phí mua xe điện quá cao, yêu cầu vay lãi suất thấp và quy trình đăng ký rõ ràng. Ở round 37, một bình luận nêu thời gian chờ đổi pin có thể làm mất đơn.
- Người lao động nêu khoảng trống tuyến buýt trước 6 giờ sáng cho người làm theo ca. Ở round 37, nhà vận hành buýt nhắc đến tần suất, làn ưu tiên, kết nối metro và thanh toán tiền mặt.
- Ở round 14, tài khoản mô phỏng chính quyền thành phố **nói sẽ** công bố dữ liệu phát thải, tiêu chí miễn trừ và tiến độ hạ tầng. Đây là phát biểu của agent, chưa phải bằng chứng chính sách đã triển khai. Ở round 48, tài khoản mô phỏng Grab đề xuất bổ sung tuyến đêm và đăng ký xe giao hàng linh hoạt.

Đây là phát ngôn và hành động của **nhân vật mô phỏng**, không phải khảo sát người dân, số liệu GPS thực, quyết định của TP.HCM hay dự báo đã kiểm chứng.

## Giới hạn của báo cáo AI hiện có

[`full_report.md`](../backend/uploads/reports/report_e3e35b835d96/full_report.md) đã được tạo, nhưng hai mục đầu chứa lời gọi công cụ chưa xử lý thay vì kết luận hoàn chỉnh. Hai mục sau mô tả diễn biến qua nhiều tuần và hết 90 ngày, kèm trích dẫn, số tiền phạt/trợ cấp và số liệu chính trị rất cụ thể. Nhật ký chỉ chứa **60 giờ mô phỏng**; không đủ cơ sở để xem những chi tiết này là sự kiện đã xảy ra trong lượt chạy. Phần báo cáo nên được đọc như diễn giải giả định và đối chiếu từng nhận định với nhật ký hành động trước khi sử dụng.

Các trung bình telemetry xấp xỉ 0,65–0,70 qua năm mốc, song giá trị 0,72 lặp lại ở nhiều agent (Twitter 208/320, Reddit 168/320). Không nên diễn giải các con số đó là xác suất thực nghiệm của kết quả chính sách.
