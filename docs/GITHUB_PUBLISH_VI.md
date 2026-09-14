# Chuẩn bị đăng SAMKY Studio lên GitHub

Hướng dẫn này áp dụng cho thư mục `MiroFish-Offline` hiện tại. Tên sản phẩm là **SAMKY Studio**; tên thư mục cục bộ và tên module backend `mirofish-offline-backend` vẫn có thể giữ để tránh làm hỏng đường dẫn và công cụ cũ. Repo hiện có `origin` trỏ tới `nikmcfly/MiroFish-Offline` và nhánh làm việc là `phase0-minimal-strict-neo4j`. **Không push lên `origin` hiện tại.** Bạn sẽ tạo repo GitHub của mình rồi đổi remote trước khi push.

## 1. Hoàn thiện nội dung trước khi đăng

1. Kiểm tra quyền công bố mọi tài liệu, dữ liệu thí nghiệm, hình ảnh và mã được thêm vào từ dự án khác. Repo dùng [AGPL-3.0](../LICENSE); giữ giấy phép, thông báo bản quyền và ghi nhận nguồn MiroFish trong README. Nếu có tài sản bên thứ ba, kiểm tra điều khoản riêng của từng tài sản.
2. Đọc lại [README](../README.md), [hướng dẫn tiếng Việt](USER_GUIDE_VI.md), [hướng dẫn tiếng Anh](USER_GUIDE.md) và [hướng dẫn tiếng Tây Ban Nha](USER_GUIDE_ES.md). Sửa các thông tin hạ tầng, model, đường dẫn và kết quả nghiên cứu chưa còn đúng.
3. Chạy ứng dụng thật với model bạn định giới thiệu: tải tài liệu, chạy ít nhất một mô phỏng, mở graph, tạo báo cáo, phỏng vấn agent; kiểm tra desktop, mobile, light mode và dark mode. Hiệu ứng tia chớp trên logo chỉ chạy trong dark mode, lặp khoảng 7 giây và dừng khi hệ điều hành bật giảm chuyển động.
4. Chạy kiểm tra cục bộ từ gốc repo:

   ```powershell
   npm ci
   npm --prefix frontend ci
   npm run build
   node --test frontend/tests/run-state.test.mjs
   cd backend
   uv sync --locked --group dev
   uv run pytest -q tests/test_api_status.py tests/test_headless_api_modes.py
   cd ..
   ```

   CI trong `.github/workflows/ci.yml` cũng chạy build frontend và smoke test backend sau khi bạn push. Nếu máy đã có môi trường `backend/.venv311` và không muốn `uv` truy cập cache, có thể chạy `backend/.venv311/Scripts/python.exe -m pytest -q backend/tests/test_api_status.py backend/tests/test_headless_api_modes.py` từ gốc repo. Nếu không đủ tài nguyên chạy mô phỏng thật, ghi rõ giới hạn đó trong phần phát hành.

## 2. Rà soát dữ liệu riêng tư và file sẽ commit

`.gitignore` đã loại `.env`, các biến thể `.env.*` (trừ file `.example`), thư mục test runtime và upload. Đặc biệt, file `.env.openrouter` ở máy hiện tại là cấu hình riêng, **không đưa lên GitHub**. Không đăng API key, mật khẩu Neo4j thật, thông tin SSH/HPC, dữ liệu người dùng, tài liệu nguồn có bản quyền, log có prompt, hay kết quả mô phỏng riêng tư.

```powershell
git status --short
git remote -v
git check-ignore -v .env .env.openrouter .env.online
git ls-files .env .env.openrouter .env.online
git diff --check
```

Lệnh `git ls-files` ở trên phải không in ra các file cấu hình riêng. Xem **toàn bộ** file mới và diff trước khi stage; repo hiện có nhiều file mới chưa được theo dõi và thay đổi tồn đọng từ trước, nên không dùng `git add .` theo thói quen. Đặc biệt cần duyệt và stage các file mới phục vụ sản phẩm như `frontend/src/studio/`, các trang `Studio*.vue`, `backend/app/services/studio_runtime.py`, `backend/scripts/sam_cli.py`, `.env.online.example`, tài liệu người dùng và `.github/workflows/ci.yml`; nếu thiếu chúng thì build/CI hoặc tài liệu sẽ không đầy đủ. Stage từng thư mục/file đã duyệt bằng `git add <đường-dẫn>` hoặc `git add -p`, rồi kiểm tra chính xác bản sẽ commit:

```powershell
git diff --cached --name-status
git diff --cached --check
git diff --cached
```

Hiện `git diff --check` báo vài dòng thừa khoảng trắng trong README và mã backend đã thay đổi trước đợt đổi tên này. Hãy sửa những dòng bạn định stage trước khi commit; đừng bỏ qua đầu ra của lệnh kiểm tra.

Kiểm tra cả **lịch sử Git**, không chỉ file hiện tại. Có thể dùng công cụ quét secret như `gitleaks` trên toàn bộ lịch sử trước khi public. Nếu một khóa từng nằm trong commit, hãy thu hồi/đổi khóa trước; xóa file ở commit mới không xóa khóa khỏi lịch sử. Xem [hướng dẫn xử lý dữ liệu nhạy cảm của GitHub](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

## 3. Tạo repo GitHub của bạn

Trên [trang tạo repository](https://github.com/new), chọn tài khoản của bạn, đặt tên **`SAMKY-Studio`**, chọn `Private` để kiểm tra thử trước hoặc `Public` khi đã sẵn sàng. Để trống các tùy chọn tạo README, `.gitignore` và LICENSE vì repo cục bộ đã có. GitHub cũng [khuyên không tạo các file này khi nhập repo đã tồn tại](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository).

Repo hiện có lịch sử MiroFish-Offline. Nếu bạn muốn GitHub thể hiện quan hệ fork rõ ràng, có thể tạo fork của repo gốc rồi đổi tên fork trong Settings. Với fork đã có nhánh `main`, hãy push lên một nhánh mới (`git push -u origin HEAD:samky-studio`) rồi tạo pull request; **không** dùng lệnh `HEAD:main` của bước 4 để ghi trực tiếp vào nhánh `main` của fork. Nếu muốn tên repo độc lập, tạo repo trống như trên và giữ ghi nhận nguồn trong README cùng giấy phép. Không cần copy toàn bộ thư mục `Claw-4-FUN` lên GitHub: chỉ thư mục `MiroFish-Offline` là repo ứng dụng.

## 4. Commit và push sau khi đã rà soát

Với **repo mới đang trống**, tại gốc `MiroFish-Offline`, sau khi đã stage và kiểm tra nội dung ở bước 2:

```powershell
git commit -m "Brand as SAMKY Studio and prepare GitHub release"
git remote rename origin upstream
git remote add origin https://github.com/<TEN_TAI_KHOAN>/SAMKY-Studio.git
git remote -v
git push -u origin HEAD:main
```

Thay `<TEN_TAI_KHOAN>` bằng username hoặc tên tổ chức của bạn. Nếu bạn dùng fork, `origin` mới là URL fork sau khi đổi tên, còn `upstream` vẫn chỉ tới `nikmcfly/MiroFish-Offline`. Lệnh `HEAD:main` đưa commit hiện tại lên nhánh `main` của repo mới mà không đổi tên nhánh cục bộ. Chỉ chạy khi repo GitHub mới đang trống và các kiểm tra đã đạt. GitHub yêu cầu đăng nhập phù hợp khi push qua HTTPS; không đưa token vào dòng lệnh hay URL remote. Xem [hướng dẫn remote](https://docs.github.com/en/get-started/git-basics/managing-remote-repositories) và [hướng dẫn đưa code cục bộ lên GitHub](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github).

## 5. Kiểm tra sau khi push

1. Mở repo mới: xác nhận README hiển thị tên SAMKY Studio, LICENSE hiện diện, các file `.env` thật và dữ liệu runtime không xuất hiện.
2. Mở tab **Actions**, chờ workflow CI xanh. Nếu đỏ, đọc log, sửa ở máy rồi push commit mới.
3. Mở **Settings → Advanced Security** và bật secret scanning/push protection nếu tài khoản và repo hỗ trợ; [GitHub hướng dẫn bật push protection tại đây](https://docs.github.com/en/code-security/how-tos/secure-your-secrets/prevent-future-leaks/enable-push-protection).
4. Điền mô tả, topics và ảnh chụp giao diện đã xóa dữ liệu riêng tư. Có thể tạo release/tag đầu tiên khi kiểm thử thật và CI đã đạt.

**Chưa thực hiện bước tạo repo hoặc push trong hướng dẫn này.** Chỉ bạn quyết định thời điểm và chế độ hiển thị của repo GitHub.
