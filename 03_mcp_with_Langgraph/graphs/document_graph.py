"""
Document Analysis Pipeline — LangGraph StateGraph
Nodes: segment → extract_entities → score_sentences → readability → action_items → compile
Performs NLP-style analysis using only Python stdlib (no ML libraries required).
"""

import re
from collections import Counter
from typing import TypedDict, List, Optional
from langgraph.graph import StateGraph, START, END

_STOPWORDS = frozenset({
    "the", "a", "an", "is", "in", "it", "of", "and", "to", "for", "that",
    "this", "with", "are", "was", "were", "be", "been", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might",
    "shall", "can", "not", "but", "or", "as", "at", "by", "from", "on", "up",
    "out", "if", "so", "we", "i", "you", "he", "she", "they", "their", "our",
    "your", "my", "its", "which", "who", "what", "how", "when", "where",
    "then", "than", "there", "here", "also", "just", "very", "more", "some",
    "any", "all", "been", "into", "over", "about", "after", "before",
})

_ACTION_RE = re.compile(
    r"\b(?:must|should|need to|will need|requires?|please|ensure|implement|"
    r"review|update|check|verify|confirm|complete|submit|send|create|build|"
    r"fix|test|deploy|schedule|contact|follow[\s-]?up|notify|approve|sign)\b",
    re.IGNORECASE,
)


class DocumentState(TypedDict):
    text: str
    sentences: List[str]
    word_count: int
    word_frequency: dict
    entities: dict
    sentence_scores: List[float]
    key_sentences: List[str]
    readability_score: float
    readability_level: str
    action_items: List[str]
    summary: str
    analysis: str


def segment_text(state: DocumentState) -> dict:
    text = state["text"].strip()

    # Sentence boundary: after . ! ? not followed by a lowercase letter (handles Mr., Dr., etc.)
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z"(\[])', text)
    sentences = [s.strip() for s in parts if len(s.strip()) > 10]

    words = re.findall(r"\b[a-zA-Z]+\b", text.lower())
    content_words = [w for w in words if w not in _STOPWORDS and len(w) > 2]
    freq = dict(Counter(content_words).most_common(40))

    return {"sentences": sentences, "word_count": len(words), "word_frequency": freq}


def extract_entities(state: DocumentState) -> dict:
    text = state["text"]

    emails = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text)
    urls = re.findall(r"https?://[^\s<>\"']+", text)

    # Proper noun phrases: 1-4 consecutive title-cased words
    cap_phrases = re.findall(r"\b(?:[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3})\b", text)
    cap_phrases = [
        p for p in cap_phrases
        if len(p) > 3 and p not in {
            "The", "This", "That", "These", "Those",
            "When", "Where", "What", "Why", "How", "There",
        }
    ]

    # Numbers with optional units
    numbers = re.findall(
        r"\b\d+(?:[.,]\d+)?(?:\s*(?:million|billion|trillion|thousand|percent|%|USD|EUR|GBP|hours?|days?|weeks?|months?|years?))?\b",
        text,
        re.IGNORECASE,
    )

    return {
        "entities": {
            "emails": sorted(set(emails)),
            "urls": sorted(set(urls))[:8],
            "key_phrases": list(dict.fromkeys(cap_phrases))[:20],
            "numbers": list(dict.fromkeys(numbers))[:15],
        }
    }


def score_sentences(state: DocumentState) -> dict:
    sentences = state["sentences"]
    freq = state.get("word_frequency", {})

    if not sentences:
        return {"sentence_scores": [], "key_sentences": []}

    max_freq = max(freq.values(), default=1)
    norm = {w: v / max_freq for w, v in freq.items()}

    scores: List[float] = []
    for sent in sentences:
        words = re.findall(r"\b[a-zA-Z]+\b", sent.lower())
        content = [w for w in words if w not in _STOPWORDS and len(w) > 2]
        base = sum(norm.get(w, 0.0) for w in content) / max(len(content), 1)
        # Boost for sentences with numbers or capitalized content
        if re.search(r"\d+", sent):
            base *= 1.25
        if sum(1 for c in sent if c.isupper()) > 3:
            base *= 1.1
        # Penalize very short or very long sentences
        word_count = len(words)
        if word_count < 5 or word_count > 60:
            base *= 0.7
        scores.append(round(base, 5))

    # Pick top sentences (up to 5), preserving reading order
    n_pick = min(5, max(3, len(sentences) // 5))
    top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n_pick]
    key_sentences = [sentences[i] for i in sorted(top_idx)]

    return {"sentence_scores": scores, "key_sentences": key_sentences}


def analyze_readability(state: DocumentState) -> dict:
    text = state["text"]
    sentences = state.get("sentences", [])
    word_count = state.get("word_count", 0)

    if not sentences or word_count == 0:
        return {"readability_score": 0.0, "readability_level": "Unknown"}

    def syllable_count(word: str) -> int:
        word = word.lower().rstrip(".,!?;:'\"")
        if len(word) <= 3:
            return 1
        count = prev_vowel = 0
        for ch in word:
            is_v = ch in "aeiouy"
            if is_v and not prev_vowel:
                count += 1
            prev_vowel = is_v
        if word.endswith("e") and count > 1:
            count -= 1
        return max(1, count)

    all_words = re.findall(r"\b[a-zA-Z]+\b", text)
    total_syllables = sum(syllable_count(w) for w in all_words)

    wps = word_count / len(sentences)
    spw = total_syllables / max(word_count, 1)
    fre = round(max(0.0, min(100.0, 206.835 - 1.015 * wps - 84.6 * spw)), 1)

    if fre >= 90:
        level = "Very Easy (5th grade)"
    elif fre >= 80:
        level = "Easy (6th grade)"
    elif fre >= 70:
        level = "Fairly Easy (7th grade)"
    elif fre >= 60:
        level = "Standard (8–9th grade)"
    elif fre >= 50:
        level = "Fairly Difficult (10–12th grade)"
    elif fre >= 30:
        level = "Difficult (College level)"
    else:
        level = "Very Complex (Professional/Technical)"

    return {"readability_score": fre, "readability_level": level}


def extract_action_items(state: DocumentState) -> dict:
    sentences = state.get("sentences", [])
    items = [s for s in sentences if _ACTION_RE.search(s)]
    return {"action_items": items[:12]}


def compile_analysis(state: DocumentState) -> dict:
    sentences = state.get("sentences", [])
    word_count = state.get("word_count", 0)
    freq = state.get("word_frequency", {})
    entities = state.get("entities", {})
    key_sentences = state.get("key_sentences", [])
    readability_score = state.get("readability_score", 0.0)
    readability_level = state.get("readability_level", "Unknown")
    action_items = state.get("action_items", [])

    summary = " ".join(key_sentences[:3]) if key_sentences else state["text"][:300] + "..."
    top_keywords = list(freq.keys())[:12]
    avg_words = word_count // max(len(sentences), 1)

    lines = [
        "# Document Analysis Report",
        "",
        "## Statistics",
        f"- **Word count:** {word_count}",
        f"- **Sentence count:** {len(sentences)}",
        f"- **Avg words/sentence:** {avg_words}",
        f"- **Readability (Flesch):** {readability_score}/100 — {readability_level}",
        "",
        "## Auto-Generated Summary",
        summary,
        "",
        "## Key Sentences",
    ]
    for s in key_sentences:
        lines.append(f"- {s}")

    lines += ["", "## Top Keywords"]
    lines.append(", ".join(top_keywords) or "—")

    if entities.get("key_phrases"):
        lines += ["", "## Named Entities & Key Phrases"]
        lines.append(", ".join(entities["key_phrases"][:12]))

    if entities.get("numbers"):
        lines += ["", "## Numbers & Quantities Found"]
        lines.append(", ".join(entities["numbers"][:10]))

    if entities.get("emails"):
        lines += ["", "## Email Addresses"]
        for e in entities["emails"]:
            lines.append(f"- {e}")

    if entities.get("urls"):
        lines += ["", "## URLs"]
        for u in entities["urls"][:5]:
            lines.append(f"- {u}")

    if action_items:
        lines += ["", "## Action Items"]
        for i, item in enumerate(action_items, 1):
            lines.append(f"{i}. {item}")

    return {"summary": summary, "analysis": "\n".join(lines)}


def _build():
    g = StateGraph(DocumentState)
    g.add_node("segment", segment_text)
    g.add_node("entities", extract_entities)
    g.add_node("score_sentences", score_sentences)
    g.add_node("readability", analyze_readability)
    g.add_node("action_items", extract_action_items)
    g.add_node("compile", compile_analysis)

    g.add_edge(START, "segment")
    g.add_edge("segment", "entities")
    g.add_edge("entities", "score_sentences")
    g.add_edge("score_sentences", "readability")
    g.add_edge("readability", "action_items")
    g.add_edge("action_items", "compile")
    g.add_edge("compile", END)
    return g.compile()


compiled = _build()
