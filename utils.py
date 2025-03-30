import os
import re
import asyncio
import edge_tts
import uuid
from typing import List, Dict, Any
import tempfile
import logging
import subprocess

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def get_available_voices() -> List[Dict[str, Any]]:
    """Get a list of available voices from Edge TTS"""
    voices_manager = await edge_tts.VoicesManager.create()
    return voices_manager.voices

async def get_chinese_voices() -> List[Dict[str, Any]]:
    """Get a list of Chinese voices from Edge TTS"""
    voices = await get_available_voices()
    return [voice for voice in voices if voice["Locale"].startswith("zh-")]

def parse_shici_file(file_path: str) -> List[Dict[str, str]]:
    """
    Parse the shici.txt file and extract individual entries
    
    Returns a list of dictionaries with keys:
    - number: entry number
    - character: Chinese character
    - pinyin: pronunciation in pinyin
    - content: full content of the entry
    """
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Split by numbered entries (e.g., "1. 比 (bǐ)")
    entries_raw = re.split(r'(\d+\.\s+.+?\([^)]+\))', content)[1:]
    
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
    
    return entries

def group_entries_for_tts(entries: List[Dict[str, str]], max_chars: int = 8000) -> List[List[Dict[str, str]]]:
    """
    将词条分组，每组不超过最大字符数限制
    
    Args:
        entries: 词条列表
        max_chars: 每组最大字符数
    
    Returns:
        分组后的词条列表
    """
    groups = []
    current_group = []
    current_length = 0
    
    for entry in entries:
        entry_length = len(entry["content"])
        
        # 如果单个条目超过最大长度，需要单独处理
        if entry_length > max_chars:
            # 如果当前组不为空，先添加
            if current_group:
                groups.append(current_group)
                current_group = []
                current_length = 0
            
            # 将过长的条目单独作为一组
            groups.append([entry])
            continue
        
        # 如果添加当前条目后超过最大长度，创建新组
        if current_length + entry_length > max_chars:
            groups.append(current_group)
            current_group = [entry]
            current_length = entry_length
        else:
            current_group.append(entry)
            current_length += entry_length
    
    # 添加最后一组
    if current_group:
        groups.append(current_group)
    
    return groups

async def convert_text_to_speech(text: str, voice: str, rate: str = "+0%", volume: str = "+0%", pitch: str = "+0Hz", output_path: str = None) -> str:
    """
    Convert text to speech using Edge TTS
    
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
    if output_path is None:
        os.makedirs("static/audio", exist_ok=True)
        output_path = f"static/audio/{uuid.uuid4()}.mp3"
    
    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch)
    await communicate.save(output_path)
    
    return output_path

def merge_audio_files(audio_files: List[str], output_file: str) -> str:
    """
    合并多个音频文件为一个，使用二进制拼接方法
    
    Args:
        audio_files: 要合并的音频文件路径列表
        output_file: 输出文件路径
    
    Returns:
        合并后的音频文件路径
    """
    if not audio_files:
        raise ValueError("No audio files to merge")
    
    # 如果只有一个文件，直接返回
    if len(audio_files) == 1:
        return audio_files[0]
    
    try:
        # 尝试使用 ffmpeg 合并文件
        if is_ffmpeg_available():
            return merge_with_ffmpeg(audio_files, output_file)
        
        # 如果 ffmpeg 不可用，使用二进制文件拼接方法
        logger.info(f"使用二进制拼接方法合并 {len(audio_files)} 个音频文件")
        with open(output_file, 'wb') as outfile:
            for audio_file in audio_files:
                if os.path.exists(audio_file):
                    with open(audio_file, 'rb') as infile:
                        outfile.write(infile.read())
        
        logger.info(f"合并了 {len(audio_files)} 个音频文件到 {output_file}")
        return output_file
    
    except Exception as e:
        logger.error(f"合并音频文件失败: {str(e)}")
        # 如果合并失败，返回第一个文件
        return audio_files[0]

def is_ffmpeg_available() -> bool:
    """检查系统中是否可用 ffmpeg"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                             stdout=subprocess.PIPE, 
                             stderr=subprocess.PIPE,
                             text=True)
        return result.returncode == 0
    except Exception:
        return False

def merge_with_ffmpeg(audio_files: List[str], output_file: str) -> str:
    """使用 ffmpeg 合并音频文件"""
    try:
        # 创建临时文件列表
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
            list_file = f.name
            for audio_file in audio_files:
                f.write(f"file '{os.path.abspath(audio_file)}'\n")
        
        # 调用 ffmpeg 合并文件
        cmd = [
            'ffmpeg', 
            '-f', 'concat', 
            '-safe', '0', 
            '-i', list_file, 
            '-c', 'copy', 
            output_file
        ]
        
        subprocess.run(cmd, check=True)
        
        # 删除临时文件
        os.unlink(list_file)
        
        logger.info(f"使用 ffmpeg 合并了 {len(audio_files)} 个音频文件到 {output_file}")
        return output_file
    
    except Exception as e:
        logger.error(f"使用 ffmpeg 合并失败: {str(e)}")
        # 如果 ffmpeg 失败，尝试使用二进制拼接
        with open(output_file, 'wb') as outfile:
            for audio_file in audio_files:
                if os.path.exists(audio_file):
                    with open(audio_file, 'rb') as infile:
                        outfile.write(infile.read())
        return output_file

async def process_shici_entries(entries: List[Dict[str, str]], voice: str, rate: str = "+0%", volume: str = "+0%", pitch: str = "+0Hz", output_dir: str = "static/audio") -> Dict[str, Any]:
    """
    Process shici entries and convert them to speech, then merge into groups
    
    Args:
        entries: List of entry dictionaries
        voice: Voice to use
        rate: Speed of speech (e.g., "+0%", "-50%", "+50%")
        volume: Volume of speech (e.g., "+0%", "-50%", "+50%")
        pitch: Pitch of speech (e.g., "+0Hz", "-50Hz", "+50Hz")
        output_dir: Directory to save audio files
        
    Returns:
        Dictionary with individual and merged audio file information
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # 将词条分组
    grouped_entries = group_entries_for_tts(entries)
    logger.info(f"将 {len(entries)} 个词条分成了 {len(grouped_entries)} 组")
    
    # 处理每组词条
    merged_results = []
    individual_results = []
    
    for group_idx, group in enumerate(grouped_entries):
        # 准备该组的合并文本
        group_text = "\n\n".join([entry["content"] for entry in group])
        
        # 每组生成一个合并的音频文件
        group_filename = f"{output_dir}/shici_group_{group_idx+1}_{uuid.uuid4()}.mp3"
        await convert_text_to_speech(group_text, voice, rate, volume, pitch, group_filename)
        
        # 记录该组信息
        merged_results.append({
            "group_id": group_idx+1,
            "path": group_filename,
            "entries": [{"id": entry["number"], "character": entry["character"], "pinyin": entry["pinyin"]} for entry in group]
        })
        
        # 同时也为每个词条生成单独的音频
        for entry in group:
            output_filename = f"{output_dir}/shici_{entry['number']}_{uuid.uuid4()}.mp3"
            await convert_text_to_speech(entry['content'], voice, rate, volume, pitch, output_filename)
            
            individual_results.append({
                "id": entry['number'],
                "character": entry['character'],
                "pinyin": entry['pinyin'],
                "path": output_filename
            })
    
    # 生成一个包含所有词条的完整音频
    if grouped_entries:
        all_group_files = [group["path"] for group in merged_results]
        complete_filename = f"{output_dir}/shici_complete_{uuid.uuid4()}.mp3"
        
        try:
            # 使用改进的合并方法合并所有组音频
            complete_path = merge_audio_files(all_group_files, complete_filename)
            
            return {
                "complete_audio": {
                    "path": complete_path,
                    "total_entries": len(entries)
                },
                "group_audio": merged_results,
                "individual_audio": individual_results
            }
        
        except Exception as e:
            logger.error(f"合并完整音频失败: {str(e)}")
    
    return {
        "group_audio": merged_results,
        "individual_audio": individual_results
    } 