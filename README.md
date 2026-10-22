# BTVN #03 – Flight Booking Agent

**Môn:** SE343 – Software Agent Engineering  
**MSSV:** 24521351  
**Họ tên:** *(điền tên của bạn)*

---

## 📁 Cấu trúc thư mục

```
btvn_03/
├── .env                          # API key (KHÔNG commit — xem .gitignore)
├── .gitignore                    # Bỏ qua .env, __pycache__, memory.json, ...
├── flight_agent.py               # Agent gốc: ReAct / Plan-then-Execute / Hybrid
├── flight_agent_memory.py        # Challenge A: Agent + Persistent Memory (JSON)
├── gen_memory_report.py          # Script sinh file báo cáo .docx
├── 24521351_BTVN_03.pdf          # Báo cáo gốc (nộp trước)
├── 24521351_ChallengeA_Memory.docx  # Báo cáo Challenge A: Persistent Memory
└── README.md                     # File này
```

> **Lưu ý:** `memory.json` được tạo tự động lúc chạy và nằm trong `.gitignore`
> (không commit vào repo vì là dữ liệu runtime).

---

## ⚙️ Cài đặt

### 1. Yêu cầu

- Python 3.11+
- pip

### 2. Cài thư viện

```bash
pip install langchain langchain-core langchain-google-genai python-docx
```

### 3. Tạo file `.env`

Tạo file `.env` trong cùng thư mục với nội dung:

```
GOOGLE_API_KEY='your-google-api-key-here'
```

> ⚠️ **Không bao giờ commit file `.env` lên GitHub!**

---

## 🚀 Cách chạy

### Agent gốc (`flight_agent.py`)

```bash
python flight_agent.py
```

Chọn pattern và case theo menu:

| Lựa chọn | Mô tả |
|---|---|
| **Pattern 1 – ReAct** | Think → Act → Observe, từng bước một (linh hoạt) |
| **Pattern 2 – Plan-then-Execute** | Lên kế hoạch toàn bộ trước, sau đó thực thi |
| **Pattern 3 – Hybrid** | Plan trước; nếu thất bại → ReAct fallback |
| **Case: success** | Có chuyến bay hợp lệ → đặt và thanh toán → DONE |
| **Case: fail** | Không có chuyến bay hợp lệ → harness chặn → FAILED + handoff |

---

### Agent có Persistent Memory (`flight_agent_memory.py`) — Challenge A

```bash
python flight_agent_memory.py
```

Chương trình sẽ:

1. **Nạp memory** từ `memory.json` (nếu chưa có → tạo mới trống)
2. **Kiểm tra quy ước** — nếu `CONSTRAINTS` thay đổi so với lần trước, in cảnh báo và đánh dấu các session cũ là `stale`
3. **In `[KIỂM CHỨNG]`** — hiển thị đúng phần memory sẽ inject vào system prompt
4. **Chạy agent** với system prompt được tăng cường bởi memory
5. **Lưu kết quả** session vào `memory.json`

**Ví dụ output đầu session thứ hai (sau khi đã chạy session 1 thành công):**

```
[KIỂM CHỨNG - Memory injected into context]
[MEMORY - Project conventions (saved 2026-10-22T10:00:00)]
  Route: SGN -> DAD
  Date: 2026-10-07
  Depart before: 12:00
  Max price: 2,000,000 VND

[MEMORY - Last session (sess-001, 2026-10-22T10:00:00)]
  Pattern: react | Case: success
  Bookings: VN122-12A (paid=True)
  Result: DONE
```

---

### Tạo lại báo cáo `.docx`

```bash
python gen_memory_report.py
```

Sinh ra file `24521351_ChallengeA_Memory.docx` trong cùng thư mục.

---

## 🧠 Kiến trúc Agent

```
User Request
     │
     ▼
┌─────────────┐      ┌───────────────────────────┐
│   MODEL     │◄────►│          HARNESS           │
│ (Scripted / │      │  check_permission()        │
│   LLM)      │      │  guarded_call()            │
│             │      │  is_done()                 │
│ ReAct       │      │  handoff()                 │
│ Plan+Exec   │      │  validate_plan()           │
│ Hybrid      │      │  confirm_plan()            │
└─────────────┘      │  record_booking() ← Memory │
                     └───────────────────────────┘
                                  │
                           memory.json
                      (Persistent Memory)
```

### Nguyên tắc cốt lõi (Harness Ideas)

| # | Ý tưởng | Cách implement |
|---|---|---|
| 1 | Constraints là DATA | `Constraints` dataclass → prompt & permission check |
| 2 | Permission check | `check_permission()` chạy trước MỌI tool call |
| 3 | Done do CODE quyết | `is_done()` đọc lại từ hệ thống, không tin model |
| 4 | Handoff cho người | `handoff()` khi agent thất bại |
| 5 | Plan là DATA | `validate_plan()` kiểm tra trước khi chạy |
| 6 | Người dùng duyệt plan | `confirm_plan()` → không step nào chạy nếu chưa "yes" |
| 7 | **Persistent Memory** | Harness ghi sau `pay` thành công; nạp ở đầu session |

---

## 📄 Báo cáo

- **`24521351_BTVN_03.pdf`** — Báo cáo gốc (Harness ideas 1–6)
- **`24521351_ChallengeA_Memory.docx`** — Báo cáo Challenge A: Persistent Memory

---

## 🗂️ Tóm tắt Memory Design (Challenge A)

| Câu hỏi | Trả lời |
|---|---|
| **Lưu ở đâu?** | `memory.json` — JSON, human-readable, không cần thư viện ngoài |
| **Ai ghi?** | Harness (sau `pay` thành công + khi session bắt đầu) |
| **Khi nào nạp?** | Đầu mỗi session, inject vào system prompt |
| **Khi quy ước đổi?** | `update_conventions()` phát hiện, cập nhật, mark stale |
| **Kiểm chứng?** | In `[KIỂM CHỨNG]` trước khi agent chạy |
