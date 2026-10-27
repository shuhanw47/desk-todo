# Desk To-do

住在桌面小球里的 to-do list。不用"打开一个 app"——它一直在桌面角落，球里的数字就是还剩几件事。

A to-do list that lives in a little ball on your Windows desktop. Click the ball to open the list; the number inside is how many tasks are left.

## 功能

- **桌面小球**：苹果风半透明小球，数字 = 剩余任务（To-do + Pending）。单击展开 / 收起，拖动换位置
- **展开不跑位**：小球固定不动，面板从球的位置展开；靠近屏幕底部时自动往上展开
- **四个状态**：To-do / Pending / Completed / Cancelled
- **分类**
  - 输入框左边的 `inbox ▾` 选分类或新建分类
  - 直接输入 `work: weekly report`（冒号前是分类）
  - 按住任务拖到别的分类上松开即可换分类
  - 右键分类名：在此添加 / 重命名 / 删除
- **glass 半透明开关**，Ctrl + 滚轮微调透明度
- **像普通窗口一样拖边缘缩放**，窗口变大字也跟着变大一点
- **多屏幕**：可以直接拖过去，或右键 → 移到屏幕
- **字体**：英文 Garamond，中文方正静蕾简体（未安装时用系统中文字体）
- **开机自启**：右键小球 → 开机自启

## 运行

需要 Windows 10/11 和 Python 3.10+。

```bash
pip install -r requirements.txt
```

然后双击 `todo.pyw`，或者：

```bash
pythonw todo.pyw
```

设为开机自启 / 取消：

```bash
python todo.pyw --autostart
python todo.pyw --no-autostart
```

任务保存在同目录的 `todos.json`（已在 `.gitignore` 里，不会被提交）。

## 操作速查

| 操作 | 方式 |
|---|---|
| 展开 / 收起 | 单击小球（Esc 也能收起） |
| 添加任务 | 底部输入框回车，或点 + |
| 完成 / 恢复 | 点任务前面的方框 |
| 编辑 | 双击任务文字 |
| 换分类 | 拖动任务；或右键任务 → 移到分类 |
| 改状态 / 删除 | 右键任务 |
| 折叠分类 | 点分类名 |
| 设置 | 右键小球或顶部日期 |

## 灵感

来自小红书 @小饼干🍪lilian.chiuuu 的视频《本视频目标：打败市面上99%的to-do apps》。

## 作者

Shuhan Wang — [GitHub](https://github.com/shuhanw47) · [作品集](https://shuhanw47.github.io)

## License

[MIT](LICENSE)
