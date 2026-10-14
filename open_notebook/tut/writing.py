"""Writing discipline applied to everything Tut Agent writes in MCIT AI.

Two rule packs, both MIT licensed (full originals in ``skills_reference/``):
  * no-ai-slop  - https://github.com/petergyang/no-ai-slop (Peter Yang)
  * humanizer   - https://github.com/blader/humanizer (Siqi Chen)

Compact digests are injected because local models have small context windows.
Custom skills are managed in Tut Agent itself.
"""

RULES = {
    "no-ai-slop": (
        "Lead with the point. Be concrete: names, numbers, dates and mechanisms beat abstractions. "
        "Every sentence must add something; cut throat-clearing, filler and empty qualifiers. "
        "Use active voice and direct verbs ('decided', not 'made a decision'). "
        "Apply the portability test: a sentence that would fit any other organisation or topic is filler. "
        "Show with facts instead of telling the reader something is important. Never invent facts."
    ),
    "humanizer": (
        "Avoid these AI tells: 'not X but Y' contrasts; one-line dramatic closers; 'the real question is', "
        "'at its core'; run-ups like 'let's dive in', 'here's what you need to know'; forced groups of three; "
        "em dashes (use commas, colons or periods); stacked hedges; the words delve, crucial, pivotal, robust, "
        "seamless, landscape, tapestry, testament, showcase, underscore, vibrant, meticulous, enhance, leverage; "
        "inflated significance ('marks a pivotal moment', 'the future looks bright'); sales language; "
        "'serves as' or 'boasts' instead of 'is' or 'has'; bold labels and Title Case headings; emojis; "
        "chatbot residue ('Great question', 'I hope this helps', 'Let me know'). "
        "Write headings in sentence case. Vary sentence length."
    ),
}

MAX_INJECTED_CHARS = 3200


def compact_writing_rules() -> str:
    text = "Writing rules you must follow:\n" + "\n".join(
        f"[{k}] {v}" for k, v in RULES.items()
    )
    return text[:MAX_INJECTED_CHARS]
