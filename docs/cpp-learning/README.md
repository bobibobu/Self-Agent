# C++ 复习资料库（遗忘重启 → 精通）

> 为"学过但忘了大半"的 C++ 开发者定制的复习资料合集，全部为官方开源或公开免费的资源。
> 建立日期：2026-10。配套的 Rust 学习目录见 [../rust-learning](../rust-learning/README.md)。

## 目录结构

```
docs/cpp-learning/
├── README.md                    # 本文件：总览与索引
├── 01-C++复习路线图.md           # 遗忘重启完整路线（含路线图与双线作战策略）
├── 02-书籍与资源清单.md          # 本地 8 套资料 + 在线资源/工具/付费书建议
└── books/                       # 已下载的完整资料
    ├── 01-C++核心指南-CppCoreGuidelines/    # ⭐ 官方编码准则（Stroustrup）
    ├── 02-现代C++教程-modern-cpp-tutorial/  # ⭐ 主力教材 C++11-20（中英双语）
    ├── 03-C++那些事-CPlusPlusThings/        # ⭐ 中文复习库（基础/底层/并发/设计模式）
    ├── 04-C++面试知识-interview/            # 八股自测
    ├── 05-现代C++特性速查-modern-cpp-features/
    ├── 06-C++最佳实践-cppbestpractices/
    ├── 07-awesome-cpp资源索引/
    └── 08-Google风格指南-styleguide/
```

## 快速开始（三步）

1. **自测定位**（3~5 天）：翻一遍 `books/04-C++面试知识-interview/` 的 C++ 部分，标记哪些彻底忘了——决定从路线图哪一周开始
2. **基础重建主线**：[learncpp.com](https://www.learncpp.com/)（在线）+ `books/03-C++那些事/`（中文对照），每周配 04 仓库自测
3. **进入现代 C++**：`books/02-现代C++教程/` 从 `book/zh-cn/` 顺序读，配 `code/` 里的示例动手跑

## 一句话用法

| 你现在的状态 | 打开哪个 |
| --- | --- |
| 概念都模糊 | learncpp 第 1 章（路线图阶段 1） |
| 基础还在，新标准忘了 | `02-现代C++教程` 直接开始 |
| 想查某个特性/函数 | `05-特性速查` / [cppreference](https://zh.cppreference.com/) |
| 想知道"该怎么写" | `01-核心指南` + `06-最佳实践` |
| 要面试了 | `04-面试知识` 循环 + LeetCode C++ 刷题 |

详细规划见 [01-C++复习路线图.md](01-C++复习路线图.md)（含 C++/Rust 双线时间安排），资源明细见 [02-书籍与资源清单.md](02-书籍与资源清单.md)。
