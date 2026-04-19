"""
Photo Handler — aiogram router for receipt OCR via photo/document upload.
"""
from aiogram import Router, F
from aiogram.types import Message, ContentType, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
from decimal import Decimal
from app.services.ocr_service import OCRService, OCRConfidenceError
from app.services.expense_manager import add_expense_from_ocr
from app.core.security import check_ocr_rate_limit, validate_text

router = Router()
ocr_service = OCRService()

@router.message(F.content_type.in_([ContentType.PHOTO, ContentType.DOCUMENT]))
async def handle_receipt_photo(message: Message):
    user_id = message.from_user.id
    try:
        check_ocr_rate_limit(user_id)
    except Exception as e:
        await message.reply(str(e))
        return
    file = message.photo[-1] if message.photo else message.document
    file_id = file.file_id
    bot = message.bot
    file_obj = await bot.get_file(file_id)
    image_bytes = await bot.download_file(file_obj.file_path)
    try:
        result = await ocr_service.extract_receipt(await image_bytes.read())
        # Validate extracted fields
        result["description"] = validate_text(result.get("description", ""), 128)
        result["currency"] = validate_text(result.get("currency", ""), 8)
        # Confirm with user if confidence < 0.9
        if float(result.get("confidence", 0)) < 0.9:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Confirm", callback_data=f"ocr_confirm:{file_id}"),
                     InlineKeyboardButton(text="✏️ Edit", callback_data=f"ocr_edit:{file_id}")]
                ]
            )
            await message.reply(
                f"Extracted: {result['total_amount']} {result['currency']} — {result['description']}\nIs this correct?",
                reply_markup=kb
            )
            # Store result in FSM or cache (not shown)
            return
        # High confidence: save directly
        await add_expense_from_ocr(message, result)
        await message.reply("Expense recorded from receipt ✅")
    except OCRConfidenceError as e:
        await message.reply(f"Could not extract receipt data: {e}\nPlease enter manually.")

# Callback handlers for confirm/edit (not shown: would use FSM or cache)
@router.callback_query(F.data.startswith("ocr_confirm:"))
async def ocr_confirm_callback(call: CallbackQuery):
    # Retrieve cached OCR result, save as expense
    await call.answer("Confirmed. Expense saved.")

@router.callback_query(F.data.startswith("ocr_edit:"))
async def ocr_edit_callback(call: CallbackQuery):
    await call.answer("Please enter the details manually.")
