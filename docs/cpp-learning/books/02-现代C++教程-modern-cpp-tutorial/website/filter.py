# !/usr/bin/env python3
# author: changkun<hi[at]changkun.de>
import os
import re

source_dir = [
    '../book/zh-cn/',
    '../book/en-us/'
]

destination_dir = [
    './src/modern-cpp/zh-cn/',
    './src/modern-cpp/en-us/'
]

chapters = ['00-preface.md', '01-intro.md',  '02-usability.md', '03-runtime.md', '04-containers.md', '05-pointers.md', '06-regex.md', '07-thread.md', '08-filesystem.md', '09-others.md', '10-cpp20.md', '11-cpp23.md', '12-cpp26.md', 'appendix1.md', 'appendix2.md', 'appendix3.md']

ignores = ['TOC', '返回目录', '许可', 'license', 'Table of Content', 'License']

for index, source in enumerate(source_dir):
    for chapter in chapters:
        dst_filepath = destination_dir[index] + chapter[:-3]
        os.makedirs(dst_filepath)
        print(dst_filepath)
        print(dst_filepath + '/index.md')
        with open(source+chapter, 'r', encoding='utf-8') as source_file:
            with open(dst_filepath + '/index.md', 'w', encoding='utf-8') as output_file:
                for line in source_file:
                    if any(keyword in line for keyword in ignores):
                        continue
                    else:
                        # Rewrite relative cross-chapter links `](./NN-name.md)`
                        # (optionally with a #anchor) to the website's
                        # `](../NN-name/index.html)` form. The pattern is anchored
                        # to the `](./…md)` link syntax with a simple filename so it
                        # cannot corrupt external URLs — the previous loose regex
                        # `(./)(.*?)(.md)` matched any `:/ … md` span and mangled
                        # links like `#cmdoption-…` into `https..//…`.
                        output_file.write(re.sub(r'\]\(\./([\w-]+)\.md(#[^)]*)?\)', r'](../\1/index.html\2)', line))
