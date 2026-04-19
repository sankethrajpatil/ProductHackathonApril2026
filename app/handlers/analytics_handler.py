"""
Analytics Handler — aiogram router for conversational analytics Q&A.
"""
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from app.core.analytics_agent import AnalyticsAgent
from app.core.security import validate_text

router = Router()
agent = AnalyticsAgent()

@router.message(Command("analytics"))
async def analytics_command(message: Message):
    from app.serverless import ensure_db
    await ensure_db()
    # Extract question from command or prompt user
    text = message.text or ""
    question = text.partition(" ")[2].strip() or None
    if not question:
        await message.reply("Please provide a question, e.g. /analytics How much did we spend on food this month?")
        return
    try:
        question = validate_text(question, max_len=256)
        group_id = message.chat.id
        reply = await agent.answer(group_id, question)
        await message.reply(reply)
    except Exception as e:
        await message.reply(f"Sorry, could not answer: {e}")
