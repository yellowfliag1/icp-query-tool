# ICP Query Tool 2.0

基于工信部备案查询接口的自动化查询工具，支持网站 / APP / 小程序 / 快应用，支持单条和 `txt` 批量查询。

## 版本说明

- `v2.0`：使用 `ddddocr` 滑块识别，支持 `curl_cffi` 传输层，增强抗风控能力。
- 入口脚本：`miit_icp_auto_query.py`
- 兼容入口：`icp.py`（内部转发到 2.0）

## 环境要求

- Python 3.9+
- 推荐使用你当前虚拟环境

## 安装依赖

```bash
pip install -r requirements.txt
```

## 命令行用法

### 1) 单条查询（默认网站）

```bash
python miit_icp_auto_query.py "深圳市腾讯计算机系统有限公司"
```

### 2) 指定类型查询

```bash
python miit_icp_auto_query.py "深圳市腾讯计算机系统有限公司" --service-type 7
```

`--service-type` 对应关系：
- `1` 网站
- `6` APP
- `7` 小程序
- `8` 快应用

### 3) 批量查询（txt 每行一个关键词）

```bash
python miit_icp_auto_query.py --input queries.txt
```

示例 `queries.txt`：

```text
深圳市腾讯计算机系统有限公司
baidu.com
```

### 4) 批量查询并导出 JSON

```bash
python miit_icp_auto_query.py --input queries.txt --output result.json
```

### 5) 常用可选参数（都已设默认值）

- `--retries`：验证码重试次数，默认 `5`
- `--transport`：`curl` 或 `requests`，默认 `curl`
- `--manual-offset`：手动滑块偏移（调试用，默认 `-1`）


## 注意事项

- 高频查询可能触发目标站风控（403），建议降低频率并重试。
- 仅用于学习和合规场景，请遵守目标站点条款与相关法律法规。

## License

MIT

## Web 界面（2.0）

启动：

```bash
python -m uvicorn miit_icp_web:app --host 0.0.0.0 --port 8000
```

访问：

- `http://127.0.0.1:8000`

说明：

- 支持主体名/域名查询
- 支持批量（文本框每行一个关键词）
- 搜索结果列表 + 详情展开（空字段自动隐藏）
- APP/小程序/快应用会补调详情接口 `queryDetailByAppAndMiniId`
