"""查询预处理（D12）：把口语查询拆成关键词，再喂给检索。

基线病因：整句当一个短语做连续匹配，一字不差才认 → 口语查询全军覆没。
拆词三刀：标点切段 → 停词当刀 → 长段滑窗二字块。词与词之间是 OR 关系。

土办法 v1（D009）：不引入 jieba 分词库。切错的二字块是噪音词，查不到即无害——
OR 合并的特性：多切无害，漏切才有事。评估集说不够再升级（jieba 是已知升级点）。
"""

from __future__ import annotations

import re

# 停词表：不承担信息量的废话词。不当"过滤"用，当"刀"用——见到就切，切完即扔。
# 长的必须先切（"面试官问我"先于"问"），否则被小刀切碎留残渣。
STOPWORDS = (
    "面试官问我", "面试官问", "自我介绍", "介绍一下", "能不能", "可不可以",
    "什么是", "为什么", "怎么样", "怎么看", "怎么理解", "怎么实现",
    "请问", "说说", "聊聊", "讲讲", "谈谈", "解释", "描述",
    "到底", "究竟", "干嘛", "干吗", "如何",
    "什么", "怎么", "哪些", "哪个", "啥",
    "问题", "区别", "意思",
    "的", "了", "把", "是", "吗", "呢", "啊", "吧", "嘛",
    "我", "你", "您", "这", "那", "有", "和", "与", "及", "或", "被", "让",
)

# 第一刀的刀口：中英文标点 + 空白
_PUNCT = re.compile(r"[\s，。！？；：、,.!?;:\"'()（）【】《》<>〈〉…—\-~·/\\|]+")
# 纯中文（不含字母数字下划线）才需要滑窗；英文技术词（MCP / IVF_FLAT）是原子的
_CJK = re.compile(r"^[一-鿿]+$")


def _cut_stopwords(segment: str) -> list[str]:
    """第二刀：停词当刀。把段里的废话词当分隔符，切出肉块。"""
    parts = [segment]
    for word in sorted(STOPWORDS, key=len, reverse=True):
        parts = [piece for part in parts for piece in part.split(word)]
    return [p for p in parts if p]


def _chunk_terms(chunk: str) -> list[str]:
    """第三刀：短段/非纯中文整留；纯中文长段加滑窗二字块（整段也留，短语命中是最强信号）。"""
    if len(chunk) <= 4 or not _CJK.fullmatch(chunk):
        return [chunk]
    return [chunk] + [chunk[i : i + 2] for i in range(len(chunk) - 1)]


def extract_terms(query: str) -> list[str]:
    """整句查询 → 关键词列表（去重、保持出现顺序）。空查询/全是废话 → 空列表。"""
    terms: list[str] = []
    for segment in _PUNCT.split(query):
        for chunk in _cut_stopwords(segment):
            for term in _chunk_terms(chunk):
                if term not in terms:
                    terms.append(term)
    return terms
