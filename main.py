import os
import logging
import asyncio
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import sqlite3
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
# 🔐 КОНФИГУРАЦИЯ - ТОКЕН БОТА
# ВСТАВЬТЕ ВАШ ТОКЕН МЕЖДУ КАВЫЧЕК 👇
BOT_TOKEN = "8381749720:AAFi1jCnmNp8DGQiFX0zjwNf6IK__lPJFPY"

class NeuroMentorDB:
    def __init__(self):
        self.conn = sqlite3.connect('neuro_knowledge.db', check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        with self.conn:
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS knowledge (
                    id INTEGER PRIMARY KEY,
                    category TEXT,
                    question TEXT,
                    answer TEXT,
                    created_at TIMESTAMP
                )
            ''')
    
    def add_knowledge(self, category, question, answer):
        with self.conn:
            self.conn.execute(
                'INSERT INTO knowledge (category, question, answer, created_at) VALUES (?, ?, ?, ?)',
                (category, question, answer, datetime.now())
            )
    
    def get_knowledge(self, category=None):
        cursor = self.conn.cursor()
        if category:
            cursor.execute('SELECT * FROM knowledge WHERE category = ?', (category,))
        else:
            cursor.execute('SELECT * FROM knowledge')
        return cursor.fetchall()
    
    def find_answer(self, question):
        cursor = self.conn.cursor()
        cursor.execute('SELECT answer, category FROM knowledge WHERE question LIKE ?', 
                      (f'%{question}%',))
        return cursor.fetchone()

db = NeuroMentorDB()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [
        ['/learn', '/knowledge'],
        ['/help', '/status']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    welcome_text = f"""
🧠 *Добро пожаловать в NeuroMentorAI*, {user.first_name}!

*Я ваш персональный AI-наставник!*

📚 *Доступные команды:*
/learn - Обучить меня новому
/knowledge - Просмотреть знания
/status - Статус системы
/help - Помощь

*Просто напишите вопрос, и я постараюсь ответить!*
    """
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def learn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("""
📖 *Формат обучения:*
/learn [категория] [вопрос] | [ответ]

*Пример:*
/learn python "как создать функцию" | "def my_func(): pass"
/learn math "теорема Пифагора" | "a² + b² = c²"
        """, parse_mode='Markdown')
        return
    
    try:
        args = " ".join(context.args)
        if "|" not in args:
            await update.message.reply_text("Используйте | для разделения вопроса и ответа")
            return
        
        parts = args.split("|", 1)
        category_part = parts[0].strip().split(" ", 1)
        
        if len(category_part) < 2:
            await update.message.reply_text("Укажите категорию и вопрос")
            return
        
        category = category_part[0].lower()
        question = category_part[1].strip().strip('"\'')
        answer = parts[1].strip().strip('"\'')
        
        db.add_knowledge(category, question, answer)
        
        await update.message.reply_text(f"""
✅ *Знание добавлено!*

*Категория:* {category}
*Вопрос:* {question}
*Ответ:* {answer}

*Теперь я это запомнил!*
        """, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def knowledge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        category = " ".join(context.args).lower()
        knowledge = db.get_knowledge(category)
        title = f"знания в категории '{category}'"
    else:
        knowledge = db.get_knowledge()
        title = "все знания"
        categories = set([item[1] for item in knowledge])
        await update.message.reply_text(f"📚 *Категории:*\n" + "\n".join([f"• {cat}" for cat in categories]), parse_mode='Markdown')
        return
    
    if knowledge:
        response = f"📖 *{title}:*\n\n"
        for i, item in enumerate(knowledge, 1):
            response += f"{i}. *{item[2]}*\n   → {item[3]}\n\n"
        
        await update.message.reply_text(response, parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Знаний не найдено", parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    knowledge = db.get_knowledge()
    status_text = f"""
📊 *Статус NeuroMentorAI:*

*База знаний:*
• Записей: {len(knowledge)}
• Категорий: {len(set([item[1] for item in knowledge]))}

*Сервер:* Render.com (бесплатный)
*Статус:* ✅ Работает

*Используйте /learn для добавления знаний*
    """
    await update.message.reply_text(status_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🧠 *NeuroMentorAI - Помощь*

*Команды:*
/learn - Добавить новое знание
/knowledge - Просмотреть знания
/status - Статус системы
/help - Эта справка

*Пример:*
/learn programming "Hello World" | "print('Hello World')"
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    if user_text.startswith('/'):
        return
    
    await update.message.reply_chat_action("typing")
    
    try:
        result = db.find_answer(user_text)
        if result:
            answer, category = result
            await update.message.reply_text(f"💡 *Нашел в '{category}':*\n\n{answer}", parse_mode='Markdown')
        else:
            await update.message.reply_text("""
🤔 *Я еще не знаю ответ на этот вопрос.*

*Обучите меня через:*
/learn [категория] [вопрос] | [ответ]

*Пример:*
/learn general "Как тебя зовут?" | "Меня зовут NeuroMentorAI!"
            """, parse_mode='Markdown')
            
    except Exception as e:
        await update.message.reply_text("❌ Произошла ошибка обработки", parse_mode='Markdown')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")

def main():
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не установлен!")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("learn", learn_command))
    application.add_handler(CommandHandler("knowledge", knowledge_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    
    logger.info("✅ NeuroMentorAI запущен на Render!")
    application.run_polling()

if __name__ == "__main__":
    main()