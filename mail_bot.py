import re
import logging
from collections import OrderedDict

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==========================================
# CONFIGURATION
# ==========================================

TOKEN = "8728921470:AAEwKA3dOLyzwsSS9E8NBfev_IkytqtxmkI"
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
MAX_MESSAGE_LENGTH = 4000

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.WARNING,
)

# ==========================================
# EMAIL EXTRACTION
# ==========================================

EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+"
)

batches = {}


def extract_emails(text):
    """Extract unique email addresses, preserving first-seen order."""
    unique = OrderedDict()

    for match in EMAIL_PATTERN.findall(text):
        email = match.rstrip(".,;:!?)]}>\"'")

        if email and "@" in email:
            unique.setdefault(email.casefold(), email)

    return list(unique.values())


def get_batch(user_id):
    if user_id not in batches:
        batches[user_id] = {
            "emails": OrderedDict(),
            "occurrences": 0,
            "messages": 0,
            "collecting": False,
        }

    return batches[user_id]


def add_to_batch(batch, text):
    matches = EMAIL_PATTERN.findall(text)

    batch["occurrences"] += len(matches)
    batch["messages"] += 1

    for match in matches:
        email = match.rstrip(".,;:!?)]}>\"'")

        if email and "@" in email:
            batch["emails"].setdefault(email.casefold(), email)

    return len(matches)


# ==========================================
# SEND EMAILS AS MESSAGES
# ==========================================

async def send_results(message, emails, occurrences, messages=None):
    """Send only unique email addresses as Telegram messages."""

    if not emails:
        await message.reply_text("No email addresses found.")
        return

    chunks = []
    current_chunk = ""

    for email in emails:
        line = email + "\n"

        if len(current_chunk) + len(line) > MAX_MESSAGE_LENGTH:
            if current_chunk:
                chunks.append(current_chunk.rstrip())

            current_chunk = ""

        current_chunk += line

    if current_chunk:
        chunks.append(current_chunk.rstrip())

    for chunk in chunks:
        await message.reply_text(chunk)


# ==========================================
# COMMANDS
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "UNIQUE EMAIL EXTRACTOR\n\n"
        "Send a message containing email addresses to extract them.\n"
        "Upload a .txt file to process its contents.\n\n"
        "For multiple messages:\n"
        "/collect - Start collecting\n"
        "Forward or send your messages\n"
        "/done - Finish and receive unique emails\n\n"
        "Other commands:\n"
        "/stats - View collection statistics\n"
        "/reset - Clear the current collection"
    )


async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    batches[user_id] = {
        "emails": OrderedDict(),
        "occurrences": 0,
        "messages": 0,
        "collecting": True,
    }

    await update.effective_message.reply_text(
        "Collection started!\n"
        "Forward messages, send email lists, or upload TXT files.\n"
        "Send /done when finished."
    )


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    batch = get_batch(user_id)

    batch["collecting"] = False

    await send_results(
        update.effective_message,
        list(batch["emails"].values()),
        batch["occurrences"],
        batch["messages"],
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    batch = get_batch(update.effective_user.id)

    await update.effective_message.reply_text(
        "COLLECTION STATISTICS\n\n"
        f"Messages/files processed: {batch['messages']}\n"
        f"Email occurrences: {batch['occurrences']}\n"
        f"Unique emails: {len(batch['emails'])}\n"
        f"Collecting: {'Yes' if batch['collecting'] else 'No'}"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    batches[update.effective_user.id] = {
        "emails": OrderedDict(),
        "occurrences": 0,
        "messages": 0,
        "collecting": False,
    }

    await update.effective_message.reply_text(
        "Collection cleared successfully."
    )


# ==========================================
# TEXT MESSAGE HANDLER
# ==========================================

async def process_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user_id = update.effective_user.id
    text = message.text or message.caption or ""

    if not text:
        return

    batch = get_batch(user_id)

    if batch["collecting"]:
        add_to_batch(batch, text)
        return

    emails = extract_emails(text)
    occurrences = len(EMAIL_PATTERN.findall(text))

    await send_results(message, emails, occurrences)


# ==========================================
# TXT FILE HANDLER
# ==========================================

async def process_document(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    user_id = update.effective_user.id
    document = message.document

    if not document:
        return

    if (
        not document.file_name
        or not document.file_name.lower().endswith(".txt")
    ):
        await message.reply_text("Please upload a .txt file.")
        return

    if document.file_size and document.file_size > MAX_FILE_SIZE:
        await message.reply_text("Maximum supported file size is 20 MB.")
        return

    try:
        telegram_file = await document.get_file()
        data = await telegram_file.download_as_bytearray()

        if len(data) > MAX_FILE_SIZE:
            await message.reply_text("Maximum supported file size is 20 MB.")
            return

        content = bytes(data).decode("utf-8-sig", errors="replace")

    except Exception:
        logging.exception("Failed to read uploaded file")
        await message.reply_text(
            "Could not read the file. Please try again."
        )
        return

    batch = get_batch(user_id)

    if batch["collecting"]:
        add_to_batch(batch, content)
        return

    emails = extract_emails(content)
    occurrences = len(EMAIL_PATTERN.findall(content))

    await send_results(message, emails, occurrences)


# ==========================================
# START BOT
# ==========================================

def main():
    if (
        not TOKEN
        or TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE"
    ):
        raise SystemExit(
            "ERROR: Enter your Telegram bot token in the TOKEN variable."
        )

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("collect", collect))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("reset", reset))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            process_text,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Document.ALL,
            process_document,
        )
    )

    print("Unique Email Extractor Bot is running...")

    app.run_polling()


if __name__ == "__main__":
    main()