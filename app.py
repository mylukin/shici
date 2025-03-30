import os
import re
import uuid
import json
import asyncio
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import edge_tts
import logging
from typing import List, Dict, Optional, Set, Any
import utils
import shutil
import threading

# 配置日志
DEBUG_MODE = os.environ.get('DEBUG_MODE', 'false').lower() in ['true', '1', 'yes']
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s' if DEBUG_MODE else '%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# 初始化应用
logger.info(f"初始化应用，调试模式：{'开启' if DEBUG_MODE else '关闭'}")
app = FastAPI()

# 静态文件和模板
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/batches", StaticFiles(directory="batches"), name="batches")
templates = Jinja2Templates(directory="templates")

# 确保文件夹存在
os.makedirs("static/audio", exist_ok=True)
os.makedirs("uploads", exist_ok=True)
os.makedirs("batches", exist_ok=True)

# 全局变量和锁
chinese_voices = []
active_batches = {}  # 活跃批次信息
batch_locks = {}     # 每个批次的锁，确保多用户同时处理不同批次时的线程安全
stop_requested = set()  # 请求停止的批次ID集合

# 全局锁，用于保护共享数据结构
global_lock = threading.Lock()

# WebSocket连接管理器
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_lock = threading.Lock()
    
    async def connect(self, websocket: WebSocket, batch_id: str):
        await websocket.accept()
        with self.connection_lock:
            self.active_connections[batch_id] = websocket
        logger.info(f"WebSocket连接建立: {batch_id}")
    
    def disconnect(self, batch_id: str):
        with self.connection_lock:
            if batch_id in self.active_connections:
                del self.active_connections[batch_id]
                logger.info(f"WebSocket连接关闭: {batch_id}")
    
    async def send_message(self, batch_id: str, message: str):
        with self.connection_lock:
            if batch_id in self.active_connections:
                await self.active_connections[batch_id].send_text(message)
                logger.debug(f"发送消息到 {batch_id}: {message[:100]}...")

manager = ConnectionManager()

@app.on_event("startup")
async def startup_event():
    """应用启动时执行的操作"""
    global chinese_voices
    logger.info("应用启动，正在获取可用语音...")
    try:
        chinese_voices = await utils.get_chinese_voices()
        logger.info(f"成功获取 {len(chinese_voices)} 个中文语音")
    except Exception as e:
        logger.error(f"获取语音失败: {str(e)}")
        chinese_voices = []

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """主页"""
    logger.info("访问主页")
    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request, 
            "voices": chinese_voices,
            "voice": "zh-CN-YunyangNeural"  # 设置默认语音
        }
    )

@app.get("/batch/{batch_id}")
async def get_batch(request: Request, batch_id: str):
    """批次处理页面"""
    logger.info(f"访问批次页面: {batch_id}")
    
    # 检查批次是否存在
    batch_dir = os.path.join("batches", batch_id)
    if not os.path.exists(batch_dir):
        logger.error(f"批次不存在: {batch_id}")
        return RedirectResponse(url="/")
    
    # 读取批次信息
    try:
        with open(os.path.join(batch_dir, "info.json"), "r", encoding="utf-8") as f:
            batch_info = json.load(f)
    except:
        logger.error(f"读取批次信息失败: {batch_id}")
        batch_info = {}
    
    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request,
            "voices": chinese_voices,
            "batch_id": batch_id,
            "voice": batch_info.get("voice", ""),
            "rate": batch_info.get("rate", "+0%"),
            "volume": batch_info.get("volume", "+0%"),
            "pitch": batch_info.get("pitch", "+0%"),
            "file_name": batch_info.get("file_name", "未知文件"),
            "file_location": batch_info.get("file_location", ""),
            "batch_process_started": True
        }
    )

@app.get("/convert")
async def convert_text_get():
    """处理对/convert的GET请求，重定向到主页"""
    logger.info("收到对/convert的GET请求，重定向到主页")
    return RedirectResponse(url="/")

@app.post("/convert")
async def convert_text(
    request: Request,
    text: str = Form(...),
    voice: str = Form(...),
    rate: str = Form("+0%"),
    volume: str = Form("+0%"),
    pitch: str = Form("+0Hz")
):
    """转换文本为语音 - 传统方式，返回页面"""
    # 确保参数格式正确
    if rate and not rate.endswith('%'):
        rate = f"{'+' if int(rate) >= 0 else ''}{rate}%"
    if volume and not volume.endswith('%'):
        volume = f"{'+' if int(volume) >= 0 else ''}{volume}%"
    if pitch and not pitch.endswith('Hz'):
        pitch = f"{'+' if int(pitch) >= 0 else ''}{pitch}Hz"
        
    logger.info(f"接收文本转语音请求: voice={voice}, rate={rate}, volume={volume}, pitch={pitch}")
    logger.info(f"文本长度: {len(text)} 字符")
    
    try:
        audio_path = await utils.convert_text_to_speech(text, voice, rate, volume, pitch)
        logger.info(f"转换成功，输出文件: {audio_path}")
        
        return templates.TemplateResponse(
            "index.html", 
            {
                "request": request,
                "voices": chinese_voices,
                "audio_path": audio_path,
                "text": text,
                "voice": voice,
                "rate": rate,
                "volume": volume,
                "pitch": pitch
            }
        )
    except Exception as e:
        logger.error(f"转换失败: {str(e)}")
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "voices": chinese_voices,
                "error": f"转换失败: {str(e)}",
                "text": text,
                "voice": voice,
                "rate": rate,
                "volume": volume,
                "pitch": pitch
            }
        )

@app.post("/api/convert")
async def api_convert_text(
    text: str = Form(...),
    voice: str = Form(...),
    rate: str = Form("+0%"),
    volume: str = Form("+0%"),
    pitch: str = Form("+0Hz")
):
    """API端点：转换文本为语音 - 返回JSON"""
    # 确保参数格式正确
    if rate and not rate.endswith('%'):
        rate = f"{'+' if int(rate) >= 0 else ''}{rate}%"
    if volume and not volume.endswith('%'):
        volume = f"{'+' if int(volume) >= 0 else ''}{volume}%"
    if pitch and not pitch.endswith('Hz'):
        pitch = f"{'+' if int(pitch) >= 0 else ''}{pitch}Hz"
        
    logger.info(f"API接收文本转语音请求: voice={voice}, rate={rate}, volume={volume}, pitch={pitch}")
    logger.info(f"文本长度: {len(text)} 字符")
    
    try:
        audio_path = await utils.convert_text_to_speech(text, voice, rate, volume, pitch)
        logger.info(f"API转换成功，输出文件: {audio_path}")
        
        return JSONResponse({
            "success": True,
            "audio_path": audio_path
        })
    except Exception as e:
        logger.error(f"API转换失败: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        })

@app.get("/upload_file")
async def upload_file_get(request: Request, no: str = None):
    """处理对/upload_file的GET请求
    如果有no参数，则显示特定批次的处理页面
    否则重定向到文件上传标签页
    """
    if no:
        logger.info(f"访问批次处理页面，批次号: {no}")
        # 检查批次是否存在
        batch_dir = os.path.join("batches", no)
        if not os.path.exists(batch_dir):
            logger.error(f"批次不存在: {no}")
            return RedirectResponse(url="/?tab=fileUpload")
        
        # 读取批次信息
        try:
            with open(os.path.join(batch_dir, "info.json"), "r", encoding="utf-8") as f:
                batch_info = json.load(f)
        except:
            logger.error(f"读取批次信息失败: {no}")
            batch_info = {}
        
        return templates.TemplateResponse(
            "index.html", 
            {
                "request": request,
                "voices": chinese_voices,
                "batch_id": no,
                "voice": batch_info.get("voice", ""),
                "rate": batch_info.get("rate", "+0%"),
                "volume": batch_info.get("volume", "+0%"),
                "pitch": batch_info.get("pitch", "+0%"),
                "file_name": batch_info.get("file_name", "未知文件"),
                "file_location": batch_info.get("file_location", ""),
                "batch_process_started": True
            }
        )
    else:
        logger.info("收到对/upload_file的GET请求，重定向到文件上传标签页")
        return RedirectResponse(url="/?tab=fileUpload")

@app.post("/upload_file")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    voice: str = Form(...),
    rate: str = Form("+0%"),
    volume: str = Form("+0%"),
    pitch: str = Form("+0Hz")
):
    """上传文本文件并转换为语音 - 创建批次并重定向到/upload_file?no=batch_id页面"""
    # 确保参数格式正确
    if rate and not rate.endswith('%'):
        rate = f"{'+' if int(rate) >= 0 else ''}{rate}%"
    if volume and not volume.endswith('%'):
        volume = f"{'+' if int(volume) >= 0 else ''}{volume}%"
    if pitch and not pitch.endswith('Hz'):
        pitch = f"{'+' if int(pitch) >= 0 else ''}{pitch}Hz"
        
    logger.info(f"接收文件转语音请求: voice={voice}, rate={rate}, volume={volume}, pitch={pitch}")
    logger.info(f"文件名: {file.filename}")
    
    # 生成唯一的batch_id用于WebSocket连接和批次管理
    batch_id = str(uuid.uuid4())
    
    # 创建批次目录
    batch_dir = os.path.join("batches", batch_id)
    batch_audio_dir = os.path.join(batch_dir, "audio")
    os.makedirs(batch_dir, exist_ok=True)
    os.makedirs(batch_audio_dir, exist_ok=True)
    
    # 保存上传的文件
    file_location = os.path.join(batch_dir, f"source_{file.filename}")
    try:
        with open(file_location, "wb") as f:
            content = await file.read()
            f.write(content)
        
        logger.info(f"文件已保存到: {file_location}, 大小: {len(content)} 字节")
        
        # 保存批次信息
        batch_info = {
            "batch_id": batch_id,
            "voice": voice,
            "rate": rate,
            "volume": volume,
            "pitch": pitch,
            "file_name": file.filename,
            "file_location": file_location,
            "created_at": utils.get_current_time_str()
        }
        
        with open(os.path.join(batch_dir, "info.json"), "w", encoding="utf-8") as f:
            json.dump(batch_info, f, ensure_ascii=False, indent=2)
        
        # 创建批次锁并将批次信息添加到全局管理中
        with global_lock:
            batch_locks[batch_id] = threading.Lock()
            active_batches[batch_id] = batch_info
        
        # 重定向到URL格式: /upload_file?no=batch_id
        return RedirectResponse(url=f"/upload_file?no={batch_id}", status_code=303)
    except Exception as e:
        logger.error(f"文件上传失败: {str(e)}")
        # 清理创建的目录
        shutil.rmtree(batch_dir, ignore_errors=True)
        
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "voices": chinese_voices,
                "error": f"文件上传失败: {str(e)}",
                "voice": voice,
                "rate": rate,
                "volume": volume,
                "pitch": pitch
            }
        )

@app.post("/api/stop_batch/{batch_id}")
async def stop_batch(batch_id: str):
    """API端点: 停止批次处理"""
    logger.info(f"收到停止批次处理请求: {batch_id}")
    
    # 检查批次目录是否存在
    batch_dir = os.path.join("batches", batch_id)
    if not os.path.exists(batch_dir):
        logger.error(f"批次不存在: {batch_id}")
        return JSONResponse({
            "success": False,
            "error": "批次不存在或已被删除"
        })
    
    # 添加到停止请求集合
    with global_lock:
        stop_requested.add(batch_id)
        logger.info(f"已将批次 {batch_id} 添加到停止请求集合")
    
    # 终止与批次关联的所有进程
    try:
        success = utils.terminate_batch_processes(batch_id)
        logger.info(f"批次进程终止{'成功' if success else '失败但继续处理'}: {batch_id}")
    except Exception as e:
        logger.error(f"终止批次进程时出错: {str(e)}")
        success = False
    
    # 更新批次状态为已停止
    update_batch_status(batch_id, "stopped", "用户请求停止")
    
    # 发送停止消息给所有连接的客户端
    try:
        await manager.send_message(batch_id, json.dumps({
            "type": "stopped",
            "message": "处理已停止 - 用户请求停止"
        }))
    except Exception as e:
        logger.error(f"发送停止消息失败: {str(e)}")
    
    # 返回成功响应
    logger.info(f"批次已成功标记为停止: {batch_id}")
    return JSONResponse({
        "success": True,
        "message": "已停止批次处理并终止相关进程"
    })

@app.websocket("/ws/{batch_id}")
async def websocket_endpoint(websocket: WebSocket, batch_id: str):
    """WebSocket连接端点，用于实时更新生成的音频信息"""
    await manager.connect(websocket, batch_id)
    processing_lock = None
    
    try:
        # 接收初始消息，包含处理参数
        data = await websocket.receive_text()
        params = json.loads(data)
        logger.info(f"通过WebSocket接收处理参数: {params}")
        
        # 注册当前进程
        utils.register_process(batch_id, os.getpid())
        logger.info(f"注册主WebSocket进程 {os.getpid()} 到批次 {batch_id}")
        
        # 检查是否是停止请求
        if params.get("action") == "stop":
            logger.info(f"收到直接停止请求: {batch_id}")
            with global_lock:
                stop_requested.add(batch_id)
            
            # 终止与批次关联的所有进程
            try:
                utils.terminate_batch_processes(batch_id)
            except Exception as e:
                logger.error(f"终止批次进程时出错: {str(e)}")
            
            # 更新批次状态
            update_batch_status(batch_id, "stopped", "用户请求停止")
            
            await manager.send_message(batch_id, json.dumps({
                "type": "stopped",
                "message": "处理已停止"
            }))
            return
        
        voice = params.get("voice", "zh-CN-YunyangNeural")
        rate = params.get("rate", "+0%")
        volume = params.get("volume", "+0%")
        pitch = params.get("pitch", "+0Hz")
        file_location = params.get("file_location", "")
        is_refresh = params.get("refresh", False)  # 判断是否为页面刷新
        
        # 确保参数格式正确
        if rate and not rate.endswith('%'):
            rate = f"{'+' if int(rate) >= 0 else ''}{rate}%"
        if volume and not volume.endswith('%'):
            volume = f"{'+' if int(volume) >= 0 else ''}{volume}%"
        if pitch and not pitch.endswith('Hz'):
            pitch = f"{'+' if int(pitch) >= 0 else ''}{pitch}Hz"
        
        logger.info(f"处理参数格式化后: voice={voice}, rate={rate}, volume={volume}, pitch={pitch}, 是否刷新: {is_refresh}")
        
        # 检查批次目录
        batch_dir = os.path.join("batches", batch_id)
        batch_audio_dir = os.path.join(batch_dir, "audio")
        batch_info_file = os.path.join(batch_dir, "info.json")
        segments_file = os.path.join(batch_dir, "segments.json")
        
        # 确保目录存在
        if not os.path.exists(batch_dir):
            os.makedirs(batch_dir, exist_ok=True)
        if not os.path.exists(batch_audio_dir):
            os.makedirs(batch_audio_dir, exist_ok=True)
        
        # 首先检查批次状态，无论是否能获取锁
        batch_status = ""
        if os.path.exists(batch_info_file):
            try:
                with open(batch_info_file, "r", encoding="utf-8") as f:
                    batch_info = json.load(f)
                batch_status = batch_info.get("status", "")
                logger.info(f"批次 {batch_id} 当前状态: {batch_status}")
            except Exception as e:
                logger.error(f"读取批次信息失败: {str(e)}")
        
        # 如果是刷新页面但批次没有状态（新批次）或正在处理中，应该继续执行而非恢复
        should_process = not batch_status or batch_status == "processing"
        
        # 如果是页面刷新且批次已完成/已停止/错误，则直接发送状态而不获取锁
        if is_refresh and not should_process and batch_status in ["completed", "stopped", "error"]:
            logger.info(f"页面刷新且批次已完成/停止/错误，直接发送当前状态而不重新处理")
            await check_and_send_batch_status(batch_id, websocket, batch_dir, batch_audio_dir, batch_info_file)
            return
        
        # 获取批次锁，防止重复处理
        with global_lock:
            if batch_id not in batch_locks:
                batch_locks[batch_id] = threading.Lock()
            processing_lock = batch_locks[batch_id]
        
        # 尝试获取锁，如果已被占用则表明有其他线程在处理
        if not processing_lock.acquire(blocking=False):
            logger.info(f"批次 {batch_id} 已在处理中，发送当前状态并返回")
            await check_and_send_batch_status(batch_id, websocket, batch_dir, batch_audio_dir, batch_info_file)
            return
        
        # 成功获取锁，现在检查批次状态
        try:
            if os.path.exists(batch_info_file):
                try:
                    with open(batch_info_file, "r", encoding="utf-8") as f:
                        batch_info = json.load(f)
                    
                    # 如果批次已完成或已停止，发送历史数据并返回
                    status = batch_info.get("status", "")
                    if status in ["completed", "stopped"]:
                        logger.info(f"批次 {batch_id} 已{status}，发送历史数据")
                        processing_lock.release()
                        await check_and_send_batch_status(batch_id, websocket, batch_dir, batch_audio_dir, batch_info_file)
                        return
                    
                    # 如果批次处于错误状态，检查是否需要重新开始
                    if status == "error":
                        error_message = batch_info.get("error", "未知错误")
                        await manager.send_message(batch_id, json.dumps({
                            "type": "info",
                            "message": f"上次处理失败 ({error_message})，正在重新尝试..."
                        }))
                        # 不返回，继续处理
                except Exception as e:
                    logger.error(f"读取批次信息失败: {str(e)}")
                    # 继续处理
        except Exception as e:
            logger.error(f"检查批次状态时出错: {str(e)}")
        
        # 处理批次
        logger.info(f"获取到批次 {batch_id} 的处理锁，开始处理")
        
        try:
            # 检查上传的文件是否存在
            if not os.path.exists(file_location):
                await manager.send_message(batch_id, json.dumps({
                    "type": "error",
                    "message": f"找不到上传的文件: {file_location}"
                }))
                return
            
            # 读取文件内容
            try:
                with open(file_location, "r", encoding="utf-8") as f:
                    text = f.read()
                
                await manager.send_message(batch_id, json.dumps({
                    "type": "info",
                    "message": f"成功读取文件，文本长度: {len(text)} 字符，当前时间: {utils.get_current_time_str()}"
                }))
            except Exception as e:
                await manager.send_message(batch_id, json.dumps({
                    "type": "error",
                    "message": f"读取文件失败: {str(e)}"
                }))
                return
            
            # 分割文本为段落，只按照\n\n分割
            segments = split_text_to_segments(text)
            total_segments = len(segments)
            
            await manager.send_message(batch_id, json.dumps({
                "type": "info",
                "message": f"文本已分割为 {total_segments} 个段落"
            }))
            
            # 更新状态为处理中
            update_batch_status(batch_id, "processing")
            
            # 记录段落信息
            segments_info = []
            for idx, segment in enumerate(segments):
                segment_idx = idx + 1
                segment_text = segment.strip()
                if segment_text:
                    segments_info.append({
                        "id": segment_idx,
                        "text": segment_text[:100] + ("..." if len(segment_text) > 100 else ""),
                        "full_text": segment_text,
                        "status": "pending",
                        "timestamp": utils.get_current_time_str()
                    })
            
            # 保存段落信息
            with open(segments_file, "w", encoding="utf-8") as f:
                json.dump(segments_info, f, ensure_ascii=False, indent=2)
            
            # 处理每个文本段落并生成音频
            audio_files = []
            
            for idx, segment in enumerate(segments):
                segment_idx = idx + 1
                
                # 检查是否请求停止
                with global_lock:
                    if batch_id in stop_requested:
                        logger.info(f"批次处理已停止: {batch_id}")
                        await manager.send_message(batch_id, json.dumps({
                            "type": "stopped",
                            "message": "处理已停止"
                        }))
                        
                        # 更新批次状态
                        update_batch_status(batch_id, "stopped", "用户请求停止")
                        return
                
                segment_text = segment.strip()
                if not segment_text:
                    continue
                
                # 更新段落状态为处理中
                if idx < len(segments_info):
                    segments_info[idx]["status"] = "processing"
                    segments_info[idx]["timestamp"] = utils.get_current_time_str()
                    with open(segments_file, "w", encoding="utf-8") as f:
                        json.dump(segments_info, f, ensure_ascii=False, indent=2)
                
                # 生成音频文件名
                output_filename = os.path.join(batch_audio_dir, f"segment_{segment_idx}.mp3")
                web_path = f"/batches/{batch_id}/audio/segment_{segment_idx}.mp3"
                
                try:
                    # 转换文本段落为语音，并提供批次ID用于进程管理
                    await utils.convert_text_to_speech(
                        segment_text, 
                        voice, 
                        rate, 
                        volume, 
                        pitch, 
                        output_filename,
                        batch_id
                    )
                    
                    # 添加到音频文件列表
                    audio_files.append(output_filename)
                    
                    # 更新段落状态为完成
                    if idx < len(segments_info):
                        segments_info[idx]["status"] = "completed"
                        segments_info[idx]["timestamp"] = utils.get_current_time_str()
                        with open(segments_file, "w", encoding="utf-8") as f:
                            json.dump(segments_info, f, ensure_ascii=False, indent=2)
                    
                    # 发送进度信息到前端
                    segment_preview = segment_text[:50] + "..." if len(segment_text) > 50 else segment_text
                    segment_info = {
                        "id": segment_idx,
                        "text": segment_preview,
                        "path": web_path,
                        "segment_idx": segment_idx,
                        "total_segments": total_segments
                    }
                    
                    await manager.send_message(batch_id, json.dumps({
                        "type": "audio",
                        "data": segment_info
                    }))
                    
                except Exception as e:
                    error_message = str(e)
                    logger.error(f"转换段落 {segment_idx} 失败: {error_message}")
                    
                    # 如果是停止请求导致的错误，则正常处理
                    if "处理已停止" in error_message:
                        await manager.send_message(batch_id, json.dumps({
                            "type": "stopped",
                            "message": "处理已停止"
                        }))
                        
                        # 更新段落和批次状态
                        if idx < len(segments_info):
                            segments_info[idx]["status"] = "stopped"
                            segments_info[idx]["timestamp"] = utils.get_current_time_str()
                            with open(segments_file, "w", encoding="utf-8") as f:
                                json.dump(segments_info, f, ensure_ascii=False, indent=2)
                        
                        update_batch_status(batch_id, "stopped", "用户请求停止")
                        return
                    
                    # 常规错误处理
                    # 更新段落状态为错误
                    if idx < len(segments_info):
                        segments_info[idx]["status"] = "error"
                        segments_info[idx]["error"] = error_message
                        segments_info[idx]["timestamp"] = utils.get_current_time_str()
                        with open(segments_file, "w", encoding="utf-8") as f:
                            json.dump(segments_info, f, ensure_ascii=False, indent=2)
                    
                    await manager.send_message(batch_id, json.dumps({
                        "type": "error",
                        "message": f"转换段落 {segment_idx} 失败: {error_message}"
                    }))
                    
                    # 检查是否有致命错误需要中断整个处理
                    if "No connection could be made" in error_message or "无法连接" in error_message:
                        await manager.send_message(batch_id, json.dumps({
                            "type": "error",
                            "message": "网络连接失败，处理中断"
                        }))
                        # 更新批次状态
                        update_batch_status(batch_id, "error", error_message)
                        return
            
            # 合并所有音频文件
            if audio_files:
                await manager.send_message(batch_id, json.dumps({
                    "type": "info",
                    "message": f"所有段落处理完成，正在合并 {len(audio_files)} 个音频文件..."
                }))
                
                # 生成合并后的音频文件名
                complete_filename = os.path.join(batch_dir, "complete.mp3")
                web_path = f"/batches/{batch_id}/complete.mp3"
                
                try:
                    # 合并音频文件
                    utils.merge_audio_files(audio_files, complete_filename)
                    
                    # 更新所有段落为已合并状态
                    for segment in segments_info:
                        if segment["status"] == "completed":
                            segment["status"] = "merged"
                    with open(segments_file, "w", encoding="utf-8") as f:
                        json.dump(segments_info, f, ensure_ascii=False, indent=2)
                    
                    # 发送合并后的音频信息
                    await manager.send_message(batch_id, json.dumps({
                        "type": "complete",
                        "data": {
                            "path": web_path,
                            "total_segments": len(audio_files),
                            "file_size_kb": os.path.getsize(complete_filename) / 1024
                        }
                    }))
                    
                    # 更新批次状态
                    update_batch_status(batch_id, "completed")
                    
                except Exception as e:
                    error_message = str(e)
                    logger.error(f"合并音频文件失败: {error_message}")
                    await manager.send_message(batch_id, json.dumps({
                        "type": "error",
                        "message": f"合并音频文件失败: {error_message}"
                    }))
                    
                    # 更新批次状态
                    update_batch_status(batch_id, "error", error_message)
            
            # 处理完成
            await manager.send_message(batch_id, json.dumps({
                "type": "finished"
            }))
            
        finally:
            # 无论处理成功与否，都释放处理锁
            if processing_lock and processing_lock.locked():
                processing_lock.release()
                logger.info(f"释放批次 {batch_id} 的处理锁")
    
    except WebSocketDisconnect:
        manager.disconnect(batch_id)
        logger.info(f"WebSocket连接断开: 批次 {batch_id}")
        if processing_lock and processing_lock.locked():
            processing_lock.release()
            logger.info(f"WebSocket断开连接，释放批次 {batch_id} 的处理锁")
    except Exception as e:
        error_message = str(e)
        logger.error(f"WebSocket处理异常: {error_message}")
        try:
            await manager.send_message(batch_id, json.dumps({
                "type": "error",
                "message": f"处理失败: {error_message}"
            }))
            
            # 更新批次状态
            update_batch_status(batch_id, "error", error_message)
            
        except:
            pass
        manager.disconnect(batch_id)
        if processing_lock and processing_lock.locked():
            processing_lock.release()
            logger.info(f"处理异常，释放批次 {batch_id} 的处理锁")
    finally:
        # 清理停止请求
        with global_lock:
            if batch_id in stop_requested:
                stop_requested.remove(batch_id)
                logger.info(f"已从停止请求集合中移除批次 {batch_id}")

async def check_and_send_batch_status(batch_id: str, websocket: WebSocket, batch_dir: str, batch_audio_dir: str, batch_info_file: str):
    """检查批次状态并发送历史数据"""
    try:
        # 读取批次信息
        batch_info = {}
        if os.path.exists(batch_info_file):
            try:
                with open(batch_info_file, "r", encoding="utf-8") as f:
                    batch_info = json.load(f)
                
                status = batch_info.get("status", "")
                
                # 发送批次状态信息
                await manager.send_message(batch_id, json.dumps({
                    "type": "info",
                    "message": f"批次状态: {status}"
                }))
                
                # 批次存在但状态为空（新批次）
                if not status:
                    await manager.send_message(batch_id, json.dumps({
                        "type": "info",
                        "message": "新批次将开始处理"
                    }))
                    return
                
                # 预先查找所有音频文件，按段落序号排序
                audio_files = []
                if os.path.exists(batch_audio_dir):
                    for f in os.listdir(batch_audio_dir):
                        if f.endswith('.mp3'):
                            match = re.search(r'segment_(\d+)', f)
                            if match:
                                segment_idx = int(match.group(1))
                                audio_files.append((segment_idx, f))
                    
                    # 按序号排序
                    audio_files.sort(key=lambda x: x[0])
                    
                    if audio_files:
                        await manager.send_message(batch_id, json.dumps({
                            "type": "info",
                            "message": f"找到 {len(audio_files)} 个已生成的音频段落"
                        }))
                
                # 如果有段落信息文件，读取详细信息
                segments_info = []
                segments_file = os.path.join(batch_dir, "segments.json")
                if os.path.exists(segments_file):
                    try:
                        with open(segments_file, "r", encoding="utf-8") as f:
                            segments_info = json.load(f)
                        
                        if segments_info:
                            total_segments = len(segments_info)
                            completed_segments = sum(1 for seg in segments_info if seg.get("status") in ["completed", "merged"])
                            
                            await manager.send_message(batch_id, json.dumps({
                                "type": "info",
                                "message": f"从段落信息恢复: 总计 {total_segments} 个段落，已完成 {completed_segments} 个"
                            }))
                    except Exception as e:
                        logger.error(f"读取段落信息失败: {str(e)}")
                
                # 处理音频文件，发送已完成的段落
                if audio_files:
                    # 发送每个段落的信息
                    for _, (segment_idx, file) in enumerate(audio_files):
                        web_path = f"/batches/{batch_id}/audio/{file}"
                        
                        # 尝试从segments.json获取文本信息
                        segment_text = f"段落 {segment_idx}"
                        for seg_info in segments_info:
                            if seg_info.get("id") == segment_idx:
                                segment_text = seg_info.get("text", segment_text)
                                break
                        
                        total_segs = len(segments_info) or len(audio_files)
                        
                        # 发送音频数据，标记为恢复的段落
                        await manager.send_message(batch_id, json.dumps({
                            "type": "audio",
                            "data": {
                                "id": segment_idx,
                                "text": segment_text,
                                "path": web_path,
                                "segment_idx": segment_idx,
                                "total_segments": total_segs
                            },
                            "is_restored": True  # 标记为恢复的段落
                        }))
                    
                    # 如果合并文件存在，发送完成信息
                    complete_path = os.path.join(batch_dir, "complete.mp3")
                    if os.path.exists(complete_path):
                        web_path = f"/batches/{batch_id}/complete.mp3"
                        await manager.send_message(batch_id, json.dumps({
                            "type": "complete",
                            "data": {
                                "path": web_path,
                                "total_segments": len(audio_files),
                                "file_size_kb": os.path.getsize(complete_path) / 1024
                            }
                        }))
                
                # 发送最终状态消息
                if status == "completed":
                    await manager.send_message(batch_id, json.dumps({
                        "type": "info",
                        "message": "批次处理已完成"
                    }))
                    await manager.send_message(batch_id, json.dumps({
                        "type": "finished"
                    }))
                elif status == "stopped":
                    await manager.send_message(batch_id, json.dumps({
                        "type": "info",
                        "message": "批次处理已停止"
                    }))
                    await manager.send_message(batch_id, json.dumps({
                        "type": "stopped",
                        "message": "处理已停止"
                    }))
                elif status == "error":
                    error_message = batch_info.get("error", "未知错误")
                    await manager.send_message(batch_id, json.dumps({
                        "type": "info",
                        "message": f"批次处理出错: {error_message}"
                    }))
                    await manager.send_message(batch_id, json.dumps({
                        "type": "error",
                        "message": f"处理失败: {error_message}"
                    }))
                elif status == "processing":
                    if audio_files:
                        await manager.send_message(batch_id, json.dumps({
                            "type": "info",
                            "message": "批次处理被中断，已显示已完成的部分。批次未标记为已完成。"
                        }))
                    else:
                        await manager.send_message(batch_id, json.dumps({
                            "type": "info",
                            "message": "批次正在处理中，等待处理完成..."
                        }))
            except Exception as e:
                logger.error(f"读取批次信息失败: {str(e)}")
                await manager.send_message(batch_id, json.dumps({
                    "type": "error",
                    "message": f"读取批次信息失败: {str(e)}"
                }))
        else:
            # 批次信息文件不存在
            await manager.send_message(batch_id, json.dumps({
                "type": "info",
                "message": "找不到批次信息，可能是新创建的批次，将开始处理"
            }))
            
    except Exception as e:
        logger.error(f"检查批次状态失败: {str(e)}")
        try:
            await manager.send_message(batch_id, json.dumps({
                "type": "error",
                "message": f"检查批次状态失败: {str(e)}"
            }))
        except:
            pass

@app.get("/download/{filename}")
async def download_file(filename: str):
    """下载生成的音频文件 (static/audio 目录中的文件)"""
    filepath = f"static/audio/{filename}"
    logger.info(f"尝试下载文件: {filepath}")
    
    if os.path.exists(filepath):
        logger.info(f"文件存在，开始下载: {filepath}")
        return FileResponse(filepath, filename=filename)
    else:
        logger.error(f"文件不存在: {filepath}")
        return {"error": "文件不存在"}

@app.get("/batches/{batch_id}/audio/{filename}")
async def get_batch_audio(batch_id: str, filename: str):
    """获取批次目录中的音频文件"""
    filepath = f"batches/{batch_id}/audio/{filename}"
    logger.info(f"尝试获取批次音频文件: {filepath}")
    
    if os.path.exists(filepath):
        return FileResponse(filepath)
    else:
        logger.error(f"批次音频文件不存在: {filepath}")
        raise HTTPException(status_code=404, detail="文件不存在")

@app.get("/batches/{batch_id}/{filename}")
async def get_batch_file(batch_id: str, filename: str):
    """获取批次目录中的文件"""
    filepath = f"batches/{batch_id}/{filename}"
    logger.info(f"尝试获取批次文件: {filepath}")
    
    if os.path.exists(filepath):
        return FileResponse(filepath)
    else:
        logger.error(f"批次文件不存在: {filepath}")
        raise HTTPException(status_code=404, detail="文件不存在")

@app.post("/api/clean_old_batches")
async def clean_old_batches(days: int = 7):
    """清理旧的批次文件"""
    logger.info(f"开始清理超过 {days} 天的旧批次...")
    
    try:
        cleaned = utils.clean_old_batches(days)
        return JSONResponse({
            "success": True,
            "message": f"已清理 {cleaned} 个旧批次"
        })
    except Exception as e:
        logger.error(f"清理旧批次失败: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        })

def update_batch_status(batch_id: str, status: str, error_message: str = None):
    """更新批次状态"""
    batch_dir = os.path.join("batches", batch_id)
    os.makedirs(batch_dir, exist_ok=True)
    
    batch_info_file = os.path.join(batch_dir, "info.json")
    
    # 读取现有信息（如果存在）
    batch_info = {}
    if os.path.exists(batch_info_file):
        try:
            with open(batch_info_file, "r", encoding="utf-8") as f:
                batch_info = json.load(f)
        except Exception as e:
            logger.error(f"读取批次信息失败: {str(e)}")
    
    # 更新状态
    batch_info["status"] = status
    batch_info["updated_at"] = utils.get_current_time_str()
    
    if error_message:
        batch_info["error"] = error_message
    
    # 保存更新后的信息
    try:
        with open(batch_info_file, "w", encoding="utf-8") as f:
            json.dump(batch_info, f, ensure_ascii=False, indent=2)
        logger.info(f"批次 {batch_id} 状态已更新为: {status}")
    except Exception as e:
        logger.error(f"保存批次信息失败: {str(e)}")

def split_text_to_segments(text: str) -> List[str]:
    """
    将文本分割为段落，只按照\n\n分割
    
    Args:
        text: 要分割的文本
        
    Returns:
        文本段落列表
    """
    # 按段落分割（双换行符）
    paragraphs = text.split('\n\n')
    
    # 过滤掉空段落
    segments = [para for para in paragraphs if para.strip()]
    
    return segments

if __name__ == "__main__":
    import uvicorn
    logger.info("以直接运行模式启动应用")
    uvicorn.run(app, host="0.0.0.0", port=8000) 