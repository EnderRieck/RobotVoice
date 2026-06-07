# coding: utf-8

from __future__ import unicode_literals

import re
import unicodedata

from ros_llm_voice_agent.compat import to_text


_ACRONYM_REPLACEMENTS = (
    (re.compile(r"\bAIUI\b", re.IGNORECASE), "A I U I"),
    (re.compile(r"\bASR\b", re.IGNORECASE), "语音识别"),
    (re.compile(r"\bTTS\b", re.IGNORECASE), "语音合成"),
    (re.compile(r"\bLLM\b", re.IGNORECASE), "大模型"),
    (re.compile(r"\bAPI\b", re.IGNORECASE), "接口"),
    (re.compile(r"\bROS\b", re.IGNORECASE), "R O S"),
    (re.compile(r"\bGPT\b", re.IGNORECASE), "G P T"),
)

_SENTENCE_END_RE = re.compile("[。！？!?；;：:]$")
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")


def sanitize_for_tts(text):
    text = to_text(text).strip()
    if not text:
        return ""

    text = _CODE_FENCE_RE.sub("", text)
    text = _MARKDOWN_LINK_RE.sub(r"\1", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _URL_RE.sub("链接", text)

    for pattern, replacement in _ACRONYM_REPLACEMENTS:
        text = pattern.sub(replacement, text)

    text = _strip_markdown_marks(text)
    text = _normalize_lines(text)
    text = _normalize_symbols(text)
    text = _collapse_spaces_and_punctuation(text)
    return text.strip()


def _strip_markdown_marks(text):
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    text = re.sub(r"(?m)^\s*\d+[\.\)、)]\s*", "", text)
    text = text.replace("**", "")
    text = text.replace("__", "")
    text = text.replace("~~", "")
    text = text.replace("*", "")
    text = text.replace("_", "")
    text = text.replace(">", "")
    text = text.replace("|", "，")
    return text


def _normalize_lines(text):
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not _SENTENCE_END_RE.search(line):
            line += "。"
        lines.append(line)
    return "".join(lines)


def _normalize_symbols(text):
    replacements = {
        "（": "，",
        "）": "，",
        "(": "，",
        ")": "，",
        "[": "，",
        "]": "，",
        "{": "，",
        "}": "，",
        "/": "或",
        "\\": "，",
        "@": " at ",
        "#": "",
        "$": "",
        "^": "",
        "=": "等于",
        "<": "",
        ">": "",
    }
    chars = []
    for ch in text:
        if ch in replacements:
            chars.append(replacements[ch])
            continue
        category = unicodedata.category(ch)
        if category.startswith("C"):
            continue
        if category.startswith("S"):
            chars.append("，")
            continue
        chars.append(ch)
    return "".join(chars)


def _collapse_spaces_and_punctuation(text):
    text = re.sub(r"\s+", " ", text)
    text = re.sub("[,，]{2,}", "，", text)
    text = re.sub("[。]{2,}", "。", text)
    text = re.sub("[；;]{2,}", "；", text)
    text = re.sub("[!?！？]{2,}", "！", text)
    text = re.sub("，。", "。", text)
    text = re.sub("。，", "。", text)
    return text
