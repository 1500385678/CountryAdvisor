#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
md_to_country_db.py
====================
Phase 0 / Task 0.3  ·  2026-08-26 T2 交付
Phase 0 / Task 0.5  ·  2026-08-29 T2 扩展(parser 覆盖度 2/10 → 10/10 全册)

解析张勇 _CountryLib/ 下的国别知识 md
  - 默认扫 _CountryLib/ 下所有 0X_主题目录(01-10 全册)
  - 也可用 --src 显式指定若干目录
→ 统一结构的 JSON,落地到 data/countries.json

输出结构
---------
{
  "generated_at": "2026-08-26T03:20:00+08:00",
  "source": "01_国家起源与演变,02_国家分支与特点",
  "categories": [            # 从 ### 标题提取的"分支"概念
    {"id": "superpower", "name": "超级大国", "source_section": "二、", "description": "...",
     "representative_countries": ["美国", "中国"], "characteristics": [...]}
  ],
  "country_mentions": {      # 国家 → 出处章节(去重)
    "中国": [{"section": "一、国家大师讲起源", "context": "..."}, ...]
  },
  "tables": [                # 所有抽取到的原始表格(便于人工校对)
    {"section": "一、", "header": [...], "rows": [[...]]}
  ]
}

用法
-----
  python3 scripts/md_to_country_db.py
  python3 scripts/md_to_country_db.py --src ../01_国家起源与演变 --src ../02_国家分支与特点 --out data/countries.json

零外部依赖,纯 stdlib (re/json/pathlib)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# 北京时区
CST = timezone(timedelta(hours=8))

# 国家名常见中→英/简写映射(只列出现有 md 里出现过的)
COUNTRY_ALIASES: dict[str, dict[str, str]] = {
    "美国": {"iso2": "US", "iso3": "USA", "en": "United States"},
    "中国": {"iso2": "CN", "iso3": "CHN", "en": "China"},
    "俄罗斯": {"iso2": "RU", "iso3": "RUS", "en": "Russia"},
    "英国": {"iso2": "GB", "iso3": "GBR", "en": "United Kingdom"},
    "法国": {"iso2": "FR", "iso3": "FRA", "en": "France"},
    "德国": {"iso2": "DE", "iso3": "DEU", "en": "Germany"},
    "日本": {"iso2": "JP", "iso3": "JPN", "en": "Japan"},
    "印度": {"iso2": "IN", "iso3": "IND", "en": "India"},
    "巴西": {"iso2": "BR", "iso3": "BRA", "en": "Brazil"},
    "澳大利亚": {"iso2": "AU", "iso3": "AUS", "en": "Australia"},
    "韩国": {"iso2": "KR", "iso3": "KOR", "en": "South Korea"},
    "新加坡": {"iso2": "SG", "iso3": "SGP", "en": "Singapore"},
    "以色列": {"iso2": "IL", "iso3": "ISR", "en": "Israel"},
    "新西兰": {"iso2": "NZ", "iso3": "NZL", "en": "New Zealand"},
    "沙特阿拉伯": {"iso2": "SA", "iso3": "SAU", "en": "Saudi Arabia"},
    "伊朗": {"iso2": "IR", "iso3": "IRN", "en": "Iran"},
    "梵蒂冈": {"iso2": "VA", "iso3": "VAT", "en": "Vatican City"},
}

# 识别表格中"代表国家"列的关键词
COUNTRY_COL_KEYS = ("代表国家", "代表", "国家")

# ---------- 解析器 ----------

def parse_md(path: Path) -> dict[str, Any]:
    """解析单个 md,返回 {sections: [...], tables: [...], mentions: [...]}"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    sections: list[dict[str, Any]] = []  # {level, title, start_line}
    tables: list[dict[str, Any]] = []    # {section, header, rows, line}
    mentions: list[dict[str, str]] = [] # {country, section, context}

    current_h2 = ""
    current_h3 = ""

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        # 标题
        if stripped.startswith("## ") and not stripped.startswith("### "):
            current_h2 = stripped[3:].strip()
            current_h3 = ""
            sections.append({"level": 2, "title": current_h2, "line": i + 1})
        elif stripped.startswith("### "):
            current_h3 = stripped[4:].strip()
            sections.append({"level": 3, "title": current_h3, "line": i + 1})

        # 表格:以 | 开头,且下一行是分隔符 (---|---|...)
        elif stripped.startswith("|") and i + 1 < n and re.match(r"^\|[\s:|-]+\|?$", lines[i + 1].strip()):
            header_cells = [c.strip() for c in stripped.strip("|").split("|")]
            j = i + 2  # 跳过分隔行
            rows: list[list[str]] = []
            while j < n and lines[j].strip().startswith("|"):
                row_cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                rows.append(row_cells)
                j += 1
            section_label = f"{current_h2} / {current_h3}" if current_h3 else current_h2
            tables.append({
                "section": section_label,
                "header": header_cells,
                "rows": rows,
                "line": i + 1,
            })

            # 抽取"代表国家"列里的国家名
            country_col_idx = None
            for idx, h in enumerate(header_cells):
                if any(k in h for k in COUNTRY_COL_KEYS):
                    country_col_idx = idx
                    break
            if country_col_idx is not None:
                for row in rows:
                    if country_col_idx >= len(row):
                        continue
                    cell = row[country_col_idx]
                    # 拆分:中顿号、逗号、英文逗号、"和"
                    names = re.split(r"[、,,，和]", cell)
                    for nm in names:
                        nm = nm.strip()
                        if not nm:
                            continue
                        # 只在已知别名表里出现的国家计入 mentions
                        if nm in COUNTRY_ALIASES:
                            mentions.append({
                                "country": nm,
                                "iso3": COUNTRY_ALIASES[nm]["iso3"],
                                "section": section_label,
                                "context": " | ".join(row),
                            })
            i = j
            continue

        i += 1

    return {"sections": sections, "tables": tables, "mentions": mentions}


# ---------- 分类器:从 ### 标题和表格推断 category ----------

CATEGORY_PATTERNS = [
    (re.compile(r"超级大国|准超级大国"), "superpower", "超级大国"),
    (re.compile(r"地区大国|区域霸主"), "regional_power", "地区大国"),
    (re.compile(r"中等强国"), "middle_power", "中等强国"),
    (re.compile(r"小国"), "small_state", "小国"),
    (re.compile(r"西方民主制"), "western_democracy", "西方民主制"),
    (re.compile(r"中国模式"), "china_model", "中国模式"),
    (re.compile(r"君主制"), "monarchy", "君主制"),
    (re.compile(r"神权政治"), "theocracy", "神权政治"),
    (re.compile(r"硬实力"), "hard_power", "硬实力"),
    (re.compile(r"软实力"), "soft_power", "软实力"),
    (re.compile(r"巧实力"), "smart_power", "巧实力"),
]


def build_categories(parsed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从所有 ### 标题 和 表格的"分支/类型"列 中识别 category,并附上代表国家。"""
    # 收集所有分类候选
    cat_map: dict[str, dict[str, Any]] = {}
    for p in parsed:
        for sec in p["sections"]:
            if sec["level"] != 3:
                continue
            title = sec["title"]
            for pat, cid, name in CATEGORY_PATTERNS:
                if pat.search(title):
                    if cid not in cat_map:
                        cat_map[cid] = {
                            "id": cid,
                            "name": name,
                            "source_sections": [],
                            "representative_countries": [],
                            "characteristics": [],
                        }
                    if sec["title"] not in cat_map[cid]["source_sections"]:
                        cat_map[cid]["source_sections"].append(sec["title"])
                    break

    # 第二轮:从表格"分支/类型"列里识别 category 名(如"超级大国" / "西方民主制")
    BRANCH_COL_KEYS = ("分支", "类型")
    for p in parsed:
        for tbl in p["tables"]:
            branch_col = None
            for idx, h in enumerate(tbl["header"]):
                if any(k in h for k in BRANCH_COL_KEYS):
                    branch_col = idx
                    break
            if branch_col is None:
                continue
            for row in tbl["rows"]:
                if branch_col >= len(row):
                    continue
                cell = row[branch_col].strip()
                for pat, cid, name in CATEGORY_PATTERNS:
                    if pat.search(cell):
                        if cid not in cat_map:
                            cat_map[cid] = {
                                "id": cid,
                                "name": name,
                                "source_sections": [],
                                "representative_countries": [],
                                "characteristics": [],
                            }
                        section_label = tbl["section"]
                        if section_label not in cat_map[cid]["source_sections"]:
                            cat_map[cid]["source_sections"].append(section_label)
                        break

    # 从 tables 中取代表国家 + 特征
    for p in parsed:
        for tbl in p["tables"]:
            section_label = tbl["section"]
            # 找分类
            matched_cids: list[str] = [
                cid for cid, info in cat_map.items()
                if any(sec in section_label for sec in info["source_sections"])
            ]
            if not matched_cids:
                continue
            # 找"分支/类型"列(用于 row 级精确分类)
            branch_col = None
            for idx, h in enumerate(tbl["header"]):
                if any(k in h for k in ("分支", "类型")):
                    branch_col = idx
                    break
            # 代表国家列
            country_col = None
            for idx, h in enumerate(tbl["header"]):
                if any(k in h for k in COUNTRY_COL_KEYS):
                    country_col = idx
                    break
            # 特征列
            feat_col = None
            for idx, h in enumerate(tbl["header"]):
                if any(k in h for k in ("特征", "特点", "思想", "核心维度", "评估维度")):
                    feat_col = idx
                    break
            for row in tbl["rows"]:
                # row 级别:根据 branch cell 决定这条 row 属于哪些 category
                row_cids: list[str] = []
                if branch_col is not None and branch_col < len(row):
                    branch_cell = row[branch_col]
                    for pat, cid, _ in CATEGORY_PATTERNS:
                        if pat.search(branch_cell):
                            row_cids.append(cid)
                if not row_cids:
                    row_cids = matched_cids  # 兜底:本节所有 category 都吃这条 row
                # 把 row 的代表国家挂到 row_cids
                if country_col is not None and country_col < len(row):
                    for nm in re.split(r"[、,,，和]", row[country_col]):
                        nm = nm.strip()
                        if nm and nm in COUNTRY_ALIASES:
                            for cid in row_cids:
                                if nm not in cat_map[cid]["representative_countries"]:
                                    cat_map[cid]["representative_countries"].append(nm)
                # 把 row 的特征挂到 row_cids
                if feat_col is not None and feat_col < len(row):
                    feat = row[feat_col].strip()
                    if feat:
                        for cid in row_cids:
                            if feat not in cat_map[cid]["characteristics"]:
                                cat_map[cid]["characteristics"].append(feat)

    return list(cat_map.values())


# ---------- 主流程 ----------

def main() -> int:
    ap = argparse.ArgumentParser(description="md → country JSON 抽取器")
    ap.add_argument(
        "--src",
        action="append",
        type=Path,
        help="源 md 所在目录(可多次指定),会扫描 0X_*.md",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "countries.json",
        help="输出 JSON 路径",
    )
    ap.add_argument("--pretty", action="store_true", help="格式化输出(默认紧凑)")

    args = ap.parse_args()

    # 默认源目录:动态扫 _CountryLib/ 下所有 0X_主题目录(覆盖 01-10 全册)
    if not args.src:
        web_root = Path(__file__).resolve().parent.parent
        lib_root = web_root.parent
        # 自动发现:任何以"数字_"开头的子目录都算主题目录
        args.src = sorted(
            d for d in lib_root.iterdir()
            if d.is_dir() and d.name[:3].rstrip("_").isdigit()
        )
        if not args.src:
            # 兜底:显式列 01-10(若 iterdir 因权限/macOS 不可用时)
            args.src = [lib_root / f"{i:02d}_" for i in range(1, 11)]

    # 收集所有 md:glob 模式要能匹配 01_..09_..10_(0* 会漏掉 10_*)
    md_files: list[Path] = []
    for src_dir in args.src:
        if not src_dir.exists():
            print(f"⚠️  目录不存在: {src_dir}", file=sys.stderr)
            continue
        # 匹配数字开头的 md:01_*.md ~ 99_*.md
        for md in sorted(src_dir.glob("[0-9]*.md")):
            md_files.append(md)

    if not md_files:
        print("❌ 未找到任何源 md", file=sys.stderr)
        return 1

    print(f"📂 扫描到 {len(md_files)} 个 md:")
    for m in md_files:
        print(f"   - {m.relative_to(m.parent.parent)}")

    # 解析
    parsed: list[dict[str, Any]] = []
    all_mentions: list[dict[str, str]] = []
    all_tables: list[dict[str, Any]] = []
    for md in md_files:
        p = parse_md(md)
        parsed.append(p)
        all_mentions.extend(p["mentions"])
        for t in p["tables"]:
            t["source_file"] = md.name
            all_tables.append(t)

    # 国家去重
    country_mentions: dict[str, list[dict[str, str]]] = {}
    for m in all_mentions:
        country_mentions.setdefault(m["country"], []).append(
            {k: v for k, v in m.items() if k != "country"}
        )

    # 分类
    categories = build_categories(parsed)

    # 组装输出
    output = {
        "generated_at": datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "schema_version": "0.1",
        "source": [m.name for m in md_files],
        "stats": {
            "sections": sum(len(p["sections"]) for p in parsed),
            "tables": len(all_tables),
            "mentions": len(all_mentions),
            "unique_countries": len(country_mentions),
            "categories": len(categories),
        },
        "categories": categories,
        "country_mentions": country_mentions,
        "country_aliases": COUNTRY_ALIASES,
        "tables": all_tables,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(output, ensure_ascii=False, indent=2 if args.pretty else None),
        encoding="utf-8",
    )

    print()
    print(f"✅ 已生成: {args.out}")
    print(f"   - sections:  {output['stats']['sections']}")
    print(f"   - tables:    {output['stats']['tables']}")
    print(f"   - mentions:  {output['stats']['mentions']}")
    print(f"   - countries: {output['stats']['unique_countries']}")
    print(f"   - categories:{output['stats']['categories']}")
    print()
    print("🌍 识别到的国家:")
    for c, ms in sorted(country_mentions.items()):
        iso3 = ms[0].get("iso3", "??")
        print(f"   - {c} ({iso3})  ·  {len(ms)} 处提及")
    print()
    print("🏷️  分类(branch):")
    for c in categories:
        cn = c["representative_countries"]
        print(f"   - {c['name']:8s}  · 代表: {', '.join(cn) if cn else '(无)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
