#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻洞察卡片校验器。

用法:
    python validate_card.py <卡片文件.md>
    python validate_card.py -                # 从标准输入读
    python validate_card.py <卡片文件.md> --json

退出码:
    0 = 全部通过（可能有 WARN）
    1 = 有 FAIL，必须修改后重跑
    2 = 用法错误 / 文件不存在

只读脚本：不修改任何文件。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

# ------------------------------------------------------------------ 规则

MARKERS = [
    ("title", "【原文标题】"),
    ("core_word", "【1个核心词】"),
    ("summary", "【一句话概括】"),
    ("bullets", "【核心梳理】"),
    ("insight", "【1个洞见】"),
    ("counter", "【1个反直觉洞见】"),
    ("law", "【1个底层规律】"),
]

LABELS = {
    "title": "原文标题",
    "core_word": "1个核心词",
    "summary": "一句话概括",
    "bullets": "核心梳理",
    "insight": "1个洞见",
    "counter": "1个反直觉洞见",
    "law": "1个底层规律",
}

LIMIT_SUMMARY = 40
LIMIT_BULLET = 30
LIMIT_INSIGHT = 35
LIMIT_CORE_WORD_MAX = 8
LIMIT_CORE_WORD_MIN = 2
BULLET_MIN = 2
BULLET_MAX = 4
KEYWORD_MIN = 2
KEYWORD_MAX = 6

BANNED_WORDS = [
    "我觉得", "我认为", "令人", "震撼", "震惊", "不得不说",
    "值得深思", "发人深省", "堪称", "意义重大", "值得关注", "重磅",
]

BULLET_RE = re.compile(r"^(\d+)\s*[.、)]\s*[（(]([^）)]{1,12})[）)]\s*(.+?)\s*$")
PUNCT_RE = re.compile(r"[，。、；：！？‘’“”（）()《》〈〉·—…,.;:!?\"'\[\]{}]")
FOOTER_RE = re.compile(r"^>\s*(原文|来源)")
MARKER_PREFIX = "【"


# ------------------------------------------------------------------ 工具

def count_chars(text: str) -> int:
    """字数 = 非空白字符数（含标点）。"""
    return len(re.sub(r"\s+", "", text or ""))


def parse(text: str):
    """把卡片文本解析成字段字典。缺失的字段为 None。"""
    lines = text.splitlines()
    pos = {}
    for key, marker in MARKERS:
        pos[key] = None
        for i, line in enumerate(lines):
            if line.strip().startswith(marker):
                pos[key] = i
                break

    def scalar(key) -> str | None:
        i = pos[key]
        if i is None:
            return None
        marker = dict(MARKERS)[key]
        value = lines[i].strip()[len(marker):].strip()
        if value:
            return value
        # 内容写在下一行的情况
        for j in range(i + 1, len(lines)):
            nxt = lines[j].strip()
            if not nxt:
                continue
            if nxt.startswith(MARKER_PREFIX):
                return ""
            return nxt
        return ""

    bullets = []
    if pos["bullets"] is not None:
        start = pos["bullets"] + 1
        end = len(lines)
        for key in ("insight", "counter", "law"):
            if pos[key] is not None and pos[key] > pos["bullets"]:
                end = min(end, pos[key])
        for line in lines[start:end]:
            s = line.strip()
            if not s:
                continue
            if s.startswith(MARKER_PREFIX):
                break
            bullets.append(s)

    footer = ""
    for line in lines:
        if FOOTER_RE.match(line.strip()):
            footer = line.strip()
            break

    return {
        "title": scalar("title"),
        "core_word": scalar("core_word"),
        "summary": scalar("summary"),
        "bullets": bullets,
        "insight": scalar("insight"),
        "counter": scalar("counter"),
        "law": scalar("law"),
        "footer": footer,
        "positions": pos,
    }


def check(card) -> list:
    results = []

    def add(status, name, message):
        results.append({"status": status, "check": name, "message": message})

    # 1) 字段齐全 + 顺序
    missing = [LABELS[k] for k, _ in MARKERS if card["positions"][k] is None]
    if missing:
        add("FAIL", "字段齐全", "缺少字段：" + "、".join(missing))
    else:
        order = [card["positions"][k] for k, _ in MARKERS]
        if order != sorted(order):
            add("FAIL", "字段顺序", "七个字段的顺序被打乱了")
        else:
            add("PASS", "字段齐全", "七个字段齐全且顺序正确")

    # 2) 原文标题
    if card["title"] is None:
        pass
    elif not card["title"]:
        add("FAIL", "原文标题", "为空——必须原样保留原文标题")
    else:
        add("PASS", "原文标题", f"{count_chars(card['title'])} 字")

    # 3) 核心词
    if card["core_word"] is not None:
        w = card["core_word"]
        n = count_chars(w)
        problems = []
        if not (LIMIT_CORE_WORD_MIN <= n <= LIMIT_CORE_WORD_MAX):
            problems.append(f"{n} 字（要求 {LIMIT_CORE_WORD_MIN}-{LIMIT_CORE_WORD_MAX} 字）")
        if re.search(r"\s", w):
            problems.append("含空格")
        if PUNCT_RE.search(w):
            problems.append("含标点")
        if problems:
            add("FAIL", "1个核心词", "；".join(problems) + f" → 「{w}」")
        else:
            add("PASS", "1个核心词", f"{n} 字")

    # 4) 一句话概括
    if card["summary"] is not None:
        n = count_chars(card["summary"])
        if n > LIMIT_SUMMARY:
            add("FAIL", "一句话概括", f"{n} 字，超 {n - LIMIT_SUMMARY} 字（上限 {LIMIT_SUMMARY}）")
        elif not card["summary"]:
            add("FAIL", "一句话概括", "为空")
        else:
            add("PASS", "一句话概括", f"{n}/{LIMIT_SUMMARY} 字")

    # 5) 核心梳理
    bullets = card["bullets"]
    if card["positions"]["bullets"] is not None:
        if not (BULLET_MIN <= len(bullets) <= BULLET_MAX):
            add("FAIL", "核心梳理条数", f"{len(bullets)} 条（要求 {BULLET_MIN}-{BULLET_MAX} 条，不硬凑）")
        else:
            add("PASS", "核心梳理条数", f"{len(bullets)} 条")
        for idx, line in enumerate(bullets, 1):
            m = BULLET_RE.match(line)
            if not m:
                add("FAIL", f"核心梳理第{idx}条", f"格式应为「序号.（关键词）内容」→ {line[:30]}")
                continue
            keyword, content = m.group(2), m.group(3)
            kn, cn = count_chars(keyword), count_chars(content)
            problems = []
            if not (KEYWORD_MIN <= kn <= KEYWORD_MAX):
                problems.append(f"关键词 {kn} 字（要求 {KEYWORD_MIN}-{KEYWORD_MAX}）")
            if cn > LIMIT_BULLET:
                problems.append(f"内容 {cn} 字（上限 {LIMIT_BULLET}，超 {cn - LIMIT_BULLET}）")
            if problems:
                add("FAIL", f"核心梳理第{idx}条", "；".join(problems))
            else:
                add("PASS", f"核心梳理第{idx}条", f"内容 {cn}/{LIMIT_BULLET} 字")

    # 6) 三条洞见
    for key, label in (("insight", "1个洞见"), ("counter", "1个反直觉洞见"), ("law", "1个底层规律")):
        value = card[key]
        if value is None:
            continue
        n = count_chars(value)
        if not value:
            add("FAIL", label, "为空")
            continue
        if n > LIMIT_INSIGHT:
            add("FAIL", label, f"{n} 字，超 {n - LIMIT_INSIGHT} 字（上限 {LIMIT_INSIGHT}）")
            continue
        hit = [w for w in BANNED_WORDS if w in value]
        if hit:
            add("FAIL", label, f"{n} 字，但含感想类词：{'、'.join(hit)}")
            continue
        add("PASS", label, f"{n}/{LIMIT_INSIGHT} 字")

    # 7) 底层规律格式（只提示）
    law = card["law"]
    if law and ("——" not in law and "—" not in law):
        add("WARN", "1个底层规律", "建议写成「理论名——一句话解释」")

    # 8) 溯源行（只提示）
    if card["footer"]:
        add("PASS", "溯源行", card["footer"][:60])
    else:
        add("WARN", "溯源行", "缺少「> 原文：<链接>｜<来源>｜<日期>」")

    return results


# ------------------------------------------------------------------ 输出

def render(results: list, source: str) -> str:
    fails = [r for r in results if r["status"] == "FAIL"]
    warns = [r for r in results if r["status"] == "WARN"]
    lines = [f"== 新闻洞察卡片校验 ==", f"来源: {source}", ""]
    icon = {"PASS": " OK ", "FAIL": "FAIL", "WARN": "WARN"}
    for r in results:
        lines.append(f"[{icon[r['status']]}] {r['check']:<14} {r['message']}")
    lines.append("")
    if fails:
        lines.append(f"结论: {len(fails)} 项不合格，{len(warns)} 项提示 —— 改完重跑，不许把没过的卡片交出去。")
    else:
        lines.append(f"结论: 全部通过（{len(warns)} 项提示）—— 可以交付。")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="新闻洞察卡片校验器（只读）")
    parser.add_argument("path", help="卡片文件路径，或 - 表示从标准输入读")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args(argv)

    if args.path == "-":
        text = sys.stdin.read()
        source = "<stdin>"
    else:
        path = os.path.abspath(args.path)
        if not os.path.isfile(path):
            print(f"错误: 文件不存在: {path}", file=sys.stderr)
            return 2
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        source = path

    if not text.strip():
        print("错误: 卡片内容为空", file=sys.stderr)
        return 2

    results = check(parse(text))

    if args.json:
        fails = [r for r in results if r["status"] == "FAIL"]
        print(json.dumps(
            {"source": source, "results": results,
             "fail_count": len(fails),
             "warn_count": sum(1 for r in results if r["status"] == "WARN")},
            ensure_ascii=False, indent=2))
    else:
        print(render(results, source))

    return 1 if any(r["status"] == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
