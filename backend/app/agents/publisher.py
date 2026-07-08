"""发布编辑 Agent：字数适配 + Markdown → 微信公众号 HTML"""

import re
from typing import Optional

import markdown


class PublisherAgent:
    def __init__(self, platform: str = "wechat", max_length: int = 9500):
        self.name = "publisher"
        self.platform = platform
        self.max_length = max_length

    def prepare(self, title: str, body: str, summary: Optional[str] = None) -> dict:
        html = self._markdown_to_wechat_html(body)
        if not summary:
            summary = self._auto_summary(body)
        # 中文字数估算（去除 HTML 标签后统计）
        import re
        text_only = re.sub(r'<[^>]+>', '', html)
        chinese_count = sum(1 for c in text_only if '一' <= c <= '鿿')
        return {
            "title": title,
            "body": html,
            "summary": summary,
            "platform": self.platform,
            "word_count": chinese_count,
        }

    def _markdown_to_wechat_html(self, markdown_text: str) -> str:
        # 清除未上传图片的占位符行，避免输出到微信 HTML 板式
        markdown_text = re.sub(
            r'(?:>\s*)?\*\*\[待生成(?:封面图|插图 \d+) Prompt\]\*\*：[\s\S]*?(?:\n\n|$)',
            '',
            markdown_text
        )

        # 先预处理代码块（微信不支持 pre/code）
        code_blocks = []
        def save_code(m):
            code_blocks.append(m.group(0))
            return f"__CODEBLOCK_{len(code_blocks)-1}__"
        md = re.sub(r'```[\w]*\n[\s\S]+?\n```', save_code, markdown_text)

        html = markdown.markdown(md, extensions=["tables", "fenced_code"])

        # 还原代码块
        for i, block in enumerate(code_blocks):
            inner = re.sub(r'^```\w*\n|\n```$', '', block)
            replacement = f'<p style="background:#f4f4f4;padding:12px 16px;border-radius:6px;font-size:14px;color:#555;margin:12px 0;overflow-x:auto;">{inner}</p>'
            html = html.replace(f"__CODEBLOCK_{i}__", replacement)

        # 整体预处理：合并多行 blockquote 和 ul/ol 为单行再处理
        html = self._preprocess_blocks(html)
        html = self._post_process(html)
        return html

    def _preprocess_blocks(self, html: str) -> str:
        """把多行 blockquote / ul / ol 合并成单行"""
        # blockquote: <blockquote>...</blockquote> 可能跨多行
        html = re.sub(r'<blockquote[^>]*>(.*?)</blockquote>', self._render_blockquote, html, flags=re.DOTALL)
        # ul / ol 列表：合并内部所有 li 再整体渲染
        html = re.sub(r'<ul>(.*?)</ul>', self._render_list, html, flags=re.DOTALL)
        html = re.sub(r'<ol>(.*?)</ol>', self._render_list, html, flags=re.DOTALL)
        return html

    def _render_blockquote(self, m) -> str:
        inner = m.group(1)
        # 去掉 p 标签，内部换行转成空格
        inner = re.sub(r'</?p[^>]*>', '', inner)
        inner = re.sub(r'\s+', ' ', inner).strip()
        if inner.startswith("提醒：") or inner.startswith("<strong>提醒</strong>："):
            return (
                '<blockquote style="border-left:4px solid #2563eb;padding:12px 16px;'
                'margin:20px 0;background:#eff6ff;border-radius:6px;color:#1e3a8a;'
                f'font-size:15px;line-height:1.85;">{inner}</blockquote>'
            )
        return f'<blockquote style="border-left:3px solid #cbd5e1;padding:10px 16px;margin:18px 0;background:#f8fafc;border-radius:4px;color:#475569;font-size:15px;line-height:1.85;">{inner}</blockquote>'

    def _render_list(self, m) -> str:
        items = re.findall(r'<li>(.*?)</li>', m.group(1), re.DOTALL)
        lines = []
        for item in items:
            item = re.sub(r'</?p[^>]*>', '', item).strip()
            if item.startswith("步骤：") or item.startswith("<strong>步骤</strong>："):
                cleaned = re.sub(r'^(<strong>)?步骤(</strong>)?：', '', item).strip()
                lines.append(
                    '<p style="border:1px solid #e4e4e7;background:#fafafa;'
                    'border-radius:8px;padding:10px 12px;margin:8px 0;line-height:1.8;'
                    f'font-size:15px;color:#333;"><strong style="color:#2563eb;">步骤</strong>：{cleaned}</p>'
                )
            else:
                lines.append(f'<p style="margin:6px 0 6px 20px;line-height:1.8;font-size:15px;color:#444;">• {item}</p>')
        return "\n".join(lines)

    def _post_process(self, html: str) -> str:
        """处理剩余的单行 HTML 标签"""
        lines = html.split("\n")
        result = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # h2 / h3 标题
            hm = re.match(r'<h([23])>(.+)</h\1>', stripped)
            if hm:
                level, text = hm.group(1), hm.group(2)
                size = "19px" if level == "2" else "17px"
                result.append(
                    '<p style="margin:28px 0 12px;padding-top:4px;'
                    f'font-size:{size};font-weight:700;color:#18181b;line-height:1.55;">{text}</p>'
                )
                continue

            # img → 占位提示
            if stripped.startswith("<img"):
                result.append('<p style="text-align:center;margin:16px 0;color:#aaa;font-size:13px;">[图片占位符]</p>')
                continue

            # hr
            if stripped.startswith("<hr"):
                result.append('<p style="border-top:1px dashed #ddd;margin:20px 0;"></p>')
                continue

            # 预处理阶段输出的 blockquote 和列表项直接保留，不做二次包裹
            if (
                stripped.startswith("<blockquote")
                or ("• " in stripped and stripped.startswith("<p"))
                or ("<strong style=\"color:#2563eb;\">步骤</strong>" in stripped and stripped.startswith("<p"))
            ):
                result.append(stripped)
                continue

            # 表格
            if stripped.startswith("<table"):
                # 简单表格处理：提取第一行作为粗体，其余行普通
                table_lines = [l.strip() for l in stripped.splitlines() if l.strip()]
                for tl in table_lines:
                    cells = re.findall(r'<td>(.*?)</td>', tl)
                    if cells:
                        row_text = " | ".join(cells)
                        result.append(f'<p style="margin:4px 0;font-size:15px;line-height:1.6;">{row_text}</p>')
                continue

            # 其余全部当段落处理。按长度微调节奏，避免整篇文章像机器切出来的等距段落。
            text = re.sub(r'^<p>(.*)</p>$', r'\1', stripped)
            plain_text = re.sub(r'<[^>]+>', '', text).strip()
            if len(plain_text) <= 24:
                style = "margin:14px 0 8px;line-height:1.75;font-size:15px;color:#222;font-weight:500;"
            elif len(plain_text) >= 120:
                style = "margin:12px 0;line-height:1.95;font-size:15px;color:#333;"
            else:
                style = "margin:9px 0;line-height:1.88;font-size:15px;color:#333;"
            result.append(f'<p style="{style}">{text}</p>')

        final = "\n".join(result)
        final = re.sub(r'<p style="margin:8px 0;line-height:1.9;font-size:15px;color:#333;">\s*</p>', '', final)
        return final

    def _auto_summary(self, markdown_text: str) -> str:
        """从 Markdown 原文提取前150字"""
        clean = re.sub(r'#{1,6}\s+|[\*_]{1,2}([^*_]+)[\*_]{1,2}|\[([^\]]+)\]\([^\)]+\)|`{1,3}[^`]*`{1,3}|^\s*[-*+]\s+|^\s*>\s*', '', markdown_text, flags=re.MULTILINE)
        clean = re.sub(r'\n+', ' ', clean).strip()
        return clean[:150] + "..." if len(clean) > 150 else clean
