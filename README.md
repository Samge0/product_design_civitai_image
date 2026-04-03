# Civitai 图片爬虫

专门用于从 Civitai 抓取产品设计和工业设计相关图片的 Python 爬虫工具。

## 功能特点

- 支持按关键词过滤（包含/排除关键词）
- 支持按年份过滤（默认 2025 年）
- **智能进度管理**：自动保存爬取进度，支持断点续传
- **自动重试机制**：请求超时自动指数退避重试
- **流式下载**：使用 requests 流式下载，支持缓存
- **动态 CDN Key**：自动获取最新 CDN key，确保下载稳定
- 自动跳过已下载的图片
- 随机 User-Agent 避免 IP 封禁
- 支持代理配置

## 环境要求

- **Python 3.8+**

## 安装

1. 克隆或下载本项目

2. 安装依赖：

```bash
pip install -r requirements.txt
```

## 使用方法

### 基本使用（自动断点续传）

```bash
python civitai_crawler.py
```

### 限制爬取页数

```bash
python civitai_crawler.py --max-pages 10
```

### 重新开始（忽略上次进度）

```bash
python civitai_crawler.py --restart
```

### 组合使用

```bash
# 重新开始并限制页数
python civitai_crawler.py --restart --max-pages 5
```

### 中断恢复

- 按 `Ctrl+C` 中断爬取，进度会自动保存
- 下次运行会从上次位置继续

## 命令行参数

| 参数 | 说明 |
|------|------|
| `--max-pages N` | 最大爬取页数 |
| `--restart` | 重新开始（忽略上次进度） |

## 项目结构

```
.
├── civitai_crawler.py    # 爬虫主程序
├── requirements.txt       # 依赖列表
├── .gitignore            # Git 忽略配置
└── .cache/               # 缓存目录（自动创建）
    ├── crawl_progress.json  # 爬取进度文件
    ├── fail_ids            # 失败记录
    ├── download_cache/      # 下载缓存
    └── civitai_com_image_results/  # 下载的图片
```

## 配置说明

在 [civitai_crawler.py](civitai_crawler.py) 中可以修改以下配置：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `include_keywords` | 必须包含的关键词 | `["industrial design", "product design", "product rendering"]` |
| `exclude_keywords` | 排除的关键词 | `["anime", "cartoon", "nsfw", ...]` |
| `target_years` | 目标年份 | `[2025]` |
| `download_interval` | 下载间隔（秒） | `1` |

### 环境变量配置

创建 `.env` 文件配置以下选项：

```bash
# 代理配置（可选）
PROXY=127.0.0.1:7890

# CDN Key（可选，不填则自动获取）
CIVITAI_CDN_KEY=your_key_here
```

## 注意事项

1. 请确保遵守 Civitai 的使用条款和服务协议
2. 建议配置代理以避免 IP 限制
3. 图片默认保存在 `.cache/civitai_com_image_results/` 目录
4. 文件名格式：`{年份}_{id}_{uuid}.jpg`
5. 已下载的图片会自动跳过，不会重复下载
6. 请求失败会自动重试（最多 5 次，指数退避）

## 依赖项

- `requests` - HTTP 请求库
- `Pillow` - 图片验证
- `fake-useragent` - 随机 User-Agent
