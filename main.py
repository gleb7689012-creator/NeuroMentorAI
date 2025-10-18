import os
import logging
import hashlib
import json
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# === КОНФИГУРАЦИЯ ЛИМИТОВ ===
BOT_TOKEN = os.getenv('BOT_TOKEN')
DB_FILE = "secure_files.json"

# Лимиты хранилища
STORAGE_LIMITS = {
    'free_tier_gb': 1024,  # 1TB бесплатно
    'warning_threshold_gb': 900,  # Предупреждение при 900GB
    'auto_cleanup_days': 30,  # Автоудаление файлов старше 30 дней
    'max_files_per_user': 100  # Максимум файлов на пользователя
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === УМНАЯ СИСТЕМА ОЧИСТКИ ===
class StorageManager:
    def __init__(self):
        self.limits = STORAGE_LIMITS
    
    def check_storage_limits(self, user_db, new_file_size_gb=0):
        """Проверяет не превышены ли лимиты"""
        projected_usage = user_db["total_used_gb"] + new_file_size_gb
        
        # Проверка общего лимита
        if projected_usage > self.limits['free_tier_gb']:
            return False, f"❌ Превышен лимит 1TB! Использовано: {user_db['total_used_gb']:.2f}GB"
        
        # Проверка количества файлов
        if len(user_db["files"]) >= self.limits['max_files_per_user']:
            return False, f"❌ Слишком много файлов! Максимум: {self.limits['max_files_per_user']}"
        
        # Предупреждение о接近 лимита
        if projected_usage > self.limits['warning_threshold_gb']:
            free_space = self.limits['free_tier_gb'] - projected_usage
            return True, f"⚠️ Мало свободного места! Осталось: {free_space:.2f}GB"
        
        return True, "OK"
    
    def auto_cleanup_old_files(self, user_db):
        """Автоматически удаляет старые файлы"""
        deleted_files = []
        current_time = datetime.now()
        
        for filename, file_info in list(user_db["files"].items()):
            uploaded_at = datetime.fromisoformat(file_info["uploaded_at"].replace('Z', '+00:00'))
            file_age = current_time - uploaded_at
            
            # Удаляем файлы старше 30 дней
            if file_age.days > self.limits['auto_cleanup_days']:
                user_db["total_used_gb"] -= file_info["size_gb"]
                del user_db["files"][filename]
                deleted_files.append(filename)
                logger.info(f"Автоочистка: удален {filename}")
        
        user_db["file_count"] = len(user_db["files"])
        return user_db, deleted_files
    
    def get_storage_stats(self, user_db):
        """Возвращает статистику хранилища"""
        free_space = self.limits['free_tier_gb'] - user_db["total_used_gb"]
        usage_percent = (user_db["total_used_gb"] / self.limits['free_tier_gb']) * 100
        
        # Находим самые старые файлы для потенциального удаления
        old_files = []
        current_time = datetime.now()
        
        for filename, file_info in user_db["files"].items():
            uploaded_at = datetime.fromisoformat(file_info["uploaded_at"].replace('Z', '+00:00'))
            file_age = current_time - uploaded_at
            
            if file_age.days > 20:  # Файлы старше 20 дней
                old_files.append({
                    'name': filename,
                    'age_days': file_age.days,
                    'size_gb': file_info["size_gb"]
                })
        
        return {
            'used_gb': user_db["total_used_gb"],
            'free_gb': free_space,
            'usage_percent': usage_percent,
            'file_count': user_db["file_count"],
            'old_files': sorted(old_files, key=lambda x: x['age_days'], reverse=True)[:5]
        }

# Инициализация менеджера хранилища
storage_manager = StorageManager()
# === СИСТЕМА БЕЗОПАСНОСТИ С КОНТРОЛЕМ МЕСТА ===
def get_user_id(update: Update):
    """Генерирует уникальный ID пользователя"""
    user = update.effective_user
    return hashlib.md5(f"{user.id}_{user.username}".encode()).hexdigest()[:10]

def load_user_db(user_id):
    """Загружает базу данных пользователя"""
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
            user_db = all_data.get(user_id, {"files": {}, "total_used_gb": 0, "file_count": 0})
            
            # Автоматическая очистка при загрузке
            user_db, deleted = storage_manager.auto_cleanup_old_files(user_db)
            if deleted:
                save_user_db(user_id, user_db)
                logger.info(f"Автоочистка для {user_id}: удалено {len(deleted)} файлов")
            
            return user_db
    except:
        return {"files": {}, "total_used_gb": 0, "file_count": 0}

def save_user_db(user_id, user_data):
    """Сохраняет базу данных пользователя"""
    try:
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                all_data = json.load(f)
        except:
            all_data = {}
        
        all_data[user_id] = user_data
        
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Save error: {e}")
        return False
# === КОМАНДЫ С КОНТРОЛЕМ МЕСТА ===
async def smart_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Умная загрузка с проверкой места"""
    user_id = get_user_id(update)
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "📤 **Умная загрузка:**\n"
            "Используй: /upload <имя> <текст>\n\n"
            "🤖 Я проверю свободное место и предложу очистку если нужно!"
        )
        return
    
    filename = context.args[0]
    content = " ".join(context.args[1:])
    file_size_gb = len(content) / (1024**3)
    
    # Загружаем базу и проверяем лимиты
    user_db = load_user_db(user_id)
    can_upload, message = storage_manager.check_storage_limits(user_db, file_size_gb)
    
    if not can_upload:
        # Предлагаем очистку
        stats = storage_manager.get_storage_stats(user_db)
        
        cleanup_suggestion = ""
        if stats['old_files']:
            cleanup_suggestion = "\n\n🗑️ **Старые файлы для удаления:**\n"
            for old_file in stats['old_files']:
                cleanup_suggestion += f"• {old_file['name']} ({old_file['age_days']} дней, {old_file['size_gb']:.2f}GB)\n"
            cleanup_suggestion += f"\n💡 Используй /cleanup_old для удаления старых файлов"
        
        await update.message.reply_text(
            f"{message}\n"
            f"💾 Использовано: {stats['used_gb']:.2f}GB из 1024GB\n"
            f"📊 Заполнено: {stats['usage_percent']:.1f}%{cleanup_suggestion}"
        )
        return
    
    # Место есть - загружаем
    user_db["files"][filename] = {
        "size_gb": file_size_gb,
        "type": "text",
        "uploaded_at": str(datetime.now()),
        "content_preview": content[:100] + "..." if len(content) > 100 else content
    }
    user_db["total_used_gb"] += file_size_gb
    user_db["file_count"] = len(user_db["files"])
    save_user_db(user_id, user_db)
    
    stats = storage_manager.get_storage_stats(user_db)
    
    await update.message.reply_text(
        f"✅ **Файл сохранен!**\n\n"
        f"📁 {filename}\n"
        f"💾 Размер: {file_size_gb:.4f}GB\n"
        f"📊 Использовано: {stats['used_gb']:.2f}GB / 1024GB\n"
        f"💿 Свободно: {stats['free_gb']:.2f}GB\n"
        f"📈 Заполнено: {stats['usage_percent']:.1f}%"
    )

async def storage_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальная статистика хранилища"""
    user_id = get_user_id(update)
    user_db = load_user_db(user_id)
    stats = storage_manager.get_storage_stats(user_db)
    
    response = f"💾 **ДЕТАЛЬНАЯ СТАТИСТИКА ХРАНИЛИЩА**\n\n"
    response += f"📀 Всего места: 1.0 TB (1024 GB)\n"
    response += f"📁 Использовано: {stats['used_gb']:.2f} GB\n"
    response += f"💿 Свободно: {stats['free_gb']:.2f} GB\n"
    response += f"📊 Заполнено: {stats['usage_percent']:.1f}%\n\n"
    
    if stats['usage_percent'] > 80:
        response += f"⚠️ **ВНИМАНИЕ:** Мало свободного места!\n"
    elif stats['usage_percent'] > 95:
        response += f"🚨 **КРИТИЧЕСКИ:** Почти нет места!\n"
    
    response += f"\n📈 **Ваша статистика:**\n"
    response += f"• 📄 Файлов: {stats['file_count']}\n"
    response += f"• 🗑️ Старых файлов (>20 дней): {len(stats['old_files'])}\n"
    
    if stats['old_files']:
        response += f"\n🗑️ **Самые старые файлы:**\n"
        for old_file in stats['old_files'][:3]:
            response += f"• {old_file['name']} ({old_file['age_days']} дней, {old_file['size_gb']:.2f}GB)\n"
        response += f"\n💡 Используй /cleanup_old для очистки"
    
    await update.message.reply_text(response)

async def cleanup_old_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистка старых файлов"""
    user_id = get_user_id(update)
    user_db = load_user_db(user_id)
    
    # Автоматическая очистка
    user_db, deleted_files = storage_manager.auto_cleanup_old_files(user_db)
    
    if deleted_files:
        save_user_db(user_id, user_db)
        stats = storage_manager.get_storage_stats(user_db)
        
        response = f"🧹 **АВТООЧИСТКА ВЫПОЛНЕНА!**\n\n"
        response += f"🗑️ Удалено файлов: {len(deleted_files)}\n"
        response += f"💾 Освобождено: {sum(f['size_gb'] for f in [user_db['files'].get(f, {}) for f in deleted_files] if f):.2f}GB\n"
        response += f"📊 Теперь свободно: {stats['free_gb']:.2f}GB\n\n"
        response += f"📋 Удаленные файлы:\n"
        
        for filename in deleted_files[:5]:  # Показываем первые 5
            response += f"• {filename}\n"
        
        if len(deleted_files) > 5:
            response += f"• ... и еще {len(deleted_files) - 5} файлов\n"
    
    else:
        response = "✅ Старых файлов для очистки не найдено!\n\n"
        response += "🗑️ Файлы автоматически удаляются через 30 дней"
    
    await update.message.reply_text(response)

async def force_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительная очистка по размеру"""
    user_id = get_user_id(update)
    user_db = load_user_db(user_id)
    
    if not context.args:
        await update.message.reply_text(
            "🗑️ **Принудительная очистка:**\n"
            "Используй: /force_cleanup <размер_в_GB>\n\n"
            "Пример: /force_cleanup 10.5\n"
            "🤖 Удалит самые старые файлы пока не освободит 10.5GB"
        )
        return
    
    try:
        target_free_gb = float(context.args[0])
        current_stats = storage_manager.get_storage_stats(user_db)
        
        if current_stats['free_gb'] >= target_free_gb:
            await update.message.reply_text(
                f"✅ Уже достаточно свободного места!\n"
                f"💿 Свободно: {current_stats['free_gb']:.2f}GB\n"
                f"🎯 Требовалось: {target_free_gb}GB"
            )
            return
        
        needed_gb = target_free_gb - current_stats['free_gb']
        deleted_files = []
        freed_gb = 0
        
        # Сортируем файлы по дате (старые сначала)
        sorted_files = sorted(
            user_db["files"].items(),
            key=lambda x: datetime.fromisoformat(x[1]["uploaded_at"].replace('Z', '+00:00'))
        )
        
        for filename, file_info in sorted_files:
            if freed_gb >= needed_gb:
                break
                
            user_db["total_used_gb"] -= file_info["size_gb"]
            freed_gb += file_info["size_gb"]
            deleted_files.append(filename)
            del user_db["files"][filename]
        
        user_db["file_count"] = len(user_db["files"])
        save_user_db(user_id, user_db)
        
        new_stats = storage_manager.get_storage_stats(user_db)
        
        await update.message.reply_text(
            f"🧹 **ПРИНУДИТЕЛЬНАЯ ОЧИСТКА**\n\n"
            f"🗑️ Удалено файлов: {len(deleted_files)}\n"
            f"💾 Освобождено: {freed_gb:.2f}GB\n"
            f"📊 Теперь свободно: {new_stats['free_gb']:.2f}GB\n"
            f"🎯 Цель достигнута: {'✅' if new_stats['free_gb'] >= target_free_gb else '⚠️'}"
        )
        
    except ValueError:
        await update.message.reply_text("❌ Укажи число в GB! Пример: /force_cleanup 5.2")
# === ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    user_db = load_user_db(user_id)
    stats = storage_manager.get_storage_stats(user_db)
    
    await update.message.reply_text(
        f"🤖 **УМНЫЙ TERABOX БОТ С ОЧИСТКОЙ**\n\n"
        f"💾 **Ваше хранилище:**\n"
        f"📊 Использовано: {stats['used_gb']:.2f}GB / 1024GB\n"
        f"💿 Свободно: {stats['free_gb']:.2f}GB\n"
        f"📈 Заполнено: {stats['usage_percent']:.1f}%\n\n"
        f"🚀 **Команды с контролем места:**\n"
        f"📤 /upload <имя> <текст> - Умная загрузка\n"
        f"💾 /storage - Детальная статистика\n"
        f"🗑️ /cleanup_old - Очистка старых файлов\n"
        f"🧹 /force_cleanup <GB> - Принудительная очистка\n"
        f"📁 /my_files - Ваши файлы\n\n"
        f"🛡️ **Автоочистка:** Файлы удаляются через 30 дней!"
    )

async def list_files_with_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список файлов с информацией о размере"""
    user_id = get_user_id(update)
    user_db = load_user_db(user_id)
    
    if not user_db["files"]:
        await update.message.reply_text("📭 Файлов пока нет!")
        return
    
    response = "📁 **Ваши файлы (сортировка по размеру):**\n\n"
    
    # Сортируем по размеру (большие сначала)
    sorted_files = sorted(
        user_db["files"].items(),
        key=lambda x: x[1]["size_gb"],
        reverse=True
    )
    
    total_size = 0
    for filename, info in sorted_files[:10]:  # Показываем 10 самых больших
        uploaded_at = datetime.fromisoformat(info["uploaded_at"].replace('Z', '+00:00'))
        age_days = (datetime.now() - uploaded_at).days
        
        response += f"📄 **{filename}**\n"
        response += f"   📏 {info['size_gb']:.4f} GB | 🕐 {age_days} дней\n"
        
        if age_days > 20:
            response += f"   ⚠️ Старый файл (удалится через {30 - age_days} дней)\n"
        
        response += "\n"
        total_size += info["size_gb"]
    
    response += f"💾 **Суммарный размер показанных файлов:** {total_size:.2f}GB"
    
    await update.message.reply_text(response)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("upload", smart_upload))
    application.add_handler(CommandHandler("storage", storage_status))
    application.add_handler(CommandHandler("cleanup_old", cleanup_old_files))
    application.add_handler(CommandHandler("force_cleanup", force_cleanup))
    application.add_handler(CommandHandler("my_files", list_files_with_size))
    
    print("🤖 Умный бот с контролем места запускается...")
    application.run_polling()

if __name__ == '__main__':
    main()