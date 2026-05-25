import logging
import os

from dotenv import load_dotenv
from telegram.error import NetworkError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes
from telegram import Update

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

import db
from handlers.add import add_handler
from handlers.balance import (
    balance_handler,
    paid_handler,
    settle_callback,
    settle_cancel_callback,
    settle_confirm_callback,
)
from handlers.history import (
    delete_callback,
    delete_cancel_callback,
    delete_confirm_callback,
    history_handler,
)
from handlers.members import addmember_handler, currency_handler, members_handler
from handlers.misc import help_handler, start_handler


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, NetworkError):
        logger.warning("Network hiccup (auto-retry): %s", context.error)
    else:
        logger.exception("Unhandled error", exc_info=context.error)


def main():
    db.init_db()

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN not set — copy .env.example to .env and fill it in")

    app = Application.builder().token(token).build()

    # ConversationHandler must be registered before generic handlers
    app.add_handler(add_handler)

    # Commands
    app.add_handler(CommandHandler("start",    start_handler))
    app.add_handler(CommandHandler("help",     help_handler))
    app.add_handler(CommandHandler("balance",  balance_handler))
    app.add_handler(CommandHandler("history",  history_handler))
    app.add_handler(CommandHandler("members",   members_handler))
    app.add_handler(CommandHandler("addmember", addmember_handler))
    app.add_handler(CommandHandler("currency",  currency_handler))
    app.add_handler(CommandHandler("paid",     paid_handler))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(settle_callback,         pattern=r"^settle:"))
    app.add_handler(CallbackQueryHandler(settle_confirm_callback, pattern=r"^settleok:"))
    app.add_handler(CallbackQueryHandler(settle_cancel_callback,  pattern=r"^settlecancel$"))
    app.add_handler(CallbackQueryHandler(delete_callback,         pattern=r"^del:"))
    app.add_handler(CallbackQueryHandler(delete_confirm_callback, pattern=r"^delok:"))
    app.add_handler(CallbackQueryHandler(delete_cancel_callback,  pattern=r"^delcancel$"))

    app.add_error_handler(error_handler)

    logger.info("🌱 SplitTwig is running")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
