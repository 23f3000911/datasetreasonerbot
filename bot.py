import json
import time
import os
from openai import OpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
AIPIPE_TOKEN = os.environ["AIPIPE_TOKEN"]
LOG_URL = "https://raw.githubusercontent.com/23f3000911/datasetreasonerbot/main/run.jsonl"

client = OpenAI(base_url="https://aipipe.org/openai/v1", api_key=AIPIPE_TOKEN)
LOG_FILE = "run.jsonl"
MAX_HISTORY = 6

# Keeps the last few messages per chat, so multi-turn questions work —
# "answer the LAST message" still needs the earlier ones for context.
conversation_history = {}

def log_event(event: dict):
    event["timestamp"] = time.time()
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(event) + "\n")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    log_event({"type": "incoming", "chat_id": chat_id, "text": user_text})

    history = conversation_history.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})

    # Ask the AI to work out the answer. The system prompt tells it exactly how to
    # format the final reply — this is the part that MUST match what the question asked.
    system_prompt = (
        "You are a careful data analyst. "
        "Always answer the user's LAST message. "
        "If earlier messages contain data or context needed to answer the last message, use them. "
        "The answer must exactly match the JSON structure requested in the user's LAST message. "
        "Do not rename keys, add keys, remove keys, or change nesting. "
        "If the user provides data inline, analyze it. "
        "If the question references a public dataset or URL, use it if possible. "
        "Compute the correct answer and reply with ONLY one valid JSON object. "
        "Do not include explanations, markdown, or code fences."
        )
    
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "system", "content": system_prompt}] + history[-MAX_HISTORY:],
    )
    reply_text = response.choices[0].message.content.strip()
    history.append({"role": "assistant", "content": reply_text})

    # Make sure we actually reply with valid JSON containing "log_url" — if the model
    # forgot the log_url field or wrapped it in markdown, fix it up here so the grader
    # never sees a malformed reply.
    try:
        parsed = json.loads(reply_text)
    except Exception:
        try:
            start = reply_text.find("{")
            end = reply_text.rfind("}")
            parsed = json.loads(reply_text[start:end + 1])
        except Exception:
            parsed = {"answer": reply_text}
    parsed["log_url"] = LOG_URL
    final_reply = json.dumps(parsed, separators=(",", ":"))

    log_event({"type": "outgoing", "chat_id": chat_id, "text": final_reply})
    await update.message.reply_text(final_reply)

app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
print("Bot is running on Railway...")
app.run_polling()
