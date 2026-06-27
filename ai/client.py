"""
Async wrapper around the Groq SDK.
"""

from groq import AsyncGroq
from config import GROQ_API_KEY, GROQ_MODEL

_groq = AsyncGroq(api_key=GROQ_API_KEY)


async def generate_reply(
    system_prompt: str,
    history: list[dict],
    user_message_wrapped: str,
) -> str:
    """
    Send a request to Groq and return the assistant's reply text.

    Parameters
    ----------
    system_prompt        : built system prompt (base + anchor)
    history              : last N messages as [{"role": ..., "content": ...}]
    user_message_wrapped : XML-tagged user input
    """
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message_wrapped})

    response = await _groq.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=0.7,
        max_tokens=512,
    )
    return response.choices[0].message.content.strip()
