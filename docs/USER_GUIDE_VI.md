# Hướng dẫn sử dụng SAMKY Studio

SAMKY Studio là giao diện thân thiện xây trên pipeline MiroFish-Offline. Một lượt chạy đi qua bốn khâu thật: đọc tài liệu, dựng knowledge graph, tạo xã hội tác nhân và chạy tương tác; sau đó có thể sinh báo cáo hoặc phỏng vấn tác nhân.

## Chọn cách chạy

| Cách | Model sinh nội dung | Dữ liệu sự kiện | Phù hợp khi |
|---|---|---|---|
| Offline | Ollama trên máy của bạn | Ở máy của bạn | Riêng tư, không muốn gửi nội dung ra ngoài |
| Online | Endpoint OpenAI-compatible do bạn cấu hình | Prompt được gửi tới nhà cung cấp model | Máy không đủ GPU/RAM hoặc cần model mạnh hơn |
| Không UI | Giống cấu hình server | Giống hai chế độ trên | Batch, cron, notebook, CI/HPC |

Neo4j luôn lưu graph tại máy/volume của bạn. Ở cấu hình online mặc định, embedding vẫn chạy bằng Ollama local; chỉ các yêu cầu sinh nội dung được gửi tới endpoint bạn chọn.

## 1. Chạy offline bằng Docker

Yêu cầu: Docker Desktop/Engine có Compose v2. RAM 16 GB là mức tối thiểu thực tế cho model 7B; GPU được Ollama hỗ trợ sẽ nhanh hơn đáng kể.

Tại thư mục repository:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker exec mirofish-ollama ollama pull qwen2.5:7b
docker exec mirofish-ollama ollama pull nomic-embed-text
```

Mở `http://localhost:3000`. Thẻ **Môi trường hiện tại** phải báo model và Neo4j sẵn sàng. Nếu model vừa tải xong, bấm nút làm mới trên thẻ.

Để dừng mà vẫn giữ dữ liệu:

```powershell
docker compose down
```

Không thêm `-v` nếu muốn giữ Neo4j và model đã tải.

## 2. Chạy với model online

Tạo cấu hình riêng để không vô tình commit API key:

```powershell
Copy-Item .env.online.example .env.online
```

Mở `.env.online` và điền bốn giá trị: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`, `OPENAI_API_KEY`. `OPENAI_API_BASE_URL` thường giống `LLM_BASE_URL`.

Khởi động:

```powershell
docker compose -f compose.online.yml --env-file .env.online up -d --build
docker exec mirofish-embeddings ollama pull nomic-embed-text
```

Mở `http://localhost:3000`. Giao diện sẽ tự nhận diện **Online** từ endpoint đã cấu hình. Bạn có thể nhập hoặc xóa API key ngay trên trang thiết lập; khóa được giữ trong bộ nhớ server, không lưu trong bộ nhớ trình duyệt.

## 3. Tạo một simulation bằng UI

1. Nhập tên sự kiện (không bắt buộc).
2. Viết một câu hỏi cụ thể. Câu hỏi tốt thường nêu mốc thời gian, nhóm liên quan và đầu ra cần quan sát, ví dụ: “Trong 30 ngày sau thông báo, khách hàng, báo chí và đối thủ có thể phản ứng thế nào; đâu là ba rủi ro danh tiếng lớn nhất?”.
3. Thêm ít nhất một tệp PDF, Markdown hoặc TXT. Chỉ đưa vào thông tin người dùng simulation thực sự cần biết.
4. Chọn online/offline, endpoint, model và API key nếu cần. Chọn số vòng ngay tại đây; **đề xuất 60 vòng**.
5. Chọn **Bắt đầu mô phỏng**. Các bước chuẩn bị chạy tự động; màn hình chỉ tập trung vào graph và thanh tiến độ.
6. Khi chạy xong, tạo báo cáo hoặc phỏng vấn agent riêng lẻ/nhóm. Xem [hướng dẫn giao diện mới](STUDIO_UI.md).

## 4. Chạy không cần UI

CLI kết nối tới cùng API, vì vậy server phải đang chạy. Kiểm tra trước:

```powershell
python backend/scripts/sam_cli.py doctor
```

Chạy một sự kiện và chờ đến khi xong:

```powershell
python backend/scripts/sam_cli.py run `
  --file .\examples\event.md `
  --goal "Trong 30 ngày tới, các bên liên quan sẽ phản ứng như thế nào?" `
  --name "Sự kiện thử nghiệm" `
  --rounds 10 `
  --wait `
  --report
```

Trên Bash, thay dấu xuống dòng PowerShell bằng `\`. Dùng lại `--file` để nạp nhiều tài liệu. Lệnh in JSON chứa `project_id`, `graph_id`, `simulation_id` và `report_id` (nếu có), thuận tiện cho script khác xử lý.

Ví dụ chạy trên server khác:

```bash
python backend/scripts/sam_cli.py --base-url https://sam.example.com run \
  --file event.md --goal "Map stakeholder reactions" --rounds 20 --wait
```

## 5. Chạy trực tiếp để phát triển

```powershell
npm run setup
npm run setup:backend
npm run dev
```

Frontend ở `http://localhost:3000`, API ở `http://localhost:5001`. Neo4j và Ollama vẫn phải chạy; có thể khởi động riêng hai service bằng Docker.

## Khắc phục nhanh

- **Model chưa sẵn sàng:** chạy `ollama list` hoặc `docker exec mirofish-ollama ollama list`; tên trong `.env` phải khớp chính xác.
- **Neo4j chưa kết nối:** kiểm tra `docker compose ps` và `NEO4J_PASSWORD`.
- **Online trả 401/403:** kiểm tra API key, base URL kết thúc bằng `/v1`, và model ID được tài khoản cho phép.
- **Máy hết RAM/VRAM:** giảm xuống model nhỏ hơn, giảm số tác nhân/vòng ở bước thiết lập, hoặc chuyển sang endpoint online.
- **Simulation chậm:** lần chạy đầu phải tạo ontology, graph và persona. Thử tài liệu ngắn cùng 5 vòng trước khi chạy lớn.

## An toàn và diễn giải kết quả

Không đưa bí mật, dữ liệu cá nhân nhạy cảm hoặc tài liệu chưa được phép xử lý vào nhà cung cấp online. Simulation phản ánh dữ liệu, prompt, model và giả định persona; luôn ghi lại cấu hình và đối chiếu với chuyên gia lĩnh vực trước khi ra quyết định quan trọng.
