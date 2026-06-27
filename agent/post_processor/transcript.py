import re


def _message_content(msg: dict) -> str:
    content = msg.get("content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
                elif "text" in part:
                    parts.append(str(part["text"]))
            elif isinstance(part, str):
                parts.append(part)
        return " ".join(p for p in parts if p).strip()
    return str(content).strip() if content else ""


def messages_to_transcript(messages: list[dict]) -> str:
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "")
        content = _message_content(msg)
        if not content:
            continue
        if role == "user":
            lines.append(f"User: {content}")
        elif role in ("assistant", "model"):
            lines.append(f"Agent: {content}")
    return "\n".join(lines)


def normalize_conversation_tags(conversation: str) -> str:
    lines = conversation.split("\n")
    normalized: list[str] = []
    agent_pattern = re.compile(
        r"^(?:Sarah\s*\(Agent\)|Agent\s*\([^)]*\)|Sarah|Agent)\s*:\s*(.*)$",
        re.IGNORECASE,
    )
    user_pattern = re.compile(r"^User\s*:\s*(.*)$", re.IGNORECASE)

    for line in lines:
        agent_match = agent_pattern.match(line)
        if agent_match:
            normalized.append(f"Agent: {agent_match.group(1)}")
            continue
        user_match = user_pattern.match(line)
        if user_match:
            normalized.append(f"User: {user_match.group(1)}")
        else:
            normalized.append(line)
    return "\n".join(normalized)
