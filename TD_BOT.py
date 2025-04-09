import os
import tempfile
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from docx import Document
import fitz  # PyMuPDF
import textract
from openai import OpenAI
from fpdf import FPDF  # Для генерации PDF с поддержкой кириллицы
from langdetect import detect_langs

# === Загрузка переменных окружения ===
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ADMIN_ID = int(os.getenv('ADMIN_ID'))

def detect_main_language(text1, text2):
    combined_text = text1 + " " + text2
    langs = detect_langs(combined_text)
    lang_scores = {lang.lang: lang.prob for lang in langs}
    ru_score = lang_scores.get('ru', 0)
    en_score = lang_scores.get('en', 0)
    return 'ru' if ru_score > en_score else 'en'


client = OpenAI(api_key=OPENAI_API_KEY)
user_files = {}
updater = None

# === Извлечение текста ===
def extract_text_from_pdf(file_path):
    doc = fitz.open(file_path)
    return "\n".join([page.get_text() for page in doc])

def extract_text_from_docx(file_path):
    doc = Document(file_path)
    return "\n".join([p.text for p in doc.paragraphs])

def extract_text_from_txt(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

def extract_text_from_doc(file_path):
    return textract.process(file_path).decode('utf-8')

# === GPT-сравнение ===
def ask_openai_to_compare(text1, text2):
    lang = detect_main_language(text1, text2)

    if lang == 'ru':
        prompt = f"""Сравни два технических документа. Выведи список параметров, где:
1. Есть совпадения.
2. Есть различия.
3. Укажи названия параметров, значения в первом и втором документе.
4. Оформи результат в виде таблицы или отчета.

Документ 1:
{text1}

Документ 2:
{text2}
"""
    else:
        prompt = f"""Compare the following two technical documents. Provide a list of:
1. Parameters with similarities.
2. Parameters with differences.
3. Names of the parameters, values in the first and second document.
4. Format the result as a report or table.

Document 1:
{text1}

Document 2:
{text2}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2000
        )
        return response.choices[0].message.content
    except Exception as e:
        raise Exception(f"Error OpenAI: {e}")
    
# === Сохранение в разных форматах ===
def save_docx_from_text(text):
    doc = Document()
    doc.add_heading("Comparative analysis of AI", 0)
    for line in text.splitlines():
        doc.add_paragraph(line)
    result_path = tempfile.NamedTemporaryFile(delete=False, suffix='.docx').name
    doc.save(result_path)
    return result_path

def save_txt_from_text(text):
    path = tempfile.NamedTemporaryFile(delete=False, suffix='.txt').name
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path
# ======================================================================================================
def save_pdf_from_text(text):
    from fpdf import FPDF
    import glob

    path = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf').name
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Абсолютный путь к шрифту, лежащему рядом с TD_BOT.py
    font_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'MyDejaVuSans.ttf'))

    if not os.path.exists(font_path):
        raise FileNotFoundError(f"Font file not found: {font_path}")

    # print(f"Путь к шрифту: {font_path}")
    
    # === Очистка кэша FPDF для этого шрифта ===
    cache_dir = os.path.join(os.path.dirname(font_path), '__pycache__')
    font_base = os.path.splitext(os.path.basename(font_path))[0]

    for ext in ['.pkl', '.afm', '.z']:
        for file in glob.glob(os.path.join(os.path.dirname(font_path), f'{font_base}*{ext}')):
            try:
                os.remove(file)
            except Exception as e:
                print(f"Failed to delete the cache file: {file}: {e}")

    # === Регистрация шрифта ===
    pdf.add_font("MyDejaVu", "", font_path, uni=True)
    pdf.set_font("MyDejaVu", size=12)

    for line in text.splitlines():
        pdf.multi_cell(0, 10, line)

    pdf.output(path)
    return path
# ==================================================================================================
# === Команды Telegram ===
def start(update: Update, context: CallbackContext):
    update.message.reply_text("Hello! Please send two files (PDF, DOCX, DOC, or TXT). First the reference file, then the second one for comparison.")

def stop(update: Update, context: CallbackContext):
    global updater
    user_id = update.message.from_user.id

    if user_id == ADMIN_ID:
        update.message.reply_text("The bot is shutting down.")
        if updater:
            updater.stop()
            updater.is_idle = False
    else:
        update.message.reply_text("You do not have permission to stop the bot.")

# === Обработка файлов ===
def handle_file(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if user_id not in user_files:
        user_files[user_id] = []

    file = update.message.document.get_file()
    file_name = update.message.document.file_name
    file_ext = os.path.splitext(file_name)[1].lower()
    temp_path = tempfile.NamedTemporaryFile(delete=False, suffix=file_ext).name
    file.download(custom_path=temp_path)

    try:
        if file_ext == '.pdf':
            text = extract_text_from_pdf(temp_path)
        elif file_ext == '.docx':
            text = extract_text_from_docx(temp_path)
        elif file_ext == '.doc':
            text = extract_text_from_doc(temp_path)
        elif file_ext == '.txt':
            text = extract_text_from_txt(temp_path)
        else:
            update.message.reply_text("The format is not supported. Please send PDF, DOCX, DOC, or TXT.")
            os.remove(temp_path)
            return
    except Exception as e:
        update.message.reply_text(f"Error reading the file: {e}")
        os.remove(temp_path)
        return

    user_files[user_id].append((temp_path, text))
    update.message.reply_text(f"File {len(user_files[user_id])} received.")

    if len(user_files[user_id]) == 2:
        (_, text1), (_, text2) = user_files[user_id]
        update.message.reply_text("Analyzing documents...")

        try:
            result_text = ask_openai_to_compare(text1, text2)
        except Exception as e:
            update.message.reply_text(str(e))
            return

        update.message.reply_text("Analysis completed. Sending the results in DOCX, PDF, and TXT formats...")

        docx_path = save_docx_from_text(result_text)
        txt_path = save_txt_from_text(result_text)
        pdf_path = save_pdf_from_text(result_text)

        update.message.reply_document(open(docx_path, "rb"), filename="Comparison_AI.docx")
        update.message.reply_document(open(txt_path, "rb"), filename="Comparison_AI.txt")
        update.message.reply_document(open(pdf_path, "rb"), filename="Comparison_AI.pdf")

        # Очистка
        for f, _ in user_files.get(user_id, []):
            os.remove(f)
        for path in [docx_path, txt_path, pdf_path]:
            if os.path.exists(path):
                os.remove(path)

        user_files[user_id] = []

# === Запуск бота ===
def main():
    global updater
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("stop", stop))
    dp.add_handler(MessageHandler(Filters.document, handle_file))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
