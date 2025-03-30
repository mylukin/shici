# 古文语音合成工具

一款专为中国古典文学爱好者设计的语音合成工具，能将古诗词、文言文等转换为自然流畅的语音。基于微软Edge TTS引擎，提供高质量的中文语音合成服务。

## 主要功能

- **单句转换**：在网页界面直接输入文本，即时转换并播放
- **批量处理**：上传TXT文件，一次性转换整篇古文
- **语音定制**：多种中文音色选择，可调节语速、音量和音调
- **批次管理**：每个转换任务分配唯一ID，支持断点续传和状态查询
- **实时反馈**：WebSocket实时显示转换进度和生成音频
- **响应式设计**：自适应PC和移动设备的界面布局

## 技术实现

- **前端**：原生HTML/CSS/JavaScript，响应式设计
- **后端**：基于FastAPI的异步处理框架
- **语音引擎**：Edge TTS作为Git子模块集成
- **实时通信**：WebSocket提供转换进度和状态反馈
- **并发处理**：支持多用户同时处理不同批次
- **资源管理**：线程安全的批次锁和全局锁机制
- **音频处理**：集成FFmpeg/Pydub进行音频合并

## 开始使用

### 环境要求
- Python 3.7+
- FFmpeg (推荐但非必需)

### 安装步骤

```bash
# 克隆项目
git clone https://github.com/mylukin/shici.git
cd shici

# 初始化Edge TTS子模块
git submodule init
git submodule update

# 安装依赖
python -m venv venv
source venv/bin/activate  # Linux/Mac或venv\Scripts\activate (Windows)
pip install -r requirements.txt

# 启动应用
python app.py  # 或uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

访问 `http://localhost:8000` 开始使用

## 使用指南

### 单句转换
1. 在"文本转语音"标签页中输入文本
2. 选择中文音色，调整语速、音量和音调
3. 点击"转换"按钮，音频将在页面中直接播放

### 批量转换
1. 切换到"批量文件转换"标签页
2. 上传包含文本内容的TXT文件
3. 选择转换参数，点击"开始转换"
4. 系统生成批次ID，实时显示处理进度
5. 可通过批次链接随时查看或分享结果

### 批次功能
- 每个批次有唯一URL，可随时访问：`/upload_file?no=<批次ID>`
- 支持随时停止处理：点击"停止处理"按钮
- 处理完成后自动合并所有音频片段
- 支持下载单个段落或完整合并后的音频

## API接口

系统提供以下API端点：

- `POST /api/convert`：单句文本转语音
- `POST /api/stop_batch/{batch_id}`：停止指定批次
- `POST /api/clean_old_batches`：清理过期批次
- `WebSocket /ws/{batch_id}`：获取批次实时处理状态

## 目录结构

```
shici/
├── app.py            # 主应用入口，路由和处理逻辑
├── utils.py          # 工具函数，TTS和文件处理
├── edge-tts/         # Edge TTS引擎(子模块)
├── static/           # 静态资源
├── templates/        # HTML模板
│   └── index.html    # 主界面
├── uploads/          # 上传文件临时存储
└── batches/          # 批次处理文件和结果
    └── {batch_id}/   # 每个批次的独立目录
        ├── info.json     # 批次信息和状态
        ├── segments.json # 段落处理信息
        ├── complete.mp3  # 合并后的完整音频
        └── audio/        # 分段音频文件
```

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