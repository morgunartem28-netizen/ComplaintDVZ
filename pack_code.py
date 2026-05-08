import os

# Имя выходного файла
output_file = "all_code.txt"

# Папки, которые нужно игнорировать (чтобы не тащить мусор)
exclude_dirs = ['venv', '__pycache__', '.git', '.idea', 'build', 'dist']

# Какие расширения файлов собирать
extensions = ['.py', '.env', '.txt', '.md', '.json', '.yaml', '.yml']

print(f"🔍 Начинаю сборку кода из папки: {os.getcwd()}...")

with open(output_file, 'w', encoding='utf-8') as outfile:
    outfile.write("# СОБРАННЫЙ КОД ПРОЕКТА\n\n")
    
    # Проход по всем папкам и файлам
    for root, dirs, files in os.walk('.'):
        # Убираем лишние папки из обхода
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        
        for file in files:
            # Проверка расширения
            if any(file.endswith(ext) for ext in extensions):
                filepath = os.path.join(root, file)
                
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Запись разделителя и имени файла
                    outfile.write(f"\n{'='*50}\n")
                    outfile.write(f"=== ФАЙЛ: {filepath} ===\n")
                    outfile.write(f"{'='*50}\n\n")
                    # Запись содержимого
                    outfile.write(content)
                    outfile.write("\n")
                    print(f"✅ Добавлен: {filepath}")
                except Exception as e:
                    print(f"⚠️ Ошибка чтения {filepath}: {e}")

print(f"\n🎉 ГОТОВО! Весь код собран в файл: {os.path.abspath(output_file)}")
print("Откройте этот файл, скопируйте всё содержимое и отправьте в чат.")
