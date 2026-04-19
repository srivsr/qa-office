"""
Confidence service — shared ACT / REVIEW / PAUSE decision logic.
Used by every LLM agent (A2, A3, A5, A6, A10, A11).
"""

from schemas import AgentDecision


def get_decision(confidence: float, settings) -> AgentDecision:
    """
    Convert confidence float to AgentDecision.

    Returns:
        ACT    — confidence >= act_threshold (0.85 default)
        REVIEW — confidence >= review_threshold (0.60 default)
        PAUSE  — confidence < review_threshold → stop, escalate to A7
    """
    if confidence >= settings.act_threshold:
        return AgentDecision.ACT
    if confidence >= settings.review_threshold:
        return AgentDecision.REVIEW
    return AgentDecision.PAUSE
