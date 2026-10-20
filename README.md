# AWD 批量工具 v3.1

> 仅用于**授权的 AWD 比赛 / 教学环境**。仓库包含 webshell 与批量攻防代码，请保持**私有**，不要用于未授权目标。

## 功能

- 目标 IP：扫描网段、手动列表、TCP 测试存活、导入/导出。
- 写入不死马：PHP 代码执行 / 命令执行、GET/POST 入口、自定义请求头、批量写入与验证、失败重试。
- 取 flag / 提交：多路径读取、表单/JSON/GET 提交、成功关键字 / JSON 判定、网络/5xx 重试、401/403/429 熔断。
- 自动轮次：固定间隔、只提交变化、全局去重（可选）、提交限速（可选）。
- 状态页：每台目标的存活 / 写马 / 已提交 / 最后 flag / flag 路径。
- 命令台：批量 Shell / PHP、健康巡检、防守体检。
- 结果查看：完整响应包、复制单元格/整行/整表、复制日志。
- 命令行版：不依赖 PySide6，支持 scan / probe / write / fetch / submit / command / health / check。

## 安装

```bash
pip install -r requirements.txt
```

Python 3.8+，依赖 `requests`、`PySide6`；`tkinter` 版仅作兜底。

## 启动

```bash
python main.py        # 或双击 start.bat
```

界面包含：目标 IP、写入不死马、提交 flag、命令、状态、设置。

## 命令行

```bash
python cli.py -h
python cli.py scan --my-ip 10.3.4.139 --save
python cli.py probe --target-file ip.txt
python cli.py write --target 10.3.4.70 --url http://127.0.0.1/shell.php --param cmd
python cli.py fetch --target-file ip.txt --url http://127.0.0.1/shell.php
python cli.py submit --target-file ip.txt --raw-file request.txt --param flag
```

## 配置与数据

- `settings.json`：首次保存后生成，含不死马 pass、路径、并发等；**不要提交**。
- `state.json`：上次 flag / 已提交 / 存活 / 已写马；**不要提交**。
- `ip.txt`：目标列表；**不要提交**。
- `logs/`：运行日志；**不要提交**。
- 已通过 `.gitignore` 排除以上文件；换机器/分发前也请检查。
- 默认 pass 仅用于演示，使用前请在「设置」里修改并点「载入默认代码」。

## 测试

```bash
python -m pytest -q
```

也可以双击 `run_tests.bat`（内部禁用第三方插件自动加载，避开本机 `pytest-flask` 兼容问题）。

## 目录

```text
main.py          入口，自动选择 PySide6 / tkinter
ui_qt.py         PySide6 界面
ui.py            tkinter 兜底界面
core.py          扫描 / 写马 / 取 flag / 提交 / 命令 / 批处理
config.py        配置、settings/state 读写
cli.py           命令行版
tests/           单元、集成、UI、CLI 测试
使用说明.txt      详细说明
```

## 免责声明

本项目仅用于授权范围内的安全教学与 AWD 比赛。使用者需确保对目标拥有明确授权，并遵守当地法律法规与比赛规则。作者不对未授权使用造成的后果负责。
