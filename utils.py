import os
import re
import asyncio
import edge_tts
import uuid
from typing import List, Dict, Any
import tempfile
import logging
import subprocess
import sys
import time
import datetime
import shutil
from datetime import datetime, timedelta

# 在导入 pydub 之前，创建一个 mock 类来防止 pyaudioop 导入错误
import sys
class PyAudioopMock:
    pass

# 如果 pyaudioop 模块不存在，使用 mock 替代
if 'pyaudioop' not in sys.modules:
    sys.modules['pyaudioop'] = PyAudioopMock()

# 导入 pydub 用于音频处理（但实际上我们主要使用 ffmpeg）
try:
    from pydub import AudioSegment
except ImportError:
    # 如果 pydub 导入失败，创建一个简单的 AudioSegment mock
    class AudioSegment:
        @staticmethod
        def from_file(*args, **kwargs):
            raise NotImplementedError("AudioSegment is not available. Please use ffmpeg directly.")

# 日志配置
DEBUG_MODE = os.environ.get('DEBUG_MODE', 'false').lower() in ['true', '1', 'yes']
LOG_LEVEL = logging.DEBUG if DEBUG_MODE else logging.INFO
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s' if DEBUG_MODE else '%(asctime)s - %(levelname)s - %(message)s'

# 配置日志输出
logging.basicConfig(
    level=LOG_LEVEL, 
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('tts_process.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# 初始化日志
logger.info(f"日志系统初始化完成，调试模式：{'开启' if DEBUG_MODE else '关闭'}")

async def get_available_voices() -> List[Dict[str, Any]]:
    """获取 Edge TTS 可用的所有语音"""
    logger.info("正在获取 Edge TTS 可用语音列表...")
    try:
        voices_manager = await edge_tts.VoicesManager.create()
        voices = voices_manager.voices
        logger.info(f"获取语音列表成功，共 {len(voices)} 个语音")
        if DEBUG_MODE:
            logger.debug(f"语音列表前5个：{voices[:5]}")
        return voices
    except Exception as e:
        logger.error(f"获取语音列表失败: {str(e)}")
        raise

async def get_chinese_voices() -> List[Dict[str, Any]]:
    """获取 Edge TTS 中文语音列表，并添加中文名称"""
    logger.info("正在筛选中文语音...")
    try:
        voices = await get_available_voices()
        chinese_voices = [voice for voice in voices if voice["Locale"].startswith("zh-")]
        logger.info(f"中文语音筛选完成，共 {len(chinese_voices)} 个语音")
        
        # 为中文语音添加中文名称
        voice_chinese_names = {
            "zh-CN-XiaoxiaoNeural": "晓晓（女声，清新甜美）",
            "zh-CN-XiaoyiNeural": "晓伊（女声，温柔自然）",
            "zh-CN-YunjianNeural": "云健（男声，稳重成熟）",
            "zh-CN-YunxiNeural": "云熙（男声，阳光青年）",
            "zh-CN-YunxiaNeural": "云夏（女声，活泼可爱）",
            "zh-CN-YunyangNeural": "云扬（男声，标准播音）",
            "zh-CN-liaoning-XiaobeiNeural": "晓北（女声，东北方言）",
            "zh-CN-shaanxi-XiaoniNeural": "晓妮（女声，陕西方言）",
            "zh-HK-HiuGaaiNeural": "晓佳（女声，粤语）",
            "zh-HK-HiuMaanNeural": "晓曼（女声，粤语）",
            "zh-HK-WanLungNeural": "云龙（男声，粤语）",
            "zh-TW-HsiaoChenNeural": "晓辰（女声，台湾）",
            "zh-TW-YunJheNeural": "云哲（男声，台湾）",
            "zh-TW-HsiaoYuNeural": "晓宇（女声，台湾）"
        }
        
        for voice in chinese_voices:
            voice_name = voice["ShortName"]
            if voice_name in voice_chinese_names:
                voice["ChineseName"] = voice_chinese_names[voice_name]
            else:
                # 如果没有预定义的中文名，生成一个默认的中文名
                name_parts = voice_name.split('-')
                if len(name_parts) >= 3:
                    last_part = name_parts[-1].replace('Neural', '')
                    gender = "女声" if voice["Gender"] == "Female" else "男声"
                    locale = "普通话" if "CN" in voice_name else ("粤语" if "HK" in voice_name else "台湾")
                    voice["ChineseName"] = f"{last_part}（{gender}，{locale}）"
                else:
                    voice["ChineseName"] = voice_name
        
        if DEBUG_MODE:
            for voice in chinese_voices:
                logger.debug(f"中文语音: {voice['ShortName']}, 中文名: {voice['ChineseName']}, 性别: {voice['Gender']}")
        
        # 确保默认语音 YunyangNeural 排在最前面
        chinese_voices.sort(key=lambda x: 0 if x["ShortName"] == "zh-CN-YunyangNeural" else 1)
        
        return chinese_voices
    except Exception as e:
        logger.error(f"筛选中文语音失败: {str(e)}")
        raise

def parse_shici_file(file_path: str) -> List[Dict[str, str]]:
    """
    解析 shici.txt 文件并提取各个条目
    
    Returns a list of dictionaries with keys:
    - number: entry number
    - character: Chinese character
    - pinyin: pronunciation in pinyin
    - content: full content of the entry
    """
    logger.info(f"开始解析文件: {file_path}")
    
    if not os.path.exists(file_path):
        logger.error(f"文件不存在: {file_path}")
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        logger.info(f"文件读取成功，内容大小: {len(content)} 字符")
        
        # Split by numbered entries (e.g., "1. 比 (bǐ)")
        entries_raw = re.split(r'(\d+\.\s+.+?\([^)]+\))', content)[1:]
        logger.info(f"初步分割得到 {len(entries_raw)} 个片段")
        
        # Group entries and their content
        entries = []
        for i in range(0, len(entries_raw), 2):
            if i+1 < len(entries_raw):
                header = entries_raw[i].strip()
                entry_content = entries_raw[i+1].strip()
                
                # Extract entry info
                match = re.match(r'(\d+)\.\s+(.+?)\s+\(([^)]+)\)', header)
                if match:
                    number, character, pinyin = match.groups()
                    entries.append({
                        "number": number,
                        "character": character,
                        "pinyin": pinyin,
                        "content": header + "\n" + entry_content
                    })
                    if DEBUG_MODE and len(entries) <= 2:
                        logger.debug(f"解析条目 {number}: {character}({pinyin}), 内容长度: {len(entry_content)} 字符")
        
        logger.info(f"文件解析完成，共提取 {len(entries)} 个词条")
        return entries
    except Exception as e:
        logger.error(f"解析文件失败: {str(e)}")
        raise

def group_entries_by_count(entries: List[Dict[str, str]], group_size: int = 10) -> List[List[Dict[str, str]]]:
    """
    将词条按照固定数量分组，每组包含指定数量的词条
    
    Args:
        entries: 词条列表
        group_size: 每组词条数量，默认为10
    
    Returns:
        分组后的词条列表
    """
    logger.info(f"开始按每组 {group_size} 个词条进行分组，总词条数: {len(entries)}")
    
    groups = []
    for i in range(0, len(entries), group_size):
        group = entries[i:i + group_size]
        groups.append(group)
        if DEBUG_MODE:
            logger.debug(f"创建第 {len(groups)} 组，包含 {len(group)} 个词条，ID范围: {group[0]['number']}~{group[-1]['number']}")
    
    logger.info(f"分组完成，共 {len(groups)} 组，平均每组 {sum(len(group) for group in groups)/len(groups):.1f} 个词条")
    return groups

async def convert_text_to_speech(text: str, voice: str, rate: str = "+0%", volume: str = "+0%", pitch: str = "+0Hz", output_path: str = None) -> str:
    """
    使用 Edge TTS 将文本转换为语音
    
    Args:
        text: Text to convert
        voice: Voice to use
        rate: Speed of speech (e.g., "+0%", "-50%", "+50%")
        volume: Volume of speech (e.g., "+0%", "-50%", "+50%")
        pitch: Pitch of speech (e.g., "+0Hz", "-50Hz", "+50Hz")
        output_path: Optional output path for the audio file
        
    Returns:
        Path to the generated audio file
    """
    start_time = time.time()
    text_preview = text[:50] + "..." if len(text) > 50 else text
    
    if DEBUG_MODE:
        logger.debug(f"开始转换文本为语音: '{text_preview}'")
        logger.debug(f"参数: voice={voice}, rate={rate}, volume={volume}, pitch={pitch}")
    else:
        logger.info(f"开始转换文本: '{text_preview}'")
    
    if output_path is None:
        os.makedirs("static/audio", exist_ok=True)
        output_path = f"static/audio/{uuid.uuid4()}.mp3"
    
    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch)
        await communicate.save(output_path)
        
        end_time = time.time()
        file_size = os.path.getsize(output_path) / 1024  # KB
        logger.info(f"文本转语音成功，输出文件: {output_path}, 大小: {file_size:.1f}KB, 用时: {end_time-start_time:.2f}秒")
        return output_path
    except Exception as e:
        logger.error(f"文本转语音失败: {str(e)}")
        raise

def merge_audio_files(audio_files: List[str], output_file: str) -> str:
    """
    合并多个音频文件为一个，优先使用 ffmpeg
    
    Args:
        audio_files: 要合并的音频文件路径列表
        output_file: 输出文件路径
    
    Returns:
        合并后的音频文件路径
    """
    if not audio_files:
        logger.error("没有音频文件可合并")
        raise ValueError("No audio files to merge")
    
    # 如果只有一个文件，直接返回
    if len(audio_files) == 1:
        logger.info(f"只有一个音频文件，无需合并，返回: {audio_files[0]}")
        return audio_files[0]
    
    logger.info(f"开始合并 {len(audio_files)} 个音频文件到 {output_file}")
    
    # 检查所有文件是否存在
    for i, file in enumerate(audio_files):
        if not os.path.exists(file):
            logger.error(f"文件不存在: {file} (第 {i+1} 个文件)")
            raise FileNotFoundError(f"File not found: {file}")
        if DEBUG_MODE:
            logger.debug(f"准备合并文件 {i+1}/{len(audio_files)}: {file}, 大小: {os.path.getsize(file)/1024:.1f}KB")
    
    try:
        # 优先使用 ffmpeg 合并文件
        if is_ffmpeg_available():
            logger.info("检测到 ffmpeg，使用 ffmpeg 进行音频合并")
            return merge_with_ffmpeg(audio_files, output_file)
        
        # 如果 ffmpeg 不可用，使用二进制文件拼接方法
        logger.info("未检测到 ffmpeg，使用二进制拼接方法合并音频文件")
        return merge_with_binary_concat(audio_files, output_file)
    
    except Exception as e:
        logger.error(f"合并音频文件失败: {str(e)}")
        # 如果合并失败，返回第一个文件
        logger.info(f"返回第一个音频文件作为替代: {audio_files[0]}")
        return audio_files[0]

def merge_with_binary_concat(audio_files: List[str], output_file: str) -> str:
    """使用二进制拼接方法合并音频文件"""
    logger.info(f"开始使用二进制拼接方法合并 {len(audio_files)} 个音频文件")
    
    try:
        with open(output_file, 'wb') as outfile:
            total_size = 0
            for i, audio_file in enumerate(audio_files):
                with open(audio_file, 'rb') as infile:
                    data = infile.read()
                    outfile.write(data)
                    total_size += len(data)
                    if (i+1) % 5 == 0 or i+1 == len(audio_files):
                        logger.info(f"已合并 {i+1}/{len(audio_files)} 个文件，当前大小: {total_size/1024:.1f}KB")
        
        logger.info(f"二进制合并完成，输出文件: {output_file}, 大小: {os.path.getsize(output_file)/1024:.1f}KB")
        return output_file
    except Exception as e:
        logger.error(f"二进制拼接合并失败: {str(e)}")
        raise

def is_ffmpeg_available() -> bool:
    """检查系统中是否可用 ffmpeg"""
    logger.info("检查 ffmpeg 是否可用...")
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                             stdout=subprocess.PIPE, 
                             stderr=subprocess.PIPE,
                             text=True)
        is_available = result.returncode == 0
        if is_available and DEBUG_MODE:
            version_info = result.stdout.split('\n')[0]
            logger.debug(f"ffmpeg 可用，版本信息: {version_info}")
        else:
            logger.info(f"ffmpeg {'可用' if is_available else '不可用'}")
        return is_available
    except Exception as e:
        logger.error(f"检查 ffmpeg 失败: {str(e)}")
        return False

def merge_with_ffmpeg(audio_files: List[str], output_file: str) -> str:
    """使用 ffmpeg 合并音频文件"""
    logger.info(f"开始使用 ffmpeg 合并 {len(audio_files)} 个音频文件")
    start_time = time.time()
    
    try:
        # 创建临时文件列表
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
            list_file = f.name
            logger.info(f"创建临时文件列表: {list_file}")
            for i, audio_file in enumerate(audio_files):
                f.write(f"file '{os.path.abspath(audio_file)}'\n")
                if DEBUG_MODE and (i < 3 or i >= len(audio_files) - 3):
                    logger.debug(f"添加到列表: {os.path.abspath(audio_file)}")
        
        # 调用 ffmpeg 合并文件
        cmd = [
            'ffmpeg', 
            '-f', 'concat', 
            '-safe', '0', 
            '-i', list_file, 
            '-c', 'copy', 
            output_file
        ]
        
        logger.info(f"执行 ffmpeg 命令: {' '.join(cmd)}")
        process = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        if DEBUG_MODE:
            stderr_lines = process.stderr.split('\n')
            for line in stderr_lines[:10]:  # 只显示前10行
                if line.strip():
                    logger.debug(f"ffmpeg 输出: {line}")
        
        # 删除临时文件
        os.unlink(list_file)
        logger.info(f"已删除临时文件: {list_file}")
        
        end_time = time.time()
        logger.info(f"ffmpeg 合并完成，输出文件: {output_file}, 大小: {os.path.getsize(output_file)/1024:.1f}KB, 用时: {end_time-start_time:.2f}秒")
        return output_file
    
    except Exception as e:
        logger.error(f"使用 ffmpeg 合并失败: {str(e)}")
        logger.info("尝试使用二进制拼接方法作为备选")
        
        # 如果 ffmpeg 失败，尝试使用二进制拼接
        with open(output_file, 'wb') as outfile:
            for audio_file in audio_files:
                if os.path.exists(audio_file):
                    with open(audio_file, 'rb') as infile:
                        outfile.write(infile.read())
                        
        logger.info(f"二进制拼接完成，输出文件: {output_file}")
        return output_file

async def process_shici_entries(entries: List[Dict[str, str]], voice: str, rate: str = "+0%", volume: str = "+0%", pitch: str = "+0Hz", output_dir: str = "static/audio") -> Dict[str, Any]:
    """
    Process shici entries and convert them to speech, then merge into a single complete audio file
    
    Args:
        entries: List of entry dictionaries
        voice: Voice to use
        rate: Speed of speech (e.g., "+0%", "-50%", "+50%")
        volume: Volume of speech (e.g., "+0%", "-50%", "+50%")
        pitch: Pitch of speech (e.g., "+0Hz", "-50Hz", "+50Hz")
        output_dir: Directory to save audio files
        
    Returns:
        Dictionary with audio file information
    """
    logger.info("=" * 50)
    logger.info(f"开始处理 shici 词条，总数: {len(entries)}")
    logger.info(f"参数: voice={voice}, rate={rate}, volume={volume}, pitch={pitch}, output_dir={output_dir}")
    
    total_start_time = time.time()
    os.makedirs(output_dir, exist_ok=True)
    
    # 将词条合并到一个文本中
    complete_text = "\n\n".join([entry["content"] for entry in entries])
    logger.info(f"合并文本长度: {len(complete_text)} 字符")
    
    # 生成一个包含所有词条的完整音频
    complete_filename = f"{output_dir}/shici_complete_{uuid.uuid4()}.mp3"
    logger.info(f"开始生成完整音频文件: {complete_filename}")
    
    try:
        # 直接转换完整文本为一个音频文件
        await convert_text_to_speech(complete_text, voice, rate, volume, pitch, complete_filename)
        
        total_end_time = time.time()
        file_size = os.path.getsize(complete_filename) / 1024  # KB
        logger.info(f"处理完成，生成文件大小: {file_size:.1f}KB, 总用时: {total_end_time-total_start_time:.2f}秒")
        logger.info("=" * 50)
        
        return {
            "complete_audio": {
                "path": complete_filename,
                "total_entries": len(entries),
                "file_size_kb": file_size
            }
        }
    
    except Exception as e:
        logger.error(f"生成完整音频失败: {str(e)}")
        
        # 如果直接转换失败，尝试分组处理后合并
        logger.info("尝试分组处理后合并...")
        
        # 将词条按照每组10个分组
        grouped_entries = group_entries_by_count(entries, 10)
        group_audio_files = []
        
        for group_idx, group in enumerate(grouped_entries):
            group_start_time = time.time()
            logger.info(f"开始处理第 {group_idx+1}/{len(grouped_entries)} 组，包含 {len(group)} 个词条")
            
            # 准备该组的合并文本
            group_text = "\n\n".join([entry["content"] for entry in group])
            
            # 每组生成一个合并的音频文件
            group_filename = f"{output_dir}/shici_group_{group_idx+1}_{uuid.uuid4()}.mp3"
            logger.info(f"开始为组 {group_idx+1} 生成音频文件: {group_filename}")
            
            await convert_text_to_speech(group_text, voice, rate, volume, pitch, group_filename)
            group_audio_files.append(group_filename)
            
            group_end_time = time.time()
            logger.info(f"第 {group_idx+1}/{len(grouped_entries)} 组处理完成，用时: {group_end_time-group_start_time:.2f}秒")
        
        # 合并所有组音频为一个完整音频
        logger.info(f"开始合并 {len(group_audio_files)} 个组音频文件到完整音频: {complete_filename}")
        complete_path = merge_audio_files(group_audio_files, complete_filename)
        
        # 清理临时的组音频文件
        if DEBUG_MODE:
            logger.debug("保留临时组音频文件用于调试")
        else:
            logger.info("清理临时组音频文件")
            for file in group_audio_files:
                try:
                    os.remove(file)
                    if DEBUG_MODE:
                        logger.debug(f"已删除临时文件: {file}")
                except Exception as e:
                    logger.error(f"删除临时文件失败: {file}, 错误: {str(e)}")
        
        total_end_time = time.time()
        file_size = os.path.getsize(complete_path) / 1024  # KB
        logger.info(f"处理完成，生成文件大小: {file_size:.1f}KB, 总用时: {total_end_time-total_start_time:.2f}秒")
        logger.info("=" * 50)
        
        return {
            "complete_audio": {
                "path": complete_path,
                "total_entries": len(entries),
                "file_size_kb": file_size
            }
        }

def get_current_time_str() -> str:
    """获取当前时间的格式化字符串"""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def clean_old_batches(days=7):
    """
    清理指定天数之前的批次文件
    
    Args:
        days: 超过多少天的批次将被清理，默认为7天
    
    Returns:
        int: 被清理的批次数量
    """
    logger.info(f"开始清理超过 {days} 天的旧批次...")
    batches_dir = "batches"
    if not os.path.exists(batches_dir):
        logger.warning(f"批次目录不存在: {batches_dir}")
        return 0
    
    # 计算截止日期
    cutoff_date = datetime.now() - timedelta(days=days)
    logger.info(f"清理截止日期: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 获取所有批次目录
    batch_dirs = [os.path.join(batches_dir, d) for d in os.listdir(batches_dir) 
                 if os.path.isdir(os.path.join(batches_dir, d))]
    
    cleaned_count = 0
    for batch_dir in batch_dirs:
        try:
            # 检查批次信息文件
            info_file = os.path.join(batch_dir, "info.json")
            
            # 如果没有info.json，使用目录的创建时间
            if not os.path.exists(info_file):
                dir_stat = os.stat(batch_dir)
                created_time = datetime.fromtimestamp(dir_stat.st_ctime)
                if created_time < cutoff_date:
                    logger.info(f"清理旧批次目录(无信息文件): {batch_dir}, 创建时间: {created_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    shutil.rmtree(batch_dir)
                    cleaned_count += 1
                continue
            
            # 读取批次信息
            import json
            with open(info_file, "r", encoding="utf-8") as f:
                batch_info = json.load(f)
            
            # 检查创建时间
            created_at = batch_info.get("created_at")
            if created_at:
                try:
                    # 将字符串转换为日期时间对象
                    batch_date = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                    if batch_date < cutoff_date:
                        logger.info(f"清理旧批次: {batch_dir}, 创建时间: {created_at}")
                        shutil.rmtree(batch_dir)
                        cleaned_count += 1
                except ValueError:
                    logger.warning(f"无法解析批次创建时间: {created_at}, 使用文件修改时间")
                    file_stat = os.stat(info_file)
                    mod_time = datetime.fromtimestamp(file_stat.st_mtime)
                    if mod_time < cutoff_date:
                        logger.info(f"清理旧批次(基于文件修改时间): {batch_dir}, 修改时间: {mod_time.strftime('%Y-%m-%d %H:%M:%S')}")
                        shutil.rmtree(batch_dir)
                        cleaned_count += 1
            else:
                # 使用文件修改时间
                file_stat = os.stat(info_file)
                mod_time = datetime.fromtimestamp(file_stat.st_mtime)
                if mod_time < cutoff_date:
                    logger.info(f"清理旧批次(无创建时间记录): {batch_dir}, 修改时间: {mod_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    shutil.rmtree(batch_dir)
                    cleaned_count += 1
        
        except Exception as e:
            logger.error(f"清理批次失败: {batch_dir}, 错误: {str(e)}")
    
    logger.info(f"批次清理完成，共清理 {cleaned_count} 个旧批次")
    return cleaned_count 