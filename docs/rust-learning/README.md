# Rust 学习资料库

> 为 C++ 背景的 Rust 纯小白定制的学习资料合集，全部为官方开源或作者公开免费的资源。
> 建立日期：2026-10

## 目录结构

```
docs/rust-learning/
├── README.md                        # 本文件：总览与索引
├── 01-学习路线图.md                  # 从零到就业的完整路线（含路线图）
├── 02-书籍与资源清单.md              # 本地 14 本书说明 + 在线资源/社区/工具
├── 03-岗位市场分析与语言对比-2026.md # Java/Go/Rust/C++ 四语言深度对比分析
└── books/                           # 已下载的完整书籍源码（Markdown）
    ├── 01-rust语言圣经-rust-course/          # ⭐ 主力中文教程
    ├── 02-rust程序设计语言-中文版/            # ⭐ 官方书中文翻译
    ├── 03-the-rust-programming-language-en/  # 官方书英文原版
    ├── 04-comprehensive-rust-Google课程/     # Google 内部 Rust 课程
    ├── 05-rustlings-官方练习/                # ⭐ 官方上手练习
    ├── 06-rust-by-practice-实战练习/         # 中文在线练习题
    ├── 07-100-exercises-to-learn-rust/       # 100 道渐进练习
    ├── 08-easy-rust-简明教程/                # 简单英语/中文讲解
    ├── 09-rust-for-cpp-programmers/          # ⭐ C++ 程序员专用对照
    ├── 10-rust-by-example-官方示例/          # 官方可运行示例
    ├── 11-async-book-异步编程/               # 官方异步编程书
    ├── 12-rust-atomics-and-locks-中文/       # 并发圣经（中文，未完）
    ├── 13-rust-atomics-and-locks-en/         # ⭐ 并发圣经（英文完整）
    ├── 14-rustonomicon-unsafe进阶/           # unsafe/黑魔法进阶
    ├── 15-rust设计模式-patterns/             # Rust 设计模式（社区权威）
    └── 16-rust宏小书-tlborm/                 # Rust 宏教程（写宏必读）
```

## 快速开始（三步）

1. **装环境**：到 [rustup.rs](https://rustup.rs) 下载安装器，`rustup` 会一并装好 `cargo`（包管理/构建工具）。Windows 上选择默认的 MSVC 工具链即可（你有 C++ 背景，VS 生成工具大概率已就绪）。
2. **开始读**：打开 `books/01-rust语言圣经-rust-course/`，从 `SUMMARY.md` 开始按顺序读（在线版地址：<https://course.rs>）。
3. **边读边练**：克隆式练习 `books/05-rustlings-官方练习/`，每学一章做一组题。

## 我该怎么用这批资料？（C++ 背景专属建议）

| 你的状态 | 用法 |
| --- | --- |
| 第一周 | 语言圣经 1~5 章 + rustlings 的 `intro`/`functions` 组 |
| 卡在所有权 | 直接跳读 `09-rust-for-cpp-programmers/` 的 `unique.md`、`borrowed.md`、`rc-raw.md`，用 C++ 的 `unique_ptr`/引用/RALL 对照理解 |
| 想看例子 | `10-rust-by-example-官方示例/` 按主题查 |
| 学完基础 | `06-rust-by-practice` + `07-100-exercises` 双题库刷题巩固 |
| 进入实战 | 语言圣经后半 + `11-async-book` 异步 + 选做项目 |
| 深入底层 | `13-rust-atomics-and-locks-en`（并发）+ `14-rustonomicon`（unsafe） |

详细规划见 [01-学习路线图.md](01-学习路线图.md)，资源明细见 [02-书籍与资源清单.md](02-书籍与资源清单.md)，转行决策参考 [03-岗位市场分析与语言对比-2026.md](03-岗位市场分析与语言对比-2026.md)。
