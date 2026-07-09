"""News AI Agent.

每日定时抓取权威外媒（CNA / The Economist / SCMP / The Times / CNBC / 联合早报）
指定板块新闻，按关键词过滤去重，调用 Google Gemini 生成英文精简摘要 + 核心关键词
+ 关键段落中文翻译，最终排版成 HTML 简报邮件发送到个人邮箱。

全流程开源、配置驱动（config.yaml），支持 Docker 一键启动与 GitHub Actions 免服务器定时运行。
"""

__version__ = "1.0.0"
