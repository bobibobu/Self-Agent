"""
RAG 知识库（Retrieval-Augmented Generation）
=============================================
让 Agent 基于私有文档回答问题，而非仅靠模型自身的预训练知识。

流程：
1. 上传文档（txt/md/等文本）
2. 分块（chunking）—— 切成适合检索的小段
3. 向量化（embedding）—— 存入向量库（复用 BaseStore 的语义索引）
4. 检索增强 —— 对话时按问题语义检索相关块，注入提示词

实现复用已有的 PostgresStore/InMemoryStore（带 index），
文档块存为 store 的 item，namespace 按知识库隔离。
"""
