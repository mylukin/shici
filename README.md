# 古文语音合成工具

这是一个基于 FastAPI 和 Edge TTS 的古文语音合成工具，可以将文言文转换为语音。

## 特性

- 单句文本转语音（不刷新页面）
- 批量从 TXT 文件转换，支持批次号管理
- 可调节语速、音量和音调
- 自定义选择语音
- 支持多用户同时处理不同文件
- 批处理过程中可随时停止
- 批次管理和自动清理功能
- 响应式设计，适配移动设备

## 安装

### 前提条件
- Python 3.7+
- FFmpeg (用于音频合并，推荐但非必需)

### 步骤

1. 克隆此仓库:
   ```
   git clone https://github.com/mylukin/shici.git
   cd shici
   ```

2. 初始化并更新子模块:
   ```
   git submodule init
   git submodule update
   ```

3. 创建并激活虚拟环境:
   ```
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   venv\Scripts\activate     # Windows
   ```

4. 安装依赖:
   ```
   pip install -r requirements.txt
   ```

5. 启动应用:
   ```
   python app.py
   ```
   或者使用 uvicorn:
   ```
   uvicorn app:app --host 0.0.0.0 --port 8000 --reload
   ```

6. 打开浏览器访问 `http://localhost:8000`

## 使用方法

### 单句转换
1. 在主页的文本框中输入要转换的文本
2. 选择语音、调整速度、音量和音调
3. 点击"转换"按钮（音频将直接在页面中播放，无需刷新）

### 从文件批量转换
1. 上传 TXT 文本文件
2. 选择语音和参数
3. 点击"转换"按钮
4. 系统会生成一个唯一的批次号，并显示处理进度
5. 可以通过批次号 URL (`/upload_file?no=batch_id`) 随时查看处理状态
6. 处理过程中可点击"停止"按钮随时中断处理

### 批次管理
- 每个批次都有唯一的ID，可通过 URL 访问
- 生成的音频按批次保存在独立目录中
- 系统支持自动清理旧批次（默认7天）
- 多用户可同时处理不同批次，互不干扰

## 多用户支持

系统支持多个用户同时使用：
- 每个批处理任务有独立的批次ID和资源
- 线程安全的WebSocket连接管理
- 全局锁保证共享资源的安全访问
- 不同批次的资源隔离，避免冲突

## 调试模式

系统支持调试模式，可通过环境变量 `DEBUG_MODE` 开启：

```bash
# Linux/Mac
export DEBUG_MODE=true
python app.py

# Windows (PowerShell)
$env:DEBUG_MODE="true"
python app.py

# Windows (CMD)
set DEBUG_MODE=true
python app.py
```

在调试模式下：
- 日志级别会设为 DEBUG，输出更详细的信息
- 日志格式会包含更多调试信息
- 批处理过程中会记录每一个关键步骤
- 所有日志同时写入文件 (app.log)

### 日志系统

系统有完善的日志系统：
- 正常模式下只输出关键日志信息
- 调试模式下输出详细的过程信息
- 所有批处理过程都有进度和时间记录
- 文件操作和音频合并过程有详细记录
- 错误信息会被完整捕获并记录

## Edge TTS 子模块

本项目使用 Edge TTS 作为语音合成引擎，它作为 Git 子模块集成到项目中：

### 关于 Edge TTS
- Edge TTS 是一个允许使用微软 Edge 浏览器在线文本转语音服务的 Python 模块
- 提供高质量的多语言语音合成能力，支持中文在内的多种语言
- 允许调整语速、音量和音调
- 支持生成音频文件和字幕文件

### 子模块管理
- 子模块路径：`edge-tts/`
- 初始化：使用 `git submodule init` 和 `git submodule update` 命令
- 更新：使用 `git submodule update --remote` 命令获取最新版本

## 项目结构

```
shici/
├── app.py            # FastAPI 应用主文件
├── utils.py          # 工具函数，包含 TTS 和文件处理逻辑
├── requirements.txt  # 项目依赖
├── edge-tts/         # Edge TTS 子模块
├── static/           # 静态文件
│   └── audio/        # 生成的单句音频文件
├── templates/        # HTML 模板
│   └── index.html    # 主页模板
├── uploads/          # 上传的文件
└── batches/          # 批次处理目录
    └── {batch_id}/   # 每个批次的独立目录
        ├── info.json     # 批次信息
        ├── complete.mp3  # 合并后的完整音频
        └── audio/        # 批次音频片段
```

## REST API

系统提供多个API端点：

- `POST /api/convert`: 单句文本转语音，返回JSON响应
- `POST /api/stop_batch/{batch_id}`: 停止指定批次的处理
- `POST /api/clean_old_batches`: 清理旧批次文件

## WebSocket

系统使用WebSocket提供实时进度更新：

- 连接: `/ws/{batch_id}`
- 消息类型: 
  - `info`: 信息消息
  - `error`: 错误消息
  - `audio`: 音频片段生成
  - `complete`: 处理完成
  - `stopped`: 处理被停止

## 技术栈

- FastAPI: Web 框架
- Edge TTS: 微软 Edge 浏览器的文本转语音引擎
- Jinja2: HTML 模板引擎
- WebSockets: 实时通信
- Pydub/FFmpeg: 音频处理
- psutil: 进程管理和监控

## 许可

MIT License

Copyright (c) 2023-2024 Lukin

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE. 