import os
import time
import threading
import cv2
import logging
from datetime import datetime, timedelta
import glob
import queue
import subprocess

from config import FPS, HEIGHT, MAX_VIDEOS, RTSP_URL, SEGMENT_DURATION, WIDTH, VIDEO_DIR

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("recorder")

os.makedirs(VIDEO_DIR, exist_ok=True)



class VideoRecorder:
    def __init__(self):
        self.cap = None
        self.running = True
        self.current_writer = None
        self.current_filename = None
        self.segment_start_time = None
        self.frame_count = 0
        self.segment_count = 0
        
        # Очередь для хранения путей к видеофайлам
        self.video_queue = queue.Queue(maxsize=MAX_VIDEOS)
        
        logger.info("📡 Подключение к RTSP...")
        self.connect()

        # Запускаем потоки
        threading.Thread(target=self.capture_loop, daemon=True).start()
        threading.Thread(target=self.cleanup_manager, daemon=True).start()
        
        # Загружаем существующие видеофайлы в очередь
        self.load_existing_videos()
        
        logger.info("🎥 Видеорекордер запущен (непрерывная запись на диск)")

    # ================= RTSP =================
    def connect(self):
        if self.cap:
            try:
                self.cap.release()
            except:
                pass

        self.cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
        
        if not self.cap.isOpened():
            logger.error("❌ RTSP поток не открылся")
        else:
            logger.info("✅ RTSP подключён")

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        self.cap.set(cv2.CAP_PROP_FPS, FPS)

    # ================= LOAD EXISTING VIDEOS =================
    def load_existing_videos(self):
        """Загружает существующие видеофайлы в очередь"""
        try:
            # Получаем все видеофайлы, отсортированные по времени создания
            video_files = sorted(
                glob.glob(os.path.join(VIDEO_DIR, "*.mp4")),
                key=os.path.getctime
            )
            
            for video_file in video_files[-MAX_VIDEOS:]:  # Берем последние MAX_VIDEOS файлов
                try:
                    if self.video_queue.full():
                        # Удаляем самый старый файл, если очередь полна
                        old_file = self.video_queue.get()
                        try:
                            os.remove(old_file)
                            logger.info(f"🗑️ Удалён устаревший файл: {os.path.basename(old_file)}")
                        except:
                            pass
                    
                    self.video_queue.put(video_file)
                    logger.debug(f"📂 Загружен в очередь: {os.path.basename(video_file)}")
                except:
                    pass
                    
            logger.info(f"📊 Загружено {self.video_queue.qsize()} существующих видеофайлов")
            
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки существующих видео: {e}")

    # ================= CREATE NEW SEGMENT =================
    def create_new_segment(self):
        """Создает новый сегмент видео"""
        try:
            # Закрываем предыдущий writer, если есть
            if self.current_writer is not None:
                self.current_writer.release()
            
            # Создаем имя файла
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.current_filename = os.path.join(VIDEO_DIR, f"segment_{timestamp}.mp4")
            
            # Создаем VideoWriter
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.current_writer = cv2.VideoWriter(
                self.current_filename,
                fourcc,
                FPS,
                (WIDTH, HEIGHT)
            )
            
            if not self.current_writer.isOpened():
                logger.error("❌ Не удалось создать VideoWriter, пробую другой кодек...")
                fourcc = cv2.VideoWriter_fourcc(*'XVID')
                self.current_writer = cv2.VideoWriter(
                    self.current_filename,
                    fourcc,
                    FPS,
                    (WIDTH, HEIGHT)
                )
                
                if not self.current_writer.isOpened():
                    logger.error("❌ Не удалось создать VideoWriter ни с одним кодеком")
                    return False
            
            self.segment_start_time = time.time()
            self.frame_count = 0
            self.segment_count += 1
            
            logger.info(f"📹 Начат новый сегмент: {os.path.basename(self.current_filename)}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания нового сегмента: {e}")
            return False

    # ================= CAPTURE LOOP =================
    def capture_loop(self):
        """Основной цикл захвата и записи видео"""
        errors = 0
        
        # Создаем первый сегмент
        if not self.create_new_segment():
            logger.error("❌ Не удалось начать запись")
            return

        while self.running:
            # Проверяем, не пора ли создать новый сегмент
            if time.time() - self.segment_start_time >= SEGMENT_DURATION:
                self.finalize_segment()
                if not self.create_new_segment():
                    logger.error("❌ Не удалось создать новый сегмент")
                    time.sleep(1)
                    continue

            if not self.cap or not self.cap.isOpened():
                logger.warning("🔄 RTSP недоступен — переподключаемся")
                self.connect()
                time.sleep(2)
                continue

            ret, frame = self.cap.read()

            if not ret:
                errors += 1
                logger.warning("⚠️ Потерян кадр")
                if errors > 10:
                    logger.error("🔄 Слишком много ошибок — переподключение RTSP")
                    self.connect()
                    errors = 0
                time.sleep(0.2)
                continue

            errors = 0
            
            # Ресайзим кадр
            frame = cv2.resize(frame, (WIDTH, HEIGHT))
            
            # Записываем кадр в текущий сегмент
            try:
                self.current_writer.write(frame)
                self.frame_count += 1
            except Exception as e:
                logger.error(f"❌ Ошибка записи кадра: {e}")
            
            # Поддерживаем FPS
            time.sleep(1 / FPS)

    # ================= FINALIZE SEGMENT =================
    def finalize_segment(self):
        """Завершает текущий сегмент видео и добавляет его в очередь"""
        if self.current_writer is not None:
            try:
                self.current_writer.release()
                
                # Проверяем, записалось ли что-то в файл
                if os.path.exists(self.current_filename) and os.path.getsize(self.current_filename) > 0:
                    
                    # Управляем очередью видеофайлов
                    if self.video_queue.full():
                        # Удаляем самый старый файл
                        try:
                            old_file = self.video_queue.get()
                            if os.path.exists(old_file):
                                os.remove(old_file)
                                logger.info(f"🗑️ Удалён устаревший сегмент: {os.path.basename(old_file)}")
                        except:
                            pass
                    
                    # Добавляем новый файл в очередь
                    self.video_queue.put(self.current_filename)
                    
                    duration = time.time() - self.segment_start_time
                    logger.info(f"💾 Сегмент завершен: {os.path.basename(self.current_filename)} " 
                               f"({self.frame_count} кадров, {duration:.1f} сек)")
                else:
                    # Удаляем пустой файл
                    if os.path.exists(self.current_filename):
                        os.remove(self.current_filename)
                        logger.warning(f"🗑️ Удалён пустой сегмент: {os.path.basename(self.current_filename)}")
                
            except Exception as e:
                logger.error(f"❌ Ошибка завершения сегмента: {e}")
            
            self.current_writer = None

    # ================= CLEANUP MANAGER =================
    def cleanup_manager(self):
        """Управляет очисткой устаревших файлов"""
        while self.running:
            try:
                # Получаем все видеофайлы
                all_files = glob.glob(os.path.join(VIDEO_DIR, "*.mp4"))
                
                # Получаем файлы из очереди
                queue_files = []
                temp_queue = queue.Queue()
                while not self.video_queue.empty():
                    file = self.video_queue.get()
                    queue_files.append(file)
                    temp_queue.put(file)
                
                # Восстанавливаем очередь
                self.video_queue = temp_queue
                
                # Находим файлы, которые не в очереди
                files_to_delete = [f for f in all_files if f not in queue_files]
                
                # Удаляем лишние файлы
                for filepath in files_to_delete:
                    try:
                        # Не удаляем текущий записываемый файл
                        if filepath != self.current_filename:
                            os.remove(filepath)
                            logger.info(f"🧹 Удалён потерянный файл: {os.path.basename(filepath)}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка удаления файла {filepath}: {e}")
                
                time.sleep(60)  # Проверяем каждую минуту
                
            except Exception as e:
                logger.error(f"❌ Ошибка в cleanup_manager: {e}")
                time.sleep(60)

    # ================= API METHODS =================
    def get_last_video(self):
        """Возвращает путь к последнему сохраненному видеофайлу"""
        try:
            # Получаем последний файл из очереди
            last_video = None
            
            # Создаем временную очередь для поиска последнего файла
            temp_queue = queue.Queue()
            while not self.video_queue.empty():
                video = self.video_queue.get()
                last_video = video
                temp_queue.put(video)
            
            # Восстанавливаем очередь
            self.video_queue = temp_queue
            
            if last_video and os.path.exists(last_video):
                logger.info(f"📁 Найден последний сегмент: {os.path.basename(last_video)}")
                return last_video
            else:
                logger.warning("⚠️ Нет сохраненных видеофайлов")
                return None
                
        except Exception as e:
            logger.error(f"❌ Ошибка получения последнего видео: {e}")
            return None

    def get_all_videos(self):
        """Возвращает список всех сохраненных видеофайлов"""
        try:
            videos = []
            temp_queue = queue.Queue()
            
            while not self.video_queue.empty():
                video = self.video_queue.get()
                videos.append(video)
                temp_queue.put(video)
            
            # Восстанавливаем очередь
            self.video_queue = temp_queue
            
            return sorted(videos, key=os.path.getctime)
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения списка видео: {e}")
            return []

    def save_current_segment(self):
        """Немедленно завершает текущий сегмент и начинает новый"""
        logger.info("🎬 Запрос на сохранение текущего сегмента...")
        
        # Завершаем текущий сегмент
        self.finalize_segment()
        
        # Создаем новый сегмент
        if self.create_new_segment():
            # Получаем последний сохраненный файл (только что завершенный)
            return self.get_last_video()
        else:
            return None

    def convert_for_telegram(self, input_path):
        """Конвертирует видео для лучшей совместимости с Telegram"""
        try:
            output_path = input_path.replace('.mp4', '_tg.mp4')
            
            # Используем ffmpeg для конвертации
            command = [
                'ffmpeg', '-i', input_path,
                '-c:v', 'libx264',
                '-preset', 'fast',
                '-crf', '23',
                '-c:a', 'aac',
                '-b:a', '128k',
                '-movflags', '+faststart',
                '-vf', 'scale=640:-2',
                '-y', output_path
            ]
            
            subprocess.run(command, check=True, capture_output=True, text=True)
            
            if os.path.exists(output_path):
                return output_path
            else:
                return input_path
                
        except Exception as e:
            logger.error(f"❌ Ошибка конвертации видео: {e}")
            return input_path  # Возвращаем оригинал, если конвертация не удалась

    # ================= STATISTICS =================
    def get_stats(self):
        """Возвращает статистику записи"""
        return {
            "segment_count": self.segment_count,
            "current_frames": self.frame_count,
            "queue_size": self.video_queue.qsize(),
            "current_segment": os.path.basename(self.current_filename) if self.current_filename else None,
            "segment_duration": time.time() - self.segment_start_time if self.segment_start_time else 0
        }

    def stop(self):
        """Останавливает рекордер"""
        self.running = False
        try:
            self.finalize_segment()
            if self.cap:
                self.cap.release()
        except:
            pass
        logger.info("⏹️ Рекордер остановлен")