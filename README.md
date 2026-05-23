# pixiv-bookmarks-backup

Pixiv 收藏夹增量下载工具。将收藏的插画/漫画增量备份到本地。

## 功能

- **增量下载**：首次全量下载，之后只下载新增收藏
- **断点续传**：中断后重新运行会跳过已下载作品
- **按画师分目录**：每个画师一个文件夹
- **多图作品**：自动创建子目录存放分页图
- **支持公开/私密收藏**
- **支持 ugoira 动图**

## 依赖

```bash
pip install pixivpy3 requests
```

## 使用步骤

### 1. 获取 refresh_token

```bash
python get_token.py
```

在浏览器中打开输出的URL → 登录Pixiv → 复制跳转后的URL粘贴回来。

### 2. 运行下载

```bash
python pixiv_backup.py
```

## 配置

首次运行会自动生成 `config.json`：

```json
{
  "refresh_token": "你的token",
  "output_dir": "~/Pictures/pixiv_bookmarks",
  "download_private": false,
  "delay_between_downloads": 0.5,
  "max_pages_per_run": 0,
  "filename_pattern": "{id}_p{page}.{ext}",
  "skip_ai_generated": false
}
```

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `refresh_token` | Pixiv API 认证 token | (必填) |
| `output_dir` | 下载保存目录 | `~/Pictures/pixiv_bookmarks` |
| `download_private` | 是否下载私密收藏 | `false` |
| `delay_between_downloads` | 每张图下载间隔(秒) | `0.5` |
| `max_pages_per_run` | 每次运行最多获取几页(0=不限) | `0` |
| `filename_pattern` | 文件名格式 | `{id}_p{page}.{ext}` |
| `skip_ai_generated` | 跳过AI生成作品 | `false` |

## 下载目录结构

```
~/Pictures/pixiv_bookmarks/
├── 画师A/
│   ├── 12345678_p0.jpg      # 单图作品
│   ├── 12345680/             # 多图作品子目录
│   │   ├── 12345680_p0.jpg
│   │   └── 12345680_p1.jpg
│   └── ...
├── 画师B/
│   └── ...
└── ...
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `pixiv_backup.py` | 主下载脚本 |
| `get_token.py` | refresh_token 获取工具 |
| `config.json` | 配置文件（不提交） |
| `download_history.json` | 下载历史记录（自动生成） |

## 注意事项

- `refresh_token` 有效期约1年，失效后重新运行 `get_token.py`
- 删除 `download_history.json` 会触发全量重新下载
- 首次运行建议设置 `max_pages_per_run: 10` 先测试

## 增量下载原理

```
收藏夹: A, B, C, D, E
已下载: A, B, C
→ 只下载 D, E
→ 更新已下载列表: A, B, C, D, E
```

## License

MIT
