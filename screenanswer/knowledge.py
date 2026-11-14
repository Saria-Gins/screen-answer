"""Local knowledge base built from the accompanying study material.

支持的资料格式：

* ``.docx`` —— Word 题库/资料（stdlib 解析，无需额外依赖）
* ``.pdf``  —— 有文本层的 PDF（pypdf）；扫描件自动退回 Windows OCR
* ``.txt`` / ``.md`` —— 纯文本资料

文件夹查找顺序（全部合并，重复条目自动去重）：

1. 程序旁边的 ``know``（打包版 exe 同级目录，方便直接加资料）
2. 源码树里的 ``know``（未打包运行时）
3. PyInstaller 打包进去的 ``know``（``sys._MEIPASS``）

解析结果按文件（大小 + 修改时间）缓存在 ``%APPDATA%\\ScreenAnswer\\kb-cache``，
新增或改动文件只重解析该文件。
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import math
import os
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = (".docx", ".pdf", ".txt", ".md")
CACHE_VERSION = 6
MAX_PDF_PAGES = 600
MAX_OCR_PAGES = 60
MAX_OCR_SECONDS = 150
MAX_OCR_PIXELS = 1700
MAX_FILE_CHARS = 1_500_000
PASSAGE_CHARS = 1200
TEXT_PER_PAGE_FLOOR = 40
UNIQUE_CHARS_PER_PAGE_FLOOR = 150

_WORD_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
}
_QUESTION_START = re.compile(r"^第\s*(\d+)\s*题")
_ANSWER_LINE = re.compile(r"【[^】]*参考答案[^】]*】")
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_ASCII_WORD = re.compile(r"[a-z0-9]+")
_NON_TEXT = re.compile(r"[^0-9a-z\u3400-\u4dbf\u4e00-\u9fff]+")
# 含这些虚词的二字组（的栈、栈和、和队…）几乎不会出现在资料里，
# 算覆盖率时排除，否则自然语句永远匹配不上。
_FILLER_CHARS = set("的了是和与及或就也都而之其把被让从于对为以")
# 题库 PDF 里常见的广告/水印行，混进索引会污染检索结果
_NOISE_LINE = re.compile(
    r"(51jobs|taobao|galerjim|deoffer|offertop|toeekk|eehelp|"
    r"求职工作室|求职教育|笔试包过|代做包过|版权所有|违者必究|"
    r"仅限购买者|客服微信|唯一旺旺)"
)


@dataclass
class KnowledgeEntry:
    source: str
    number: str
    text: str
    question: str
    answer: str
    dedupe_key: str = ""
    token_set: set[str] = field(default_factory=set)
    kind: str = "question"  # "question" or "passage"
    norm_text: str = ""
    ascii_words: set[str] = field(default_factory=set)


@dataclass
class KnowledgeStats:
    files: int = 0
    entries: int = 0
    chars: int = 0
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if not self.files:
            return "未找到知识库文件"
        text = f"已加载 {self.files} 个文件 / {self.entries} 条资料"
        if self.skipped:
            text += f"（{len(self.skipped)} 个无文本层已跳过）"
        if self.errors:
            text += f"（{len(self.errors)} 个文件读取失败）"
        return text


def _knowledge_roots() -> list[Path]:
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent / "know")
    else:
        roots.append(Path(__file__).resolve().parent.parent / "know")
    bundle = getattr(sys, "_MEIPASS", "")
    if bundle:
        roots.append(Path(bundle) / "know")
    return roots


def _is_doc_only(path: Path) -> bool:
    """README/说明 这类说明文件不当作资料。"""
    stem = path.stem.strip().lower()
    return stem == "readme" or stem.startswith("_") or stem in {"说明", "资料说明"}


def find_knowledge_dirs() -> list[Path]:
    """Every existing folder that contains at least one supported file."""
    found: list[Path] = []
    for root in _knowledge_roots():
        try:
            if not root.is_dir():
                continue
            if any(
                path.suffix.lower() in SUPPORTED_SUFFIXES
                for path in root.iterdir()
                if path.is_file()
            ):
                found.append(root)
        except OSError:
            continue
    return found


def find_knowledge_dir() -> Path | None:
    """Backwards compatible single-folder helper."""
    dirs = find_knowledge_dirs()
    return dirs[0] if dirs else None


# --------------------------------------------------------------------- parsing
def _extract_docx(path: Path) -> list[str]:
    """Extract paragraphs and tables from a .docx using only stdlib."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    body = root.find("w:body", _WORD_NS)
    if body is None:
        return []
    paragraphs: list[str] = []
    for node in body:
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = "".join(
                part.text or "" for part in node.findall(".//w:t", _WORD_NS)
            ).strip()
            if text:
                paragraphs.append(text)
        elif tag == "tbl":
            rows: list[str] = []
            for row in node.findall("w:tr", _WORD_NS):
                cells = []
                for cell in row.findall("w:tc", _WORD_NS):
                    value = "".join(
                        part.text or ""
                        for part in cell.findall(".//w:t", _WORD_NS)
                    ).strip()
                    cells.append(value)
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                paragraphs.extend(rows)
    return paragraphs


def _extract_pdf(path: Path) -> tuple[list[str], str]:
    """Return (paragraphs, skip_reason).

    有文本层的 PDF 直接抽取；文本层稀薄（扫描件、只有水印）时退回 Windows OCR，
    页数上限 ``MAX_OCR_PAGES``，结果进缓存，只在第一次索引时付出代价。
    """
    paragraphs: list[str] = []
    total = 0
    pages = 0
    try:
        from pypdf import PdfReader  # 延迟导入：没装也不影响其它格式
    except Exception:
        logger.warning("pypdf 未安装，跳过 %s", path.name)
        return [], "缺少 pypdf 依赖"
    try:
        reader = PdfReader(str(path))
        pages = len(reader.pages)
        for index, page in enumerate(reader.pages):
            if index >= MAX_PDF_PAGES or total >= MAX_FILE_CHARS:
                break
            try:
                text = page.extract_text() or ""
            except Exception:
                logger.debug("PDF page extraction failed: %s p%s", path.name, index + 1)
                continue
            for line in text.splitlines():
                line = line.strip()
                if line:
                    paragraphs.append(line)
                    total += len(line)
    except Exception:
        logger.exception("Could not open PDF %s", path.name)

    if pages:
        unique_chars = sum(len(line) for line in set(paragraphs))
        rich_text = (
            total / pages >= TEXT_PER_PAGE_FLOOR
            and unique_chars / pages >= UNIQUE_CHARS_PER_PAGE_FLOOR
        )
        if rich_text:
            return paragraphs, ""
    if not pages:
        return [], "PDF 无法打开"

    ocr_paragraphs, reason = _ocr_pdf(path, pages)
    if ocr_paragraphs:
        logger.info("OCR fallback: %s -> %d 段", path.name, len(ocr_paragraphs))
        return ocr_paragraphs, ""
    if paragraphs:
        logger.warning("%s 文本层稀疏且 OCR 不可用（%s），按已有文本索引", path.name, reason)
        return paragraphs, ""
    return [], reason or "扫描件/无文本层"


def _ocr_pdf(path: Path, pages: int) -> tuple[list[str], str]:
    """Render scanned PDF pages and OCR them with the Windows engine.

    扫描件往往分辨率离谱，按“最长边约 MAX_OCR_PIXELS”决定渲染倍率；
    整份文件最多花 MAX_OCR_SECONDS 秒，超时就先索引已识别的部分。
    """
    try:
        import pypdfium2 as pdfium  # 可选依赖
    except Exception:
        return [], "缺少 pypdfium2（无法 OCR 扫描件）"
    try:
        from .ocr import recognize_image
    except Exception:
        return [], "OCR 模块不可用"
    import tempfile
    import time

    paragraphs: list[str] = []
    limit = min(pages, MAX_OCR_PAGES)
    deadline = time.monotonic() + MAX_OCR_SECONDS
    document = None
    ocr_pages = 0
    try:
        document = pdfium.PdfDocument(str(path))
        for index in range(limit):
            if time.monotonic() > deadline:
                logger.info("%s 扫描件 OCR 超时，先索引前 %d 页", path.name, index)
                break
            try:
                page = document[index]
                width, height = page.get_size()
                longest = max(width, height) or 1.0
                scale = max(1.0, min(2.0, MAX_OCR_PIXELS / longest))
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil().convert("RGB")
            except Exception:
                continue
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    suffix=".png", delete=False
                ) as handle:
                    temp_path = Path(handle.name)
                image.save(temp_path)
                result = recognize_image(temp_path)
                if result.error:
                    logger.debug(
                        "OCR page %s of %s failed: %s",
                        index + 1,
                        path.name,
                        result.error,
                    )
                    continue
                ocr_pages += 1
                for line in result.text.splitlines():
                    line = line.strip()
                    if line:
                        paragraphs.append(line)
            finally:
                if temp_path is not None:
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
            if ocr_pages and ocr_pages % 10 == 0:
                logger.info("OCR %s: 已完成 %d 页", path.name, ocr_pages)
    finally:
        if document is not None:
            try:
                document.close()
            except Exception:
                pass
    if limit < pages:
        logger.info("%s 扫描件只 OCR 了前 %d/%d 页", path.name, limit, pages)
    return paragraphs, ""


def _extract_text_file(path: Path) -> list[str]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "replace")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _read_paragraphs(path: Path) -> tuple[list[str], str]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _extract_docx(path), ""
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix in (".txt", ".md"):
        return _extract_text_file(path), ""
    return [], "不支持的格式"


# ------------------------------------------------------------------- chunking
def _question_blocks(paragraphs: list[str]) -> list[list[str]]:
    starts = [
        index
        for index, line in enumerate(paragraphs)
        if _QUESTION_START.match(line)
    ]
    blocks: list[list[str]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(paragraphs)
        block = paragraphs[start:end]
        if any(_ANSWER_LINE.search(line) for line in block):
            blocks.append(block)
    return blocks


def _passage_chunks(paragraphs: list[str]) -> list[str]:
    """把没有题目结构的资料按段落切成可检索的片段。"""
    chunks: list[str] = []
    buffer: list[str] = []
    size = 0
    for line in paragraphs:
        if size + len(line) > PASSAGE_CHARS and buffer:
            chunks.append("\n".join(buffer))
            buffer = []
            size = 0
        buffer.append(line)
        size += len(line) + 1
    if buffer:
        chunks.append("\n".join(buffer))
    return chunks


def _tokens(text: str) -> set[str]:
    text = text.lower()
    tokens: set[str] = set()
    for run in _CJK_RUN.findall(text):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[i : i + 2] for i in range(len(run) - 1))
    tokens.update(_ASCII_WORD.findall(text))
    return tokens


def _informative(tokens: set[str]) -> set[str]:
    informative = {
        token
        for token in tokens
        if len(token) > 1
        and token[0] not in _FILLER_CHARS
        and token[1] not in _FILLER_CHARS
    }
    return informative or tokens


def _normalise(text: str) -> str:
    return _NON_TEXT.sub("", text.lower())


def _question_stem(question: str) -> str:
    """Question text without its number and answer options."""
    lines = []
    for line in question.splitlines():
        if re.match(r"^[A-DＡ-Ｄ][\.．、]", line.strip()):
            break
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"^第\s*\d+\s*题[.．、]?\s*", "", text)
    return _normalise(text)


def _query_trigrams(text: str) -> set[str]:
    """查询里的 CJK 三字组：比二字组稳得多，几乎不会误命中。"""
    grams: set[str] = set()
    for run in _CJK_RUN.findall(_normalise(text)):
        if len(run) < 3:
            continue
        for index in range(len(run) - 2):
            grams.add(run[index : index + 3])
    return grams


def _query_ascii_words(text: str) -> set[str]:
    return {word for word in _ASCII_WORD.findall(text.lower()) if len(word) >= 5}


def _entry_ascii_words(text: str) -> set[str]:
    return set(_ASCII_WORD.findall(text.lower()))


# ----------------------------------------------------------------------- cache
def _cache_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home())) / "ScreenAnswer"
    return base / "kb-cache"


def _cache_path(path: Path) -> Path:
    stat = path.stat()
    key = f"{path.name}|{stat.st_size}|{int(stat.st_mtime)}|{CACHE_VERSION}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return _cache_dir() / f"{digest}.json.gz"


def _load_cached_paragraphs(path: Path) -> tuple[list[str], str] | None:
    cache = _cache_path(path)
    try:
        if not cache.is_file():
            return None
        payload = json.loads(gzip.decompress(cache.read_bytes()).decode("utf-8"))
        if payload.get("version") != CACHE_VERSION:
            return None
        return list(payload.get("paragraphs") or []), str(payload.get("skip") or "")
    except Exception:
        logger.debug("Cache read failed for %s", path.name, exc_info=True)
        return None


def _store_cached_paragraphs(path: Path, paragraphs: list[str], skip: str) -> None:
    try:
        cache = _cache_path(path)
        cache.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"version": CACHE_VERSION, "paragraphs": paragraphs, "skip": skip},
            ensure_ascii=False,
        ).encode("utf-8")
        temp = cache.with_suffix(".tmp")
        temp.write_bytes(gzip.compress(payload, 6))
        os.replace(temp, cache)
    except Exception:
        logger.debug("Cache write failed for %s", path.name, exc_info=True)


def _paragraphs_for(path: Path) -> tuple[list[str], str]:
    cached = _load_cached_paragraphs(path)
    if cached is not None:
        return cached
    paragraphs, skip = _read_paragraphs(path)
    _store_cached_paragraphs(path, paragraphs, skip)
    return paragraphs, skip


def clear_cache() -> int:
    removed = 0
    directory = _cache_dir()
    if not directory.is_dir():
        return 0
    for item in directory.glob("*.json.gz"):
        try:
            item.unlink()
            removed += 1
        except OSError:
            continue
    return removed


# ------------------------------------------------------------------------- API
class KnowledgeBase:
    def __init__(self, directory: Path | None = None):
        if directory is not None:
            self.directories = [directory]
        else:
            self.directories = find_knowledge_dirs()
        self.entries: list[KnowledgeEntry] = []
        self.stats = KnowledgeStats()
        self._df: dict[str, int] = {}
        self._idf: dict[str, float] = {}

    @property
    def directory(self) -> Path | None:
        return self.directories[0] if self.directories else None

    @property
    def available(self) -> bool:
        return bool(self.entries)

    def _iter_files(self):
        seen: set[str] = set()
        for directory in self.directories:
            try:
                files = sorted(
                    path
                    for path in directory.iterdir()
                    if path.is_file()
                    and path.suffix.lower() in SUPPORTED_SUFFIXES
                    and not _is_doc_only(path)
                )
            except OSError:
                continue
            for path in files:
                key = path.name.lower()
                if key in seen:
                    continue
                seen.add(key)
                yield path

    def _build_entries(self, path: Path, paragraphs: list[str]) -> list[KnowledgeEntry]:
        entries: list[KnowledgeEntry] = []
        cleaned = [
            line
            for line in paragraphs
            if len(line.strip()) >= 2 and not _NOISE_LINE.search(line)
        ]
        paragraphs = cleaned or paragraphs
        blocks = _question_blocks(paragraphs)
        if blocks:
            for block in blocks:
                text = "\n".join(block).strip()
                if not text:
                    continue
                match = _QUESTION_START.match(block[0])
                number = match.group(1) if match else ""
                answer_index = next(
                    (
                        index
                        for index, line in enumerate(block)
                        if _ANSWER_LINE.search(line)
                    ),
                    None,
                )
                if answer_index is None:
                    continue
                question = "\n".join(block[:answer_index]).strip()
                answer = "\n".join(block[answer_index:]).strip()
                entries.append(
                    KnowledgeEntry(
                        source=path.stem,
                        number=number,
                        text=text,
                        question=question,
                        answer=answer,
                        dedupe_key=_question_stem(question),
                        kind="question",
                    )
                )
            return entries
        # 没有题目结构：当作参考资料按段落切块，也能被检索到
        for chunk in _passage_chunks(paragraphs):
            chunk = chunk.strip()
            if len(chunk) < 40:
                continue
            entries.append(
                KnowledgeEntry(
                    source=path.stem,
                    number="",
                    text=chunk,
                    question=chunk,
                    answer="",
                    dedupe_key=_normalise(chunk)[:160],
                    kind="passage",
                )
            )
        return entries

    def load(self) -> KnowledgeStats:
        self.entries = []
        self._df = {}
        self._idf = {}
        stats = KnowledgeStats()
        seen_content: set[tuple[str, str]] = set()
        for path in self._iter_files():
            try:
                paragraphs, skip = _paragraphs_for(path)
                if skip:
                    stats.skipped.append(f"{path.name}（{skip}）")
                    logger.warning("Skipped %s: %s", path.name, skip)
                    continue
                if not paragraphs:
                    stats.errors.append(path.name)
                    continue
                file_entries = self._build_entries(path, paragraphs)
                if not file_entries:
                    stats.errors.append(path.name)
                    logger.warning("No usable content found in %s", path.name)
                    continue
                stats.files += 1
                for entry in file_entries:
                    key = (entry.dedupe_key, _normalise(entry.answer)[:80])
                    if key in seen_content:
                        continue
                    seen_content.add(key)
                    entry.token_set = _tokens(entry.question + "\n" + entry.answer)
                    self.entries.append(entry)
                    stats.chars += len(entry.text)
            except Exception:
                logger.exception("Could not read knowledge file %s", path.name)
                stats.errors.append(path.name)
        stats.entries = len(self.entries)
        for entry in self.entries:
            for token in entry.token_set:
                self._df[token] = self._df.get(token, 0) + 1
        count = max(1, len(self.entries))
        self._idf = {
            token: math.log((count + 1) / (frequency + 0.5))
            for token, frequency in self._df.items()
        }
        self.stats = stats
        logger.info(
            "Knowledge base: %s (dirs=%s)",
            stats.summary,
            ", ".join(str(d) for d in self.directories) or "-",
        )
        return stats

    def _query_idf_total(self, query_tokens: set[str]) -> float:
        """查询里所有 token 的 IDF 总和；语料里没有的词按偏高分计。"""
        unknown = math.log(max(2, len(self.entries)) + 1) * 0.6
        total = sum(self._idf.get(token, unknown) for token in query_tokens)
        return total or 1.0

    def _score(
        self,
        entry: KnowledgeEntry,
        query_tokens: set[str],
        query_norm: str,
        total_idf: float,
    ) -> tuple[float, float, bool]:
        """Return (score, query coverage, exact phrase hit)."""
        if not query_tokens:
            return 0.0, 0.0, False
        overlap = query_tokens & entry.token_set
        if not overlap:
            return 0.0, 0.0, False
        idf_sum = sum(self._idf.get(token, 0.0) for token in overlap)
        coverage = len(overlap) / max(1, len(query_tokens))
        relevance = idf_sum / total_idf
        question_key = _normalise(entry.question)[:45]
        exact = len(question_key) >= 10 and question_key in query_norm
        if not exact and entry.dedupe_key and len(entry.dedupe_key) >= 6:
            # 题干（去掉题号和选项）整体出现，也算命中，覆盖纯数字题
            exact = entry.dedupe_key in query_norm

        if entry.kind == "passage":
            # 粗筛，真正的精度由 search() 里的“三字组短语证据”把关
            if not exact and (relevance < 0.15 or coverage < 0.15):
                return 0.0, coverage, exact
            length_norm = 1.0 + math.log(1.0 + len(entry.token_set) / 60.0)
            score = (idf_sum / length_norm) * (0.5 + coverage)
            if exact:
                score += 3.0
            return score * 0.85, coverage, exact

        if not exact and relevance < 0.15:
            return 0.0, coverage, exact
        score = idf_sum / math.sqrt(max(1, len(entry.token_set)))
        if exact:
            score += 40.0
        return score, coverage, exact

    def search(self, query: str, limit: int = 4) -> list[KnowledgeEntry]:
        if not self.entries or not query.strip():
            return []
        query_norm = _normalise(query)
        query_tokens = _informative(_tokens(query[:14000]))
        total_idf = self._query_idf_total(query_tokens)
        trigrams = _query_trigrams(query)
        ascii_words = _query_ascii_words(query)
        scored: list[tuple[int, float, KnowledgeEntry]] = []
        for entry in self.entries:
            score, _coverage, exact = self._score(
                entry, query_tokens, query_norm, total_idf
            )
            if score <= 0:
                continue
            phrase_hits = 0
            if not exact:
                if not entry.norm_text:
                    entry.norm_text = _normalise(entry.text)
                phrase_hits = sum(1 for gram in trigrams if gram in entry.norm_text)
                if not phrase_hits and ascii_words:
                    if not entry.ascii_words:
                        entry.ascii_words = _entry_ascii_words(entry.text)
                    phrase_hits = len(ascii_words & entry.ascii_words)
                if not phrase_hits:
                    continue
            scored.append((phrase_hits, score, entry))
        if not scored:
            return []
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        best = max(item[1] for item in scored)
        floor = max(0.6, best * 0.55)
        matches: list[KnowledgeEntry] = []
        seen_stems: set[str] = set()
        for phrase_hits, score, entry in scored:
            if score < floor and phrase_hits < 3:
                continue
            key = entry.dedupe_key or _normalise(entry.question)
            if key in seen_stems:
                continue
            seen_stems.add(key)
            matches.append(entry)
            if len(matches) >= limit:
                break
        return matches

    def build_context(
        self,
        query: str,
        limit: int = 4,
        max_chars: int = 7000,
    ) -> str:
        matches = self.search(query, limit=limit)
        if not matches:
            return ""
        parts = [
            "以下是从本地题库/资料库检索到的可能相关资料。"
            "请先判断是否与屏幕题目匹配；匹配时优先参考，"
            "不匹配时以屏幕内容为准，不要生搬硬套。"
        ]
        used = 0
        for index, entry in enumerate(matches, start=1):
            body = entry.text
            if len(body) > 2200:
                body = body[:2200].rstrip() + "\n[资料过长已截断]"
            label = "题库" if entry.kind == "question" else "资料"
            block = f"[资料 {index}｜{label}｜来源：{entry.source}]\n{body}"
            if used + len(block) > max_chars:
                break
            parts.append(block)
            used += len(block)
        return "\n\n".join(parts) if len(parts) > 1 else ""
