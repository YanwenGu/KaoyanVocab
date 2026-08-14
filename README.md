# 考研英语词汇自动化收集系统 (Vocab-Collector)

做真题时复制生词 → 粘贴到网页 → AI 自动补全释义、例句、派生词 → 周末导出 PDF 打印背诵。

## 快速开始

```bash
# 1. 安装依赖
pip install fastapi uvicorn requests python-dotenv

# 2. 配置 API Key（编辑 .env 文件）
# DEEPSEEK_API_KEY=你的key

# 3. 启动后端
python main.py

# 4. 打开前端
open index.html
```

## 使用方式

- **录入单词**：复制单词，粘贴到输入框，按回车。系统自动补全词性、释义、例句、派生词
- **录入词组**：粘贴词组（如 `take it for granted`），点击按钮直接录入（跳过拼写检查）
- **拼写纠错**：回车录入时自动检查拼写，打错字母会弹出建议窗口
- **浏览与删除**：表格按时间倒序展示，点击 ✕ 可删除
- **导出 PDF**：点击"导出PDF"按钮 → Cmd+P → 保存为 PDF → 打印

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python + FastAPI + Uvicorn |
| 数据库 | SQLite（单文件，零配置） |
| AI 引擎 | DeepSeek API（deepseek-v4-flash） |
| 前端 | 纯 HTML + Vanilla JS + CSS（无框架） |
| PDF 导出 | CSS @media print + 浏览器原生打印 |
