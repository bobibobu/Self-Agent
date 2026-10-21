#!/usr/bin/env python3
"""同步 docs 目录下的文档。

以仓库根目录的 README.md、README_en.md 为准，生成 docs/README.md 和 docs/en.md。
docs 版本与源文件的唯一差别是头部：Github 徽章换成链接、Docsify 变为纯文本、去掉语言切换栏。

用法：
    python scripts/sync_docs.py
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

# docs 版文档的头部（与源文件的唯一差别）
DOCS_HEADER = (
    '<div align="center">\n'
    '<a href="https://github.com/huihut/interview">📖 Github</a>\n'
    '&emsp;&emsp; | &emsp;&emsp;\n'
    '📚 Docsify\n'
    '</div> \n'
    '<br>\n'
    '\n'
)

# 源文件头部结束、正文开始的标记（“关于”折叠块）
BODY_MARKER = '<b><details>'

# (源文件, 目标文件)
PAIRS = [
    (ROOT / 'README.md', ROOT / 'docs' / 'README.md'),
    (ROOT / 'README_en.md', ROOT / 'docs' / 'en.md'),
]


def make_docs_content(src_text: str, src_name: str) -> str:
    idx = src_text.find(BODY_MARKER)
    if idx == -1:
        raise RuntimeError(f'{src_name}: 找不到正文起始标记 {BODY_MARKER!r}，请检查文件头部')
    return DOCS_HEADER + src_text[idx:]


def main() -> int:
    for src, dst in PAIRS:
        if not src.is_file():
            print(f'跳过：源文件不存在 {src}', file=sys.stderr)
            continue
        with open(src, encoding='utf-8', newline='') as f:
            src_text = f.read()
        content = make_docs_content(src_text, src.name)
        if dst.is_file():
            with open(dst, encoding='utf-8', newline='') as f:
                if f.read() == content:
                    print(f'无变化：{dst.relative_to(ROOT)}')
                    continue
        with open(dst, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        print(f'已同步：{src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
